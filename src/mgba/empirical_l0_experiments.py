"""Paired empirical-response vs hard-clamp L0 semantics matrix (ADR-0038).

Runs the frozen three conditions — baseline, reference_clamp (hard OE clamp of
the bridge-mapped abstract node), and empirical_response (response-table unit at
the same dose) — over the same seeds, then reuses the WP8 paired-comparison
machinery. The constructor enforces that the two runners differ in L0 only, and
each seed additionally runs the empirical runner without perturbations: that
no-perturbation trajectory must be bit-identical to the reference baseline
(identity gate for the variant's natural dynamics).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass, replace
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
from .layers.l0 import ABSTRACT_GENE_NAMES
from .multiscale import MultiscaleScenario
from .runner import MultirateCrossScaleRunner, save_run_artifact

EMPIRICAL_L0_ARTIFACT_SCHEMA = "mgba-empirical-l0-artifact-0.1"
EMPIRICAL_L0_CONDITIONS = ("baseline", "reference_clamp", "empirical_response")
EMPIRICAL_L0_COMPARISONS = (
    "reference_clamp_vs_baseline",
    "empirical_vs_baseline",
    "empirical_vs_reference_clamp",
)


@dataclass(frozen=True, slots=True)
class EmpiricalL0ComparisonConfig:
    """Frozen protocol parameters for the empirical L0 paired matrix."""

    model_version: str
    ticks: int
    seeds: tuple[int, ...]
    cell_id: str
    unit: str
    reference_node: str
    dose: float

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("empirical L0 model_version must not be empty")
        if (
            isinstance(self.ticks, bool)
            or not isinstance(self.ticks, int)
            or self.ticks < 1
        ):
            raise ValueError("empirical L0 ticks must be a positive integer")
        if len(self.seeds) < 2:
            raise ValueError("empirical L0 requires at least two seeds")
        if self.seeds != tuple(sorted(self.seeds)) or len(set(self.seeds)) != len(
            self.seeds
        ):
            raise ValueError("empirical L0 seeds must be unique and sorted")
        if any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in self.seeds
        ):
            raise ValueError("empirical L0 seeds must be non-negative integers")
        if not self.cell_id.strip() or not self.unit.strip():
            raise ValueError("empirical L0 cell_id and unit must not be empty")
        if not self.reference_node.strip():
            raise ValueError("empirical L0 reference_node must not be empty")
        if not 0.0 < self.dose <= 1.0:
            raise ValueError("empirical L0 dose must be in (0, 1]")


def load_empirical_l0_comparison_config(path: str | Path) -> EmpiricalL0ComparisonConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return EmpiricalL0ComparisonConfig(
            model_version=str(raw["model_version"]),
            ticks=int(raw["ticks"]),
            seeds=tuple(int(item) for item in raw["seeds"]),
            cell_id=str(raw["cell_id"]),
            unit=str(raw["unit"]),
            reference_node=str(raw["reference_node"]),
            dose=float(raw["dose"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid empirical L0 comparison config: {error}") from error


@dataclass(frozen=True, slots=True)
class EmpiricalL0ComparisonResult:
    config: EmpiricalL0ComparisonConfig
    matrix_id: str
    scenario_digest: str
    runner_model_versions: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    records: tuple[CausalRunRecord, ...]
    comparisons: tuple[CausalComparison, ...]
    comparison_ids: tuple[str, ...]
    summaries: tuple[ConditionSummary, ...]
    baseline_identity_verified: bool

    def __post_init__(self) -> None:
        if not self.records or not self.comparisons or not self.summaries:
            raise ValueError("empirical L0 matrix requires records and comparisons")
        if not self.baseline_identity_verified:
            raise ValueError("empirical runner baseline must equal the reference baseline")
        if tuple(
            comparison.condition_id for comparison in self.comparisons
        ) != tuple(
            comparison_id
            for comparison_id in self.comparison_ids
            for _ in self.config.seeds
        ):
            raise ValueError("comparison order must follow comparison_ids x seeds")

    def summary_dict(self) -> dict[str, Any]:
        def _default(value: Any) -> Any:
            if is_dataclass(value) and not isinstance(value, type):
                return asdict(value)
            raise TypeError(f"not JSON serializable: {value!r}")

        return {
            "schema_version": EMPIRICAL_L0_ARTIFACT_SCHEMA,
            "matrix_id": self.matrix_id,
            "scenario_digest": self.scenario_digest,
            "config": json.loads(json.dumps(self.config, default=_default)),
            "baseline_identity_verified": self.baseline_identity_verified,
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
                    "comparison_id": comparison.condition_id,
                    "seed": comparison.seed,
                    "layer_effects": {
                        layer.value: value for layer, value in comparison.layer_effects
                    },
                    "propagation_ticks": {
                        layer.value: value
                        for layer, value in comparison.propagation_ticks
                    },
                    "final_metric_effects": dict(comparison.final_metric_effects),
                    "reference_outcome": comparison.baseline_outcome.value,
                    "condition_outcome": comparison.condition_outcome.value,
                }
                for comparison in self.comparisons
            ],
            "summaries": [
                {
                    "comparison_id": item.condition_id,
                    "seeds": list(item.seeds),
                    "mean_layer_effects": {
                        layer.value: value for layer, value in item.mean_layer_effects
                    },
                    "mean_final_metric_effects": dict(item.mean_final_metric_effects),
                    "outcome_counts": {
                        outcome.value: count for outcome, count in item.outcome_counts
                    },
                }
                for item in self.summaries
            ],
        }


class EmpiricalL0ComparisonRunner:
    """Runs the frozen empirical-response paired matrix over two L0 runners."""

    def __init__(
        self,
        config: EmpiricalL0ComparisonConfig,
        *,
        baseline_runner: MultirateCrossScaleRunner,
        empirical_runner: MultirateCrossScaleRunner,
    ) -> None:
        if not isinstance(config, EmpiricalL0ComparisonConfig):
            raise TypeError("empirical L0 matrix requires an EmpiricalL0ComparisonConfig")
        baseline_versions = dict(baseline_runner.model_versions)
        empirical_versions = dict(empirical_runner.model_versions)
        changed = {
            layer
            for layer, version in empirical_versions.items()
            if version != baseline_versions[layer]
        }
        if changed != {"L0"}:
            raise ValueError(
                "the empirical runner must differ from the reference runner in L0 only"
            )
        self.config = config
        self.runners = {
            "baseline": baseline_runner,
            "reference_clamp": baseline_runner,
            "empirical_response": empirical_runner,
        }
        if any(
            config.ticks > runner.config.max_total_ticks
            for runner in self.runners.values()
        ):
            raise ValueError("empirical L0 matrix ticks exceed a runner budget")

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    def _perturbations_for(self, condition_id: str) -> dict[str, dict[str, float]] | None:
        if condition_id == "reference_clamp":
            return {self.config.cell_id: {self.config.reference_node: self.config.dose}}
        if condition_id == "empirical_response":
            return {self.config.cell_id: {self.config.unit: self.config.dose}}
        return None

    def run(self, scenario: MultiscaleScenario) -> EmpiricalL0ComparisonResult:
        if not isinstance(scenario, MultiscaleScenario):
            raise TypeError("empirical L0 matrix requires a MultiscaleScenario")

        records: list[CausalRunRecord] = []
        identity_ok = True
        for seed in self.config.seeds:
            seeded = replace(scenario, seed=seed)
            runs: dict[str, Any] = {}
            for condition_id in EMPIRICAL_L0_CONDITIONS:
                runner = self.runners[condition_id]
                run = runner.run(
                    seeded,
                    ticks=self.config.ticks,
                    perturbations=self._perturbations_for(condition_id),
                )
                if len(run.ticks) != self.config.ticks:
                    raise RuntimeError(
                        "E0 failed: empirical L0 comparison run did not produce every tick"
                    )
                runs[condition_id] = run
                records.append(
                    CausalRunRecord(
                        condition_id=condition_id,
                        condition_kind=(
                            ConditionKind.BASELINE
                            if condition_id == "baseline"
                            else ConditionKind.PERTURBATION
                        ),
                        seed=seed,
                        run=run,
                    )
                )
            empirical_free = self.runners["empirical_response"].run(
                seeded, ticks=self.config.ticks
            )
            identity_ok = identity_ok and all(
                _strip_l0_identity(left.l0) == _strip_l0_identity(right.l0)
                for left, right in zip(
                    empirical_free.ticks, runs["baseline"].ticks, strict=True
                )
            )

        record_map = {
            (record.condition_id, record.seed): record for record in records
        }
        comparisons: list[CausalComparison] = []
        for comparison_id in EMPIRICAL_L0_COMPARISONS:
            for seed in self.config.seeds:
                if comparison_id == "reference_clamp_vs_baseline":
                    left = record_map[("baseline", seed)]
                    right = record_map[("reference_clamp", seed)]
                elif comparison_id == "empirical_vs_baseline":
                    left = record_map[("baseline", seed)]
                    right = record_map[("empirical_response", seed)]
                else:
                    left = record_map[("reference_clamp", seed)]
                    right = record_map[("empirical_response", seed)]
                comparisons.append(
                    replace(
                        compare_runs(left, right),
                        condition_id=comparison_id,
                    )
                )
        summaries = tuple(
            summarize_condition(
                comparison_id,
                tuple(
                    comparison
                    for comparison in comparisons
                    if comparison.condition_id == comparison_id
                ),
            )
            for comparison_id in EMPIRICAL_L0_COMPARISONS
        )
        runner_versions = (
            ("empirical", self.runners["empirical_response"].model_versions),
            ("reference", self.runners["baseline"].model_versions),
        )
        matrix_id = f"empirical-l0-{digest_payload({'config': self.config, 'scenario': scenario, 'runners': runner_versions})[:16]}"
        return EmpiricalL0ComparisonResult(
            config=self.config,
            matrix_id=matrix_id,
            scenario_digest=digest_payload(scenario),
            runner_model_versions=runner_versions,
            records=tuple(records),
            comparisons=tuple(comparisons),
            comparison_ids=EMPIRICAL_L0_COMPARISONS,
            summaries=summaries,
            baseline_identity_verified=identity_ok,
        )


def _strip_l0_identity(states: Any) -> Any:
    """Normalize provenance metadata so value identity is comparable."""
    return tuple(
        replace(
            state,
            metadata=replace(
                state.metadata,
                model_version="identity-gate",
                source_digest="identity-gate",
            ),
        )
        for state in states
    )


def save_empirical_l0_artifacts(
    artifact_root: str | Path, result: EmpiricalL0ComparisonResult
) -> dict[str, Path]:
    """Persist raw runs, manifest, and derived summary (append-only)."""
    if not isinstance(result, EmpiricalL0ComparisonResult):
        raise TypeError("save_empirical_l0_artifacts requires an EmpiricalL0ComparisonResult")
    root = Path(artifact_root) / result.matrix_id
    raw_root = root / "raw"
    summary_path = root / "derived" / "summary.json"
    manifest_path = root / "manifest.json"
    record_index = []
    for record in result.records:
        relative_path = Path("raw") / record.condition_id / f"seed-{record.seed}.json"
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
        "schema_version": EMPIRICAL_L0_ARTIFACT_SCHEMA,
        "matrix_id": result.matrix_id,
        "scenario_digest": result.scenario_digest,
        "runner_model_versions": [
            {"name": name, "versions": dict(versions)}
            for name, versions in result.runner_model_versions
        ],
        "baseline_identity_verified": result.baseline_identity_verified,
        "records": record_index,
    }
    write_json_once(manifest_path, manifest, artifact="empirical L0 artifact")
    write_json_once(summary_path, result.summary_dict(), artifact="empirical L0 artifact")
    return {
        "root": root,
        "manifest": manifest_path,
        "raw": raw_root,
        "summary": summary_path,
    }


SCHEDULE_ARTIFACT_SCHEMA = "mgba-empirical-l0-schedule-0.1"
SCHEDULE_ARMS = ("reference", "empirical")


@dataclass(frozen=True, slots=True)
class EmpiricalL0ScheduleConfig:
    """Config-driven multi-unit/scheduled paired matrix protocol (ADR-0041)."""

    model_version: str
    ticks: int
    seeds: tuple[int, ...]
    conditions: tuple[dict[str, Any], ...]
    comparisons: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("schedule comparison model_version must not be empty")
        if (
            isinstance(self.ticks, bool)
            or not isinstance(self.ticks, int)
            or self.ticks < 1
        ):
            raise ValueError("schedule comparison ticks must be a positive integer")
        if len(self.seeds) < 2:
            raise ValueError("schedule comparison requires at least two seeds")
        if self.seeds != tuple(sorted(self.seeds)) or len(set(self.seeds)) != len(
            self.seeds
        ):
            raise ValueError("schedule comparison seeds must be unique and sorted")
        ids = [condition["condition_id"] for condition in self.conditions]
        if len(ids) != len(set(ids)):
            raise ValueError("condition ids must be unique")
        if "baseline" not in ids:
            raise ValueError("a baseline condition is required")
        for condition in self.conditions:
            if set(condition) != {"condition_id", "arm", "perturbations", "schedule"}:
                raise ValueError(
                    "condition keys must be condition_id/arm/perturbations/schedule"
                )
            if condition["arm"] not in SCHEDULE_ARMS:
                raise ValueError(f"unknown condition arm: {condition['arm']!r}")
            both_none = (
                condition["perturbations"] is None and condition["schedule"] is None
            )
            both_set = (
                condition["perturbations"] is not None
                and condition["schedule"] is not None
            )
            if condition["condition_id"] == "baseline":
                if not both_none:
                    raise ValueError("baseline must take neither perturbations nor schedule")
            elif both_none or both_set:
                raise ValueError(
                    f"condition {condition['condition_id']} needs exactly one of "
                    "perturbations/schedule"
                )
        for left, right in self.comparisons:
            if left not in ids or right not in ids:
                raise ValueError("comparisons must reference declared conditions")


def load_empirical_l0_schedule_config(path: str | Path) -> EmpiricalL0ScheduleConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return EmpiricalL0ScheduleConfig(
            model_version=str(raw["model_version"]),
            ticks=int(raw["ticks"]),
            seeds=tuple(int(item) for item in raw["seeds"]),
            conditions=tuple(
                {
                    "condition_id": str(item["condition_id"]),
                    "arm": str(item["arm"]),
                    "perturbations": item.get("perturbations"),
                    "schedule": (
                        {int(tick): values for tick, values in item["schedule"].items()}
                        if item.get("schedule") is not None
                        else None
                    ),
                }
                for item in raw["conditions"]
            ),
            comparisons=tuple(
                (str(pair[0]), str(pair[1])) for pair in raw["comparisons"]
            ),
        )
    except (KeyError, TypeError, json.JSONDecodeError, OSError, AttributeError) as error:
        raise ValueError(f"invalid empirical L0 schedule config: {error}") from error


@dataclass(frozen=True, slots=True)
class EmpiricalL0ScheduleResult:
    config: EmpiricalL0ScheduleConfig
    matrix_id: str
    scenario_digest: str
    runner_model_versions: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    records: tuple[CausalRunRecord, ...]
    comparisons: tuple[CausalComparison, ...]
    summaries: tuple[ConditionSummary, ...]
    baseline_identity_verified: bool

    def __post_init__(self) -> None:
        if not self.records or not self.comparisons or not self.summaries:
            raise ValueError("schedule matrix requires records and comparisons")
        if not self.baseline_identity_verified:
            raise ValueError("empirical runner baseline must equal the reference baseline")

    def summary_dict(self) -> dict[str, Any]:
        def _default(value: Any) -> Any:
            if is_dataclass(value) and not isinstance(value, type):
                return asdict(value)
            raise TypeError(f"not JSON serializable: {value!r}")

        return {
            "schema_version": SCHEDULE_ARTIFACT_SCHEMA,
            "matrix_id": self.matrix_id,
            "scenario_digest": self.scenario_digest,
            "config": json.loads(json.dumps(self.config, default=_default)),
            "baseline_identity_verified": self.baseline_identity_verified,
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
                    "comparison_id": comparison.condition_id,
                    "seed": comparison.seed,
                    "layer_effects": {
                        layer.value: value for layer, value in comparison.layer_effects
                    },
                    "propagation_ticks": {
                        layer.value: value
                        for layer, value in comparison.propagation_ticks
                    },
                    "final_metric_effects": dict(comparison.final_metric_effects),
                    "reference_outcome": comparison.baseline_outcome.value,
                    "condition_outcome": comparison.condition_outcome.value,
                }
                for comparison in self.comparisons
            ],
            "summaries": [
                {
                    "comparison_id": item.condition_id,
                    "seeds": list(item.seeds),
                    "mean_layer_effects": {
                        layer.value: value for layer, value in item.mean_layer_effects
                    },
                    "mean_final_metric_effects": dict(item.mean_final_metric_effects),
                    "outcome_counts": {
                        outcome.value: count for outcome, count in item.outcome_counts
                    },
                }
                for item in self.summaries
            ],
        }


class EmpiricalL0ScheduleRunner:
    """Runs the config-driven ADR-0041 schedule matrix over two L0 runners."""

    def __init__(
        self,
        config: EmpiricalL0ScheduleConfig,
        *,
        baseline_runner: MultirateCrossScaleRunner,
        empirical_runner: MultirateCrossScaleRunner,
    ) -> None:
        if not isinstance(config, EmpiricalL0ScheduleConfig):
            raise TypeError("schedule matrix requires an EmpiricalL0ScheduleConfig")
        baseline_versions = dict(baseline_runner.model_versions)
        empirical_versions = dict(empirical_runner.model_versions)
        changed = {
            layer
            for layer, version in empirical_versions.items()
            if version != baseline_versions[layer]
        }
        if changed != {"L0"}:
            raise ValueError(
                "the empirical runner must differ from the reference runner in L0 only"
            )
        # Fail fast on unknown genes before any run.
        from .layers.l0_empirical import EmpiricalResponseGrnModel

        genome_model = empirical_runner.genome_model
        if not isinstance(genome_model, EmpiricalResponseGrnModel):
            raise TypeError("the empirical runner must carry EmpiricalResponseGrnModel")
        known = set(genome_model.response_table.units) | set(ABSTRACT_GENE_NAMES)
        for condition in config.conditions:
            genes: set[str] = set()
            if condition["perturbations"]:
                for values in condition["perturbations"].values():
                    genes.update(values)
            if condition["schedule"]:
                for values in condition["schedule"].values():
                    for cell_values in values.values():
                        genes.update(cell_values)
            unknown = genes - known
            if unknown:
                raise ValueError(f"conditions target unknown genes/units: {sorted(unknown)}")
        self.config = config
        self.runners = {"reference": baseline_runner, "empirical": empirical_runner}
        if any(config.ticks > runner.config.max_total_ticks for runner in self.runners.values()):
            raise ValueError("schedule matrix ticks exceed a runner budget")

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    def run(self, scenario: MultiscaleScenario) -> EmpiricalL0ScheduleResult:
        if not isinstance(scenario, MultiscaleScenario):
            raise TypeError("schedule matrix requires a MultiscaleScenario")
        records: list[CausalRunRecord] = []
        identity_ok = True
        for seed in self.config.seeds:
            seeded = replace(scenario, seed=seed)
            runs: dict[str, Any] = {}
            for condition in self.config.conditions:
                run = self.runners[condition["arm"]].run(
                    seeded,
                    ticks=self.config.ticks,
                    perturbations=condition["perturbations"],
                    perturbation_schedule=condition["schedule"],
                )
                if len(run.ticks) != self.config.ticks:
                    raise RuntimeError(
                        "E0 failed: schedule comparison run did not produce every tick"
                    )
                runs[condition["condition_id"]] = run
                records.append(
                    CausalRunRecord(
                        condition_id=condition["condition_id"],
                        condition_kind=(
                            ConditionKind.BASELINE
                            if condition["condition_id"] == "baseline"
                            else ConditionKind.PERTURBATION
                        ),
                        seed=seed,
                        run=run,
                    )
                )
            empirical_free = self.runners["empirical"].run(seeded, ticks=self.config.ticks)
            identity_ok = identity_ok and all(
                _strip_l0_identity(left.l0) == _strip_l0_identity(right.l0)
                for left, right in zip(
                    empirical_free.ticks, runs["baseline"].ticks, strict=True
                )
            )
        record_map = {
            (record.condition_id, record.seed): record for record in records
        }
        comparisons = tuple(
            replace(
                compare_runs(
                    record_map[(left, seed)], record_map[(right, seed)]
                ),
                condition_id=f"{right}_vs_{left}",
            )
            for left, right in self.config.comparisons
            for seed in self.config.seeds
        )
        summaries = tuple(
            summarize_condition(
                f"{right}_vs_{left}",
                tuple(
                    comparison
                    for comparison in comparisons
                    if comparison.condition_id == f"{right}_vs_{left}"
                ),
            )
            for left, right in self.config.comparisons
        )
        runner_versions = (
            ("empirical", self.runners["empirical"].model_versions),
            ("reference", self.runners["reference"].model_versions),
        )
        matrix_id = f"empirical-l0-schedule-{digest_payload({'config': self.config, 'scenario': scenario, 'runners': runner_versions})[:16]}"
        return EmpiricalL0ScheduleResult(
            config=self.config,
            matrix_id=matrix_id,
            scenario_digest=digest_payload(scenario),
            runner_model_versions=runner_versions,
            records=tuple(records),
            comparisons=comparisons,
            summaries=summaries,
            baseline_identity_verified=identity_ok,
        )


def save_empirical_l0_schedule_artifacts(
    artifact_root: str | Path, result: EmpiricalL0ScheduleResult
) -> dict[str, Path]:
    """Persist raw runs, manifest, and derived summary (append-only)."""
    if not isinstance(result, EmpiricalL0ScheduleResult):
        raise TypeError("save requires an EmpiricalL0ScheduleResult")
    root = Path(artifact_root) / result.matrix_id
    raw_root = root / "raw"
    summary_path = root / "derived" / "summary.json"
    manifest_path = root / "manifest.json"
    record_index = []
    for record in result.records:
        relative_path = Path("raw") / record.condition_id / f"seed-{record.seed}.json"
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
        "schema_version": SCHEDULE_ARTIFACT_SCHEMA,
        "matrix_id": result.matrix_id,
        "scenario_digest": result.scenario_digest,
        "runner_model_versions": [
            {"name": name, "versions": dict(versions)}
            for name, versions in result.runner_model_versions
        ],
        "baseline_identity_verified": result.baseline_identity_verified,
        "records": record_index,
    }
    write_json_once(manifest_path, manifest, artifact="empirical L0 artifact")
    write_json_once(summary_path, result.summary_dict(), artifact="empirical L0 artifact")
    return {
        "root": root,
        "manifest": manifest_path,
        "raw": raw_root,
        "summary": summary_path,
    }


