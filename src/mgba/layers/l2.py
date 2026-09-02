from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..hashing import digest_payload
from .contracts import (
    CellAction,
    CellPhase,
    CellState,
    LocalEnvironment,
    MolecularState,
    StateMetadata,
)


@dataclass(frozen=True, slots=True)
class CellConfig:
    model_version: str
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
    activation_threshold: float
    repair_threshold: float
    stress_threshold: float
    death_drive_threshold: float
    death_viability_threshold: float
    secretion_multipliers: tuple[tuple[CellPhase, float], ...]

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("cell model_version must not be empty")
        scalar_names = (
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
            "activation_threshold",
            "repair_threshold",
            "stress_threshold",
            "death_drive_threshold",
            "death_viability_threshold",
        )
        for name in scalar_names:
            value = getattr(self, name)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and in [0, 1]")
        multiplier_phases = tuple(phase for phase, _ in self.secretion_multipliers)
        if multiplier_phases != tuple(CellPhase):
            raise ValueError("secretion multipliers must match every CellPhase in order")
        for _, value in self.secretion_multipliers:
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError("secretion multipliers must be finite and in [0, 1]")

    @property
    def secretion_multiplier_map(self) -> dict[CellPhase, float]:
        return dict(self.secretion_multipliers)


@dataclass(frozen=True, slots=True)
class CellTrajectory:
    states: tuple[CellState, ...]
    actions: tuple[CellAction, ...]

    def __post_init__(self) -> None:
        if not self.states or len(self.states) != len(self.actions):
            raise ValueError("cell trajectory requires aligned states and actions")


def load_cell_config(path: str | Path) -> CellConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        raw_multipliers: dict[str, Any] = raw["secretion_multipliers"]
        if set(raw_multipliers) != {phase.value for phase in CellPhase}:
            raise ValueError("cell config has missing or unknown secretion phases")
        return CellConfig(
            model_version=str(raw["model_version"]),
            stress_environment_weight=float(raw["stress_environment_weight"]),
            resource_deficit_weight=float(raw["resource_deficit_weight"]),
            death_stress_weight=float(raw["death_stress_weight"]),
            metabolic_buffer_weight=float(raw["metabolic_buffer_weight"]),
            signal_activation_weight=float(raw["signal_activation_weight"]),
            incoming_signal_weight=float(raw["incoming_signal_weight"]),
            death_effector_weight=float(raw["death_effector_weight"]),
            stress_mortality_weight=float(raw["stress_mortality_weight"]),
            repair_recovery_rate=float(raw["repair_recovery_rate"]),
            stress_damage_rate=float(raw["stress_damage_rate"]),
            death_damage_rate=float(raw["death_damage_rate"]),
            basal_consumption=float(raw["basal_consumption"]),
            activation_consumption_rate=float(raw["activation_consumption_rate"]),
            repair_consumption_rate=float(raw["repair_consumption_rate"]),
            activation_threshold=float(raw["activation_threshold"]),
            repair_threshold=float(raw["repair_threshold"]),
            stress_threshold=float(raw["stress_threshold"]),
            death_drive_threshold=float(raw["death_drive_threshold"]),
            death_viability_threshold=float(raw["death_viability_threshold"]),
            secretion_multipliers=tuple(
                (phase, float(raw_multipliers[phase.value])) for phase in CellPhase
            ),
        )
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid cell config: {error}") from error


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


class StaticCellModel:
    """Frozen continuous L2 baseline retained for contract regression."""

    model_version = "reference-l2-static-rules-0.2"

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
        activation = _clamp(molecular.signal_protein * environment.stress)
        viability = _clamp(
            0.5 * molecular.repair_protein
            + 0.5 * molecular.metabolic_capacity
            - 0.4 * environment.stress
        )
        phase = CellPhase.DEAD if viability == 0.0 else CellPhase.ACTIVATED
        metadata = _metadata(
            logical_time=logical_time,
            model_version=self.model_version,
            source={
                "molecular": molecular,
                "environment": environment,
                "previous_state": previous_state,
            },
        )
        state = CellState(
            metadata=metadata,
            cell_id=molecular.cell_id,
            phase=phase,
            activation=activation,
            viability=viability,
            stress_load=environment.stress,
        )
        if phase is CellPhase.DEAD:
            action = _dead_action(metadata, molecular.cell_id)
        else:
            action = CellAction(
                metadata=metadata,
                cell_id=molecular.cell_id,
                secretion=_clamp(
                    molecular.signal_protein
                    * environment.stress
                    * (0.5 + 0.5 * molecular.metabolic_capacity)
                ),
                resource_consumption=0.0,
                repair_effort=0.0,
                apoptosis=False,
            )
        return state, action


class CellStateMachineModel:
    """Deterministic local-information Cell state machine for L2."""

    def __init__(self, config: CellConfig) -> None:
        self.config = config

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

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
        stress_load = _clamp(
            self.config.stress_environment_weight * environment.stress
            + self.config.resource_deficit_weight
            * (1.0 - environment.resource_level)
            + self.config.death_stress_weight * molecular.death_effector
            - self.config.metabolic_buffer_weight * molecular.metabolic_capacity
        )
        activation_drive = _clamp(
            self.config.signal_activation_weight * molecular.signal_protein
            + self.config.incoming_signal_weight * environment.incoming_signal
        )
        repair_drive = _clamp(
            molecular.repair_protein
            * stress_load
            * environment.resource_level
        )
        death_drive = _clamp(
            self.config.death_effector_weight * molecular.death_effector
            + self.config.stress_mortality_weight
            * stress_load
            * (1.0 - molecular.metabolic_capacity)
        )
        source = {
            "molecular": molecular,
            "environment": environment,
            "previous_state": previous_state,
            "config": self.config,
        }
        metadata = _metadata(
            logical_time=logical_time,
            model_version=self.model_version,
            source=source,
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
        phase = self._phase(
            viability=viability,
            repair_drive=repair_drive,
            stress_load=stress_load,
            death_drive=death_drive,
            activation_drive=activation_drive,
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

    def _phase(
        self,
        *,
        viability: float,
        repair_drive: float,
        stress_load: float,
        death_drive: float,
        activation_drive: float,
    ) -> CellPhase:
        if (
            viability <= self.config.death_viability_threshold
            or death_drive >= self.config.death_drive_threshold
        ):
            return CellPhase.DEAD
        if repair_drive >= self.config.repair_threshold:
            return CellPhase.REPAIRING
        if stress_load >= self.config.stress_threshold:
            return CellPhase.STRESSED
        if activation_drive >= self.config.activation_threshold:
            return CellPhase.ACTIVATED
        return CellPhase.QUIESCENT

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
                    model_version="l3-to-l2-local-boundary-0.1",
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


def _dead_action(metadata: StateMetadata, cell_id: str) -> CellAction:
    return CellAction(
        metadata=metadata,
        cell_id=cell_id,
        secretion=0.0,
        resource_consumption=0.0,
        repair_effort=0.0,
        apoptosis=True,
    )


def _validate_inputs(
    *,
    molecular: MolecularState,
    environment: LocalEnvironment,
    previous_state: CellState | None,
    logical_time: int,
) -> None:
    if not isinstance(molecular, MolecularState):
        raise TypeError("Cell models consume MolecularState only")
    if not isinstance(environment, LocalEnvironment):
        raise TypeError("Cell models require a LocalEnvironment")
    if previous_state is not None and not isinstance(previous_state, CellState):
        raise TypeError("previous L2 state must be a CellState")
    if molecular.cell_id != environment.cell_id:
        raise ValueError("molecular and environment cell ids must match")
    if previous_state is not None:
        if previous_state.cell_id != molecular.cell_id:
            raise ValueError("previous L2 state must belong to the same cell")
        if logical_time <= previous_state.metadata.logical_time:
            raise ValueError("logical_time must advance beyond the previous L2 state")
    if environment.metadata.logical_time != logical_time:
        raise ValueError("local environment time must match the L2 step")
    if molecular.metadata.logical_time > logical_time:
        raise ValueError("L2 cannot consume a future MolecularState")
