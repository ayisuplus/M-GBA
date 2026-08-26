"""Extreme edge-case and crash-prevention tests for the L4→L3 feedback loop.

Covers the homeostatic controller math (dead-zone, anti-windup, safety
barrier), config fail-fast validation, constraint-aware L3 dynamics
(bitwise equivalence to the vanilla model without a constraint), runner
wiring (checkpoint replay determinism, malformed policy rejection), and
the frozen E4 matrix protocol.
"""

import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from mgba.feedback import (
    FeedbackControllerConfig,
    FixedConstraintPolicy,
    HomeostaticFeedbackController,
    load_feedback_config,
)
from mgba.feedback_experiments import (
    FeedbackExperimentConfig,
    FeedbackExperimentRunner,
    _dataclass_default,
    build_feedback_runners,
    load_feedback_experiment_config,
    save_feedback_artifacts,
)
from mgba.layers import (
    CellAction,
    CellPhase,
    CellState,
    FeedbackConstraint,
    LocalEnvironment,
    MolecularInput,
    OrganismState,
    RegulatoryInput,
    StateMetadata,
)
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config
from mgba.layers.l2 import CellStateMachineModel, load_cell_config
from mgba.layers.l3 import (
    ConstraintAwareTissueModel,
    StaticTissueModel,
    TissueEnvironmentModel,
    load_tissue_config,
)
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.multiscale import load_multiscale_scenario
from mgba.runner import MultirateCrossScaleRunner, load_runner_config


def _meta(time: int, version: str = "test-model-0.1") -> StateMetadata:
    return StateMetadata(
        logical_time=time, model_version=version, source_digest="test"
    )


def _organism(homeostasis: float, time: int = 10) -> OrganismState:
    return OrganismState(
        metadata=_meta(time),
        vitality=homeostasis,
        damage_burden=1.0 - homeostasis,
        inflammation=0.1,
        homeostasis=homeostasis,
        recovery_capacity=0.5,
    )


def _config(**overrides) -> FeedbackControllerConfig:
    base = dict(
        model_version="test-controller",
        setpoint=0.75,
        proportional_gain=0.4,
        integral_gain=0.1,
        back_calculation_gain=0.25,
        deadband=0.02,
        integral_bound=0.5,
        resource_ceiling_idle=1.0,
        resource_gain=0.4,
        resource_ceiling_min=0.3,
        stress_floor_idle=0.0,
        stress_gain=1.0,
        stress_floor_max=0.8,
        alarm_homeostasis=0.4,
    )
    base.update(overrides)
    return FeedbackControllerConfig(**base)


class _TruncatedRunner:
    """Runner double whose run() violates the E0 tick-completeness contract."""

    def __init__(self, config, model_versions) -> None:
        self.config = config
        self.model_versions = model_versions

    def run(self, scenario, ticks):
        return SimpleNamespace(ticks=())


class FeedbackControllerMathTests(unittest.TestCase):
    def test_error_and_pi_values_match_closed_form(self) -> None:
        controller = HomeostaticFeedbackController(_config())
        constraint = controller.observe(_organism(0.5), logical_time=10)
        self.assertAlmostEqual(constraint.error, 0.25)
        # u = Kp*e + I = 0.1; r = 1 - 0.4*0.1 = 0.96; I' = 0 + 0.1*0.25 = 0.025
        self.assertAlmostEqual(constraint.resource_ceiling, 0.96)
        self.assertAlmostEqual(constraint.integral, 0.025)
        self.assertFalse(constraint.saturated)
        # Safety barrier active: 0.4 - 0.5 < 0 -> floor stays idle.
        self.assertAlmostEqual(constraint.stress_floor, 0.0)

    def test_deadband_suppresses_small_error_and_anti_windup_clamps(self) -> None:
        controller = HomeostaticFeedbackController(
            _config(proportional_gain=1.0, integral_gain=1.0)
        )
        tiny = controller.observe(_organism(0.745), logical_time=10)
        self.assertEqual(0.0, tiny.error)
        self.assertEqual(0.0, tiny.integral)
        huge = controller.observe(_organism(0.0), logical_time=20)
        self.assertAlmostEqual(huge.error, 0.75)
        self.assertAlmostEqual(huge.integral, 0.5)  # clipped at I_max
        saturated = controller.observe(_organism(0.0), logical_time=30)
        self.assertTrue(saturated.saturated)
        # u saturates at 1.0, so r = r0 - gamma_r*1 = 1 - 0.4 = 0.6.
        self.assertAlmostEqual(saturated.resource_ceiling, 0.6)
        self.assertAlmostEqual(saturated.integral, 0.5)  # clipped at I_max
        self.assertAlmostEqual(saturated.stress_floor, 0.4)  # min(0.8, 0.4)

    def test_safety_barrier_is_monotone_and_bounded(self) -> None:
        controller = HomeostaticFeedbackController(
            _config(stress_floor_idle=0.1, stress_gain=0.5)
        )
        floors = []
        for index, homeostasis in enumerate((0.39, 0.2, 0.1, 0.0), start=1):
            constraint = controller.observe(
                _organism(homeostasis), logical_time=index * 10
            )
            floors.append(constraint.stress_floor)
        self.assertEqual(floors, sorted(floors))
        for floor in floors:
            self.assertLessEqual(floor, 0.8)

    def test_time_regression_and_type_violations_raise(self) -> None:
        controller = HomeostaticFeedbackController(_config())
        controller.observe(_organism(0.5), logical_time=10)
        with self.assertRaises(ValueError):
            controller.observe(_organism(0.5), logical_time=10)
        with self.assertRaises(ValueError):
            controller.observe(_organism(0.5), logical_time=5)
        with self.assertRaises(TypeError):
            controller.observe("not-an-organism", logical_time=20)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            controller.observe(_organism(0.5), logical_time=True)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            controller.observe(_organism(0.5), logical_time=0)

    def test_reset_restores_pristine_state(self) -> None:
        controller = HomeostaticFeedbackController(_config())
        first = controller.observe(_organism(0.5), logical_time=10)
        controller.reset()
        again = controller.observe(_organism(0.5), logical_time=10)
        self.assertEqual(first, again)


class FeedbackConfigCrashPreventionTests(unittest.TestCase):
    def test_illegal_numeric_parameters_fail_fast(self) -> None:
        for field, value in (
            ("setpoint", 0.0),
            ("setpoint", 1.0),
            ("proportional_gain", math.inf),
            ("integral_gain", math.nan),
            ("deadband", 1.0),
            ("integral_bound", -0.1),
            ("resource_ceiling_idle", 0.0),
            ("resource_ceiling_min", 1.2),
            ("stress_gain", 1.5),
            ("stress_floor_idle", -0.2),
        ):
            with self.assertRaises(ValueError, msg=f"{field}={value}"):
                _config(**{field: value})
        # Relational guards.
        with self.assertRaises(ValueError):
            _config(resource_ceiling_min=1.0, resource_ceiling_idle=0.9)
        with self.assertRaises(ValueError):
            _config(alarm_homeostasis=0.75)
        with self.assertRaises(ValueError):
            _config(stress_floor_max=0.05, stress_floor_idle=0.1)

    def test_constraint_dto_rejects_non_finite_and_wrong_types(self) -> None:
        with self.assertRaises(ValueError):
            FeedbackConstraint(
                metadata=_meta(1),
                resource_ceiling=math.nan,
                stress_floor=0.0,
                error=0.0,
                integral=0.0,
                saturated=False,
            )
        with self.assertRaises(ValueError):
            FeedbackConstraint(
                metadata=_meta(1),
                resource_ceiling=1.0,
                stress_floor=0.0,
                error=1.5,
                integral=0.0,
                saturated=False,
            )
        with self.assertRaises(TypeError):
            FeedbackConstraint(
                metadata=_meta(1),
                resource_ceiling=1.0,
                stress_floor=0.0,
                error=0.0,
                integral=0.0,
                saturated="yes",  # type: ignore[arg-type]
            )

    def test_fixed_policy_extreme_bounds_accepted_and_garbage_rejected(self) -> None:
        policy = FixedConstraintPolicy(resource_ceiling=1.0, stress_floor=0.0)
        constraint = policy.observe(_organism(0.5), logical_time=1)
        self.assertEqual(1.0, constraint.resource_ceiling)
        self.assertEqual(0.0, constraint.stress_floor)
        with self.assertRaises(ValueError):
            FixedConstraintPolicy(resource_ceiling=0.0, stress_floor=0.0)
        with self.assertRaises(ValueError):
            FixedConstraintPolicy(resource_ceiling=1.0, stress_floor=1.0)

    def test_shipped_configs_load_and_validate(self) -> None:
        root = Path(__file__).parents[1]
        config = load_feedback_config(
            root / "configs" / "layers" / "l4_feedback_controller.json"
        )
        self.assertLess(config.alarm_homeostasis, config.setpoint)
        e4 = load_feedback_experiment_config(
            root / "configs" / "experiments" / "e4_feedback.json"
        )
        self.assertGreaterEqual(len(e4.seeds), 2)
        with self.assertRaises(ValueError):
            FeedbackExperimentConfig(
                model_version="bad",
                ticks=0,
                seeds=(1,),
                fixed_resource_ceiling=0.7,
                fixed_stress_floor=0.3,
            )


class FeedbackTissueModelTests(unittest.TestCase):
    """L3 constraint-aware dynamics and byte-equivalence with the baseline."""

    def setUp(self) -> None:
        root = Path(__file__).parents[1]
        layer_configs = root / "configs" / "layers"
        self.scenario = load_multiscale_scenario(
            root / "configs" / "multiscale_demo.json"
        )
        self.tissue_config = load_tissue_config(
            layer_configs / "l3_reference_tissue.json"
        )
        self.cell_model = CellStateMachineModel(
            load_cell_config(layer_configs / "l2_reference_cell.json")
        )
        self.edges = self.scenario.edges
        self.cell_states, self.cell_actions, self.environments = self._seed_l2()

    def _seed_l2(self):
        molecular_model = CoarseMolecularModel(
            load_molecular_config(
                Path(__file__).parents[1]
                / "configs"
                / "layers"
                / "l1_reference_molecular.json"
            )
        )
        genome_model = DiscreteGrnModel(
            load_grn_config(
                Path(__file__).parents[1]
                / "configs"
                / "layers"
                / "l0_reference_grn.json"
            )
        )
        l0 = {}
        l1 = {}
        regulatory = RegulatoryInput(
            damage_signal=self.scenario.environment_stress
        )
        for cell_id, genome in sorted(self.scenario.genomes):
            result = genome_model.step(
                cell_id=cell_id,
                genome=genome,
                previous_state=None,
                regulatory_input=regulatory,
                perturbations={},
                logical_time=1,
            )
            l0[cell_id] = result.state
            l1[cell_id] = molecular_model.step(
                result.state,
                previous_state=None,
                molecular_input=MolecularInput(
                    metadata=_meta(1, "l2-to-l1-activation-boundary-0.2"),
                    cell_id=cell_id,
                    local_signal=0.0,
                ),
                logical_time=1,
            )
        environments = tuple(
            LocalEnvironment(
                metadata=_meta(1, "scenario-boundary-0.1"),
                cell_id=cell_id,
                stress=self.scenario.environment_stress,
                resource_level=self.scenario.resource_level,
                incoming_signal=self.scenario.incoming_signal,
            )
            for cell_id, _ in sorted(self.scenario.genomes)
        )
        states = []
        actions = []
        for cell_id, _ in sorted(self.scenario.genomes):
            state, action = self.cell_model.step(
                l1[cell_id],
                environments[[e.cell_id for e in environments].index(cell_id)],
                previous_state=None,
                logical_time=1,
            )
            states.append(state)
            actions.append(action)
        return tuple(states), tuple(actions), environments

    def _neutral(self, time: int = 1) -> FeedbackConstraint:
        return FeedbackConstraint.neutral(
            logical_time=time, model_version="neutral-test"
        )

    def test_without_constraint_dynamics_match_vanilla_model(self) -> None:
        vanilla = TissueEnvironmentModel(self.tissue_config)
        aware = ConstraintAwareTissueModel(self.tissue_config)
        base = vanilla.step(
            self.cell_states,
            self.cell_actions,
            initial_environments=self.environments,
            previous_state=None,
            edges=self.edges,
            logical_time=1,
        )
        aware_state = aware.step(
            self.cell_states,
            self.cell_actions,
            initial_environments=self.environments,
            previous_state=None,
            edges=self.edges,
            logical_time=1,
        )
        # The two models have distinct identities (different model_version),
        # but without a constraint the dynamics must agree field-by-field.
        for field in (
            "cell_count",
            "nodes",
            "edges",
            "edge_density",
            "mean_activation",
            "mean_viability",
            "mean_resource",
            "mean_signal",
            "dead_fraction",
            "repair_activity",
            "coordinated_signal",
            "tissue_damage",
        ):
            self.assertEqual(getattr(base, field), getattr(aware_state, field), field)
        self.assertNotEqual(
            base.metadata.model_version, aware_state.metadata.model_version
        )

    def test_neutral_constraint_equals_vanilla_step(self) -> None:
        vanilla = TissueEnvironmentModel(self.tissue_config)
        aware = ConstraintAwareTissueModel(self.tissue_config)
        base = vanilla.step(
            self.cell_states,
            self.cell_actions,
            initial_environments=self.environments,
            previous_state=None,
            edges=self.edges,
            logical_time=1,
        )
        neutral = aware.step(
            self.cell_states,
            self.cell_actions,
            initial_environments=self.environments,
            previous_state=None,
            edges=self.edges,
            logical_time=1,
            constraint=self._neutral(),
        )
        self.assertEqual(base.nodes, neutral.nodes)
        self.assertEqual(base.tissue_damage, neutral.tissue_damage)

    def test_resource_ceiling_caps_recovery(self) -> None:
        aware = ConstraintAwareTissueModel(self.tissue_config)
        starving = replace(self.environments[0], resource_level=0.1)
        environments = tuple(
            starving if env.cell_id == starving.cell_id else env
            for env in self.environments
        )
        actions = tuple(
            replace(action, resource_consumption=0.0)
            for action in self.cell_actions
        )
        capped = FeedbackConstraint(
            metadata=_meta(1),
            resource_ceiling=0.4,
            stress_floor=0.0,
            error=0.0,
            integral=0.0,
            saturated=False,
        )
        state = aware.step(
            self.cell_states,
            actions,
            initial_environments=environments,
            previous_state=None,
            edges=self.edges,
            logical_time=1,
            constraint=capped,
        )
        target_cell = starving.cell_id
        node = next(node for node in state.nodes if node.cell_id == target_cell)
        expected = 0.1 + self.tissue_config.resource_recovery * (0.4 - 0.1)
        self.assertAlmostEqual(node.resource_level, expected)
        self.assertLessEqual(node.resource_level, 0.4)

    def test_stress_floor_lifts_monotone_and_zero_floor_is_identity(self) -> None:
        aware = ConstraintAwareTissueModel(self.tissue_config)
        vanilla = TissueEnvironmentModel(self.tissue_config)
        base = vanilla.step(
            self.cell_states,
            self.cell_actions,
            initial_environments=self.environments,
            previous_state=None,
            edges=self.edges,
            logical_time=1,
        )
        lifted = aware.step(
            self.cell_states,
            self.cell_actions,
            initial_environments=self.environments,
            previous_state=None,
            edges=self.edges,
            logical_time=1,
            constraint=FeedbackConstraint(
                metadata=_meta(1),
                resource_ceiling=1.0,
                stress_floor=0.9,
                error=0.0,
                integral=0.0,
                saturated=False,
            ),
        )
        for base_node, lifted_node in zip(base.nodes, lifted.nodes, strict=True):
            self.assertGreaterEqual(lifted_node.stress, base_node.stress - 1e-12)
        self.assertGreater(
            max(node.stress for node in lifted.nodes),
            max(node.stress for node in base.nodes),
        )

    def test_coupling_zero_disables_stress_floor(self) -> None:
        aware = ConstraintAwareTissueModel(
            self.tissue_config, stress_floor_coupling=0.0
        )
        vanilla = TissueEnvironmentModel(self.tissue_config)
        base = vanilla.step(
            self.cell_states,
            self.cell_actions,
            initial_environments=self.environments,
            previous_state=None,
            edges=self.edges,
            logical_time=1,
        )
        decoupled = aware.step(
            self.cell_states,
            self.cell_actions,
            initial_environments=self.environments,
            previous_state=None,
            edges=self.edges,
            logical_time=1,
            constraint=FeedbackConstraint(
                metadata=_meta(1),
                resource_ceiling=1.0,
                stress_floor=0.9,
                error=0.0,
                integral=0.0,
                saturated=False,
            ),
        )
        self.assertEqual(base.nodes, decoupled.nodes)

    def test_legacy_models_reject_constraints_loudly(self) -> None:
        constraint = self._neutral()
        for model in (
            StaticTissueModel(),
            TissueEnvironmentModel(self.tissue_config),
        ):
            with self.assertRaises(ValueError):
                model.step(
                    self.cell_states,
                    self.cell_actions,
                    initial_environments=self.environments,
                    previous_state=None,
                    edges=self.edges,
                    logical_time=1,
                    constraint=constraint,
                )

    def test_future_or_mistyped_constraint_rejected(self) -> None:
        aware = ConstraintAwareTissueModel(self.tissue_config)
        with self.assertRaises(ValueError):
            aware.step(
                self.cell_states,
                self.cell_actions,
                initial_environments=self.environments,
                previous_state=None,
                edges=self.edges,
                logical_time=1,
                constraint=FeedbackConstraint(
                    metadata=_meta(5),
                    resource_ceiling=1.0,
                    stress_floor=0.0,
                    error=0.0,
                    integral=0.0,
                    saturated=False,
                ),
            )
        with self.assertRaises(TypeError):
            aware.step(
                self.cell_states,
                self.cell_actions,
                initial_environments=self.environments,
                previous_state=None,
                edges=self.edges,
                logical_time=1,
                constraint={"resource_ceiling": 1.0},  # type: ignore[arg-type]
            )
        with self.assertRaises(ValueError):
            ConstraintAwareTissueModel(
                self.tissue_config, stress_floor_coupling=1.5
            )


class RunnerFeedbackWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).parents[1]
        layer_configs = self.root / "configs" / "layers"
        self.scenario = load_multiscale_scenario(
            self.root / "configs" / "multiscale_demo.json"
        )
        self.runner_config = load_runner_config(
            self.root / "configs" / "runner_reference.json"
        )
        self.layer_models = dict(
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
                load_phenotype_config(layer_configs / "l4_reference_phenotype.json")
            ),
        )
        self.feedback_config = load_feedback_config(
            self.root / "configs" / "layers" / "l4_feedback_controller.json"
        )

    def _runners(self):
        return build_feedback_runners(
            layer_models=self.layer_models,
            runner_config=self.runner_config,
            feedback_config=self.feedback_config,
            fixed_resource_ceiling=0.7,
            fixed_stress_floor=0.3,
        )

    def test_state_feedback_changes_trajectory_and_is_traceable(self) -> None:
        runners = self._runners()
        base = runners["no_feedback"].run(self.scenario, ticks=30)
        with_feedback = runners["state_feedback"].run(self.scenario, ticks=30)
        self.assertNotEqual(base.history_digest, with_feedback.history_digest)
        constrained = [
            tick
            for tick in with_feedback.ticks
            if "constraint" in tick.l3.metadata.source_digest
            or tick.l3.metadata.source_digest != base.ticks[0].l3.metadata.source_digest
        ]
        self.assertTrue(constrained)
        # Constraints only take effect after the first L4 observation (t=1);
        # the tick-1 tissue state precedes any constraint application beyond
        # the observation at the same tick, and both runs share tick 1 L0/L1.
        self.assertEqual(base.ticks[0].l0, with_feedback.ticks[0].l0)

    def test_checkpoint_replay_reproduces_feedback_state(self) -> None:
        runner = self._runners()["state_feedback"]
        full = runner.run(self.scenario, ticks=30)
        part1 = runner.run(self.scenario, ticks=13)
        part2 = runner.run(self.scenario, ticks=17, checkpoint=part1.checkpoint)
        self.assertEqual(full.history_digest, part2.history_digest)
        self.assertEqual(full.checkpoint, part2.checkpoint)
        self.assertEqual(full.terminal_observation, part2.terminal_observation)
        self.assertEqual(full.phenotype_window, part2.phenotype_window)

    def test_policy_is_reused_across_runs_via_reset(self) -> None:
        runner = self._runners()["state_feedback"]
        first = runner.run(self.scenario, ticks=20)
        second = runner.run(self.scenario, ticks=20)
        self.assertEqual(first.history_digest, second.history_digest)

    def test_malformed_feedback_policy_rejected_at_construction(self) -> None:
        tissue_models = dict(self.layer_models)
        tissue_models["tissue_model"] = ConstraintAwareTissueModel(
            self.layer_models["tissue_model"].config
        )
        with self.assertRaises(TypeError):
            MultirateCrossScaleRunner(
                self.runner_config, **tissue_models, feedback_policy=object()
            )
        with self.assertRaises(TypeError):
            MultirateCrossScaleRunner(
                self.runner_config, **tissue_models, feedback_policy=42
            )

    def test_no_feedback_runner_identity_matches_vanilla_baseline(self) -> None:
        runners = self._runners()
        vanilla = MultirateCrossScaleRunner(
            self.runner_config, **self.layer_models
        )
        base = vanilla.run(self.scenario, ticks=30)
        no_feedback = runners["no_feedback"].run(self.scenario, ticks=30)
        self.assertEqual(base.manifest.experiment_id, no_feedback.manifest.experiment_id)
        self.assertEqual(base.history_digest, no_feedback.history_digest)


class E4FeedbackMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).parents[1]
        self.scenario = load_multiscale_scenario(
            self.root / "configs" / "multiscale_demo.json"
        )
        self.config = load_feedback_experiment_config(
            self.root / "configs" / "experiments" / "e4_feedback.json"
        )
        self.feedback_config = load_feedback_config(
            self.root / "configs" / "layers" / "l4_feedback_controller.json"
        )
        layer_configs = self.root / "configs" / "layers"
        self.layer_models = dict(
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
                load_phenotype_config(layer_configs / "l4_reference_phenotype.json")
            ),
        )

    def test_e4_matrix_structure_and_determinism(self) -> None:
        runners = build_feedback_runners(
            layer_models=self.layer_models,
            runner_config=load_runner_config(
                self.root / "configs" / "runner_reference.json"
            ),
            feedback_config=self.feedback_config,
            fixed_resource_ceiling=self.config.fixed_resource_ceiling,
            fixed_stress_floor=self.config.fixed_stress_floor,
        )
        matrix = FeedbackExperimentRunner(self.config, runners=runners).run(
            self.scenario
        )
        self.assertEqual(3 * len(self.config.seeds), len(matrix.records))
        self.assertEqual(2 * len(self.config.seeds), len(matrix.comparisons))
        self.assertEqual(2, len(matrix.summaries))
        self.assertTrue(matrix.matrix_id.startswith("feedback-"))
        second = FeedbackExperimentRunner(self.config, runners=runners).run(
            self.scenario
        )
        self.assertEqual(matrix.matrix_id, second.matrix_id)
        self.assertEqual(
            [record.run.history_digest for record in matrix.records],
            [record.run.history_digest for record in second.records],
        )

    def test_runner_budget_enforced(self) -> None:
        runners = build_feedback_runners(
            layer_models=self.layer_models,
            runner_config=replace(
                load_runner_config(self.root / "configs" / "runner_reference.json"),
                max_total_ticks=5,
            ),
            feedback_config=self.feedback_config,
            fixed_resource_ceiling=0.7,
            fixed_stress_floor=0.3,
        )
        config = replace(self.config, ticks=30)
        with self.assertRaises(ValueError):
            FeedbackExperimentRunner(config, runners=runners)

    def _build_runners(self):
        return build_feedback_runners(
            layer_models=self.layer_models,
            runner_config=load_runner_config(
                self.root / "configs" / "runner_reference.json"
            ),
            feedback_config=self.feedback_config,
            fixed_resource_ceiling=self.config.fixed_resource_ceiling,
            fixed_stress_floor=self.config.fixed_stress_floor,
        )

    def test_runner_set_and_scenario_type_enforced(self) -> None:
        runners = self._build_runners()
        runners.pop("state_feedback")
        with self.assertRaises(ValueError):
            FeedbackExperimentRunner(self.config, runners=runners)
        matrix = FeedbackExperimentRunner(self.config, runners=self._build_runners())
        with self.assertRaises(TypeError):
            matrix.run(object())

    def test_truncated_trace_fails_closed(self) -> None:
        runner_config = load_runner_config(
            self.root / "configs" / "runner_reference.json"
        )
        versions = dict(self._build_runners()["no_feedback"].model_versions)
        stubs = {
            condition: _TruncatedRunner(runner_config, versions)
            for condition in ("no_feedback", "fixed_feedback", "state_feedback")
        }
        matrix = FeedbackExperimentRunner(
            replace(self.config, ticks=5), runners=stubs
        )
        with self.assertRaises(RuntimeError):
            matrix.run(self.scenario)

    def test_model_version_property_tracks_config_digest(self) -> None:
        matrix = FeedbackExperimentRunner(self.config, runners=self._build_runners())
        self.assertTrue(
            matrix.model_version.startswith(f"{self.config.model_version}+")
        )
        other = FeedbackExperimentRunner(
            replace(self.config, ticks=5), runners=self._build_runners()
        )
        self.assertNotEqual(matrix.model_version, other.model_version)

    def test_dataclass_default_serializes_dataclasses_and_rejects_garbage(self) -> None:
        payload = _dataclass_default(self.config)
        self.assertEqual(self.config.ticks, payload["ticks"])
        self.assertEqual(tuple(self.config.seeds), tuple(payload["seeds"]))
        with self.assertRaises(TypeError):
            _dataclass_default(object())

    def test_experiment_config_guards_fail_closed(self) -> None:
        cases = (
            {"model_version": "  "},
            {"ticks": 0},
            {"ticks": True},
            {"seeds": (42,)},
            {"seeds": (2, 1)},
            {"seeds": (1, 1)},
            {"seeds": (-1, 2)},
            {"fixed_resource_ceiling": 0.0},
            {"fixed_resource_ceiling": 1.5},
            {"fixed_stress_floor": -0.1},
            {"fixed_stress_floor": 1.0},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    replace(self.config, **overrides)

    def test_load_config_wraps_malformed_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_feedback_experiment_config(path)
            path.write_text(json.dumps({"model_version": "x"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_feedback_experiment_config(path)

    def test_build_runners_requires_all_five_layer_models(self) -> None:
        models = dict(self.layer_models)
        models.pop("genome_model")
        with self.assertRaises(ValueError):
            build_feedback_runners(
                layer_models=models,
                runner_config=load_runner_config(
                    self.root / "configs" / "runner_reference.json"
                ),
                feedback_config=self.feedback_config,
                fixed_resource_ceiling=0.7,
                fixed_stress_floor=0.3,
            )

    def test_artifacts_persist_append_only_and_refuse_conflicts(self) -> None:
        config = replace(self.config, seeds=(1, 2), ticks=3)
        result = FeedbackExperimentRunner(
            config, runners=self._build_runners()
        ).run(self.scenario)
        with tempfile.TemporaryDirectory() as directory:
            paths = save_feedback_artifacts(directory, result)
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
            raw_files = tuple(paths["raw"].rglob("seed-*.json"))

            self.assertEqual("mgba-feedback-artifact-0.1", manifest["schema_version"])
            self.assertEqual(result.matrix_id, manifest["matrix_id"])
            self.assertEqual(result.scenario_digest, manifest["scenario_digest"])
            self.assertEqual(result.matrix_id, summary["matrix_id"])
            self.assertEqual(3 * len(config.seeds), len(manifest["records"]))
            self.assertEqual(3 * len(config.seeds), len(raw_files))
            self.assertEqual(2, len(summary["summaries"]))

            with self.assertRaises(TypeError):
                save_feedback_artifacts(directory, "not-a-result")

            # Append-only: identical content is a no-op.
            save_feedback_artifacts(directory, result)

            # Result payload guard: empty records/comparisons are rejected.
            with self.assertRaises(ValueError):
                replace(result, records=())

            # A tampered result targeting the same matrix_id is refused.
            with self.assertRaises(ValueError):
                save_feedback_artifacts(
                    directory, replace(result, scenario_digest="0" * 64)
                )

            # A corrupt existing artifact is refused, not overwritten.
            paths["manifest"].write_text("{corrupt", encoding="utf-8")
            with self.assertRaises(ValueError):
                save_feedback_artifacts(directory, result)


if __name__ == "__main__":
    unittest.main()
