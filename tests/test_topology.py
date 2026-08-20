"""Extreme edge-case and crash-prevention tests for the adaptive L3 topology.

Covers governance fail-fast config validation, degenerate topologies
(single cell, no in-neighbors, all-dead tissue), budget and degree-cap
enforcement, T1 edge-count conservation, determinism, identity/time
contract violations, and static-vs-adaptive paired-matrix invariants.
"""

import math
import unittest
from dataclasses import replace
from pathlib import Path

from mgba.layers import CellPhase
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config
from mgba.layers.l2 import CellStateMachineModel, load_cell_config
from mgba.layers.l3 import TissueEnvironmentModel, load_tissue_config
from mgba.layers.l3_adaptive import (
    AdaptiveTopologyConfig,
    DynamicTopologyTissueModel,
    load_adaptive_topology_config,
)
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.multiscale import MultiscaleScenario, load_multiscale_scenario
from mgba.models import Genome
from mgba.runner import MultirateCrossScaleRunner, load_runner_config
from mgba.topology_experiments import (
    TopologyExperimentRunner,
    load_topology_experiment_config,
)

ROOT = Path(__file__).parents[1]
LAYER_CONFIGS = ROOT / "configs" / "layers"


def _governance(**overrides) -> AdaptiveTopologyConfig:
    values = dict(
        model_version="test-adaptive-topology",
        max_swaps_per_tick=2,
        exchange_gain_threshold=0.05,
        max_out_degree=4,
    )
    values.update(overrides)
    return AdaptiveTopologyConfig(**values)


def _adaptive_model(**overrides) -> DynamicTopologyTissueModel:
    return DynamicTopologyTissueModel(
        load_tissue_config(LAYER_CONFIGS / "l3_reference_tissue.json"),
        _governance(**overrides),
    )


def _scenario(cell_count: int, stress: float = 0.35) -> MultiscaleScenario:
    genome = Genome(
        version="abstract-genome-0.2",
        traits={
            "damage_response": 0.2,
            "signal_expression": 0.8,
            "repair_expression": 0.7,
            "metabolic_expression": 0.8,
            "death_expression": 0.1,
            "negative_feedback_expression": 0.2,
        },
    )
    genomes = tuple((f"cell-{index:03d}", genome) for index in range(cell_count))
    ids = [cell_id for cell_id, _ in genomes]
    edges = tuple(
        (ids[index], ids[(index + 1) % cell_count]) for index in range(cell_count)
    ) if cell_count > 1 else ()
    return MultiscaleScenario(
        seed=42,
        environment_stress=stress,
        resource_level=1.0,
        incoming_signal=0.0,
        genomes=genomes,
        edges=edges,
    )


def _layer_models(tissue_model) -> dict:
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
        "tissue_model": tissue_model,
        "phenotype_model": PhenotypeObserverModel(
            load_phenotype_config(LAYER_CONFIGS / "l4_reference_phenotype.json")
        ),
    }


def _runner(tissue_model) -> MultirateCrossScaleRunner:
    return MultirateCrossScaleRunner(
        load_runner_config(ROOT / "configs" / "runner_reference.json"),
        **_layer_models(tissue_model),
    )


class AdaptiveTopologyConfigCrashPreventionTests(unittest.TestCase):
    def test_illegal_governance_parameters_fail_fast(self) -> None:
        cases = (
            ("max_swaps_per_tick", -1),
            ("max_swaps_per_tick", True),
            ("max_out_degree", 0),
            ("max_out_degree", -3),
            ("exchange_gain_threshold", math.nan),
            ("exchange_gain_threshold", math.inf),
            ("exchange_gain_threshold", 1.5),
            ("model_version", "   "),
        )
        for field, value in cases:
            with self.assertRaises(ValueError, msg=f"{field}={value}"):
                _governance(**{field: value})

    def test_missing_config_file_raises_value_error(self) -> None:
        missing = ROOT / "configs" / "layers" / "l3_adaptive_missing.json"
        self.assertFalse(missing.exists())
        with self.assertRaises(ValueError):
            load_adaptive_topology_config(missing)

    def test_constructor_type_guards(self) -> None:
        tissue_config = load_tissue_config(
            LAYER_CONFIGS / "l3_reference_tissue.json"
        )
        with self.assertRaises(TypeError):
            DynamicTopologyTissueModel(object(), _governance())
        with self.assertRaises(TypeError):
            DynamicTopologyTissueModel(tissue_config, object())
        with self.assertRaises(ValueError):
            DynamicTopologyTissueModel(
                tissue_config, _governance(), stress_floor_coupling=2.0
            )


class AdaptiveTopologyEdgeCaseTests(unittest.TestCase):
    def test_single_cell_scenario_does_not_crash(self) -> None:
        runner = _runner(_adaptive_model())
        run = runner.run(_scenario(1), ticks=5)
        self.assertEqual(0, len(run.ticks[-1].l3.edges))

    def test_zero_budget_never_swaps(self) -> None:
        runner = _runner(_adaptive_model(max_swaps_per_tick=0, exchange_gain_threshold=-1.0))
        run = runner.run(_scenario(4), ticks=20)
        edges_sequence = [tuple(sorted(tick.l3.edges)) for tick in run.ticks]
        self.assertEqual(1, len(set(edges_sequence)))

    def test_budget_one_caps_parallel_proposals(self) -> None:
        permissive = _adaptive_model(max_swaps_per_tick=1, exchange_gain_threshold=-1.0)
        capped = _adaptive_model(max_swaps_per_tick=4, exchange_gain_threshold=-1.0)
        scenario = _scenario(6)
        run_capped = _runner(capped).run(scenario, ticks=10)
        run_limited = _runner(permissive).run(scenario, ticks=10)
        # With budget 1 at most one edge pair may change per tick.
        for previous, current in zip(run_limited.ticks, run_limited.ticks[1:]):
            removed = set(previous.l3.edges) - set(current.l3.edges)
            added = set(current.l3.edges) - set(previous.l3.edges)
            self.assertLessEqual(len(removed), 1)
            self.assertLessEqual(len(added), 1)

    def test_edge_count_conserved_through_swaps(self) -> None:
        runner = _runner(_adaptive_model(exchange_gain_threshold=-1.0))
        run = runner.run(_scenario(5), ticks=15)
        initial = len(run.ticks[0].l3.edges)
        for tick in run.ticks:
            self.assertEqual(initial, len(tick.l3.edges))
            edges = tick.l3.edges
            self.assertEqual(len(edges), len(set(edges)))
            for source, target in edges:
                self.assertNotEqual(source, target)

    def test_in_degree_conserved_by_t1_exchanges(self) -> None:
        runner = _runner(_adaptive_model(exchange_gain_threshold=-1.0))
        scenario = _scenario(5)
        run = runner.run(scenario, ticks=15)
        initial_in = {
            cell_id: 0 for cell_id, _ in sorted(scenario.genomes)
        }
        for source, target in run.ticks[0].l3.edges:
            initial_in[target] += 1
        for tick in run.ticks:
            in_degree = {cell_id: 0 for cell_id in initial_in}
            for source, target in tick.l3.edges:
                in_degree[target] += 1
            self.assertEqual(initial_in, in_degree)

    def test_degree_cap_excludes_busy_sources(self) -> None:
        # max_out_degree=1: once a source holds one edge it cannot be added.
        model = _adaptive_model(exchange_gain_threshold=-1.0, max_out_degree=1)
        runner = _runner(model)
        run = runner.run(_scenario(6), ticks=10)
        for tick in run.ticks:
            out_degree: dict[str, int] = {}
            for source, _ in tick.l3.edges:
                out_degree[source] = out_degree.get(source, 0) + 1
            for degree in out_degree.values():
                self.assertLessEqual(degree, 1)

    def test_determinism_of_topology_trajectory(self) -> None:
        first = _runner(_adaptive_model()).run(_scenario(4), ticks=15)
        second = _runner(_adaptive_model()).run(_scenario(4), ticks=15)
        self.assertEqual(
            [tuple(sorted(t.l3.edges)) for t in first.ticks],
            [tuple(sorted(t.l3.edges)) for t in second.ticks],
        )
        self.assertEqual(first.history_digest, second.history_digest)

    def test_swaps_appear_in_source_digest_audit_chain(self) -> None:
        # A permissive threshold forces swaps; their record must change the
        # L3 source digest hash chain relative to the static run.
        static = _runner(
            TissueEnvironmentModel(
                load_tissue_config(LAYER_CONFIGS / "l3_reference_tissue.json")
            )
        ).run(_scenario(4), ticks=10)
        adaptive = _runner(
            _adaptive_model(exchange_gain_threshold=-1.0)
        ).run(_scenario(4), ticks=10)
        self.assertNotEqual(static.history_digest, adaptive.history_digest)


class TopologyMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_demo.json"
        )
        self.config = load_topology_experiment_config(
            ROOT / "configs" / "experiments" / "topology_comparison.json"
        )
        self.runner_config = load_runner_config(
            ROOT / "configs" / "runner_reference.json"
        )
        tissue_config = load_tissue_config(
            LAYER_CONFIGS / "l3_reference_tissue.json"
        )
        self.static_runner = MultirateCrossScaleRunner(
            self.runner_config,
            **_layer_models(TissueEnvironmentModel(tissue_config)),
        )
        self.adaptive_runner = MultirateCrossScaleRunner(
            self.runner_config,
            **_layer_models(
                DynamicTopologyTissueModel(
                    tissue_config,
                    load_adaptive_topology_config(
                        LAYER_CONFIGS / "l3_adaptive_tissue.json"
                    ),
                )
            ),
        )

    def _runners(self) -> dict:
        return {
            "static_topology": self.static_runner,
            "adaptive_topology": self.adaptive_runner,
        }

    def test_matrix_structure_and_determinism(self) -> None:
        matrix = TopologyExperimentRunner(
            self.config, runners=self._runners()
        ).run(self.scenario)
        self.assertEqual(2 * len(self.config.seeds), len(matrix.records))
        self.assertEqual(len(self.config.seeds), len(matrix.comparisons))
        self.assertEqual(len(self.config.seeds), len(matrix.stability))
        self.assertTrue(matrix.matrix_id.startswith("topology-"))
        second = TopologyExperimentRunner(
            self.config, runners=self._runners()
        ).run(self.scenario)
        self.assertEqual(matrix.matrix_id, second.matrix_id)
        self.assertEqual(
            [record.run.history_digest for record in matrix.records],
            [record.run.history_digest for record in second.records],
        )

    def test_static_condition_identity_matches_vanilla_baseline(self) -> None:
        vanilla = MultirateCrossScaleRunner(
            self.runner_config,
            **_layer_models(
                TissueEnvironmentModel(
                    load_tissue_config(LAYER_CONFIGS / "l3_reference_tissue.json")
                )
            ),
        ).run(self.scenario, ticks=self.config.ticks)
        matrix = TopologyExperimentRunner(
            self.config, runners=self._runners()
        ).run(self.scenario)
        static_record = next(
            record
            for record in matrix.records
            if record.condition_id == "static_topology" and record.seed == 42
        )
        self.assertEqual(
            vanilla.manifest.experiment_id,
            static_record.run.manifest.experiment_id,
        )
        self.assertEqual(
            vanilla.history_digest, static_record.run.history_digest
        )

    def test_runner_rejects_wrong_layer_change(self) -> None:
        bad = dict(self._runners())
        bad_models = _layer_models(
            DynamicTopologyTissueModel(
                load_tissue_config(LAYER_CONFIGS / "l3_reference_tissue.json"),
                load_adaptive_topology_config(
                    LAYER_CONFIGS / "l3_adaptive_tissue.json"
                ),
            )
        )
        from mgba.layers.l2_active_inference import (
            ActiveInferenceCellModel,
            load_active_inference_config,
        )

        bad_models["cell_model"] = ActiveInferenceCellModel(
            load_active_inference_config(LAYER_CONFIGS / "l2_active_inference.json")
        )
        bad["adaptive_topology"] = MultirateCrossScaleRunner(
            self.runner_config, **bad_models
        )
        with self.assertRaises(ValueError):
            TopologyExperimentRunner(self.config, runners=bad)

    def test_budget_enforced(self) -> None:
        config = replace(self.config, ticks=999999)
        with self.assertRaises(ValueError):
            TopologyExperimentRunner(config, runners=self._runners())


if __name__ == "__main__":
    unittest.main()
