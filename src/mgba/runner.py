from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from . import __version__
from .experiment import (
    ExperimentManifest,
    LayerTransitionEvent,
    canonical_json,
    digest_payload,
)
from .layers import (
    CellAction,
    CellModel,
    CellPhase,
    CellState,
    GenomeModel,
    L0PerturbationEvent,
    LayerId,
    LocalEnvironment,
    MolecularInput,
    MolecularModel,
    MolecularState,
    OrganismState,
    PhenotypeWindow,
    RegulatoryInput,
    StateMetadata,
    TissueModel,
    TissueNodeState,
    TissueState,
    TranscriptState,
    WindowedPhenotypeModel,
)
from .layers.l3 import environments_from_tissue
from .multiscale import MultiscaleScenario


CHECKPOINT_SCHEMA_VERSION = "mgba-runner-checkpoint-0.1"


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    model_version: str
    l0_interval: int
    l4_interval: int
    max_total_ticks: int
    max_cells: int
    max_events_per_tick: int

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("runner model_version must not be empty")
        for name in (
            "l0_interval",
            "l4_interval",
            "max_total_ticks",
            "max_cells",
            "max_events_per_tick",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


def load_runner_config(path: str | Path) -> RunnerConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return RunnerConfig(
            model_version=str(raw["model_version"]),
            l0_interval=raw["l0_interval"],
            l4_interval=raw["l4_interval"],
            max_total_ticks=raw["max_total_ticks"],
            max_cells=raw["max_cells"],
            max_events_per_tick=raw["max_events_per_tick"],
        )
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid runner config: {error}") from error


def _metadata(
    *, logical_time: int, model_version: str, source: Any
) -> StateMetadata:
    return StateMetadata(
        logical_time=logical_time,
        model_version=model_version,
        source_digest=digest_payload(source),
    )


def _json_dict(value: Any) -> dict[str, Any]:
    result = json.loads(canonical_json(value))
    if not isinstance(result, dict):
        raise TypeError("expected a JSON object")
    return result


@dataclass(frozen=True, slots=True)
class MultiscaleTickTrace:
    logical_time: int
    l0_updated: bool
    l4_observed: bool
    l0: tuple[TranscriptState, ...]
    l0_perturbation_events: tuple[L0PerturbationEvent, ...]
    l1_inputs: tuple[MolecularInput, ...]
    l1: tuple[MolecularState, ...]
    l2_environments: tuple[LocalEnvironment, ...]
    l2: tuple[CellState, ...]
    l2_actions: tuple[CellAction, ...]
    l3: TissueState
    l4: OrganismState | None
    transitions: tuple[LayerTransitionEvent, ...]
    event_count: int

    def __post_init__(self) -> None:
        if self.logical_time < 1:
            raise ValueError("tick logical_time must be positive")
        if not self.l0 or not self.l1 or not self.l2:
            raise ValueError("each tick must contain L0, L1 and L2 states")
        id_groups = (
            tuple(state.cell_id for state in self.l0),
            tuple(item.cell_id for item in self.l1_inputs),
            tuple(state.cell_id for state in self.l1),
            tuple(item.cell_id for item in self.l2_environments),
            tuple(state.cell_id for state in self.l2),
            tuple(action.cell_id for action in self.l2_actions),
            tuple(node.cell_id for node in self.l3.nodes),
        )
        if any(ids != id_groups[0] for ids in id_groups[1:]):
            raise ValueError("cell identity must align throughout each tick")
        if id_groups[0] != tuple(sorted(id_groups[0])):
            raise ValueError("tick Cell states must be sorted by id")
        if self.l4_observed != (self.l4 is not None):
            raise ValueError("l4_observed must match the optional L4 state")
        if not self.l0_updated and self.l0_perturbation_events:
            raise ValueError("held L0 state cannot emit perturbation events")
        expected_path = [
            (LayerId.L0, LayerId.L1),
            (LayerId.L1, LayerId.L2),
            (LayerId.L2, LayerId.L3),
        ]
        if self.l4_observed:
            expected_path.append((LayerId.L3, LayerId.L4))
        observed_path = [
            (event.source_layer, event.target_layer)
            for event in self.transitions
        ]
        if observed_path != expected_path:
            raise ValueError("tick transitions must follow the adjacent layer path")
        if any(
            event.logical_time != self.logical_time for event in self.transitions
        ):
            raise ValueError("tick transition times must match logical_time")
        expected_event_count = len(self.transitions) + len(
            self.l0_perturbation_events
        )
        if self.event_count != expected_event_count:
            raise ValueError("tick event_count does not match emitted events")

    def as_dict(self) -> dict[str, Any]:
        result = _json_dict(self)
        result["transitions"] = [event.as_dict() for event in self.transitions]
        return result


@dataclass(frozen=True, slots=True)
class RunnerCheckpoint:
    schema_version: str
    experiment_id: str
    logical_time: int
    model_versions: tuple[tuple[str, str], ...]
    l0: tuple[TranscriptState, ...]
    l1: tuple[MolecularState, ...]
    l2: tuple[CellState, ...]
    l3: TissueState
    l4_observations: tuple[OrganismState, ...]
    history_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("unsupported runner checkpoint schema")
        if not self.experiment_id.strip() or not self.history_digest.strip():
            raise ValueError("checkpoint identity fields must not be empty")
        if self.logical_time < 1:
            raise ValueError("checkpoint logical_time must be positive")
        if self.model_versions != tuple(sorted(self.model_versions)):
            raise ValueError("checkpoint model_versions must be unique and sorted")
        versions = dict(self.model_versions)
        if len(versions) != len(self.model_versions) or set(versions) != {
            "L0",
            "L1",
            "L2",
            "L3",
            "L4",
            "runner",
        }:
            raise ValueError("checkpoint must identify runner and all five models")
        id_groups = (
            tuple(state.cell_id for state in self.l0),
            tuple(state.cell_id for state in self.l1),
            tuple(state.cell_id for state in self.l2),
            tuple(node.cell_id for node in self.l3.nodes),
        )
        if not id_groups[0] or any(ids != id_groups[0] for ids in id_groups[1:]):
            raise ValueError("checkpoint Cell identities must be complete and aligned")
        if id_groups[0] != tuple(sorted(id_groups[0])):
            raise ValueError("checkpoint Cell identities must be sorted")
        for state in self.l0:
            if (
                state.metadata.model_version != versions["L0"]
                or state.metadata.logical_time > self.logical_time
            ):
                raise ValueError("checkpoint L0 state does not match its model/time")
        for layer, states in (("L1", self.l1), ("L2", self.l2)):
            if any(
                state.metadata.model_version != versions[layer]
                or state.metadata.logical_time != self.logical_time
                for state in states
            ):
                raise ValueError(f"checkpoint {layer} state does not match model/time")
        if (
            self.l3.metadata.model_version != versions["L3"]
            or self.l3.metadata.logical_time != self.logical_time
        ):
            raise ValueError("checkpoint L3 state does not match its model/time")
        observation_times = tuple(
            state.metadata.logical_time for state in self.l4_observations
        )
        if not observation_times or any(
            current <= previous
            for previous, current in zip(
                observation_times, observation_times[1:]
            )
        ):
            raise ValueError("checkpoint L4 observations must strictly increase")
        if observation_times[-1] > self.logical_time or any(
            state.metadata.model_version != versions["L4"]
            for state in self.l4_observations
        ):
            raise ValueError("checkpoint L4 observations do not match model/time")

    @property
    def checkpoint_id(self) -> str:
        return f"checkpoint-{digest_payload(self)[:16]}"

    def as_dict(self) -> dict[str, Any]:
        result = _json_dict(self)
        result["checkpoint_id"] = self.checkpoint_id
        return result


@dataclass(frozen=True, slots=True)
class MultirateRun:
    manifest: ExperimentManifest
    start_tick: int
    end_tick: int
    ticks: tuple[MultiscaleTickTrace, ...]
    checkpoint: RunnerCheckpoint
    terminal_observation: OrganismState
    phenotype_window: PhenotypeWindow
    history_digest: str

    def __post_init__(self) -> None:
        if self.start_tick < 1 or self.end_tick < self.start_tick:
            raise ValueError("run tick range must be positive and ordered")
        expected_times = tuple(range(self.start_tick, self.end_tick + 1))
        if tuple(tick.logical_time for tick in self.ticks) != expected_times:
            raise ValueError("run must contain every requested tick in order")
        if self.checkpoint.logical_time != self.end_tick:
            raise ValueError("run checkpoint must end at end_tick")
        if self.checkpoint.experiment_id != self.manifest.experiment_id:
            raise ValueError("run manifest and checkpoint experiment ids must match")
        if self.terminal_observation.metadata.logical_time != self.end_tick:
            raise ValueError("terminal L4 observation must occur at end_tick")
        if self.phenotype_window.end_time != self.end_tick:
            raise ValueError("phenotype window must include the terminal observation")
        if self.history_digest != self.checkpoint.history_digest:
            raise ValueError("run and checkpoint history digests must match")

    def summary_dict(self) -> dict[str, Any]:
        return {
            "model_status": "reference-trajectory-not-validated-biological-model",
            "experiment": self.manifest.as_dict(),
            "start_tick": self.start_tick,
            "end_tick": self.end_tick,
            "tick_count": len(self.ticks),
            "scheduled_l4_observations": len(
                self.checkpoint.l4_observations
            ),
            "checkpoint_id": self.checkpoint.checkpoint_id,
            "history_digest": self.history_digest,
            "terminal_observation": _json_dict(self.terminal_observation),
            "phenotype_window": _json_dict(self.phenotype_window),
        }

    def as_dict(self) -> dict[str, Any]:
        result = self.summary_dict()
        result["checkpoint"] = self.checkpoint.as_dict()
        result["ticks"] = [tick.as_dict() for tick in self.ticks]
        return result


class MultirateCrossScaleRunner:
    """Deterministic multi-rate composition of the five reference layers."""

    def __init__(
        self,
        config: RunnerConfig,
        *,
        genome_model: GenomeModel,
        molecular_model: MolecularModel,
        cell_model: CellModel,
        tissue_model: TissueModel,
        phenotype_model: WindowedPhenotypeModel,
    ) -> None:
        self.config = config
        self.genome_model = genome_model
        self.molecular_model = molecular_model
        self.cell_model = cell_model
        self.tissue_model = tissue_model
        self.phenotype_model = phenotype_model

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    @property
    def model_versions(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                {
                    "runner": self.model_version,
                    "L0": self.genome_model.model_version,
                    "L1": self.molecular_model.model_version,
                    "L2": self.cell_model.model_version,
                    "L3": self.tissue_model.model_version,
                    "L4": self.phenotype_model.model_version,
                }.items()
            )
        )

    def run(
        self,
        scenario: MultiscaleScenario,
        *,
        ticks: int,
        perturbations: Mapping[str, Mapping[str, float]] | None = None,
        checkpoint: RunnerCheckpoint | None = None,
    ) -> MultirateRun:
        if not isinstance(scenario, MultiscaleScenario):
            raise TypeError("multirate runner requires a MultiscaleScenario")
        if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks < 1:
            raise ValueError("ticks must be a positive integer")
        if len(scenario.genomes) > self.config.max_cells:
            raise ValueError("scenario exceeds runner max_cells budget")

        normalized_perturbations = {
            str(cell_id): {
                str(gene): float(value) for gene, value in values.items()
            }
            for cell_id, values in (perturbations or {}).items()
        }
        known_cell_ids = {cell_id for cell_id, _ in scenario.genomes}
        unknown_cell_ids = set(normalized_perturbations) - known_cell_ids
        if unknown_cell_ids:
            raise ValueError(
                f"perturbations target unknown cells: {sorted(unknown_cell_ids)}"
            )
        manifest = ExperimentManifest.create(
            experiment_name="multirate-reference-run",
            seed=scenario.seed,
            code_version=__version__,
            config={
                "scenario": scenario,
                "perturbations": normalized_perturbations,
                "runner": self.config,
            },
            model_versions=dict(self.model_versions),
        )

        if checkpoint is None:
            start_tick = 1
            previous_l0: tuple[TranscriptState, ...] | None = None
            previous_l1: tuple[MolecularState, ...] | None = None
            previous_l2: tuple[CellState, ...] | None = None
            previous_l3: TissueState | None = None
            l4_observations: list[OrganismState] = []
            history_digest = digest_payload(
                {"phase": "initial", "manifest": manifest.as_dict()}
            )
        else:
            self._validate_checkpoint(checkpoint, manifest)
            start_tick = checkpoint.logical_time + 1
            previous_l0 = checkpoint.l0
            previous_l1 = checkpoint.l1
            previous_l2 = checkpoint.l2
            previous_l3 = checkpoint.l3
            l4_observations = list(checkpoint.l4_observations)
            history_digest = checkpoint.history_digest

        end_tick = start_tick + ticks - 1
        if end_tick > self.config.max_total_ticks:
            raise ValueError("run exceeds runner max_total_ticks budget")

        traces: list[MultiscaleTickTrace] = []
        genomes = tuple(sorted(scenario.genomes, key=lambda item: item[0]))
        regulatory_input = RegulatoryInput(
            damage_signal=scenario.environment_stress
        )

        for logical_time in range(start_tick, end_tick + 1):
            l0_updated = (logical_time - 1) % self.config.l0_interval == 0
            if l0_updated:
                previous_l0_by_id = {
                    state.cell_id: state for state in previous_l0 or ()
                }
                l0_results = tuple(
                    self.genome_model.step(
                        cell_id=cell_id,
                        genome=genome,
                        previous_state=previous_l0_by_id.get(cell_id),
                        regulatory_input=regulatory_input,
                        perturbations=normalized_perturbations.get(cell_id, {}),
                        logical_time=logical_time,
                    )
                    for cell_id, genome in genomes
                )
                l0 = tuple(result.state for result in l0_results)
                l0_events = tuple(
                    event
                    for result in l0_results
                    for event in result.perturbation_events
                )
            else:
                if previous_l0 is None:
                    raise RuntimeError("L0 cannot be held before initialization")
                l0 = previous_l0
                l0_events = ()

            previous_l2_by_id = {
                state.cell_id: state for state in previous_l2 or ()
            }
            l1_inputs = tuple(
                MolecularInput(
                    metadata=_metadata(
                        logical_time=logical_time,
                        model_version="l2-to-l1-activation-boundary-0.2",
                        source={
                            "cell_id": transcript.cell_id,
                            "previous_cell": previous_l2_by_id.get(
                                transcript.cell_id
                            ),
                        },
                    ),
                    cell_id=transcript.cell_id,
                    local_signal=(
                        previous_l2_by_id[transcript.cell_id].activation
                        if transcript.cell_id in previous_l2_by_id
                        else 0.0
                    ),
                )
                for transcript in l0
            )
            previous_l1_by_id = {
                state.cell_id: state for state in previous_l1 or ()
            }
            l1 = tuple(
                self.molecular_model.step(
                    transcript,
                    previous_state=previous_l1_by_id.get(transcript.cell_id),
                    molecular_input=molecular_input,
                    logical_time=logical_time,
                )
                for transcript, molecular_input in zip(
                    l0, l1_inputs, strict=True
                )
            )

            if previous_l3 is None:
                environments = tuple(
                    LocalEnvironment(
                        metadata=_metadata(
                            logical_time=logical_time,
                            model_version="scenario-boundary-0.1",
                            source={
                                "cell_id": state.cell_id,
                                "environment_stress": scenario.environment_stress,
                                "resource_level": scenario.resource_level,
                                "incoming_signal": scenario.incoming_signal,
                            },
                        ),
                        cell_id=state.cell_id,
                        stress=scenario.environment_stress,
                        resource_level=scenario.resource_level,
                        incoming_signal=scenario.incoming_signal,
                    )
                    for state in l1
                )
            else:
                environments = environments_from_tissue(
                    previous_l3, logical_time=logical_time
                )

            l2_pairs = tuple(
                self.cell_model.step(
                    molecular,
                    environment,
                    previous_state=previous_l2_by_id.get(molecular.cell_id),
                    logical_time=logical_time,
                )
                for molecular, environment in zip(
                    l1, environments, strict=True
                )
            )
            l2 = tuple(pair[0] for pair in l2_pairs)
            l2_actions = tuple(pair[1] for pair in l2_pairs)
            l3 = self.tissue_model.step(
                l2,
                l2_actions,
                initial_environments=(
                    environments if previous_l3 is None else None
                ),
                previous_state=previous_l3,
                edges=scenario.edges,
                logical_time=logical_time,
            )

            l4_observed = (logical_time - 1) % self.config.l4_interval == 0
            l4 = (
                self.phenotype_model.step(l3, logical_time=logical_time)
                if l4_observed
                else None
            )
            if l4 is not None:
                l4_observations.append(l4)

            transitions = self._transitions(
                logical_time=logical_time,
                l0_updated=l0_updated,
                l0=l0,
                previous_l1=previous_l1,
                l1_inputs=l1_inputs,
                l1=l1,
                environments=environments,
                previous_l2=previous_l2,
                l2=l2,
                l2_actions=l2_actions,
                previous_l3=previous_l3,
                l3=l3,
                edges=scenario.edges,
                l4=l4,
            )
            event_count = len(transitions) + len(l0_events)
            if event_count > self.config.max_events_per_tick:
                raise ValueError("tick exceeds runner max_events_per_tick budget")
            trace = MultiscaleTickTrace(
                logical_time=logical_time,
                l0_updated=l0_updated,
                l4_observed=l4_observed,
                l0=l0,
                l0_perturbation_events=l0_events,
                l1_inputs=l1_inputs,
                l1=l1,
                l2_environments=environments,
                l2=l2,
                l2_actions=l2_actions,
                l3=l3,
                l4=l4,
                transitions=transitions,
                event_count=event_count,
            )
            history_digest = digest_payload(
                {"previous": history_digest, "tick": trace}
            )
            traces.append(trace)
            previous_l0 = l0
            previous_l1 = l1
            previous_l2 = l2
            previous_l3 = l3

        if (
            previous_l0 is None
            or previous_l1 is None
            or previous_l2 is None
            or previous_l3 is None
        ):
            raise RuntimeError("multirate run ended without complete layer state")
        checkpoint_result = RunnerCheckpoint(
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            experiment_id=manifest.experiment_id,
            logical_time=end_tick,
            model_versions=self.model_versions,
            l0=previous_l0,
            l1=previous_l1,
            l2=previous_l2,
            l3=previous_l3,
            l4_observations=tuple(l4_observations),
            history_digest=history_digest,
        )
        if l4_observations[-1].metadata.logical_time == end_tick:
            terminal_observation = l4_observations[-1]
            window_states = tuple(l4_observations)
        else:
            terminal_observation = self.phenotype_model.step(
                previous_l3, logical_time=end_tick
            )
            window_states = (*l4_observations, terminal_observation)
        phenotype_window = self.phenotype_model.summarize(window_states)
        return MultirateRun(
            manifest=manifest,
            start_tick=start_tick,
            end_tick=end_tick,
            ticks=tuple(traces),
            checkpoint=checkpoint_result,
            terminal_observation=terminal_observation,
            phenotype_window=phenotype_window,
            history_digest=history_digest,
        )

    def _validate_checkpoint(
        self, checkpoint: RunnerCheckpoint, manifest: ExperimentManifest
    ) -> None:
        if not isinstance(checkpoint, RunnerCheckpoint):
            raise TypeError("checkpoint must be a RunnerCheckpoint")
        if checkpoint.experiment_id != manifest.experiment_id:
            raise ValueError("checkpoint belongs to a different experiment")
        if checkpoint.model_versions != self.model_versions:
            raise ValueError("checkpoint model versions do not match this runner")

    def _transitions(
        self,
        *,
        logical_time: int,
        l0_updated: bool,
        l0: tuple[TranscriptState, ...],
        previous_l1: tuple[MolecularState, ...] | None,
        l1_inputs: tuple[MolecularInput, ...],
        l1: tuple[MolecularState, ...],
        environments: tuple[LocalEnvironment, ...],
        previous_l2: tuple[CellState, ...] | None,
        l2: tuple[CellState, ...],
        l2_actions: tuple[CellAction, ...],
        previous_l3: TissueState | None,
        l3: TissueState,
        edges: tuple[tuple[str, str], ...],
        l4: OrganismState | None,
    ) -> tuple[LayerTransitionEvent, ...]:
        events = [
            self._transition(
                LayerId.L0,
                LayerId.L1,
                {
                    "transcript_states": l0,
                    "l0_updated": l0_updated,
                    "previous_molecular_states": previous_l1,
                    "molecular_inputs": l1_inputs,
                },
                l1,
                self.molecular_model.model_version,
                "current transcript state advanced molecular dynamics",
                "fast-tick",
                logical_time,
            ),
            self._transition(
                LayerId.L1,
                LayerId.L2,
                {
                    "molecular_states": l1,
                    "local_environments": environments,
                    "previous_cell_states": previous_l2,
                },
                {"states": l2, "actions": l2_actions},
                self.cell_model.model_version,
                "molecular state and local environment advanced Cell state",
                "fast-tick",
                logical_time,
            ),
            self._transition(
                LayerId.L2,
                LayerId.L3,
                {
                    "cell_states": l2,
                    "cell_actions": l2_actions,
                    "initial_environments": (
                        environments if previous_l3 is None else None
                    ),
                    "previous_state": previous_l3,
                    "edges": edges,
                },
                l3,
                self.tissue_model.model_version,
                "Cell actions advanced tissue environment",
                "fast-tick",
                logical_time,
            ),
        ]
        if l4 is not None:
            events.append(
                self._transition(
                    LayerId.L3,
                    LayerId.L4,
                    l3,
                    l4,
                    self.phenotype_model.model_version,
                    "scheduled tissue observation produced organism phenotype",
                    "macro-window",
                    logical_time,
                )
            )
        return tuple(events)

    @staticmethod
    def _transition(
        source_layer: LayerId,
        target_layer: LayerId,
        source: Any,
        target: Any,
        model_version: str,
        reason: str,
        timescale: str,
        logical_time: int,
    ) -> LayerTransitionEvent:
        return LayerTransitionEvent(
            logical_time=logical_time,
            source_layer=source_layer,
            target_layer=target_layer,
            model_version=model_version,
            input_digest=digest_payload(source),
            output_digest=digest_payload(target),
            timescale=timescale,
            reason=reason,
        )


def _state_metadata_from(raw: Mapping[str, Any]) -> StateMetadata:
    return StateMetadata(
        logical_time=int(raw["logical_time"]),
        model_version=str(raw["model_version"]),
        source_digest=str(raw["source_digest"]),
    )


def _transcript_from(raw: Mapping[str, Any]) -> TranscriptState:
    return TranscriptState(
        metadata=_state_metadata_from(raw["metadata"]),
        cell_id=str(raw["cell_id"]),
        damage_response=float(raw["damage_response"]),
        signal_expression=float(raw["signal_expression"]),
        repair_expression=float(raw["repair_expression"]),
        metabolic_expression=float(raw["metabolic_expression"]),
        death_expression=float(raw["death_expression"]),
        negative_feedback_expression=float(raw["negative_feedback_expression"]),
    )


def _molecular_from(raw: Mapping[str, Any]) -> MolecularState:
    return MolecularState(
        metadata=_state_metadata_from(raw["metadata"]),
        cell_id=str(raw["cell_id"]),
        damage_receptor=float(raw["damage_receptor"]),
        signal_protein=float(raw["signal_protein"]),
        repair_protein=float(raw["repair_protein"]),
        metabolic_capacity=float(raw["metabolic_capacity"]),
        death_effector=float(raw["death_effector"]),
        feedback_inhibitor=float(raw["feedback_inhibitor"]),
    )


def _cell_from(raw: Mapping[str, Any]) -> CellState:
    return CellState(
        metadata=_state_metadata_from(raw["metadata"]),
        cell_id=str(raw["cell_id"]),
        phase=CellPhase(str(raw["phase"])),
        activation=float(raw["activation"]),
        viability=float(raw["viability"]),
        stress_load=float(raw["stress_load"]),
    )


def _tissue_node_from(raw: Mapping[str, Any]) -> TissueNodeState:
    return TissueNodeState(
        cell_id=str(raw["cell_id"]),
        stress=float(raw["stress"]),
        resource_level=float(raw["resource_level"]),
        signal=float(raw["signal"]),
    )


def _tissue_from(raw: Mapping[str, Any]) -> TissueState:
    return TissueState(
        metadata=_state_metadata_from(raw["metadata"]),
        cell_count=int(raw["cell_count"]),
        nodes=tuple(_tissue_node_from(item) for item in raw["nodes"]),
        edges=tuple(
            (str(source), str(target)) for source, target in raw["edges"]
        ),
        edge_density=float(raw["edge_density"]),
        mean_activation=float(raw["mean_activation"]),
        mean_viability=float(raw["mean_viability"]),
        mean_resource=float(raw["mean_resource"]),
        mean_signal=float(raw["mean_signal"]),
        dead_fraction=float(raw["dead_fraction"]),
        repair_activity=float(raw["repair_activity"]),
        coordinated_signal=float(raw["coordinated_signal"]),
        tissue_damage=float(raw["tissue_damage"]),
    )


def _organism_from(raw: Mapping[str, Any]) -> OrganismState:
    return OrganismState(
        metadata=_state_metadata_from(raw["metadata"]),
        vitality=float(raw["vitality"]),
        damage_burden=float(raw["damage_burden"]),
        inflammation=float(raw["inflammation"]),
        homeostasis=float(raw["homeostasis"]),
        recovery_capacity=float(raw["recovery_capacity"]),
    )


def load_checkpoint(path: str | Path) -> RunnerCheckpoint:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("checkpoint root must be an object")
        expected_fields = {
            "schema_version",
            "experiment_id",
            "logical_time",
            "model_versions",
            "l0",
            "l1",
            "l2",
            "l3",
            "l4_observations",
            "history_digest",
            "checkpoint_id",
        }
        if set(raw) != expected_fields:
            raise ValueError("checkpoint fields do not match its schema")
        checkpoint = RunnerCheckpoint(
            schema_version=str(raw["schema_version"]),
            experiment_id=str(raw["experiment_id"]),
            logical_time=int(raw["logical_time"]),
            model_versions=tuple(
                (str(name), str(version))
                for name, version in raw["model_versions"]
            ),
            l0=tuple(_transcript_from(item) for item in raw["l0"]),
            l1=tuple(_molecular_from(item) for item in raw["l1"]),
            l2=tuple(_cell_from(item) for item in raw["l2"]),
            l3=_tissue_from(raw["l3"]),
            l4_observations=tuple(
                _organism_from(item) for item in raw["l4_observations"]
            ),
            history_digest=str(raw["history_digest"]),
        )
        if checkpoint.checkpoint_id != str(raw["checkpoint_id"]):
            raise ValueError("checkpoint content digest does not match checkpoint_id")
        return checkpoint
    except (
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        raise ValueError(f"invalid runner checkpoint: {error}") from error


def _write_json_once(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("existing artifact is not valid JSON") from error
        if existing != payload:
            raise ValueError("refusing to overwrite a different artifact")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp")
    if temporary.exists():
        raise ValueError("temporary artifact path already exists")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def save_checkpoint(path: str | Path, checkpoint: RunnerCheckpoint) -> None:
    if not isinstance(checkpoint, RunnerCheckpoint):
        raise TypeError("save_checkpoint requires a RunnerCheckpoint")
    _write_json_once(path, checkpoint.as_dict())


def save_run_artifact(path: str | Path, run: MultirateRun) -> None:
    if not isinstance(run, MultirateRun):
        raise TypeError("save_run_artifact requires a MultirateRun")
    _write_json_once(path, run.as_dict())
