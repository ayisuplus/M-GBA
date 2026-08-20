"""E3 population-dynamics experiment: multi-seed noisy-L0 ensemble.

Executes the W14/M9 protocol: run the same scenario under several explicit
seeds, each with a seeded stochastic L0 model (``NoisyDiscreteGrnModel``),
then grade every macro metric through the pre-registered E3 criteria
ladder (``mgba.e3_statistics``).  Determinism contract: a fixed seed
reproduces its trajectory exactly because the noise stream is derived from
``sha256(seed | cell | time)``.

The ensemble deliberately spans different seeds; per-seed experiment ids
therefore differ, which is expected and audited through each run manifest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping

from .e3_statistics import (
    E3CriteriaConfig,
    E3MetricStats,
    e3_summary_digest,
    evaluate_e3,
)
from .experiment import digest_payload
from .multiscale import MultiscaleScenario
from .runner import MultirateCrossScaleRunner, save_run_artifact


@dataclass(frozen=True, slots=True)
class E3ExperimentConfig:
    """Frozen protocol parameters for the E3 ensemble."""

    model_version: str
    ticks: int
    seeds: tuple[int, ...]
    criteria: E3CriteriaConfig

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("E3 experiment model_version must not be empty")
        if (
            isinstance(self.ticks, bool)
            or not isinstance(self.ticks, int)
            or self.ticks < 1
        ):
            raise ValueError("E3 experiment ticks must be a positive integer")
        if len(self.seeds) < 2:
            raise ValueError("E3 experiment requires at least two seeds")
        if self.seeds != tuple(sorted(self.seeds)) or len(set(self.seeds)) != len(
            self.seeds
        ):
            raise ValueError("E3 experiment seeds must be unique and sorted")
        if any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in self.seeds
        ):
            raise ValueError("E3 experiment seeds must be non-negative integers")
        if not isinstance(self.criteria, E3CriteriaConfig):
            raise TypeError("E3 experiment requires an E3CriteriaConfig")


def load_e3_experiment_config(path: str | Path) -> E3ExperimentConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        criteria = E3CriteriaConfig(
            model_version=str(raw["model_version"]),
            cv_threshold=float(raw["cv_threshold"]),
            coupling_threshold=float(raw["coupling_threshold"]),
            persistence_threshold=float(raw["persistence_threshold"]),
            pattern_threshold=float(raw["pattern_threshold"]),
        )
        return E3ExperimentConfig(
            model_version=str(raw["model_version"]),
            ticks=int(raw["ticks"]),
            seeds=tuple(int(item) for item in raw["seeds"]),
            criteria=criteria,
        )
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid E3 experiment config: {error}") from error


@dataclass(frozen=True, slots=True)
class E3MatrixResult:
    """Multi-seed ensemble with per-metric E3 grades."""

    config: E3ExperimentConfig
    matrix_id: str
    scenario_digest: str
    experiment_ids: tuple[tuple[int, str], ...]
    history_digests: tuple[tuple[int, str], ...]
    outcomes: tuple[tuple[int, str], ...]
    stats: tuple[E3MetricStats, ...]
    summary_digest: str

    def __post_init__(self) -> None:
        if not self.stats:
            raise ValueError("E3 matrix requires graded metrics")

    def summary_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "mgba-e3-artifact-0.1",
            "matrix_id": self.matrix_id,
            "scenario_digest": self.scenario_digest,
            "seeds": [seed for seed, _ in self.experiment_ids],
            "experiment_ids": {
                str(seed): experiment_id
                for seed, experiment_id in self.experiment_ids
            },
            "outcomes": {str(seed): outcome for seed, outcome in self.outcomes},
            "summary_digest": self.summary_digest,
            "metrics": [item.as_dict() for item in self.stats],
        }


class E3ExperimentRunner:
    """Runs the frozen multi-seed stochastic-L0 E3 ensemble."""

    def __init__(
        self,
        config: E3ExperimentConfig,
        *,
        build_runner: Callable[[int], MultirateCrossScaleRunner],
    ) -> None:
        if not callable(build_runner):
            raise TypeError("E3 experiment requires a build_runner callable")
        self.config = config
        self.build_runner = build_runner
        for seed in config.seeds:
            runner = build_runner(seed)
            if config.ticks > runner.config.max_total_ticks:
                raise ValueError("E3 ensemble ticks exceed a runner budget")

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    def run(self, scenario: MultiscaleScenario) -> E3MatrixResult:
        if not isinstance(scenario, MultiscaleScenario):
            raise TypeError("E3 ensemble requires a MultiscaleScenario")

        runs: dict[int, MultirateRun] = {}
        experiment_ids: list[tuple[int, str]] = []
        history_digests: list[tuple[int, str]] = []
        outcomes: list[tuple[int, str]] = []
        for seed in self.config.seeds:
            seeded_scenario = replace(scenario, seed=seed)
            runner = self.build_runner(seed)
            run = runner.run(seeded_scenario, ticks=self.config.ticks)
            if len(run.ticks) != self.config.ticks:
                raise RuntimeError(
                    "E0 failed: E3 run did not produce every tick"
                )
            runs[seed] = run
            experiment_ids.append((seed, run.manifest.experiment_id))
            history_digests.append((seed, run.history_digest))
            outcomes.append((seed, run.phenotype_window.outcome.value))

        stats = evaluate_e3(runs, self.config.criteria)
        matrix_id = (
            f"e3-{digest_payload({'config': self.config, 'scenario': scenario, 'stats': e3_summary_digest(stats)})[:16]}"
        )
        return E3MatrixResult(
            config=self.config,
            matrix_id=matrix_id,
            scenario_digest=digest_payload(scenario),
            experiment_ids=tuple(experiment_ids),
            history_digests=tuple(history_digests),
            outcomes=tuple(outcomes),
            stats=stats,
            summary_digest=e3_summary_digest(stats),
        )


def save_e3_artifacts(
    artifact_root: str | Path, result: E3MatrixResult
) -> dict[str, Path]:
    """Persist the E3 summary (append-only); raw runs stay in-memory."""
    if not isinstance(result, E3MatrixResult):
        raise TypeError("save_e3_artifacts requires an E3MatrixResult")
    root = Path(artifact_root) / result.matrix_id
    root.mkdir(parents=True, exist_ok=True)
    summary_path = root / "e3-summary.json"
    manifest_path = root / "manifest.json"
    manifest = {
        "schema_version": "mgba-e3-artifact-0.1",
        "matrix_id": result.matrix_id,
        "scenario_digest": result.scenario_digest,
        "summary_digest": result.summary_digest,
        "experiment_ids": {
            str(seed): experiment_id
            for seed, experiment_id in result.experiment_ids
        },
    }
    _write_json_once(manifest_path, manifest)
    _write_json_once(summary_path, result.summary_dict())
    return {
        "root": root,
        "manifest": manifest_path,
        "summary": summary_path,
    }


def _write_json_once(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("existing E3 artifact is invalid JSON") from error
        if existing != payload:
            raise ValueError("refusing to overwrite a different E3 artifact")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
