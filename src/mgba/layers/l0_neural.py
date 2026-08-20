"""Frozen-weight MLP variant of the L0 GRN (opt-in contract demonstrator).

``NeuralGrnModel`` replaces the hand-wired regulatory edges of the
frozen ``DiscreteGrnModel`` with a two-layer perceptron whose weights
are derived deterministically from ``weight_seed`` via
``mgba.neural.seeded_matrix``.  It is a **contract demonstrator**
(ADR-0017): it proves a neural-shaped L0 can satisfy the
``GenomeModel`` protocol, the synchronous clock, and the perturbation
semantics — it is not a trained or biologically fitted network, and no
training loop or supervision target exists in this repository.

Mathematical formulation
------------------------

The per-cell input vector at L0 update time :math:`t` is the
13-dimensional concatenation

.. math::

    u = \\bigl(x(t-1),\\; g,\\; d\\bigr) \\in [0,1]^{6+6+1}

of the previous expression values (or the genome traits on the first
tick, matching ``DiscreteGrnModel`` initialisation), the six abstract
genome traits, and the regulatory damage signal.  One hidden tanh
layer and a sigmoid output layer produce the expression target

.. math::

    y = \\sigma\\!\\bigl(W_2\\,\\tanh(W_1 u)\\bigr) \\in (0,1)^6,

which enters the same leaky update family as the reference model:

.. math::

    x_i(t) = (1-\\lambda)\\,x_i(t-1) + \\lambda\\,y_i,

with ``lambda = update_rate``.  Perturbation clamps are applied
*after* this natural update via the shared ``_perturb`` helper, so
hard knockdowns/overexpression remain exact, exactly as in the
reference and noisy GRN models.

The config (including ``weight_seed`` and ``hidden_dim``) is serialized
into the ``TranscriptState`` source digest, keeping every weight draw
auditable in the history hash chain.

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
from typing import Any, Mapping

from ..experiment import digest_payload
from ..models import Genome
from ..neural import mlp_forward, seeded_matrix
from .contracts import (
    GenomeStepResult,
    RegulatoryInput,
    TranscriptState,
)
from .l0 import (
    ABSTRACT_GENE_NAMES,
    _build_state,
    _perturb,
    _state_values,
    _validate_genome,
)

_INPUT_DIM = 2 * len(ABSTRACT_GENE_NAMES) + 1


@dataclass(frozen=True, slots=True)
class NeuralGrnConfig:
    """Frozen parameters of the MLP-shaped L0 contract demonstrator."""

    model_version: str
    weight_seed: int
    hidden_dim: int
    update_rate: float

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("neural GRN model_version must not be empty")
        if isinstance(self.weight_seed, bool) or not isinstance(self.weight_seed, int):
            raise TypeError("weight_seed must be an int")
        if self.weight_seed < 0:
            raise ValueError("weight_seed must be non-negative")
        if isinstance(self.hidden_dim, bool) or not isinstance(self.hidden_dim, int):
            raise TypeError("hidden_dim must be an int")
        if self.hidden_dim < 1:
            raise ValueError("hidden_dim must be a positive integer")
        if not math.isfinite(self.update_rate) or not 0.0 < self.update_rate <= 1.0:
            raise ValueError("update_rate must be finite and in (0, 1]")


def load_neural_grn_config(path: str | Path) -> NeuralGrnConfig:
    """Load the frozen-weight L0 MLP config; any read/parse failure is a ValueError."""
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return NeuralGrnConfig(
            model_version=str(raw["model_version"]),
            weight_seed=int(raw["weight_seed"]),
            hidden_dim=int(raw["hidden_dim"]),
            update_rate=float(raw["update_rate"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid neural GRN config: {error}") from error


class NeuralGrnModel:
    """Deterministic frozen-weight MLP L0 model over the abstract genes."""

    def __init__(self, config: NeuralGrnConfig) -> None:
        if not isinstance(config, NeuralGrnConfig):
            raise TypeError("NeuralGrnModel requires a NeuralGrnConfig")
        self.config = config
        self._weights = (
            seeded_matrix(
                config.weight_seed, "l0-neural-hidden", config.hidden_dim, _INPUT_DIM
            ),
            seeded_matrix(
                config.weight_seed,
                "l0-neural-output",
                len(ABSTRACT_GENE_NAMES),
                config.hidden_dim,
            ),
        )

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    def step(
        self,
        *,
        cell_id: str,
        genome: Genome,
        previous_state: TranscriptState | None,
        regulatory_input: RegulatoryInput,
        perturbations: Mapping[str, float],
        logical_time: int,
    ) -> GenomeStepResult:
        _validate_genome(genome)
        if not isinstance(regulatory_input, RegulatoryInput):
            raise TypeError("NeuralGrnModel requires a RegulatoryInput")
        if previous_state is not None:
            if not isinstance(previous_state, TranscriptState):
                raise TypeError("previous L0 state must be a TranscriptState")
            if previous_state.cell_id != cell_id:
                raise ValueError("previous L0 state must belong to the same cell")
            if logical_time <= previous_state.metadata.logical_time:
                raise ValueError(
                    "logical_time must advance beyond the previous L0 state"
                )
            previous_values = _state_values(previous_state)
        else:
            previous_values = dict(genome.traits)

        input_vector = (
            tuple(previous_values[gene] for gene in ABSTRACT_GENE_NAMES)
            + tuple(genome.traits[gene] for gene in ABSTRACT_GENE_NAMES)
            + (regulatory_input.damage_signal,)
        )
        target = mlp_forward(
            input_vector, weights=self._weights, activation="tanh"
        )
        rate = self.config.update_rate
        natural = {
            gene: (1.0 - rate) * previous_values[gene] + rate * target[index]
            for index, gene in enumerate(ABSTRACT_GENE_NAMES)
        }

        applied, events = _perturb(
            cell_id=cell_id,
            logical_time=logical_time,
            natural_values=natural,
            perturbations=perturbations,
        )
        state = _build_state(
            cell_id=cell_id,
            logical_time=logical_time,
            model_version=self.model_version,
            source={
                "genome": genome,
                "previous_state": previous_state,
                "regulatory_input": regulatory_input,
                "perturbations": perturbations,
                "config": self.config,
            },
            values=applied,
        )
        return GenomeStepResult(state=state, perturbation_events=events)
