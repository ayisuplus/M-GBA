import json
import subprocess
import sys
import unittest
from pathlib import Path


class MvpDemoTests(unittest.TestCase):
    def test_fallback_demo_is_executable_and_scope_limited(self) -> None:
        root = Path(__file__).parents[1]
        completed = subprocess.run(
            (
                sys.executable,
                str(root / "scripts" / "mvp_demo.py"),
                "--mode",
                "fallback",
            ),
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)

        self.assertEqual("fallback", result["mode"])
        self.assertEqual("mgba-023f543fb5a130ab", result["single_tick_experiment_id"])
        self.assertIn("30-tick runner", result["scope"])
        self.assertEqual(64, len(result["history_digest"]))
        self.assertEqual(64, len(result["sten_event_digest"]))


if __name__ == "__main__":
    unittest.main()
