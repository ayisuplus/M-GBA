import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from mgba.layers import (
    CellAction,
    CellPhase,
    CellState,
    LocalEnvironment,
    StateMetadata,
)
from mgba.layers.l3 import (
    TissueEnvironmentModel,
    environments_from_tissue,
    load_tissue_config,
)


class TissueEnvironmentModelTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).parents[1]
        self.config_path = root / "configs" / "layers" / "l3_reference_tissue.json"
        self.model = TissueEnvironmentModel(load_tissue_config(self.config_path))
        self.cells = (
            self._cell("cell-a", activation=0.6, viability=0.8),
            self._cell("cell-b", activation=0.2, viability=0.7),
        )
        self.environments = (
            self._environment("cell-a", stress=0.4, resource=0.8),
            self._environment("cell-b", stress=0.2, resource=0.8),
        )

    @staticmethod
    def _cell(
        cell_id: str,
        *,
        activation: float,
        viability: float,
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
        secretion: float = 0.0,
        consumption: float = 0.0,
        repair: float = 0.0,
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
        cell_id: str,
        *,
        stress: float,
        resource: float,
        signal: float = 0.0,
    ) -> LocalEnvironment:
        return LocalEnvironment(
            metadata=StateMetadata(1, "test-environment-0.1", f"env-{cell_id}"),
            cell_id=cell_id,
            stress=stress,
            resource_level=resource,
            incoming_signal=signal,
        )

    @staticmethod
    def _node_map(tissue):
        return {node.cell_id: node for node in tissue.nodes}

    def test_trajectory_is_deterministic_bounded_and_keeps_static_edges(self) -> None:
        actions = (
            self._action("cell-a", secretion=0.5, consumption=0.2),
            self._action("cell-b", repair=0.1),
        )
        kwargs = {
            "cell_states": self.cells,
            "cell_actions": actions,
            "initial_environments": self.environments,
            "edges": (("cell-a", "cell-b"),),
            "steps": 10,
        }
        first = self.model.simulate(**kwargs)
        second = self.model.simulate(**kwargs)

        self.assertEqual(first, second)
        self.assertEqual(
            tuple(range(1, 11)),
            tuple(state.metadata.logical_time for state in first.states),
        )
        for state in first.states:
            self.assertEqual((("cell-a", "cell-b"),), state.edges)
            for node in state.nodes:
                for value in (node.stress, node.resource_level, node.signal):
                    self.assertGreaterEqual(value, 0.0)
                    self.assertLessEqual(value, 1.0)
            for value in (
                state.edge_density,
                state.mean_activation,
                state.mean_viability,
                state.mean_resource,
                state.mean_signal,
                state.dead_fraction,
                state.repair_activity,
                state.coordinated_signal,
                state.tissue_damage,
            ):
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)

    def test_signal_follows_edge_direction(self) -> None:
        tissue = self.model.step(
            self.cells,
            (
                self._action("cell-a", secretion=1.0),
                self._action("cell-b", secretion=0.0),
            ),
            initial_environments=self.environments,
            previous_state=None,
            edges=(("cell-a", "cell-b"),),
            logical_time=1,
        )
        nodes = self._node_map(tissue)

        self.assertEqual(0.0, nodes["cell-a"].signal)
        self.assertEqual(0.8, nodes["cell-b"].signal)

    def test_consumption_is_local_and_recovery_applies_without_it(self) -> None:
        environments = (
            self._environment("cell-a", stress=0.2, resource=0.5),
            self._environment("cell-b", stress=0.2, resource=0.5),
        )
        tissue = self.model.step(
            self.cells,
            (
                self._action("cell-a", consumption=0.5),
                self._action("cell-b", consumption=0.0),
            ),
            initial_environments=environments,
            previous_state=None,
            edges=(("cell-a", "cell-b"),),
            logical_time=1,
        )
        nodes = self._node_map(tissue)

        self.assertAlmostEqual(0.25, nodes["cell-a"].resource_level)
        self.assertAlmostEqual(0.55, nodes["cell-b"].resource_level)

    def test_repair_reduces_stress_and_apoptosis_increases_it(self) -> None:
        cell = (self._cell("cell-a", activation=0.0, viability=0.5),)
        environment = (self._environment("cell-a", stress=0.8, resource=1.0),)

        neutral = self.model.step(
            cell,
            (self._action("cell-a"),),
            initial_environments=environment,
            previous_state=None,
            edges=(),
            logical_time=1,
        )
        repaired = self.model.step(
            cell,
            (self._action("cell-a", repair=0.5),),
            initial_environments=environment,
            previous_state=None,
            edges=(),
            logical_time=1,
        )
        apoptotic = self.model.step(
            (replace(cell[0], phase=CellPhase.DEAD),),
            (self._action("cell-a", apoptosis=True),),
            initial_environments=environment,
            previous_state=None,
            edges=(),
            logical_time=1,
        )

        self.assertLess(repaired.nodes[0].stress, neutral.nodes[0].stress)
        self.assertGreater(apoptotic.nodes[0].stress, neutral.nodes[0].stress)
        self.assertNotEqual(repaired.tissue_damage, neutral.tissue_damage)

    def test_tissue_nodes_create_next_local_environments(self) -> None:
        tissue = self.model.step(
            self.cells,
            (self._action("cell-a"), self._action("cell-b")),
            initial_environments=self.environments,
            previous_state=None,
            edges=(("cell-a", "cell-b"),),
            logical_time=1,
        )
        next_environments = environments_from_tissue(tissue, logical_time=2)

        self.assertEqual(
            tuple(node.cell_id for node in tissue.nodes),
            tuple(environment.cell_id for environment in next_environments),
        )
        for node, environment in zip(
            tissue.nodes, next_environments, strict=True
        ):
            self.assertEqual(node.stress, environment.stress)
            self.assertEqual(node.resource_level, environment.resource_level)
            self.assertEqual(node.signal, environment.incoming_signal)
            self.assertEqual(2, environment.metadata.logical_time)

    def test_graph_contract_config_and_fingerprint_fail_closed(self) -> None:
        actions = (self._action("cell-a"), self._action("cell-b"))
        invalid_edges = (
            (("cell-a", "unknown"),),
            (("cell-a", "cell-a"),),
            (("cell-a", "cell-b"), ("cell-a", "cell-b")),
        )
        for edges in invalid_edges:
            with self.subTest(edges=edges), self.assertRaises(ValueError):
                self.model.step(
                    self.cells,
                    actions,
                    initial_environments=self.environments,
                    previous_state=None,
                    edges=edges,
                    logical_time=1,
                )

        first = self.model.step(
            self.cells,
            actions,
            initial_environments=self.environments,
            previous_state=None,
            edges=(("cell-a", "cell-b"),),
            logical_time=1,
        )
        with self.assertRaises(ValueError):
            self.model.step(
                self.cells,
                actions,
                initial_environments=None,
                previous_state=first,
                edges=(("cell-b", "cell-a"),),
                logical_time=2,
            )

        changed = TissueEnvironmentModel(
            replace(self.model.config, secretion_coupling=0.7)
        )
        self.assertNotEqual(self.model.model_version, changed.model_version)

        original = json.loads(self.config_path.read_text(encoding="utf-8"))
        invalid_cases = []
        missing = json.loads(json.dumps(original))
        missing.pop("repair_stress_reduction")
        invalid_cases.append(missing)
        non_finite = json.loads(json.dumps(original))
        non_finite["signal_retention"] = float("nan")
        invalid_cases.append(non_finite)
        invalid_weight_sum = json.loads(json.dumps(original))
        invalid_weight_sum["damage_viability_weight"] = 0.5
        invalid_cases.append(invalid_weight_sum)

        with tempfile.TemporaryDirectory() as directory:
            invalid_path = Path(directory) / "invalid-tissue.json"
            for raw in invalid_cases:
                invalid_path.write_text(json.dumps(raw), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_tissue_config(invalid_path)


if __name__ == "__main__":
    unittest.main()
