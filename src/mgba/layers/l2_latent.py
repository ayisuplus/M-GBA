"""Continuous latent-state ("virtual cell") Cell policy for L2 (opt-in).

``LatentCellModel`` instantiates the architecture class used by AI virtual
cell (AIVC) research — a continuous latent cell state, a structured
transition operator, and a readout head — as a layer-internal ``CellModel``
variant, with pure-stdlib frozen weights derived from an explicit
``weight_seed`` via ``mgba.neural.seeded_matrix``.  It is a **contract
demonstrator** (ADR-0019): it proves a latent-state-shaped L2 can satisfy
the ``CellModel`` protocol, the multirate runner, and the checkpoint
invariants — it is not a trained or biologically fitted network, and no
training loop, external weight file, or perturbation dataset exists in
this repository.  The rule state machine ``CellStateMachineModel`` stays
the default and permanent baseline.

Protocol constraint that shapes the design
------------------------------------------

``CellModel.step`` receives the *only* legal history carrier: the formal
``CellState`` DTO (phase + activation/viability/stress_load).  Checkpoints
serialize DTOs only, and a resumed runner rebuilds model instances from
scratch, so any hidden per-cell memory would silently desynchronize on
resume.  The latent state is therefore **recomputed deterministically from
the formal contract state every tick** — the embedding is a function of
the observable cell state, mirroring the AIVC notion that a cell embedding
is a function of the cell's measured state, and keeping the
checkpoint/restore identity bit-exact.

Mathematical formulation
------------------------

The per-tick input vector is the 12-dimensional concatenation

.. math::

    u_t = \\bigl(m_t,\\; e_t,\\; s_{t-1}\\bigr) \\in [0,1]^{6+3+3}

of the six L1 molecular species, the three local-environment fields, and
the previous ``CellState`` scalars (neutral 0.5 on the first tick).  With
frozen seed-derived matrices the latent update is the leaky recurrence

.. math::

    z^{prev} = \\tanh(W_s\\, s_{t-1}),\\qquad
    z_t = (1-\\lambda)\\, z^{prev} + \\lambda\\, \\tanh\\bigl(
        W_{in} u_t + W_{rec} z^{prev} + b \\bigr),

where ``W_rec`` rows are L1-normalized to norm <= 1 so the tanh recurrence
stays contractive, and ``lambda = leak_rate``.  A linear readout over the
four non-dead phases gives logits ``W_{ph} z_t``; the phase is a
deterministic argmax with config-frozen tie-break order.  Death is never
produced by the readout: it follows the same hard guards as the rule and
active-inference models (``viability <= death_viability_threshold`` or
``death_drive >= death_drive_threshold``), and DEAD stays absorbing.

State bookkeeping (viability, stress load, activation drive) and the
action family (per-phase secretion multiplier, consumption rates, repair
effort only while REPAIRING) are identical to the rule model, so a paired
swap against the rule baseline isolates exactly one variable: the phase
is produced by a continuous latent-state representation instead of a
fixed threshold priority.

This module is deliberately **not** re-exported from
``mgba.layers.__init__``: the stable package surface stays limited to
DTOs and Protocols.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..experiment import digest_payload
from ..neural import seeded_matrix
from .contracts import (
    CellAction,
    CellPhase,
    CellState,
    LocalEnvironment,
    MolecularState,
    StateMetadata,
)
from .l2 import CellTrajectory, _dead_action, _validate_inputs

_INPUT_DIM = 12
_NEUTRAL_PREVIOUS = (0.5, 0.5, 0.5)

# Readout head covers every non-dead phase in deterministic tie-break
# priority order; DEAD is only reachable through the hard viability/death
# guards shared with the rule and active-inference models.
_LATENT_PHASES = (
    CellPhase.QUIESCENT,
    CellPhase.ACTIVATED,
    CellPhase.REPAIRING,
    CellPhase.STRESSED,
)
_PHASES = tuple(CellPhase)

_BOOKKEEPING_FIELDS = (
    "stress_environment_weight",
    "resource_deficit_weight",
    "death_stress_weight",
    "metabolic_buffer_weight",
    "signal_activation_weight",
    "incoming_signal_weight",
    "death_effector_weight",
    "stress_mortality_weight",
    "repair_recovery_rate",
    "stress_damage_rate",
    "death_damage_rate",
    "basal_consumption",
    "activation_consumption_rate",
    "repair_consumption_rate",
    "death_viability_threshold",
    "death_drive_threshold",
)


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


def _matvec(
    matrix: tuple[tuple[float, ...], ...], vector: tuple[float, ...] | list[float]
) -> list[float]:
    return [
        sum(weight * value for weight, value in zip(row, vector))
        for row in matrix
    ]


@dataclass(frozen=True, slots=True)
class LatentCellConfig:
    """Frozen parameter set for the latent-state L2 policy."""

    model_version: str

    # Latent architecture: dimensions, leak, and the explicit seed that
    # deterministically derives every frozen weight matrix.
    latent_dim: int
    leak_rate: float
    weight_seed: int

    # Bookkeeping parameters: identical semantics to the rule CellConfig.
    stress_environment_weight: float
    resource_deficit_weight: float
    death_stress_weight: float
    metabolic_buffer_weight: float
    signal_activation_weight: float
    incoming_signal_weight: float
    death_effector_weight: float
    stress_mortality_weight: float
    repair_recovery_rate: float
    stress_damage_rate: float
    death_damage_rate: float
    basal_consumption: float
    activation_consumption_rate: float
    repair_consumption_rate: float
    death_viability_threshold: float
    death_drive_threshold: float
    secretion_multipliers: tuple[tuple[CellPhase, float], ...]

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("cell model_version must not be empty")
        if isinstance(self.latent_dim, bool) or not isinstance(self.latent_dim, int):
            raise TypeError("latent_dim must be an int")
        if self.latent_dim < 1:
            raise ValueError("latent_dim must be a positive integer")
        if not math.isfinite(self.leak_rate) or not 0.0 < self.leak_rate <= 1.0:
            raise ValueError("leak_rate must be finite and in (0, 1]")
        if isinstance(self.weight_seed, bool) or not isinstance(
            self.weight_seed, int
        ):
            raise TypeError("weight_seed must be an int")
        if self.weight_seed < 0:
            raise ValueError("weight_seed must be non-negative")
        for name in _BOOKKEEPING_FIELDS:
            value = getattr(self, name)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and in [0, 1]")
        multiplier_phases = tuple(phase for phase, _ in self.secretion_multipliers)
        if multiplier_phases != _PHASES:
            raise ValueError("secretion multipliers must match every CellPhase in order")
        for _, value in self.secretion_multipliers:
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError("secretion multipliers must be finite and in [0, 1]")

    @property
    def secretion_multiplier_map(self) -> dict[CellPhase, float]:
        return dict(self.secretion_multipliers)


def load_latent_cell_config(path: str | Path) -> LatentCellConfig:
    """Load the frozen latent-cell config; any read/parse failure is a ValueError."""
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        raw_multipliers: dict[str, Any] = raw["secretion_multipliers"]
        if set(raw_multipliers) != {phase.value for phase in _PHASES}:
            raise ValueError("cell config has missing or unknown secretion phases")
        return LatentCellConfig(
            model_version=str(raw["model_version"]),
            latent_dim=int(raw["latent_dim"]),
            leak_rate=float(raw["leak_rate"]),
            weight_seed=int(raw["weight_seed"]),
            **{name: float(raw[name]) for name in _BOOKKEEPING_FIELDS},
            secretion_multipliers=tuple(
                (phase, float(raw_multipliers[phase.value])) for phase in _PHASES
            ),
        )
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid latent cell config: {error}") from error


class LatentCellModel:
    """Deterministic continuous latent-state Cell policy for L2."""

    def __init__(self, config: LatentCellConfig) -> None:
        self.config = config
        seed = config.weight_seed
        dim = config.latent_dim
        self._w_in = seeded_matrix(seed, "l2-latent-input", dim, _INPUT_DIM)
        self._w_rec = self._normalize_rows(
            seeded_matrix(seed, "l2-latent-recurrent", dim, dim)
        )
        self._bias = tuple(
            row[0] for row in seeded_matrix(seed, "l2-latent-bias", dim, 1)
        )
        self._w_state = seeded_matrix(seed, "l2-latent-state-embed", dim, 3)
        self._w_phase = seeded_matrix(
            seed, "l2-latent-phase-readout", len(_LATENT_PHASES), dim
        )

    @staticmethod
    def _normalize_rows(
        matrix: tuple[tuple[float, ...], ...]
    ) -> tuple[tuple[float, ...], ...]:
        """Scale each row so its L1 norm is at most 1 (contraction guard)."""
        normalized = []
        for row in matrix:
            norm = sum(abs(value) for value in row)
            if norm > 1.0:
                row = tuple(value / norm for value in row)
            normalized.append(row)
        return tuple(normalized)

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    def _drives(
        self, molecular: MolecularState, environment: LocalEnvironment
    ) -> tuple[float, float, float, float]:
        config = self.config
        stress_load = _clamp(
            config.stress_environment_weight * environment.stress
            + config.resource_deficit_weight * (1.0 - environment.resource_level)
            + config.death_stress_weight * molecular.death_effector
            - config.metabolic_buffer_weight * molecular.metabolic_capacity
        )
        activation_drive = _clamp(
            config.signal_activation_weight * molecular.signal_protein
            + config.incoming_signal_weight * environment.incoming_signal
        )
        repair_drive = _clamp(
            molecular.repair_protein
            * stress_load
            * environment.resource_level
        )
        death_drive = _clamp(
            config.death_effector_weight * molecular.death_effector
            + config.stress_mortality_weight
            * stress_load
            * (1.0 - molecular.metabolic_capacity)
        )
        return stress_load, activation_drive, repair_drive, death_drive

    def _input_vector(
        self,
        molecular: MolecularState,
        environment: LocalEnvironment,
        previous_state: CellState | None,
    ) -> tuple[float, ...]:
        if previous_state is None:
            previous_scalars = _NEUTRAL_PREVIOUS
        else:
            previous_scalars = (
                previous_state.activation,
                previous_state.viability,
                previous_state.stress_load,
            )
        return (
            molecular.damage_receptor,
            molecular.signal_protein,
            molecular.repair_protein,
            molecular.metabolic_capacity,
            molecular.death_effector,
            molecular.feedback_inhibitor,
            environment.stress,
            environment.resource_level,
            environment.incoming_signal,
            *previous_scalars,
        )

    def _latent(
        self, inputs: tuple[float, ...], previous_state: CellState | None
    ) -> list[float]:
        if previous_state is None:
            previous_scalars = _NEUTRAL_PREVIOUS
        else:
            previous_scalars = (
                previous_state.activation,
                previous_state.viability,
                previous_state.stress_load,
            )
        z_previous = [
            math.tanh(value)
            for value in _matvec(self._w_state, previous_scalars)
        ]
        recurrent = _matvec(self._w_rec, z_previous)
        driven = _matvec(self._w_in, inputs)
        leak = self.config.leak_rate
        return [
            (1.0 - leak) * z_previous[index]
            + leak * math.tanh(driven[index] + recurrent[index] + self._bias[index])
            for index in range(self.config.latent_dim)
        ]

    def _select_phase(self, latent: list[float]) -> CellPhase:
        """Deterministic argmax over the non-dead phase readout logits."""
        logits = _matvec(self._w_phase, latent)
        best_phase = _LATENT_PHASES[0]
        best_logit = logits[0]
        for phase, logit in zip(_LATENT_PHASES[1:], logits[1:]):
            if logit > best_logit:
                best_logit = logit
                best_phase = phase
        return best_phase

    def step(
        self,
        molecular: MolecularState,
        environment: LocalEnvironment,
        *,
        previous_state: CellState | None,
        logical_time: int,
    ) -> tuple[CellState, CellAction]:
        _validate_inputs(
            molecular=molecular,
            environment=environment,
            previous_state=previous_state,
            logical_time=logical_time,
        )
        stress_load, activation_drive, repair_drive, death_drive = self._drives(
            molecular, environment
        )
        metadata = _metadata(
            logical_time=logical_time,
            model_version=self.model_version,
            source={
                "molecular": molecular,
                "environment": environment,
                "previous_state": previous_state,
                "config": self.config,
            },
        )

        if previous_state is not None and previous_state.phase is CellPhase.DEAD:
            state = CellState(
                metadata=metadata,
                cell_id=molecular.cell_id,
                phase=CellPhase.DEAD,
                activation=0.0,
                viability=previous_state.viability,
                stress_load=stress_load,
            )
            return state, _dead_action(metadata, molecular.cell_id)

        viability_base = (
            previous_state.viability
            if previous_state is not None
            else 0.5 * molecular.repair_protein
            + 0.5 * molecular.metabolic_capacity
        )
        viability = _clamp(
            viability_base
            + self.config.repair_recovery_rate * repair_drive
            - self.config.stress_damage_rate * stress_load
            - self.config.death_damage_rate * death_drive
        )

        if (
            viability <= self.config.death_viability_threshold
            or death_drive >= self.config.death_drive_threshold
        ):
            phase = CellPhase.DEAD
        else:
            phase = self._select_phase(
                self._latent(
                    self._input_vector(molecular, environment, previous_state),
                    previous_state,
                )
            )

        state = CellState(
            metadata=metadata,
            cell_id=molecular.cell_id,
            phase=phase,
            activation=activation_drive,
            viability=viability,
            stress_load=stress_load,
        )
        if phase is CellPhase.DEAD:
            return state, _dead_action(metadata, molecular.cell_id)

        repair_effort = (
            repair_drive if phase is CellPhase.REPAIRING else 0.0
        )
        action = CellAction(
            metadata=metadata,
            cell_id=molecular.cell_id,
            secretion=_clamp(
                self.config.secretion_multiplier_map[phase]
                * activation_drive
                * molecular.metabolic_capacity
            ),
            resource_consumption=_clamp(
                self.config.basal_consumption
                + self.config.activation_consumption_rate * activation_drive
                + self.config.repair_consumption_rate * repair_effort
            ),
            repair_effort=repair_effort,
            apoptosis=False,
        )
        return state, action

    def simulate(
        self,
        *,
        molecular: MolecularState,
        stress: float,
        resource_level: float,
        incoming_signal: float,
        steps: int,
    ) -> CellTrajectory:
        if steps < 1:
            raise ValueError("steps must be positive")
        states: list[CellState] = []
        actions: list[CellAction] = []
        previous_state: CellState | None = None
        for logical_time in range(1, steps + 1):
            environment = LocalEnvironment(
                metadata=_metadata(
                    logical_time=logical_time,
                    model_version="l3-to-l2-local-boundary-latent-0.1",
                    source={
                        "cell_id": molecular.cell_id,
                        "stress": stress,
                        "resource_level": resource_level,
                        "incoming_signal": incoming_signal,
                    },
                ),
                cell_id=molecular.cell_id,
                stress=stress,
                resource_level=resource_level,
                incoming_signal=incoming_signal,
            )
            state, action = self.step(
                molecular,
                environment,
                previous_state=previous_state,
                logical_time=logical_time,
            )
            states.append(state)
            actions.append(action)
            previous_state = state
        return CellTrajectory(states=tuple(states), actions=tuple(actions))
