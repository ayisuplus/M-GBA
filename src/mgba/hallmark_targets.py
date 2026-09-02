"""ADR-0046 Hallmark structured-target builder (pure stdlib).

Consumes a frozen ``mgba-aivc-empirical-log2fc-0.1`` bundle, its Stage 1
``mgba-aivc-perturbation-profile-0.1`` profile, and the full MSigDB v2026.1
Hallmark GMT, then emits the ``mgba-hallmark-target-0.1`` supervised target:
per-unit vectors over every covered Hallmark set (unweighted mean of the
deduplicated set ∩ gene_universe log2fc, the frozen bridge's aggregation rule)
plus the frozen six-node union head (definitionally identical to
``aggregate_hallmark_bridge``).  Roles are copied verbatim from the profile —
no re-split.  A build-time gate enforces ≤1e-12 agreement between each unit's
six-node head and the profile's frozen ``six_node_vector``.

This module is deliberately outside the L0--L4 generation loop; the target is
an offline training artifact, never a runtime input.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping, Sequence

from .experiment import write_json_once
from .hashing import digest_payload
from .layers.l0 import ABSTRACT_GENE_NAMES
from .ocellus_anchors import (
    HALLMARK_BRIDGE_DIGEST,
    HALLMARK_BRIDGE_VERSION,
    REQUIRED_HALLMARK_SETS,
    aggregate_hallmark_bridge,
    sign,
    spearman,
)
from .perturbation_anchors import PROFILE_SCHEMA_VERSION, EmpiricalBundle
from .validation import file_sha256, finite, required_text, sha256_text

TARGET_SCHEMA_VERSION = "mgba-hallmark-target-0.1"
TRAIN_ROLE = "train"
HOLDOUT_ROLE = "holdout"
ROLES = (TRAIN_ROLE, HOLDOUT_ROLE)
HEAD_GATE_TOLERANCE = 1e-12

TARGET_ID_PREFIX_BY_DATASET = {
    "norman-weissman-2019-scperturb-filtered": "norman-hallmark-target",
    "replogle-2022-k562-essential-scperturb": "replogle-kd-hallmark-target",
}

SCIENTIFIC_BOUNDARY = (
    "Structured supervised target over the full covered Hallmark collection "
    "plus the frozen six-node union head, derived from de-identified aggregate "
    "Perturb-seq profiles. Offline training target only; reference-model "
    "grade. Not a biological fit, a virtual-cell claim, or an efficacy "
    "predictor; never enters the L0-L4 tick loop."
)

_PROFILE_TOP_KEYS = {
    "schema_version",
    "profile_id",
    "dataset_id",
    "scientific_boundary",
    "bridge",
    "source",
    "parameters",
    "split",
    "centroid_train_only",
    "units",
    "metrics_summary",
}
_PROFILE_UNIT_KEYS = {"unit", "cells", "role", "six_node_vector", "metrics_vs_centroid"}
_PROFILE_SPLIT_KEYS = {"salt", "train_fraction", "rule", "train_units", "holdout_units"}
_HALLMARK_SOURCE_KEYS = {"path", "sha256", "bytes", "license", "rights_verified", "version"}
_TARGET_TOP_KEYS = {
    "schema_version",
    "target_id",
    "dataset_id",
    "scientific_boundary",
    "bridge",
    "source",
    "split",
    "dims",
    "excluded_sets",
    "coverage",
    "roles",
    "centroid_train_only",
    "units",
}


def _exact_keys(raw: Mapping[str, Any], expected: set[str], *, name: str) -> None:
    keys = set(raw)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise ValueError(f"{name} keys mismatch; missing={missing} extra={extra}")


def _read_json_object(path: Path, *, name: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {name}: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError(f"{name} must be a JSON object")
    return raw


def load_all_hallmark_memberships(
    gmt_path: str | Path, *, expected_sha256: str
) -> dict[str, tuple[str, ...]]:
    """Parse the Hallmark GMT and return every set's deduplicated membership.

    Same parsing and digest pinning as
    ``perturbation_anchors.load_hallmark_memberships`` (which stays frozen on
    the bridge's ten sets); this loader keeps all sets in the collection.
    """
    path = Path(gmt_path)
    if file_sha256(path) != sha256_text(expected_sha256, name="expected gmt sha256"):
        raise ValueError("Hallmark GMT SHA-256 disagrees with the bundle identity")
    memberships: dict[str, tuple[str, ...]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            columns = line.rstrip("\n").split("\t")
            if len(columns) < 3:
                continue
            name = columns[0]
            genes = tuple(sorted({gene for gene in columns[2:] if gene}))
            if not genes:
                raise ValueError(f"Hallmark set {name} is empty")
            if name in memberships:
                raise ValueError(f"Hallmark set {name} appears twice")
            memberships[name] = genes
    if not memberships:
        raise ValueError("Hallmark GMT parsed zero sets")
    return memberships


def load_source_profile(path: str | Path) -> dict[str, Any]:
    """Strictly load the Stage 1 profile a target is derived from."""
    profile_path = Path(path)
    raw = _read_json_object(profile_path, name="perturbation profile")
    _exact_keys(raw, _PROFILE_TOP_KEYS, name="perturbation profile")
    if raw["schema_version"] != PROFILE_SCHEMA_VERSION:
        raise ValueError("unsupported profile schema")
    required_text(raw["profile_id"], name="profile_id")
    required_text(raw["dataset_id"], name="profile dataset_id")
    source = raw["source"]
    if not isinstance(source, dict):
        raise ValueError("profile source must be an object")
    if "bundle_sha256" not in source:
        raise ValueError("profile source lacks bundle_sha256")
    sha256_text(source["bundle_sha256"], name="profile source.bundle_sha256")
    split = raw["split"]
    if not isinstance(split, dict):
        raise ValueError("profile split must be an object")
    _exact_keys(split, _PROFILE_SPLIT_KEYS, name="profile split")
    required_text(split["salt"], name="profile split.salt")
    units = raw["units"]
    if not isinstance(units, list) or not units:
        raise ValueError("profile units must be a non-empty list")
    names: list[str] = []
    for index, item in enumerate(units):
        if not isinstance(item, dict):
            raise ValueError(f"profile units[{index}] must be an object")
        _exact_keys(item, _PROFILE_UNIT_KEYS, name=f"profile units[{index}]")
        names.append(required_text(item["unit"], name=f"profile units[{index}].unit"))
        role = required_text(item["role"], name=f"profile units[{index}].role")
        if role not in ROLES:
            raise ValueError(f"profile units[{index}].role must be train or holdout")
        vector = item["six_node_vector"]
        if not isinstance(vector, dict):
            raise ValueError(f"profile units[{index}].six_node_vector must be an object")
        if tuple(vector.keys()) != ABSTRACT_GENE_NAMES:
            raise ValueError(f"profile units[{index}] node order disagrees with frozen order")
        for node, value in vector.items():
            finite(value, name=f"{item['unit']}.{node}")
    if len(names) != len(set(names)):
        raise ValueError("profile unit names must be unique")
    raw["_file_sha256"] = file_sha256(profile_path)
    return raw


def build_hallmark_targets(
    bundle: EmpiricalBundle,
    profile: Mapping[str, Any],
    memberships: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    """Build the Hallmark-set + six-node-head target for one dataset.

    ``profile`` must come from ``load_source_profile`` (strict, digest
    carrying).  The build-time gate raises if any unit's six-node head
    deviates from the profile's frozen vector by more than 1e-12.
    """
    if not isinstance(bundle, EmpiricalBundle):
        raise TypeError("bundle must be an EmpiricalBundle")
    if not isinstance(memberships, Mapping) or not memberships:
        raise ValueError("memberships must be a non-empty mapping")
    if profile["dataset_id"] != bundle.dataset_id:
        raise ValueError("profile dataset_id disagrees with the bundle")
    if profile["source"]["bundle_sha256"] != bundle.bundle_digest:
        raise ValueError("profile was not built from this bundle (bundle_sha256)")
    missing_bridge = [name for name in REQUIRED_HALLMARK_SETS if name not in memberships]
    if missing_bridge:
        raise ValueError(f"memberships miss frozen bridge sets: {missing_bridge}")
    bridge_memberships = {name: memberships[name] for name in REQUIRED_HALLMARK_SETS}

    universe = set(bundle.universe_genes)
    covered_genes: dict[str, tuple[str, ...]] = {}
    excluded_sets: list[str] = []
    for set_name in sorted(memberships):
        members = memberships[set_name]
        if isinstance(members, (str, bytes)) or not isinstance(members, Sequence):
            raise TypeError(f"Hallmark set {set_name} must be a gene sequence")
        genes = tuple(sorted({required_text(gene, name=f"{set_name} gene") for gene in members}))
        if not genes:
            raise ValueError(f"Hallmark set {set_name} is empty")
        covered = tuple(gene for gene in genes if gene in universe)
        if covered:
            covered_genes[set_name] = covered
        else:
            excluded_sets.append(set_name)
    included = tuple(sorted(covered_genes))
    if not included:
        raise ValueError("no Hallmark set covers the gene universe")
    coverage = {name: len(covered_genes[name]) for name in included}
    dims = included + ABSTRACT_GENE_NAMES

    profile_units: dict[str, Mapping[str, Any]] = {
        unit["unit"]: unit for unit in profile["units"]
    }
    roles: dict[str, str] = {}
    unit_entries: list[dict[str, Any]] = []
    for unit in sorted(bundle.units, key=lambda item: item.unit):
        profile_unit = profile_units.get(unit.unit)
        if profile_unit is None:
            raise ValueError(f"unit {unit.unit} missing from the profile (fail-closed)")
        role = profile_unit["role"]
        roles[unit.unit] = role
        effect_map = dict(zip(bundle.universe_genes, unit.log2fc, strict=True))
        values: dict[str, float] = {
            set_name: fmean(effect_map[gene] for gene in covered_genes[set_name])
            for set_name in included
        }
        head = aggregate_hallmark_bridge(effect_map, bridge_memberships)
        profile_vector = profile_unit["six_node_vector"]
        for node, value in head.values:
            if abs(value - profile_vector[node]) > HEAD_GATE_TOLERANCE:
                raise ValueError(
                    f"six-node head disagrees with the profile for unit {unit.unit} "
                    f"at {node} (>{HEAD_GATE_TOLERANCE})"
                )
            values[node] = value
        unit_entries.append(
            {"unit": unit.unit, "target": {dim: values[dim] for dim in dims}}
        )

    train_entries = [entry for entry in unit_entries if roles[entry["unit"]] == TRAIN_ROLE]
    if not train_entries or len(train_entries) == len(unit_entries):
        raise ValueError("roles must keep non-empty train and holdout groups")
    centroid = {
        dim: fmean(entry["target"][dim] for entry in train_entries) for dim in dims
    }

    content: dict[str, Any] = {
        "schema_version": TARGET_SCHEMA_VERSION,
        "dataset_id": bundle.dataset_id,
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
        "bridge": {
            "version": HALLMARK_BRIDGE_VERSION,
            "digest": HALLMARK_BRIDGE_DIGEST,
        },
        "source": {
            "bundle_sha256": bundle.bundle_digest,
            "profile_sha256": sha256_text(profile["_file_sha256"], name="profile sha256"),
            "hallmark_gmt": dict(bundle.hallmark_source),
        },
        "split": dict(profile["split"]),
        "dims": list(dims),
        "excluded_sets": excluded_sets,
        "coverage": coverage,
        "roles": roles,
        "centroid_train_only": centroid,
        "units": unit_entries,
    }
    prefix = TARGET_ID_PREFIX_BY_DATASET.get(bundle.dataset_id, "hallmark-target")
    content["target_id"] = f"{prefix}-{digest_payload(content)[:16]}"
    return content


def save_hallmark_target(target: Mapping[str, Any], output_path: str | Path) -> Path:
    """Write-once canonical save; a different existing file is refused."""
    return write_json_once(output_path, target, artifact="hallmark target")


# ---------------------------------------------------------------------------
# Loader for the evaluation segment (strict, fail-closed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HallmarkTargetUnit:
    unit: str
    target: tuple[float, ...]  # aligned to HallmarkTarget.dims


@dataclass(frozen=True, slots=True)
class HallmarkTarget:
    target_id: str
    dataset_id: str
    dims: tuple[str, ...]
    set_dims: tuple[str, ...]
    excluded_sets: tuple[str, ...]
    coverage: dict[str, int]
    roles: dict[str, str]
    centroid: tuple[float, ...]  # aligned to dims
    units: tuple[HallmarkTargetUnit, ...]
    split: dict[str, Any]
    source: dict[str, Any]
    target_digest: str

    def __post_init__(self) -> None:
        names = [unit.unit for unit in self.units]
        if len(names) != len(set(names)):
            raise ValueError("target unit names must be unique")
        for unit in self.units:
            if len(unit.target) != len(self.dims):
                raise ValueError(f"unit {unit.unit} target length disagrees with dims")


def _dim_list(raw: Any, *, name: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{name} must be a non-empty list")
    dims = tuple(required_text(item, name=f"{name} entry") for item in raw)
    if len(dims) != len(set(dims)):
        raise ValueError(f"{name} entries must be unique")
    return dims


def load_hallmark_target(path: str | Path) -> HallmarkTarget:
    target_path = Path(path)
    raw = _read_json_object(target_path, name="hallmark target")
    _exact_keys(raw, _TARGET_TOP_KEYS, name="hallmark target")
    if raw["schema_version"] != TARGET_SCHEMA_VERSION:
        raise ValueError("unsupported hallmark target schema")
    target_id = required_text(raw["target_id"], name="target_id")
    dataset_id = required_text(raw["dataset_id"], name="dataset_id")
    dims = _dim_list(raw["dims"], name="dims")
    if len(dims) <= len(ABSTRACT_GENE_NAMES):
        raise ValueError("dims must contain set dimensions plus the six-node head")
    if dims[-len(ABSTRACT_GENE_NAMES):] != ABSTRACT_GENE_NAMES:
        raise ValueError("dims must end with the frozen six-node order")
    set_dims = dims[: -len(ABSTRACT_GENE_NAMES)]
    if tuple(sorted(set_dims)) != set_dims:
        raise ValueError("set dimensions must be sorted")
    excluded_raw = raw["excluded_sets"]
    if not isinstance(excluded_raw, list):
        raise ValueError("excluded_sets must be a list")
    excluded_sets = tuple(
        required_text(item, name="excluded_sets entry") for item in excluded_raw
    )
    if len(excluded_sets) != len(set(excluded_sets)):
        raise ValueError("excluded_sets entries must be unique")
    if set(excluded_sets) & set(dims):
        raise ValueError("excluded sets must not appear in dims")
    coverage_raw = raw["coverage"]
    if not isinstance(coverage_raw, dict):
        raise ValueError("coverage must be an object")
    if set(coverage_raw) != set(set_dims):
        raise ValueError("coverage keys must equal the set dimensions")
    coverage: dict[str, int] = {}
    for name, count in coverage_raw.items():
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError(f"coverage[{name}] must be a positive integer")
        coverage[name] = count
    roles_raw = raw["roles"]
    if not isinstance(roles_raw, dict) or not roles_raw:
        raise ValueError("roles must be a non-empty object")
    roles: dict[str, str] = {}
    for unit_name, role in roles_raw.items():
        required_text(unit_name, name="roles unit")
        role = required_text(role, name=f"roles[{unit_name}]")
        if role not in ROLES:
            raise ValueError(f"roles[{unit_name}] must be train or holdout")
        roles[unit_name] = role
    if len(set(roles.values())) != len(ROLES):
        raise ValueError("roles must keep non-empty train and holdout groups")
    centroid_raw = raw["centroid_train_only"]
    if not isinstance(centroid_raw, dict):
        raise ValueError("centroid_train_only must be an object")
    if set(centroid_raw.keys()) != set(dims):
        raise ValueError("centroid_train_only keys must equal dims")
    centroid = tuple(finite(centroid_raw[dim], name=f"centroid[{dim}]") for dim in dims)
    units_raw = raw["units"]
    if not isinstance(units_raw, list) or not units_raw:
        raise ValueError("units must be a non-empty list")
    units = []
    for index, item in enumerate(units_raw):
        if not isinstance(item, dict):
            raise ValueError(f"units[{index}] must be an object")
        _exact_keys(item, {"unit", "target"}, name=f"units[{index}]")
        unit_name = required_text(item["unit"], name=f"units[{index}].unit")
        target_raw = item["target"]
        if not isinstance(target_raw, dict):
            raise ValueError(f"units[{index}].target must be an object")
        if set(target_raw.keys()) != set(dims):
            raise ValueError(f"units[{index}].target keys must equal dims")
        units.append(
            HallmarkTargetUnit(
                unit=unit_name,
                target=tuple(
                    finite(target_raw[dim], name=f"{unit_name}.{dim}") for dim in dims
                ),
            )
        )
    if {unit.unit for unit in units} != set(roles):
        raise ValueError("units and roles disagree on the covered units")
    split = raw["split"]
    if not isinstance(split, dict):
        raise ValueError("split must be an object")
    _exact_keys(split, _PROFILE_SPLIT_KEYS, name="split")
    required_text(split["salt"], name="split.salt")
    if split["train_units"] != sum(1 for role in roles.values() if role == TRAIN_ROLE):
        raise ValueError("split.train_units disagrees with roles")
    if split["holdout_units"] != sum(1 for role in roles.values() if role == HOLDOUT_ROLE):
        raise ValueError("split.holdout_units disagrees with roles")
    source = raw["source"]
    if not isinstance(source, dict):
        raise ValueError("source must be an object")
    _exact_keys(source, {"bundle_sha256", "profile_sha256", "hallmark_gmt"}, name="source")
    sha256_text(source["bundle_sha256"], name="source.bundle_sha256")
    sha256_text(source["profile_sha256"], name="source.profile_sha256")
    gmt = source["hallmark_gmt"]
    if not isinstance(gmt, dict):
        raise ValueError("source.hallmark_gmt must be an object")
    _exact_keys(gmt, _HALLMARK_SOURCE_KEYS, name="source.hallmark_gmt")
    sha256_text(gmt["sha256"], name="source.hallmark_gmt.sha256")
    return HallmarkTarget(
        target_id=target_id,
        dataset_id=dataset_id,
        dims=dims,
        set_dims=set_dims,
        excluded_sets=excluded_sets,
        coverage=coverage,
        roles=roles,
        centroid=centroid,
        units=tuple(units),
        split=dict(split),
        source=dict(source),
        target_digest=file_sha256(target_path),
    )


# ---------------------------------------------------------------------------
# D-dimensional metrics (formulas copied from ocellus_anchors; that module's
# vector_metrics/mean_metrics are locked to the six-node type and cannot be
# reused; spearman/sign are generic and reused directly)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VectorMetricsD:
    mae: float
    sign_agreement: float
    spearman: float


def vector_metrics_d(
    predicted: Sequence[float], empirical: Sequence[float]
) -> VectorMetricsD:
    if not isinstance(predicted, Sequence) or not isinstance(empirical, Sequence):
        raise TypeError("vectors must be sequences")
    if len(predicted) != len(empirical) or not predicted:
        raise ValueError("vectors must be non-empty and equally long")
    left = [finite(value, name="predicted") for value in predicted]
    right = [finite(value, name="empirical") for value in empirical]
    return VectorMetricsD(
        mae=fmean(abs(x - y) for x, y in zip(left, right, strict=True)),
        sign_agreement=fmean(
            float(sign(x) == sign(y)) for x, y in zip(left, right, strict=True)
        ),
        spearman=spearman(left, right),
    )


def mean_metrics_d(items: Sequence[VectorMetricsD]) -> VectorMetricsD:
    if not items:
        raise ValueError("cannot summarize an empty metric group")
    return VectorMetricsD(
        mae=fmean(item.mae for item in items),
        sign_agreement=fmean(item.sign_agreement for item in items),
        spearman=fmean(item.spearman for item in items),
    )
