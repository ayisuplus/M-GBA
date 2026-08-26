import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from mgba.scenarios.carm import build_carm_profile, load_carm_profile, save_carm_profile
from mgba.scenarios.carm.data import (
    PROFILE_SCHEMA_VERSION,
    CarmCohortProfile,
    SourceArtifact,
)


class CarmDataImportTests(unittest.TestCase):
    @staticmethod
    def _write_legacy_fixture(root: Path) -> None:
        immune_types = [
            "T_cells_CD8",
            "Macrophages_M1",
            "Macrophages_M2",
            *(f"immune_{index:02d}" for index in range(19)),
        ]
        counts = {"high_immune": 323, "low_immune": 273, "normal": 156}
        records = []
        sample_index = 0
        for subtype, count in counts.items():
            for _ in range(count):
                sample_index += 1
                base = {
                    "high_immune": 0.6,
                    "low_immune": 0.2,
                    "normal": 0.4,
                }[subtype]
                records.append(
                    {
                        "sample_id": f"sample-{sample_index:04d}",
                        "immune_infiltration": [base] * len(immune_types),
                        "immune_subtype": subtype,
                        "subtype_probs": [0.2, 0.3, 0.5],
                        "survival_risk": 0.5,
                    }
                )
        predictions = {
            "metadata": {
                "cancer_type": "TCGA-BRCA",
                "n_samples": 752,
                "n_genes": 5000,
                "model": "GAT-2layer-4heads",
                "backend": "numpy",
                "cv_scores": {
                    "auc": 0.78,
                    "accuracy": 0.57,
                    "f1": 0.54,
                    "auc_risk": 0.47,
                },
            },
            "predictions": records,
            "immune_cell_types": immune_types,
        }
        graph = {
            "n_nodes": 5000,
            "n_edges": 12000,
            "source": "string",
        }
        scenarios = [
            {
                "name": "high immune",
                "car_design": {"targetAntigen": "HER2", "affinity": 7},
                "tcga_source": {"subtype": "high_immune", "sample_count": 45},
            }
        ]
        for name, payload in (
            ("tcga_predictions.json", predictions),
            ("tcga_graph_info.json", graph),
            ("tcga_patient_scenarios.json", scenarios),
        ):
            (root / name).write_text(json.dumps(payload), encoding="utf-8")

    def test_import_recounts_subtypes_and_removes_sample_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_legacy_fixture(root)
            profile = build_carm_profile(root)
            output = root / "aggregate.json"
            save_carm_profile(output, profile)
            text = output.read_text(encoding="utf-8")

            self.assertEqual(752, profile.total_sample_count)
            self.assertEqual(323, profile.sample_count)
            self.assertEqual(
                {"high_immune": 323, "low_immune": 273, "normal": 156},
                dict(profile.subtype_counts),
            )
            self.assertEqual(22, len(profile.mean_immune_infiltration))
            self.assertEqual(45, profile.legacy_reported_sample_count)
            self.assertNotIn("sample_id", text)
            self.assertNotIn("sample-0001", text)

    def test_source_change_changes_the_recorded_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_legacy_fixture(root)
            first = build_carm_profile(root)
            graph_path = root / "tcga_graph_info.json"
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            graph["n_edges"] += 1
            graph_path.write_text(json.dumps(graph), encoding="utf-8")
            second = build_carm_profile(root)

            self.assertNotEqual(first.source_artifacts, second.source_artifacts)
            self.assertEqual(first.mean_immune_infiltration, second.mean_immune_infiltration)


def _valid_profile_kwargs() -> dict:
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "cohort_id": "tcga_brca_high_immune",
        "cancer_type": "TCGA-BRCA",
        "immune_subtype": "high_immune",
        "total_sample_count": 6,
        "sample_count": 3,
        "subtype_counts": (
            ("high_immune", 3),
            ("low_immune", 2),
            ("normal", 1),
        ),
        "mean_immune_infiltration": (("B_cells", 0.5), ("T_cells_CD8", 0.25)),
        "source_model": "GAT-2layer-4heads",
        "source_backend": "numpy",
        "subtype_accuracy": 0.57,
        "survival_auc": 0.47,
        "graph_source": "string",
        "graph_node_count": 5000,
        "graph_edge_count": 12000,
        "legacy_preset_name": "high immune",
        "legacy_reported_sample_count": 45,
        "source_artifacts": (
            SourceArtifact("a.json", "a" * 64),
            SourceArtifact("b.json", "b" * 64),
        ),
        "proxy_label_notice": "proxy labels, not clinical ground truth",
    }


class SourceArtifactValidationTests(unittest.TestCase):
    def test_rejects_blank_name(self) -> None:
        with self.assertRaises(ValueError):
            SourceArtifact("   ", "a" * 64)

    def test_rejects_malformed_sha256(self) -> None:
        for digest in ("abcd", "A" * 64, "g" * 64):
            with self.subTest(digest=digest[:8]):
                with self.assertRaises(ValueError):
                    SourceArtifact("artifact.json", digest)


class CarmCohortProfileValidationTests(unittest.TestCase):
    def test_valid_kwargs_construct(self) -> None:
        profile = CarmCohortProfile(**_valid_profile_kwargs())
        self.assertEqual({"B_cells": 0.5, "T_cells_CD8": 0.25}, profile.infiltration)

    def test_rejects_invalid_fields(self) -> None:
        base = CarmCohortProfile(**_valid_profile_kwargs())
        cases = {
            "schema_version pin": {"schema_version": "other-schema"},
            "blank cohort_id": {"cohort_id": "  "},
            "blank proxy notice": {"proxy_label_notice": ""},
            "unknown immune subtype": {"immune_subtype": "bcell"},
            "zero total samples": {"total_sample_count": 0},
            "zero selected samples": {"sample_count": 0},
            "selected exceeds total": {"sample_count": 7},
            "zero legacy reported count": {"legacy_reported_sample_count": 0},
            "zero graph nodes": {"graph_node_count": 0},
            "zero graph edges": {"graph_edge_count": 0},
            "accuracy above one": {"subtype_accuracy": 1.5},
            "accuracy NaN": {"subtype_accuracy": math.nan},
            "negative survival auc": {"survival_auc": -0.1},
            "subtype keyset incomplete": {
                "subtype_counts": (("high_immune", 3), ("normal", 3))
            },
            "subtype sum mismatch": {
                "subtype_counts": (
                    ("high_immune", 3),
                    ("low_immune", 2),
                    ("normal", 2),
                )
            },
            "selected count mismatch": {
                "subtype_counts": (
                    ("high_immune", 4),
                    ("low_immune", 1),
                    ("normal", 1),
                )
            },
            "empty infiltration": {"mean_immune_infiltration": ()},
            "unsorted infiltration": {
                "mean_immune_infiltration": (("T_cells_CD8", 0.25), ("B_cells", 0.5))
            },
            "duplicate infiltration names": {
                "mean_immune_infiltration": (("B_cells", 0.5), ("B_cells", 0.25))
            },
            "infiltration out of range": {
                "mean_immune_infiltration": (("B_cells", 1.5),)
            },
            "empty source artifacts": {"source_artifacts": ()},
            "unsorted source artifacts": {
                "source_artifacts": (
                    SourceArtifact("b.json", "b" * 64),
                    SourceArtifact("a.json", "a" * 64),
                )
            },
            "duplicate source artifacts": {
                "source_artifacts": (
                    SourceArtifact("a.json", "a" * 64),
                    SourceArtifact("a.json", "b" * 64),
                )
            },
        }
        for name, overrides in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(ValueError):
                    replace(base, **overrides)


class LegacyTreeRejectionTests(unittest.TestCase):
    @staticmethod
    def _stage(root: Path) -> None:
        CarmDataImportTests._write_legacy_fixture(root)

    @staticmethod
    def _overwrite(root: Path, name: str, payload: object) -> None:
        (root / name).write_text(json.dumps(payload), encoding="utf-8")

    def _assert_rejected(self, action, subtype: str = "high_immune") -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._stage(root)
            action(root)
            with self.assertRaises(ValueError):
                build_carm_profile(root, immune_subtype=subtype)

    def _mutate_predictions(self, mutate, subtype: str = "high_immune") -> None:
        def action(root: Path) -> None:
            path = root / "tcga_predictions.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            mutate(payload)
            self._overwrite(root, "tcga_predictions.json", payload)

        self._assert_rejected(action, subtype=subtype)

    def test_unreadable_file_is_wrapped_as_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._stage(root)
            (root / "tcga_graph_info.json").unlink()
            with self.assertRaises(ValueError):
                build_carm_profile(root)

    def test_malformed_json_is_wrapped_as_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._stage(root)
            (root / "tcga_predictions.json").write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_carm_profile(root)

    def test_nested_app_public_layout_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "app" / "public" / "data" / "tcga"
            nested.mkdir(parents=True)
            self._stage(nested)
            profile = build_carm_profile(root)
            self.assertEqual(752, profile.total_sample_count)

    def test_empty_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                build_carm_profile(Path(directory))

    def test_unknown_subtype_is_rejected_upfront(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                build_carm_profile(Path(directory), immune_subtype="bcell")

    def test_prediction_and_graph_roots_must_be_objects(self) -> None:
        for name in ("tcga_predictions.json", "tcga_graph_info.json"):
            with self.subTest(file=name):
                self._assert_rejected(
                    lambda root, name=name: self._overwrite(root, name, [1, 2, 3])
                )

    def test_scenarios_must_be_an_array(self) -> None:
        self._assert_rejected(
            lambda root: self._overwrite(
                root, "tcga_patient_scenarios.json", {"name": "not-a-list"}
            )
        )

    def test_predictions_schema_requires_metadata_and_records(self) -> None:
        for key in ("metadata", "predictions"):
            with self.subTest(missing=key):
                self._mutate_predictions(lambda payload, key=key: payload.pop(key))

    def test_immune_cell_types_must_be_22_unique_names(self) -> None:
        cases = {
            "short": lambda payload: payload["immune_cell_types"].pop(0),
            "blank name": lambda payload: payload["immune_cell_types"].__setitem__(0, "  "),
            "duplicate name": lambda payload: payload["immune_cell_types"].__setitem__(
                1, payload["immune_cell_types"][0]
            ),
            "non-list": lambda payload: payload.__setitem__(
                "immune_cell_types", "T_cells_CD8"
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                self._mutate_predictions(mutate)

    def test_records_must_be_objects(self) -> None:
        self._mutate_predictions(lambda payload: payload["predictions"].append("bogus"))

    def test_sample_ids_must_be_non_empty(self) -> None:
        def mutate(payload: dict) -> None:
            payload["predictions"][0]["sample_id"] = "  "

        self._mutate_predictions(mutate)

    def test_sample_ids_must_be_unique(self) -> None:
        def mutate(payload: dict) -> None:
            records = payload["predictions"]
            records[1]["sample_id"] = records[0]["sample_id"]

        self._mutate_predictions(mutate)

    def test_unknown_record_subtype_is_rejected(self) -> None:
        def mutate(payload: dict) -> None:
            payload["predictions"][0]["immune_subtype"] = "bcell"

        self._mutate_predictions(mutate)

    def test_infiltration_vector_length_must_match(self) -> None:
        def mutate(payload: dict) -> None:
            payload["predictions"][0]["immune_infiltration"] = [0.5] * 21

        self._mutate_predictions(mutate)

    def test_infiltration_values_must_be_probabilities(self) -> None:
        def mutate(payload: dict) -> None:
            payload["predictions"][0]["immune_infiltration"][0] = 1.5

        self._mutate_predictions(mutate)

    def test_metadata_sample_count_must_match_records(self) -> None:
        def mutate(payload: dict) -> None:
            payload["metadata"]["n_samples"] = 1

        self._mutate_predictions(mutate)

    def test_selected_subtype_must_have_samples(self) -> None:
        def mutate(payload: dict) -> None:
            records = [
                record
                for record in payload["predictions"]
                if record["immune_subtype"] != "low_immune"
            ]
            payload["predictions"] = records
            payload["metadata"]["n_samples"] = len(records)

        self._mutate_predictions(mutate, subtype="low_immune")

    def test_scenarios_require_exactly_one_her2_preset(self) -> None:
        def zero_presets(root: Path) -> None:
            self._overwrite(root, "tcga_patient_scenarios.json", [])

        def two_presets(root: Path) -> None:
            path = root / "tcga_patient_scenarios.json"
            scenarios = json.loads(path.read_text(encoding="utf-8"))
            scenarios.append(dict(scenarios[0]))
            self._overwrite(root, "tcga_patient_scenarios.json", scenarios)

        for name, action in (("none", zero_presets), ("two", two_presets)):
            with self.subTest(case=name):
                self._assert_rejected(action)

    def test_cv_scores_must_be_present(self) -> None:
        self._mutate_predictions(lambda payload: payload["metadata"].pop("cv_scores"))


class CarmProfileRoundTripTests(unittest.TestCase):
    @staticmethod
    def _build_profile(root: Path) -> CarmCohortProfile:
        CarmDataImportTests._write_legacy_fixture(root)
        return build_carm_profile(root)

    def test_load_round_trips_saved_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = self._build_profile(root)
            target = root / "profile.json"
            save_carm_profile(target, profile)
            loaded = load_carm_profile(target)
            self.assertEqual(profile, loaded)
            self.assertEqual(profile.as_dict(), loaded.as_dict())

    def test_load_rejects_non_object_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "profile.json"
            target.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_carm_profile(target)

    def test_load_wraps_missing_keys_as_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "profile.json"
            target.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_carm_profile(target)

    def test_load_propagates_invalid_field_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = self._build_profile(root)
            target = root / "profile.json"
            payload = profile.as_dict()
            payload["sample_count"] = payload["total_sample_count"] + 1
            target.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_carm_profile(target)

    def test_save_rejects_non_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(TypeError):
                save_carm_profile(
                    Path(directory) / "profile.json", {"schema_version": "x"}
                )

    def test_save_is_idempotent_for_identical_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = self._build_profile(root)
            target = root / "profile.json"
            save_carm_profile(target, profile)
            first = target.read_text(encoding="utf-8")
            save_carm_profile(target, profile)
            self.assertEqual(first, target.read_text(encoding="utf-8"))

    def test_save_refuses_to_overwrite_different_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = self._build_profile(root)
            target = root / "profile.json"
            save_carm_profile(target, profile)
            different = profile.as_dict()
            different["cohort_id"] = "tcga_brca_other"
            target.write_text(json.dumps(different), encoding="utf-8")
            with self.assertRaises(ValueError):
                save_carm_profile(target, profile)


if __name__ == "__main__":
    unittest.main()
