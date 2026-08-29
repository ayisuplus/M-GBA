import hashlib
import json
import copy
import tempfile
import unittest
from pathlib import Path

from mgba.experiment import digest_payload
from mgba.lab import (
    LAB_BUNDLE_SCHEMA,
    LAB_CATALOG_SCHEMA,
    LAB_EXECUTION_REVISION,
    LAB_FILES_SCHEMA,
    LAB_REQUEST_SCHEMA,
    LabExperimentRequest,
    export_competition_lab_data,
    run_lab_experiment,
    verify_lab_bundle,
    write_lab_bundle_set,
)
from mgba.lab_server import _allow_client

ROOT = Path(__file__).parents[1]
LAB_EXPORT_SOURCES = (
    ROOT / "artifacts" / "demo" / "carm-playbook.json",
    ROOT / "artifacts" / "carm-state-conditioned-intervention" / "state-intervention-0e92bb234ba3a840",
    ROOT / "artifacts" / "carm-spatial" / "carm-spatial-0f88408d1e44b25a",
)
LAB_EXPORT_SOURCES_AVAILABLE = all(path.exists() for path in LAB_EXPORT_SOURCES)


def _fixture_bundle(bundle_id: str) -> dict:
    payload = {
        "schema_version": LAB_BUNDLE_SCHEMA,
        "bundle_id": bundle_id,
        "kind": "fixture",
        "title": f"Fixture {bundle_id}",
        "description": "deterministic bundle fixture",
        "model_status": "contract demonstrator",
        "boundary_note": "not a clinical predictor",
        "target_status": "真实数据 Target 已于 2026-08-28 生成（spatial-anchor-29c87ba1411d4fc8）；首次评估未锚定，ADR-0043 calibration 确认 improved。",
        "seed": 42,
        "roles": {"tumor-001": "tumor"},
        "layout": {"tumor-001": [0.5, 0.5]},
        "reference_condition": "baseline",
        "default_comparison_condition": "intervention",
        "conditions": [
            {
                "condition_id": "baseline",
                "label": "Baseline",
                "ticks": [{"t": 1}],
            },
            {
                "condition_id": "intervention",
                "label": "Intervention",
                "ticks": [{"t": 1}],
            },
        ],
        "analysis": {},
        "evidence": {},
        "config_summary": {},
    }
    payload["bundle_digest"] = digest_payload(payload)
    return payload


class LabRequestTests(unittest.TestCase):
    def _request(self, **updates: object) -> dict:
        raw = {
            "schema_version": LAB_REQUEST_SCHEMA,
            "scenario_id": "carm_high_immune_her2",
            "protocol_id": "state_conditioned_signal_expression",
            "dose": 0.7,
            "onset": "late",
            "exposure": "short",
        }
        raw.update(updates)
        return raw

    def test_request_is_strict_allow_list_and_schedule_is_clock_aligned(self) -> None:
        request = LabExperimentRequest.from_mapping(self._request())
        self.assertEqual((31, 36, 41), request.schedule_ticks)
        self.assertEqual("live_070_late_short", request.condition_id)
        self.assertRegex(request.run_id, r"^lab-run-[0-9a-f]{16}$")
        self.assertEqual(
            request.run_id,
            LabExperimentRequest.from_mapping(self._request()).run_id,
        )
        with self.assertRaises(ValueError):
            LabExperimentRequest.from_mapping(self._request(dose=0.5))
        with self.assertRaises(ValueError):
            LabExperimentRequest.from_mapping({**self._request(), "targets": ["tumor-001"]})
        with self.assertRaises(ValueError):
            LabExperimentRequest.from_mapping(self._request(onset="tick-17"))

    def test_long_schedule_preserves_frozen_l0_clock(self) -> None:
        early = LabExperimentRequest.from_mapping(
            self._request(onset="early", exposure="long", dose=1.0)
        )
        late = LabExperimentRequest.from_mapping(
            self._request(onset="late", exposure="long", dose=1.0)
        )
        self.assertEqual((1, 6, 11, 16, 21, 26), early.schedule_ticks)
        self.assertEqual((31, 36, 41, 46, 51, 56), late.schedule_ticks)

    def test_rate_limit_rejects_sixth_run_in_one_hour(self) -> None:
        client = "test-client-lab-contract"
        for offset in range(5):
            self.assertTrue(_allow_client(client, now=1000.0 + offset))
        self.assertFalse(_allow_client(client, now=1006.0))
        self.assertTrue(_allow_client(client, now=5000.0))


class LabBundleTests(unittest.TestCase):
    def test_bundle_digest_is_fail_closed(self) -> None:
        bundle = _fixture_bundle("alpha")
        self.assertEqual(bundle, verify_lab_bundle(bundle))
        tampered = json.loads(json.dumps(bundle))
        tampered["title"] = "changed"
        with self.assertRaises(ValueError):
            verify_lab_bundle(tampered)

    def test_catalog_bundle_and_manifest_are_byte_rebuildable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = write_lab_bundle_set(
                root / "first",
                (_fixture_bundle("alpha"), _fixture_bundle("beta")),
            )
            second = write_lab_bundle_set(
                root / "second",
                (_fixture_bundle("alpha"), _fixture_bundle("beta")),
            )
            self.assertEqual(set(first), set(second))
            for key in first:
                self.assertEqual(first[key].read_bytes(), second[key].read_bytes())
            catalog = json.loads(first["catalog"].read_text(encoding="utf-8"))
            manifest = json.loads(first["manifest"].read_text(encoding="utf-8"))
            self.assertEqual(LAB_CATALOG_SCHEMA, catalog["schema_version"])
            self.assertEqual(LAB_FILES_SCHEMA, manifest["schema_version"])
            self.assertEqual(2, len(catalog["experiments"]))
            for name, digest in manifest["files"].items():
                actual = hashlib.sha256((first["catalog"].parent / name).read_bytes()).hexdigest()
                self.assertEqual(digest, actual)

    @unittest.skipUnless(
        LAB_EXPORT_SOURCES_AVAILABLE,
        "competition lab artifacts are gitignored; present only on the generator machine",
    )
    def test_full_lab_export_is_rebuildable_and_collective_growth_is_bounded(self) -> None:
        sources = {
            "dose_playbook": LAB_EXPORT_SOURCES[0],
            "intervention_root": LAB_EXPORT_SOURCES[1],
            "spatial_root": LAB_EXPORT_SOURCES[2],
        }
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            first = export_competition_lab_data(
                output_dir=temporary_root / "first", **sources
            )
            second = export_competition_lab_data(
                output_dir=temporary_root / "second", **sources
            )
            self.assertEqual(set(first), set(second))
            for key in first:
                self.assertEqual(first[key].read_bytes(), second[key].read_bytes())
            for bundle_id in ("dose-response", "state-intervention", "spatial-l3"):
                bundle = json.loads(first[bundle_id].read_text(encoding="utf-8"))
                self.assertIn("collective_dynamics", bundle["analysis"])
                without_collective = copy.deepcopy(bundle)
                without_collective["analysis"].pop("collective_dynamics")
                for condition in without_collective["conditions"]:
                    for tick in condition["ticks"]:
                        for cell in tick["cells"].values():
                            cell.pop("collective_response", None)
                compact = lambda value: (
                    json.dumps(
                        value,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode("utf-8")
                growth = len(compact(bundle)) / len(compact(without_collective)) - 1.0
                self.assertLessEqual(growth, 0.15, bundle_id)


class LabLiveContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).parents[1]
        cls.request = LabExperimentRequest.from_mapping(
            {
                "schema_version": LAB_REQUEST_SCHEMA,
                "scenario_id": "carm_high_immune_her2",
                "protocol_id": "state_conditioned_signal_expression",
                "dose": 0.7,
                "onset": "late",
                "exposure": "short",
            }
        )
        cls.bundle = run_lab_experiment(cls.request, project_root=cls.root)

    def test_live_pair_has_full_trace_and_pre_onset_identity(self) -> None:
        bundle = verify_lab_bundle(self.bundle)
        self.assertEqual(self.request.run_id, bundle["bundle_id"])
        self.assertEqual(2, len(bundle["conditions"]))
        baseline, intervention = bundle["conditions"]
        self.assertEqual(60, len(baseline["ticks"]))
        self.assertEqual(60, len(intervention["ticks"]))
        for index in range(30):
            self.assertEqual(
                baseline["ticks"][index]["cells"],
                intervention["ticks"][index]["cells"],
            )
            self.assertEqual(
                baseline["ticks"][index]["l3"],
                intervention["ticks"][index]["l3"],
            )
        self.assertEqual(15, intervention["ticks"][30]["audit"]["l0_perturbation_count"])
        self.assertEqual(0, baseline["ticks"][30]["audit"]["l0_perturbation_count"])

        collective = bundle["analysis"]["collective_dynamics"]
        baseline_report = collective["conditions"]["baseline"]
        intervention_report = collective["conditions"][self.request.condition_id]
        for cohort_id in baseline_report["cohorts"]:
            self.assertEqual(
                baseline_report["cohorts"][cohort_id]["series"][:30],
                intervention_report["cohorts"][cohort_id]["series"][:30],
            )
        for condition in bundle["conditions"]:
            for tick in condition["ticks"]:
                for cell in tick["cells"].values():
                    self.assertAlmostEqual(
                        cell["activation"] - cell["stress_load"],
                        cell["collective_response"],
                        places=4,
                    )

    def test_live_pair_keeps_manifest_and_scientific_boundary(self) -> None:
        self.assertIn("不是临床预测", self.bundle["boundary_note"])
        self.assertIn("Target 已于 2026-08-28 生成", self.bundle["target_status"])
        self.assertEqual(42, self.bundle["seed"])
        self.assertEqual(63, len(self.bundle["roles"]))
        for condition in self.bundle["conditions"]:
            self.assertRegex(condition["experiment_id"], r"^mgba-[0-9a-f]{16}$")
            self.assertRegex(condition["history_digest"], r"^[0-9a-f]{64}$")
        collective = self.bundle["analysis"]["collective_dynamics"]
        self.assertEqual(
            "collective-dynamics-observer-0.1", collective["observer_version"]
        )
        self.assertRegex(collective["config_digest"], r"^[0-9a-f]{64}$")
        self.assertIn("不是物理相变", collective["scientific_boundary"])
        self.assertEqual("carm-state-conditioned-paired-0.3", LAB_EXECUTION_REVISION)


if __name__ == "__main__":
    unittest.main()
