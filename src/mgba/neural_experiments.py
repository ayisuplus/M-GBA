"""E2-style neural layer-swap experiment: rule reference vs frozen-weight variant.

Runs the same scenario and seed set through two runners that differ in
exactly one layer — the frozen rule reference model versus the
frozen-weight neural contract demonstrator (``NeuralGrnModel`` for L0
or ``GnnTissueModel`` for L3, ADR-0017) — and compares them with the
WP8 paired-comparison machinery (per-layer mean absolute distance,
directed final L4 metric effects, first propagation tick).  Because
both runners share every other layer, the schedule, and the seed, any
measured difference isolates the swapped layer itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .experiment import write_json_once
from .hashing import digest_payload
from .experiments import (
    CausalComparison,
    CausalRunRecord,
    ConditionKind,
    ConditionSummary,
    compare_runs,
    summarize_condition,
)
from .multiscale import MultiscaleScenario
from .runner import MultirateCrossScaleRunner, save_run_artifact


_NEURAL_CONDITIONS = ("reference", "neural")
_CHANGED_LAYERS = frozenset({"L0", "L3"})


@dataclass(frozen=True, slots=True)
class NeuralComparisonConfig:
    """Frozen protocol parameters for the neural layer-swap comparison."""

    model_version: str
    ticks: int
    seeds: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("neural comparison model_version must not be empty")
        if (
            isinstance(self.ticks, bool)
            or not isinstance(self.ticks, int)
            or self.ticks < 1
        ):
            raise ValueError("neural comparison ticks must be a positive integer")
        if len(self.seeds) < 2:
            raise ValueError("neural comparison requires at least two seeds")
        if self.seeds != tuple(sorted(self.seeds)) or len(set(self.seeds)) != len(
            self.seeds
        ):
            raise ValueError("neural comparison seeds must be unique and sorted")
        if any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in self.seeds
        ):
            raise ValueError("neural comparison seeds must be non-negative integers")


def load_neural_comparison_config(path: str | Path) -> NeuralComparisonConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return NeuralComparisonConfig(
            model_version=str(raw["model_version"]),
            ticks=int(raw["ticks"]),
            seeds=tuple(int(item) for item in raw["seeds"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid neural comparison config: {error}") from error


@dataclass(frozen=True, slots=True)
class NeuralComparisonResult:
    """Reference-vs-neural paired-comparison matrix for one swapped layer."""

    config: NeuralComparisonConfig
    changed_layer: str
    matrix_id: str
    scenario_digest: str
    runner_model_versions: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    records: tuple[CausalRunRecord, ...]
    comparisons: tuple[CausalComparison, ...]
    summaries: tuple[ConditionSummary, ...]

    def __post_init__(self) -> None:
        if self.changed_layer not in _CHANGED_LAYERS:
            raise ValueError("changed_layer must be L0 or L3")
        if not self.records or not self.comparisons or not self.summaries:
            raise ValueError("neural matrix requires records and comparisons")

    def summary_dict(self) -> dict[str, Any]:
        from dataclasses import asdict, is_dataclass

        def _default(value: Any) -> Any:
            if is_dataclass(value) and not isinstance(value, type):
                return asdict(value)
            raise TypeError(f"not JSON serializable: {value!r}")

        return {
            "schema_version": "mgba-neural-artifact-0.1",
            "matrix_id": self.matrix_id,
            "changed_layer": self.changed_layer,
            "scenario_digest": self.scenario_digest,
            "config": json.loads(json.dumps(self.config, default=_default)),
            "records": [
                {
                    "condition_id": record.condition_id,
                    "seed": record.seed,
                    "experiment_id": record.run.manifest.experiment_id,
                    "history_digest": record.run.history_digest,
                    "outcome": record.run.phenotype_window.outcome.value,
                }
                for record in self.records
            ],
            "comparisons": [
                {
                    "condition_id": item.condition_id,
                    "seed": item.seed,
                    "layer_effects": {
                        layer.value: value for layer, value in item.layer_effects
                    },
                    "propagation_ticks": {
                        layer.value: value
                        for layer, value in item.propagation_ticks
                    },
                    "final_metric_effects": dict(item.final_metric_effects),
                    "baseline_outcome": item.baseline_outcome.value,
                    "condition_outcome": item.condition_outcome.value,
                }
                for item in self.comparisons
            ],
            "summaries": [
                {
                    "condition_id": item.condition_id,
                    "seeds": list(item.seeds),
                    "mean_layer_effects": {
                        layer.value: value
                        for layer, value in item.mean_layer_effects
                    },
                    "mean_final_metric_effects": dict(
                        item.mean_final_metric_effects
                    ),
                    "outcome_counts": {
                        outcome.value: count
                        for outcome, count in item.outcome_counts
                    },
                }
                for item in self.summaries
            ],
        }


class NeuralComparisonRunner:
    """Runs the frozen reference-vs-neural single-layer swap matrix."""

    def __init__(
        self,
        config: NeuralComparisonConfig,
        *,
        baseline_runner: MultirateCrossScaleRunner,
        neural_runner: MultirateCrossScaleRunner,
        changed_layer: str,
    ) -> None:
        if not isinstance(config, NeuralComparisonConfig):
            raise TypeError("neural matrix requires a NeuralComparisonConfig")
        if not isinstance(changed_layer, str) or changed_layer not in _CHANGED_LAYERS:
            raise ValueError("changed_layer must be L0 or L3")
        baseline_versions = dict(baseline_runner.model_versions)
        neural_versions = dict(neural_runner.model_versions)
        changed = {
            layer
            for layer, version in neural_versions.items()
            if version != baseline_versions[layer]
        }
        if changed != {changed_layer}:
            raise ValueError(
                f"the neural runner must differ from the reference runner in "
                f"{changed_layer} only"
            )
        self.config = config
        self.runners = {
            "reference": baseline_runner,
            "neural": neural_runner,
        }
        self.changed_layer = changed_layer
        if any(
            config.ticks > runner.config.max_total_ticks
            for runner in self.runners.values()
        ):
            raise ValueError("neural matrix ticks exceed a runner budget")

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    def run(self, scenario: MultiscaleScenario) -> NeuralComparisonResult:
        if not isinstance(scenario, MultiscaleScenario):
            raise TypeError("neural matrix requires a MultiscaleScenario")

        from dataclasses import replace

        records: list[CausalRunRecord] = []
        for condition_id in _NEURAL_CONDITIONS:
            runner = self.runners[condition_id]
            kind = (
                ConditionKind.BASELINE
                if condition_id == "reference"
                else ConditionKind.PERTURBATION
            )
            for seed in self.config.seeds:
                seeded_scenario = replace(scenario, seed=seed)
                run = runner.run(seeded_scenario, ticks=self.config.ticks)
                if len(run.ticks) != self.config.ticks:
                    raise RuntimeError(
                        "E0 failed: neural comparison run did not produce every tick"
                    )
                records.append(
                    CausalRunRecord(
                        condition_id=condition_id,
                        condition_kind=kind,
                        seed=seed,
                        run=run,
                    )
                )

        record_map = {
            (record.condition_id, record.seed): record for record in records
        }
        comparisons = tuple(
            compare_runs(record_map[("reference", seed)], record)
            for seed in self.config.seeds
            for record in (record_map[("neural", seed)],)
        )
        summaries = (
            summarize_condition(
                "neural",
                tuple(comparisons),
            ),
        )
        runner_versions = tuple(
            (name, runner.model_versions)
            for name, runner in sorted(self.runners.items())
        )
        matrix_id = (
            f"neural-{digest_payload({'config': self.config, 'changed_layer': self.changed_layer, 'scenario': scenario, 'runners': runner_versions})[:16]}"
        )
        return NeuralComparisonResult(
            config=self.config,
            changed_layer=self.changed_layer,
            matrix_id=matrix_id,
            scenario_digest=digest_payload(scenario),
            runner_model_versions=runner_versions,
            records=tuple(records),
            comparisons=comparisons,
            summaries=summaries,
        )


def save_neural_artifacts(
    artifact_root: str | Path, result: NeuralComparisonResult
) -> dict[str, Path]:
    """Persist raw runs, manifest, and derived summary (append-only)."""
    if not isinstance(result, NeuralComparisonResult):
        raise TypeError("save_neural_artifacts requires a NeuralComparisonResult")
    root = Path(artifact_root) / result.matrix_id
    raw_root = root / "raw"
    summary_path = root / "derived" / "summary.json"
    manifest_path = root / "manifest.json"
    record_index = []
    for record in result.records:
        relative_path = (
            Path("raw") / record.condition_id / f"seed-{record.seed}.json"
        )
        save_run_artifact(root / relative_path, record.run)
        record_index.append(
            {
                "condition_id": record.condition_id,
                "condition_kind": record.condition_kind.value,
                "seed": record.seed,
                "experiment_id": record.run.manifest.experiment_id,
                "history_digest": record.run.history_digest,
                "path": relative_path.as_posix(),
            }
        )
    manifest = {
        "schema_version": "mgba-neural-artifact-0.1",
        "matrix_id": result.matrix_id,
        "changed_layer": result.changed_layer,
        "scenario_digest": result.scenario_digest,
        "runner_model_versions": [
            {"name": name, "versions": dict(versions)}
            for name, versions in result.runner_model_versions
        ],
        "records": record_index,
    }
    write_json_once(manifest_path, manifest, artifact="neural artifact")
    write_json_once(summary_path, result.summary_dict(), artifact="neural artifact")
    return {
        "root": root,
        "manifest": manifest_path,
        "raw": raw_root,
        "summary": summary_path,
    }


