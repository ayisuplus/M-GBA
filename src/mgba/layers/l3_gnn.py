"""Frozen-weight message-passing GNN variant of L3 (opt-in contract demonstrator).

``GnnTissueModel`` replaces the hand-tuned field equations of the
frozen ``TissueEnvironmentModel`` with a one-hop graph neural network
update whose weights are derived deterministically from
``weight_seed`` via ``mgba.neural.seeded_matrix``.  It is a **contract
demonstrator** (ADR-0017): it proves a message-passing layer can
satisfy the ``TissueModel`` protocol over the fixed static graph — it
is not a trained or biologically fitted network, and no training loop
or supervision target exists in this repository.  The graph itself is
never modified; topology governance stays with ``l3_adaptive.py``.

Mathematical formulation
------------------------

Each node contributes the 6-dimensional feature vector

.. math::

    x_i = (\\sigma_i, r_i, s_i, \\mathrm{sec}_i, \\mathrm{rep}_i,
           \\mathrm{cons}_i)

from its previous ``TissueNodeState`` fields (stress, resource, signal)
and the current ``CellAction`` fields (secretion, repair effort,
resource consumption).  In-neighbour messages are mean-aggregated,

.. math::

    m_i = \\frac{1}{|N^{in}(i)|} \\sum_{j \\to i} x_j

(zero vector for source nodes), and the update is one frozen linear
combination with a per-element sigmoid:

.. math::

    h_i = \\sigma\\!\\bigl(W_{self}\\, x_i + W_{neigh}\\, m_i + b\\bigr)
          \\in (0,1)^3,

written back as ``(stress, resource_level, signal) = h_i[0:3]``
(clamped to ``[0, 1]`` as a belt-and-braces guard; the sigmoid already
bounds the range).  ``W_self``, ``W_neigh`` (both 3x6) and ``b`` (3)
are derived from ``weight_seed`` under the salts ``l3-gnn-self``,
``l3-gnn-neigh`` and ``l3-gnn-bias``.

Aggregate fields reuse the frozen ``_build_tissue_state`` formulas:
``coordinated_signal = mean(signal)`` and

.. math::

    D = \\mathrm{clamp}\\bigl(0.6\\,\\bar\\sigma + 0.4\\,(1 - \\bar v)\\bigr),

where the 0.6/0.4 damage aggregation weights are the frozen reference
values of ADR-0005, embedded in ``GnnTissueConfig`` (this model does
not read a ``TissueConfig``).  The config and ``weight_seed`` are
serialized into the ``TissueState`` source digest so every weight draw
stays auditable in the history hash chain.

Feedback constraints are rejected exactly as in
``TissueEnvironmentModel``: the GNN variant is not part of the E4
closed loop.

This module is deliberately **not** re-exported from
``mgba.layers.__init__``: the stable package surface stays limited to
DTOs and Protocols, and importing the experiment helpers from the
package ``__init__`` would create a circular import.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any

from ..hashing import digest_payload
from ..neural import message_passing_step, seeded_matrix, sigmoid
from .contracts import (
    CellAction,
    CellState,
    FeedbackConstraint,
    LocalEnvironment,
    TissueNodeState,
    TissueState,
)
from .l3 import _build_tissue_state, _clamp, _validated_inputs

#: Frozen L4 damage aggregation weights inherited from ADR-0005 / TissueConfig.
_REFERENCE_DAMAGE_STRESS_WEIGHT = 0.6
_REFERENCE_DAMAGE_VIABILITY_WEIGHT = 0.4


@dataclass(frozen=True, slots=True)
class GnnTissueConfig:
    """Frozen parameters of the message-passing L3 contract demonstrator.

    ``damage_stress_weight`` / ``damage_viability_weight`` default to the
    frozen reference values (0.6/0.4) of ADR-0005 and are part of the
    audited config digest; they exist so the L4-facing ``tissue_damage``
    aggregate stays comparable with the reference model without this
    variant depending on ``TissueConfig``.
    """

    model_version: str
    weight_seed: int
    damage_stress_weight: float = _REFERENCE_DAMAGE_STRESS_WEIGHT
    damage_viability_weight: float = _REFERENCE_DAMAGE_VIABILITY_WEIGHT

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("GNN tissue model_version must not be empty")
        if isinstance(self.weight_seed, bool) or not isinstance(self.weight_seed, int):
            raise TypeError("weight_seed must be an int")
        if self.weight_seed < 0:
            raise ValueError("weight_seed must be non-negative")
        for name in ("damage_stress_weight", "damage_viability_weight"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and in [0, 1]")
        if not math.isclose(
            self.damage_stress_weight + self.damage_viability_weight,
            1.0,
            abs_tol=1e-12,
        ):
            raise ValueError("GNN damage aggregation weights must sum to 1")


def load_gnn_tissue_config(path: str | Path) -> GnnTissueConfig:
    """Load the frozen-weight L3 GNN config; any read/parse failure is a ValueError."""
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return GnnTissueConfig(
            model_version=str(raw["model_version"]),
            weight_seed=int(raw["weight_seed"]),
            damage_stress_weight=float(
                raw.get("damage_stress_weight", _REFERENCE_DAMAGE_STRESS_WEIGHT)
            ),
            damage_viability_weight=float(
                raw.get("damage_viability_weight", _REFERENCE_DAMAGE_VIABILITY_WEIGHT)
            ),
        )
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid GNN tissue config: {error}") from error


class GnnTissueModel:
    """Deterministic frozen-weight one-hop GNN over the static tissue graph."""

    def __init__(self, config: GnnTissueConfig) -> None:
        if not isinstance(config, GnnTissueConfig):
            raise TypeError("GnnTissueModel requires a GnnTissueConfig")
        self.config = config
        self._w_self = seeded_matrix(config.weight_seed, "l3-gnn-self", 3, 6)
        self._w_neigh = seeded_matrix(config.weight_seed, "l3-gnn-neigh", 3, 6)
        self._bias = tuple(
            row[0] for row in seeded_matrix(config.weight_seed, "l3-gnn-bias", 3, 1)
        )

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    def step(
        self,
        cell_states: tuple[CellState, ...],
        cell_actions: tuple[CellAction, ...],
        *,
        initial_environments: tuple[LocalEnvironment, ...] | None,
        previous_state: TissueState | None,
        edges: tuple[tuple[str, str], ...],
        logical_time: int,
        constraint: FeedbackConstraint | None = None,
    ) -> TissueState:
        if constraint is not None:
            raise ValueError(
                "GnnTissueModel does not support feedback constraints; "
                "use ConstraintAwareTissueModel"
            )
        inputs = _validated_inputs(
            cell_states=cell_states,
            cell_actions=cell_actions,
            initial_environments=initial_environments,
            previous_state=previous_state,
            edges=edges,
            logical_time=logical_time,
        )

        previous_nodes = {node.cell_id: node for node in inputs.previous_nodes}
        features = {
            cell_id: (
                previous_nodes[cell_id].stress,
                previous_nodes[cell_id].resource_level,
                previous_nodes[cell_id].signal,
                inputs.actions[cell_id].secretion,
                inputs.actions[cell_id].repair_effort,
                inputs.actions[cell_id].resource_consumption,
            )
            for cell_id in sorted(inputs.cells)
        }
        messages = message_passing_step(features, inputs.edges)

        next_nodes: list[TissueNodeState] = []
        for cell_id in sorted(inputs.cells):
            node_features = features[cell_id]
            message = messages[cell_id]
            updated = tuple(
                _clamp(
                    sigmoid(
                        math.fsum(
                            weight * value
                            for weight, value in zip(row_self, node_features)
                        )
                        + math.fsum(
                            weight * value
                            for weight, value in zip(row_neigh, message)
                        )
                        + bias
                    )
                )
                for row_self, row_neigh, bias in zip(
                    self._w_self, self._w_neigh, self._bias
                )
            )
            next_nodes.append(
                TissueNodeState(
                    cell_id=cell_id,
                    stress=updated[0],
                    resource_level=updated[1],
                    signal=updated[2],
                )
            )
        nodes = tuple(next_nodes)

        mean_stress = fmean(node.stress for node in nodes)
        mean_viability = fmean(cell.viability for cell in inputs.cells.values())
        return _build_tissue_state(
            logical_time=logical_time,
            model_version=self.model_version,
            source={
                **inputs.source,
                "config": self.config,
                "weights_seed": self.config.weight_seed,
            },
            nodes=nodes,
            edges=inputs.edges,
            edge_density=inputs.edge_density,
            cell_states=inputs.cells,
            cell_actions=inputs.actions,
            coordinated_signal=fmean(node.signal for node in nodes),
            tissue_damage=_clamp(
                self.config.damage_stress_weight * mean_stress
                + self.config.damage_viability_weight * (1.0 - mean_viability)
            ),
        )
