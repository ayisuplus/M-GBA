from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import SemanticMessage, TopologyOperation, TopologyProposal


class TopologyViolation(ValueError):
    """Raised when a topology mutation violates an explicit system invariant."""


@dataclass(slots=True)
class DirectedTopology:
    nodes: set[str]
    max_out_degree: int
    _edges: set[tuple[str, str]] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.nodes or any(not node for node in self.nodes):
            raise TopologyViolation("topology requires named nodes")
        if self.max_out_degree < 1:
            raise TopologyViolation("max_out_degree must be positive")

    @classmethod
    def from_edges(
        cls,
        nodes: set[str],
        edges: list[tuple[str, str]],
        max_out_degree: int,
    ) -> DirectedTopology:
        topology = cls(nodes=set(nodes), max_out_degree=max_out_degree)
        for source, target in edges:
            topology.connect(source, target)
        return topology

    def connect(self, source: str, target: str) -> bool:
        self._require_nodes(source, target)
        if source == target:
            raise TopologyViolation("self edges are not allowed")
        edge = (source, target)
        if edge in self._edges:
            return False
        if len(self.outgoing(source)) >= self.max_out_degree:
            raise TopologyViolation(f"{source} exceeds max_out_degree")
        self._edges.add(edge)
        return True

    def disconnect(self, source: str, target: str) -> bool:
        self._require_nodes(source, target)
        edge = (source, target)
        if edge not in self._edges:
            return False
        self._edges.remove(edge)
        return True

    def has_edge(self, source: str, target: str) -> bool:
        return (source, target) in self._edges

    def outgoing(self, source: str) -> tuple[str, ...]:
        if source not in self.nodes:
            raise TopologyViolation(f"unknown node: {source}")
        return tuple(sorted(target for origin, target in self._edges if origin == source))

    def snapshot(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(self._edges))

    def _require_nodes(self, *nodes: str) -> None:
        unknown = set(nodes) - self.nodes
        if unknown:
            raise TopologyViolation(f"unknown nodes: {sorted(unknown)}")


class StenEngine:
    """Routes semantic messages and applies guarded, agent-owned edge mutations."""

    def __init__(self, topology: DirectedTopology, max_message_bytes: int = 2048):
        if max_message_bytes < 1:
            raise ValueError("max_message_bytes must be positive")
        self.topology = topology
        self.max_message_bytes = max_message_bytes
        self._mailboxes: dict[str, list[SemanticMessage]] = defaultdict(list)
        self.events: list[dict[str, Any]] = []

    def route(self, message: SemanticMessage, requested_by: str) -> None:
        if requested_by != message.source:
            raise TopologyViolation("an agent cannot send on behalf of another agent")
        if not self.topology.has_edge(message.source, message.target):
            raise TopologyViolation("message route is not present in the active topology")
        if message.encoded_size() > self.max_message_bytes:
            raise ValueError("message exceeds max_message_bytes")
        self._mailboxes[message.target].append(message)
        self.events.append({"event": "message_routed", **asdict(message)})

    def drain(self, agent_id: str) -> tuple[SemanticMessage, ...]:
        messages = self._mailboxes.pop(agent_id, [])
        messages.sort(key=lambda item: (-item.priority, item.message_id))
        return tuple(messages)

    def apply(self, proposal: TopologyProposal, requested_by: str) -> bool:
        if requested_by != proposal.actor:
            raise TopologyViolation("an agent cannot mutate another agent's outgoing edges")
        if proposal.operation is TopologyOperation.CREATE:
            changed = self.topology.connect(proposal.actor, proposal.peer)
        else:
            changed = self.topology.disconnect(proposal.actor, proposal.peer)
        self.events.append(
            {"event": "topology_changed" if changed else "topology_unchanged", **asdict(proposal)}
        )
        return changed
