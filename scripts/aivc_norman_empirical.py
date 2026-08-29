#!/usr/bin/env python
"""ADR-0036 empirical segment: Norman h5ad -> bridge-scoped log2FC bundle.

Runs ONLY in the independent training venv (``.venv-train``) with h5py; the
core package never imports h5py. All processing rules are frozen by ADR-0036
before any expression value is computed:

- QC: keep cells with ``obs/good_coverage == True`` only;
- control: perturbation label exactly ``control``;
- units: full perturbation strings with >= 50 QC cells (all 237 pass);
- normalization: per-cell library size scaled to 1e4, then log2(1+x);
  unit score = mean over the unit's QC cells; log2FC = unit - control;
- gene universe: MSigDB v2026.1 Hallmark 50-set symbol union intersected with
  the h5ad var axis (bridge scope; not full transcriptome).

Output: ``mgba-aivc-empirical-log2fc-0.1`` JSON with full provenance. The file
stays under ``data/aivc/A2-scperturb/`` (landing zone, not committed).
"""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

import h5py
import numpy as np

SCHEMA_VERSION = "mgba-aivc-empirical-log2fc-0.1"
DATASET_ID = "norman-weissman-2019-scperturb-filtered"
ZENODO_DOI = "10.5281/zenodo.7041849"
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
    """Union of every Hallmark set's symbols in the GMT (sorted, unique)."""
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
        shape = handle["X"].attrs["shape"]
        n_cells, n_genes = int(shape[0]), int(shape[1])
        data = handle["X/data"][:]
        indices = handle["X/indices"][:]
        indptr = handle["X/indptr"][:]
        if indptr.shape[0] != n_genes + 1:
            raise ValueError("X must be a CSC matrix over genes")
        var_index = [_decode(v) for v in handle["var/_index"][:]]
        if len(set(var_index)) != len(var_index):
            raise ValueError("var gene symbols must be unique")
        categories = [_decode(v) for v in handle["obs/perturbation/categories"][:]]
        codes = handle["obs/perturbation/codes"][:].astype(np.int64)
        good = handle[f"obs/{QC_FLAG}"][:].astype(bool)

    qc_cells = np.flatnonzero(good)
    qc_codes = codes[qc_cells]
    if CONTROL_LABEL not in categories:
        raise ValueError("control label missing from perturbation categories")
    control_code = categories.index(CONTROL_LABEL)
    control_cells = qc_cells[qc_codes == control_code]
    if control_cells.shape[0] < MIN_CELLS:
        raise ValueError("control has fewer than 50 QC cells")

    kept: list[tuple[int, str, int]] = []  # (code, unit, cells)
    for code, unit in enumerate(categories):
        if code == control_code:
            continue
        cells = int((qc_codes == code).sum())
        if cells >= MIN_CELLS:
            kept.append((code, unit, cells))
    if not kept:
        raise ValueError("no perturbation unit passes the frozen >=50 rule")
    kept_codes = np.array([code for code, _, _ in kept], dtype=np.int64)

    # Per-cell library size over every gene (row sums of the CSC matrix).
    libsize = np.bincount(indices, weights=data, minlength=n_cells).astype(np.float64)
    if (libsize <= 0).any():
        raise ValueError("every cell needs a positive library size")

    var_position = {symbol: column for column, symbol in enumerate(var_index)}
    universe_columns = [
        (symbol, var_position[symbol]) for symbol in universe if symbol in var_position
    ]
    if not universe_columns:
        raise ValueError("no Hallmark universe gene present in var")

    n_units = len(kept)
    n_universe = len(universe_columns)
    unit_sums = np.zeros((n_units, n_universe), dtype=np.float64)
    control_sums = np.zeros(n_universe, dtype=np.float64)
    # Map every QC cell to its kept-unit slot (-1 = not a kept perturbation).
    slot_of_code = np.full(len(categories), -1, dtype=np.int64)
    for slot, (code, _unit, _cells) in enumerate(kept):
        slot_of_code[code] = slot
    cell_slot_by_row = np.full(n_cells, -1, dtype=np.int64)
    cell_slot_by_row[qc_cells] = slot_of_code[qc_codes]
    is_control = np.zeros(n_cells, dtype=bool)
    is_control[control_cells] = True

    for gene_slot, (_symbol, column) in enumerate(universe_columns):
        start, end = int(indptr[column]), int(indptr[column + 1])
        rows = indices[start:end]
        values = data[start:end].astype(np.float64)
        normalized = np.log2(1.0 + LIBRARY_SIZE_SCALE * values / libsize[rows])
        slots = cell_slot_by_row[rows]
        in_unit = slots >= 0
        if in_unit.any():
            np.add.at(unit_sums[:, gene_slot], slots[in_unit], normalized[in_unit])
        in_control = is_control[rows]
        if in_control.any():
            control_sums[gene_slot] += float(normalized[in_control].sum())

    control_means = control_sums / float(control_cells.shape[0])
    units = []
    for slot, (_code, unit, cells) in enumerate(kept):
        means = unit_sums[slot] / float(cells)
        log2fc = means - control_means
        units.append(
            {
                "unit": unit,
                "cells": cells,
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
            "description": "MSigDB v2026.1 Hallmark 50-set symbol union intersected with h5ad var",
            "genes": [symbol for symbol, _column in universe_columns],
        },
        "control_cells": int(control_cells.shape[0]),
        "units": units,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h5ad", required=True, help="Norman scPerturb h5ad path")
    parser.add_argument("--hallmark", required=True, help="Hallmark symbols GMT path")
    parser.add_argument("--output", required=True, help="empirical bundle JSON output")
    args = parser.parse_args()
    bundle = build_bundle(Path(args.h5ad), Path(args.hallmark))
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing bundle: {output}")
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
