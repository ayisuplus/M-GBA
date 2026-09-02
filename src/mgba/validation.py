"""Shared payload validation helpers for data/artifact boundary modules.

These validators previously existed as per-module private copies that had
drifted apart (uppercase digest normalization vs rejection, untrimmed text
acceptance vs rejection, TypeError vs ValueError for non-numeric input).
This module is the single implementation; the canonical semantics are the
fail-closed variants:

* text must be a pre-trimmed non-empty string (no silent normalization);
* digests must be exactly 64 lowercase hexadecimal characters (uppercase
  is rejected, not normalized);
* numbers must be real and finite (``bool`` is rejected).

Only invalid-input error paths changed relative to the old copies; every
previously valid payload is accepted identically.  Like ``hashing.py`` this
module is dependency-free so any layer or boundary module may import it
without creating an import cycle.
"""

from __future__ import annotations

import math
from hashlib import sha256
from pathlib import Path
from typing import Any

__all__ = ["file_sha256", "finite", "required_text", "sha256_text"]


def required_text(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a non-empty trimmed string")
    return value


def sha256_text(value: Any, *, name: str) -> str:
    text = required_text(value, name=name)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{name} must be 64 lowercase hexadecimal characters (SHA-256 digest)")
    return text


def finite(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
