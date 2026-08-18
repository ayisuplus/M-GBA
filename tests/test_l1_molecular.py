import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from mgba.layers import MolecularInput, MolecularState, StateMetadata, TranscriptState
from mgba.layers.l1 import (
    MOLECULAR_SPECIES,
    CoarseMolecularModel,
    load_molecular_config,
)


class CoarseMolecularModelTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).parents[1]
        self.config_path = (
            root / "configs" / "layers" / "l1_reference_molecular.json"
        )
        self.model = CoarseMolecularModel(
            load_molecular_config(self.config_path)
        )
        self.transcript = TranscriptState(
            metadata=StateMetadata(
                logical_time=0,
                model_version="test-transcript-0.1",
                source_digest="test-source",
            ),
            cell_id="cell-a",
            damage_response=0.4,
            signal_expression=0.6,
            repair_expression=0.7,
            metabolic_expression=0.8,
            death_expression=0.2,
            negative_feedback_expression=0.3,
        )

    @staticmethod
    def _values(state: MolecularState) -> tuple[float, ...]:
        return tuple(getattr(state, species) for species in MOLECULAR_SPECIES)

    def _simulate(
        self,
        transcript: TranscriptState | None = None,
        *,
        local_signal: float = 0.0,
        steps: int = 200,
    ):
        return self.model.simulate(
            transcript=transcript or self.transcript,
            local_signal=local_signal,
            steps=steps,
        )

    def test_trajectory_is_deterministic_bounded_and_time_ordered(self) -> None:
        first = self._simulate(steps=50)
        second = self._simulate(steps=50)

        self.assertEqual(first, second)
        self.assertEqual(
            tuple(range(51)),
            tuple(state.metadata.logical_time for state in first.states),
        )
        for state in first.states:
            for value in self._values(state):
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)

    def test_constant_transcript_converges_by_200_ticks(self) -> None:
        trajectory = self._simulate()
        previous, final = trajectory.states[-2:]
        final_delta = max(
            abs(after - before)
            for before, after in zip(
                self._values(previous),
                self._values(final),
                strict=True,
            )
        )
        self.assertLess(final_delta, 1e-8)

    def test_each_direct_transcript_mapping_is_monotonic(self) -> None:
        mapping = {
            "damage_response": "damage_receptor",
            "signal_expression": "signal_protein",
            "repair_expression": "repair_protein",
            "metabolic_expression": "metabolic_capacity",
            "death_expression": "death_effector",
            "negative_feedback_expression": "feedback_inhibitor",
        }
        for transcript_name, molecular_name in mapping.items():
            with self.subTest(transcript=transcript_name):
                low = self._simulate(
                    replace(self.transcript, **{transcript_name: 0.1})
                ).states[-1]
                high = self._simulate(
                    replace(self.transcript, **{transcript_name: 0.9})
                ).states[-1]
                self.assertGreater(
                    getattr(high, molecular_name),
                    getattr(low, molecular_name),
                )

    def test_zero_transcript_causes_every_nonzero_species_to_decay(self) -> None:
        previous = MolecularState(
            metadata=StateMetadata(0, "test-molecular-0.1", "test-source"),
            cell_id="cell-a",
            damage_receptor=0.8,
            signal_protein=0.8,
            repair_protein=0.8,
            metabolic_capacity=0.8,
            death_effector=0.8,
            feedback_inhibitor=0.8,
        )
        zero_transcript = replace(
            self.transcript,
            damage_response=0.0,
            signal_expression=0.0,
            repair_expression=0.0,
            metabolic_expression=0.0,
            death_expression=0.0,
            negative_feedback_expression=0.0,
        )
        molecular_input = MolecularInput(
            metadata=StateMetadata(1, "feedback-off-0.1", "test-input"),
            cell_id="cell-a",
            local_signal=0.0,
        )
        result = self.model.step(
            zero_transcript,
            previous_state=previous,
            molecular_input=molecular_input,
            logical_time=1,
        )

        for before, after in zip(
            self._values(previous), self._values(result), strict=True
        ):
            self.assertLess(after, before)

    def test_local_signal_entry_is_effective_and_can_be_disabled(self) -> None:
        disabled = self._simulate(local_signal=0.0).states[-1]
        enabled = self._simulate(local_signal=1.0).states[-1]
        repeated_disabled = self._simulate(local_signal=0.0).states[-1]

        self.assertEqual(disabled, repeated_disabled)
        self.assertGreater(enabled.signal_protein, disabled.signal_protein)

    def test_contract_and_invalid_config_fail_closed(self) -> None:
        wrong_cell_input = MolecularInput(
            metadata=StateMetadata(1, "feedback-off-0.1", "test-input"),
            cell_id="cell-b",
            local_signal=0.0,
        )
        with self.assertRaises(ValueError):
            self.model.step(
                self.transcript,
                previous_state=None,
                molecular_input=wrong_cell_input,
                logical_time=1,
            )
        with self.assertRaises(TypeError):
            self.model.step(
                self._simulate(steps=1).states[-1],  # type: ignore[arg-type]
                previous_state=None,
                molecular_input=wrong_cell_input,
                logical_time=1,
            )

        original = json.loads(self.config_path.read_text(encoding="utf-8"))
        invalid_cases = []

        missing_species = json.loads(json.dumps(original))
        missing_species["species"].pop("death_effector")
        invalid_cases.append(missing_species)

        unknown_transcript = json.loads(json.dumps(original))
        unknown_transcript["species"]["death_effector"]["transcript"] = "unknown"
        invalid_cases.append(unknown_transcript)

        unstable_rate = json.loads(json.dumps(original))
        unstable_rate["species"]["repair_protein"]["synthesis_rate"] = 0.9
        invalid_cases.append(unstable_rate)

        non_finite = json.loads(json.dumps(original))
        non_finite["local_signal_gain"] = float("nan")
        invalid_cases.append(non_finite)

        with tempfile.TemporaryDirectory() as directory:
            invalid_path = Path(directory) / "invalid-molecular.json"
            for raw in invalid_cases:
                invalid_path.write_text(json.dumps(raw), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_molecular_config(invalid_path)

    def test_config_fingerprint_is_part_of_model_version(self) -> None:
        changed = CoarseMolecularModel(
            replace(self.model.config, local_signal_gain=0.4)
        )
        self.assertNotEqual(self.model.model_version, changed.model_version)


if __name__ == "__main__":
    unittest.main()
