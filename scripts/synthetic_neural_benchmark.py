"""Synthetic benchmark for the neural layer-swap comparison (ADR-0017).

Reuses the deterministic synthetic scenario dataset from
``synthetic_feedback_benchmark.generate_dataset`` (creating it on
demand) and runs, for every scenario, two paired matrices with the
WP8 comparison machinery:

* ``l0`` — frozen ``DiscreteGrnModel`` vs frozen-weight ``NeuralGrnModel``;
* ``l3`` — frozen ``TissueEnvironmentModel`` vs frozen-weight ``GnnTissueModel``.

Per-condition final L4 outcomes and per-layer effects are aggregated
into CSV + JSON artifacts under ``artifacts/synthetic-neural-benchmark/``.
Both variants are frozen-weight contract demonstrators, not trained
models; benchmark differences quantify the trajectory impact of the
layer swap, not biological fidelity.

Usage (from the repository root, inside the project venv):

    python scripts/synthetic_neural_benchmark.py generate   # dataset (idempotent)
    python scripts/synthetic_neural_benchmark.py run
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

from mgba.layers.l0_neural import (  # noqa: E402
    NeuralGrnModel,
    load_neural_grn_config,
)
from mgba.layers.l3_gnn import GnnTissueModel, load_gnn_tissue_config  # noqa: E402
from mgba.multiscale import load_multiscale_scenario  # noqa: E402
from mgba.neural_experiments import (  # noqa: E402
    NeuralComparisonConfig,
    NeuralComparisonRunner,
)
from mgba.runner import MultirateCrossScaleRunner, load_runner_config  # noqa: E402

SWAP_LAYERS = ("l0", "l3")


def _neural_runner_pair(changed_layer: str) -> dict[str, MultirateCrossScaleRunner]:
    runner_config = load_runner_config(
        PROJECT_ROOT / "configs" / "runner_reference.json"
    )
    layer_configs = PROJECT_ROOT / "configs" / "layers"
    baseline_models = _layer_models()
    neural_models = _layer_models()
    if changed_layer == "l0":
        neural_models["genome_model"] = NeuralGrnModel(
            load_neural_grn_config(layer_configs / "l0_neural_grn.json")
        )
    else:
        neural_models["tissue_model"] = GnnTissueModel(
            load_gnn_tissue_config(layer_configs / "l3_gnn_tissue.json")
        )
    return {
        "reference": MultirateCrossScaleRunner(runner_config, **baseline_models),
        "neural": MultirateCrossScaleRunner(runner_config, **neural_models),
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
    config = NeuralComparisonConfig(
        model_version="synthetic-neural-swap-benchmark-0.1",
        ticks=ticks,
        seeds=seeds,
    )
    runner_pairs = {layer: _neural_runner_pair(layer) for layer in SWAP_LAYERS}

    rows: list[dict[str, Any]] = []
    scenario_matrices: dict[str, dict[str, str]] = {}
    for entry in spec["scenarios"]:
        scenario_path = dataset_root / entry["path"]
        if _sha256(scenario_path) != entry["sha256"]:
            raise ValueError(f"scenario file drifted from manifest: {scenario_path}")
        scenario = load_multiscale_scenario(scenario_path)
        scenario_matrices[entry["scenario_id"]] = {}
        for changed_layer in SWAP_LAYERS:
            matrix = NeuralComparisonRunner(
                config,
                baseline_runner=runner_pairs[changed_layer]["reference"],
                neural_runner=runner_pairs[changed_layer]["neural"],
                changed_layer=changed_layer.upper(),
            ).run(scenario)
            scenario_matrices[entry["scenario_id"]][changed_layer] = matrix.matrix_id
            mean_layer_effects = {
                layer.value: value
                for layer, value in matrix.summaries[0].mean_layer_effects
            }
            for record in matrix.records:
                terminal = record.run.terminal_observation
                rows.append(
                    {
                        "scenario_id": entry["scenario_id"],
                        "regime": entry["regime"],
                        "changed_layer": changed_layer,
                        "matrix_id": matrix.matrix_id,
                        "condition_id": record.condition_id,
                        "seed": record.seed,
                        "outcome": record.run.phenotype_window.outcome.value,
                        "mean_homeostasis": record.run.phenotype_window.mean_homeostasis,
                        "effect_l0": mean_layer_effects["L0"],
                        "effect_l1": mean_layer_effects["L1"],
                        "effect_l2": mean_layer_effects["L2"],
                        "effect_l3": mean_layer_effects["L3"],
                        "effect_l4": mean_layer_effects["L4"],
                        **{
                            f"final_{metric}": getattr(terminal, metric)
                            for metric in L4_METRICS
                        },
                    }
                )

    output_dir = artifact_root / "synthetic-neural-benchmark"
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "neural-benchmark-results.csv"
    fieldnames = (
        "scenario_id",
        "regime",
        "changed_layer",
        "matrix_id",
        "condition_id",
        "seed",
        "outcome",
        "mean_homeostasis",
        "effect_l0",
        "effect_l1",
        "effect_l2",
        "effect_l3",
        "effect_l4",
        *(f"final_{metric}" for metric in L4_METRICS),
    )
    with csv_path.open("w", encoding="utf-8", newline="\n") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in fieldnames})

    summary: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["regime"], row["changed_layer"], row["condition_id"])
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
        "schema_version": "mgba-synthetic-neural-benchmark-0.1",
        "spec_sha256": _sha256(spec_path),
        "config": {"ticks": ticks, "seeds": list(seeds)},
        "scenario_matrices": scenario_matrices,
        "summary": [
            {
                "regime": regime,
                "changed_layer": changed_layer,
                "condition_id": condition,
                **bucket,
            }
            for (regime, changed_layer, condition), bucket in sorted(summary.items())
        ],
        "csv": csv_path.name,
    }
    _write_json_once(output_dir / "neural-benchmark-summary.json", summary_payload)
    return {
        "output_root": str(output_dir),
        "csv": str(csv_path),
        "summary": str(output_dir / "neural-benchmark-summary.json"),
        "rows": len(rows),
        "scenarios": len(scenario_matrices),
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
        "run", help="execute the neural layer-swap benchmark over the dataset"
    )
    run.add_argument(
        "--dataset-dir", default=str(DATA_ROOT), help="generated dataset root"
    )
    run.add_argument(
        "--artifact-root",
        default=str(PROJECT_ROOT / "artifacts"),
        help="benchmark artifact root",
    )
    run.add_argument("--ticks", type=int, default=30, help="comparison matrix horizon")
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
