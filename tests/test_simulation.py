import unittest
from pathlib import Path

from mgba.simulation import load_scenario, run_scenario


class SimulationTests(unittest.TestCase):
    def test_demo_is_deterministic(self) -> None:
        config = Path(__file__).parents[1] / "configs" / "demo.json"
        scenario = load_scenario(config)
        first = run_scenario(scenario)
        second = run_scenario(scenario)
        self.assertEqual(first, second)
        self.assertEqual(16, first["messages_routed"])


if __name__ == "__main__":
    unittest.main()
