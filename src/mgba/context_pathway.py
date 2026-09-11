"""Evidence boundary for cross-context Hallmark perturbation prediction.

This module is deliberately dependency-free.  Raw single-cell processing and
model training stay in the independent training environment; the core package
only validates canonical bundles, freezes leakage-resistant splits, and later
verifies prediction artifacts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

from .experiment import write_json_once
from .hashing import digest_payload
from .validation import file_sha256, finite, required_text, sha256_text

CONTEXT_BUNDLE_SCHEMA_VERSION = "mgba-perturbation-context-bundle-0.1"
SPLIT_MANIFEST_SCHEMA_VERSION = "mgba-ood-split-manifest-0.1"
EMBEDDING_TABLE_SCHEMA_VERSION = "mgba-gene-embedding-table-0.1"
EMBEDDING_DIM = 768
HALLMARK_DIM_COUNT = 50
MINIMUM_SHARED_GENES = 500
MINIMUM_RELIABILITY = 0.30
DEVELOPMENT_CONTEXTS = (
    "replogle-k562",
    "replogle-rpe1",
    "nadig-hepg2",
    "nadig-jurkat",
)
PRE_REGISTERED_SALTS = tuple(
    f"mgba-context-pathway-ood-2026-09-03-{index}" for index in range(1, 6)
)
SPLIT_RATIOS = {"train": 0.70, "validation": 0.15, "test": 0.15}
EXTERNAL_CONTEXT_ID = "arc-h1-hesc"

_NORMALIZATION = {
    "library_size_scale": 10000.0,
    "transform": "log2(1+x)",
    "aggregation": "per-cell-transform-then-mean",
    "effect": "perturbed-minus-matched-control",
}
_SCIENTIFIC_BOUNDARY = (
    "Offline pathway-level CRISPRi response benchmark. Development claims are "
    "restricted to gene-disjoint, context-disjoint, and joint OOD evaluation; "
    "the sealed Arc H1 labels are not development data. This is not a clinical, "
    "CAR-M efficacy, full-transcriptome, or validated virtual-cell claim."
)


def _exact_keys(raw: Mapping[str, Any], expected: set[str], *, name: str) -> None:
    keys = set(raw)
    if keys != expected:
        raise ValueError(
            f"{name} keys mismatch; missing={sorted(expected - keys)} "
            f"extra={sorted(keys - expected)}"
        )


def _positive_int(value: Any, *, name: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _vector_mapping(
    raw: Any, dims: Sequence[str], *, name: str
) -> tuple[float, ...]:
    if not isinstance(raw, dict) or set(raw) != set(dims):
        raise ValueError(f"{name} target dimensions must exactly match dims")
    return tuple(finite(raw[dim], name=f"{name}.{dim}") for dim in dims)


def _source_identity(raw: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{name} must be an object")
    _exact_keys(
        raw,
        {"path", "sha256", "bytes", "license", "rights_verified"},
        name=name,
    )
    if raw["rights_verified"] is not True:
        raise ValueError(f"{name}.rights_verified must be true")
    return {
        "path": required_text(raw["path"], name=f"{name}.path"),
        "sha256": sha256_text(raw["sha256"], name=f"{name}.sha256"),
        "bytes": _positive_int(raw["bytes"], name=f"{name}.bytes"),
        "license": required_text(raw["license"], name=f"{name}.license"),
        "rights_verified": True,
    }


def _hallmark_identity(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("hallmark_source must be an object")
    _exact_keys(
        raw,
        {"path", "sha256", "version", "license", "rights_verified"},
        name="hallmark_source",
    )
    if raw["rights_verified"] is not True:
        raise ValueError("hallmark_source.rights_verified must be true")
    return {
        "path": required_text(raw["path"], name="hallmark_source.path"),
        "sha256": sha256_text(raw["sha256"], name="hallmark_source.sha256"),
        "version": required_text(raw["version"], name="hallmark_source.version"),
        "license": required_text(raw["license"], name="hallmark_source.license"),
        "rights_verified": True,
    }


@dataclass(frozen=True, slots=True)
class ContextUnit:
    gene: str
    cells: int
    target: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class ContextBundle:
    dataset_id: str
    context_id: str
    perturbation_type: str
    scientific_boundary: str
    source: dict[str, Any]
    hallmark_source: dict[str, Any]
    normalization: dict[str, Any]
    dims: tuple[str, ...]
    control_cells: int
    control: tuple[float, ...]
    units: tuple[ContextUnit, ...]
    reliability_resamples: int
    reliability_seed: int
    median_split_half_spearman: float
    file_sha256: str


def load_context_bundle(path: str | Path) -> ContextBundle:
    bundle_path = Path(path)
    try:
        raw = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid context bundle: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("context bundle must be an object")
    _exact_keys(
        raw,
        {
            "schema_version",
            "dataset_id",
            "context_id",
            "perturbation_type",
            "scientific_boundary",
            "source",
            "hallmark_source",
            "normalization",
            "dims",
            "control",
            "units",
            "reliability",
        },
        name="context bundle",
    )
    if raw["schema_version"] != CONTEXT_BUNDLE_SCHEMA_VERSION:
        raise ValueError("unsupported context bundle schema")
    if raw["perturbation_type"] != "crispri":
        raise ValueError("context bundle perturbation_type must be crispri")

    dims_raw = raw["dims"]
    if not isinstance(dims_raw, list):
        raise ValueError("dims must be a list")
    dims = tuple(required_text(dim, name="Hallmark dimension") for dim in dims_raw)
    if (
        len(dims) != HALLMARK_DIM_COUNT
        or len(set(dims)) != len(dims)
        or dims != tuple(sorted(dims))
        or any(not dim.startswith("HALLMARK_") for dim in dims)
    ):
        raise ValueError("dims must be 50 unique sorted Hallmark dimensions")

    normalization = raw["normalization"]
    if not isinstance(normalization, dict) or normalization != _NORMALIZATION:
        raise ValueError("normalization must match the frozen pathway protocol")

    control = raw["control"]
    if not isinstance(control, dict):
        raise ValueError("control must be an object")
    _exact_keys(control, {"cells", "vector"}, name="control")
    control_vector = _vector_mapping(control["vector"], dims, name="control.vector")

    units_raw = raw["units"]
    if not isinstance(units_raw, list) or not units_raw:
        raise ValueError("units must be a non-empty list")
    units = []
    for index, item in enumerate(units_raw):
        if not isinstance(item, dict):
            raise ValueError(f"units[{index}] must be an object")
        _exact_keys(item, {"gene", "cells", "target"}, name=f"units[{index}]")
        units.append(
            ContextUnit(
                gene=required_text(item["gene"], name=f"units[{index}].gene"),
                cells=_positive_int(item["cells"], name=f"units[{index}].cells", minimum=50),
                target=_vector_mapping(item["target"], dims, name=f"units[{index}].target"),
            )
        )
    genes = tuple(unit.gene for unit in units)
    if genes != tuple(sorted(genes)) or len(set(genes)) != len(genes):
        raise ValueError("unit genes must be unique and sorted")

    reliability = raw["reliability"]
    if not isinstance(reliability, dict):
        raise ValueError("reliability must be an object")
    _exact_keys(
        reliability,
        {"resamples", "seed", "median_split_half_spearman"},
        name="reliability",
    )
    resamples = _positive_int(reliability["resamples"], name="reliability.resamples")
    if resamples != 20:
        raise ValueError("reliability.resamples must equal the frozen value 20")
    reliability_seed = _positive_int(reliability["seed"], name="reliability.seed")
    if reliability_seed != 20260903:
        raise ValueError("reliability.seed changed after protocol lock")
    reliability_value = finite(
        reliability["median_split_half_spearman"],
        name="reliability.median_split_half_spearman",
    )
    if not -1.0 <= reliability_value <= 1.0:
        raise ValueError("median split-half reliability must be in [-1, 1]")

    return ContextBundle(
        dataset_id=required_text(raw["dataset_id"], name="dataset_id"),
        context_id=required_text(raw["context_id"], name="context_id"),
        perturbation_type="crispri",
        scientific_boundary=required_text(
            raw["scientific_boundary"], name="scientific_boundary"
        ),
        source=_source_identity(raw["source"], name="source"),
        hallmark_source=_hallmark_identity(raw["hallmark_source"]),
        normalization=dict(_NORMALIZATION),
        dims=dims,
        control_cells=_positive_int(control["cells"], name="control.cells", minimum=50),
        control=control_vector,
        units=tuple(units),
        reliability_resamples=resamples,
        reliability_seed=reliability_seed,
        median_split_half_spearman=reliability_value,
        file_sha256=file_sha256(bundle_path),
    )


def _partition_genes(genes: Sequence[str], salt: str) -> dict[str, list[str]]:
    ranked = sorted(
        genes,
        key=lambda gene: sha256(f"{salt}|{gene}".encode("utf-8")).hexdigest(),
    )
    train_end = int(len(ranked) * SPLIT_RATIOS["train"])
    validation_end = train_end + int(len(ranked) * SPLIT_RATIOS["validation"])
    return {
        "train_genes": sorted(ranked[:train_end]),
        "validation_genes": sorted(ranked[train_end:validation_end]),
        "test_genes": sorted(ranked[validation_end:]),
    }


def build_ood_split_manifest(
    bundles: Sequence[ContextBundle], *, embedding_genes: Sequence[str],
    embedding_table_sha256: str, external_labels_sha256: str
) -> dict[str, Any]:
    by_context = {bundle.context_id: bundle for bundle in bundles}
    if len(by_context) != len(bundles) or set(by_context) != set(DEVELOPMENT_CONTEXTS):
        raise ValueError(
            f"bundles must contain exactly the frozen development contexts: "
            f"{list(DEVELOPMENT_CONTEXTS)}"
        )
    ordered = [by_context[context] for context in DEVELOPMENT_CONTEXTS]
    first = ordered[0]
    for bundle in ordered:
        if bundle.dims != first.dims:
            raise ValueError("development bundles must use identical Hallmark dimensions")
        if bundle.hallmark_source["sha256"] != first.hallmark_source["sha256"]:
            raise ValueError("development bundles must use the same Hallmark source")
        if bundle.median_split_half_spearman < MINIMUM_RELIABILITY:
            raise ValueError(
                f"context {bundle.context_id} reliability is below {MINIMUM_RELIABILITY:.2f}"
            )
    source_shared = sorted(
        set.intersection(*(set(unit.gene for unit in bundle.units) for bundle in ordered))
    )
    if isinstance(embedding_genes, (str, bytes)) or any(
        not isinstance(gene, str) or not gene for gene in embedding_genes
    ):
        raise ValueError("embedding_genes must be unique non-empty strings")
    eligible = set(embedding_genes)
    if len(eligible) != len(embedding_genes):
        raise ValueError("embedding_genes must be unique non-empty strings")
    shared = sorted(set(source_shared) & eligible)
    excluded = sorted(set(source_shared) - eligible)
    if len(shared) < MINIMUM_SHARED_GENES:
        raise ValueError(
            f"embedding-covered shared perturbation genes must be at least "
            f"{MINIMUM_SHARED_GENES}; observed {len(shared)}"
        )

    folds = []
    for salt in PRE_REGISTERED_SALTS:
        partition = _partition_genes(shared, salt)
        for outer_context in DEVELOPMENT_CONTEXTS:
            folds.append(
                {
                    "fold_id": f"{outer_context}--{salt.rsplit('-', 1)[-1]}",
                    "outer_context": outer_context,
                    "training_contexts": [
                        context for context in DEVELOPMENT_CONTEXTS if context != outer_context
                    ],
                    "salt": salt,
                    **partition,
                }
            )
    content: dict[str, Any] = {
        "schema_version": SPLIT_MANIFEST_SCHEMA_VERSION,
        "study_id": "mgba-context-pathway-ood-2026-09-03",
        "protocol_status": "locked",
        "scientific_boundary": _SCIENTIFIC_BOUNDARY,
        "contexts": list(DEVELOPMENT_CONTEXTS),
        "bundles": {
            bundle.context_id: {
                "dataset_id": bundle.dataset_id,
                "sha256": bundle.file_sha256,
                "reliability": bundle.median_split_half_spearman,
            }
            for bundle in ordered
        },
        "dims": list(first.dims),
        "feature_eligibility": {
            "rule": "four-context-intersection-with-frozen-geneformer-availability",
            "schema_version": EMBEDDING_TABLE_SCHEMA_VERSION,
            "embedding_dim": EMBEDDING_DIM,
            "embedding_table_sha256": sha256_text(
                embedding_table_sha256, name="embedding_table_sha256"
            ),
            "source_shared_genes": source_shared,
            "excluded_genes": excluded,
        },
        "shared_genes": shared,
        "minimum_shared_genes": MINIMUM_SHARED_GENES,
        "minimum_reliability": MINIMUM_RELIABILITY,
        "salts": list(PRE_REGISTERED_SALTS),
        "ratios": dict(SPLIT_RATIOS),
        "folds": folds,
        "external_test": {
            "context_id": EXTERNAL_CONTEXT_ID,
            "labels_sha256": sha256_text(
                external_labels_sha256, name="external_labels_sha256"
            ),
            "status": "sealed",
        },
    }
    content["split_id"] = f"ood-split-{digest_payload(content)[:16]}"
    return content


def _validate_split_manifest(raw: Mapping[str, Any]) -> None:
    _exact_keys(
        raw,
        {
            "schema_version",
            "study_id",
            "protocol_status",
            "scientific_boundary",
            "contexts",
            "bundles",
            "dims",
            "feature_eligibility",
            "shared_genes",
            "minimum_shared_genes",
            "minimum_reliability",
            "salts",
            "ratios",
            "folds",
            "external_test",
            "split_id",
        },
        name="OOD split manifest",
    )
    if raw["schema_version"] != SPLIT_MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported OOD split manifest schema")
    identity_content = dict(raw)
    split_id = identity_content.pop("split_id")
    expected_id = f"ood-split-{digest_payload(identity_content)[:16]}"
    if split_id != expected_id:
        raise ValueError("split_id does not match the OOD split manifest content")
    if raw["protocol_status"] != "locked":
        raise ValueError("OOD protocol must be locked")
    if raw["contexts"] != list(DEVELOPMENT_CONTEXTS):
        raise ValueError("OOD development contexts changed after lock")
    if raw["salts"] != list(PRE_REGISTERED_SALTS) or raw["ratios"] != SPLIT_RATIOS:
        raise ValueError("OOD salts or ratios changed after lock")
    if raw["minimum_shared_genes"] != MINIMUM_SHARED_GENES:
        raise ValueError("minimum_shared_genes changed after lock")
    if raw["minimum_reliability"] != MINIMUM_RELIABILITY:
        raise ValueError("minimum_reliability changed after lock")
    bundles = raw["bundles"]
    if not isinstance(bundles, dict) or set(bundles) != set(DEVELOPMENT_CONTEXTS):
        raise ValueError("bundles must match the frozen development contexts")
    for context, identity in bundles.items():
        if not isinstance(identity, dict):
            raise ValueError(f"bundles.{context} must be an object")
        _exact_keys(
            identity,
            {"dataset_id", "sha256", "reliability"},
            name=f"bundles.{context}",
        )
        required_text(identity["dataset_id"], name=f"bundles.{context}.dataset_id")
        sha256_text(identity["sha256"], name=f"bundles.{context}.sha256")
        reliability = finite(
            identity["reliability"], name=f"bundles.{context}.reliability"
        )
        if reliability < MINIMUM_RELIABILITY or reliability > 1.0:
            raise ValueError(f"bundles.{context}.reliability is outside the locked gate")
    dims = raw["dims"]
    if (
        not isinstance(dims, list)
        or len(dims) != HALLMARK_DIM_COUNT
        or len(set(dims)) != len(dims)
        or dims != sorted(dims)
        or any(not isinstance(dim, str) or not dim.startswith("HALLMARK_") for dim in dims)
    ):
        raise ValueError("manifest dims must be 50 unique sorted Hallmark dimensions")
    feature = raw["feature_eligibility"]
    if not isinstance(feature, dict):
        raise ValueError("feature_eligibility must be an object")
    _exact_keys(
        feature,
        {
            "rule",
            "schema_version",
            "embedding_dim",
            "embedding_table_sha256",
            "source_shared_genes",
            "excluded_genes",
        },
        name="feature_eligibility",
    )
    if feature["rule"] != "four-context-intersection-with-frozen-geneformer-availability":
        raise ValueError("feature eligibility rule changed after lock")
    if (
        feature["schema_version"] != EMBEDDING_TABLE_SCHEMA_VERSION
        or feature["embedding_dim"] != EMBEDDING_DIM
    ):
        raise ValueError("feature eligibility source changed after lock")
    sha256_text(
        feature["embedding_table_sha256"],
        name="feature_eligibility.embedding_table_sha256",
    )
    shared = raw["shared_genes"]
    if (
        not isinstance(shared, list)
        or len(shared) < MINIMUM_SHARED_GENES
        or shared != sorted(shared)
        or len(set(shared)) != len(shared)
    ):
        raise ValueError("manifest shared_genes are invalid")
    source_shared = feature["source_shared_genes"]
    excluded = feature["excluded_genes"]
    if (
        not isinstance(source_shared, list)
        or source_shared != sorted(source_shared)
        or len(set(source_shared)) != len(source_shared)
        or not isinstance(excluded, list)
        or excluded != sorted(excluded)
        or len(set(excluded)) != len(excluded)
        or set(shared) & set(excluded)
        or source_shared != sorted(shared + excluded)
    ):
        raise ValueError("feature eligibility gene audit is invalid")
    external = raw["external_test"]
    if not isinstance(external, dict):
        raise ValueError("external_test must be an object")
    _exact_keys(external, {"context_id", "labels_sha256", "status"}, name="external_test")
    if external["context_id"] != EXTERNAL_CONTEXT_ID or external["status"] != "sealed":
        raise ValueError("Arc H1 external test must remain sealed")
    sha256_text(external["labels_sha256"], name="external_test.labels_sha256")

    folds = raw["folds"]
    if not isinstance(folds, list) or len(folds) != len(DEVELOPMENT_CONTEXTS) * len(PRE_REGISTERED_SALTS):
        raise ValueError("manifest must contain the frozen 20 OOD folds")
    expected = []
    for salt in PRE_REGISTERED_SALTS:
        partition = _partition_genes(shared, salt)
        for outer_context in DEVELOPMENT_CONTEXTS:
            expected.append(
                {
                    "fold_id": f"{outer_context}--{salt.rsplit('-', 1)[-1]}",
                    "outer_context": outer_context,
                    "training_contexts": [
                        context for context in DEVELOPMENT_CONTEXTS if context != outer_context
                    ],
                    "salt": salt,
                    **partition,
                }
            )
    if folds != expected:
        raise ValueError("OOD folds are not the deterministic disjoint split")


def load_ood_split_manifest(path: str | Path) -> dict[str, Any]:
    split_path = Path(path)
    try:
        raw = json.loads(split_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid OOD split manifest: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("OOD split manifest must be an object")
    _validate_split_manifest(raw)
    raw["_file_sha256"] = file_sha256(split_path)
    return raw


def save_ood_split_manifest(manifest: Mapping[str, Any], output_path: str | Path) -> Path:
    _validate_split_manifest(manifest)
    return write_json_once(output_path, manifest, artifact="OOD split manifest")
