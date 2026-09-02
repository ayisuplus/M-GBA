"""AIVC Norman Perturb-seq empirical six-node anchor (ADR-0036).

Pure-stdlib aggregation segment. It consumes the ``mgba-aivc-empirical-log2fc-0.1``
bundle produced by ``scripts/aivc_norman_empirical.py`` (independent venv only)
and the MSigDB v2026.1 Hallmark GMT, then applies the frozen six-node bridge,
digest-ranked train/holdout split, train-only centroid baseline, and
MAE/sign/Spearman descriptive metrics. No predictor exists yet: the profile is
a reference-model-grade empirical description, not a validation result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping, Sequence

from .hashing import digest_payload
from .layers.l0 import ABSTRACT_GENE_NAMES
from .ocellus_anchors import (
    HALLMARK_BRIDGE,
    HALLMARK_BRIDGE_DIGEST,
    HALLMARK_BRIDGE_VERSION,
    REQUIRED_HALLMARK_SETS,
    VectorMetrics,
    aggregate_hallmark_bridge,
    mean_metrics,
    sign,
    spearman,
    vector_metrics,
)
from .validation import file_sha256, finite, required_text, sha256_text

EMPIRICAL_BUNDLE_SCHEMA_VERSION = "mgba-aivc-empirical-log2fc-0.1"
PROFILE_SCHEMA_VERSION = "mgba-aivc-perturbation-profile-0.1"
SPLIT_SALT = "mgba-aivc-norman-anchor-2026-08-28"
TRAIN_FRACTION = 0.8
TRAIN_ROLE = "train"
HOLDOUT_ROLE = "holdout"

# profile_id prefix per dataset; the Norman prefix is frozen with the Stage 1
# artifact identity and must never change for that dataset.
PROFILE_ID_PREFIX_BY_DATASET = {
    "norman-weissman-2019-scperturb-filtered": "norman-perturbation-profile",
    "norman-weissman-2019-geo-native": "norman-geo-perturbation-profile",
    "replogle-2022-k562-essential-scperturb": "replogle-kd-perturbation-profile",
}

# Frozen before any expression value was computed, per dataset (ADR-0036/0039).
FROZEN_PARAMETERS = {
    "qc_flag": "good_coverage",
    "control_label": "control",
    "min_cells": 50,
    "library_size_scale": 10000.0,
    "normalization": "library-size-1e4-log2(1+x)-unit-mean",
    "log2fc_rule": "log2fc = unit_mean_log2 - control_mean_log2",
}
FROZEN_PARAMETERS_REPLOGLE = {
    "qc_flag": "none-filtered-release",
    "control_label": "control",
    "min_cells": 50,
    "library_size_scale": 10000.0,
    "normalization": "library-size-1e4-log2(1+x)-unit-mean",
    "log2fc_rule": "log2fc = unit_mean_log2 - control_mean_log2",
}
# Top-level bundle keys allowed beyond the base set, per dataset (fail-closed).
EXTRA_BUNDLE_KEYS_BY_DATASET = {
    "norman-weissman-2019-geo-native": ("auxiliary_sources",),
}
AUXILIARY_SOURCE_KEYS = ("barcodes_sha256", "genes_sha256", "cell_identities_sha256")

FROZEN_PARAMETERS_BY_DATASET = {
    "norman-weissman-2019-scperturb-filtered": FROZEN_PARAMETERS,
    "norman-weissman-2019-geo-native": FROZEN_PARAMETERS,
    "replogle-2022-k562-essential-scperturb": FROZEN_PARAMETERS_REPLOGLE,
}

SCIENTIFIC_BOUNDARY = (
    "De-identified aggregate empirical profile of public Perturb-seq data "
    "projected through the frozen Hallmark six-node bridge; reference-model "
    "grade description only. Not a biological fit, a virtual-cell claim, or "
    "an efficacy predictor; Norman 2019 is CRISPRa overexpression in a single "
    "K562 background and must not be extrapolated."
)








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


def _source_identity(raw: Any, *, name: str, extra_keys: set[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{name} must be an object")
    _exact_keys(
        raw,
        {"path", "sha256", "bytes", "license", "rights_verified"} | extra_keys,
        name=name,
    )
    identity = {
        "path": required_text(raw["path"], name=f"{name}.path"),
        "sha256": sha256_text(raw["sha256"], name=f"{name}.sha256"),
        "bytes": 0,
        "license": required_text(raw["license"], name=f"{name}.license"),
        "rights_verified": raw["rights_verified"],
    }
    if isinstance(raw["bytes"], bool) or not isinstance(raw["bytes"], int) or raw["bytes"] < 1:
        raise ValueError(f"{name}.bytes must be a positive integer")
    identity["bytes"] = raw["bytes"]
    if identity["rights_verified"] is not True:
        raise ValueError(f"{name} needs explicit rights verification")
    for key in extra_keys:
        identity[key] = required_text(raw[key], name=f"{name}.{key}")
    return identity


@dataclass(frozen=True, slots=True)
class EmpiricalUnit:
    unit: str
    cells: int
    log2fc: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.unit.strip():
            raise ValueError("unit name must not be empty")
        if self.cells < 50:
            raise ValueError("empirical unit must keep the frozen >=50 QC cells")


@dataclass(frozen=True, slots=True)
class EmpiricalBundle:
    dataset_id: str
    source: dict[str, Any]
    hallmark_source: dict[str, Any]
    parameters: dict[str, Any]
    universe_genes: tuple[str, ...]
    control_cells: int
    units: tuple[EmpiricalUnit, ...]
    bundle_digest: str

    def __post_init__(self) -> None:
        if not self.dataset_id.strip():
            raise ValueError("dataset_id must not be empty")
        if not self.universe_genes:
            raise ValueError("gene universe must not be empty")
        if len(set(self.universe_genes)) != len(self.universe_genes):
            raise ValueError("gene universe must be unique")
        if self.control_cells < 50:
            raise ValueError("control needs the frozen >=50 QC cells")
        names = [unit.unit for unit in self.units]
        if len(names) != len(set(names)):
            raise ValueError("empirical unit names must be unique")
        for unit in self.units:
            if len(unit.log2fc) != len(self.universe_genes):
                raise ValueError(f"unit {unit.unit} log2fc length disagrees with universe")


def load_empirical_bundle(path: str | Path) -> EmpiricalBundle:
    bundle_path = Path(path)
    raw = _read_json_object(bundle_path, name="empirical log2fc bundle")
    dataset_id_top = raw.get("dataset_id")
    extra_keys = EXTRA_BUNDLE_KEYS_BY_DATASET.get(dataset_id_top, ())
    _exact_keys(
        raw,
        {
            "schema_version",
            "dataset_id",
            "source",
            "hallmark_source",
            "parameters",
            "gene_universe",
            "control_cells",
            "units",
        }
        | set(extra_keys),
        name="empirical log2fc bundle",
    )
    if "auxiliary_sources" in raw:
        aux = raw["auxiliary_sources"]
        if not isinstance(aux, dict):
            raise ValueError("auxiliary_sources must be an object")
        _exact_keys(aux, set(AUXILIARY_SOURCE_KEYS), name="auxiliary_sources")
        for key in AUXILIARY_SOURCE_KEYS:
            sha256_text(aux[key], name=f"auxiliary_sources.{key}")
    if raw["schema_version"] != EMPIRICAL_BUNDLE_SCHEMA_VERSION:
        raise ValueError("unsupported empirical bundle schema")
    parameters = raw["parameters"]
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")
    dataset_id = required_text(raw["dataset_id"], name="dataset_id")
    expected_parameters = FROZEN_PARAMETERS_BY_DATASET.get(dataset_id)
    if expected_parameters is None:
        raise ValueError(f"empirical bundle dataset_id not in the frozen allowlist: {dataset_id}")
    _exact_keys(parameters, set(expected_parameters), name="bundle parameters")
    for key, expected in expected_parameters.items():
        if parameters[key] != expected:
            raise ValueError(
                f"frozen parameter {key} disagrees: {parameters[key]!r} != {expected!r}"
            )
    universe_raw = raw["gene_universe"]
    if not isinstance(universe_raw, dict):
        raise ValueError("gene_universe must be an object")
    _exact_keys(universe_raw, {"description", "genes"}, name="gene_universe")
    required_text(universe_raw["description"], name="gene_universe.description")
    genes = universe_raw["genes"]
    if not isinstance(genes, list):
        raise ValueError("gene_universe.genes must be a list")
    universe = tuple(required_text(gene, name="universe gene") for gene in genes)
    units_raw = raw["units"]
    if not isinstance(units_raw, list) or not units_raw:
        raise ValueError("units must be a non-empty list")
    units = []
    for index, item in enumerate(units_raw):
        if not isinstance(item, dict):
            raise ValueError(f"units[{index}] must be an object")
        _exact_keys(item, {"unit", "cells", "log2fc"}, name=f"units[{index}]")
        log2fc_raw = item["log2fc"]
        if not isinstance(log2fc_raw, list):
            raise ValueError(f"units[{index}].log2fc must be a list")
        cells = item["cells"]
        if isinstance(cells, bool) or not isinstance(cells, int):
            raise ValueError(f"units[{index}].cells must be an integer")
        units.append(
            EmpiricalUnit(
                unit=required_text(item["unit"], name=f"units[{index}].unit"),
                cells=cells,
                log2fc=tuple(
                    finite(value, name=f"units[{index}].log2fc") for value in log2fc_raw
                ),
            )
        )
    control_cells = raw["control_cells"]
    if isinstance(control_cells, bool) or not isinstance(control_cells, int):
        raise ValueError("control_cells must be an integer")
    return EmpiricalBundle(
        dataset_id=dataset_id,
        source=_source_identity(raw["source"], name="source", extra_keys={"zenodo_doi"}),
        hallmark_source=_source_identity(
            raw["hallmark_source"], name="hallmark_source", extra_keys={"version"}
        ),
        parameters=dict(expected_parameters),
        universe_genes=universe,
        control_cells=control_cells,
        units=tuple(units),
        bundle_digest=file_sha256(bundle_path),
    )


def load_hallmark_memberships(
    gmt_path: str | Path, *, expected_sha256: str
) -> dict[str, tuple[str, ...]]:
    """Parse the Hallmark GMT and return the frozen bridge's ten memberships."""
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
            if name in REQUIRED_HALLMARK_SETS:
                genes = tuple(sorted({gene for gene in columns[2:] if gene}))
                if not genes:
                    raise ValueError(f"Hallmark set {name} is empty")
                memberships[name] = genes
    missing = [name for name in REQUIRED_HALLMARK_SETS if name not in memberships]
    if missing:
        raise ValueError(f"Hallmark GMT misses frozen bridge sets: {missing}")
    return memberships


def assign_splits(
    unit_names: Sequence[str], *, salt: str = SPLIT_SALT, train_fraction: float = TRAIN_FRACTION
) -> dict[str, str]:
    """Deterministic digest-ranked split; floor(n * fraction) train units."""
    if not 0.0 < train_fraction < 1.0:
        raise ValueError("train_fraction must be in (0, 1)")
    if not unit_names or len(set(unit_names)) != len(unit_names):
        raise ValueError("unit names must be unique for splitting")
    ranked = sorted(
        unit_names,
        key=lambda name: sha256(f"{salt}|{name}".encode("utf-8")).hexdigest(),
    )
    train_count = int(len(ranked) * train_fraction)
    if train_count < 1 or train_count >= len(ranked):
        raise ValueError("split would leave an empty train or holdout role")
    return {
        name: (TRAIN_ROLE if index < train_count else HOLDOUT_ROLE)
        for index, name in enumerate(ranked)
    }


@dataclass(frozen=True, slots=True)
class UnitProfile:
    unit: str
    cells: int
    role: str
    vector: tuple[tuple[str, float], ...]
    metrics: dict[str, float]

    def __post_init__(self) -> None:
        if self.role not in {TRAIN_ROLE, HOLDOUT_ROLE}:
            raise ValueError("unit role must be train or holdout")
        if tuple(name for name, _ in self.vector) != ABSTRACT_GENE_NAMES:
            raise ValueError("unit vector must use the frozen six-node order")


@dataclass(frozen=True, slots=True)
class PerturbationProfile:
    dataset_id: str
    bundle_digest: str
    source: dict[str, Any]
    hallmark_source: dict[str, Any]
    parameters: dict[str, Any]
    split: dict[str, Any]
    centroid: tuple[tuple[str, float], ...]
    units: tuple[UnitProfile, ...]
    train_summary: dict[str, float]
    holdout_summary: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        content: dict[str, Any] = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "dataset_id": self.dataset_id,
            "scientific_boundary": SCIENTIFIC_BOUNDARY,
            "bridge": {
                "version": HALLMARK_BRIDGE_VERSION,
                "digest": HALLMARK_BRIDGE_DIGEST,
            },
            "source": {
                "bundle_sha256": self.bundle_digest,
                "h5ad": self.source,
                "hallmark_gmt": self.hallmark_source,
            },
            "parameters": self.parameters,
            "split": self.split,
            "centroid_train_only": dict(self.centroid),
            "units": [
                {
                    "unit": unit.unit,
                    "cells": unit.cells,
                    "role": unit.role,
                    "six_node_vector": dict(unit.vector),
                    "metrics_vs_centroid": unit.metrics,
                }
                for unit in self.units
            ],
            "metrics_summary": {
            "train": self.train_summary,
            "holdout": self.holdout_summary,
            },
        }
        prefix = PROFILE_ID_PREFIX_BY_DATASET.get(self.dataset_id, "perturbation-profile")
        content["profile_id"] = f"{prefix}-{digest_payload(content)[:16]}"
        return content


def build_perturbation_profile(
    bundle: EmpiricalBundle,
    memberships: Mapping[str, Sequence[str]],
    *,
    salt: str = SPLIT_SALT,
) -> PerturbationProfile:
    """Apply the frozen bridge, split, and train-only centroid baseline."""
    roles = assign_splits([unit.unit for unit in bundle.units], salt=salt)
    projections: dict[str, tuple[tuple[str, float], ...]] = {}
    for unit in bundle.units:
        projection = aggregate_hallmark_bridge(
            dict(zip(bundle.universe_genes, unit.log2fc, strict=True)),
            memberships,
        )
        projections[unit.unit] = projection.values

    train_units = [unit for unit in bundle.units if roles[unit.unit] == TRAIN_ROLE]
    holdout_units = [unit for unit in bundle.units if roles[unit.unit] == HOLDOUT_ROLE]
    centroid_values = tuple(
        fmean(dict(projections[unit.unit])[node] for unit in train_units)
        for node in ABSTRACT_GENE_NAMES
    )
    centroid = tuple(zip(ABSTRACT_GENE_NAMES, centroid_values, strict=True))

    metrics_by_unit: dict[str, VectorMetrics] = {}

    def _metrics_for(unit: EmpiricalUnit) -> dict[str, float]:
        result = vector_metrics(centroid, projections[unit.unit])
        metrics_by_unit[unit.unit] = result
        return {
            "six_node_mae": result.six_node_mae,
            "sign_agreement": result.sign_agreement,
            "spearman": result.spearman,
        }

    profiles = tuple(
        UnitProfile(
            unit=unit.unit,
            cells=unit.cells,
            role=roles[unit.unit],
            vector=projections[unit.unit],
            metrics=_metrics_for(unit),
        )
        for unit in sorted(bundle.units, key=lambda item: item.unit)
    )

    def _summary(units: Sequence[EmpiricalUnit]) -> dict[str, float]:
        # Reuse the per-unit metrics already computed for the profiles instead
        # of evaluating the same (centroid, projection) pairs a second time.
        mean = mean_metrics([metrics_by_unit[unit.unit] for unit in units])
        return {
            "six_node_mae": mean.six_node_mae,
            "sign_agreement": mean.sign_agreement,
            "spearman": mean.spearman,
            "unit_count": len(units),
        }

    return PerturbationProfile(
        dataset_id=bundle.dataset_id,
        bundle_digest=bundle.bundle_digest,
        source=bundle.source,
        hallmark_source=bundle.hallmark_source,
        parameters=dict(bundle.parameters),
        split={
            "salt": salt,
            "train_fraction": TRAIN_FRACTION,
            "rule": "sha256(salt|unit) ranked; floor(n*0.8) train",
            "train_units": len(train_units),
            "holdout_units": len(holdout_units),
        },
        centroid=centroid,
        units=profiles,
        train_summary=_summary(train_units),
        holdout_summary=_summary(holdout_units),
    )


def save_perturbation_profile(
    profile: PerturbationProfile, output_path: str | Path
) -> Path:
    """Write-once save; existing output is never overwritten."""
    output = Path(output_path)
    if output.exists():
        raise ValueError(f"refusing to overwrite existing profile: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(profile.as_dict(), indent=2), encoding="utf-8")
    return output


# ---------------------------------------------------------------------------
# ADR-0042: two-source cross-check of Stage 1 profiles
# ---------------------------------------------------------------------------

CROSSCHECK_SCHEMA_VERSION = "mgba-aivc-crosscheck-0.1"
CROSSCHECK_MIN_SPEARMAN = 0.8
CROSSCHECK_MIN_SIGN = 0.8

CROSSCHECK_BOUNDARY = (
    "Consistency check of two independent source-format pipelines for the same "
    "dataset (scPerturb harmonized vs GEO-native). Descriptive reproducibility "
    "evidence only; not a biological validation."
)


def load_profile_for_crosscheck(path: str | Path) -> dict[str, Any]:
    profile_path = Path(path)
    raw = _read_json_object(profile_path, name="perturbation profile")
    for key in ("schema_version", "profile_id", "units"):
        if key not in raw:
            raise ValueError(f"profile lacks {key}")
    if raw["schema_version"] != PROFILE_SCHEMA_VERSION:
        raise ValueError("unsupported profile schema")
    if not isinstance(raw["units"], list) or not raw["units"]:
        raise ValueError("profile units must be a non-empty list")
    for index, unit in enumerate(raw["units"]):
        if not isinstance(unit, dict) or "unit" not in unit or "six_node_vector" not in unit:
            raise ValueError(f"profile units[{index}] lacks unit/six_node_vector")
        vector = unit["six_node_vector"]
        if not isinstance(vector, dict):
            raise ValueError(f"profile units[{index}].six_node_vector must be an object")
        if tuple(vector.keys()) != ABSTRACT_GENE_NAMES:
            raise ValueError(f"profile units[{index}] node order disagrees with frozen order")
        for node, value in vector.items():
            finite(value, name=f"{unit['unit']}.{node}")
    raw["_file_sha256"] = file_sha256(profile_path)
    return raw


def compare_profiles(
    profile_a: dict[str, Any], profile_b: dict[str, Any]
) -> dict[str, Any]:
    """Frozen consistency metrics over shared units (thresholds pre-registered)."""
    units_a = {unit["unit"]: unit["six_node_vector"] for unit in profile_a["units"]}
    units_b = {unit["unit"]: unit["six_node_vector"] for unit in profile_b["units"]}
    shared = sorted(set(units_a) & set(units_b))
    if len(shared) < 10:
        raise ValueError(f"too few shared units for a cross-check: {len(shared)}")

    per_unit = []
    flat_a: list[float] = []
    flat_b: list[float] = []
    for unit in shared:
        vector_a = [units_a[unit][node] for node in ABSTRACT_GENE_NAMES]
        vector_b = [units_b[unit][node] for node in ABSTRACT_GENE_NAMES]
        flat_a.extend(vector_a)
        flat_b.extend(vector_b)
        per_unit.append(
            {
                "unit": unit,
                "mae": fmean(abs(x - y) for x, y in zip(vector_a, vector_b, strict=True)),
                "sign_agreement": fmean(
                    float(sign(x) == sign(y)) for x, y in zip(vector_a, vector_b, strict=True)
                ),
            }
        )
    spearman_value = spearman(flat_a, flat_b)
    mean_mae = fmean(item["mae"] for item in per_unit)
    mean_sign = fmean(item["sign_agreement"] for item in per_unit)
    verdict = (
        "consistent"
        if spearman_value > CROSSCHECK_MIN_SPEARMAN and mean_sign > CROSSCHECK_MIN_SIGN
        else "inconsistent"
    )
    content: dict[str, Any] = {
        "schema_version": CROSSCHECK_SCHEMA_VERSION,
        "scientific_boundary": CROSSCHECK_BOUNDARY,
        "profiles": {
            "a": {"profile_id": profile_a["profile_id"], "sha256": profile_a["_file_sha256"]},
            "b": {"profile_id": profile_b["profile_id"], "sha256": profile_b["_file_sha256"]},
        },
        "rule": {
            "shared_units": "intersection of unit names",
            "thresholds": f"spearman > {CROSSCHECK_MIN_SPEARMAN} and mean sign agreement > {CROSSCHECK_MIN_SIGN}",
            "salt_note": "splits are irrelevant to this comparison",
        },
        "shared_units": len(shared),
        "metrics": {
            "mean_mae": mean_mae,
            "mean_sign_agreement": mean_sign,
            "flattened_spearman": spearman_value,
        },
        "per_unit": per_unit,
        "verdict": verdict,
    }
    content["crosscheck_id"] = f"aivc-crosscheck-{digest_payload(content)[:16]}"
    return content


def save_crosscheck(result: Mapping[str, Any], output_path: str | Path) -> Path:
    output = Path(output_path)
    if output.exists():
        raise ValueError(f"refusing to overwrite existing crosscheck: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(result), indent=2), encoding="utf-8")
    return output
