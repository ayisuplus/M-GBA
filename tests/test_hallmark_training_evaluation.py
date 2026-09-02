"""Tests for the ADR-0046 Hallmark training-evaluation segment."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
from pathlib import Path
from statistics import fmean
from unittest import mock

from mgba.cli import main as cli_main
from mgba.hallmark_training_evaluation import (
    EVALUATION_SCHEMA_VERSION,
    FROZEN_HALLMARK_TRAINING,
    PASS_EPSILON,
    PREDICTIONS_SCHEMA_VERSION,
    evaluate_hallmark_training,
    load_hallmark_predictions,
    save_hallmark_training_evaluation,
)
from mgba.hallmark_targets import TARGET_SCHEMA_VERSION
from mgba.layers.l0 import ABSTRACT_GENE_NAMES

_SETS = ("HALLMARK_ALPHA", "HALLMARK_BETA")
_DIMS = tuple(sorted(_SETS)) + ABSTRACT_GENE_NAMES
_HEAD = len(ABSTRACT_GENE_NAMES)
_UNITS = ("U1", "U2", "U3", "U4", "U5", "U6")
_ROLES = {"U1": "train", "U2": "train", "U3": "train", "U4": "train", "U5": "holdout", "U6": "holdout"}
_TARGETS = {unit: 0.01 * (index + 1) for index, unit in enumerate(_UNITS)}
_CENTROID = fmean(_TARGETS[unit] for unit in _UNITS if _ROLES[unit] == "train")


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _target_payload(dataset_id: str, holdout_value: float | None = None) -> dict:
    def _value(unit: str) -> float:
        if holdout_value is not None and _ROLES[unit] == "holdout":
            return holdout_value
        return _TARGETS[unit]

    return {
        "schema_version": TARGET_SCHEMA_VERSION,
        "target_id": f"{'replogle-kd' if 'replogle' in dataset_id else 'norman'}-hallmark-target-fixture",
        "dataset_id": dataset_id,
        "scientific_boundary": "fixture",
        "bridge": {"version": "fixture", "digest": "0" * 64},
        "source": {
            "bundle_sha256": "a" * 64,
            "profile_sha256": "b" * 64,
            "hallmark_gmt": {
                "path": "hallmark.gmt",
                "sha256": "c" * 64,
                "bytes": 50,
                "license": "MSigDB terms",
                "rights_verified": True,
                "version": "fixture",
            },
        },
        "split": {
            "salt": "fixture-salt",
            "train_fraction": 0.8,
            "rule": "fixture",
            "train_units": 4,
            "holdout_units": 2,
        },
        "dims": list(_DIMS),
        "excluded_sets": [],
        "coverage": {name: 2 for name in _SETS},
        "roles": dict(_ROLES),
        "centroid_train_only": {dim: _CENTROID for dim in _DIMS},
        "units": [
            {"unit": unit, "target": {dim: _value(unit) for dim in _DIMS}}
            for unit in _UNITS
        ],
    }


def _target(
    root: Path,
    dataset_id: str = "replogle-2022-k562-essential-scperturb",
    holdout_value: float | None = None,
) -> Path:
    path = root / "target.json"
    path.write_text(
        json.dumps(_target_payload(dataset_id, holdout_value)), encoding="utf-8"
    )
    return path


def _predictions_payload(
    target_path: Path,
    *,
    mlp_shift: float = -0.001,
    ridge_shift: float = 0.004,
    holdout_target: float | None = None,
) -> dict:
    def _value(unit: str) -> float:
        if holdout_target is not None and _ROLES[unit] == "holdout":
            return holdout_target
        return _TARGETS[unit]

    return {
        "schema_version": PREDICTIONS_SCHEMA_VERSION,
        "target_id": "replogle-kd-hallmark-target-fixture",
        "target_sha256": _sha256(target_path),
        "training": dict(FROZEN_HALLMARK_TRAINING)
        | {
            "torch_version": "fixture",
            "final_train_loss_mse": 0.0001,
            "output_dim": len(_DIMS),
            "embedding_table_sha256": "e" * 64,
            "embedding_dim": 768,
            "covered_units": len(_UNITS),
            "excluded_units": 0,
            "centroid_crosscheck_max_abs_diff": 0.0,
        },
        "weights": {"path": "w.npz", "sha256": "c" * 64, "bytes": 10},
        "split": {"salt": "fixture-salt", "train_units": 4, "holdout_units": 2},
        "dims": list(_DIMS),
        "units": [
            {
                "unit": unit,
                "role": _ROLES[unit],
                "target": [_value(unit)] * len(_DIMS),
                "centroid_pred": [_CENTROID] * len(_DIMS),
                "ridge_pred": [_value(unit) + ridge_shift] * len(_DIMS),
                "mlp_pred": [_value(unit) + mlp_shift] * len(_DIMS),
            }
            for unit in _UNITS
        ],
    }


def _write_predictions(root: Path, target_path: Path, **overrides) -> Path:
    path = root / "predictions.json"
    path.write_text(
        json.dumps(_predictions_payload(target_path, **overrides)), encoding="utf-8"
    )
    return path


class PredictionsGateTests(unittest.TestCase):
    def test_valid_predictions_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = _target(root)
            loaded = load_hallmark_predictions(_write_predictions(root, target))
            self.assertEqual(6, len(loaded.units))
            self.assertEqual(_DIMS, loaded.dims)
            self.assertEqual(64, len(loaded.predictions_digest))

    def test_rejections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = _target(root)
            good = _predictions_payload(target)
            cases = []
            cases.append((dict(good, schema_version="other"), "unsupported"))
            bad_param = json.loads(json.dumps(good))
            bad_param["training"]["epochs"] = 10
            cases.append((bad_param, "frozen training parameter"))
            bad_input = json.loads(json.dumps(good))
            bad_input["training"]["input_dim"] = 105
            cases.append((bad_input, "frozen training parameter"))
            bad_check = json.loads(json.dumps(good))
            bad_check["training"]["centroid_crosscheck_max_abs_diff"] = 1e-6
            cases.append((bad_check, "cross-check"))
            bad_dim = json.loads(json.dumps(good))
            bad_dim["training"]["output_dim"] = 6
            cases.append((bad_dim, "output_dim"))
            bad_len = json.loads(json.dumps(good))
            bad_len["units"][0]["target"] = [0.1]
            cases.append((bad_len, "element list"))
            bad_tail = json.loads(json.dumps(good))
            bad_tail["dims"][-1] = "HALLMARK_SNEAKY"
            bad_tail["units"] = [
                {**unit, "target": unit["target"]} for unit in bad_tail["units"]
            ]
            cases.append((bad_tail, "six-node"))
            for payload, fragment in cases:
                with self.subTest(fragment=fragment):
                    path = root / "case.json"
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, fragment):
                        load_hallmark_predictions(path)


class TamperTests(unittest.TestCase):
    def test_target_sha_mismatch_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = _target(root)
            loaded = load_hallmark_predictions(_write_predictions(root, target))
            other = root / "other.json"
            payload = _target_payload("replogle-2022-k562-essential-scperturb")
            payload["scientific_boundary"] = "tampered"
            other.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                evaluate_hallmark_training(loaded, other)

    def test_unit_target_tamper_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = _target(root)
            payload = _predictions_payload(target)
            payload["units"][0]["target"][0] += 1e-6
            path = root / "predictions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "target vector tampered"):
                evaluate_hallmark_training(load_hallmark_predictions(path), target)

    def test_role_tamper_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = _target(root)
            payload = _predictions_payload(target)
            payload["units"][0]["role"] = "holdout"
            path = root / "predictions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "role tampered"):
                evaluate_hallmark_training(load_hallmark_predictions(path), target)

    def test_centroid_prediction_tamper_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = _target(root)
            payload = _predictions_payload(target)
            for unit in payload["units"]:
                unit["centroid_pred"] = [value + 1e-6 for value in unit["centroid_pred"]]
            path = root / "predictions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "centroid prediction tampered"):
                evaluate_hallmark_training(load_hallmark_predictions(path), target)

    def test_embedded_centroid_tamper_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = _target(root)
            predictions = _write_predictions(root, target)
            payload = _target_payload("replogle-2022-k562-essential-scperturb")
            payload["centroid_train_only"] = {
                dim: _CENTROID + 1e-6 for dim in _DIMS
            }
            target.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_hallmark_predictions(_write_predictions(root, target))
            with self.assertRaisesRegex(ValueError, "centroid_train_only disagrees"):
                evaluate_hallmark_training(loaded, target)

    def test_unknown_dataset_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = _target(root, dataset_id="mystery-dataset")
            payload = _predictions_payload(target)
            payload["target_id"] = "norman-hallmark-target-fixture"
            path = root / "predictions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no frozen arm"):
                evaluate_hallmark_training(load_hallmark_predictions(path), target)

    def test_unit_outside_target_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = _target(root)
            payload = _predictions_payload(target)
            payload["units"].append(
                {
                    "unit": "GHOST",
                    "role": "holdout",
                    "target": [0.0] * len(_DIMS),
                    "centroid_pred": [_CENTROID] * len(_DIMS),
                    "ridge_pred": [0.0] * len(_DIMS),
                    "mlp_pred": [0.0] * len(_DIMS),
                }
            )
            path = root / "predictions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "outside the target"):
                evaluate_hallmark_training(load_hallmark_predictions(path), target)


class VerdictTests(unittest.TestCase):
    def _evaluate(self, root: Path, **overrides) -> dict:
        target = _target(root)
        predictions = load_hallmark_predictions(
            _write_predictions(root, target, **overrides)
        )
        return evaluate_hallmark_training(predictions, target)

    def test_passed_branch_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._evaluate(Path(tmp), mlp_shift=-0.001)
            rule = result["pass_rule"]
            self.assertEqual("passed", rule["verdict"])
            self.assertEqual("primary", result["arm"])
            self.assertGreater(rule["margin_vs_centroid"], PASS_EPSILON)
            self.assertGreater(rule["margin_vs_ridge"], PASS_EPSILON)
            holdout = result["metrics"]["six_node_head"]["holdout"]
            self.assertEqual(2, holdout["mlp"]["unit_count"])
            self.assertAlmostEqual(0.001, holdout["mlp"]["mae"], places=12)
            self.assertAlmostEqual(0.004, holdout["ridge"]["mae"], places=12)
            self.assertAlmostEqual(0.03, holdout["centroid"]["mae"], places=12)
            set_dims = result["metrics"]["set_dims"]["holdout"]
            self.assertAlmostEqual(0.001, set_dims["mlp"]["mean_mae"], places=12)
            self.assertEqual(2, result["metrics"]["set_dims"]["set_dim_count"])
            self.assertTrue(
                result["evaluation_id"].startswith("hallmark-training-eval-")
            )
            self.assertEqual(EVALUATION_SCHEMA_VERSION, result["schema_version"])

    def test_failed_by_ridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._evaluate(Path(tmp), mlp_shift=0.004, ridge_shift=-0.001)
            self.assertEqual("failed", result["pass_rule"]["verdict"])
            self.assertIn(
                "mlp does not beat ridge on holdout", result["pass_rule"]["reasons"]
            )

    def test_failed_by_centroid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._evaluate(Path(tmp), mlp_shift=0.05)
            self.assertEqual("failed", result["pass_rule"]["verdict"])
            self.assertIn(
                "mlp does not beat the train-only centroid on holdout",
                result["pass_rule"]["reasons"],
            )

    def test_margin_exactly_epsilon_fails(self) -> None:
        # margin_vs_ridge == PASS_EPSILON (the double 1e-12) exactly: the rule
        # requires a STRICTLY greater margin, so the arm must fail.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = _target(root, holdout_value=0.0)
            payload = _predictions_payload(target, holdout_target=0.0)
            for unit in payload["units"]:
                if unit["role"] != "holdout":
                    continue
                unit["mlp_pred"] = [0.0] * len(_DIMS)
                unit["ridge_pred"] = [PASS_EPSILON] * len(_DIMS)
            path = root / "predictions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = evaluate_hallmark_training(load_hallmark_predictions(path), target)
            self.assertEqual(PASS_EPSILON, result["pass_rule"]["margin_vs_ridge"])
            self.assertEqual("failed", result["pass_rule"]["verdict"])

    def test_margin_above_epsilon_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = _target(root, holdout_value=0.0)
            payload = _predictions_payload(target, holdout_target=0.0)
            for unit in payload["units"]:
                if unit["role"] != "holdout":
                    continue
                unit["mlp_pred"] = [0.0] * len(_DIMS)
                unit["ridge_pred"] = [2 * PASS_EPSILON] * len(_DIMS)
            path = root / "predictions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = evaluate_hallmark_training(load_hallmark_predictions(path), target)
            self.assertEqual(2 * PASS_EPSILON, result["pass_rule"]["margin_vs_ridge"])
            self.assertEqual("passed", result["pass_rule"]["verdict"])

    def test_descriptive_arm_verdict_literal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = _target(root, dataset_id="norman-weissman-2019-scperturb-filtered")
            payload = _predictions_payload(target)
            payload["target_id"] = "norman-hallmark-target-fixture"
            path = root / "predictions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = evaluate_hallmark_training(load_hallmark_predictions(path), target)
            self.assertEqual("descriptive", result["arm"])
            self.assertEqual("descriptive", result["pass_rule"]["verdict"])
            # margins are still recomputed and reported for the descriptive arm
            self.assertGreater(result["pass_rule"]["margin_vs_centroid"], PASS_EPSILON)
            self.assertIn(
                "descriptive arm; no pass claim (ADR-0040 precedent)",
                result["pass_rule"]["reasons"],
            )

    def test_write_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._evaluate(root)
            output = root / "eval.json"
            save_hallmark_training_evaluation(result, output)
            self.assertTrue(output.exists())
            save_hallmark_training_evaluation(result, output)  # identical no-op
            other = dict(result, arm="tampered")
            with self.assertRaisesRegex(ValueError, "overwrite"):
                save_hallmark_training_evaluation(other, output)

    def test_cli_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = _target(root)
            predictions = _write_predictions(root, target)
            output = root / "out.json"
            stdout = StringIO()
            argv = [
                "mgba",
                "hallmark-training-evaluate",
                "--predictions",
                str(predictions),
                "--target",
                str(target),
                "--output",
                str(output),
            ]
            with mock.patch("sys.argv", argv), redirect_stdout(stdout):
                cli_main()
            result = json.loads(stdout.getvalue())
            self.assertEqual("passed", result["verdict"])
            self.assertEqual("primary", result["arm"])
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(saved["evaluation_id"].startswith("hallmark-training-eval-"))


if __name__ == "__main__":
    unittest.main()
