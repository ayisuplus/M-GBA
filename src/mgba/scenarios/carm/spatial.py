"""Checkpoint-complete causal spatial L3 reference model for CAR-M.

This optional model upgrades only L3.  It keeps normalized two-dimensional
coordinates, a three-channel dimensionless field grid, and a radius-derived
local topology in the formal ``SpatialTissueState``.  It is deliberately a
small deterministic reference model, not a physical diffusion solver or a
validated reconstruction of tumor tissue geometry.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any

from ...experiment import digest_payload
from ...layers import (
    CellAction,
    CellPhase,
    CellState,
    FeedbackConstraint,
    LocalEnvironment,
    SpatialCoordinate,
    SpatialFieldCell,
    SpatialTissueState,
    StateMetadata,
    TissueNodeState,
    TissueState,
)
from .models import CarmTissueModel
from .scenario import CarmTissueConfig, CellRole


_IMMUNE_ROLES = {
    CellRole.ENGINEERED_MACROPHAGE,
    CellRole.WILD_TYPE_MACROPHAGE,
    CellRole.CD8_T_CELL,
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _require_unit(value: float, name: str) -> None:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and in [0, 1]")


@dataclass(frozen=True, slots=True)
class CarmSpatialConfig:
    """Pre-registered parameters for the CAR-M spatial L3 variant."""

    model_version: str
    seed: int
    grid_rows: int
    grid_columns: int
    neighbor_radius: float
    movement_rate: float
    field_retention: float
    field_diffusion: float
    stress_source_gain: float
    resource_sink_gain: float
    signal_source_gain: float
    node_field_coupling: float

    def __post_init__(self) -> None:
        if not isinstance(self.model_version, str) or not self.model_version.strip():
            raise ValueError("CAR-M spatial model_version must not be empty")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("CAR-M spatial seed must be a non-negative integer")
        for name in ("grid_rows", "grid_columns"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 2:
                raise ValueError(f"{name} must be an integer of at least two")
        if (
            not math.isfinite(self.neighbor_radius)
            or self.neighbor_radius <= 0.0
            or self.neighbor_radius > math.sqrt(2.0)
        ):
            raise ValueError(
                "neighbor_radius must be finite and in (0, sqrt(2)]"
            )
        for name in (
            "movement_rate",
            "field_retention",
            "field_diffusion",
            "stress_source_gain",
            "resource_sink_gain",
            "signal_source_gain",
            "node_field_coupling",
        ):
            _require_unit(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class CarmSpatialMechanisms:
    """Explicit switches for the L3-only factorial mechanism audit."""

    movement: bool
    field_coupling: bool
    spatial_topology: bool

    def __post_init__(self) -> None:
        for name in ("movement", "field_coupling", "spatial_topology"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} mechanism switch must be a bool")

    @property
    def condition_id(self) -> str:
        return (
            f"space_m{int(self.movement)}_"
            f"f{int(self.field_coupling)}_"
            f"t{int(self.spatial_topology)}"
        )


def load_carm_spatial_config(path: str | Path) -> CarmSpatialConfig:
    try:
        raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("CAR-M spatial config root must be an object")
        return CarmSpatialConfig(
            model_version=str(raw["model_version"]),
            seed=raw["seed"],
            grid_rows=raw["grid_rows"],
            grid_columns=raw["grid_columns"],
            neighbor_radius=float(raw["neighbor_radius"]),
            movement_rate=float(raw["movement_rate"]),
            field_retention=float(raw["field_retention"]),
            field_diffusion=float(raw["field_diffusion"]),
            stress_source_gain=float(raw["stress_source_gain"]),
            resource_sink_gain=float(raw["resource_sink_gain"]),
            signal_source_gain=float(raw["signal_source_gain"]),
            node_field_coupling=float(raw["node_field_coupling"]),
        )
    except (KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid CAR-M spatial config: {error}") from error


class SpatialCarmTissueModel:
    """Deterministic CAR-M L3 with explicit positions, fields, and topology."""

    def __init__(
        self,
        tissue_config: CarmTissueConfig,
        spatial_config: CarmSpatialConfig,
        *,
        roles: tuple[tuple[str, CellRole], ...],
        source_profile_digest: str,
        mechanisms: CarmSpatialMechanisms | None = None,
    ) -> None:
        if not isinstance(tissue_config, CarmTissueConfig):
            raise TypeError("spatial CAR-M requires a CarmTissueConfig")
        if not isinstance(spatial_config, CarmSpatialConfig):
            raise TypeError("spatial CAR-M requires a CarmSpatialConfig")
        self.config = spatial_config
        self.roles = dict(roles)
        if not self.roles or len(self.roles) != len(roles):
            raise ValueError("spatial CAR-M roles must be non-empty and unique")
        if not source_profile_digest.strip():
            raise ValueError("spatial CAR-M requires a source profile digest")
        if mechanisms is not None and not isinstance(
            mechanisms, CarmSpatialMechanisms
        ):
            raise TypeError("spatial mechanisms must be CarmSpatialMechanisms")
        self.source_profile_digest = source_profile_digest
        self.mechanisms = mechanisms
        self._base = CarmTissueModel(
            tissue_config,
            roles=roles,
            source_profile_digest=source_profile_digest,
        )

    @property
    def model_version(self) -> str:
        identity: tuple[Any, ...] = (
            self._base.model_version,
            self.config,
            tuple(sorted(self.roles.items())),
            self.source_profile_digest,
        )
        if self.mechanisms is not None:
            identity = (*identity, self.mechanisms)
        return f"{self.config.model_version}+{digest_payload(identity)[:12]}"

    def step(
        self,
        cell_states: tuple[CellState, ...],
        cell_actions: tuple[CellAction, ...],
        *,
        initial_environments: tuple[LocalEnvironment, ...] | None,
        previous_state: TissueState | None,
        edges: tuple[tuple[str, str], ...],
        logical_time: int,
        constraint: FeedbackConstraint | None = None,
    ) -> SpatialTissueState:
        if constraint is not None:
            raise ValueError(
                "spatial CAR-M does not support feedback constraints in this "
                "single-layer comparison"
            )
        cells, actions = self._validate_l2_inputs(
            cell_states, cell_actions, logical_time=logical_time
        )
        self._validate_boundary_edges(edges, set(cells))

        if previous_state is None:
            if initial_environments is None:
                raise ValueError("initial spatial CAR-M step requires environments")
            environment_ids = tuple(item.cell_id for item in initial_environments)
            if environment_ids != tuple(sorted(cells)):
                raise ValueError("initial spatial environments must align")
            coordinates = self._initial_coordinates()
            previous_field = self._initial_field(initial_environments)
        else:
            if initial_environments is not None:
                raise ValueError("resumed spatial CAR-M step cannot reset environments")
            if not isinstance(previous_state, SpatialTissueState):
                raise TypeError(
                    "previous spatial CAR-M state must be a SpatialTissueState"
                )
            if previous_state.metadata.logical_time >= logical_time:
                raise ValueError("previous spatial state must precede this step")
            if (
                previous_state.field_rows != self.config.grid_rows
                or previous_state.field_columns != self.config.grid_columns
            ):
                raise ValueError("previous spatial grid does not match the config")
            movement_enabled = (
                self.mechanisms is None or self.mechanisms.movement
            )
            coordinates = (
                self._move_coordinates(
                    previous_state.coordinates,
                    previous_state.field_cells,
                    cells,
                    logical_time=logical_time,
                    use_field_gradients=(
                        self.mechanisms is None
                        or self.mechanisms.field_coupling
                    ),
                )
                if movement_enabled
                else previous_state.coordinates
            )
            previous_field = previous_state.field_cells

        field_enabled = (
            self.mechanisms is None or self.mechanisms.field_coupling
        )
        field_cells = (
            self._advance_field(previous_field, coordinates, cells, actions)
            if field_enabled
            else previous_field
        )
        spatial_edges = (
            self._spatial_edges(coordinates)
            if self.mechanisms is None or self.mechanisms.spatial_topology
            else edges
        )
        base = self._base.step(
            cell_states,
            cell_actions,
            initial_environments=initial_environments,
            previous_state=previous_state,
            edges=spatial_edges,
            logical_time=logical_time,
            constraint=None,
        )
        field_by_index = {
            (item.row, item.column): item for item in field_cells
        }
        coordinate_by_id = {item.cell_id: item for item in coordinates}
        coupling = self.config.node_field_coupling if field_enabled else 0.0
        nodes = tuple(
            self._coupled_node(
                node,
                self._sample_field(
                    coordinate_by_id[node.cell_id], field_by_index
                ),
                coupling,
            )
            for node in base.nodes
        )
        source = {
            "base_step_digest": base.metadata.source_digest,
            "previous_spatial_state": previous_state,
            "scenario_boundary_edges": edges,
            "spatial_edges": spatial_edges,
            "coordinates": coordinates,
            "field_cells": field_cells,
            "spatial_config": self.config,
            "source_profile_digest": self.source_profile_digest,
        }
        if self.mechanisms is not None:
            source["mechanisms"] = self.mechanisms
        return SpatialTissueState(
            metadata=StateMetadata(
                logical_time=logical_time,
                model_version=self.model_version,
                source_digest=digest_payload(source),
            ),
            cell_count=base.cell_count,
            nodes=nodes,
            edges=spatial_edges,
            edge_density=base.edge_density,
            mean_activation=base.mean_activation,
            mean_viability=base.mean_viability,
            mean_resource=fmean(node.resource_level for node in nodes),
            mean_signal=fmean(node.signal for node in nodes),
            dead_fraction=base.dead_fraction,
            repair_activity=base.repair_activity,
            coordinated_signal=fmean(node.signal for node in nodes),
            tissue_damage=base.tissue_damage,
            coordinates=coordinates,
            field_rows=self.config.grid_rows,
            field_columns=self.config.grid_columns,
            field_cells=field_cells,
        )

    def _validate_l2_inputs(
        self,
        cell_states: tuple[CellState, ...],
        cell_actions: tuple[CellAction, ...],
        *,
        logical_time: int,
    ) -> tuple[dict[str, CellState], dict[str, CellAction]]:
        if logical_time < 1:
            raise ValueError("spatial CAR-M logical_time must be positive")
        if not cell_states or len(cell_states) != len(cell_actions):
            raise ValueError("spatial CAR-M requires aligned L2 states and actions")
        cell_ids = tuple(item.cell_id for item in cell_states)
        action_ids = tuple(item.cell_id for item in cell_actions)
        if cell_ids != tuple(sorted(cell_ids)) or cell_ids != action_ids:
            raise ValueError("spatial CAR-M Cell ids must be aligned and sorted")
        if set(cell_ids) != set(self.roles):
            raise ValueError("spatial CAR-M roles must cover every Cell")
        return (
            {item.cell_id: item for item in cell_states},
            {item.cell_id: item for item in cell_actions},
        )

    @staticmethod
    def _validate_boundary_edges(
        edges: tuple[tuple[str, str], ...], cell_ids: set[str]
    ) -> None:
        if edges != tuple(sorted(edges)) or len(edges) != len(set(edges)):
            raise ValueError("scenario boundary edges must be unique and sorted")
        if any(
            source == target or source not in cell_ids or target not in cell_ids
            for source, target in edges
        ):
            raise ValueError("scenario boundary edges must connect known Cells")

    def _initial_coordinates(self) -> tuple[SpatialCoordinate, ...]:
        rings = {
            CellRole.ENGINEERED_MACROPHAGE: 0.28,
            CellRole.WILD_TYPE_MACROPHAGE: 0.36,
            CellRole.CD8_T_CELL: 0.44,
        }
        result = []
        for cell_id, role in sorted(self.roles.items()):
            angle = 2.0 * math.pi * self._fraction(f"angle|{role.value}|{cell_id}")
            radial_fraction = self._fraction(f"radius|{role.value}|{cell_id}")
            if role is CellRole.TUMOR:
                radius = 0.03 + 0.15 * math.sqrt(radial_fraction)
            else:
                radius = rings[role] + 0.035 * (2.0 * radial_fraction - 1.0)
            result.append(
                SpatialCoordinate(
                    cell_id=cell_id,
                    x=_clamp(0.5 + radius * math.cos(angle)),
                    y=_clamp(0.5 + radius * math.sin(angle)),
                )
            )
        return tuple(result)

    def _fraction(self, label: str) -> float:
        payload = f"{self.config.seed}|{label}".encode("utf-8")
        integer = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
        return integer / float((1 << 64) - 1)

    def _initial_field(
        self, environments: tuple[LocalEnvironment, ...]
    ) -> tuple[SpatialFieldCell, ...]:
        stress = fmean(item.stress for item in environments)
        resource = fmean(item.resource_level for item in environments)
        signal = fmean(item.incoming_signal for item in environments)
        return tuple(
            SpatialFieldCell(row, column, stress, resource, signal)
            for row in range(self.config.grid_rows)
            for column in range(self.config.grid_columns)
        )

    def _move_coordinates(
        self,
        previous: tuple[SpatialCoordinate, ...],
        field_cells: tuple[SpatialFieldCell, ...],
        cells: dict[str, CellState],
        *,
        logical_time: int,
        use_field_gradients: bool = True,
    ) -> tuple[SpatialCoordinate, ...]:
        field = {(item.row, item.column): item for item in field_cells}
        result = []
        for coordinate in previous:
            state = cells[coordinate.cell_id]
            role = self.roles[coordinate.cell_id]
            if role not in _IMMUNE_ROLES or state.phase is CellPhase.DEAD:
                result.append(coordinate)
                continue
            stress_gradient = (
                self._field_gradient(coordinate, field, channel="stress")
                if use_field_gradients
                else (0.0, 0.0)
            )
            signal_gradient = (
                self._field_gradient(coordinate, field, channel="signal")
                if use_field_gradients
                else (0.0, 0.0)
            )
            angle = 2.0 * math.pi * self._fraction(
                f"move|{logical_time}|{coordinate.cell_id}"
            )
            dx = (
                signal_gradient[0]
                + 0.6 * stress_gradient[0]
                + 0.25 * (0.5 - coordinate.x)
                + 0.15 * math.cos(angle)
            )
            dy = (
                signal_gradient[1]
                + 0.6 * stress_gradient[1]
                + 0.25 * (0.5 - coordinate.y)
                + 0.15 * math.sin(angle)
            )
            norm = math.hypot(dx, dy)
            if norm <= 1e-15:
                result.append(coordinate)
                continue
            distance = (
                self.config.movement_rate
                * state.viability
                * (0.25 + 0.75 * state.activation)
            )
            result.append(
                SpatialCoordinate(
                    cell_id=coordinate.cell_id,
                    x=_clamp(coordinate.x + distance * dx / norm),
                    y=_clamp(coordinate.y + distance * dy / norm),
                )
            )
        return tuple(result)

    def _field_gradient(
        self,
        coordinate: SpatialCoordinate,
        field: dict[tuple[int, int], SpatialFieldCell],
        *,
        channel: str,
    ) -> tuple[float, float]:
        row, column = self._grid_index(coordinate)
        left = max(0, column - 1)
        right = min(self.config.grid_columns - 1, column + 1)
        top = max(0, row - 1)
        bottom = min(self.config.grid_rows - 1, row + 1)
        dx = (
            getattr(field[(row, right)], channel)
            - getattr(field[(row, left)], channel)
        ) / max(1, right - left)
        dy = (
            getattr(field[(bottom, column)], channel)
            - getattr(field[(top, column)], channel)
        ) / max(1, bottom - top)
        return dx, dy

    def _advance_field(
        self,
        previous: tuple[SpatialFieldCell, ...],
        coordinates: tuple[SpatialCoordinate, ...],
        cells: dict[str, CellState],
        actions: dict[str, CellAction],
    ) -> tuple[SpatialFieldCell, ...]:
        prior = {(item.row, item.column): item for item in previous}
        deposits: dict[tuple[int, int], list[str]] = {
            index: [] for index in prior
        }
        for coordinate in coordinates:
            deposits[self._grid_index(coordinate)].append(coordinate.cell_id)

        result = []
        for row in range(self.config.grid_rows):
            for column in range(self.config.grid_columns):
                index = (row, column)
                item = prior[index]
                neighbors = tuple(
                    prior[candidate]
                    for candidate in (
                        (row - 1, column),
                        (row + 1, column),
                        (row, column - 1),
                        (row, column + 1),
                    )
                    if candidate in prior
                )

                def diffuse(channel: str) -> float:
                    neighbor_mean = fmean(
                        getattr(neighbor, channel) for neighbor in neighbors
                    )
                    current = getattr(item, channel)
                    return current + self.config.field_diffusion * (
                        neighbor_mean - current
                    )

                local_ids = deposits[index]
                if local_ids:
                    stress_source = fmean(
                        (
                            0.5 * cells[cell_id].stress_load
                            + 0.5 * cells[cell_id].viability
                            if self.roles[cell_id] is CellRole.TUMOR
                            else cells[cell_id].stress_load
                        )
                        for cell_id in local_ids
                    )
                    resource_sink = fmean(
                        actions[cell_id].resource_consumption
                        for cell_id in local_ids
                    )
                    signal_source = fmean(
                        actions[cell_id].secretion for cell_id in local_ids
                    )
                else:
                    stress_source = resource_sink = signal_source = 0.0
                stress = _clamp(
                    self.config.field_retention * diffuse("stress")
                    + self.config.stress_source_gain * stress_source
                )
                resource_base = diffuse("resource_level")
                resource = _clamp(
                    resource_base
                    + self._base.config.resource_recovery * (1.0 - resource_base)
                    - self.config.resource_sink_gain * resource_sink
                )
                signal = _clamp(
                    self.config.field_retention * diffuse("signal")
                    + self.config.signal_source_gain * signal_source
                )
                result.append(
                    SpatialFieldCell(
                        row=row,
                        column=column,
                        stress=stress,
                        resource_level=resource,
                        signal=signal,
                    )
                )
        return tuple(result)

    def _grid_index(self, coordinate: SpatialCoordinate) -> tuple[int, int]:
        row = min(
            self.config.grid_rows - 1,
            int(coordinate.y * self.config.grid_rows),
        )
        column = min(
            self.config.grid_columns - 1,
            int(coordinate.x * self.config.grid_columns),
        )
        return row, column

    def _sample_field(
        self,
        coordinate: SpatialCoordinate,
        field: dict[tuple[int, int], SpatialFieldCell],
    ) -> SpatialFieldCell:
        return field[self._grid_index(coordinate)]

    @staticmethod
    def _coupled_node(
        node: TissueNodeState,
        field: SpatialFieldCell,
        coupling: float,
    ) -> TissueNodeState:
        complement = 1.0 - coupling
        return TissueNodeState(
            cell_id=node.cell_id,
            stress=_clamp(complement * node.stress + coupling * field.stress),
            resource_level=_clamp(
                complement * node.resource_level + coupling * field.resource_level
            ),
            signal=_clamp(complement * node.signal + coupling * field.signal),
        )

    def _spatial_edges(
        self, coordinates: tuple[SpatialCoordinate, ...]
    ) -> tuple[tuple[str, str], ...]:
        if len(coordinates) < 2:
            return ()
        points = {item.cell_id: item for item in coordinates}

        def distance(left: str, right: str) -> float:
            return math.hypot(
                points[left].x - points[right].x,
                points[left].y - points[right].y,
            )

        ids = tuple(sorted(points))
        edges = {
            (source, target)
            for source in ids
            for target in ids
            if source != target
            and distance(source, target) <= self.config.neighbor_radius
        }
        for cell_id in ids:
            nearest = min(
                (other for other in ids if other != cell_id),
                key=lambda other: (distance(cell_id, other), other),
            )
            if not any(source == cell_id for source, _ in edges):
                edges.add((cell_id, nearest))
            if not any(target == cell_id for _, target in edges):
                edges.add((nearest, cell_id))
        return tuple(sorted(edges))
