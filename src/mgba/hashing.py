"""Canonical JSON serialization and sha256 digest primitives.

These helpers are dependency-free so that both the layer implementations
(``mgba.layers.*``) and the experiment orchestration side
(``mgba.experiment``) can share them without forming an import cycle.
Function bodies are byte-identical to the implementations that lived in
``mgba.experiment`` before this module was extracted; every digest,
checkpoint, and frozen baseline is unchanged.
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

__all__ = ["canonical_json", "digest_payload", "jsonable"]


def jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(jsonable(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        jsonable(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def digest_payload(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()
