"""Seeded stochastic transcriptional noise for L0 (E3 prerequisite).

This module adds ``NoisyDiscreteGrnModel``: a drop-in ``GenomeModel`` that
keeps the deterministic leaky-update right-hand side of the frozen
``DiscreteGrnModel`` bit-for-bit and superimposes bounded multiplicative
noise on every gene value *before* perturbation clamps are applied.

The noise is a first-moment approximation of bursty (telegraph) transcription
noise — gene switching produces expression fluctuations whose magnitude
scales with the mean expression level — reduced to bounded multiplicative
jitter so that the synchronous L0 clock and the ``TranscriptState`` contract
are preserved (arXiv:2405.12897, 2024; Sukys et al. 2025; Nature Index
stochastic-expression review, 2025).

Mathematical formulation
------------------------

The deterministic right-hand side is identical to ``DiscreteGrnModel``:

.. math::

    \\hat x_i(t+1) = (1-\\lambda)\\,x_i(t)
        + \\lambda\\,\\sigma\\!\\bigl(b_i + w_{\\text{basal}}(g_i-\\tfrac12)
        + w^{(d)}_i\\,d + \\textstyle\\sum_{j\\to i} w_{ji}\\,x_j(t)\\bigr).

**Seeded noise injection.**  For scenario seed :math:`s`, cell :math:`c`
and L0 update time :math:`t`, the random stream is derived deterministically:

.. math::

    \\mathrm{rng}_{c,t} = \\mathrm{Random}\\!\\Bigl(
        \\mathrm{sha256}(s\\,\\|\\,c\\,\\|\\,t)\\Bigr).

Each gene draws one uniform variate in sorted gene order:

.. math::

    x_i'(t+1) = \\mathrm{clamp}\\bigl(
        \\hat x_i(t+1)\\,(1 + \\sigma_\\eta\\,u_i),\\; 0,\\; 1\\bigr),
    \\qquad u_i \\sim \\mathcal{U}[-1, 1],

where :math:`\\sigma_\\eta` is the frozen ``noise_sigma``.  Because the
stream is re-derived from :math:`(s, c, t)` on every call, the model is
stateless: checkpoint resume replays exactly the same draws.  The same
seed reproduces the same trajectory; different seeds form distinct
trajectories — the pre-registered E3 requirement.

The noise enters the ``TranscriptState`` source digest hash chain (seed and
sigma are serialized into the state source), so every stochastic draw stays
auditable.  Perturbation clamps still act *after* the noise, so hard
knockdowns/overexpression remain exact.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, Mapping

from ..hashing import digest_payload
from ..models import Genome
from .contracts import (
    GenomeStepResult,
    RegulatoryInput,
    TranscriptState,
)
from .l0 import (
    DiscreteGrnModel,
    GrnConfig,
    RegulatoryEdge,
    _build_state,
    _perturb,
    _sigmoid,
    _state_values,
    _validate_genome,
)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def load_noisy_grn_config(path: str | Path) -> tuple[GrnConfig, float]:
    """Load a full GRN config plus the frozen ``noise_sigma`` parameter."""
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        noise_sigma = float(raw["noise_sigma"])
        grn_config = GrnConfig(
            model_version=str(raw["model_version"]),
            nodes=tuple(str(node) for node in raw["nodes"]),
            update_rate=float(raw["update_rate"]),
            basal_weight=float(raw["basal_weight"]),
            biases=tuple(
                sorted(
                    (str(name), float(value))
                    for name, value in raw["biases"].items()
                )
            ),
            damage_weights=tuple(
                sorted(
                    (str(name), float(value))
                    for name, value in raw["damage_weights"].items()
                )
            ),
            edges=tuple(
                RegulatoryEdge(
                    source=str(edge["source"]),
                    target=str(edge["target"]),
                    weight=float(edge["weight"]),
                )
                for edge in raw["edges"]
            ),
        )
        return grn_config, noise_sigma
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid noisy GRN config: {error}") from error


class NoisyDiscreteGrnModel(DiscreteGrnModel):
    """Deterministic GRN dynamics plus seeded multiplicative transcription noise."""

    def __init__(
        self, config: GrnConfig, *, noise_sigma: float, noise_seed: int
    ) -> None:
        super().__init__(config)
        if not math.isfinite(noise_sigma) or not 0.0 <= noise_sigma <= 1.0:
            raise ValueError("noise_sigma must be finite and in [0, 1]")
        if isinstance(noise_seed, bool) or not isinstance(noise_seed, int):
            raise TypeError("noise_seed must be an int")
        if noise_seed < 0:
            raise ValueError("noise_seed must be non-negative")
        self.noise_sigma = noise_sigma
        self.noise_seed = noise_seed

    @property
    def model_version(self) -> str:
        return (
            f"{self.config.model_version}+"
            f"{digest_payload((self.config, self.noise_sigma, self.noise_seed))[:12]}"
        )

    def _noise_stream(self, cell_id: str, logical_time: int) -> random.Random:
        payload = f"{self.noise_seed}|{cell_id}|{logical_time}".encode("utf-8")
        stream_seed = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
        return random.Random(stream_seed)

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
            raise TypeError("NoisyDiscreteGrnModel requires a RegulatoryInput")
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

        biases = self.config.bias_map
        damage_weights = self.config.damage_weight_map
        natural: dict[str, float] = {}
        for node in self.config.nodes:
            drive = (
                biases[node]
                + self.config.basal_weight * (genome.traits[node] - 0.5)
                + damage_weights.get(node, 0.0) * regulatory_input.damage_signal
            )
            for edge in self.config.edges:
                if edge.target == node:
                    drive += edge.weight * previous_values[edge.source]
            target = _sigmoid(drive)
            natural[node] = (
                (1.0 - self.config.update_rate) * previous_values[node]
                + self.config.update_rate * target
            )

        if self.noise_sigma > 0.0:
            rng = self._noise_stream(cell_id, logical_time)
            natural = {
                gene: _clamp(value * (1.0 + self.noise_sigma * rng.uniform(-1.0, 1.0)))
                for gene, value in natural.items()
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
                "noise_sigma": self.noise_sigma,
                "noise_seed": self.noise_seed,
            },
            values=applied,
        )
        return GenomeStepResult(state=state, perturbation_events=events)
