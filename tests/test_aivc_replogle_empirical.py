"""Numeric tests for the ADR-0039 Replogle dense-X empirical segment.

Runs under .venv-train (h5py/numpy) and anywhere those exist; skipped otherwise.
The fixture is hand-computed: dense X with known integer counts.
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
SCRIPT_PATH = ROOT / "scripts" / "aivc_replogle_empirical.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("aivc_replogle_empirical", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(H5PY_AVAILABLE, "h5py only exists in the .venv-train environment")
class ReplogleEmpiricalTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        import h5py
        import numpy as np

        gmt = root / "hallmark.gmt"
        gmt.write_text(
            "HALLMARK_A\tu\tG1\tG2\nHALLMARK_B\tu\tG3\n", encoding="utf-8"
        )
        # 100 cells: 0-49 control (G1=10, G3=40), 50-99 U1 (G1=20, G2=10, G3=20).
        # G4 carries counts (lib=50 for all) but is outside the universe.
        x = np.zeros((100, 4), dtype=np.float32)
        x[0:50, 0] = 10.0
        x[0:50, 2] = 40.0
        x[50:100, 0] = 20.0
        x[50:100, 1] = 10.0
        x[50:100, 2] = 20.0
        x[:, 3] = 0.0
        h5ad = root / "toy.h5ad"
        with h5py.File(h5ad, "w") as handle:
            handle.create_dataset("X", data=x)
            var = handle.create_group("var")
            var.create_dataset("gene_name", data=[b"G1", b"G2", b"G3", b"G4"])
            obs = handle.create_group("obs")
            pert = obs.create_group("perturbation")
            pert.create_dataset("categories", data=[b"control", b"U1"])
            pert.create_dataset(
                "codes", data=np.array([0] * 50 + [1] * 50, dtype=np.int16)
            )
        return h5ad, gmt

    def test_dense_hand_computed_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h5ad, gmt = self._fixture(root)
            bundle = _load_script().build_bundle(h5ad, gmt)
            self.assertEqual("replogle-2022-k562-essential-scperturb", bundle["dataset_id"])
            self.assertEqual("none-filtered-release", bundle["parameters"]["qc_flag"])
            self.assertEqual(["G1", "G2", "G3"], bundle["gene_universe"]["genes"])
            self.assertEqual(50, bundle["control_cells"])
            self.assertEqual(1, len(bundle["units"]))
            unit = bundle["units"][0]
            self.assertEqual("U1", unit["unit"])
            expected = (
                math.log2(4001 / 2001),
                math.log2(2001),
                math.log2(4001 / 8001),
            )
            for got, want in zip(unit["log2fc"], expected, strict=True):
                self.assertAlmostEqual(want, got, places=12)
            self.assertEqual(
                sha256(h5ad.read_bytes()).hexdigest(), bundle["source"]["sha256"]
            )

    def test_under_50_unit_rejected_fail_closed(self) -> None:
        import h5py
        import numpy as np

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h5ad, gmt = self._fixture(root)
            with h5py.File(h5ad, "a") as handle:
                pert = handle["obs/perturbation"]
                del pert["codes"]
                pert.create_dataset(
                    "codes",
                    data=np.array([0] * 50 + [1] * 49 + [0], dtype=np.int16),
                )
            with self.assertRaisesRegex(ValueError, "no perturbation unit"):
                _load_script().build_bundle(h5ad, gmt)


if __name__ == "__main__":
    unittest.main()
