"""Tests for the ADR-0038 empirical L0 paired matrix."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from mgba.cli import main as cli_main
from mgba.empirical_l0_experiments import (
    EMPIRICAL_L0_COMPARISONS,
    EMPIRICAL_L0_CONDITIONS,
    EmpiricalL0ComparisonRunner,
    load_empirical_l0_comparison_config,
    save_empirical_l0_artifacts,
)
from mgba.empirical_response import EmpiricalResponseTable
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l0_empirical import EmpiricalResponseGrnModel
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config
from mgba.layers.l2 import CellStateMachineModel, load_cell_config
from mgba.layers.l3 import TissueEnvironmentModel, load_tissue_config
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.multiscale import load_multiscale_scenario
from mgba.runner import MultirateCrossScaleRunner, load_runner_config

ROOT = Path(__file__).parents[1]
CONFIGS = ROOT / "configs"
_UNIT = "BAK1"
_VECTOR = [0.01, -0.005, 0.003, 0.004, -0.001, -0.002]


def _table() -> EmpiricalResponseTable:
    return EmpiricalResponseTable(
        table_id="l0-response-table-fixture",
        source={"verdict": "passed"},
        vectors=((_UNIT, tuple(_VECTOR)),),
        table_digest="d" * 64,
    )


def _models(*, empirical: bool) -> dict[str, object]:
    genome_model: object
    if empirical:
        genome_model = EmpiricalResponseGrnModel(
            load_grn_config(CONFIGS / "layers" / "l0_reference_grn.json"),
            response_table=_table(),
            table_path="fixture-table.json",
        )
    else:
        genome_model = DiscreteGrnModel(
            load_grn_config(CONFIGS / "layers" / "l0_reference_grn.json")
        )
    return {
        "genome_model": genome_model,
        "molecular_model": CoarseMolecularModel(
            load_molecular_config(CONFIGS / "layers" / "l1_reference_molecular.json")
        ),
        "cell_model": CellStateMachineModel(
            load_cell_config(CONFIGS / "layers" / "l2_reference_cell.json")
        ),
        "tissue_model": TissueEnvironmentModel(
            load_tissue_config(CONFIGS / "layers" / "l3_reference_tissue.json")
        ),
        "phenotype_model": PhenotypeObserverModel(
            load_phenotype_config(CONFIGS / "layers" / "l4_reference_phenotype.json")
        ),
    }


def _runner(empirical: bool) -> MultirateCrossScaleRunner:
    return MultirateCrossScaleRunner(
        load_runner_config(CONFIGS / "runner_reference.json"), **_models(empirical=empirical)
    )


def _config(root: Path | None = None) -> object:
    if root is None:
        return load_empirical_l0_comparison_config(
            CONFIGS / "experiments" / "empirical_l0_comparison.json"
        )
    path = root / "matrix.json"
    path.write_text(
        json.dumps(
            {
                "model_version": "empirical-l0-comparison-test",
                "ticks": 6,
                "seeds": [41, 42],
                "cell_id": "cell-a",
                "unit": _UNIT,
                "reference_node": "damage_response",
                "dose": 1.0,
            }
        ),
        encoding="utf-8",
    )
    return load_empirical_l0_comparison_config(path)


class ConfigGateTests(unittest.TestCase):
    def test_real_config_loads(self) -> None:
        config = _config()
        self.assertEqual((41, 42, 43), config.seeds)
        self.assertEqual(_UNIT, config.unit)

    def test_validation(self) -> None:
        base = {
            "model_version": "x",
            "ticks": 6,
            "seeds": [41, 42],
            "cell_id": "cell-a",
            "unit": "U",
            "reference_node": "damage_response",
            "dose": 1.0,
        }
        for key, value, fragment in (
            ("ticks", 0, "positive integer"),
            ("seeds", [42, 41], "unique and sorted"),
            ("dose", 0.0, "\\(0, 1\\]"),
            ("unit", " ", "must not be empty"),
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                payload = dict(base, **{key: value})
                path = Path(tmp) / "c.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, fragment):
                    load_empirical_l0_comparison_config(path)


class MatrixTests(unittest.TestCase):
    def test_l0_only_gate(self) -> None:
        config = _config()
        reference = _runner(empirical=False)
        wrong = MultirateCrossScaleRunner(
            load_runner_config(CONFIGS / "runner_reference.json"),
            **_models(empirical=False),
            feedback_policy=None,
        )
        with self.assertRaisesRegex(ValueError, "L0 only"):
            EmpiricalL0ComparisonRunner(
                config, baseline_runner=reference, empirical_runner=wrong
            )

    def test_full_matrix_and_identity_gate(self) -> None:
        config = _config()
        matrix = EmpiricalL0ComparisonRunner(
            config,
            baseline_runner=_runner(empirical=False),
            empirical_runner=_runner(empirical=True),
        ).run(load_multiscale_scenario(CONFIGS / "multiscale_demo.json"))
        self.assertTrue(matrix.baseline_identity_verified)
        self.assertEqual(9, len(matrix.records))
        self.assertEqual(9, len(matrix.comparisons))
        self.assertEqual(
            tuple(
                comparison_id
                for comparison_id in EMPIRICAL_L0_COMPARISONS
                for _seed in config.seeds
            ),
            tuple(comparison.condition_id for comparison in matrix.comparisons),
        )
        clamp = next(
            c for c in matrix.comparisons if c.condition_id == "reference_clamp_vs_baseline" and c.seed == 41
        )
        empirical = next(
            c for c in matrix.comparisons if c.condition_id == "empirical_vs_baseline" and c.seed == 41
        )
        clamp_l0 = dict(clamp.layer_effects)["L0"]
        empirical_l0 = dict(empirical.layer_effects)["L0"]
        self.assertGreater(clamp_l0, 0.0)
        self.assertGreater(empirical_l0, 0.0)
        self.assertGreater(clamp_l0, empirical_l0)  # hard clamp dominates a subtle vector
        self.assertEqual(3, len(matrix.summaries))

    def test_artifacts_write_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            matrix = EmpiricalL0ComparisonRunner(
                config,
                baseline_runner=_runner(empirical=False),
                empirical_runner=_runner(empirical=True),
            ).run(load_multiscale_scenario(CONFIGS / "multiscale_demo.json"))
            root = Path(tmp) / "artifacts"
            first = save_empirical_l0_artifacts(root, matrix)
            self.assertTrue(first["manifest"].exists())
            save_empirical_l0_artifacts(root, matrix)  # identical: fine
            payload = json.loads(first["summary"].read_text(encoding="utf-8"))
            payload["matrix_id"] = "tampered"
            first["summary"].write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different"):
                save_empirical_l0_artifacts(root, matrix)


class CliTests(unittest.TestCase):
    def test_cli_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "matrix.json"
            _config(root)
            layer_config = root / "layer.json"
            layer_config.write_text(
                json.dumps(
                    {
                        "model_version": "empirical-l0-response-0.1",
                        "response_table_path": "unused.json",
                        "response_table_sha256": "0" * 64,
                    }
                ),
                encoding="utf-8",
            )
            # The CLI loads the real table through the identity config, so
            # build one against the real derived artifacts.
            table_path = ROOT / "data" / "aivc" / "derived" / "l0-response-table.json"
            if not table_path.exists():
                self.skipTest("real response table not built on this machine")
            import hashlib

            layer_config.write_text(
                json.dumps(
                    {
                        "model_version": "empirical-l0-response-0.1",
                        "response_table_path": str(table_path).replace("\\", "/"),
                        "response_table_sha256": hashlib.sha256(
                            table_path.read_bytes()
                        ).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            argv = [
                "mgba",
                "empirical-l0-experiment",
                "--config",
                str(CONFIGS / "multiscale_demo.json"),
                "--matrix-config",
                str(config_path),
                "--runner-config",
                str(CONFIGS / "runner_reference.json"),
                "--l0-config",
                str(CONFIGS / "layers" / "l0_reference_grn.json"),
                "--l1-config",
                str(CONFIGS / "layers" / "l1_reference_molecular.json"),
                "--l2-config",
                str(CONFIGS / "layers" / "l2_reference_cell.json"),
                "--l3-config",
                str(CONFIGS / "layers" / "l3_reference_tissue.json"),
                "--l4-config",
                str(CONFIGS / "layers" / "l4_reference_phenotype.json"),
                "--empirical-l0-config",
                str(layer_config),
            ]
            stdout = StringIO()
            with mock.patch("sys.argv", argv), redirect_stdout(stdout):
                cli_main()
            result = json.loads(stdout.getvalue())
            self.assertTrue(result["baseline_identity_verified"])
            self.assertEqual(6, len(result["comparisons"]))


if __name__ == "__main__":
    unittest.main()
