import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from mgba.demo import DEMO_PLAYBOOK_SCHEMA, export_carm_demo
from mgba.hashing import digest_payload
from mgba.experiments import load_causal_config
from mgba.runner import load_runner_config
from mgba.scenarios.carm import (
    build_carm_runners,
    compile_carm_scenario,
    load_carm_scenario_config,
    run_carm_matrix,
)


EXPECTED_CONDITIONS = ("baseline", "car_off_000", "car_affinity_070", "car_max_100")


class DemoExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).parents[1]
        cls.temporary = tempfile.TemporaryDirectory()
        cls.temp_root = Path(cls.temporary.name)
        cls.configs = {
            "scenario_config": cls.root
            / "configs"
            / "scenarios"
            / "carm"
            / "high_immune_her2.json",
            "matrix_config": cls.root
            / "configs"
            / "experiments"
            / "carm_vertical_slice.json",
            "runner_config": cls.root / "configs" / "runner_reference.json",
            "l0_config": cls.root / "configs" / "layers" / "l0_reference_grn.json",
            "l1_config": cls.root
            / "configs"
            / "layers"
            / "l1_reference_molecular.json",
            "l4_config": cls.root
            / "configs"
            / "layers"
            / "l4_reference_phenotype.json",
        }
        cls.paths = export_carm_demo(
            **cls.configs, output_dir=cls.temp_root / "demo-a"
        )
        cls.playbook = json.loads(cls.paths.playbook.read_text(encoding="utf-8"))
        cls.html = cls.paths.html.read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_export_is_deterministic_and_manifest_is_complete(self) -> None:
        second = export_carm_demo(
            **self.configs, output_dir=self.temp_root / "demo-b"
        )
        self.assertEqual(
            self.paths.playbook.read_bytes(), second.playbook.read_bytes()
        )
        self.assertEqual(self.paths.html.read_bytes(), second.html.read_bytes())
        manifest = json.loads(self.paths.manifest.read_text(encoding="utf-8"))
        self.assertEqual("mgba-demo-files-0.1", manifest["schema_version"])
        self.assertEqual(
            {"carm-playbook.json", "mgba-carm-demo.html"},
            set(manifest["files"]),
        )
        for name, digest in manifest["files"].items():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            actual = hashlib.sha256(
                (self.paths.root / name).read_bytes()
            ).hexdigest()
            self.assertEqual(digest, actual)
        self.assertEqual(
            manifest["playbook_digest"], self.playbook["playbook_digest"]
        )

    def test_playbook_structure_matches_frozen_slice(self) -> None:
        playbook = self.playbook
        self.assertEqual(DEMO_PLAYBOOK_SCHEMA, playbook["schema_version"])
        self.assertEqual(42, playbook["seed"])
        self.assertEqual(63, len(playbook["roles"]))
        self.assertEqual(set(playbook["roles"]), set(playbook["layout"]))
        self.assertEqual("baseline", playbook["observer"]["reference_condition"])
        self.assertEqual(
            "car_affinity_070",
            playbook["observer"]["default_comparison_condition"],
        )
        self.assertEqual(
            ["stress", "signal", "resource_level"],
            playbook["observer"]["field_layers"],
        )
        for position in playbook["layout"].values():
            self.assertEqual(2, len(position))
            self.assertTrue(all(0.0 <= value <= 1.0 for value in position))
        conditions = playbook["conditions"]
        self.assertEqual(
            list(EXPECTED_CONDITIONS),
            [condition["condition_id"] for condition in conditions],
        )
        for condition in conditions:
            self.assertEqual(64, len(condition["history_digest"]))
            self.assertEqual(30, len(condition["ticks"]))
            self.assertIn(
                condition["outcome"],
                {"stable", "recovered", "deteriorating", "failed"},
            )
            observed = [
                tick["t"] for tick in condition["ticks"] if tick["l4"] is not None
            ]
            self.assertEqual([1, 11, 21], observed)
            self.assertEqual(5, len(condition["terminal_l4"]))
            for tick in condition["ticks"]:
                self.assertEqual(63, len(tick["cells"]))
                self.assertEqual(set(playbook["roles"]), set(tick["cells"]))
                self.assertEqual(tick["l4_observed"], tick["l4"] is not None)
                self.assertEqual(
                    tick["audit"]["transition_count"],
                    len(tick["audit"]["layer_paths"]),
                )
        stripped = {
            key: value
            for key, value in playbook.items()
            if key != "playbook_digest"
        }
        self.assertEqual(digest_payload(stripped), playbook["playbook_digest"])

    def test_playbook_values_reconcile_with_raw_runs_and_keep_negative_baseline(
        self,
    ) -> None:
        compiled = compile_carm_scenario(
            load_carm_scenario_config(self.configs["scenario_config"])
        )
        matrix_config = load_causal_config(self.configs["matrix_config"])
        demo_config = replace(matrix_config, ablations=())
        runners = build_carm_runners(
            compiled,
            demo_config,
            runner_config=load_runner_config(self.configs["runner_config"]),
            l0_config=self.configs["l0_config"],
            l1_config=self.configs["l1_config"],
            l4_config=self.configs["l4_config"],
        )
        result = run_carm_matrix(compiled, demo_config, runners=runners)
        records = {
            (record.condition_id, record.seed): record
            for record in result.records
        }
        raw_max = records[("car_max_100", 42)].run
        conditions = {
            condition["condition_id"]: condition
            for condition in self.playbook["conditions"]
        }
        cell = conditions["car_max_100"]["ticks"][0]["cells"]["eng-mac-001"]
        raw_l0 = next(
            state for state in raw_max.ticks[0].l0 if state.cell_id == "eng-mac-001"
        )
        self.assertAlmostEqual(
            raw_l0.signal_expression, cell["l0"]["signal_expression"], delta=5e-5
        )
        self.assertAlmostEqual(
            raw_max.terminal_observation.inflammation,
            conditions["car_max_100"]["terminal_l4"]["inflammation"],
            delta=5e-5,
        )
        # The frozen negative baseline must stay visible in the demo payload:
        # the highest dose raises terminal inflammation and the burden proxy.
        self.assertGreater(
            conditions["car_max_100"]["terminal_l4"]["inflammation"],
            conditions["baseline"]["terminal_l4"]["inflammation"],
        )
        self.assertGreater(
            conditions["car_max_100"]["terminal_l4"]["damage_burden"],
            conditions["baseline"]["terminal_l4"]["damage_burden"],
        )

    def test_html_player_is_self_contained_and_honest(self) -> None:
        html = self.html
        self.assertIn("window.MGBA_PLAYBOOK", html)
        for condition_id in EXPECTED_CONDITIONS:
            self.assertIn(condition_id, html)
        self.assertIn("terminal_l4", html)
        self.assertIn("不是临床预测", html)
        self.assertIn("负面基线", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)

    def test_html_player_exposes_synchronized_comparison_and_observation_fields(
        self,
    ) -> None:
        html = self.html
        self.assertIn("双轨同步对照", html)
        self.assertIn('id="tissue-reference"', html)
        self.assertIn('id="tissue-comparison"', html)
        self.assertIn('data-field="stress"', html)
        self.assertIn("L4 终末结果对照", html)
        self.assertIn("当前 tick 审计", html)
        self.assertIn("不是连续物理场求解", html)


if __name__ == "__main__":
    unittest.main()
