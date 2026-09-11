from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

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
    build_autolab_manifest,
    load_autolab_config,
    load_proposal_file,
    save_autolab_artifacts,
    validate_proposals,
)
from .autolab_planning import (
    AutolabPlan,
    compile_autolab_plan,
    save_autolab_plan,
    save_verification_report,
    verify_autolab_plan,
    verify_autolab_result,
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
from .lab import export_competition_lab_data
from .perturbation_anchors import (
    SPLIT_SALT,
    build_perturbation_profile,
    compare_profiles,
    load_empirical_bundle,
    load_hallmark_memberships,
    load_profile_for_crosscheck,
    save_crosscheck,
    save_perturbation_profile,
)
from .l0_training_evaluation import (
    evaluate_training,
    load_response_predictions,
    save_training_evaluation,
)
from .hallmark_targets import (
    build_hallmark_targets,
    load_all_hallmark_memberships,
    load_source_profile,
    save_hallmark_target,
)
from .hallmark_training_evaluation import (
    evaluate_hallmark_training,
    load_hallmark_predictions,
    save_hallmark_training_evaluation,
)
from .context_pathway import (
    EMBEDDING_DIM,
    EMBEDDING_TABLE_SCHEMA_VERSION,
    build_ood_split_manifest,
    load_context_bundle,
    save_ood_split_manifest,
)
from .context_pathway_evaluation import (
    evaluate_context_pathway_predictions,
    evaluate_external_context_pathway_predictions,
    load_context_pathway_predictions,
    save_context_pathway_evaluation,
)
from .validation import file_sha256
from .calibration import load_calibration_protocol
from .spatial_calibration import (
    CONSUMED_CONFIRMATION_TARGET_IDS,
    make_spatial_objective,
    point_to_overrides,
    reference_box_point,
    run_spatial_calibration,
    save_spatial_calibration_artifacts,
)
from .collective_dynamics import (
    analyze_collective_dynamics_raw,
    load_cohort_map,
    load_collective_dynamics_config,
    load_raw_run_mapping,
    save_collective_dynamics_artifact,
)
from .empirical_l0_experiments import (
    EmpiricalL0ComparisonRunner,
    EmpiricalL0ScheduleRunner,
    load_empirical_l0_comparison_config,
    load_empirical_l0_schedule_config,
    save_empirical_l0_artifacts,
    save_empirical_l0_schedule_artifacts,
)
from .empirical_response import build_response_table, load_response_table, save_response_table
from .layers.l0_empirical import EmpiricalResponseGrnModel, load_empirical_l0_config
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
    compare_runs,
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
from .evidence_report import build_evidence_report, verify_evidence_report
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



def _register_run(commands) -> None:
    layered = commands.add_parser("run", help="run the default L0-to-L4 contract trace")
    _add_layered_arguments(layered)



def _register_simulate(commands) -> None:
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



def _register_experiment(commands) -> None:
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



def _register_report(commands) -> None:
    report = commands.add_parser(
        "report", help="rebuild the WP9 report from a saved WP8 causal matrix"
    )
    report.add_argument(
        "--matrix-root", required=True, help="saved causal matrix artifact directory"
    )
    report.add_argument(
        "--output-dir", help="optional report directory; defaults inside the matrix"
    )



def _register_run_report(commands) -> None:
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



def _register_evidence_report(commands) -> None:
    evidence_report = commands.add_parser(
        "evidence-report",
        help="build the unified read-only evidence overview across saved artifacts (ADR-0050)",
    )
    evidence_report.add_argument(
        "--artifact-root",
        default="artifacts",
        help="artifact root scanned by the pipeline (default: artifacts)",
    )
    evidence_report.add_argument(
        "--output",
        help="optional report directory; defaults to <artifact-root>/evidence-report",
    )
    evidence_report.add_argument(
        "--registry",
        help="optional data registry JSON; defaults to <artifact-root>/../data/registry.json",
    )
    evidence_report.add_argument(
        "--verify",
        action="store_true",
        help="rebuild into a temporary directory and byte-compare against the existing output",
    )



def _register_carm_import(commands) -> None:
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



def _register_carm_experiment(commands) -> None:
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



def _register_carm_spatial_experiment(commands) -> None:
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



def _register_carm_spatial_ablation(commands) -> None:
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



def _register_spatial_anchor_build(commands) -> None:
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



def _register_spatial_source_adapt_field(commands) -> None:
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



def _register_spatial_source_adapt_neighborhood(commands) -> None:
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



def _register_spatial_anchor_check(commands) -> None:
    spatial_anchor_check = commands.add_parser(
        "spatial-anchor-check",
        help="verify the identity and de-identification boundary of an L3 spatial target",
    )
    spatial_anchor_check.add_argument(
        "--target",
        required=True,
        help="aggregate spatial target JSON",
    )



def _register_carm_spatial_anchor_evaluate(commands) -> None:
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



def _register_aivc_perturbation_anchor(commands) -> None:
    aivc_anchor = commands.add_parser(
        "aivc-perturbation-anchor",
        help="build the de-identified six-node perturbation profile from an empirical log2FC bundle",
    )
    aivc_anchor.add_argument(
        "--bundle",
        required=True,
        help="empirical log2fc bundle JSON from scripts/aivc_norman_empirical.py",
    )
    aivc_anchor.add_argument(
        "--hallmark",
        required=True,
        help="MSigDB Hallmark symbols GMT (sha256 must match the bundle identity)",
    )
    aivc_anchor.add_argument(
        "--output",
        required=True,
        help="write-once perturbation profile JSON output",
    )
    aivc_anchor.add_argument(
        "--salt",
        default=None,
        help="split salt override (default: frozen Stage 1 salt)",
    )



def _register_l0_training_evaluate(commands) -> None:
    l0_training_eval = commands.add_parser(
        "l0-training-evaluate",
        help="verify L0 response predictions and apply the frozen ADR-0037 pass rule",
    )
    l0_training_eval.add_argument(
        "--predictions",
        required=True,
        help="mgba-l0-response-predictions-0.1 JSON from the venv training script",
    )
    l0_training_eval.add_argument(
        "--profile",
        required=True,
        help="Stage 1 perturbation profile JSON (identity cross-checked)",
    )
    l0_training_eval.add_argument(
        "--output",
        required=True,
        help="write-once training evaluation JSON output",
    )



def _register_l0_response_table_build(commands) -> None:
    response_table = commands.add_parser(
        "l0-response-table-build",
        help="distill verified predictions into the write-once L0 response table",
    )
    response_table.add_argument("--predictions", required=True)
    response_table.add_argument("--evaluation", required=True)
    response_table.add_argument("--output", required=True)


def _register_hallmark_target_build(commands) -> None:
    hallmark_target = commands.add_parser(
        "hallmark-target-build",
        help="build the ADR-0046 Hallmark-set + six-node-head structured target",
    )
    hallmark_target.add_argument(
        "--bundle",
        required=True,
        help="empirical log2fc bundle JSON (identity pinned by SHA-256)",
    )
    hallmark_target.add_argument(
        "--profile",
        required=True,
        help="Stage 1 perturbation profile JSON (roles and head gate source)",
    )
    hallmark_target.add_argument(
        "--output",
        required=True,
        help="write-once hallmark target JSON output",
    )
    hallmark_target.add_argument(
        "--hallmark",
        default="data/aivc/A1-msigdb-hallmark/h.all.v2026.1.Hs.symbols.gmt",
        help="MSigDB Hallmark symbols GMT (sha256 must match the bundle identity)",
    )


def _register_hallmark_training_evaluate(commands) -> None:
    hallmark_eval = commands.add_parser(
        "hallmark-training-evaluate",
        help="verify Hallmark-target predictions and apply the frozen ADR-0046 pass rule",
    )
    hallmark_eval.add_argument(
        "--predictions",
        required=True,
        help="mgba-l0-hallmark-predictions-0.1 JSON from the venv training script",
    )
    hallmark_eval.add_argument(
        "--target",
        required=True,
        help="mgba-hallmark-target-0.1 JSON (identity cross-checked)",
    )
    hallmark_eval.add_argument(
        "--output",
        required=True,
        help="write-once training evaluation JSON output",
    )


def _register_ood_split_build(commands) -> None:
    split_build = commands.add_parser(
        "ood-split-build",
        help="freeze the four-context, five-salt gene/context-disjoint benchmark",
    )
    split_build.add_argument(
        "--bundle",
        action="append",
        required=True,
        help="mgba-perturbation-context-bundle-0.1 JSON; pass once per context",
    )
    split_build.add_argument(
        "--external-labels-sha256",
        required=True,
        help="pre-recorded SHA-256 of the sealed Arc H1 response labels",
    )
    split_build.add_argument(
        "--embeddings",
        required=True,
        help="frozen mgba-gene-embedding-table-0.1 JSON used for gene eligibility",
    )
    split_build.add_argument(
        "--output",
        required=True,
        help="write-once OOD split manifest JSON output",
    )


def _register_context_pathway_evaluate(commands) -> None:
    evaluation = commands.add_parser(
        "context-pathway-evaluate",
        help="verify OOD pathway predictions and apply the locked development gates",
    )
    evaluation.add_argument(
        "--predictions",
        action="append",
        default=[],
        help="one prediction artifact per evaluated fold",
    )
    evaluation.add_argument(
        "--split",
        required=True,
        help="locked mgba-ood-split-manifest-0.1 JSON",
    )
    evaluation.add_argument(
        "--bundle",
        action="append",
        required=True,
        help="locked context bundle; pass once per development context",
    )
    evaluation.add_argument(
        "--output",
        required=True,
        help="write-once context pathway evaluation JSON",
    )
    evaluation.add_argument(
        "--external-predictions",
        help="locked Arc H1 prediction artifact; enables the one-shot final gate",
    )
    evaluation.add_argument(
        "--external-bundle",
        help="Arc H1 context bundle whose source digest was sealed in the split",
    )
    evaluation.add_argument(
        "--development-evaluation",
        help="complete passed development evaluation required before Arc access",
    )
    evaluation.add_argument(
        "--external-access-lock",
        help="new path claimed before reading Arc labels; an existing path is refused",
    )


def _register_empirical_l0_experiment(commands) -> None:
    empirical_l0 = commands.add_parser(
        "empirical-l0-experiment",
        help="run the ADR-0038 empirical-response vs hard-clamp paired L0 matrix",
    )
    empirical_l0.add_argument(
        "--config",
        default="configs/multiscale_demo.json",
        help="multiscale scenario JSON",
    )
    empirical_l0.add_argument(
        "--matrix-config",
        default="configs/experiments/empirical_l0_comparison.json",
        help="frozen empirical L0 comparison protocol JSON",
    )
    empirical_l0.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    empirical_l0.add_argument(
        "--l0-config",
        default="configs/layers/l0_reference_grn.json",
        help="reference L0 GRN JSON (shared natural dynamics)",
    )
    empirical_l0.add_argument(
        "--l1-config",
        default="configs/layers/l1_reference_molecular.json",
        help="L1 coarse molecular model JSON",
    )
    empirical_l0.add_argument(
        "--l2-config",
        default="configs/layers/l2_reference_cell.json",
        help="L2 rule cell model JSON",
    )
    empirical_l0.add_argument(
        "--l3-config",
        default="configs/layers/l3_reference_tissue.json",
        help="L3 fixed-graph tissue model JSON",
    )
    empirical_l0.add_argument(
        "--l4-config",
        default="configs/layers/l4_reference_phenotype.json",
        help="L4 phenotype observer JSON",
    )
    empirical_l0.add_argument(
        "--empirical-l0-config",
        default="configs/layers/l0_empirical_response.json",
        help="empirical L0 response-table identity JSON",
    )
    empirical_l0.add_argument("--artifact-root", help="optional artifact root")



def _register_empirical_l0_schedule_experiment(commands) -> None:
    empirical_l0_schedule = commands.add_parser(
        "empirical-l0-schedule-experiment",
        help="run the ADR-0041 config-driven multi-unit/schedule paired L0 matrix",
    )
    empirical_l0_schedule.add_argument(
        "--config",
        default="configs/multiscale_demo.json",
        help="multiscale scenario JSON",
    )
    empirical_l0_schedule.add_argument(
        "--matrix-config",
        default="configs/experiments/empirical_l0_schedule.json",
        help="frozen schedule comparison protocol JSON",
    )
    empirical_l0_schedule.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    empirical_l0_schedule.add_argument(
        "--l0-config",
        default="configs/layers/l0_reference_grn.json",
        help="reference L0 GRN JSON (shared natural dynamics)",
    )
    empirical_l0_schedule.add_argument(
        "--l1-config",
        default="configs/layers/l1_reference_molecular.json",
        help="L1 coarse molecular model JSON",
    )
    empirical_l0_schedule.add_argument(
        "--l2-config",
        default="configs/layers/l2_reference_cell.json",
        help="L2 rule cell model JSON",
    )
    empirical_l0_schedule.add_argument(
        "--l3-config",
        default="configs/layers/l3_reference_tissue.json",
        help="L3 fixed-graph tissue model JSON",
    )
    empirical_l0_schedule.add_argument(
        "--l4-config",
        default="configs/layers/l4_reference_phenotype.json",
        help="L4 phenotype observer JSON",
    )
    empirical_l0_schedule.add_argument(
        "--empirical-l0-config",
        default="configs/layers/l0_empirical_response.json",
        help="empirical L0 response-table identity JSON",
    )
    empirical_l0_schedule.add_argument("--artifact-root", help="optional artifact root")



def _register_aivc_crosscheck(commands) -> None:
    crosscheck = commands.add_parser(
        "aivc-crosscheck",
        help="compare two Stage 1 profiles from independent source formats (ADR-0042)",
    )
    crosscheck.add_argument("--profile-a", required=True)
    crosscheck.add_argument("--profile-b", required=True)
    crosscheck.add_argument("--output", required=True)



def _register_carm_spatial_calibrate(commands) -> None:
    spatial_calibrate = commands.add_parser(
        "carm-spatial-calibrate",
        help="run the ADR-0043 calibration-subset L3 parameter selection",
    )
    spatial_calibrate.add_argument(
        "--target",
        default="data/spatial-carm/derived/carm-spatial-anchor-target.json",
        help="verified de-identified spatial target JSON",
    )
    spatial_calibrate.add_argument(
        "--protocol",
        default="configs/experiments/carm_spatial_anchor_protocol.json",
        help="frozen spatial-anchor protocol JSON",
    )
    spatial_calibrate.add_argument(
        "--calibration-config",
        default="configs/experiments/carm_spatial_calibration.json",
        help="frozen calibration search protocol JSON",
    )
    spatial_calibrate.add_argument(
        "--evaluation-config",
        default="configs/experiments/carm_spatial_anchor_evaluation.json",
        help="frozen spatial evaluation horizon/seed JSON",
    )
    spatial_calibrate.add_argument(
        "--config",
        default="configs/scenarios/carm/high_immune_her2.json",
        help="CAR-M scenario JSON",
    )
    spatial_calibrate.add_argument(
        "--runner-config",
        default="configs/runner_reference.json",
        help="multi-rate runner schedule and budget JSON",
    )
    spatial_calibrate.add_argument(
        "--spatial-config",
        default="configs/layers/l3_carm_spatial.json",
        help="reference spatial L3 JSON (incumbent)",
    )
    spatial_calibrate.add_argument(
        "--l0-config",
        default="configs/layers/l0_reference_grn.json",
        help="L0 discrete GRN JSON",
    )
    spatial_calibrate.add_argument(
        "--l1-config",
        default="configs/layers/l1_reference_molecular.json",
        help="L1 coarse molecular model JSON",
    )
    spatial_calibrate.add_argument(
        "--l4-config",
        default="configs/layers/l4_reference_phenotype.json",
        help="L4 phenotype observer JSON",
    )
    spatial_calibrate.add_argument("--artifact-root", help="optional artifact root")



def _register_carm_intervention_experiment(commands) -> None:
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



def _register_demo_export(commands) -> None:
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



def _register_lab_export(commands) -> None:
    lab_export = commands.add_parser(
        "lab-export",
        help="export deterministic competition virtual-lab catalog and bundles",
    )
    lab_export.add_argument(
        "--dose-playbook",
        default="artifacts/demo/carm-playbook.json",
        help="frozen CAR-M dose-response demo playbook JSON",
    )
    lab_export.add_argument(
        "--intervention-root",
        default=(
            "artifacts/carm-state-conditioned-intervention/"
            "state-intervention-0e92bb234ba3a840"
        ),
        help="saved state-conditioned intervention artifact directory",
    )
    lab_export.add_argument(
        "--spatial-root",
        default="artifacts/carm-spatial/carm-spatial-0f88408d1e44b25a",
        help="saved CAR-M spatial comparison artifact directory",
    )
    lab_export.add_argument(
        "--output-dir",
        default="web/public/lab-data",
        help="competition site lab-data output directory",
    )



def _register_collective_analyze(commands) -> None:
    collective = commands.add_parser(
        "collective-analyze",
        help="derive deterministic collective-dynamics proxies from a raw run",
    )
    collective.add_argument(
        "--input", required=True, help="formal MultirateRun JSON artifact"
    )
    collective.add_argument(
        "--cohort-map",
        help="optional complete Cell-id to cohort-name JSON mapping",
    )
    collective.add_argument(
        "--output", required=True, help="write-once collective dynamics JSON artifact"
    )



def _register_sten_smoke(commands) -> None:
    sten = commands.add_parser("sten-smoke", help="run the L3 STEN subsystem smoke test")
    sten.add_argument("--config", default="configs/demo.json", help="STEN scenario JSON")
    sten.add_argument("--ticks", type=int, help="override scenario tick count")



def _register_feedback_experiment(commands) -> None:
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



def _register_policy_experiment(commands) -> None:
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



def _register_latent_experiment(commands) -> None:
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



def _register_autolab(commands) -> None:
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



def _register_autolab_plan(commands) -> None:
    autolab_plan = commands.add_parser(
        "autolab-plan",
        help="compile or validate a closed Autolab plan without executing it",
    )
    autolab_plan.add_argument(
        "--autolab-config",
        default="configs/experiments/autolab_screen.json",
        help="frozen autolab hypothesis registry and protocol JSON",
    )
    autolab_plan.add_argument(
        "--plan",
        help="optional closed-schema plan JSON to validate instead of compiling",
    )
    autolab_plan.add_argument(
        "--artifact-root",
        help="optional root for write-once plan and verification artifacts",
    )



def _register_autolab_propose(commands) -> None:
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



def _register_data_check(commands) -> None:
    data_check = commands.add_parser(
        "data-check",
        help="verify every dataset registered in data/registry.json (fail-closed)",
    )
    data_check.add_argument(
        "--registry",
        default="data/registry.json",
        help="dataset registry JSON",
    )



def _register_topology_experiment(commands) -> None:
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



def _register_e3_experiment(commands) -> None:
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



def _register_closed_loop_experiment(commands) -> None:
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



def _register_neural_experiment(commands) -> None:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an M-GBA reference scenario")
    commands = parser.add_subparsers(dest="command", required=True)

    _register_run(commands)
    _register_simulate(commands)
    _register_experiment(commands)
    _register_report(commands)
    _register_run_report(commands)
    _register_evidence_report(commands)
    _register_carm_import(commands)
    _register_carm_experiment(commands)
    _register_carm_spatial_experiment(commands)
    _register_carm_spatial_ablation(commands)
    _register_spatial_anchor_build(commands)
    _register_spatial_source_adapt_field(commands)
    _register_spatial_source_adapt_neighborhood(commands)
    _register_spatial_anchor_check(commands)
    _register_carm_spatial_anchor_evaluate(commands)
    _register_aivc_perturbation_anchor(commands)
    _register_l0_training_evaluate(commands)
    _register_l0_response_table_build(commands)
    _register_hallmark_target_build(commands)
    _register_hallmark_training_evaluate(commands)
    _register_ood_split_build(commands)
    _register_context_pathway_evaluate(commands)
    _register_empirical_l0_experiment(commands)
    _register_empirical_l0_schedule_experiment(commands)
    _register_aivc_crosscheck(commands)
    _register_carm_spatial_calibrate(commands)
    _register_carm_intervention_experiment(commands)
    _register_demo_export(commands)
    _register_lab_export(commands)
    _register_collective_analyze(commands)
    _register_sten_smoke(commands)
    _register_feedback_experiment(commands)
    _register_policy_experiment(commands)
    _register_latent_experiment(commands)
    _register_autolab(commands)
    _register_autolab_plan(commands)
    _register_autolab_propose(commands)
    _register_data_check(commands)
    _register_topology_experiment(commands)
    _register_e3_experiment(commands)
    _register_closed_loop_experiment(commands)
    _register_neural_experiment(commands)
    return parser


def _cmd_run(args: argparse.Namespace) -> dict[str, Any]:
    scenario = load_multiscale_scenario(args.config)
    runner = ReferenceCrossScaleRunner(**_load_layer_models(args))
    result = summarize_trace(scenario, runner.run(scenario))
    return result


def _cmd_simulate(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_experiment(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_report(args: argparse.Namespace) -> dict[str, Any]:
    paths = build_causal_report(args.matrix_root, args.output_dir)
    report_manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    result = {
        "matrix_id": report_manifest["matrix_id"],
        "report_root": str(paths.root),
        "report_manifest": str(paths.manifest),
        "files": report_manifest["files"],
    }
    return result


def _cmd_run_report(args: argparse.Namespace) -> dict[str, Any]:
    paths = build_run_report(args.run, args.output_dir)
    report_manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    result = {
        "experiment_id": report_manifest["experiment_id"],
        "history_digest": report_manifest["history_digest"],
        "report_root": str(paths.root),
        "report_manifest": str(paths.manifest),
        "files": report_manifest["files"],
    }
    return result


def _cmd_evidence_report(args: argparse.Namespace) -> dict[str, Any]:
    if args.verify:
        result = verify_evidence_report(
            args.artifact_root, args.output, registry=args.registry
        )
        if not result["verified"]:
            raise SystemExit(
                "evidence report verification failed: "
                + "; ".join(result["mismatches"])
            )
        return result
    paths = build_evidence_report(
        args.artifact_root, args.output, registry=args.registry
    )
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    summary = json.loads(paths.summary.read_text(encoding="utf-8"))
    return {
        "report_root": str(paths.root),
        "report_manifest": str(paths.manifest),
        "summary": str(paths.summary),
        "html": str(paths.html),
        "sections": {
            section["section_id"]: section["status"]
            for section in summary["sections"]
        },
        "negative_findings": len(summary["negative_findings"]),
        "files": manifest["files"],
    }


def _cmd_carm_import(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_carm_experiment(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_carm_spatial_experiment(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_carm_spatial_ablation(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_spatial_source_adapt_field(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_spatial_source_adapt_neighborhood(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_spatial_anchor_build(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_spatial_anchor_check(args: argparse.Namespace) -> dict[str, Any]:
    target = verify_spatial_anchor_target(args.target)
    result = {
        "schema_version": target["schema_version"],
        "target_id": target["target_id"],
        "samples": len(target["samples"]),
        "distributions": len(target["distributions"]),
        "ok": True,
    }
    return result


def _cmd_carm_spatial_anchor_evaluate(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_carm_intervention_experiment(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_demo_export(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_lab_export(args: argparse.Namespace) -> dict[str, Any]:
    paths = export_competition_lab_data(
        output_dir=args.output_dir,
        dose_playbook=args.dose_playbook,
        intervention_root=args.intervention_root,
        spatial_root=args.spatial_root,
    )
    result = {name: str(path) for name, path in sorted(paths.items())}
    return result


def _cmd_l0_training_evaluate(args: argparse.Namespace) -> dict[str, Any]:
    evaluation = evaluate_training(
        load_response_predictions(args.predictions), args.profile
    )
    output = save_training_evaluation(evaluation, args.output)
    result = {
        "schema_version": evaluation["schema_version"],
        "evaluation_id": evaluation["evaluation_id"],
        "verdict": evaluation["pass_rule"]["verdict"],
        "reasons": evaluation["pass_rule"]["reasons"],
        "margin_vs_centroid": evaluation["pass_rule"]["margin_vs_centroid"],
        "margin_vs_ridge": evaluation["pass_rule"]["margin_vs_ridge"],
        "holdout_metrics": evaluation["metrics"]["holdout"],
        "output": str(output),
        "model_status": "offline-training-evaluation-not-a-runtime-change",
    }
    return result


def _cmd_l0_response_table_build(args: argparse.Namespace) -> dict[str, Any]:
    table = build_response_table(args.predictions, args.evaluation)
    output = save_response_table(table, args.output)
    result = {
        "schema_version": table["schema_version"],
        "table_id": table["table_id"],
        "units": len(table["units"]),
        "verdict": table["source"]["verdict"],
        "output": str(output),
        "model_status": "verified-distilled-response-table",
    }
    return result


def _cmd_hallmark_target_build(args: argparse.Namespace) -> dict[str, Any]:
    bundle = load_empirical_bundle(args.bundle)
    target = build_hallmark_targets(
        bundle,
        load_source_profile(args.profile),
        load_all_hallmark_memberships(
            args.hallmark, expected_sha256=bundle.hallmark_source["sha256"]
        ),
    )
    output = save_hallmark_target(target, args.output)
    result = {
        "schema_version": target["schema_version"],
        "target_id": target["target_id"],
        "dataset_id": target["dataset_id"],
        "dims": len(target["dims"]),
        "excluded_sets": target["excluded_sets"],
        "units": len(target["units"]),
        "split": target["split"],
        "output": str(output),
        "model_status": "offline-training-target-not-a-runtime-change",
    }
    return result

def _cmd_hallmark_training_evaluate(args: argparse.Namespace) -> dict[str, Any]:
    evaluation = evaluate_hallmark_training(
        load_hallmark_predictions(args.predictions), args.target
    )
    output = save_hallmark_training_evaluation(evaluation, args.output)
    result = {
        "schema_version": evaluation["schema_version"],
        "evaluation_id": evaluation["evaluation_id"],
        "arm": evaluation["arm"],
        "verdict": evaluation["pass_rule"]["verdict"],
        "reasons": evaluation["pass_rule"]["reasons"],
        "margin_vs_centroid": evaluation["pass_rule"]["margin_vs_centroid"],
        "margin_vs_ridge": evaluation["pass_rule"]["margin_vs_ridge"],
        "holdout_metrics": evaluation["metrics"]["six_node_head"]["holdout"],
        "output": str(output),
        "model_status": "offline-training-evaluation-not-a-runtime-change",
    }
    return result


def _cmd_ood_split_build(args: argparse.Namespace) -> dict[str, Any]:
    embeddings_path = Path(args.embeddings)
    try:
        table = json.loads(embeddings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid Geneformer embedding table: {error}") from error
    if (
        not isinstance(table, dict)
        or table.get("schema_version") != EMBEDDING_TABLE_SCHEMA_VERSION
        or table.get("embedding_dim") != EMBEDDING_DIM
        or not isinstance(table.get("embeddings"), dict)
        or not table["embeddings"]
    ):
        raise ValueError("expected a non-empty 768-dimensional Geneformer embedding table")
    for gene, vector in table["embeddings"].items():
        if not isinstance(gene, str) or not gene or not isinstance(vector, list) or len(vector) != EMBEDDING_DIM:
            raise ValueError("Geneformer embedding entries must be named 768-element vectors")
    manifest = build_ood_split_manifest(
        [load_context_bundle(path) for path in args.bundle],
        embedding_genes=list(table["embeddings"]),
        embedding_table_sha256=file_sha256(embeddings_path),
        external_labels_sha256=args.external_labels_sha256,
    )
    output = save_ood_split_manifest(manifest, args.output)
    return {
        "schema_version": manifest["schema_version"],
        "split_id": manifest["split_id"],
        "contexts": len(manifest["contexts"]),
        "source_shared_genes": len(
            manifest["feature_eligibility"]["source_shared_genes"]
        ),
        "embedding_excluded_genes": len(
            manifest["feature_eligibility"]["excluded_genes"]
        ),
        "shared_genes": len(manifest["shared_genes"]),
        "folds": len(manifest["folds"]),
        "external_test_status": manifest["external_test"]["status"],
        "output": str(output),
        "model_status": "locked-offline-ood-protocol-not-a-runtime-change",
    }


def _cmd_context_pathway_evaluate(args: argparse.Namespace) -> dict[str, Any]:
    external = (
        args.external_predictions,
        args.external_bundle,
        args.development_evaluation,
        args.external_access_lock,
    )
    if any(external) and not all(external):
        raise SystemExit(
            "external evaluation requires --external-predictions, --external-bundle, "
            "--development-evaluation, and --external-access-lock"
        )
    if all(external) and not args.predictions:
        raise SystemExit("external evaluation requires all development --predictions")
    if not all(external) and not args.predictions:
        raise SystemExit("development evaluation requires at least one --predictions")
    evaluation = (
        evaluate_external_context_pathway_predictions(
            args.external_predictions,
            args.external_bundle,
            args.development_evaluation,
            args.split,
            args.bundle,
            args.external_access_lock,
            args.predictions,
        )
        if all(external)
        else evaluate_context_pathway_predictions(
            [load_context_pathway_predictions(path) for path in args.predictions],
            args.split,
            args.bundle,
        )
    )
    output = save_context_pathway_evaluation(evaluation, args.output)
    return {
        "schema_version": evaluation["schema_version"],
        "evaluation_id": evaluation["evaluation_id"],
        "development_verdict": evaluation["pass_rule"]["development_verdict"],
        "paper_verdict": evaluation["pass_rule"]["paper_verdict"],
        "folds": evaluation["coverage"]["folds"],
        "external_test_status": evaluation["coverage"]["external_test_status"],
        "output": str(output),
        "model_status": "offline-ood-evaluation-not-a-runtime-change",
    }


def _cmd_empirical_l0_schedule_experiment(args: argparse.Namespace) -> dict[str, Any]:
    scenario = load_multiscale_scenario(args.config)
    schedule_config = load_empirical_l0_schedule_config(args.matrix_config)
    runner_config = load_runner_config(args.runner_config)
    empirical_identity = load_empirical_l0_config(args.empirical_l0_config)
    table = load_response_table(
        empirical_identity["response_table_path"],
        expected_sha256=empirical_identity["response_table_sha256"],
    )
    baseline_models = _load_layer_models(args)
    empirical_models = dict(baseline_models)
    empirical_models["genome_model"] = EmpiricalResponseGrnModel(
        load_grn_config(args.l0_config),
        response_table=table,
        table_path=empirical_identity["response_table_path"],
    )
    matrix = EmpiricalL0ScheduleRunner(
        schedule_config,
        baseline_runner=MultirateCrossScaleRunner(
            runner_config, **baseline_models
        ),
        empirical_runner=MultirateCrossScaleRunner(
            runner_config, **empirical_models
        ),
    ).run(scenario)
    result = matrix.summary_dict()
    result["model_status"] = "reference-model-not-validated-biological-model"
    if args.artifact_root:
        result["artifacts"] = {
            name: str(path)
            for name, path in save_empirical_l0_schedule_artifacts(
                args.artifact_root, matrix
            ).items()
        }
    return result


def _cmd_empirical_l0_experiment(args: argparse.Namespace) -> dict[str, Any]:
    scenario = load_multiscale_scenario(args.config)
    comparison_config = load_empirical_l0_comparison_config(args.matrix_config)
    runner_config = load_runner_config(args.runner_config)
    empirical_identity = load_empirical_l0_config(args.empirical_l0_config)
    table = load_response_table(
        empirical_identity["response_table_path"],
        expected_sha256=empirical_identity["response_table_sha256"],
    )
    baseline_models = _load_layer_models(args)
    empirical_models = dict(baseline_models)
    empirical_models["genome_model"] = EmpiricalResponseGrnModel(
        load_grn_config(args.l0_config),
        response_table=table,
        table_path=empirical_identity["response_table_path"],
    )
    matrix = EmpiricalL0ComparisonRunner(
        comparison_config,
        baseline_runner=MultirateCrossScaleRunner(
            runner_config, **baseline_models
        ),
        empirical_runner=MultirateCrossScaleRunner(
            runner_config, **empirical_models
        ),
    ).run(scenario)
    result = matrix.summary_dict()
    result["model_status"] = "reference-model-not-validated-biological-model"
    if args.artifact_root:
        result["artifacts"] = {
            name: str(path)
            for name, path in save_empirical_l0_artifacts(
                args.artifact_root, matrix
            ).items()
        }
    return result


def _cmd_carm_spatial_calibrate(args: argparse.Namespace) -> dict[str, Any]:
    target = verify_spatial_anchor_target(args.target)
    if target.get("target_id") in CONSUMED_CONFIRMATION_TARGET_IDS:
        raise ValueError(
            "spatial calibration confirmation target was already consumed; "
            "provide a new untouched target"
        )
    anchor_protocol = load_spatial_anchor_protocol(args.protocol)
    compiled = compile_carm_scenario(load_carm_scenario_config(args.config))
    runner_config = load_runner_config(args.runner_config)
    base_spatial_config = load_carm_spatial_config(args.spatial_config)
    evaluation_config = load_spatial_anchor_evaluation_config(args.evaluation_config)
    protocol = load_calibration_protocol(args.calibration_config)

    def _confirm(point):
        candidate = replace(base_spatial_config, **point_to_overrides(point))
        runners = build_carm_spatial_runners(
            compiled,
            runner_config=runner_config,
            spatial_config=candidate,
            l0_config=args.l0_config,
            l1_config=args.l1_config,
            l4_config=args.l4_config,
        )
        evaluation = SpatialAnchorEvaluator(
            evaluation_config,
            runner=runners["spatial_field"],
            protocol=anchor_protocol,
        ).evaluate(compiled, target=target)
        role_means = {
            role.role: role.mean_normalized_absolute_error
            for role in evaluation.score.role_scores
        }
        return {
            "evaluation_id": evaluation.evaluation_id,
            "best_point": point_to_overrides(point),
            "calibration_mean_nae": role_means["calibration"],
            "holdout_mean_nae": role_means["holdout"],
            "external_validation_mean_nae": role_means["external_validation"],
        }

    outcome = run_spatial_calibration(
        protocol,
        make_spatial_objective(
            compiled=compiled,
            target=target,
            anchor_protocol=anchor_protocol,
            evaluation_config=evaluation_config,
            runner_config=runner_config,
            base_spatial_config=base_spatial_config,
            l0_config=args.l0_config,
            l1_config=args.l1_config,
            l4_config=args.l4_config,
        ),
        reference_point=reference_box_point(base_spatial_config),
        confirm=_confirm,
    )
    result = outcome.as_dict()
    result["model_status"] = "calibration-diagnosis-not-a-validation"
    if args.artifact_root:
        paths = save_spatial_calibration_artifacts(args.artifact_root, outcome)
        result["artifact_summary"] = str(paths["summary"])
    return result


def _cmd_aivc_crosscheck(args: argparse.Namespace) -> dict[str, Any]:
    result = compare_profiles(
        load_profile_for_crosscheck(args.profile_a),
        load_profile_for_crosscheck(args.profile_b),
    )
    output = save_crosscheck(result, args.output)
    result = {
        "schema_version": result["schema_version"],
        "crosscheck_id": result["crosscheck_id"],
        "verdict": result["verdict"],
        "shared_units": result["shared_units"],
        "metrics": result["metrics"],
        "output": str(output),
        "model_status": "reproducibility-check-not-a-validation",
    }
    return result


def _cmd_aivc_perturbation_anchor(args: argparse.Namespace) -> dict[str, Any]:
    bundle = load_empirical_bundle(args.bundle)
    profile = build_perturbation_profile(
        bundle,
        load_hallmark_memberships(
            args.hallmark, expected_sha256=bundle.hallmark_source["sha256"]
        ),
        salt=args.salt if args.salt is not None else SPLIT_SALT,
    )
    output = save_perturbation_profile(profile, args.output)
    payload = profile.as_dict()
    result = {
        "schema_version": payload["schema_version"],
        "profile_id": payload["profile_id"],
        "units": len(payload["units"]),
        "split": payload["split"],
        "metrics_summary": payload["metrics_summary"],
        "output": str(output),
        "model_status": "reference-model-empirical-profile-not-a-validation",
    }
    return result


def _cmd_collective_analyze(args: argparse.Namespace) -> dict[str, Any]:
    report = analyze_collective_dynamics_raw(
        load_raw_run_mapping(args.input),
        None if args.cohort_map is None else load_cohort_map(args.cohort_map),
        # ADR-0031 fixes the CLI grammar; thresholds always come from the frozen default.
        load_collective_dynamics_config("configs/experiments/collective_dynamics.json"),
    )
    output = save_collective_dynamics_artifact(args.output, report)
    result = {
        "schema_version": report.as_dict()["schema_version"],
        "observer_version": report.as_dict()["observer_version"],
        "source_experiment_id": report.source_experiment_id,
        "source_history_digest": report.source_history_digest,
        "config_digest": report.config.config_digest,
        "report_digest": report.report_digest,
        "cohorts": [item.cohort_id for item in report.cohorts],
        "output": str(output),
        "model_status": "reference-proxy-observer-not-a-physical-phase-model",
    }
    return result


def _cmd_feedback_experiment(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_policy_experiment(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_latent_experiment(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_autolab(args: argparse.Namespace) -> dict[str, Any]:
    scenario = load_multiscale_scenario(args.config)
    autolab_config = load_autolab_config(args.autolab_config)
    plan = compile_autolab_plan(autolab_config)
    preflight = verify_autolab_plan(plan, autolab_config)
    if not preflight.valid:
        raise SystemExit("frozen Autolab plan failed preflight verification")
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
            comparison = compare_runs(
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
    manifest = build_autolab_manifest(session)
    verification = verify_autolab_result(
        plan,
        session,
        manifest,
        registry=autolab_config,
        claim_level="reference_model",
    )
    if not verification.fully_verified:
        raise SystemExit("Autolab result failed manifest/history verification")
    result = session.summary_dict()
    result["model_status"] = "reference-model-not-validated-biological-model"
    result["control_plane"] = {
        "plan_id": plan.plan_id,
        "verification": verification.summary_dict(),
    }
    if args.artifact_root:
        paths = save_autolab_artifacts(args.artifact_root, session)
        control_root = paths["root"] / "control"
        plan_path = save_autolab_plan(control_root / "plan.json", plan)
        verification_path = save_verification_report(
            control_root / "verification.json", verification
        )
        result["artifact_root"] = str(paths["root"])
        result["artifact_manifest"] = str(paths["manifest"])
        result["artifact_summary"] = str(paths["summary"])
        result["control_plane"]["plan_artifact"] = str(plan_path)
        result["control_plane"]["verification_artifact"] = str(
            verification_path
        )
    return result


def _cmd_autolab_plan(args: argparse.Namespace) -> dict[str, Any]:
    registry = load_autolab_config(args.autolab_config)
    if args.plan:
        try:
            candidate = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit(f"invalid Autolab plan file: {error}") from error
    else:
        candidate = compile_autolab_plan(registry)
    verification = verify_autolab_plan(candidate, registry)
    plan_payload = (
        candidate.as_dict()
        if isinstance(candidate, AutolabPlan)
        else candidate
    )
    result = {
        "schema_version": "mgba-autolab-plan-bundle-0.1",
        "executed": False,
        "plan": plan_payload,
        "verification": verification.summary_dict(),
    }
    if verification.valid and args.artifact_root:
        parsed_plan = (
            candidate
            if isinstance(candidate, AutolabPlan)
            else AutolabPlan.from_dict(candidate)
        )
        control_root = Path(args.artifact_root) / parsed_plan.plan_id
        plan_path = save_autolab_plan(control_root / "plan.json", parsed_plan)
        verification_path = save_verification_report(
            control_root / "verification.json", verification
        )
        result["artifact_root"] = str(control_root)
        result["plan_artifact"] = str(plan_path)
        result["verification_artifact"] = str(verification_path)
    if not verification.valid:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        raise SystemExit(1)
    return result


def _cmd_autolab_propose(args: argparse.Namespace) -> dict[str, Any]:
    registry = load_autolab_config(args.autolab_config)
    proposals = load_proposal_file(args.proposals)
    result = validate_proposals(
        proposals,
        registry_ids=[item.hypothesis_id for item in registry.hypotheses],
    ).summary_dict()
    return result


def _cmd_data_check(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_topology_experiment(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_e3_experiment(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_closed_loop_experiment(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_neural_experiment(args: argparse.Namespace) -> dict[str, Any]:
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
    return result


def _cmd_sten_smoke(args: argparse.Namespace) -> dict[str, Any]:
    if args.ticks is not None and args.ticks < 1:
        raise SystemExit("--ticks must be positive")
    result = run_scenario(load_scenario(args.config), ticks=args.ticks)
    return result


_COMMAND_HANDLERS: dict[str, Callable[[argparse.Namespace], dict[str, Any]]] = {
    "run": _cmd_run,
    "simulate": _cmd_simulate,
    "experiment": _cmd_experiment,
    "report": _cmd_report,
    "run-report": _cmd_run_report,
    "evidence-report": _cmd_evidence_report,
    "carm-import": _cmd_carm_import,
    "carm-experiment": _cmd_carm_experiment,
    "carm-spatial-experiment": _cmd_carm_spatial_experiment,
    "carm-spatial-ablation": _cmd_carm_spatial_ablation,
    "spatial-source-adapt-field": _cmd_spatial_source_adapt_field,
    "spatial-source-adapt-neighborhood": _cmd_spatial_source_adapt_neighborhood,
    "spatial-anchor-build": _cmd_spatial_anchor_build,
    "spatial-anchor-check": _cmd_spatial_anchor_check,
    "carm-spatial-anchor-evaluate": _cmd_carm_spatial_anchor_evaluate,
    "carm-intervention-experiment": _cmd_carm_intervention_experiment,
    "demo-export": _cmd_demo_export,
    "lab-export": _cmd_lab_export,
    "l0-training-evaluate": _cmd_l0_training_evaluate,
    "l0-response-table-build": _cmd_l0_response_table_build,
    "hallmark-target-build": _cmd_hallmark_target_build,
    "hallmark-training-evaluate": _cmd_hallmark_training_evaluate,
    "ood-split-build": _cmd_ood_split_build,
    "context-pathway-evaluate": _cmd_context_pathway_evaluate,
    "empirical-l0-schedule-experiment": _cmd_empirical_l0_schedule_experiment,
    "empirical-l0-experiment": _cmd_empirical_l0_experiment,
    "carm-spatial-calibrate": _cmd_carm_spatial_calibrate,
    "aivc-crosscheck": _cmd_aivc_crosscheck,
    "aivc-perturbation-anchor": _cmd_aivc_perturbation_anchor,
    "collective-analyze": _cmd_collective_analyze,
    "feedback-experiment": _cmd_feedback_experiment,
    "policy-experiment": _cmd_policy_experiment,
    "latent-experiment": _cmd_latent_experiment,
    "autolab": _cmd_autolab,
    "autolab-plan": _cmd_autolab_plan,
    "autolab-propose": _cmd_autolab_propose,
    "data-check": _cmd_data_check,
    "topology-experiment": _cmd_topology_experiment,
    "e3-experiment": _cmd_e3_experiment,
    "closed-loop-experiment": _cmd_closed_loop_experiment,
    "neural-experiment": _cmd_neural_experiment,
    "sten-smoke": _cmd_sten_smoke,
}


def main() -> None:
    args = build_parser().parse_args()
    result = _COMMAND_HANDLERS[args.command](args)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
