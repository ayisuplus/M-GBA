"""Edge-case, contract, and paired-matrix tests for the latent-cell L2 policy.

Covers numerical extremes (degenerate drives, minimal/large latent dims,
full leak), config fail-fast validation, dead absorbing state, the
no-hidden-memory reconstruction invariant, determinism, identity/time
contract violations, and rule-vs-latent paired-matrix determinism.
"""

import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from mgba.experiment import digest_payload
from mgba.layers import (
    CellPhase,
    CellState,
    LocalEnvironment,
    MolecularState,
    StateMetadata,
)
from mgba.layers.l2 import CellStateMachineModel, load_cell_config
from mgba.layers.l2_latent import (
    _BOOKKEEPING_FIELDS,
    _LATENT_PHASES,
    LatentCellConfig,
    LatentCellModel,
    load_latent_cell_config,
)
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config
from mgba.layers.l3 import (
    ConstraintAwareTissueModel,
    TissueEnvironmentModel,
    load_tissue_config,
)
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.multiscale import load_multiscale_scenario
from mgba.latent_experiments import (
    LatentExperimentRunner,
    load_latent_experiment_config,
    save_latent_artifacts,
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


def _config(**overrides) -> LatentCellConfig:
    raw = load_latent_cell_config(LAYER_CONFIGS / "l2_latent_cell.json")
    values = {
        field: getattr(raw, field)
        for field in (
            "model_version",
            "latent_dim",
            "leak_rate",
            "weight_seed",
            *_BOOKKEEPING_FIELDS,
            "secretion_multipliers",
        )
    }
    values.update(overrides)
    return LatentCellConfig(**values)


def _model(**overrides) -> LatentCellModel:
    return LatentCellModel(_config(**overrides))


class _TruncatedRunner:
    """Runner double whose run() violates the E0 tick-completeness contract."""

    def __init__(self, config, model_versions) -> None:
        self.config = config
        self.model_versions = model_versions

    def run(self, scenario, ticks):
        return SimpleNamespace(ticks=())


class LatentConfigCrashPreventionTests(unittest.TestCase):
    def test_illegal_parameters_fail_fast(self) -> None:
        value_error_cases = (
            ("stress_environment_weight", math.nan),
            ("repair_recovery_rate", math.inf),
            ("basal_consumption", -0.1),
            ("death_viability_threshold", 1.5),
            ("latent_dim", 0),
            ("latent_dim", -3),
            ("leak_rate", 0.0),
            ("leak_rate", 1.5),
            ("leak_rate", math.nan),
            ("weight_seed", -1),
        )
        for field, value in value_error_cases:
            with self.assertRaises(ValueError, msg=f"{field}={value}"):
                _config(**{field: value})
        type_error_cases = (
            ("latent_dim", True),
            ("latent_dim", 2.5),
            ("weight_seed", True),
            ("weight_seed", "x"),
        )
        for field, value in type_error_cases:
            with self.assertRaises(TypeError, msg=f"{field}={value}"):
                _config(**{field: value})

    def test_secretion_multipliers_must_cover_every_phase_and_range(self) -> None:
        partial = tuple(
            item
            for item in _config().secretion_multipliers
            if item[0] is not CellPhase.DEAD
        )
        with self.assertRaises(ValueError):
            _config(secretion_multipliers=partial)
        bad = tuple(
            (phase, 1.5 if phase is CellPhase.STRESSED else value)
            for phase, value in _config().secretion_multipliers
        )
        with self.assertRaises(ValueError):
            _config(secretion_multipliers=bad)

    def test_missing_config_file_raises_value_error(self) -> None:
        missing = ROOT / "configs" / "layers" / "l2_latent_cell_missing.json"
        self.assertFalse(missing.exists())
        with self.assertRaises(ValueError):
            load_latent_cell_config(missing)


class LatentNumericalEdgeCaseTests(unittest.TestCase):
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
                    self.assertIn(state.phase, tuple(CellPhase))
                    for field in ("activation", "viability", "stress_load"):
                        value = getattr(state, field)
                        self.assertTrue(0.0 <= value <= 1.0, field)
                    for field in ("secretion", "resource_consumption", "repair_effort"):
                        value = getattr(action, field)
                        self.assertTrue(0.0 <= value <= 1.0, field)

    def test_minimal_and_large_latent_dims_stay_stable(self) -> None:
        for dim in (1, 64):
            model = _model(latent_dim=dim)
            state, _ = model.step(
                _molecular(), _environment(), previous_state=None, logical_time=1
            )
            self.assertIn(state.phase, tuple(CellPhase))
            self.assertTrue(math.isfinite(state.viability))

    def test_full_leak_rate_stays_valid(self) -> None:
        model = _model(leak_rate=1.0)
        trajectory = model.simulate(
            molecular=_molecular(),
            stress=0.6,
            resource_level=0.4,
            incoming_signal=0.2,
            steps=8,
        )
        self.assertEqual(8, len(trajectory.states))
        for state in trajectory.states:
            self.assertIn(state.phase, tuple(CellPhase))

    def test_recurrent_rows_are_l1_normalized(self) -> None:
        model = _model()
        for row in model._w_rec:
            self.assertLessEqual(sum(abs(value) for value in row), 1.0 + 1e-12)

    def test_readout_never_selects_dead(self) -> None:
        model = _model()
        state, action = model.step(
            _molecular(signal_protein=0.8, repair_protein=0.9),
            _environment(stress=0.1, resource_level=0.9, incoming_signal=0.5),
            previous_state=None,
            logical_time=1,
        )
        self.assertIn(state.phase, _LATENT_PHASES)
        self.assertIsNot(state.phase, CellPhase.DEAD)
        self.assertFalse(action.apoptosis)

    def test_dead_absorbing_state_ignores_all_inputs(self) -> None:
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


class LatentContractTests(unittest.TestCase):
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
        model = LatentCellModel(config)
        self.assertIn(digest_payload(config)[:12], model.model_version)
        other = LatentCellModel(_config(weight_seed=19002))
        self.assertNotEqual(model.model_version, other.model_version)

    def test_latent_state_reconstructs_from_formal_state(self) -> None:
        """No hidden memory: the formal CellState fully carries the history."""
        model = _model()
        molecular = _molecular(signal_protein=0.6, repair_protein=0.4)
        long_run = model.simulate(
            molecular=molecular,
            stress=0.5,
            resource_level=0.5,
            incoming_signal=0.1,
            steps=6,
        )
        short_run = model.simulate(
            molecular=molecular,
            stress=0.5,
            resource_level=0.5,
            incoming_signal=0.1,
            steps=5,
        )
        continuation = model.step(
            molecular,
            _environment(time=6, stress=0.5, resource_level=0.5, incoming_signal=0.1),
            previous_state=short_run.states[-1],
            logical_time=6,
        )
        # Boundary metadata provenance differs between simulate() and the
        # manual step, so compare the semantic payload, not the digest.
        expected_state = long_run.states[-1]
        actual_state = continuation[0]
        for field in ("cell_id", "phase", "activation", "viability", "stress_load"):
            self.assertEqual(getattr(expected_state, field), getattr(actual_state, field))
        expected_action = long_run.actions[-1]
        actual_action = continuation[1]
        for field in (
            "cell_id",
            "secretion",
            "resource_consumption",
            "repair_effort",
            "apoptosis",
        ):
            self.assertEqual(
                getattr(expected_action, field), getattr(actual_action, field)
            )


class LatentMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_demo.json"
        )
        self.runner_config = load_runner_config(
            ROOT / "configs" / "runner_reference.json"
        )
        self.latent_config = load_latent_experiment_config(
            ROOT / "configs" / "experiments" / "latent_comparison.json"
        )

    def _layer_models(self, *, use_latent: bool) -> dict:
        return {
            "genome_model": DiscreteGrnModel(
                load_grn_config(LAYER_CONFIGS / "l0_reference_grn.json")
            ),
            "molecular_model": CoarseMolecularModel(
                load_molecular_config(LAYER_CONFIGS / "l1_reference_molecular.json")
            ),
            "cell_model": (
                LatentCellModel(
                    load_latent_cell_config(LAYER_CONFIGS / "l2_latent_cell.json")
                )
                if use_latent
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
                self.runner_config, **self._layer_models(use_latent=False)
            ),
            "latent_cell_policy": MultirateCrossScaleRunner(
                self.runner_config, **self._layer_models(use_latent=True)
            ),
        }

    def test_matrix_structure_and_determinism(self) -> None:
        runners = self._runners()
        matrix = LatentExperimentRunner(self.latent_config, runners=runners).run(
            self.scenario
        )
        self.assertEqual(2 * len(self.latent_config.seeds), len(matrix.records))
        self.assertEqual(len(self.latent_config.seeds), len(matrix.comparisons))
        self.assertEqual(1, len(matrix.summaries))
        self.assertTrue(matrix.matrix_id.startswith("latent-"))
        second = LatentExperimentRunner(self.latent_config, runners=runners).run(
            self.scenario
        )
        self.assertEqual(matrix.matrix_id, second.matrix_id)
        self.assertEqual(
            [record.run.history_digest for record in matrix.records],
            [record.run.history_digest for record in second.records],
        )

    def test_l0_effect_is_zero_and_l1_only_reflects_adjacent_feedback(self) -> None:
        runners = self._runners()
        matrix = LatentExperimentRunner(self.latent_config, runners=runners).run(
            self.scenario
        )
        for comparison in matrix.comparisons:
            effects = dict(comparison.layer_effects)
            # The latent policy only changes L2 decisions: L0 must stay identical.
            self.assertEqual(0.0, effects["L0"])
            # L1 differs only through the adjacent L2->L1 local_signal feedback.
            self.assertLess(effects["L1"], 1e-6)
            self.assertGreaterEqual(effects["L2"], 0.0)

    def test_runner_rejects_wrong_layer_change(self) -> None:
        runners = self._runners()
        bad_models = self._layer_models(use_latent=True)
        bad_models["tissue_model"] = ConstraintAwareTissueModel(
            load_tissue_config(LAYER_CONFIGS / "l3_reference_tissue.json")
        )
        bad_runners = dict(runners)
        bad_runners["latent_cell_policy"] = MultirateCrossScaleRunner(
            self.runner_config, **bad_models
        )
        with self.assertRaises(ValueError):
            LatentExperimentRunner(self.latent_config, runners=bad_runners)

    def test_budget_enforced(self) -> None:
        runners = self._runners()
        config = replace(self.latent_config, ticks=999999)
        with self.assertRaises(ValueError):
            LatentExperimentRunner(config, runners=runners)

    def test_runner_set_and_scenario_type_enforced(self) -> None:
        runners = self._runners()
        runners.pop("latent_cell_policy")
        with self.assertRaises(ValueError):
            LatentExperimentRunner(self.latent_config, runners=runners)
        matrix = LatentExperimentRunner(self.latent_config, runners=self._runners())
        with self.assertRaises(TypeError):
            matrix.run(object())

    def test_truncated_trace_fails_closed(self) -> None:
        base_versions = {"L0": "v", "L1": "v", "L2": "rule", "L3": "v", "L4": "v"}
        latent_versions = dict(base_versions, L2="latent")
        stubs = {
            "rule_policy": _TruncatedRunner(self.runner_config, base_versions),
            "latent_cell_policy": _TruncatedRunner(
                self.runner_config, latent_versions
            ),
        }
        matrix = LatentExperimentRunner(
            replace(self.latent_config, ticks=5), runners=stubs
        )
        with self.assertRaises(RuntimeError):
            matrix.run(self.scenario)

    def test_model_version_property_tracks_config_digest(self) -> None:
        matrix = LatentExperimentRunner(self.latent_config, runners=self._runners())
        self.assertTrue(
            matrix.model_version.startswith(f"{self.latent_config.model_version}+")
        )
        other = LatentExperimentRunner(
            replace(self.latent_config, ticks=5), runners=self._runners()
        )
        self.assertNotEqual(matrix.model_version, other.model_version)

    def test_experiment_config_guards_fail_closed(self) -> None:
        cases = (
            {"model_version": "  "},
            {"ticks": 0},
            {"ticks": True},
            {"seeds": (42,)},
            {"seeds": (2, 1)},
            {"seeds": (1, 1)},
            {"seeds": (-1, 2)},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    replace(self.latent_config, **overrides)

    def test_load_config_wraps_malformed_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_latent_experiment_config(path)
            path.write_text(json.dumps({"model_version": "x"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_latent_experiment_config(path)

    def test_artifacts_persist_append_only_and_refuse_conflicts(self) -> None:
        config = replace(self.latent_config, seeds=(1, 2), ticks=3)
        result = LatentExperimentRunner(config, runners=self._runners()).run(
            self.scenario
        )
        with tempfile.TemporaryDirectory() as directory:
            paths = save_latent_artifacts(directory, result)
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
            raw_files = tuple(paths["raw"].rglob("seed-*.json"))

            self.assertEqual("mgba-latent-artifact-0.1", manifest["schema_version"])
            self.assertEqual(result.matrix_id, manifest["matrix_id"])
            self.assertEqual(result.scenario_digest, summary["scenario_digest"])
            self.assertEqual(2 * len(config.seeds), len(manifest["records"]))
            self.assertEqual(2 * len(config.seeds), len(raw_files))
            self.assertEqual(1, len(summary["summaries"]))

            with self.assertRaises(TypeError):
                save_latent_artifacts(directory, "not-a-result")

            # Append-only: identical content is a no-op.
            save_latent_artifacts(directory, result)

            # Result payload guard: empty records/comparisons are rejected.
            with self.assertRaises(ValueError):
                replace(result, records=())

            # A tampered result targeting the same matrix_id is refused.
            with self.assertRaises(ValueError):
                save_latent_artifacts(
                    directory, replace(result, scenario_digest="0" * 64)
                )

            # A corrupt existing artifact is refused, not overwritten.
            paths["manifest"].write_text("{corrupt", encoding="utf-8")
            with self.assertRaises(ValueError):
                save_latent_artifacts(directory, result)


if __name__ == "__main__":
    unittest.main()
