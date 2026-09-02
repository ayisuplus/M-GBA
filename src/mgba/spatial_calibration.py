"""ADR-0043: calibration-subset parameter selection for the CAR-M spatial L3.

Pure stdlib, reusing the frozen ADR-0018 search core. The objective runs a full
20-tick spatial evaluation per candidate and maximizes the negative calibration
mean normalized absolute error. The reference config is always evaluated first
as incumbent, so the search cannot regress it on the training objective. The
confirmation rule is frozen before the search: holdout mean NAE must beat the
pinned reference value by > 1e-12, exactly once, no refit loops.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .calibration import CalibrationProtocol, CalibrationResult, run_search
from .carm_spatial_experiments import build_carm_spatial_runners
from .hashing import digest_payload
from .scenarios.carm.scenario import CompiledCarmScenario
from .scenarios.carm.spatial import CarmSpatialConfig
from .spatial_anchor_evaluation import (
    SpatialAnchorEvaluationConfig,
    SpatialAnchorEvaluator,
)
from .spatial_anchors import SpatialAnchorProtocol

SPATIAL_CALIBRATION_SCHEMA = "mgba-spatial-calibration-0.1"
CONSUMED_CONFIRMATION_TARGET_IDS = frozenset({"spatial-anchor-29c87ba1411d4fc8"})

# Frozen by ADR-0043 §2 before any search evaluation.
PARAMETER_BOUNDS: tuple[tuple[str, float, float], ...] = (
    ("neighbor_radius", 0.05, 0.40),
    ("field_retention", 0.50, 0.98),
    ("field_diffusion", 0.00, 0.60),
    ("node_field_coupling", 0.00, 1.00),
)
REFERENCE_HOLDOUT_MEAN_NAE = 12.146142329407688
CONFIRM_EPSILON = 1e-12


def _to_box(value: float, low: float, high: float) -> float:
    return (value - low) / (high - low)


def _from_box(point: float, low: float, high: float) -> float:
    return low + point * (high - low)


def reference_box_point(config: CarmSpatialConfig) -> tuple[float, ...]:
    return tuple(
        _to_box(float(getattr(config, name)), low, high)
        for name, low, high in PARAMETER_BOUNDS
    )


def point_to_overrides(point: Sequence[float]) -> dict[str, float]:
    if len(point) != len(PARAMETER_BOUNDS):
        raise ValueError("point dimension disagrees with the frozen parameter set")
    values = []
    for value, (name, low, high) in zip(point, PARAMETER_BOUNDS, strict=True):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"point coordinate for {name} outside the unit box")
        values.append(_from_box(value, low, high))
    return {name: value for (name, _low, _high), value in zip(PARAMETER_BOUNDS, values, strict=True)}


def make_spatial_objective(
    *,
    compiled: CompiledCarmScenario,
    target: Mapping[str, Any],
    anchor_protocol: SpatialAnchorProtocol,
    evaluation_config: SpatialAnchorEvaluationConfig,
    runner_config: Any,
    base_spatial_config: CarmSpatialConfig,
    l0_config: str,
    l1_config: str,
    l4_config: str,
) -> Callable[[tuple[float, ...]], float]:
    """Objective: negative calibration mean NAE of a full 20-tick evaluation."""

    def objective(point: tuple[float, ...]) -> float:
        overrides = point_to_overrides(point)
        candidate = replace(base_spatial_config, **overrides)
        runners = build_carm_spatial_runners(
            compiled,
            runner_config=runner_config,
            spatial_config=candidate,
            l0_config=l0_config,
            l1_config=l1_config,
            l4_config=l4_config,
        )
        result = SpatialAnchorEvaluator(
            evaluation_config,
            runner=runners["spatial_field"],
            protocol=anchor_protocol,
        ).evaluate(compiled, target=target)
        for role_score in result.score.role_scores:
            if role_score.role == "calibration":
                return -role_score.mean_normalized_absolute_error
        raise RuntimeError("calibration role missing from the evaluation score")

    return objective


@dataclass(frozen=True, slots=True)
class SpatialCalibrationOutcome:
    search: CalibrationResult
    reference_calibration_score: float
    confirmation: dict[str, Any]

    def __post_init__(self) -> None:
        if not math.isfinite(self.reference_calibration_score):
            raise ValueError("reference calibration score must be finite")

    def as_dict(self) -> dict[str, Any]:
        content: dict[str, Any] = {
            "schema_version": SPATIAL_CALIBRATION_SCHEMA,
            "scientific_boundary": (
                "calibration-role parameter diagnosis for the dimensionless "
                "spatial reference model; not fitted biology, not an efficacy "
                "claim, and not a change to any frozen configuration"
            ),
            "parameter_bounds": [
                {"name": name, "low": low, "high": high}
                for name, low, high in PARAMETER_BOUNDS
            ],
            "reference_calibration_mean_nae": -self.reference_calibration_score,
            "search": self.search.summary_dict(),
            "confirmation": self.confirmation,
        }
        content["calibration_id"] = (
            f"carm-spatial-calibration-{digest_payload(content)[:16]}"
        )
        return content


def run_spatial_calibration(
    protocol: CalibrationProtocol,
    objective: Callable[[tuple[float, ...]], float],
    *,
    reference_point: tuple[float, ...],
    confirm: Callable[[tuple[float, ...]], dict[str, Any]],
) -> SpatialCalibrationOutcome:
    """Run the frozen search, then the one-shot confirmation evaluation."""
    if len(reference_point) != len(protocol.parameter_names):
        raise ValueError("reference point dimension disagrees with parameter_names")
    search = run_search(protocol, objective, incumbents=(reference_point,))
    incumbent_score = search.evaluations[0].score
    if search.best_score < incumbent_score - 1e-12:
        raise RuntimeError("search regressed the incumbent reference point")
    confirmation = confirm(search.best_point)
    holdout_nae = confirmation["holdout_mean_nae"]
    verdict = (
        "improved"
        if holdout_nae < REFERENCE_HOLDOUT_MEAN_NAE - CONFIRM_EPSILON
        else "not-anchored"
    )
    confirmation = dict(confirmation, verdict=verdict)
    return SpatialCalibrationOutcome(
        search=search,
        reference_calibration_score=incumbent_score,
        confirmation=confirmation,
    )


def save_spatial_calibration_artifacts(
    artifact_root: str | Path, outcome: SpatialCalibrationOutcome
) -> dict[str, Path]:
    root = Path(artifact_root)
    root.mkdir(parents=True, exist_ok=True)
    summary_path = root / "calibration-summary.json"
    payload = outcome.as_dict()
    if summary_path.exists():
        existing = json.loads(summary_path.read_text(encoding="utf-8"))
        if existing != payload:
            raise ValueError("refusing to overwrite a different calibration artifact")
        return {"summary": summary_path}
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"summary": summary_path}
