from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any

from ..hashing import digest_payload
from .contracts import (
    CellAction,
    CellPhase,
    CellState,
    FeedbackConstraint,
    LocalEnvironment,
    StateMetadata,
    TissueNodeState,
    TissueState,
)


@dataclass(frozen=True, slots=True)
class TissueConfig:
    model_version: str
    resource_recovery: float
    consumption_gain: float
    stress_retention: float
    stress_diffusion: float
    resource_stress_gain: float
    apoptosis_stress_gain: float
    repair_stress_reduction: float
    signal_retention: float
    secretion_coupling: float
    damage_stress_weight: float
    damage_viability_weight: float

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("tissue model_version must not be empty")
        for name in (
            "resource_recovery",
            "consumption_gain",
            "stress_retention",
            "stress_diffusion",
            "resource_stress_gain",
            "apoptosis_stress_gain",
            "repair_stress_reduction",
            "signal_retention",
            "secretion_coupling",
            "damage_stress_weight",
            "damage_viability_weight",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and in [0, 1]")
        if not math.isclose(
            self.damage_stress_weight + self.damage_viability_weight,
            1.0,
            abs_tol=1e-12,
        ):
            raise ValueError("tissue damage aggregation weights must sum to 1")


@dataclass(frozen=True, slots=True)
class TissueTrajectory:
    states: tuple[TissueState, ...]

    def __post_init__(self) -> None:
        if not self.states:
            raise ValueError("tissue trajectory must contain at least one state")


def load_tissue_config(path: str | Path) -> TissueConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return TissueConfig(
            model_version=str(raw["model_version"]),
            resource_recovery=float(raw["resource_recovery"]),
            consumption_gain=float(raw["consumption_gain"]),
            stress_retention=float(raw["stress_retention"]),
            stress_diffusion=float(raw["stress_diffusion"]),
            resource_stress_gain=float(raw["resource_stress_gain"]),
            apoptosis_stress_gain=float(raw["apoptosis_stress_gain"]),
            repair_stress_reduction=float(raw["repair_stress_reduction"]),
            signal_retention=float(raw["signal_retention"]),
            secretion_coupling=float(raw["secretion_coupling"]),
            damage_stress_weight=float(raw["damage_stress_weight"]),
            damage_viability_weight=float(raw["damage_viability_weight"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid tissue config: {error}") from error


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


class StaticTissueModel:
    """Frozen aggregate-only L3 baseline retained for contract regression."""

    model_version = "reference-l3-static-aggregate-0.2"

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
    ) -> TissueState:
        if constraint is not None:
            raise ValueError(
                "StaticTissueModel does not support feedback constraints"
            )
        inputs = _validated_inputs(
            cell_states=cell_states,
            cell_actions=cell_actions,
            initial_environments=initial_environments,
            previous_state=previous_state,
            edges=edges,
            logical_time=logical_time,
        )
        nodes = inputs.previous_nodes
        mean_secretion = fmean(action.secretion for action in inputs.actions.values())
        coordinated_signal = _clamp(
            mean_secretion * (0.5 + 0.5 * inputs.edge_density)
        )
        return _build_tissue_state(
            logical_time=logical_time,
            model_version=self.model_version,
            source=inputs.source,
            nodes=nodes,
            edges=inputs.edges,
            edge_density=inputs.edge_density,
            cell_states=inputs.cells,
            cell_actions=inputs.actions,
            coordinated_signal=coordinated_signal,
            tissue_damage=_clamp(
                fmean(node.stress for node in nodes)
                * (1.0 - fmean(cell.viability for cell in inputs.cells.values()))
            ),
        )


class TissueEnvironmentModel:
    """Deterministic fixed-graph environment dynamics for L3."""

    def __init__(self, config: TissueConfig) -> None:
        self.config = config

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

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
    ) -> TissueState:
        if constraint is not None:
            raise ValueError(
                "TissueEnvironmentModel does not support feedback constraints; "
                "use ConstraintAwareTissueModel"
            )
        inputs = _validated_inputs(
            cell_states=cell_states,
            cell_actions=cell_actions,
            initial_environments=initial_environments,
            previous_state=previous_state,
            edges=edges,
            logical_time=logical_time,
        )
        nodes = _environment_nodes(
            inputs=inputs,
            config=self.config,
            constraint=None,
            stress_floor_coupling=0.0,
        )

        mean_stress = fmean(node.stress for node in nodes)
        mean_viability = fmean(cell.viability for cell in inputs.cells.values())
        return _build_tissue_state(
            logical_time=logical_time,
            model_version=self.model_version,
            source={**inputs.source, "config": self.config},
            nodes=nodes,
            edges=inputs.edges,
            edge_density=inputs.edge_density,
            cell_states=inputs.cells,
            cell_actions=inputs.actions,
            coordinated_signal=fmean(node.signal for node in nodes),
            tissue_damage=_clamp(
                self.config.damage_stress_weight * mean_stress
                + self.config.damage_viability_weight * (1.0 - mean_viability)
            ),
        )

    def simulate(
        self,
        *,
        cell_states: tuple[CellState, ...],
        cell_actions: tuple[CellAction, ...],
        initial_environments: tuple[LocalEnvironment, ...],
        edges: tuple[tuple[str, str], ...],
        steps: int,
    ) -> TissueTrajectory:
        if steps < 1:
            raise ValueError("steps must be positive")
        states: list[TissueState] = []
        previous_state: TissueState | None = None
        for logical_time in range(1, steps + 1):
            state = self.step(
                cell_states,
                cell_actions,
                initial_environments=(
                    initial_environments if previous_state is None else None
                ),
                previous_state=previous_state,
                edges=edges,
                logical_time=logical_time,
            )
            states.append(state)
            previous_state = state
        return TissueTrajectory(states=tuple(states))


def environments_from_tissue(
    tissue: TissueState, *, logical_time: int
) -> tuple[LocalEnvironment, ...]:
    if not isinstance(tissue, TissueState):
        raise TypeError("environments require a TissueState")
    if logical_time <= tissue.metadata.logical_time:
        raise ValueError("next local environment time must advance beyond TissueState")
    return tuple(
        LocalEnvironment(
            metadata=_metadata(
                logical_time=logical_time,
                model_version="l3-to-l2-local-boundary-0.2",
                source={"tissue": tissue, "cell_id": node.cell_id},
            ),
            cell_id=node.cell_id,
            stress=node.stress,
            resource_level=node.resource_level,
            incoming_signal=node.signal,
        )
        for node in tissue.nodes
    )


def _environment_nodes(
    *,
    inputs: _ValidatedInputs,
    config: TissueConfig,
    constraint: FeedbackConstraint | None,
    stress_floor_coupling: float,
) -> tuple[TissueNodeState, ...]:
    """Deterministic node-level field update shared by the L3 environment models.

    Without a constraint this reproduces the reference equations bit-for-bit:
    the resource recovery target stays 1.0 and no stress-floor term is added.

    With a constraint ``c`` the equations become

    .. math::

        R_{t+1} = \\mathrm{clamp}\\bigl(
            R_t + \\rho\\,(r_k - R_t) - g\\,c_t\\bigr)

    .. math::

        \\Sigma_{t+1} = \\mathrm{clamp}\\bigl(
            \\Sigma_t' + \\gamma_c\\,\\max(0,\\, s_k - \\Sigma_t')\\bigr)

    where :math:`\\Sigma_t'` is the reference stress right-hand side,
    :math:`r_k` the resource ceiling and :math:`s_k` the stress floor.
    The stress-floor term is monotone upward and vanishes at :math:`s_k=0`.
    """
    resource_target = (
        constraint.resource_ceiling if constraint is not None else 1.0
    )
    stress_floor = constraint.stress_floor if constraint is not None else 0.0

    previous_nodes = {node.cell_id: node for node in inputs.previous_nodes}
    incoming_sources: dict[str, list[str]] = {
        cell_id: [] for cell_id in inputs.cells
    }
    for source, target in inputs.edges:
        incoming_sources[target].append(source)

    next_nodes: list[TissueNodeState] = []
    for cell_id in sorted(inputs.cells):
        previous = previous_nodes[cell_id]
        action = inputs.actions[cell_id]
        sources = incoming_sources[cell_id]
        incoming_stress = (
            fmean(previous_nodes[source].stress for source in sources)
            if sources
            else 0.0
        )
        incoming_secretion = (
            fmean(inputs.actions[source].secretion for source in sources)
            if sources
            else 0.0
        )
        resource = _clamp(
            previous.resource_level
            + config.resource_recovery * (resource_target - previous.resource_level)
            - config.consumption_gain * action.resource_consumption
        )
        stress = _clamp(
            config.stress_retention * previous.stress
            + config.stress_diffusion * incoming_stress
            + config.resource_stress_gain * (1.0 - resource)
            + config.apoptosis_stress_gain * float(action.apoptosis)
            - config.repair_stress_reduction * action.repair_effort
        )
        if constraint is not None and stress_floor > 0.0:
            stress = _clamp(
                stress
                + stress_floor_coupling * max(0.0, stress_floor - stress)
            )
        signal = _clamp(
            config.signal_retention * previous.signal
            + config.secretion_coupling * incoming_secretion
        )
        next_nodes.append(
            TissueNodeState(
                cell_id=cell_id,
                stress=stress,
                resource_level=resource,
                signal=signal,
            )
        )
    return tuple(next_nodes)


class ConstraintAwareTissueModel:
    """Deterministic fixed-graph L3 dynamics under an audited L4 constraint.

    With ``constraint=None`` every step is value-identical to
    ``TissueEnvironmentModel``; with a constraint the resource recovery
    target and the stress floor are reshaped as documented in ADR-0012.
    The constraint is serialized into the tissue state source digest so the
    downward action is traceable in the history hash chain.
    """

    def __init__(
        self, config: TissueConfig, *, stress_floor_coupling: float = 1.0
    ) -> None:
        if not isinstance(config, TissueConfig):
            raise TypeError("ConstraintAwareTissueModel requires a TissueConfig")
        if (
            not math.isfinite(stress_floor_coupling)
            or not 0.0 <= stress_floor_coupling <= 1.0
        ):
            raise ValueError("stress_floor_coupling must be finite and in [0, 1]")
        self.config = config
        self.stress_floor_coupling = stress_floor_coupling

    @property
    def model_version(self) -> str:
        return (
            f"{self.config.model_version}+{digest_payload((self.config, self.stress_floor_coupling))[:12]}"
        )

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
    ) -> TissueState:
        if constraint is not None:
            if not isinstance(constraint, FeedbackConstraint):
                raise TypeError("L3 constraint must be a FeedbackConstraint")
            if constraint.metadata.logical_time > logical_time:
                raise ValueError("L3 cannot consume a future feedback constraint")
        inputs = _validated_inputs(
            cell_states=cell_states,
            cell_actions=cell_actions,
            initial_environments=initial_environments,
            previous_state=previous_state,
            edges=edges,
            logical_time=logical_time,
        )
        nodes = _environment_nodes(
            inputs=inputs,
            config=self.config,
            constraint=constraint,
            stress_floor_coupling=self.stress_floor_coupling,
        )
        mean_stress = fmean(node.stress for node in nodes)
        mean_viability = fmean(cell.viability for cell in inputs.cells.values())
        source: dict[str, Any] = {**inputs.source, "config": self.config}
        if constraint is not None:
            source["constraint"] = constraint
        return _build_tissue_state(
            logical_time=logical_time,
            model_version=self.model_version,
            source=source,
            nodes=nodes,
            edges=inputs.edges,
            edge_density=inputs.edge_density,
            cell_states=inputs.cells,
            cell_actions=inputs.actions,
            coordinated_signal=fmean(node.signal for node in nodes),
            tissue_damage=_clamp(
                self.config.damage_stress_weight * mean_stress
                + self.config.damage_viability_weight * (1.0 - mean_viability)
            ),
        )


@dataclass(frozen=True, slots=True)
class _ValidatedInputs:
    cells: dict[str, CellState]
    actions: dict[str, CellAction]
    previous_nodes: tuple[TissueNodeState, ...]
    edges: tuple[tuple[str, str], ...]
    edge_density: float
    source: dict[str, Any]


def _validated_inputs(
    *,
    cell_states: tuple[CellState, ...],
    cell_actions: tuple[CellAction, ...],
    initial_environments: tuple[LocalEnvironment, ...] | None,
    previous_state: TissueState | None,
    edges: tuple[tuple[str, str], ...],
    logical_time: int,
    dynamic_topology: bool = False,
) -> _ValidatedInputs:
    if not cell_states or any(not isinstance(item, CellState) for item in cell_states):
        raise TypeError("Tissue models consume non-empty CellState objects")
    if any(not isinstance(item, CellAction) for item in cell_actions):
        raise TypeError("Tissue models consume CellAction objects")
    cells = {cell.cell_id: cell for cell in cell_states}
    actions = {action.cell_id: action for action in cell_actions}
    if len(cells) != len(cell_states) or len(actions) != len(cell_actions):
        raise ValueError("CellState and CellAction ids must be unique")
    if set(cells) != set(actions):
        raise ValueError("each CellState must have one same-id CellAction")
    for item in (*cell_states, *cell_actions):
        if item.metadata.logical_time > logical_time:
            raise ValueError("L3 cannot consume a future L2 object")

    normalized_edges = tuple(sorted(edges))
    if len(normalized_edges) != len(set(normalized_edges)):
        raise ValueError("tissue graph cannot contain duplicate edges")
    for source, target in normalized_edges:
        if source == target or source not in cells or target not in cells:
            raise ValueError("tissue edges must connect distinct known Cell ids")

    if (initial_environments is None) == (previous_state is None):
        raise ValueError(
            "provide initial_environments for the first tick or previous_state later"
        )
    if previous_state is None:
        assert initial_environments is not None
        if any(
            not isinstance(environment, LocalEnvironment)
            for environment in initial_environments
        ):
            raise TypeError("initial tissue environments must be LocalEnvironment objects")
        environments = {item.cell_id: item for item in initial_environments}
        if len(environments) != len(initial_environments) or set(environments) != set(
            cells
        ):
            raise ValueError("initial environments must match Cell ids exactly")
        for environment in initial_environments:
            if environment.metadata.logical_time > logical_time:
                raise ValueError("L3 cannot consume a future LocalEnvironment")
        previous_nodes = tuple(
            TissueNodeState(
                cell_id=cell_id,
                stress=environments[cell_id].stress,
                resource_level=environments[cell_id].resource_level,
                signal=environments[cell_id].incoming_signal,
            )
            for cell_id in sorted(cells)
        )
    else:
        if not isinstance(previous_state, TissueState):
            raise TypeError("previous L3 state must be a TissueState")
        if logical_time <= previous_state.metadata.logical_time:
            raise ValueError("logical_time must advance beyond previous TissueState")
        if dynamic_topology:
            effective_edges = tuple(sorted(previous_state.edges))
            if len(effective_edges) != len(set(effective_edges)):
                raise ValueError("previous topology cannot contain duplicate edges")
            for source, target in effective_edges:
                if source == target or source not in cells or target not in cells:
                    raise ValueError(
                        "previous topology edges must connect distinct known Cell ids"
                    )
            normalized_edges = effective_edges
        else:
            if tuple(previous_state.edges) != normalized_edges:
                raise ValueError(
                    "WP5 tissue topology must remain static within a trajectory"
                )
        if {node.cell_id for node in previous_state.nodes} != set(cells):
            raise ValueError("previous TissueState nodes must match current Cell ids")
        previous_nodes = previous_state.nodes

    possible_edges = len(cells) * max(1, len(cells) - 1)
    edge_density = len(normalized_edges) / possible_edges
    return _ValidatedInputs(
        cells=cells,
        actions=actions,
        previous_nodes=previous_nodes,
        edges=normalized_edges,
        edge_density=edge_density,
        source={
            "cell_states": cell_states,
            "cell_actions": cell_actions,
            "initial_environments": initial_environments,
            "previous_state": previous_state,
            "edges": normalized_edges,
        },
    )


def _build_tissue_state(
    *,
    logical_time: int,
    model_version: str,
    source: Any,
    nodes: tuple[TissueNodeState, ...],
    edges: tuple[tuple[str, str], ...],
    edge_density: float,
    cell_states: dict[str, CellState],
    cell_actions: dict[str, CellAction],
    coordinated_signal: float,
    tissue_damage: float,
) -> TissueState:
    return TissueState(
        metadata=_metadata(
            logical_time=logical_time,
            model_version=model_version,
            source=source,
        ),
        cell_count=len(cell_states),
        nodes=nodes,
        edges=edges,
        edge_density=edge_density,
        mean_activation=fmean(cell.activation for cell in cell_states.values()),
        mean_viability=fmean(cell.viability for cell in cell_states.values()),
        mean_resource=fmean(node.resource_level for node in nodes),
        mean_signal=fmean(node.signal for node in nodes),
        dead_fraction=fmean(
            float(cell.phase is CellPhase.DEAD) for cell in cell_states.values()
        ),
        repair_activity=fmean(
            action.repair_effort for action in cell_actions.values()
        ),
        coordinated_signal=coordinated_signal,
        tissue_damage=tissue_damage,
    )
