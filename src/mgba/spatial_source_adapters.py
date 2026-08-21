"""Source-format adapters for the pre-registered CAR-M spatial anchors.

The adapters live outside the L0--L4 runtime.  They verify the licensed source
artifacts named by a local manifest, translate selected raw tables into the
temporary observation-bundle contract, and stop there.  No external value is
fed into a model tick and no raw identifier is written to a derived target.
"""

from __future__ import annotations

import csv
import gzip
import json
import math
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any, Iterable, Mapping, TextIO

from .spatial_anchors import (
    OBSERVATION_SCHEMA_VERSION,
    load_spatial_observation_bundle,
)


SOURCE_PROTOCOL_SCHEMA_VERSION = "mgba-spatial-source-protocol-0.1"
WU_MANIFEST_SCHEMA_VERSION = "mgba-wu-visium-source-manifest-0.1"
JACKSON_MANIFEST_SCHEMA_VERSION = "mgba-jackson-imc-source-manifest-0.1"


def _exact_keys(raw: Mapping[str, Any], expected: set[str], *, name: str) -> None:
    keys = set(raw)
    if keys != expected:
        raise ValueError(
            f"{name} keys differ; "
            f"missing={sorted(expected - keys)}, extra={sorted(keys - expected)}"
        )


def _text(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _positive_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _finite(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _sha256_text(value: Any, *, name: str) -> str:
    result = _text(value, name=name).lower()
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    return result


def _read_object(path: Path, *, name: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {name}: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError(f"{name} root must be an object")
    return raw


def _local_path(root: Path, value: Any, *, name: str) -> Path:
    relative = Path(_text(value, name=name))
    if relative.is_absolute():
        raise ValueError(f"{name} must be relative to its manifest")
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"{name} escapes its manifest directory") from error
    if not resolved.is_file():
        raise ValueError(f"{name} does not exist: {relative.as_posix()}")
    return resolved


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_artifacts(
    raw: Any, *, root: Path
) -> tuple[list[dict[str, Any]], set[Path]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("source_artifacts must be a non-empty list")
    result: list[dict[str, Any]] = []
    file_ids: set[str] = set()
    paths: set[Path] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"source_artifacts[{index}] must be an object")
        _exact_keys(
            item,
            {
                "path",
                "file_id",
                "sha256",
                "bytes",
                "license",
                "rights_verified",
            },
            name=f"source_artifacts[{index}]",
        )
        file_id = _text(item["file_id"], name=f"source_artifacts[{index}].file_id")
        digest = _sha256_text(
            item["sha256"], name=f"source_artifacts[{index}].sha256"
        )
        byte_count = _positive_int(
            item["bytes"], name=f"source_artifacts[{index}].bytes"
        )
        license_name = _text(
            item["license"], name=f"source_artifacts[{index}].license"
        )
        if item["rights_verified"] is not True:
            raise ValueError("every source artifact needs explicit rights verification")
        source_path = _local_path(
            root, item["path"], name=f"source_artifacts[{index}].path"
        )
        if source_path.stat().st_size != byte_count:
            raise ValueError(f"source artifact byte count mismatch: {file_id}")
        if _file_sha256(source_path) != digest:
            raise ValueError(f"source artifact SHA-256 mismatch: {file_id}")
        if file_id in file_ids or source_path in paths:
            raise ValueError("source artifact ids and local paths must be unique")
        file_ids.add(file_id)
        paths.add(source_path)
        result.append(
            {
                "file_id": file_id,
                "sha256": digest,
                "bytes": byte_count,
                "license": license_name,
                "rights_verified": True,
            }
        )
    # Identical extracted files (especially features.tsv) are legitimate.
    # Verify every path above, then retain one deterministic provenance record
    # per content digest because the downstream target contract is content based.
    by_digest: dict[str, dict[str, Any]] = {}
    for item in sorted(result, key=lambda value: value["file_id"]):
        by_digest.setdefault(item["sha256"], item)
    return sorted(by_digest.values(), key=lambda item: item["file_id"]), paths


def _open_text(path: Path) -> TextIO:
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def _read_lines(path: Path) -> list[str]:
    with _open_text(path) as handle:
        return [line.rstrip("\r\n") for line in handle if line.rstrip("\r\n")]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with _open_text(path) as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path.name}")
        return [
            {str(key): "" if value is None else value.strip() for key, value in row.items()}
            for row in reader
        ]


def _column(row: Mapping[str, str], name: str, *, table: str) -> str:
    if name not in row:
        raise ValueError(f"missing column {name!r} in {table}")
    return row[name].strip()


def _normalize(values: Iterable[float], *, name: str) -> list[float]:
    raw = list(values)
    low, high = min(raw), max(raw)
    if high <= low:
        raise ValueError(f"{name} must span a non-zero range")
    return [(value - low) / (high - low) for value in raw]


def _write_bundle(path: str | Path, payload: Mapping[str, Any]) -> Path:
    output = Path(path)
    encoded = json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
    ) + "\n"
    if output.exists():
        try:
            if output.read_text(encoding="utf-8") == encoded:
                return output
        except OSError as error:
            raise ValueError(f"cannot inspect observation bundle: {error}") from error
        raise ValueError("refusing to overwrite a different observation bundle")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded, encoding="utf-8")
    # Reuse the strict downstream parser as the final adapter boundary.
    load_spatial_observation_bundle(output)
    return output


def load_spatial_source_protocol(path: str | Path) -> dict[str, Any]:
    raw = _read_object(Path(path), name="spatial source protocol")
    _exact_keys(
        raw,
        {
            "schema_version",
            "model_version",
            "field_dataset_id",
            "neighborhood_dataset_id",
            "library_size_scale",
            "feature_symbol_column",
            "min_genes_per_channel",
            "field_channels",
        },
        name="spatial source protocol",
    )
    if raw["schema_version"] != SOURCE_PROTOCOL_SCHEMA_VERSION:
        raise ValueError("unsupported spatial source protocol schema")
    _text(raw["model_version"], name="model_version")
    _text(raw["field_dataset_id"], name="field_dataset_id")
    _text(raw["neighborhood_dataset_id"], name="neighborhood_dataset_id")
    scale = _finite(raw["library_size_scale"], name="library_size_scale")
    if scale <= 0.0:
        raise ValueError("library_size_scale must be positive")
    feature_column = raw["feature_symbol_column"]
    if isinstance(feature_column, bool) or not isinstance(feature_column, int) or feature_column < 0:
        raise ValueError("feature_symbol_column must be a non-negative integer")
    minimum = _positive_int(raw["min_genes_per_channel"], name="min_genes_per_channel")
    channels = raw["field_channels"]
    if not isinstance(channels, dict) or set(channels) != {"stress", "resource", "signal"}:
        raise ValueError("field_channels must contain exactly stress/resource/signal")
    normalized_channels: dict[str, list[str]] = {}
    for channel in ("stress", "resource", "signal"):
        genes = channels[channel]
        if not isinstance(genes, list):
            raise ValueError(f"field_channels.{channel} must be a list")
        cleaned = [_text(gene, name=f"field_channels.{channel} gene").upper() for gene in genes]
        if len(cleaned) != len(set(cleaned)) or len(cleaned) < minimum:
            raise ValueError(f"field_channels.{channel} is duplicate or too small")
        normalized_channels[channel] = cleaned
    result = dict(raw)
    result["field_channels"] = normalized_channels
    return result


def _read_positions(
    path: Path,
    *,
    barcode_column: str,
    in_tissue_column: str,
    x_column: str,
    y_column: str,
) -> dict[str, tuple[float, float]]:
    with _open_text(path) as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise ValueError(f"positions file is empty: {path.name}")
    headerless = rows[0][0].strip().lower() != barcode_column.lower()
    if headerless:
        if len(rows[0]) != 6:
            raise ValueError("headerless Visium positions must have six columns")
        names = [
            "barcode",
            "in_tissue",
            "array_row",
            "array_col",
            "pxl_row_in_fullres",
            "pxl_col_in_fullres",
        ]
        records = [dict(zip(names, row, strict=True)) for row in rows]
    else:
        names = [value.strip() for value in rows[0]]
        records = [dict(zip(names, row, strict=True)) for row in rows[1:]]
    result: dict[str, tuple[float, float]] = {}
    for record in records:
        barcode = _column(record, barcode_column, table=path.name)
        if _column(record, in_tissue_column, table=path.name) not in {"1", "true", "TRUE"}:
            continue
        if not barcode or barcode in result:
            raise ValueError(f"blank or duplicate barcode in {path.name}")
        result[barcode] = (
            _finite(float(_column(record, x_column, table=path.name)), name="position x"),
            _finite(float(_column(record, y_column, table=path.name)), name="position y"),
        )
    if not result:
        raise ValueError(f"positions file has no in-tissue spots: {path.name}")
    return result


def _read_regions(
    path: Path,
    *,
    barcode_column: str,
    region_column: str,
    region_map: Mapping[str, Any],
) -> dict[str, str]:
    rows = _read_csv(path)
    mapped: dict[str, str] = {}
    normalized_map = {
        _text(source, name="region_map key"): _text(target, name="region_map value")
        for source, target in region_map.items()
    }
    if len(set(normalized_map.values())) < 2:
        raise ValueError("region_map must produce at least two aggregate regions")
    for row in rows:
        barcode = _column(row, barcode_column, table=path.name)
        raw_region = _column(row, region_column, table=path.name)
        if raw_region not in normalized_map:
            continue
        if not barcode or barcode in mapped:
            raise ValueError(f"blank or duplicate mapped barcode in {path.name}")
        mapped[barcode] = normalized_map[raw_region]
    return mapped


def _read_10x_scores(
    *,
    matrix_path: Path,
    features_path: Path,
    barcodes_path: Path,
    retained_barcodes: set[str],
    protocol: Mapping[str, Any],
) -> dict[str, dict[str, float]]:
    barcodes = [line.split("\t", 1)[0] for line in _read_lines(barcodes_path)]
    if len(barcodes) != len(set(barcodes)):
        raise ValueError("10x barcodes must be unique")
    retained_columns = {
        index + 1: barcode
        for index, barcode in enumerate(barcodes)
        if barcode in retained_barcodes
    }
    if set(retained_columns.values()) != retained_barcodes:
        missing = sorted(retained_barcodes - set(retained_columns.values()))
        raise ValueError(f"region/position barcodes missing from 10x matrix: {missing[:3]}")

    feature_column = int(protocol["feature_symbol_column"])
    features = []
    for line in _read_lines(features_path):
        columns = line.split("\t")
        if feature_column >= len(columns):
            raise ValueError("feature_symbol_column exceeds a features.tsv row")
        features.append(columns[feature_column].strip().upper())
    requested = {
        gene
        for genes in protocol["field_channels"].values()
        for gene in genes
    }
    selected_rows: dict[int, str] = {
        index + 1: gene for index, gene in enumerate(features) if gene in requested
    }
    present_genes = set(selected_rows.values())
    for channel, genes in protocol["field_channels"].items():
        found = present_genes.intersection(genes)
        if len(found) < int(protocol["min_genes_per_channel"]):
            raise ValueError(
                f"{channel} has only {len(found)} genes in the feature table; "
                f"minimum is {protocol['min_genes_per_channel']}"
            )

    totals = {barcode: 0.0 for barcode in retained_barcodes}
    counts = {
        gene: {barcode: 0.0 for barcode in retained_barcodes}
        for gene in present_genes
    }
    dimensions_seen = False
    with _open_text(matrix_path) as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("%"):
                continue
            columns = stripped.split()
            if not dimensions_seen:
                if len(columns) != 3:
                    raise ValueError("MatrixMarket dimensions row must have three fields")
                rows, cols, _entries = (int(value) for value in columns)
                if rows != len(features) or cols != len(barcodes):
                    raise ValueError("MatrixMarket dimensions disagree with features/barcodes")
                dimensions_seen = True
                continue
            if len(columns) != 3:
                raise ValueError("MatrixMarket entry must have three fields")
            row_index, column_index = int(columns[0]), int(columns[1])
            value = _finite(float(columns[2]), name="MatrixMarket count")
            if value < 0.0:
                raise ValueError("MatrixMarket counts must be non-negative")
            barcode = retained_columns.get(column_index)
            if barcode is None:
                continue
            totals[barcode] += value
            gene = selected_rows.get(row_index)
            if gene is not None:
                counts[gene][barcode] += value
    if not dimensions_seen:
        raise ValueError("MatrixMarket dimensions row is missing")
    if any(total <= 0.0 for total in totals.values()):
        raise ValueError("every retained spot needs a positive library size")

    scale = float(protocol["library_size_scale"])
    standardized: dict[str, dict[str, float]] = {}
    ordered_barcodes = sorted(retained_barcodes)
    for gene in sorted(present_genes):
        values = [
            math.log1p(scale * counts[gene][barcode] / totals[barcode])
            for barcode in ordered_barcodes
        ]
        mean = fmean(values)
        deviation = pstdev(values)
        standardized[gene] = {
            barcode: (value - mean) / deviation if deviation > 0.0 else 0.0
            for barcode, value in zip(ordered_barcodes, values, strict=True)
        }

    result: dict[str, dict[str, float]] = {}
    for barcode in ordered_barcodes:
        channels: dict[str, float] = {}
        for channel in ("stress", "resource", "signal"):
            available = [
                gene
                for gene in protocol["field_channels"][channel]
                if gene in standardized
            ]
            module_z = fmean(standardized[gene][barcode] for gene in available)
            clipped = max(-60.0, min(60.0, module_z))
            channels[channel] = 1.0 / (1.0 + math.exp(-clipped))
        result[barcode] = channels
    return result


def adapt_wu_visium_source(
    manifest_path: str | Path,
    *,
    protocol_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Adapt six manifested 10x Visium samples into a field bundle."""

    manifest_file = Path(manifest_path)
    raw = _read_object(manifest_file, name="Wu Visium source manifest")
    _exact_keys(
        raw,
        {"schema_version", "dataset_id", "source_artifacts", "samples"},
        name="Wu Visium source manifest",
    )
    if raw["schema_version"] != WU_MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported Wu Visium source manifest schema")
    protocol = load_spatial_source_protocol(protocol_path)
    if raw["dataset_id"] != protocol["field_dataset_id"]:
        raise ValueError("Wu manifest dataset_id disagrees with source protocol")
    artifacts, verified_paths = _verified_artifacts(
        raw["source_artifacts"], root=manifest_file.parent
    )
    if not isinstance(raw["samples"], list) or len(raw["samples"]) != 6:
        raise ValueError("Wu Visium manifest must contain exactly six samples")

    samples = []
    used_paths: set[Path] = set()
    for index, item in enumerate(raw["samples"]):
        if not isinstance(item, dict):
            raise ValueError(f"samples[{index}] must be an object")
        _exact_keys(
            item,
            {
                "sample_id",
                "matrix_path",
                "features_path",
                "barcodes_path",
                "positions_path",
                "regions_path",
                "position_barcode_column",
                "position_in_tissue_column",
                "position_x_column",
                "position_y_column",
                "region_barcode_column",
                "region_value_column",
                "region_map",
            },
            name=f"samples[{index}]",
        )
        sample_id = _text(item["sample_id"], name=f"samples[{index}].sample_id")
        if not isinstance(item["region_map"], dict):
            raise ValueError(f"samples[{index}].region_map must be an object")
        positions_path = _local_path(
            manifest_file.parent, item["positions_path"], name="positions_path"
        )
        regions_path = _local_path(
            manifest_file.parent, item["regions_path"], name="regions_path"
        )
        matrix_path = _local_path(
            manifest_file.parent, item["matrix_path"], name="matrix_path"
        )
        features_path = _local_path(
            manifest_file.parent, item["features_path"], name="features_path"
        )
        barcodes_path = _local_path(
            manifest_file.parent, item["barcodes_path"], name="barcodes_path"
        )
        used_paths.update(
            {positions_path, regions_path, matrix_path, features_path, barcodes_path}
        )
        positions = _read_positions(
            positions_path,
            barcode_column=_text(item["position_barcode_column"], name="position_barcode_column"),
            in_tissue_column=_text(item["position_in_tissue_column"], name="position_in_tissue_column"),
            x_column=_text(item["position_x_column"], name="position_x_column"),
            y_column=_text(item["position_y_column"], name="position_y_column"),
        )
        regions = _read_regions(
            regions_path,
            barcode_column=_text(item["region_barcode_column"], name="region_barcode_column"),
            region_column=_text(item["region_value_column"], name="region_value_column"),
            region_map=item["region_map"],
        )
        retained = set(positions).intersection(regions)
        if len(retained) < 3 or len({regions[barcode] for barcode in retained}) < 2:
            raise ValueError(f"sample {sample_id} needs at least three mapped spots and two regions")
        scores = _read_10x_scores(
            matrix_path=matrix_path,
            features_path=features_path,
            barcodes_path=barcodes_path,
            retained_barcodes=retained,
            protocol=protocol,
        )
        ordered = sorted(retained)
        xs = _normalize((positions[barcode][0] for barcode in ordered), name=f"{sample_id} x")
        ys = _normalize((positions[barcode][1] for barcode in ordered), name=f"{sample_id} y")
        observations = [
            {
                "observation_id": barcode,
                "x": x,
                "y": y,
                "region": regions[barcode],
                "channels": scores[barcode],
            }
            for barcode, x, y in zip(ordered, xs, ys, strict=True)
        ]
        samples.append({"sample_id": sample_id, "observations": observations})

    missing_paths = used_paths - verified_paths
    if missing_paths:
        raise ValueError(
            "every file read by the Wu adapter must be a verified source artifact; "
            f"missing={[path.name for path in sorted(missing_paths)]}"
        )
    payload = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "dataset_id": protocol["field_dataset_id"],
        "modality": "field",
        "source_artifacts": artifacts,
        "samples": sorted(samples, key=lambda item: item["sample_id"]),
    }
    return _write_bundle(output_path, payload)


def adapt_jackson_imc_source(
    manifest_path: str | Path,
    *,
    protocol_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Adapt manifested IMC location/cluster CSV pairs into a neighborhood bundle."""

    manifest_file = Path(manifest_path)
    raw = _read_object(manifest_file, name="Jackson IMC source manifest")
    _exact_keys(
        raw,
        {"schema_version", "dataset_id", "source_artifacts", "tables"},
        name="Jackson IMC source manifest",
    )
    if raw["schema_version"] != JACKSON_MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported Jackson IMC source manifest schema")
    protocol = load_spatial_source_protocol(protocol_path)
    if raw["dataset_id"] != protocol["neighborhood_dataset_id"]:
        raise ValueError("Jackson manifest dataset_id disagrees with source protocol")
    artifacts, verified_paths = _verified_artifacts(
        raw["source_artifacts"], root=manifest_file.parent
    )
    if not isinstance(raw["tables"], list) or not raw["tables"]:
        raise ValueError("Jackson IMC manifest needs at least one table pair")

    grouped: dict[str, list[tuple[str, float, float, str]]] = defaultdict(list)
    used_paths: set[Path] = set()
    for index, item in enumerate(raw["tables"]):
        if not isinstance(item, dict):
            raise ValueError(f"tables[{index}] must be an object")
        _exact_keys(
            item,
            {
                "table_id",
                "locations_path",
                "labels_path",
                "location_sample_column",
                "location_cell_column",
                "x_column",
                "y_column",
                "label_sample_column",
                "label_cell_column",
                "label_column",
                "label_map",
            },
            name=f"tables[{index}]",
        )
        table_id = _text(item["table_id"], name=f"tables[{index}].table_id")
        if not isinstance(item["label_map"], dict) or not item["label_map"]:
            raise ValueError(f"tables[{index}].label_map must be a non-empty object")
        label_map = {
            _text(source, name="label_map key"): _text(target, name="label_map value")
            for source, target in item["label_map"].items()
        }
        if not set(label_map.values()).issubset({"immune", "other", "tumor"}):
            raise ValueError("label_map values must be immune/other/tumor")
        locations_path = _local_path(
            manifest_file.parent, item["locations_path"], name="locations_path"
        )
        labels_path = _local_path(
            manifest_file.parent, item["labels_path"], name="labels_path"
        )
        used_paths.update({locations_path, labels_path})
        labels: dict[tuple[str, str], str] = {}
        for row in _read_csv(labels_path):
            key = (
                _column(row, _text(item["label_sample_column"], name="label_sample_column"), table=labels_path.name),
                _column(row, _text(item["label_cell_column"], name="label_cell_column"), table=labels_path.name),
            )
            raw_label = _column(
                row, _text(item["label_column"], name="label_column"), table=labels_path.name
            )
            if key in labels:
                raise ValueError(f"duplicate Jackson label key: {key}")
            if raw_label not in label_map:
                raise ValueError(f"unmapped Jackson cluster label: {raw_label!r}")
            labels[key] = label_map[raw_label]
        used: set[tuple[str, str]] = set()
        for row in _read_csv(locations_path):
            raw_sample = _column(
                row, _text(item["location_sample_column"], name="location_sample_column"), table=locations_path.name
            )
            cell_id = _column(
                row, _text(item["location_cell_column"], name="location_cell_column"), table=locations_path.name
            )
            key = (raw_sample, cell_id)
            if key not in labels:
                raise ValueError(f"Jackson location has no cluster label: {key}")
            if key in used:
                raise ValueError(f"duplicate Jackson location key: {key}")
            used.add(key)
            sample_id = f"{table_id}:{raw_sample}"
            grouped[sample_id].append(
                (
                    cell_id,
                    _finite(float(_column(row, _text(item["x_column"], name="x_column"), table=locations_path.name)), name="Jackson x"),
                    _finite(float(_column(row, _text(item["y_column"], name="y_column"), table=locations_path.name)), name="Jackson y"),
                    labels[key],
                )
            )
        if used != set(labels):
            raise ValueError("Jackson label table contains rows with no matching location")

    missing_paths = used_paths - verified_paths
    if missing_paths:
        raise ValueError(
            "every file read by the Jackson adapter must be a verified source artifact; "
            f"missing={[path.name for path in sorted(missing_paths)]}"
        )
    samples = []
    for sample_id in sorted(grouped):
        rows = sorted(grouped[sample_id], key=lambda item: item[0])
        labels = {item[3] for item in rows}
        if not {"immune", "tumor"}.issubset(labels):
            raise ValueError(f"Jackson sample {sample_id} needs immune and tumor cells")
        xs = _normalize((item[1] for item in rows), name=f"{sample_id} x")
        ys = _normalize((item[2] for item in rows), name=f"{sample_id} y")
        observations = [
            {
                "observation_id": cell_id,
                "x": x,
                "y": y,
                "label": label,
            }
            for (cell_id, _raw_x, _raw_y, label), x, y in zip(rows, xs, ys, strict=True)
        ]
        samples.append({"sample_id": sample_id, "observations": observations})

    payload = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "dataset_id": protocol["neighborhood_dataset_id"],
        "modality": "neighborhood",
        "source_artifacts": artifacts,
        "samples": samples,
    }
    return _write_bundle(output_path, payload)
