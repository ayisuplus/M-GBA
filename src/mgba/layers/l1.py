from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..hashing import digest_payload
from .contracts import MolecularInput, MolecularState, StateMetadata, TranscriptState


MOLECULAR_SPECIES = (
    "damage_receptor",
    "signal_protein",
    "repair_protein",
    "metabolic_capacity",
    "death_effector",
    "feedback_inhibitor",
)

TRANSCRIPT_BY_SPECIES = {
    "damage_receptor": "damage_response",
    "signal_protein": "signal_expression",
    "repair_protein": "repair_expression",
    "metabolic_capacity": "metabolic_expression",
    "death_effector": "death_expression",
    "feedback_inhibitor": "negative_feedback_expression",
}


@dataclass(frozen=True, slots=True)
class MolecularSpeciesConfig:
    name: str
    transcript: str
    synthesis_rate: float
    degradation_rate: float

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.transcript.strip():
            raise ValueError("molecular species names must not be empty")
        if not math.isfinite(self.synthesis_rate) or not math.isfinite(
            self.degradation_rate
        ):
            raise ValueError("molecular rates must be finite")
        if not (
            0.0 < self.synthesis_rate <= self.degradation_rate <= 1.0
        ):
            raise ValueError(
                "molecular rates must satisfy 0 < synthesis <= degradation <= 1"
            )


@dataclass(frozen=True, slots=True)
class MolecularConfig:
    model_version: str
    species: tuple[MolecularSpeciesConfig, ...]
    local_signal_gain: float
    feedback_inhibition: float

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("molecular model_version must not be empty")
        names = tuple(item.name for item in self.species)
        if names != MOLECULAR_SPECIES:
            raise ValueError("molecular species must match the frozen order")
        mappings = {item.name: item.transcript for item in self.species}
        if mappings != TRANSCRIPT_BY_SPECIES:
            raise ValueError("molecular transcript mappings must match ADR-0003")
        for value, name in (
            (self.local_signal_gain, "local_signal_gain"),
            (self.feedback_inhibition, "feedback_inhibition"),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and in [0, 1]")


@dataclass(frozen=True, slots=True)
class MolecularTrajectory:
    states: tuple[MolecularState, ...]

    def __post_init__(self) -> None:
        if not self.states:
            raise ValueError("molecular trajectory must contain an initial state")


def load_molecular_config(path: str | Path) -> MolecularConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        raw_species: dict[str, Any] = raw["species"]
        if set(raw_species) != set(MOLECULAR_SPECIES):
            raise ValueError("molecular config has missing or unknown species")
        species = tuple(
            MolecularSpeciesConfig(
                name=name,
                transcript=str(raw_species[name]["transcript"]),
                synthesis_rate=float(raw_species[name]["synthesis_rate"]),
                degradation_rate=float(raw_species[name]["degradation_rate"]),
            )
            for name in MOLECULAR_SPECIES
        )
        return MolecularConfig(
            model_version=str(raw["model_version"]),
            species=species,
            local_signal_gain=float(raw["local_signal_gain"]),
            feedback_inhibition=float(raw["feedback_inhibition"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid molecular config: {error}") from error


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _state_values(state: MolecularState) -> dict[str, float]:
    return {species: getattr(state, species) for species in MOLECULAR_SPECIES}


def _build_state(
    *,
    cell_id: str,
    logical_time: int,
    model_version: str,
    source: Any,
    values: dict[str, float],
) -> MolecularState:
    return MolecularState(
        metadata=StateMetadata(
            logical_time=logical_time,
            model_version=model_version,
            source_digest=digest_payload(source),
        ),
        cell_id=cell_id,
        **{species: values[species] for species in MOLECULAR_SPECIES},
    )


class StaticMolecularModel:
    """Frozen identity-like L1 baseline retained for contract regression."""

    model_version = "reference-l1-static-placeholder-0.2"

    def step(
        self,
        transcript: TranscriptState,
        *,
        previous_state: MolecularState | None,
        molecular_input: MolecularInput,
        logical_time: int,
    ) -> MolecularState:
        _validate_inputs(
            transcript=transcript,
            previous_state=previous_state,
            molecular_input=molecular_input,
            logical_time=logical_time,
        )
        values = {
            species: getattr(transcript, transcript_name)
            for species, transcript_name in TRANSCRIPT_BY_SPECIES.items()
        }
        return _build_state(
            cell_id=transcript.cell_id,
            logical_time=logical_time,
            model_version=self.model_version,
            source={
                "transcript": transcript,
                "previous_state": previous_state,
                "molecular_input": molecular_input,
            },
            values=values,
        )


class CoarseMolecularModel:
    """Deterministic translation/degradation reference model for L1."""

    def __init__(self, config: MolecularConfig) -> None:
        self.config = config

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    def initialize(
        self,
        *,
        transcript: TranscriptState,
        molecular_input: MolecularInput,
        logical_time: int = 0,
    ) -> MolecularState:
        _validate_inputs(
            transcript=transcript,
            previous_state=None,
            molecular_input=molecular_input,
            logical_time=logical_time,
            allow_same_transcript_time=True,
        )
        return _build_state(
            cell_id=transcript.cell_id,
            logical_time=logical_time,
            model_version=self.model_version,
            source={
                "phase": "initial",
                "transcript": transcript,
                "molecular_input": molecular_input,
                "config": self.config,
            },
            values={species: 0.0 for species in MOLECULAR_SPECIES},
        )

    def step(
        self,
        transcript: TranscriptState,
        *,
        previous_state: MolecularState | None,
        molecular_input: MolecularInput,
        logical_time: int,
    ) -> MolecularState:
        _validate_inputs(
            transcript=transcript,
            previous_state=previous_state,
            molecular_input=molecular_input,
            logical_time=logical_time,
        )
        previous_values = (
            _state_values(previous_state)
            if previous_state is not None
            else {species: 0.0 for species in MOLECULAR_SPECIES}
        )
        next_values: dict[str, float] = {}
        for species in self.config.species:
            transcript_drive = getattr(transcript, species.transcript)
            if species.name == "signal_protein":
                transcript_drive = _clamp(
                    transcript_drive
                    * (
                        1.0
                        - self.config.feedback_inhibition
                        * previous_values["feedback_inhibitor"]
                    )
                    + self.config.local_signal_gain
                    * previous_values["damage_receptor"]
                    * molecular_input.local_signal
                )
            next_values[species.name] = _clamp(
                (1.0 - species.degradation_rate)
                * previous_values[species.name]
                + species.synthesis_rate * transcript_drive
            )
        return _build_state(
            cell_id=transcript.cell_id,
            logical_time=logical_time,
            model_version=self.model_version,
            source={
                "transcript": transcript,
                "previous_state": previous_state,
                "molecular_input": molecular_input,
                "config": self.config,
            },
            values=next_values,
        )

    def simulate(
        self,
        *,
        transcript: TranscriptState,
        local_signal: float,
        steps: int,
    ) -> MolecularTrajectory:
        if steps < 0:
            raise ValueError("steps must be non-negative")
        initial_input = _molecular_input(
            cell_id=transcript.cell_id,
            local_signal=local_signal,
            logical_time=0,
        )
        states = [
            self.initialize(
                transcript=transcript,
                molecular_input=initial_input,
            )
        ]
        for logical_time in range(1, steps + 1):
            result = self.step(
                transcript,
                previous_state=states[-1],
                molecular_input=_molecular_input(
                    cell_id=transcript.cell_id,
                    local_signal=local_signal,
                    logical_time=logical_time,
                ),
                logical_time=logical_time,
            )
            states.append(result)
        return MolecularTrajectory(states=tuple(states))


def _molecular_input(
    *, cell_id: str, local_signal: float, logical_time: int
) -> MolecularInput:
    return MolecularInput(
        metadata=StateMetadata(
            logical_time=logical_time,
            model_version="l1-local-signal-boundary-0.1",
            source_digest=digest_payload(
                {"cell_id": cell_id, "local_signal": local_signal}
            ),
        ),
        cell_id=cell_id,
        local_signal=local_signal,
    )


def _validate_inputs(
    *,
    transcript: TranscriptState,
    previous_state: MolecularState | None,
    molecular_input: MolecularInput,
    logical_time: int,
    allow_same_transcript_time: bool = False,
) -> None:
    if not isinstance(transcript, TranscriptState):
        raise TypeError("molecular models consume TranscriptState only")
    if previous_state is not None and not isinstance(previous_state, MolecularState):
        raise TypeError("previous L1 state must be a MolecularState")
    if not isinstance(molecular_input, MolecularInput):
        raise TypeError("molecular models require a MolecularInput")
    if molecular_input.cell_id != transcript.cell_id:
        raise ValueError("molecular input and transcript cell ids must match")
    if previous_state is not None:
        if previous_state.cell_id != transcript.cell_id:
            raise ValueError("previous L1 state must belong to the same cell")
        if logical_time <= previous_state.metadata.logical_time:
            raise ValueError("logical_time must advance beyond the previous L1 state")
    if molecular_input.metadata.logical_time != logical_time:
        raise ValueError("molecular input time must match the L1 step")
    if not allow_same_transcript_time and transcript.metadata.logical_time > logical_time:
        raise ValueError("L1 cannot consume a future TranscriptState")
