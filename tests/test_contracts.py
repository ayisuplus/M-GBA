import unittest
from pathlib import Path

from mgba.experiment import LayerTransitionEvent, digest_payload
from mgba.layers import (
    LayerId,
    LocalEnvironment,
    MolecularInput,
    MolecularState,
    StateMetadata,
    TranscriptState,
)
from mgba.multiscale import (
    ReferenceCellModel,
    ReferenceCrossScaleRunner,
    load_multiscale_scenario,
)


class LayerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        config = Path(__file__).parents[1] / "configs" / "multiscale_demo.json"
        self.scenario = load_multiscale_scenario(config)
        self.trace = ReferenceCrossScaleRunner().run(self.scenario)

    def test_trace_contains_only_adjacent_layer_transitions(self) -> None:
        self.assertEqual(
            "reference-l0-static-placeholder-0.2",
            self.trace.l0[0].metadata.model_version,
        )
        self.assertEqual(
            "reference-l1-static-placeholder-0.2",
            self.trace.l1[0].metadata.model_version,
        )
        self.assertEqual(
            "reference-l2-static-rules-0.2",
            self.trace.l2[0].metadata.model_version,
        )
        self.assertEqual(
            "reference-l3-static-aggregate-0.2",
            self.trace.l3.metadata.model_version,
        )
        self.assertEqual(
            "reference-l4-static-observer-0.2",
            self.trace.l4.metadata.model_version,
        )
        self.assertTrue(
            all(item.local_signal == 0.0 for item in self.trace.l1_inputs)
        )
        self.assertEqual(
            digest_payload(
                {
                    "transcript_states": self.trace.l0,
                    "previous_molecular_states": None,
                    "molecular_inputs": self.trace.l1_inputs,
                }
            ),
            self.trace.transitions[0].input_digest,
        )
        self.assertEqual(
            (
                (LayerId.L0, LayerId.L1),
                (LayerId.L1, LayerId.L2),
                (LayerId.L2, LayerId.L3),
                (LayerId.L3, LayerId.L4),
            ),
            tuple(
                (event.source_layer, event.target_layer)
                for event in self.trace.transitions
            ),
        )
        self.assertEqual(
            self.trace.l3.metadata.source_digest,
            self.trace.transitions[2].input_digest,
        )
        self.assertEqual(
            self.trace.transitions[2].output_digest,
            self.trace.transitions[3].input_digest,
        )
        self.assertEqual(
            digest_payload(self.trace.l4),
            self.trace.transitions[3].output_digest,
        )

    def test_non_adjacent_transition_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            LayerTransitionEvent(
                logical_time=0,
                source_layer=LayerId.L0,
                target_layer=LayerId.L2,
                model_version="invalid-test-0.1",
                input_digest="input",
                output_digest="output",
                timescale="contract-step",
                reason="attempted layer skip",
            )

    def test_cell_model_rejects_l0_state(self) -> None:
        environment = LocalEnvironment(
            metadata=StateMetadata(
                logical_time=0,
                model_version="scenario-boundary-0.1",
                source_digest="scenario",
            ),
            cell_id=self.trace.l0[0].cell_id,
            stress=self.scenario.environment_stress,
            resource_level=self.scenario.resource_level,
            incoming_signal=self.scenario.incoming_signal,
        )
        with self.assertRaises(TypeError):
            ReferenceCellModel().step(
                self.trace.l0[0],  # type: ignore[arg-type]
                environment,
                previous_state=None,
                logical_time=0,
            )

    def test_one_layer_can_be_replaced_without_changing_scenario(self) -> None:
        class ZeroRepairMolecularModel:
            model_version = "test-l1-zero-repair-0.1"

            def step(
                self,
                transcript: TranscriptState,
                *,
                previous_state: MolecularState | None,
                molecular_input: MolecularInput,
                logical_time: int,
            ) -> MolecularState:
                return MolecularState(
                    metadata=StateMetadata(
                        logical_time=logical_time,
                        model_version=self.model_version,
                        source_digest=transcript.metadata.source_digest,
                    ),
                    cell_id=transcript.cell_id,
                    damage_receptor=transcript.damage_response,
                    signal_protein=transcript.signal_expression,
                    repair_protein=0.0,
                    metabolic_capacity=transcript.metabolic_expression,
                    death_effector=transcript.death_expression,
                    feedback_inhibitor=transcript.negative_feedback_expression,
                )

        baseline = self.trace
        replaced = ReferenceCrossScaleRunner(
            molecular_model=ZeroRepairMolecularModel()
        ).run(self.scenario)

        self.assertEqual(
            tuple(state.cell_id for state in baseline.l0),
            tuple(state.cell_id for state in replaced.l0),
        )
        self.assertLess(replaced.l4.vitality, baseline.l4.vitality)
        self.assertEqual(
            "test-l1-zero-repair-0.1", replaced.transitions[0].model_version
        )


if __name__ == "__main__":
    unittest.main()
