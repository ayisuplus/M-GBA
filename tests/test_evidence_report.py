"""ADR-0050 evidence overview report pipeline gates.

Covers: schema validation, missing-source degradation, byte-level double-run
determinism, manifest digest recheck, negative-result surfacing, --verify
byte comparison, and CLI registration. Real-artifact tests are skipped on
machines without the gitignored artifacts/ tree (same convention as
tests/test_cli.py::ReportCommandTests).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
from pathlib import Path
from unittest import mock

from mgba.cli import main as cli_main
from mgba.evidence_report import (
    EVIDENCE_SCHEMA,
    MANIFEST_SCHEMA,
    SECTION_ORDER,
    build_evidence_report,
    validate_evidence_summary,
    verify_evidence_report,
)

ROOT = Path(__file__).parents[1]
ARTIFACT_ROOT = ROOT / "artifacts"
REGISTRY = ROOT / "data" / "registry.json"
_REQUIRED_INPUTS = (
    ARTIFACT_ROOT / "extrapolation-boundary" / "results.json",
    ARTIFACT_ROOT / "falsification" / "label-shuffle" / "results.json",
    ARTIFACT_ROOT / "exploratory" / "effect-robustness-2026-09-11" / "summary.json",
    ARTIFACT_ROOT
    / "mvp-demo"
    / "matrix-7da4137aa39d5122"
    / "derived"
    / "summary.json",
    ARTIFACT_ROOT
    / "carm-state-conditioned-intervention"
    / "state-intervention-0e92bb234ba3a840"
    / "derived"
    / "summary.json",
    ARTIFACT_ROOT / "audit" / "bridge-coverage-2026-09-11" / "audit.json",
    REGISTRY,
)
EVIDENCE_INPUTS_AVAILABLE = all(path.is_file() for path in _REQUIRED_INPUTS)

_EXPECTED_FILES = {
    "index.html",
    "summary.json",
    "manifest.json",
    "training-evaluation.svg",
    "training-evaluation.csv",
    "extrapolation-boundary.svg",
    "extrapolation-boundary.csv",
    "falsification-controls.svg",
    "falsification-controls.csv",
    "effect-robustness-forest.svg",
    "effect-robustness-forest.csv",
    "wp8-matrix.svg",
    "wp8-matrix.csv",
    "carm-intervention.svg",
    "carm-intervention.csv",
    "spatial-anchor.svg",
    "spatial-anchor.csv",
    "bridge-coverage.svg",
    "bridge-coverage.csv",
    "data-registry.svg",
    "data-registry.csv",
}


def _run_cli(*argv: str) -> dict:
    stdout = StringIO()
    with mock.patch("sys.argv", ["mgba", *argv]), redirect_stdout(stdout):
        cli_main()
    return json.loads(stdout.getvalue())


@unittest.skipUnless(
    EVIDENCE_INPUTS_AVAILABLE,
    "evidence source artifacts are gitignored; present only on the generator machine",
)
class EvidenceReportRealArtifactTests(unittest.TestCase):
    def test_full_build_all_sections_present(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = build_evidence_report(ARTIFACT_ROOT, directory)
            summary = json.loads(paths.summary.read_text(encoding="utf-8"))
            self.assertEqual(EVIDENCE_SCHEMA, summary["schema_version"])
            statuses = {
                section["section_id"]: section["status"]
                for section in summary["sections"]
            }
            self.assertEqual(
                {section_id: "present" for section_id, _ in SECTION_ORDER},
                statuses,
            )
            produced = {path.name for path in paths.root.iterdir() if path.is_file()}
            self.assertEqual(_EXPECTED_FILES, produced)

    def test_summary_schema_validation_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = build_evidence_report(ARTIFACT_ROOT, directory)
            summary = json.loads(paths.summary.read_text(encoding="utf-8"))
            validate_evidence_summary(summary)
            tampered = dict(summary, schema_version="bogus")
            with self.assertRaises(ValueError):
                validate_evidence_summary(tampered)
            reordered = dict(summary)
            reordered["sections"] = list(reversed(summary["sections"]))
            with self.assertRaises(ValueError):
                validate_evidence_summary(reordered)

    def test_double_run_byte_identical(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first_dir,
            tempfile.TemporaryDirectory() as second_dir,
        ):
            first = build_evidence_report(ARTIFACT_ROOT, first_dir)
            second = build_evidence_report(ARTIFACT_ROOT, second_dir)
            first_files = {
                path.name: path.read_bytes()
                for path in first.root.iterdir()
                if path.is_file()
            }
            second_files = {
                path.name: path.read_bytes()
                for path in second.root.iterdir()
                if path.is_file()
            }
            self.assertEqual(first_files, second_files)

    def test_manifest_digests_match_disk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = build_evidence_report(ARTIFACT_ROOT, directory)
            manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
            self.assertEqual(MANIFEST_SCHEMA, manifest["schema_version"])
            self.assertEqual(EVIDENCE_SCHEMA, manifest["report_schema"])
            for name, digest in manifest["files"].items():
                actual = sha256((paths.root / name).read_bytes()).hexdigest()
                self.assertEqual(digest, actual, name)
            input_ids = set(manifest["inputs"])
            self.assertIn("data-registry", input_ids)
            self.assertIn("extrapolation-boundary", input_ids)

    def test_html_surfaces_negative_results_without_javascript(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = build_evidence_report(ARTIFACT_ROOT, directory)
            page = paths.html.read_text(encoding="utf-8")
            self.assertNotIn("<script", page)
            self.assertNotIn("fetch(", page)
            self.assertIn('lang="zh-CN"', page)
            self.assertIn("failed", page)
            self.assertIn("criteria_not_met", page)
            self.assertIn("未锚定", page)
            self.assertIn("负面结果与未通过判定", page)
            summary = json.loads(paths.summary.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(summary["negative_findings"]), 4)
            verdicts = {
                item["dataset_id"]: item["verdict"]
                for item in summary["sections"][0]["findings"]["evaluations"]
            }
            self.assertEqual("passed", verdicts["aivc-l0-training-evaluation"])
            self.assertEqual(
                "failed", verdicts["aivc-replogle-kd-training-evaluation"]
            )

    def test_csv_row_counts_match_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = build_evidence_report(ARTIFACT_ROOT, directory)

            def row_count(name: str) -> int:
                lines = (paths.root / name).read_text(encoding="utf-8").splitlines()
                return len(lines) - 1

            self.assertEqual(4, row_count("training-evaluation.csv"))
            self.assertEqual(2, row_count("extrapolation-boundary.csv"))
            self.assertEqual(36, row_count("effect-robustness-forest.csv"))
            self.assertEqual(39, row_count("spatial-anchor.csv"))
            self.assertEqual(30, row_count("wp8-matrix.csv"))
            self.assertEqual(6, row_count("bridge-coverage.csv"))
            self.assertEqual(26, row_count("data-registry.csv"))

    def test_forest_svg_well_formed_with_ci_labels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = build_evidence_report(ARTIFACT_ROOT, directory)
            svg = (paths.root / "effect-robustness-forest.svg").read_text(
                encoding="utf-8"
            )
            self.assertTrue(svg.startswith("<svg"))
            self.assertIn('<title id="title">', svg)
            self.assertIn('<desc id="desc">', svg)
            self.assertIn("一致率", svg)
            self.assertIn("WP8 矩阵", svg)
            self.assertIn("CAR-M 干预", svg)

    def test_verify_passes_and_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = build_evidence_report(ARTIFACT_ROOT, directory)
            clean = verify_evidence_report(ARTIFACT_ROOT, directory)
            self.assertTrue(clean["verified"])
            self.assertEqual([], clean["mismatches"])
            target = paths.root / "index.html"
            target.write_text(
                target.read_text(encoding="utf-8") + "<!-- tampered -->",
                encoding="utf-8",
            )
            dirty = verify_evidence_report(ARTIFACT_ROOT, directory)
            self.assertFalse(dirty["verified"])
            self.assertIn("index.html: byte mismatch", dirty["mismatches"])

    def test_cli_build_and_verify_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = _run_cli(
                "evidence-report",
                "--artifact-root",
                str(ARTIFACT_ROOT),
                "--output",
                directory,
            )
            self.assertTrue(Path(payload["report_manifest"]).is_file())
            self.assertEqual(
                {section_id: "present" for section_id, _ in SECTION_ORDER},
                payload["sections"],
            )
            self.assertGreaterEqual(payload["negative_findings"], 4)
            verified = _run_cli(
                "evidence-report",
                "--artifact-root",
                str(ARTIFACT_ROOT),
                "--output",
                directory,
                "--verify",
            )
            self.assertTrue(verified["verified"])


class EvidenceReportDegradationTests(unittest.TestCase):
    """Synthetic-tree tests: no real artifacts required."""

    def test_empty_tree_degrades_all_sections_without_failing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_root = root / "artifacts"
            artifact_root.mkdir()
            output = root / "out"
            paths = build_evidence_report(artifact_root, output)
            summary = json.loads(paths.summary.read_text(encoding="utf-8"))
            statuses = {
                section["section_id"]: section["status"]
                for section in summary["sections"]
            }
            self.assertEqual(
                {section_id: "missing" for section_id, _ in SECTION_ORDER},
                statuses,
            )
            produced = {path.name for path in paths.root.iterdir() if path.is_file()}
            self.assertEqual({"index.html", "summary.json", "manifest.json"}, produced)
            page = paths.html.read_text(encoding="utf-8")
            self.assertIn("未生成", page)
            self.assertNotIn("<script", page)
            self.assertEqual([], summary["negative_findings"])
            clean = verify_evidence_report(artifact_root, output)
            self.assertTrue(clean["verified"])

    def test_schema_mismatch_degrades_like_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_root = root / "artifacts"
            target_dir = artifact_root / "extrapolation-boundary"
            target_dir.mkdir(parents=True)
            (target_dir / "results.json").write_text(
                json.dumps({"schema_version": "mgba-unrelated-9.9"}),
                encoding="utf-8",
            )
            output = root / "out"
            paths = build_evidence_report(artifact_root, output)
            summary = json.loads(paths.summary.read_text(encoding="utf-8"))
            section = next(
                item
                for item in summary["sections"]
                if item["section_id"] == "extrapolation-boundary"
            )
            self.assertEqual("missing", section["status"])
            self.assertIn("schema_version 与冻结枚举不符", section["notes"][0])
            self.assertFalse((output / "extrapolation-boundary.svg").exists())

    def test_verify_missing_output_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "artifacts").mkdir()
            with self.assertRaises(ValueError):
                verify_evidence_report(root / "artifacts", root / "absent-output")

    def test_cli_verify_failure_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_root = root / "artifacts"
            artifact_root.mkdir()
            output = root / "out"
            build_evidence_report(artifact_root, output)
            summary = output / "summary.json"
            summary.write_text(
                summary.read_text(encoding="utf-8") + "\n", encoding="utf-8"
            )
            stdout = StringIO()
            with mock.patch(
                "sys.argv",
                [
                    "mgba",
                    "evidence-report",
                    "--artifact-root",
                    str(artifact_root),
                    "--output",
                    str(output),
                    "--verify",
                ],
            ), redirect_stdout(stdout):
                with self.assertRaises(SystemExit) as caught:
                    cli_main()
            self.assertIn(
                "evidence report verification failed", str(caught.exception)
            )


if __name__ == "__main__":
    unittest.main()
