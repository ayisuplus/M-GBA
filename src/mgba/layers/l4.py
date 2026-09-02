from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any

from ..hashing import digest_payload
from .contracts import (
    OrganismOutcome,
    OrganismState,
    PhenotypeWindow,
    StateMetadata,
    TissueState,
)


@dataclass(frozen=True, slots=True)
class PhenotypeConfig:
    model_version: str
    vitality_support_weights: tuple[float, float]
    inflammation_weights: tuple[float, float, float]
    homeostasis_weights: tuple[float, float, float]
    recovery_weights: tuple[float, float, float]
    failed_vitality_max: float
    failed_damage_min: float
    recovered_homeostasis_min: float
    trend_delta_min: float

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("phenotype model_version must not be empty")
        weight_groups = (
            ("vitality_support_weights", self.vitality_support_weights, 2),
            ("inflammation_weights", self.inflammation_weights, 3),
            ("homeostasis_weights", self.homeostasis_weights, 3),
            ("recovery_weights", self.recovery_weights, 3),
        )
        for name, weights, expected_length in weight_groups:
            if len(weights) != expected_length:
                raise ValueError(f"{name} must contain {expected_length} weights")
            if any(
                not math.isfinite(weight) or not 0.0 <= weight <= 1.0
                for weight in weights
            ):
                raise ValueError(f"{name} must contain finite weights in [0, 1]")
            if not math.isclose(sum(weights), 1.0, abs_tol=1e-12):
                raise ValueError(f"{name} must sum to 1")
        for name in (
            "failed_vitality_max",
            "failed_damage_min",
            "recovered_homeostasis_min",
            "trend_delta_min",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and in [0, 1]")
        if self.trend_delta_min == 0.0:
            raise ValueError("trend_delta_min must be positive")


def _load_weights(raw: Any, name: str) -> tuple[float, ...]:
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"{name} must be a JSON array")
    try:
        return tuple(float(value) for value in raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must contain numbers") from error


def load_phenotype_config(path: str | Path) -> PhenotypeConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return PhenotypeConfig(
            model_version=str(raw["model_version"]),
            vitality_support_weights=_load_weights(
                raw["vitality_support_weights"], "vitality_support_weights"
            ),
            inflammation_weights=_load_weights(
                raw["inflammation_weights"], "inflammation_weights"
            ),
            homeostasis_weights=_load_weights(
                raw["homeostasis_weights"], "homeostasis_weights"
            ),
            recovery_weights=_load_weights(
                raw["recovery_weights"], "recovery_weights"
            ),
            failed_vitality_max=float(raw["failed_vitality_max"]),
            failed_damage_min=float(raw["failed_damage_min"]),
            recovered_homeostasis_min=float(raw["recovered_homeostasis_min"]),
            trend_delta_min=float(raw["trend_delta_min"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid phenotype config: {error}") from error


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _metadata(
    *, logical_time: int, model_version: str, source: Any
) -> StateMetadata:
    return StateMetadata(
        logical_time=logical_time,
        model_version=model_version,
        source_digest=digest_payload(source),
    )


def _validated_tissue(tissue: TissueState, logical_time: int) -> None:
    if not isinstance(tissue, TissueState):
        raise TypeError("Phenotype models consume TissueState only")
    if tissue.metadata.logical_time > logical_time:
        raise ValueError("L4 cannot consume a future TissueState")


class StaticPhenotypeModel:
    """Frozen aggregate L4 baseline retained for contract regression."""

    model_version = "reference-l4-static-observer-0.2"

    def step(self, tissue: TissueState, *, logical_time: int) -> OrganismState:
        _validated_tissue(tissue, logical_time)
        vitality = _clamp(tissue.mean_viability * (1.0 - tissue.tissue_damage))
        inflammation = _clamp(tissue.mean_activation + tissue.tissue_damage)
        return OrganismState(
            metadata=_metadata(
                logical_time=logical_time,
                model_version=self.model_version,
                source=tissue,
            ),
            vitality=vitality,
            damage_burden=tissue.tissue_damage,
            inflammation=inflammation,
            homeostasis=_clamp(vitality * (1.0 - 0.5 * inflammation)),
            recovery_capacity=_clamp(
                tissue.mean_viability * tissue.repair_activity
            ),
        )


class PhenotypeObserverModel:
    """Deterministic L4 observer over formal TissueState inputs only."""

    def __init__(self, config: PhenotypeConfig) -> None:
        self.config = config

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    def step(self, tissue: TissueState, *, logical_time: int) -> OrganismState:
        _validated_tissue(tissue, logical_time)
        resource_weight, damage_absence_weight = (
            self.config.vitality_support_weights
        )
        damage_weight, activation_weight, signal_weight = (
            self.config.inflammation_weights
        )
        vitality_weight, calm_weight, survival_weight = (
            self.config.homeostasis_weights
        )
        repair_weight, recovery_resource_weight, low_damage_weight = (
            self.config.recovery_weights
        )

        vitality = _clamp(
            tissue.mean_viability
            * (
                resource_weight * tissue.mean_resource
                + damage_absence_weight * (1.0 - tissue.tissue_damage)
            )
        )
        inflammation = _clamp(
            damage_weight * tissue.tissue_damage
            + activation_weight * tissue.mean_activation
            + signal_weight * tissue.coordinated_signal
        )
        homeostasis = _clamp(
            vitality_weight * vitality
            + calm_weight * (1.0 - inflammation)
            + survival_weight * (1.0 - tissue.dead_fraction)
        )
        recovery_capacity = _clamp(
            tissue.mean_viability
            * (
                repair_weight * tissue.repair_activity
                + recovery_resource_weight * tissue.mean_resource
                + low_damage_weight * (1.0 - tissue.tissue_damage)
            )
        )
        return OrganismState(
            metadata=_metadata(
                logical_time=logical_time,
                model_version=self.model_version,
                source={"tissue": tissue, "config": self.config},
            ),
            vitality=vitality,
            damage_burden=tissue.tissue_damage,
            inflammation=inflammation,
            homeostasis=homeostasis,
            recovery_capacity=recovery_capacity,
        )

    def summarize(self, states: tuple[OrganismState, ...]) -> PhenotypeWindow:
        if not states:
            raise ValueError("phenotype window must contain at least one state")
        if any(not isinstance(state, OrganismState) for state in states):
            raise TypeError("phenotype window consumes OrganismState objects")
        if any(
            state.metadata.model_version != self.model_version for state in states
        ):
            raise ValueError("phenotype window cannot mix L4 model versions")
        times = tuple(state.metadata.logical_time for state in states)
        if any(current <= previous for previous, current in zip(times, times[1:])):
            raise ValueError("phenotype window logical times must strictly increase")

        first = states[0]
        final = states[-1]
        homeostasis_delta = final.homeostasis - first.homeostasis
        outcome = self._classify(final, homeostasis_delta)
        return PhenotypeWindow(
            metadata=_metadata(
                logical_time=times[-1],
                model_version=self.model_version,
                source={"states": states, "config": self.config},
            ),
            start_time=times[0],
            end_time=times[-1],
            sample_count=len(states),
            mean_vitality=fmean(state.vitality for state in states),
            mean_damage_burden=fmean(
                state.damage_burden for state in states
            ),
            mean_inflammation=fmean(state.inflammation for state in states),
            mean_homeostasis=fmean(state.homeostasis for state in states),
            mean_recovery_capacity=fmean(
                state.recovery_capacity for state in states
            ),
            final_vitality=final.vitality,
            final_damage_burden=final.damage_burden,
            final_homeostasis=final.homeostasis,
            homeostasis_delta=homeostasis_delta,
            outcome=outcome,
        )

    def _classify(
        self, final: OrganismState, homeostasis_delta: float
    ) -> OrganismOutcome:
        if (
            final.vitality <= self.config.failed_vitality_max
            or final.damage_burden >= self.config.failed_damage_min
        ):
            return OrganismOutcome.FAILED
        if (
            final.homeostasis >= self.config.recovered_homeostasis_min
            and homeostasis_delta >= self.config.trend_delta_min
        ):
            return OrganismOutcome.RECOVERED
        if homeostasis_delta <= -self.config.trend_delta_min:
            return OrganismOutcome.DETERIORATING
        return OrganismOutcome.STABLE
