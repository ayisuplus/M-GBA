from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..experiment import digest_payload
from ..models import Genome
from .contracts import (
    GenomeStepResult,
    L0PerturbationEvent,
    PerturbationKind,
    RegulatoryInput,
    StateMetadata,
    TranscriptState,
)


ABSTRACT_GENE_NAMES = (
    "damage_response",
    "signal_expression",
    "repair_expression",
    "metabolic_expression",
    "death_expression",
    "negative_feedback_expression",
)


@dataclass(frozen=True, slots=True)
class RegulatoryEdge:
    source: str
    target: str
    weight: float

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.target.strip():
            raise ValueError("regulatory edge endpoints must not be empty")
        if not math.isfinite(self.weight) or self.weight == 0.0:
            raise ValueError("regulatory edge weight must be finite and non-zero")


@dataclass(frozen=True, slots=True)
class GrnConfig:
    model_version: str
    nodes: tuple[str, ...]
    update_rate: float
    basal_weight: float
    biases: tuple[tuple[str, float], ...]
    damage_weights: tuple[tuple[str, float], ...]
    edges: tuple[RegulatoryEdge, ...]

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("GRN model_version must not be empty")
        if self.nodes != ABSTRACT_GENE_NAMES:
            raise ValueError("GRN nodes must match the frozen abstract gene order")
        if not math.isfinite(self.update_rate) or not 0.0 < self.update_rate <= 1.0:
            raise ValueError("update_rate must be finite and in (0, 1]")
        if not math.isfinite(self.basal_weight):
            raise ValueError("basal_weight must be finite")

        node_set = set(self.nodes)
        bias_names = [name for name, _ in self.biases]
        if set(bias_names) != node_set or len(bias_names) != len(node_set):
            raise ValueError("biases must contain each frozen GRN node exactly once")
        damage_names = [name for name, _ in self.damage_weights]
        if not set(damage_names) <= node_set or len(damage_names) != len(
            set(damage_names)
        ):
            raise ValueError("damage weights must target unique known GRN nodes")
        for _, value in (*self.biases, *self.damage_weights):
            if not math.isfinite(value):
                raise ValueError("GRN scalar parameters must be finite")

        edge_keys: set[tuple[str, str]] = set()
        for edge in self.edges:
            if edge.source not in node_set or edge.target not in node_set:
                raise ValueError("regulatory edges must connect known GRN nodes")
            key = (edge.source, edge.target)
            if key in edge_keys:
                raise ValueError("duplicate regulatory edges are not allowed")
            edge_keys.add(key)

    @property
    def bias_map(self) -> dict[str, float]:
        return dict(self.biases)

    @property
    def damage_weight_map(self) -> dict[str, float]:
        return dict(self.damage_weights)


@dataclass(frozen=True, slots=True)
class GrnTrajectory:
    states: tuple[TranscriptState, ...]
    perturbation_events: tuple[L0PerturbationEvent, ...]

    def __post_init__(self) -> None:
        if not self.states:
            raise ValueError("GRN trajectory must contain at least an initial state")


def load_grn_config(path: str | Path) -> GrnConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return GrnConfig(
            model_version=str(raw["model_version"]),
            nodes=tuple(str(node) for node in raw["nodes"]),
            update_rate=float(raw["update_rate"]),
            basal_weight=float(raw["basal_weight"]),
            biases=tuple(
                sorted((str(name), float(value)) for name, value in raw["biases"].items())
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
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid GRN config: {error}") from error


def _validate_genome(genome: Genome) -> None:
    actual = set(genome.traits)
    expected = set(ABSTRACT_GENE_NAMES)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(
            f"genome traits must match frozen GRN nodes; missing={missing}, unknown={unknown}"
        )


def _state_values(state: TranscriptState) -> dict[str, float]:
    return {gene: getattr(state, gene) for gene in ABSTRACT_GENE_NAMES}


def _perturb(
    *,
    cell_id: str,
    logical_time: int,
    natural_values: Mapping[str, float],
    perturbations: Mapping[str, float],
) -> tuple[dict[str, float], tuple[L0PerturbationEvent, ...]]:
    unknown = set(perturbations) - set(ABSTRACT_GENE_NAMES)
    if unknown:
        raise ValueError(f"perturbations target unknown abstract genes: {sorted(unknown)}")

    applied = dict(natural_values)
    events: list[L0PerturbationEvent] = []
    for gene, requested in sorted(perturbations.items()):
        if not math.isfinite(requested) or not 0.0 <= requested <= 1.0:
            raise ValueError("perturbation values must be finite and in [0, 1]")
        natural = natural_values[gene]
        if requested < natural:
            kind = PerturbationKind.KNOCKDOWN
        elif requested > natural:
            kind = PerturbationKind.OVEREXPRESSION
        else:
            kind = PerturbationKind.CLAMP_NO_CHANGE
        applied[gene] = requested
        events.append(
            L0PerturbationEvent(
                cell_id=cell_id,
                logical_time=logical_time,
                gene=gene,
                unperturbed_value=natural,
                applied_value=requested,
                kind=kind,
            )
        )
    return applied, tuple(events)


def _build_state(
    *,
    cell_id: str,
    logical_time: int,
    model_version: str,
    source: Any,
    values: Mapping[str, float],
) -> TranscriptState:
    return TranscriptState(
        metadata=StateMetadata(
            logical_time=logical_time,
            model_version=model_version,
            source_digest=digest_payload(source),
        ),
        cell_id=cell_id,
        **{gene: values[gene] for gene in ABSTRACT_GENE_NAMES},
    )


class StaticGenomeModel:
    """Frozen static L0 contract baseline retained beside the discrete GRN."""

    model_version = "reference-l0-static-placeholder-0.2"

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
            raise TypeError("StaticGenomeModel requires a RegulatoryInput")
        if previous_state is not None and not isinstance(
            previous_state, TranscriptState
        ):
            raise TypeError("previous L0 state must be a TranscriptState")
        if previous_state is not None and previous_state.cell_id != cell_id:
            raise ValueError("previous L0 state must belong to the same cell")
        natural = (
            _state_values(previous_state)
            if previous_state is not None
            else dict(genome.traits)
        )
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
            },
            values=applied,
        )
        return GenomeStepResult(state=state, perturbation_events=events)


class DiscreteGrnModel:
    """Deterministic synchronous L0 reference model over abstract variables."""

    def __init__(self, config: GrnConfig) -> None:
        self.config = config

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    def initialize(
        self,
        *,
        cell_id: str,
        genome: Genome,
        regulatory_input: RegulatoryInput,
        perturbations: Mapping[str, float],
        logical_time: int = 0,
    ) -> GenomeStepResult:
        _validate_genome(genome)
        if not isinstance(regulatory_input, RegulatoryInput):
            raise TypeError("DiscreteGrnModel requires a RegulatoryInput")
        applied, events = _perturb(
            cell_id=cell_id,
            logical_time=logical_time,
            natural_values=genome.traits,
            perturbations=perturbations,
        )
        state = _build_state(
            cell_id=cell_id,
            logical_time=logical_time,
            model_version=self.model_version,
            source={
                "phase": "initial",
                "genome": genome,
                "regulatory_input": regulatory_input,
                "perturbations": perturbations,
                "config": self.config,
            },
            values=applied,
        )
        return GenomeStepResult(state=state, perturbation_events=events)

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
            raise TypeError("DiscreteGrnModel requires a RegulatoryInput")
        if previous_state is not None:
            if not isinstance(previous_state, TranscriptState):
                raise TypeError("previous L0 state must be a TranscriptState")
            if previous_state.cell_id != cell_id:
                raise ValueError("previous L0 state must belong to the same cell")
            if logical_time <= previous_state.metadata.logical_time:
                raise ValueError("logical_time must advance beyond the previous L0 state")
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

    def simulate(
        self,
        *,
        cell_id: str,
        genome: Genome,
        damage_signal: float,
        steps: int,
        perturbations: Mapping[str, float] | None = None,
    ) -> GrnTrajectory:
        if steps < 0:
            raise ValueError("steps must be non-negative")
        regulatory_input = RegulatoryInput(damage_signal=damage_signal)
        perturbations = perturbations or {}
        initial = self.initialize(
            cell_id=cell_id,
            genome=genome,
            regulatory_input=regulatory_input,
            perturbations=perturbations,
        )
        states = [initial.state]
        events = list(initial.perturbation_events)
        for logical_time in range(1, steps + 1):
            result = self.step(
                cell_id=cell_id,
                genome=genome,
                previous_state=states[-1],
                regulatory_input=regulatory_input,
                perturbations=perturbations,
                logical_time=logical_time,
            )
            states.append(result.state)
            events.extend(result.perturbation_events)
        return GrnTrajectory(states=tuple(states), perturbation_events=tuple(events))


def _sigmoid(value: float) -> float:
    if value >= 0.0:
        return 1.0 / (1.0 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)
