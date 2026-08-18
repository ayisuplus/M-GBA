import json
import tempfile
import unittest
from pathlib import Path

from mgba.scenarios.carm import build_carm_profile, save_carm_profile


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


if __name__ == "__main__":
    unittest.main()
