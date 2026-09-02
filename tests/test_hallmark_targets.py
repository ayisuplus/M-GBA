"""Tests for the ADR-0046 Hallmark structured-target builder segment."""

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
from mgba.hashing import digest_payload
from mgba.hallmark_targets import (
    TARGET_SCHEMA_VERSION,
    build_hallmark_targets,
    load_all_hallmark_memberships,
    load_hallmark_target,
    load_source_profile,
    mean_metrics_d,
    save_hallmark_target,
    vector_metrics_d,
)
from mgba.layers.l0 import ABSTRACT_GENE_NAMES
from mgba.ocellus_anchors import REQUIRED_HALLMARK_SETS, aggregate_hallmark_bridge
from mgba.perturbation_anchors import (
    EMPIRICAL_BUNDLE_SCHEMA_VERSION,
    FROZEN_PARAMETERS,
    PROFILE_SCHEMA_VERSION,
    load_empirical_bundle,
)

_EXTRA_SET = "HALLMARK_EXTRA_ONE"
_ZERO_SET = "HALLMARK_EXTRA_ZERO"
_SET_GENES = {name: (f"{name}_G1", f"{name}_G2") for name in REQUIRED_HALLMARK_SETS}
_SET_GENES[_EXTRA_SET] = ("EXTRA_G1", "EXTRA_G2")
_SET_GENES[_ZERO_SET] = ("ZERO_G1", "ZERO_G2")  # never in the universe
_UNIVERSE = tuple(
    sorted(
        gene
        for set_name, genes in _SET_GENES.items()
        if set_name != _ZERO_SET
        for gene in genes
    )
)
_INCLUDED_SETS = tuple(sorted(name for name in _SET_GENES if name != _ZERO_SET))
_DIMS = _INCLUDED_SETS + ABSTRACT_GENE_NAMES
_UNITS = ("AAA", "BBB", "CCC", "DDD", "EEE")
_ROLES = {"AAA": "train", "BBB": "train", "CCC": "train", "DDD": "holdout", "EEE": "holdout"}
_BASE = {unit: 0.01 * (index + 1) for index, unit in enumerate(_UNITS)}

_NODE_SETS = {
    "damage_response": ("HALLMARK_P53_PATHWAY", "HALLMARK_UV_RESPONSE_DN"),
    "signal_expression": (
        "HALLMARK_TNFA_SIGNALING_VIA_NFKB",
        "HALLMARK_KRAS_SIGNALING_UP",
        "HALLMARK_IL6_JAK_STAT3_SIGNALING",
    ),
    "repair_expression": ("HALLMARK_DNA_REPAIR",),
    "metabolic_expression": ("HALLMARK_OXIDATIVE_PHOSPHORYLATION", "HALLMARK_GLYCOLYSIS"),
    "death_expression": ("HALLMARK_APOPTOSIS",),
    "negative_feedback_expression": ("HALLMARK_TGF_BETA_SIGNALING",),
}


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _value(unit: str, gene: str) -> float:
    return _BASE[unit] + 0.001 * _UNIVERSE.index(gene)


def _expected_set(unit: str, set_name: str) -> float:
    return fmean(_value(unit, gene) for gene in sorted(_SET_GENES[set_name]))


def _expected_head(unit: str, node: str) -> float:
    union = sorted({gene for set_name in _NODE_SETS[node] for gene in _SET_GENES[set_name]})
    return fmean(_value(unit, gene) for gene in union)


def _gmt(root: Path) -> Path:
    order = list(REQUIRED_HALLMARK_SETS) + [_EXTRA_SET, _ZERO_SET]
    lines = [
        "\t".join([name, "https://example.invalid/set", *_SET_GENES[name]])
        for name in order
    ]
    path = root / "hallmark.gmt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _bundle_payload(gmt_sha256: str = "b" * 64) -> dict:
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
            "sha256": gmt_sha256,
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
                "log2fc": [_value(unit, gene) for gene in _UNIVERSE],
            }
            for unit in _UNITS
        ],
    }


def _profile_payload(bundle_digest: str) -> dict:
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile_id": "norman-perturbation-profile-fixture",
        "dataset_id": "norman-weissman-2019-scperturb-filtered",
        "scientific_boundary": "fixture",
        "bridge": {"version": "fixture", "digest": "0" * 64},
        "source": {"bundle_sha256": bundle_digest},
        "parameters": dict(FROZEN_PARAMETERS),
        "split": {
            "salt": "fixture-salt",
            "train_fraction": 0.8,
            "rule": "fixture",
            "train_units": 3,
            "holdout_units": 2,
        },
        "centroid_train_only": {
            node: fmean(
                _expected_head(unit, node)
                for unit in _UNITS
                if _ROLES[unit] == "train"
            )
            for node in ABSTRACT_GENE_NAMES
        },
        "units": [
            {
                "unit": unit,
                "cells": 50,
                "role": _ROLES[unit],
                "six_node_vector": {
                    node: _expected_head(unit, node) for node in ABSTRACT_GENE_NAMES
                },
                "metrics_vs_centroid": {},
            }
            for unit in _UNITS
        ],
        "metrics_summary": {},
    }


def _fixture(root: Path):
    gmt = _gmt(root)
    bundle_path = root / "bundle.json"
    bundle_path.write_text(
        json.dumps(_bundle_payload(gmt_sha256=_sha256(gmt))), encoding="utf-8"
    )
    bundle = load_empirical_bundle(bundle_path)
    profile_path = root / "profile.json"
    profile_path.write_text(
        json.dumps(_profile_payload(bundle.bundle_digest)), encoding="utf-8"
    )
    memberships = load_all_hallmark_memberships(gmt, expected_sha256=_sha256(gmt))
    profile = load_source_profile(profile_path)
    return bundle, profile, memberships, profile_path, gmt


class AllMembershipTests(unittest.TestCase):
    def test_all_sets_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gmt = _gmt(Path(tmp))
            memberships = load_all_hallmark_memberships(gmt, expected_sha256=_sha256(gmt))
            self.assertEqual(set(_SET_GENES), set(memberships))
            for name, genes in memberships.items():
                self.assertEqual(tuple(sorted(_SET_GENES[name])), genes)

    def test_digest_mismatch_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gmt = _gmt(Path(tmp))
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                load_all_hallmark_memberships(gmt, expected_sha256="0" * 64)

    def test_empty_set_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.gmt"
            path.write_text("HALLMARK_EMPTY\turl\t\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "empty"):
                load_all_hallmark_memberships(path, expected_sha256=_sha256(path))

    def test_duplicate_set_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dup.gmt"
            line = "HALLMARK_DUP\turl\tG1\tG2\n"
            path.write_text(line + line, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "twice"):
                load_all_hallmark_memberships(path, expected_sha256=_sha256(path))


class BuildTargetTests(unittest.TestCase):
    def test_aggregation_matches_hand_computation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, profile, memberships, _, _ = _fixture(Path(tmp))
            target = build_hallmark_targets(bundle, profile, memberships)
            self.assertEqual(TARGET_SCHEMA_VERSION, target["schema_version"])
            self.assertEqual(list(_DIMS), target["dims"])
            self.assertEqual([_ZERO_SET], target["excluded_sets"])
            self.assertEqual(
                {name: 2 for name in _INCLUDED_SETS}, target["coverage"]
            )
            for entry in target["units"]:
                unit = entry["unit"]
                expected = {
                    **{name: _expected_set(unit, name) for name in _INCLUDED_SETS},
                    **{node: _expected_head(unit, node) for node in ABSTRACT_GENE_NAMES},
                }
                self.assertEqual(expected, entry["target"])

    def test_head_equals_frozen_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, profile, memberships, _, _ = _fixture(Path(tmp))
            target = build_hallmark_targets(bundle, profile, memberships)
            bridge_memberships = {
                name: memberships[name] for name in REQUIRED_HALLMARK_SETS
            }
            for entry in target["units"]:
                unit = next(u for u in bundle.units if u.unit == entry["unit"])
                effect_map = dict(zip(bundle.universe_genes, unit.log2fc))
                projection = aggregate_hallmark_bridge(effect_map, bridge_memberships)
                head = {node: entry["target"][node] for node in ABSTRACT_GENE_NAMES}
                self.assertEqual(dict(projection.values), head)

    def test_roles_copied_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, profile, memberships, _, _ = _fixture(Path(tmp))
            target = build_hallmark_targets(bundle, profile, memberships)
            self.assertEqual(_ROLES, target["roles"])
            self.assertEqual(bundle.dataset_id, target["dataset_id"])
            self.assertEqual(bundle.bundle_digest, target["source"]["bundle_sha256"])
            self.assertEqual(profile["_file_sha256"], target["source"]["profile_sha256"])
            self.assertEqual("fixture-salt", target["split"]["salt"])
            train = [u for u in _UNITS if _ROLES[u] == "train"]
            for dim in _DIMS:
                expected = fmean(
                    next(e["target"][dim] for e in target["units"] if e["unit"] == unit)
                    for unit in train
                )
                self.assertEqual(expected, target["centroid_train_only"][dim])

    def test_profile_digest_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, profile, memberships, _, _ = _fixture(Path(tmp))
            bad = json.loads(json.dumps(profile))
            bad["source"]["bundle_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "not built from this bundle"):
                build_hallmark_targets(bundle, bad, memberships)

    def test_dataset_mismatch_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, profile, memberships, _, _ = _fixture(Path(tmp))
            bad = json.loads(json.dumps(profile))
            bad["dataset_id"] = "other-dataset"
            with self.assertRaisesRegex(ValueError, "dataset_id"):
                build_hallmark_targets(bundle, bad, memberships)

    def test_missing_unit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, profile, memberships, _, _ = _fixture(Path(tmp))
            bad = json.loads(json.dumps(profile))
            bad["units"] = bad["units"][1:]
            with self.assertRaisesRegex(ValueError, "missing from the profile"):
                build_hallmark_targets(bundle, bad, memberships)

    def test_head_gate_rejects_profile_deviation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, profile, memberships, _, _ = _fixture(Path(tmp))
            bad = json.loads(json.dumps(profile))
            node = ABSTRACT_GENE_NAMES[0]
            bad["units"][0]["six_node_vector"][node] += 1e-6
            with self.assertRaisesRegex(ValueError, "six-node head disagrees"):
                build_hallmark_targets(bundle, bad, memberships)

    def test_missing_bridge_set_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, profile, memberships, _, _ = _fixture(Path(tmp))
            shrunk = dict(memberships)
            del shrunk[REQUIRED_HALLMARK_SETS[0]]
            with self.assertRaisesRegex(ValueError, "frozen bridge sets"):
                build_hallmark_targets(bundle, profile, shrunk)

    def test_deterministic_byte_identical_builds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, profile, memberships, _, _ = _fixture(root)
            first = build_hallmark_targets(bundle, profile, memberships)
            second = build_hallmark_targets(bundle, profile, memberships)
            out_a = save_hallmark_target(first, root / "a.json")
            out_b = save_hallmark_target(second, root / "b.json")
            self.assertEqual(out_a.read_bytes(), out_b.read_bytes())
            self.assertEqual(
                f"norman-hallmark-target-{digest_payload({k: v for k, v in first.items() if k != 'target_id'})[:16]}",
                first["target_id"],
            )

    def test_write_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, profile, memberships, _, _ = _fixture(root)
            target = build_hallmark_targets(bundle, profile, memberships)
            output = root / "target.json"
            save_hallmark_target(target, output)
            save_hallmark_target(target, output)  # identical rewrite is a no-op
            other = dict(target, dataset_id="tampered")
            with self.assertRaisesRegex(ValueError, "overwrite"):
                save_hallmark_target(other, output)


class LoadTargetTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, profile, memberships, _, _ = _fixture(root)
            target = build_hallmark_targets(bundle, profile, memberships)
            output = save_hallmark_target(target, root / "target.json")
            loaded = load_hallmark_target(output)
            self.assertEqual(target["target_id"], loaded.target_id)
            self.assertEqual(tuple(target["dims"]), loaded.dims)
            self.assertEqual(tuple(_INCLUDED_SETS), loaded.set_dims)
            self.assertEqual((_ZERO_SET,), loaded.excluded_sets)
            self.assertEqual(_ROLES, loaded.roles)
            self.assertEqual(len(_UNITS), len(loaded.units))
            self.assertEqual(64, len(loaded.target_digest))
            for entry, unit in zip(target["units"], loaded.units):
                self.assertEqual(entry["unit"], unit.unit)
                self.assertEqual(
                    tuple(entry["target"][dim] for dim in loaded.dims), unit.target
                )

    def test_loader_rejections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, profile, memberships, _, _ = _fixture(root)
            target = build_hallmark_targets(bundle, profile, memberships)
            output = save_hallmark_target(target, root / "target.json")
            good = json.loads(output.read_text(encoding="utf-8"))
            cases = []
            cases.append((dict(good, schema_version="other"), "unsupported"))
            bad_dims = json.loads(json.dumps(good))
            bad_dims["dims"][-1] = "HALLMARK_SNEAKY"
            cases.append((bad_dims, "six-node"))
            bad_coverage = json.loads(json.dumps(good))
            bad_coverage["coverage"].pop(_INCLUDED_SETS[0])
            cases.append((bad_coverage, "coverage keys"))
            bad_role = json.loads(json.dumps(good))
            bad_role["roles"]["AAA"] = "eval"
            cases.append((bad_role, "train or holdout"))
            bad_count = json.loads(json.dumps(good))
            bad_count["split"]["train_units"] = 99
            cases.append((bad_count, "train_units"))
            bad_centroid = json.loads(json.dumps(good))
            bad_centroid["centroid_train_only"].pop(_DIMS[0])
            cases.append((bad_centroid, "centroid_train_only"))
            bad_unit = json.loads(json.dumps(good))
            bad_unit["units"][0]["target"].pop(_DIMS[0])
            cases.append((bad_unit, "target keys"))
            for payload, fragment in cases:
                with self.subTest(fragment=fragment):
                    path = root / "case.json"
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, fragment):
                        load_hallmark_target(path)


class VectorMetricsDTests(unittest.TestCase):
    def test_hand_computed(self) -> None:
        metrics = vector_metrics_d([1.0, 2.0, 3.0], [1.0, 2.0, 4.0])
        self.assertAlmostEqual(1.0 / 3.0, metrics.mae, places=15)
        self.assertEqual(1.0, metrics.sign_agreement)
        self.assertEqual(1.0, metrics.spearman)
        flipped = vector_metrics_d([1.0, -2.0], [-1.0, -2.0])
        self.assertEqual(0.5, flipped.sign_agreement)
        constant = vector_metrics_d([1.0, 1.0], [2.0, 3.0])
        self.assertEqual(0.0, constant.spearman)

    def test_mean(self) -> None:
        first = vector_metrics_d([1.0, 2.0], [1.0, 4.0])
        second = vector_metrics_d([0.0, 0.0], [1.0, 1.0])
        mean = mean_metrics_d([first, second])
        self.assertAlmostEqual((1.0 + 1.0) / 2.0, mean.mae, places=15)
        self.assertAlmostEqual((1.0 + 0.0) / 2.0, mean.sign_agreement, places=15)

    def test_rejections(self) -> None:
        with self.assertRaisesRegex(ValueError, "equally long"):
            vector_metrics_d([1.0], [1.0, 2.0])
        with self.assertRaisesRegex(ValueError, "non-empty"):
            vector_metrics_d([], [])
        with self.assertRaisesRegex(ValueError, "finite"):
            vector_metrics_d([float("nan")], [0.0])
        with self.assertRaisesRegex(ValueError, "empty metric group"):
            mean_metrics_d([])


class CliRoundTripTests(unittest.TestCase):
    def test_hallmark_target_build_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gmt = _gmt(root)
            bundle_path = root / "bundle.json"
            bundle_path.write_text(
                json.dumps(_bundle_payload(gmt_sha256=_sha256(gmt))), encoding="utf-8"
            )
            bundle = load_empirical_bundle(bundle_path)
            profile_path = root / "profile.json"
            profile_path.write_text(
                json.dumps(_profile_payload(bundle.bundle_digest)), encoding="utf-8"
            )
            output = root / "target.json"
            stdout = StringIO()
            argv = [
                "mgba",
                "hallmark-target-build",
                "--bundle",
                str(bundle_path),
                "--profile",
                str(profile_path),
                "--hallmark",
                str(gmt),
                "--output",
                str(output),
            ]
            with mock.patch("sys.argv", argv), redirect_stdout(stdout):
                cli_main()
            result = json.loads(stdout.getvalue())
            self.assertEqual(TARGET_SCHEMA_VERSION, result["schema_version"])
            self.assertEqual(len(_DIMS), result["dims"])
            self.assertEqual([_ZERO_SET], result["excluded_sets"])
            self.assertEqual(len(_UNITS), result["units"])
            loaded = load_hallmark_target(output)
            self.assertEqual(result["target_id"], loaded.target_id)


if __name__ == "__main__":
    unittest.main()
