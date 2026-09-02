from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping

from .experiment import write_json_once
from .hashing import canonical_json, digest_payload
from .layers import LayerId, OrganismOutcome
from .multiscale import MultiscaleScenario
from .runner import (
    MultirateCrossScaleRunner,
    MultirateRun,
    MultiscaleTickTrace,
    save_run_artifact,
)


_CONDITION_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_ALLOWED_ABLATIONS = ("l1_static", "l2_static", "l3_static")
_ABLATION_LAYER = {
    "l1_static": "L1",
    "l2_static": "L2",
    "l3_static": "L3",
}
_LAYER_ORDER = tuple(LayerId)
_L4_METRICS = (
    "vitality",
    "damage_burden",
    "inflammation",
    "homeostasis",
    "recovery_capacity",
)


class ConditionKind(StrEnum):
    BASELINE = "baseline"
    PERTURBATION = "perturbation"
    ABLATION = "ablation"


@dataclass(frozen=True, slots=True)
class PerturbationCondition:
    condition_id: str
    cell_id: str
    gene: str
    value: float

    def __post_init__(self) -> None:
        if not _CONDITION_ID.fullmatch(self.condition_id):
            raise ValueError("condition_id contains unsupported path characters")
        if self.condition_id == "baseline":
            raise ValueError("baseline is reserved for the control condition")
        if not self.cell_id.strip() or not self.gene.strip():
            raise ValueError("perturbation Cell and gene names must not be empty")
        if not math.isfinite(self.value) or not 0.0 <= self.value <= 1.0:
            raise ValueError("perturbation value must be finite and in [0, 1]")


@dataclass(frozen=True, slots=True)
class GroupPerturbationCondition:
    condition_id: str
    targets: tuple[str, ...]
    gene: str
    value: float

    def __post_init__(self) -> None:
        if not _CONDITION_ID.fullmatch(self.condition_id):
            raise ValueError("condition_id contains unsupported path characters")
        if self.condition_id == "baseline":
            raise ValueError("baseline is reserved for the control condition")
        if not self.targets or self.targets != tuple(sorted(self.targets)):
            raise ValueError("group perturbation targets must be non-empty and sorted")
        if len(set(self.targets)) != len(self.targets):
            raise ValueError("group perturbation targets must be unique")
        if any(not target.strip() for target in self.targets) or not self.gene.strip():
            raise ValueError("perturbation Cell and gene names must not be empty")
        if not math.isfinite(self.value) or not 0.0 <= self.value <= 1.0:
            raise ValueError("perturbation value must be finite and in [0, 1]")


PerturbationSpec = PerturbationCondition | GroupPerturbationCondition


def _condition_targets(condition: PerturbationSpec) -> tuple[str, ...]:
    if isinstance(condition, GroupPerturbationCondition):
        return condition.targets
    return (condition.cell_id,)


@dataclass(frozen=True, slots=True)
class CausalExperimentConfig:
    model_version: str
    ticks: int
    seeds: tuple[int, ...]
    perturbations: tuple[PerturbationSpec, ...]
    ablations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("causal matrix model_version must not be empty")
        if isinstance(self.ticks, bool) or not isinstance(self.ticks, int) or self.ticks < 1:
            raise ValueError("causal matrix ticks must be a positive integer")
        if len(self.seeds) < 2:
            raise ValueError("causal matrix requires at least two seeds")
        if self.seeds != tuple(sorted(self.seeds)) or len(set(self.seeds)) != len(
            self.seeds
        ):
            raise ValueError("causal matrix seeds must be unique and sorted")
        if any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in self.seeds
        ):
            raise ValueError("causal matrix seeds must be non-negative integers")
        if len(self.perturbations) < 2:
            raise ValueError("causal matrix requires multiple perturbation doses")
        condition_ids = [item.condition_id for item in self.perturbations]
        if len(condition_ids) != len(set(condition_ids)):
            raise ValueError("causal matrix condition ids must be unique")
        if len(self.ablations) != len(set(self.ablations)) or any(
            item not in _ALLOWED_ABLATIONS for item in self.ablations
        ):
            raise ValueError("causal matrix contains duplicate or unknown ablations")
        if set(condition_ids) & set(self.ablations):
            raise ValueError("perturbation and ablation condition ids must be distinct")


def load_causal_config(path: str | Path) -> CausalExperimentConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))

        def load_perturbation(item: Mapping[str, Any]) -> PerturbationSpec:
            has_cell_id = "cell_id" in item
            has_targets = "targets" in item
            if has_cell_id == has_targets:
                raise ValueError(
                    "each perturbation requires exactly one of cell_id or targets"
                )
            common = {
                "condition_id": str(item["condition_id"]),
                "gene": str(item["gene"]),
                "value": float(item["value"]),
            }
            if has_targets:
                raw_targets = item["targets"]
                if not isinstance(raw_targets, list):
                    raise ValueError("group perturbation targets must be a JSON array")
                return GroupPerturbationCondition(
                    targets=tuple(str(target) for target in raw_targets),
                    **common,
                )
            return PerturbationCondition(cell_id=str(item["cell_id"]), **common)

        return CausalExperimentConfig(
            model_version=str(raw["model_version"]),
            ticks=raw["ticks"],
            seeds=tuple(raw["seeds"]),
            perturbations=tuple(load_perturbation(item) for item in raw["perturbations"]),
            ablations=tuple(str(item) for item in raw["ablations"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid causal experiment config: {error}") from error


def _json_value(value: Any) -> Any:
    return json.loads(canonical_json(value))


@dataclass(frozen=True, slots=True)
class CausalRunRecord:
    condition_id: str
    condition_kind: ConditionKind
    seed: int
    run: MultirateRun

    def __post_init__(self) -> None:
        if not _CONDITION_ID.fullmatch(self.condition_id):
            raise ValueError("run record condition_id is invalid")
        if self.run.manifest.seed != self.seed:
            raise ValueError("run record seed must match its manifest")


@dataclass(frozen=True, slots=True)
class CausalComparison:
    condition_id: str
    condition_kind: ConditionKind
    seed: int
    baseline_experiment_id: str
    condition_experiment_id: str
    baseline_history_digest: str
    condition_history_digest: str
    layer_effects: tuple[tuple[LayerId, float], ...]
    propagation_ticks: tuple[tuple[LayerId, int | None], ...]
    final_metric_effects: tuple[tuple[str, float], ...]
    baseline_outcome: OrganismOutcome
    condition_outcome: OrganismOutcome

    def __post_init__(self) -> None:
        if self.condition_kind is ConditionKind.BASELINE:
            raise ValueError("baseline cannot be compared against itself")
        if tuple(layer for layer, _ in self.layer_effects) != _LAYER_ORDER:
            raise ValueError("comparison layer effects must contain L0-L4 in order")
        if tuple(layer for layer, _ in self.propagation_ticks) != _LAYER_ORDER:
            raise ValueError("comparison propagation must contain L0-L4 in order")
        if any(
            not math.isfinite(value) or not 0.0 <= value <= 1.0
            for _, value in self.layer_effects
        ):
            raise ValueError("layer effects must be finite and in [0, 1]")
        if any(value is not None and value < 1 for _, value in self.propagation_ticks):
            raise ValueError("propagation ticks must be positive or null")
        if tuple(name for name, _ in self.final_metric_effects) != _L4_METRICS:
            raise ValueError("comparison final metric effects are incomplete")
        if any(
            not math.isfinite(value) or not -1.0 <= value <= 1.0
            for _, value in self.final_metric_effects
        ):
            raise ValueError("final metric effects must be finite and in [-1, 1]")


@dataclass(frozen=True, slots=True)
class ConditionSummary:
    condition_id: str
    condition_kind: ConditionKind
    seeds: tuple[int, ...]
    mean_layer_effects: tuple[tuple[LayerId, float], ...]
    mean_propagation_ticks: tuple[tuple[LayerId, float | None], ...]
    mean_final_metric_effects: tuple[tuple[str, float], ...]
    outcome_counts: tuple[tuple[OrganismOutcome, int], ...]


@dataclass(frozen=True, slots=True)
class CausalMatrixResult:
    config: CausalExperimentConfig
    matrix_id: str
    scenario_digest: str
    runner_model_versions: tuple[
        tuple[str, tuple[tuple[str, str], ...]], ...
    ]
    records: tuple[CausalRunRecord, ...]
    comparisons: tuple[CausalComparison, ...]
    summaries: tuple[ConditionSummary, ...]

    def __post_init__(self) -> None:
        condition_count = 1 + len(self.config.perturbations) + len(
            self.config.ablations
        )
        if len(self.records) != condition_count * len(self.config.seeds):
            raise ValueError("causal matrix run count is incomplete")
        if len(self.comparisons) != (condition_count - 1) * len(
            self.config.seeds
        ):
            raise ValueError("causal matrix comparison count is incomplete")
        if len(self.summaries) != condition_count - 1:
            raise ValueError("causal matrix condition summaries are incomplete")

    def summary_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "mgba-causal-matrix-0.1",
            "matrix_id": self.matrix_id,
            "scenario_digest": self.scenario_digest,
            "config": _json_value(self.config),
            "runner_model_versions": _json_value(self.runner_model_versions),
            "condition_count": 1
            + len(self.config.perturbations)
            + len(self.config.ablations),
            "run_count": len(self.records),
            "comparison_count": len(self.comparisons),
            "records": [
                {
                    "condition_id": record.condition_id,
                    "condition_kind": record.condition_kind.value,
                    "seed": record.seed,
                    "experiment_id": record.run.manifest.experiment_id,
                    "history_digest": record.run.history_digest,
                    "outcome": record.run.phenotype_window.outcome.value,
                }
                for record in self.records
            ],
            "comparisons": _json_value(self.comparisons),
            "summaries": _json_value(self.summaries),
        }

    def report_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "mgba-causal-report-0.1",
            "matrix_id": self.matrix_id,
            "scenario_digest": self.scenario_digest,
            "condition_count": 1
            + len(self.config.perturbations)
            + len(self.config.ablations),
            "run_count": len(self.records),
            "comparison_count": len(self.comparisons),
            "summaries": _json_value(self.summaries),
        }


def _mean_absolute(differences: list[float]) -> float:
    if not differences:
        raise ValueError("layer distance requires at least one value")
    return fmean(differences)


def _aligned_state_pairs(baseline: tuple[Any, ...], condition: tuple[Any, ...]):
    baseline_ids = tuple(state.cell_id for state in baseline)
    condition_ids = tuple(state.cell_id for state in condition)
    if baseline_ids != condition_ids:
        raise ValueError("paired layer states must have aligned Cell ids")
    return zip(baseline, condition, strict=True)


def _l0_distance(
    baseline: MultiscaleTickTrace, condition: MultiscaleTickTrace
) -> float:
    fields = (
        "damage_response",
        "signal_expression",
        "repair_expression",
        "metabolic_expression",
        "death_expression",
        "negative_feedback_expression",
    )
    return _mean_absolute(
        [
            abs(getattr(left, field) - getattr(right, field))
            for left, right in _aligned_state_pairs(baseline.l0, condition.l0)
            for field in fields
        ]
    )


def _l1_distance(
    baseline: MultiscaleTickTrace, condition: MultiscaleTickTrace
) -> float:
    fields = (
        "damage_receptor",
        "signal_protein",
        "repair_protein",
        "metabolic_capacity",
        "death_effector",
        "feedback_inhibitor",
    )
    return _mean_absolute(
        [
            abs(getattr(left, field) - getattr(right, field))
            for left, right in _aligned_state_pairs(baseline.l1, condition.l1)
            for field in fields
        ]
    )


def _l2_distance(
    baseline: MultiscaleTickTrace, condition: MultiscaleTickTrace
) -> float:
    differences: list[float] = []
    for left, right in _aligned_state_pairs(baseline.l2, condition.l2):
        differences.extend(
            (
                float(left.phase != right.phase),
                abs(left.activation - right.activation),
                abs(left.viability - right.viability),
                abs(left.stress_load - right.stress_load),
            )
        )
    return _mean_absolute(differences)


def _l3_distance(
    baseline: MultiscaleTickTrace, condition: MultiscaleTickTrace
) -> float:
    left = baseline.l3
    right = condition.l3
    if tuple(node.cell_id for node in left.nodes) != tuple(
        node.cell_id for node in right.nodes
    ):
        raise ValueError("paired TissueState nodes must align")
    differences = [float(left.edges != right.edges)]
    for left_node, right_node in zip(left.nodes, right.nodes, strict=True):
        differences.extend(
            (
                abs(left_node.stress - right_node.stress),
                abs(left_node.resource_level - right_node.resource_level),
                abs(left_node.signal - right_node.signal),
            )
        )
    fields = (
        "edge_density",
        "mean_activation",
        "mean_viability",
        "mean_resource",
        "mean_signal",
        "dead_fraction",
        "repair_activity",
        "coordinated_signal",
        "tissue_damage",
    )
    differences.extend(
        abs(getattr(left, field) - getattr(right, field)) for field in fields
    )
    return _mean_absolute(differences)


def _l4_distance_from_states(left: Any, right: Any) -> float:
    return _mean_absolute(
        [abs(getattr(left, field) - getattr(right, field)) for field in _L4_METRICS]
    )


def tick_layer_distance(
    layer: LayerId,
    baseline: MultiscaleTickTrace,
    condition: MultiscaleTickTrace,
) -> float | None:
    if layer is LayerId.L0:
        return _l0_distance(baseline, condition)
    if layer is LayerId.L1:
        return _l1_distance(baseline, condition)
    if layer is LayerId.L2:
        return _l2_distance(baseline, condition)
    if layer is LayerId.L3:
        return _l3_distance(baseline, condition)
    if baseline.l4 is None or condition.l4 is None:
        return None
    return _l4_distance_from_states(baseline.l4, condition.l4)


def compare_runs(
    baseline: CausalRunRecord, condition: CausalRunRecord
) -> CausalComparison:
    if baseline.seed != condition.seed:
        raise ValueError("causal comparisons must pair the same seed")
    baseline_end = baseline.run.ticks[-1]
    condition_end = condition.run.ticks[-1]
    layer_effects: list[tuple[LayerId, float]] = []
    propagation: list[tuple[LayerId, int | None]] = []
    for layer in _LAYER_ORDER:
        if layer is LayerId.L4:
            terminal_distance = _l4_distance_from_states(
                baseline.run.terminal_observation,
                condition.run.terminal_observation,
            )
            layer_effects.append((layer, terminal_distance))
        else:
            distance = tick_layer_distance(layer, baseline_end, condition_end)
            assert distance is not None
            layer_effects.append((layer, distance))

        first_difference: int | None = None
        for left_tick, right_tick in zip(
            baseline.run.ticks, condition.run.ticks, strict=True
        ):
            distance = tick_layer_distance(layer, left_tick, right_tick)
            if distance is not None and distance > 1e-12:
                first_difference = left_tick.logical_time
                break
        if (
            layer is LayerId.L4
            and first_difference is None
            and layer_effects[-1][1] > 1e-12
        ):
            first_difference = condition.run.end_tick
        propagation.append((layer, first_difference))

    final_metric_effects = tuple(
        (
            field,
            getattr(condition.run.terminal_observation, field)
            - getattr(baseline.run.terminal_observation, field),
        )
        for field in _L4_METRICS
    )
    return CausalComparison(
        condition_id=condition.condition_id,
        condition_kind=condition.condition_kind,
        seed=condition.seed,
        baseline_experiment_id=baseline.run.manifest.experiment_id,
        condition_experiment_id=condition.run.manifest.experiment_id,
        baseline_history_digest=baseline.run.history_digest,
        condition_history_digest=condition.run.history_digest,
        layer_effects=tuple(layer_effects),
        propagation_ticks=tuple(propagation),
        final_metric_effects=final_metric_effects,
        baseline_outcome=baseline.run.phenotype_window.outcome,
        condition_outcome=condition.run.phenotype_window.outcome,
    )


def summarize_condition(
    condition_id: str,
    comparisons: tuple[CausalComparison, ...],
) -> ConditionSummary:
    if not comparisons:
        raise ValueError("condition summary requires comparisons")
    layer_effects = tuple(
        (
            layer,
            fmean(dict(item.layer_effects)[layer] for item in comparisons),
        )
        for layer in _LAYER_ORDER
    )
    propagation = []
    for layer in _LAYER_ORDER:
        observed = [
            value
            for item in comparisons
            if (value := dict(item.propagation_ticks)[layer]) is not None
        ]
        propagation.append((layer, fmean(observed) if observed else None))
    metric_effects = tuple(
        (
            metric,
            fmean(dict(item.final_metric_effects)[metric] for item in comparisons),
        )
        for metric in _L4_METRICS
    )
    outcome_counts = tuple(
        (
            outcome,
            sum(item.condition_outcome is outcome for item in comparisons),
        )
        for outcome in OrganismOutcome
    )
    return ConditionSummary(
        condition_id=condition_id,
        condition_kind=comparisons[0].condition_kind,
        seeds=tuple(item.seed for item in comparisons),
        mean_layer_effects=layer_effects,
        mean_propagation_ticks=tuple(propagation),
        mean_final_metric_effects=metric_effects,
        outcome_counts=outcome_counts,
    )


class CausalExperimentRunner:
    """Runs frozen paired perturbation/ablation comparisons over raw traces."""

    def __init__(
        self,
        config: CausalExperimentConfig,
        *,
        runners: Mapping[str, MultirateCrossScaleRunner],
    ) -> None:
        self.config = config
        expected_runners = {"baseline", *config.ablations}
        if set(runners) != expected_runners:
            raise ValueError("causal matrix runners must match baseline and ablations")
        self.runners = dict(runners)
        baseline_versions = dict(self.runners["baseline"].model_versions)
        for ablation in config.ablations:
            versions = dict(self.runners[ablation].model_versions)
            changed = {
                layer
                for layer, version in versions.items()
                if version != baseline_versions[layer]
            }
            if changed != {_ABLATION_LAYER[ablation]}:
                raise ValueError(
                    f"{ablation} runner must change only {_ABLATION_LAYER[ablation]}"
                )
        if any(
            config.ticks > runner.config.max_total_ticks
            for runner in self.runners.values()
        ):
            raise ValueError("causal matrix ticks exceed a runner budget")

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    def run(self, scenario: MultiscaleScenario) -> CausalMatrixResult:
        if not isinstance(scenario, MultiscaleScenario):
            raise TypeError("causal matrix requires a MultiscaleScenario")
        known_cell_ids = {cell_id for cell_id, _ in scenario.genomes}
        unknown_targets = {
            target
            for item in self.config.perturbations
            for target in _condition_targets(item)
        } - known_cell_ids
        if unknown_targets:
            raise ValueError(
                f"causal perturbations target unknown cells: {sorted(unknown_targets)}"
            )

        conditions: list[
            tuple[str, ConditionKind, MultirateCrossScaleRunner, dict[str, dict[str, float]]]
        ] = [
            (
                "baseline",
                ConditionKind.BASELINE,
                self.runners["baseline"],
                {},
            )
        ]
        conditions.extend(
            (
                item.condition_id,
                ConditionKind.PERTURBATION,
                self.runners["baseline"],
                {
                    target: {item.gene: item.value}
                    for target in _condition_targets(item)
                },
            )
            for item in self.config.perturbations
        )
        conditions.extend(
            (
                ablation,
                ConditionKind.ABLATION,
                self.runners[ablation],
                {},
            )
            for ablation in self.config.ablations
        )

        records: list[CausalRunRecord] = []
        for condition_id, kind, runner, perturbations in conditions:
            for seed in self.config.seeds:
                seeded_scenario = replace(scenario, seed=seed)
                run = runner.run(
                    seeded_scenario,
                    ticks=self.config.ticks,
                    perturbations=perturbations,
                )
                if len(run.ticks) != self.config.ticks:
                    raise RuntimeError("E0 failed: run did not produce every tick")
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
            compare_runs(record_map[("baseline", seed)], record)
            for condition_id, kind, _, _ in conditions
            if kind is not ConditionKind.BASELINE
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
            for condition_id, kind, _, _ in conditions
            if kind is not ConditionKind.BASELINE
        )
        runner_versions = tuple(
            (name, runner.model_versions)
            for name, runner in sorted(self.runners.items())
        )
        scenario_digest = digest_payload(scenario)
        matrix_id = f"matrix-{digest_payload({'config': self.config, 'scenario': scenario, 'runners': runner_versions})[:16]}"
        return CausalMatrixResult(
            config=self.config,
            matrix_id=matrix_id,
            scenario_digest=scenario_digest,
            runner_model_versions=runner_versions,
            records=tuple(records),
            comparisons=comparisons,
            summaries=summaries,
        )


@dataclass(frozen=True, slots=True)
class CausalArtifactPaths:
    root: Path
    manifest: Path
    raw: Path
    summary: Path




def save_causal_artifacts(
    artifact_root: str | Path, result: CausalMatrixResult
) -> CausalArtifactPaths:
    if not isinstance(result, CausalMatrixResult):
        raise TypeError("save_causal_artifacts requires a CausalMatrixResult")
    root = Path(artifact_root) / result.matrix_id
    raw_root = root / "raw"
    summary_path = root / "derived" / "summary.json"
    manifest_path = root / "manifest.json"
    record_index = []
    for record in result.records:
        relative_path = (
            Path("raw")
            / record.condition_id
            / f"seed-{record.seed}.json"
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
        "schema_version": "mgba-causal-artifact-0.1",
        "matrix_id": result.matrix_id,
        "scenario_digest": result.scenario_digest,
        "config": _json_value(result.config),
        "runner_model_versions": _json_value(result.runner_model_versions),
        "records": record_index,
    }
    write_json_once(manifest_path, manifest, artifact="causal artifact")
    write_json_once(summary_path, result.summary_dict(), artifact="causal artifact")
    return CausalArtifactPaths(
        root=root,
        manifest=manifest_path,
        raw=raw_root,
        summary=summary_path,
    )
