from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any


REGISTRY_SCHEMA_VERSION = "mgba-data-registry-0.1"
ALLOWED_KINDS = (
    "aggregated_profile",
    "synthetic",
    "external_raw",
    "external_profile",
    "external_planned",
)
ALLOWED_STATUSES = ("materialized", "generated", "planned")
_HASHED_STATUSES = ("materialized", "generated")


def _require_text(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be empty")


def _require_sha256(value: str, name: str) -> None:
    if (
        len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"{name} must be 64 lowercase hexadecimal characters")


@dataclass(frozen=True, slots=True)
class DatasetProvenance:
    source: str
    date: str
    license: str
    deidentified: bool
    proxy_notice: str

    def __post_init__(self) -> None:
        _require_text(self.source, "provenance source")
        _require_text(self.date, "provenance date")
        _require_text(self.license, "provenance license")
        if not isinstance(self.deidentified, bool):
            raise TypeError("provenance deidentified must be a bool")
        if not isinstance(self.proxy_notice, str):
            raise TypeError("provenance proxy_notice must be a string")


@dataclass(frozen=True, slots=True)
class DatasetEntry:
    dataset_id: str
    kind: str
    status: str
    path: str
    sha256: str | None
    provenance: DatasetProvenance
    notes: str

    def __post_init__(self) -> None:
        _require_text(self.dataset_id, "dataset_id")
        _require_text(self.path, "dataset path")
        if self.kind not in ALLOWED_KINDS:
            raise ValueError(f"unknown dataset kind: {self.kind}")
        if self.status not in ALLOWED_STATUSES:
            raise ValueError(f"unknown dataset status: {self.status}")
        if self.status in _HASHED_STATUSES:
            if not isinstance(self.sha256, str):
                raise ValueError(f"{self.status} datasets must register a sha256")
            _require_sha256(self.sha256, "dataset sha256")
        elif self.sha256 is not None:
            raise ValueError("planned datasets must not register a sha256")
        if not isinstance(self.provenance, DatasetProvenance):
            raise TypeError("dataset provenance must be a DatasetProvenance")
        if not isinstance(self.notes, str):
            raise TypeError("dataset notes must be a string")


@dataclass(frozen=True, slots=True)
class DatasetVerdict:
    dataset_id: str
    ok: bool
    detail: str


def _parse_entry(raw: Any) -> DatasetEntry:
    if not isinstance(raw, dict):
        raise ValueError("dataset entries must be objects")
    provenance = raw.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("dataset provenance must be an object")
    return DatasetEntry(
        dataset_id=str(raw["dataset_id"]),
        kind=str(raw["kind"]),
        status=str(raw["status"]),
        path=str(raw["path"]),
        sha256=(None if raw.get("sha256") is None else str(raw["sha256"])),
        provenance=DatasetProvenance(
            source=str(provenance["source"]),
            date=str(provenance["date"]),
            license=str(provenance["license"]),
            deidentified=provenance["deidentified"],
            proxy_notice=str(provenance.get("proxy_notice", "")),
        ),
        notes=str(raw.get("notes", "")),
    )


def load_data_registry(path: str | Path) -> tuple[DatasetEntry, ...]:
    source = Path(path)
    try:
        raw: Any = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("registry must be a JSON object")
        if raw.get("schema_version") != REGISTRY_SCHEMA_VERSION:
            raise ValueError("unsupported data registry schema version")
        datasets = raw["datasets"]
        if not isinstance(datasets, list):
            raise ValueError("registry datasets must be a list")
        entries = tuple(_parse_entry(item) for item in datasets)
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid data registry: {error}") from error
    ids = [entry.dataset_id for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("invalid data registry: dataset_id values must be unique")
    return entries


def validate_data_registry(
    entries: tuple[DatasetEntry, ...], *, data_root: str | Path
) -> tuple[DatasetVerdict, ...]:
    """Check registered artifacts without raising; callers decide when to fail."""
    root = Path(data_root)
    verdicts: list[DatasetVerdict] = []
    for entry in entries:
        if entry.status == "planned":
            verdicts.append(
                DatasetVerdict(
                    dataset_id=entry.dataset_id,
                    ok=True,
                    detail="planned; no artifact required",
                )
            )
            continue
        target = root / entry.path
        if not target.is_file():
            verdicts.append(
                DatasetVerdict(
                    dataset_id=entry.dataset_id,
                    ok=False,
                    detail=f"registered file missing: {entry.path}",
                )
            )
            continue
        actual = sha256(target.read_bytes()).hexdigest()
        if actual != entry.sha256:
            verdicts.append(
                DatasetVerdict(
                    dataset_id=entry.dataset_id,
                    ok=False,
                    detail=(
                        f"sha256 mismatch for {entry.path}: "
                        f"registered {entry.sha256} actual {actual}"
                    ),
                )
            )
            continue
        verdicts.append(
            DatasetVerdict(
                dataset_id=entry.dataset_id,
                ok=True,
                detail="sha256 verified",
            )
        )
    return tuple(verdicts)
