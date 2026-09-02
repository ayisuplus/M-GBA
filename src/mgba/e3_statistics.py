"""E3 population statistics: pre-registered criteria for group patterns.

Implements the W14/M9 protocol from the MVP plan: given an ensemble of
multi-seed runs, quantify each macro pattern with distribution-free
descriptors and classify it through a pre-registered grading ladder that
mirrors the AGENTS.md terminology (aggregation / group dynamics /
emergence candidate).  No p-values are claimed; every threshold is frozen
in config before the ensemble is measured.

Mathematical formulation
------------------------

For each macro metric :math:`m` (terminal L3/L4 scalars) across seeds
:math:`s = 1..N`:

.. math::

    \\mu_m = \\frac{1}{N}\\sum_s m_s, \\qquad
    \\sigma_m = \\sqrt{\\frac{1}{N-1}\\sum_s (m_s - \\mu_m)^2}.

**Stability (coefficient of variation)** with an absolute fallback when
the mean is degenerate:

.. math::

    \\mathrm{CV}_m =
    \\begin{cases}
        \\sigma_m / \\mu_m, & |\\mu_m| > \\epsilon \\\\
        \\sigma_m, & \\text{otherwise}
    \\end{cases}

**Encoding independence.**  The micro drive of seed :math:`s` is the
within-run mean of the terminal L0 damage-response and signal-expression
values, :math:`x_s`.  A simple OLS fit :math:`m_s = a + b\\,x_s` yields

.. math::

    R^2_m = 1 - \\frac{\\sum_s (m_s - \\hat m_s)^2}{\\sum_s (m_s - \\mu_m)^2},
    \\qquad \\text{decoupling}_m = 1 - R^2_m,

with :math:`R^2 = 0` when the total variance is degenerate.  High
decoupling means the macro pattern is *not* explained by the measured
micro drive — a necessary (not sufficient) condition for emergence.

**Persistence.**  The fraction of seeds whose value exceeds the
pre-registered pattern threshold:

.. math::

    \\mathrm{persist}_m = \\frac{1}{N}\\sum_s \\mathbb{1}[m_s \\ge \\tau_m].

**Grading ladder** (pre-registered, evaluated in order):

1. ``insufficient_seeds`` — :math:`N < 3` (no meaningful spread);
2. ``no_pattern`` — :math:`\\sigma_m \\approx 0` (identical across seeds);
3. ``emergence_candidate`` — stable (:math:`\\mathrm{CV} \\le c`), decoupled
   (:math:`1-R^2 \\ge \\gamma`) and persistent (:math:`\\mathrm{persist}
   \\ge p`);
4. ``group_dynamics`` — stable but coupled to the micro drive;
5. ``aggregation`` — everything else (noise-dominated variation).

This implements — and deliberately stops short of — the AGENTS.md §4
requirement: a ``validated result`` additionally needs a frozen protocol,
statistical testing and layer ablations, which remain future work.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .hashing import digest_payload
from .runner import MultirateRun

_EPS = 1e-12

_E3_GRADES = (
    "insufficient_seeds",
    "no_pattern",
    "emergence_candidate",
    "group_dynamics",
    "aggregation",
)

# Terminal scalars composing the macro pattern vector.
E3_MACRO_METRICS = (
    "dead_fraction",
    "mean_viability",
    "tissue_damage",
    "homeostasis",
    "inflammation",
)


@dataclass(frozen=True, slots=True)
class E3CriteriaConfig:
    """Pre-registered E3 thresholds (frozen before measurement)."""

    model_version: str
    cv_threshold: float  # stability bound c
    coupling_threshold: float  # decoupling bound gamma
    persistence_threshold: float  # persistence bound p
    pattern_threshold: float  # per-seed pattern predicate tau

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("E3 criteria model_version must not be empty")
        for name in (
            "cv_threshold",
            "coupling_threshold",
            "persistence_threshold",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be finite and in (0, 1]")
        if (
            not math.isfinite(self.pattern_threshold)
            or not 0.0 <= self.pattern_threshold <= 1.0
        ):
            raise ValueError("pattern_threshold must be finite and in [0, 1]")


def load_e3_criteria_config(path: str | Path) -> E3CriteriaConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return E3CriteriaConfig(
            model_version=str(raw["model_version"]),
            cv_threshold=float(raw["cv_threshold"]),
            coupling_threshold=float(raw["coupling_threshold"]),
            persistence_threshold=float(raw["persistence_threshold"]),
            pattern_threshold=float(raw["pattern_threshold"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid E3 criteria config: {error}") from error


def macro_metric_values(run: MultirateRun, metric: str) -> float:
    """Extract one terminal macro scalar from a completed run."""
    if metric in E3_MACRO_METRICS[:3]:
        return float(getattr(run.ticks[-1].l3, metric))
    return float(getattr(run.terminal_observation, metric))


def micro_drive(run: MultirateRun) -> float:
    """Within-run mean of terminal L0 damage-response and signal expression."""
    terminal_l0 = run.ticks[-1].l0
    values = [
        0.5 * (state.damage_response + state.signal_expression)
        for state in terminal_l0
    ]
    return statistics.fmean(values)


@dataclass(frozen=True, slots=True)
class E3MetricStats:
    """Distribution-free description and grade for one macro metric."""

    metric: str
    seed_values: tuple[float, ...]
    micro_drives: tuple[float, ...]
    mean: float
    std: float
    cv: float
    absolute_spread: bool
    r_squared: float
    decoupling: float
    persistence: float
    grade: str
    note: str

    def __post_init__(self) -> None:
        if self.metric not in E3_MACRO_METRICS:
            raise ValueError(f"unknown E3 metric: {self.metric}")
        if self.grade not in _E3_GRADES:
            raise ValueError(f"unknown E3 grade: {self.grade}")
        if len(self.seed_values) != len(self.micro_drives):
            raise ValueError("E3 stats require aligned seeds and drives")

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "seed_count": len(self.seed_values),
            "seed_values": list(self.seed_values),
            "micro_drives": list(self.micro_drives),
            "mean": self.mean,
            "std": self.std,
            "cv": self.cv,
            "absolute_spread": self.absolute_spread,
            "r_squared": self.r_squared,
            "decoupling": self.decoupling,
            "persistence": self.persistence,
            "grade": self.grade,
            "note": self.note,
        }


def _ols_r_squared(xs: tuple[float, ...], ys: tuple[float, ...]) -> float:
    """Coefficient of determination of the best linear fit y ~ x."""
    n = len(xs)
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    total = sum((y - mean_y) ** 2 for y in ys)
    if total < _EPS or variance_x < _EPS:
        return 0.0
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / variance_x
    intercept = mean_y - slope * mean_x
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r_squared = 1.0 - residual / total
    return max(0.0, min(1.0, r_squared))


def classify_metric(
    metric: str,
    seed_values: tuple[float, ...],
    micro_drives: tuple[float, ...],
    config: E3CriteriaConfig,
) -> E3MetricStats:
    """Grade one macro metric against the pre-registered criteria."""
    if not seed_values:
        raise ValueError("seed_values must not be empty")
    n = len(seed_values)
    mean = statistics.fmean(seed_values)
    std = statistics.stdev(seed_values) if n >= 2 else 0.0
    absolute_spread = abs(mean) < _EPS
    cv = std if absolute_spread else std / abs(mean)
    r_squared = _ols_r_squared(micro_drives, seed_values) if n >= 2 else 0.0
    decoupling = 1.0 - r_squared
    persistence = (
        sum(1.0 for value in seed_values if value >= config.pattern_threshold) / n
    )

    stable = cv <= config.cv_threshold
    decoupled = decoupling >= config.coupling_threshold
    persistent = persistence >= config.persistence_threshold

    if n < 3:
        grade, note = "insufficient_seeds", "fewer than three seeds"
    elif std < _EPS:
        grade, note = "no_pattern", "identical across seeds"
    elif stable and decoupled and persistent:
        grade, note = (
            "emergence_candidate",
            "stable, weakly coupled to the measured micro drive, persistent",
        )
    elif stable:
        grade, note = (
            "group_dynamics",
            "stable but coupled to the measured micro drive",
        )
    else:
        grade, note = "aggregation", "noise-dominated variation"

    return E3MetricStats(
        metric=metric,
        seed_values=seed_values,
        micro_drives=micro_drives,
        mean=mean,
        std=std,
        cv=cv,
        absolute_spread=absolute_spread,
        r_squared=r_squared,
        decoupling=decoupling,
        persistence=persistence,
        grade=grade,
        note=note,
    )


def evaluate_e3(
    runs: Mapping[int, MultirateRun], config: E3CriteriaConfig
) -> tuple[E3MetricStats, ...]:
    """Grade every macro metric over a seed-indexed run ensemble."""
    if not runs:
        raise ValueError("E3 evaluation requires at least one run")
    ordered_seeds = tuple(sorted(runs))
    drives = tuple(micro_drive(runs[seed]) for seed in ordered_seeds)
    return tuple(
        classify_metric(
            metric,
            tuple(macro_metric_values(runs[seed], metric) for seed in ordered_seeds),
            drives,
            config,
        )
        for metric in E3_MACRO_METRICS
    )


def e3_summary_digest(stats: tuple[E3MetricStats, ...]) -> str:
    return digest_payload(tuple(item.as_dict() for item in stats))
