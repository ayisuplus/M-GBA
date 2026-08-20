"""Extreme edge-case and crash-prevention tests for the active-inference L2 policy.

Covers numerical extremes (degenerate drives, sharp/flat beliefs, saturated
failure probabilities), config fail-fast validation, dead absorbing state,
determinism, identity/time contract violations, and rule-vs-inference
paired-matrix determinism.
"""

import math
import unittest
from dataclasses import replace
from pathlib import Path

from mgba.experiment import digest_payload
from mgba.layers import (
    CellPhase,
    CellState,
    LocalEnvironment,
    MolecularState,
    StateMetadata,
)
from mgba.layers.l2 import CellStateMachineModel, load_cell_config
from mgba.layers.l2_active_inference import (
    ActiveInferenceCellConfig,
    ActiveInferenceCellModel,
    _ACTIONS,
    _PHASES,
    load_active_inference_config,
)
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config
from mgba.layers.l3 import ConstraintAwareTissueModel, TissueEnvironmentModel, load_tissue_config
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.multiscale import load_multiscale_scenario
from mgba.policy_experiments import (
    PolicyExperimentRunner,
    load_policy_experiment_config,
)
from mgba.runner import MultirateCrossScaleRunner, load_runner_config

ROOT = Path(__file__).parents[1]
LAYER_CONFIGS = ROOT / "configs" / "layers"


def _meta(time: int, version: str = "test-0.1") -> StateMetadata:
    return StateMetadata(
        logical_time=time, model_version=version, source_digest="test"
    )


def _molecular(
    cell_id: str = "cell-x",
    time: int = 1,
    *,
    signal_protein: float = 0.2,
    repair_protein: float = 0.3,
    metabolic_capacity: float = 0.6,
    death_effector: float = 0.1,
    feedback_inhibitor: float = 0.1,
) -> MolecularState:
    return MolecularState(
        metadata=_meta(time, "test-l1-0.1"),
        cell_id=cell_id,
        damage_receptor=0.1,
        signal_protein=signal_protein,
        repair_protein=repair_protein,
        metabolic_capacity=metabolic_capacity,
        death_effector=death_effector,
        feedback_inhibitor=feedback_inhibitor,
    )


def _environment(
    cell_id: str = "cell-x",
    time: int = 1,
    *,
    stress: float = 0.2,
    resource_level: float = 0.8,
    incoming_signal: float = 0.0,
) -> LocalEnvironment:
    return LocalEnvironment(
        metadata=_meta(time, "test-env-0.1"),
        cell_id=cell_id,
        stress=stress,
        resource_level=resource_level,
        incoming_signal=incoming_signal,
    )


def _config(**overrides) -> ActiveInferenceCellConfig:
    raw = load_active_inference_config(LAYER_CONFIGS / "l2_active_inference.json")
    values = {
        field: getattr(raw, field)
        for field in (
            "model_version",
            "stress_environment_weight",
            "resource_deficit_weight",
            "death_stress_weight",
            "metabolic_buffer_weight",
            "signal_activation_weight",
            "incoming_signal_weight",
            "death_effector_weight",
            "stress_mortality_weight",
            "repair_recovery_rate",
            "stress_damage_rate",
            "death_damage_rate",
            "basal_consumption",
            "activation_consumption_rate",
            "repair_consumption_rate",
            "death_viability_threshold",
            "death_drive_threshold",
            "belief_precision",
            "ambiguity_weight",
            "phase_utilities",
            "secretion_multipliers",
        )
    }
    values.update(overrides)
    return ActiveInferenceCellConfig(**values)


def _model(**overrides) -> ActiveInferenceCellModel:
    return ActiveInferenceCellModel(_config(**overrides))


class ActiveInferenceConfigCrashPreventionTests(unittest.TestCase):
    def test_illegal_parameters_fail_fast(self) -> None:
        cases = (
            ("stress_environment_weight", math.nan),
            ("repair_recovery_rate", math.inf),
            ("basal_consumption", -0.1),
            ("death_viability_threshold", 1.5),
            ("belief_precision", 0.0),
            ("belief_precision", -2.0),
            ("belief_precision", math.nan),
            ("ambiguity_weight", -0.5),
            ("ambiguity_weight", math.inf),
        )
        for field, value in cases:
            with self.assertRaises(ValueError, msg=f"{field}={value}"):
                _config(**{field: value})

    def test_phase_utilities_must_cover_every_phase(self) -> None:
        partial = tuple(
            item
            for item in _config().phase_utilities
            if item[0] is not CellPhase.DEAD
        )
        with self.assertRaises(ValueError):
            _config(phase_utilities=partial)
        non_finite = tuple(
            (phase, math.inf if phase is CellPhase.DEAD else value)
            for phase, value in _config().phase_utilities
        )
        with self.assertRaises(ValueError):
            _config(phase_utilities=non_finite)

    def test_secretion_multipliers_must_cover_every_phase_and_range(self) -> None:
        bad = tuple(
            (phase, 1.5 if phase is CellPhase.STRESSED else value)
            for phase, value in _config().secretion_multipliers
        )
        with self.assertRaises(ValueError):
            _config(secretion_multipliers=bad)

    def test_missing_config_file_raises_value_error(self) -> None:
        missing = ROOT / "configs" / "layers" / "l2_active_inference_missing.json"
        self.assertFalse(missing.exists())
        with self.assertRaises(ValueError):
            load_active_inference_config(missing)


class ActiveInferenceNumericalEdgeCaseTests(unittest.TestCase):
    def test_extreme_molecular_boundaries_do_not_crash(self) -> None:
        model = _model()
        for signal in (0.0, 1.0):
            for repair in (0.0, 1.0):
                for death in (0.0, 1.0):
                    state, action = model.step(
                        _molecular(
                            signal_protein=signal,
                            repair_protein=repair,
                            death_effector=death,
                            metabolic_capacity=1.0 - death,
                        ),
                        _environment(stress=death, resource_level=1.0 - death),
                        previous_state=None,
                        logical_time=1,
                    )
                    self.assertIn(state.phase, _PHASES)
                    for field in ("activation", "viability", "stress_load"):
                        value = getattr(state, field)
                        self.assertTrue(0.0 <= value <= 1.0, field)

    def test_extreme_belief_precision_stays_stable(self) -> None:
        for precision in (1e-9, 1.0, 1e9):
            model = _model(belief_precision=precision)
            state, action = model.step(
                _molecular(), _environment(), previous_state=None, logical_time=1
            )
            self.assertIn(state.phase, _PHASES)
            self.assertTrue(math.isfinite(state.viability))

    def test_zero_ambiguity_weight_still_selects_valid_phase(self) -> None:
        model = _model(ambiguity_weight=0.0)
        state, action = model.step(
            _molecular(), _environment(), previous_state=None, logical_time=1
        )
        self.assertIn(state.phase, _PHASES)

    def test_dead_absorbing_state_ignores_all_actions(self) -> None:
        model = _model()
        forced_state, forced_action = model.step(
            _molecular(death_effector=1.0, metabolic_capacity=0.0),
            _environment(stress=1.0, resource_level=0.0),
            previous_state=None,
            logical_time=1,
        )
        self.assertIs(forced_state.phase, CellPhase.DEAD)
        self.assertTrue(forced_action.apoptosis)

        previous_dead = CellState(
            metadata=_meta(1, model.model_version),
            cell_id="cell-x",
            phase=CellPhase.DEAD,
            activation=0.0,
            viability=0.5,
            stress_load=0.5,
        )
        state, action = model.step(
            _molecular(time=2),
            _environment(time=2, stress=0.0, resource_level=1.0),
            previous_state=previous_dead,
            logical_time=2,
        )
        self.assertIs(state.phase, CellPhase.DEAD)
        self.assertTrue(action.apoptosis)
        self.assertEqual(0.0, action.repair_effort)
        self.assertEqual(0.0, action.secretion)

    def test_saturated_failure_probability_normalizes(self) -> None:
        model = _model()
        predicted = model._predicted_next(
            CellPhase.REPAIRING, (1.0, 0.0, 0.0, 1.0)
        )
        self.assertAlmostEqual(1.0, sum(predicted))
        self.assertTrue(all(p >= 0.0 for p in predicted))

    def test_all_actions_yield_valid_distributions(self) -> None:
        model = _model()
        for action in _ACTIONS:
            for drives in (
                (0.0, 0.0, 0.0, 0.0),
                (1.0, 1.0, 1.0, 1.0),
                (0.5, 0.5, 0.5, 0.5),
            ):
                predicted = model._predicted_next(action, drives)
                self.assertAlmostEqual(1.0, sum(predicted), msg=(action, drives))
                self.assertTrue(all(0.0 <= p <= 1.0 for p in predicted))

    def test_belief_is_a_valid_posterior(self) -> None:
        model = _model()
        for drives in ((0.0, 0.0, 0.0, 0.0), (1.0, 1.0, 1.0, 1.0)):
            for previous in (None, CellPhase.STRESSED):
                belief = model._belief(drives, previous)
                self.assertAlmostEqual(1.0, sum(belief))
                self.assertTrue(all(0.0 <= b <= 1.0 for b in belief))


class ActiveInferenceContractTests(unittest.TestCase):
    def test_time_regression_and_identity_violations_raise(self) -> None:
        model = _model()
        first, _ = model.step(
            _molecular(), _environment(), previous_state=None, logical_time=1
        )
        with self.assertRaises(ValueError):
            model.step(
                _molecular(time=1),
                _environment(time=1),
                previous_state=first,
                logical_time=1,
            )
        with self.assertRaises(ValueError):
            model.step(
                _molecular(cell_id="other"),
                _environment(),
                previous_state=None,
                logical_time=1,
            )
        with self.assertRaises(TypeError):
            model.step(
                "not-a-state", _environment(), previous_state=None, logical_time=1
            )

    def test_determinism_across_repeated_steps(self) -> None:
        model = _model()
        molecular = _molecular(signal_protein=0.7, repair_protein=0.5)
        environment = _environment(stress=0.3, resource_level=0.6)
        first = model.step(molecular, environment, previous_state=None, logical_time=1)
        second = model.step(molecular, environment, previous_state=None, logical_time=1)
        self.assertEqual(first, second)

    def test_model_version_encodes_config_digest(self) -> None:
        config = _config()
        model = ActiveInferenceCellModel(config)
        self.assertIn(digest_payload(config)[:12], model.model_version)
        other = ActiveInferenceCellModel(_config(ambiguity_weight=0.5))
        self.assertNotEqual(model.model_version, other.model_version)


class PolicyMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_demo.json"
        )
        self.runner_config = load_runner_config(
            ROOT / "configs" / "runner_reference.json"
        )
        self.policy_config = load_policy_experiment_config(
            ROOT / "configs" / "experiments" / "policy_comparison.json"
        )

    def _layer_models(self, *, use_inference: bool) -> dict:
        return {
            "genome_model": DiscreteGrnModel(
                load_grn_config(LAYER_CONFIGS / "l0_reference_grn.json")
            ),
            "molecular_model": CoarseMolecularModel(
                load_molecular_config(LAYER_CONFIGS / "l1_reference_molecular.json")
            ),
            "cell_model": (
                ActiveInferenceCellModel(
                    load_active_inference_config(
                        LAYER_CONFIGS / "l2_active_inference.json"
                    )
                )
                if use_inference
                else CellStateMachineModel(
                    load_cell_config(LAYER_CONFIGS / "l2_reference_cell.json")
                )
            ),
            "tissue_model": TissueEnvironmentModel(
                load_tissue_config(LAYER_CONFIGS / "l3_reference_tissue.json")
            ),
            "phenotype_model": PhenotypeObserverModel(
                load_phenotype_config(LAYER_CONFIGS / "l4_reference_phenotype.json")
            ),
        }

    def _runners(self) -> dict:
        return {
            "rule_policy": MultirateCrossScaleRunner(
                self.runner_config, **self._layer_models(use_inference=False)
            ),
            "active_inference_policy": MultirateCrossScaleRunner(
                self.runner_config, **self._layer_models(use_inference=True)
            ),
        }

    def test_matrix_structure_and_determinism(self) -> None:
        runners = self._runners()
        matrix = PolicyExperimentRunner(self.policy_config, runners=runners).run(
            self.scenario
        )
        self.assertEqual(2 * len(self.policy_config.seeds), len(matrix.records))
        self.assertEqual(len(self.policy_config.seeds), len(matrix.comparisons))
        self.assertEqual(1, len(matrix.summaries))
        self.assertTrue(matrix.matrix_id.startswith("policy-"))
        second = PolicyExperimentRunner(self.policy_config, runners=runners).run(
            self.scenario
        )
        self.assertEqual(matrix.matrix_id, second.matrix_id)
        self.assertEqual(
            [record.run.history_digest for record in matrix.records],
            [record.run.history_digest for record in second.records],
        )

    def test_l0_effect_is_zero_and_l1_only_reflects_adjacent_feedback(self) -> None:
        runners = self._runners()
        matrix = PolicyExperimentRunner(self.policy_config, runners=runners).run(
            self.scenario
        )
        for comparison in matrix.comparisons:
            effects = dict(comparison.layer_effects)
            # AIF only changes L2 decisions: L0 must stay exactly identical.
            self.assertEqual(0.0, effects["L0"])
            # L1 differs only through the adjacent L2->L1 local_signal feedback.
            self.assertLess(effects["L1"], 1e-6)
            self.assertGreaterEqual(effects["L2"], 0.0)

    def test_runner_rejects_wrong_layer_change(self) -> None:
        runners = self._runners()
        bad_models = self._layer_models(use_inference=True)
        bad_models["tissue_model"] = ConstraintAwareTissueModel(
            load_tissue_config(LAYER_CONFIGS / "l3_reference_tissue.json")
        )
        bad_runners = dict(runners)
        bad_runners["active_inference_policy"] = MultirateCrossScaleRunner(
            self.runner_config, **bad_models
        )
        with self.assertRaises(ValueError):
            PolicyExperimentRunner(self.policy_config, runners=bad_runners)

    def test_budget_enforced(self) -> None:
        runners = self._runners()
        config = replace(self.policy_config, ticks=999999)
        with self.assertRaises(ValueError):
            PolicyExperimentRunner(config, runners=runners)


if __name__ == "__main__":
    unittest.main()
