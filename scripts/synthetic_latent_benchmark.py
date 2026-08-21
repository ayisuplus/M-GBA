"""Synthetic benchmark for the L2 rule-vs-latent-cell policy comparison.

Reuses the deterministic synthetic scenario dataset from
``synthetic_feedback_benchmark.generate_dataset`` (creating it on demand)
and runs the paired L2 policy matrix (frozen rule state machine vs the
continuous latent-state "virtual cell" policy) on every scenario,
aggregating per-condition final L4 outcomes into CSV + JSON artifacts.

Usage (from the repository root, inside the project venv):

    python scripts/synthetic_latent_benchmark.py generate   # dataset (idempotent)
    python scripts/synthetic_latent_benchmark.py run
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from synthetic_feedback_benchmark import (  # noqa: E402
    DATA_ROOT,
    L4_METRICS,
    _layer_models,
    _sha256,
    _write_json_once,
    generate_dataset,
)

from mgba.layers.l2 import CellStateMachineModel, load_cell_config  # noqa: E402
from mgba.layers.l2_latent import (  # noqa: E402
    LatentCellModel,
    load_latent_cell_config,
)
from mgba.multiscale import load_multiscale_scenario  # noqa: E402
from mgba.latent_experiments import (  # noqa: E402
    LatentExperimentConfig,
    LatentExperimentRunner,
)
from mgba.runner import MultirateCrossScaleRunner, load_runner_config  # noqa: E402


def _latent_runners() -> dict[str, MultirateCrossScaleRunner]:
    runner_config = load_runner_config(
        PROJECT_ROOT / "configs" / "runner_reference.json"
    )
    layer_configs = PROJECT_ROOT / "configs" / "layers"
    rule_models = _layer_models()
    rule_models["cell_model"] = CellStateMachineModel(
        load_cell_config(layer_configs / "l2_reference_cell.json")
    )
    latent_models = _layer_models()
    latent_models["cell_model"] = LatentCellModel(
        load_latent_cell_config(layer_configs / "l2_latent_cell.json")
    )
    return {
        "rule_policy": MultirateCrossScaleRunner(runner_config, **rule_models),
        "latent_cell_policy": MultirateCrossScaleRunner(
            runner_config, **latent_models
        ),
    }


def run_benchmark(
    *, dataset_root: Path, artifact_root: Path, ticks: int, seeds: tuple[int, ...]
) -> dict[str, Any]:
    spec_path = dataset_root / "benchmark_spec.json"
    if not spec_path.exists():
        raise ValueError(
            f"dataset not found at {dataset_root}; run the generate command first"
        )
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    config = LatentExperimentConfig(
        model_version="synthetic-l2-latent-benchmark-0.1",
        ticks=ticks,
        seeds=seeds,
    )
    runners = _latent_runners()

    rows: list[dict[str, Any]] = []
    scenario_digests = []
    for entry in spec["scenarios"]:
        scenario_path = dataset_root / entry["path"]
        if _sha256(scenario_path) != entry["sha256"]:
            raise ValueError(f"scenario file drifted from manifest: {scenario_path}")
        scenario = load_multiscale_scenario(scenario_path)
        matrix = LatentExperimentRunner(config, runners=runners).run(scenario)
        scenario_digests.append((entry["scenario_id"], matrix.matrix_id))
        for record in matrix.records:
            terminal = record.run.terminal_observation
            rows.append(
                {
                    "scenario_id": entry["scenario_id"],
                    "regime": entry["regime"],
                    "matrix_id": matrix.matrix_id,
                    "condition_id": record.condition_id,
                    "seed": record.seed,
                    "outcome": record.run.phenotype_window.outcome.value,
                    "mean_homeostasis": record.run.phenotype_window.mean_homeostasis,
                    **{
                        f"final_{metric}": getattr(terminal, metric)
                        for metric in L4_METRICS
                    },
                }
            )

    output_dir = artifact_root / "synthetic-latent-benchmark"
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "latent-benchmark-results.csv"
    fieldnames = (
        "scenario_id",
        "regime",
        "matrix_id",
        "condition_id",
        "seed",
        "outcome",
        "mean_homeostasis",
        *(f"final_{metric}" for metric in L4_METRICS),
    )
    with csv_path.open("w", encoding="utf-8", newline="\n") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in fieldnames})

    summary: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["regime"], row["condition_id"])
        bucket = summary.setdefault(
            key,
            {
                "runs": 0,
                "outcomes": {},
                "mean_final_homeostasis": 0.0,
                "mean_final_inflammation": 0.0,
                "mean_final_vitality": 0.0,
            },
        )
        bucket["runs"] += 1
        bucket["outcomes"][row["outcome"]] = (
            bucket["outcomes"].get(row["outcome"], 0) + 1
        )
        bucket["mean_final_homeostasis"] += row["final_homeostasis"]
        bucket["mean_final_inflammation"] += row["final_inflammation"]
        bucket["mean_final_vitality"] += row["final_vitality"]
    for bucket in summary.values():
        for metric in (
            "mean_final_homeostasis",
            "mean_final_inflammation",
            "mean_final_vitality",
        ):
            bucket[metric] = round(bucket[metric] / bucket["runs"], 6)

    summary_payload = {
        "schema_version": "mgba-synthetic-latent-benchmark-0.1",
        "spec_sha256": _sha256(spec_path),
        "config": {"ticks": ticks, "seeds": list(seeds)},
        "scenario_matrices": dict(scenario_digests),
        "summary": [
            {"regime": regime, "condition_id": condition, **bucket}
            for (regime, condition), bucket in sorted(summary.items())
        ],
        "csv": csv_path.name,
    }
    _write_json_once(output_dir / "latent-benchmark-summary.json", summary_payload)
    return {
        "output_root": str(output_dir),
        "csv": str(csv_path),
        "summary": str(output_dir / "latent-benchmark-summary.json"),
        "rows": len(rows),
        "scenarios": len(scenario_digests),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser(
        "generate", help="write the deterministic synthetic scenario dataset"
    )
    generate.add_argument("--seed", type=int, default=2026, help="dataset seed")
    generate.add_argument("--cells", type=int, default=12, help="cells per scenario")
    generate.add_argument("--chords", type=int, default=4, help="random chords per ring")
    generate.add_argument("--ticks", type=int, default=60, help="dataset spec horizon")
    generate.add_argument(
        "--output-dir", default=str(DATA_ROOT), help="dataset output root"
    )

    run = commands.add_parser(
        "run", help="execute the L2 latent-policy benchmark over the dataset"
    )
    run.add_argument(
        "--dataset-dir", default=str(DATA_ROOT), help="generated dataset root"
    )
    run.add_argument(
        "--artifact-root",
        default=str(PROJECT_ROOT / "artifacts"),
        help="benchmark artifact root",
    )
    run.add_argument("--ticks", type=int, default=30, help="latent matrix horizon")
    run.add_argument(
        "--seeds", type=int, nargs="+", default=[7, 42, 1337], help="matrix seeds"
    )

    args = parser.parse_args()
    if args.command == "generate":
        result = generate_dataset(
            seed=args.seed,
            cells=args.cells,
            chords=args.chords,
            ticks=args.ticks,
            seeds=(7, 42, 1337),
            output_root=Path(args.output_dir),
        )
    else:
        result = run_benchmark(
            dataset_root=Path(args.dataset_dir),
            artifact_root=Path(args.artifact_root),
            ticks=args.ticks,
            seeds=tuple(sorted(set(args.seeds))),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
