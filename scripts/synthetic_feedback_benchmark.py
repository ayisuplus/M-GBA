"""Synthetic dataset generator and benchmark for the L4→L3 feedback loop.

No real experimental data exists for the five-layer reference model, so
this script fabricates deterministic scenario datasets tailored to the
homeostatic feedback benchmark (E4):

* ``generate`` writes seeded scenario JSON files (heterogeneous abstract
  genomes, ring-plus-chord topologies, graded environment stress and
  resource scarcity), a SHA-256 manifest, and a benchmark spec. The same
  arguments reproduce the dataset byte-for-byte.
* ``run`` executes the E4 no/fixed/state feedback matrix on every
  generated scenario and aggregates per-condition final L4 outcomes into
  CSV + JSON artifacts.

Everything is append-safe: regenerating an identical dataset is a no-op,
while conflicting files are rejected.

Usage (from the repository root, inside the project venv):

    python scripts/synthetic_feedback_benchmark.py generate
    python scripts/synthetic_feedback_benchmark.py run
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mgba.feedback import load_feedback_config  # noqa: E402
from mgba.feedback_experiments import (  # noqa: E402
    FeedbackExperimentConfig,
    FeedbackExperimentRunner,
    build_feedback_runners,
)
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config  # noqa: E402
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config  # noqa: E402
from mgba.layers.l2 import CellStateMachineModel, load_cell_config  # noqa: E402
from mgba.layers.l3 import TissueEnvironmentModel, load_tissue_config  # noqa: E402
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config  # noqa: E402
from mgba.multiscale import load_multiscale_scenario  # noqa: E402
from mgba.runner import load_runner_config  # noqa: E402

GENOME_TRAITS = (
    "damage_response",
    "signal_expression",
    "repair_expression",
    "metabolic_expression",
    "death_expression",
    "negative_feedback_expression",
)

STRESS_REGIMES = (
    ("calm", 0.15, 1.0),
    ("injury", 0.35, 0.8),
    ("severe", 0.6, 0.5),
    ("collapse", 0.8, 0.3),
)

DATA_ROOT = PROJECT_ROOT / "data" / "synthetic-feedback"
L4_METRICS = (
    "vitality",
    "damage_burden",
    "inflammation",
    "homeostasis",
    "recovery_capacity",
)


def _write_json_once(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise ValueError(f"refusing to overwrite a different file: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_genome(rng: random.Random, regime: str) -> dict[str, float]:
    """Heterogeneous abstract genome biased by the stress regime.

    Severe regimes skew populations toward weaker repair and higher death
    expression so the feedback controller faces a genuinely harder task.
    """
    bias = {
        "calm": (0.5, 0.7, 0.1, 0.15),
        "injury": (0.4, 0.6, 0.12, 0.2),
        "severe": (0.25, 0.45, 0.18, 0.3),
        "collapse": (0.15, 0.3, 0.25, 0.4),
    }[regime]
    repair_low, repair_high, death_low, death_high = bias
    return {
        "damage_response": round(rng.uniform(0.1, 0.5), 4),
        "signal_expression": round(rng.uniform(0.3, 0.9), 4),
        "repair_expression": round(rng.uniform(repair_low, repair_high), 4),
        "metabolic_expression": round(rng.uniform(0.4, 0.9), 4),
        "death_expression": round(rng.uniform(death_low, death_high), 4),
        "negative_feedback_expression": round(rng.uniform(0.1, 0.5), 4),
    }


def _make_edges(rng: random.Random, cell_ids: list[str], chords: int) -> list[list[str]]:
    """Ring backbone plus seeded random chords (no duplicates, no loops)."""
    edges = {
        tuple(sorted((cell_ids[i], cell_ids[(i + 1) % len(cell_ids)])))
        for i in range(len(cell_ids))
    }
    attempts = 0
    while len(edges) < len(cell_ids) + chords and attempts < chords * 50:
        attempts += 1
        source, target = rng.sample(cell_ids, 2)
        edge = tuple(sorted((source, target)))
        if edge[0] != edge[1]:
            edges.add(edge)
    return sorted(list(edge) for edge in edges)


def generate_dataset(
    *,
    seed: int,
    cells: int,
    chords: int,
    ticks: int,
    seeds: tuple[int, ...],
    output_root: Path,
) -> dict[str, Any]:
    if cells < 3:
        raise ValueError("scenarios need at least 3 cells for a ring topology")
    rng = random.Random(seed)
    scenarios_dir = output_root / "scenarios"
    manifest_entries = []

    for regime, stress, resource in STRESS_REGIMES:
        scenario_id = f"synthetic-{regime}-n{cells}-seed{seed}"
        cell_ids = [f"cell-{index:03d}" for index in range(cells)]
        agents = [
            {
                "id": cell_id,
                "genome": {
                    "version": "abstract-genome-synthetic-0.1",
                    "traits": _make_genome(rng, regime),
                },
            }
            for cell_id in cell_ids
        ]
        payload = {
            "seed": seeds[0],
            "environment_stress": stress,
            "resource_level": resource,
            "incoming_signal": 0.0,
            "agents": agents,
            "edges": _make_edges(rng, cell_ids, chords),
        }
        scenario_path = scenarios_dir / f"{scenario_id}.json"
        _write_json_once(scenario_path, payload)
        manifest_entries.append(
            {
                "scenario_id": scenario_id,
                "regime": regime,
                "environment_stress": stress,
                "resource_level": resource,
                "cells": cells,
                "path": scenario_path.relative_to(output_root).as_posix(),
                "sha256": _sha256(scenario_path),
            }
        )

    spec = {
        "schema_version": "mgba-synthetic-feedback-benchmark-0.1",
        "generator": {
            "seed": seed,
            "cells": cells,
            "chords": chords,
            "ticks": ticks,
            "seeds": list(seeds),
        },
        "e4": {
            "model_version": "synthetic-e4-benchmark-0.1",
            "ticks": ticks,
            "seeds": list(seeds),
            "fixed_resource_ceiling": 0.7,
            "fixed_stress_floor": 0.3,
        },
        "scenarios": manifest_entries,
    }
    spec_path = output_root / "benchmark_spec.json"
    _write_json_once(spec_path, spec)
    manifest_path = output_root / "manifest.json"
    _write_json_once(
        manifest_path,
        {
            "schema_version": "mgba-synthetic-dataset-manifest-0.1",
            "generator": spec["generator"],
            "spec_sha256": _sha256(spec_path),
            "scenarios": manifest_entries,
        },
    )
    return {
        "output_root": str(output_root),
        "scenario_count": len(manifest_entries),
        "manifest": str(manifest_path),
        "spec": str(spec_path),
    }


def _layer_models() -> dict[str, Any]:
    layer_configs = PROJECT_ROOT / "configs" / "layers"
    return {
        "genome_model": DiscreteGrnModel(
            load_grn_config(layer_configs / "l0_reference_grn.json")
        ),
        "molecular_model": CoarseMolecularModel(
            load_molecular_config(layer_configs / "l1_reference_molecular.json")
        ),
        "cell_model": CellStateMachineModel(
            load_cell_config(layer_configs / "l2_reference_cell.json")
        ),
        "tissue_model": TissueEnvironmentModel(
            load_tissue_config(layer_configs / "l3_reference_tissue.json")
        ),
        "phenotype_model": PhenotypeObserverModel(
            load_phenotype_config(layer_configs / "l4_reference_phenotype.json")
        ),
    }


def run_benchmark(
    *, dataset_root: Path, artifact_root: Path, ticks_override: int | None
) -> dict[str, Any]:
    spec_path = dataset_root / "benchmark_spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    e4_raw = dict(spec["e4"])
    if ticks_override is not None:
        e4_raw["ticks"] = ticks_override
    e4_config = FeedbackExperimentConfig(
        model_version=str(e4_raw["model_version"]),
        ticks=int(e4_raw["ticks"]),
        seeds=tuple(int(item) for item in e4_raw["seeds"]),
        fixed_resource_ceiling=float(e4_raw["fixed_resource_ceiling"]),
        fixed_stress_floor=float(e4_raw["fixed_stress_floor"]),
    )
    feedback_config = load_feedback_config(
        PROJECT_ROOT / "configs" / "layers" / "l4_feedback_controller.json"
    )
    runner_config = load_runner_config(
        PROJECT_ROOT / "configs" / "runner_reference.json"
    )
    layer_models = _layer_models()
    runners = build_feedback_runners(
        layer_models=layer_models,
        runner_config=runner_config,
        feedback_config=feedback_config,
        fixed_resource_ceiling=e4_config.fixed_resource_ceiling,
        fixed_stress_floor=e4_config.fixed_stress_floor,
    )

    rows: list[dict[str, Any]] = []
    scenario_digests = []
    for entry in spec["scenarios"]:
        scenario_path = dataset_root / entry["path"]
        if _sha256(scenario_path) != entry["sha256"]:
            raise ValueError(f"scenario file drifted from manifest: {scenario_path}")
        scenario = load_multiscale_scenario(scenario_path)
        matrix = FeedbackExperimentRunner(e4_config, runners=runners).run(scenario)
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
                    "final_homeostasis_mean": record.run.phenotype_window.mean_homeostasis,
                    **{
                        f"final_{metric}": getattr(terminal, metric)
                        for metric in L4_METRICS
                    },
                }
            )

    output_dir = artifact_root / "synthetic-feedback-benchmark"
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "feedback-benchmark-results.csv"
    fieldnames = (
        "scenario_id",
        "regime",
        "matrix_id",
        "condition_id",
        "seed",
        "outcome",
        "final_homeostasis_mean",
        *(f"final_{metric}" for metric in L4_METRICS),
    )
    with csv_path.open("w", encoding="utf-8", newline="\n") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in fieldnames})

    summary: dict[str, Any] = {}
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
        for metric in ("mean_final_homeostasis", "mean_final_inflammation", "mean_final_vitality"):
            bucket[metric] = round(bucket[metric] / bucket["runs"], 6)

    summary_payload = {
        "schema_version": "mgba-synthetic-feedback-benchmark-0.1",
        "spec_sha256": _sha256(spec_path),
        "e4": e4_raw,
        "scenario_matrices": dict(scenario_digests),
        "summary": [
            {"regime": regime, "condition_id": condition, **bucket}
            for (regime, condition), bucket in sorted(summary.items())
        ],
        "csv": csv_path.name,
    }
    _write_json_once(output_dir / "benchmark-summary.json", summary_payload)
    return {
        "output_root": str(output_dir),
        "csv": str(csv_path),
        "summary": str(output_dir / "benchmark-summary.json"),
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
    generate.add_argument("--ticks", type=int, default=60, help="E4 horizon")
    generate.add_argument(
        "--output-dir", default=str(DATA_ROOT), help="dataset output root"
    )

    run = commands.add_parser(
        "run", help="execute the E4 feedback benchmark over the dataset"
    )
    run.add_argument(
        "--dataset-dir", default=str(DATA_ROOT), help="generated dataset root"
    )
    run.add_argument(
        "--artifact-root",
        default=str(PROJECT_ROOT / "artifacts"),
        help="benchmark artifact root",
    )
    run.add_argument("--ticks", type=int, help="override the E4 horizon")

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
            ticks_override=args.ticks,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
