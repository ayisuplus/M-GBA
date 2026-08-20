"""Synthetic benchmark for the stochastic closed-loop feedback matrix.

Reuses the deterministic synthetic scenario dataset from
``synthetic_feedback_benchmark.generate_dataset`` (creating it on demand)
and runs the three-condition closed-loop matrix (stochastic open loop,
stochastic closed loop, deterministic closed loop) on every scenario,
aggregating per-condition stability grades and final L4 outcomes into
CSV + JSON artifacts.

Usage (from the repository root, inside the project venv):

    python scripts/synthetic_closed_loop_benchmark.py generate   # dataset
    python scripts/synthetic_closed_loop_benchmark.py run
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

from mgba.closed_loop_experiments import (  # noqa: E402
    ClosedLoopExperimentConfig,
    ClosedLoopExperimentRunner,
)
from mgba.feedback import load_feedback_config  # noqa: E402
from mgba.layers.l0_noisy import load_noisy_grn_config  # noqa: E402
from mgba.multiscale import load_multiscale_scenario  # noqa: E402
from mgba.runner import load_runner_config  # noqa: E402


def run_benchmark(
    *, dataset_root: Path, artifact_root: Path, ticks: int, seeds: tuple[int, ...]
) -> dict[str, Any]:
    spec_path = dataset_root / "benchmark_spec.json"
    if not spec_path.exists():
        raise ValueError(
            f"dataset not found at {dataset_root}; run the generate command first"
        )
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    config = ClosedLoopExperimentConfig(
        model_version="synthetic-closed-loop-benchmark-0.1",
        ticks=ticks,
        seeds=seeds,
        sign_change_min=2,
        amplitude_min=0.01,
        lock_std_max=0.002,
        recovery_delta_min=0.05,
        recovery_homeostasis_min=0.6,
        deterioration_delta_min=0.05,
    )
    runner_config = load_runner_config(
        PROJECT_ROOT / "configs" / "runner_reference.json"
    )
    layer_configs = PROJECT_ROOT / "configs" / "layers"
    grn_config, noise_sigma = load_noisy_grn_config(
        layer_configs / "l0_noisy_grn.json"
    )
    feedback_config = load_feedback_config(
        layer_configs / "l4_feedback_controller.json"
    )
    layer_models = _layer_models()

    rows: list[dict[str, Any]] = []
    grade_counts: dict[str, int] = {}
    condition_grade_counts: dict[tuple[str, str], int] = {}
    scenario_digests = []
    for entry in spec["scenarios"]:
        scenario_path = dataset_root / entry["path"]
        if _sha256(scenario_path) != entry["sha256"]:
            raise ValueError(f"scenario file drifted from manifest: {scenario_path}")
        scenario = load_multiscale_scenario(scenario_path)
        matrix = ClosedLoopExperimentRunner(
            config,
            runner_config=runner_config,
            layer_models=layer_models,
            feedback_config=feedback_config,
            noisy_grn_config=grn_config,
            noise_sigma=noise_sigma,
        ).run(scenario)
        scenario_digests.append((entry["scenario_id"], matrix.matrix_id))
        for item in matrix.stability:
            grade_counts[item.grade] = grade_counts.get(item.grade, 0) + 1
            key = (item.condition_id, item.grade)
            condition_grade_counts[key] = condition_grade_counts.get(key, 0) + 1
            rows.append(
                {
                    "scenario_id": entry["scenario_id"],
                    "regime": entry["regime"],
                    "matrix_id": matrix.matrix_id,
                    "condition_id": item.condition_id,
                    "seed": item.seed,
                    "grade": item.grade,
                    "amplitude": round(item.amplitude, 6),
                    "trend": round(item.trend, 6),
                    "sign_changes": item.sign_changes,
                }
            )

    output_dir = artifact_root / "synthetic-closed-loop-benchmark"
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "closed-loop-benchmark-results.csv"
    fieldnames = (
        "scenario_id",
        "regime",
        "matrix_id",
        "condition_id",
        "seed",
        "grade",
        "amplitude",
        "trend",
        "sign_changes",
    )
    with csv_path.open("w", encoding="utf-8", newline="\n") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in fieldnames})

    summary_payload = {
        "schema_version": "mgba-synthetic-closed-loop-benchmark-0.1",
        "spec_sha256": _sha256(spec_path),
        "config": {"ticks": ticks, "seeds": list(seeds)},
        "scenario_matrices": dict(scenario_digests),
        "grade_counts": grade_counts,
        "condition_grade_counts": [
            {"condition_id": condition, "grade": grade, "count": count}
            for (condition, grade), count in sorted(condition_grade_counts.items())
        ],
        "csv": csv_path.name,
    }
    _write_json_once(output_dir / "closed-loop-benchmark-summary.json", summary_payload)
    return {
        "output_root": str(output_dir),
        "csv": str(csv_path),
        "summary": str(output_dir / "closed-loop-benchmark-summary.json"),
        "rows": len(rows),
        "scenarios": len(scenario_digests),
        "grade_counts": grade_counts,
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
        "run", help="execute the closed-loop benchmark over the dataset"
    )
    run.add_argument(
        "--dataset-dir", default=str(DATA_ROOT), help="generated dataset root"
    )
    run.add_argument(
        "--artifact-root",
        default=str(PROJECT_ROOT / "artifacts"),
        help="benchmark artifact root",
    )
    run.add_argument("--ticks", type=int, default=30, help="matrix horizon")
    run.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        default=[7, 42, 1337, 2026],
        help="ensemble seeds",
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
