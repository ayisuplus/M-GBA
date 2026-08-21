"""Tests for the raw-source to spatial-observation adapter boundary."""

from __future__ import annotations

import csv
import gzip
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from mgba.cli import main as cli_main
from mgba.spatial_anchors import (
    build_spatial_anchor_profile,
    load_spatial_anchor_protocol,
    load_spatial_observation_bundle,
    save_spatial_anchor_profile,
    verify_spatial_anchor_target,
)
from mgba.spatial_source_adapters import (
    JACKSON_MANIFEST_SCHEMA_VERSION,
    WU_MANIFEST_SCHEMA_VERSION,
    adapt_jackson_imc_source,
    adapt_wu_visium_source,
    load_spatial_source_protocol,
)


ROOT = Path(__file__).parents[1]
SOURCE_PROTOCOL = (
    ROOT / "configs" / "experiments" / "carm_spatial_source_protocol.json"
)
ANCHOR_PROTOCOL = (
    ROOT / "configs" / "experiments" / "carm_spatial_anchor_protocol.json"
)


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _write_gzip_lines(path: Path, lines: list[str]) -> Path:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def _artifact(path: Path, file_id: str, *, root: Path | None = None) -> dict:
    payload = path.read_bytes()
    return {
        "path": (path.relative_to(root).as_posix() if root is not None else path.name),
        "file_id": file_id,
        "sha256": sha256(payload).hexdigest(),
        "bytes": len(payload),
        "license": "fixture CC BY",
        "rights_verified": True,
    }


def _field_fixture(root: Path, *, reverse: bool = False) -> Path:
    protocol = load_spatial_source_protocol(SOURCE_PROTOCOL)
    genes = [
        gene
        for channel in ("stress", "resource", "signal")
        for gene in protocol["field_channels"][channel]
    ] + ["HOUSE"]
    samples = []
    for sample_index in range(6):
        sample_root = root / f"sample-{sample_index}"
        sample_root.mkdir()
        barcodes = [f"spot-{sample_index}-{value}" for value in range(9)]
        features = [f"ENSG{index:05d}\t{gene}\tGene Expression" for index, gene in enumerate(genes)]
        _write_gzip_lines(sample_root / "features.tsv.gz", features)
        _write_gzip_lines(sample_root / "barcodes.tsv.gz", barcodes)
        entries = []
        for gene_index, _gene in enumerate(genes, start=1):
            for spot_index in range(1, 10):
                # Non-proportional positive counts exercise library normalization.
                value = 1 + ((gene_index * spot_index + sample_index) % 11)
                entries.append(f"{gene_index} {spot_index} {value}")
        matrix = [
            "%%MatrixMarket matrix coordinate integer general",
            "% synthetic source-format fixture",
            f"{len(genes)} 9 {len(entries)}",
            *entries,
        ]
        (sample_root / "matrix.mtx").write_text("\n".join(matrix) + "\n", encoding="utf-8")
        positions = ["barcode,in_tissue,array_row,array_col"] + [
            f"{barcode},1,{spot_index // 3},{spot_index % 3}"
            for spot_index, barcode in enumerate(barcodes)
        ]
        (sample_root / "positions.csv").write_text("\n".join(positions) + "\n", encoding="utf-8")
        regions = ["Barcode,Classification"] + [
            f"{barcode},{'invasive' if spot_index % 3 == 0 else 'stroma'}"
            for spot_index, barcode in enumerate(barcodes)
        ]
        (sample_root / "regions.csv").write_text("\n".join(regions) + "\n", encoding="utf-8")
        samples.append(
            {
                "sample_id": f"private-wu-{sample_index}",
                "matrix_path": f"{sample_root.name}/matrix.mtx",
                "features_path": f"{sample_root.name}/features.tsv.gz",
                "barcodes_path": f"{sample_root.name}/barcodes.tsv.gz",
                "positions_path": f"{sample_root.name}/positions.csv",
                "regions_path": f"{sample_root.name}/regions.csv",
                "position_barcode_column": "barcode",
                "position_in_tissue_column": "in_tissue",
                "position_x_column": "array_col",
                "position_y_column": "array_row",
                "region_barcode_column": "Barcode",
                "region_value_column": "Classification",
                "region_map": {"invasive": "core", "stroma": "rim"},
            }
        )
    sources = []
    for index, name in enumerate(("counts.tar.gz", "spatial.tar.gz", "metadata.tar.gz")):
        path = root / name
        path.write_bytes(f"fixture-source-{index}".encode("ascii"))
        sources.append(_artifact(path, name))
    for sample in samples:
        for key in (
            "matrix_path",
            "features_path",
            "barcodes_path",
            "positions_path",
            "regions_path",
        ):
            relative = sample[key]
            sources.append(_artifact(root / relative, relative, root=root))
    return _write_json(
        root / ("field-reversed.json" if reverse else "field.json"),
        {
            "schema_version": WU_MANIFEST_SCHEMA_VERSION,
            "dataset_id": "wu-swarbrick-brca-visium",
            "source_artifacts": sources,
            "samples": list(reversed(samples)) if reverse else samples,
        },
    )


def _write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _neighborhood_fixture(root: Path, *, unmapped: bool = False) -> Path:
    locations = []
    labels = []
    raw_labels = ("Macrophage", "Tumor", "Tumor", "Stroma", "Macrophage", "Tumor")
    coordinates = ((0, 0), (1, 0), (2, 0), (5, 5), (6, 5), (7, 6))
    for sample in ("image-a", "image-b"):
        for index, ((x, y), label) in enumerate(zip(coordinates, raw_labels, strict=True)):
            cell = f"cell-{index}"
            locations.append(
                {"image": sample, "cell": cell, "center_x": str(x), "center_y": str(y)}
            )
            labels.append(
                {
                    "image": sample,
                    "cell": cell,
                    "cluster": "Unknown" if unmapped and index == 0 else label,
                }
            )
    location_path = _write_csv(root / "locations.csv", locations)
    label_path = _write_csv(root / "labels.csv", labels)
    source_paths = []
    for index, name in enumerate(("singlecell_locations.zip", "singlecell_cluster_labels.zip")):
        path = root / name
        path.write_bytes(f"jackson-fixture-{index}".encode("ascii"))
        source_paths.append(_artifact(path, name))
    source_paths.extend(
        (
            _artifact(location_path, location_path.name),
            _artifact(label_path, label_path.name),
        )
    )
    return _write_json(
        root / ("neighborhood-unmapped.json" if unmapped else "neighborhood.json"),
        {
            "schema_version": JACKSON_MANIFEST_SCHEMA_VERSION,
            "dataset_id": "jackson-brca-imc",
            "source_artifacts": source_paths,
            "tables": [
                {
                    "table_id": "basel",
                    "locations_path": location_path.name,
                    "labels_path": label_path.name,
                    "location_sample_column": "image",
                    "location_cell_column": "cell",
                    "x_column": "center_x",
                    "y_column": "center_y",
                    "label_sample_column": "image",
                    "label_cell_column": "cell",
                    "label_column": "cluster",
                    "label_map": {
                        "Macrophage": "immune",
                        "Stroma": "other",
                        "Tumor": "tumor",
                    },
                }
            ],
        },
    )


class SpatialSourceProtocolTests(unittest.TestCase):
    def test_protocol_freezes_three_transparent_proxy_modules(self) -> None:
        protocol = load_spatial_source_protocol(SOURCE_PROTOCOL)
        self.assertEqual(10_000.0, protocol["library_size_scale"])
        self.assertEqual(1, protocol["feature_symbol_column"])
        self.assertEqual(4, protocol["min_genes_per_channel"])
        self.assertEqual({"stress", "resource", "signal"}, set(protocol["field_channels"]))
        self.assertTrue(all(len(genes) == 8 for genes in protocol["field_channels"].values()))


class WuVisiumSourceAdapterTests(unittest.TestCase):
    def test_streaming_10x_adapter_builds_six_finite_field_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "field-bundle.json"
            adapt_wu_visium_source(
                _field_fixture(root), protocol_path=SOURCE_PROTOCOL, output_path=output
            )
            bundle = load_spatial_observation_bundle(output)
            self.assertEqual("field", bundle.modality)
            self.assertEqual(6, len(bundle.samples))
            self.assertEqual(54, sum(len(sample.field_observations) for sample in bundle.samples))
            for sample in bundle.samples:
                self.assertEqual({"core", "rim"}, {item.region for item in sample.field_observations})
                for item in sample.field_observations:
                    self.assertTrue(all(0.0 <= value <= 1.0 for _name, value in item.channels))

    def test_manifest_order_does_not_change_bundle_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_manifest = _field_fixture(root)
            first = root / "first.json"
            adapt_wu_visium_source(first_manifest, protocol_path=SOURCE_PROTOCOL, output_path=first)
            reversed_manifest = _write_json(
                root / "reversed.json",
                {
                    **json.loads(first_manifest.read_text(encoding="utf-8")),
                    "samples": list(
                        reversed(json.loads(first_manifest.read_text(encoding="utf-8"))["samples"])
                    ),
                },
            )
            second = root / "second.json"
            adapt_wu_visium_source(reversed_manifest, protocol_path=SOURCE_PROTOCOL, output_path=second)
            self.assertEqual(
                load_spatial_observation_bundle(first).input_digest,
                load_spatial_observation_bundle(second).input_digest,
            )

    def test_source_byte_or_digest_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = _field_fixture(root)
            (root / "counts.tar.gz").write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                adapt_wu_visium_source(
                    manifest,
                    protocol_path=SOURCE_PROTOCOL,
                    output_path=root / "field.json",
                )


class JacksonImcSourceAdapterTests(unittest.TestCase):
    def test_exact_cluster_mapping_builds_normalized_neighborhood_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "neighborhood-bundle.json"
            adapt_jackson_imc_source(
                _neighborhood_fixture(root),
                protocol_path=SOURCE_PROTOCOL,
                output_path=output,
            )
            bundle = load_spatial_observation_bundle(output)
            self.assertEqual("neighborhood", bundle.modality)
            self.assertEqual(2, len(bundle.samples))
            for sample in bundle.samples:
                self.assertEqual(
                    {"immune", "other", "tumor"},
                    {item.label for item in sample.neighborhood_observations},
                )
                self.assertTrue(
                    all(0.0 <= item.x <= 1.0 and 0.0 <= item.y <= 1.0 for item in sample.neighborhood_observations)
                )

    def test_unmapped_published_cluster_fails_instead_of_being_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                adapt_jackson_imc_source(
                    _neighborhood_fixture(root, unmapped=True),
                    protocol_path=SOURCE_PROTOCOL,
                    output_path=root / "neighborhood.json",
                )


class SpatialSourceCliTests(unittest.TestCase):
    def test_both_cli_adapters_feed_the_existing_target_checker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            field_root = root / "field"
            neighborhood_root = root / "neighborhood"
            field_root.mkdir()
            neighborhood_root.mkdir()
            field_manifest = _field_fixture(field_root)
            neighborhood_manifest = _neighborhood_fixture(neighborhood_root)
            field_bundle = root / "field-bundle.json"
            neighborhood_bundle = root / "neighborhood-bundle.json"
            for command in (
                [
                    "mgba",
                    "spatial-source-adapt-field",
                    "--manifest",
                    str(field_manifest),
                    "--protocol",
                    str(SOURCE_PROTOCOL),
                    "--output",
                    str(field_bundle),
                ],
                [
                    "mgba",
                    "spatial-source-adapt-neighborhood",
                    "--manifest",
                    str(neighborhood_manifest),
                    "--protocol",
                    str(SOURCE_PROTOCOL),
                    "--output",
                    str(neighborhood_bundle),
                ],
            ):
                stdout = StringIO()
                with patch("sys.argv", command), redirect_stdout(stdout):
                    cli_main()
                self.assertIn("input_digest", json.loads(stdout.getvalue()))

            profile = build_spatial_anchor_profile(
                load_spatial_anchor_protocol(ANCHOR_PROTOCOL),
                field_bundle=load_spatial_observation_bundle(field_bundle),
                neighborhood_bundle=load_spatial_observation_bundle(neighborhood_bundle),
            )
            target = save_spatial_anchor_profile(root / "derived" / "target.json", profile)
            verified = verify_spatial_anchor_target(target)
            self.assertEqual(profile.target_id, verified["target_id"])


if __name__ == "__main__":
    unittest.main()
