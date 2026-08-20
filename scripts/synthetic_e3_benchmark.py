"""Synthetic benchmark for the E3 multi-seed stochastic-L0 ensemble.

Reuses the deterministic synthetic scenario dataset from
``synthetic_feedback_benchmark.generate_dataset`` (creating it on demand)
and runs the seeded noisy-L0 E3 ensemble on every scenario, aggregating
per-scenario E3 grades, grade counts, and per-seed outcomes into CSV +
JSON artifacts.

Usage (from the repository root, inside the project venv):

    python scripts/synthetic_e3_benchmark.py generate   # dataset (idempotent)
    python scripts/synthetic_e3_benchmark.py run
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
    _layer_models,
    _sha256,
    _write_json_once,
    generate_dataset,
)

from mgba.e3_experiments import (  # noqa: E402
    E3ExperimentConfig,
    E3ExperimentRunner,
)
from mgba.e3_statistics import E3CriteriaConfig  # noqa: E402
from mgba.layers.l0_noisy import (  # noqa: E402
    NoisyDiscreteGrnModel,
    load_noisy_grn_config,
)
from mgba.multiscale import load_multiscale_scenario  # noqa: E402
from mgba.runner import MultirateCrossScaleRunner, load_runner_config  # noqa: E402


def _build_e3_runner_factory(
    seeds: tuple[int, ...]
) -> Any:
    runner_config = load_runner_config(
        PROJECT_ROOT / "configs" / "runner_reference.json"
    )
    layer_configs = PROJECT_ROOT / "configs" / "layers"
    grn_config, noise_sigma = load_noisy_grn_config(
        layer_configs / "l0_noisy_grn.json"
    )

    def build(seed: int) -> MultirateCrossScaleRunner:
        models = _layer_models()
        models["genome_model"] = NoisyDiscreteGrnModel(
            grn_config, noise_sigma=noise_sigma, noise_seed=seed
        )
        return MultirateCrossScaleRunner(runner_config, **models)

    return build


def run_benchmark(
    *, dataset_root: Path, artifact_root: Path, ticks: int, seeds: tuple[int, ...]
) -> dict[str, Any]:
    spec_path = dataset_root / "benchmark_spec.json"
    if not spec_path.exists():
        raise ValueError(
            f"dataset not found at {dataset_root}; run the generate command first"
        )
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    criteria = E3CriteriaConfig(
        model_version="synthetic-e3-benchmark-0.1",
        cv_threshold=0.05,
        coupling_threshold=0.5,
        persistence_threshold=0.6,
        pattern_threshold=0.4,
    )
    config = E3ExperimentConfig(
        model_version="synthetic-e3-benchmark-0.1",
        ticks=ticks,
        seeds=seeds,
        criteria=criteria,
    )
    build_runner = _build_e3_runner_factory(seeds)

    rows: list[dict[str, Any]] = []
    grade_counts: dict[str, int] = {}
    outcome_counts: dict[str, int] = {}
    scenario_digests = []
    for entry in spec["scenarios"]:
        scenario_path = dataset_root / entry["path"]
        if _sha256(scenario_path) != entry["sha256"]:
            raise ValueError(f"scenario file drifted from manifest: {scenario_path}")
        scenario = load_multiscale_scenario(scenario_path)
        matrix = E3ExperimentRunner(config, build_runner=build_runner).run(
            scenario
        )
        scenario_digests.append((entry["scenario_id"], matrix.matrix_id))
        for seed, outcome in matrix.outcomes:
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        for item in matrix.stats:
            grade_counts[item.grade] = grade_counts.get(item.grade, 0) + 1
            rows.append(
                {
                    "scenario_id": entry["scenario_id"],
                    "regime": entry["regime"],
                    "matrix_id": matrix.matrix_id,
                    "metric": item.metric,
                    "grade": item.grade,
                    "mean": round(item.mean, 6),
                    "std": round(item.std, 6),
                    "cv": round(item.cv, 6),
                    "r_squared": round(item.r_squared, 6),
                    "decoupling": round(item.decoupling, 6),
                    "persistence": round(item.persistence, 6),
                }
            )

    output_dir = artifact_root / "synthetic-e3-benchmark"
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "e3-benchmark-results.csv"
    fieldnames = (
        "scenario_id",
        "regime",
        "matrix_id",
        "metric",
        "grade",
        "mean",
        "std",
        "cv",
        "r_squared",
        "decoupling",
        "persistence",
    )
    with csv_path.open("w", encoding="utf-8", newline="\n") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in fieldnames})

    summary_payload = {
        "schema_version": "mgba-synthetic-e3-benchmark-0.1",
        "spec_sha256": _sha256(spec_path),
        "config": {"ticks": ticks, "seeds": list(seeds)},
        "scenario_matrices": dict(scenario_digests),
        "grade_counts": grade_counts,
        "outcome_counts": outcome_counts,
        "metrics": rows,
        "csv": csv_path.name,
    }
    _write_json_once(output_dir / "e3-benchmark-summary.json", summary_payload)
    return {
        "output_root": str(output_dir),
        "csv": str(csv_path),
        "summary": str(output_dir / "e3-benchmark-summary.json"),
        "rows": len(rows),
        "scenarios": len(scenario_digests),
        "grade_counts": grade_counts,
        "outcome_counts": outcome_counts,
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
        "run", help="execute the E3 noisy-L0 ensemble benchmark over the dataset"
    )
    run.add_argument(
        "--dataset-dir", default=str(DATA_ROOT), help="generated dataset root"
    )
    run.add_argument(
        "--artifact-root",
        default=str(PROJECT_ROOT / "artifacts"),
        help="benchmark artifact root",
    )
    run.add_argument("--ticks", type=int, default=30, help="ensemble horizon")
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
