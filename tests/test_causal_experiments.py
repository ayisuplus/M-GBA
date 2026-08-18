import json
import tempfile
import unittest
from pathlib import Path

from mgba.experiments import (
    CausalExperimentRunner,
    load_causal_config,
    save_causal_artifacts,
)
from mgba.layers import LayerId
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l1 import (
    CoarseMolecularModel,
    StaticMolecularModel,
    load_molecular_config,
)
from mgba.layers.l2 import (
    CellStateMachineModel,
    StaticCellModel,
    load_cell_config,
)
from mgba.layers.l3 import (
    StaticTissueModel,
    TissueEnvironmentModel,
    load_tissue_config,
)
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.multiscale import load_multiscale_scenario
from mgba.runner import MultirateCrossScaleRunner, load_runner_config


class CausalExperimentRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).parents[1]
        self.scenario = load_multiscale_scenario(
            self.root / "configs" / "multiscale_demo.json"
        )
        self.config_path = (
            self.root / "configs" / "experiments" / "wp8_reference.json"
        )
        self.config = load_causal_config(self.config_path)

    def _multirate_runner(self, variant: str) -> MultirateCrossScaleRunner:
        layers = self.root / "configs" / "layers"
        molecular_model = (
            StaticMolecularModel()
            if variant == "l1_static"
            else CoarseMolecularModel(
                load_molecular_config(layers / "l1_reference_molecular.json")
            )
        )
        cell_model = (
            StaticCellModel()
            if variant == "l2_static"
            else CellStateMachineModel(
                load_cell_config(layers / "l2_reference_cell.json")
            )
        )
        tissue_model = (
            StaticTissueModel()
            if variant == "l3_static"
            else TissueEnvironmentModel(
                load_tissue_config(layers / "l3_reference_tissue.json")
            )
        )
        return MultirateCrossScaleRunner(
            load_runner_config(self.root / "configs" / "runner_reference.json"),
            genome_model=DiscreteGrnModel(
                load_grn_config(layers / "l0_reference_grn.json")
            ),
            molecular_model=molecular_model,
            cell_model=cell_model,
            tissue_model=tissue_model,
            phenotype_model=PhenotypeObserverModel(
                load_phenotype_config(layers / "l4_reference_phenotype.json")
            ),
        )

    def _runner(self) -> CausalExperimentRunner:
        return CausalExperimentRunner(
            self.config,
            runners={
                "baseline": self._multirate_runner("baseline"),
                "l1_static": self._multirate_runner("l1_static"),
                "l2_static": self._multirate_runner("l2_static"),
                "l3_static": self._multirate_runner("l3_static"),
            },
        )

    def test_reference_matrix_is_complete_and_deterministic(self) -> None:
        first = self._runner().run(self.scenario)
        second = self._runner().run(self.scenario)

        self.assertEqual(first.matrix_id, second.matrix_id)
        self.assertEqual(first.comparisons, second.comparisons)
        self.assertEqual(first.summaries, second.summaries)
        self.assertEqual(first.summary_dict(), second.summary_dict())
        self.assertEqual(21, len(first.records))
        self.assertEqual(18, len(first.comparisons))
        self.assertEqual(6, len(first.summaries))
        self.assertEqual(
            {
                "baseline",
                "repair_kd_000",
                "repair_clamp_050",
                "repair_oe_100",
                "l1_static",
                "l2_static",
                "l3_static",
            },
            {record.condition_id for record in first.records},
        )
        for record in first.records:
            self.assertEqual(30, len(record.run.ticks))
            self.assertEqual(30, record.run.end_tick)

    def test_full_repair_knockdown_has_a_traceable_five_layer_path(self) -> None:
        result = self._runner().run(self.scenario)
        comparison = next(
            item
            for item in result.comparisons
            if item.condition_id == "repair_kd_000" and item.seed == 42
        )
        layer_effects = dict(comparison.layer_effects)
        propagation = dict(comparison.propagation_ticks)

        for layer in LayerId:
            self.assertGreater(layer_effects[layer], 0.0)
            self.assertIsNotNone(propagation[layer])
        observed_times = [propagation[layer] for layer in LayerId]
        self.assertEqual(observed_times, sorted(observed_times))
        self.assertEqual(
            comparison.baseline_experiment_id,
            next(
                record.run.manifest.experiment_id
                for record in result.records
                if record.condition_id == "baseline" and record.seed == 42
            ),
        )
        self.assertNotEqual(
            comparison.baseline_history_digest,
            comparison.condition_history_digest,
        )

    def test_each_ablation_changes_only_its_target_model_version(self) -> None:
        result = self._runner().run(self.scenario)
        baseline = next(
            record
            for record in result.records
            if record.condition_id == "baseline" and record.seed == 42
        )
        expected_targets = {
            "l1_static": "L1",
            "l2_static": "L2",
            "l3_static": "L3",
        }
        baseline_versions = dict(baseline.run.manifest.model_versions)

        for condition_id, target in expected_targets.items():
            record = next(
                item
                for item in result.records
                if item.condition_id == condition_id and item.seed == 42
            )
            changed_layers = {
                layer
                for layer, version in dict(
                    record.run.manifest.model_versions
                ).items()
                if version != baseline_versions[layer]
            }
            self.assertEqual({target}, changed_layers)

    def test_artifacts_preserve_every_raw_run_and_refuse_conflicts(self) -> None:
        result = self._runner().run(self.scenario)
        with tempfile.TemporaryDirectory() as directory:
            paths = save_causal_artifacts(directory, result)
            manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
            summary = json.loads(paths.summary.read_text(encoding="utf-8"))
            raw_files = tuple(paths.raw.rglob("seed-*.json"))

            self.assertEqual(result.matrix_id, manifest["matrix_id"])
            self.assertEqual(result.matrix_id, summary["matrix_id"])
            self.assertEqual(21, len(raw_files))
            save_causal_artifacts(directory, result)
            paths.summary.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                save_causal_artifacts(directory, result)

    def test_invalid_matrix_configs_fail_closed(self) -> None:
        original = json.loads(self.config_path.read_text(encoding="utf-8"))
        invalid_cases = []
        missing = json.loads(json.dumps(original))
        missing.pop("seeds")
        invalid_cases.append(missing)
        one_seed = json.loads(json.dumps(original))
        one_seed["seeds"] = [42]
        invalid_cases.append(one_seed)
        duplicate_seed = json.loads(json.dumps(original))
        duplicate_seed["seeds"] = [41, 41]
        invalid_cases.append(duplicate_seed)
        invalid_dose = json.loads(json.dumps(original))
        invalid_dose["perturbations"][0]["value"] = 1.5
        invalid_cases.append(invalid_dose)
        duplicate_condition = json.loads(json.dumps(original))
        duplicate_condition["perturbations"][1]["condition_id"] = (
            duplicate_condition["perturbations"][0]["condition_id"]
        )
        invalid_cases.append(duplicate_condition)
        invalid_ablation = json.loads(json.dumps(original))
        invalid_ablation["ablations"] = ["l1_static", "unknown"]
        invalid_cases.append(invalid_ablation)
        invalid_id = json.loads(json.dumps(original))
        invalid_id["perturbations"][0]["condition_id"] = "../escape"
        invalid_cases.append(invalid_id)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-matrix.json"
            for raw in invalid_cases:
                path.write_text(json.dumps(raw), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_causal_config(path)


if __name__ == "__main__":
    unittest.main()
