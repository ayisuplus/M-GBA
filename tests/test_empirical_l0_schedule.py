"""Tests for the ADR-0041 config-driven schedule comparison matrix."""

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
    EmpiricalL0ScheduleRunner,
    load_empirical_l0_schedule_config,
    save_empirical_l0_schedule_artifacts,
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


def _runner(empirical: bool) -> MultirateCrossScaleRunner:
    genome_model: object = (
        EmpiricalResponseGrnModel(
            load_grn_config(CONFIGS / "layers" / "l0_reference_grn.json"),
            response_table=_table(),
            table_path="fixture-table.json",
        )
        if empirical
        else DiscreteGrnModel(load_grn_config(CONFIGS / "layers" / "l0_reference_grn.json"))
    )
    return MultirateCrossScaleRunner(
        load_runner_config(CONFIGS / "runner_reference.json"),
        genome_model=genome_model,
        molecular_model=CoarseMolecularModel(
            load_molecular_config(CONFIGS / "layers" / "l1_reference_molecular.json")
        ),
        cell_model=CellStateMachineModel(
            load_cell_config(CONFIGS / "layers" / "l2_reference_cell.json")
        ),
        tissue_model=TissueEnvironmentModel(
            load_tissue_config(CONFIGS / "layers" / "l3_reference_tissue.json")
        ),
        phenotype_model=PhenotypeObserverModel(
            load_phenotype_config(CONFIGS / "layers" / "l4_reference_phenotype.json")
        ),
    )


def _config(root: Path, **overrides) -> Path:
    payload = {
        "model_version": "empirical-l0-schedule-test",
        "ticks": 6,
        "seeds": [41, 42],
        "conditions": [
            {
                "condition_id": "baseline",
                "arm": "reference",
                "perturbations": None,
                "schedule": None,
            },
            {
                "condition_id": "empirical_constant",
                "arm": "empirical",
                "perturbations": {"cell-a": {_UNIT: 1.0}},
                "schedule": None,
            },
            {
                "condition_id": "empirical_scheduled",
                "arm": "empirical",
                "perturbations": None,
                "schedule": {"6": {"cell-a": {_UNIT: 1.0}}},
            },
        ],
        "comparisons": [
            ["baseline", "empirical_constant"],
            ["baseline", "empirical_scheduled"],
            ["empirical_constant", "empirical_scheduled"],
        ],
    }
    payload.update(overrides)
    path = root / "schedule.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class ScheduleConfigTests(unittest.TestCase):
    def test_real_config_loads(self) -> None:
        config = load_empirical_l0_schedule_config(
            CONFIGS / "experiments" / "empirical_l0_schedule.json"
        )
        self.assertEqual(5, len(config.conditions))
        self.assertEqual(5, len(config.comparisons))
        self.assertEqual({16}, set(config.conditions[3]["schedule"]))

    def test_validation(self) -> None:
        cases = []
        bad_arm = {"conditions": None}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for key, mutate, fragment in (
                ("arm", lambda c: c.update(arm="weird"), "unknown condition arm"),
                ("both", lambda c: c.update(schedule={"6": {"cell-a": {_UNIT: 1.0}}}), "exactly one"),
                ("baseline-pert", lambda c: c.update(perturbations={"cell-a": {_UNIT: 1.0}}), "baseline must take neither"),
                ("unknown-cmp", None, "declared conditions"),
            ):
                with self.subTest(key=key):
                    if key == "unknown-cmp":
                        path = _config(root, comparisons=[["baseline", "ghost"]])
                    elif key == "baseline-pert":
                        payload = json.loads(_config(root).read_text(encoding="utf-8"))
                        payload["conditions"][0]["perturbations"] = {"cell-a": {_UNIT: 1.0}}
                        path = root / "case.json"
                        path.write_text(json.dumps(payload), encoding="utf-8")
                    else:
                        payload = json.loads(_config(root).read_text(encoding="utf-8"))
                        mutate(payload["conditions"][1])
                        path = root / "case.json"
                        path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, fragment):
                        load_empirical_l0_schedule_config(path)


class ScheduleMatrixTests(unittest.TestCase):
    def _matrix(self, root: Path):
        config = load_empirical_l0_schedule_config(_config(root))
        return EmpiricalL0ScheduleRunner(
            config,
            baseline_runner=_runner(empirical=False),
            empirical_runner=_runner(empirical=True),
        ).run(load_multiscale_scenario(CONFIGS / "multiscale_demo.json"))

    def test_gates(self) -> None:
        config = load_empirical_l0_schedule_config(_config(Path(tempfile.mkdtemp())))
        with self.assertRaisesRegex(ValueError, "L0 only"):
            EmpiricalL0ScheduleRunner(
                config,
                baseline_runner=_runner(empirical=False),
                empirical_runner=_runner(empirical=False),
            )
        with tempfile.TemporaryDirectory() as tmp:
            bad = _config(Path(tmp))
            payload = json.loads(bad.read_text(encoding="utf-8"))
            payload["conditions"][1]["perturbations"] = {"cell-a": {"GHOST": 1.0}}
            bad.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown genes/units"):
                EmpiricalL0ScheduleRunner(
                    load_empirical_l0_schedule_config(bad),
                    baseline_runner=_runner(empirical=False),
                    empirical_runner=_runner(empirical=True),
                )

    def test_matrix_shape_and_schedule_invariant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            matrix = self._matrix(Path(tmp))
            self.assertTrue(matrix.baseline_identity_verified)
            self.assertEqual(6, len(matrix.records))  # 3 conditions x 2 seeds
            self.assertEqual(6, len(matrix.comparisons))  # 3 comparisons x 2 seeds
            self.assertEqual(
                (
                    "empirical_constant_vs_baseline",
                    "empirical_constant_vs_baseline",
                    "empirical_scheduled_vs_baseline",
                    "empirical_scheduled_vs_baseline",
                    "empirical_scheduled_vs_empirical_constant",
                    "empirical_scheduled_vs_empirical_constant",
                ),
                tuple(c.condition_id for c in matrix.comparisons),
            )
            # Pre-onset invariant: scheduled arm equals baseline before tick 6.
            records = {(r.condition_id, r.seed): r for r in matrix.records}
            base = records[("baseline", 41)].run
            sched = records[("empirical_scheduled", 41)].run
            for before in base.ticks[:5]:
                after = sched.ticks[before.logical_time - 1]
                self.assertEqual(
                    [ (s.cell_id, s.damage_response) for s in before.l0 ],
                    [ (s.cell_id, s.damage_response) for s in after.l0 ],
                )
            self.assertNotEqual(
                [(s.cell_id, s.damage_response) for s in base.ticks[5].l0],
                [(s.cell_id, s.damage_response) for s in sched.ticks[5].l0],
            )

    def test_artifacts_write_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            matrix = self._matrix(root)
            out = root / "artifacts"
            first = save_empirical_l0_schedule_artifacts(out, matrix)
            self.assertTrue(first["manifest"].exists())
            save_empirical_l0_schedule_artifacts(out, matrix)
            payload = json.loads(first["summary"].read_text(encoding="utf-8"))
            payload["matrix_id"] = "tampered"
            first["summary"].write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different"):
                save_empirical_l0_schedule_artifacts(out, matrix)


class ScheduleCliTests(unittest.TestCase):
    def test_cli_round_trip(self) -> None:
        table_path = ROOT / "data" / "aivc" / "derived" / "l0-response-table.json"
        if not table_path.exists():
            self.skipTest("real response table not built on this machine")
        import hashlib

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layer_config = root / "layer.json"
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
                "empirical-l0-schedule-experiment",
                "--config",
                str(CONFIGS / "multiscale_demo.json"),
                "--matrix-config",
                str(_config(root)),
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
