import unittest
from dataclasses import replace
from pathlib import Path

from mgba.layers import (
    CellAgent,
    LocalEnvironment,
    MolecularState,
    StateMetadata,
    TranscriptState,
)
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config
from mgba.layers.l2 import CellStateMachineModel, StaticCellModel, load_cell_config
from mgba.layers.l3 import TissueEnvironmentModel, load_tissue_config
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.models import Genome
from mgba.multiscale import load_multiscale_scenario
from mgba.runner import MultirateCrossScaleRunner, load_runner_config


def _genome() -> Genome:
    return Genome(version="test-genome-0.1", traits={"signal": 0.5})


def _inputs(cell_id: str, logical_time: int = 1):
    metadata = StateMetadata(logical_time, "test-input-0.1", "digest")
    molecular = MolecularState(
        metadata=metadata,
        cell_id=cell_id,
        damage_receptor=0.3,
        signal_protein=0.4,
        repair_protein=0.5,
        metabolic_capacity=0.7,
        death_effector=0.1,
        feedback_inhibitor=0.2,
    )
    environment = LocalEnvironment(
        metadata=metadata,
        cell_id=cell_id,
        stress=0.4,
        resource_level=0.6,
        incoming_signal=0.2,
    )
    return molecular, environment


class CellAgentTests(unittest.TestCase):
    def test_construction_validates_identity_genome_and_policy(self) -> None:
        genome = _genome()
        policy = StaticCellModel()
        with self.assertRaises(ValueError):
            CellAgent("  ", genome, policy)
        with self.assertRaises(TypeError):
            CellAgent("cell-a", "not-a-genome", policy)

        class NoStep:
            model_version = "incomplete-0.1"

        with self.assertRaises(TypeError):
            CellAgent("cell-a", genome, NoStep())

    def test_decide_delegates_and_feeds_back_previous_state(self) -> None:
        policy = StaticCellModel()
        agent = CellAgent("cell-a", _genome(), policy)
        molecular, environment = _inputs("cell-a")

        first = agent.decide(molecular, environment, logical_time=1)
        direct_first = policy.step(
            molecular, environment, previous_state=None, logical_time=1
        )
        self.assertEqual(direct_first, first)

        molecular2, environment2 = _inputs("cell-a", logical_time=2)

        second = agent.decide(molecular2, environment2, logical_time=2)
        direct_second = policy.step(
            molecular2,
            environment2,
            previous_state=direct_first[0],
            logical_time=2,
        )
        self.assertEqual(direct_second, second)
        self.assertIs(agent.l2, second[0])

    def test_decide_rejects_cross_cell_inputs(self) -> None:
        agent = CellAgent("cell-a", _genome(), StaticCellModel())
        molecular, environment = _inputs("cell-a")
        with self.assertRaises(ValueError):
            agent.decide(
                replace(molecular, cell_id="cell-b"), environment, logical_time=1
            )
        with self.assertRaises(ValueError):
            agent.decide(
                molecular, replace(environment, cell_id="cell-b"), logical_time=1
            )

    def test_decide_rejects_cross_cell_policy_output(self) -> None:
        class CrosswiredPolicy:
            model_version = "fake-crosswired-0.1"

            def step(self, molecular, environment, *, previous_state, logical_time):
                state, action = StaticCellModel().step(
                    molecular,
                    environment,
                    previous_state=previous_state,
                    logical_time=logical_time,
                )
                return (
                    replace(state, cell_id="cell-b"),
                    replace(action, cell_id="cell-b"),
                )

        agent = CellAgent("cell-a", _genome(), CrosswiredPolicy())
        molecular, environment = _inputs("cell-a")
        with self.assertRaises(ValueError):
            agent.decide(molecular, environment, logical_time=1)

    def test_advance_rejects_other_cell_states(self) -> None:
        agent = CellAgent("cell-a", _genome(), StaticCellModel())
        molecular, _ = _inputs("cell-a")
        transcript = TranscriptState(
            metadata=StateMetadata(1, "test-l0-0.1", "digest"),
            cell_id="cell-b",
            damage_response=0.1,
            signal_expression=0.2,
            repair_expression=0.3,
            metabolic_expression=0.4,
            death_expression=0.0,
            negative_feedback_expression=0.1,
        )
        with self.assertRaises(ValueError):
            agent.advance_l0(transcript)
        with self.assertRaises(ValueError):
            agent.advance_l1(replace(molecular, cell_id="cell-b"))
        state, _ = agent.decide(molecular, _inputs("cell-a")[1], logical_time=1)
        with self.assertRaises(ValueError):
            agent.advance_l2(replace(state, cell_id="cell-b"))


class CellAgentIntegrationTests(unittest.TestCase):
    def test_agent_path_matches_direct_layer_model_calls(self) -> None:
        root = Path(__file__).parents[1]
        scenario = load_multiscale_scenario(root / "configs" / "multiscale_demo.json")
        layer_configs = root / "configs" / "layers"
        runner = MultirateCrossScaleRunner(
            load_runner_config(root / "configs" / "runner_reference.json"),
            genome_model=DiscreteGrnModel(
                load_grn_config(layer_configs / "l0_reference_grn.json")
            ),
            molecular_model=CoarseMolecularModel(
                load_molecular_config(layer_configs / "l1_reference_molecular.json")
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
        run = runner.run(scenario, ticks=5)
        tick = run.ticks[0]

        direct_model = CellStateMachineModel(
            load_cell_config(layer_configs / "l2_reference_cell.json")
        )
        for state, action, molecular, environment in zip(
            tick.l2, tick.l2_actions, tick.l1, tick.l2_environments, strict=True
        ):
            direct_state, direct_action = direct_model.step(
                molecular, environment, previous_state=None, logical_time=1
            )
            self.assertEqual(direct_state, state)
            self.assertEqual(direct_action, action)


if __name__ == "__main__":
    unittest.main()
