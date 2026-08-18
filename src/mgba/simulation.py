from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Genome, MessageKind, SemanticMessage
from .sten import DirectedTopology, StenEngine


@dataclass(frozen=True, slots=True)
class AgentSpec:
    agent_id: str
    role: str
    genome: Genome


@dataclass(frozen=True, slots=True)
class Scenario:
    seed: int
    ticks: int
    max_out_degree: int
    max_message_bytes: int
    agents: tuple[AgentSpec, ...]
    edges: tuple[tuple[str, str], ...]


class RuleBasedAgent:
    """Deterministic baseline kept behind the same decision boundary as a future LLM policy."""

    def __init__(self, spec: AgentSpec):
        self.spec = spec

    def decide(
        self,
        tick: int,
        neighbors: tuple[str, ...],
        inbox: tuple[SemanticMessage, ...],
    ) -> tuple[SemanticMessage, ...]:
        intensity = self.spec.genome.traits.get("signal_rate", 0.0)
        if intensity == 0.0:
            return ()
        return tuple(
            SemanticMessage(
                message_id=f"{self.spec.agent_id}:{tick}:{target}",
                source=self.spec.agent_id,
                target=target,
                tick=tick,
                kind=MessageKind.SIGNAL,
                priority=min(100, round(50 + 10 * len(inbox))),
                payload={
                    "role": self.spec.role,
                    "intensity": intensity,
                    "observed_messages": len(inbox),
                },
            )
            for target in neighbors
        )


def load_scenario(path: str | Path) -> Scenario:
    raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    agents = tuple(
        AgentSpec(
            agent_id=item["id"],
            role=item["role"],
            genome=Genome(**item["genome"]),
        )
        for item in raw["agents"]
    )
    ids = [agent.agent_id for agent in agents]
    if len(ids) != len(set(ids)):
        raise ValueError("agent ids must be unique")
    return Scenario(
        seed=int(raw["seed"]),
        ticks=int(raw["ticks"]),
        max_out_degree=int(raw["max_out_degree"]),
        max_message_bytes=int(raw["max_message_bytes"]),
        agents=agents,
        edges=tuple(tuple(edge) for edge in raw["edges"]),
    )


def run_scenario(scenario: Scenario, ticks: int | None = None) -> dict[str, Any]:
    topology = DirectedTopology.from_edges(
        nodes={agent.agent_id for agent in scenario.agents},
        edges=list(scenario.edges),
        max_out_degree=scenario.max_out_degree,
    )
    sten = StenEngine(topology, max_message_bytes=scenario.max_message_bytes)
    agents = {agent.agent_id: RuleBasedAgent(agent) for agent in scenario.agents}

    for tick in range(scenario.ticks if ticks is None else ticks):
        outbound: list[SemanticMessage] = []
        for agent_id in sorted(agents):
            outbound.extend(
                agents[agent_id].decide(
                    tick=tick,
                    neighbors=topology.outgoing(agent_id),
                    inbox=sten.drain(agent_id),
                )
            )
        for message in outbound:
            sten.route(message, requested_by=message.source)

    serialized_events = json.dumps(
        sten.events, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "seed": scenario.seed,
        "ticks": scenario.ticks if ticks is None else ticks,
        "nodes": len(topology.nodes),
        "edges": len(topology.snapshot()),
        "messages_routed": sum(event["event"] == "message_routed" for event in sten.events),
        "events": len(sten.events),
        "event_digest": hashlib.sha256(serialized_events).hexdigest(),
    }
