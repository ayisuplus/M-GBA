"""Empirical L0 response table: distilled pass-gated predictions (ADR-0038).

Pure stdlib. The table is the only training product the runtime chain may see:
plain six-node float vectors per public perturbation unit, gated on the
ADR-0037 evaluation verdict and triple digest cross-identity. The model side
(`mgba.layers.l0_empirical`) loads this table and never touches torch, numpy,
or the weights file.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from .experiment import digest_payload
from .l0_training_evaluation import EVALUATION_SCHEMA_VERSION, PREDICTIONS_SCHEMA_VERSION
from .layers.l0 import ABSTRACT_GENE_NAMES

TABLE_SCHEMA_VERSION = "mgba-l0-response-table-0.1"

SCIENTIFIC_BOUNDARY = (
    "Distilled six-node response vectors from the ADR-0037 verified predictor "
    "(Norman 2019 K562 CRISPRa). Lookup data for an optional L0 variant; not a "
    "biological truth table, not validated beyond the frozen pass rule, and "
    "not an efficacy claim."
)


def _required_text(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _sha256_text(value: Any, *, name: str) -> str:
    result = _required_text(value, name=name).lower()
    if (
        len(result) != 64
        or result != value.strip()
        or any(char not in "0123456789abcdef" for char in result)
    ):
        raise ValueError(f"{name} must be 64 lowercase hexadecimal characters")
    return result


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_object(path: Path, *, name: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {name}: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError(f"{name} must be a JSON object")
    return raw


def _vector6(value: Any, *, name: str) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != len(ABSTRACT_GENE_NAMES):
        raise ValueError(f"{name} must be a six-element list")
    result = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise TypeError(f"{name} must contain finite numbers")
        if not math.isfinite(float(item)):
            raise ValueError(f"{name} must contain finite numbers")
        result.append(float(item))
    return tuple(result)


def build_response_table(
    predictions_path: str | Path, evaluation_path: str | Path
) -> dict[str, Any]:
    """Distill MLP predictions into the response table, gated on the verdict."""
    pred_path = Path(predictions_path)
    eval_path = Path(evaluation_path)
    predictions = _read_json_object(pred_path, name="response predictions")
    evaluation = _read_json_object(eval_path, name="training evaluation")

    if predictions.get("schema_version") != PREDICTIONS_SCHEMA_VERSION:
        raise ValueError("unexpected predictions schema")
    if evaluation.get("schema_version") != EVALUATION_SCHEMA_VERSION:
        raise ValueError("unexpected evaluation schema")
    pass_rule = evaluation.get("pass_rule")
    if not isinstance(pass_rule, dict):
        raise ValueError("evaluation lacks a pass_rule block")
    if pass_rule.get("verdict") != "passed":
        raise ValueError("response table requires a passed ADR-0037 verdict")
    source = evaluation.get("source")
    if not isinstance(source, dict):
        raise ValueError("evaluation lacks a source block")
    if source.get("predictions_sha256") != _file_sha256(pred_path):
        raise ValueError("evaluation does not cover this predictions file")
    if source.get("profile_sha256") != predictions.get("profile_sha256"):
        raise ValueError("predictions/evaluation profile identity mismatch")

    units_raw = predictions.get("units")
    if not isinstance(units_raw, list) or not units_raw:
        raise ValueError("predictions contain no units")
    table: dict[str, tuple[float, ...]] = {}
    for index, item in enumerate(units_raw):
        if not isinstance(item, dict):
            raise ValueError(f"units[{index}] must be an object")
        unit = _required_text(item.get("unit"), name=f"units[{index}].unit")
        if unit in table:
            raise ValueError(f"duplicate unit in predictions: {unit}")
        table[unit] = _vector6(item.get("mlp_pred"), name=f"units[{index}].mlp_pred")

    content: dict[str, Any] = {
        "schema_version": TABLE_SCHEMA_VERSION,
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
        "source": {
            "predictions_sha256": _file_sha256(pred_path),
            "evaluation_sha256": _file_sha256(eval_path),
            "profile_id": _required_text(
                predictions.get("profile_id"), name="profile_id"
            ),
            "evaluation_id": _required_text(
                evaluation.get("evaluation_id"), name="evaluation_id"
            ),
            "verdict": "passed",
        },
        "node_order": list(ABSTRACT_GENE_NAMES),
        "units": {unit: list(vector) for unit, vector in sorted(table.items())},
    }
    content["table_id"] = f"l0-response-table-{digest_payload(content)[:16]}"
    return content


def save_response_table(table: Mapping[str, Any], output_path: str | Path) -> Path:
    """Write-once save; existing output is never overwritten."""
    output = Path(output_path)
    if output.exists():
        raise ValueError(f"refusing to overwrite existing response table: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(table), indent=2), encoding="utf-8")
    return output


@dataclass(frozen=True, slots=True)
class EmpiricalResponseTable:
    """Runtime view of the response table for the empirical L0 variant."""

    table_id: str
    source: dict[str, Any]
    vectors: tuple[tuple[str, tuple[float, ...]], ...]
    table_digest: str
    _index: dict[str, tuple[float, ...]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        names = [unit for unit, _ in self.vectors]
        if len(names) != len(set(names)):
            raise ValueError("response table units must be unique")
        if tuple(sorted(names)) != tuple(names):
            raise ValueError("response table units must be sorted")
        object.__setattr__(self, "_index", dict(self.vectors))

    @property
    def units(self) -> frozenset[str]:
        return frozenset(unit for unit, _ in self.vectors)

    def vector(self, unit: str) -> tuple[float, ...]:
        try:
            return self._index[unit]
        except KeyError:
            raise KeyError(f"unit not in the empirical response table: {unit}") from None

    def as_node_dict(self, unit: str) -> dict[str, float]:
        return dict(zip(ABSTRACT_GENE_NAMES, self.vector(unit), strict=True))


def load_response_table(path: str | Path, *, expected_sha256: str) -> EmpiricalResponseTable:
    table_path = Path(path)
    digest = _file_sha256(table_path)
    if digest != _sha256_text(expected_sha256, name="expected table sha256"):
        raise ValueError("response table SHA-256 disagrees with the layer config")
    raw = _read_json_object(table_path, name="empirical response table")
    if raw.get("schema_version") != TABLE_SCHEMA_VERSION:
        raise ValueError("unsupported response table schema")
    for key in ("table_id", "scientific_boundary", "source", "node_order", "units"):
        if key not in raw:
            raise ValueError(f"response table lacks {key}")
    if list(raw["node_order"]) != list(ABSTRACT_GENE_NAMES):
        raise ValueError("response table node order disagrees with the frozen order")
    source = raw["source"]
    if not isinstance(source, dict) or source.get("verdict") != "passed":
        raise ValueError("response table source must carry a passed verdict")
    units_raw = raw["units"]
    if not isinstance(units_raw, dict) or not units_raw:
        raise ValueError("response table units must be a non-empty object")
    vectors = tuple(
        (
            _required_text(unit, name="table unit"),
            _vector6(vector, name=f"table[{unit}]"),
        )
        for unit, vector in sorted(units_raw.items())
    )
    table_id = _required_text(raw["table_id"], name="table_id")
    expected_id = f"l0-response-table-{digest_payload({key: value for key, value in raw.items() if key != 'table_id'})[:16]}"
    if table_id != expected_id:
        raise ValueError("response table id does not match its content")
    return EmpiricalResponseTable(
        table_id=table_id,
        source=dict(source),
        vectors=vectors,
        table_digest=digest,
    )
