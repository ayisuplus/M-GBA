"""Tests for the AIDO-inspired state-conditioned intervention protocol."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from mgba.intervention_experiments import (
    ScheduledInterventionCondition,
    StateConditionedInterventionRunner,
    TimingContrastSpec,
    build_carm_intervention_runner,
    load_state_conditioned_intervention_config,
    save_state_conditioned_intervention_artifacts,
)
from mgba.runner import load_runner_config
from mgba.scenarios.carm import compile_carm_scenario, load_carm_scenario_config


ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "configs" / "experiments" / "carm_state_conditioned_intervention.json"


class StateConditionedInterventionConfigTests(unittest.TestCase):
    def test_shipped_protocol_is_a_balanced_timing_by_exposure_design(self) -> None:
        config = load_state_conditioned_intervention_config(CONFIG)
        self.assertEqual(60, config.ticks)
        self.assertEqual("signal_expression", config.gene)
        self.assertEqual(1.0, config.value)
        self.assertEqual(4, len(config.conditions))
        self.assertEqual(2, len(config.timing_contrasts))
        for contrast in config.timing_contrasts:
            early = config.condition_map[contrast.early_condition_id]
            late = config.condition_map[contrast.late_condition_id]
            self.assertEqual(len(early.l0_update_ticks), len(late.l0_update_ticks))
            self.assertLess(early.l0_update_ticks[0], late.l0_update_ticks[0])

    def test_off_clock_and_unbalanced_contrasts_fail_fast(self) -> None:
        config = load_state_conditioned_intervention_config(CONFIG)
        compiled = compile_carm_scenario(
            load_carm_scenario_config(
                ROOT / "configs" / "scenarios" / "carm" / "high_immune_her2.json"
            )
        )
        runner = build_carm_intervention_runner(
            compiled,
            runner_config=load_runner_config(ROOT / "configs" / "runner_reference.json"),
            l0_config=ROOT / "configs" / "layers" / "l0_reference_grn.json",
            l1_config=ROOT / "configs" / "layers" / "l1_reference_molecular.json",
            l4_config=ROOT / "configs" / "layers" / "l4_reference_phenotype.json",
        )
        bad_clock = replace(
            config,
            conditions=(
                ScheduledInterventionCondition("early", (2,)),
                ScheduledInterventionCondition("late", (6,)),
            ),
            timing_contrasts=(TimingContrastSpec("timing", "early", "late"),),
        )
        with self.assertRaises(ValueError):
            StateConditionedInterventionRunner(bad_clock, runner=runner)
        with self.assertRaises(ValueError):
            replace(
                config,
                conditions=(
                    ScheduledInterventionCondition("early", (1,)),
                    ScheduledInterventionCondition("late", (6, 11)),
                ),
                timing_contrasts=(TimingContrastSpec("timing", "early", "late"),),
            )


class StateConditionedInterventionExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compiled = compile_carm_scenario(
            load_carm_scenario_config(
                ROOT / "configs" / "scenarios" / "carm" / "high_immune_her2.json"
            )
        )
        cls.runner = build_carm_intervention_runner(
            cls.compiled,
            runner_config=load_runner_config(ROOT / "configs" / "runner_reference.json"),
            l0_config=ROOT / "configs" / "layers" / "l0_reference_grn.json",
            l1_config=ROOT / "configs" / "layers" / "l1_reference_molecular.json",
            l4_config=ROOT / "configs" / "layers" / "l4_reference_phenotype.json",
        )
        shipped = load_state_conditioned_intervention_config(CONFIG)
        cls.config = replace(
            shipped,
            model_version="test-state-conditioned-intervention",
            ticks=12,
            seeds=(41, 42),
            conditions=(
                ScheduledInterventionCondition("early", (1,)),
                ScheduledInterventionCondition("late", (6,)),
            ),
            timing_contrasts=(TimingContrastSpec("timing", "early", "late"),),
        )
        cls.result = StateConditionedInterventionRunner(
            cls.config, runner=cls.runner
        ).run(cls.compiled)

    def test_equal_interventions_are_audited_in_different_baseline_states(self) -> None:
        self.assertEqual(6, len(self.result.records))
        self.assertEqual(4, len(self.result.comparisons))
        self.assertEqual(4, len(self.result.context_audits))
        self.assertEqual(2, len(self.result.timing_contrasts))
        self.assertEqual(15, len(self.result.target_ids))
        for audit in self.result.context_audits:
            self.assertEqual(0.0, audit.pre_onset_max_layer_distance)
        contexts = {
            (item.condition_id, item.seed): item
            for item in self.result.context_audits
        }
        for seed in self.config.seeds:
            self.assertEqual(0, contexts[("early", seed)].context_tick)
            self.assertEqual(5, contexts[("late", seed)].context_tick)
            self.assertNotEqual(
                contexts[("early", seed)].baseline_context_digest,
                contexts[("late", seed)].baseline_context_digest,
            )
        self.assertTrue(
            all(item.terminal_l4_distance >= 0.0 for item in self.result.timing_contrasts)
        )

    def test_schedule_is_checkpoint_exact_and_rejects_ambiguous_inputs(self) -> None:
        scenario = replace(self.compiled.scenario, seed=41)
        target = self.result.target_ids[0]
        schedule = {
            1: {target: {"signal_expression": 1.0}},
            11: {target: {"signal_expression": 1.0}},
        }
        one_shot = self.runner.run(
            scenario, ticks=12, perturbation_schedule=schedule
        )
        first = self.runner.run(scenario, ticks=6, perturbation_schedule=schedule)
        resumed = self.runner.run(
            scenario,
            ticks=6,
            perturbation_schedule=schedule,
            checkpoint=first.checkpoint,
        )
        self.assertEqual(one_shot.history_digest, resumed.history_digest)
        self.assertEqual(one_shot.checkpoint, resumed.checkpoint)
        with self.assertRaises(ValueError):
            self.runner.run(
                scenario,
                ticks=2,
                perturbations={target: {"signal_expression": 1.0}},
                perturbation_schedule={1: {target: {"signal_expression": 1.0}}},
            )
        with self.assertRaises(ValueError):
            self.runner.run(
                scenario,
                ticks=2,
                perturbation_schedule={2: {target: {"signal_expression": 1.0}}},
            )

    def test_artifacts_keep_every_raw_run_and_refuse_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = save_state_conditioned_intervention_artifacts(tmp, self.result)
            repeated = save_state_conditioned_intervention_artifacts(tmp, self.result)
            self.assertEqual(paths, repeated)
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            self.assertEqual(7, len(manifest["files"]))
            self.assertTrue(paths["summary"].exists())
            paths["summary"].write_text("{}\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                save_state_conditioned_intervention_artifacts(tmp, self.result)


if __name__ == "__main__":
    unittest.main()
