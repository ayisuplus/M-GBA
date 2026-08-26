"""CLI dispatch coverage: execute every ``mgba.cli.main()`` branch at least once.

Cheap commands (``run``, ``simulate``, the L0-L4 matrix commands, ``autolab``,
``lab-export``, the spatial source/anchor chain) run for real against committed
configs. The CAR-M runtime matrices (81-116s each) and ``demo-export`` (40s) are
covered by patching the handlers imported into the ``mgba.cli`` namespace, which
still executes the full dispatch body (result assembly and artifact plumbing).
"""

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
from types import SimpleNamespace
from unittest import mock

from mgba.cli import main as cli_main
from mgba.spatial_anchors import OBSERVATION_SCHEMA_VERSION
from mgba.spatial_source_adapters import (
    JACKSON_MANIFEST_SCHEMA_VERSION,
    WU_MANIFEST_SCHEMA_VERSION,
    load_spatial_source_protocol,
)

ROOT = Path(__file__).parents[1]
MATRIX_ROOT = ROOT / "artifacts" / "mvp-demo" / "matrix-7da4137aa39d5122"
RUN_ARTIFACT = MATRIX_ROOT / "raw" / "l2_static" / "seed-41.json"
SOURCE_PROTOCOL = ROOT / "configs" / "experiments" / "carm_spatial_source_protocol.json"
ANCHOR_PROTOCOL = ROOT / "configs" / "experiments" / "carm_spatial_anchor_protocol.json"


def _run_cli(*argv: str) -> dict:
    stdout = StringIO()
    with mock.patch("sys.argv", ["mgba", *argv]), redirect_stdout(stdout):
        cli_main()
    return json.loads(stdout.getvalue())


def _run_cli_failure(self: unittest.TestCase, *argv: str) -> tuple[SystemExit, dict]:
    stdout = StringIO()
    with mock.patch("sys.argv", ["mgba", *argv]), redirect_stdout(stdout):
        with self.assertRaises(SystemExit) as caught:
            cli_main()
    text = stdout.getvalue()
    return caught.exception, (json.loads(text) if text.strip() else {})


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_legacy_carm_fixture(root: Path) -> None:
    """Compact copy of tests/test_carm_data.py::_write_legacy_fixture."""
    immune_types = [
        "T_cells_CD8",
        "Macrophages_M1",
        "Macrophages_M2",
        *(f"immune_{index:02d}" for index in range(19)),
    ]
    counts = {"high_immune": 323, "low_immune": 273, "normal": 156}
    records = []
    sample_index = 0
    for subtype, count in counts.items():
        for _ in range(count):
            sample_index += 1
            base = {"high_immune": 0.6, "low_immune": 0.2, "normal": 0.4}[subtype]
            records.append(
                {
                    "sample_id": f"sample-{sample_index:04d}",
                    "immune_infiltration": [base] * len(immune_types),
                    "immune_subtype": subtype,
                    "subtype_probs": [0.2, 0.3, 0.5],
                    "survival_risk": 0.5,
                }
            )
    predictions = {
        "metadata": {
            "cancer_type": "TCGA-BRCA",
            "n_samples": 752,
            "n_genes": 5000,
            "model": "GAT-2layer-4heads",
            "backend": "numpy",
            "cv_scores": {"auc": 0.78, "accuracy": 0.57, "f1": 0.54, "auc_risk": 0.47},
        },
        "predictions": records,
        "immune_cell_types": immune_types,
    }
    graph = {"n_nodes": 5000, "n_edges": 12000, "source": "string"}
    scenarios = [
        {
            "name": "high immune",
            "car_design": {"targetAntigen": "HER2", "affinity": 7},
            "tcga_source": {"subtype": "high_immune", "sample_count": 45},
        }
    ]
    for name, payload in (
        ("tcga_predictions.json", predictions),
        ("tcga_graph_info.json", graph),
        ("tcga_patient_scenarios.json", scenarios),
    ):
        _write_json(root / name, payload)


def _raw_run_payload() -> dict:
    """Minimal MultirateRun JSON after tests/test_collective_dynamics.py::_raw_run."""
    cells = {
        "cell-a": [(0.9, 0.1), (0.8, 0.2), (0.7, 0.3), (0.6, 0.4)],
        "cell-b": [(0.2, 0.7), (0.3, 0.6), (0.4, 0.5), (0.5, 0.4)],
    }
    ticks = []
    length = len(next(iter(cells.values())))
    for index in range(length):
        logical_time = index + 1
        l4 = None
        if logical_time in {1, length}:
            l4 = {
                "vitality": 0.8 - 0.01 * index,
                "damage_burden": 0.2 + 0.01 * index,
                "inflammation": 0.1 + 0.01 * index,
                "homeostasis": 0.7 - 0.01 * index,
                "recovery_capacity": 0.6 - 0.01 * index,
            }
        ticks.append(
            {
                "logical_time": logical_time,
                "l2": [
                    {
                        "cell_id": cell_id,
                        "activation": values[index][0],
                        "stress_load": values[index][1],
                    }
                    for cell_id, values in sorted(cells.items())
                ],
                "l3": {"edges": [["cell-a", "cell-b"]]},
                "l4": l4,
            }
        )
    terminal = dict(ticks[-1]["l4"])
    terminal["metadata"] = {"logical_time": length}
    return {
        "experiment": {"experiment_id": "mgba-cli-fixture"},
        "history_digest": "a" * 64,
        "ticks": ticks,
        "terminal_observation": terminal,
    }


def _write_gzip_lines(path: Path, lines: list[str]) -> Path:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def _source_artifact(path: Path, file_id: str, *, root: Path | None = None) -> dict:
    payload = path.read_bytes()
    return {
        "path": (path.relative_to(root).as_posix() if root is not None else path.name),
        "file_id": file_id,
        "sha256": sha256(payload).hexdigest(),
        "bytes": len(payload),
        "license": "fixture CC BY",
        "rights_verified": True,
    }


def _write_wu_field_manifest(root: Path) -> Path:
    """Minimal licensed Wu Visium source tree (6 samples) + manifest."""
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
        features = [
            f"ENSG{index:05d}\t{gene}\tGene Expression"
            for index, gene in enumerate(genes)
        ]
        _write_gzip_lines(sample_root / "features.tsv.gz", features)
        _write_gzip_lines(sample_root / "barcodes.tsv.gz", barcodes)
        entries = []
        for gene_index, _gene in enumerate(genes, start=1):
            for spot_index in range(1, 10):
                value = 1 + ((gene_index * spot_index + sample_index) % 11)
                entries.append(f"{gene_index} {spot_index} {value}")
        matrix = [
            "%%MatrixMarket matrix coordinate integer general",
            "% synthetic source-format fixture",
            f"{len(genes)} 9 {len(entries)}",
            *entries,
        ]
        (sample_root / "matrix.mtx").write_text(
            "\n".join(matrix) + "\n", encoding="utf-8"
        )
        positions = ["barcode,in_tissue,array_row,array_col"] + [
            f"{barcode},1,{spot_index // 3},{spot_index % 3}"
            for spot_index, barcode in enumerate(barcodes)
        ]
        (sample_root / "positions.csv").write_text(
            "\n".join(positions) + "\n", encoding="utf-8"
        )
        regions = ["Barcode,Classification"] + [
            f"{barcode},{'invasive' if spot_index % 3 == 0 else 'stroma'}"
            for spot_index, barcode in enumerate(barcodes)
        ]
        (sample_root / "regions.csv").write_text(
            "\n".join(regions) + "\n", encoding="utf-8"
        )
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
        sources.append(_source_artifact(path, name))
    for sample in samples:
        for key in (
            "matrix_path",
            "features_path",
            "barcodes_path",
            "positions_path",
            "regions_path",
        ):
            relative = sample[key]
            sources.append(_source_artifact(root / relative, relative, root=root))
    return _write_json(
        root / "field.json",
        {
            "schema_version": WU_MANIFEST_SCHEMA_VERSION,
            "dataset_id": "wu-swarbrick-brca-visium",
            "source_artifacts": sources,
            "samples": samples,
        },
    )


def _write_jackson_neighborhood_manifest(root: Path) -> Path:
    """Minimal licensed Jackson IMC CSV pair + manifest."""
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
            labels.append({"image": sample, "cell": cell, "cluster": label})

    def _write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path

    location_path = _write_csv(root / "locations.csv", locations)
    label_path = _write_csv(root / "labels.csv", labels)
    source_paths = []
    for index, name in enumerate(
        ("singlecell_locations.zip", "singlecell_cluster_labels.zip")
    ):
        path = root / name
        path.write_bytes(f"jackson-fixture-{index}".encode("ascii"))
        source_paths.append(_source_artifact(path, name))
    source_paths.extend(
        (
            _source_artifact(location_path, location_path.name),
            _source_artifact(label_path, label_path.name),
        )
    )
    return _write_json(
        root / "neighborhood.json",
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


def _fake_artifact_paths(root: Path) -> dict[str, Path]:
    return {
        "root": root,
        "manifest": root / "manifest.json",
        "summary": root / "summary.json",
    }


def _mock_matrix(summary: dict) -> mock.Mock:
    matrix = mock.Mock(name="matrix")
    matrix.summary_dict.return_value = dict(summary)
    matrix.report_dict.return_value = dict(summary)
    return matrix


class RunCommandTests(unittest.TestCase):
    def test_run_default_scenario_prints_trace_summary(self) -> None:
        payload = _run_cli("run")
        self.assertEqual(
            "contract-demonstrator-not-biological-model", payload["model_status"]
        )
        self.assertIn("trace_digest", payload)
        self.assertIn("layers", payload)


class SimulateCommandTests(unittest.TestCase):
    def test_checkpoint_roundtrip_and_trace_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "checkpoint.json"
            trace = root / "trace.json"
            first = _run_cli(
                "simulate",
                "--ticks",
                "3",
                "--checkpoint-out",
                str(checkpoint),
                "--trace-out",
                str(trace),
            )
            self.assertTrue(checkpoint.is_file())
            self.assertTrue(trace.is_file())
            self.assertIn("history_digest", first)
            resumed = _run_cli(
                "simulate", "--ticks", "2", "--checkpoint-in", str(checkpoint)
            )
            self.assertIn("end_tick", resumed)

    def test_non_positive_ticks_rejected(self) -> None:
        error, _ = _run_cli_failure(self, "simulate", "--ticks", "0")
        self.assertIn("--ticks must be positive", str(error))


class Wp8ExperimentCommandTests(unittest.TestCase):
    def test_experiment_matrix_writes_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = _run_cli("experiment", "--artifact-root", directory)
            self.assertIn("matrix_id", payload)
            self.assertTrue(Path(payload["artifact_root"]).is_dir())


class ReportCommandTests(unittest.TestCase):
    def test_report_rebuilds_into_temp_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = _run_cli(
                "report",
                "--matrix-root",
                str(MATRIX_ROOT),
                "--output-dir",
                directory,
            )
            self.assertEqual("matrix-7da4137aa39d5122", payload["matrix_id"])
            self.assertTrue(Path(payload["report_manifest"]).is_file())
            self.assertTrue(
                str(Path(payload["report_root"]).resolve()).startswith(
                    str(Path(directory).resolve())
                )
            )

    def test_run_report_rebuilds_into_temp_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = _run_cli(
                "run-report",
                "--run",
                str(RUN_ARTIFACT),
                "--output-dir",
                directory,
            )
            self.assertIn("experiment_id", payload)
            self.assertTrue(Path(payload["report_manifest"]).is_file())


class CarmImportCommandTests(unittest.TestCase):
    def test_legacy_tree_imports_to_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_legacy_carm_fixture(root)
            output = root / "profile.json"
            payload = _run_cli(
                "carm-import", "--legacy-root", str(root), "--output", str(output)
            )
            self.assertTrue(output.is_file())
            self.assertEqual(752, payload["total_sample_count"])
            self.assertEqual(
                {"high_immune": 323, "low_immune": 273, "normal": 156},
                payload["subtype_counts"],
            )
            self.assertEqual(str(output), payload["output"])


class CarmMatrixCommandTests(unittest.TestCase):
    """CAR-M runtime matrices exceed the test-time budget; the imported handlers
    are stubbed so the dispatch body (result assembly, artifact plumbing) runs."""

    def test_carm_experiment_dispatch(self) -> None:
        compiled = SimpleNamespace(
            config=SimpleNamespace(profile=SimpleNamespace(cohort_id="cohort-x")),
            profile_digest="d" * 16,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = SimpleNamespace(
                causal=SimpleNamespace(root=root / "causal"),
                provenance=root / "provenance.json",
            )
            with (
                mock.patch("mgba.cli.compile_carm_scenario", return_value=compiled) as compile_mock,
                mock.patch("mgba.cli.build_carm_runners", return_value={"runner": object()}),
                mock.patch(
                    "mgba.cli.run_carm_matrix",
                    return_value=_mock_matrix({"matrix_id": "carm-m"}),
                ) as matrix_mock,
                mock.patch("mgba.cli.save_carm_artifacts", return_value=artifacts),
                mock.patch(
                    "mgba.cli.build_causal_report",
                    return_value=SimpleNamespace(html=root / "report.html"),
                ),
            ):
                payload = _run_cli("carm-experiment", "--artifact-root", directory)
            compile_mock.assert_called_once()
            matrix_mock.assert_called_once()
            self.assertEqual("carm-m", payload["matrix_id"])
            self.assertEqual("cohort-x", payload["cohort_id"])
            self.assertEqual("d" * 16, payload["profile_digest"])
            self.assertIn("model_status", payload)
            self.assertIn("artifact_root", payload)
            self.assertIn("provenance", payload)
            self.assertIn("report", payload)

    def test_carm_spatial_experiment_dispatch(self) -> None:
        compiled = SimpleNamespace(
            config=SimpleNamespace(profile=SimpleNamespace(cohort_id="cohort-x")),
            profile_digest="d" * 16,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner_type = mock.Mock(name="CarmSpatialExperimentRunner")
            runner_type.return_value.run.return_value = _mock_matrix(
                {"matrix_id": "spatial-m"}
            )
            with (
                mock.patch("mgba.cli.compile_carm_scenario", return_value=compiled),
                mock.patch(
                    "mgba.cli.build_carm_spatial_runners",
                    return_value={"spatial_field": object()},
                ) as builders_mock,
                mock.patch("mgba.cli.CarmSpatialExperimentRunner", runner_type),
                mock.patch(
                    "mgba.cli.save_carm_spatial_artifacts",
                    return_value=_fake_artifact_paths(root),
                ) as save_mock,
            ):
                payload = _run_cli(
                    "carm-spatial-experiment", "--artifact-root", directory
                )
            builders_mock.assert_called_once()
            runner_type.return_value.run.assert_called_once_with(compiled)
            save_mock.assert_called_once()
            self.assertEqual("spatial-m", payload["matrix_id"])
            self.assertEqual("cohort-x", payload["cohort_id"])
            self.assertEqual(str(root), payload["artifact_root"])
            self.assertIn("artifact_manifest", payload)
            self.assertIn("artifact_summary", payload)

    def test_carm_spatial_ablation_dispatch(self) -> None:
        compiled = SimpleNamespace(
            config=SimpleNamespace(profile=SimpleNamespace(cohort_id="cohort-x")),
            profile_digest="d" * 16,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner_type = mock.Mock(name="CarmSpatialAblationRunner")
            runner_type.return_value.run.return_value = _mock_matrix(
                {"audit_id": "ablation-a"}
            )
            with (
                mock.patch("mgba.cli.compile_carm_scenario", return_value=compiled),
                mock.patch(
                    "mgba.cli.build_carm_spatial_ablation_runners",
                    return_value={"audit": object()},
                ),
                mock.patch("mgba.cli.CarmSpatialAblationRunner", runner_type),
                mock.patch(
                    "mgba.cli.save_carm_spatial_ablation_artifacts",
                    return_value=_fake_artifact_paths(root),
                ),
            ):
                payload = _run_cli(
                    "carm-spatial-ablation", "--artifact-root", directory
                )
            runner_type.return_value.run.assert_called_once_with(compiled)
            self.assertEqual("ablation-a", payload["audit_id"])
            self.assertEqual("cohort-x", payload["cohort_id"])
            self.assertEqual(str(root), payload["artifact_root"])

    def test_carm_intervention_dispatch(self) -> None:
        compiled = SimpleNamespace(
            config=SimpleNamespace(profile=SimpleNamespace(cohort_id="cohort-x")),
            profile_digest="d" * 16,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner_type = mock.Mock(name="StateConditionedInterventionRunner")
            runner_type.return_value.run.return_value = _mock_matrix(
                {"intervention_id": "int-i"}
            )
            with (
                mock.patch("mgba.cli.compile_carm_scenario", return_value=compiled),
                mock.patch(
                    "mgba.cli.build_carm_intervention_runner",
                    return_value=object(),
                ),
                mock.patch(
                    "mgba.cli.StateConditionedInterventionRunner", runner_type
                ),
                mock.patch(
                    "mgba.cli.save_state_conditioned_intervention_artifacts",
                    return_value=_fake_artifact_paths(root),
                ),
            ):
                payload = _run_cli(
                    "carm-intervention-experiment", "--artifact-root", directory
                )
            runner_type.return_value.run.assert_called_once_with(compiled)
            self.assertEqual("int-i", payload["intervention_id"])
            self.assertEqual(str(root), payload["artifact_root"])

    def test_carm_spatial_anchor_evaluate_dispatch(self) -> None:
        target = {
            "schema_version": "target",
            "target_id": "t-1",
            "samples": [],
            "distributions": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluator_type = mock.Mock(name="SpatialAnchorEvaluator")
            evaluator_type.return_value.evaluate.return_value = _mock_matrix(
                {"evaluation_id": "eval-e"}
            )
            with (
                mock.patch(
                    "mgba.cli.verify_spatial_anchor_target", return_value=target
                ),
                mock.patch(
                    "mgba.cli.compile_carm_scenario",
                    return_value=SimpleNamespace(),
                ),
                mock.patch(
                    "mgba.cli.build_carm_spatial_runners",
                    return_value={"spatial_field": object()},
                ),
                mock.patch("mgba.cli.SpatialAnchorEvaluator", evaluator_type),
                mock.patch(
                    "mgba.cli.save_spatial_anchor_evaluation_artifacts",
                    return_value=_fake_artifact_paths(root),
                ),
            ):
                payload = _run_cli(
                    "carm-spatial-anchor-evaluate",
                    "--target",
                    str(root / "target.json"),
                    "--artifact-root",
                    directory,
                )
            evaluator_type.return_value.evaluate.assert_called_once()
            self.assertEqual("eval-e", payload["evaluation_id"])
            self.assertEqual(str(root), payload["artifact_root"])


class SpatialSourceAndAnchorCliTests(unittest.TestCase):
    def test_source_adapters_feed_anchor_build_and_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            field_root = root / "field"
            neighborhood_root = root / "neighborhood"
            field_root.mkdir()
            neighborhood_root.mkdir()
            field_manifest = _write_wu_field_manifest(field_root)
            neighborhood_manifest = _write_jackson_neighborhood_manifest(
                neighborhood_root
            )
            field_bundle = root / "field-bundle.json"
            neighborhood_bundle = root / "neighborhood-bundle.json"

            field_payload = _run_cli(
                "spatial-source-adapt-field",
                "--manifest",
                str(field_manifest),
                "--protocol",
                str(SOURCE_PROTOCOL),
                "--output",
                str(field_bundle),
            )
            self.assertTrue(field_bundle.is_file())
            self.assertEqual("wu-swarbrick-brca-visium", field_payload["dataset_id"])
            self.assertEqual("field", field_payload["modality"])
            self.assertEqual(6, field_payload["samples"])

            neighborhood_payload = _run_cli(
                "spatial-source-adapt-neighborhood",
                "--manifest",
                str(neighborhood_manifest),
                "--protocol",
                str(SOURCE_PROTOCOL),
                "--output",
                str(neighborhood_bundle),
            )
            self.assertTrue(neighborhood_bundle.is_file())
            self.assertEqual(
                "jackson-brca-imc", neighborhood_payload["dataset_id"]
            )
            self.assertEqual("neighborhood", neighborhood_payload["modality"])

            target = root / "derived" / "target.json"
            built = _run_cli(
                "spatial-anchor-build",
                "--protocol",
                str(ANCHOR_PROTOCOL),
                "--field-bundle",
                str(field_bundle),
                "--neighborhood-bundle",
                str(neighborhood_bundle),
                "--output",
                str(target),
            )
            self.assertTrue(target.is_file())
            self.assertIn("target_id", built)
            self.assertEqual(
                {"calibration", "holdout", "external_validation"},
                set(built["role_counts"]),
            )

            checked = _run_cli("spatial-anchor-check", "--target", str(target))
            self.assertTrue(checked["ok"])
            self.assertEqual(built["target_id"], checked["target_id"])


class DemoExportCommandTests(unittest.TestCase):
    def test_demo_export_dispatch_reads_written_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            playbook = _write_json(
                root / "carm-playbook.json",
                {
                    "conditions": [
                        {"condition_id": "dose-low", "ticks": [1, 2, 3]},
                        {"condition_id": "dose-high", "ticks": [1, 2, 3]},
                    ],
                    "roles": {"cell-a": "effector", "cell-b": "target"},
                },
            )
            manifest = _write_json(
                root / "demo-manifest.json", {"playbook_digest": "p" * 64}
            )
            paths = SimpleNamespace(
                playbook=playbook, html=root / "demo.html", manifest=manifest
            )
            with mock.patch(
                "mgba.cli.export_carm_demo", return_value=paths
            ) as export_mock:
                payload = _run_cli("demo-export", "--output-dir", directory)
            export_mock.assert_called_once()
            self.assertEqual(["dose-low", "dose-high"], payload["conditions"])
            self.assertEqual(3, payload["ticks"])
            self.assertEqual(2, payload["cells"])
            self.assertEqual("p" * 64, payload["playbook_digest"])


class LabExportCommandTests(unittest.TestCase):
    def test_lab_export_writes_catalog_to_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = _run_cli("lab-export", "--output-dir", directory)
            self.assertTrue(payload)
            for value in payload.values():
                self.assertTrue(Path(value).is_file())


class CollectiveAnalyzeCommandTests(unittest.TestCase):
    def test_raw_run_analysis_with_and_without_cohort_map(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = _write_json(root / "raw-run.json", _raw_run_payload())
            cohort_map = _write_json(
                root / "cohorts.json", {"cell-a": "alpha", "cell-b": "beta"}
            )
            plain_out = root / "plain.json"
            plain = _run_cli(
                "collective-analyze", "--input", str(raw), "--output", str(plain_out)
            )
            self.assertTrue(plain_out.is_file())
            self.assertEqual("mgba-cli-fixture", plain["source_experiment_id"])
            self.assertEqual(["all_cells"], plain["cohorts"])

            mapped_out = root / "mapped.json"
            mapped = _run_cli(
                "collective-analyze",
                "--input",
                str(raw),
                "--cohort-map",
                str(cohort_map),
                "--output",
                str(mapped_out),
            )
            self.assertTrue(mapped_out.is_file())
            self.assertEqual(["all_cells", "alpha", "beta"], sorted(mapped["cohorts"]))


class StenSmokeCommandTests(unittest.TestCase):
    def test_sten_smoke_runs_with_tick_override(self) -> None:
        payload = _run_cli("sten-smoke", "--ticks", "2")
        self.assertIn("event_digest", payload)
        self.assertIn("nodes", payload)

    def test_sten_smoke_rejects_non_positive_ticks(self) -> None:
        error, _ = _run_cli_failure(self, "sten-smoke", "--ticks", "0")
        self.assertIn("--ticks must be positive", str(error))


class LayeredMatrixCommandTests(unittest.TestCase):
    """Real small matrices; each writes its append-only artifact bundle."""

    def _assert_matrix_command(self, *argv: str) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            payload = _run_cli(*argv, "--artifact-root", directory)
            self.assertIn("matrix_id", payload)
            self.assertEqual(
                "reference-model-not-validated-biological-model",
                payload["model_status"],
            )
            self.assertTrue(Path(payload["artifact_manifest"]).is_file())
            self.assertTrue(Path(payload["artifact_summary"]).is_file())
            return payload

    def test_feedback_experiment(self) -> None:
        self._assert_matrix_command("feedback-experiment")

    def test_policy_experiment(self) -> None:
        self._assert_matrix_command("policy-experiment")

    def test_latent_experiment(self) -> None:
        self._assert_matrix_command("latent-experiment")

    def test_topology_experiment(self) -> None:
        self._assert_matrix_command("topology-experiment")

    def test_e3_experiment(self) -> None:
        self._assert_matrix_command("e3-experiment")

    def test_closed_loop_experiment(self) -> None:
        self._assert_matrix_command("closed-loop-experiment")

    def test_neural_experiment_l0(self) -> None:
        self._assert_matrix_command("neural-experiment", "--layer", "l0")

    def test_neural_experiment_l3(self) -> None:
        self._assert_matrix_command("neural-experiment", "--layer", "l3")


class AutolabCommandTests(unittest.TestCase):
    def test_autolab_loop_writes_session_and_control_plane(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = _run_cli("autolab", "--artifact-root", directory)
            self.assertEqual(
                "reference-model-not-validated-biological-model",
                payload["model_status"],
            )
            control = payload["control_plane"]
            self.assertIn("plan_id", control)
            self.assertTrue(Path(control["plan_artifact"]).is_file())
            self.assertTrue(Path(control["verification_artifact"]).is_file())
            self.assertTrue(Path(payload["artifact_manifest"]).is_file())

    def test_invalid_frozen_plan_aborts_before_running(self) -> None:
        with mock.patch(
            "mgba.cli.verify_autolab_plan",
            return_value=SimpleNamespace(valid=False),
        ):
            error, _ = _run_cli_failure(self, "autolab")
        self.assertIn("failed preflight verification", str(error))

    def test_ticks_beyond_runner_budget_abort_before_running(self) -> None:
        with mock.patch(
            "mgba.cli.load_runner_config",
            return_value=SimpleNamespace(max_total_ticks=0),
        ):
            error, _ = _run_cli_failure(self, "autolab")
        self.assertIn("runner budget", str(error))

    def test_unverified_result_aborts_before_reporting(self) -> None:
        session_type = mock.Mock(name="AutolabSession")
        with (
            mock.patch("mgba.cli.AutolabSession", session_type),
            mock.patch(
                "mgba.cli.build_autolab_manifest",
                return_value=SimpleNamespace(),
            ),
            mock.patch(
                "mgba.cli.verify_autolab_result",
                return_value=SimpleNamespace(fully_verified=False),
            ),
        ):
            error, _ = _run_cli_failure(self, "autolab")
        self.assertIn("failed manifest/history verification", str(error))
    def test_compile_and_validate_with_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = _run_cli("autolab-plan", "--artifact-root", directory)
            self.assertFalse(payload["executed"])
            self.assertEqual("accepted", payload["verification"]["verdict"])
            self.assertTrue(Path(payload["plan_artifact"]).is_file())
            self.assertTrue(Path(payload["verification_artifact"]).is_file())

    def test_malformed_plan_is_rejected_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = _write_json(
                Path(directory) / "plan.json", {"schema_version": "bogus"}
            )
            error, payload = _run_cli_failure(self, "autolab-plan", "--plan", str(plan))
            self.assertEqual(1, error.code)
            self.assertFalse(payload["executed"])
            self.assertEqual("rejected", payload["verification"]["verdict"])

    def test_unreadable_plan_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "absent.json"
            error, _ = _run_cli_failure(self, "autolab-plan", "--plan", str(missing))
            self.assertIn("invalid Autolab plan file", str(error))


class AutolabProposeCommandTests(unittest.TestCase):
    def test_proposals_validated_fail_closed_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proposals = _write_json(
                Path(directory) / "proposals.json",
                {
                    "proposals": [
                        {
                            "proposal_id": "p-accept",
                            "proposed_by": "llm",
                            "rationale": "probe the L2 axis further",
                            "hypothesis": {
                                "hypothesis_id": "cli-novel-l2",
                                "kind": "layer_static_swap",
                                "layer": "L2",
                                "priority": 0.5,
                            },
                        },
                        {
                            "proposal_id": "p-reject",
                            "proposed_by": "llm",
                            "rationale": "skip a layer read",
                            "hypothesis": {
                                "hypothesis_id": "cli-bad-kind",
                                "kind": "skip_l1_read_genes",
                                "layer": "L2",
                                "priority": 0.5,
                            },
                        },
                    ]
                },
            )
            payload = _run_cli("autolab-propose", "--proposals", str(proposals))
            self.assertFalse(payload["executed"])
            self.assertEqual(1, payload["counts"]["accepted"])
            self.assertEqual(1, payload["counts"]["rejected"])


class DataCheckCommandTests(unittest.TestCase):
    def test_committed_registry_is_valid(self) -> None:
        payload = _run_cli("data-check")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["entries"])
        self.assertTrue(all(entry["ok"] for entry in payload["entries"]))

    def test_digest_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "data"
            data_dir.mkdir()
            blob = root / "blob.json"
            blob.write_text("{}", encoding="utf-8")
            registry = _write_json(
                data_dir / "registry.json",
                {
                    "schema_version": "mgba-data-registry-0.1",
                    "datasets": [
                        {
                            "dataset_id": "fixture-dataset",
                            "kind": "synthetic",
                            "status": "materialized",
                            "path": "blob.json",
                            "sha256": "0" * 64,
                            "provenance": {
                                "source": "fixture",
                                "date": "2026-08-26",
                                "license": "fixture license",
                                "deidentified": True,
                                "proxy_notice": "fixture",
                            },
                            "notes": "digest mismatch fixture",
                        }
                    ],
                },
            )
            error, payload = _run_cli_failure(
                self, "data-check", "--registry", str(registry)
            )
            self.assertEqual(1, error.code)
            self.assertFalse(payload["ok"])
            self.assertFalse(payload["entries"][0]["ok"])
            self.assertIn("sha256", payload["entries"][0]["detail"])


if __name__ == "__main__":
    unittest.main()
