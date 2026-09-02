"""Deterministic 2×2×2 mechanism audit for the CAR-M spatial L3.

The audit toggles movement, field coupling, and spatial topology inside the
same L3 model family.  It is descriptive factorial bookkeeping, not an
inferential-statistics protocol: the current CAR-M dynamics are deterministic
and one declared scenario seed is used as an auditable replay identity.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping

from .carm_spatial_experiments import spatial_metrics
from .experiment import write_json_once
from .hashing import digest_payload
from .experiments import (
    CausalComparison,
    CausalRunRecord,
    ConditionKind,
    compare_runs,
)
from .layers import LayerId
from .layers.l0 import DiscreteGrnModel, load_grn_config
from .layers.l1 import CoarseMolecularModel, load_molecular_config
from .layers.l4 import PhenotypeObserverModel, load_phenotype_config
from .runner import MultirateCrossScaleRunner, RunnerConfig, save_run_artifact
from .scenarios.carm.models import CarmCellModel, CarmTissueModel
from .scenarios.carm.scenario import CompiledCarmScenario
from .scenarios.carm.spatial import (
    CarmSpatialConfig,
    CarmSpatialMechanisms,
    SpatialCarmTissueModel,
)


_L4_METRICS = (
    "vitality",
    "damage_burden",
    "inflammation",
    "homeostasis",
    "recovery_capacity",
)
_MECHANISM_NAMES = ("movement", "field_coupling", "spatial_topology")
_FACTORIAL_MECHANISMS = tuple(
    CarmSpatialMechanisms(
        movement=bool(movement),
        field_coupling=bool(field),
        spatial_topology=bool(topology),
    )
    for movement in (0, 1)
    for field in (0, 1)
    for topology in (0, 1)
)


@dataclass(frozen=True, slots=True)
class CarmSpatialAblationConfig:
    model_version: str
    ticks: int
    scenario_seed: int

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("spatial ablation model_version is required")
        if isinstance(self.ticks, bool) or not isinstance(self.ticks, int) or self.ticks < 2:
            raise ValueError("spatial ablation requires at least two ticks")
        if (
            isinstance(self.scenario_seed, bool)
            or not isinstance(self.scenario_seed, int)
            or self.scenario_seed < 0
        ):
            raise ValueError("spatial ablation scenario_seed must be non-negative")


def load_carm_spatial_ablation_config(
    path: str | Path,
) -> CarmSpatialAblationConfig:
    try:
        raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("spatial ablation config root must be an object")
        return CarmSpatialAblationConfig(
            model_version=str(raw["model_version"]),
            ticks=raw["ticks"],
            scenario_seed=raw["scenario_seed"],
        )
    except (KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid spatial ablation config: {error}") from error


@dataclass(frozen=True, slots=True)
class SpatialMechanismDiagnostics:
    condition_id: str
    mechanisms: CarmSpatialMechanisms
    mean_displacement: float
    mean_edge_turnover: float
    terminal_field_heterogeneity: float
    terminal_field_gradient: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "mechanisms": {
                name: getattr(self.mechanisms, name) for name in _MECHANISM_NAMES
            },
            "mean_displacement": self.mean_displacement,
            "mean_edge_turnover": self.mean_edge_turnover,
            "terminal_field_heterogeneity": self.terminal_field_heterogeneity,
            "terminal_field_gradient": self.terminal_field_gradient,
        }


@dataclass(frozen=True, slots=True)
class SpatialFactorEffect:
    mechanism: str
    pair_count: int
    mean_l3_distance: float
    mean_l4_distance: float
    mean_final_metric_effects: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        if self.mechanism not in _MECHANISM_NAMES:
            raise ValueError("unknown spatial mechanism")
        if self.pair_count != 4:
            raise ValueError("a 2×2×2 main effect requires four matched pairs")
        if any(
            not math.isfinite(value) or value < 0.0
            for value in (self.mean_l3_distance, self.mean_l4_distance)
        ):
            raise ValueError("factor distances must be finite and non-negative")
        if tuple(name for name, _ in self.mean_final_metric_effects) != _L4_METRICS:
            raise ValueError("factor effect must cover every L4 metric in order")

    def as_dict(self) -> dict[str, Any]:
        return {
            "mechanism": self.mechanism,
            "pair_count": self.pair_count,
            "mean_l3_distance": self.mean_l3_distance,
            "mean_l4_distance": self.mean_l4_distance,
            "mean_final_metric_effects": dict(self.mean_final_metric_effects),
        }


@dataclass(frozen=True, slots=True)
class CarmSpatialAblationResult:
    config: CarmSpatialAblationConfig
    audit_id: str
    scenario_digest: str
    runner_model_versions: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    records: tuple[CausalRunRecord, ...]
    baseline_comparisons: tuple[CausalComparison, ...]
    diagnostics: tuple[SpatialMechanismDiagnostics, ...]
    factor_effects: tuple[SpatialFactorEffect, ...]

    def __post_init__(self) -> None:
        if len(self.records) != 1 + len(_FACTORIAL_MECHANISMS):
            raise ValueError("spatial audit requires fixed baseline plus eight cells")
        if len(self.baseline_comparisons) != len(_FACTORIAL_MECHANISMS):
            raise ValueError("spatial audit must compare every cell with fixed baseline")
        if len(self.diagnostics) != len(_FACTORIAL_MECHANISMS):
            raise ValueError("spatial audit must diagnose every factorial cell")
        if tuple(item.mechanism for item in self.factor_effects) != _MECHANISM_NAMES:
            raise ValueError("spatial audit factor effects are incomplete or unordered")

    def summary_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "mgba-carm-spatial-ablation-0.1",
            "audit_id": self.audit_id,
            "scenario_digest": self.scenario_digest,
            "config": {
                "model_version": self.config.model_version,
                "ticks": self.config.ticks,
                "scenario_seed": self.config.scenario_seed,
            },
            "records": [
                {
                    "condition_id": item.condition_id,
                    "experiment_id": item.run.manifest.experiment_id,
                    "history_digest": item.run.history_digest,
                    "outcome": item.run.phenotype_window.outcome.value,
                }
                for item in self.records
            ],
            "baseline_comparisons": [
                {
                    "condition_id": item.condition_id,
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
                for item in self.baseline_comparisons
            ],
            "diagnostics": [item.as_dict() for item in self.diagnostics],
            "factor_effects": [item.as_dict() for item in self.factor_effects],
            "interpretation_boundary": (
                "deterministic within-L3 factorial audit; main effects are "
                "descriptive model contrasts, not inferential statistics or "
                "biological efficacy estimates"
            ),
        }


def build_carm_spatial_ablation_runners(
    compiled: CompiledCarmScenario,
    *,
    runner_config: RunnerConfig,
    spatial_config: CarmSpatialConfig,
    l0_config: str | Path,
    l1_config: str | Path,
    l4_config: str | Path,
) -> dict[str, MultirateCrossScaleRunner]:
    if not isinstance(compiled, CompiledCarmScenario):
        raise TypeError("spatial ablation requires a compiled CAR-M scenario")

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

    runners = {
        "fixed_graph": build(
            CarmTissueModel(
                compiled.config.tissue_model,
                roles=compiled.roles,
                source_profile_digest=compiled.profile_digest,
            )
        )
    }
    for mechanisms in _FACTORIAL_MECHANISMS:
        runners[mechanisms.condition_id] = build(
            SpatialCarmTissueModel(
                compiled.config.tissue_model,
                spatial_config,
                roles=compiled.roles,
                source_profile_digest=compiled.profile_digest,
                mechanisms=mechanisms,
            )
        )
    return runners


class CarmSpatialAblationRunner:
    def __init__(
        self,
        config: CarmSpatialAblationConfig,
        *,
        runners: Mapping[str, MultirateCrossScaleRunner],
    ) -> None:
        expected = {"fixed_graph"} | {
            mechanisms.condition_id for mechanisms in _FACTORIAL_MECHANISMS
        }
        if set(runners) != expected:
            raise ValueError("spatial ablation runner set is incomplete")
        baseline = dict(runners["fixed_graph"].model_versions)
        for name, runner in runners.items():
            if name == "fixed_graph":
                continue
            versions = dict(runner.model_versions)
            changed = {
                layer for layer, version in versions.items() if version != baseline[layer]
            }
            if changed != {"L3"}:
                raise ValueError("every factorial runner must differ in L3 only")
        if any(config.ticks > runner.config.max_total_ticks for runner in runners.values()):
            raise ValueError("spatial ablation ticks exceed a runner budget")
        self.config = config
        self.runners = dict(runners)

    def run(self, compiled: CompiledCarmScenario) -> CarmSpatialAblationResult:
        if not isinstance(compiled, CompiledCarmScenario):
            raise TypeError("spatial ablation requires a compiled CAR-M scenario")
        scenario = replace(compiled.scenario, seed=self.config.scenario_seed)
        condition_order = (
            "fixed_graph",
            *(item.condition_id for item in _FACTORIAL_MECHANISMS),
        )
        record_list: list[CausalRunRecord] = []
        for condition_id in condition_order:
            run = self.runners[condition_id].run(scenario, ticks=self.config.ticks)
            if len(run.ticks) != self.config.ticks:
                raise RuntimeError("E0 failed: run did not produce every tick")
            record_list.append(
                CausalRunRecord(
                    condition_id=condition_id,
                    condition_kind=(
                        ConditionKind.BASELINE
                        if condition_id == "fixed_graph"
                        else ConditionKind.ABLATION
                    ),
                    seed=self.config.scenario_seed,
                    run=run,
                )
            )
        records = tuple(record_list)
        record_map = {item.condition_id: item for item in records}
        comparisons = tuple(
            compare_runs(
                record_map["fixed_graph"], record_map[item.condition_id]
            )
            for item in _FACTORIAL_MECHANISMS
        )
        diagnostics = tuple(
            _diagnostics(record_map[item.condition_id], item)
            for item in _FACTORIAL_MECHANISMS
        )
        factor_effects = tuple(
            _factor_effect(name, record_map) for name in _MECHANISM_NAMES
        )
        versions = tuple(
            (name, self.runners[name].model_versions) for name in condition_order
        )
        identity = {
            "config": self.config,
            "scenario": scenario,
            "runners": versions,
        }
        return CarmSpatialAblationResult(
            config=self.config,
            audit_id=f"carm-spatial-ablation-{digest_payload(identity)[:16]}",
            scenario_digest=digest_payload(scenario),
            runner_model_versions=versions,
            records=records,
            baseline_comparisons=comparisons,
            diagnostics=diagnostics,
            factor_effects=factor_effects,
        )


def _diagnostics(
    record: CausalRunRecord, mechanisms: CarmSpatialMechanisms
) -> SpatialMechanismDiagnostics:
    metrics = spatial_metrics(record)
    return SpatialMechanismDiagnostics(
        condition_id=record.condition_id,
        mechanisms=mechanisms,
        mean_displacement=metrics.mean_displacement,
        mean_edge_turnover=metrics.mean_edge_turnover,
        terminal_field_heterogeneity=metrics.terminal_field_heterogeneity,
        terminal_field_gradient=metrics.terminal_field_gradient,
    )


def _factor_effect(
    mechanism: str, records: Mapping[str, CausalRunRecord]
) -> SpatialFactorEffect:
    pairs = []
    for off in _FACTORIAL_MECHANISMS:
        if getattr(off, mechanism):
            continue
        on = replace(off, **{mechanism: True})
        pairs.append(
            compare_runs(records[off.condition_id], records[on.condition_id])
        )
    return SpatialFactorEffect(
        mechanism=mechanism,
        pair_count=len(pairs),
        mean_l3_distance=fmean(dict(item.layer_effects)[LayerId.L3] for item in pairs),
        mean_l4_distance=fmean(dict(item.layer_effects)[LayerId.L4] for item in pairs),
        mean_final_metric_effects=tuple(
            (
                metric,
                fmean(dict(item.final_metric_effects)[metric] for item in pairs),
            )
            for metric in _L4_METRICS
        ),
    )




def save_carm_spatial_ablation_artifacts(
    artifact_root: str | Path, result: CarmSpatialAblationResult
) -> dict[str, Path]:
    if not isinstance(result, CarmSpatialAblationResult):
        raise TypeError("spatial ablation artifacts require a result")
    root = Path(artifact_root) / result.audit_id
    record_index = []
    for record in result.records:
        relative = Path("raw") / record.condition_id / "run.json"
        save_run_artifact(root / relative, record.run)
        record_index.append(
            {
                "condition_id": record.condition_id,
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
            "schema_version": "mgba-carm-spatial-ablation-0.1",
            "audit_id": result.audit_id,
            "scenario_digest": result.scenario_digest,
            "runner_model_versions": [
                {"name": name, "versions": dict(versions)}
                for name, versions in result.runner_model_versions
            ],
            "records": record_index,
        },
        artifact="spatial ablation artifact",
    )
    write_json_once(summary, result.summary_dict(), artifact="spatial ablation artifact")
    return {"root": root, "manifest": manifest, "summary": summary}

