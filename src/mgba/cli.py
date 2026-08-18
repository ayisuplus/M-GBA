from __future__ import annotations

import argparse
import json

from .experiments import (
    CausalExperimentRunner,
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
from .runner import (
    MultirateCrossScaleRunner,
    load_checkpoint,
    load_runner_config,
    save_checkpoint,
    save_run_artifact,
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

    sten = commands.add_parser("sten-smoke", help="run the L3 STEN subsystem smoke test")
    sten.add_argument("--config", default="configs/demo.json", help="STEN scenario JSON")
    sten.add_argument("--ticks", type=int, help="override scenario tick count")
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
    else:
        if args.ticks is not None and args.ticks < 1:
            raise SystemExit("--ticks must be positive")
        result = run_scenario(load_scenario(args.config), ticks=args.ticks)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
