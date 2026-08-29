"""Tests for the ADR-0037 core training-evaluation segment."""

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
from mgba.experiment import digest_payload
from mgba.l0_training_evaluation import (
    ENCODING_EMBEDDING,
    ENCODING_ONEHOT,
    EVALUATION_SCHEMA_VERSION,
    FROZEN_TRAINING,
    PASS_EPSILON,
    PREDICTIONS_SCHEMA_VERSION,
    evaluate_training,
    load_response_predictions,
    save_training_evaluation,
)
from mgba.layers.l0 import ABSTRACT_GENE_NAMES

_NODES = ABSTRACT_GENE_NAMES
_UNITS = ("U1", "U2", "U3", "U4", "U5", "U6")
_ROLES = {"U1": "train", "U2": "train", "U3": "train", "U4": "train", "U5": "holdout", "U6": "holdout"}
_TARGETS = {unit: [0.01 * (index + 1)] * 6 for index, unit in enumerate(_UNITS)}
_CENTROID = [0.025] * 6  # mean of U1..U4 targets per node


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _profile(root: Path) -> Path:
    payload = {
        "profile_id": "norman-perturbation-profile-fixture",
        "centroid_train_only": dict(zip(_NODES, _CENTROID)),
        "units": [
            {
                "unit": unit,
                "cells": 50,
                "role": _ROLES[unit],
                "six_node_vector": dict(zip(_NODES, _TARGETS[unit])),
            }
            for unit in _UNITS
        ],
    }
    path = root / "profile.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _predictions_payload(
    profile_path: Path, *, mlp_shift: float = -0.001, ridge_shift: float = 0.004
) -> dict:
    centroid_mae_holdout = sum(
        abs(_CENTROID[0] - _TARGETS[unit][0]) for unit in ("U5", "U6")
    ) / 2.0

    def _pred(unit: str, shift: float) -> list[float]:
        return [value + shift for value in _TARGETS[unit]]

    return {
        "schema_version": PREDICTIONS_SCHEMA_VERSION,
        "profile_id": "norman-perturbation-profile-fixture",
        "profile_sha256": _sha256(profile_path),
        "training": dict(FROZEN_TRAINING)
        | {
            "torch_version": "fixture",
            "final_train_loss_mse": 0.0001,
            "component_vocab_size": 4,
            "combo_units": 0,
        },
        "weights": {"path": "w.pt", "sha256": "c" * 64, "bytes": 10},
        "split": {"salt": "fixture-salt", "train_units": 4, "holdout_units": 2},
        "centroid_crosscheck_max_abs_diff": 0.0,
        "units": [
            {
                "unit": unit,
                "role": _ROLES[unit],
                "target": list(_TARGETS[unit]),
                "centroid_pred": list(_CENTROID),
                "ridge_pred": _pred(unit, ridge_shift),
                "mlp_pred": _pred(unit, mlp_shift),
            }
            for unit in _UNITS
        ],
        "_expected_centroid_mae": centroid_mae_holdout,
    }


def _write_predictions(root: Path, profile_path: Path, **overrides) -> Path:
    payload = _predictions_payload(profile_path, **overrides)
    payload.pop("_expected_centroid_mae", None)
    path = root / "predictions.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class PredictionsGateTests(unittest.TestCase):
    def test_valid_predictions_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = _profile(root)
            loaded = load_response_predictions(_write_predictions(root, profile))
            self.assertEqual(6, len(loaded.units))
            self.assertEqual(64, len(loaded.predictions_digest))

    def test_rejections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = _profile(root)
            good = _predictions_payload(profile)
            good.pop("_expected_centroid_mae")
            cases = []
            bad_schema = dict(good, schema_version="other")
            cases.append((bad_schema, "unsupported"))
            bad_param = json.loads(json.dumps(good))
            bad_param["training"]["epochs"] = 10
            cases.append((bad_param, "frozen training parameter"))
            bad_check = dict(good, centroid_crosscheck_max_abs_diff=1e-6)
            cases.append((bad_check, "cross-check"))
            bad_role = json.loads(json.dumps(good))
            bad_role["units"][0]["role"] = "holdout"
            cases.append((bad_role, None))  # passes loader, fails evaluation
            short = json.loads(json.dumps(good))
            short["units"][0]["target"] = [0.1]
            cases.append((short, "six-element"))
            for payload, fragment in cases:
                path = root / "case.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.subTest(fragment=str(fragment)):
                    if fragment is None:
                        loaded = load_response_predictions(path)
                        with self.assertRaisesRegex(ValueError, "role tampered"):
                            evaluate_training(loaded, profile)
                    else:
                        with self.assertRaisesRegex(ValueError, fragment):
                            load_response_predictions(path)

    def test_profile_mismatch_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = _profile(root)
            loaded = load_response_predictions(_write_predictions(root, profile))
            other = root / "other.json"
            other.write_text(json.dumps({"profile_id": "x", "units": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                evaluate_training(loaded, other)


class EmbeddingEncodingTests(unittest.TestCase):
    def _embedding_payload(self, profile_path: Path, *, exclude_u6: bool = True) -> dict:
        units = [u for u in _UNITS if not (exclude_u6 and u == "U6")]
        covered_train = [u for u in units if _ROLES[u] == "train"]
        covered_centroid = [
            sum(_TARGETS[u][i] for u in covered_train) / len(covered_train)
            for i in range(6)
        ]
        return {
            "schema_version": PREDICTIONS_SCHEMA_VERSION,
            "profile_id": "norman-perturbation-profile-fixture",
            "profile_sha256": _sha256(profile_path),
            "training": dict(FROZEN_TRAINING)
            | {
                "torch_version": "fixture",
                "final_train_loss_mse": 0.0001,
                "feature_encoding": ENCODING_EMBEDDING,
                "embedding_table_sha256": "e" * 64,
                "embedding_dim": 768,
                "covered_units": len(units),
                "excluded_units": len(_UNITS) - len(units),
                "centroid_drift_vs_profile": 0.0002,
            },
            "weights": {"path": "w.npz", "sha256": "c" * 64, "bytes": 10},
            "split": {"salt": "fixture-salt", "train_units": 4, "holdout_units": 1},
            "units": [
                {
                    "unit": unit,
                    "role": _ROLES[unit],
                    "target": list(_TARGETS[unit]),
                    "centroid_pred": list(covered_centroid),
                    "ridge_pred": [v + 0.004 for v in _TARGETS[unit]],
                    "mlp_pred": [v - 0.001 for v in _TARGETS[unit]],
                }
                for unit in units
            ],
        }

    def test_embedding_encoding_roundtrip_and_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = _profile(root)
            path = root / "pred.json"
            path.write_text(
                json.dumps(self._embedding_payload(profile)), encoding="utf-8"
            )
            loaded = load_response_predictions(path)
            self.assertEqual(ENCODING_EMBEDDING, loaded.training["feature_encoding"])
            self.assertEqual(5, len(loaded.units))
            result = evaluate_training(loaded, profile)
            self.assertEqual("passed", result["pass_rule"]["verdict"])

    def test_unknown_encoding_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = _profile(root)
            payload = self._embedding_payload(profile)
            payload["training"]["feature_encoding"] = "mystery"
            path = root / "pred.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown feature encoding"):
                load_response_predictions(path)

    def test_unit_outside_profile_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = _profile(root)
            payload = self._embedding_payload(profile)
            payload["units"].append(
                {
                    "unit": "GHOST",
                    "role": "holdout",
                    "target": [0.0] * 6,
                    "centroid_pred": [0.0] * 6,
                    "ridge_pred": [0.0] * 6,
                    "mlp_pred": [0.0] * 6,
                }
            )
            path = root / "pred.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_response_predictions(path)
            with self.assertRaisesRegex(ValueError, "outside the profile"):
                evaluate_training(loaded, profile)

    def test_covered_centroid_tamper_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = _profile(root)
            payload = self._embedding_payload(profile)
            for unit in payload["units"]:
                unit["centroid_pred"] = [v + 1e-6 for v in unit["centroid_pred"]]
            path = root / "pred.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_response_predictions(path)
            with self.assertRaisesRegex(ValueError, "centroid prediction tampered"):
                evaluate_training(loaded, profile)


class VerdictTests(unittest.TestCase):
    def _evaluate(self, root: Path, **overrides) -> dict:
        profile = _profile(root)
        predictions = load_response_predictions(
            _write_predictions(root, profile, **overrides)
        )
        return evaluate_training(predictions, profile)

    def test_passed_branch_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._evaluate(Path(tmp), mlp_shift=-0.001)
            rule = result["pass_rule"]
            self.assertEqual("passed", rule["verdict"])
            self.assertGreater(rule["margin_vs_centroid"], PASS_EPSILON)
            self.assertGreater(rule["margin_vs_ridge"], PASS_EPSILON)
            holdout = result["metrics"]["holdout"]
            self.assertEqual(2, holdout["mlp"]["unit_count"])
            expected_mae = 0.001
            self.assertAlmostEqual(expected_mae, holdout["mlp"]["six_node_mae"], places=12)
            self.assertAlmostEqual(0.004, holdout["ridge"]["six_node_mae"], places=12)
            self.assertTrue(
                result["evaluation_id"].startswith("l0-training-eval-")
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

    def test_tie_margin_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = _profile(root)
            payload = _predictions_payload(profile)
            payload.pop("_expected_centroid_mae")
            # mlp equals centroid on holdout -> zero margin must fail.
            for unit in payload["units"]:
                unit["mlp_pred"] = list(_CENTROID)
            path = root / "predictions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = evaluate_training(load_response_predictions(path), profile)
            self.assertEqual("failed", result["pass_rule"]["verdict"])

    def test_write_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._evaluate(root)
            output = root / "eval.json"
            save_training_evaluation(result, output)
            self.assertTrue(output.exists())
            with self.assertRaisesRegex(ValueError, "overwrite"):
                save_training_evaluation(result, output)

    def test_cli_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = _profile(root)
            predictions = _write_predictions(root, profile)
            output = root / "out.json"
            stdout = StringIO()
            argv = [
                "mgba",
                "l0-training-evaluate",
                "--predictions",
                str(predictions),
                "--profile",
                str(profile),
                "--output",
                str(output),
            ]
            with mock.patch("sys.argv", argv), redirect_stdout(stdout):
                cli_main()
            result = json.loads(stdout.getvalue())
            self.assertEqual("passed", result["verdict"])
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                digest_payload({k: v for k, v in saved.items() if k != "evaluation_id"})
                [:16],
                saved["evaluation_id"].rsplit("-", 1)[1],
            )


if __name__ == "__main__":
    unittest.main()
