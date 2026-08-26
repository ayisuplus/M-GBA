"""Contracts and crash-prevention gates for the causal CAR-M spatial L3."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from mgba.carm_spatial_experiments import (
    CarmSpatialExperimentRunner,
    SpatialRunMetrics,
    _spatial_metrics,
    build_carm_spatial_runners,
    load_carm_spatial_experiment_config,
    save_carm_spatial_artifacts,
)
from mgba.experiments import CausalRunRecord, ConditionKind
from mgba.layers import SpatialTissueState, TissueState
from mgba.runner import load_checkpoint, load_runner_config, save_checkpoint
from mgba.scenarios.carm import (
    CarmSpatialConfig,
    compile_carm_scenario,
    load_carm_scenario_config,
    load_carm_spatial_config,
)


ROOT = Path(__file__).parents[1]


class CarmSpatialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compiled = compile_carm_scenario(
            load_carm_scenario_config(
                ROOT / "configs" / "scenarios" / "carm" / "high_immune_her2.json"
            )
        )
        cls.spatial_config = load_carm_spatial_config(
            ROOT / "configs" / "layers" / "l3_carm_spatial.json"
        )
        cls.runner_config = load_runner_config(
            ROOT / "configs" / "runner_reference.json"
        )
        cls.runners = cls._build_runners()

    @classmethod
    def _build_runners(cls, spatial_config=None):
        return build_carm_spatial_runners(
            cls.compiled,
            runner_config=cls.runner_config,
            spatial_config=spatial_config or cls.spatial_config,
            l0_config=ROOT / "configs" / "layers" / "l0_reference_grn.json",
            l1_config=ROOT / "configs" / "layers" / "l1_reference_molecular.json",
            l4_config=ROOT / "configs" / "layers" / "l4_reference_phenotype.json",
        )

    def test_spatial_config_rejects_malformed_or_unstable_domains(self) -> None:
        cases = (
            ("model_version", " "),
            ("seed", -1),
            ("seed", True),
            ("grid_rows", 1),
            ("grid_columns", 1),
            ("neighbor_radius", 0.0),
            ("neighbor_radius", 2.0),
            ("movement_rate", 1.1),
            ("field_diffusion", float("nan")),
            ("node_field_coupling", -0.1),
        )
        for name, value in cases:
            with self.assertRaises(ValueError, msg=f"{name}={value}"):
                replace(self.spatial_config, **{name: value})
        self.assertIsInstance(self.spatial_config, CarmSpatialConfig)

    def test_spatial_state_is_complete_deterministic_and_causal(self) -> None:
        runner = self.runners["spatial_field"]
        first = runner.run(self.compiled.scenario, ticks=4)
        repeated = runner.run(self.compiled.scenario, ticks=4)
        self.assertEqual(first.history_digest, repeated.history_digest)
        self.assertEqual(first.checkpoint, repeated.checkpoint)
        state = first.ticks[-1].l3
        self.assertIsInstance(state, SpatialTissueState)
        self.assertEqual(63, len(state.coordinates))
        self.assertEqual(
            self.spatial_config.grid_rows * self.spatial_config.grid_columns,
            len(state.field_cells),
        )
        self.assertEqual(
            tuple(node.cell_id for node in state.nodes),
            tuple(item.cell_id for item in state.coordinates),
        )
        self.assertNotEqual(self.compiled.scenario.edges, state.edges)
        self.assertNotEqual(
            first.ticks[0].l3.coordinates, first.ticks[-1].l3.coordinates
        )
        self.assertNotEqual(
            first.ticks[0].l3.field_cells, first.ticks[-1].l3.field_cells
        )
        self.assertNotEqual(
            first.ticks[0].l3.metadata.source_digest,
            first.ticks[-1].l3.metadata.source_digest,
        )

    def test_spatial_checkpoint_round_trip_and_resume_are_exact(self) -> None:
        runner = self.runners["spatial_field"]
        complete = runner.run(self.compiled.scenario, ticks=6)
        first = runner.run(self.compiled.scenario, ticks=2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spatial-checkpoint.json"
            save_checkpoint(path, first.checkpoint)
            loaded = load_checkpoint(path)
        self.assertIsInstance(loaded.l3, SpatialTissueState)
        resumed = runner.run(
            self.compiled.scenario, ticks=4, checkpoint=loaded
        )
        self.assertEqual(complete.checkpoint, resumed.checkpoint)
        self.assertEqual(complete.history_digest, resumed.history_digest)
        self.assertEqual(complete.terminal_observation, resumed.terminal_observation)
        self.assertEqual(complete.ticks, first.ticks + resumed.ticks)

    def test_fixed_graph_baseline_serialization_remains_non_spatial(self) -> None:
        run = self.runners["fixed_graph"].run(self.compiled.scenario, ticks=2)
        self.assertIs(type(run.checkpoint.l3), TissueState)
        payload = run.checkpoint.as_dict()["l3"]
        for field in (
            "coordinates",
            "field_rows",
            "field_columns",
            "field_cells",
        ):
            self.assertNotIn(field, payload)

    def test_l0_perturbation_reaches_l4_through_spatial_runner(self) -> None:
        runner = self.runners["spatial_field"]
        baseline = runner.run(self.compiled.scenario, ticks=4)
        perturbed = runner.run(
            self.compiled.scenario,
            ticks=4,
            perturbations={
                cell_id: {"signal_expression": 0.0}
                for cell_id in self.compiled.engineered_targets
            },
        )
        self.assertNotEqual(
            baseline.terminal_observation, perturbed.terminal_observation
        )
        self.assertNotEqual(
            baseline.ticks[-1].l3.field_cells,
            perturbed.ticks[-1].l3.field_cells,
        )

    def test_paired_matrix_changes_only_l3_and_reports_spatial_metrics(self) -> None:
        config = replace(
            load_carm_spatial_experiment_config(
                ROOT / "configs" / "experiments" / "carm_spatial_comparison.json"
            ),
            ticks=3,
            seeds=(1, 2),
        )
        result = CarmSpatialExperimentRunner(
            config, runners=self.runners
        ).run(self.compiled)
        baseline_versions = dict(self.runners["fixed_graph"].model_versions)
        spatial_versions = dict(self.runners["spatial_field"].model_versions)
        changed = {
            layer
            for layer, value in spatial_versions.items()
            if value != baseline_versions[layer]
        }
        self.assertEqual({"L3"}, changed)
        self.assertEqual(4, len(result.records))
        self.assertEqual(2, len(result.comparisons))
        self.assertEqual(2, len(result.spatial_metrics))
        for metric in result.spatial_metrics:
            self.assertGreater(metric.mean_displacement, 0.0)
            self.assertGreater(metric.mean_edge_turnover, 0.0)
            self.assertGreater(metric.terminal_field_heterogeneity, 0.0)
            self.assertGreater(metric.terminal_field_gradient, 0.0)
        for comparison in result.comparisons:
            effects = dict(comparison.layer_effects)
            self.assertGreater(effects[next(layer for layer in effects if layer.value == "L3")], 0.0)
            self.assertGreater(effects[next(layer for layer in effects if layer.value == "L4")], 0.0)

    def test_checkpoint_with_partial_spatial_payload_fails_closed(self) -> None:
        checkpoint = self.runners["spatial_field"].run(
            self.compiled.scenario, ticks=2
        ).checkpoint.as_dict()
        del checkpoint["l3"]["field_cells"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "partial.json"
            path.write_text(json.dumps(checkpoint), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_checkpoint(path)
    def test_experiment_config_fields_fail_fast(self) -> None:
        config = load_carm_spatial_experiment_config(
            ROOT / "configs" / "experiments" / "carm_spatial_comparison.json"
        )
        cases = (
            {"model_version": "   "},
            {"ticks": 1},
            {"ticks": True},
            {"seeds": (1,)},
            {"seeds": (2, 1)},
            {"seeds": (1, 1)},
            {"seeds": (-1, 2)},
            {"seeds": (True, 2)},
        )
        for overrides in cases:
            with self.assertRaises(ValueError, msg=str(overrides)):
                replace(config, **overrides)

    def test_experiment_config_loader_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_carm_spatial_experiment_config(path)
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_carm_spatial_experiment_config(path)

    def test_spatial_run_metrics_fail_fast(self) -> None:
        base = dict(
            seed=1,
            mean_displacement=0.1,
            mean_edge_turnover=0.2,
            terminal_field_heterogeneity=0.3,
            terminal_field_gradient=0.4,
        )
        cases = (
            {"seed": -1},
            {"seed": True},
            {"mean_displacement": -0.1},
            {"mean_edge_turnover": float("nan")},
            {"mean_displacement": 2.0},
            {"mean_edge_turnover": 1.5},
        )
        for overrides in cases:
            with self.assertRaises(ValueError, msg=str(overrides)):
                SpatialRunMetrics(**(base | overrides))
        self.assertEqual(base, SpatialRunMetrics(**base).as_dict())

    def test_runner_construction_and_matrix_guards(self) -> None:
        with self.assertRaises(TypeError):
            build_carm_spatial_runners(
                object(),
                runner_config=self.runner_config,
                spatial_config=self.spatial_config,
                l0_config=ROOT / "configs" / "layers" / "l0_reference_grn.json",
                l1_config=(
                    ROOT / "configs" / "layers" / "l1_reference_molecular.json"
                ),
                l4_config=(
                    ROOT / "configs" / "layers" / "l4_reference_phenotype.json"
                ),
            )
        config = replace(
            load_carm_spatial_experiment_config(
                ROOT
                / "configs"
                / "experiments"
                / "carm_spatial_comparison.json"
            ),
            ticks=3,
            seeds=(1, 2),
        )
        with self.assertRaises(ValueError):
            CarmSpatialExperimentRunner(
                config, runners={"fixed_graph": self.runners["fixed_graph"]}
            )

        class _StubRunner:
            def __init__(self, model_versions, max_total_ticks) -> None:
                self.model_versions = model_versions
                self.config = SimpleNamespace(
                    max_total_ticks=max_total_ticks
                )

        fixed_versions = self.runners["fixed_graph"].model_versions
        spatial_versions = self.runners["spatial_field"].model_versions
        mismatched = tuple(
            (layer, f"{version}-mismatch" if layer == "L2" else version)
            for layer, version in fixed_versions
        )
        with self.assertRaises(ValueError):
            CarmSpatialExperimentRunner(
                config,
                runners={
                    "fixed_graph": _StubRunner(fixed_versions, 100),
                    "spatial_field": _StubRunner(mismatched, 100),
                },
            )
        with self.assertRaises(ValueError):
            CarmSpatialExperimentRunner(
                config,
                runners={
                    "fixed_graph": _StubRunner(fixed_versions, 1),
                    "spatial_field": _StubRunner(spatial_versions, 100),
                },
            )
        runner = CarmSpatialExperimentRunner(config, runners=self.runners)
        with self.assertRaises(TypeError):
            runner.run(object())

    def test_spatial_metrics_reject_non_spatial_traces(self) -> None:
        run = self.runners["fixed_graph"].run(self.compiled.scenario, ticks=2)
        record = CausalRunRecord(
            condition_id="fixed_graph",
            condition_kind=ConditionKind.BASELINE,
            seed=self.compiled.scenario.seed,
            run=run,
        )
        with self.assertRaises(TypeError):
            _spatial_metrics(record)

    def test_artifacts_persist_and_refuse_conflicts(self) -> None:
        config = replace(
            load_carm_spatial_experiment_config(
                ROOT
                / "configs"
                / "experiments"
                / "carm_spatial_comparison.json"
            ),
            ticks=3,
            seeds=(1, 2),
        )
        result = CarmSpatialExperimentRunner(
            config, runners=self.runners
        ).run(self.compiled)
        with tempfile.TemporaryDirectory() as directory:
            paths = save_carm_spatial_artifacts(directory, result)
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
            raw_files = tuple((paths["root"] / "raw").rglob("seed-*.json"))

            self.assertEqual(result.matrix_id, manifest["matrix_id"])
            self.assertEqual(result.matrix_id, summary["matrix_id"])
            self.assertEqual(
                "mgba-carm-spatial-artifact-0.1", summary["schema_version"]
            )
            self.assertEqual(4, len(raw_files))
            self.assertEqual(2, len(manifest["spatial_metrics"]))
            self.assertEqual(2, len(summary["spatial_metrics"]))
            save_carm_spatial_artifacts(directory, result)
            with self.assertRaises(ValueError):
                save_carm_spatial_artifacts(
                    directory, replace(result, scenario_digest="different")
                )
        with self.assertRaises(ValueError):
            replace(result, records=())


if __name__ == "__main__":
    unittest.main()
