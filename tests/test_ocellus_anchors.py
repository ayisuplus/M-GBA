from __future__ import annotations

import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from mgba.experiment import digest_payload
from mgba.layers.l0 import ABSTRACT_GENE_NAMES
from mgba.ocellus_anchors import (
    HALLMARK_BRIDGE,
    HALLMARK_BRIDGE_DIGEST,
    HOLDOUT_SPLIT,
    OCELLUS_ANCHOR_SCHEMA_VERSION,
    PERTURBATION_REVIEW_SCHEMA_VERSION,
    REQUIRED_HALLMARK_SETS,
    TRAIN_SPLIT,
    HallmarkLibraryIdentity,
    HumanAnchorApproval,
    OfflineModelIdentity,
    PerturbationContext,
    PerturbationObservation,
    PerturbationScheduleCandidateSpec,
    SourceIdentity,
    aggregate_hallmark_bridge,
    build_ocellus_perturbation_anchor,
    compile_perturbation_schedule_candidate,
    save_ocellus_perturbation_anchor,
    save_perturbation_schedule_candidate,
    verify_ocellus_anchor_payload,
    verify_ocellus_perturbation_anchor,
)


def _memberships() -> dict[str, list[str]]:
    return {
        name: [f"GENE{index:02d}"]
        for index, name in enumerate(REQUIRED_HALLMARK_SETS)
    }


def _gene_values(node_values: dict[str, float]) -> dict[str, float]:
    memberships = _memberships()
    result: dict[str, float] = {}
    for node, hallmark_sets in HALLMARK_BRIDGE:
        for set_name in hallmark_sets:
            result[memberships[set_name][0]] = node_values[node]
    return result


def _node_values(
    damage: float,
    signal: float,
    repair: float,
    metabolic: float,
    death: float,
    feedback: float,
) -> dict[str, float]:
    return dict(
        zip(
            ABSTRACT_GENE_NAMES,
            (damage, signal, repair, metabolic, death, feedback),
            strict=True,
        )
    )


def _context(context_id: str) -> PerturbationContext:
    return PerturbationContext(
        context_id=context_id,
        cell_background="K562",
        control_state="non-targeting-control-centroid",
        dose="single-guide",
        timepoint="96h",
    )


def _observation(
    observation_id: str,
    split: str,
    context_id: str,
    knockout_gene: str,
    predicted: dict[str, float],
    empirical: dict[str, float],
) -> PerturbationObservation:
    return PerturbationObservation.from_mappings(
        observation_id=observation_id,
        split=split,
        context=_context(context_id),
        knockout_gene=knockout_gene,
        predicted_gene_log2fc=_gene_values(predicted),
        empirical_gene_log2fc=_gene_values(empirical),
    )


def _source() -> SourceIdentity:
    return SourceIdentity(
        dataset_id="replogle-perturbseq-processed",
        version="2022-processed-v1",
        sha256="a" * 64,
        license="CC-BY-4.0",
        rights_verified=True,
    )


def _model() -> OfflineModelIdentity:
    return OfflineModelIdentity(
        model_id="ocellus-candidate",
        version="offline-export-v1",
        weights_sha256="b" * 64,
        license="research-weights-license",
        rights_verified=True,
    )


def _hallmark() -> HallmarkLibraryIdentity:
    return HallmarkLibraryIdentity(
        collection_id="MSigDB-Hallmark",
        version="2026.1.Hs",
        sha256="c" * 64,
        license="MSigDB-terms",
        rights_verified=True,
    )


TRAIN_EMPIRICAL = _node_values(-0.5, -0.2, 0.1, 0.3, 0.5, 0.8)
HOLDOUT_EMPIRICAL = _node_values(-0.8, -0.4, 0.2, 0.5, 0.7, 0.9)
HOLDOUT_GOOD = _node_values(-0.75, -0.35, 0.25, 0.45, 0.65, 0.85)


def _passing_anchor():
    observations = (
        _observation(
            "train-001",
            TRAIN_SPLIT,
            "context-train",
            "TP53",
            TRAIN_EMPIRICAL,
            TRAIN_EMPIRICAL,
        ),
        _observation(
            "holdout-001",
            HOLDOUT_SPLIT,
            "context-holdout",
            "BRCA1",
            HOLDOUT_GOOD,
            HOLDOUT_EMPIRICAL,
        ),
    )
    return build_ocellus_perturbation_anchor(
        source=_source(),
        model=_model(),
        hallmark_library=_hallmark(),
        observations=observations,
        hallmark_memberships=_memberships(),
    )


def _negative_anchor():
    zero = _node_values(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    observations = (
        _observation(
            "train-001",
            TRAIN_SPLIT,
            "context-train",
            "TP53",
            TRAIN_EMPIRICAL,
            TRAIN_EMPIRICAL,
        ),
        _observation(
            "holdout-001",
            HOLDOUT_SPLIT,
            "context-holdout",
            "BRCA1",
            zero,
            TRAIN_EMPIRICAL,
        ),
    )
    return build_ocellus_perturbation_anchor(
        source=_source(),
        model=_model(),
        hallmark_library=_hallmark(),
        observations=observations,
        hallmark_memberships=_memberships(),
    )


class IdentityAndBridgeTests(unittest.TestCase):
    def test_source_model_and_hallmark_identity_are_fail_closed(self) -> None:
        for constructor, kwargs in (
            (
                SourceIdentity,
                {
                    "dataset_id": "source",
                    "version": "v1",
                    "sha256": "not-a-digest",
                    "license": "CC0",
                    "rights_verified": True,
                },
            ),
            (
                OfflineModelIdentity,
                {
                    "model_id": "model",
                    "version": "v1",
                    "weights_sha256": "d" * 64,
                    "license": "",
                    "rights_verified": True,
                },
            ),
            (
                HallmarkLibraryIdentity,
                {
                    "collection_id": "Hallmark",
                    "version": "v1",
                    "sha256": "e" * 64,
                    "license": "terms",
                    "rights_verified": False,
                },
            ),
        ):
            with self.subTest(constructor=constructor.__name__):
                with self.assertRaises(ValueError):
                    constructor(**kwargs)

        with self.assertRaises(ValueError):
            replace(_model(), network_used=True)
        with self.assertRaises(ValueError):
            replace(_model(), offline_inference=False)

    def test_frozen_bridge_uses_union_mean_and_reports_coverage(self) -> None:
        memberships = _memberships()
        damage_sets = dict(HALLMARK_BRIDGE)["damage_response"]
        memberships[damage_sets[0]] = ["SHARED", "DAMAGE_A"]
        memberships[damage_sets[1]] = ["SHARED", "DAMAGE_B"]
        effects = {gene: 0.0 for genes in memberships.values() for gene in genes}
        effects.update({"SHARED": 3.0, "DAMAGE_A": 0.0, "DAMAGE_B": 6.0})
        projection = aggregate_hallmark_bridge(effects, memberships)
        self.assertEqual(3.0, projection.value_map["damage_response"])
        coverage = projection.coverage_dict()["damage_response"]
        self.assertEqual(3, coverage["gene_count"])
        self.assertEqual(64, len(coverage["gene_digest"]))

    def test_bridge_rejects_missing_sets_and_missing_node_coverage(self) -> None:
        memberships = _memberships()
        memberships.pop(REQUIRED_HALLMARK_SETS[0])
        with self.assertRaises(ValueError):
            aggregate_hallmark_bridge({"GENE00": 1.0}, memberships)

        memberships = _memberships()
        effects = _gene_values(TRAIN_EMPIRICAL)
        repair_set = dict(HALLMARK_BRIDGE)["repair_expression"][0]
        effects.pop(memberships[repair_set][0])
        with self.assertRaisesRegex(ValueError, "repair_expression"):
            aggregate_hallmark_bridge(effects, memberships)

    def test_prediction_and_empirical_gene_universes_cannot_blur(self) -> None:
        predicted = _gene_values(TRAIN_EMPIRICAL)
        empirical = dict(predicted)
        empirical["EXTRA"] = 1.0
        with self.assertRaisesRegex(ValueError, "same explicit gene universe"):
            PerturbationObservation.from_mappings(
                observation_id="record",
                split=TRAIN_SPLIT,
                context=_context("context"),
                knockout_gene="TP53",
                predicted_gene_log2fc=predicted,
                empirical_gene_log2fc=empirical,
            )


class EvaluationProtocolTests(unittest.TestCase):
    def test_pass_uses_holdout_mae_and_reports_secondary_metrics(self) -> None:
        anchor = _passing_anchor()
        self.assertTrue(anchor.decision.passed)
        payload = anchor.as_dict()
        self.assertEqual(OCELLUS_ANCHOR_SCHEMA_VERSION, payload["schema_version"])
        self.assertEqual(HALLMARK_BRIDGE_DIGEST, payload["protocol"]["bridge_digest"])
        self.assertEqual("six_node_mae", payload["protocol"]["primary_metric"])
        self.assertEqual(
            ["sign_agreement", "spearman"],
            payload["protocol"]["secondary_metrics"],
        )
        holdout = payload["split_comparisons"][1]
        self.assertLess(
            holdout["model_metrics"]["six_node_mae"],
            holdout["baseline_metrics"]["six_node_mae"],
        )
        self.assertAlmostEqual(1.0, holdout["model_metrics"]["sign_agreement"])
        self.assertAlmostEqual(1.0, holdout["model_metrics"]["spearman"])
        record = payload["records"][0]
        self.assertIn("predicted_gene_log2fc", record)
        self.assertIn("empirical_gene_log2fc", record)
        self.assertNotEqual(
            id(record["predicted_gene_log2fc"]),
            id(record["empirical_gene_log2fc"]),
        )

    def test_train_only_centroid_is_reused_for_holdout(self) -> None:
        payload = _passing_anchor().as_dict()
        expected = next(
            record["empirical_six_node_log2fc"]
            for record in payload["records"]
            if record["split"] == TRAIN_SPLIT
        )
        for record in payload["records"]:
            self.assertEqual(expected, record["baseline_six_node_log2fc"])

    def test_negative_result_is_finite_and_preserved(self) -> None:
        anchor = _negative_anchor()
        self.assertFalse(anchor.decision.passed)
        holdout = anchor.as_dict()["split_comparisons"][1]
        self.assertTrue(math.isfinite(holdout["model_metrics"]["spearman"]))
        self.assertEqual(0.0, holdout["model_metrics"]["spearman"])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "negative.json"
            save_ocellus_perturbation_anchor(path, anchor)
            verified = verify_ocellus_perturbation_anchor(path)
            self.assertFalse(verified["decision"]["passed"])

    def test_train_holdout_units_must_be_disjoint(self) -> None:
        records = (
            _observation(
                "train",
                TRAIN_SPLIT,
                "same-context",
                "TP53",
                TRAIN_EMPIRICAL,
                TRAIN_EMPIRICAL,
            ),
            _observation(
                "holdout",
                HOLDOUT_SPLIT,
                "same-context",
                "TP53",
                HOLDOUT_GOOD,
                HOLDOUT_EMPIRICAL,
            ),
        )
        with self.assertRaisesRegex(ValueError, "split units overlap"):
            build_ocellus_perturbation_anchor(
                source=_source(),
                model=_model(),
                hallmark_library=_hallmark(),
                observations=records,
                hallmark_memberships=_memberships(),
            )

    def test_input_order_does_not_change_anchor_identity(self) -> None:
        first = _passing_anchor()
        raw = tuple(item.observation for item in first.records)
        second = build_ocellus_perturbation_anchor(
            source=_source(),
            model=_model(),
            hallmark_library=_hallmark(),
            observations=tuple(reversed(raw)),
            hallmark_memberships={
                name: _memberships()[name]
                for name in reversed(REQUIRED_HALLMARK_SETS)
            },
        )
        self.assertEqual(first.anchor_digest, second.anchor_digest)
        self.assertEqual(first.as_dict(), second.as_dict())


class ArtifactDisciplineTests(unittest.TestCase):
    def test_write_once_is_idempotent_and_refuses_conflicts(self) -> None:
        first = _passing_anchor()
        second = _negative_anchor()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "anchor.json"
            save_ocellus_perturbation_anchor(path, first)
            original = path.read_bytes()
            save_ocellus_perturbation_anchor(path, first)
            self.assertEqual(original, path.read_bytes())
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                save_ocellus_perturbation_anchor(path, second)

    def test_verifier_recomputes_metrics_even_if_attacker_updates_digest(self) -> None:
        payload = _passing_anchor().as_dict()
        payload["records"][1]["predicted_six_node_log2fc"]["repair_expression"] += 0.5
        core = {
            key: value
            for key, value in payload.items()
            if key not in {"anchor_id", "anchor_digest"}
        }
        payload["anchor_digest"] = digest_payload(core)
        payload["anchor_id"] = f"ocellus-anchor-{payload['anchor_digest'][:16]}"
        with self.assertRaisesRegex(ValueError, "bridge aggregation|model metrics"):
            verify_ocellus_anchor_payload(payload)

    def test_strict_schema_rejects_unknown_fields(self) -> None:
        payload = _passing_anchor().as_dict()
        payload["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "extra"):
            verify_ocellus_anchor_payload(payload)


class ReviewCandidateTests(unittest.TestCase):
    def _spec(self, observation_id: str = "holdout-001"):
        return PerturbationScheduleCandidateSpec(
            evidence_observation_id=observation_id,
            abstract_node="repair_expression",
            target_cell_ids=("cell-a", "cell-b"),
            l0_update_ticks=(1, 6),
            clamp_value=0.2,
        )

    def _approval(self, anchor, *, approved: bool = True, digest: str | None = None):
        return HumanAnchorApproval(
            reviewed_anchor_digest=digest or anchor.anchor_digest,
            reviewer_id="project-owner",
            decision_note="Reviewed as an L0 reference-model schedule candidate only.",
            approved=approved,
        )

    def test_passing_approved_holdout_compiles_runner_compatible_mapping(self) -> None:
        anchor = _passing_anchor()
        candidate = compile_perturbation_schedule_candidate(
            anchor,
            approval=self._approval(anchor),
            spec=self._spec(),
        )
        self.assertEqual(
            {
                1: {
                    "cell-a": {"repair_expression": 0.2},
                    "cell-b": {"repair_expression": 0.2},
                },
                6: {
                    "cell-a": {"repair_expression": 0.2},
                    "cell-b": {"repair_expression": 0.2},
                },
            },
            candidate.perturbation_schedule,
        )
        payload = candidate.as_dict()
        self.assertEqual(PERTURBATION_REVIEW_SCHEMA_VERSION, payload["schema_version"])
        self.assertFalse(payload["executed"])
        self.assertEqual(HOLDOUT_SPLIT, payload["evidence_split"])

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate.json"
            save_perturbation_schedule_candidate(path, candidate)
            first = path.read_bytes()
            save_perturbation_schedule_candidate(path, candidate)
            self.assertEqual(first, path.read_bytes())
            decoded = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(decoded["executed"])

    def test_negative_unapproved_wrong_digest_and_train_evidence_are_rejected(self) -> None:
        negative = _negative_anchor()
        with self.assertRaisesRegex(ValueError, "negative"):
            compile_perturbation_schedule_candidate(
                negative,
                approval=self._approval(negative),
                spec=self._spec(),
            )

        passing = _passing_anchor()
        with self.assertRaisesRegex(ValueError, "explicit human approval"):
            compile_perturbation_schedule_candidate(
                passing,
                approval=self._approval(passing, approved=False),
                spec=self._spec(),
            )
        with self.assertRaisesRegex(ValueError, "does not cover"):
            compile_perturbation_schedule_candidate(
                passing,
                approval=self._approval(passing, digest="f" * 64),
                spec=self._spec(),
            )
        with self.assertRaisesRegex(ValueError, "held-out"):
            compile_perturbation_schedule_candidate(
                passing,
                approval=self._approval(passing),
                spec=self._spec("train-001"),
            )


if __name__ == "__main__":
    unittest.main()
