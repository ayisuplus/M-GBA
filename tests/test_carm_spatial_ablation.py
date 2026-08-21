"""Factor-isolation gates for the CAR-M spatial L3 mechanism audit."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from mgba.carm_spatial_ablation import (
    CarmSpatialAblationRunner,
    build_carm_spatial_ablation_runners,
    load_carm_spatial_ablation_config,
    save_carm_spatial_ablation_artifacts,
)
from mgba.layers import LayerId
from mgba.runner import load_runner_config
from mgba.scenarios.carm import (
    CarmSpatialMechanisms,
    compile_carm_scenario,
    load_carm_scenario_config,
    load_carm_spatial_config,
)


ROOT = Path(__file__).parents[1]


class CarmSpatialAblationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compiled = compile_carm_scenario(
            load_carm_scenario_config(
                ROOT / "configs" / "scenarios" / "carm" / "high_immune_her2.json"
            )
        )
        cls.config = replace(
            load_carm_spatial_ablation_config(
                ROOT / "configs" / "experiments" / "carm_spatial_ablation.json"
            ),
            ticks=4,
        )
        cls.runners = build_carm_spatial_ablation_runners(
            cls.compiled,
            runner_config=load_runner_config(
                ROOT / "configs" / "runner_reference.json"
            ),
            spatial_config=load_carm_spatial_config(
                ROOT / "configs" / "layers" / "l3_carm_spatial.json"
            ),
            l0_config=ROOT / "configs" / "layers" / "l0_reference_grn.json",
            l1_config=ROOT / "configs" / "layers" / "l1_reference_molecular.json",
            l4_config=ROOT / "configs" / "layers" / "l4_reference_phenotype.json",
        )
        cls.result = CarmSpatialAblationRunner(
            cls.config, runners=cls.runners
        ).run(cls.compiled)
        cls.records = {item.condition_id: item for item in cls.result.records}
        cls.comparisons = {
            item.condition_id: item for item in cls.result.baseline_comparisons
        }
        cls.diagnostics = {
            item.condition_id: item for item in cls.result.diagnostics
        }

    def test_config_and_switches_fail_fast(self) -> None:
        for name, value in (
            ("model_version", " "),
            ("ticks", 1),
            ("ticks", True),
            ("scenario_seed", -1),
            ("scenario_seed", True),
        ):
            with self.assertRaises(ValueError, msg=f"{name}={value}"):
                replace(self.config, **{name: value})
        with self.assertRaises(TypeError):
            CarmSpatialMechanisms(1, False, False)

    def test_all_disabled_is_a_zero_effect_state_wrapper(self) -> None:
        condition = "space_m0_f0_t0"
        comparison = self.comparisons[condition]
        self.assertTrue(all(value == 0.0 for _, value in comparison.layer_effects))
        self.assertTrue(
            all(value == 0.0 for _, value in comparison.final_metric_effects)
        )
        baseline = self.records["fixed_graph"].run
        disabled = self.records[condition].run
        for metric in (
            "vitality",
            "damage_burden",
            "inflammation",
            "homeostasis",
            "recovery_capacity",
        ):
            self.assertEqual(
                getattr(baseline.terminal_observation, metric),
                getattr(disabled.terminal_observation, metric),
            )
        self.assertEqual(self.compiled.scenario.edges, disabled.ticks[-1].l3.edges)
        self.assertEqual(
            disabled.ticks[0].l3.coordinates,
            disabled.ticks[-1].l3.coordinates,
        )
        self.assertEqual(
            disabled.ticks[0].l3.field_cells,
            disabled.ticks[-1].l3.field_cells,
        )

    def test_each_single_mechanism_has_the_declared_semantics(self) -> None:
        movement = self.records["space_m1_f0_t0"].run
        movement_effects = dict(
            self.comparisons["space_m1_f0_t0"].layer_effects
        )
        self.assertNotEqual(
            movement.ticks[0].l3.coordinates,
            movement.ticks[-1].l3.coordinates,
        )
        self.assertEqual(0.0, movement_effects[LayerId.L3])
        self.assertEqual(0.0, movement_effects[LayerId.L4])

        field = self.records["space_m0_f1_t0"].run
        field_effects = dict(self.comparisons["space_m0_f1_t0"].layer_effects)
        self.assertEqual(field.ticks[0].l3.coordinates, field.ticks[-1].l3.coordinates)
        self.assertEqual(self.compiled.scenario.edges, field.ticks[-1].l3.edges)
        self.assertGreater(field_effects[LayerId.L3], 0.0)
        self.assertGreater(field_effects[LayerId.L4], 0.0)
        self.assertGreater(
            self.diagnostics["space_m0_f1_t0"].terminal_field_heterogeneity,
            0.0,
        )

        topology = self.records["space_m0_f0_t1"].run
        topology_effects = dict(
            self.comparisons["space_m0_f0_t1"].layer_effects
        )
        self.assertEqual(
            topology.ticks[0].l3.coordinates,
            topology.ticks[-1].l3.coordinates,
        )
        self.assertNotEqual(self.compiled.scenario.edges, topology.ticks[-1].l3.edges)
        self.assertEqual(
            topology.ticks[0].l3.field_cells,
            topology.ticks[-1].l3.field_cells,
        )
        self.assertGreater(topology_effects[LayerId.L3], 0.0)
        self.assertGreater(topology_effects[LayerId.L4], 0.0)

    def test_full_factorial_and_main_effects_are_complete(self) -> None:
        self.assertEqual(9, len(self.result.records))
        self.assertEqual(8, len(self.result.baseline_comparisons))
        self.assertEqual(8, len(self.result.diagnostics))
        self.assertEqual(
            ("movement", "field_coupling", "spatial_topology"),
            tuple(item.mechanism for item in self.result.factor_effects),
        )
        for item in self.result.factor_effects:
            self.assertEqual(4, item.pair_count)
            self.assertGreater(item.mean_l3_distance, 0.0)
            self.assertGreater(item.mean_l4_distance, 0.0)

    def test_every_factorial_runner_changes_only_l3(self) -> None:
        baseline = dict(self.runners["fixed_graph"].model_versions)
        for name, runner in self.runners.items():
            if name == "fixed_graph":
                continue
            versions = dict(runner.model_versions)
            changed = {
                layer for layer, version in versions.items() if version != baseline[layer]
            }
            self.assertEqual({"L3"}, changed)

    def test_artifacts_are_complete_idempotent_and_conflict_refusing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = save_carm_spatial_ablation_artifacts(directory, self.result)
            self.assertTrue(paths["manifest"].is_file())
            self.assertTrue(paths["summary"].is_file())
            self.assertEqual(
                9,
                len(tuple((paths["root"] / "raw").rglob("run.json"))),
            )
            self.assertEqual(
                paths,
                save_carm_spatial_ablation_artifacts(directory, self.result),
            )
            with self.assertRaises(ValueError):
                save_carm_spatial_ablation_artifacts(
                    directory,
                    replace(self.result, scenario_digest="different"),
                )


if __name__ == "__main__":
    unittest.main()
