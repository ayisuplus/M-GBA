"""Tests for the ADR-0043 spatial calibration machinery."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from mgba.calibration import CalibrationProtocol, load_calibration_protocol
from mgba.cli import main as cli_main
from mgba.spatial_calibration import (
    PARAMETER_BOUNDS,
    REFERENCE_HOLDOUT_MEAN_NAE,
    point_to_overrides,
    reference_box_point,
    run_spatial_calibration,
    save_spatial_calibration_artifacts,
)
from mgba.scenarios.carm.spatial import load_carm_spatial_config

ROOT = Path(__file__).parents[1]
CONFIGS = ROOT / "configs"


def _protocol() -> CalibrationProtocol:
    return CalibrationProtocol(
        model_version="test-calibration",
        search_seed=7,
        candidate_count=6,
        top_k=2,
        refinement_steps=(0.25,),
        max_sweeps=1,
        ticks=4,
        parameter_names=tuple(name for name, _low, _high in PARAMETER_BOUNDS),
    )


class BoxMappingTests(unittest.TestCase):
    def test_roundtrip_and_reference_point(self) -> None:
        config = load_carm_spatial_config(CONFIGS / "layers" / "l3_carm_spatial.json")
        point = reference_box_point(config)
        overrides = point_to_overrides(point)
        for name, _low, _high in PARAMETER_BOUNDS:
            self.assertAlmostEqual(getattr(config, name), overrides[name], places=12)
        self.assertAlmostEqual(0.3142857142857143, point[0], places=12)

    def test_out_of_box_and_dimension_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unit box"):
            point_to_overrides((1.5, 0.5, 0.5, 0.5))
        with self.assertRaisesRegex(ValueError, "dimension"):
            point_to_overrides((0.5, 0.5))

    def test_protocol_loader_and_real_config(self) -> None:
        protocol = load_calibration_protocol(
            CONFIGS / "experiments" / "carm_spatial_calibration.json"
        )
        self.assertEqual(24, protocol.candidate_count)
        self.assertEqual(4, len(protocol.parameter_names))
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"model_version": "x"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid calibration protocol"):
                load_calibration_protocol(bad)


class CalibrationRunTests(unittest.TestCase):
    def _objective(self, peak: tuple[float, ...]):
        def objective(point: tuple[float, ...]) -> float:
            return -sum((p - q) ** 2 for p, q in zip(point, peak, strict=True))

        return objective

    def test_incumbent_never_regressed_and_verdict_branches(self) -> None:
        # Objective peaks at a box corner; incumbent is mid-box.
        peak = (0.9, 0.1, 0.9, 0.1)
        incumbent = (0.5, 0.5, 0.5, 0.5)

        outcome = run_spatial_calibration(
            _protocol(),
            self._objective(peak),
            reference_point=incumbent,
            confirm=lambda point: {"holdout_mean_nae": REFERENCE_HOLDOUT_MEAN_NAE - 1.0},
        )
        incumbent_score = outcome.search.evaluations[0].score
        self.assertEqual("incumbent", outcome.search.evaluations[0].phase)
        self.assertGreaterEqual(outcome.search.best_score, incumbent_score)
        self.assertEqual("improved", outcome.confirmation["verdict"])

        outcome_bad = run_spatial_calibration(
            _protocol(),
            self._objective(peak),
            reference_point=incumbent,
            confirm=lambda point: {"holdout_mean_nae": REFERENCE_HOLDOUT_MEAN_NAE + 1.0},
        )
        self.assertEqual("not-anchored", outcome_bad.confirmation["verdict"])

    def test_exact_margin_boundary(self) -> None:
        incumbent = (0.5, 0.5, 0.5, 0.5)
        outcome = run_spatial_calibration(
            _protocol(),
            self._objective(incumbent),
            reference_point=incumbent,
            confirm=lambda point: {
                "holdout_mean_nae": REFERENCE_HOLDOUT_MEAN_NAE - 1e-13
            },
        )
        # Margin 1e-13 < 1e-12 epsilon -> not improved.
        self.assertEqual("not-anchored", outcome.confirmation["verdict"])

    def test_write_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outcome = run_spatial_calibration(
                _protocol(),
                self._objective((0.5, 0.5, 0.5, 0.5)),
                reference_point=(0.5, 0.5, 0.5, 0.5),
                confirm=lambda point: {"holdout_mean_nae": 999.0},
            )
            paths = save_spatial_calibration_artifacts(tmp, outcome)
            self.assertTrue(paths["summary"].exists())
            save_spatial_calibration_artifacts(tmp, outcome)  # identical: fine
            payload = json.loads(paths["summary"].read_text(encoding="utf-8"))
            payload["calibration_id"] = "tampered"
            paths["summary"].write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different"):
                save_spatial_calibration_artifacts(tmp, outcome)


class CalibrateCliTests(unittest.TestCase):
    def test_cli_dispatch_with_stubbed_search(self) -> None:
        from mgba.spatial_calibration import SpatialCalibrationOutcome
        from mgba.calibration import CalibrationEvaluation, CalibrationResult

        protocol = _protocol()
        stub_result = CalibrationResult(
            protocol=protocol,
            evaluations=(CalibrationEvaluation(phase="incumbent", point=(0.5,) * 4, score=-10.0),),
            best_point=(0.5,) * 4,
            best_score=-10.0,
        )
        outcome = SpatialCalibrationOutcome(
            search=stub_result,
            reference_calibration_score=-10.0,
            confirmation={
                "evaluation_id": "carm-spatial-anchor-eval-stub",
                "best_point": {},
                "calibration_mean_nae": 10.0,
                "holdout_mean_nae": 999.0,
                "external_validation_mean_nae": 1.0,
                "verdict": "not-anchored",
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["mgba", "carm-spatial-calibrate", "--artifact-root", tmp]
            stdout = StringIO()
            with mock.patch("sys.argv", argv), mock.patch(
                "mgba.cli.run_spatial_calibration", return_value=outcome
            ), mock.patch("mgba.cli.verify_spatial_anchor_target", return_value={}), mock.patch(
                "mgba.cli.compile_carm_scenario", return_value=None
            ), mock.patch("mgba.cli.make_spatial_objective", return_value=lambda p: 0.0), redirect_stdout(stdout):
                cli_main()
            result = json.loads(stdout.getvalue())
            self.assertEqual("mgba-spatial-calibration-0.1", result["schema_version"])
            self.assertEqual("not-anchored", result["confirmation"]["verdict"])
            self.assertTrue((Path(tmp) / "calibration-summary.json").exists())


if __name__ == "__main__":
    unittest.main()
