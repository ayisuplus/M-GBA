"""Extreme edge-case and crash-prevention tests for the neural layer variants.

Covers the shared pure-stdlib neural kernels (deterministic seeding,
fail-fast validation, saturation safety), the frozen-weight L0 MLP and
L3 GNN contract demonstrators (protocol conformance, determinism,
perturbation exactness, static-topology gate), the paired-comparison
matrix (determinism, single-layer-swap enforcement, budget), and the
frozen-baseline identity guard (default chain untouched).
"""

import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from mgba.layers import (
    CellAction,
    CellPhase,
    CellState,
    FeedbackConstraint,
    LocalEnvironment,
    StateMetadata,
)
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l0_neural import (
    NeuralGrnConfig,
    NeuralGrnModel,
    load_neural_grn_config,
)
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config
from mgba.layers.l2 import CellStateMachineModel, load_cell_config
from mgba.layers.l3 import TissueEnvironmentModel, load_tissue_config
from mgba.layers.l3_gnn import (
    GnnTissueConfig,
    GnnTissueModel,
    load_gnn_tissue_config,
)
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.models import Genome
from mgba.layers.contracts import RegulatoryInput
from mgba.multiscale import load_multiscale_scenario
from mgba.neural import mlp_forward, message_passing_step, seeded_matrix
from mgba.neural_experiments import (
    NeuralComparisonConfig,
    NeuralComparisonRunner,
    load_neural_comparison_config,
    save_neural_artifacts,
)
from mgba.runner import MultirateCrossScaleRunner, load_runner_config

ROOT = Path(__file__).parents[1]
LAYER_CONFIGS = ROOT / "configs" / "layers"

GENOME = Genome(
    version="test-genome-0.1",
    traits={
        "damage_response": 0.2,
        "signal_expression": 0.6,
        "repair_expression": 0.7,
        "metabolic_expression": 0.8,
        "death_expression": 0.1,
        "negative_feedback_expression": 0.3,
    },
)


class _TruncatedRunner:
    """Runner double whose run() violates the E0 tick-completeness contract."""

    def __init__(self, config, model_versions) -> None:
        self.config = config
        self.model_versions = model_versions

    def run(self, scenario, ticks):
        return SimpleNamespace(ticks=())


def _neural_grn_config(**overrides) -> NeuralGrnConfig:
    base = dict(
        model_version="test-neural-l0",
        weight_seed=20260820,
        hidden_dim=8,
        update_rate=0.35,
    )
    base.update(overrides)
    return NeuralGrnConfig(**base)


def _gnn_tissue_config(**overrides) -> GnnTissueConfig:
    base = dict(model_version="test-neural-l3", weight_seed=20260821)
    base.update(overrides)
    return GnnTissueConfig(**base)


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


class NeuralKernelTests(unittest.TestCase):
    def test_seeded_matrix_is_deterministic_and_seed_sensitive(self) -> None:
        first = seeded_matrix(42, "salt-a", 3, 4)
        self.assertEqual(first, seeded_matrix(42, "salt-a", 3, 4))
        self.assertNotEqual(first, seeded_matrix(43, "salt-a", 3, 4))
        self.assertNotEqual(first, seeded_matrix(42, "salt-b", 3, 4))
        bound = 1.0 / math.sqrt(4)
        for row in first:
            self.assertEqual(4, len(row))
            for value in row:
                self.assertLessEqual(abs(value), bound + 1e-18)
        self.assertEqual(3, len(first))

    def test_seeded_matrix_rejects_illegal_arguments(self) -> None:
        for rows, cols in ((0, 1), (1, 0), (-2, 3), (True, 2), (2, False)):
            with self.assertRaises((ValueError, TypeError), msg=(rows, cols)):
                seeded_matrix(1, "salt", rows, cols)
        with self.assertRaises(ValueError):
            seeded_matrix(1, "", 1, 1)
        with self.assertRaises(ValueError):
            seeded_matrix(1, "   ", 1, 1)
        with self.assertRaises(ValueError):
            seeded_matrix(-1, "salt", 1, 1)
        with self.assertRaises(TypeError):
            seeded_matrix(True, "salt", 1, 1)

    def test_mlp_forward_zero_weights_yield_constant_output(self) -> None:
        zero_hidden = ((0.0, 0.0), (0.0, 0.0), (0.0, 0.0))
        zero_output = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        result = mlp_forward(
            (0.9, 0.1), weights=(zero_hidden, zero_output), activation="tanh"
        )
        self.assertEqual((0.5, 0.5), result)

    def test_mlp_forward_rejects_non_finite_input_and_bad_activation(self) -> None:
        weights = (((1.0,),),)
        with self.assertRaises(ValueError):
            mlp_forward((math.nan,), weights=weights, activation="tanh")
        with self.assertRaises(ValueError):
            mlp_forward((math.inf,), weights=weights, activation="tanh")
        with self.assertRaises(ValueError):
            mlp_forward((0.5,), weights=weights, activation="relu")
        with self.assertRaises(ValueError):
            mlp_forward((0.5,), weights=(), activation="tanh")
        with self.assertRaises(ValueError):
            mlp_forward(
                (0.5, 0.5),
                weights=(((1.0, 1.0),), ((1.0, 1.0),)),
                activation="tanh",
            )

    def test_mlp_forward_saturates_without_overflow(self) -> None:
        huge = (((1e300, 1e300),),)
        result = mlp_forward((1.0, 1.0), weights=huge, activation="tanh")
        self.assertEqual((1.0,), result)
        neg = mlp_forward((-1.0, -1.0), weights=huge, activation="tanh")
        self.assertEqual((0.0,), neg)
        deep = mlp_forward(
            (1e300,),
            weights=(((1e300,), (1e300,)), ((1e300, 1e300),)),
            activation="tanh",
        )
        for value in deep:
            self.assertTrue(math.isfinite(value))
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_message_passing_means_zero_vector_and_validation(self) -> None:
        features = {
            "cell-a": (1.0, 3.0),
            "cell-b": (0.0, 1.0),
            "cell-c": (0.5, 0.5),
        }
        messages = message_passing_step(
            features, (("cell-a", "cell-b"), ("cell-c", "cell-b"))
        )
        self.assertEqual((0.0, 0.0), messages["cell-a"])
        self.assertEqual((0.75, 1.75), messages["cell-b"])
        with self.assertRaises(ValueError):
            message_passing_step(features, (("cell-a", "cell-a"),))
        with self.assertRaises(ValueError):
            message_passing_step(features, (("cell-a", "cell-z"),))
        with self.assertRaises(ValueError):
            message_passing_step(
                features,
                (("cell-a", "cell-b"), ("cell-a", "cell-b")),
            )
        with self.assertRaises(ValueError):
            message_passing_step(
                {"cell-a": (1.0,), "cell-b": (1.0, 2.0)}, ()
            )
        with self.assertRaises(ValueError):
            message_passing_step({"cell-a": (math.nan,)}, ())


class NeuralGrnModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = NeuralGrnModel(load_neural_grn_config(LAYER_CONFIGS / "l0_neural_grn.json"))
        self.regulatory = RegulatoryInput(damage_signal=0.4)

    def _step(self, model, previous=None, time=0, perturbations=None, cell_id="cell-1"):
        return model.step(
            cell_id=cell_id,
            genome=GENOME,
            previous_state=previous,
            regulatory_input=self.regulatory,
            perturbations=perturbations or {},
            logical_time=time,
        )

    def test_protocol_contract_same_cell_and_advancing_time(self) -> None:
        initial = self._step(self.model)
        follow_up = self._step(self.model, previous=initial.state, time=1)
        self.assertEqual("cell-1", follow_up.state.cell_id)
        with self.assertRaises(ValueError):
            self._step(self.model, previous=initial.state, time=1, cell_id="cell-2")
        with self.assertRaises(ValueError):
            self._step(self.model, previous=initial.state, time=0)
        with self.assertRaises(TypeError):
            self.model.step(
                cell_id="cell-1",
                genome=GENOME,
                previous_state=None,
                regulatory_input="not-a-regulatory-input",
                perturbations={},
                logical_time=0,
            )

    def test_determinism_across_instances(self) -> None:
        twin = NeuralGrnModel(
            load_neural_grn_config(LAYER_CONFIGS / "l0_neural_grn.json")
        )
        first = self._step(self.model)
        second = self._step(twin)
        self.assertEqual(first.state, second.state)
        chained_a = self._step(self.model, previous=first.state, time=1)
        chained_b = self._step(twin, previous=second.state, time=1)
        self.assertEqual(chained_a.state, chained_b.state)
        self.assertTrue(self.model.model_version.startswith("neural-l0-grn-0.1+"))

    def test_hidden_dim_one_and_extreme_inputs_do_not_crash(self) -> None:
        tiny = NeuralGrnModel(_neural_grn_config(hidden_dim=1))
        extreme_genome = Genome(
            version="test-genome-extreme",
            traits={
                "damage_response": 0.0,
                "signal_expression": 1.0,
                "repair_expression": 0.0,
                "metabolic_expression": 1.0,
                "death_expression": 0.0,
                "negative_feedback_expression": 1.0,
            },
        )
        state = tiny.step(
            cell_id="cell-x",
            genome=extreme_genome,
            previous_state=None,
            regulatory_input=RegulatoryInput(damage_signal=1.0),
            perturbations={},
            logical_time=0,
        ).state
        for gene in (
            "damage_response",
            "signal_expression",
            "repair_expression",
            "metabolic_expression",
            "death_expression",
            "negative_feedback_expression",
        ):
            value = getattr(state, gene)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_perturbation_clamp_stays_exact_after_mlp(self) -> None:
        initial = self._step(self.model)
        clamped = self._step(
            self.model,
            previous=initial.state,
            time=1,
            perturbations={"repair_expression": 0.0},
        )
        self.assertEqual(0.0, clamped.state.repair_expression)
        event = clamped.perturbation_events[0]
        self.assertEqual("repair_expression", event.gene)
        self.assertEqual(0.0, event.applied_value)
        self.assertGreater(event.unperturbed_value, 0.0)
        overexpressed = self._step(
            self.model,
            previous=initial.state,
            time=1,
            perturbations={"death_expression": 1.0},
        )
        self.assertEqual(1.0, overexpressed.state.death_expression)
        with self.assertRaises(ValueError):
            self._step(
                self.model,
                previous=initial.state,
                time=1,
                perturbations={"unknown_gene": 0.5},
            )

    def test_config_fail_fast_and_missing_file(self) -> None:
        for overrides in (
            {"model_version": " "},
            {"weight_seed": -1},
            {"weight_seed": True},
            {"hidden_dim": 0},
            {"hidden_dim": True},
            {"update_rate": 0.0},
            {"update_rate": 1.5},
            {"update_rate": math.nan},
        ):
            with self.assertRaises((ValueError, TypeError), msg=overrides):
                _neural_grn_config(**overrides)
        missing = LAYER_CONFIGS / "l0_neural_missing.json"
        self.assertFalse(missing.exists())
        with self.assertRaises(ValueError):
            load_neural_grn_config(missing)

    def test_model_rejects_foreign_config(self) -> None:
        with self.assertRaises(TypeError):
            NeuralGrnModel(load_grn_config(LAYER_CONFIGS / "l0_reference_grn.json"))


class GnnTissueModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = GnnTissueModel(
            load_gnn_tissue_config(LAYER_CONFIGS / "l3_gnn_tissue.json")
        )

    @staticmethod
    def _cell(
        cell_id: str,
        *,
        activation: float = 0.5,
        viability: float = 0.8,
        phase: CellPhase = CellPhase.ACTIVATED,
    ) -> CellState:
        return CellState(
            metadata=StateMetadata(1, "test-cell-0.1", f"state-{cell_id}"),
            cell_id=cell_id,
            phase=phase,
            activation=activation,
            viability=viability,
            stress_load=0.3,
        )

    @staticmethod
    def _action(
        cell_id: str,
        *,
        secretion: float = 0.2,
        consumption: float = 0.1,
        repair: float = 0.1,
        apoptosis: bool = False,
    ) -> CellAction:
        return CellAction(
            metadata=StateMetadata(1, "test-action-0.1", f"action-{cell_id}"),
            cell_id=cell_id,
            secretion=secretion,
            resource_consumption=consumption,
            repair_effort=repair,
            apoptosis=apoptosis,
        )

    @staticmethod
    def _environment(
        cell_id: str, *, stress: float = 0.2, resource: float = 0.8
    ) -> LocalEnvironment:
        return LocalEnvironment(
            metadata=StateMetadata(1, "test-environment-0.1", f"env-{cell_id}"),
            cell_id=cell_id,
            stress=stress,
            resource_level=resource,
            incoming_signal=0.0,
        )

    def _first_tick(self, model, cells=("c1", "c2", "c3")):
        edges = tuple(
            (cells[index], cells[(index + 1) % len(cells)])
            for index in range(len(cells))
        ) if len(cells) > 1 else ()
        return model.step(
            tuple(self._cell(cell_id) for cell_id in cells),
            tuple(self._action(cell_id) for cell_id in cells),
            initial_environments=tuple(
                self._environment(cell_id) for cell_id in cells
            ),
            previous_state=None,
            edges=edges,
            logical_time=1,
        )

    def test_determinism_and_static_topology_gate(self) -> None:
        twin = GnnTissueModel(
            load_gnn_tissue_config(LAYER_CONFIGS / "l3_gnn_tissue.json")
        )
        first = self._first_tick(self.model)
        self.assertEqual(first, self._first_tick(twin))
        follow_up = self.model.step(
            tuple(self._cell(cell_id) for cell_id in ("c1", "c2", "c3")),
            tuple(self._action(cell_id) for cell_id in ("c1", "c2", "c3")),
            initial_environments=None,
            previous_state=first,
            edges=first.edges,
            logical_time=2,
        )
        self.assertEqual(first.edges, follow_up.edges)
        with self.assertRaises(ValueError):
            self.model.step(
                tuple(self._cell(cell_id) for cell_id in ("c1", "c2", "c3")),
                tuple(self._action(cell_id) for cell_id in ("c1", "c2", "c3")),
                initial_environments=None,
                previous_state=first,
                edges=(("c1", "c2"),),
                logical_time=2,
            )

    def test_single_cell_and_all_dead_tissues_do_not_crash(self) -> None:
        solo = self._first_tick(self.model, cells=("solo",))
        self.assertEqual(1, solo.cell_count)
        self.assertEqual((), solo.edges)
        node = solo.nodes[0]
        for value in (node.stress, node.resource_level, node.signal):
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

        dead = self.model.step(
            (
                self._cell("d1", viability=0.0, phase=CellPhase.DEAD),
                self._cell("d2", viability=0.0, phase=CellPhase.DEAD),
            ),
            (self._action("d1"), self._action("d2", apoptosis=True)),
            initial_environments=(
                self._environment("d1", stress=1.0, resource=0.0),
                self._environment("d2", stress=1.0, resource=0.0),
            ),
            previous_state=None,
            edges=(("d1", "d2"),),
            logical_time=1,
        )
        self.assertEqual(1.0, dead.dead_fraction)
        self.assertGreater(dead.tissue_damage, 0.0)
        self.assertLessEqual(dead.tissue_damage, 1.0)

    def test_constraint_rejected_like_reference_model(self) -> None:
        first = self._first_tick(self.model)
        constraint = FeedbackConstraint.neutral(
            logical_time=1, model_version="test-feedback"
        )
        with self.assertRaises(ValueError):
            self.model.step(
                tuple(self._cell(cell_id) for cell_id in ("c1", "c2", "c3")),
                tuple(self._action(cell_id) for cell_id in ("c1", "c2", "c3")),
                initial_environments=None,
                previous_state=first,
                edges=first.edges,
                logical_time=2,
                constraint=constraint,
            )

    def test_config_fail_fast_and_missing_file(self) -> None:
        for overrides in (
            {"model_version": " "},
            {"weight_seed": -1},
            {"weight_seed": True},
            {"damage_stress_weight": 1.5},
            {"damage_stress_weight": math.nan},
            {"damage_stress_weight": 0.7, "damage_viability_weight": 0.2},
        ):
            with self.assertRaises((ValueError, TypeError), msg=overrides):
                _gnn_tissue_config(**overrides)
        missing = LAYER_CONFIGS / "l3_gnn_missing.json"
        self.assertFalse(missing.exists())
        with self.assertRaises(ValueError):
            load_gnn_tissue_config(missing)
        with self.assertRaises(TypeError):
            GnnTissueModel(load_tissue_config(LAYER_CONFIGS / "l3_reference_tissue.json"))

    def test_model_version_carries_config_digest(self) -> None:
        self.assertTrue(self.model.model_version.startswith("neural-l3-gnn-0.1+"))
        other = GnnTissueModel(_gnn_tissue_config(weight_seed=99))
        self.assertNotEqual(self.model.model_version, other.model_version)


class NeuralComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_demo.json"
        )
        self.runner_config = load_runner_config(
            ROOT / "configs" / "runner_reference.json"
        )
        self.config = NeuralComparisonConfig(
            model_version="test-neural-swap", ticks=5, seeds=(7, 42)
        )

    def _runner(self, changed_layer: str, config=None) -> NeuralComparisonRunner:
        baseline_models = _layer_models()
        neural_models = _layer_models()
        if changed_layer == "L0":
            neural_models["genome_model"] = NeuralGrnModel(
                load_neural_grn_config(LAYER_CONFIGS / "l0_neural_grn.json")
            )
        else:
            neural_models["tissue_model"] = GnnTissueModel(
                load_gnn_tissue_config(LAYER_CONFIGS / "l3_gnn_tissue.json")
            )
        return NeuralComparisonRunner(
            config or self.config,
            baseline_runner=MultirateCrossScaleRunner(
                self.runner_config, **baseline_models
            ),
            neural_runner=MultirateCrossScaleRunner(
                self.runner_config, **neural_models
            ),
            changed_layer=changed_layer,
        )

    def test_matrix_determinism_structure_and_tick_completeness(self) -> None:
        for changed_layer in ("L0", "L3"):
            matrix = self._runner(changed_layer).run(self.scenario)
            self.assertTrue(matrix.matrix_id.startswith("neural-"))
            self.assertEqual(changed_layer, matrix.changed_layer)
            self.assertEqual(2 * len(self.config.seeds), len(matrix.records))
            self.assertEqual(len(self.config.seeds), len(matrix.comparisons))
            for record in matrix.records:
                self.assertEqual(self.config.ticks, len(record.run.ticks))
            second = self._runner(changed_layer).run(self.scenario)
            self.assertEqual(matrix.matrix_id, second.matrix_id)
            self.assertEqual(
                [record.run.history_digest for record in matrix.records],
                [record.run.history_digest for record in second.records],
            )

    def test_wrong_layer_or_multi_layer_difference_rejected(self) -> None:
        baseline_models = _layer_models()
        drifted_l2 = _layer_models()
        drifted_l2["cell_model"] = CellStateMachineModel(
            replace(
                load_cell_config(LAYER_CONFIGS / "l2_reference_cell.json"),
                model_version="drifted-l2",
            )
        )
        with self.assertRaises(ValueError):
            NeuralComparisonRunner(
                self.config,
                baseline_runner=MultirateCrossScaleRunner(
                    self.runner_config, **baseline_models
                ),
                neural_runner=MultirateCrossScaleRunner(
                    self.runner_config, **drifted_l2
                ),
                changed_layer="L0",
            )
        two_layers = _layer_models()
        two_layers["genome_model"] = NeuralGrnModel(
            load_neural_grn_config(LAYER_CONFIGS / "l0_neural_grn.json")
        )
        two_layers["tissue_model"] = GnnTissueModel(
            load_gnn_tissue_config(LAYER_CONFIGS / "l3_gnn_tissue.json")
        )
        with self.assertRaises(ValueError):
            NeuralComparisonRunner(
                self.config,
                baseline_runner=MultirateCrossScaleRunner(
                    self.runner_config, **baseline_models
                ),
                neural_runner=MultirateCrossScaleRunner(
                    self.runner_config, **two_layers
                ),
                changed_layer="L0",
            )
        with self.assertRaises(ValueError):
            NeuralComparisonRunner(
                self.config,
                baseline_runner=MultirateCrossScaleRunner(
                    self.runner_config, **baseline_models
                ),
                neural_runner=MultirateCrossScaleRunner(
                    self.runner_config, **two_layers
                ),
                changed_layer="L2",
            )

    def test_budget_enforced(self) -> None:
        config = replace(self.config, ticks=self.runner_config.max_total_ticks + 1)
        with self.assertRaises(ValueError):
            self._runner("L3", config=config)

    def test_config_fail_fast_and_shipped_config_loads(self) -> None:
        with self.assertRaises(ValueError):
            NeuralComparisonConfig(model_version=" ", ticks=5, seeds=(7, 42))
        with self.assertRaises(ValueError):
            NeuralComparisonConfig(
                model_version="x", ticks=5, seeds=(42,)
            )
        with self.assertRaises(ValueError):
            NeuralComparisonConfig(model_version="x", ticks=5, seeds=(2, 1))
        shipped = load_neural_comparison_config(
            ROOT / "configs" / "experiments" / "neural_comparison.json"
        )
        self.assertGreaterEqual(len(shipped.seeds), 2)
        self.assertGreater(shipped.ticks, 0)

    def test_config_guards_cover_ticks_and_seed_sign(self) -> None:
        with self.assertRaises(ValueError):
            NeuralComparisonConfig(model_version="x", ticks=0, seeds=(7, 42))
        with self.assertRaises(ValueError):
            NeuralComparisonConfig(model_version="x", ticks=True, seeds=(7, 42))
        with self.assertRaises(ValueError):
            NeuralComparisonConfig(model_version="x", ticks=5, seeds=(-1, 42))

    def test_load_config_wraps_malformed_and_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_neural_comparison_config(path)
            missing = Path(directory) / "missing.json"
            self.assertFalse(missing.exists())
            with self.assertRaises(ValueError):
                load_neural_comparison_config(missing)

    def test_config_type_and_scenario_type_enforced(self) -> None:
        with self.assertRaises(TypeError):
            NeuralComparisonRunner(
                "not-a-config",
                baseline_runner=MultirateCrossScaleRunner(
                    self.runner_config, **_layer_models()
                ),
                neural_runner=MultirateCrossScaleRunner(
                    self.runner_config, **_layer_models()
                ),
                changed_layer="L0",
            )
        matrix = self._runner("L0")
        with self.assertRaises(TypeError):
            matrix.run(object())

    def test_truncated_trace_fails_closed(self) -> None:
        base_versions = {"L0": "rule", "L1": "v", "L2": "v", "L3": "v", "L4": "v"}
        neural_versions = dict(base_versions, L0="neural")
        matrix = NeuralComparisonRunner(
            replace(self.config, ticks=5),
            baseline_runner=_TruncatedRunner(self.runner_config, base_versions),
            neural_runner=_TruncatedRunner(self.runner_config, neural_versions),
            changed_layer="L0",
        )
        with self.assertRaises(RuntimeError):
            matrix.run(self.scenario)

    def test_model_version_property_tracks_config_digest(self) -> None:
        matrix = self._runner("L3")
        self.assertTrue(
            matrix.model_version.startswith(f"{self.config.model_version}+")
        )
        other = self._runner("L3", config=replace(self.config, ticks=3))
        self.assertNotEqual(matrix.model_version, other.model_version)

    def test_artifacts_persist_append_only_and_refuse_conflicts(self) -> None:
        config = replace(self.config, seeds=(1, 2), ticks=3)
        result = self._runner("L0", config=config).run(self.scenario)
        with tempfile.TemporaryDirectory() as directory:
            paths = save_neural_artifacts(directory, result)
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
            raw_files = tuple(paths["raw"].rglob("seed-*.json"))

            self.assertEqual("mgba-neural-artifact-0.1", manifest["schema_version"])
            self.assertEqual(result.matrix_id, manifest["matrix_id"])
            self.assertEqual("L0", manifest["changed_layer"])
            self.assertEqual("L0", summary["changed_layer"])
            self.assertEqual(2 * len(config.seeds), len(manifest["records"]))
            self.assertEqual(2 * len(config.seeds), len(raw_files))
            self.assertEqual(1, len(summary["summaries"]))

            with self.assertRaises(TypeError):
                save_neural_artifacts(directory, "not-a-result")

            # Append-only: identical content is a no-op.
            save_neural_artifacts(directory, result)

            # Result payload guards: unknown layer and empty payloads rejected.
            with self.assertRaises(ValueError):
                replace(result, changed_layer="L2")
            with self.assertRaises(ValueError):
                replace(result, records=())

            # A tampered result targeting the same matrix_id is refused.
            with self.assertRaises(ValueError):
                save_neural_artifacts(
                    directory, replace(result, scenario_digest="0" * 64)
                )

            # A corrupt existing artifact is refused, not overwritten.
            paths["manifest"].write_text("{corrupt", encoding="utf-8")
            with self.assertRaises(ValueError):
                save_neural_artifacts(directory, result)


class FrozenBaselineGuardTests(unittest.TestCase):
    def test_deterministic_100_tick_identity_unchanged(self) -> None:
        scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_demo.json"
        )
        runner = MultirateCrossScaleRunner(
            load_runner_config(ROOT / "configs" / "runner_reference.json"),
            **_layer_models(),
        )
        run = runner.run(scenario, ticks=100)
        self.assertEqual("mgba-e6a6d65dba732341", run.manifest.experiment_id)
        self.assertEqual(
            "7bd4d10044c420f5d4f18cb706765c673a6ca1930cccb1ddea5322abb1f336ff",
            run.history_digest,
        )
        self.assertEqual("failed", run.phenotype_window.outcome.value)


if __name__ == "__main__":
    unittest.main()
