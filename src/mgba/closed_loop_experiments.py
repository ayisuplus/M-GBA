"""Stochastic closed-loop experiment: E4 × E3 feedback-under-noise matrix.

Combines the ADR-0012 homeostatic controller with the ADR-0015 seeded
transcriptional noise to answer the MVP-plan E4 question — does state
feedback restore homeostasis, oscillate, lock, or deteriorate — under real
multi-seed stochastic excitation, and isolates the noise contribution via a
deterministic closed-loop control condition.

Mathematical formulation
------------------------

For one run, let :math:`h_1, \\ldots, h_K` be the scheduled slow-clock
homeostasis observations (the ``l4_observations`` stored in the run
checkpoint).  Define first differences :math:`d_k = h_{k+1} - h_k`, the
sign-change count

.. math::

    \\phi = \\#\\{\\,k : d_k\\,d_{k+1} < 0\\,\\},

the amplitude :math:`s = \\mathrm{std}(h)` and the trend
:math:`\\Delta = h_K - h_1`.  The pre-registered grading ladder evaluates,
in order:

1. ``insufficient_observations`` — :math:`K < 3`;
2. ``oscillation`` — :math:`\\phi \\ge \\phi_{\\min}` and :math:`s \\ge a_{\\min}`;
3. ``lock`` — :math:`s \\le \\ell_{\\max}` (flat trajectory, dead or frozen);
4. ``recovery`` — :math:`\\Delta \\ge \\delta_{\\text{rec}}` and
   :math:`h_K \\ge h_{\\text{rec}}`;
5. ``deterioration`` — :math:`\\Delta \\le -\\delta_{\\text{det}}`;
6. ``indeterminate`` — everything else.

All thresholds are frozen in config before measurement; the grading is a
reference-model diagnostic, not a biological homeostasis claim.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .experiment import digest_payload
from .experiments import (
    CausalComparison,
    CausalRunRecord,
    ConditionKind,
    ConditionSummary,
    _compare_runs,
    _summarize_condition,
)
from .feedback import (
    FeedbackControllerConfig,
    HomeostaticFeedbackController,
    load_feedback_config,
)
from .layers.l0_noisy import NoisyDiscreteGrnModel, load_noisy_grn_config
from .layers.l3 import ConstraintAwareTissueModel
from .multiscale import MultiscaleScenario
from .runner import (
    MultirateCrossScaleRunner,
    RunnerConfig,
    save_run_artifact,
)


_CLOSED_LOOP_CONDITIONS = (
    "stochastic_open_loop",
    "stochastic_closed_loop",
    "deterministic_closed_loop",
)

_STABILITY_GRADES = (
    "insufficient_observations",
    "oscillation",
    "lock",
    "recovery",
    "deterioration",
    "indeterminate",
)


@dataclass(frozen=True, slots=True)
class ClosedLoopExperimentConfig:
    """Frozen protocol parameters for the stochastic closed-loop matrix."""

    model_version: str
    ticks: int
    seeds: tuple[int, ...]
    sign_change_min: int  # phi_min
    amplitude_min: float  # a_min
    lock_std_max: float  # l_max
    recovery_delta_min: float  # delta_rec
    recovery_homeostasis_min: float  # h_rec
    deterioration_delta_min: float  # delta_det

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError(
                "closed-loop experiment model_version must not be empty"
            )
        if (
            isinstance(self.ticks, bool)
            or not isinstance(self.ticks, int)
            or self.ticks < 1
        ):
            raise ValueError(
                "closed-loop experiment ticks must be a positive integer"
            )
        if len(self.seeds) < 2:
            raise ValueError(
                "closed-loop experiment requires at least two seeds"
            )
        if self.seeds != tuple(sorted(self.seeds)) or len(set(self.seeds)) != len(
            self.seeds
        ):
            raise ValueError(
                "closed-loop experiment seeds must be unique and sorted"
            )
        if any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in self.seeds
        ):
            raise ValueError(
                "closed-loop experiment seeds must be non-negative integers"
            )
        if (
            isinstance(self.sign_change_min, bool)
            or not isinstance(self.sign_change_min, int)
            or self.sign_change_min < 1
        ):
            raise ValueError("sign_change_min must be a positive integer")
        for name in (
            "amplitude_min",
            "lock_std_max",
            "recovery_delta_min",
            "deterioration_delta_min",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and in [0, 1]")
        if (
            not math.isfinite(self.recovery_homeostasis_min)
            or not 0.0 <= self.recovery_homeostasis_min <= 1.0
        ):
            raise ValueError(
                "recovery_homeostasis_min must be finite and in [0, 1]"
            )


def load_closed_loop_config(path: str | Path) -> ClosedLoopExperimentConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return ClosedLoopExperimentConfig(
            model_version=str(raw["model_version"]),
            ticks=int(raw["ticks"]),
            seeds=tuple(int(item) for item in raw["seeds"]),
            sign_change_min=int(raw["sign_change_min"]),
            amplitude_min=float(raw["amplitude_min"]),
            lock_std_max=float(raw["lock_std_max"]),
            recovery_delta_min=float(raw["recovery_delta_min"]),
            recovery_homeostasis_min=float(raw["recovery_homeostasis_min"]),
            deterioration_delta_min=float(raw["deterioration_delta_min"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        raise ValueError(
            f"invalid closed-loop experiment config: {error}"
        ) from error


@dataclass(frozen=True, slots=True)
class StabilityGrade:
    """Pre-registered stability classification for one run."""

    condition_id: str
    seed: int
    observations: tuple[float, ...]
    sign_changes: int
    amplitude: float
    trend: float
    grade: str
    note: str

    def __post_init__(self) -> None:
        if self.grade not in _STABILITY_GRADES:
            raise ValueError(f"unknown stability grade: {self.grade}")
        if any(
            not math.isfinite(value) or not 0.0 <= value <= 1.0
            for value in self.observations
        ):
            raise ValueError("homeostasis observations must be in [0, 1]")

    def as_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "seed": self.seed,
            "observation_count": len(self.observations),
            "sign_changes": self.sign_changes,
            "amplitude": self.amplitude,
            "trend": self.trend,
            "grade": self.grade,
            "note": self.note,
        }


def classify_stability(
    condition_id: str,
    seed: int,
    observations: tuple[float, ...],
    config: ClosedLoopExperimentConfig,
) -> StabilityGrade:
    """Grade one homeostasis observation sequence against frozen thresholds."""
    k = len(observations)
    differences = tuple(
        observations[index + 1] - observations[index] for index in range(k - 1)
    )
    sign_changes = sum(
        1
        for index in range(len(differences) - 1)
        if differences[index] * differences[index + 1] < 0.0
    )
    amplitude = statistics.stdev(observations) if k >= 2 else 0.0
    trend = observations[-1] - observations[0] if observations else 0.0

    if k < 3:
        grade, note = "insufficient_observations", "fewer than three observations"
    elif sign_changes >= config.sign_change_min and amplitude >= config.amplitude_min:
        grade, note = (
            "oscillation",
            "sustained sign changes with non-trivial amplitude",
        )
    elif amplitude <= config.lock_std_max:
        grade, note = "lock", "flat trajectory (frozen or absorbed)"
    elif trend >= config.recovery_delta_min and observations[-1] >= config.recovery_homeostasis_min:
        grade, note = "recovery", "homeostasis rises toward the set-point band"
    elif trend <= -config.deterioration_delta_min:
        grade, note = "deterioration", "homeostasis declines across the window"
    else:
        grade, note = "indeterminate", "does not meet any frozen criterion"

    return StabilityGrade(
        condition_id=condition_id,
        seed=seed,
        observations=observations,
        sign_changes=sign_changes,
        amplitude=amplitude,
        trend=trend,
        grade=grade,
        note=note,
    )


@dataclass(frozen=True, slots=True)
class ClosedLoopMatrixResult:
    """Stochastic closed-loop paired matrix with stability grades."""

    config: ClosedLoopExperimentConfig
    matrix_id: str
    scenario_digest: str
    runner_model_versions: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    records: tuple[CausalRunRecord, ...]
    comparisons: tuple[CausalComparison, ...]
    summaries: tuple[ConditionSummary, ...]
    stability: tuple[StabilityGrade, ...]
    stability_digest: str

    def __post_init__(self) -> None:
        if not self.records or not self.comparisons or not self.stability:
            raise ValueError(
                "closed-loop matrix requires records, comparisons and grades"
            )

    def summary_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "mgba-closed-loop-artifact-0.1",
            "matrix_id": self.matrix_id,
            "scenario_digest": self.scenario_digest,
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
                    "final_metric_effects": dict(item.final_metric_effects),
                    "baseline_outcome": item.baseline_outcome.value,
                    "condition_outcome": item.condition_outcome.value,
                }
                for item in self.comparisons
            ],
            "stability": [item.as_dict() for item in self.stability],
            "stability_digest": self.stability_digest,
        }



def _noisy_models(
    layer_models: Mapping[str, Any],
    noisy_grn_config: Any,
    noise_sigma: float,
    *,
    seed: int,
) -> dict[str, Any]:
    models = dict(layer_models)
    models["genome_model"] = NoisyDiscreteGrnModel(
        noisy_grn_config, noise_sigma=noise_sigma, noise_seed=seed
    )
    return models


class ClosedLoopExperimentRunner:
    """Runs the frozen stochastic closed-loop comparison matrix."""

    def __init__(
        self,
        config: ClosedLoopExperimentConfig,
        *,
        runner_config: RunnerConfig,
        layer_models: Mapping[str, Any],
        feedback_config: FeedbackControllerConfig,
        noisy_grn_config: Any,
        noise_sigma: float,
        stress_floor_coupling: float = 1.0,
    ) -> None:
        if set(layer_models) != {
            "genome_model",
            "molecular_model",
            "cell_model",
            "tissue_model",
            "phenotype_model",
        }:
            raise ValueError("layer_models must provide all five layer model keys")
        self.config = config
        self.runner_config = runner_config
        self.layer_models = dict(layer_models)
        self.feedback_config = feedback_config
        self.noisy_grn_config = noisy_grn_config
        self.noise_sigma = noise_sigma
        self.stress_floor_coupling = stress_floor_coupling
        if any(
            config.ticks > runner_config.max_total_ticks
            for _ in _CLOSED_LOOP_CONDITIONS
        ):
            raise ValueError("closed-loop matrix ticks exceed the runner budget")

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    def _build_runners(self, seed: int) -> dict[str, MultirateCrossScaleRunner]:
        noisy_models = _noisy_models(
            self.layer_models, self.noisy_grn_config, self.noise_sigma, seed=seed
        )
        constraint_models = dict(self.layer_models)
        constraint_models["tissue_model"] = ConstraintAwareTissueModel(
            self.layer_models["tissue_model"].config,
            stress_floor_coupling=self.stress_floor_coupling,
        )
        noisy_constraint_models = _noisy_models(
            constraint_models, self.noisy_grn_config, self.noise_sigma, seed=seed
        )
        return {
            "stochastic_open_loop": MultirateCrossScaleRunner(
                self.runner_config, **noisy_models
            ),
            "stochastic_closed_loop": MultirateCrossScaleRunner(
                self.runner_config,
                **noisy_constraint_models,
                feedback_policy=HomeostaticFeedbackController(self.feedback_config),
            ),
            "deterministic_closed_loop": MultirateCrossScaleRunner(
                self.runner_config,
                **constraint_models,
                feedback_policy=HomeostaticFeedbackController(self.feedback_config),
            ),
        }

    def run(self, scenario: MultiscaleScenario) -> ClosedLoopMatrixResult:
        if not isinstance(scenario, MultiscaleScenario):
            raise TypeError(
                "closed-loop matrix requires a MultiscaleScenario"
            )
        from dataclasses import replace

        records: list[CausalRunRecord] = []
        stability: list[StabilityGrade] = []
        for seed in self.config.seeds:
            runners = self._build_runners(seed)
            seeded_scenario = replace(scenario, seed=seed)
            for condition_id in _CLOSED_LOOP_CONDITIONS:
                runner = runners[condition_id]
                run = runner.run(seeded_scenario, ticks=self.config.ticks)
                if len(run.ticks) != self.config.ticks:
                    raise RuntimeError(
                        "E0 failed: closed-loop run did not produce every tick"
                    )
                kind = (
                    ConditionKind.BASELINE
                    if condition_id == "stochastic_open_loop"
                    else ConditionKind.PERTURBATION
                )
                records.append(
                    CausalRunRecord(
                        condition_id=condition_id,
                        condition_kind=kind,
                        seed=seed,
                        run=run,
                    )
                )
                observations = tuple(
                    state.homeostasis
                    for state in run.checkpoint.l4_observations
                )
                stability.append(
                    classify_stability(
                        condition_id, seed, observations, self.config
                    )
                )

        record_map = {
            (record.condition_id, record.seed): record for record in records
        }
        comparisons = tuple(
            _compare_runs(
                record_map[("stochastic_open_loop", seed)], record
            )
            for condition_id in (
                "stochastic_closed_loop",
                "deterministic_closed_loop",
            )
            for seed in self.config.seeds
            for record in (record_map[(condition_id, seed)],)
        )
        summaries = tuple(
            _summarize_condition(
                condition_id,
                tuple(
                    item
                    for item in comparisons
                    if item.condition_id == condition_id
                ),
            )
            for condition_id in (
                "stochastic_closed_loop",
                "deterministic_closed_loop",
            )
        )
        runner_versions = tuple(
            (condition_id, runners.model_versions)
            for condition_id, runners in self._build_runners(
                self.config.seeds[0]
            ).items()
        )
        stability_digest = digest_payload(
            tuple(item.as_dict() for item in stability)
        )
        matrix_id = (
            f"closedloop-{digest_payload({'config': self.config, 'scenario': scenario, 'runners': runner_versions, 'stability': stability_digest})[:16]}"
        )
        return ClosedLoopMatrixResult(
            config=self.config,
            matrix_id=matrix_id,
            scenario_digest=digest_payload(scenario),
            runner_model_versions=runner_versions,
            records=tuple(records),
            comparisons=comparisons,
            summaries=summaries,
            stability=tuple(stability),
            stability_digest=stability_digest,
        )


def save_closed_loop_artifacts(
    artifact_root: str | Path, result: ClosedLoopMatrixResult
) -> dict[str, Path]:
    """Persist raw runs, manifest, and derived summary (append-only)."""
    if not isinstance(result, ClosedLoopMatrixResult):
        raise TypeError(
            "save_closed_loop_artifacts requires a ClosedLoopMatrixResult"
        )
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
        "schema_version": "mgba-closed-loop-artifact-0.1",
        "matrix_id": result.matrix_id,
        "scenario_digest": result.scenario_digest,
        "runner_model_versions": [
            {"name": name, "versions": dict(versions)}
            for name, versions in result.runner_model_versions
        ],
        "records": record_index,
        "stability": [item.as_dict() for item in result.stability],
    }
    _write_json_once(manifest_path, manifest)
    _write_json_once(summary_path, result.summary_dict())
    return {
        "root": root,
        "manifest": manifest_path,
        "raw": raw_root,
        "summary": summary_path,
    }


def _write_json_once(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(
                "existing closed-loop artifact is invalid JSON"
            ) from error
        if existing != payload:
            raise ValueError(
                "refusing to overwrite a different closed-loop artifact"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
