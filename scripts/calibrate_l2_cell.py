"""L2 CellConfig calibration experiment (ADR-0018).

Pre-registered protocol
-----------------------

* **Search space**: the 19 scalar ``CellConfig`` fields
  (``mgba.calibration.L2_SCALAR_PARAMETERS``), unit box ``[0, 1]^19``;
  ``model_version`` and ``secretion_multipliers`` stay frozen at the
  reference values.
* **Objective**: ``PhenotypeWindow.mean_homeostasis`` of a 60-tick
  deterministic run on the training scenario
  (``configs/multiscale_demo.json``).  Outcome class is reported but
  never enters the scalar objective.
* **Search**: 512 sha256-seeded uniform candidates + coordinate
  refinement from the top 3 (steps 0.1/0.05, up to 4 sweeps).  The
  frozen reference vector is always the first evaluation, so the
  training result can never be worse than the reference.
* **Holdout**: the four synthetic stress regimes
  (``data/synthetic-feedback``, calm/injury/severe/collapse), same
  deterministic chain, same horizon.  Verdict, fixed before any run:
  ``generalized`` if the calibrated config improves mean homeostasis
  on every regime, ``not-generalized`` if on none, else ``mixed``.

The frozen reference config is never modified; the calibrated vector
is written only into the artifact directory with full provenance.
Both positive and negative results are recorded (AGENTS.md §4).

Usage (from the repository root, inside the project venv):

    python scripts/calibrate_l2_cell.py
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mgba.calibration import (  # noqa: E402
    L2_SCALAR_PARAMETERS,
    CalibrationProtocol,
    run_search,
    save_calibration_artifacts,
)
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config  # noqa: E402
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config  # noqa: E402
from mgba.layers.l2 import (  # noqa: E402
    CellConfig,
    CellStateMachineModel,
    load_cell_config,
)
from mgba.layers.l3 import TissueEnvironmentModel, load_tissue_config  # noqa: E402
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config  # noqa: E402
from mgba.multiscale import load_multiscale_scenario  # noqa: E402
from mgba.runner import MultirateCrossScaleRunner, load_runner_config  # noqa: E402

LAYER_CONFIGS = PROJECT_ROOT / "configs" / "layers"
DATASET_ROOT = PROJECT_ROOT / "data" / "synthetic-feedback"
CALIBRATED_MODEL_VERSION = "calibrated-l2-cell-state-machine-0.1"
L4_METRICS = (
    "vitality",
    "damage_burden",
    "inflammation",
    "homeostasis",
    "recovery_capacity",
)


def _base_models(cell_config: CellConfig) -> dict[str, Any]:
    return {
        "genome_model": DiscreteGrnModel(
            load_grn_config(LAYER_CONFIGS / "l0_reference_grn.json")
        ),
        "molecular_model": CoarseMolecularModel(
            load_molecular_config(LAYER_CONFIGS / "l1_reference_molecular.json")
        ),
        "cell_model": CellStateMachineModel(cell_config),
        "tissue_model": TissueEnvironmentModel(
            load_tissue_config(LAYER_CONFIGS / "l3_reference_tissue.json")
        ),
        "phenotype_model": PhenotypeObserverModel(
            load_phenotype_config(LAYER_CONFIGS / "l4_reference_phenotype.json")
        ),
    }


def _run_window(
    *, cell_config: CellConfig, scenario_path: Path, runner_config, ticks: int
):
    scenario = load_multiscale_scenario(scenario_path)
    runner = MultirateCrossScaleRunner(
        runner_config, **_base_models(cell_config)
    )
    return runner.run(scenario, ticks=ticks)


def run_calibration(
    *,
    protocol: CalibrationProtocol,
    scenario_path: Path,
    artifact_root: Path,
) -> dict[str, Any]:
    runner_config = load_runner_config(
        PROJECT_ROOT / "configs" / "runner_reference.json"
    )
    reference_config = load_cell_config(LAYER_CONFIGS / "l2_reference_cell.json")
    reference_point = tuple(
        getattr(reference_config, name) for name in L2_SCALAR_PARAMETERS
    )

    def objective(point: tuple[float, ...]) -> float:
        candidate_config = replace(
            reference_config,
            model_version=CALIBRATED_MODEL_VERSION,
            **dict(zip(L2_SCALAR_PARAMETERS, point, strict=True)),
        )
        run = _run_window(
            cell_config=candidate_config,
            scenario_path=scenario_path,
            runner_config=runner_config,
            ticks=protocol.ticks,
        )
        return run.phenotype_window.mean_homeostasis

    result = run_search(protocol, objective, incumbents=(reference_point,))
    reference_train_score = result.evaluations[0].score
    best_config = replace(
        reference_config,
        model_version=CALIBRATED_MODEL_VERSION,
        **result.best_mapping(),
    )

    manifest_path = DATASET_ROOT / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(
            f"synthetic dataset not found at {DATASET_ROOT}; "
            "run scripts/synthetic_feedback_benchmark.py generate first"
        )
    dataset_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    holdout_rows: list[dict[str, Any]] = []
    for entry in dataset_manifest["scenarios"]:
        holdout_path = DATASET_ROOT / entry["path"]
        for label, config in (("reference", reference_config), ("calibrated", best_config)):
            run = _run_window(
                cell_config=config,
                scenario_path=holdout_path,
                runner_config=runner_config,
                ticks=protocol.ticks,
            )
            terminal = run.terminal_observation
            holdout_rows.append(
                {
                    "scenario_id": entry["scenario_id"],
                    "regime": entry["regime"],
                    "config": label,
                    "mean_homeostasis": run.phenotype_window.mean_homeostasis,
                    "outcome": run.phenotype_window.outcome.value,
                    **{
                        f"final_{metric}": getattr(terminal, metric)
                        for metric in L4_METRICS
                    },
                }
            )

    deltas = []
    for entry in dataset_manifest["scenarios"]:
        pair = {
            row["config"]: row
            for row in holdout_rows
            if row["scenario_id"] == entry["scenario_id"]
        }
        deltas.append(
            pair["calibrated"]["mean_homeostasis"]
            - pair["reference"]["mean_homeostasis"]
        )
    if all(delta > 0.0 for delta in deltas):
        verdict = "generalized"
    elif all(delta <= 0.0 for delta in deltas):
        verdict = "not-generalized"
    else:
        verdict = "mixed"

    paths = save_calibration_artifacts(artifact_root, result)
    root = paths["root"]

    config_payload = {
        "model_version": CALIBRATED_MODEL_VERSION,
        "provenance": {
            "search_digest": result.search_digest,
            "protocol": result.summary_dict()["protocol"],
            "train_scenario": scenario_path.name,
            "train_reference_score": reference_train_score,
            "train_best_score": result.best_score,
            "holdout_verdict": verdict,
        },
        **result.best_mapping(),
        "secretion_multipliers": {
            phase.value: value
            for phase, value in reference_config.secretion_multipliers
        },
    }
    calibrated_config_path = root / "calibrated_l2_cell.json"
    if calibrated_config_path.exists():
        if json.loads(calibrated_config_path.read_text(encoding="utf-8")) != config_payload:
            raise ValueError("refusing to overwrite a different calibrated config")
    else:
        calibrated_config_path.write_text(
            json.dumps(config_payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

    csv_path = root / "holdout.csv"
    fieldnames = (
        "scenario_id",
        "regime",
        "config",
        "mean_homeostasis",
        "outcome",
        *(f"final_{metric}" for metric in L4_METRICS),
    )
    rows_text = []
    with csv_path.open("w", encoding="utf-8", newline="\n") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in holdout_rows:
            writer.writerow({key: row[key] for key in fieldnames})
            rows_text.append(row)

    holdout_payload = {
        "schema_version": "mgba-calibration-artifact-0.1",
        "search_digest": result.search_digest,
        "dataset": "data/synthetic-feedback",
        "verdict": verdict,
        "mean_homeostasis_delta": sum(deltas) / len(deltas),
        "per_regime_delta": dict(
            zip((entry["regime"] for entry in dataset_manifest["scenarios"]), deltas)
        ),
        "rows": holdout_rows,
    }
    holdout_path = root / "holdout.json"
    if holdout_path.exists():
        if json.loads(holdout_path.read_text(encoding="utf-8")) != holdout_payload:
            raise ValueError("refusing to overwrite a different holdout artifact")
    else:
        holdout_path.write_text(
            json.dumps(holdout_payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

    return {
        "artifact_root": str(root),
        "search_digest": result.search_digest,
        "evaluation_count": len(result.evaluations),
        "train_reference_score": reference_train_score,
        "train_best_score": result.best_score,
        "train_improvement": result.best_score - reference_train_score,
        "holdout_verdict": verdict,
        "holdout_mean_homeostasis_delta": sum(deltas) / len(deltas),
        "calibrated_config": str(calibrated_config_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--search-seed", type=int, default=20260821)
    parser.add_argument("--candidates", type=int, default=512)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--max-sweeps", type=int, default=4)
    parser.add_argument("--ticks", type=int, default=60)
    parser.add_argument(
        "--scenario",
        default=str(PROJECT_ROOT / "configs" / "multiscale_demo.json"),
        help="training scenario JSON",
    )
    parser.add_argument(
        "--artifact-root",
        default=str(PROJECT_ROOT / "artifacts" / "calibration-l2"),
        help="calibration artifact root",
    )
    args = parser.parse_args()
    protocol = CalibrationProtocol(
        model_version="l2-cell-calibration-0.1",
        search_seed=args.search_seed,
        candidate_count=args.candidates,
        top_k=args.top_k,
        refinement_steps=(0.1, 0.05),
        max_sweeps=args.max_sweeps,
        ticks=args.ticks,
        parameter_names=L2_SCALAR_PARAMETERS,
    )
    result = run_calibration(
        protocol=protocol,
        scenario_path=Path(args.scenario),
        artifact_root=Path(args.artifact_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
