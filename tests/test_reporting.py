import csv
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from mgba.experiments import (
    CausalExperimentRunner,
    load_causal_config,
    save_causal_artifacts,
)
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l1 import (
    CoarseMolecularModel,
    StaticMolecularModel,
    load_molecular_config,
)
from mgba.layers.l2 import CellStateMachineModel, load_cell_config
from mgba.layers.l3 import TissueEnvironmentModel, load_tissue_config
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.multiscale import load_multiscale_scenario
from mgba.reporting import build_causal_report
from mgba.runner import MultirateCrossScaleRunner, load_runner_config


class CausalReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).parents[1]
        cls.temporary = tempfile.TemporaryDirectory()
        cls.temp_root = Path(cls.temporary.name)
        scenario = load_multiscale_scenario(
            cls.root / "configs" / "multiscale_demo.json"
        )
        full_config = load_causal_config(
            cls.root / "configs" / "experiments" / "wp8_reference.json"
        )
        config = replace(
            full_config,
            ticks=3,
            seeds=(1, 2),
            perturbations=full_config.perturbations[:2],
            ablations=("l1_static",),
        )
        matrix = CausalExperimentRunner(
            config,
            runners={
                "baseline": cls._multirate_runner("baseline"),
                "l1_static": cls._multirate_runner("l1_static"),
            },
        ).run(scenario)
        cls.artifact_paths = save_causal_artifacts(cls.temp_root, matrix)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    @classmethod
    def _multirate_runner(cls, variant: str) -> MultirateCrossScaleRunner:
        layers = cls.root / "configs" / "layers"
        return MultirateCrossScaleRunner(
            load_runner_config(cls.root / "configs" / "runner_reference.json"),
            genome_model=DiscreteGrnModel(
                load_grn_config(layers / "l0_reference_grn.json")
            ),
            molecular_model=(
                StaticMolecularModel()
                if variant == "l1_static"
                else CoarseMolecularModel(
                    load_molecular_config(
                        layers / "l1_reference_molecular.json"
                    )
                )
            ),
            cell_model=CellStateMachineModel(
                load_cell_config(layers / "l2_reference_cell.json")
            ),
            tissue_model=TissueEnvironmentModel(
                load_tissue_config(layers / "l3_reference_tissue.json")
            ),
            phenotype_model=PhenotypeObserverModel(
                load_phenotype_config(
                    layers / "l4_reference_phenotype.json"
                )
            ),
        )

    @staticmethod
    def _csv_rows(path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_report_is_complete_deterministic_and_rebuilds_deleted_files(self) -> None:
        output = self.temp_root / "report-output"
        first = build_causal_report(self.artifact_paths.root, output)
        first_manifest = first.manifest.read_bytes()
        repair_path_bytes = first.repair_path_chart.read_bytes()

        self.assertEqual(3, len(self._csv_rows(first.condition_summary_csv)))
        self.assertEqual(30, len(self._csv_rows(first.layer_effects_csv)))
        self.assertEqual(30, len(self._csv_rows(first.metric_effects_csv)))
        self.assertEqual(24, len(self._csv_rows(first.tissue_timeseries_csv)))
        self.assertEqual(16, len(self._csv_rows(first.l4_observations_csv)))
        for chart in first.charts:
            text = chart.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("<svg"))
            self.assertIn('<title id="title">', text)
            self.assertIn('<desc id="desc">', text)
        html = first.html.read_text(encoding="utf-8")
        self.assertNotIn("fetch(", html)
        self.assertNotIn("<script", html)

        second = build_causal_report(self.artifact_paths.root, output)
        self.assertEqual(first_manifest, second.manifest.read_bytes())
        first.repair_path_chart.unlink()
        rebuilt = build_causal_report(self.artifact_paths.root, output)
        self.assertEqual(repair_path_bytes, rebuilt.repair_path_chart.read_bytes())
        self.assertEqual(first_manifest, rebuilt.manifest.read_bytes())

    def test_derived_matrix_summary_is_not_an_input(self) -> None:
        copied = self.temp_root / "summary-independent"
        shutil.copytree(self.artifact_paths.root, copied)
        (copied / "derived" / "summary.json").write_text("{}", encoding="utf-8")

        report = build_causal_report(copied, copied / "rebuilt")

        self.assertTrue(report.html.is_file())
        self.assertEqual(30, len(self._csv_rows(report.layer_effects_csv)))

    def test_corrupt_raw_identity_and_escaping_paths_fail_closed(self) -> None:
        corrupt_raw = self.temp_root / "corrupt-raw"
        shutil.copytree(self.artifact_paths.root, corrupt_raw)
        manifest_path = corrupt_raw / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw_path = corrupt_raw / manifest["records"][0]["path"]
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        raw["experiment"]["experiment_id"] = "wrong-experiment"
        raw_path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(ValueError):
            build_causal_report(corrupt_raw, corrupt_raw / "report")

        escaping = self.temp_root / "escaping-path"
        shutil.copytree(self.artifact_paths.root, escaping)
        escaping_manifest_path = escaping / "manifest.json"
        escaping_manifest = json.loads(
            escaping_manifest_path.read_text(encoding="utf-8")
        )
        escaping_manifest["records"][0]["path"] = "../outside.json"
        escaping_manifest_path.write_text(
            json.dumps(escaping_manifest), encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            build_causal_report(escaping, escaping / "report")


if __name__ == "__main__":
    unittest.main()
