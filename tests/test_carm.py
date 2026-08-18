import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from mgba.experiments import load_causal_config
from mgba.layers import LayerId, LocalEnvironment, MolecularState, StateMetadata
from mgba.reporting import build_causal_report
from mgba.runner import load_runner_config
from mgba.scenarios.carm import (
    CarmCellModel,
    CellRole,
    build_carm_runners,
    compile_carm_scenario,
    load_carm_scenario_config,
    run_carm_matrix,
    save_carm_artifacts,
)


class CarmScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).parents[1]
        cls.config_path = (
            cls.root / "configs" / "scenarios" / "carm" / "high_immune_her2.json"
        )
        cls.config = load_carm_scenario_config(cls.config_path)
        cls.compiled = compile_carm_scenario(cls.config)

    def test_frozen_scenario_has_complete_roles_and_topology(self) -> None:
        compiled = self.compiled
        self.assertEqual(63, len(compiled.roles))
        self.assertEqual(63, len(compiled.scenario.genomes))
        self.assertEqual(15, len(compiled.engineered_targets))
        self.assertEqual(298, len(compiled.scenario.edges))
        self.assertEqual(
            {
                CellRole.ENGINEERED_MACROPHAGE,
                CellRole.WILD_TYPE_MACROPHAGE,
                CellRole.TUMOR,
                CellRole.CD8_T_CELL,
            },
            set(compiled.role_map.values()),
        )
        self.assertEqual(
            compiled.scenario.edges, tuple(sorted(set(compiled.scenario.edges)))
        )
        self.assertTrue(
            all(source != target for source, target in compiled.scenario.edges)
        )
        self.assertGreater(compiled.environment_stress, 0.0)
        self.assertGreater(compiled.incoming_signal, 0.0)

    def test_engineered_identity_does_not_change_cell_rules_without_l0_signal(self) -> None:
        profile_digest = self.compiled.profile_digest
        model = CarmCellModel(
            self.config.cell_model,
            roles=(
                ("eng", CellRole.ENGINEERED_MACROPHAGE),
                ("wt", CellRole.WILD_TYPE_MACROPHAGE),
            ),
            source_profile_digest=profile_digest,
        )

        def inputs(cell_id: str):
            metadata = StateMetadata(1, "test-input-0.1", "digest")
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

        eng = model.step(*inputs("eng"), previous_state=None, logical_time=1)
        wt = model.step(*inputs("wt"), previous_state=None, logical_time=1)
        self.assertEqual(eng[0].phase, wt[0].phase)
        self.assertEqual(eng[0].activation, wt[0].activation)
        self.assertEqual(eng[0].viability, wt[0].viability)
        self.assertEqual(eng[1].secretion, wt[1].secretion)
        self.assertEqual(eng[1].repair_effort, wt[1].repair_effort)

    def test_invalid_legacy_antigen_fails_closed(self) -> None:
        raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        raw["car_design"]["target_antigen"] = "CD47"
        with tempfile.TemporaryDirectory() as directory:
            temp_root = Path(directory)
            config_path = temp_root / "scenario.json"
            profile_path = temp_root / "profile.json"
            profile_path.write_text(
                (self.root / "data" / "carm" / "tcga_brca_high_immune.json").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )
            raw["cohort_profile"] = "profile.json"
            config_path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_carm_scenario_config(config_path)


class CarmExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).parents[1]
        cls.compiled = compile_carm_scenario(
            load_carm_scenario_config(
                cls.root
                / "configs"
                / "scenarios"
                / "carm"
                / "high_immune_her2.json"
            )
        )
        cls.matrix_config = load_causal_config(
            cls.root / "configs" / "experiments" / "carm_vertical_slice.json"
        )
        cls.runners = cls._runners(cls.matrix_config)
        cls.matrix = run_carm_matrix(
            cls.compiled, cls.matrix_config, runners=cls.runners
        )

    @classmethod
    def _runners(cls, matrix_config):
        return build_carm_runners(
            cls.compiled,
            matrix_config,
            runner_config=load_runner_config(
                cls.root / "configs" / "runner_reference.json"
            ),
            l0_config=cls.root / "configs" / "layers" / "l0_reference_grn.json",
            l1_config=(
                cls.root / "configs" / "layers" / "l1_reference_molecular.json"
            ),
            l4_config=(
                cls.root / "configs" / "layers" / "l4_reference_phenotype.json"
            ),
        )

    def test_frozen_matrix_has_21_runs_and_traceable_doses(self) -> None:
        self.assertEqual(21, len(self.matrix.records))
        self.assertEqual(18, len(self.matrix.comparisons))
        self.assertEqual(6, len(self.matrix.summaries))
        comparisons = {
            item.condition_id: item
            for item in self.matrix.comparisons
            if item.seed == 42
        }
        affinity = comparisons["car_affinity_070"]
        maximum = comparisons["car_max_100"]
        for comparison in (affinity, maximum):
            self.assertTrue(
                all(value > 0.0 for _, value in comparison.layer_effects)
            )
            self.assertTrue(
                all(value is not None for _, value in comparison.propagation_ticks)
            )
        for layer in LayerId:
            self.assertGreater(
                dict(maximum.layer_effects)[layer],
                dict(affinity.layer_effects)[layer],
            )
        record = next(
            item
            for item in self.matrix.records
            if item.condition_id == "car_affinity_070" and item.seed == 42
        )
        first_events = record.run.ticks[0].l0_perturbation_events
        self.assertEqual(15, len(first_events))
        self.assertEqual(
            set(self.compiled.engineered_targets),
            {event.cell_id for event in first_events},
        )

    def test_ablations_change_only_the_named_layer(self) -> None:
        baseline_versions = dict(self.runners["baseline"].model_versions)
        expected = {"l1_static": "L1", "l2_static": "L2", "l3_static": "L3"}
        for variant, target in expected.items():
            changed = {
                layer
                for layer, version in dict(self.runners[variant].model_versions).items()
                if version != baseline_versions[layer]
            }
            self.assertEqual({target}, changed)

    def test_carm_checkpoint_resume_is_exact(self) -> None:
        runner = self.runners["baseline"]
        complete = runner.run(self.compiled.scenario, ticks=6)
        first = runner.run(self.compiled.scenario, ticks=2)
        resumed = runner.run(
            self.compiled.scenario, ticks=4, checkpoint=first.checkpoint
        )
        self.assertEqual(complete.checkpoint, resumed.checkpoint)
        self.assertEqual(complete.history_digest, resumed.history_digest)
        self.assertEqual(complete.terminal_observation, resumed.terminal_observation)

    def test_reduced_matrix_rebuilds_report_from_raw_runs(self) -> None:
        reduced = replace(
            self.matrix_config,
            ticks=3,
            seeds=(1, 2),
            perturbations=self.matrix_config.perturbations[:2],
            ablations=("l3_static",),
        )
        matrix = run_carm_matrix(
            self.compiled, reduced, runners=self._runners(reduced)
        )
        with tempfile.TemporaryDirectory() as directory:
            artifacts = save_carm_artifacts(directory, matrix, self.compiled)
            report = build_causal_report(artifacts.causal.root)
            provenance = artifacts.provenance.read_text(encoding="utf-8")
            html = report.html.read_text(encoding="utf-8")

            self.assertTrue(report.manifest.is_file())
            self.assertNotIn("sample_id", provenance)
            self.assertIn("car_off_000", html)
            self.assertNotIn("Complete repair knockdown", html)


if __name__ == "__main__":
    unittest.main()
