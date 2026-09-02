"""E4 feedback-loop experiment: no / fixed / state-dependent L4→L3 feedback.

Compares three paired conditions on the same scenario and seed set,
reusing the WP8 paired-comparison machinery (per-layer mean absolute
distance, directed final L4 metric effects, first propagation tick):

* ``no_feedback``: the 0.2.0 vanilla runner (byte-identical baseline);
* ``fixed_feedback``: a constant environment constraint, isolating the
  effect of a static environment shift;
* ``state_feedback``: the homeostatic PI + safety-barrier controller from
  ``mgba.feedback``.

The protocol answers MVP-plan E4: does state-dependent feedback restore
homeostasis, oscillate, lock, or deteriorate compared with no feedback?
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

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
from .feedback import (
    FeedbackControllerConfig,
    FixedConstraintPolicy,
    HomeostaticFeedbackController,
)
from .layers.l3 import ConstraintAwareTissueModel
from .multiscale import MultiscaleScenario
from .runner import (
    MultirateCrossScaleRunner,
    RunnerConfig,
    save_run_artifact,
)


_CONDITION_IDS = ("no_feedback", "fixed_feedback", "state_feedback")


@dataclass(frozen=True, slots=True)
class FeedbackExperimentConfig:
    """Frozen E4 protocol parameters."""

    model_version: str
    ticks: int
    seeds: tuple[int, ...]
    fixed_resource_ceiling: float
    fixed_stress_floor: float

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("feedback experiment model_version must not be empty")
        if (
            isinstance(self.ticks, bool)
            or not isinstance(self.ticks, int)
            or self.ticks < 1
        ):
            raise ValueError("feedback experiment ticks must be a positive integer")
        if len(self.seeds) < 2:
            raise ValueError("feedback experiment requires at least two seeds")
        if self.seeds != tuple(sorted(self.seeds)) or len(set(self.seeds)) != len(
            self.seeds
        ):
            raise ValueError("feedback experiment seeds must be unique and sorted")
        if any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in self.seeds
        ):
            raise ValueError("feedback experiment seeds must be non-negative integers")
        if (
            not isinstance(self.fixed_resource_ceiling, float)
            or not 0.0 < self.fixed_resource_ceiling <= 1.0
        ):
            raise ValueError("fixed_resource_ceiling must be in (0, 1]")
        if (
            not isinstance(self.fixed_stress_floor, float)
            or not 0.0 <= self.fixed_stress_floor < 1.0
        ):
            raise ValueError("fixed_stress_floor must be in [0, 1)")


def load_feedback_experiment_config(
    path: str | Path,
) -> FeedbackExperimentConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return FeedbackExperimentConfig(
            model_version=str(raw["model_version"]),
            ticks=int(raw["ticks"]),
            seeds=tuple(int(item) for item in raw["seeds"]),
            fixed_resource_ceiling=float(raw["fixed_resource_ceiling"]),
            fixed_stress_floor=float(raw["fixed_stress_floor"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid feedback experiment config: {error}") from error


def build_feedback_runners(
    *,
    layer_models: Mapping[str, Any],
    runner_config: RunnerConfig,
    feedback_config: FeedbackControllerConfig,
    fixed_resource_ceiling: float,
    fixed_stress_floor: float,
    stress_floor_coupling: float = 1.0,
) -> dict[str, MultirateCrossScaleRunner]:
    """Construct the three E4 condition runners from shared layer models.

    ``no_feedback`` keeps the original tissue model so its runs are
    byte-identical to the 0.2.0 baseline; the feedback conditions swap in
    the constraint-aware L3 model plus the matching policy.
    """
    required = {
        "genome_model",
        "molecular_model",
        "cell_model",
        "tissue_model",
        "phenotype_model",
    }
    if set(layer_models) != required:
        raise ValueError("layer_models must provide all five layer model keys")

    vanilla = MultirateCrossScaleRunner(runner_config, **layer_models)
    constraint_models = dict(layer_models)
    constraint_models["tissue_model"] = ConstraintAwareTissueModel(
        layer_models["tissue_model"].config,
        stress_floor_coupling=stress_floor_coupling,
    )

    def _policy_runner(policy: Any) -> MultirateCrossScaleRunner:
        return MultirateCrossScaleRunner(
            runner_config, **constraint_models, feedback_policy=policy
        )

    return {
        "no_feedback": vanilla,
        "fixed_feedback": _policy_runner(
            FixedConstraintPolicy(
                resource_ceiling=fixed_resource_ceiling,
                stress_floor=fixed_stress_floor,
            )
        ),
        "state_feedback": _policy_runner(
            HomeostaticFeedbackController(feedback_config)
        ),
    }


@dataclass(frozen=True, slots=True)
class FeedbackMatrixResult:
    """E4 paired-comparison matrix over the three feedback conditions."""

    config: FeedbackExperimentConfig
    matrix_id: str
    scenario_digest: str
    runner_model_versions: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    records: tuple[CausalRunRecord, ...]
    comparisons: tuple[CausalComparison, ...]
    summaries: tuple[ConditionSummary, ...]

    def __post_init__(self) -> None:
        if not self.records or not self.comparisons or not self.summaries:
            raise ValueError("feedback matrix requires records and comparisons")

    def summary_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "mgba-feedback-artifact-0.1",
            "matrix_id": self.matrix_id,
            "scenario_digest": self.scenario_digest,
            "config": json.loads(
                json.dumps(self.config, default=_dataclass_default)
            ),
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
                        layer.value: value
                        for layer, value in item.layer_effects
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


def _dataclass_default(value: Any) -> Any:
    from dataclasses import asdict, is_dataclass

    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"not JSON serializable: {value!r}")


class FeedbackExperimentRunner:
    """Runs the frozen E4 no/fixed/state feedback comparison matrix."""

    def __init__(
        self,
        config: FeedbackExperimentConfig,
        *,
        runners: Mapping[str, MultirateCrossScaleRunner],
    ) -> None:
        if set(runners) != set(_CONDITION_IDS):
            raise ValueError(
                "feedback matrix requires no_feedback, fixed_feedback and "
                "state_feedback runners"
            )
        self.config = config
        self.runners = dict(runners)
        if any(
            config.ticks > runner.config.max_total_ticks
            for runner in self.runners.values()
        ):
            raise ValueError("feedback matrix ticks exceed a runner budget")

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    def run(self, scenario: MultiscaleScenario) -> FeedbackMatrixResult:
        if not isinstance(scenario, MultiscaleScenario):
            raise TypeError("feedback matrix requires a MultiscaleScenario")

        records: list[CausalRunRecord] = []
        for condition_id in _CONDITION_IDS:
            runner = self.runners[condition_id]
            kind = (
                ConditionKind.BASELINE
                if condition_id == "no_feedback"
                else ConditionKind.PERTURBATION
            )
            for seed in self.config.seeds:
                seeded_scenario = _replace_seed(scenario, seed)
                run = runner.run(seeded_scenario, ticks=self.config.ticks)
                if len(run.ticks) != self.config.ticks:
                    raise RuntimeError(
                        "E0 failed: feedback run did not produce every tick"
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
            compare_runs(record_map[("no_feedback", seed)], record)
            for condition_id in ("fixed_feedback", "state_feedback")
            for seed in self.config.seeds
            for record in (record_map[(condition_id, seed)],)
        )
        summaries = tuple(
            summarize_condition(
                condition_id,
                tuple(
                    item
                    for item in comparisons
                    if item.condition_id == condition_id
                ),
            )
            for condition_id in ("fixed_feedback", "state_feedback")
        )
        runner_versions = tuple(
            (name, runner.model_versions)
            for name, runner in sorted(self.runners.items())
        )
        matrix_id = (
            f"feedback-{digest_payload({'config': self.config, 'scenario': scenario, 'runners': runner_versions})[:16]}"
        )
        return FeedbackMatrixResult(
            config=self.config,
            matrix_id=matrix_id,
            scenario_digest=digest_payload(scenario),
            runner_model_versions=runner_versions,
            records=tuple(records),
            comparisons=comparisons,
            summaries=summaries,
        )


def _replace_seed(scenario: MultiscaleScenario, seed: int) -> MultiscaleScenario:
    from dataclasses import replace

    return replace(scenario, seed=seed)


def save_feedback_artifacts(
    artifact_root: str | Path, result: FeedbackMatrixResult
) -> dict[str, Path]:
    """Persist raw runs, manifest, and derived summary (append-only)."""
    if not isinstance(result, FeedbackMatrixResult):
        raise TypeError("save_feedback_artifacts requires a FeedbackMatrixResult")
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
        "schema_version": "mgba-feedback-artifact-0.1",
        "matrix_id": result.matrix_id,
        "scenario_digest": result.scenario_digest,
        "config": json.loads(
            json.dumps(result.config, default=_dataclass_default)
        ),
        "runner_model_versions": [
            {"name": name, "versions": dict(versions)}
            for name, versions in result.runner_model_versions
        ],
        "records": record_index,
    }
    write_json_once(manifest_path, manifest, artifact="feedback artifact")
    write_json_once(summary_path, result.summary_dict(), artifact="feedback artifact")
    return {
        "root": root,
        "manifest": manifest_path,
        "raw": raw_root,
        "summary": summary_path,
    }


