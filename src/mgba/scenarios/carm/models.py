from __future__ import annotations

from statistics import fmean
from typing import Any

from ...hashing import digest_payload
from ...layers import (
    CellAction,
    CellPhase,
    CellState,
    FeedbackConstraint,
    LocalEnvironment,
    MolecularState,
    StateMetadata,
    TissueNodeState,
    TissueState,
)
from .scenario import CarmCellConfig, CarmTissueConfig, CellRole


_MACROPHAGE_ROLES = {
    CellRole.ENGINEERED_MACROPHAGE,
    CellRole.WILD_TYPE_MACROPHAGE,
}
_IMMUNE_ROLES = {*_MACROPHAGE_ROLES, CellRole.CD8_T_CELL}


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


def _dead_action(metadata: StateMetadata, cell_id: str) -> CellAction:
    return CellAction(
        metadata=metadata,
        cell_id=cell_id,
        secretion=0.0,
        resource_consumption=0.0,
        repair_effort=0.0,
        apoptosis=True,
    )


class CarmCellModel:
    """Deterministic CAR-M Cell rules over only L1 and the local L3 boundary."""

    def __init__(
        self,
        config: CarmCellConfig,
        *,
        roles: tuple[tuple[str, CellRole], ...],
        source_profile_digest: str,
    ) -> None:
        self.config = config
        self.roles = dict(roles)
        if not self.roles or len(self.roles) != len(roles):
            raise ValueError("CAR-M Cell roles must be non-empty and unique")
        if not source_profile_digest.strip():
            raise ValueError("CAR-M Cell model requires a source profile digest")
        self.source_profile_digest = source_profile_digest

    @property
    def model_version(self) -> str:
        return (
            f"{self.config.model_version}+"
            f"{digest_payload((self.config, tuple(sorted(self.roles.items())), self.source_profile_digest))[:12]}"
        )
    def step(
        self,
        molecular: MolecularState,
        environment: LocalEnvironment,
        *,
        previous_state: CellState | None,
        logical_time: int,
    ) -> tuple[CellState, CellAction]:
        if not isinstance(molecular, MolecularState):
            raise TypeError("CAR-M Cell model consumes MolecularState only")
        if not isinstance(environment, LocalEnvironment):
            raise TypeError("CAR-M Cell model consumes LocalEnvironment only")
        if molecular.cell_id != environment.cell_id:
            raise ValueError("CAR-M Cell inputs must belong to the same Cell")
        if molecular.cell_id not in self.roles:
            raise ValueError("CAR-M Cell input has no configured role")
        if previous_state is not None and (
            not isinstance(previous_state, CellState)
            or previous_state.cell_id != molecular.cell_id
        ):
            raise ValueError("previous CAR-M Cell state is invalid")
        if molecular.metadata.logical_time > logical_time or environment.metadata.logical_time > logical_time:
            raise ValueError("CAR-M Cell model cannot consume future inputs")

        role = self.roles[molecular.cell_id]
        source = {
            "molecular": molecular,
            "environment": environment,
            "previous_state": previous_state,
            "role": role,
            "config": self.config,
            "source_profile_digest": self.source_profile_digest,
        }
        metadata = _metadata(
            logical_time=logical_time,
            model_version=self.model_version,
            source=source,
        )
        if previous_state is not None and previous_state.phase is CellPhase.DEAD:
            state = CellState(
                metadata=metadata,
                cell_id=molecular.cell_id,
                phase=CellPhase.DEAD,
                activation=0.0,
                viability=0.0,
                stress_load=previous_state.stress_load,
            )
            return state, _dead_action(metadata, molecular.cell_id)

        previous_viability = previous_state.viability if previous_state else 1.0
        stress_load = _clamp(
            0.65 * environment.stress
            + 0.35 * (1.0 - environment.resource_level)
        )
        feedback_factor = _clamp(
            1.0
            - self.config.feedback_suppression * molecular.feedback_inhibitor
        )

        if role in _MACROPHAGE_ROLES:
            activation = _clamp(
                (
                    self.config.macrophage_signal_weight
                    * molecular.signal_protein
                    + (1.0 - self.config.macrophage_signal_weight)
                    * environment.incoming_signal
                )
                * feedback_factor
            )
            effector = _clamp(
                self.config.macrophage_repair_gain
                * activation
                * molecular.repair_protein
                * environment.resource_level
            )
            viability = _clamp(
                previous_viability
                + self.config.immune_recovery_rate
                * molecular.metabolic_capacity
                * environment.resource_level
                - self.config.immune_stress_rate * stress_load
            )
            secretion = _clamp(
                activation * (0.5 + 0.5 * molecular.repair_protein)
            )
            consumption = _clamp(0.1 + 0.35 * activation + 0.25 * effector)
            repair_effort = effector
        elif role is CellRole.CD8_T_CELL:
            activation = _clamp(
                (
                    self.config.cd8_signal_weight * molecular.signal_protein
                    + (1.0 - self.config.cd8_signal_weight)
                    * environment.incoming_signal
                )
                * feedback_factor
            )
            effector = _clamp(
                activation * environment.resource_level * (1.0 - stress_load)
            )
            viability = _clamp(
                previous_viability
                + self.config.immune_recovery_rate
                * molecular.metabolic_capacity
                * environment.resource_level
                - self.config.immune_stress_rate * stress_load
            )
            secretion = activation
            consumption = _clamp(0.08 + 0.4 * activation)
            repair_effort = effector
        else:
            activation = _clamp(
                0.6
                * molecular.metabolic_capacity
                * environment.resource_level
                + 0.4 * molecular.signal_protein
            )
            stress_load = _clamp(stress_load + 0.25 * molecular.death_effector)
            viability = _clamp(
                previous_viability
                + self.config.tumor_growth_rate * activation
                - self.config.tumor_stress_rate * stress_load
            )
            secretion = _clamp(
                activation * (0.4 + 0.6 * molecular.feedback_inhibitor)
            )
            consumption = _clamp(0.2 + 0.5 * activation)
            repair_effort = 0.0

        apoptosis = viability <= self.config.apoptosis_threshold
        if apoptosis:
            viability = 0.0
            phase = CellPhase.DEAD
        elif stress_load >= self.config.stress_threshold:
            phase = CellPhase.STRESSED
        elif role in _MACROPHAGE_ROLES and repair_effort >= self.config.activation_threshold:
            phase = CellPhase.REPAIRING
        elif activation >= self.config.activation_threshold:
            phase = CellPhase.ACTIVATED
        else:
            phase = CellPhase.QUIESCENT
        state = CellState(
            metadata=metadata,
            cell_id=molecular.cell_id,
            phase=phase,
            activation=activation,
            viability=viability,
            stress_load=stress_load,
        )
        if apoptosis:
            return state, _dead_action(metadata, molecular.cell_id)
        return state, CellAction(
            metadata=metadata,
            cell_id=molecular.cell_id,
            secretion=secretion,
            resource_consumption=consumption,
            repair_effort=repair_effort,
            apoptosis=False,
        )


class CarmTissueModel:
    """Fixed-graph tumor microenvironment adapter over formal L2 outputs."""

    def __init__(
        self,
        config: CarmTissueConfig,
        *,
        roles: tuple[tuple[str, CellRole], ...],
        source_profile_digest: str,
    ) -> None:
        self.config = config
        self.roles = dict(roles)
        if not self.roles or len(self.roles) != len(roles):
            raise ValueError("CAR-M Tissue roles must be non-empty and unique")
        if not source_profile_digest.strip():
            raise ValueError("CAR-M Tissue model requires a source profile digest")
        self.source_profile_digest = source_profile_digest

    @property
    def model_version(self) -> str:
        return (
            f"{self.config.model_version}+"
            f"{digest_payload((self.config, tuple(sorted(self.roles.items())), self.source_profile_digest))[:12]}"
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
            raise ValueError(
                "CAR-M tissue model does not support feedback constraints; "
                "use ConstraintAwareTissueModel for feedback experiments"
            )
        cells, actions, previous_nodes = self._validated_inputs(
            cell_states,
            cell_actions,
            initial_environments=initial_environments,
            previous_state=previous_state,
            edges=edges,
            logical_time=logical_time,
        )
        incoming: dict[str, list[str]] = {cell_id: [] for cell_id in cells}
        for source, target in edges:
            incoming[target].append(source)

        next_nodes: list[TissueNodeState] = []
        for cell_id in sorted(cells):
            previous = previous_nodes[cell_id]
            action = actions[cell_id]
            role = self.roles[cell_id]
            sources = incoming[cell_id]
            resource = _clamp(
                previous.resource_level
                + self.config.resource_recovery * (1.0 - previous.resource_level)
                - self.config.resource_consumption_gain
                * action.resource_consumption
            )
            incoming_secretion = (
                fmean(actions[source].secretion for source in sources)
                if sources
                else 0.0
            )
            signal = _clamp(
                self.config.signal_retention * previous.signal
                + self.config.secretion_coupling * incoming_secretion
            )
            if role is CellRole.TUMOR:
                weighted_effects = []
                for source in sources:
                    source_role = self.roles[source]
                    if source_role in _MACROPHAGE_ROLES:
                        gain = self.config.macrophage_effector_gain
                    elif source_role is CellRole.CD8_T_CELL:
                        gain = self.config.cd8_effector_gain
                    else:
                        continue
                    weighted_effects.append(gain * actions[source].repair_effort)
                effector_pressure = fmean(weighted_effects) if weighted_effects else 0.0
                stress = _clamp(
                    self.config.stress_retention * previous.stress
                    + effector_pressure
                    + self.config.resource_consumption_gain * (1.0 - resource)
                )
            else:
                tumor_suppression = (
                    fmean(
                        actions[source].secretion
                        for source in sources
                        if self.roles[source] is CellRole.TUMOR
                    )
                    if any(self.roles[source] is CellRole.TUMOR for source in sources)
                    else 0.0
                )
                stress = _clamp(
                    self.config.stress_retention * previous.stress
                    + self.config.tumor_suppression_gain * tumor_suppression
                    + self.config.resource_consumption_gain * (1.0 - resource)
                    - self.config.immune_stress_recovery * action.repair_effort
                )
            next_nodes.append(
                TissueNodeState(
                    cell_id=cell_id,
                    stress=stress,
                    resource_level=resource,
                    signal=signal,
                )
            )

        nodes = tuple(next_nodes)
        immune_ids = tuple(
            cell_id for cell_id, role in self.roles.items() if role in _IMMUNE_ROLES
        )
        tumor_ids = tuple(
            cell_id for cell_id, role in self.roles.items() if role is CellRole.TUMOR
        )
        immune_viability = fmean(cells[cell_id].viability for cell_id in immune_ids)
        tumor_viability = fmean(cells[cell_id].viability for cell_id in tumor_ids)
        immune_activation = fmean(cells[cell_id].activation for cell_id in immune_ids)
        immune_dead_fraction = fmean(
            float(cells[cell_id].phase is CellPhase.DEAD) for cell_id in immune_ids
        )
        immune_effort = fmean(actions[cell_id].repair_effort for cell_id in immune_ids)
        tissue_damage = _clamp(
            self.config.tumor_burden_weight * tumor_viability
            + (1.0 - self.config.tumor_burden_weight)
            * (1.0 - immune_viability)
        )
        edge_density = (
            len(edges) / (len(cells) * (len(cells) - 1))
            if len(cells) > 1
            else 0.0
        )
        source = {
            "cell_states": cell_states,
            "cell_actions": cell_actions,
            "initial_environments": initial_environments,
            "previous_state": previous_state,
            "edges": edges,
            "roles": tuple(sorted(self.roles.items())),
            "config": self.config,
            "source_profile_digest": self.source_profile_digest,
            "tumor_burden_proxy": tissue_damage,
        }
        return TissueState(
            metadata=_metadata(
                logical_time=logical_time,
                model_version=self.model_version,
                source=source,
            ),
            cell_count=len(cells),
            nodes=nodes,
            edges=edges,
            edge_density=edge_density,
            mean_activation=immune_activation,
            mean_viability=immune_viability,
            mean_resource=fmean(node.resource_level for node in nodes),
            mean_signal=fmean(node.signal for node in nodes),
            dead_fraction=immune_dead_fraction,
            repair_activity=immune_effort,
            coordinated_signal=fmean(node.signal for node in nodes),
            tissue_damage=tissue_damage,
        )

    def _validated_inputs(
        self,
        cell_states: tuple[CellState, ...],
        cell_actions: tuple[CellAction, ...],
        *,
        initial_environments: tuple[LocalEnvironment, ...] | None,
        previous_state: TissueState | None,
        edges: tuple[tuple[str, str], ...],
        logical_time: int,
    ) -> tuple[
        dict[str, CellState],
        dict[str, CellAction],
        dict[str, TissueNodeState],
    ]:
        if not cell_states or len(cell_states) != len(cell_actions):
            raise ValueError("CAR-M Tissue model requires aligned L2 states and actions")
        cell_ids = tuple(state.cell_id for state in cell_states)
        action_ids = tuple(action.cell_id for action in cell_actions)
        if cell_ids != tuple(sorted(cell_ids)) or cell_ids != action_ids:
            raise ValueError("CAR-M Tissue Cell ids must be aligned and sorted")
        if set(cell_ids) != set(self.roles):
            raise ValueError("CAR-M Tissue roles must cover every Cell")
        if edges != tuple(sorted(edges)) or len(edges) != len(set(edges)):
            raise ValueError("CAR-M Tissue edges must be unique and sorted")
        cell_set = set(cell_ids)
        if any(
            source == target or source not in cell_set or target not in cell_set
            for source, target in edges
        ):
            raise ValueError("CAR-M Tissue edges must connect known distinct Cells")
        if previous_state is None:
            if initial_environments is None:
                raise ValueError("initial CAR-M Tissue step requires environments")
            environment_ids = tuple(item.cell_id for item in initial_environments)
            if environment_ids != cell_ids:
                raise ValueError("initial CAR-M Tissue environments must align")
            previous_nodes = {
                item.cell_id: TissueNodeState(
                    cell_id=item.cell_id,
                    stress=item.stress,
                    resource_level=item.resource_level,
                    signal=item.incoming_signal,
                )
                for item in initial_environments
            }
        else:
            if initial_environments is not None:
                raise ValueError("resumed CAR-M Tissue step cannot reset environments")
            if not isinstance(previous_state, TissueState):
                raise TypeError("previous CAR-M Tissue state must be a TissueState")
            if previous_state.metadata.logical_time >= logical_time:
                raise ValueError("previous CAR-M Tissue state must precede this step")
            previous_nodes = {node.cell_id: node for node in previous_state.nodes}
            if set(previous_nodes) != cell_set:
                raise ValueError("previous CAR-M Tissue nodes must align")
        return (
            {state.cell_id: state for state in cell_states},
            {action.cell_id: action for action in cell_actions},
            previous_nodes,
        )
