import unittest

from mgba.models import MessageKind, SemanticMessage, TopologyOperation, TopologyProposal
from mgba.sten import DirectedTopology, StenEngine, TopologyViolation


class StenEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.topology = DirectedTopology.from_edges(
            {"a", "b", "c"}, [("a", "b")], max_out_degree=1
        )

    def test_topology_guards_self_edges_and_degree(self) -> None:
        with self.assertRaises(TopologyViolation):
            self.topology.connect("a", "a")
        with self.assertRaises(TopologyViolation):
            self.topology.connect("a", "c")

    def test_route_requires_an_active_edge(self) -> None:
        engine = StenEngine(self.topology)
        message = SemanticMessage("m1", "a", "b", 0, MessageKind.SIGNAL, 50, {"x": 1})
        engine.route(message, requested_by="a")
        self.assertEqual((message,), engine.drain("b"))

        blocked = SemanticMessage("m2", "b", "a", 0, MessageKind.SIGNAL, 50, {"x": 1})
        with self.assertRaises(TopologyViolation):
            engine.route(blocked, requested_by="b")

        with self.assertRaises(TopologyViolation):
            engine.route(message, requested_by="c")

    def test_agent_can_change_its_outgoing_edge(self) -> None:
        engine = StenEngine(self.topology)
        removed = engine.apply(
            TopologyProposal("a", "b", TopologyOperation.DESTROY, "local signal ended", 1),
            requested_by="a",
        )
        added = engine.apply(
            TopologyProposal("a", "c", TopologyOperation.CREATE, "new local signal", 2),
            requested_by="a",
        )
        self.assertTrue(removed and added)
        self.assertEqual((("a", "c"),), self.topology.snapshot())

        with self.assertRaises(TopologyViolation):
            engine.apply(
                TopologyProposal("a", "c", TopologyOperation.DESTROY, "forged request", 3),
                requested_by="b",
            )


if __name__ == "__main__":
    unittest.main()
