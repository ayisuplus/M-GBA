"""Read-only six-direction, three-ring observation of formal spatial L3 state.

``ClockSectorObserver`` is generation-chain external.  It combines the
``SpatialTissueState`` and the L0 states visible at the same runner tick into a
deterministic neighbourhood description.  It never writes back to a layer,
does not participate in checkpoint state, and deliberately exposes the L0
values as abstract reference variables rather than biological genes.

Distances are divided by the median nearest-neighbour distance for the whole
snapshot.  The three rings are ``[0, 1]``, ``(1, 2]`` and ``(2, infinity)`` in
those normalized units.  Six directions are centred on 0, 60, ..., 300
degrees in Cartesian coordinates.  An exact angular boundary belongs to the
counter-clockwise sector; this explicit tie rule avoids platform-dependent
binning at 30 + 60*k degrees.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .experiment import digest_payload
from .layers import SpatialTissueState, TranscriptState
from .layers.l0 import ABSTRACT_GENE_NAMES


CLOCK_SECTOR_SCHEMA = "mgba-clock-sector-observation-0.1"
CLOCK_SECTOR_OBSERVER_VERSION = "clock-sector-observer-0.1"
CLOCK_DIRECTION_COUNT = 6
CLOCK_RING_COUNT = 3
CLOCK_RING_BOUNDARIES = (1.0, 2.0)
CLOCK_DIRECTION_LABELS = (
    "east",
    "north_east",
    "north_west",
    "west",
    "south_west",
    "south_east",
)
CLOCK_RING_LABELS = ("near", "middle", "far")
CLOCK_SECTOR_SCIENTIFIC_BOUNDARY = (
    "Clock sectors are a dimensionless, read-only reference representation; "
    "they are not physical tissue geometry, spatial-omics reconstruction, or "
    "evidence that this representation is superior to radius or grid baselines."
)

ABSTRACT_L0_NODES = tuple(sorted(ABSTRACT_GENE_NAMES))

_FULL_TURN = 2.0 * math.pi
_SECTOR_WIDTH = _FULL_TURN / CLOCK_DIRECTION_COUNT
_HALF_SECTOR = _SECTOR_WIDTH / 2.0
_BOUNDARY_TOLERANCE = 1e-12


def _rounded(value: float) -> float:
    result = round(float(value), 12)
    return 0.0 if result == 0.0 else result


def _require_non_empty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")


@dataclass(frozen=True, slots=True)
class ClockSectorNeighbor:
    """One neighbour projected into a focal Cell's clock-sector slot."""

    cell_id: str
    distance: float
    normalized_distance: float
    abstract_l0_nodes: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        _require_non_empty(self.cell_id, "neighbor cell_id")
        for name in ("distance", "normalized_distance"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"neighbor {name} must be finite and positive")
        names = tuple(name for name, _ in self.abstract_l0_nodes)
        if names != ABSTRACT_L0_NODES:
            raise ValueError("neighbor abstract L0 nodes must be complete and sorted")
        if any(
            not math.isfinite(value) or not 0.0 <= value <= 1.0
            for _, value in self.abstract_l0_nodes
        ):
            raise ValueError("neighbor abstract L0 values must be finite and in [0, 1]")

    def as_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "distance": self.distance,
            "normalized_distance": self.normalized_distance,
            "abstract_l0_nodes": [
                {"name": name, "value": value}
                for name, value in self.abstract_l0_nodes
            ],
        }


@dataclass(frozen=True, slots=True)
class ClockSectorBin:
    """One of the 18 direction-by-ring slots for a focal Cell."""

    direction_index: int
    ring_index: int
    neighbors: tuple[ClockSectorNeighbor, ...]

    def __post_init__(self) -> None:
        if self.direction_index not in range(CLOCK_DIRECTION_COUNT):
            raise ValueError("direction_index must identify one of six sectors")
        if self.ring_index not in range(CLOCK_RING_COUNT):
            raise ValueError("ring_index must identify one of three rings")
        ordering = tuple(
            (neighbor.normalized_distance, neighbor.cell_id)
            for neighbor in self.neighbors
        )
        if ordering != tuple(sorted(ordering)):
            raise ValueError("clock-sector neighbors must be deterministically sorted")
        if len({neighbor.cell_id for neighbor in self.neighbors}) != len(
            self.neighbors
        ):
            raise ValueError("a clock-sector bin cannot repeat a neighbor")

    @property
    def slot_id(self) -> str:
        return f"d{self.direction_index}-r{self.ring_index}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "direction_index": self.direction_index,
            "direction_label": CLOCK_DIRECTION_LABELS[self.direction_index],
            "ring_index": self.ring_index,
            "ring_label": CLOCK_RING_LABELS[self.ring_index],
            "neighbor_count": len(self.neighbors),
            "neighbors": [neighbor.as_dict() for neighbor in self.neighbors],
        }


@dataclass(frozen=True, slots=True)
class ClockCellObservation:
    """Complete 18-slot observation centred on one Cell."""

    cell_id: str
    x: float
    y: float
    bins: tuple[ClockSectorBin, ...]

    def __post_init__(self) -> None:
        _require_non_empty(self.cell_id, "focal cell_id")
        if any(not math.isfinite(value) for value in (self.x, self.y)):
            raise ValueError("focal coordinates must be finite")
        expected = tuple(
            (direction, ring)
            for direction in range(CLOCK_DIRECTION_COUNT)
            for ring in range(CLOCK_RING_COUNT)
        )
        observed = tuple(
            (slot.direction_index, slot.ring_index) for slot in self.bins
        )
        if observed != expected:
            raise ValueError("each Cell must contain all 18 clock-sector slots")
        neighbor_ids = [
            neighbor.cell_id
            for slot in self.bins
            for neighbor in slot.neighbors
        ]
        if self.cell_id in neighbor_ids or len(neighbor_ids) != len(set(neighbor_ids)):
            raise ValueError("each other Cell must occur in exactly one focal slot")

    def as_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "coordinate": {"x": self.x, "y": self.y},
            "bins": [slot.as_dict() for slot in self.bins],
        }


@dataclass(frozen=True, slots=True)
class ClockSectorObservation:
    """One same-tick, provenance-complete clock-sector artifact payload."""

    logical_time: int
    normalization_distance: float
    l3_model_version: str
    l3_source_digest: str
    l0_sources: tuple[tuple[str, int, str, str], ...]
    cells: tuple[ClockCellObservation, ...]

    def __post_init__(self) -> None:
        if self.logical_time < 0:
            raise ValueError("observation logical_time must be non-negative")
        if not math.isfinite(self.normalization_distance) or self.normalization_distance <= 0:
            raise ValueError("normalization distance must be finite and positive")
        _require_non_empty(self.l3_model_version, "L3 model_version")
        _require_non_empty(self.l3_source_digest, "L3 source_digest")
        cell_ids = tuple(cell.cell_id for cell in self.cells)
        source_ids = tuple(item[0] for item in self.l0_sources)
        if not cell_ids or cell_ids != tuple(sorted(cell_ids)):
            raise ValueError("clock-sector Cell observations must be non-empty and sorted")
        if source_ids != cell_ids:
            raise ValueError("L0 sources must align with observed Cells")
        for cell_id, l0_time, model_version, source_digest in self.l0_sources:
            _require_non_empty(cell_id, "L0 source cell_id")
            if l0_time < 0 or l0_time > self.logical_time:
                raise ValueError("L0 source time must be visible at the observation tick")
            _require_non_empty(model_version, "L0 source model_version")
            _require_non_empty(source_digest, "L0 source digest")

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": CLOCK_SECTOR_SCHEMA,
            "observer_version": CLOCK_SECTOR_OBSERVER_VERSION,
            "scientific_boundary": CLOCK_SECTOR_SCIENTIFIC_BOUNDARY,
            "logical_time": self.logical_time,
            "source": {
                "l3_model_version": self.l3_model_version,
                "l3_source_digest": self.l3_source_digest,
                "l0": [
                    {
                        "cell_id": cell_id,
                        "logical_time": logical_time,
                        "model_version": model_version,
                        "source_digest": source_digest,
                    }
                    for cell_id, logical_time, model_version, source_digest in self.l0_sources
                ],
            },
            "normalization": {
                "method": "median-nearest-neighbor-distance",
                "distance": self.normalization_distance,
                "single_cell_fallback": 1.0,
            },
            "encoding": {
                "direction_count": CLOCK_DIRECTION_COUNT,
                "ring_count": CLOCK_RING_COUNT,
                "direction_labels": list(CLOCK_DIRECTION_LABELS),
                "direction_centers_degrees": [
                    index * 60 for index in range(CLOCK_DIRECTION_COUNT)
                ],
                "angular_boundary_policy": "counter-clockwise-sector",
                "ring_boundaries_normalized": list(CLOCK_RING_BOUNDARIES),
                "radial_boundary_policy": "inner-ring",
                "slot_order": "direction-major-then-ring",
            },
            "cells": [cell.as_dict() for cell in self.cells],
        }

    @property
    def observation_digest(self) -> str:
        return digest_payload(self._payload())

    def as_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["observation_digest"] = digest_payload(payload)
        return payload


def _median_nearest_neighbor_distance(
    coordinates: tuple[tuple[str, float, float], ...],
) -> float:
    if len(coordinates) == 1:
        return 1.0
    nearest = []
    for focal_id, focal_x, focal_y in coordinates:
        distances = [
            math.hypot(other_x - focal_x, other_y - focal_y)
            for other_id, other_x, other_y in coordinates
            if other_id != focal_id
        ]
        minimum = min(distances)
        if minimum <= 0.0:
            raise ValueError(
                "clock-sector normalization requires distinct Cell coordinates"
            )
        nearest.append(minimum)
    scale = statistics.median(nearest)
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("invalid median nearest-neighbor normalization distance")
    return scale


def _direction_index(delta_x: float, delta_y: float) -> int:
    angle = math.atan2(delta_y, delta_x) % _FULL_TURN
    shifted = (angle + _HALF_SECTOR) % _FULL_TURN
    scaled = shifted / _SECTOR_WIDTH
    closest_boundary = round(scaled)
    if math.isclose(
        scaled,
        closest_boundary,
        rel_tol=0.0,
        abs_tol=_BOUNDARY_TOLERANCE,
    ):
        scaled = float(closest_boundary)
    return int(math.floor(scaled)) % CLOCK_DIRECTION_COUNT


def _ring_index(normalized_distance: float) -> int:
    for index, boundary in enumerate(CLOCK_RING_BOUNDARIES):
        if normalized_distance < boundary or math.isclose(
            normalized_distance,
            boundary,
            rel_tol=0.0,
            abs_tol=_BOUNDARY_TOLERANCE,
        ):
            return index
    return CLOCK_RING_COUNT - 1


def _l0_nodes(state: TranscriptState) -> tuple[tuple[str, float], ...]:
    return tuple((name, _rounded(getattr(state, name))) for name in ABSTRACT_L0_NODES)


class ClockSectorObserver:
    """Build deterministic clock-sector summaries without mutating inputs."""

    @property
    def model_version(self) -> str:
        return CLOCK_SECTOR_OBSERVER_VERSION

    def observe(
        self,
        tissue_state: SpatialTissueState,
        transcript_states: Iterable[TranscriptState],
    ) -> ClockSectorObservation:
        if not isinstance(tissue_state, SpatialTissueState):
            raise TypeError("ClockSectorObserver requires a SpatialTissueState")
        transcripts = tuple(transcript_states)
        if any(not isinstance(state, TranscriptState) for state in transcripts):
            raise TypeError("clock-sector L0 inputs must be TranscriptState objects")
        transcript_by_id = {state.cell_id: state for state in transcripts}
        if len(transcript_by_id) != len(transcripts):
            raise ValueError("clock-sector L0 Cell ids must be unique")
        coordinate_ids = tuple(item.cell_id for item in tissue_state.coordinates)
        if set(transcript_by_id) != set(coordinate_ids):
            raise ValueError("clock-sector L0 and L3 Cell identities must align")
        logical_time = tissue_state.metadata.logical_time
        if any(state.metadata.logical_time > logical_time for state in transcripts):
            raise ValueError("clock-sector L0 state cannot come from a future tick")

        coordinates = tuple(
            (item.cell_id, float(item.x), float(item.y))
            for item in tissue_state.coordinates
        )
        scale = _median_nearest_neighbor_distance(coordinates)
        coordinate_by_id = {
            cell_id: (x, y) for cell_id, x, y in coordinates
        }
        cells = tuple(
            self._observe_cell(
                focal_id,
                coordinate_by_id,
                transcript_by_id,
                scale,
            )
            for focal_id in sorted(coordinate_by_id)
        )
        l0_sources = tuple(
            (
                cell_id,
                transcript_by_id[cell_id].metadata.logical_time,
                transcript_by_id[cell_id].metadata.model_version,
                transcript_by_id[cell_id].metadata.source_digest,
            )
            for cell_id in sorted(transcript_by_id)
        )
        return ClockSectorObservation(
            logical_time=logical_time,
            normalization_distance=_rounded(scale),
            l3_model_version=tissue_state.metadata.model_version,
            l3_source_digest=tissue_state.metadata.source_digest,
            l0_sources=l0_sources,
            cells=cells,
        )

    def observe_tick(self, tick: Any) -> ClockSectorObservation:
        """Observe a trace-like tick without importing the runner module."""

        try:
            logical_time = tick.logical_time
            tissue_state = tick.l3
            transcript_states = tick.l0
        except AttributeError as error:
            raise TypeError("observe_tick requires a formal trace-like tick") from error
        if tissue_state.metadata.logical_time != logical_time:
            raise ValueError("trace tick and spatial L3 logical times must match")
        return self.observe(tissue_state, transcript_states)

    @staticmethod
    def _observe_cell(
        focal_id: str,
        coordinates: dict[str, tuple[float, float]],
        transcripts: dict[str, TranscriptState],
        scale: float,
    ) -> ClockCellObservation:
        focal_x, focal_y = coordinates[focal_id]
        grouped: dict[tuple[int, int], list[ClockSectorNeighbor]] = {
            (direction, ring): []
            for direction in range(CLOCK_DIRECTION_COUNT)
            for ring in range(CLOCK_RING_COUNT)
        }
        for neighbor_id in sorted(coordinates):
            if neighbor_id == focal_id:
                continue
            neighbor_x, neighbor_y = coordinates[neighbor_id]
            delta_x = neighbor_x - focal_x
            delta_y = neighbor_y - focal_y
            distance = math.hypot(delta_x, delta_y)
            if distance <= 0.0:
                raise ValueError(
                    "clock-sector observation requires distinct Cell coordinates"
                )
            normalized = distance / scale
            key = (_direction_index(delta_x, delta_y), _ring_index(normalized))
            grouped[key].append(
                ClockSectorNeighbor(
                    cell_id=neighbor_id,
                    distance=_rounded(distance),
                    normalized_distance=_rounded(normalized),
                    abstract_l0_nodes=_l0_nodes(transcripts[neighbor_id]),
                )
            )
        bins = tuple(
            ClockSectorBin(
                direction_index=direction,
                ring_index=ring,
                neighbors=tuple(
                    sorted(
                        grouped[(direction, ring)],
                        key=lambda item: (item.normalized_distance, item.cell_id),
                    )
                ),
            )
            for direction in range(CLOCK_DIRECTION_COUNT)
            for ring in range(CLOCK_RING_COUNT)
        )
        return ClockCellObservation(
            cell_id=focal_id,
            x=_rounded(focal_x),
            y=_rounded(focal_y),
            bins=bins,
        )


def observe_clock_sectors(
    tissue_state: SpatialTissueState,
    transcript_states: Iterable[TranscriptState],
) -> ClockSectorObservation:
    """Functional entry point for one same-tick spatial/L0 observation."""

    return ClockSectorObserver().observe(tissue_state, transcript_states)


def save_clock_sector_artifact(
    path: str | Path, observation: ClockSectorObservation
) -> Path:
    """Write one canonical observation once; accept byte-identical rebuilds."""

    if not isinstance(observation, ClockSectorObservation):
        raise TypeError("clock-sector artifact requires a ClockSectorObservation")
    target = Path(path)
    content = (
        json.dumps(
            observation.as_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    if target.exists():
        if target.read_bytes() != content:
            raise ValueError("refusing to overwrite a different clock-sector artifact")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp")
    if temporary.exists():
        raise ValueError("temporary clock-sector artifact path already exists")
    temporary.write_bytes(content)
    temporary.replace(target)
    return target
