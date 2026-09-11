"""Extreme edge-case and crash-prevention tests for the closed-loop matrix.

Covers the pre-registered stability grading ladder (all six grades on
hand-built sequences), config fail-fast validation, matrix determinism
under noise, runner-construction guards, budget enforcement, and the
frozen-baseline identity guard (deterministic chain untouched).
"""

import math
import unittest
from dataclasses import replace
from pathlib import Path

from mgba.closed_loop_experiments import (
    ClosedLoopExperimentConfig,
    ClosedLoopExperimentRunner,
    StabilityGrade,
    classify_stability,
    load_closed_loop_config,
)
from mgba.feedback import load_feedback_config
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l0_noisy import load_noisy_grn_config
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config
from mgba.layers.l2 import CellStateMachineModel, load_cell_config
from mgba.layers.l3 import TissueEnvironmentModel, load_tissue_config
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.multiscale import load_multiscale_scenario
from mgba.runner import load_runner_config

ROOT = Path(__file__).parents[1]
LAYER_CONFIGS = ROOT / "configs" / "layers"


def _config(**overrides) -> ClosedLoopExperimentConfig:
    base = dict(
        model_version="test-closed-loop",
        ticks=60,
        seeds=(7, 42, 1337),
        sign_change_min=2,
        amplitude_min=0.01,
        lock_std_max=0.002,
        recovery_delta_min=0.05,
        recovery_homeostasis_min=0.6,
        deterioration_delta_min=0.05,
    )
    base.update(overrides)
    return ClosedLoopExperimentConfig(**base)


def _layer_models() -> dict:
    return {
        "genome_model": DiscreteGrnModel(
            load_grn_config(LAYER_CONFIGS / "l0_reference_grn.json")
        ),
        "molecular_model": CoarseMolecularModel(
            load_molecular_config(LAYER_CONFIGS / "l1_reference_molecular.json")
        ),
        "cell_model": CellStateMachineModel(
            load_cell_config(LAYER_CONFIGS / "l2_reference_cell.json")
        ),
        "tissue_model": TissueEnvironmentModel(
            load_tissue_config(LAYER_CONFIGS / "l3_reference_tissue.json")
        ),
        "phenotype_model": PhenotypeObserverModel(
            load_phenotype_config(LAYER_CONFIGS / "l4_reference_phenotype.json")
        ),
    }


class ClosedLoopConfigCrashPreventionTests(unittest.TestCase):
    def test_illegal_parameters_fail_fast(self) -> None:
        cases = (
            ("ticks", 0),
            ("ticks", True),
            ("seeds", (42,)),
            ("seeds", (2, 1)),
            ("seeds", (1, 1)),
            ("sign_change_min", 0),
            ("sign_change_min", True),
            ("amplitude_min", math.nan),
            ("lock_std_max", math.inf),
            ("recovery_delta_min", -0.1),
            ("recovery_homeostasis_min", 1.5),
            ("deterioration_delta_min", 2.0),
        )
        for field, value in cases:
            with self.assertRaises(ValueError, msg=f"{field}={value}"):
                _config(**{field: value})

    def test_missing_config_file_raises_value_error(self) -> None:
        missing = ROOT / "configs" / "experiments" / "closed_loop_missing.json"
        self.assertFalse(missing.exists())
        with self.assertRaises(ValueError):
            load_closed_loop_config(missing)

    def test_shipped_config_loads_and_validates(self) -> None:
        config = load_closed_loop_config(
            ROOT / "configs" / "experiments" / "closed_loop_stochastic.json"
        )
        self.assertGreaterEqual(len(config.seeds), 2)
        self.assertGreater(config.ticks, 0)


class StabilityGradingTests(unittest.TestCase):
    def test_all_six_grades_reachable(self) -> None:
        config = _config()
        # 1. Fewer than three observations.
        grade = classify_stability("c", 1, (0.5, 0.5), config)
        self.assertEqual("insufficient_observations", grade.grade)
        # 2. Sustained sign changes with amplitude.
        grade = classify_stability(
            "c", 1, (0.5, 0.6, 0.5, 0.6, 0.5), config
        )
        self.assertEqual("oscillation", grade.grade)
        self.assertEqual(3, grade.sign_changes)
        # 3. Flat trajectory.
        grade = classify_stability(
            "c", 1, (0.5, 0.5, 0.5, 0.5, 0.5), config
        )
        self.assertEqual("lock", grade.grade)
        # 4. Rising trajectory reaching the set-point band.
        grade = classify_stability(
            "c", 1, (0.2, 0.3, 0.4, 0.5, 0.7), config
        )
        self.assertEqual("recovery", grade.grade)
        # 5. Falling trajectory.
        grade = classify_stability(
            "c", 1, (0.9, 0.8, 0.7, 0.6, 0.5), config
        )
        self.assertEqual("deterioration", grade.grade)
        # 6. Nothing matches.
        grade = classify_stability(
            "c", 1, (0.5, 0.505, 0.505, 0.51, 0.51), config
        )
        self.assertEqual("indeterminate", grade.grade)

    def test_stability_grade_rejects_out_of_range_and_unknown(self) -> None:
        with self.assertRaises(ValueError):
            StabilityGrade(
                condition_id="c",
                seed=1,
                observations=(1.5,),
                sign_changes=0,
                amplitude=0.0,
                trend=0.0,
                grade="indeterminate",
                note="bad",
            )
        with self.assertRaises(ValueError):
            StabilityGrade(
                condition_id="c",
                seed=1,
                observations=(0.5,),
                sign_changes=0,
                amplitude=0.0,
                trend=0.0,
                grade="not-a-grade",
                note="bad",
            )

    def test_oscillation_threshold_boundary_is_exclusive(self) -> None:
        config = _config(sign_change_min=3, amplitude_min=0.05)
        # Exactly two sign changes -> below threshold.
        grade = classify_stability(
            "c", 1, (0.5, 0.55, 0.5, 0.55, 0.5), config
        )
        self.assertNotEqual("oscillation", grade.grade)


class ClosedLoopMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_demo.json"
        )
        self.config = load_closed_loop_config(
            ROOT / "configs" / "experiments" / "closed_loop_stochastic.json"
        )
        self.runner_config = load_runner_config(
            ROOT / "configs" / "runner_reference.json"
        )
        self.grn_config, self.noise_sigma = load_noisy_grn_config(
            LAYER_CONFIGS / "l0_noisy_grn.json"
        )
        self.feedback_config = load_feedback_config(
            LAYER_CONFIGS / "l4_feedback_controller.json"
        )

    def _runner(self, config=None) -> ClosedLoopExperimentRunner:
        return ClosedLoopExperimentRunner(
            config or self.config,
            runner_config=self.runner_config,
            layer_models=_layer_models(),
            feedback_config=self.feedback_config,
            noisy_grn_config=self.grn_config,
            noise_sigma=self.noise_sigma,
        )

    def test_matrix_structure_and_determinism(self) -> None:
        matrix = self._runner().run(self.scenario)
        seeds = len(self.config.seeds)
        self.assertEqual(3 * seeds, len(matrix.records))
        self.assertEqual(2 * seeds, len(matrix.comparisons))
        self.assertEqual(3 * seeds, len(matrix.stability))
        self.assertTrue(matrix.matrix_id.startswith("closedloop-"))
        second = self._runner().run(self.scenario)
        self.assertEqual(matrix.matrix_id, second.matrix_id)
        self.assertEqual(matrix.stability_digest, second.stability_digest)
        self.assertEqual(
            [record.run.history_digest for record in matrix.records],
            [record.run.history_digest for record in second.records],
        )

    def test_noise_separates_stochastic_from_deterministic_closed_loop(self) -> None:
        matrix = self._runner().run(self.scenario)
        by_condition = {
            record.condition_id: record
            for record in matrix.records
            if record.seed == self.config.seeds[0]
        }
        self.assertNotEqual(
            by_condition["stochastic_closed_loop"].run.history_digest,
            by_condition["deterministic_closed_loop"].run.history_digest,
        )
        # The manifest embeds the seed, so deterministic runs have distinct
        # history digests; the dynamics must still be value-identical.
        terminal_l3 = {
            tuple(
                (node.cell_id, node.stress, node.resource_level, node.signal)
                for node in record.run.ticks[-1].l3.nodes
            )
            for record in matrix.records
            if record.condition_id == "deterministic_closed_loop"
        }
        self.assertEqual(1, len(terminal_l3))

    def test_missing_layer_model_key_rejected(self) -> None:
        models = _layer_models()
        del models["phenotype_model"]
        with self.assertRaises(ValueError):
            ClosedLoopExperimentRunner(
                self.config,
                runner_config=self.runner_config,
                layer_models=models,
                feedback_config=self.feedback_config,
                noisy_grn_config=self.grn_config,
                noise_sigma=self.noise_sigma,
            )

    def test_budget_enforced(self) -> None:
        config = replace(self.config, ticks=999999)
        with self.assertRaises(ValueError):
            self._runner(config)


class FrozenBaselineGuardTests(unittest.TestCase):
    def test_deterministic_100_tick_identity_unchanged(self) -> None:
        scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_demo.json"
        )
        from mgba.runner import MultirateCrossScaleRunner

        runner = MultirateCrossScaleRunner(
            load_runner_config(ROOT / "configs" / "runner_reference.json"),
            **_layer_models(),
        )
        run = runner.run(scenario, ticks=100)
        self.assertEqual("mgba-c4801af10685fcb7", run.manifest.experiment_id)
        self.assertEqual(
            "5715209a09cc63b6495c0a4212467dac6fa662c9d03a885d1cd20df3e08325f2",
            run.history_digest,
        )
        self.assertEqual("failed", run.phenotype_window.outcome.value)


if __name__ == "__main__":
    unittest.main()
