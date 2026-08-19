import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from statistics import fmean

from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config
from mgba.layers.l2 import CellStateMachineModel, load_cell_config
from mgba.layers.l3 import TissueEnvironmentModel, load_tissue_config
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.multiscale import load_multiscale_scenario
from mgba.run_report import build_run_report
from mgba.runner import (
    MultirateCrossScaleRunner,
    load_runner_config,
    save_run_artifact,
)


class RunReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).parents[1]
        cls.temporary = tempfile.TemporaryDirectory()
        cls.temp_root = Path(cls.temporary.name)
        layers = cls.root / "configs" / "layers"
        scenario = load_multiscale_scenario(
            cls.root / "configs" / "multiscale_demo.json"
        )
        runner = MultirateCrossScaleRunner(
            load_runner_config(cls.root / "configs" / "runner_reference.json"),
            genome_model=DiscreteGrnModel(
                load_grn_config(layers / "l0_reference_grn.json")
            ),
            molecular_model=CoarseMolecularModel(
                load_molecular_config(layers / "l1_reference_molecular.json")
            ),
            cell_model=CellStateMachineModel(
                load_cell_config(layers / "l2_reference_cell.json")
            ),
            tissue_model=TissueEnvironmentModel(
                load_tissue_config(layers / "l3_reference_tissue.json")
            ),
            phenotype_model=PhenotypeObserverModel(
                load_phenotype_config(layers / "l4_reference_phenotype.json")
            ),
        )
        run = runner.run(scenario, ticks=30)
        cls.run_path = cls.temp_root / "run.json"
        save_run_artifact(cls.run_path, run)
        cls.raw = json.loads(cls.run_path.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    @staticmethod
    def _csv_rows(path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_report_is_complete_deterministic_and_byte_rebuildable(self) -> None:
        first_dir = self.temp_root / "report-a"
        second_dir = self.temp_root / "report-b"
        first = build_run_report(self.run_path, first_dir)
        rebuilt = build_run_report(self.run_path, second_dir)
        expected_names = {
            "l0-gene-expression.csv",
            "l1-molecular-state.csv",
            "l2-cell-state.csv",
            "l2-phase-counts.csv",
            "l3-tissue-fields.csv",
            "l4-phenotype.csv",
            "l0-gene-expression.svg",
            "l1-molecular-state.svg",
            "l2-cell-state.svg",
            "l2-phase-counts.svg",
            "l3-tissue-fields.svg",
            "l4-phenotype.svg",
            "run-report.html",
            "run-report-manifest.json",
        }
        self.assertEqual(
            expected_names, {path.name for path in first_dir.iterdir()}
        )
        for path in (*first.generated_files, first.manifest):
            counterpart = second_dir / path.name
            self.assertEqual(
                path.read_bytes(),
                counterpart.read_bytes(),
                f"{path.name} is not byte-rebuildable",
            )
        manifest = json.loads(rebuilt.manifest.read_text(encoding="utf-8"))
        self.assertEqual("mgba-run-report-files-0.1", manifest["schema_version"])
        self.assertEqual(
            self.raw["experiment"]["experiment_id"], manifest["experiment_id"]
        )
        self.assertEqual(self.raw["history_digest"], manifest["history_digest"])
        self.assertEqual(
            {
                "l0-gene-expression.csv",
                "l1-molecular-state.csv",
                "l2-cell-state.csv",
                "l2-phase-counts.csv",
                "l3-tissue-fields.csv",
                "l4-phenotype.csv",
                "l0-gene-expression.svg",
                "l1-molecular-state.svg",
                "l2-cell-state.svg",
                "l2-phase-counts.svg",
                "l3-tissue-fields.svg",
                "l4-phenotype.svg",
                "run-report.html",
            },
            set(manifest["files"]),
        )
        for digest in manifest["files"].values():
            self.assertEqual(64, len(digest))

    def test_series_match_raw_ticks(self) -> None:
        output = self.temp_root / "report-values"
        build_run_report(self.run_path, output)
        l0_rows = self._csv_rows(output / "l0-gene-expression.csv")
        self.assertEqual(30, len(l0_rows))
        tick_index = 7
        expected = fmean(
            state["signal_expression"]
            for state in self.raw["ticks"][tick_index]["l0"]
        )
        self.assertEqual(
            f"{expected:.12g}", l0_rows[tick_index]["signal_expression"]
        )
        l3_rows = self._csv_rows(output / "l3-tissue-fields.csv")
        self.assertEqual(
            f"{self.raw['ticks'][tick_index]['l3']['tissue_damage']:.12g}",
            l3_rows[tick_index]["tissue_damage"],
        )
        cell_count = len(self.raw["ticks"][tick_index]["l2"])
        phase_rows = self._csv_rows(output / "l2-phase-counts.csv")
        for tick_index, row in enumerate(phase_rows):
            total = sum(
                int(value) for key, value in row.items() if key != "tick"
            )
            self.assertEqual(cell_count, total)
        observed = [
            tick for tick in self.raw["ticks"] if tick["l4"] is not None
        ]
        l4_rows = self._csv_rows(output / "l4-phenotype.csv")
        self.assertEqual(len(observed), len(l4_rows))
        self.assertEqual(
            [tick["logical_time"] for tick in observed],
            [int(row["tick"]) for row in l4_rows],
        )
        self.assertEqual(
            f"{observed[0]['l4']['vitality']:.12g}", l4_rows[0]["vitality"]
        )

    def test_tampered_or_incomplete_runs_fail_closed(self) -> None:
        cases = {}
        tampered_tick = json.loads(json.dumps(self.raw))
        tampered_tick["ticks"][5]["l3"]["tissue_damage"] += 0.01
        cases["tampered tick"] = tampered_tick
        tampered_manifest = json.loads(json.dumps(self.raw))
        tampered_manifest["experiment"]["seed"] = 999
        cases["tampered manifest"] = tampered_manifest
        incomplete = json.loads(json.dumps(self.raw))
        incomplete["ticks"] = incomplete["ticks"][1:]
        cases["incomplete tick range"] = incomplete
        broken_schema = {key: self.raw[key] for key in self.raw if key != "ticks"}
        cases["missing schema field"] = broken_schema
        for name, document in cases.items():
            with self.subTest(case=name):
                path = self.temp_root / f"tampered-{len(name)}.json"
                path.write_text(
                    json.dumps(document, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaises(ValueError):
                    build_run_report(path, self.temp_root / f"out-{len(name)}")

    def test_default_output_refuses_raw_artifact_directories(self) -> None:
        raw_dir = self.temp_root / "matrix" / "raw" / "baseline"
        raw_dir.mkdir(parents=True)
        nested_run = raw_dir / "seed-41.json"
        shutil.copyfile(self.run_path, nested_run)
        with self.assertRaises(ValueError):
            build_run_report(nested_run)
        explicit = build_run_report(
            nested_run, self.temp_root / "matrix" / "derived" / "seed-41-report"
        )
        self.assertTrue(explicit.manifest.is_file())


if __name__ == "__main__":
    unittest.main()
