#!/usr/bin/env python
"""Build one locked CRISPRi context bundle from a raw h5ad file.

Run in ``.venv-train``.  The dependency-free package only consumes the JSON
artifact written here; AnnData, NumPy, and SciPy remain outside core runtime.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import anndata as ad
import numpy as np
from scipy import sparse
from scipy.stats import spearmanr

from mgba.context_pathway import (
    CONTEXT_BUNDLE_SCHEMA_VERSION,
    DEVELOPMENT_CONTEXTS,
)
from mgba.experiment import write_json_once
from mgba.validation import file_sha256

MIN_CELLS = 50
RESAMPLES = 20
SEED = 20260903
CHUNK_ROWS = 20_000


def load_hallmark_sets(path: Path) -> dict[str, tuple[str, ...]]:
    sets: dict[str, tuple[str, ...]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            columns = line.rstrip("\n").split("\t")
            if len(columns) < 3 or not columns[0].startswith("HALLMARK_"):
                raise ValueError(f"invalid Hallmark GMT row {line_number}")
            if columns[0] in sets:
                raise ValueError(f"duplicate Hallmark set: {columns[0]}")
            genes = tuple(dict.fromkeys(gene for gene in columns[2:] if gene))
            if not genes:
                raise ValueError(f"empty Hallmark set: {columns[0]}")
            sets[columns[0]] = genes
    if len(sets) != 50:
        raise ValueError(f"Hallmark GMT must contain exactly 50 sets; observed {len(sets)}")
    return dict(sorted(sets.items()))


def _pathway_scores(block, library_sizes: np.ndarray, membership):
    if sparse.issparse(block):
        scaled = block.astype(np.float64).multiply((10_000.0 / library_sizes)[:, None])
        scaled.data = np.log2(1.0 + scaled.data)
        return np.asarray(scaled @ membership, dtype=np.float32)
    scaled = np.asarray(block, dtype=np.float64) * (10_000.0 / library_sizes)[:, None]
    return np.asarray(np.log2(1.0 + scaled) @ membership, dtype=np.float32)


def _split_half_reliability(
    control: np.ndarray, units: dict[str, np.ndarray]
) -> float:
    rng = np.random.default_rng(SEED)
    per_unit: list[float] = []
    for values in units.values():
        correlations = []
        for _ in range(RESAMPLES):
            control_order = rng.permutation(len(control))
            unit_order = rng.permutation(len(values))
            control_half = len(control_order) // 2
            unit_half = len(unit_order) // 2
            first = (
                values[unit_order[:unit_half]].mean(axis=0)
                - control[control_order[:control_half]].mean(axis=0)
            )
            second = (
                values[unit_order[unit_half:]].mean(axis=0)
                - control[control_order[control_half:]].mean(axis=0)
            )
            correlation = float(spearmanr(first, second).statistic)
            correlations.append(correlation if math.isfinite(correlation) else 0.0)
        per_unit.append(float(np.median(correlations)))
    return float(np.median(per_unit))


def build_bundle(
    h5ad_path: Path,
    hallmark_path: Path,
    output_path: Path,
    *,
    dataset_id: str,
    context_id: str,
    perturbation_key: str,
    gene_key: str | None,
    control_label: str,
    source_license: str,
    hallmark_version: str,
    hallmark_license: str,
    context_key: str | None = None,
    context_value: str | None = None,
) -> dict:
    if context_id not in DEVELOPMENT_CONTEXTS:
        raise ValueError("builder only accepts the four locked development contexts")
    if bool(context_key) != bool(context_value):
        raise ValueError("context_key and context_value must be provided together")
    hallmark_sets = load_hallmark_sets(hallmark_path)
    data = ad.read_h5ad(h5ad_path, backed="r")
    try:
        if perturbation_key not in data.obs:
            raise ValueError(f"obs key not found: {perturbation_key}")
        labels = data.obs[perturbation_key].astype(str).to_numpy()
        selected_rows = np.ones(data.n_obs, dtype=bool)
        if context_key:
            if context_key not in data.obs:
                raise ValueError(f"obs key not found: {context_key}")
            selected_rows = data.obs[context_key].astype(str).to_numpy() == context_value
        if not selected_rows.any():
            raise ValueError("context selection produced no cells")

        symbols = (
            data.var_names.astype(str).to_numpy()
            if gene_key is None
            else data.var[gene_key].astype(str).to_numpy()
        )
        hallmark_symbols = {
            gene for genes in hallmark_sets.values() for gene in genes
        }
        covered_columns: dict[str, list[int]] = {}
        for index, symbol in enumerate(symbols):
            if symbol in hallmark_symbols:
                covered_columns.setdefault(symbol, []).append(index)
        duplicate_covered = sorted(
            symbol for symbol, indexes in covered_columns.items() if len(indexes) > 1
        )
        if duplicate_covered:
            raise ValueError(
                f"Hallmark gene symbols must be unique: {duplicate_covered[0]}"
            )
        symbol_to_column = {
            symbol: indexes[0] for symbol, indexes in covered_columns.items()
        }
        covered_symbols = sorted(
            symbol_to_column
        )
        if not covered_symbols:
            raise ValueError("no Hallmark genes are present in the h5ad")
        columns = [symbol_to_column[symbol] for symbol in covered_symbols]
        covered_index = {symbol: index for index, symbol in enumerate(covered_symbols)}
        membership = np.zeros((len(covered_symbols), 50), dtype=np.float64)
        for pathway_index, genes in enumerate(hallmark_sets.values()):
            covered = [gene for gene in genes if gene in covered_index]
            if not covered:
                raise ValueError(f"Hallmark set has no covered genes: {list(hallmark_sets)[pathway_index]}")
            for gene in covered:
                membership[covered_index[gene], pathway_index] = 1.0 / len(covered)

        selected_labels = labels[selected_rows]
        names, counts = np.unique(selected_labels, return_counts=True)
        count_by_label = dict(zip(names.tolist(), counts.tolist()))
        if count_by_label.get(control_label, 0) < MIN_CELLS:
            raise ValueError("matched control has fewer than 50 cells")
        kept = {
            label
            for label, count in count_by_label.items()
            if label != control_label and count >= MIN_CELLS
        }
        if not kept:
            raise ValueError("no perturbation has at least 50 cells")
        retained = kept | {control_label}
        chunks: dict[str, list[np.ndarray]] = {label: [] for label in retained}
        for start in range(0, data.n_obs, CHUNK_ROWS):
            stop = min(start + CHUNK_ROWS, data.n_obs)
            local_mask = selected_rows[start:stop]
            local_labels = labels[start:stop]
            wanted = local_mask & np.isin(local_labels, tuple(retained))
            if not wanted.any():
                continue
            block = data.X[start:stop]
            retained_values = block[wanted]
            retained_values = (
                retained_values.data
                if sparse.issparse(retained_values)
                else np.asarray(retained_values)
            )
            if (
                not np.all(np.isfinite(retained_values))
                or np.any(retained_values < 0)
                or not np.allclose(
                    retained_values,
                    np.rint(retained_values),
                    rtol=0.0,
                    atol=1e-6,
                )
            ):
                raise ValueError("h5ad X must contain finite non-negative raw counts")
            library_sizes = np.asarray(block.sum(axis=1)).reshape(-1)
            if np.any(library_sizes[wanted] <= 0):
                raise ValueError("every retained cell needs a positive library size")
            safe_library_sizes = library_sizes.copy()
            safe_library_sizes[safe_library_sizes <= 0] = 1.0
            scores = _pathway_scores(
                block[:, columns], safe_library_sizes, membership
            )
            for label in retained:
                label_mask = wanted & (local_labels == label)
                if label_mask.any():
                    chunks[label].append(scores[label_mask])
    finally:
        data.file.close()

    arrays = {label: np.concatenate(parts) for label, parts in chunks.items()}
    control = arrays.pop(control_label)
    control_mean = control.mean(axis=0, dtype=np.float64)
    dims = list(hallmark_sets)
    reliability = _split_half_reliability(control, arrays)
    payload = {
        "schema_version": CONTEXT_BUNDLE_SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "context_id": context_id,
        "perturbation_type": "crispri",
        "scientific_boundary": (
            "Public-data pathway-level CRISPRi response; not a biological or clinical validation."
        ),
        "source": {
            "path": h5ad_path.name,
            "sha256": file_sha256(h5ad_path),
            "bytes": h5ad_path.stat().st_size,
            "license": source_license,
            "rights_verified": True,
        },
        "hallmark_source": {
            "path": hallmark_path.name,
            "sha256": file_sha256(hallmark_path),
            "version": hallmark_version,
            "license": hallmark_license,
            "rights_verified": True,
        },
        "normalization": {
            "library_size_scale": 10000.0,
            "transform": "log2(1+x)",
            "aggregation": "per-cell-transform-then-mean",
            "effect": "perturbed-minus-matched-control",
        },
        "dims": dims,
        "control": {
            "cells": len(control),
            "vector": dict(zip(dims, map(float, control_mean))),
        },
        "units": [
            {
                "gene": gene,
                "cells": len(values),
                "target": dict(
                    zip(dims, map(float, values.mean(axis=0, dtype=np.float64) - control_mean))
                ),
            }
            for gene, values in sorted(arrays.items())
        ],
        "reliability": {
            "resamples": RESAMPLES,
            "seed": SEED,
            "median_split_half_spearman": reliability,
        },
    }
    write_json_once(output_path, payload, artifact="context pathway bundle")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h5ad", required=True)
    parser.add_argument("--hallmark", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--context-id", required=True, choices=DEVELOPMENT_CONTEXTS)
    parser.add_argument("--perturbation-key", required=True)
    parser.add_argument("--gene-key")
    parser.add_argument("--control-label", required=True)
    parser.add_argument("--context-key")
    parser.add_argument("--context-value")
    parser.add_argument("--source-license", required=True)
    parser.add_argument("--hallmark-version", required=True)
    parser.add_argument("--hallmark-license", required=True)
    parser.add_argument("--rights-verified", action="store_true")
    args = parser.parse_args()
    if not args.rights_verified:
        raise SystemExit("--rights-verified is required after checking source terms")
    result = build_bundle(
        Path(args.h5ad),
        Path(args.hallmark),
        Path(args.output),
        dataset_id=args.dataset_id,
        context_id=args.context_id,
        perturbation_key=args.perturbation_key,
        gene_key=args.gene_key,
        control_label=args.control_label,
        source_license=args.source_license,
        hallmark_version=args.hallmark_version,
        hallmark_license=args.hallmark_license,
        context_key=args.context_key,
        context_value=args.context_value,
    )
    print(json.dumps({
        "schema_version": result["schema_version"],
        "context_id": result["context_id"],
        "units": len(result["units"]),
        "reliability": result["reliability"]["median_split_half_spearman"],
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
