"""Contract, edge-case, and reproducibility tests for the read-only observer."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from mgba.collective_dynamics import (
    COLLECTIVE_DYNAMICS_SCHEMA,
    COLLECTIVE_OBSERVER_VERSION,
    CollectiveDynamicsConfig,
    CollectiveDynamicsObserver,
    analyze_collective_dynamics,
    analyze_collective_dynamics_raw,
    classify_collective_state,
    compare_collective_dynamics,
    save_collective_dynamics_artifact,
)
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config
from mgba.layers.l2 import CellStateMachineModel, load_cell_config
from mgba.layers.l3 import TissueEnvironmentModel, load_tissue_config
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.multiscale import load_multiscale_scenario
from mgba.runner import MultirateCrossScaleRunner, load_runner_config


ROOT = Path(__file__).parents[1]


def _raw_run(
    cells: dict[str, list[tuple[float, float]]],
    *,
    edges: tuple[tuple[str, str], ...] = (),
    experiment_id: str = "mgba-fixture",
) -> dict:
    length = len(next(iter(cells.values())))
    if any(len(values) != length for values in cells.values()):
        raise ValueError("fixture Cell series must align")
    ticks = []
    for index in range(length):
        logical_time = index + 1
        l4 = None
        if logical_time in {1, length}:
            l4 = {
                "vitality": 0.8 - 0.01 * index,
                "damage_burden": 0.2 + 0.01 * index,
                "inflammation": 0.1 + 0.01 * index,
                "homeostasis": 0.7 - 0.01 * index,
                "recovery_capacity": 0.6 - 0.01 * index,
            }
        ticks.append(
            {
                "logical_time": logical_time,
                "l2": [
                    {
                        "cell_id": cell_id,
                        "activation": values[index][0],
                        "stress_load": values[index][1],
                    }
                    for cell_id, values in sorted(cells.items())
                ],
                "l3": {"edges": [list(edge) for edge in edges]},
                "l4": l4,
            }
        )
    terminal = dict(ticks[-1]["l4"] or ticks[0]["l4"])
    terminal["metadata"] = {"logical_time": length}
    return {
        "experiment": {"experiment_id": experiment_id},
        "history_digest": "a" * 64,
        "ticks": ticks,
        "terminal_observation": terminal,
    }


def _cohort(report, cohort_id="all_cells") -> dict:
    return report.as_dict()["cohorts"][cohort_id]


class CollectiveFormulaAndClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = CollectiveDynamicsConfig()

    def test_formula_fractions_alignment_and_no_edge_null(self) -> None:
        raw = _raw_run(
            {
                "a": [(0.8, 0.2)],
                "b": [(0.2, 0.8)],
            }
        )
        point = _cohort(analyze_collective_dynamics_raw(raw))["series"][0]
        self.assertAlmostEqual(0.0, point["direction"])
        self.assertAlmostEqual(0.34, point["intensity"])
        self.assertAlmostEqual(0.36, point["polarization"])
        self.assertEqual("population_split", point["state"])
        self.assertEqual(0.5, point["activation_dominant_fraction"])
        self.assertEqual(0.5, point["stress_dominant_fraction"])
        self.assertIsNone(point["edge_alignment"])

        raw["ticks"][0]["l3"]["edges"] = [["a", "b"]]
        aligned = _cohort(analyze_collective_dynamics_raw(raw))["series"][0]
        self.assertAlmostEqual(-0.36, aligned["edge_alignment"])

    def test_ordered_threshold_boundaries_are_frozen(self) -> None:
        classify = lambda m, c, p: classify_collective_state(m, c, p, self.config)
        self.assertEqual("low_activity", classify(0.9, 0.039999, 1.0))
        self.assertEqual("activation_dominant", classify(0.15, 0.04, 1.0))
        self.assertEqual("stress_dominant", classify(-0.15, 0.16, 1.0))
        self.assertEqual("population_split", classify(0.0, 0.16, 0.09))
        self.assertEqual("coactivated_balance", classify(0.0, 0.16, 0.089999))
        self.assertEqual("transitional", classify(0.1, 0.10, 0.01))

    def test_short_neutral_and_non_finite_traces_fail_honestly(self) -> None:
        neutral = _raw_run({"a": [(0.0, 0.0), (0.1, 0.1)]})
        cohort = _cohort(analyze_collective_dynamics_raw(neutral))
        self.assertEqual("persistent_low_activity", cohort["trajectory_class"])
        self.assertIsNone(cohort["first_qualified_transition_tick"])
        self.assertEqual([], cohort["state_transitions"])
        neutral["ticks"][0]["l2"][0]["activation"] = math.nan
        with self.assertRaises(ValueError):
            analyze_collective_dynamics_raw(neutral)

    def test_single_cell_all_dead_trace_remains_a_valid_negative_case(self) -> None:
        raw = _raw_run({"dead-cell": [(0.0, 0.8)] * 5})
        for tick in raw["ticks"]:
            tick["l2"][0]["phase"] = "dead"
        cohort = _cohort(analyze_collective_dynamics_raw(raw))
        self.assertEqual("persistent_stress", cohort["trajectory_class"])
        self.assertTrue(
            all(point["state"] == "stress_dominant" for point in cohort["series"])
        )


class CollectiveTrajectoryTests(unittest.TestCase):
    def _report_for_z(self, values: list[float]):
        pairs = [(max(value, 0.0), max(-value, 0.0)) for value in values]
        return analyze_collective_dynamics_raw(_raw_run({"a": pairs}))

    def test_minimum_dwell_and_trajectory_priority(self) -> None:
        reversal = self._report_for_z([0.6] * 5 + [-0.6] * 5)
        cohort = _cohort(reversal)
        self.assertEqual("reversal", cohort["trajectory_class"])
        self.assertEqual(1, cohort["qualified_direction_switches"])
        self.assertEqual(6, cohort["first_qualified_transition_tick"])
        self.assertEqual("single_switch", cohort["cell_archetypes"]["a"])
        association = cohort["state_transitions"][0]["l4_association"]
        self.assertEqual("temporal_association_only", association["relationship"])
        self.assertEqual(1, association["before"]["tick"])
        self.assertEqual(10, association["after"]["tick"])

        brief = self._report_for_z([0.6] * 3 + [-0.6] * 2 + [0.6] * 3)
        self.assertEqual(0, _cohort(brief)["qualified_direction_switches"])
        self.assertIsNone(_cohort(brief)["first_qualified_transition_tick"])

        oscillatory = self._report_for_z(
            [0.6] * 3 + [-0.6] * 3 + [0.6] * 3 + [-0.6] * 3
        )
        self.assertEqual("oscillatory", _cohort(oscillatory)["trajectory_class"])
        self.assertEqual("oscillatory", _cohort(oscillatory)["cell_archetypes"]["a"])

    def test_cohort_contract_and_variance_decomposition(self) -> None:
        raw = _raw_run(
            {
                "a": [(0.8, 0.2)] * 3,
                "b": [(0.7, 0.2)] * 3,
                "c": [(0.2, 0.7)] * 3,
                "d": [(0.2, 0.8)] * 3,
            }
        )
        mapping = {"a": "left", "b": "left", "c": "right", "d": "right"}
        report = analyze_collective_dynamics_raw(raw, mapping)
        self.assertEqual({"all_cells", "left", "right"}, set(report.as_dict()["cohorts"]))
        for item in report.variance_decomposition:
            self.assertAlmostEqual(
                item["total_polarization"],
                item["within_cohort"] + item["between_cohort"] + item["residual"],
                places=7,
            )
        with self.assertRaises(ValueError):
            analyze_collective_dynamics_raw(raw, {"a": "left"})
        with self.assertRaises(ValueError):
            analyze_collective_dynamics_raw(raw, {**mapping, "unknown": "left"})

    def test_cell_identity_drift_is_rejected(self) -> None:
        raw = _raw_run({"a": [(0.6, 0.0)] * 3, "b": [(0.0, 0.6)] * 3})
        raw["ticks"][1]["l2"][1]["cell_id"] = "c"
        with self.assertRaises(ValueError):
            analyze_collective_dynamics_raw(raw)


class CollectiveReproducibilityTests(unittest.TestCase):
    def test_report_comparison_and_write_once_are_deterministic(self) -> None:
        raw = _raw_run({"a": [(0.6, 0.0)] * 6})
        first = analyze_collective_dynamics_raw(raw)
        second = analyze_collective_dynamics_raw(raw)
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual(COLLECTIVE_DYNAMICS_SCHEMA, first.as_dict()["schema_version"])
        self.assertEqual(COLLECTIVE_OBSERVER_VERSION, first.as_dict()["observer_version"])
        comparison = compare_collective_dynamics(first, second).as_dict()
        all_cells = comparison["cohorts"]["all_cells"]
        self.assertIsNone(all_cells["first_state_divergence_tick"])
        self.assertEqual(
            {"direction": 0.0, "intensity": 0.0, "polarization": 0.0},
            all_cells["mean_absolute_difference"],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "collective.json"
            save_collective_dynamics_artifact(path, first)
            original = path.read_bytes()
            save_collective_dynamics_artifact(path, second)
            self.assertEqual(original, path.read_bytes())
            path.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                save_collective_dynamics_artifact(path, first)

    def test_observer_does_not_mutate_formal_run_or_frozen_identity(self) -> None:
        layers = ROOT / "configs" / "layers"
        runner = MultirateCrossScaleRunner(
            load_runner_config(ROOT / "configs" / "runner_reference.json"),
            genome_model=DiscreteGrnModel(load_grn_config(layers / "l0_reference_grn.json")),
            molecular_model=CoarseMolecularModel(load_molecular_config(layers / "l1_reference_molecular.json")),
            cell_model=CellStateMachineModel(load_cell_config(layers / "l2_reference_cell.json")),
            tissue_model=TissueEnvironmentModel(load_tissue_config(layers / "l3_reference_tissue.json")),
            phenotype_model=PhenotypeObserverModel(load_phenotype_config(layers / "l4_reference_phenotype.json")),
        )
        run = runner.run(load_multiscale_scenario(ROOT / "configs" / "multiscale_demo.json"), ticks=8)
        before = run.as_dict()
        history = run.history_digest
        checkpoint = run.checkpoint
        report = analyze_collective_dynamics(run)
        self.assertEqual(before, run.as_dict())
        self.assertEqual(history, run.history_digest)
        self.assertEqual(checkpoint, run.checkpoint)
        self.assertEqual(run.manifest.experiment_id, report.source_experiment_id)
        self.assertEqual(history, report.source_history_digest)
        self.assertEqual(
            COLLECTIVE_OBSERVER_VERSION,
            CollectiveDynamicsObserver().model_version,
        )


if __name__ == "__main__":
    unittest.main()
