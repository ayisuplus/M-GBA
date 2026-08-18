import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from mgba.layers.l0 import (
    ABSTRACT_GENE_NAMES,
    DiscreteGrnModel,
    PerturbationKind,
    load_grn_config,
)
from mgba.models import Genome


class DiscreteGrnTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).parents[1]
        self.config_path = root / "configs" / "layers" / "l0_reference_grn.json"
        self.model = DiscreteGrnModel(load_grn_config(self.config_path))
        self.genome = Genome(
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

    @staticmethod
    def _expressions(state: object) -> tuple[float, ...]:
        return tuple(getattr(state, gene) for gene in ABSTRACT_GENE_NAMES)

    def _simulate(
        self,
        damage_signal: float,
        *,
        steps: int = 200,
        perturbations: dict[str, float] | None = None,
    ):
        return self.model.simulate(
            cell_id="cell-a",
            genome=self.genome,
            damage_signal=damage_signal,
            steps=steps,
            perturbations=perturbations,
        )

    def test_trajectory_is_deterministic_bounded_and_time_ordered(self) -> None:
        first = self._simulate(0.35, steps=50)
        second = self._simulate(0.35, steps=50)

        self.assertEqual(first, second)
        self.assertEqual(
            tuple(range(51)),
            tuple(state.metadata.logical_time for state in first.states),
        )
        for state in first.states:
            for value in self._expressions(state):
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)

    def test_reference_trajectory_converges_by_200_ticks(self) -> None:
        trajectory = self._simulate(0.35)
        previous, final = trajectory.states[-2:]
        final_delta = max(
            abs(after - before)
            for before, after in zip(
                self._expressions(previous),
                self._expressions(final),
                strict=True,
            )
        )
        self.assertLess(final_delta, 1e-8)

    def test_damage_dose_has_frozen_directional_response(self) -> None:
        low = self._simulate(0.0).states[-1]
        high = self._simulate(1.0).states[-1]

        self.assertGreater(high.damage_response, low.damage_response)
        self.assertGreater(high.signal_expression, low.signal_expression)
        self.assertGreater(high.death_expression, low.death_expression)
        self.assertLess(high.metabolic_expression, low.metabolic_expression)

    def test_sustained_repair_clamp_is_exact_and_audited(self) -> None:
        knockdown = self._simulate(
            0.35,
            steps=20,
            perturbations={"repair_expression": 0.0},
        )
        overexpression = self._simulate(
            0.35,
            steps=20,
            perturbations={"repair_expression": 1.0},
        )

        self.assertTrue(
            all(state.repair_expression == 0.0 for state in knockdown.states)
        )
        self.assertTrue(
            all(state.repair_expression == 1.0 for state in overexpression.states)
        )
        self.assertEqual(21, len(knockdown.perturbation_events))
        self.assertTrue(
            all(
                event.kind is PerturbationKind.KNOCKDOWN
                for event in knockdown.perturbation_events
            )
        )
        self.assertTrue(
            all(
                event.kind is PerturbationKind.OVEREXPRESSION
                for event in overexpression.perturbation_events
            )
        )
        self.assertGreater(
            knockdown.states[-1].death_expression,
            overexpression.states[-1].death_expression,
        )

    def test_invalid_inputs_and_config_fail_closed(self) -> None:
        incomplete = Genome(version="invalid", traits={"repair_expression": 0.5})
        with self.assertRaises(ValueError):
            self.model.simulate(
                cell_id="cell-a",
                genome=incomplete,
                damage_signal=0.35,
                steps=1,
            )
        with self.assertRaises(ValueError):
            self._simulate(1.1, steps=1)
        with self.assertRaises(ValueError):
            self._simulate(0.35, steps=1, perturbations={"unknown_gene": 0.0})

        with tempfile.TemporaryDirectory() as directory:
            invalid_path = Path(directory) / "invalid-grn.json"
            original = json.loads(self.config_path.read_text(encoding="utf-8"))

            invalid_cases = []
            unknown_edge = json.loads(json.dumps(original))
            unknown_edge["edges"].append(
                {
                    "source": "unknown_gene",
                    "target": "repair_expression",
                    "weight": 1.0,
                }
            )
            invalid_cases.append(unknown_edge)

            duplicate_edge = json.loads(json.dumps(original))
            duplicate_edge["edges"].append(dict(duplicate_edge["edges"][0]))
            invalid_cases.append(duplicate_edge)

            non_finite = json.loads(json.dumps(original))
            non_finite["biases"]["damage_response"] = float("nan")
            invalid_cases.append(non_finite)

            for raw in invalid_cases:
                invalid_path.write_text(json.dumps(raw), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_grn_config(invalid_path)

    def test_config_fingerprint_is_part_of_model_version(self) -> None:
        changed = DiscreteGrnModel(
            replace(self.model.config, update_rate=0.4)
        )
        self.assertNotEqual(self.model.model_version, changed.model_version)


if __name__ == "__main__":
    unittest.main()
