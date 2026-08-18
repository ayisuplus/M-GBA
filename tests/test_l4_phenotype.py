import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from statistics import fmean

from mgba.layers import (
    OrganismOutcome,
    OrganismState,
    StateMetadata,
    TissueNodeState,
    TissueState,
)
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config


class PhenotypeObserverModelTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).parents[1]
        self.config_path = root / "configs" / "layers" / "l4_reference_phenotype.json"
        self.model = PhenotypeObserverModel(
            load_phenotype_config(self.config_path)
        )

    @staticmethod
    def _tissue(
        *,
        logical_time: int = 1,
        viability: float = 0.8,
        resource: float = 0.7,
        damage: float = 0.2,
        activation: float = 0.3,
        signal: float = 0.2,
        dead_fraction: float = 0.1,
        repair: float = 0.2,
    ) -> TissueState:
        return TissueState(
            metadata=StateMetadata(
                logical_time, "test-tissue-0.1", f"tissue-{logical_time}"
            ),
            cell_count=1,
            nodes=(
                TissueNodeState(
                    cell_id="cell-a",
                    stress=damage,
                    resource_level=resource,
                    signal=signal,
                ),
            ),
            edges=(),
            edge_density=0.0,
            mean_activation=activation,
            mean_viability=viability,
            mean_resource=resource,
            mean_signal=signal,
            dead_fraction=dead_fraction,
            repair_activity=repair,
            coordinated_signal=signal,
            tissue_damage=damage,
        )

    def _organism(
        self,
        logical_time: int,
        *,
        vitality: float,
        homeostasis: float,
        damage: float,
    ) -> OrganismState:
        return OrganismState(
            metadata=StateMetadata(
                logical_time,
                self.model.model_version,
                f"organism-{logical_time}-{homeostasis}",
            ),
            vitality=vitality,
            damage_burden=damage,
            inflammation=damage,
            homeostasis=homeostasis,
            recovery_capacity=0.5,
        )

    def test_healthy_and_failed_extremes_are_exact_and_deterministic(self) -> None:
        healthy_tissue = self._tissue(
            viability=1.0,
            resource=1.0,
            damage=0.0,
            activation=0.0,
            signal=0.0,
            dead_fraction=0.0,
            repair=0.0,
        )
        failed_tissue = self._tissue(
            viability=0.0,
            resource=0.0,
            damage=1.0,
            activation=1.0,
            signal=1.0,
            dead_fraction=1.0,
            repair=0.0,
        )

        healthy = self.model.step(healthy_tissue, logical_time=1)
        failed = self.model.step(failed_tissue, logical_time=1)

        self.assertEqual(healthy, self.model.step(healthy_tissue, logical_time=1))
        self.assertEqual(
            (1.0, 0.0, 0.0, 1.0, 0.5),
            (
                healthy.vitality,
                healthy.damage_burden,
                healthy.inflammation,
                healthy.homeostasis,
                healthy.recovery_capacity,
            ),
        )
        self.assertEqual(
            (0.0, 1.0, 1.0, 0.0, 0.0),
            (
                failed.vitality,
                failed.damage_burden,
                failed.inflammation,
                failed.homeostasis,
                failed.recovery_capacity,
            ),
        )

    def test_tissue_inputs_have_frozen_directional_effects(self) -> None:
        baseline = self.model.step(self._tissue(), logical_time=1)
        damaged = self.model.step(self._tissue(damage=0.6), logical_time=1)
        activated = self.model.step(
            self._tissue(activation=0.7, signal=0.6), logical_time=1
        )
        repairing = self.model.step(self._tissue(repair=0.8), logical_time=1)
        depleted = self.model.step(self._tissue(resource=0.2), logical_time=1)
        low_viability = self.model.step(self._tissue(viability=0.4), logical_time=1)

        self.assertGreater(damaged.damage_burden, baseline.damage_burden)
        self.assertGreater(damaged.inflammation, baseline.inflammation)
        self.assertLess(damaged.vitality, baseline.vitality)
        self.assertLess(damaged.homeostasis, baseline.homeostasis)
        self.assertLess(damaged.recovery_capacity, baseline.recovery_capacity)

        self.assertGreater(activated.inflammation, baseline.inflammation)
        self.assertEqual(activated.vitality, baseline.vitality)
        self.assertEqual(activated.damage_burden, baseline.damage_burden)
        self.assertEqual(
            activated.recovery_capacity, baseline.recovery_capacity
        )

        self.assertGreater(repairing.recovery_capacity, baseline.recovery_capacity)
        self.assertEqual(repairing.vitality, baseline.vitality)
        self.assertEqual(repairing.inflammation, baseline.inflammation)
        self.assertEqual(repairing.homeostasis, baseline.homeostasis)

        self.assertLess(depleted.vitality, baseline.vitality)
        self.assertLess(depleted.recovery_capacity, baseline.recovery_capacity)
        self.assertLess(low_viability.vitality, baseline.vitality)
        self.assertLess(
            low_viability.recovery_capacity, baseline.recovery_capacity
        )

    def test_window_is_a_deterministic_descriptive_summary(self) -> None:
        states = tuple(
            self.model.step(
                self._tissue(
                    logical_time=logical_time,
                    viability=viability,
                    damage=damage,
                ),
                logical_time=logical_time,
            )
            for logical_time, viability, damage in (
                (1, 0.6, 0.5),
                (2, 0.7, 0.3),
                (3, 0.9, 0.1),
            )
        )
        window = self.model.summarize(states)

        self.assertEqual(window, self.model.summarize(states))
        self.assertEqual((1, 3, 3), (window.start_time, window.end_time, window.sample_count))
        self.assertAlmostEqual(
            fmean(state.vitality for state in states), window.mean_vitality
        )
        self.assertAlmostEqual(
            fmean(state.damage_burden for state in states),
            window.mean_damage_burden,
        )
        self.assertAlmostEqual(
            states[-1].homeostasis - states[0].homeostasis,
            window.homeostasis_delta,
        )
        self.assertEqual(states[-1].vitality, window.final_vitality)
        self.assertEqual(states[-1].homeostasis, window.final_homeostasis)
        self.assertEqual(states[-1].damage_burden, window.final_damage_burden)

    def test_final_outcomes_are_distinct_and_failed_has_priority(self) -> None:
        cases = (
            (
                (
                    self._organism(1, vitality=0.6, homeostasis=0.60, damage=0.2),
                    self._organism(2, vitality=0.6, homeostasis=0.62, damage=0.2),
                ),
                OrganismOutcome.STABLE,
            ),
            (
                (
                    self._organism(1, vitality=0.5, homeostasis=0.60, damage=0.3),
                    self._organism(2, vitality=0.8, homeostasis=0.75, damage=0.1),
                ),
                OrganismOutcome.RECOVERED,
            ),
            (
                (
                    self._organism(1, vitality=0.8, homeostasis=0.80, damage=0.1),
                    self._organism(2, vitality=0.5, homeostasis=0.60, damage=0.5),
                ),
                OrganismOutcome.DETERIORATING,
            ),
            (
                (
                    self._organism(1, vitality=0.1, homeostasis=0.10, damage=0.9),
                    self._organism(2, vitality=0.2, homeostasis=0.75, damage=0.8),
                ),
                OrganismOutcome.FAILED,
            ),
        )

        for states, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(expected, self.model.summarize(states).outcome)

    def test_l4_rejects_non_tissue_future_and_invalid_windows(self) -> None:
        with self.assertRaises(TypeError):
            self.model.step(object(), logical_time=1)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            self.model.step(self._tissue(logical_time=2), logical_time=1)
        with self.assertRaises(ValueError):
            self.model.summarize(())

        first = self.model.step(self._tissue(logical_time=1), logical_time=1)
        second = self.model.step(self._tissue(logical_time=2), logical_time=2)
        with self.assertRaises(ValueError):
            self.model.summarize((second, first))
        with self.assertRaises(ValueError):
            self.model.summarize(
                (
                    first,
                    replace(
                        second,
                        metadata=replace(
                            second.metadata, model_version="other-l4-model"
                        ),
                    ),
                )
            )

    def test_config_contract_and_fingerprint_fail_closed(self) -> None:
        changed = PhenotypeObserverModel(
            replace(self.model.config, trend_delta_min=0.1)
        )
        self.assertNotEqual(self.model.model_version, changed.model_version)

        original = json.loads(self.config_path.read_text(encoding="utf-8"))
        invalid_cases = []
        missing = json.loads(json.dumps(original))
        missing.pop("homeostasis_weights")
        invalid_cases.append(missing)
        wrong_length = json.loads(json.dumps(original))
        wrong_length["vitality_support_weights"] = [1.0]
        invalid_cases.append(wrong_length)
        non_finite = json.loads(json.dumps(original))
        non_finite["recovery_weights"][0] = float("nan")
        invalid_cases.append(non_finite)
        invalid_sum = json.loads(json.dumps(original))
        invalid_sum["inflammation_weights"] = [0.5, 0.3, 0.3]
        invalid_cases.append(invalid_sum)
        invalid_threshold = json.loads(json.dumps(original))
        invalid_threshold["trend_delta_min"] = 0.0
        invalid_cases.append(invalid_threshold)

        with tempfile.TemporaryDirectory() as directory:
            invalid_path = Path(directory) / "invalid-phenotype.json"
            for raw in invalid_cases:
                invalid_path.write_text(json.dumps(raw), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_phenotype_config(invalid_path)


if __name__ == "__main__":
    unittest.main()
