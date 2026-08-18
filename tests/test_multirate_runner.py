import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from mgba.layers import LayerId
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config
from mgba.layers.l2 import CellStateMachineModel, load_cell_config
from mgba.layers.l3 import TissueEnvironmentModel, load_tissue_config
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.multiscale import load_multiscale_scenario
from mgba.runner import (
    MultirateCrossScaleRunner,
    load_checkpoint,
    load_runner_config,
    save_checkpoint,
    save_run_artifact,
)


class MultirateCrossScaleRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).parents[1]
        self.scenario = load_multiscale_scenario(
            self.root / "configs" / "multiscale_demo.json"
        )
        self.config_path = self.root / "configs" / "runner_reference.json"
        self.config = load_runner_config(self.config_path)

    def _runner(self, config=None) -> MultirateCrossScaleRunner:
        layer_configs = self.root / "configs" / "layers"
        return MultirateCrossScaleRunner(
            config or self.config,
            genome_model=DiscreteGrnModel(
                load_grn_config(layer_configs / "l0_reference_grn.json")
            ),
            molecular_model=CoarseMolecularModel(
                load_molecular_config(
                    layer_configs / "l1_reference_molecular.json"
                )
            ),
            cell_model=CellStateMachineModel(
                load_cell_config(layer_configs / "l2_reference_cell.json")
            ),
            tissue_model=TissueEnvironmentModel(
                load_tissue_config(layer_configs / "l3_reference_tissue.json")
            ),
            phenotype_model=PhenotypeObserverModel(
                load_phenotype_config(
                    layer_configs / "l4_reference_phenotype.json"
                )
            ),
        )

    def test_100_tick_run_is_deterministic_multirate_and_complete(self) -> None:
        first = self._runner().run(self.scenario, ticks=100)
        second = self._runner().run(self.scenario, ticks=100)

        self.assertEqual(first, second)
        self.assertEqual(tuple(range(1, 101)), tuple(t.logical_time for t in first.ticks))
        self.assertEqual(
            tuple(range(1, 101, 5)),
            tuple(t.logical_time for t in first.ticks if t.l0_updated),
        )
        self.assertEqual(
            tuple(range(1, 101, 10)),
            tuple(t.logical_time for t in first.ticks if t.l4_observed),
        )
        self.assertEqual(100, first.checkpoint.logical_time)
        self.assertEqual(100, first.terminal_observation.metadata.logical_time)
        self.assertEqual(100, first.phenotype_window.end_time)
        self.assertEqual(11, first.phenotype_window.sample_count)
        self.assertEqual(first.history_digest, first.checkpoint.history_digest)

        expected_fast_path = (
            (LayerId.L0, LayerId.L1),
            (LayerId.L1, LayerId.L2),
            (LayerId.L2, LayerId.L3),
        )
        for tick in first.ticks:
            observed = tuple(
                (event.source_layer, event.target_layer)
                for event in tick.transitions
            )
            self.assertEqual(expected_fast_path, observed[:3])
            if tick.l4_observed:
                self.assertEqual(
                    (LayerId.L3, LayerId.L4), observed[3]
                )
            else:
                self.assertEqual(3, len(observed))

    def test_previous_states_feed_only_adjacent_boundaries(self) -> None:
        result = self._runner().run(self.scenario, ticks=2)
        first, second = result.ticks

        self.assertTrue(first.l0_updated)
        self.assertFalse(second.l0_updated)
        self.assertEqual(first.l0, second.l0)
        self.assertTrue(all(item.local_signal == 0.0 for item in first.l1_inputs))
        self.assertEqual(
            tuple(state.activation for state in first.l2),
            tuple(item.local_signal for item in second.l1_inputs),
        )
        self.assertEqual(
            tuple(node.cell_id for node in first.l3.nodes),
            tuple(environment.cell_id for environment in second.l2_environments),
        )
        for node, environment in zip(
            first.l3.nodes, second.l2_environments, strict=True
        ):
            self.assertEqual(node.stress, environment.stress)
            self.assertEqual(node.resource_level, environment.resource_level)
            self.assertEqual(node.signal, environment.incoming_signal)
        self.assertEqual(
            2, second.l1[0].metadata.logical_time
        )
        self.assertEqual(2, second.l2[0].metadata.logical_time)
        self.assertEqual(2, second.l3.metadata.logical_time)

    def test_checkpoint_resume_matches_one_shot_and_artifacts_are_json(self) -> None:
        full = self._runner().run(self.scenario, ticks=30)
        first = self._runner().run(self.scenario, ticks=13)

        with tempfile.TemporaryDirectory() as directory:
            checkpoint_path = Path(directory) / "checkpoint.json"
            trace_path = Path(directory) / "run.json"
            save_checkpoint(checkpoint_path, first.checkpoint)
            loaded = load_checkpoint(checkpoint_path)
            resumed = self._runner().run(
                self.scenario, ticks=17, checkpoint=loaded
            )
            save_run_artifact(trace_path, resumed)
            raw = json.loads(trace_path.read_text(encoding="utf-8"))

        self.assertEqual(full.checkpoint, resumed.checkpoint)
        self.assertEqual(full.history_digest, resumed.history_digest)
        self.assertEqual(full.terminal_observation, resumed.terminal_observation)
        self.assertEqual(full.phenotype_window, resumed.phenotype_window)
        self.assertEqual(
            full.ticks, first.ticks + resumed.ticks
        )
        self.assertEqual(17, raw["tick_count"])
        self.assertEqual(30, raw["end_tick"])
        self.assertEqual(full.history_digest, raw["history_digest"])

    def test_checkpoint_rejects_conflicts_corruption_and_other_experiments(self) -> None:
        baseline = self._runner().run(self.scenario, ticks=5)

        with self.assertRaises(ValueError):
            self._runner().run(
                self.scenario,
                ticks=1,
                perturbations={"cell-a": {"repair_expression": 0.0}},
                checkpoint=baseline.checkpoint,
            )
        with self.assertRaises(ValueError):
            self._runner(replace(self.config, l0_interval=4)).run(
                self.scenario, ticks=1, checkpoint=baseline.checkpoint
            )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            save_checkpoint(path, baseline.checkpoint)
            with self.assertRaises(ValueError):
                save_checkpoint(
                    path,
                    self._runner().run(self.scenario, ticks=6).checkpoint,
                )
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["schema_version"] = "unknown-schema"
            corrupt = Path(directory) / "corrupt.json"
            corrupt.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_checkpoint(corrupt)

    def test_resource_and_event_budgets_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            self._runner(replace(self.config, max_cells=3)).run(
                self.scenario, ticks=1
            )
        with self.assertRaises(ValueError):
            self._runner(replace(self.config, max_total_ticks=5)).run(
                self.scenario, ticks=6
            )
        with self.assertRaises(ValueError):
            self._runner(replace(self.config, max_events_per_tick=3)).run(
                self.scenario, ticks=1
            )

    def test_perturbation_still_propagates_through_the_timed_chain(self) -> None:
        baseline = self._runner().run(self.scenario, ticks=3)
        perturbed = self._runner().run(
            self.scenario,
            ticks=3,
            perturbations={"cell-a": {"repair_expression": 0.0}},
        )

        self.assertEqual(1, len(perturbed.ticks[0].l0_perturbation_events))
        self.assertLess(
            perturbed.ticks[-1].l1[0].repair_protein,
            baseline.ticks[-1].l1[0].repair_protein,
        )
        self.assertLess(
            perturbed.ticks[-1].l2[0].viability,
            baseline.ticks[-1].l2[0].viability,
        )
        self.assertGreater(
            perturbed.ticks[-1].l3.tissue_damage,
            baseline.ticks[-1].l3.tissue_damage,
        )
        self.assertLess(
            perturbed.terminal_observation.vitality,
            baseline.terminal_observation.vitality,
        )

    def test_runner_config_validation_and_fingerprint(self) -> None:
        changed = self._runner(replace(self.config, l0_interval=4))
        self.assertNotEqual(self._runner().model_version, changed.model_version)

        original = json.loads(self.config_path.read_text(encoding="utf-8"))
        invalid_cases = []
        missing = json.loads(json.dumps(original))
        missing.pop("l4_interval")
        invalid_cases.append(missing)
        zero_interval = json.loads(json.dumps(original))
        zero_interval["l0_interval"] = 0
        invalid_cases.append(zero_interval)
        zero_budget = json.loads(json.dumps(original))
        zero_budget["max_events_per_tick"] = 0
        invalid_cases.append(zero_budget)
        fractional_interval = json.loads(json.dumps(original))
        fractional_interval["l4_interval"] = 2.5
        invalid_cases.append(fractional_interval)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-runner.json"
            for raw in invalid_cases:
                path.write_text(json.dumps(raw), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_runner_config(path)


if __name__ == "__main__":
    unittest.main()
