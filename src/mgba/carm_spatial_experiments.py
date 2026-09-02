"""Paired fixed-graph versus causal-spatial CAR-M L3 experiment."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import fmean, pstdev
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
from .layers import SpatialTissueState
from .layers.l0 import DiscreteGrnModel, load_grn_config
from .layers.l1 import CoarseMolecularModel, load_molecular_config
from .layers.l4 import PhenotypeObserverModel, load_phenotype_config
from .runner import MultirateCrossScaleRunner, RunnerConfig, save_run_artifact
from .scenarios.carm.models import CarmCellModel, CarmTissueModel
from .scenarios.carm.scenario import CompiledCarmScenario
from .scenarios.carm.spatial import CarmSpatialConfig, SpatialCarmTissueModel


_CONDITIONS = ("fixed_graph", "spatial_field")


@dataclass(frozen=True, slots=True)
class CarmSpatialExperimentConfig:
    model_version: str
    ticks: int
    seeds: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("CAR-M spatial experiment model_version is required")
        if isinstance(self.ticks, bool) or not isinstance(self.ticks, int) or self.ticks < 2:
            raise ValueError("CAR-M spatial experiment needs at least two ticks")
        if len(self.seeds) < 2:
            raise ValueError("CAR-M spatial experiment requires at least two seeds")
        if self.seeds != tuple(sorted(self.seeds)) or len(set(self.seeds)) != len(
            self.seeds
        ):
            raise ValueError("CAR-M spatial seeds must be unique and sorted")
        if any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in self.seeds
        ):
            raise ValueError("CAR-M spatial seeds must be non-negative integers")


def load_carm_spatial_experiment_config(
    path: str | Path,
) -> CarmSpatialExperimentConfig:
    try:
        raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("CAR-M spatial experiment root must be an object")
        return CarmSpatialExperimentConfig(
            model_version=str(raw["model_version"]),
            ticks=raw["ticks"],
            seeds=tuple(raw["seeds"]),
        )
    except (KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid CAR-M spatial experiment config: {error}") from error


@dataclass(frozen=True, slots=True)
class SpatialRunMetrics:
    seed: int
    mean_displacement: float
    mean_edge_turnover: float
    terminal_field_heterogeneity: float
    terminal_field_gradient: float

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("spatial metric seed must be non-negative")
        values = (
            self.mean_displacement,
            self.mean_edge_turnover,
            self.terminal_field_heterogeneity,
            self.terminal_field_gradient,
        )
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError("spatial metrics must be finite and non-negative")
        if self.mean_displacement > math.sqrt(2.0):
            raise ValueError("mean displacement exceeds the normalized domain")
        if self.mean_edge_turnover > 1.0:
            raise ValueError("mean edge turnover must be in [0, 1]")

    def as_dict(self) -> dict[str, float | int]:
        return {
            "seed": self.seed,
            "mean_displacement": self.mean_displacement,
            "mean_edge_turnover": self.mean_edge_turnover,
            "terminal_field_heterogeneity": self.terminal_field_heterogeneity,
            "terminal_field_gradient": self.terminal_field_gradient,
        }


@dataclass(frozen=True, slots=True)
class CarmSpatialMatrixResult:
    config: CarmSpatialExperimentConfig
    matrix_id: str
    scenario_digest: str
    runner_model_versions: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    records: tuple[CausalRunRecord, ...]
    comparisons: tuple[CausalComparison, ...]
    summaries: tuple[ConditionSummary, ...]
    spatial_metrics: tuple[SpatialRunMetrics, ...]

    def __post_init__(self) -> None:
        if not self.records or not self.comparisons or not self.spatial_metrics:
            raise ValueError("CAR-M spatial matrix requires runs and comparisons")

    def summary_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "mgba-carm-spatial-artifact-0.1",
            "matrix_id": self.matrix_id,
            "scenario_digest": self.scenario_digest,
            "config": {
                "model_version": self.config.model_version,
                "ticks": self.config.ticks,
                "seeds": list(self.config.seeds),
            },
            "records": [
                {
                    "condition_id": item.condition_id,
                    "seed": item.seed,
                    "experiment_id": item.run.manifest.experiment_id,
                    "history_digest": item.run.history_digest,
                    "outcome": item.run.phenotype_window.outcome.value,
                }
                for item in self.records
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
            "spatial_metrics": [item.as_dict() for item in self.spatial_metrics],
            "model_status": (
                "dimensionless-causal-spatial-reference-model; not a physical "
                "diffusion solver or validated tissue reconstruction"
            ),
        }


def build_carm_spatial_runners(
    compiled: CompiledCarmScenario,
    *,
    runner_config: RunnerConfig,
    spatial_config: CarmSpatialConfig,
    l0_config: str | Path,
    l1_config: str | Path,
    l4_config: str | Path,
) -> dict[str, MultirateCrossScaleRunner]:
    if not isinstance(compiled, CompiledCarmScenario):
        raise TypeError("spatial runner construction requires a compiled CAR-M scenario")

    def build(tissue_model: Any) -> MultirateCrossScaleRunner:
        return MultirateCrossScaleRunner(
            runner_config,
            genome_model=DiscreteGrnModel(load_grn_config(l0_config)),
            molecular_model=CoarseMolecularModel(load_molecular_config(l1_config)),
            cell_model=CarmCellModel(
                compiled.config.cell_model,
                roles=compiled.roles,
                source_profile_digest=compiled.profile_digest,
            ),
            tissue_model=tissue_model,
            phenotype_model=PhenotypeObserverModel(
                load_phenotype_config(l4_config)
            ),
        )

    return {
        "fixed_graph": build(
            CarmTissueModel(
                compiled.config.tissue_model,
                roles=compiled.roles,
                source_profile_digest=compiled.profile_digest,
            )
        ),
        "spatial_field": build(
            SpatialCarmTissueModel(
                compiled.config.tissue_model,
                spatial_config,
                roles=compiled.roles,
                source_profile_digest=compiled.profile_digest,
            )
        ),
    }


class CarmSpatialExperimentRunner:
    def __init__(
        self,
        config: CarmSpatialExperimentConfig,
        *,
        runners: Mapping[str, MultirateCrossScaleRunner],
    ) -> None:
        if set(runners) != set(_CONDITIONS):
            raise ValueError("spatial matrix requires fixed_graph and spatial_field")
        baseline = dict(runners["fixed_graph"].model_versions)
        spatial = dict(runners["spatial_field"].model_versions)
        changed = {
            layer for layer, version in spatial.items() if version != baseline[layer]
        }
        if changed != {"L3"}:
            raise ValueError("CAR-M spatial runners must differ in L3 only")
        if any(config.ticks > runner.config.max_total_ticks for runner in runners.values()):
            raise ValueError("CAR-M spatial ticks exceed a runner budget")
        self.config = config
        self.runners = dict(runners)

    def run(self, compiled: CompiledCarmScenario) -> CarmSpatialMatrixResult:
        if not isinstance(compiled, CompiledCarmScenario):
            raise TypeError("CAR-M spatial matrix requires a compiled scenario")
        records = []
        for condition_id in _CONDITIONS:
            condition_kind = (
                ConditionKind.BASELINE
                if condition_id == "fixed_graph"
                else ConditionKind.PERTURBATION
            )
            for seed in self.config.seeds:
                scenario = replace(compiled.scenario, seed=seed)
                run = self.runners[condition_id].run(
                    scenario, ticks=self.config.ticks
                )
                records.append(
                    CausalRunRecord(
                        condition_id=condition_id,
                        condition_kind=condition_kind,
                        seed=seed,
                        run=run,
                    )
                )
        record_map = {
            (record.condition_id, record.seed): record for record in records
        }
        comparisons = tuple(
            compare_runs(
                record_map[("fixed_graph", seed)],
                record_map[("spatial_field", seed)],
            )
            for seed in self.config.seeds
        )
        spatial_run_metrics = tuple(
            spatial_metrics(record_map[("spatial_field", seed)])
            for seed in self.config.seeds
        )
        runner_versions = tuple(
            (name, runner.model_versions)
            for name, runner in sorted(self.runners.items())
        )
        identity = {
            "config": self.config,
            "scenario": compiled.scenario,
            "runners": runner_versions,
        }
        return CarmSpatialMatrixResult(
            config=self.config,
            matrix_id=f"carm-spatial-{digest_payload(identity)[:16]}",
            scenario_digest=digest_payload(compiled.scenario),
            runner_model_versions=runner_versions,
            records=tuple(records),
            comparisons=comparisons,
            summaries=(
                summarize_condition("spatial_field", comparisons),
            ),
            spatial_metrics=spatial_run_metrics,
        )


def spatial_metrics(record: CausalRunRecord) -> SpatialRunMetrics:
    states = tuple(tick.l3 for tick in record.run.ticks)
    if any(not isinstance(state, SpatialTissueState) for state in states):
        raise TypeError("spatial metrics require SpatialTissueState traces")
    first = states[0]
    terminal = states[-1]
    first_coordinates = {item.cell_id: item for item in first.coordinates}
    terminal_coordinates = {item.cell_id: item for item in terminal.coordinates}
    displacement = fmean(
        math.hypot(
            terminal_coordinates[cell_id].x - first_coordinates[cell_id].x,
            terminal_coordinates[cell_id].y - first_coordinates[cell_id].y,
        )
        for cell_id in sorted(first_coordinates)
    )
    turnovers = []
    for left, right in zip(states, states[1:]):
        left_edges = set(left.edges)
        right_edges = set(right.edges)
        union = left_edges | right_edges
        turnovers.append(
            len(left_edges ^ right_edges) / len(union) if union else 0.0
        )
    channels = ("stress", "resource_level", "signal")
    heterogeneity = fmean(
        pstdev(getattr(item, channel) for item in terminal.field_cells)
        for channel in channels
    )
    grid = {(item.row, item.column): item for item in terminal.field_cells}
    gradients = []
    for row in range(terminal.field_rows):
        for column in range(terminal.field_columns):
            for neighbor in ((row + 1, column), (row, column + 1)):
                if neighbor not in grid:
                    continue
                gradients.extend(
                    abs(
                        getattr(grid[(row, column)], channel)
                        - getattr(grid[neighbor], channel)
                    )
                    for channel in channels
                )
    return SpatialRunMetrics(
        seed=record.seed,
        mean_displacement=displacement,
        mean_edge_turnover=fmean(turnovers),
        terminal_field_heterogeneity=heterogeneity,
        terminal_field_gradient=fmean(gradients),
    )




def save_carm_spatial_artifacts(
    artifact_root: str | Path, result: CarmSpatialMatrixResult
) -> dict[str, Path]:
    root = Path(artifact_root) / result.matrix_id
    records = []
    for record in result.records:
        relative = Path("raw") / record.condition_id / f"seed-{record.seed}.json"
        save_run_artifact(root / relative, record.run)
        records.append(
            {
                "condition_id": record.condition_id,
                "seed": record.seed,
                "experiment_id": record.run.manifest.experiment_id,
                "history_digest": record.run.history_digest,
                "path": relative.as_posix(),
            }
        )
    manifest = root / "manifest.json"
    summary = root / "derived" / "summary.json"
    write_json_once(
        manifest,
        {
            "schema_version": "mgba-carm-spatial-artifact-0.1",
            "matrix_id": result.matrix_id,
            "scenario_digest": result.scenario_digest,
            "runner_model_versions": [
                {"name": name, "versions": dict(versions)}
                for name, versions in result.runner_model_versions
            ],
            "records": records,
            "spatial_metrics": [item.as_dict() for item in result.spatial_metrics],
        },
        artifact="spatial artifact",
    )
    write_json_once(summary, result.summary_dict(), artifact="spatial artifact")
    return {"root": root, "manifest": manifest, "summary": summary}

