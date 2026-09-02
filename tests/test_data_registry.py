"""Tests for the machine-readable dataset registry and its validator.

Covers the real data/registry.json gate (byte stability of registered
artifacts), path/sha256 verdicts on temporary fixtures, and fail-fast
loading of malformed registries.
"""

import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from mgba.data_registry import (
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
    return {"schema_version": "mgba-data-registry-0.1", "datasets": list(entries)}


def _entry_payload(**overrides) -> dict:
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
            "deidentified": True,
            "proxy_notice": "",
        },
        "notes": "",
    }
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
        self.assertEqual(18, len(entries))  # 2026-09-02: +ADR-0046 hallmark targets & evaluations
        verdicts = validate_data_registry(entries, data_root=ROOT)
        failures = [verdict for verdict in verdicts if not verdict.ok]
        self.assertEqual([], [f"{v.dataset_id}: {v.detail}" for v in failures])


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


if __name__ == "__main__":
    unittest.main()
