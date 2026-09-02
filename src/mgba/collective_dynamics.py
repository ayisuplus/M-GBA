"""Deterministic, generation-chain-external collective dynamics observer.

The observer reads completed L0--L4 traces and derives dimensionless group
response proxies.  It never participates in the runner tick loop and must not
be imported by any layer model.  The resulting labels describe reference
trajectories; they are not physical phase transitions, biological mechanisms,
or clinical predictions.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .hashing import digest_payload
from .validation import finite
from .runner import MultirateRun


COLLECTIVE_DYNAMICS_SCHEMA = "mgba-collective-dynamics-0.1"
COLLECTIVE_CONFIG_SCHEMA = "mgba-collective-dynamics-config-0.1"
COLLECTIVE_OBSERVER_VERSION = "collective-dynamics-observer-0.1"
COLLECTIVE_SCIENTIFIC_BOUNDARY = (
    "群体状态与转换均为 activation-stress reference proxy；不是物理相变、"
    "真实生物机制或临床预测。"
)

_L4_FIELDS = (
    "vitality",
    "damage_burden",
    "inflammation",
    "homeostasis",
    "recovery_capacity",
)
_GROUP_STATES = (
    "low_activity",
    "activation_dominant",
    "stress_dominant",
    "population_split",
    "coactivated_balance",
    "transitional",
)
_TRAJECTORY_CLASSES = (
    "oscillatory",
    "reversal",
    "activation_convergence",
    "stress_convergence",
    "persistent_activation",
    "persistent_stress",
    "persistent_split",
    "persistent_low_activity",
    "indeterminate",
)
_CELL_ARCHETYPES = ("stable", "single_switch", "intermittent", "oscillatory")




def _rounded(value: float) -> float:
    result = round(float(value), 8)
    return 0.0 if result == 0.0 else result


@dataclass(frozen=True, slots=True)
class CollectiveDynamicsConfig:
    """Frozen thresholds for the reference collective-dynamics proxy."""

    schema_version: str = COLLECTIVE_CONFIG_SCHEMA
    cell_direction_threshold: float = 0.15
    group_direction_threshold: float = 0.15
    low_intensity_threshold: float = 0.04
    high_intensity_threshold: float = 0.16
    population_split_threshold: float = 0.09
    minimum_dwell_ticks: int = 3
    endpoint_window_ticks: int = 5
    persistent_fraction: float = 0.50
    low_activity_fraction: float = 0.80

    def __post_init__(self) -> None:
        if self.schema_version != COLLECTIVE_CONFIG_SCHEMA:
            raise ValueError("unsupported collective dynamics config schema")
        for name in (
            "cell_direction_threshold",
            "group_direction_threshold",
            "low_intensity_threshold",
            "high_intensity_threshold",
            "population_split_threshold",
        ):
            value = finite(getattr(self, name), name=name)
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be in (0, 1]")
        if self.low_intensity_threshold >= self.high_intensity_threshold:
            raise ValueError("low intensity threshold must be below high intensity threshold")
        for name in ("minimum_dwell_ticks", "endpoint_window_ticks"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("persistent_fraction", "low_activity_fraction"):
            value = finite(getattr(self, name), name=name)
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be in (0, 1]")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CollectiveDynamicsConfig":
        expected = {
            "schema_version",
            "cell_direction_threshold",
            "group_direction_threshold",
            "low_intensity_threshold",
            "high_intensity_threshold",
            "population_split_threshold",
            "minimum_dwell_ticks",
            "endpoint_window_ticks",
            "persistent_fraction",
            "low_activity_fraction",
        }
        if not isinstance(raw, Mapping) or set(raw) != expected:
            raise ValueError("collective dynamics config fields do not match the frozen schema")
        for name in ("minimum_dwell_ticks", "endpoint_window_ticks"):
            if isinstance(raw[name], bool) or not isinstance(raw[name], int):
                raise ValueError(f"{name} must be an integer")
        return cls(
            schema_version=str(raw["schema_version"]),
            cell_direction_threshold=finite(
                raw["cell_direction_threshold"], name="cell_direction_threshold"
            ),
            group_direction_threshold=finite(
                raw["group_direction_threshold"], name="group_direction_threshold"
            ),
            low_intensity_threshold=finite(
                raw["low_intensity_threshold"], name="low_intensity_threshold"
            ),
            high_intensity_threshold=finite(
                raw["high_intensity_threshold"], name="high_intensity_threshold"
            ),
            population_split_threshold=finite(
                raw["population_split_threshold"], name="population_split_threshold"
            ),
            minimum_dwell_ticks=raw["minimum_dwell_ticks"],
            endpoint_window_ticks=raw["endpoint_window_ticks"],
            persistent_fraction=finite(
                raw["persistent_fraction"], name="persistent_fraction"
            ),
            low_activity_fraction=finite(
                raw["low_activity_fraction"], name="low_activity_fraction"
            ),
        )

    @property
    def config_digest(self) -> str:
        return digest_payload(asdict(self))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_collective_dynamics_config(
    path: str | Path,
) -> CollectiveDynamicsConfig:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid collective dynamics config: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("collective dynamics config root must be an object")
    return CollectiveDynamicsConfig.from_mapping(raw)


@dataclass(frozen=True, slots=True)
class _CellView:
    cell_id: str
    activation: float
    stress_load: float


@dataclass(frozen=True, slots=True)
class _TickView:
    logical_time: int
    cells: tuple[_CellView, ...]
    edges: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _RunView:
    experiment_id: str
    history_digest: str
    ticks: tuple[_TickView, ...]
    l4_observations: tuple[tuple[int, dict[str, float]], ...]


@dataclass(frozen=True, slots=True)
class CollectiveCohortReport:
    cohort_id: str
    cell_ids: tuple[str, ...]
    series: tuple[dict[str, Any], ...]
    trajectory_class: str
    qualified_direction_switches: int
    first_qualified_transition_tick: int | None
    state_transitions: tuple[dict[str, Any], ...]
    cell_archetypes: tuple[tuple[str, str], ...]
    archetype_counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if not self.cohort_id or not self.cell_ids:
            raise ValueError("collective cohort identity must not be empty")
        if self.trajectory_class not in _TRAJECTORY_CLASSES:
            raise ValueError("unknown collective trajectory class")

    def as_dict(self) -> dict[str, Any]:
        return {
            "cohort_id": self.cohort_id,
            "cell_ids": list(self.cell_ids),
            "series": list(self.series),
            "trajectory_class": self.trajectory_class,
            "qualified_direction_switches": self.qualified_direction_switches,
            "first_qualified_transition_tick": self.first_qualified_transition_tick,
            "state_transitions": list(self.state_transitions),
            "cell_archetypes": dict(self.cell_archetypes),
            "archetype_counts": dict(self.archetype_counts),
        }


@dataclass(frozen=True, slots=True)
class CollectiveDynamicsReport:
    source_experiment_id: str
    source_history_digest: str
    config: CollectiveDynamicsConfig
    cohorts: tuple[CollectiveCohortReport, ...]
    variance_decomposition: tuple[dict[str, float | int], ...]
    l4_observations: tuple[dict[str, Any], ...]

    @property
    def report_digest(self) -> str:
        return digest_payload(self._payload())

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": COLLECTIVE_DYNAMICS_SCHEMA,
            "observer_version": COLLECTIVE_OBSERVER_VERSION,
            "source_experiment_id": self.source_experiment_id,
            "source_history_digest": self.source_history_digest,
            "config": self.config.as_dict(),
            "config_digest": self.config.config_digest,
            "scientific_boundary": COLLECTIVE_SCIENTIFIC_BOUNDARY,
            "cohorts": {
                cohort.cohort_id: cohort.as_dict() for cohort in self.cohorts
            },
            "variance_decomposition": list(self.variance_decomposition),
            "l4_observations": list(self.l4_observations),
        }

    def as_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["report_digest"] = digest_payload(payload)
        return payload


@dataclass(frozen=True, slots=True)
class CollectiveDynamicsComparison:
    reference_report_digest: str
    comparison_report_digest: str
    config_digest: str
    cohorts: tuple[tuple[str, dict[str, Any]], ...]

    @property
    def comparison_digest(self) -> str:
        return digest_payload(self._payload())

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": COLLECTIVE_DYNAMICS_SCHEMA,
            "observer_version": COLLECTIVE_OBSERVER_VERSION,
            "reference_report_digest": self.reference_report_digest,
            "comparison_report_digest": self.comparison_report_digest,
            "config_digest": self.config_digest,
            "scientific_boundary": COLLECTIVE_SCIENTIFIC_BOUNDARY,
            "cohorts": dict(self.cohorts),
        }

    def as_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["comparison_digest"] = digest_payload(payload)
        return payload


def _l4_payload(raw: Any) -> dict[str, float]:
    if isinstance(raw, Mapping):
        values = {name: finite(raw[name], name=f"L4 {name}") for name in _L4_FIELDS}
    else:
        values = {
            name: finite(getattr(raw, name), name=f"L4 {name}") for name in _L4_FIELDS
        }
    return {name: _rounded(value) for name, value in values.items()}


def _view_from_run(run: MultirateRun) -> _RunView:
    if not isinstance(run, MultirateRun):
        raise TypeError("analyze_collective_dynamics requires a MultirateRun")
    ticks = tuple(
        _TickView(
            logical_time=tick.logical_time,
            cells=tuple(
                _CellView(
                    state.cell_id,
                    finite(state.activation, name="activation"),
                    finite(state.stress_load, name="stress_load"),
                )
                for state in tick.l2
            ),
            edges=tuple((str(source), str(target)) for source, target in tick.l3.edges),
        )
        for tick in run.ticks
    )
    l4_by_tick = {
        tick.logical_time: _l4_payload(tick.l4)
        for tick in run.ticks
        if tick.l4 is not None
    }
    terminal_tick = run.terminal_observation.metadata.logical_time
    l4_by_tick[terminal_tick] = _l4_payload(run.terminal_observation)
    return _RunView(
        experiment_id=run.manifest.experiment_id,
        history_digest=run.history_digest,
        ticks=ticks,
        l4_observations=tuple(sorted(l4_by_tick.items())),
    )


def _view_from_raw_mapping(raw: Mapping[str, Any]) -> _RunView:
    """Validate a serialized ``MultirateRun.as_dict`` for the CLI boundary."""

    try:
        experiment = raw["experiment"]
        ticks_raw = raw["ticks"]
        history_digest = str(raw["history_digest"])
        terminal = raw["terminal_observation"]
    except (KeyError, TypeError) as error:
        raise ValueError(f"raw run is missing a required field: {error}") from error
    if not isinstance(experiment, Mapping) or not isinstance(ticks_raw, list) or not ticks_raw:
        raise ValueError("raw run must contain an experiment and non-empty tick list")
    if not history_digest:
        raise ValueError("raw run history digest must not be empty")
    ticks: list[_TickView] = []
    l4_by_tick: dict[int, dict[str, float]] = {}
    try:
        for raw_tick in ticks_raw:
            raw_time = raw_tick["logical_time"]
            if isinstance(raw_time, bool) or not isinstance(raw_time, int):
                raise ValueError("tick logical_time must be an integer")
            logical_time = raw_time
            cells = tuple(
                _CellView(
                    str(cell["cell_id"]),
                    finite(cell["activation"], name="activation"),
                    finite(cell["stress_load"], name="stress_load"),
                )
                for cell in raw_tick["l2"]
            )
            edges = tuple(
                (str(source), str(target)) for source, target in raw_tick["l3"]["edges"]
            )
            ticks.append(_TickView(logical_time, cells, edges))
            if raw_tick.get("l4") is not None:
                l4_by_tick[logical_time] = _l4_payload(raw_tick["l4"])
        terminal_tick = terminal["metadata"]["logical_time"]
        if isinstance(terminal_tick, bool) or not isinstance(terminal_tick, int):
            raise ValueError("terminal L4 logical_time must be an integer")
        l4_by_tick[terminal_tick] = _l4_payload(terminal)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid raw run trace: {error}") from error
    return _RunView(
        experiment_id=str(experiment["experiment_id"]),
        history_digest=history_digest,
        ticks=tuple(ticks),
        l4_observations=tuple(sorted(l4_by_tick.items())),
    )


def _view_from_lab_condition(condition: Mapping[str, Any]) -> _RunView:
    """Build the same read-only view from a LabRunBundle condition projection."""

    try:
        ticks_raw = condition["ticks"]
        terminal = condition["terminal_l4"]
        experiment_id = str(condition["experiment_id"])
        history_digest = str(condition["history_digest"])
    except (KeyError, TypeError) as error:
        raise ValueError(f"lab condition is missing a required field: {error}") from error
    if not isinstance(ticks_raw, list) or not ticks_raw:
        raise ValueError("lab condition must contain a non-empty tick list")
    ticks: list[_TickView] = []
    l4_by_tick: dict[int, dict[str, float]] = {}
    try:
        for raw_tick in ticks_raw:
            raw_time = raw_tick["t"]
            if isinstance(raw_time, bool) or not isinstance(raw_time, int):
                raise ValueError("lab tick time must be an integer")
            logical_time = raw_time
            cells = tuple(
                _CellView(
                    str(cell_id),
                    finite(cell["activation"], name="activation"),
                    finite(cell["stress_load"], name="stress_load"),
                )
                for cell_id, cell in sorted(raw_tick["cells"].items())
            )
            edges = tuple(
                (str(source), str(target)) for source, target in raw_tick.get("edges", [])
            )
            ticks.append(_TickView(logical_time, cells, edges))
            if raw_tick.get("l4") is not None:
                l4_by_tick[logical_time] = _l4_payload(raw_tick["l4"])
        l4_by_tick[ticks[-1].logical_time] = _l4_payload(terminal)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid lab condition trace: {error}") from error
    return _RunView(
        experiment_id=experiment_id,
        history_digest=history_digest,
        ticks=tuple(ticks),
        l4_observations=tuple(sorted(l4_by_tick.items())),
    )


def _validate_view(view: _RunView) -> tuple[str, ...]:
    if not view.experiment_id or not view.history_digest or not view.ticks:
        raise ValueError("collective dynamics source identity must not be empty")
    if len(view.history_digest) != 64 or any(
        character not in "0123456789abcdef" for character in view.history_digest
    ):
        raise ValueError("collective dynamics history digest must be lowercase SHA-256")
    times = tuple(tick.logical_time for tick in view.ticks)
    if any(current != previous + 1 for previous, current in zip(times, times[1:])):
        raise ValueError("collective dynamics ticks must be consecutive and increasing")
    first_ids = tuple(cell.cell_id for cell in view.ticks[0].cells)
    if not first_ids or len(first_ids) != len(set(first_ids)):
        raise ValueError("collective dynamics requires unique Cell identities")
    if first_ids != tuple(sorted(first_ids)):
        raise ValueError("collective dynamics Cell identities must be sorted")
    known = set(first_ids)
    for tick in view.ticks:
        ids = tuple(cell.cell_id for cell in tick.cells)
        if ids != first_ids:
            raise ValueError("Cell identities drift across the collective trace")
        for source, target in tick.edges:
            if source not in known or target not in known or source == target:
                raise ValueError("collective trace edges must connect distinct known Cells")
        if tick.edges != tuple(sorted(set(tick.edges))):
            raise ValueError("collective trace edges must be unique and sorted")
    return first_ids


def _cohorts(
    cell_ids: tuple[str, ...], cohort_map: Mapping[str, str] | None
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if cohort_map is None:
        return (("all_cells", cell_ids),)
    if not isinstance(cohort_map, Mapping) or set(cohort_map) != set(cell_ids):
        raise ValueError("cohort_map must cover every known Cell exactly once")
    groups: dict[str, list[str]] = {}
    for cell_id in cell_ids:
        cohort = cohort_map[cell_id]
        if not isinstance(cohort, str) or not cohort.strip() or cohort == "all_cells":
            raise ValueError("cohort names must be non-empty strings and cannot be all_cells")
        groups.setdefault(cohort, []).append(cell_id)
    return (("all_cells", cell_ids),) + tuple(
        (name, tuple(groups[name])) for name in sorted(groups)
    )


def classify_collective_state(
    direction: float, intensity: float, polarization: float, config: CollectiveDynamicsConfig
) -> str:
    """Classify one group tick in the frozen, ordered decision ladder."""

    direction = finite(direction, name="direction")
    intensity = finite(intensity, name="intensity")
    polarization = finite(polarization, name="polarization")
    if intensity < config.low_intensity_threshold:
        return "low_activity"
    if direction >= config.group_direction_threshold:
        return "activation_dominant"
    if direction <= -config.group_direction_threshold:
        return "stress_dominant"
    if (
        intensity >= config.high_intensity_threshold
        and polarization >= config.population_split_threshold
    ):
        return "population_split"
    if intensity >= config.high_intensity_threshold:
        return "coactivated_balance"
    return "transitional"


def _sign(value: float, threshold: float) -> int:
    if value >= threshold:
        return 1
    if value <= -threshold:
        return -1
    return 0


def _runs(values: Sequence[Any]) -> list[tuple[Any, int, int, int]]:
    result: list[tuple[Any, int, int, int]] = []
    if not values:
        return result
    start = 0
    current = values[0]
    for index, value in enumerate(values[1:], start=1):
        if value != current:
            result.append((current, start, index - 1, index - start))
            current = value
            start = index
    result.append((current, start, len(values) - 1, len(values) - start))
    return result


def _qualified_switch_count(
    values: Sequence[float], threshold: float, minimum_dwell: int
) -> int:
    signs = [_sign(value, threshold) for value in values]
    qualified = [
        sign for sign, _start, _end, dwell in _runs(signs) if sign and dwell >= minimum_dwell
    ]
    compact: list[int] = []
    for sign in qualified:
        if not compact or compact[-1] != sign:
            compact.append(sign)
    return max(0, len(compact) - 1)


def _stable_window_sign(values: Sequence[float], config: CollectiveDynamicsConfig) -> int:
    if not values:
        return 0
    mean = statistics.fmean(values)
    candidate = _sign(mean, config.group_direction_threshold)
    if candidate == 0:
        return 0
    matching = sum(
        1
        for value in values
        if _sign(value, config.group_direction_threshold) == candidate
    ) / len(values)
    return candidate if matching >= config.persistent_fraction else 0


def _trajectory_class(
    series: Sequence[Mapping[str, Any]], config: CollectiveDynamicsConfig
) -> tuple[str, int]:
    directions = [float(item["direction"]) for item in series]
    switches = _qualified_switch_count(
        directions, config.group_direction_threshold, config.minimum_dwell_ticks
    )
    window = min(config.endpoint_window_ticks, len(directions))
    first = _stable_window_sign(directions[:window], config)
    last = _stable_window_sign(directions[-window:], config)
    if switches >= 3:
        return "oscillatory", switches
    if first and last and first != last:
        return "reversal", switches
    if last == 1 and first != 1:
        return "activation_convergence", switches
    if last == -1 and first != -1:
        return "stress_convergence", switches
    if first == last == 1:
        return "persistent_activation", switches
    if first == last == -1:
        return "persistent_stress", switches
    if sum(item["state"] == "population_split" for item in series) / len(series) >= config.persistent_fraction:
        return "persistent_split", switches
    if sum(item["state"] == "low_activity" for item in series) / len(series) >= config.low_activity_fraction:
        return "persistent_low_activity", switches
    return "indeterminate", switches


def _cell_archetype(switches: int) -> str:
    if switches == 0:
        return "stable"
    if switches == 1:
        return "single_switch"
    if switches == 2:
        return "intermittent"
    return "oscillatory"


def _l4_association(
    observations: Sequence[tuple[int, dict[str, float]]], transition_tick: int
) -> dict[str, Any]:
    before = [(tick, state) for tick, state in observations if tick < transition_tick]
    after = [(tick, state) for tick, state in observations if tick >= transition_tick]
    return {
        "relationship": "temporal_association_only",
        "before": None
        if not before
        else {"tick": before[-1][0], "state": before[-1][1]},
        "after": None if not after else {"tick": after[0][0], "state": after[0][1]},
    }


def _state_transitions(
    series: Sequence[Mapping[str, Any]],
    observations: Sequence[tuple[int, dict[str, float]]],
    config: CollectiveDynamicsConfig,
) -> tuple[dict[str, Any], ...]:
    states = [item["state"] for item in series]
    qualified = [
        (state, start, end, dwell)
        for state, start, end, dwell in _runs(states)
        if dwell >= config.minimum_dwell_ticks
    ]
    transitions: list[dict[str, Any]] = []
    for previous, current in zip(qualified, qualified[1:]):
        if previous[0] == current[0]:
            continue
        tick = int(series[current[1]]["t"])
        transitions.append(
            {
                "tick": tick,
                "from_state": previous[0],
                "to_state": current[0],
                "source_dwell_ticks": previous[3],
                "target_dwell_ticks": current[3],
                "l4_association": _l4_association(observations, tick),
            }
        )
    return tuple(transitions)


def _analyze_view(
    view: _RunView,
    cohort_map: Mapping[str, str] | None,
    config: CollectiveDynamicsConfig,
) -> CollectiveDynamicsReport:
    cell_ids = _validate_view(view)
    cohorts = _cohorts(cell_ids, cohort_map)
    # One dict per tick instead of two linear scans per (cell, tick) pair;
    # _validate_view guarantees every tick carries exactly these cell ids.
    per_tick = [
        {cell.cell_id: cell.activation - cell.stress_load for cell in tick.cells}
        for tick in view.ticks
    ]
    cell_series = {
        cell_id: [tick_values[cell_id] for tick_values in per_tick]
        for cell_id in cell_ids
    }
    reports: list[CollectiveCohortReport] = []
    for cohort_id, members in cohorts:
        member_set = set(members)
        series: list[dict[str, Any]] = []
        for tick_index, tick in enumerate(view.ticks):
            states = [cell for cell in tick.cells if cell.cell_id in member_set]
            zs = [cell.activation - cell.stress_load for cell in states]
            direction = statistics.fmean(zs)
            intensity = statistics.fmean(
                (cell.activation**2 + cell.stress_load**2) / 2.0 for cell in states
            )
            polarization = statistics.fmean((value - direction) ** 2 for value in zs)
            edge_products = [
                cell_series[source][tick_index] * cell_series[target][tick_index]
                for source, target in tick.edges
                if source in member_set and target in member_set
            ]
            threshold = config.cell_direction_threshold
            activation_count = sum(value >= threshold for value in zs)
            stress_count = sum(value <= -threshold for value in zs)
            count = len(zs)
            state = classify_collective_state(direction, intensity, polarization, config)
            series.append(
                {
                    "t": tick.logical_time,
                    "direction": _rounded(direction),
                    "intensity": _rounded(intensity),
                    "polarization": _rounded(polarization),
                    "edge_alignment": None
                    if not edge_products
                    else _rounded(statistics.fmean(edge_products)),
                    "activation_dominant_fraction": _rounded(activation_count / count),
                    "stress_dominant_fraction": _rounded(stress_count / count),
                    "neutral_fraction": _rounded((count - activation_count - stress_count) / count),
                    "state": state,
                }
            )
        trajectory, switches = _trajectory_class(series, config)
        archetypes = []
        counts = {name: 0 for name in _CELL_ARCHETYPES}
        for cell_id in members:
            switch_count = _qualified_switch_count(
                cell_series[cell_id],
                config.cell_direction_threshold,
                config.minimum_dwell_ticks,
            )
            archetype = _cell_archetype(switch_count)
            archetypes.append((cell_id, archetype))
            counts[archetype] += 1
        transitions = _state_transitions(series, view.l4_observations, config)
        reports.append(
            CollectiveCohortReport(
                cohort_id=cohort_id,
                cell_ids=members,
                series=tuple(series),
                trajectory_class=trajectory,
                qualified_direction_switches=switches,
                first_qualified_transition_tick=(
                    None if not transitions else int(transitions[0]["tick"])
                ),
                state_transitions=transitions,
                cell_archetypes=tuple(archetypes),
                archetype_counts=tuple((name, counts[name]) for name in _CELL_ARCHETYPES),
            )
        )

    decompositions: list[dict[str, float | int]] = []
    if len(cohorts) > 1:
        group_members = cohorts[1:]
        for tick_index, tick in enumerate(view.ticks):
            all_values = [cell_series[cell_id][tick_index] for cell_id in cell_ids]
            overall_mean = statistics.fmean(all_values)
            total = statistics.fmean((value - overall_mean) ** 2 for value in all_values)
            within_sum = 0.0
            between_sum = 0.0
            for _name, members in group_members:
                values = [cell_series[cell_id][tick_index] for cell_id in members]
                mean = statistics.fmean(values)
                weight = len(values) / len(all_values)
                within_sum += weight * statistics.fmean((value - mean) ** 2 for value in values)
                between_sum += weight * (mean - overall_mean) ** 2
            decompositions.append(
                {
                    "t": tick.logical_time,
                    "total_polarization": _rounded(total),
                    "within_cohort": _rounded(within_sum),
                    "between_cohort": _rounded(between_sum),
                    "residual": _rounded(total - within_sum - between_sum),
                }
            )

    return CollectiveDynamicsReport(
        source_experiment_id=view.experiment_id,
        source_history_digest=view.history_digest,
        config=config,
        cohorts=tuple(reports),
        variance_decomposition=tuple(decompositions),
        l4_observations=tuple(
            {"tick": tick, "state": state} for tick, state in view.l4_observations
        ),
    )


class CollectiveDynamicsObserver:
    """Replaceable read-only facade around the frozen observer protocol."""

    model_version = COLLECTIVE_OBSERVER_VERSION

    def __init__(self, config: CollectiveDynamicsConfig | None = None) -> None:
        self.config = config or CollectiveDynamicsConfig()

    def analyze(
        self,
        run: MultirateRun,
        cohort_map: Mapping[str, str] | None = None,
    ) -> CollectiveDynamicsReport:
        return _analyze_view(_view_from_run(run), cohort_map, self.config)

    def compare(
        self,
        reference: CollectiveDynamicsReport,
        comparison: CollectiveDynamicsReport,
    ) -> CollectiveDynamicsComparison:
        if reference.config.config_digest != self.config.config_digest:
            raise ValueError("reference report does not use this observer config")
        return compare_collective_dynamics(reference, comparison)


def analyze_collective_dynamics(
    run: MultirateRun,
    cohort_map: Mapping[str, str] | None = None,
    config: CollectiveDynamicsConfig | None = None,
) -> CollectiveDynamicsReport:
    """Analyze one immutable completed run without changing it."""

    return CollectiveDynamicsObserver(config).analyze(run, cohort_map)


def analyze_collective_dynamics_raw(
    raw: Mapping[str, Any],
    cohort_map: Mapping[str, str] | None = None,
    config: CollectiveDynamicsConfig | None = None,
) -> CollectiveDynamicsReport:
    """CLI adapter for a serialized formal ``MultirateRun`` artifact."""

    if not isinstance(raw, Mapping):
        raise ValueError("raw run root must be an object")
    return _analyze_view(
        _view_from_raw_mapping(raw), cohort_map, config or CollectiveDynamicsConfig()
    )


def analyze_collective_dynamics_lab_condition(
    condition: Mapping[str, Any],
    cohort_map: Mapping[str, str] | None = None,
    config: CollectiveDynamicsConfig | None = None,
) -> CollectiveDynamicsReport:
    """Internal adapter for an immutable lab display projection."""

    return _analyze_view(
        _view_from_lab_condition(condition), cohort_map, config or CollectiveDynamicsConfig()
    )


def _cohort_by_id(report: CollectiveDynamicsReport) -> dict[str, CollectiveCohortReport]:
    return {item.cohort_id: item for item in report.cohorts}


def _l4_after(report: CollectiveDynamicsReport, tick: int) -> dict[str, Any] | None:
    return next(
        (item for item in report.l4_observations if int(item["tick"]) >= tick),
        None,
    )


def compare_collective_dynamics(
    reference: CollectiveDynamicsReport,
    comparison: CollectiveDynamicsReport,
) -> CollectiveDynamicsComparison:
    """Compare aligned reports; every delta remains descriptive and non-causal."""

    if not isinstance(reference, CollectiveDynamicsReport) or not isinstance(
        comparison, CollectiveDynamicsReport
    ):
        raise TypeError("collective comparison requires two reports")
    if reference.config.config_digest != comparison.config.config_digest:
        raise ValueError("collective reports must use the same frozen config")
    left = _cohort_by_id(reference)
    right = _cohort_by_id(comparison)
    if set(left) != set(right):
        raise ValueError("collective reports must contain the same cohorts")
    results: list[tuple[str, dict[str, Any]]] = []
    for cohort_id in sorted(left):
        left_cohort = left[cohort_id]
        right_cohort = right[cohort_id]
        if left_cohort.cell_ids != right_cohort.cell_ids:
            raise ValueError("collective cohort membership must align")
        left_series = left_cohort.series
        right_series = right_cohort.series
        left_ticks = tuple(int(item["t"]) for item in left_series)
        right_ticks = tuple(int(item["t"]) for item in right_series)
        if left_ticks != right_ticks:
            raise ValueError("collective report ticks must align")
        divergence = next(
            (
                int(left_item["t"])
                for left_item, right_item in zip(left_series, right_series, strict=True)
                if left_item["state"] != right_item["state"]
            ),
            None,
        )
        mean_absolute = {
            metric: _rounded(
                statistics.fmean(
                    abs(float(right_item[metric]) - float(left_item[metric]))
                    for left_item, right_item in zip(left_series, right_series, strict=True)
                )
            )
            for metric in ("direction", "intensity", "polarization")
        }
        l4_difference = None
        if divergence is not None:
            left_l4 = _l4_after(reference, divergence)
            right_l4 = _l4_after(comparison, divergence)
            if left_l4 is not None and right_l4 is not None:
                l4_difference = {
                    "relationship": "temporal_association_only",
                    "reference_tick": left_l4["tick"],
                    "comparison_tick": right_l4["tick"],
                    "delta": {
                        name: _rounded(
                            float(right_l4["state"][name])
                            - float(left_l4["state"][name])
                        )
                        for name in _L4_FIELDS
                    },
                }
        results.append(
            (
                cohort_id,
                {
                    "first_state_divergence_tick": divergence,
                    "mean_absolute_difference": mean_absolute,
                    "reference_trajectory_class": left_cohort.trajectory_class,
                    "comparison_trajectory_class": right_cohort.trajectory_class,
                    "trajectory_class_changed": (
                        left_cohort.trajectory_class != right_cohort.trajectory_class
                    ),
                    "l4_difference_at_divergence": l4_difference,
                },
            )
        )
    return CollectiveDynamicsComparison(
        reference_report_digest=reference.report_digest,
        comparison_report_digest=comparison.report_digest,
        config_digest=reference.config.config_digest,
        cohorts=tuple(results),
    )


def save_collective_dynamics_artifact(
    path: str | Path, report: CollectiveDynamicsReport
) -> Path:
    """Write one report once; identical reconstruction is accepted."""

    if not isinstance(report, CollectiveDynamicsReport):
        raise TypeError("collective dynamics artifact requires a report")
    target = Path(path)
    content = (
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if target.exists():
        if target.read_bytes() != content:
            raise ValueError("refusing to overwrite a different collective dynamics artifact")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp")
    if temporary.exists():
        raise ValueError("temporary collective artifact path already exists")
    temporary.write_bytes(content)
    temporary.replace(target)
    return target


def load_cohort_map(path: str | Path) -> dict[str, str]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid cohort map: {error}") from error
    if not isinstance(raw, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in raw.items()
    ):
        raise ValueError("cohort map must be a Cell-id to cohort-name JSON object")
    return {str(key): str(value) for key, value in raw.items()}


def load_raw_run_mapping(path: str | Path) -> dict[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid raw run artifact: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("raw run artifact root must be an object")
    return raw


def collective_response(activation: Any, stress_load: Any) -> float:
    """Public display helper for the frozen per-Cell response proxy."""

    return _rounded(finite(activation, name="activation") - finite(stress_load, name="stress_load"))
