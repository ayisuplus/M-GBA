#!/usr/bin/env python
"""ADR-0042 empirical segment: Norman GEO-native files -> log2FC bundle.

Runs ONLY in the independent training venv (``.venv-train``). Frozen by
ADR-0042 before any expression value is computed:

- QC: ``good_coverage == True`` in the cell identities table;
- guide rollup: parts split on ``__`` then ``_``; tokens starting with
  ``NegCtrl`` are control markers; all-marker cells -> unit ``control``;
  otherwise ordered unique gene tokens (first appearance) joined by ``_``;
- normalization: library size 1e4 -> log2(1+x); unit mean - control mean;
- units keep >= 50 QC cells; gene universe = Hallmark v2026.1 union.

Output: ``mgba-aivc-empirical-log2fc-0.1`` JSON under ``data/aivc/A3-norman2019-geo/``.
"""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd

SCHEMA_VERSION = "mgba-aivc-empirical-log2fc-0.1"
DATASET_ID = "norman-weissman-2019-geo-native"
GEO_ACCESSION = "GSE133344"
QC_FLAG = "good_coverage"
CONTROL_LABEL = "control"
MIN_CELLS = 50
LIBRARY_SIZE_SCALE = 1e4
NORMALIZATION = "library-size-1e4-log2(1+x)-unit-mean"
LOG2FC_RULE = "log2fc = unit_mean_log2 - control_mean_log2"


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


def rollup_unit(guide_identity: str) -> str:
    """Frozen guide_identity -> gene-level unit rule (ADR-0042 §3)."""
    genes: list[str] = []
    for part in guide_identity.split("__"):
        for token in part.split("_"):
            if token.startswith("NegCtrl"):
                continue
            if token and token not in genes:
                genes.append(token)
    return CONTROL_LABEL if not genes else "_".join(genes)


def build_bundle(matrix_path: Path, barcodes_path: Path, genes_path: Path, identities_path: Path, gmt_path: Path) -> dict:
    universe = load_hallmark_universe(gmt_path)

    identities = pd.read_csv(identities_path)
    for column in ("cell_barcode", "guide_identity", "good_coverage"):
        if column not in identities.columns:
            raise ValueError(f"cell identities lack column {column}")
    identities = identities[identities["good_coverage"] == True]  # noqa: E712
    unit_of_barcode = dict(
        zip(identities["cell_barcode"], identities["guide_identity"].map(rollup_unit))
    )

    barcodes = pd.read_csv(barcodes_path, header=None, names=["barcode"])["barcode"]
    n_cells = len(barcodes)
    cell_unit_codes = np.full(n_cells, -1, dtype=np.int64)
    units_in_order: list[str] = []
    unit_index: dict[str, int] = {}
    for row, barcode in enumerate(barcodes):
        unit = unit_of_barcode.get(barcode)
        if unit is None:
            continue
        if unit not in unit_index:
            unit_index[unit] = len(units_in_order)
            units_in_order.append(unit)
        cell_unit_codes[row] = unit_index[unit]

    counts = np.bincount(
        cell_unit_codes[cell_unit_codes >= 0], minlength=len(units_in_order)
    )
    if CONTROL_LABEL not in unit_index:
        raise ValueError("no control cells after the frozen rollup")
    control_index = unit_index[CONTROL_LABEL]
    if counts[control_index] < MIN_CELLS:
        raise ValueError("control has fewer than 50 QC cells")
    kept = [
        index
        for index, unit in enumerate(units_in_order)
        if index != control_index and counts[index] >= MIN_CELLS
    ]
    if not kept:
        raise ValueError("no perturbation unit passes the frozen >=50 rule")

    genes_df = pd.read_csv(genes_path, sep="\t", header=None, names=["ensembl", "symbol"])
    n_gene_rows = len(genes_df)
    # Frozen by ADR-0042 §3: symbols with duplicate Ensembl rows are dropped as
    # a group (34 such symbols in GSE133344); never a "first row wins" pick.
    # MatrixMarket row positions refer to the ORIGINAL file order, so dropped
    # rows keep their positions (no reindexing).
    duplicated = genes_df["symbol"].duplicated(keep=False)
    genes_df = genes_df[~duplicated]
    gene_row_of_symbol = dict(zip(genes_df["symbol"], genes_df.index))
    universe_rows = sorted(
        {gene_row_of_symbol[gene] for gene in universe if gene in gene_row_of_symbol}
    )
    if not universe_rows:
        raise ValueError("no Hallmark universe gene present in genes.tsv")
    universe_genes = [genes_df.loc[row, "symbol"] for row in universe_rows]
    universe_row_set = np.zeros(n_gene_rows, dtype=bool)
    universe_row_set[universe_rows] = True

    entries = pd.read_csv(
        matrix_path,
        sep=" ",
        comment="%",
        header=None,
        names=["gene", "cell", "value"],
        dtype={"gene": np.int32, "cell": np.int32, "value": np.float64},
    )
    cells = entries["cell"].to_numpy() - 1  # MatrixMarket is 1-based
    genes_idx = entries["gene"].to_numpy() - 1
    values = entries["value"].to_numpy()
    if (values < 0).any():
        raise ValueError("MatrixMarket counts must be non-negative")

    libsize = np.bincount(cells, weights=values, minlength=n_cells)
    if (libsize <= 0).any():
        raise ValueError("every cell needs a positive library size")

    mask = universe_row_set[genes_idx]
    cells_u = cells[mask]
    genes_u = genes_idx[mask]
    values_u = values[mask]
    normalized = np.log2(1.0 + LIBRARY_SIZE_SCALE * values_u / libsize[cells_u])
    unit_codes = cell_unit_codes[cells_u]

    n_units = len(units_in_order)
    slot_of_gene = np.full(n_gene_rows, -1, dtype=np.int64)
    slot_of_gene[universe_rows] = np.arange(len(universe_rows), dtype=np.int64)
    gene_slots = slot_of_gene[genes_u]

    # Only entries from cells with an assigned unit (code >= 0) may contribute;
    # np.add.at with a -1 index would pollute the last row.
    valid = unit_codes >= 0
    sums = np.zeros((n_units, len(universe_rows)), dtype=np.float64)
    np.add.at(sums, (unit_codes[valid], gene_slots[valid]), normalized[valid])

    control_means = sums[control_index] / float(counts[control_index])
    units = []
    for index in kept:
        means = sums[index] / float(counts[index])
        log2fc = means - control_means
        units.append(
            {
                "unit": units_in_order[index],
                "cells": int(counts[index]),
                "log2fc": [float(value) for value in log2fc],
            }
        )
    units.sort(key=lambda item: item["unit"])

    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "source": {
            "path": matrix_path.name,
            "sha256": _sha256_file(matrix_path),
            "bytes": matrix_path.stat().st_size,
            "license": "GEO public data",
            "rights_verified": True,
            "zenodo_doi": f"GEO:{GEO_ACCESSION}",
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
            "description": "MSigDB v2026.1 Hallmark 50-set symbol union intersected with genes.tsv",
            "genes": universe_genes,
        },
        "control_cells": int(counts[control_index]),
        "units": units,
        "auxiliary_sources": {
            "barcodes_sha256": _sha256_file(barcodes_path),
            "genes_sha256": _sha256_file(genes_path),
            "cell_identities_sha256": _sha256_file(identities_path),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", required=True)
    parser.add_argument("--barcodes", required=True)
    parser.add_argument("--genes", required=True)
    parser.add_argument("--identities", required=True)
    parser.add_argument("--hallmark", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing bundle: {output}")
    bundle = build_bundle(
        Path(args.matrix),
        Path(args.barcodes),
        Path(args.genes),
        Path(args.identities),
        Path(args.hallmark),
    )
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
