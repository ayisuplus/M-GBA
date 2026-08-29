"""Tests for ADR-0042: profile cross-check and GEO-native bundle gates."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
from pathlib import Path
from unittest import mock

from mgba.cli import main as cli_main
from mgba.layers.l0 import ABSTRACT_GENE_NAMES
from mgba.perturbation_anchors import (
    CROSSCHECK_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
    compare_profiles,
    load_empirical_bundle,
    load_profile_for_crosscheck,
    save_crosscheck,
)

ROOT = Path(__file__).parents[1]
SCRIPT_PATH = ROOT / "scripts" / "aivc_norman_geo_empirical.py"


def _load_rollup():
    spec = importlib.util.spec_from_file_location("aivc_norman_geo_empirical", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.rollup_unit


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _vector(seed: float) -> dict[str, float]:
    return {
        node: seed * (index + 1) * 0.01 * (1.0 if index % 2 == 0 else -1.0)
        for index, node in enumerate(ABSTRACT_GENE_NAMES)
    }


def _profile(root: Path, name: str, units: dict[str, list[float]], pid: str) -> Path:
    path = root / f"{name}.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": PROFILE_SCHEMA_VERSION,
                "profile_id": pid,
                "units": [
                    {"unit": unit, "six_node_vector": vector}
                    for unit, vector in sorted(units.items())
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


@unittest.skipUnless(
    importlib.util.find_spec("pandas") is not None
    and importlib.util.find_spec("numpy") is not None,
    "pandas/numpy only in the train venv",
)
class RollupTests(unittest.TestCase):
    def test_frozen_rollup_rule(self) -> None:
        rollup = _load_rollup()
        self.assertEqual("control", rollup("NegCtrl10_NegCtrl0__NegCtrl10_NegCtrl0"))
        self.assertEqual("KLF1", rollup("KLF1_NegCtrl0__KLF1_NegCtrl0"))
        self.assertEqual("BAK1", rollup("NegCtrl0_BAK1__NegCtrl0_BAK1"))
        self.assertEqual("DUSP9_ETS2", rollup("DUSP9_ETS2__DUSP9_ETS2"))
        # Non-NegCtrl tokens are all kept (real guide suffixes are NegCtrl* only)
        self.assertEqual("A_X_B_Y_C_Z", rollup("A_X__B_Y__C_Z"))


class CrosscheckTests(unittest.TestCase):
    def _pair(self, root: Path, *, divergent: bool = False) -> tuple[Path, Path]:
        units_a = {f"U{i:02d}": _vector(float(i)) for i in range(12)}
        if divergent:
            units_b = {
                unit: {
                    node: value * -3.7
                    for node, value in _vector(float(index + 40)).items()
                }
                for index, unit in enumerate(units_a)
            }
        else:
            units_b = {unit: dict(vector) for unit, vector in units_a.items()}
        a = _profile(root, "a", units_a, "profile-a")
        b = _profile(root, "b", units_b, "profile-b")
        return a, b

    def test_consistent_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a, b = self._pair(Path(tmp))
            result = compare_profiles(load_profile_for_crosscheck(a), load_profile_for_crosscheck(b))
            self.assertEqual(CROSSCHECK_SCHEMA_VERSION, result["schema_version"])
            self.assertEqual("consistent", result["verdict"])
            self.assertEqual(12, result["shared_units"])
            self.assertAlmostEqual(1.0, result["metrics"]["flattened_spearman"], places=9)
            self.assertAlmostEqual(1.0, result["metrics"]["mean_sign_agreement"], places=9)
            self.assertEqual(0.0, result["metrics"]["mean_mae"])

    def test_inconsistent_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a, b = self._pair(Path(tmp), divergent=True)
            result = compare_profiles(load_profile_for_crosscheck(a), load_profile_for_crosscheck(b))
            self.assertEqual("inconsistent", result["verdict"])

    def test_too_few_shared_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = _profile(root, "a", {f"A{i}": _vector(float(i)) for i in range(12)}, "pa")
            b = _profile(root, "b", {f"B{i}": _vector(float(i)) for i in range(12)}, "pb")
            with self.assertRaisesRegex(ValueError, "too few shared units"):
                compare_profiles(load_profile_for_crosscheck(a), load_profile_for_crosscheck(b))

    def test_node_order_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = _profile(root, "a", {f"A{i}": _vector(float(i)) for i in range(12)}, "pa")
            raw = json.loads(a.read_text(encoding="utf-8"))
            raw["units"][0]["six_node_vector"] = dict(
                reversed(list(raw["units"][0]["six_node_vector"].items()))
            )
            a.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "node order"):
                load_profile_for_crosscheck(a)

    def test_write_once_and_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a, b = self._pair(root)
            out = root / "cc.json"
            stdout = StringIO()
            argv = ["mgba", "aivc-crosscheck", "--profile-a", str(a), "--profile-b", str(b), "--output", str(out)]
            with mock.patch("sys.argv", argv), redirect_stdout(stdout):
                cli_main()
            result = json.loads(stdout.getvalue())
            self.assertEqual("consistent", result["verdict"])
            with self.assertRaisesRegex(ValueError, "overwrite"):
                save_crosscheck(compare_profiles(
                    load_profile_for_crosscheck(a), load_profile_for_crosscheck(b)
                ), out)


class GeoBundleGateTests(unittest.TestCase):
    def _geo_payload(self) -> dict:
        from test_perturbation_anchors import _bundle_payload

        payload = _bundle_payload()
        payload["dataset_id"] = "norman-weissman-2019-geo-native"
        payload["auxiliary_sources"] = {
            "barcodes_sha256": "1" * 64,
            "genes_sha256": "2" * 64,
            "cell_identities_sha256": "3" * 64,
        }
        return payload

    def test_geo_extra_keys_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.json"
            path.write_text(json.dumps(self._geo_payload()), encoding="utf-8")
            bundle = load_empirical_bundle(path)
            self.assertEqual("norman-weissman-2019-geo-native", bundle.dataset_id)

    def test_aux_sha_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = self._geo_payload()
            payload["auxiliary_sources"]["genes_sha256"] = "nope"
            path = Path(tmp) / "b.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hexadecimal"):
                load_empirical_bundle(path)

    def test_extra_key_rejected_for_norman(self) -> None:
        from test_perturbation_anchors import _bundle_payload

        with tempfile.TemporaryDirectory() as tmp:
            payload = _bundle_payload()
            payload["auxiliary_sources"] = {"barcodes_sha256": "1" * 64, "genes_sha256": "2" * 64, "cell_identities_sha256": "3" * 64}
            path = Path(tmp) / "b.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "keys mismatch"):
                load_empirical_bundle(path)


if __name__ == "__main__":
    unittest.main()
