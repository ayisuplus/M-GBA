#!/usr/bin/env python
"""ADR-0039 empirical segment: Replogle K562 essential h5ad -> KD log2FC bundle.

Runs ONLY in the independent training venv (``.venv-train``) with h5py/numpy.
Frozen by ADR-0039 before any expression value is computed:

- no extra QC filtering (the harmonized release has no good_coverage flag);
- control: perturbation label exactly ``control``;
- units: perturbation strings with >= 50 cells (1,833 of 2,058 pass);
- normalization: per-cell library size scaled to 1e4, then log2(1+x);
  unit score = mean over the unit's cells; log2FC = unit - control;
- gene universe: MSigDB v2026.1 Hallmark 50-set symbol union intersected with
  var.gene_name (2,377 genes; coverage fact frozen before computing).

Output: ``mgba-aivc-empirical-log2fc-0.1`` JSON under ``data/aivc/B2-replogle2022/``.
"""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

import h5py
import numpy as np

SCHEMA_VERSION = "mgba-aivc-empirical-log2fc-0.1"
DATASET_ID = "replogle-2022-k562-essential-scperturb"
ZENODO_DOI = "10.5281/zenodo.7041849"
QC_FLAG = "none-filtered-release"
CONTROL_LABEL = "control"
MIN_CELLS = 50
LIBRARY_SIZE_SCALE = 1e4
NORMALIZATION = "library-size-1e4-log2(1+x)-unit-mean"
LOG2FC_RULE = "log2fc = unit_mean_log2 - control_mean_log2"
LIBSIZE_CHUNK_ROWS = 20_000


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decode(value) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def load_hallmark_universe(gmt_path: Path) -> list[str]:
    genes: set[str] = set()
    with gmt_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            columns = line.rstrip("\n").split("\t")
            if len(columns) < 3 or not columns[0].startswith("HALLMARK_"):
                raise ValueError(f"invalid Hallmark GMT row: {columns[:1]}")
            genes.update(gene for gene in columns[2:] if gene)
    if not genes:
        raise ValueError("Hallmark GMT produced an empty universe")
    return sorted(genes)


def build_bundle(h5ad_path: Path, gmt_path: Path) -> dict:
    universe = load_hallmark_universe(gmt_path)
    with h5py.File(h5ad_path, "r") as handle:
        x_ds = handle["X"]
        n_cells, n_genes = (int(v) for v in x_ds.shape)
        gene_names = [_decode(v) for v in handle["var/gene_name"][:]]
        if len(set(gene_names)) != len(gene_names):
            raise ValueError("var.gene_name must be unique")
        categories = [_decode(v) for v in handle["obs/perturbation/categories"][:]]
        codes = handle["obs/perturbation/codes"][:].astype(np.int64)

        # Library size per cell over every gene, chunked row-wise.
        libsize = np.zeros(n_cells, dtype=np.float64)
        for start in range(0, n_cells, LIBSIZE_CHUNK_ROWS):
            block = x_ds[start : start + LIBSIZE_CHUNK_ROWS, :]
            libsize[start : start + block.shape[0]] = block.sum(axis=1)
        if (libsize <= 0).any():
            raise ValueError("every cell needs a positive library size")

        position = {name: column for column, name in enumerate(gene_names)}
        universe_columns = [position[gene] for gene in universe if gene in position]
        if not universe_columns:
            raise ValueError("no Hallmark universe gene present in var.gene_name")
        universe_columns.sort()
        universe_genes = [gene_names[column] for column in universe_columns]
        sub = x_ds[:, universe_columns].astype(np.float64)

    control_code = categories.index(CONTROL_LABEL) if CONTROL_LABEL in categories else -1
    if control_code < 0:
        raise ValueError("control label missing from perturbation categories")
    counts = np.bincount(codes, minlength=len(categories))
    if counts[control_code] < MIN_CELLS:
        raise ValueError("control has fewer than 50 cells")
    kept = [
        code
        for code, unit in enumerate(categories)
        if code != control_code and counts[code] >= MIN_CELLS
    ]
    if not kept:
        raise ValueError("no perturbation unit passes the frozen >=50 rule")

    normalized = np.log2(1.0 + LIBRARY_SIZE_SCALE * sub / libsize[:, None])
    order = np.argsort(codes, kind="stable")
    sorted_codes = codes[order]
    normalized = normalized[order, :]
    # Rows are contiguous per perturbation after the sort; slice, never mask.
    starts = np.searchsorted(sorted_codes, np.arange(len(categories)))

    control_rows = normalized[starts[control_code] : starts[control_code] + counts[control_code]]
    control_means = control_rows.mean(axis=0)

    units = []
    for code in kept:
        rows = normalized[starts[code] : starts[code] + counts[code]]
        means = rows.mean(axis=0)
        log2fc = means - control_means
        units.append(
            {
                "unit": categories[int(code)],
                "cells": int(counts[code]),
                "log2fc": [float(value) for value in log2fc],
            }
        )
    units.sort(key=lambda item: item["unit"])

    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "source": {
            "path": h5ad_path.name,
            "sha256": _sha256_file(h5ad_path),
            "bytes": h5ad_path.stat().st_size,
            "license": "CC BY 4.0",
            "rights_verified": True,
            "zenodo_doi": ZENODO_DOI,
        },
        "hallmark_source": {
            "path": gmt_path.name,
            "sha256": _sha256_file(gmt_path),
            "bytes": gmt_path.stat().st_size,
            "version": "MSigDB v2026.1",
            "license": "MSigDB terms (no redistribution)",
            "rights_verified": True,
        },
        "parameters": {
            "qc_flag": QC_FLAG,
            "control_label": CONTROL_LABEL,
            "min_cells": MIN_CELLS,
            "library_size_scale": LIBRARY_SIZE_SCALE,
            "normalization": NORMALIZATION,
            "log2fc_rule": LOG2FC_RULE,
        },
        "gene_universe": {
            "description": "MSigDB v2026.1 Hallmark 50-set symbol union intersected with var.gene_name",
            "genes": universe_genes,
        },
        "control_cells": int(counts[control_code]),
        "units": units,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h5ad", required=True, help="Replogle scPerturb h5ad path")
    parser.add_argument("--hallmark", required=True, help="Hallmark symbols GMT path")
    parser.add_argument("--output", required=True, help="empirical bundle JSON output")
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing bundle: {output}")
    bundle = build_bundle(Path(args.h5ad), Path(args.hallmark))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle), encoding="utf-8")
    print(
        json.dumps(
            {
                "schema_version": bundle["schema_version"],
                "units": len(bundle["units"]),
                "universe_genes": len(bundle["gene_universe"]["genes"]),
                "control_cells": bundle["control_cells"],
                "output": str(output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
