from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any


REGISTRY_SCHEMA_VERSION = "mgba-data-registry-0.2"
ALLOWED_KINDS = (
    "aggregated_profile",
    "synthetic",
    "external_raw",
    "external_profile",
    "external_planned",
)
ALLOWED_STATUSES = ("materialized", "generated", "planned")
_HASHED_STATUSES = ("materialized", "generated")
# ``local-only`` marks registered bytes whose licence forbids redistribution:
# the sha256 is still checked wherever the file exists, but its absence (a
# clean clone, CI) is reported instead of failing the gate.
ALLOWED_DISTRIBUTIONS = ("repository", "local-only")
# Machine-readable licence vocabulary: SPDX identifiers where one exists,
# ``LicenseRef-*`` for terms that have none. The prose ``license`` field keeps
# the human wording; only these identifiers are audited.
ALLOWED_LICENSE_IDS = (
    "CC-BY-1.0",
    "CC-BY-4.0",
    "LicenseRef-GEO-Public",
    "LicenseRef-Geneformer",
    "LicenseRef-Legacy-CARM",
    "LicenseRef-MGBA-Internal",
    "LicenseRef-MSigDB",
    "LicenseRef-Per-Resource",
    "LicenseRef-TCGA-Public",
)
# ``dataset:`` names another registry entry, ``repo:`` a repository path;
# ``doi:``/``geo:``/``url:`` point outside the repository.
SOURCE_REF_SCHEMES = ("dataset", "doi", "geo", "repo", "url")
_EXTERNAL_SOURCE_SCHEMES = ("dataset", "doi", "geo", "url")
_KINDS_REQUIRING_EXTERNAL_SOURCE = (
    "aggregated_profile",
    "external_raw",
    "external_profile",
)


def _require_text(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be empty")


def _require_sha256(value: str, name: str) -> None:
    if (
        len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"{name} must be 64 lowercase hexadecimal characters")


def _require_unique_strings(values: tuple[str, ...], name: str) -> None:
    if not isinstance(values, tuple) or not values:
        raise ValueError(f"{name} must be a non-empty tuple")
    if any(not isinstance(value, str) for value in values):
        raise TypeError(f"{name} entries must be strings")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} entries must be unique")


def _split_source_ref(ref: str) -> tuple[str, str]:
    scheme, separator, value = ref.partition(":")
    if not separator or scheme not in SOURCE_REF_SCHEMES:
        raise ValueError(f"unknown source ref scheme: {ref}")
    if not value or value != value.strip():
        raise ValueError(f"source ref value must be non-empty and trimmed: {ref}")
    if scheme == "doi" and not value.startswith("10."):
        raise ValueError(f"doi source ref must start with 10.: {ref}")
    if scheme == "geo" and not (value.startswith("GSE") and value[3:].isdigit()):
        raise ValueError(f"geo source ref must be a GSE accession: {ref}")
    if scheme == "url" and not value.startswith("https://"):
        raise ValueError(f"url source ref must use https: {ref}")
    if scheme == "repo":
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError(f"repo source ref must be a relative POSIX path: {ref}")
    return scheme, value


@dataclass(frozen=True, slots=True)
class DatasetProvenance:
    source: str
    date: str
    license: str
    license_ids: tuple[str, ...]
    source_refs: tuple[str, ...]
    deidentified: bool
    proxy_notice: str

    def __post_init__(self) -> None:
        _require_text(self.source, "provenance source")
        _require_text(self.date, "provenance date")
        _require_text(self.license, "provenance license")
        _require_unique_strings(self.license_ids, "provenance license_ids")
        unknown = [item for item in self.license_ids if item not in ALLOWED_LICENSE_IDS]
        if unknown:
            raise ValueError(f"unknown license ids: {', '.join(unknown)}")
        _require_unique_strings(self.source_refs, "provenance source_refs")
        for ref in self.source_refs:
            _split_source_ref(ref)
        if not isinstance(self.deidentified, bool):
            raise TypeError("provenance deidentified must be a bool")
        if not isinstance(self.proxy_notice, str):
            raise TypeError("provenance proxy_notice must be a string")

    def refs(self, scheme: str) -> tuple[str, ...]:
        return tuple(
            value
            for ref_scheme, value in map(_split_source_ref, self.source_refs)
            if ref_scheme == scheme
        )


@dataclass(frozen=True, slots=True)
class DatasetEntry:
    dataset_id: str
    kind: str
    status: str
    path: str
    sha256: str | None
    provenance: DatasetProvenance
    notes: str
    distribution: str = "repository"

    def __post_init__(self) -> None:
        _require_text(self.dataset_id, "dataset_id")
        _require_text(self.path, "dataset path")
        if self.kind not in ALLOWED_KINDS:
            raise ValueError(f"unknown dataset kind: {self.kind}")
        if self.status not in ALLOWED_STATUSES:
            raise ValueError(f"unknown dataset status: {self.status}")
        if self.distribution not in ALLOWED_DISTRIBUTIONS:
            raise ValueError(f"unknown dataset distribution: {self.distribution}")
        if self.distribution == "local-only" and self.status not in _HASHED_STATUSES:
            raise ValueError("only materialized or generated datasets can be local-only")
        if self.status in _HASHED_STATUSES:
            if not isinstance(self.sha256, str):
                raise ValueError(f"{self.status} datasets must register a sha256")
            _require_sha256(self.sha256, "dataset sha256")
        elif self.sha256 is not None:
            raise ValueError("planned datasets must not register a sha256")
        if not isinstance(self.provenance, DatasetProvenance):
            raise TypeError("dataset provenance must be a DatasetProvenance")
        if self.kind in _KINDS_REQUIRING_EXTERNAL_SOURCE and not any(
            self.provenance.refs(scheme) for scheme in _EXTERNAL_SOURCE_SCHEMES
        ):
            raise ValueError(
                f"{self.kind} datasets must cite a dataset, doi, geo or url source ref"
            )
        if self.dataset_id in self.provenance.refs("dataset"):
            raise ValueError("dataset source refs must not cite the entry itself")
        if not isinstance(self.notes, str):
            raise TypeError("dataset notes must be a string")


@dataclass(frozen=True, slots=True)
class DatasetVerdict:
    dataset_id: str
    ok: bool
    detail: str


def _string_tuple(raw: Any, name: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"{name} must be a list")
    return tuple(raw)


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
            license_ids=_string_tuple(provenance["license_ids"], "license_ids"),
            source_refs=_string_tuple(provenance["source_refs"], "source_refs"),
            deidentified=provenance["deidentified"],
            proxy_notice=str(provenance.get("proxy_notice", "")),
        ),
        notes=str(raw.get("notes", "")),
        distribution=str(raw.get("distribution", "repository")),
    )


def _check_lineage(entries: tuple[DatasetEntry, ...]) -> None:
    """Every ``dataset:`` ref must resolve, and licences must propagate downstream."""
    by_id = {entry.dataset_id: entry for entry in entries}
    for entry in entries:
        own = set(entry.provenance.license_ids)
        for upstream_id in entry.provenance.refs("dataset"):
            upstream = by_id.get(upstream_id)
            if upstream is None:
                raise ValueError(
                    f"{entry.dataset_id} cites unregistered dataset {upstream_id}"
                )
            missing = sorted(set(upstream.provenance.license_ids) - own)
            if missing:
                raise ValueError(
                    f"{entry.dataset_id} drops upstream license ids from "
                    f"{upstream_id}: {', '.join(missing)}"
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
    try:
        _check_lineage(entries)
    except ValueError as error:
        raise ValueError(f"invalid data registry: {error}") from error
    return entries


def validate_data_registry(
    entries: tuple[DatasetEntry, ...], *, data_root: str | Path
) -> tuple[DatasetVerdict, ...]:
    """Check registered artifacts without raising; callers decide when to fail."""
    root = Path(data_root)
    verdicts: list[DatasetVerdict] = []
    for entry in entries:
        missing_refs = [
            ref for ref in entry.provenance.refs("repo") if not (root / ref).exists()
        ]
        if missing_refs:
            verdicts.append(
                DatasetVerdict(
                    dataset_id=entry.dataset_id,
                    ok=False,
                    detail=f"repo source ref missing: {', '.join(missing_refs)}",
                )
            )
            continue
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
        if not target.is_file() and entry.distribution == "local-only":
            verdicts.append(
                DatasetVerdict(
                    dataset_id=entry.dataset_id,
                    ok=True,
                    detail=(
                        "local-only; not distributed with the repository, "
                        f"sha256 not checked here: {entry.path}"
                    ),
                )
            )
            continue
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
