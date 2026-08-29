"""Numeric tests for the ADR-0036 empirical segment script (.venv-train only).

These tests need h5py and therefore run under the independent training venv
(``.venv-train``); on the zero-dependency core interpreter they are skipped.
They build a tiny synthetic CSC h5ad whose every expected value is computed by
hand, proving the frozen QC/control/normalization/log2FC rules — no mocking.
"""

from __future__ import annotations

import importlib.util
import json
import math
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

H5PY_AVAILABLE = importlib.util.find_spec("h5py") is not None

ROOT = Path(__file__).parents[1]
SCRIPT_PATH = ROOT / "scripts" / "aivc_norman_empirical.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("aivc_norman_empirical", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(H5PY_AVAILABLE, "h5py only exists in the .venv-train environment")
class EmpiricalSegmentTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        import h5py
        import numpy as np

        gmt = root / "hallmark.gmt"
        gmt.write_text(
            "HALLMARK_A\tu\tG1\tG2\nHALLMARK_B\tu\tG3\n", encoding="utf-8"
        )
        # 101 cells: 0-49 control, 50-99 U1, 100 U1-but-bad-coverage.
        # G1: ctrl 10, U1 20, bad 999; G2: U1 10; G3: ctrl 40, U1 20.
        g1_rows = list(range(0, 100)) + [100]
        g1_vals = [10] * 50 + [20] * 50 + [999]
        g2_rows = list(range(50, 100))
        g2_vals = [10] * 50
        g3_rows = list(range(0, 100))
        g3_vals = [40] * 50 + [20] * 50
        rows = g1_rows + g2_rows + g3_rows
        vals = g1_vals + g2_vals + g3_vals
        indptr = [0, len(g1_rows), len(g1_rows) + len(g2_rows), len(rows)]
        h5ad = root / "toy.h5ad"
        with h5py.File(h5ad, "w") as handle:
            x = handle.create_group("X")
            x.attrs["encoding-type"] = "csc_matrix"
            x.attrs["shape"] = np.array([101, 3])
            x.create_dataset("data", data=np.array(vals, dtype=np.float32))
            x.create_dataset("indices", data=np.array(rows, dtype=np.int32))
            x.create_dataset("indptr", data=np.array(indptr, dtype=np.int32))
            var = handle.create_group("var")
            var.create_dataset("_index", data=[b"G1", b"G2", b"G3"])
            obs = handle.create_group("obs")
            pert = obs.create_group("perturbation")
            pert.create_dataset("categories", data=[b"control", b"U1", b"U2"])
            pert.create_dataset(
                "codes",
                data=np.array([0] * 50 + [1] * 50 + [1], dtype=np.int16),
            )
            obs.create_dataset(
                "good_coverage", data=np.array([True] * 100 + [False])
            )
        return h5ad, gmt

    def test_frozen_rules_and_hand_computed_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h5ad, gmt = self._fixture(root)
            module = _load_script()
            bundle = module.build_bundle(h5ad, gmt)

            self.assertEqual("mgba-aivc-empirical-log2fc-0.1", bundle["schema_version"])
            self.assertEqual(50, bundle["control_cells"])
            self.assertEqual(["G1", "G2", "G3"], bundle["gene_universe"]["genes"])
            self.assertEqual(sha256(h5ad.read_bytes()).hexdigest(), bundle["source"]["sha256"])
            self.assertEqual(sha256(gmt.read_bytes()).hexdigest(), bundle["hallmark_source"]["sha256"])

            # Only U1 passes the frozen >=50 rule; the bad-coverage cell is gone.
            self.assertEqual(1, len(bundle["units"]))
            unit = bundle["units"][0]
            self.assertEqual("U1", unit["unit"])
            self.assertEqual(50, unit["cells"])
            expected = (
                math.log2(4001 / 2001),
                math.log2(2001),
                math.log2(4001 / 8001),
            )
            for got, want in zip(unit["log2fc"], expected, strict=True):
                self.assertAlmostEqual(want, got, places=12)

    def test_cli_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h5ad, gmt = self._fixture(root)
            module = _load_script()
            import sys
            from unittest import mock

            output = root / "bundle.json"
            output.write_text("{}", encoding="utf-8")
            argv = [
                "aivc_norman_empirical.py",
                "--h5ad",
                str(h5ad),
                "--hallmark",
                str(gmt),
                "--output",
                str(output),
            ]
            with mock.patch.object(sys, "argv", argv):
                with self.assertRaises(SystemExit):
                    module.main()


if __name__ == "__main__":
    unittest.main()
