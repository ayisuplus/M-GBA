import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from mgba.layers import (
    CellPhase,
    LocalEnvironment,
    MolecularState,
    StateMetadata,
)
from mgba.layers.l2 import CellStateMachineModel, load_cell_config


class CellStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).parents[1]
        self.config_path = root / "configs" / "layers" / "l2_reference_cell.json"
        self.model = CellStateMachineModel(load_cell_config(self.config_path))
        self.molecular = MolecularState(
            metadata=StateMetadata(0, "test-molecular-0.1", "test-source"),
            cell_id="cell-a",
            damage_receptor=0.4,
            signal_protein=0.4,
            repair_protein=0.5,
            metabolic_capacity=0.6,
            death_effector=0.1,
            feedback_inhibitor=0.2,
        )

    def _environment(
        self,
        *,
        stress: float,
        resource_level: float = 1.0,
        incoming_signal: float = 0.0,
        logical_time: int = 1,
        cell_id: str = "cell-a",
    ) -> LocalEnvironment:
        return LocalEnvironment(
            metadata=StateMetadata(
                logical_time,
                "test-local-environment-0.1",
                f"environment-{logical_time}",
            ),
            cell_id=cell_id,
            stress=stress,
            resource_level=resource_level,
            incoming_signal=incoming_signal,
        )

    def test_trajectory_is_deterministic_bounded_and_time_ordered(self) -> None:
        first = self.model.simulate(
            molecular=self.molecular,
            stress=0.35,
            resource_level=0.8,
            incoming_signal=0.2,
            steps=20,
        )
        second = self.model.simulate(
            molecular=self.molecular,
            stress=0.35,
            resource_level=0.8,
            incoming_signal=0.2,
            steps=20,
        )

        self.assertEqual(first, second)
        self.assertEqual(
            tuple(range(1, 21)),
            tuple(state.metadata.logical_time for state in first.states),
        )
        for state, action in zip(first.states, first.actions, strict=True):
            for value in (state.activation, state.viability, state.stress_load):
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)
            for value in (
                action.secretion,
                action.resource_consumption,
                action.repair_effort,
            ):
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)

    def test_same_molecular_state_responds_to_local_environment(self) -> None:
        quiet_state, quiet_action = self.model.step(
            self.molecular,
            self._environment(stress=0.1, incoming_signal=0.0),
            previous_state=None,
            logical_time=1,
        )
        signaled_state, signaled_action = self.model.step(
            self.molecular,
            self._environment(stress=0.1, incoming_signal=1.0),
            previous_state=None,
            logical_time=1,
        )

        self.assertEqual(CellPhase.ACTIVATED, quiet_state.phase)
        self.assertEqual(CellPhase.ACTIVATED, signaled_state.phase)
        self.assertGreater(signaled_state.activation, quiet_state.activation)
        self.assertGreater(signaled_action.secretion, quiet_action.secretion)
        self.assertGreater(
            signaled_action.resource_consumption,
            quiet_action.resource_consumption,
        )

    def test_high_stress_separates_repairing_from_stressed(self) -> None:
        repairing_state, repairing_action = self.model.step(
            self.molecular,
            self._environment(stress=0.9),
            previous_state=None,
            logical_time=1,
        )
        low_repair = replace(self.molecular, repair_protein=0.05)
        stressed_state, stressed_action = self.model.step(
            low_repair,
            self._environment(stress=0.9),
            previous_state=None,
            logical_time=1,
        )

        self.assertEqual(CellPhase.REPAIRING, repairing_state.phase)
        self.assertGreater(repairing_action.repair_effort, 0.0)
        self.assertEqual(CellPhase.STRESSED, stressed_state.phase)
        self.assertEqual(0.0, stressed_action.repair_effort)

    def test_dead_is_absorbing_and_has_only_apoptosis_action(self) -> None:
        lethal = replace(
            self.molecular,
            metabolic_capacity=0.2,
            death_effector=0.9,
        )
        dead_state, dead_action = self.model.step(
            lethal,
            self._environment(stress=0.9),
            previous_state=None,
            logical_time=1,
        )
        self.assertEqual(CellPhase.DEAD, dead_state.phase)
        self.assertTrue(dead_action.apoptosis)
        self.assertEqual(0.0, dead_action.secretion)
        self.assertEqual(0.0, dead_action.resource_consumption)
        self.assertEqual(0.0, dead_action.repair_effort)

        healthy = replace(
            self.molecular,
            repair_protein=1.0,
            metabolic_capacity=1.0,
            death_effector=0.0,
        )
        still_dead, action = self.model.step(
            healthy,
            self._environment(stress=0.0, logical_time=2),
            previous_state=dead_state,
            logical_time=2,
        )
        self.assertEqual(CellPhase.DEAD, still_dead.phase)
        self.assertTrue(action.apoptosis)

    def test_cell_identity_is_local_and_cannot_be_swapped(self) -> None:
        state, _ = self.model.step(
            self.molecular,
            self._environment(stress=0.2),
            previous_state=None,
            logical_time=1,
        )
        other_molecular = replace(self.molecular, cell_id="cell-b")
        with self.assertRaises(ValueError):
            self.model.step(
                other_molecular,
                self._environment(stress=0.2, logical_time=2, cell_id="cell-b"),
                previous_state=state,
                logical_time=2,
            )
        with self.assertRaises(ValueError):
            self.model.step(
                self.molecular,
                self._environment(stress=0.2, cell_id="cell-b"),
                previous_state=None,
                logical_time=1,
            )

    def test_invalid_config_and_fingerprint_fail_closed(self) -> None:
        changed = CellStateMachineModel(
            replace(self.model.config, activation_threshold=0.2)
        )
        self.assertNotEqual(self.model.model_version, changed.model_version)

        original = json.loads(self.config_path.read_text(encoding="utf-8"))
        invalid_cases = []

        missing = json.loads(json.dumps(original))
        missing.pop("repair_threshold")
        invalid_cases.append(missing)

        invalid_threshold = json.loads(json.dumps(original))
        invalid_threshold["death_viability_threshold"] = 1.2
        invalid_cases.append(invalid_threshold)

        non_finite = json.loads(json.dumps(original))
        non_finite["stress_environment_weight"] = float("nan")
        invalid_cases.append(non_finite)

        unknown_phase = json.loads(json.dumps(original))
        unknown_phase["secretion_multipliers"]["unknown"] = 1.0
        invalid_cases.append(unknown_phase)

        with tempfile.TemporaryDirectory() as directory:
            invalid_path = Path(directory) / "invalid-cell.json"
            for raw in invalid_cases:
                invalid_path.write_text(json.dumps(raw), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_cell_config(invalid_path)


if __name__ == "__main__":
    unittest.main()
