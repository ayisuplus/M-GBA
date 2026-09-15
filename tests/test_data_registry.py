"""Tests for the machine-readable dataset registry and its validator.

Covers the real data/registry.json gate (byte stability of registered
artifacts), path/sha256 verdicts on temporary fixtures, fail-fast
loading of malformed registries, and the structured licence/source
fields (controlled licence vocabulary, source ref schemes, dataset-ref
resolution and downstream licence propagation).
"""

import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from mgba.data_registry import (
    ALLOWED_LICENSE_IDS,
    REGISTRY_SCHEMA_VERSION,
    DatasetEntry,
    DatasetProvenance,
    load_data_registry,
    validate_data_registry,
)

ROOT = Path(__file__).parents[1]

_PROVENANCE = DatasetProvenance(
    source="unit-test fixture",
    date="2026-08-21",
    license="test",
    license_ids=("LicenseRef-MGBA-Internal",),
    source_refs=("url:https://example.org/fixture",),
    deidentified=True,
    proxy_notice="",
)


def _entry(**overrides) -> DatasetEntry:
    values = {
        "dataset_id": "fixture",
        "kind": "synthetic",
        "status": "generated",
        "path": "fixture/payload.json",
        "sha256": "0" * 64,
        "provenance": _PROVENANCE,
        "notes": "",
    }
    values.update(overrides)
    return DatasetEntry(**values)


def _registry_payload(*entries: dict) -> dict:
    return {"schema_version": REGISTRY_SCHEMA_VERSION, "datasets": list(entries)}


def _entry_payload(provenance: dict | None = None, **overrides) -> dict:
    payload = {
        "dataset_id": "fixture",
        "kind": "synthetic",
        "status": "generated",
        "path": "fixture/payload.json",
        "sha256": "0" * 64,
        "provenance": {
            "source": "unit-test fixture",
            "date": "2026-08-21",
            "license": "test",
            "license_ids": ["LicenseRef-MGBA-Internal"],
            "source_refs": ["url:https://example.org/fixture"],
            "deidentified": True,
            "proxy_notice": "",
        },
        "notes": "",
    }
    payload["provenance"].update(provenance or {})
    payload.update(overrides)
    return payload


def _write_registry(directory: Path, payload: dict) -> Path:
    path = directory / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class RealRegistryGateTests(unittest.TestCase):
    def test_repository_registry_loads_and_verifies(self) -> None:
        entries = load_data_registry(ROOT / "data" / "registry.json")
        # Deliberate count guard: bump only when a dataset entry is added/removed.
        self.assertEqual(26, len(entries))  # 2026-09-11: +ADR-0047 D1-context-ood bundles/split/screen/evaluations
        verdicts = validate_data_registry(entries, data_root=ROOT)
        failures = [verdict for verdict in verdicts if not verdict.ok]
        self.assertEqual([], [f"{v.dataset_id}: {v.detail}" for v in failures])

    def test_local_only_entries_are_the_non_redistributable_geo_bundles(self) -> None:
        # Deliberate guard: local-only must not become a way to skip the sha256
        # gate. Extend only when a licence forbids redistributing a new entry.
        entries = load_data_registry(ROOT / "data" / "registry.json")
        self.assertEqual(
            [
                "aivc-d1-context-bundle-nadig-hepg2",
                "aivc-d1-context-bundle-nadig-jurkat",
            ],
            sorted(e.dataset_id for e in entries if e.distribution == "local-only"),
        )


class RegistryValidationTests(unittest.TestCase):
    def test_matching_sha256_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = b'{"ok": true}'
            (root / "fixture").mkdir()
            (root / "fixture" / "payload.json").write_bytes(payload)
            entry = _entry(sha256=sha256(payload).hexdigest())
            (verdict,) = validate_data_registry((entry,), data_root=root)
            self.assertTrue(verdict.ok)

    def test_sha256_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "fixture").mkdir()
            (root / "fixture" / "payload.json").write_bytes(b'{"ok": false}')
            (verdict,) = validate_data_registry((_entry(),), data_root=root)
            self.assertFalse(verdict.ok)
            self.assertIn("mismatch", verdict.detail)

    def test_missing_materialized_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entry = _entry(status="materialized", kind="aggregated_profile")
            (verdict,) = validate_data_registry((entry,), data_root=Path(tmp))
            self.assertFalse(verdict.ok)
            self.assertIn("missing", verdict.detail)

    def test_missing_planned_file_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entry = _entry(kind="external_planned", status="planned", sha256=None)
            (verdict,) = validate_data_registry((entry,), data_root=Path(tmp))
            self.assertTrue(verdict.ok)

    def test_missing_local_only_file_is_reported_not_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entry = _entry(distribution="local-only")
            (verdict,) = validate_data_registry((entry,), data_root=Path(tmp))
            self.assertTrue(verdict.ok)
            self.assertIn("local-only", verdict.detail)
            self.assertIn("sha256 not checked", verdict.detail)

    def test_present_local_only_file_is_still_sha256_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "fixture").mkdir()
            (root / "fixture" / "payload.json").write_bytes(b'{"tampered": true}')
            entry = _entry(distribution="local-only")
            (verdict,) = validate_data_registry((entry,), data_root=root)
            self.assertFalse(verdict.ok)
            self.assertIn("mismatch", verdict.detail)


class RegistryLoadTests(unittest.TestCase):
    def test_duplicate_dataset_id_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = _registry_payload(_entry_payload(), _entry_payload())
            with self.assertRaises(ValueError):
                load_data_registry(_write_registry(Path(tmp), payload))

    def test_unknown_kind_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = _registry_payload(_entry_payload(kind="mystery"))
            with self.assertRaises(ValueError):
                load_data_registry(_write_registry(Path(tmp), payload))

    def test_unknown_status_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = _registry_payload(_entry_payload(status="archived"))
            with self.assertRaises(ValueError):
                load_data_registry(_write_registry(Path(tmp), payload))

    def test_planned_entry_must_not_carry_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = _registry_payload(
                _entry_payload(
                    kind="external_planned", status="planned", sha256="0" * 64
                )
            )
            with self.assertRaises(ValueError):
                load_data_registry(_write_registry(Path(tmp), payload))

    def test_unreadable_registry_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_data_registry(Path(tmp) / "absent.json")

    def test_distribution_defaults_to_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (entry,) = load_data_registry(
                _write_registry(Path(tmp), _registry_payload(_entry_payload()))
            )
            self.assertEqual("repository", entry.distribution)

    def test_unknown_distribution_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = _registry_payload(_entry_payload(distribution="elsewhere"))
            with self.assertRaises(ValueError):
                load_data_registry(_write_registry(Path(tmp), payload))

    def test_planned_entry_cannot_be_local_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = _registry_payload(
                _entry_payload(
                    kind="external_planned",
                    status="planned",
                    sha256=None,
                    distribution="local-only",
                )
            )
            with self.assertRaises(ValueError):
                load_data_registry(_write_registry(Path(tmp), payload))

    def test_legacy_schema_without_structured_fields_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = _registry_payload(_entry_payload())
            payload["schema_version"] = "mgba-data-registry-0.1"
            with self.assertRaises(ValueError):
                load_data_registry(_write_registry(Path(tmp), payload))


class StructuredProvenanceTests(unittest.TestCase):
    def _load(self, *entries: dict):
        with tempfile.TemporaryDirectory() as tmp:
            return load_data_registry(
                _write_registry(Path(tmp), _registry_payload(*entries))
            )

    def _assert_rejected(self, *entries: dict, message: str = "") -> None:
        with self.assertRaises(ValueError) as caught:
            self._load(*entries)
        self.assertIn(message, str(caught.exception))

    def test_unknown_license_id_rejected(self) -> None:
        self._assert_rejected(
            _entry_payload({"license_ids": ["Free-For-Everyone"]}),
            message="unknown license ids",
        )

    def test_missing_or_empty_license_ids_rejected(self) -> None:
        self._assert_rejected(_entry_payload({"license_ids": []}))
        self._assert_rejected(_entry_payload({"license_ids": "CC-BY-4.0"}))
        payload = _entry_payload()
        del payload["provenance"]["license_ids"]
        self._assert_rejected(payload)

    def test_duplicate_license_ids_rejected(self) -> None:
        self._assert_rejected(
            _entry_payload({"license_ids": ["CC-BY-4.0", "CC-BY-4.0"]})
        )

    def test_malformed_source_refs_rejected(self) -> None:
        for ref in (
            "ftp:example.org/data",
            "no-scheme",
            "doi:zenodo.7041849",
            "geo:SRP123",
            "url:http://example.org/insecure",
            "repo:/abs/path.py",
            "repo:../outside.json",
            "url: https://example.org/untrimmed",
        ):
            with self.subTest(ref=ref):
                self._assert_rejected(_entry_payload({"source_refs": [ref]}))

    def test_empty_source_refs_rejected(self) -> None:
        self._assert_rejected(_entry_payload({"source_refs": []}))

    def test_external_profile_must_cite_external_source(self) -> None:
        self._assert_rejected(
            _entry_payload(
                {"source_refs": ["repo:scripts/build.py"]},
                kind="external_profile",
                status="materialized",
            ),
            message="must cite a dataset, doi, geo or url",
        )

    def test_dataset_ref_must_resolve(self) -> None:
        self._assert_rejected(
            _entry_payload({"source_refs": ["dataset:ghost"]}),
            message="cites unregistered dataset ghost",
        )

    def test_dataset_ref_to_itself_rejected(self) -> None:
        self._assert_rejected(
            _entry_payload({"source_refs": ["dataset:fixture"]}),
            message="must not cite the entry itself",
        )

    def test_downstream_entry_must_keep_upstream_license_ids(self) -> None:
        upstream = _entry_payload(
            {"license_ids": ["CC-BY-4.0", "LicenseRef-MSigDB"]},
            dataset_id="upstream",
        )
        downstream = _entry_payload(
            {"license_ids": ["CC-BY-4.0"], "source_refs": ["dataset:upstream"]},
            dataset_id="downstream",
        )
        self._assert_rejected(
            upstream,
            downstream,
            message="downstream drops upstream license ids from upstream: LicenseRef-MSigDB",
        )

    def test_downstream_superset_of_upstream_licenses_loads(self) -> None:
        upstream = _entry_payload(
            {"license_ids": ["CC-BY-4.0"]}, dataset_id="upstream"
        )
        downstream = _entry_payload(
            {
                "license_ids": ["CC-BY-4.0", "LicenseRef-Geneformer"],
                "source_refs": ["dataset:upstream"],
            },
            dataset_id="downstream",
        )
        entries = self._load(upstream, downstream)
        self.assertEqual(
            ("upstream",), entries[1].provenance.refs("dataset")
        )

    def test_missing_repo_source_ref_fails_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entry = _entry(
                kind="external_planned",
                status="planned",
                sha256=None,
                provenance=DatasetProvenance(
                    source="planned fixture",
                    date="2026-09-15",
                    license="per resource",
                    license_ids=("LicenseRef-Per-Resource",),
                    source_refs=("repo:manifests/README.md",),
                    deidentified=True,
                    proxy_notice="",
                ),
            )
            (verdict,) = validate_data_registry((entry,), data_root=Path(tmp))
            self.assertFalse(verdict.ok)
            self.assertIn("repo source ref missing", verdict.detail)

            (Path(tmp) / "manifests").mkdir()
            (Path(tmp) / "manifests" / "README.md").write_text("list", encoding="utf-8")
            (verdict,) = validate_data_registry((entry,), data_root=Path(tmp))
            self.assertTrue(verdict.ok)

    def test_repository_registry_uses_only_vocabulary_license_ids(self) -> None:
        entries = load_data_registry(ROOT / "data" / "registry.json")
        used = {item for entry in entries for item in entry.provenance.license_ids}
        self.assertTrue(used)
        self.assertLessEqual(used, set(ALLOWED_LICENSE_IDS))


if __name__ == "__main__":
    unittest.main()
