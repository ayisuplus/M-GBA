"""Tests for the de-identified CAR-M L3 spatial-anchor contract."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from mgba.cli import main as cli_main
from mgba.carm_spatial_experiments import build_carm_spatial_runners
from mgba.experiment import digest_payload
from mgba.runner import load_runner_config
from mgba.scenarios.carm import (
    compile_carm_scenario,
    load_carm_scenario_config,
    load_carm_spatial_config,
)
from mgba.spatial_anchor_evaluation import (
    SpatialAnchorEvaluator,
    load_spatial_anchor_evaluation_config,
    save_spatial_anchor_evaluation_artifacts,
)
from mgba.spatial_anchors import (
    OBSERVATION_SCHEMA_VERSION,
    TARGET_SCHEMA_VERSION,
    build_spatial_anchor_profile,
    load_spatial_anchor_protocol,
    load_spatial_observation_bundle,
    project_spatial_tissue_state,
    save_spatial_anchor_profile,
    score_spatial_projection,
    verify_spatial_anchor_target,
)


ROOT = Path(__file__).parents[1]
PROTOCOL_PATH = ROOT / "configs" / "experiments" / "carm_spatial_anchor_protocol.json"
EVALUATION_PATH = (
    ROOT / "configs" / "experiments" / "carm_spatial_anchor_evaluation.json"
)


def _source(file_id: str = "source") -> dict:
    return {
        "file_id": file_id,
        "sha256": ("a" if file_id == "source" else "b") * 64,
        "bytes": 1234,
        "license": "unit-test license",
        "rights_verified": True,
    }


def _field_bundle_payload(*, reverse: bool = False) -> dict:
    samples = []
    for sample_index in range(6):
        observations = []
        for row in range(3):
            for column in range(3):
                stress = (row + column + sample_index) / 9.0
                observations.append(
                    {
                        "observation_id": f"private-spot-{sample_index}-{row}-{column}",
                        "x": column / 2.0,
                        "y": row / 2.0,
                        "region": "core" if column < 1 else "rim",
                        "channels": {
                            "stress": stress,
                            "resource": 1.0 - stress * 0.5,
                            "signal": (row * 2 + column + sample_index) / 11.0,
                        },
                    }
                )
        samples.append(
            {
                "sample_id": f"private-field-sample-{sample_index}",
                "observations": list(reversed(observations)) if reverse else observations,
            }
        )
    return {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "dataset_id": "wu-swarbrick-brca-visium",
        "modality": "field",
        "source_artifacts": [_source()],
        "samples": list(reversed(samples)) if reverse else samples,
    }


def _neighborhood_bundle_payload(*, reverse: bool = False) -> dict:
    layouts = (
        (
            (0.10, 0.10, "immune"),
            (0.18, 0.12, "tumor"),
            (0.25, 0.16, "tumor"),
            (0.70, 0.70, "immune"),
            (0.76, 0.72, "tumor"),
            (0.50, 0.50, "other"),
        ),
        (
            (0.12, 0.80, "immune"),
            (0.18, 0.76, "tumor"),
            (0.40, 0.50, "other"),
            (0.55, 0.48, "tumor"),
            (0.82, 0.18, "immune"),
            (0.78, 0.24, "tumor"),
        ),
    )
    samples = []
    for sample_index, layout in enumerate(layouts):
        observations = [
            {
                "observation_id": f"private-cell-{sample_index}-{index}",
                "x": x,
                "y": y,
                "label": label,
            }
            for index, (x, y, label) in enumerate(layout)
        ]
        samples.append(
            {
                "sample_id": f"private-image-{sample_index}",
                "observations": list(reversed(observations)) if reverse else observations,
            }
        )
    return {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "dataset_id": "jackson-brca-imc",
        "modality": "neighborhood",
        "source_artifacts": [_source("locations")],
        "samples": list(reversed(samples)) if reverse else samples,
    }


def _write(directory: Path, name: str, payload: dict) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _load_fixture_bundles(directory: Path, *, reverse: bool = False):
    field = load_spatial_observation_bundle(
        _write(directory, "field.json", _field_bundle_payload(reverse=reverse))
    )
    neighborhood = load_spatial_observation_bundle(
        _write(
            directory,
            "neighborhood.json",
            _neighborhood_bundle_payload(reverse=reverse),
        )
    )
    return field, neighborhood


class SpatialAnchorProtocolTests(unittest.TestCase):
    def test_shipped_protocol_freezes_the_preregistered_split_and_metrics(self) -> None:
        protocol = load_spatial_anchor_protocol(PROTOCOL_PATH)
        self.assertEqual(6, protocol.expected_field_samples)
        self.assertEqual(4, protocol.field_calibration_count)
        self.assertEqual(4, protocol.field_knn_k)
        self.assertEqual(2.0, protocol.neighborhood_radius_factor)
        self.assertEqual(0.5, protocol.model_tumor_region_quantile)

    def test_protocol_fails_fast_on_leakage_or_unusable_domains(self) -> None:
        protocol = load_spatial_anchor_protocol(PROTOCOL_PATH)
        with self.assertRaises(ValueError):
            replace(protocol, neighborhood_dataset_id=protocol.field_dataset_id)
        with self.assertRaises(ValueError):
            replace(protocol, field_calibration_count=6)
        with self.assertRaises(ValueError):
            replace(protocol, field_knn_k=1)
        with self.assertRaises(ValueError):
            replace(protocol, neighborhood_radius_factor=10.0)
        with self.assertRaises(ValueError):
            replace(protocol, model_tumor_region_quantile=1.0)


class ObservationBundleTests(unittest.TestCase):
    def test_bundle_identity_is_independent_of_input_order(self) -> None:
        with tempfile.TemporaryDirectory() as left_tmp, tempfile.TemporaryDirectory() as right_tmp:
            left = _load_fixture_bundles(Path(left_tmp), reverse=False)
            right = _load_fixture_bundles(Path(right_tmp), reverse=True)
            self.assertEqual(left[0].input_digest, right[0].input_digest)
            self.assertEqual(left[1].input_digest, right[1].input_digest)

    def test_unknown_fields_unverified_rights_and_duplicate_coordinates_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unknown = _field_bundle_payload()
            unknown["surprise"] = True
            with self.assertRaises(ValueError):
                load_spatial_observation_bundle(_write(root, "unknown.json", unknown))

            rights = _field_bundle_payload()
            rights["source_artifacts"][0]["rights_verified"] = False
            with self.assertRaises(ValueError):
                load_spatial_observation_bundle(_write(root, "rights.json", rights))

            duplicate = _field_bundle_payload()
            duplicate["samples"][0]["observations"][1]["x"] = 0.0
            duplicate["samples"][0]["observations"][1]["y"] = 0.0
            with self.assertRaises(ValueError):
                load_spatial_observation_bundle(
                    _write(root, "duplicate.json", duplicate)
                )


class SpatialAnchorProfileTests(unittest.TestCase):
    def _build(self, directory: Path, *, reverse: bool = False):
        field, neighborhood = _load_fixture_bundles(directory, reverse=reverse)
        return build_spatial_anchor_profile(
            load_spatial_anchor_protocol(PROTOCOL_PATH),
            field_bundle=field,
            neighborhood_bundle=neighborhood,
        )

    def test_profile_has_frozen_roles_and_no_raw_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._build(Path(tmp))
            roles = [item.role for item in profile.samples]
            self.assertEqual(4, roles.count("calibration"))
            self.assertEqual(2, roles.count("holdout"))
            self.assertEqual(2, roles.count("external_validation"))
            encoded = json.dumps(profile.as_dict(), sort_keys=True)
            self.assertNotIn("private-field-sample", encoded)
            self.assertNotIn("private-image", encoded)
            self.assertNotIn("private-spot", encoded)
            self.assertNotIn("private-cell", encoded)
            self.assertNotIn("file_id", encoded)

    def test_field_metrics_cover_every_preregistered_channel_and_measure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._build(Path(tmp))
            sample = next(item for item in profile.samples if item.modality == "field")
            names = {name for name, _ in sample.metrics}
            self.assertEqual(15, len(names))
            for channel in ("stress", "resource", "signal"):
                for measure in (
                    "cv",
                    "gradient_q50",
                    "gradient_q95",
                    "morans_i",
                    "region_variance_fraction",
                ):
                    self.assertIn(f"field.{channel}.{measure}", names)
            self.assertTrue(all(math.isfinite(value) for _, value in sample.metrics))

    def test_neighborhood_metrics_are_scale_normalized_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._build(Path(tmp))
            sample = next(
                item for item in profile.samples if item.modality == "neighborhood"
            )
            metrics = dict(sample.metrics)
            self.assertEqual(9, len(metrics))
            self.assertGreater(metrics["neighborhood.degree_mean"], 0.0)
            self.assertGreaterEqual(
                metrics["neighborhood.cross_type_adjacency_enrichment"], 0.0
            )
            for name in (
                "neighborhood.adjacency_radius",
                "neighborhood.immune_tumor_distance_q25",
                "neighborhood.immune_tumor_distance_q50",
                "neighborhood.immune_tumor_distance_q75",
                "neighborhood.mixing_score",
            ):
                self.assertGreaterEqual(metrics[name], 0.0)
                self.assertLessEqual(metrics[name], 1.0)

    def test_profile_is_deterministic_under_bundle_reordering(self) -> None:
        with tempfile.TemporaryDirectory() as left_tmp, tempfile.TemporaryDirectory() as right_tmp:
            left = self._build(Path(left_tmp), reverse=False)
            right = self._build(Path(right_tmp), reverse=True)
            self.assertEqual(left.target_id, right.target_id)
            self.assertEqual(left.as_dict(), right.as_dict())

    def test_protocol_dataset_and_sample_count_mismatches_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            field, neighborhood = _load_fixture_bundles(root)
            protocol = load_spatial_anchor_protocol(PROTOCOL_PATH)
            with self.assertRaises(ValueError):
                build_spatial_anchor_profile(
                    replace(protocol, field_dataset_id="wrong"),
                    field_bundle=field,
                    neighborhood_bundle=neighborhood,
                )
            with self.assertRaises(ValueError):
                build_spatial_anchor_profile(
                    replace(protocol, expected_field_samples=7),
                    field_bundle=field,
                    neighborhood_bundle=neighborhood,
                )

    def test_target_save_verify_idempotence_tamper_and_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = self._build(root)
            output = root / "derived" / "target.json"
            save_spatial_anchor_profile(output, profile)
            save_spatial_anchor_profile(output, profile)
            verified = verify_spatial_anchor_target(output)
            self.assertEqual(TARGET_SCHEMA_VERSION, verified["schema_version"])
            self.assertEqual(profile.target_id, verified["target_id"])

            other = build_spatial_anchor_profile(
                replace(profile.protocol, split_salt="other-frozen-salt"),
                field_bundle=_load_fixture_bundles(root)[0],
                neighborhood_bundle=_load_fixture_bundles(root)[1],
            )
            with self.assertRaises(ValueError):
                save_spatial_anchor_profile(output, other)

            payload = json.loads(output.read_text(encoding="utf-8"))
            payload["samples"][0]["metrics"][next(iter(payload["samples"][0]["metrics"]))] += 0.1
            output.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_spatial_anchor_target(output)

    def test_checker_rejects_self_consistent_leakage_and_derived_tampering(self) -> None:
        def resign(payload: dict) -> None:
            core = dict(payload)
            core.pop("target_id", None)
            payload["target_id"] = f"spatial-anchor-{digest_payload(core)[:16]}"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = self._build(root).as_dict()

            leaked = json.loads(json.dumps(payload))
            leaked["samples"][0]["sample_id"] = "forbidden-public-id"
            resign(leaked)
            leaked_path = _write(root, "leaked.json", leaked)
            with self.assertRaises(ValueError):
                verify_spatial_anchor_target(leaked_path)

            inconsistent = json.loads(json.dumps(payload))
            inconsistent["distributions"][0]["mean"] += 0.1
            resign(inconsistent)
            inconsistent_path = _write(root, "inconsistent.json", inconsistent)
            with self.assertRaises(ValueError):
                verify_spatial_anchor_target(inconsistent_path)

            unlicensed = json.loads(json.dumps(payload))
            unlicensed["sources"][0]["artifacts"][0]["rights_verified"] = False
            resign(unlicensed)
            unlicensed_path = _write(root, "unlicensed.json", unlicensed)
            with self.assertRaises(ValueError):
                verify_spatial_anchor_target(unlicensed_path)

    def test_aggregate_target_cannot_be_written_under_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = self._build(root)
            with self.assertRaises(ValueError):
                save_spatial_anchor_profile(root / "raw" / "target.json", profile)

    def test_cli_build_and_check_use_the_same_verified_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            field = _write(root, "field-cli.json", _field_bundle_payload())
            neighborhood = _write(
                root, "neighborhood-cli.json", _neighborhood_bundle_payload()
            )
            output = root / "derived" / "target.json"
            stdout = StringIO()
            with patch(
                "sys.argv",
                [
                    "mgba",
                    "spatial-anchor-build",
                    "--protocol",
                    str(PROTOCOL_PATH),
                    "--field-bundle",
                    str(field),
                    "--neighborhood-bundle",
                    str(neighborhood),
                    "--output",
                    str(output),
                ],
            ), redirect_stdout(stdout):
                cli_main()
            built = json.loads(stdout.getvalue())
            self.assertTrue(output.exists())

            stdout = StringIO()
            with patch(
                "sys.argv",
                ["mgba", "spatial-anchor-check", "--target", str(output)],
            ), redirect_stdout(stdout):
                cli_main()
            checked = json.loads(stdout.getvalue())
            self.assertTrue(checked["ok"])
            self.assertEqual(built["target_id"], checked["target_id"])


class SpatialModelProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.protocol = load_spatial_anchor_protocol(PROTOCOL_PATH)
        cls.compiled = compile_carm_scenario(
            load_carm_scenario_config(
                ROOT / "configs" / "scenarios" / "carm" / "high_immune_her2.json"
            )
        )
        cls.runners = build_carm_spatial_runners(
            cls.compiled,
            runner_config=load_runner_config(
                ROOT / "configs" / "runner_reference.json"
            ),
            spatial_config=load_carm_spatial_config(
                ROOT / "configs" / "layers" / "l3_carm_spatial.json"
            ),
            l0_config=ROOT / "configs" / "layers" / "l0_reference_grn.json",
            l1_config=ROOT
            / "configs"
            / "layers"
            / "l1_reference_molecular.json",
            l4_config=ROOT / "configs" / "layers" / "l4_reference_phenotype.json",
        )
        cls.run_two = cls.runners["spatial_field"].run(
            cls.compiled.scenario, ticks=2
        )
        cls.run_three = cls.runners["spatial_field"].run(
            cls.compiled.scenario, ticks=3
        )

    @classmethod
    def _projection(cls, run):
        return project_spatial_tissue_state(
            run.ticks[-1].l3,
            roles=cls.compiled.roles,
            protocol=cls.protocol,
        )

    def _target(self, directory: Path) -> dict:
        field, neighborhood = _load_fixture_bundles(directory)
        return build_spatial_anchor_profile(
            self.protocol,
            field_bundle=field,
            neighborhood_bundle=neighborhood,
        ).as_dict()

    def test_formal_spatial_state_projects_to_all_24_target_metrics(self) -> None:
        projection = self._projection(self.run_two)
        metrics = dict(projection.metrics)
        self.assertEqual(24, len(metrics))
        self.assertTrue(all(math.isfinite(value) for value in metrics.values()))
        self.assertEqual(
            self.run_two.ticks[-1].l3.metadata.source_digest,
            projection.source_digest,
        )
        self.assertEqual(
            self.run_two.ticks[-1].l3.metadata.model_version,
            projection.model_version,
        )

    def test_projection_is_deterministic_sensitive_and_role_guarded(self) -> None:
        first = self._projection(self.run_two)
        repeated = self._projection(self.run_two)
        later = self._projection(self.run_three)
        self.assertEqual(first, repeated)
        self.assertNotEqual(first.metrics, later.metrics)
        with self.assertRaises(ValueError):
            project_spatial_tissue_state(
                self.run_two.ticks[-1].l3,
                roles=self.compiled.roles[:-1],
                protocol=self.protocol,
            )

    def test_score_covers_calibration_holdout_and_cross_modal_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            score = score_spatial_projection(
                self._projection(self.run_two), self._target(Path(tmp))
            )
        self.assertEqual(39, len(score.comparisons))
        scores = {item.role: item for item in score.role_scores}
        self.assertEqual(15, scores["calibration"].metric_count)
        self.assertEqual(15, scores["holdout"].metric_count)
        self.assertEqual(9, scores["external_validation"].metric_count)
        self.assertTrue(
            all(math.isfinite(item.mean_normalized_absolute_error) for item in scores.values())
        )
        repeated = score_spatial_projection(
            self._projection(self.run_two), self._target_from_new_temp()
        )
        self.assertEqual(score.score_id, repeated.score_id)

    def _target_from_new_temp(self) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            return self._target(Path(tmp))

    def test_score_rejects_incomplete_or_wrong_role_target_space(self) -> None:
        target = self._target_from_new_temp()
        target["distributions"].pop()
        with self.assertRaises(ValueError):
            score_spatial_projection(self._projection(self.run_two), target)

        target = self._target_from_new_temp()
        target["distributions"][0]["role"] = "external_validation"
        with self.assertRaises(ValueError):
            score_spatial_projection(self._projection(self.run_two), target)

    def test_evaluation_config_and_runner_produce_a_traceable_target_score(self) -> None:
        shipped = load_spatial_anchor_evaluation_config(EVALUATION_PATH)
        self.assertEqual(20, shipped.ticks)
        with self.assertRaises(ValueError):
            replace(shipped, ticks=1)
        with self.assertRaises(ValueError):
            replace(shipped, scenario_seed=-1)

        evaluator = SpatialAnchorEvaluator(
            replace(shipped, ticks=2),
            runner=self.runners["spatial_field"],
            protocol=self.protocol,
        )
        target = self._target_from_new_temp()
        first = evaluator.evaluate(self.compiled, target=target)
        repeated = evaluator.evaluate(self.compiled, target=target)
        self.assertEqual(first.evaluation_id, repeated.evaluation_id)
        self.assertEqual(first.run.history_digest, repeated.run.history_digest)
        self.assertEqual(first.score.score_id, repeated.score.score_id)
        self.assertEqual(39, len(first.score.comparisons))
        self.assertEqual(
            first.run.ticks[-1].l3.metadata.source_digest,
            first.projection.source_digest,
        )

    def test_evaluation_artifacts_are_complete_idempotent_and_tamper_refusing(self) -> None:
        evaluator = SpatialAnchorEvaluator(
            replace(load_spatial_anchor_evaluation_config(EVALUATION_PATH), ticks=2),
            runner=self.runners["spatial_field"],
            protocol=self.protocol,
        )
        result = evaluator.evaluate(
            self.compiled, target=self._target_from_new_temp()
        )
        with tempfile.TemporaryDirectory() as tmp:
            paths = save_spatial_anchor_evaluation_artifacts(tmp, result)
            repeated = save_spatial_anchor_evaluation_artifacts(tmp, result)
            self.assertEqual(paths, repeated)
            self.assertTrue(paths["run"].exists())
            self.assertTrue(paths["manifest"].exists())
            self.assertTrue(paths["summary"].exists())
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            self.assertEqual(result.target_id, manifest["target_id"])
            self.assertEqual(result.run.history_digest, manifest["run"]["history_digest"])
            manifest["score_id"] = "tampered"
            paths["manifest"].write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                save_spatial_anchor_evaluation_artifacts(tmp, result)

    def test_evaluation_cli_rebuilds_the_same_score_and_writes_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            field, neighborhood = _load_fixture_bundles(root)
            profile = build_spatial_anchor_profile(
                self.protocol,
                field_bundle=field,
                neighborhood_bundle=neighborhood,
            )
            target_path = save_spatial_anchor_profile(
                root / "derived" / "target.json", profile
            )
            evaluation_config = root / "evaluation.json"
            evaluation_config.write_text(
                json.dumps(
                    {
                        "model_version": "test-spatial-anchor-evaluation",
                        "ticks": 2,
                        "scenario_seed": 42,
                    }
                ),
                encoding="utf-8",
            )
            stdout = StringIO()
            artifact_root = root / "artifacts"
            with patch(
                "sys.argv",
                [
                    "mgba",
                    "carm-spatial-anchor-evaluate",
                    "--target",
                    str(target_path),
                    "--protocol",
                    str(PROTOCOL_PATH),
                    "--evaluation-config",
                    str(evaluation_config),
                    "--config",
                    str(
                        ROOT
                        / "configs"
                        / "scenarios"
                        / "carm"
                        / "high_immune_her2.json"
                    ),
                    "--runner-config",
                    str(ROOT / "configs" / "runner_reference.json"),
                    "--spatial-config",
                    str(ROOT / "configs" / "layers" / "l3_carm_spatial.json"),
                    "--l0-config",
                    str(ROOT / "configs" / "layers" / "l0_reference_grn.json"),
                    "--l1-config",
                    str(
                        ROOT
                        / "configs"
                        / "layers"
                        / "l1_reference_molecular.json"
                    ),
                    "--l4-config",
                    str(
                        ROOT
                        / "configs"
                        / "layers"
                        / "l4_reference_phenotype.json"
                    ),
                    "--artifact-root",
                    str(artifact_root),
                ],
            ), redirect_stdout(stdout):
                cli_main()
            payload = json.loads(stdout.getvalue())
            self.assertEqual(profile.target_id, payload["target_id"])
            self.assertTrue(Path(payload["artifact_manifest"]).exists())
            self.assertEqual(39, len(payload["score"]["comparisons"]))


if __name__ == "__main__":
    unittest.main()
