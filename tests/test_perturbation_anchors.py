"""Tests for the ADR-0036 Norman perturbation anchor aggregation segment."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
from pathlib import Path
from statistics import fmean
from unittest import mock

from mgba.cli import main as cli_main
from mgba.experiment import digest_payload
from mgba.layers.l0 import ABSTRACT_GENE_NAMES
from mgba.ocellus_anchors import REQUIRED_HALLMARK_SETS
from mgba.perturbation_anchors import (
    EMPIRICAL_BUNDLE_SCHEMA_VERSION,
    FROZEN_PARAMETERS,
    FROZEN_PARAMETERS_REPLOGLE,
    PROFILE_SCHEMA_VERSION,
    SPLIT_SALT,
    EmpiricalBundle,
    assign_splits,
    build_perturbation_profile,
    load_empirical_bundle,
    load_hallmark_memberships,
    save_perturbation_profile,
)

ROOT = Path(__file__).parents[1]

_SET_GENES = {name: (f"{name}_G1", f"{name}_G2") for name in REQUIRED_HALLMARK_SETS}
_UNIVERSE = tuple(sorted(gene for genes in _SET_GENES.values() for gene in genes))
_UNITS = ("AAA", "BBB", "CCC", "DDD", "EEE")


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _gmt(root: Path) -> Path:
    lines = [
        "\t".join([name, "https://example.invalid/set", *_SET_GENES[name]])
        for name in REQUIRED_HALLMARK_SETS
    ]
    path = root / "hallmark.gmt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _bundle_payload(*, units=_UNITS) -> dict:
    values = {unit: float(index + 1) * 0.01 for index, unit in enumerate(units)}
    return {
        "schema_version": EMPIRICAL_BUNDLE_SCHEMA_VERSION,
        "dataset_id": "norman-weissman-2019-scperturb-filtered",
        "source": {
            "path": "source.h5ad",
            "sha256": "a" * 64,
            "bytes": 100,
            "license": "CC BY 4.0",
            "rights_verified": True,
            "zenodo_doi": "10.5281/zenodo.0000000",
        },
        "hallmark_source": {
            "path": "hallmark.gmt",
            "sha256": "b" * 64,
            "bytes": 50,
            "license": "MSigDB terms",
            "rights_verified": True,
            "version": "fixture",
        },
        "parameters": dict(FROZEN_PARAMETERS),
        "gene_universe": {"description": "fixture universe", "genes": list(_UNIVERSE)},
        "control_cells": 100,
        "units": [
            {
                "unit": unit,
                "cells": 50,
                "log2fc": [(1.0 if unit != "EEE" else -1.0) * values[unit]]
                * len(_UNIVERSE),
            }
            for unit in units
        ],
    }


def _write_bundle(root: Path, payload: dict | None = None) -> Path:
    path = root / "bundle.json"
    path.write_text(json.dumps(payload or _bundle_payload()), encoding="utf-8")
    return path


def _load(root: Path) -> EmpiricalBundle:
    return load_empirical_bundle(_write_bundle(root))


class BundleGateTests(unittest.TestCase):
    def test_valid_bundle_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _load(Path(tmp))
            self.assertEqual("norman-weissman-2019-scperturb-filtered", bundle.dataset_id)
            self.assertEqual(_UNITS, tuple(unit.unit for unit in bundle.units))
            self.assertEqual(_UNIVERSE, bundle.universe_genes)
            self.assertEqual(64, len(bundle.bundle_digest))

    def test_rejections(self) -> None:
        cases = []
        bad_schema = _bundle_payload()
        bad_schema["schema_version"] = "other"
        cases.append((bad_schema, "unsupported"))
        bad_sha = _bundle_payload()
        bad_sha["source"]["sha256"] = "A" * 64
        cases.append((bad_sha, "lowercase hexadecimal"))
        bad_rights = _bundle_payload()
        bad_rights["source"]["rights_verified"] = False
        cases.append((bad_rights, "rights"))
        bad_param = _bundle_payload()
        bad_param["parameters"]["min_cells"] = 30
        cases.append((bad_param, "frozen parameter"))
        dup = _bundle_payload(units=("AAA", "AAA", "CCC", "DDD", "EEE"))
        cases.append((dup, "unique"))
        few_cells = _bundle_payload()
        few_cells["units"][0]["cells"] = 49
        cases.append((few_cells, ">=50"))
        short_vec = _bundle_payload()
        short_vec["units"][0]["log2fc"] = [0.1]
        cases.append((short_vec, "length disagrees"))
        nan_vec = _bundle_payload()
        nan_vec["units"][0]["log2fc"][0] = float("nan")
        cases.append((nan_vec, "finite"))
        bad_control = _bundle_payload()
        bad_control["control_cells"] = 10
        cases.append((bad_control, ">=50"))
        dup_genes = _bundle_payload()
        dup_genes["gene_universe"]["genes"] = list(_UNIVERSE) + [_UNIVERSE[0]]
        dup_genes["units"] = [
            {**unit, "log2fc": unit["log2fc"] + [0.0]} for unit in dup_genes["units"]
        ]
        cases.append((dup_genes, "unique"))
        for payload, fragment in cases:
            with self.subTest(fragment=fragment), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(ValueError, fragment):
                    load_empirical_bundle(_write_bundle(Path(tmp), payload))


class DatasetDispatchTests(unittest.TestCase):
    def test_replogle_parameter_set_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = _bundle_payload()
            payload["dataset_id"] = "replogle-2022-k562-essential-scperturb"
            payload["parameters"] = dict(FROZEN_PARAMETERS_REPLOGLE)
            bundle = load_empirical_bundle(_write_bundle(Path(tmp), payload))
            self.assertEqual(
                "replogle-2022-k562-essential-scperturb", bundle.dataset_id
            )
            self.assertEqual("none-filtered-release", bundle.parameters["qc_flag"])

    def test_unknown_dataset_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = _bundle_payload()
            payload["dataset_id"] = "mystery-dataset"
            with self.assertRaisesRegex(ValueError, "allowlist"):
                load_empirical_bundle(_write_bundle(Path(tmp), payload))

    def test_norman_qc_mismatch_still_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = _bundle_payload()
            payload["parameters"]["qc_flag"] = "none-filtered-release"
            with self.assertRaisesRegex(ValueError, "frozen parameter"):
                load_empirical_bundle(_write_bundle(Path(tmp), payload))

    def test_salt_passthrough_changes_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _load(root)
            gmt = _gmt(root)
            memberships = load_hallmark_memberships(gmt, expected_sha256=_sha256(gmt))
            default_profile = build_perturbation_profile(bundle, memberships)
            other_profile = build_perturbation_profile(
                bundle, memberships, salt="mgba-aivc-replogle-kd-anchor-2026-08-29"
            )
            self.assertNotEqual(
                default_profile.as_dict()["split"],
                other_profile.as_dict()["split"],
            )
            self.assertEqual(
                "mgba-aivc-replogle-kd-anchor-2026-08-29",
                other_profile.as_dict()["split"]["salt"],
            )


class HallmarkGateTests(unittest.TestCase):
    def test_valid_gmt_loads_bridge_sets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _gmt(Path(tmp))
            memberships = load_hallmark_memberships(path, expected_sha256=_sha256(path))
            self.assertEqual(set(REQUIRED_HALLMARK_SETS), set(memberships))
            for name, genes in memberships.items():
                self.assertEqual(tuple(sorted(_SET_GENES[name])), genes)

    def test_sha_mismatch_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _gmt(Path(tmp))
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                load_hallmark_memberships(path, expected_sha256="0" * 64)

    def test_missing_set_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lines = [
                "\t".join([name, "u", *_SET_GENES[name]])
                for name in REQUIRED_HALLMARK_SETS[:-1]
            ]
            path = root / "partial.gmt"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "misses frozen bridge sets"):
                load_hallmark_memberships(path, expected_sha256=_sha256(path))


class SplitTests(unittest.TestCase):
    def test_digest_rule_and_disjoint_roles(self) -> None:
        roles = assign_splits(_UNITS)
        expected_rank = sorted(
            _UNITS, key=lambda n: sha256(f"{SPLIT_SALT}|{n}".encode()).hexdigest()
        )
        for index, unit in enumerate(expected_rank):
            self.assertEqual("train" if index < 4 else "holdout", roles[unit])
        self.assertEqual(4, sum(1 for r in roles.values() if r == "train"))

    def test_deterministic(self) -> None:
        self.assertEqual(assign_splits(_UNITS), assign_splits(_UNITS))

    def test_validation(self) -> None:
        with self.assertRaises(ValueError):
            assign_splits(_UNITS, train_fraction=1.5)
        with self.assertRaises(ValueError):
            assign_splits(("ONLY",))
        with self.assertRaises(ValueError):
            assign_splits(("A", "A"))


class ProfileTests(unittest.TestCase):
    def _profile(self, root: Path):
        bundle = _load(root)
        gmt = _gmt(root)
        memberships = load_hallmark_memberships(
            gmt, expected_sha256=_sha256(gmt)
        )
        return build_perturbation_profile(bundle, memberships)

    def test_vector_order_centroid_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._profile(Path(tmp))
            self.assertEqual(
                ABSTRACT_GENE_NAMES, tuple(name for name, _ in profile.centroid)
            )
            roles = assign_splits(_UNITS)
            train = [u for u in _UNITS if roles[u] == "train"]
            values = {
                u: (i + 1) * 0.01 * (-1.0 if u == "EEE" else 1.0)
                for i, u in enumerate(_UNITS)
            }
            for node_index, (node, value) in enumerate(profile.centroid):
                self.assertEqual(node, ABSTRACT_GENE_NAMES[node_index])
                self.assertAlmostEqual(
                    fmean(values[u] for u in train), value, places=12
                )
            holdout = [u for u in profile.units if u.role == "holdout"]
            self.assertEqual(1, len(holdout))
            summary = profile.holdout_summary
            self.assertEqual(1, summary["unit_count"])
            self.assertAlmostEqual(
                summary["six_node_mae"], holdout[0].metrics["six_node_mae"], places=15
            )
            payload = profile.as_dict()
            self.assertEqual(PROFILE_SCHEMA_VERSION, payload["schema_version"])
            self.assertTrue(payload["profile_id"].startswith("norman-perturbation-profile-"))

    def test_centroid_ignores_holdout_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._profile(root)
            roles = assign_splits(_UNITS)
            holdout_unit = next(u for u in _UNITS if roles[u] == "holdout")
            payload = _bundle_payload()
            for unit in payload["units"]:
                if unit["unit"] == holdout_unit:
                    unit["log2fc"] = [99.0] * len(_UNIVERSE)
            bundle = load_empirical_bundle(_write_bundle(root, payload))
            gmt = _gmt(root)
            second = build_perturbation_profile(
                bundle,
                load_hallmark_memberships(gmt, expected_sha256=_sha256(gmt)),
            )
            self.assertEqual(first.centroid, second.centroid)

    def test_write_once_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "profile.json"
            save_perturbation_profile(self._profile(root), output)
            self.assertTrue(output.exists())
            with self.assertRaisesRegex(ValueError, "overwrite"):
                save_perturbation_profile(self._profile(root), output)

    def test_cli_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle_path = _write_bundle(root)
            gmt = _gmt(root)
            # The CLI checks the gmt sha against the bundle identity; align it.
            payload = _bundle_payload()
            payload["hallmark_source"]["sha256"] = _sha256(gmt)
            bundle_path.write_text(json.dumps(payload), encoding="utf-8")
            output = root / "out.json"
            stdout = StringIO()
            argv = [
                "mgba",
                "aivc-perturbation-anchor",
                "--bundle",
                str(bundle_path),
                "--hallmark",
                str(gmt),
                "--output",
                str(output),
            ]
            with mock.patch("sys.argv", argv), redirect_stdout(stdout):
                cli_main()
            result = json.loads(stdout.getvalue())
            self.assertEqual(PROFILE_SCHEMA_VERSION, result["schema_version"])
            self.assertEqual(5, result["units"])
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                digest_payload({k: v for k, v in saved.items() if k != "profile_id"})
                [:16],
                saved["profile_id"].rsplit("-", 1)[1],
            )


if __name__ == "__main__":
    unittest.main()
