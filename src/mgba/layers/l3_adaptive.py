"""Adaptive topology governance for L3 (E5 static-vs-dynamic comparison).

This module implements the dynamic-topology counterpart of the frozen
fixed-graph L3 reference model.  Cells keep proposing topology intent; the
*system* — never a cell — authorizes and commits changes, as required by
the core principles.

The governance loop mirrors three research streams:

* **Adaptive / coevolutionary networks** (Gross–Blasius lineage): nodes
  rewire away from high-stress sources (stress-avoidance rewiring).
* **Vertex-model T1 transitions** (Lange et al. 2025; arXiv:2504.16765):
  neighbor exchange removes one edge and adds another, conserving the edge
  count and each target's in-degree.
* **Multi-agent topology adaptation** (MANTA, arXiv:2607.28527): agents
  propose, a framework layer authorizes under explicit constraints.

Mathematical formulation
------------------------

Let :math:`\\mathcal{N}^-_i(t)` be the in-neighbor set of node :math:`i`,
:math:`\\sigma_j(t)` node stress and :math:`s_k(t)` the secretion action of
node :math:`k` at time :math:`t`.

**Proposal.**  Every alive node :math:`i` scores at most one swap
candidate:

.. math::

    j^{*} = \\arg\\max_{j \\in \\mathcal{N}^-_i(t)} \\sigma_j(t)
    \\quad\\text{(worst incoming stress source)},

.. math::

    k^{*} = \\arg\\max_{k \\in \\mathcal{C}_i(t)} s_k(t)
    \\quad\\text{(best secretion source)},

with candidate set

.. math::

    \\mathcal{C}_i(t) = \\{\\, k \\neq i :
        k \\notin \\mathcal{N}^-_i(t),\\;
        k\\ \\text{alive},\\;
        \\deg^{+}_{k}(t) < \\Delta_{\\max} \\,\\},

ties broken lexicographically by cell id (deterministic, no randomness).

**Authorization.**  A swap is authorized iff all governance constraints
hold:

.. math::

    \\mathcal{N}^-_i(t) \\neq \\varnothing \\;\\wedge\\;
    \\mathcal{C}_i(t) \\neq \\varnothing \\;\\wedge\\;
    i\\ \\text{alive} \\;\\wedge\\;
    s_{k^{*}}(t) - \\sigma_{j^{*}}(t) \\ge \\theta.

**Commit (T1 exchange, in-degree conserving).**  Authorized swaps are
applied simultaneously to the next topology:

.. math::

    E(t+1) = E(t) \\setminus \\{(j^{*}, i)\\} \\cup \\{(k^{*}, i)\\},

subject to the global per-tick budget :math:`B`: proposals are processed in
cell-id order and the first :math:`B` authorized swaps are committed.

Every committed swap (target, dropped source, added source, gain) is
serialized into the new ``TissueState`` source digest, so the history hash
chain audits each topology mutation.  The topology state lives in
``TissueState.edges``; the ``edges`` step argument acts only as the seed
topology for the first tick, so checkpoint resume is exact without any
schema change.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..experiment import digest_payload
from .contracts import (
    CellAction,
    CellPhase,
    CellState,
    FeedbackConstraint,
    LocalEnvironment,
    StateMetadata,
    TissueNodeState,
    TissueState,
)
from .l3 import (
    TissueConfig,
    _build_tissue_state,
    _environment_nodes,
    _validated_inputs,
    load_tissue_config,
)


@dataclass(frozen=True, slots=True)
class AdaptiveTopologyConfig:
    """Governance parameters for the adaptive L3 topology."""

    model_version: str
    max_swaps_per_tick: int  # global budget B
    exchange_gain_threshold: float  # marginal gain theta
    max_out_degree: int  # degree cap Delta_max

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("adaptive topology model_version must not be empty")
        if (
            isinstance(self.max_swaps_per_tick, bool)
            or not isinstance(self.max_swaps_per_tick, int)
            or self.max_swaps_per_tick < 0
        ):
            raise ValueError("max_swaps_per_tick must be a non-negative integer")
        if (
            isinstance(self.max_out_degree, bool)
            or not isinstance(self.max_out_degree, int)
            or self.max_out_degree < 1
        ):
            raise ValueError("max_out_degree must be a positive integer")
        if (
            not math.isfinite(self.exchange_gain_threshold)
            or not -1.0 <= self.exchange_gain_threshold <= 1.0
        ):
            raise ValueError("exchange_gain_threshold must be finite and in [-1, 1]")


def load_adaptive_topology_config(
    path: str | Path,
) -> AdaptiveTopologyConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return AdaptiveTopologyConfig(
            model_version=str(raw["model_version"]),
            max_swaps_per_tick=int(raw["max_swaps_per_tick"]),
            exchange_gain_threshold=float(raw["exchange_gain_threshold"]),
            max_out_degree=int(raw["max_out_degree"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid adaptive topology config: {error}") from error


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _metadata(
    *, logical_time: int, model_version: str, source: Any
) -> StateMetadata:
    return StateMetadata(
        logical_time=logical_time,
        model_version=model_version,
        source_digest=digest_payload(source),
    )


class DynamicTopologyTissueModel:
    """Deterministic fixed-budget L3 dynamics with governed topology swaps.

    Node-level field dynamics are identical to the reference environment
    model (shared ``_environment_nodes``); only the edge set may evolve,
    through stress-avoidance T1-style swaps that pass authorization and fit
    the per-tick budget.
    """

    def __init__(
        self,
        config: TissueConfig,
        governance: AdaptiveTopologyConfig,
        *,
        stress_floor_coupling: float = 1.0,
    ) -> None:
        if not isinstance(config, TissueConfig):
            raise TypeError("DynamicTopologyTissueModel requires a TissueConfig")
        if not isinstance(governance, AdaptiveTopologyConfig):
            raise TypeError(
                "DynamicTopologyTissueModel requires an AdaptiveTopologyConfig"
            )
        if (
            not math.isfinite(stress_floor_coupling)
            or not 0.0 <= stress_floor_coupling <= 1.0
        ):
            raise ValueError("stress_floor_coupling must be finite and in [0, 1]")
        self.config = config
        self.governance = governance
        self.stress_floor_coupling = stress_floor_coupling

    @property
    def model_version(self) -> str:
        return (
            f"{self.config.model_version}+"
            f"{digest_payload((self.config, self.governance, self.stress_floor_coupling))[:12]}"
        )

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
            if not isinstance(constraint, FeedbackConstraint):
                raise TypeError("L3 constraint must be a FeedbackConstraint")
            if constraint.metadata.logical_time > logical_time:
                raise ValueError("L3 cannot consume a future feedback constraint")
        inputs = _validated_inputs(
            cell_states=cell_states,
            cell_actions=cell_actions,
            initial_environments=initial_environments,
            previous_state=previous_state,
            edges=edges,
            logical_time=logical_time,
            dynamic_topology=True,
        )
        nodes = _environment_nodes(
            inputs=inputs,
            config=self.config,
            constraint=constraint,
            stress_floor_coupling=self.stress_floor_coupling,
        )
        swaps = self._authorize_swaps(
            cells=inputs.cells,
            actions=inputs.actions,
            nodes=nodes,
            edges=inputs.edges,
        )
        next_edges = self._commit_swaps(inputs.edges, swaps)

        mean_stress = sum(node.stress for node in nodes) / len(nodes)
        mean_viability = sum(
            cell.viability for cell in inputs.cells.values()
        ) / len(inputs.cells)
        source: dict[str, Any] = {
            **inputs.source,
            "config": self.config,
            "governance": self.governance,
            "topology_swaps": swaps,
        }
        if constraint is not None:
            source["constraint"] = constraint
        return _build_tissue_state(
            logical_time=logical_time,
            model_version=self.model_version,
            source=source,
            nodes=nodes,
            edges=next_edges,
            edge_density=len(next_edges)
            / (len(inputs.cells) * max(1, len(inputs.cells) - 1)),
            cell_states=inputs.cells,
            cell_actions=inputs.actions,
            coordinated_signal=sum(node.signal for node in nodes) / len(nodes),
            tissue_damage=_clamp(
                self.config.damage_stress_weight * mean_stress
                + self.config.damage_viability_weight * (1.0 - mean_viability)
            ),
        )

    def _authorize_swaps(
        self,
        *,
        cells: dict[str, CellState],
        actions: dict[str, CellAction],
        nodes: tuple[TissueNodeState, ...],
        edges: tuple[tuple[str, str], ...],
    ) -> tuple[dict[str, Any], ...]:
        """Propose, authorize and budget-cap stress-avoidance swaps.

        Deterministic: nodes are processed in sorted cell-id order; every
        score tie is resolved lexicographically.
        """
        governance = self.governance
        node_by_id = {node.cell_id: node for node in nodes}
        incoming: dict[str, list[str]] = {cell_id: [] for cell_id in cells}
        out_degree: dict[str, int] = {cell_id: 0 for cell_id in cells}
        for source, target in edges:
            incoming[target].append(source)
            out_degree[source] += 1

        authorized: list[dict[str, Any]] = []
        pending_add: dict[str, int] = {}

        for target in sorted(cells):
            if len(authorized) >= governance.max_swaps_per_tick:
                break
            if cells[target].phase is CellPhase.DEAD:
                continue
            neighbors = incoming[target]
            if not neighbors:
                continue

            # Proposal: drop the most stressed incoming source.
            drop_source = max(
                sorted(neighbors),
                key=lambda source: (node_by_id[source].stress, ),
            )
            drop_score = node_by_id[drop_source].stress

            # Proposal: add the strongest alive secretion source.
            add_candidates = [
                cell_id
                for cell_id in sorted(cells)
                if cell_id != target
                and cell_id not in neighbors
                and cells[cell_id].phase is not CellPhase.DEAD
                and out_degree[cell_id] + pending_add.get(cell_id, 0)
                < governance.max_out_degree
            ]
            if not add_candidates:
                continue
            add_source = max(
                add_candidates,
                key=lambda cell_id: actions[cell_id].secretion,
            )
            add_score = actions[add_source].secretion

            # Authorization: marginal gain threshold.
            gain = add_score - drop_score
            if gain < governance.exchange_gain_threshold:
                continue
            if add_source == drop_source:
                continue

            # Commit bookkeeping: reserve out-degree capacity within this tick.
            pending_add[add_source] = pending_add.get(add_source, 0) + 1
            authorized.append(
                {
                    "target": target,
                    "drop": drop_source,
                    "add": add_source,
                    "gain": gain,
                }
            )
        return tuple(authorized)

    def _commit_swaps(
        self,
        edges: tuple[tuple[str, str], ...],
        swaps: tuple[dict[str, Any], ...],
    ) -> tuple[tuple[str, str], ...]:
        if not swaps:
            return edges
        edge_set = set(edges)
        for swap in swaps:
            edge_set.discard((swap["drop"], swap["target"]))
            edge_set.add((swap["add"], swap["target"]))
        return tuple(sorted(edge_set))
