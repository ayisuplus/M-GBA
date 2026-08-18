from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Protocol

from ..models import Genome


class LayerId(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class OrganismOutcome(StrEnum):
    STABLE = "stable"
    RECOVERED = "recovered"
    DETERIORATING = "deteriorating"
    FAILED = "failed"


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def _require_unit_interval(value: float, field_name: str) -> None:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be a finite value in [0, 1]")


@dataclass(frozen=True, slots=True)
class StateMetadata:
    logical_time: int
    model_version: str
    source_digest: str

    def __post_init__(self) -> None:
        if self.logical_time < 0:
            raise ValueError("logical_time must be non-negative")
        _require_text(self.model_version, "model_version")
        _require_text(self.source_digest, "source_digest")


@dataclass(frozen=True, slots=True)
class RegulatoryInput:
    """External L0 boundary input; it is not an output from a non-adjacent layer."""

    damage_signal: float

    def __post_init__(self) -> None:
        _require_unit_interval(self.damage_signal, "damage_signal")


@dataclass(frozen=True, slots=True)
class TranscriptState:
    metadata: StateMetadata
    cell_id: str
    damage_response: float
    signal_expression: float
    repair_expression: float
    metabolic_expression: float
    death_expression: float
    negative_feedback_expression: float

    def __post_init__(self) -> None:
        _require_text(self.cell_id, "cell_id")
        _require_unit_interval(self.damage_response, "damage_response")
        _require_unit_interval(self.signal_expression, "signal_expression")
        _require_unit_interval(self.repair_expression, "repair_expression")
        _require_unit_interval(self.metabolic_expression, "metabolic_expression")
        _require_unit_interval(self.death_expression, "death_expression")
        _require_unit_interval(
            self.negative_feedback_expression, "negative_feedback_expression"
        )


class PerturbationKind(StrEnum):
    KNOCKDOWN = "knockdown"
    OVEREXPRESSION = "overexpression"
    CLAMP_NO_CHANGE = "clamp-no-change"


@dataclass(frozen=True, slots=True)
class L0PerturbationEvent:
    cell_id: str
    logical_time: int
    gene: str
    unperturbed_value: float
    applied_value: float
    kind: PerturbationKind

    def __post_init__(self) -> None:
        _require_text(self.cell_id, "cell_id")
        _require_text(self.gene, "gene")
        if self.logical_time < 0:
            raise ValueError("logical_time must be non-negative")
        _require_unit_interval(self.unperturbed_value, "unperturbed_value")
        _require_unit_interval(self.applied_value, "applied_value")


@dataclass(frozen=True, slots=True)
class GenomeStepResult:
    state: TranscriptState
    perturbation_events: tuple[L0PerturbationEvent, ...] = ()

    def __post_init__(self) -> None:
        for event in self.perturbation_events:
            if event.cell_id != self.state.cell_id:
                raise ValueError("perturbation event cell id must match its L0 state")
            if event.logical_time != self.state.metadata.logical_time:
                raise ValueError("perturbation event time must match its L0 state")


@dataclass(frozen=True, slots=True)
class MolecularState:
    metadata: StateMetadata
    cell_id: str
    damage_receptor: float
    signal_protein: float
    repair_protein: float
    metabolic_capacity: float
    death_effector: float
    feedback_inhibitor: float

    def __post_init__(self) -> None:
        _require_text(self.cell_id, "cell_id")
        _require_unit_interval(self.damage_receptor, "damage_receptor")
        _require_unit_interval(self.signal_protein, "signal_protein")
        _require_unit_interval(self.repair_protein, "repair_protein")
        _require_unit_interval(self.metabolic_capacity, "metabolic_capacity")
        _require_unit_interval(self.death_effector, "death_effector")
        _require_unit_interval(self.feedback_inhibitor, "feedback_inhibitor")


@dataclass(frozen=True, slots=True)
class MolecularInput:
    """Adjacent L2-to-L1 signal boundary; zero keeps feedback disabled."""

    metadata: StateMetadata
    cell_id: str
    local_signal: float

    def __post_init__(self) -> None:
        _require_text(self.cell_id, "cell_id")
        _require_unit_interval(self.local_signal, "local_signal")


@dataclass(frozen=True, slots=True)
class LocalEnvironment:
    """L3 boundary state visible to one L2 cell."""

    metadata: StateMetadata
    cell_id: str
    stress: float
    resource_level: float
    incoming_signal: float

    def __post_init__(self) -> None:
        _require_text(self.cell_id, "cell_id")
        _require_unit_interval(self.stress, "stress")
        _require_unit_interval(self.resource_level, "resource_level")
        _require_unit_interval(self.incoming_signal, "incoming_signal")


class CellPhase(StrEnum):
    QUIESCENT = "quiescent"
    ACTIVATED = "activated"
    REPAIRING = "repairing"
    STRESSED = "stressed"
    DEAD = "dead"


@dataclass(frozen=True, slots=True)
class CellState:
    metadata: StateMetadata
    cell_id: str
    phase: CellPhase
    activation: float
    viability: float
    stress_load: float

    def __post_init__(self) -> None:
        _require_text(self.cell_id, "cell_id")
        _require_unit_interval(self.activation, "activation")
        _require_unit_interval(self.viability, "viability")
        _require_unit_interval(self.stress_load, "stress_load")


@dataclass(frozen=True, slots=True)
class CellAction:
    metadata: StateMetadata
    cell_id: str
    secretion: float
    resource_consumption: float
    repair_effort: float
    apoptosis: bool

    def __post_init__(self) -> None:
        _require_text(self.cell_id, "cell_id")
        _require_unit_interval(self.secretion, "secretion")
        _require_unit_interval(self.resource_consumption, "resource_consumption")
        _require_unit_interval(self.repair_effort, "repair_effort")


@dataclass(frozen=True, slots=True)
class TissueNodeState:
    cell_id: str
    stress: float
    resource_level: float
    signal: float

    def __post_init__(self) -> None:
        _require_text(self.cell_id, "cell_id")
        _require_unit_interval(self.stress, "stress")
        _require_unit_interval(self.resource_level, "resource_level")
        _require_unit_interval(self.signal, "signal")


@dataclass(frozen=True, slots=True)
class TissueState:
    metadata: StateMetadata
    cell_count: int
    nodes: tuple[TissueNodeState, ...]
    edges: tuple[tuple[str, str], ...]
    edge_density: float
    mean_activation: float
    mean_viability: float
    mean_resource: float
    mean_signal: float
    dead_fraction: float
    repair_activity: float
    coordinated_signal: float
    tissue_damage: float

    def __post_init__(self) -> None:
        if self.cell_count < 1:
            raise ValueError("cell_count must be positive")
        node_ids = tuple(node.cell_id for node in self.nodes)
        if len(self.nodes) != self.cell_count or node_ids != tuple(sorted(node_ids)):
            raise ValueError("tissue nodes must be complete, unique, and sorted")
        node_set = set(node_ids)
        if len(node_set) != self.cell_count:
            raise ValueError("tissue node ids must be unique")
        if self.edges != tuple(sorted(self.edges)) or len(self.edges) != len(
            set(self.edges)
        ):
            raise ValueError("tissue edges must be unique and sorted")
        for source, target in self.edges:
            if source == target or source not in node_set or target not in node_set:
                raise ValueError("tissue edges must connect distinct known nodes")
        for field_name in (
            "edge_density",
            "mean_activation",
            "mean_viability",
            "mean_resource",
            "mean_signal",
            "dead_fraction",
            "repair_activity",
            "coordinated_signal",
            "tissue_damage",
        ):
            _require_unit_interval(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class OrganismState:
    metadata: StateMetadata
    vitality: float
    damage_burden: float
    inflammation: float
    homeostasis: float
    recovery_capacity: float

    def __post_init__(self) -> None:
        _require_unit_interval(self.vitality, "vitality")
        _require_unit_interval(self.damage_burden, "damage_burden")
        _require_unit_interval(self.inflammation, "inflammation")
        _require_unit_interval(self.homeostasis, "homeostasis")
        _require_unit_interval(self.recovery_capacity, "recovery_capacity")


@dataclass(frozen=True, slots=True)
class PhenotypeWindow:
    metadata: StateMetadata
    start_time: int
    end_time: int
    sample_count: int
    mean_vitality: float
    mean_damage_burden: float
    mean_inflammation: float
    mean_homeostasis: float
    mean_recovery_capacity: float
    final_vitality: float
    final_damage_burden: float
    final_homeostasis: float
    homeostasis_delta: float
    outcome: OrganismOutcome

    def __post_init__(self) -> None:
        if self.start_time < 0 or self.end_time < self.start_time:
            raise ValueError("phenotype window times must be non-negative and ordered")
        if self.sample_count < 1:
            raise ValueError("phenotype window must contain at least one sample")
        if self.sample_count == 1 and self.start_time != self.end_time:
            raise ValueError("a one-sample phenotype window must have one time")
        if self.sample_count > 1 and self.start_time >= self.end_time:
            raise ValueError("a multi-sample phenotype window must advance time")
        if self.metadata.logical_time != self.end_time:
            raise ValueError("phenotype window metadata time must equal end_time")
        for field_name in (
            "mean_vitality",
            "mean_damage_burden",
            "mean_inflammation",
            "mean_homeostasis",
            "mean_recovery_capacity",
            "final_vitality",
            "final_damage_burden",
            "final_homeostasis",
        ):
            _require_unit_interval(getattr(self, field_name), field_name)
        if not math.isfinite(self.homeostasis_delta) or not -1.0 <= self.homeostasis_delta <= 1.0:
            raise ValueError("homeostasis_delta must be a finite value in [-1, 1]")
        if not isinstance(self.outcome, OrganismOutcome):
            raise TypeError("phenotype window outcome must be OrganismOutcome")


class GenomeModel(Protocol):
    model_version: str

    def step(
        self,
        *,
        cell_id: str,
        genome: Genome,
        previous_state: TranscriptState | None,
        regulatory_input: RegulatoryInput,
        perturbations: Mapping[str, float],
        logical_time: int,
    ) -> GenomeStepResult: ...


class MolecularModel(Protocol):
    model_version: str

    def step(
        self,
        transcript: TranscriptState,
        *,
        previous_state: MolecularState | None,
        molecular_input: MolecularInput,
        logical_time: int,
    ) -> MolecularState: ...


class CellModel(Protocol):
    model_version: str

    def step(
        self,
        molecular: MolecularState,
        environment: LocalEnvironment,
        *,
        previous_state: CellState | None,
        logical_time: int,
    ) -> tuple[CellState, CellAction]: ...


class TissueModel(Protocol):
    model_version: str

    def step(
        self,
        cell_states: tuple[CellState, ...],
        cell_actions: tuple[CellAction, ...],
        *,
        initial_environments: tuple[LocalEnvironment, ...] | None,
        previous_state: TissueState | None,
        edges: tuple[tuple[str, str], ...],
        logical_time: int,
    ) -> TissueState: ...


class PhenotypeModel(Protocol):
    model_version: str

    def step(
        self, tissue: TissueState, *, logical_time: int
    ) -> OrganismState: ...


class WindowedPhenotypeModel(PhenotypeModel, Protocol):
    def summarize(
        self, states: tuple[OrganismState, ...]
    ) -> PhenotypeWindow: ...
