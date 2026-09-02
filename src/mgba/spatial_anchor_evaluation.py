"""Evaluate the causal CAR-M spatial L3 against an aggregate anchor target."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .experiment import write_json_once
from .hashing import digest_payload
from .layers import SpatialTissueState
from .runner import MultirateCrossScaleRunner, MultirateRun, save_run_artifact
from .scenarios.carm.scenario import CompiledCarmScenario
from .spatial_anchors import (
    SpatialAnchorProtocol,
    SpatialModelProjection,
    SpatialTargetScore,
    project_spatial_tissue_state,
    score_spatial_projection,
)


EVALUATION_SCHEMA_VERSION = "mgba-carm-spatial-anchor-evaluation-0.1"


@dataclass(frozen=True, slots=True)
class SpatialAnchorEvaluationConfig:
    model_version: str
    ticks: int
    scenario_seed: int

    def __post_init__(self) -> None:
        if not isinstance(self.model_version, str) or not self.model_version.strip():
            raise ValueError("spatial anchor evaluation model_version is required")
        if isinstance(self.ticks, bool) or not isinstance(self.ticks, int) or self.ticks < 2:
            raise ValueError("spatial anchor evaluation needs at least two ticks")
        if (
            isinstance(self.scenario_seed, bool)
            or not isinstance(self.scenario_seed, int)
            or self.scenario_seed < 0
        ):
            raise ValueError("spatial anchor evaluation seed must be non-negative")

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "ticks": self.ticks,
            "scenario_seed": self.scenario_seed,
        }


def load_spatial_anchor_evaluation_config(
    path: str | Path,
) -> SpatialAnchorEvaluationConfig:
    try:
        raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or set(raw) != {
            "model_version",
            "ticks",
            "scenario_seed",
        }:
            raise ValueError("spatial anchor evaluation config fields differ")
        return SpatialAnchorEvaluationConfig(**raw)
    except (OSError, json.JSONDecodeError, TypeError, KeyError) as error:
        raise ValueError(f"invalid spatial anchor evaluation config: {error}") from error


@dataclass(frozen=True, slots=True)
class SpatialAnchorEvaluationResult:
    config: SpatialAnchorEvaluationConfig
    evaluation_id: str
    target_id: str
    scenario_digest: str
    run: MultirateRun
    projection: SpatialModelProjection
    score: SpatialTargetScore

    def __post_init__(self) -> None:
        if not self.evaluation_id.startswith("carm-spatial-anchor-eval-"):
            raise ValueError("invalid spatial anchor evaluation id")
        if self.target_id != self.score.target_id:
            raise ValueError("evaluation target and score target differ")
        if self.run.history_digest != self.run.checkpoint.history_digest:
            raise ValueError("evaluation run history identity differs")
        terminal = self.run.ticks[-1].l3
        if not isinstance(terminal, SpatialTissueState):
            raise TypeError("spatial anchor evaluation requires a spatial L3 run")
        if terminal.metadata.source_digest != self.projection.source_digest:
            raise ValueError("projection is not derived from the terminal L3 state")
        if self.projection != self.score.projection:
            raise ValueError("evaluation score projection differs")

    def summary_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EVALUATION_SCHEMA_VERSION,
            "evaluation_id": self.evaluation_id,
            "target_id": self.target_id,
            "scenario_digest": self.scenario_digest,
            "config": self.config.as_dict(),
            "run": {
                "experiment_id": self.run.manifest.experiment_id,
                "history_digest": self.run.history_digest,
                "checkpoint_id": self.run.checkpoint.checkpoint_id,
                "model_versions": dict(self.run.checkpoint.model_versions),
                "outcome": self.run.phenotype_window.outcome.value,
                "terminal_logical_time": self.run.end_tick,
            },
            "score": self.score.as_dict(),
            "scientific_boundary": (
                "single reference-model trajectory evaluated in a pre-registered "
                "aggregate metric space; not fitted biology, inferential statistics, "
                "clinical prediction, or efficacy evidence"
            ),
        }


class SpatialAnchorEvaluator:
    def __init__(
        self,
        config: SpatialAnchorEvaluationConfig,
        *,
        runner: MultirateCrossScaleRunner,
        protocol: SpatialAnchorProtocol,
    ) -> None:
        if not isinstance(config, SpatialAnchorEvaluationConfig):
            raise TypeError("spatial anchor evaluator needs its config")
        if not isinstance(runner, MultirateCrossScaleRunner):
            raise TypeError("spatial anchor evaluator needs a multirate runner")
        if not isinstance(protocol, SpatialAnchorProtocol):
            raise TypeError("spatial anchor evaluator needs the frozen protocol")
        if config.ticks > runner.config.max_total_ticks:
            raise ValueError("spatial anchor evaluation exceeds runner tick budget")
        self.config = config
        self.runner = runner
        self.protocol = protocol

    def evaluate(
        self,
        compiled: CompiledCarmScenario,
        *,
        target: dict[str, Any],
    ) -> SpatialAnchorEvaluationResult:
        if not isinstance(compiled, CompiledCarmScenario):
            raise TypeError("spatial anchor evaluation needs a compiled CAR-M scenario")
        scenario = replace(compiled.scenario, seed=self.config.scenario_seed)
        run = self.runner.run(scenario, ticks=self.config.ticks)
        terminal = run.ticks[-1].l3
        if not isinstance(terminal, SpatialTissueState):
            raise TypeError("spatial anchor evaluator runner did not produce spatial L3")
        projection = project_spatial_tissue_state(
            terminal,
            roles=compiled.roles,
            protocol=self.protocol,
        )
        score = score_spatial_projection(projection, target)
        scenario_digest = digest_payload(scenario)
        identity = {
            "config": self.config,
            "target_id": score.target_id,
            "scenario_digest": scenario_digest,
            "experiment_id": run.manifest.experiment_id,
            "history_digest": run.history_digest,
            "score_id": score.score_id,
        }
        return SpatialAnchorEvaluationResult(
            config=self.config,
            evaluation_id=(
                f"carm-spatial-anchor-eval-{digest_payload(identity)[:16]}"
            ),
            target_id=score.target_id,
            scenario_digest=scenario_digest,
            run=run,
            projection=projection,
            score=score,
        )




def save_spatial_anchor_evaluation_artifacts(
    artifact_root: str | Path,
    result: SpatialAnchorEvaluationResult,
) -> dict[str, Path]:
    if not isinstance(result, SpatialAnchorEvaluationResult):
        raise TypeError("evaluation artifact save needs a result")
    root = Path(artifact_root) / result.evaluation_id
    run_path = root / "raw" / "run.json"
    manifest_path = root / "manifest.json"
    summary_path = root / "derived" / "summary.json"
    save_run_artifact(run_path, result.run)
    write_json_once(
        manifest_path,
        {
            "schema_version": EVALUATION_SCHEMA_VERSION,
            "evaluation_id": result.evaluation_id,
            "target_id": result.target_id,
            "scenario_digest": result.scenario_digest,
            "run": {
                "path": "raw/run.json",
                "experiment_id": result.run.manifest.experiment_id,
                "history_digest": result.run.history_digest,
                "checkpoint_id": result.run.checkpoint.checkpoint_id,
            },
            "projection_source_digest": result.projection.source_digest,
            "score_id": result.score.score_id,
        },
        artifact="spatial evaluation artifact",
    )
    write_json_once(summary_path, result.summary_dict(), artifact="spatial evaluation artifact")
    return {
        "root": root,
        "run": run_path,
        "manifest": manifest_path,
        "summary": summary_path,
    }
