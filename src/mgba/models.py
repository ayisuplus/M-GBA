from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class MessageKind(StrEnum):
    SIGNAL = "signal"
    ALERT = "alert"
    RESOURCE = "resource"


class TopologyOperation(StrEnum):
    CREATE = "create"
    DESTROY = "destroy"


@dataclass(frozen=True, slots=True)
class Genome:
    version: str
    traits: dict[str, float]

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("genome version must not be empty")
        if not self.traits:
            raise ValueError("genome traits must not be empty")
        for name, value in self.traits.items():
            if not name.strip() or not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError("genome traits must be named finite values in [0, 1]")


@dataclass(frozen=True, slots=True)
class SemanticMessage:
    message_id: str
    source: str
    target: str
    tick: int
    kind: MessageKind
    priority: int
    payload: dict[str, Any]
    ttl: int = 1

    def __post_init__(self) -> None:
        if not self.message_id or not self.source or not self.target:
            raise ValueError("message id, source, and target are required")
        if self.tick < 0 or not 0 <= self.priority <= 100 or self.ttl < 1:
            raise ValueError("invalid tick, priority, or ttl")
        json.dumps(self.payload, ensure_ascii=False, allow_nan=False)

    def encoded_size(self) -> int:
        return len(
            json.dumps(asdict(self), ensure_ascii=False, sort_keys=True).encode("utf-8")
        )


@dataclass(frozen=True, slots=True)
class TopologyProposal:
    actor: str
    peer: str
    operation: TopologyOperation
    reason: str
    tick: int

    def __post_init__(self) -> None:
        if not self.actor or not self.peer or not self.reason.strip() or self.tick < 0:
            raise ValueError("invalid topology proposal")
