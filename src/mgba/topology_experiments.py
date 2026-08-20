"""E5 topology experiment: static vs adaptive L3 topology governance.

Runs the same scenario and seed set through two runners that differ only in
the L3 ``TissueModel`` — the frozen fixed-graph environment model versus the
governed dynamic-topology model — and compares them with the WP8
paired-comparison machinery (per-layer mean absolute distance, directed
final L4 metric effects, first propagation tick).  It additionally reports
topology-stability metrics required by the E5 protocol: total committed
swaps, ticks with at least one swap, and the final edge-count delta.
"""

from __future__ import annotations

import json
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
from .multiscale import MultiscaleScenario
from .runner import MultirateCrossScaleRunner, save_run_artifact


_TOPOLOGY_CONDITIONS = ("static_topology", "adaptive_topology")


@dataclass(frozen=True, slots=True)
class TopologyExperimentConfig:
    """Frozen protocol parameters for the E5 topology comparison."""

    model_version: str
    ticks: int
    seeds: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("topology experiment model_version must not be empty")
        if (
            isinstance(self.ticks, bool)
            or not isinstance(self.ticks, int)
            or self.ticks < 1
        ):
            raise ValueError("topology experiment ticks must be a positive integer")
        if len(self.seeds) < 2:
            raise ValueError("topology experiment requires at least two seeds")
        if self.seeds != tuple(sorted(self.seeds)) or len(set(self.seeds)) != len(
            self.seeds
        ):
            raise ValueError("topology experiment seeds must be unique and sorted")
        if any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in self.seeds
        ):
            raise ValueError("topology experiment seeds must be non-negative integers")


def load_topology_experiment_config(
    path: str | Path,
) -> TopologyExperimentConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return TopologyExperimentConfig(
            model_version=str(raw["model_version"]),
            ticks=int(raw["ticks"]),
            seeds=tuple(int(item) for item in raw["seeds"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid topology experiment config: {error}") from error


@dataclass(frozen=True, slots=True)
class TopologyStability:
    """E5 topology-stability metrics for one adaptive run."""

    condition_id: str
    seed: int
    committed_swaps: int
    ticks_with_swaps: int
    initial_edge_count: int
    final_edge_count: int

    def __post_init__(self) -> None:
        if self.committed_swaps < 0 or self.ticks_with_swaps < 0:
            raise ValueError("topology stability counters must be non-negative")
        if self.initial_edge_count < 0 or self.final_edge_count < 0:
            raise ValueError("edge counts must be non-negative")
        if self.ticks_with_swaps > self.committed_swaps:
            raise ValueError("swap ticks cannot exceed committed swaps")

    def as_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "seed": self.seed,
            "committed_swaps": self.committed_swaps,
            "ticks_with_swaps": self.ticks_with_swaps,
            "initial_edge_count": self.initial_edge_count,
            "final_edge_count": self.final_edge_count,
            "edge_count_delta": self.final_edge_count - self.initial_edge_count,
        }


@dataclass(frozen=True, slots=True)
class TopologyMatrixResult:
    """Static-vs-adaptive paired-comparison matrix with stability metrics."""

    config: TopologyExperimentConfig
    matrix_id: str
    scenario_digest: str
    runner_model_versions: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    records: tuple[CausalRunRecord, ...]
    comparisons: tuple[CausalComparison, ...]
    summaries: tuple[ConditionSummary, ...]
    stability: tuple[TopologyStability, ...]

    def __post_init__(self) -> None:
        if not self.records or not self.comparisons or not self.summaries:
            raise ValueError("topology matrix requires records and comparisons")

    def summary_dict(self) -> dict[str, Any]:
        from dataclasses import asdict, is_dataclass

        def _default(value: Any) -> Any:
            if is_dataclass(value) and not isinstance(value, type):
                return asdict(value)
            raise TypeError(f"not JSON serializable: {value!r}")

        return {
            "schema_version": "mgba-topology-artifact-0.1",
            "matrix_id": self.matrix_id,
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
            "topology_stability": [item.as_dict() for item in self.stability],
        }





class TopologyExperimentRunner:
    """Runs the frozen static-vs-adaptive L3 topology comparison matrix."""

    def __init__(
        self,
        config: TopologyExperimentConfig,
        *,
        runners: Mapping[str, MultirateCrossScaleRunner],
    ) -> None:
        if set(runners) != set(_TOPOLOGY_CONDITIONS):
            raise ValueError(
                "topology matrix requires static_topology and "
                "adaptive_topology runners"
            )
        baseline_versions = dict(runners["static_topology"].model_versions)
        adaptive_versions = dict(runners["adaptive_topology"].model_versions)
        changed = {
            layer
            for layer, version in adaptive_versions.items()
            if version != baseline_versions[layer]
        }
        if changed != {"L3"}:
            raise ValueError(
                "the adaptive topology runner must differ from the static "
                "runner in L3 only"
            )
        self.config = config
        self.runners = dict(runners)
        if any(
            config.ticks > runner.config.max_total_ticks
            for runner in self.runners.values()
        ):
            raise ValueError("topology matrix ticks exceed a runner budget")

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    def run(self, scenario: MultiscaleScenario) -> TopologyMatrixResult:
        if not isinstance(scenario, MultiscaleScenario):
            raise TypeError("topology matrix requires a MultiscaleScenario")

        from dataclasses import replace

        records: list[CausalRunRecord] = []
        for condition_id in _TOPOLOGY_CONDITIONS:
            runner = self.runners[condition_id]
            kind = (
                ConditionKind.BASELINE
                if condition_id == "static_topology"
                else ConditionKind.PERTURBATION
            )
            for seed in self.config.seeds:
                seeded_scenario = replace(scenario, seed=seed)
                run = runner.run(seeded_scenario, ticks=self.config.ticks)
                if len(run.ticks) != self.config.ticks:
                    raise RuntimeError(
                        "E0 failed: topology run did not produce every tick"
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
            _compare_runs(record_map[("static_topology", seed)], record)
            for seed in self.config.seeds
            for record in (record_map[("adaptive_topology", seed)],)
        )
        summaries = (
            _summarize_condition(
                "adaptive_topology",
                tuple(comparisons),
            ),
        )
        stability = tuple(
            _topology_stability(record)
            for record in records
            if record.condition_id == "adaptive_topology"
        )
        runner_versions = tuple(
            (name, runner.model_versions)
            for name, runner in sorted(self.runners.items())
        )
        matrix_id = (
            f"topology-{digest_payload({'config': self.config, 'scenario': scenario, 'runners': runner_versions})[:16]}"
        )
        return TopologyMatrixResult(
            config=self.config,
            matrix_id=matrix_id,
            scenario_digest=digest_payload(scenario),
            runner_model_versions=runner_versions,
            records=tuple(records),
            comparisons=comparisons,
            summaries=summaries,
            stability=stability,
        )


def _topology_stability(record: CausalRunRecord) -> TopologyStability:
    """Count committed swaps from the per-tick L3 edge sequence.

    The adaptive model conserves the edge count through T1-style swaps, so
    the per-tick committed-swap count cannot be recovered from edge counts
    alone; instead we reconstruct the swap set from consecutive edge
    differences: every changed edge pair contributes one committed swap.
    """
    committed = 0
    active_ticks = 0
    previous_edges = set(record.run.ticks[0].l3.edges)
    for tick in record.run.ticks[1:]:
        current_edges = set(tick.l3.edges)
        removed = previous_edges - current_edges
        added = current_edges - previous_edges
        if removed or added:
            committed += max(len(removed), len(added))
            active_ticks += 1
        previous_edges = current_edges
    return TopologyStability(
        condition_id=record.condition_id,
        seed=record.seed,
        committed_swaps=committed,
        ticks_with_swaps=active_ticks,
        initial_edge_count=len(record.run.ticks[0].l3.edges),
        final_edge_count=len(record.run.ticks[-1].l3.edges),
    )


def save_topology_artifacts(
    artifact_root: str | Path, result: TopologyMatrixResult
) -> dict[str, Path]:
    """Persist raw runs, manifest, and derived summary (append-only)."""
    if not isinstance(result, TopologyMatrixResult):
        raise TypeError("save_topology_artifacts requires a TopologyMatrixResult")
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
        "schema_version": "mgba-topology-artifact-0.1",
        "matrix_id": result.matrix_id,
        "scenario_digest": result.scenario_digest,
        "runner_model_versions": [
            {"name": name, "versions": dict(versions)}
            for name, versions in result.runner_model_versions
        ],
        "records": record_index,
        "topology_stability": [item.as_dict() for item in result.stability],
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
            raise ValueError("existing topology artifact is invalid JSON") from error
        if existing != payload:
            raise ValueError("refusing to overwrite a different topology artifact")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
