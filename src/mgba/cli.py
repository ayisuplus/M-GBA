from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from .data_registry import (
    REGISTRY_SCHEMA_VERSION,
    load_data_registry,
    validate_data_registry,
)
from .feedback import load_feedback_config
from .feedback_experiments import (
    FeedbackExperimentRunner,
    build_feedback_runners,
    load_feedback_experiment_config,
    save_feedback_artifacts,
)
from .policy_experiments import (
    PolicyExperimentRunner,
    load_policy_experiment_config,
    save_policy_artifacts,
)
from .latent_experiments import (
    LatentExperimentRunner,
    load_latent_experiment_config,
    save_latent_artifacts,
)
from .layers.l2_active_inference import (
    ActiveInferenceCellModel,
    load_active_inference_config,
)
from .layers.l2_latent import LatentCellModel, load_latent_cell_config
from .autolab import (
    AutolabSession,
    EvaluatorResult,
    load_autolab_config,
    load_proposal_file,
    save_autolab_artifacts,
    validate_proposals,
)
from .layers.l3_adaptive import (
    DynamicTopologyTissueModel,
    load_adaptive_topology_config,
)
from .topology_experiments import (
    TopologyExperimentRunner,
    load_topology_experiment_config,
    save_topology_artifacts,
)
from .layers.l0_noisy import NoisyDiscreteGrnModel, load_noisy_grn_config
from .e3_experiments import (
    E3ExperimentRunner,
    load_e3_experiment_config,
    save_e3_artifacts,
)
from .closed_loop_experiments import (
    ClosedLoopExperimentRunner,
    load_closed_loop_config,
    save_closed_loop_artifacts,
)
from .layers.l0_neural import NeuralGrnModel, load_neural_grn_config
from .layers.l3_gnn import GnnTissueModel, load_gnn_tissue_config
from .neural_experiments import (
    NeuralComparisonRunner,
    load_neural_comparison_config,
    save_neural_artifacts,
)
from .demo import export_carm_demo
from .carm_spatial_experiments import (
    CarmSpatialExperimentRunner,
    build_carm_spatial_runners,
    load_carm_spatial_experiment_config,
    save_carm_spatial_artifacts,
)
from .carm_spatial_ablation import (
    CarmSpatialAblationRunner,
    build_carm_spatial_ablation_runners,
    load_carm_spatial_ablation_config,
    save_carm_spatial_ablation_artifacts,
)
from .spatial_anchors import (
    build_spatial_anchor_profile,
    load_spatial_anchor_protocol,
    load_spatial_observation_bundle,
    save_spatial_anchor_profile,
    verify_spatial_anchor_target,
)
from .spatial_source_adapters import (
    adapt_jackson_imc_source,
    adapt_wu_visium_source,
)
from .intervention_experiments import (
    StateConditionedInterventionRunner,
    build_carm_intervention_runner,
    load_state_conditioned_intervention_config,
    save_state_conditioned_intervention_artifacts,
)
from .spatial_anchor_evaluation import (
    SpatialAnchorEvaluator,
    load_spatial_anchor_evaluation_config,
    save_spatial_anchor_evaluation_artifacts,
)
from .experiments import (
    CausalExperimentRunner,
    CausalRunRecord,
    ConditionKind,
    _compare_runs,
    load_causal_config,
    save_causal_artifacts,
)
from .layers.l0 import DiscreteGrnModel, load_grn_config
from .layers.l1 import (
    CoarseMolecularModel,
    StaticMolecularModel,
    load_molecular_config,
)
from .layers.l2 import CellStateMachineModel, StaticCellModel, load_cell_config
from .layers.l3 import (
    StaticTissueModel,
    TissueEnvironmentModel,
    load_tissue_config,
)
from .layers.l4 import PhenotypeObserverModel, load_phenotype_config
from .multiscale import (
    ReferenceCrossScaleRunner,
    load_multiscale_scenario,
    summarize_trace,
)
from .reporting import build_causal_report
from .run_report import build_run_report
from .runner import (
    MultirateCrossScaleRunner,
    load_checkpoint,
    load_runner_config,
    save_checkpoint,
    save_run_artifact,
)
from .scenarios.carm import (
    CARM_MODEL_STATUS,
    build_carm_profile,
    build_carm_runners,
    compile_carm_scenario,
    load_carm_spatial_config,
    load_carm_scenario_config,
    run_carm_matrix,
    save_carm_artifacts,
    save_carm_profile,
)
from .simulation import load_scenario, run_scenario


def _add_layered_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--config", default="configs/multiscale_demo.json", help="multiscale scenario JSON"
    )
    command.add_argument(
        "--l0-config",
        default="configs/layers/l0_reference_grn.json",
        help="L0 discrete GRN JSON",
    )
    command.add_argument(
        "--l1-config",
        default="configs/layers/l1_reference_molecular.json",
        help="L1 coarse molecular model JSON",
    )
    command.add_argument(
        "--l2-config",
        default="configs/layers/l2_reference_cell.json",
        help="L2 Cell state machine JSON",
    )
    command.add_argument(
        "--l3-config",
        default="configs/layers/l3_reference_tissue.json",
        help="L3 tissue environment model JSON",
    )
    command.add_argument(
        "--l4-config",
        default="configs/layers/l4_reference_phenotype.json",
        help="L4 phenotype observer model JSON",
    )


def _load_layer_models(args: argparse.Namespace) -> dict[str, object]:
    return {
        "genome_model": DiscreteGrnModel(load_grn_config(args.l0_config)),
        "molecular_model": CoarseMolecularModel(
            load_molecular_config(args.l1_config)
        ),
        "cell_model": CellStateMachineModel(load_cell_config(args.l2_config)),
        "tissue_model": TissueEnvironmentModel(
            load_tissue_config(args.l3_config)
        ),
        "phenotype_model": PhenotypeObserverModel(
            load_phenotype_config(args.l4_config)
        ),
    }


def _load_multirate_runner(
    args: argparse.Namespace, *, variant: str = "baseline"
) -> MultirateCrossScaleRunner:
    models = _load_layer_models(args)
    if variant == "l1_static":
        models["molecular_model"] = StaticMolecularModel()
    elif variant == "l2_static":
        models["cell_model"] = StaticCellModel()
    elif variant == "l3_static":
        models["tissue_model"] = StaticTissueModel()
    elif variant != "baseline":
        raise ValueError(f"unknown multirate runner variant: {variant}")
    return MultirateCrossScaleRunner(
        load_runner_config(args.runner_config), **models
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an M-GBA reference scenario")
    commands = parser.add_subparsers(dest="command", required=True)

    layered = commands.add_parser("run", help="run the default L0-to-L4 contract trace")
    _add_layered_arguments(layered)

    simulate = commands.add_parser(
        "simulate", help="run or resume the multi-rate L0-to-L4 reference trajectory"
    )
    _add_layered_arguments(simulate)
    simulate.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    simulate.add_argument(
        "--ticks", type=int, default=100, help="number of additional ticks to run"
    )
    simulate.add_argument(
        "--checkpoint-in", help="resume from a runner checkpoint JSON"
    )
    simulate.add_argument(
        "--checkpoint-out", help="write the final runner checkpoint JSON"
    )
    simulate.add_argument(
        "--trace-out", help="write the complete trace artifact JSON"
    )

    experiment = commands.add_parser(
        "experiment", help="run the frozen WP8 perturbation and ablation matrix"
    )
    _add_layered_arguments(experiment)
    experiment.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    experiment.add_argument(
        "--matrix-config",
        default="configs/experiments/wp8_reference.json",
        help="WP8 causal matrix JSON",
    )
    experiment.add_argument(
        "--artifact-root",
        help="optional root for the complete raw and derived matrix artifacts",
    )

    report = commands.add_parser(
        "report", help="rebuild the WP9 report from a saved WP8 causal matrix"
    )
    report.add_argument(
        "--matrix-root", required=True, help="saved causal matrix artifact directory"
    )
    report.add_argument(
        "--output-dir", help="optional report directory; defaults inside the matrix"
    )

    run_report = commands.add_parser(
        "run-report",
        help="rebuild per-tick L0-to-L4 trajectory charts from a saved run artifact",
    )
    run_report.add_argument(
        "--run",
        required=True,
        help="run artifact JSON from simulate --trace-out or a matrix raw run",
    )
    run_report.add_argument(
        "--output-dir",
        help="optional report directory; defaults to <run-stem>-report beside the run file",
    )

    carm_import = commands.add_parser(
        "carm-import",
        help="build a de-identified CAR-M cohort profile from legacy JSON",
    )
    carm_import.add_argument(
        "--legacy-root",
        required=True,
        help="legacy CAR-M project root or its app/public/data/tcga directory",
    )
    carm_import.add_argument(
        "--output", required=True, help="output aggregate cohort profile JSON"
    )

    carm_experiment = commands.add_parser(
        "carm-experiment",
        help="run the frozen TCGA-proxy-anchored CAR-M vertical slice",
    )
    carm_experiment.add_argument(
        "--config",
        default="configs/scenarios/carm/high_immune_her2.json",
        help="CAR-M scenario JSON",
    )
    carm_experiment.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    carm_experiment.add_argument(
        "--matrix-config",
        default="configs/experiments/carm_vertical_slice.json",
        help="CAR-M causal matrix JSON",
    )
    carm_experiment.add_argument(
        "--l0-config",
        default="configs/layers/l0_reference_grn.json",
        help="L0 discrete GRN JSON",
    )
    carm_experiment.add_argument(
        "--l1-config",
        default="configs/layers/l1_reference_molecular.json",
        help="L1 coarse molecular model JSON",
    )
    carm_experiment.add_argument(
        "--l4-config",
        default="configs/layers/l4_reference_phenotype.json",
        help="L4 phenotype observer JSON",
    )
    carm_experiment.add_argument(
        "--artifact-root",
        help="optional root for raw runs, provenance, summary, and report",
    )

    carm_spatial = commands.add_parser(
        "carm-spatial-experiment",
        help="compare the fixed CAR-M graph with the causal spatial L3 reference model",
    )
    carm_spatial.add_argument(
        "--config",
        default="configs/scenarios/carm/high_immune_her2.json",
        help="CAR-M scenario JSON",
    )
    carm_spatial.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    carm_spatial.add_argument(
        "--matrix-config",
        default="configs/experiments/carm_spatial_comparison.json",
        help="fixed-graph versus spatial L3 comparison JSON",
    )
    carm_spatial.add_argument(
        "--spatial-config",
        default="configs/layers/l3_carm_spatial.json",
        help="dimensionless CAR-M spatial L3 JSON",
    )
    carm_spatial.add_argument(
        "--l0-config",
        default="configs/layers/l0_reference_grn.json",
        help="L0 discrete GRN JSON",
    )
    carm_spatial.add_argument(
        "--l1-config",
        default="configs/layers/l1_reference_molecular.json",
        help="L1 coarse molecular model JSON",
    )
    carm_spatial.add_argument(
        "--l4-config",
        default="configs/layers/l4_reference_phenotype.json",
        help="L4 phenotype observer JSON",
    )
    carm_spatial.add_argument(
        "--artifact-root",
        help="optional root for append-only spatial comparison artifacts",
    )

    carm_spatial_ablation = commands.add_parser(
        "carm-spatial-ablation",
        help="audit movement, field coupling, and topology in a 2x2x2 CAR-M L3 design",
    )
    carm_spatial_ablation.add_argument(
        "--config",
        default="configs/scenarios/carm/high_immune_her2.json",
        help="CAR-M scenario JSON",
    )
    carm_spatial_ablation.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    carm_spatial_ablation.add_argument(
        "--audit-config",
        default="configs/experiments/carm_spatial_ablation.json",
        help="deterministic 2x2x2 mechanism-audit JSON",
    )
    carm_spatial_ablation.add_argument(
        "--spatial-config",
        default="configs/layers/l3_carm_spatial.json",
        help="dimensionless CAR-M spatial L3 JSON",
    )
    carm_spatial_ablation.add_argument(
        "--l0-config",
        default="configs/layers/l0_reference_grn.json",
        help="L0 discrete GRN JSON",
    )
    carm_spatial_ablation.add_argument(
        "--l1-config",
        default="configs/layers/l1_reference_molecular.json",
        help="L1 coarse molecular model JSON",
    )
    carm_spatial_ablation.add_argument(
        "--l4-config",
        default="configs/layers/l4_reference_phenotype.json",
        help="L4 phenotype observer JSON",
    )
    carm_spatial_ablation.add_argument(
        "--artifact-root",
        help="optional root for append-only mechanism-audit artifacts",
    )

    spatial_anchor_build = commands.add_parser(
        "spatial-anchor-build",
        help="build a de-identified L3 target from licensed field and neighborhood bundles",
    )
    spatial_anchor_build.add_argument(
        "--protocol",
        default="configs/experiments/carm_spatial_anchor_protocol.json",
        help="pre-registered spatial-anchor protocol JSON",
    )
    spatial_anchor_build.add_argument(
        "--field-bundle",
        required=True,
        help="normalized field observation bundle JSON (raw/intermediate; not committed)",
    )
    spatial_anchor_build.add_argument(
        "--neighborhood-bundle",
        required=True,
        help="normalized cell-neighborhood observation bundle JSON (raw/intermediate; not committed)",
    )
    spatial_anchor_build.add_argument(
        "--output",
        required=True,
        help="de-identified aggregate target JSON outside data/raw",
    )

    spatial_source_field = commands.add_parser(
        "spatial-source-adapt-field",
        help="adapt verified Wu Visium 10x files into a temporary field bundle",
    )
    spatial_source_field.add_argument(
        "--manifest", required=True, help="local Wu source manifest JSON"
    )
    spatial_source_field.add_argument(
        "--protocol",
        default="configs/experiments/carm_spatial_source_protocol.json",
        help="frozen source-adapter proxy and normalization protocol JSON",
    )
    spatial_source_field.add_argument(
        "--output", required=True, help="temporary field observation bundle JSON"
    )

    spatial_source_neighborhood = commands.add_parser(
        "spatial-source-adapt-neighborhood",
        help="adapt verified Jackson IMC CSVs into a temporary neighborhood bundle",
    )
    spatial_source_neighborhood.add_argument(
        "--manifest", required=True, help="local Jackson source manifest JSON"
    )
    spatial_source_neighborhood.add_argument(
        "--protocol",
        default="configs/experiments/carm_spatial_source_protocol.json",
        help="frozen source-adapter proxy and normalization protocol JSON",
    )
    spatial_source_neighborhood.add_argument(
        "--output",
        required=True,
        help="temporary neighborhood observation bundle JSON",
    )

    spatial_anchor_check = commands.add_parser(
        "spatial-anchor-check",
        help="verify the identity and de-identification boundary of an L3 spatial target",
    )
    spatial_anchor_check.add_argument(
        "--target",
        required=True,
        help="aggregate spatial target JSON",
    )

    spatial_anchor_evaluate = commands.add_parser(
        "carm-spatial-anchor-evaluate",
        help="project the causal CAR-M spatial L3 into a verified external target space",
    )
    spatial_anchor_evaluate.add_argument(
        "--target",
        required=True,
        help="verified de-identified aggregate spatial target JSON",
    )
    spatial_anchor_evaluate.add_argument(
        "--protocol",
        default="configs/experiments/carm_spatial_anchor_protocol.json",
        help="pre-registered spatial-anchor protocol JSON",
    )
    spatial_anchor_evaluate.add_argument(
        "--evaluation-config",
        default="configs/experiments/carm_spatial_anchor_evaluation.json",
        help="spatial target evaluation horizon and replay seed JSON",
    )
    spatial_anchor_evaluate.add_argument(
        "--config",
        default="configs/scenarios/carm/high_immune_her2.json",
        help="CAR-M scenario JSON",
    )
    spatial_anchor_evaluate.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    spatial_anchor_evaluate.add_argument(
        "--spatial-config",
        default="configs/layers/l3_carm_spatial.json",
        help="dimensionless CAR-M spatial L3 JSON",
    )
    spatial_anchor_evaluate.add_argument(
        "--l0-config",
        default="configs/layers/l0_reference_grn.json",
        help="L0 discrete GRN JSON",
    )
    spatial_anchor_evaluate.add_argument(
        "--l1-config",
        default="configs/layers/l1_reference_molecular.json",
        help="L1 coarse molecular model JSON",
    )
    spatial_anchor_evaluate.add_argument(
        "--l4-config",
        default="configs/layers/l4_reference_phenotype.json",
        help="L4 phenotype observer JSON",
    )
    spatial_anchor_evaluate.add_argument(
        "--artifact-root",
        help="optional root for raw run, manifest, and derived target score",
    )

    carm_intervention = commands.add_parser(
        "carm-intervention-experiment",
        help="compare equal CAR-M L0 interventions applied in different trajectory states",
    )
    carm_intervention.add_argument(
        "--config",
        default="configs/scenarios/carm/high_immune_her2.json",
        help="CAR-M scenario JSON",
    )
    carm_intervention.add_argument(
        "--intervention-config",
        default="configs/experiments/carm_state_conditioned_intervention.json",
        help="frozen scheduled-intervention protocol JSON",
    )
    carm_intervention.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    carm_intervention.add_argument(
        "--l0-config",
        default="configs/layers/l0_reference_grn.json",
        help="L0 discrete GRN JSON",
    )
    carm_intervention.add_argument(
        "--l1-config",
        default="configs/layers/l1_reference_molecular.json",
        help="L1 coarse molecular model JSON",
    )
    carm_intervention.add_argument(
        "--l4-config",
        default="configs/layers/l4_reference_phenotype.json",
        help="L4 phenotype observer JSON",
    )
    carm_intervention.add_argument(
        "--artifact-root",
        help="optional root for append-only scheduled-intervention artifacts",
    )

    demo_export = commands.add_parser(
        "demo-export",
        help="export the self-contained offline CAR-M stage demo (HTML player)",
    )
    demo_export.add_argument(
        "--config",
        default="configs/scenarios/carm/high_immune_her2.json",
        help="CAR-M scenario JSON",
    )
    demo_export.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    demo_export.add_argument(
        "--matrix-config",
        default="configs/experiments/carm_vertical_slice.json",
        help="CAR-M causal matrix JSON",
    )
    demo_export.add_argument(
        "--l0-config",
        default="configs/layers/l0_reference_grn.json",
        help="L0 discrete GRN JSON",
    )
    demo_export.add_argument(
        "--l1-config",
        default="configs/layers/l1_reference_molecular.json",
        help="L1 coarse molecular model JSON",
    )
    demo_export.add_argument(
        "--l4-config",
        default="configs/layers/l4_reference_phenotype.json",
        help="L4 phenotype observer JSON",
    )
    demo_export.add_argument(
        "--output-dir",
        default="artifacts/demo",
        help="demo output directory (playbook, HTML player, manifest)",
    )

    sten = commands.add_parser("sten-smoke", help="run the L3 STEN subsystem smoke test")
    sten.add_argument("--config", default="configs/demo.json", help="STEN scenario JSON")
    sten.add_argument("--ticks", type=int, help="override scenario tick count")

    feedback_experiment = commands.add_parser(
        "feedback-experiment",
        help="run the E4 no/fixed/state L4-to-L3 feedback comparison matrix",
    )
    _add_layered_arguments(feedback_experiment)
    feedback_experiment.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    feedback_experiment.add_argument(
        "--matrix-config",
        default="configs/experiments/e4_feedback.json",
        help="E4 feedback experiment JSON",
    )
    feedback_experiment.add_argument(
        "--feedback-config",
        default="configs/layers/l4_feedback_controller.json",
        help="homeostatic feedback controller JSON",
    )
    feedback_experiment.add_argument(
        "--artifact-root",
        help="optional root for the complete raw and derived feedback artifacts",
    )

    policy_experiment = commands.add_parser(
        "policy-experiment",
        help="run the L2 rule-vs-active-inference policy comparison matrix",
    )
    _add_layered_arguments(policy_experiment)
    policy_experiment.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    policy_experiment.add_argument(
        "--matrix-config",
        default="configs/experiments/policy_comparison.json",
        help="L2 policy comparison JSON",
    )
    policy_experiment.add_argument(
        "--active-inference-config",
        default="configs/layers/l2_active_inference.json",
        help="active inference L2 policy JSON",
    )
    policy_experiment.add_argument(
        "--artifact-root",
        help="optional root for the complete raw and derived policy artifacts",
    )

    latent_experiment = commands.add_parser(
        "latent-experiment",
        help="run the L2 rule-vs-latent-cell policy comparison matrix",
    )
    _add_layered_arguments(latent_experiment)
    latent_experiment.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    latent_experiment.add_argument(
        "--matrix-config",
        default="configs/experiments/latent_comparison.json",
        help="L2 latent policy comparison JSON",
    )
    latent_experiment.add_argument(
        "--latent-config",
        default="configs/layers/l2_latent_cell.json",
        help="latent virtual-cell L2 policy JSON",
    )
    latent_experiment.add_argument(
        "--artifact-root",
        help="optional root for the complete raw and derived latent artifacts",
    )

    autolab = commands.add_parser(
        "autolab",
        help="run the deterministic screen-then-confirm autonomous experiment loop",
    )
    _add_layered_arguments(autolab)
    autolab.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    autolab.add_argument(
        "--autolab-config",
        default="configs/experiments/autolab_screen.json",
        help="autolab hypothesis registry and protocol JSON",
    )
    autolab.add_argument(
        "--artifact-root",
        help="optional root for the autolab session artifacts",
    )

    autolab_propose = commands.add_parser(
        "autolab-propose",
        help="validate hypothesis proposals against the registry schema (never executes)",
    )
    autolab_propose.add_argument(
        "--autolab-config",
        default="configs/experiments/autolab_screen.json",
        help="autolab hypothesis registry and protocol JSON",
    )
    autolab_propose.add_argument(
        "--proposals",
        required=True,
        help="proposal JSON file to validate (proposed_by human or llm)",
    )

    data_check = commands.add_parser(
        "data-check",
        help="verify every dataset registered in data/registry.json (fail-closed)",
    )
    data_check.add_argument(
        "--registry",
        default="data/registry.json",
        help="dataset registry JSON",
    )

    topology_experiment = commands.add_parser(
        "topology-experiment",
        help="run the E5 static-vs-adaptive L3 topology comparison matrix",
    )
    _add_layered_arguments(topology_experiment)
    topology_experiment.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    topology_experiment.add_argument(
        "--matrix-config",
        default="configs/experiments/topology_comparison.json",
        help="E5 topology comparison JSON",
    )
    topology_experiment.add_argument(
        "--adaptive-config",
        default="configs/layers/l3_adaptive_tissue.json",
        help="adaptive L3 topology governance JSON",
    )
    topology_experiment.add_argument(
        "--artifact-root",
        help="optional root for the complete raw and derived topology artifacts",
    )


    e3_experiment = commands.add_parser(
        "e3-experiment",
        help="run the multi-seed noisy-L0 E3 population ensemble",
    )
    _add_layered_arguments(e3_experiment)
    e3_experiment.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    e3_experiment.add_argument(
        "--matrix-config",
        default="configs/experiments/e3_population.json",
        help="E3 population ensemble JSON",
    )
    e3_experiment.add_argument(
        "--noisy-config",
        default="configs/layers/l0_noisy_grn.json",
        help="noisy L0 discrete GRN JSON",
    )
    e3_experiment.add_argument(
        "--artifact-root",
        help="optional root for the E3 summary artifacts",
    )

    closed_loop = commands.add_parser(
        "closed-loop-experiment",
        help="run the stochastic closed-loop feedback-under-noise matrix",
    )
    _add_layered_arguments(closed_loop)
    closed_loop.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    closed_loop.add_argument(
        "--matrix-config",
        default="configs/experiments/closed_loop_stochastic.json",
        help="closed-loop stochastic matrix JSON",
    )
    closed_loop.add_argument(
        "--noisy-config",
        default="configs/layers/l0_noisy_grn.json",
        help="noisy L0 discrete GRN JSON",
    )
    closed_loop.add_argument(
        "--feedback-config",
        default="configs/layers/l4_feedback_controller.json",
        help="homeostatic feedback controller JSON",
    )
    closed_loop.add_argument(
        "--artifact-root",
        help="optional root for the complete raw and derived closed-loop artifacts",
    )

    neural_experiment = commands.add_parser(
        "neural-experiment",
        help="run the reference-vs-neural single-layer swap comparison matrix",
    )
    _add_layered_arguments(neural_experiment)
    neural_experiment.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    neural_experiment.add_argument(
        "--matrix-config",
        default="configs/experiments/neural_comparison.json",
        help="neural layer-swap comparison JSON",
    )
    neural_experiment.add_argument(
        "--layer",
        choices=("l0", "l3"),
        default="l3",
        help="layer swapped for the frozen-weight neural variant",
    )
    neural_experiment.add_argument(
        "--neural-l0-config",
        default="configs/layers/l0_neural_grn.json",
        help="frozen-weight MLP L0 GRN JSON",
    )
    neural_experiment.add_argument(
        "--neural-l3-config",
        default="configs/layers/l3_gnn_tissue.json",
        help="frozen-weight GNN L3 tissue JSON",
    )
    neural_experiment.add_argument(
        "--artifact-root",
        help="optional root for the complete raw and derived neural artifacts",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "run":
        scenario = load_multiscale_scenario(args.config)
        runner = ReferenceCrossScaleRunner(**_load_layer_models(args))
        result = summarize_trace(scenario, runner.run(scenario))
    elif args.command == "simulate":
        if args.ticks < 1:
            raise SystemExit("--ticks must be positive")
        scenario = load_multiscale_scenario(args.config)
        runner = _load_multirate_runner(args)
        checkpoint = (
            load_checkpoint(args.checkpoint_in) if args.checkpoint_in else None
        )
        run = runner.run(scenario, ticks=args.ticks, checkpoint=checkpoint)
        if args.checkpoint_out:
            save_checkpoint(args.checkpoint_out, run.checkpoint)
        if args.trace_out:
            save_run_artifact(args.trace_out, run)
        result = run.summary_dict()
    elif args.command == "experiment":
        scenario = load_multiscale_scenario(args.config)
        matrix_config = load_causal_config(args.matrix_config)
        matrix_runner = CausalExperimentRunner(
            matrix_config,
            runners={
                variant: _load_multirate_runner(args, variant=variant)
                for variant in ("baseline", *matrix_config.ablations)
            },
        )
        matrix = matrix_runner.run(scenario)
        result = matrix.report_dict()
        if args.artifact_root:
            paths = save_causal_artifacts(args.artifact_root, matrix)
            result["artifact_root"] = str(paths.root)
    elif args.command == "report":
        paths = build_causal_report(args.matrix_root, args.output_dir)
        report_manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
        result = {
            "matrix_id": report_manifest["matrix_id"],
            "report_root": str(paths.root),
            "report_manifest": str(paths.manifest),
            "files": report_manifest["files"],
        }
    elif args.command == "run-report":
        paths = build_run_report(args.run, args.output_dir)
        report_manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
        result = {
            "experiment_id": report_manifest["experiment_id"],
            "history_digest": report_manifest["history_digest"],
            "report_root": str(paths.root),
            "report_manifest": str(paths.manifest),
            "files": report_manifest["files"],
        }
    elif args.command == "carm-import":
        profile = build_carm_profile(args.legacy_root)
        save_carm_profile(args.output, profile)
        result = {
            "schema_version": profile.schema_version,
            "cohort_id": profile.cohort_id,
            "sample_count": profile.sample_count,
            "total_sample_count": profile.total_sample_count,
            "subtype_counts": dict(profile.subtype_counts),
            "output": args.output,
            "proxy_label_notice": profile.proxy_label_notice,
        }
    elif args.command == "carm-experiment":
        compiled = compile_carm_scenario(load_carm_scenario_config(args.config))
        matrix_config = load_causal_config(args.matrix_config)
        runners = build_carm_runners(
            compiled,
            matrix_config,
            runner_config=load_runner_config(args.runner_config),
            l0_config=args.l0_config,
            l1_config=args.l1_config,
            l4_config=args.l4_config,
        )
        matrix = run_carm_matrix(compiled, matrix_config, runners=runners)
        result = matrix.report_dict()
        result["model_status"] = CARM_MODEL_STATUS
        result["cohort_id"] = compiled.config.profile.cohort_id
        result["profile_digest"] = compiled.profile_digest
        if args.artifact_root:
            artifacts = save_carm_artifacts(args.artifact_root, matrix, compiled)
            report_paths = build_causal_report(artifacts.causal.root)
            result["artifact_root"] = str(artifacts.causal.root)
            result["provenance"] = str(artifacts.provenance)
            result["report"] = str(report_paths.html)
    elif args.command == "carm-spatial-experiment":
        compiled = compile_carm_scenario(load_carm_scenario_config(args.config))
        matrix_config = load_carm_spatial_experiment_config(args.matrix_config)
        runners = build_carm_spatial_runners(
            compiled,
            runner_config=load_runner_config(args.runner_config),
            spatial_config=load_carm_spatial_config(args.spatial_config),
            l0_config=args.l0_config,
            l1_config=args.l1_config,
            l4_config=args.l4_config,
        )
        matrix = CarmSpatialExperimentRunner(
            matrix_config, runners=runners
        ).run(compiled)
        result = matrix.summary_dict()
        result["cohort_id"] = compiled.config.profile.cohort_id
        result["profile_digest"] = compiled.profile_digest
        if args.artifact_root:
            paths = save_carm_spatial_artifacts(args.artifact_root, matrix)
            result["artifact_root"] = str(paths["root"])
            result["artifact_manifest"] = str(paths["manifest"])
            result["artifact_summary"] = str(paths["summary"])
    elif args.command == "carm-spatial-ablation":
        compiled = compile_carm_scenario(load_carm_scenario_config(args.config))
        audit_config = load_carm_spatial_ablation_config(args.audit_config)
        runners = build_carm_spatial_ablation_runners(
            compiled,
            runner_config=load_runner_config(args.runner_config),
            spatial_config=load_carm_spatial_config(args.spatial_config),
            l0_config=args.l0_config,
            l1_config=args.l1_config,
            l4_config=args.l4_config,
        )
        audit = CarmSpatialAblationRunner(
            audit_config, runners=runners
        ).run(compiled)
        result = audit.summary_dict()
        result["cohort_id"] = compiled.config.profile.cohort_id
        result["profile_digest"] = compiled.profile_digest
        if args.artifact_root:
            paths = save_carm_spatial_ablation_artifacts(
                args.artifact_root, audit
            )
            result["artifact_root"] = str(paths["root"])
            result["artifact_manifest"] = str(paths["manifest"])
            result["artifact_summary"] = str(paths["summary"])
    elif args.command == "spatial-source-adapt-field":
        output = adapt_wu_visium_source(
            args.manifest,
            protocol_path=args.protocol,
            output_path=args.output,
        )
        bundle = load_spatial_observation_bundle(output)
        result = {
            "schema_version": bundle.identity_dict()["schema_version"],
            "dataset_id": bundle.dataset_id,
            "modality": bundle.modality,
            "input_digest": bundle.input_digest,
            "samples": len(bundle.samples),
            "observations": sum(len(item.field_observations) for item in bundle.samples),
            "output": str(output),
            "model_status": "source-adapter-output-not-runtime-or-clinical-data",
        }
    elif args.command == "spatial-source-adapt-neighborhood":
        output = adapt_jackson_imc_source(
            args.manifest,
            protocol_path=args.protocol,
            output_path=args.output,
        )
        bundle = load_spatial_observation_bundle(output)
        result = {
            "schema_version": bundle.identity_dict()["schema_version"],
            "dataset_id": bundle.dataset_id,
            "modality": bundle.modality,
            "input_digest": bundle.input_digest,
            "samples": len(bundle.samples),
            "observations": sum(
                len(item.neighborhood_observations) for item in bundle.samples
            ),
            "output": str(output),
            "model_status": "source-adapter-output-not-runtime-or-clinical-data",
        }
    elif args.command == "spatial-anchor-build":
        profile = build_spatial_anchor_profile(
            load_spatial_anchor_protocol(args.protocol),
            field_bundle=load_spatial_observation_bundle(args.field_bundle),
            neighborhood_bundle=load_spatial_observation_bundle(
                args.neighborhood_bundle
            ),
        )
        output = save_spatial_anchor_profile(args.output, profile)
        result = {
            "schema_version": profile.as_dict()["schema_version"],
            "target_id": profile.target_id,
            "output": str(output),
            "sources": [
                {
                    "dataset_id": item["dataset_id"],
                    "modality": item["modality"],
                    "sample_count": item["sample_count"],
                    "input_digest": item["input_digest"],
                }
                for item in profile.sources
            ],
            "role_counts": {
                role: sum(1 for item in profile.samples if item.role == role)
                for role in ("calibration", "holdout", "external_validation")
            },
            "metric_distribution_count": len(profile.distributions),
            "model_status": "de-identified-L3-aggregate-target-not-runtime-or-clinical-data",
        }
    elif args.command == "spatial-anchor-check":
        target = verify_spatial_anchor_target(args.target)
        result = {
            "schema_version": target["schema_version"],
            "target_id": target["target_id"],
            "samples": len(target["samples"]),
            "distributions": len(target["distributions"]),
            "ok": True,
        }
    elif args.command == "carm-spatial-anchor-evaluate":
        target = verify_spatial_anchor_target(args.target)
        protocol = load_spatial_anchor_protocol(args.protocol)
        compiled = compile_carm_scenario(load_carm_scenario_config(args.config))
        runners = build_carm_spatial_runners(
            compiled,
            runner_config=load_runner_config(args.runner_config),
            spatial_config=load_carm_spatial_config(args.spatial_config),
            l0_config=args.l0_config,
            l1_config=args.l1_config,
            l4_config=args.l4_config,
        )
        evaluation = SpatialAnchorEvaluator(
            load_spatial_anchor_evaluation_config(args.evaluation_config),
            runner=runners["spatial_field"],
            protocol=protocol,
        ).evaluate(compiled, target=target)
        result = evaluation.summary_dict()
        if args.artifact_root:
            paths = save_spatial_anchor_evaluation_artifacts(
                args.artifact_root, evaluation
            )
            result["artifact_root"] = str(paths["root"])
            result["artifact_manifest"] = str(paths["manifest"])
            result["artifact_summary"] = str(paths["summary"])
    elif args.command == "carm-intervention-experiment":
        compiled = compile_carm_scenario(load_carm_scenario_config(args.config))
        intervention_config = load_state_conditioned_intervention_config(
            args.intervention_config
        )
        runner = build_carm_intervention_runner(
            compiled,
            runner_config=load_runner_config(args.runner_config),
            l0_config=args.l0_config,
            l1_config=args.l1_config,
            l4_config=args.l4_config,
        )
        intervention = StateConditionedInterventionRunner(
            intervention_config, runner=runner
        ).run(compiled)
        result = intervention.summary_dict()
        if args.artifact_root:
            paths = save_state_conditioned_intervention_artifacts(
                args.artifact_root, intervention
            )
            result["artifact_root"] = str(paths["root"])
            result["artifact_manifest"] = str(paths["manifest"])
            result["artifact_summary"] = str(paths["summary"])
    elif args.command == "demo-export":
        paths = export_carm_demo(
            scenario_config=args.config,
            matrix_config=args.matrix_config,
            runner_config=args.runner_config,
            l0_config=args.l0_config,
            l1_config=args.l1_config,
            l4_config=args.l4_config,
            output_dir=args.output_dir,
        )
        playbook = json.loads(paths.playbook.read_text(encoding="utf-8"))
        manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
        result = {
            "playbook": str(paths.playbook),
            "html": str(paths.html),
            "manifest": str(paths.manifest),
            "conditions": [
                condition["condition_id"] for condition in playbook["conditions"]
            ],
            "ticks": len(playbook["conditions"][0]["ticks"]),
            "cells": len(playbook["roles"]),
            "playbook_digest": manifest["playbook_digest"],
        }
    elif args.command == "feedback-experiment":
        scenario = load_multiscale_scenario(args.config)
        e4_config = load_feedback_experiment_config(args.matrix_config)
        feedback_controller = load_feedback_config(args.feedback_config)
        runners = build_feedback_runners(
            layer_models=_load_layer_models(args),
            runner_config=load_runner_config(args.runner_config),
            feedback_config=feedback_controller,
            fixed_resource_ceiling=e4_config.fixed_resource_ceiling,
            fixed_stress_floor=e4_config.fixed_stress_floor,
        )
        matrix = FeedbackExperimentRunner(e4_config, runners=runners).run(scenario)
        result = matrix.summary_dict()
        result["model_status"] = "reference-model-not-validated-biological-model"
        if args.artifact_root:
            paths = save_feedback_artifacts(args.artifact_root, matrix)
            result["artifact_root"] = str(paths["root"])
            result["artifact_manifest"] = str(paths["manifest"])
            result["artifact_summary"] = str(paths["summary"])
    elif args.command == "policy-experiment":
        scenario = load_multiscale_scenario(args.config)
        policy_config = load_policy_experiment_config(args.matrix_config)
        runner_config = load_runner_config(args.runner_config)
        rule_models = _load_layer_models(args)
        inference_models = dict(rule_models)
        inference_models["cell_model"] = ActiveInferenceCellModel(
            load_active_inference_config(args.active_inference_config)
        )
        runners = {
            "rule_policy": MultirateCrossScaleRunner(runner_config, **rule_models),
            "active_inference_policy": MultirateCrossScaleRunner(
                runner_config, **inference_models
            ),
        }
        matrix = PolicyExperimentRunner(policy_config, runners=runners).run(scenario)
        result = matrix.summary_dict()
        result["model_status"] = "reference-model-not-validated-biological-model"
        if args.artifact_root:
            paths = save_policy_artifacts(args.artifact_root, matrix)
            result["artifact_root"] = str(paths["root"])
            result["artifact_manifest"] = str(paths["manifest"])
            result["artifact_summary"] = str(paths["summary"])
    elif args.command == "latent-experiment":
        scenario = load_multiscale_scenario(args.config)
        latent_config = load_latent_experiment_config(args.matrix_config)
        runner_config = load_runner_config(args.runner_config)
        rule_models = _load_layer_models(args)
        latent_models = dict(rule_models)
        latent_models["cell_model"] = LatentCellModel(
            load_latent_cell_config(args.latent_config)
        )
        runners = {
            "rule_policy": MultirateCrossScaleRunner(runner_config, **rule_models),
            "latent_cell_policy": MultirateCrossScaleRunner(
                runner_config, **latent_models
            ),
        }
        matrix = LatentExperimentRunner(latent_config, runners=runners).run(scenario)
        result = matrix.summary_dict()
        result["model_status"] = "reference-model-not-validated-biological-model"
        if args.artifact_root:
            paths = save_latent_artifacts(args.artifact_root, matrix)
            result["artifact_root"] = str(paths["root"])
            result["artifact_manifest"] = str(paths["manifest"])
            result["artifact_summary"] = str(paths["summary"])
    elif args.command == "autolab":
        scenario = load_multiscale_scenario(args.config)
        autolab_config = load_autolab_config(args.autolab_config)
        runner_config = load_runner_config(args.runner_config)
        if (
            max(autolab_config.probe_ticks, autolab_config.confirm_ticks)
            > runner_config.max_total_ticks
        ):
            raise SystemExit("autolab ticks exceed the runner budget")
        variant_by_layer = {"L1": "l1_static", "L2": "l2_static", "L3": "l3_static"}
        baseline_runner = _load_multirate_runner(args)
        baseline_cache: dict[tuple[int, int], object] = {}

        def evaluate(hypothesis, ticks, seeds):
            condition_runner = _load_multirate_runner(
                args, variant=variant_by_layer[hypothesis.layer]
            )
            per_seed = []
            digests = []
            for seed in seeds:
                seeded = replace(scenario, seed=seed)
                cache_key = (seed, ticks)
                if cache_key not in baseline_cache:
                    baseline_cache[cache_key] = baseline_runner.run(
                        seeded, ticks=ticks
                    )
                baseline_run = baseline_cache[cache_key]
                condition_run = condition_runner.run(seeded, ticks=ticks)
                comparison = _compare_runs(
                    CausalRunRecord(
                        condition_id="baseline",
                        condition_kind=ConditionKind.BASELINE,
                        seed=seed,
                        run=baseline_run,
                    ),
                    CausalRunRecord(
                        condition_id=hypothesis.hypothesis_id,
                        condition_kind=ConditionKind.PERTURBATION,
                        seed=seed,
                        run=condition_run,
                    ),
                )
                per_seed.append((seed, comparison.final_metric_effects))
                digests.append((seed, condition_run.history_digest))
            return EvaluatorResult(
                per_seed_metric_effects=tuple(per_seed),
                history_digests=tuple(digests),
            )

        session = AutolabSession(autolab_config, evaluate=evaluate).run()
        result = session.summary_dict()
        result["model_status"] = "reference-model-not-validated-biological-model"
        if args.artifact_root:
            paths = save_autolab_artifacts(args.artifact_root, session)
            result["artifact_root"] = str(paths["root"])
            result["artifact_manifest"] = str(paths["manifest"])
            result["artifact_summary"] = str(paths["summary"])
    elif args.command == "autolab-propose":
        registry = load_autolab_config(args.autolab_config)
        proposals = load_proposal_file(args.proposals)
        result = validate_proposals(
            proposals,
            registry_ids=[item.hypothesis_id for item in registry.hypotheses],
        ).summary_dict()
    elif args.command == "data-check":
        registry_path = Path(args.registry)
        entries = load_data_registry(registry_path)
        status_by_id = {entry.dataset_id: entry.status for entry in entries}
        verdicts = validate_data_registry(
            entries, data_root=registry_path.resolve().parent.parent
        )
        ok = all(verdict.ok for verdict in verdicts)
        result = {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "ok": ok,
            "entries": [
                {
                    "dataset_id": verdict.dataset_id,
                    "status": status_by_id[verdict.dataset_id],
                    "ok": verdict.ok,
                    "detail": verdict.detail,
                }
                for verdict in verdicts
            ],
        }
        if not ok:
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            raise SystemExit(1)
    elif args.command == "topology-experiment":
        scenario = load_multiscale_scenario(args.config)
        topology_config = load_topology_experiment_config(args.matrix_config)
        runner_config = load_runner_config(args.runner_config)
        static_models = _load_layer_models(args)
        adaptive_models = dict(static_models)
        adaptive_models["tissue_model"] = DynamicTopologyTissueModel(
            static_models["tissue_model"].config,
            load_adaptive_topology_config(args.adaptive_config),
        )
        runners = {
            "static_topology": MultirateCrossScaleRunner(
                runner_config, **static_models
            ),
            "adaptive_topology": MultirateCrossScaleRunner(
                runner_config, **adaptive_models
            ),
        }
        matrix = TopologyExperimentRunner(
            topology_config, runners=runners
        ).run(scenario)
        result = matrix.summary_dict()
        result["model_status"] = "reference-model-not-validated-biological-model"
        if args.artifact_root:
            paths = save_topology_artifacts(args.artifact_root, matrix)
            result["artifact_root"] = str(paths["root"])
            result["artifact_manifest"] = str(paths["manifest"])
            result["artifact_summary"] = str(paths["summary"])
    elif args.command == "e3-experiment":
        scenario = load_multiscale_scenario(args.config)
        e3_config = load_e3_experiment_config(args.matrix_config)
        runner_config = load_runner_config(args.runner_config)
        grn_config, noise_sigma = load_noisy_grn_config(args.noisy_config)
        base_models = _load_layer_models(args)

        def build_noisy_runner(seed: int) -> MultirateCrossScaleRunner:
            models = dict(base_models)
            models["genome_model"] = NoisyDiscreteGrnModel(
                grn_config, noise_sigma=noise_sigma, noise_seed=seed
            )
            return MultirateCrossScaleRunner(runner_config, **models)

        matrix = E3ExperimentRunner(
            e3_config, build_runner=build_noisy_runner
        ).run(scenario)
        result = matrix.summary_dict()
        result["model_status"] = "reference-model-not-validated-biological-model"
        if args.artifact_root:
            paths = save_e3_artifacts(args.artifact_root, matrix)
            result["artifact_root"] = str(paths["root"])
            result["artifact_manifest"] = str(paths["manifest"])
            result["artifact_summary"] = str(paths["summary"])
    elif args.command == "closed-loop-experiment":
        scenario = load_multiscale_scenario(args.config)
        loop_config = load_closed_loop_config(args.matrix_config)
        runner_config = load_runner_config(args.runner_config)
        grn_config, noise_sigma = load_noisy_grn_config(args.noisy_config)
        feedback_config = load_feedback_config(args.feedback_config)
        matrix = ClosedLoopExperimentRunner(
            loop_config,
            runner_config=runner_config,
            layer_models=_load_layer_models(args),
            feedback_config=feedback_config,
            noisy_grn_config=grn_config,
            noise_sigma=noise_sigma,
        ).run(scenario)
        result = matrix.summary_dict()
        result["model_status"] = "reference-model-not-validated-biological-model"
        if args.artifact_root:
            paths = save_closed_loop_artifacts(args.artifact_root, matrix)
            result["artifact_root"] = str(paths["root"])
            result["artifact_manifest"] = str(paths["manifest"])
            result["artifact_summary"] = str(paths["summary"])
    elif args.command == "neural-experiment":
        scenario = load_multiscale_scenario(args.config)
        neural_config = load_neural_comparison_config(args.matrix_config)
        runner_config = load_runner_config(args.runner_config)
        baseline_models = _load_layer_models(args)
        neural_models = dict(baseline_models)
        if args.layer == "l0":
            neural_models["genome_model"] = NeuralGrnModel(
                load_neural_grn_config(args.neural_l0_config)
            )
            changed_layer = "L0"
        else:
            neural_models["tissue_model"] = GnnTissueModel(
                load_gnn_tissue_config(args.neural_l3_config)
            )
            changed_layer = "L3"
        matrix = NeuralComparisonRunner(
            neural_config,
            baseline_runner=MultirateCrossScaleRunner(
                runner_config, **baseline_models
            ),
            neural_runner=MultirateCrossScaleRunner(
                runner_config, **neural_models
            ),
            changed_layer=changed_layer,
        ).run(scenario)
        result = matrix.summary_dict()
        result["model_status"] = "reference-model-not-validated-biological-model"
        if args.artifact_root:
            paths = save_neural_artifacts(args.artifact_root, matrix)
            result["artifact_root"] = str(paths["root"])
            result["artifact_manifest"] = str(paths["manifest"])
            result["artifact_summary"] = str(paths["summary"])
    else:
        if args.ticks is not None and args.ticks < 1:
            raise SystemExit("--ticks must be positive")
        result = run_scenario(load_scenario(args.config), ticks=args.ticks)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
