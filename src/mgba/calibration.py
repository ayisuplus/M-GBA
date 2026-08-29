"""Deterministic seeded parameter calibration (ADR-0018).

Answers a pre-registered question about the reference model class:
*does the L2 rule state machine contain a parameterization that lifts
the default scenario's windowed homeostasis — and does it generalize
to held-out stress regimes that never participated in the search?*

This module is a pure search core: it never imports the runner or any
layer model.  The caller supplies an objective callable mapping a
parameter point to a finite score; the script
``scripts/calibrate_l2_cell.py`` wires the five-layer runner to it.
Keeping the core runner-free makes the search logic testable with
synthetic objectives in microseconds.

Anti-display-tuning discipline (AGENTS.md §4)
----------------------------------------------

* The objective, parameter box, budgets, and train/holdout split are
  frozen in a ``CalibrationProtocol`` *before* any evaluation runs.
* The incumbent (frozen reference parameters) is always evaluated
  first and enters the refinement seeds, so the search result can
  never be worse than the reference on the training scenario — only
  equal or better — and the holdout decides whether that improvement
  is real or overfitting.
* Every evaluated point is logged; artifacts are write-once.

Search algorithm (pure stdlib, fully deterministic)
---------------------------------------------------

1. **Seeded random sweep.**  Candidate :math:`k` draws each coordinate
   from its own stream
   :math:`\\mathrm{Random}(\\mathrm{sha256}(seed\\,\\|\\,\\text{candidate}\\,\\|\\,k)[:8])`,
   uniform in the unit box :math:`[0,1)^{19}` — a seedable analogue of
   a low-discrepancy sweep that needs no external library.
2. **Coordinate refinement.**  From each of the ``top_k`` incumbents,
   sweep coordinates in declaration order with step sizes
   ``refinement_steps`` (e.g. 0.1 then 0.05), accepting a move only
   when the score improves by more than :math:`10^{-12}`, at most
   ``max_sweeps`` rounds.  Duplicate points are never re-evaluated.

Both phases are exact functions of the protocol; the same protocol
reproduces the same evaluation log bit-for-bit.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from .experiment import digest_payload

#: Scalar ``CellConfig`` fields searched by the L2 calibration, in
#: declaration order.  ``model_version`` and ``secretion_multipliers``
#: stay frozen at the reference values (declared in ADR-0018).
L2_SCALAR_PARAMETERS = (
    "stress_environment_weight",
    "resource_deficit_weight",
    "death_stress_weight",
    "metabolic_buffer_weight",
    "signal_activation_weight",
    "incoming_signal_weight",
    "death_effector_weight",
    "stress_mortality_weight",
    "repair_recovery_rate",
    "stress_damage_rate",
    "death_damage_rate",
    "basal_consumption",
    "activation_consumption_rate",
    "repair_consumption_rate",
    "activation_threshold",
    "repair_threshold",
    "stress_threshold",
    "death_drive_threshold",
    "death_viability_threshold",
)

_OBJECTIVE_EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class CalibrationProtocol:
    """Pre-registered search definition; frozen before any evaluation."""

    model_version: str
    search_seed: int
    candidate_count: int
    top_k: int
    refinement_steps: tuple[float, ...]
    max_sweeps: int
    ticks: int
    parameter_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("calibration model_version must not be empty")
        if isinstance(self.search_seed, bool) or not isinstance(self.search_seed, int):
            raise TypeError("search_seed must be an int")
        if self.search_seed < 0:
            raise ValueError("search_seed must be non-negative")
        for name in ("candidate_count", "top_k", "max_sweeps", "ticks"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an int")
            if value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.top_k > self.candidate_count + 1:
            raise ValueError("top_k cannot exceed candidate_count plus the incumbent")
        if not self.refinement_steps:
            raise ValueError("refinement_steps must not be empty")
        if any(
            not math.isfinite(step) or step <= 0.0 or step > 0.5
            for step in self.refinement_steps
        ):
            raise ValueError("refinement_steps must be finite values in (0, 0.5]")
        if not self.parameter_names:
            raise ValueError("parameter_names must not be empty")
        if len(set(self.parameter_names)) != len(self.parameter_names):
            raise ValueError("parameter_names must be unique")
        if any(not name.strip() for name in self.parameter_names):
            raise ValueError("parameter_names must be non-empty strings")


@dataclass(frozen=True, slots=True)
class CalibrationEvaluation:
    """One objective evaluation, logged in evaluation order."""

    phase: str
    point: tuple[float, ...]
    score: float

    def __post_init__(self) -> None:
        if self.phase not in ("incumbent", "random", "refine"):
            raise ValueError("evaluation phase must be incumbent/random/refine")
        if not math.isfinite(self.score):
            raise ValueError("evaluation score must be finite")


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    """Complete deterministic outcome of one calibration search."""

    protocol: CalibrationProtocol
    evaluations: tuple[CalibrationEvaluation, ...]
    best_point: tuple[float, ...]
    best_score: float

    def __post_init__(self) -> None:
        if not self.evaluations:
            raise ValueError("calibration result requires evaluations")
        if len(self.best_point) != len(self.protocol.parameter_names):
            raise ValueError("best point dimension must match parameter_names")
        if not math.isfinite(self.best_score):
            raise ValueError("best score must be finite")

    @property
    def search_digest(self) -> str:
        return digest_payload(
            {
                "protocol": self.protocol,
                "evaluations": self.evaluations,
            }
        )

    def best_mapping(self) -> dict[str, float]:
        return dict(zip(self.protocol.parameter_names, self.best_point, strict=True))

    def summary_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "mgba-calibration-artifact-0.1",
            "search_digest": self.search_digest,
            "protocol": {
                "model_version": self.protocol.model_version,
                "search_seed": self.protocol.search_seed,
                "candidate_count": self.protocol.candidate_count,
                "top_k": self.protocol.top_k,
                "refinement_steps": list(self.protocol.refinement_steps),
                "max_sweeps": self.protocol.max_sweeps,
                "ticks": self.protocol.ticks,
                "parameter_names": list(self.protocol.parameter_names),
            },
            "evaluation_count": len(self.evaluations),
            "best_point": self.best_mapping(),
            "best_score": self.best_score,
            "evaluations": [
                {"phase": item.phase, "point": list(item.point), "score": item.score}
                for item in self.evaluations
            ],
        }


def load_calibration_protocol(path: str | Path) -> CalibrationProtocol:
    """Load a frozen calibration protocol; any read/parse failure is a ValueError."""
    try:
        raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
        return CalibrationProtocol(
            model_version=str(raw["model_version"]),
            search_seed=int(raw["search_seed"]),
            candidate_count=int(raw["candidate_count"]),
            top_k=int(raw["top_k"]),
            refinement_steps=tuple(float(v) for v in raw["refinement_steps"]),
            max_sweeps=int(raw["max_sweeps"]),
            ticks=int(raw["ticks"]),
            parameter_names=tuple(str(name) for name in raw["parameter_names"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid calibration protocol config: {error}") from error


def sample_candidates(protocol: CalibrationProtocol) -> tuple[tuple[float, ...], ...]:
    """Seeded uniform sweep of the unit box, one stream per candidate."""
    if not isinstance(protocol, CalibrationProtocol):
        raise TypeError("sample_candidates requires a CalibrationProtocol")
    dimension = len(protocol.parameter_names)
    candidates: list[tuple[float, ...]] = []
    for index in range(protocol.candidate_count):
        payload = f"{protocol.search_seed}|candidate|{index}".encode("utf-8")
        stream_seed = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
        rng = random.Random(stream_seed)
        candidates.append(tuple(rng.random() for _ in range(dimension)))
    return tuple(candidates)


def run_search(
    protocol: CalibrationProtocol,
    objective: Callable[[tuple[float, ...]], float],
    *,
    incumbents: Sequence[Sequence[float]] = (),
) -> CalibrationResult:
    """Execute the pre-registered sweep + coordinate refinement.

    ``objective`` must map a point of ``len(parameter_names)`` unit-box
    coordinates to a finite float (larger is better).  ``incumbents``
    are evaluated first and join the refinement seeds, so the result is
    never worse than the incumbent on the training objective.
    """
    if not isinstance(protocol, CalibrationProtocol):
        raise TypeError("run_search requires a CalibrationProtocol")
    dimension = len(protocol.parameter_names)
    for incumbent in incumbents:
        if len(incumbent) != dimension:
            raise ValueError("incumbent dimension must match parameter_names")
        if any(not 0.0 <= value <= 1.0 for value in incumbent):
            raise ValueError("incumbents must lie in the unit box")

    evaluations: list[CalibrationEvaluation] = []
    seen: dict[tuple[float, ...], float] = {}

    def evaluate(point: Sequence[float], phase: str) -> float:
        key = tuple(float(value) for value in point)
        if key in seen:
            return seen[key]
        score = objective(key)
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise TypeError("objective must return a real number")
        score = float(score)
        if not math.isfinite(score):
            raise ValueError("objective must return a finite score")
        seen[key] = score
        evaluations.append(CalibrationEvaluation(phase=phase, point=key, score=score))
        return score

    seeded: list[tuple[tuple[float, ...], float]] = []
    for incumbent in incumbents:
        point = tuple(float(value) for value in incumbent)
        seeded.append((point, evaluate(point, "incumbent")))
    for candidate in sample_candidates(protocol):
        seeded.append((candidate, evaluate(candidate, "random")))

    # Deterministic ranking: score descending, point tuple ascending on ties.
    seeded.sort(key=lambda item: (-item[1], item[0]))
    starters = seeded[: protocol.top_k]

    best_point, best_score = starters[0]
    for start_point, start_score in starters:
        point, score = _coordinate_refine(
            protocol, evaluate, start_point, start_score
        )
        if score > best_score + _OBJECTIVE_EPSILON:
            best_point, best_score = point, score

    return CalibrationResult(
        protocol=protocol,
        evaluations=tuple(evaluations),
        best_point=best_point,
        best_score=best_score,
    )


def _coordinate_refine(
    protocol: CalibrationProtocol,
    evaluate: Callable[[Sequence[float], str], float],
    start_point: tuple[float, ...],
    start_score: float,
) -> tuple[tuple[float, ...], float]:
    best_point = start_point
    best_score = start_score
    dimension = len(start_point)
    for _sweep in range(protocol.max_sweeps):
        improved = False
        for step in protocol.refinement_steps:
            for coordinate in range(dimension):
                for direction in (1.0, -1.0):
                    candidate = list(best_point)
                    candidate[coordinate] = min(
                        1.0, max(0.0, candidate[coordinate] + direction * step)
                    )
                    candidate_point = tuple(candidate)
                    if candidate_point == best_point:
                        continue
                    score = evaluate(candidate_point, "refine")
                    if score > best_score + _OBJECTIVE_EPSILON:
                        best_point, best_score = candidate_point, score
                        improved = True
        if not improved:
            break
    return best_point, best_score


def save_calibration_artifacts(
    artifact_root: str | Path, result: CalibrationResult
) -> dict[str, Path]:
    """Persist manifest and summary (append-only, write-once)."""
    if not isinstance(result, CalibrationResult):
        raise TypeError("save_calibration_artifacts requires a CalibrationResult")
    root = Path(artifact_root) / f"calibration-{result.search_digest[:16]}"
    manifest_path = root / "manifest.json"
    summary_path = root / "summary.json"
    manifest = {
        "schema_version": "mgba-calibration-artifact-0.1",
        "search_digest": result.search_digest,
        "protocol": result.summary_dict()["protocol"],
        "evaluation_count": len(result.evaluations),
    }
    _write_json_once(manifest_path, manifest)
    _write_json_once(summary_path, result.summary_dict())
    return {"root": root, "manifest": manifest_path, "summary": summary_path}


def _write_json_once(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("existing calibration artifact is invalid JSON") from error
        if existing != payload:
            raise ValueError("refusing to overwrite a different calibration artifact")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
