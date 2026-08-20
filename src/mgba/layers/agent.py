"""Explicit per-cell agent unit for the five-layer main chain.

A CellAgent is the L2 expression of one cell: it owns the cell identity,
genome, and current L0/L1/L2 states, and acts each tick through its decision
policy (the existing CellModel protocol). L0 and L1 remain layer-level
services advanced by the runner; only the L2 perceive-decide-act step is the
agent's own agency. L3/L4 state is tissue-level and never lives on an agent.
"""

from __future__ import annotations

from ..models import Genome
from .contracts import (
    CellAction,
    CellModel,
    CellState,
    LocalEnvironment,
    MolecularState,
    TranscriptState,
)


class CellAgent:
    """One cell in the main chain: identity, genome, L0/L1/L2 state, policy."""

    __slots__ = ("cell_id", "genome", "policy", "l0", "l1", "l2")

    cell_id: str
    genome: Genome
    policy: CellModel
    l0: TranscriptState | None
    l1: MolecularState | None
    l2: CellState | None

    def __init__(self, cell_id: str, genome: Genome, policy: CellModel) -> None:
        if not isinstance(cell_id, str) or not cell_id.strip():
            raise ValueError("cell_id must be a non-empty string")
        if not isinstance(genome, Genome):
            raise TypeError("genome must be a Genome")
        if not hasattr(policy, "step") or not hasattr(policy, "model_version"):
            raise TypeError("policy must satisfy the CellModel protocol")
        self.cell_id = cell_id
        self.genome = genome
        self.policy = policy
        self.l0 = None
        self.l1 = None
        self.l2 = None

    def _require_identity(self, state_cell_id: str, layer: str) -> None:
        if state_cell_id != self.cell_id:
            raise ValueError(
                f"{layer} state cell id {state_cell_id!r} does not match agent "
                f"{self.cell_id!r}"
            )

    def advance_l0(self, state: TranscriptState) -> None:
        if not isinstance(state, TranscriptState):
            raise TypeError("state must be a TranscriptState")
        self._require_identity(state.cell_id, "L0")
        self.l0 = state

    def advance_l1(self, state: MolecularState) -> None:
        if not isinstance(state, MolecularState):
            raise TypeError("state must be a MolecularState")
        self._require_identity(state.cell_id, "L1")
        self.l1 = state

    def advance_l2(self, state: CellState) -> None:
        """Seed L2 state; only used for checkpoint restore.

        At runtime the agent's l2 is written exclusively by ``decide``.
        """
        if not isinstance(state, CellState):
            raise TypeError("state must be a CellState")
        self._require_identity(state.cell_id, "L2")
        self.l2 = state

    def decide(
        self,
        molecular: MolecularState,
        environment: LocalEnvironment,
        *,
        logical_time: int,
    ) -> tuple[CellState, CellAction]:
        self._require_identity(molecular.cell_id, "L1")
        self._require_identity(environment.cell_id, "L3 environment")
        state, action = self.policy.step(
            molecular,
            environment,
            previous_state=self.l2,
            logical_time=logical_time,
        )
        if not isinstance(state, CellState):
            raise TypeError("policy must return a CellState")
        if not isinstance(action, CellAction):
            raise TypeError("policy must return a CellAction")
        self._require_identity(state.cell_id, "policy L2 output")
        self._require_identity(action.cell_id, "policy action output")
        self.l2 = state
        return state, action
