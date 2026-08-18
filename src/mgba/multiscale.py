from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .experiment import ExperimentManifest, LayerTransitionEvent, digest_payload
from .layers import (
    CellAction,
    CellModel,
    CellState,
    L0PerturbationEvent,
    GenomeModel,
    LayerId,
    LocalEnvironment,
    MolecularInput,
    MolecularModel,
    MolecularState,
    OrganismState,
    PhenotypeModel,
    RegulatoryInput,
    StateMetadata,
    TissueModel,
    TissueState,
    TranscriptState,
)
from .layers.l0 import StaticGenomeModel
from .layers.l1 import StaticMolecularModel
from .layers.l2 import StaticCellModel
from .layers.l3 import StaticTissueModel
from .layers.l4 import StaticPhenotypeModel
from .models import Genome


def _metadata(logical_time: int, model_version: str, source: Any) -> StateMetadata:
    return StateMetadata(
        logical_time=logical_time,
        model_version=model_version,
        source_digest=digest_payload(source),
    )


ReferenceGenomeModel = StaticGenomeModel
ReferenceMolecularModel = StaticMolecularModel
ReferenceCellModel = StaticCellModel
ReferenceTissueModel = StaticTissueModel
ReferencePhenotypeModel = StaticPhenotypeModel


@dataclass(frozen=True, slots=True)
class LayerTrace:
    l0: tuple[TranscriptState, ...]
    l0_perturbation_events: tuple[L0PerturbationEvent, ...]
    l1_inputs: tuple[MolecularInput, ...]
    l1: tuple[MolecularState, ...]
    l2_environments: tuple[LocalEnvironment, ...]
    l2: tuple[CellState, ...]
    l2_actions: tuple[CellAction, ...]
    l3: TissueState
    l4: OrganismState
    transitions: tuple[LayerTransitionEvent, ...]

    def __post_init__(self) -> None:
        if not self.l0 or not self.l1 or not self.l2:
            raise ValueError("L0, L1, and L2 states must all be present")
        layer_cell_ids = (
            tuple(state.cell_id for state in self.l0),
            tuple(molecular_input.cell_id for molecular_input in self.l1_inputs),
            tuple(state.cell_id for state in self.l1),
            tuple(environment.cell_id for environment in self.l2_environments),
            tuple(state.cell_id for state in self.l2),
            tuple(action.cell_id for action in self.l2_actions),
        )
        if any(ids != layer_cell_ids[0] for ids in layer_cell_ids[1:]):
            raise ValueError("cell identity must be preserved across L0, L1, and L2")
        expected = (
            (LayerId.L0, LayerId.L1),
            (LayerId.L1, LayerId.L2),
            (LayerId.L2, LayerId.L3),
            (LayerId.L3, LayerId.L4),
        )
        observed = tuple(
            (event.source_layer, event.target_layer) for event in self.transitions
        )
        if observed != expected:
            raise ValueError("trace must contain the complete adjacent L0-to-L4 path")

    def as_dict(self) -> dict[str, Any]:
        return {
            "L0_transcript": [asdict(state) for state in self.l0],
            "L0_perturbations": [
                asdict(event) for event in self.l0_perturbation_events
            ],
            "L1_molecular_input": [
                asdict(molecular_input) for molecular_input in self.l1_inputs
            ],
            "L1_molecular": [asdict(state) for state in self.l1],
            "L2_local_environment": [
                asdict(environment) for environment in self.l2_environments
            ],
            "L2_cell": [asdict(state) for state in self.l2],
            "L2_action": [asdict(action) for action in self.l2_actions],
            "L3_tissue": asdict(self.l3),
            "L4_organism": asdict(self.l4),
            "transitions": [event.as_dict() for event in self.transitions],
        }


@dataclass(frozen=True, slots=True)
class MultiscaleScenario:
    seed: int
    environment_stress: float
    resource_level: float
    incoming_signal: float
    genomes: tuple[tuple[str, Genome], ...]
    edges: tuple[tuple[str, str], ...]


class ReferenceCrossScaleRunner:
    """Five-layer contract demonstrator, not a validated biological model."""

    def __init__(
        self,
        *,
        genome_model: GenomeModel | None = None,
        molecular_model: MolecularModel | None = None,
        cell_model: CellModel | None = None,
        tissue_model: TissueModel | None = None,
        phenotype_model: PhenotypeModel | None = None,
    ) -> None:
        self.genome_model = genome_model or ReferenceGenomeModel()
        self.molecular_model = molecular_model or ReferenceMolecularModel()
        self.cell_model = cell_model or ReferenceCellModel()
        self.tissue_model = tissue_model or ReferenceTissueModel()
        self.phenotype_model = phenotype_model or ReferencePhenotypeModel()

    def run(
        self,
        scenario: MultiscaleScenario,
        perturbations: dict[str, dict[str, float]] | None = None,
    ) -> LayerTrace:
        logical_time = 1
        perturbations = perturbations or {}
        known_cell_ids = {cell_id for cell_id, _ in scenario.genomes}
        unknown_cell_ids = perturbations.keys() - known_cell_ids
        if unknown_cell_ids:
            raise ValueError(
                f"perturbations target unknown cells: {sorted(unknown_cell_ids)}"
            )
        regulatory_input = RegulatoryInput(
            damage_signal=scenario.environment_stress
        )
        l0_steps = tuple(
            sorted(
                (
                    self.genome_model.step(
                        cell_id=cell_id,
                        genome=genome,
                        previous_state=None,
                        regulatory_input=regulatory_input,
                        perturbations=perturbations.get(cell_id, {}),
                        logical_time=logical_time,
                    )
                    for cell_id, genome in scenario.genomes
                ),
                key=lambda result: result.state.cell_id,
            )
        )
        l0 = tuple(result.state for result in l0_steps)
        l0_perturbation_events = tuple(
            event
            for result in l0_steps
            for event in result.perturbation_events
        )
        l1_inputs = tuple(
            MolecularInput(
                metadata=_metadata(
                    logical_time,
                    "l2-to-l1-feedback-disabled-0.1",
                    {"cell_id": state.cell_id, "local_signal": 0.0},
                ),
                cell_id=state.cell_id,
                local_signal=0.0,
            )
            for state in l0
        )
        l1 = tuple(
            self.molecular_model.step(
                state,
                previous_state=None,
                molecular_input=molecular_input,
                logical_time=logical_time,
            )
            for state, molecular_input in zip(l0, l1_inputs, strict=True)
        )
        environments = tuple(
            LocalEnvironment(
                metadata=_metadata(
                    logical_time,
                    "scenario-boundary-0.1",
                    {
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
        l2_pairs = tuple(
            self.cell_model.step(
                state,
                environment,
                previous_state=None,
                logical_time=logical_time,
            )
            for state, environment in zip(l1, environments, strict=True)
        )
        l2 = tuple(pair[0] for pair in l2_pairs)
        l2_actions = tuple(pair[1] for pair in l2_pairs)
        l3 = self.tissue_model.step(
            l2,
            l2_actions,
            initial_environments=environments,
            previous_state=None,
            edges=scenario.edges,
            logical_time=logical_time,
        )
        l4 = self.phenotype_model.step(l3, logical_time=logical_time)
        transitions = (
            self._transition(
                LayerId.L0,
                LayerId.L1,
                {
                    "transcript_states": l0,
                    "previous_molecular_states": None,
                    "molecular_inputs": l1_inputs,
                },
                l1,
                self.molecular_model.model_version,
                "transcript state translated into molecular capability",
                logical_time,
            ),
            self._transition(
                LayerId.L1,
                LayerId.L2,
                {"molecular_states": l1, "local_environments": environments},
                {"states": l2, "actions": l2_actions},
                self.cell_model.model_version,
                "molecular state and local environment produced cell response",
                logical_time,
            ),
            self._transition(
                LayerId.L2,
                LayerId.L3,
                {
                    "cell_states": l2,
                    "cell_actions": l2_actions,
                    "initial_environments": environments,
                    "previous_state": None,
                    "edges": scenario.edges,
                },
                l3,
                self.tissue_model.model_version,
                "cell actions aggregated into tissue state",
                logical_time,
            ),
            self._transition(
                LayerId.L3,
                LayerId.L4,
                l3,
                l4,
                self.phenotype_model.model_version,
                "tissue state aggregated into organism phenotype",
                logical_time,
            ),
        )
        return LayerTrace(
            l0=l0,
            l0_perturbation_events=l0_perturbation_events,
            l1_inputs=l1_inputs,
            l1=l1,
            l2_environments=environments,
            l2=l2,
            l2_actions=l2_actions,
            l3=l3,
            l4=l4,
            transitions=transitions,
        )

    @staticmethod
    def _transition(
        source_layer: LayerId,
        target_layer: LayerId,
        source: Any,
        target: Any,
        model_version: str,
        reason: str,
        logical_time: int,
    ) -> LayerTransitionEvent:
        return LayerTransitionEvent(
            logical_time=logical_time,
            source_layer=source_layer,
            target_layer=target_layer,
            model_version=model_version,
            input_digest=digest_payload(source),
            output_digest=digest_payload(target),
            timescale="contract-step",
            reason=reason,
        )


def load_multiscale_scenario(path: str | Path) -> MultiscaleScenario:
    raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    stress = float(raw["environment_stress"])
    if not 0.0 <= stress <= 1.0:
        raise ValueError("environment_stress must be in [0, 1]")
    resource_level = float(raw["resource_level"])
    incoming_signal = float(raw["incoming_signal"])
    if not 0.0 <= resource_level <= 1.0:
        raise ValueError("resource_level must be in [0, 1]")
    if not 0.0 <= incoming_signal <= 1.0:
        raise ValueError("incoming_signal must be in [0, 1]")
    genomes = tuple((item["id"], Genome(**item["genome"])) for item in raw["agents"])
    ids = [cell_id for cell_id, _ in genomes]
    if len(ids) != len(set(ids)):
        raise ValueError("cell ids must be unique")
    return MultiscaleScenario(
        seed=int(raw["seed"]),
        environment_stress=stress,
        resource_level=resource_level,
        incoming_signal=incoming_signal,
        genomes=genomes,
        edges=tuple(tuple(edge) for edge in raw["edges"]),
    )


def summarize_trace(
    scenario: MultiscaleScenario,
    trace: LayerTrace,
    perturbations: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    layers = trace.as_dict()
    manifest = ExperimentManifest.create(
        experiment_name="multiscale-contract-demo",
        seed=scenario.seed,
        code_version=__version__,
        config={"scenario": scenario, "perturbations": perturbations or {}},
        model_versions={
            "L0": trace.l0[0].metadata.model_version,
            "L1": trace.l1[0].metadata.model_version,
            "L2": trace.l2[0].metadata.model_version,
            "L3": trace.l3.metadata.model_version,
            "L4": trace.l4.metadata.model_version,
        },
    )
    return {
        "model_status": "contract-demonstrator-not-biological-model",
        "seed": scenario.seed,
        "experiment": manifest.as_dict(),
        "layer_path": [layer.value for layer in LayerId],
        "trace_digest": digest_payload(layers),
        "layers": layers,
    }
