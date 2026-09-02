from __future__ import annotations

import json
from dataclasses import dataclass, fields
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from . import __version__
from .experiment import ExperimentManifest, LayerTransitionEvent, write_json_once
from .hashing import jsonable, canonical_json, digest_payload
from .layers import (
    CellAction,
    CellAgent,
    CellModel,
    CellPhase,
    CellState,
    FeedbackConstraint,
    FeedbackPolicy,
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
    SpatialCoordinate,
    SpatialFieldCell,
    SpatialTissueState,
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
        result = {
            field.name: jsonable(getattr(self, field.name))
            for field in fields(self)
            if field.name != "transitions"
        }
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
        # Serialize once: the canonical string feeds both the JSON body and
        # the checkpoint identity digest.
        encoded = canonical_json(self)
        result = json.loads(encoded)
        result["checkpoint_id"] = (
            f"checkpoint-{sha256(encoded.encode('utf-8')).hexdigest()[:16]}"
        )
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
        feedback_policy: FeedbackPolicy | None = None,
    ) -> None:
        self.config = config
        self.genome_model = genome_model
        self.molecular_model = molecular_model
        self.cell_model = cell_model
        self.tissue_model = tissue_model
        self.phenotype_model = phenotype_model
        if feedback_policy is not None and (
            not callable(getattr(feedback_policy, "observe", None))
            or not callable(getattr(feedback_policy, "reset", None))
        ):
            raise TypeError(
                "feedback_policy must implement the FeedbackPolicy protocol"
            )
        self.feedback_policy = feedback_policy
        # Model version strings are pure functions of frozen configs; snapshot
        # them once instead of re-serializing and re-hashing every tick.
        self._model_version = (
            f"{config.model_version}+{digest_payload(config)[:12]}"
        )
        self._layer_versions = {
            "L0": genome_model.model_version,
            "L1": molecular_model.model_version,
            "L2": cell_model.model_version,
            "L3": tissue_model.model_version,
            "L4": phenotype_model.model_version,
        }

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def model_versions(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted({"runner": self._model_version, **self._layer_versions}.items())
        )

    def run(
        self,
        scenario: MultiscaleScenario,
        *,
        ticks: int,
        perturbations: Mapping[str, Mapping[str, float]] | None = None,
        perturbation_schedule: Mapping[
            int, Mapping[str, Mapping[str, float]]
        ]
        | None = None,
        checkpoint: RunnerCheckpoint | None = None,
    ) -> MultirateRun:
        """Advance the scenario with one explicit CellAgent per cell.

        Each agent owns its cell identity, genome, and current L0/L1/L2
        states and decides through the CellModel policy boundary; the runner
        remains responsible for advancing L0/L1 layer services and the
        tissue-level L3/L4 state. The agents are object-form carriers of the
        per-cell previous-state bookkeeping this method used before the
        agent-centric refactor: every model call receives exactly the same
        argument values as before, so traces, history digests, checkpoints,
        and experiment matrices are bit-identical to the pre-refactor runner.
        """
        if not isinstance(scenario, MultiscaleScenario):
            raise TypeError("multirate runner requires a MultiscaleScenario")
        if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks < 1:
            raise ValueError("ticks must be a positive integer")
        if len(scenario.genomes) > self.config.max_cells:
            raise ValueError("scenario exceeds runner max_cells budget")
        if perturbations and perturbation_schedule:
            raise ValueError(
                "constant perturbations and a perturbation schedule are mutually exclusive"
            )

        normalized_perturbations = {
            str(cell_id): {
                str(gene): float(value) for gene, value in values.items()
            }
            for cell_id, values in (perturbations or {}).items()
        }
        normalized_schedule: dict[int, dict[str, dict[str, float]]] = {}
        for logical_time, cell_values in (perturbation_schedule or {}).items():
            if (
                isinstance(logical_time, bool)
                or not isinstance(logical_time, int)
                or logical_time < 1
                or logical_time > self.config.max_total_ticks
            ):
                raise ValueError(
                    "perturbation schedule ticks must be positive integers within the runner budget"
                )
            if (logical_time - 1) % self.config.l0_interval != 0:
                raise ValueError(
                    "perturbation schedule ticks must align with the L0 update clock"
                )
            normalized_schedule[logical_time] = {
                str(cell_id): {
                    str(gene): float(value) for gene, value in values.items()
                }
                for cell_id, values in cell_values.items()
            }
        known_cell_ids = {cell_id for cell_id, _ in scenario.genomes}
        unknown_cell_ids = (
            set(normalized_perturbations).union(
                cell_id
                for cell_values in normalized_schedule.values()
                for cell_id in cell_values
            )
            - known_cell_ids
        )
        if unknown_cell_ids:
            raise ValueError(
                f"perturbations target unknown cells: {sorted(unknown_cell_ids)}"
            )
        manifest_config: dict[str, Any] = {
            "scenario": scenario,
            "perturbations": normalized_perturbations,
            "runner": self.config,
        }
        if normalized_schedule:
            manifest_config["perturbation_schedule"] = normalized_schedule
        if self.feedback_policy is not None:
            manifest_config["feedback"] = self.feedback_policy.model_version
        manifest = ExperimentManifest.create(
            experiment_name="multirate-reference-run",
            seed=scenario.seed,
            code_version=__version__,
            config=manifest_config,
            model_versions=dict(self.model_versions),
        )

        sorted_genomes = tuple(sorted(scenario.genomes, key=lambda item: item[0]))
        agents = tuple(
            CellAgent(cell_id, genome, self.cell_model)
            for cell_id, genome in sorted_genomes
        )

        active_constraint: FeedbackConstraint | None = None
        if self.feedback_policy is not None:
            self.feedback_policy.reset()
        if checkpoint is None:
            start_tick = 1
            previous_l3: TissueState | None = None
            l4_observations: list[OrganismState] = []
            history_digest = digest_payload(
                {"phase": "initial", "manifest": manifest.as_dict()}
            )
        else:
            self._validate_checkpoint(checkpoint, manifest)
            start_tick = checkpoint.logical_time + 1
            for agent, l0_state, l1_state, l2_state in zip(
                agents, checkpoint.l0, checkpoint.l1, checkpoint.l2, strict=True
            ):
                if not (
                    agent.cell_id
                    == l0_state.cell_id
                    == l1_state.cell_id
                    == l2_state.cell_id
                ):
                    raise ValueError(
                        "checkpoint cell identities do not match scenario"
                    )
                agent.advance_l0(l0_state)
                agent.advance_l1(l1_state)
                agent.advance_l2(l2_state)
            previous_l3 = checkpoint.l3
            l4_observations = list(checkpoint.l4_observations)
            history_digest = checkpoint.history_digest
            if self.feedback_policy is not None:
                for observation in checkpoint.l4_observations:
                    active_constraint = self.feedback_policy.observe(
                        observation,
                        logical_time=observation.metadata.logical_time,
                    )

        end_tick = start_tick + ticks - 1
        if end_tick > self.config.max_total_ticks:
            raise ValueError("run exceeds runner max_total_ticks budget")

        traces: list[MultiscaleTickTrace] = []
        regulatory_input = RegulatoryInput(
            damage_signal=scenario.environment_stress
        )

        for logical_time in range(start_tick, end_tick + 1):
            previous_l1 = (
                tuple(agent.l1 for agent in agents)
                if agents and agents[0].l1 is not None
                else None
            )
            previous_l2 = (
                tuple(agent.l2 for agent in agents)
                if agents and agents[0].l2 is not None
                else None
            )
            l0_updated = (logical_time - 1) % self.config.l0_interval == 0
            if l0_updated:
                tick_perturbations = (
                    normalized_schedule.get(logical_time, {})
                    if normalized_schedule
                    else normalized_perturbations
                )
                l0_results = tuple(
                    self.genome_model.step(
                        cell_id=agent.cell_id,
                        genome=agent.genome,
                        previous_state=agent.l0,
                        regulatory_input=regulatory_input,
                        perturbations=tick_perturbations.get(
                            agent.cell_id, {}
                        ),
                        logical_time=logical_time,
                    )
                    for agent in agents
                )
                for agent, result in zip(agents, l0_results, strict=True):
                    agent.advance_l0(result.state)
                l0 = tuple(agent.l0 for agent in agents)
                l0_events = tuple(
                    event
                    for result in l0_results
                    for event in result.perturbation_events
                )
            else:
                if agents[0].l0 is None:
                    raise RuntimeError("L0 cannot be held before initialization")
                l0 = tuple(agent.l0 for agent in agents)
                l0_events = ()

            l1_inputs = tuple(
                MolecularInput(
                    metadata=_metadata(
                        logical_time=logical_time,
                        model_version="l2-to-l1-activation-boundary-0.2",
                        source={
                            "cell_id": agent.cell_id,
                            "previous_cell": agent.l2,
                        },
                    ),
                    cell_id=agent.cell_id,
                    local_signal=(
                        agent.l2.activation if agent.l2 is not None else 0.0
                    ),
                )
                for agent in agents
            )
            for agent, molecular_input in zip(agents, l1_inputs, strict=True):
                agent.advance_l1(
                    self.molecular_model.step(
                        agent.l0,
                        previous_state=agent.l1,
                        molecular_input=molecular_input,
                        logical_time=logical_time,
                    )
                )
            l1 = tuple(agent.l1 for agent in agents)

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
                agent.decide(molecular, environment, logical_time=logical_time)
                for agent, molecular, environment in zip(
                    agents, l1, environments, strict=True
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
                constraint=active_constraint,
            )

            l4_observed = (logical_time - 1) % self.config.l4_interval == 0
            l4 = (
                self.phenotype_model.step(l3, logical_time=logical_time)
                if l4_observed
                else None
            )
            if l4 is not None:
                l4_observations.append(l4)
                if self.feedback_policy is not None:
                    active_constraint = self.feedback_policy.observe(
                        l4, logical_time=logical_time
                    )

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
            previous_l3 = l3

        if previous_l3 is None or any(
            agent.l0 is None or agent.l1 is None or agent.l2 is None
            for agent in agents
        ):
            raise RuntimeError("multirate run ended without complete layer state")
        checkpoint_result = RunnerCheckpoint(
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            experiment_id=manifest.experiment_id,
            logical_time=end_tick,
            model_versions=self.model_versions,
            l0=tuple(agent.l0 for agent in agents),
            l1=tuple(agent.l1 for agent in agents),
            l2=tuple(agent.l2 for agent in agents),
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
                self._layer_versions["L1"],
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
                self._layer_versions["L2"],
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
                self._layer_versions["L3"],
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
                    self._layer_versions["L4"],
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


def _spatial_coordinate_from(raw: Mapping[str, Any]) -> SpatialCoordinate:
    return SpatialCoordinate(
        cell_id=str(raw["cell_id"]),
        x=float(raw["x"]),
        y=float(raw["y"]),
    )


def _spatial_field_cell_from(raw: Mapping[str, Any]) -> SpatialFieldCell:
    return SpatialFieldCell(
        row=int(raw["row"]),
        column=int(raw["column"]),
        stress=float(raw["stress"]),
        resource_level=float(raw["resource_level"]),
        signal=float(raw["signal"]),
    )


def _tissue_from(raw: Mapping[str, Any]) -> TissueState:
    common: dict[str, Any] = dict(
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
    spatial_fields = {
        "coordinates",
        "field_rows",
        "field_columns",
        "field_cells",
    }
    present_spatial_fields = spatial_fields.intersection(raw)
    if not present_spatial_fields:
        return TissueState(**common)
    if present_spatial_fields != spatial_fields:
        raise ValueError("checkpoint has an incomplete spatial L3 state")
    return SpatialTissueState(
        **common,
        coordinates=tuple(
            _spatial_coordinate_from(item) for item in raw["coordinates"]
        ),
        field_rows=int(raw["field_rows"]),
        field_columns=int(raw["field_columns"]),
        field_cells=tuple(
            _spatial_field_cell_from(item) for item in raw["field_cells"]
        ),
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




def save_checkpoint(path: str | Path, checkpoint: RunnerCheckpoint) -> None:
    if not isinstance(checkpoint, RunnerCheckpoint):
        raise TypeError("save_checkpoint requires a RunnerCheckpoint")
    write_json_once(path, checkpoint.as_dict())


def save_run_artifact(path: str | Path, run: MultirateRun) -> None:
    if not isinstance(run, MultirateRun):
        raise TypeError("save_run_artifact requires a MultirateRun")
    write_json_once(path, run.as_dict())
