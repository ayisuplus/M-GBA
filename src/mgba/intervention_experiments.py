"""State-conditioned, time-scheduled L0 intervention experiments.

This is an AIDO-inspired *evaluation protocol*, not an imported foundation
model.  The same explicit L0 clamp is applied to the same CAR-M Cell group at
different points along an otherwise identical trajectory.  Every response is
still generated through adjacent L0->L1->L2->L3->L4 contracts.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping

from .experiment import canonical_json, digest_payload
from .experiments import (
    CausalComparison,
    CausalRunRecord,
    ConditionKind,
    _compare_runs,
    _tick_layer_distance,
)
from .layers import LayerId
from .layers.l0 import ABSTRACT_GENE_NAMES, DiscreteGrnModel, load_grn_config
from .layers.l1 import CoarseMolecularModel, load_molecular_config
from .layers.l4 import PhenotypeObserverModel, load_phenotype_config
from .runner import MultirateCrossScaleRunner, MultirateRun, RunnerConfig, save_run_artifact
from .scenarios.carm.models import CarmCellModel, CarmTissueModel
from .scenarios.carm.scenario import CellRole, CompiledCarmScenario


INTERVENTION_SCHEMA_VERSION = "mgba-state-conditioned-intervention-0.1"
_CONDITION_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_L4_METRICS = (
    "vitality",
    "damage_burden",
    "inflammation",
    "homeostasis",
    "recovery_capacity",
)


@dataclass(frozen=True, slots=True)
class ScheduledInterventionCondition:
    condition_id: str
    l0_update_ticks: tuple[int, ...]

    def __post_init__(self) -> None:
        if not _CONDITION_ID.fullmatch(self.condition_id) or self.condition_id == "baseline":
            raise ValueError("scheduled intervention condition_id is invalid")
        if (
            not self.l0_update_ticks
            or self.l0_update_ticks != tuple(sorted(self.l0_update_ticks))
            or len(set(self.l0_update_ticks)) != len(self.l0_update_ticks)
        ):
            raise ValueError("l0_update_ticks must be non-empty, unique, and sorted")
        if any(
            isinstance(tick, bool) or not isinstance(tick, int) or tick < 1
            for tick in self.l0_update_ticks
        ):
            raise ValueError("l0_update_ticks must contain positive integers")


@dataclass(frozen=True, slots=True)
class TimingContrastSpec:
    contrast_id: str
    early_condition_id: str
    late_condition_id: str

    def __post_init__(self) -> None:
        if not _CONDITION_ID.fullmatch(self.contrast_id):
            raise ValueError("timing contrast id is invalid")
        if (
            not self.early_condition_id.strip()
            or not self.late_condition_id.strip()
            or self.early_condition_id == self.late_condition_id
        ):
            raise ValueError("timing contrast needs two distinct conditions")


@dataclass(frozen=True, slots=True)
class StateConditionedInterventionConfig:
    model_version: str
    ticks: int
    seeds: tuple[int, ...]
    target_role: CellRole
    gene: str
    value: float
    conditions: tuple[ScheduledInterventionCondition, ...]
    timing_contrasts: tuple[TimingContrastSpec, ...]

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("intervention model_version must not be empty")
        if isinstance(self.ticks, bool) or not isinstance(self.ticks, int) or self.ticks < 2:
            raise ValueError("intervention ticks must be an integer >= 2")
        if (
            len(self.seeds) < 2
            or self.seeds != tuple(sorted(self.seeds))
            or len(set(self.seeds)) != len(self.seeds)
            or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in self.seeds)
        ):
            raise ValueError("intervention seeds must be multiple unique sorted non-negative integers")
        if self.gene not in ABSTRACT_GENE_NAMES:
            raise ValueError("intervention gene must be one of the six abstract L0 nodes")
        if not math.isfinite(self.value) or not 0.0 <= self.value <= 1.0:
            raise ValueError("intervention value must be finite and in [0, 1]")
        condition_ids = [item.condition_id for item in self.conditions]
        if len(self.conditions) < 2 or len(condition_ids) != len(set(condition_ids)):
            raise ValueError("intervention conditions must be multiple and unique")
        if any(item.l0_update_ticks[-1] > self.ticks for item in self.conditions):
            raise ValueError("intervention schedule exceeds its horizon")
        contrast_ids = [item.contrast_id for item in self.timing_contrasts]
        if not self.timing_contrasts or len(contrast_ids) != len(set(contrast_ids)):
            raise ValueError("timing contrasts must be non-empty and unique")
        by_id = {item.condition_id: item for item in self.conditions}
        for contrast in self.timing_contrasts:
            if (
                contrast.early_condition_id not in by_id
                or contrast.late_condition_id not in by_id
            ):
                raise ValueError("timing contrast references an unknown condition")
            early = by_id[contrast.early_condition_id]
            late = by_id[contrast.late_condition_id]
            if len(early.l0_update_ticks) != len(late.l0_update_ticks):
                raise ValueError("timing contrasts require equal intervention exposure counts")
            if early.l0_update_ticks[0] >= late.l0_update_ticks[0]:
                raise ValueError("timing contrast early onset must precede late onset")

    @property
    def condition_map(self) -> dict[str, ScheduledInterventionCondition]:
        return {item.condition_id: item for item in self.conditions}


def load_state_conditioned_intervention_config(
    path: str | Path,
) -> StateConditionedInterventionConfig:
    try:
        raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or set(raw) != {
            "schema_version",
            "model_version",
            "ticks",
            "seeds",
            "target_role",
            "gene",
            "value",
            "conditions",
            "timing_contrasts",
        }:
            raise ValueError("intervention config has an unexpected field set")
        if raw["schema_version"] != INTERVENTION_SCHEMA_VERSION:
            raise ValueError("unsupported intervention config schema")
        if not isinstance(raw["conditions"], list) or not isinstance(raw["timing_contrasts"], list):
            raise ValueError("conditions and timing_contrasts must be arrays")
        conditions = []
        for item in raw["conditions"]:
            if not isinstance(item, dict) or set(item) != {"condition_id", "l0_update_ticks"}:
                raise ValueError("intervention condition has an unexpected field set")
            if not isinstance(item["l0_update_ticks"], list):
                raise ValueError("l0_update_ticks must be an array")
            conditions.append(
                ScheduledInterventionCondition(
                    condition_id=str(item["condition_id"]),
                    l0_update_ticks=tuple(item["l0_update_ticks"]),
                )
            )
        contrasts = []
        for item in raw["timing_contrasts"]:
            if not isinstance(item, dict) or set(item) != {
                "contrast_id",
                "early_condition_id",
                "late_condition_id",
            }:
                raise ValueError("timing contrast has an unexpected field set")
            contrasts.append(TimingContrastSpec(**item))
        return StateConditionedInterventionConfig(
            model_version=str(raw["model_version"]),
            ticks=raw["ticks"],
            seeds=tuple(raw["seeds"]),
            target_role=CellRole(str(raw["target_role"])),
            gene=str(raw["gene"]),
            value=float(raw["value"]),
            conditions=tuple(conditions),
            timing_contrasts=tuple(contrasts),
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError(f"invalid state-conditioned intervention config: {error}") from error


@dataclass(frozen=True, slots=True)
class InterventionContextAudit:
    condition_id: str
    seed: int
    onset_tick: int
    context_tick: int
    baseline_context_digest: str
    pre_onset_max_layer_distance: float
    post_onset_mean_l4_distance: float


@dataclass(frozen=True, slots=True)
class TimingContrastResult:
    contrast_id: str
    seed: int
    early_condition_id: str
    late_condition_id: str
    terminal_l4_distance: float
    late_minus_early_metrics: tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class StateConditionedInterventionResult:
    config: StateConditionedInterventionConfig
    experiment_id: str
    scenario_digest: str
    runner_model_versions: tuple[tuple[str, str], ...]
    target_ids: tuple[str, ...]
    records: tuple[CausalRunRecord, ...]
    comparisons: tuple[CausalComparison, ...]
    context_audits: tuple[InterventionContextAudit, ...]
    timing_contrasts: tuple[TimingContrastResult, ...]

    def summary_dict(self) -> dict[str, Any]:
        condition_count = 1 + len(self.config.conditions)
        return {
            "schema_version": "mgba-state-conditioned-intervention-result-0.1",
            "experiment_id": self.experiment_id,
            "scenario_digest": self.scenario_digest,
            "config": json.loads(canonical_json(self.config)),
            "runner_model_versions": dict(self.runner_model_versions),
            "target_count": len(self.target_ids),
            "condition_count": condition_count,
            "run_count": len(self.records),
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
            "comparisons": json.loads(canonical_json(self.comparisons)),
            "context_audits": json.loads(canonical_json(self.context_audits)),
            "timing_contrasts": json.loads(canonical_json(self.timing_contrasts)),
            "model_status": (
                "state-conditioned-scheduled-L0-reference-experiment; "
                "not an AIDO model or biological/clinical predictor"
            ),
        }


def build_carm_intervention_runner(
    compiled: CompiledCarmScenario,
    *,
    runner_config: RunnerConfig,
    l0_config: str | Path,
    l1_config: str | Path,
    l4_config: str | Path,
) -> MultirateCrossScaleRunner:
    return MultirateCrossScaleRunner(
        runner_config,
        genome_model=DiscreteGrnModel(load_grn_config(l0_config)),
        molecular_model=CoarseMolecularModel(load_molecular_config(l1_config)),
        cell_model=CarmCellModel(
            compiled.config.cell_model,
            roles=compiled.roles,
            source_profile_digest=compiled.profile_digest,
        ),
        tissue_model=CarmTissueModel(
            compiled.config.tissue_model,
            roles=compiled.roles,
            source_profile_digest=compiled.profile_digest,
        ),
        phenotype_model=PhenotypeObserverModel(load_phenotype_config(l4_config)),
    )


def _context_digest(run: MultirateRun, onset_tick: int) -> tuple[int, str]:
    if onset_tick == 1:
        return 0, digest_payload(
            {
                "phase": "scenario-initial",
                "scenario": run.manifest.config_digest,
            }
        )
    context = run.ticks[onset_tick - 2]
    return context.logical_time, digest_payload(
        {"l0": context.l0, "l1": context.l1, "l2": context.l2, "l3": context.l3}
    )


def _l4_distance(left: Any, right: Any) -> float:
    return fmean(abs(getattr(left, name) - getattr(right, name)) for name in _L4_METRICS)


class StateConditionedInterventionRunner:
    def __init__(
        self,
        config: StateConditionedInterventionConfig,
        *,
        runner: MultirateCrossScaleRunner,
    ) -> None:
        self.config = config
        self.runner = runner
        if config.ticks > runner.config.max_total_ticks:
            raise ValueError("intervention horizon exceeds the runner budget")
        for condition in config.conditions:
            if any((tick - 1) % runner.config.l0_interval != 0 for tick in condition.l0_update_ticks):
                raise ValueError("every scheduled intervention must align with the L0 clock")

    def run(self, compiled: CompiledCarmScenario) -> StateConditionedInterventionResult:
        if not isinstance(compiled, CompiledCarmScenario):
            raise TypeError("CAR-M intervention experiment requires a compiled scenario")
        targets = tuple(
            cell_id
            for cell_id, role in compiled.roles
            if role is self.config.target_role
        )
        if not targets:
            raise ValueError("intervention target role has no Cells")

        records: list[CausalRunRecord] = []
        for seed in self.config.seeds:
            scenario = replace(compiled.scenario, seed=seed)
            baseline = self.runner.run(scenario, ticks=self.config.ticks)
            records.append(
                CausalRunRecord(
                    condition_id="baseline",
                    condition_kind=ConditionKind.BASELINE,
                    seed=seed,
                    run=baseline,
                )
            )
            for condition in self.config.conditions:
                tick_values = {
                    tick: {
                        target: {self.config.gene: self.config.value}
                        for target in targets
                    }
                    for tick in condition.l0_update_ticks
                }
                run = self.runner.run(
                    scenario,
                    ticks=self.config.ticks,
                    perturbation_schedule=tick_values,
                )
                observed_event_ticks = tuple(
                    tick.logical_time
                    for tick in run.ticks
                    if tick.l0_perturbation_events
                )
                if observed_event_ticks != condition.l0_update_ticks:
                    raise RuntimeError("scheduled L0 intervention event timing drifted")
                records.append(
                    CausalRunRecord(
                        condition_id=condition.condition_id,
                        condition_kind=ConditionKind.PERTURBATION,
                        seed=seed,
                        run=run,
                    )
                )

        record_map = {(item.condition_id, item.seed): item for item in records}
        comparisons = tuple(
            _compare_runs(record_map[("baseline", seed)], record_map[(condition.condition_id, seed)])
            for condition in self.config.conditions
            for seed in self.config.seeds
        )
        audits = []
        for condition in self.config.conditions:
            onset = condition.l0_update_ticks[0]
            for seed in self.config.seeds:
                baseline = record_map[("baseline", seed)].run
                intervention = record_map[(condition.condition_id, seed)].run
                pre_distances = []
                for left_tick, right_tick in zip(baseline.ticks, intervention.ticks, strict=True):
                    if left_tick.logical_time >= onset:
                        break
                    for layer in LayerId:
                        value = _tick_layer_distance(layer, left_tick, right_tick)
                        if value is not None:
                            pre_distances.append(value)
                post_l4 = [
                    _l4_distance(left.l4, right.l4)
                    for left, right in zip(baseline.ticks, intervention.ticks, strict=True)
                    if left.logical_time >= onset and left.l4 is not None and right.l4 is not None
                ]
                context_tick, context_digest = _context_digest(baseline, onset)
                audit = InterventionContextAudit(
                    condition_id=condition.condition_id,
                    seed=seed,
                    onset_tick=onset,
                    context_tick=context_tick,
                    baseline_context_digest=context_digest,
                    pre_onset_max_layer_distance=max(pre_distances, default=0.0),
                    post_onset_mean_l4_distance=fmean(post_l4) if post_l4 else 0.0,
                )
                if audit.pre_onset_max_layer_distance > 1e-12:
                    raise RuntimeError("intervention condition diverged before its onset")
                audits.append(audit)

        contrast_results = []
        for contrast in self.config.timing_contrasts:
            for seed in self.config.seeds:
                early = record_map[(contrast.early_condition_id, seed)].run
                late = record_map[(contrast.late_condition_id, seed)].run
                contrast_results.append(
                    TimingContrastResult(
                        contrast_id=contrast.contrast_id,
                        seed=seed,
                        early_condition_id=contrast.early_condition_id,
                        late_condition_id=contrast.late_condition_id,
                        terminal_l4_distance=_l4_distance(
                            early.terminal_observation, late.terminal_observation
                        ),
                        late_minus_early_metrics=tuple(
                            (
                                name,
                                getattr(late.terminal_observation, name)
                                - getattr(early.terminal_observation, name),
                            )
                            for name in _L4_METRICS
                        ),
                    )
                )

        scenario_digest = digest_payload(compiled.scenario)
        experiment_id = "state-intervention-" + digest_payload(
            {
                "config": self.config,
                "scenario": scenario_digest,
                "runner": self.runner.model_versions,
                "targets": targets,
                "records": [
                    (item.condition_id, item.seed, item.run.history_digest)
                    for item in records
                ],
            }
        )[:16]
        return StateConditionedInterventionResult(
            config=self.config,
            experiment_id=experiment_id,
            scenario_digest=scenario_digest,
            runner_model_versions=self.runner.model_versions,
            target_ids=targets,
            records=tuple(records),
            comparisons=comparisons,
            context_audits=tuple(audits),
            timing_contrasts=tuple(contrast_results),
        )


def _write_once(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise ValueError(f"refusing to overwrite different intervention artifact: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def save_state_conditioned_intervention_artifacts(
    artifact_root: str | Path,
    result: StateConditionedInterventionResult,
) -> dict[str, Path]:
    root = Path(artifact_root) / result.experiment_id
    raw_root = root / "raw"
    summary = root / "derived" / "summary.json"
    manifest = root / "manifest.json"
    raw_paths = []
    for record in result.records:
        path = raw_root / f"{record.condition_id}-seed-{record.seed}.json"
        save_run_artifact(path, record.run)
        raw_paths.append(path)
    _write_once(summary, result.summary_dict())
    files = [*raw_paths, summary]
    _write_once(
        manifest,
        {
            "schema_version": "mgba-state-conditioned-intervention-manifest-0.1",
            "experiment_id": result.experiment_id,
            "files": [
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": _file_sha256(path),
                    "bytes": path.stat().st_size,
                }
                for path in files
            ],
        },
    )
    return {"root": root, "manifest": manifest, "summary": summary}
