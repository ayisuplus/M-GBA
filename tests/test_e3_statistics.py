"""Extreme edge-case and crash-prevention tests for the stochastic L0 + E3 layer.

Covers noise-model determinism and bounds, config fail-fast validation,
checkpoint-replay determinism under noise, OLS degeneracies, the E3 grading
ladder across all five grades, insufficient-seed ensembles, and the
frozen-baseline identity guard (deterministic L0 untouched).
"""

import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from mgba.e3_experiments import (
    E3ExperimentRunner,
    load_e3_experiment_config,
    save_e3_artifacts,
)
from mgba.e3_statistics import (
    E3CriteriaConfig,
    E3_MACRO_METRICS,
    classify_metric,
    e3_summary_digest,
    evaluate_e3,
)
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l0_noisy import NoisyDiscreteGrnModel, load_noisy_grn_config
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config
from mgba.layers.l2 import CellStateMachineModel, load_cell_config
from mgba.layers.l3 import TissueEnvironmentModel, load_tissue_config
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.models import Genome
from mgba.multiscale import load_multiscale_scenario
from mgba.runner import MultirateCrossScaleRunner, load_runner_config

ROOT = Path(__file__).parents[1]
LAYER_CONFIGS = ROOT / "configs" / "layers"


def _criteria(**overrides) -> E3CriteriaConfig:
    values = dict(
        model_version="test-e3-criteria",
        cv_threshold=0.05,
        coupling_threshold=0.5,
        persistence_threshold=0.6,
        pattern_threshold=0.4,
    )
    values.update(overrides)
    return E3CriteriaConfig(**values)


def _noisy_model(noise_seed: int, noise_sigma: float = 0.08) -> NoisyDiscreteGrnModel:
    grn_config, sigma = load_noisy_grn_config(LAYER_CONFIGS / "l0_noisy_grn.json")
    return NoisyDiscreteGrnModel(
        grn_config, noise_sigma=noise_sigma if noise_sigma != 0.08 else sigma, noise_seed=noise_seed
    )


def _layer_models(genome_model) -> dict:
    return {
        "genome_model": genome_model,
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


def _runner(genome_model) -> MultirateCrossScaleRunner:
    return MultirateCrossScaleRunner(
        load_runner_config(ROOT / "configs" / "runner_reference.json"),
        **_layer_models(genome_model),
    )


class NoisyGrnConfigCrashPreventionTests(unittest.TestCase):
    def test_illegal_noise_parameters_fail_fast(self) -> None:
        grn_config, sigma = load_noisy_grn_config(
            LAYER_CONFIGS / "l0_noisy_grn.json"
        )
        cases = (
            (math.nan, 1),
            (math.inf, 1),
            (-0.1, 1),
            (1.5, 1),
            (0.1, -1),
            (0.1, True),
        )
        for noise_sigma, noise_seed in cases:
            with self.assertRaises((ValueError, TypeError)):
                NoisyDiscreteGrnModel(
                    grn_config, noise_sigma=noise_sigma, noise_seed=noise_seed
                )

    def test_missing_config_file_raises_value_error(self) -> None:
        missing = ROOT / "configs" / "layers" / "l0_noisy_missing.json"
        self.assertFalse(missing.exists())
        with self.assertRaises(ValueError):
            load_noisy_grn_config(missing)

    def test_criteria_config_fail_fast(self) -> None:
        cases = (
            {"cv_threshold": 0.0},
            {"cv_threshold": math.nan},
            {"coupling_threshold": 1.5},
            {"persistence_threshold": -0.2},
            {"pattern_threshold": 1.2},
            {"model_version": "   "},
        )
        for overrides in cases:
            with self.assertRaises(ValueError, msg=str(overrides)):
                _criteria(**overrides)


class NoisyGrnModelBehaviorTests(unittest.TestCase):
    def test_same_seed_same_trajectory_different_seeds_differ(self) -> None:
        scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_demo.json"
        )
        first = _runner(_noisy_model(42)).run(scenario, ticks=15)
        second = _runner(_noisy_model(42)).run(scenario, ticks=15)
        other = _runner(_noisy_model(43)).run(scenario, ticks=15)
        self.assertEqual(first.history_digest, second.history_digest)
        self.assertNotEqual(first.history_digest, other.history_digest)

    def test_transcript_values_remain_bounded_under_noise(self) -> None:
        scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_demo.json"
        )
        # Large sigma stress-tests the clamp path.
        run = _runner(_noisy_model(7, noise_sigma=1.0)).run(scenario, ticks=20)
        for tick in run.ticks:
            for state in tick.l0:
                for gene in (
                    "damage_response",
                    "signal_expression",
                    "repair_expression",
                    "metabolic_expression",
                    "death_expression",
                    "negative_feedback_expression",
                ):
                    value = getattr(state, gene)
                    self.assertTrue(0.0 <= value <= 1.0, (gene, value))
    def test_zero_sigma_matches_deterministic_baseline_values(self) -> None:
        scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_demo.json"
        )
        deterministic = _runner(
            DiscreteGrnModel(load_grn_config(LAYER_CONFIGS / "l0_reference_grn.json"))
        ).run(scenario, ticks=15)
        noisy = _runner(_noisy_model(99, noise_sigma=0.0)).run(scenario, ticks=15)
        # Distinct model identities (different model_version metadata) but
        # sigma=0 must reproduce identical gene-expression values.
        genes = (
            "damage_response",
            "signal_expression",
            "repair_expression",
            "metabolic_expression",
            "death_expression",
            "negative_feedback_expression",
        )
        for base_tick, noisy_tick in zip(deterministic.ticks, noisy.ticks):
            for base_state, noisy_state in zip(base_tick.l0, noisy_tick.l0):
                self.assertEqual(base_state.cell_id, noisy_state.cell_id)
                for gene in genes:
                    self.assertEqual(
                        getattr(base_state, gene), getattr(noisy_state, gene), gene
                    )

    def test_perturbation_clamps_still_exact_under_noise(self) -> None:
        scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_demo.json"
        )
        run = _runner(_noisy_model(5)).run(
            scenario,
            ticks=10,
            perturbations={"cell-a": {"repair_expression": 0.0}},
        )
        for tick in run.ticks:
            if tick.l0_updated:
                clamped = next(s for s in tick.l0 if s.cell_id == "cell-a")
                self.assertEqual(0.0, clamped.repair_expression)

    def test_checkpoint_resume_reproduces_noisy_trajectory(self) -> None:
        scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_demo.json"
        )
        runner = _runner(_noisy_model(11))
        full = runner.run(scenario, ticks=15)
        part1 = runner.run(scenario, ticks=7)
        part2 = runner.run(scenario, ticks=8, checkpoint=part1.checkpoint)
        self.assertEqual(full.history_digest, part2.history_digest)
        self.assertEqual(full.checkpoint, part2.checkpoint)

    def test_model_version_changes_with_noise_parameters(self) -> None:
        self.assertNotEqual(
            _noisy_model(1).model_version, _noisy_model(2).model_version
        )


class E3ClassificationTests(unittest.TestCase):
    def test_all_five_grades_reachable(self) -> None:
        criteria = _criteria()
        # insufficient_seeds: two values.
        stats = classify_metric(
            "homeostasis", (0.5, 0.6), (0.5, 0.6), criteria
        )
        self.assertEqual("insufficient_seeds", stats.grade)
        # no_pattern: identical values.
        stats = classify_metric(
            "homeostasis", (0.5, 0.5, 0.5), (0.1, 0.2, 0.3), criteria
        )
        self.assertEqual("no_pattern", stats.grade)
        # emergence_candidate: stable, decoupled from drive, persistent.
        stats = classify_metric(
            "homeostasis",
            (0.61, 0.62, 0.60, 0.615),
            (0.9, 0.1, 0.5, 0.7),
            criteria,
        )
        self.assertEqual("emergence_candidate", stats.grade)
        # group_dynamics: stable but coupled to the drive.
        stats = classify_metric(
            "homeostasis",
            (0.60, 0.61, 0.62, 0.63),
            (0.60, 0.61, 0.62, 0.63),
            criteria,
        )
        self.assertEqual("group_dynamics", stats.grade)
        # aggregation: noise-dominated.
        stats = classify_metric(
            "homeostasis",
            (0.1, 0.9, 0.2, 0.8),
            (0.5, 0.5, 0.5, 0.5),
            criteria,
        )
        self.assertEqual("aggregation", stats.grade)

    def test_degenerate_variance_r_squared_is_zero(self) -> None:
        stats = classify_metric(
            "tissue_damage", (0.5, 0.5, 0.5), (0.1, 0.9, 0.5), _criteria()
        )
        self.assertEqual(0.0, stats.r_squared)

    def test_unknown_metric_rejected(self) -> None:
        with self.assertRaises(ValueError):
            classify_metric("not-a-metric", (0.5, 0.5), (0.5, 0.5), _criteria())

    def test_evaluate_e3_requires_runs_and_covers_all_metrics(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_e3({}, _criteria())
        scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_demo.json"
        )
        runs = {}
        for seed in (1, 2, 3):
            runs[seed] = _runner(_noisy_model(seed)).run(scenario, ticks=10)
        stats = evaluate_e3(runs, _criteria())
        self.assertEqual(E3_MACRO_METRICS, tuple(item.metric for item in stats))
        digest = e3_summary_digest(stats)
        self.assertEqual(64, len(digest))

    def test_matrix_runner_and_determinism(self) -> None:
        scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_demo.json"
        )
        config = load_e3_experiment_config(
            ROOT / "configs" / "experiments" / "e3_population.json"
        )
        config = replace_seeds(config, seeds=(7, 42, 1337))
        config = replace_ticks(config, ticks=15)

        def build(seed: int) -> MultirateCrossScaleRunner:
            return _runner(_noisy_model(seed))

        first = E3ExperimentRunner(config, build_runner=build).run(scenario)
        second = E3ExperimentRunner(config, build_runner=build).run(scenario)
        self.assertEqual(first.matrix_id, second.matrix_id)
        self.assertEqual(first.summary_digest, second.summary_digest)
        self.assertEqual(
            dict(first.experiment_ids), dict(second.experiment_ids)
        )
        self.assertTrue(first.matrix_id.startswith("e3-"))

    def test_budget_and_bad_build_runner_rejected(self) -> None:
        config = load_e3_experiment_config(
            ROOT / "configs" / "experiments" / "e3_population.json"
        )
        with self.assertRaises(TypeError):
            E3ExperimentRunner(config, build_runner=None)  # type: ignore[arg-type]
        huge = replace_ticks(config, ticks=999999)

        def build(seed: int) -> MultirateCrossScaleRunner:
            return _runner(_noisy_model(seed))

        with self.assertRaises(ValueError):
            E3ExperimentRunner(huge, build_runner=build)


def replace_seeds(config, *, seeds):
    from dataclasses import replace as _replace

    return _replace(config, seeds=tuple(sorted(seeds)))


def replace_ticks(config, *, ticks):
    from dataclasses import replace as _replace

    return _replace(config, ticks=ticks)


class E3ExperimentConfigCrashPreventionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_e3_experiment_config(
            ROOT / "configs" / "experiments" / "e3_population.json"
        )

    def test_invalid_config_fields_fail_fast(self) -> None:
        cases = (
            {"model_version": "   "},
            {"ticks": 0},
            {"ticks": True},
            {"seeds": (1,)},
            {"seeds": (2, 1)},
            {"seeds": (1, 1)},
            {"seeds": (-1, 2)},
            {"seeds": (True, 2)},
        )
        for overrides in cases:
            with self.assertRaises(ValueError, msg=str(overrides)):
                replace(self.config, **overrides)

    def test_wrong_criteria_type_rejected(self) -> None:
        with self.assertRaises(TypeError):
            replace(self.config, criteria=object())

    def test_malformed_config_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_e3_experiment_config(path)


class E3RunnerGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_demo.json"
        )
        self.config = load_e3_experiment_config(
            ROOT / "configs" / "experiments" / "e3_population.json"
        )

    def _build(self, seed: int) -> MultirateCrossScaleRunner:
        return _runner(_noisy_model(seed))

    def test_model_version_property_tracks_config(self) -> None:
        runner = E3ExperimentRunner(self.config, build_runner=self._build)
        self.assertTrue(
            runner.model_version.startswith(f"{self.config.model_version}+")
        )
        again = E3ExperimentRunner(self.config, build_runner=self._build)
        self.assertEqual(runner.model_version, again.model_version)
        other = E3ExperimentRunner(
            replace(self.config, model_version="other-e3-version"),
            build_runner=self._build,
        )
        self.assertNotEqual(runner.model_version, other.model_version)

    def test_non_scenario_rejected(self) -> None:
        runner = E3ExperimentRunner(self.config, build_runner=self._build)
        with self.assertRaises(TypeError):
            runner.run(object())

    def test_truncated_trace_fails_closed(self) -> None:
        stub = SimpleNamespace(
            config=SimpleNamespace(max_total_ticks=1000),
            run=lambda scenario, ticks: SimpleNamespace(ticks=()),
        )
        config = replace(self.config, seeds=(1, 2), ticks=4)
        with self.assertRaises(RuntimeError):
            E3ExperimentRunner(
                config, build_runner=lambda seed: stub
            ).run(self.scenario)

    def test_artifacts_persist_summary_and_manifest_and_refuse_conflicts(
        self,
    ) -> None:
        config = replace(self.config, seeds=(1, 2), ticks=10)
        result = E3ExperimentRunner(config, build_runner=self._build).run(
            self.scenario
        )
        with tempfile.TemporaryDirectory() as directory:
            paths = save_e3_artifacts(directory, result)
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            summary = json.loads(paths["summary"].read_text(encoding="utf-8"))

            self.assertEqual(result.matrix_id, manifest["matrix_id"])
            self.assertEqual(result.matrix_id, summary["matrix_id"])
            self.assertEqual("mgba-e3-artifact-0.1", summary["schema_version"])
            self.assertEqual([1, 2], summary["seeds"])
            self.assertEqual(
                result.summary_digest, manifest["summary_digest"]
            )
            self.assertFalse((paths["root"] / "raw").exists())
            save_e3_artifacts(directory, result)
            with self.assertRaises(ValueError):
                save_e3_artifacts(
                    directory, replace(result, scenario_digest="different")
                )
            paths["summary"].write_text("{", encoding="utf-8")
            with self.assertRaises(ValueError):
                save_e3_artifacts(directory, result)
            with self.assertRaises(TypeError):
                save_e3_artifacts(directory, object())
        with self.assertRaises(ValueError):
            replace(result, stats=())


class FrozenBaselineGuardTests(unittest.TestCase):
    def test_deterministic_100_tick_identity_unchanged(self) -> None:
        scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_demo.json"
        )
        runner = _runner(
            DiscreteGrnModel(load_grn_config(LAYER_CONFIGS / "l0_reference_grn.json"))
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
