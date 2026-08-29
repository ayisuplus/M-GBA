"""Offline OCellus perturbation anchors for the abstract M-GBA L0 layer.

This module is deliberately outside the L0--L4 generation loop.  It accepts
already-produced, gene-level offline predictions and matched empirical
Perturb-seq effects, projects both through a frozen Hallmark proxy bridge, and
compares the prediction with a transparent train-only centroid baseline.

No model is loaded here and no network, runner, PyTorch, or Qwen dependency is
used.  A successful anchor can only be compiled into an *unexecuted* review
candidate after a human approves the exact anchor digest.  It can never update
the GRN, construct a runner, or execute a perturbation itself.

The six L0 values remain abstract variables.  Hallmark aggregation is a proxy
for evaluation and does not turn those variables into real genes or establish
biological/clinical validity.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping, Sequence

from .experiment import digest_payload
from .layers.l0 import ABSTRACT_GENE_NAMES


OCELLUS_ANCHOR_SCHEMA_VERSION = "mgba-ocellus-perturbation-anchor-0.1"
PERTURBATION_REVIEW_SCHEMA_VERSION = "mgba-l0-perturbation-review-candidate-0.1"
HALLMARK_BRIDGE_VERSION = "mgba-hallmark-six-node-bridge-0.1"

TRAIN_SPLIT = "train"
HOLDOUT_SPLIT = "holdout"
SPLITS = (TRAIN_SPLIT, HOLDOUT_SPLIT)

BRIDGE_AGGREGATION = "unweighted-mean-over-deduplicated-hallmark-union-log2fc"
BASELINE_METHOD = "train-empirical-six-node-centroid"
PASS_RULE = "holdout-six-node-mae-strictly-better-than-train-centroid-baseline"
SPLIT_UNIT = "context_id+knockout_gene"
SCIENTIFIC_LEVEL = "reference_model"

# This is the proxy bridge recorded in data/aivc/README.md.  It freezes only
# the semantic mapping, not MSigDB membership.  Membership is supplied from an
# authorised local Hallmark collection and is represented in artifacts by
# digests/counts rather than redistributing the collection.
HALLMARK_BRIDGE: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "damage_response",
        ("HALLMARK_P53_PATHWAY", "HALLMARK_UV_RESPONSE_DN"),
    ),
    (
        "signal_expression",
        (
            "HALLMARK_TNFA_SIGNALING_VIA_NFKB",
            "HALLMARK_KRAS_SIGNALING_UP",
            "HALLMARK_IL6_JAK_STAT3_SIGNALING",
        ),
    ),
    ("repair_expression", ("HALLMARK_DNA_REPAIR",)),
    (
        "metabolic_expression",
        ("HALLMARK_OXIDATIVE_PHOSPHORYLATION", "HALLMARK_GLYCOLYSIS"),
    ),
    ("death_expression", ("HALLMARK_APOPTOSIS",)),
    ("negative_feedback_expression", ("HALLMARK_TGF_BETA_SIGNALING",)),
)

HALLMARK_BRIDGE_STRENGTHS: tuple[tuple[str, str], ...] = (
    ("damage_response", "medium"),
    ("signal_expression", "medium"),
    ("repair_expression", "strong"),
    ("metabolic_expression", "strong"),
    ("death_expression", "strong"),
    ("negative_feedback_expression", "weak-gap-proxy"),
)

REQUIRED_HALLMARK_SETS = tuple(
    sorted({name for _, names in HALLMARK_BRIDGE for name in names})
)

HALLMARK_BRIDGE_DIGEST = digest_payload(
    {
        "version": HALLMARK_BRIDGE_VERSION,
        "aggregation": BRIDGE_AGGREGATION,
        "nodes": {node: list(names) for node, names in HALLMARK_BRIDGE},
        "strengths": dict(HALLMARK_BRIDGE_STRENGTHS),
    }
)

SCIENTIFIC_BOUNDARY = (
    "gene-level empirical effects are the target; OCellus output is a candidate prediction",
    "Hallmark projections are frozen proxies for six abstract L0 variables, not real DNA",
    "pseudo-bulk differential expression is not single-cell temporal dynamics",
    "passing is reference-model evidence, not biological, clinical, or treatment validation",
    "the artifact never enters the L0-L4 tick loop or bypasses L1",
)

_GENE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_EPSILON = 1e-12


def _required_text(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a non-empty trimmed string")
    return value


def _sha256_text(value: Any, *, name: str) -> str:
    text = _required_text(value, name=name)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    return text


def _finite(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a real number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _exact_keys(raw: Mapping[str, Any], expected: set[str], *, name: str) -> None:
    actual = set(raw)
    if actual != expected:
        raise ValueError(
            f"{name} keys differ; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _gene_name(value: Any, *, name: str) -> str:
    gene = _required_text(value, name=name)
    if not _GENE_NAME.fullmatch(gene):
        raise ValueError(f"{name} is not a canonical gene identifier")
    return gene


def _canonical_gene_effects(
    values: Mapping[str, float] | Sequence[tuple[str, float]], *, name: str
) -> tuple[tuple[str, float], ...]:
    if isinstance(values, Mapping):
        items = list(values.items())
    elif isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        items = list(values)
    else:
        raise TypeError(f"{name} must be a mapping or pair sequence")
    if not items:
        raise ValueError(f"{name} must not be empty")
    normalized = []
    for index, item in enumerate(items):
        if not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) != 2:
            raise TypeError(f"{name}[{index}] must be a gene/value pair")
        gene = _gene_name(item[0], name=f"{name}[{index}] gene")
        normalized.append((gene, _finite(item[1], name=f"{name}[{gene}]")))
    genes = [gene for gene, _ in normalized]
    if len(genes) != len(set(genes)):
        raise ValueError(f"{name} gene identifiers must be unique")
    return tuple(sorted(normalized))


def _effect_dict(values: Sequence[tuple[str, float]]) -> dict[str, float]:
    return dict(values)


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """Versioned, licensed identity of the empirical Perturb-seq source."""

    dataset_id: str
    version: str
    sha256: str
    license: str
    rights_verified: bool

    def __post_init__(self) -> None:
        _required_text(self.dataset_id, name="source dataset_id")
        _required_text(self.version, name="source version")
        _sha256_text(self.sha256, name="source sha256")
        _required_text(self.license, name="source license")
        if self.rights_verified is not True:
            raise ValueError("source rights must be explicitly verified")

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "sha256": self.sha256,
            "license": self.license,
            "rights_verified": True,
        }


@dataclass(frozen=True, slots=True)
class OfflineModelIdentity:
    """Versioned OCellus identity; only offline, licensed weights are accepted."""

    model_id: str
    version: str
    weights_sha256: str
    license: str
    rights_verified: bool
    offline_inference: bool = True
    network_used: bool = False

    def __post_init__(self) -> None:
        _required_text(self.model_id, name="model_id")
        _required_text(self.version, name="model version")
        _sha256_text(self.weights_sha256, name="model weights_sha256")
        _required_text(self.license, name="model license")
        if self.rights_verified is not True:
            raise ValueError("model rights must be explicitly verified")
        if self.offline_inference is not True or self.network_used is not False:
            raise ValueError("OCellus anchors require offline inference with no network use")

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "weights_sha256": self.weights_sha256,
            "license": self.license,
            "rights_verified": True,
            "offline_inference": True,
            "network_used": False,
        }


@dataclass(frozen=True, slots=True)
class HallmarkLibraryIdentity:
    """Identity of the authorised local Hallmark membership collection."""

    collection_id: str
    version: str
    sha256: str
    license: str
    rights_verified: bool

    def __post_init__(self) -> None:
        _required_text(self.collection_id, name="Hallmark collection_id")
        _required_text(self.version, name="Hallmark version")
        _sha256_text(self.sha256, name="Hallmark sha256")
        _required_text(self.license, name="Hallmark license")
        if self.rights_verified is not True:
            raise ValueError("Hallmark collection rights must be explicitly verified")

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "version": self.version,
            "sha256": self.sha256,
            "license": self.license,
            "rights_verified": True,
        }


@dataclass(frozen=True, slots=True)
class PerturbationContext:
    context_id: str
    cell_background: str
    control_state: str
    dose: str
    timepoint: str

    def __post_init__(self) -> None:
        for field_name in (
            "context_id",
            "cell_background",
            "control_state",
            "dose",
            "timepoint",
        ):
            _required_text(getattr(self, field_name), name=f"context {field_name}")

    def as_dict(self) -> dict[str, str]:
        return {
            "context_id": self.context_id,
            "cell_background": self.cell_background,
            "control_state": self.control_state,
            "dose": self.dose,
            "timepoint": self.timepoint,
        }


@dataclass(frozen=True, slots=True)
class PerturbationObservation:
    """Matched prediction/target pair with deliberately separate gene channels."""

    observation_id: str
    split: str
    context: PerturbationContext
    knockout_gene: str
    predicted_gene_log2fc: tuple[tuple[str, float], ...]
    empirical_gene_log2fc: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        _required_text(self.observation_id, name="observation_id")
        if self.split not in SPLITS:
            raise ValueError("observation split must be train or holdout")
        if not isinstance(self.context, PerturbationContext):
            raise TypeError("observation context must be a PerturbationContext")
        _gene_name(self.knockout_gene, name="knockout_gene")
        predicted = _canonical_gene_effects(
            self.predicted_gene_log2fc, name="predicted_gene_log2fc"
        )
        empirical = _canonical_gene_effects(
            self.empirical_gene_log2fc, name="empirical_gene_log2fc"
        )
        if predicted != self.predicted_gene_log2fc:
            raise ValueError("predicted_gene_log2fc must be sorted by gene")
        if empirical != self.empirical_gene_log2fc:
            raise ValueError("empirical_gene_log2fc must be sorted by gene")
        if tuple(gene for gene, _ in predicted) != tuple(gene for gene, _ in empirical):
            raise ValueError(
                "predicted and empirical effects must use the same explicit gene universe"
            )

    @classmethod
    def from_mappings(
        cls,
        *,
        observation_id: str,
        split: str,
        context: PerturbationContext,
        knockout_gene: str,
        predicted_gene_log2fc: Mapping[str, float],
        empirical_gene_log2fc: Mapping[str, float],
    ) -> "PerturbationObservation":
        return cls(
            observation_id=observation_id,
            split=split,
            context=context,
            knockout_gene=knockout_gene,
            predicted_gene_log2fc=_canonical_gene_effects(
                predicted_gene_log2fc, name="predicted_gene_log2fc"
            ),
            empirical_gene_log2fc=_canonical_gene_effects(
                empirical_gene_log2fc, name="empirical_gene_log2fc"
            ),
        )

    @property
    def split_unit(self) -> str:
        return f"{self.context.context_id}+{self.knockout_gene}"


@dataclass(frozen=True, slots=True)
class SixNodeProjection:
    values: tuple[tuple[str, float], ...]
    coverage: tuple[tuple[str, tuple[str, ...], str], ...]

    def __post_init__(self) -> None:
        if tuple(name for name, _ in self.values) != ABSTRACT_GENE_NAMES:
            raise ValueError("six-node projection must use the frozen L0 order")
        if tuple(name for name, _, _ in self.coverage) != ABSTRACT_GENE_NAMES:
            raise ValueError("six-node coverage must use the frozen L0 order")
        for name, value in self.values:
            _finite(value, name=f"six-node projection {name}")
        for name, genes, digest in self.coverage:
            if (
                not genes
                or genes != tuple(sorted(genes))
                or len(genes) != len(set(genes))
            ):
                raise ValueError(
                    f"six-node coverage {name} genes must be non-empty, unique, and sorted"
                )
            for gene in genes:
                _gene_name(gene, name=f"six-node coverage {name} gene")
            if digest != digest_payload(genes):
                raise ValueError(f"six-node coverage {name} digest mismatch")
            _sha256_text(digest, name=f"six-node coverage {name} digest")

    @property
    def value_map(self) -> dict[str, float]:
        return dict(self.values)

    def coverage_dict(self) -> dict[str, dict[str, Any]]:
        return {
            name: {
                "genes": list(genes),
                "gene_count": len(genes),
                "gene_digest": digest,
            }
            for name, genes, digest in self.coverage
        }


@dataclass(frozen=True, slots=True)
class VectorMetrics:
    six_node_mae: float
    sign_agreement: float
    spearman: float

    def __post_init__(self) -> None:
        _finite(self.six_node_mae, name="six_node_mae")
        if self.six_node_mae < 0.0:
            raise ValueError("six_node_mae must be non-negative")
        for name in ("sign_agreement", "spearman"):
            value = _finite(getattr(self, name), name=name)
            lower = 0.0 if name == "sign_agreement" else -1.0
            if not lower <= value <= 1.0:
                raise ValueError(f"{name} is outside its valid range")

    def as_dict(self) -> dict[str, float]:
        return {
            "six_node_mae": self.six_node_mae,
            "sign_agreement": self.sign_agreement,
            "spearman": self.spearman,
        }


@dataclass(frozen=True, slots=True)
class EvaluatedObservation:
    observation: PerturbationObservation
    predicted_six_node_log2fc: tuple[tuple[str, float], ...]
    empirical_six_node_log2fc: tuple[tuple[str, float], ...]
    baseline_six_node_log2fc: tuple[tuple[str, float], ...]
    bridge_coverage: tuple[tuple[str, tuple[str, ...], str], ...]
    model_metrics: VectorMetrics
    baseline_metrics: VectorMetrics

    def as_dict(self) -> dict[str, Any]:
        item = self.observation
        return {
            "observation_id": item.observation_id,
            "split": item.split,
            "split_unit": item.split_unit,
            "context": item.context.as_dict(),
            "knockout_gene": item.knockout_gene,
            "predicted_gene_log2fc": dict(item.predicted_gene_log2fc),
            "empirical_gene_log2fc": dict(item.empirical_gene_log2fc),
            "bridge_coverage": SixNodeProjection(
                self.predicted_six_node_log2fc, self.bridge_coverage
            ).coverage_dict(),
            "predicted_six_node_log2fc": dict(self.predicted_six_node_log2fc),
            "empirical_six_node_log2fc": dict(self.empirical_six_node_log2fc),
            "baseline_six_node_log2fc": dict(self.baseline_six_node_log2fc),
            "model_metrics": self.model_metrics.as_dict(),
            "baseline_metrics": self.baseline_metrics.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class SplitComparison:
    split: str
    record_count: int
    model_metrics: VectorMetrics
    baseline_metrics: VectorMetrics

    def __post_init__(self) -> None:
        if self.split not in SPLITS:
            raise ValueError("split comparison must be train or holdout")
        if isinstance(self.record_count, bool) or not isinstance(self.record_count, int):
            raise TypeError("record_count must be an int")
        if self.record_count < 1:
            raise ValueError("record_count must be positive")

    def as_dict(self) -> dict[str, Any]:
        return {
            "split": self.split,
            "record_count": self.record_count,
            "model_metrics": self.model_metrics.as_dict(),
            "baseline_metrics": self.baseline_metrics.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class AnchorDecision:
    passed: bool
    holdout_mae_improvement: float
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise TypeError("anchor passed flag must be bool")
        _finite(self.holdout_mae_improvement, name="holdout_mae_improvement")
        _required_text(self.reason, name="anchor decision reason")

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "pass_rule": PASS_RULE,
            "holdout_mae_improvement": self.holdout_mae_improvement,
            "reason": self.reason,
            "scientific_level": SCIENTIFIC_LEVEL,
        }


@dataclass(frozen=True, slots=True)
class OCellusPerturbationAnchor:
    source: SourceIdentity
    model: OfflineModelIdentity
    hallmark_library: HallmarkLibraryIdentity
    hallmark_membership_digest: str
    hallmark_set_summaries: tuple[tuple[str, int, str], ...]
    records: tuple[EvaluatedObservation, ...]
    split_comparisons: tuple[SplitComparison, ...]
    decision: AnchorDecision

    def __post_init__(self) -> None:
        _sha256_text(
            self.hallmark_membership_digest, name="hallmark_membership_digest"
        )
        if tuple(name for name, _, _ in self.hallmark_set_summaries) != REQUIRED_HALLMARK_SETS:
            raise ValueError("Hallmark set summaries must cover the frozen bridge exactly")
        for name, count, digest in self.hallmark_set_summaries:
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise ValueError(f"Hallmark set {name} must contain at least one gene")
            _sha256_text(digest, name=f"Hallmark set {name} digest")
        if not self.records:
            raise ValueError("anchor must contain records")
        if tuple(item.observation.observation_id for item in self.records) != tuple(
            sorted(item.observation.observation_id for item in self.records)
        ):
            raise ValueError("anchor records must be sorted by observation_id")
        if tuple(item.split for item in self.split_comparisons) != SPLITS:
            raise ValueError("anchor needs train and holdout comparisons in order")

    def protocol_dict(self) -> dict[str, Any]:
        return {
            "bridge_version": HALLMARK_BRIDGE_VERSION,
            "bridge_digest": HALLMARK_BRIDGE_DIGEST,
            "node_to_hallmarks": {node: list(names) for node, names in HALLMARK_BRIDGE},
            "node_proxy_strength": dict(HALLMARK_BRIDGE_STRENGTHS),
            "aggregation": BRIDGE_AGGREGATION,
            "baseline_method": BASELINE_METHOD,
            "split_unit": SPLIT_UNIT,
            "pass_rule": PASS_RULE,
            "primary_metric": "six_node_mae",
            "secondary_metrics": ["sign_agreement", "spearman"],
        }

    def core_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol_dict(),
            "source": self.source.as_dict(),
            "model": self.model.as_dict(),
            "hallmark_library": {
                **self.hallmark_library.as_dict(),
                "membership_digest": self.hallmark_membership_digest,
                "set_summaries": {
                    name: {"gene_count": count, "gene_digest": digest}
                    for name, count, digest in self.hallmark_set_summaries
                },
            },
            "records": [item.as_dict() for item in self.records],
            "split_comparisons": [item.as_dict() for item in self.split_comparisons],
            "decision": self.decision.as_dict(),
            "scientific_boundary": list(SCIENTIFIC_BOUNDARY),
        }

    @property
    def anchor_digest(self) -> str:
        return digest_payload(
            {"schema_version": OCELLUS_ANCHOR_SCHEMA_VERSION, **self.core_dict()}
        )

    @property
    def anchor_id(self) -> str:
        return f"ocellus-anchor-{self.anchor_digest[:16]}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": OCELLUS_ANCHOR_SCHEMA_VERSION,
            "anchor_id": self.anchor_id,
            "anchor_digest": self.anchor_digest,
            **self.core_dict(),
        }


def _normalize_hallmark_memberships(
    memberships: Mapping[str, Sequence[str]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(memberships, Mapping):
        raise TypeError("hallmark memberships must be a mapping")
    if set(memberships) != set(REQUIRED_HALLMARK_SETS):
        raise ValueError("Hallmark memberships must cover the frozen bridge exactly")
    normalized = []
    for set_name in REQUIRED_HALLMARK_SETS:
        members = memberships[set_name]
        if isinstance(members, (str, bytes)) or not isinstance(members, Sequence):
            raise TypeError(f"Hallmark set {set_name} must be a gene sequence")
        genes = tuple(sorted(_gene_name(gene, name=f"{set_name} gene") for gene in members))
        if not genes or len(genes) != len(set(genes)):
            raise ValueError(f"Hallmark set {set_name} must contain unique genes")
        normalized.append((set_name, genes))
    return tuple(normalized)


def aggregate_hallmark_bridge(
    gene_log2fc: Mapping[str, float] | Sequence[tuple[str, float]],
    hallmark_memberships: Mapping[str, Sequence[str]],
) -> SixNodeProjection:
    """Project gene effects to the frozen six abstract nodes.

    For each node, member genes from its one or more Hallmark sets are unioned,
    deduplicated, intersected with the explicit effect universe, then averaged
    without weights.  Every node must have coverage; missing coverage fails
    instead of silently inserting zero.
    """

    effects = _canonical_gene_effects(gene_log2fc, name="gene_log2fc")
    effect_map = _effect_dict(effects)
    memberships = dict(_normalize_hallmark_memberships(hallmark_memberships))
    values = []
    coverage = []
    for node, hallmark_sets in HALLMARK_BRIDGE:
        union = sorted(
            {gene for set_name in hallmark_sets for gene in memberships[set_name]}
            & set(effect_map)
        )
        if not union:
            raise ValueError(f"Hallmark bridge node {node} has no gene-level coverage")
        values.append((node, fmean(effect_map[gene] for gene in union)))
        genes = tuple(union)
        coverage.append((node, genes, digest_payload(genes)))
    return SixNodeProjection(values=tuple(values), coverage=tuple(coverage))


def _average_ranks(values: Sequence[float]) -> tuple[float, ...]:
    ranked = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    output = [0.0] * len(values)
    cursor = 0
    while cursor < len(ranked):
        end = cursor + 1
        while end < len(ranked) and ranked[end][1] == ranked[cursor][1]:
            end += 1
        rank = ((cursor + 1) + end) / 2.0
        for index in range(cursor, end):
            output[ranked[index][0]] = rank
        cursor = end
    return tuple(output)


def _spearman(predicted: Sequence[float], empirical: Sequence[float]) -> float:
    left = _average_ranks(predicted)
    right = _average_ranks(empirical)
    left_mean = fmean(left)
    right_mean = fmean(right)
    numerator = sum(
        (x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True)
    )
    left_ss = sum((value - left_mean) ** 2 for value in left)
    right_ss = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_ss * right_ss)
    # A constant vector has undefined rank correlation.  Preserve the negative
    # result as finite zero instead of dropping the record or fabricating 1.0.
    return 0.0 if denominator == 0.0 else numerator / denominator


def _sign(value: float) -> int:
    return 1 if value > 0.0 else (-1 if value < 0.0 else 0)


def _vector_metrics(
    predicted: Sequence[tuple[str, float]], empirical: Sequence[tuple[str, float]]
) -> VectorMetrics:
    if tuple(name for name, _ in predicted) != ABSTRACT_GENE_NAMES:
        raise ValueError("predicted vector must use the frozen six-node order")
    if tuple(name for name, _ in empirical) != ABSTRACT_GENE_NAMES:
        raise ValueError("empirical vector must use the frozen six-node order")
    left = [value for _, value in predicted]
    right = [value for _, value in empirical]
    return VectorMetrics(
        six_node_mae=fmean(abs(x - y) for x, y in zip(left, right, strict=True)),
        sign_agreement=fmean(
            float(_sign(x) == _sign(y)) for x, y in zip(left, right, strict=True)
        ),
        spearman=_spearman(left, right),
    )


def _mean_metrics(items: Sequence[VectorMetrics]) -> VectorMetrics:
    if not items:
        raise ValueError("cannot summarize an empty metric group")
    return VectorMetrics(
        six_node_mae=fmean(item.six_node_mae for item in items),
        sign_agreement=fmean(item.sign_agreement for item in items),
        spearman=fmean(item.spearman for item in items),
    )


def _validate_split_discipline(observations: Sequence[PerturbationObservation]) -> None:
    ids = [item.observation_id for item in observations]
    if len(ids) != len(set(ids)):
        raise ValueError("observation_id values must be unique")
    units = {
        split: {item.split_unit for item in observations if item.split == split}
        for split in SPLITS
    }
    if not units[TRAIN_SPLIT] or not units[HOLDOUT_SPLIT]:
        raise ValueError("anchor requires non-empty train and holdout splits")
    overlap = units[TRAIN_SPLIT] & units[HOLDOUT_SPLIT]
    if overlap:
        raise ValueError(f"train/holdout split units overlap: {sorted(overlap)}")


def build_ocellus_perturbation_anchor(
    *,
    source: SourceIdentity,
    model: OfflineModelIdentity,
    hallmark_library: HallmarkLibraryIdentity,
    observations: Sequence[PerturbationObservation],
    hallmark_memberships: Mapping[str, Sequence[str]],
) -> OCellusPerturbationAnchor:
    """Build and evaluate a deterministic offline anchor, including failures."""

    if not isinstance(source, SourceIdentity):
        raise TypeError("source must be a SourceIdentity")
    if not isinstance(model, OfflineModelIdentity):
        raise TypeError("model must be an OfflineModelIdentity")
    if not isinstance(hallmark_library, HallmarkLibraryIdentity):
        raise TypeError("hallmark_library must be a HallmarkLibraryIdentity")
    if isinstance(observations, (str, bytes)) or not isinstance(observations, Sequence):
        raise TypeError("observations must be a sequence")
    if any(not isinstance(item, PerturbationObservation) for item in observations):
        raise TypeError("every observation must be a PerturbationObservation")
    ordered = tuple(sorted(observations, key=lambda item: item.observation_id))
    _validate_split_discipline(ordered)

    normalized_memberships = _normalize_hallmark_memberships(hallmark_memberships)
    normalized_map = dict(normalized_memberships)
    membership_digest = digest_payload(
        {name: list(genes) for name, genes in normalized_memberships}
    )
    set_summaries = tuple(
        (name, len(genes), digest_payload(genes))
        for name, genes in normalized_memberships
    )

    projections = []
    for item in ordered:
        predicted = aggregate_hallmark_bridge(
            item.predicted_gene_log2fc, normalized_map
        )
        empirical = aggregate_hallmark_bridge(
            item.empirical_gene_log2fc, normalized_map
        )
        if predicted.coverage != empirical.coverage:
            raise ValueError("predicted and empirical bridge coverage must be identical")
        projections.append((item, predicted, empirical))

    train_empirical = [
        empirical.value_map
        for item, _, empirical in projections
        if item.split == TRAIN_SPLIT
    ]
    centroid = tuple(
        (node, fmean(values[node] for values in train_empirical))
        for node in ABSTRACT_GENE_NAMES
    )

    evaluated = []
    for item, predicted, empirical in projections:
        evaluated.append(
            EvaluatedObservation(
                observation=item,
                predicted_six_node_log2fc=predicted.values,
                empirical_six_node_log2fc=empirical.values,
                baseline_six_node_log2fc=centroid,
                bridge_coverage=predicted.coverage,
                model_metrics=_vector_metrics(predicted.values, empirical.values),
                baseline_metrics=_vector_metrics(centroid, empirical.values),
            )
        )

    split_comparisons = tuple(
        SplitComparison(
            split=split,
            record_count=len(group),
            model_metrics=_mean_metrics([item.model_metrics for item in group]),
            baseline_metrics=_mean_metrics([item.baseline_metrics for item in group]),
        )
        for split in SPLITS
        for group in [[item for item in evaluated if item.observation.split == split]]
    )
    holdout = dict((item.split, item) for item in split_comparisons)[HOLDOUT_SPLIT]
    improvement = (
        holdout.baseline_metrics.six_node_mae
        - holdout.model_metrics.six_node_mae
    )
    passed = improvement > _EPSILON
    decision = AnchorDecision(
        passed=passed,
        holdout_mae_improvement=improvement,
        reason=(
            "holdout OCellus MAE is strictly lower than the train-only centroid baseline"
            if passed
            else "holdout OCellus MAE did not strictly improve on the train-only centroid baseline"
        ),
    )
    anchor = OCellusPerturbationAnchor(
        source=source,
        model=model,
        hallmark_library=hallmark_library,
        hallmark_membership_digest=membership_digest,
        hallmark_set_summaries=set_summaries,
        records=tuple(evaluated),
        split_comparisons=split_comparisons,
        decision=decision,
    )
    verify_ocellus_anchor_payload(anchor.as_dict())
    return anchor


def _metrics_from_raw(raw: Mapping[str, Any], *, name: str) -> VectorMetrics:
    _exact_keys(raw, {"six_node_mae", "sign_agreement", "spearman"}, name=name)
    return VectorMetrics(
        six_node_mae=_finite(raw["six_node_mae"], name=f"{name}.six_node_mae"),
        sign_agreement=_finite(raw["sign_agreement"], name=f"{name}.sign_agreement"),
        spearman=_finite(raw["spearman"], name=f"{name}.spearman"),
    )


def _six_vector_from_raw(raw: Mapping[str, Any], *, name: str) -> tuple[tuple[str, float], ...]:
    _exact_keys(raw, set(ABSTRACT_GENE_NAMES), name=name)
    return tuple(
        (node, _finite(raw[node], name=f"{name}.{node}"))
        for node in ABSTRACT_GENE_NAMES
    )


def _metrics_equal(left: VectorMetrics, right: VectorMetrics) -> bool:
    return left.as_dict() == right.as_dict()


def verify_ocellus_anchor_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Strictly verify an in-memory artifact and return a plain deep copy."""

    if not isinstance(payload, Mapping):
        raise TypeError("OCellus anchor payload must be an object")
    raw = dict(payload)
    _exact_keys(
        raw,
        {
            "schema_version",
            "anchor_id",
            "anchor_digest",
            "protocol",
            "source",
            "model",
            "hallmark_library",
            "records",
            "split_comparisons",
            "decision",
            "scientific_boundary",
        },
        name="OCellus anchor",
    )
    if raw["schema_version"] != OCELLUS_ANCHOR_SCHEMA_VERSION:
        raise ValueError("unsupported OCellus anchor schema")

    source_raw = raw["source"]
    if not isinstance(source_raw, Mapping):
        raise ValueError("anchor source must be an object")
    _exact_keys(
        source_raw,
        {"dataset_id", "version", "sha256", "license", "rights_verified"},
        name="anchor source",
    )
    SourceIdentity(**source_raw)

    model_raw = raw["model"]
    if not isinstance(model_raw, Mapping):
        raise ValueError("anchor model must be an object")
    _exact_keys(
        model_raw,
        {
            "model_id",
            "version",
            "weights_sha256",
            "license",
            "rights_verified",
            "offline_inference",
            "network_used",
        },
        name="anchor model",
    )
    OfflineModelIdentity(**model_raw)

    hallmark_raw = raw["hallmark_library"]
    if not isinstance(hallmark_raw, Mapping):
        raise ValueError("hallmark_library must be an object")
    _exact_keys(
        hallmark_raw,
        {
            "collection_id",
            "version",
            "sha256",
            "license",
            "rights_verified",
            "membership_digest",
            "set_summaries",
        },
        name="hallmark_library",
    )
    HallmarkLibraryIdentity(
        collection_id=hallmark_raw["collection_id"],
        version=hallmark_raw["version"],
        sha256=hallmark_raw["sha256"],
        license=hallmark_raw["license"],
        rights_verified=hallmark_raw["rights_verified"],
    )
    _sha256_text(hallmark_raw["membership_digest"], name="membership_digest")
    summaries = hallmark_raw["set_summaries"]
    if not isinstance(summaries, Mapping):
        raise ValueError("Hallmark set_summaries must be an object")
    _exact_keys(summaries, set(REQUIRED_HALLMARK_SETS), name="Hallmark set_summaries")
    for set_name, summary in summaries.items():
        if not isinstance(summary, Mapping):
            raise ValueError("Hallmark set summary must be an object")
        _exact_keys(summary, {"gene_count", "gene_digest"}, name=f"summary {set_name}")
        if (
            isinstance(summary["gene_count"], bool)
            or not isinstance(summary["gene_count"], int)
            or summary["gene_count"] < 1
        ):
            raise ValueError("Hallmark set gene_count must be positive")
        _sha256_text(summary["gene_digest"], name=f"summary {set_name} digest")

    protocol = raw["protocol"]
    expected_protocol = {
        "bridge_version": HALLMARK_BRIDGE_VERSION,
        "bridge_digest": HALLMARK_BRIDGE_DIGEST,
        "node_to_hallmarks": {node: list(names) for node, names in HALLMARK_BRIDGE},
        "node_proxy_strength": dict(HALLMARK_BRIDGE_STRENGTHS),
        "aggregation": BRIDGE_AGGREGATION,
        "baseline_method": BASELINE_METHOD,
        "split_unit": SPLIT_UNIT,
        "pass_rule": PASS_RULE,
        "primary_metric": "six_node_mae",
        "secondary_metrics": ["sign_agreement", "spearman"],
    }
    if protocol != expected_protocol:
        raise ValueError("anchor protocol differs from the frozen OCellus protocol")
    if raw["scientific_boundary"] != list(SCIENTIFIC_BOUNDARY):
        raise ValueError("anchor scientific boundary differs from the frozen boundary")

    records_raw = raw["records"]
    if not isinstance(records_raw, list) or not records_raw:
        raise ValueError("anchor records must be a non-empty list")
    expected_record_keys = {
        "observation_id",
        "split",
        "split_unit",
        "context",
        "knockout_gene",
        "predicted_gene_log2fc",
        "empirical_gene_log2fc",
        "bridge_coverage",
        "predicted_six_node_log2fc",
        "empirical_six_node_log2fc",
        "baseline_six_node_log2fc",
        "model_metrics",
        "baseline_metrics",
    }
    verified_records = []
    observation_ids = []
    split_units: dict[str, set[str]] = {split: set() for split in SPLITS}
    for index, record in enumerate(records_raw):
        if not isinstance(record, Mapping):
            raise ValueError(f"anchor record {index} must be an object")
        _exact_keys(record, expected_record_keys, name=f"anchor record {index}")
        observation_id = _required_text(record["observation_id"], name="observation_id")
        observation_ids.append(observation_id)
        split = record["split"]
        if split not in SPLITS:
            raise ValueError("record split must be train or holdout")
        context_raw = record["context"]
        if not isinstance(context_raw, Mapping):
            raise ValueError("record context must be an object")
        _exact_keys(
            context_raw,
            {"context_id", "cell_background", "control_state", "dose", "timepoint"},
            name="record context",
        )
        context = PerturbationContext(**context_raw)
        knockout_gene = _gene_name(record["knockout_gene"], name="knockout_gene")
        expected_unit = f"{context.context_id}+{knockout_gene}"
        if record["split_unit"] != expected_unit:
            raise ValueError("record split_unit does not match context and KO gene")
        split_units[split].add(expected_unit)

        predicted_gene_raw = record["predicted_gene_log2fc"]
        empirical_gene_raw = record["empirical_gene_log2fc"]
        if not isinstance(predicted_gene_raw, Mapping) or not isinstance(empirical_gene_raw, Mapping):
            raise ValueError("gene-level prediction and target must be separate objects")
        predicted_gene = _canonical_gene_effects(predicted_gene_raw, name="predicted_gene_log2fc")
        empirical_gene = _canonical_gene_effects(empirical_gene_raw, name="empirical_gene_log2fc")
        if tuple(name for name, _ in predicted_gene) != tuple(name for name, _ in empirical_gene):
            raise ValueError("predicted and empirical gene universes differ")

        predicted = _six_vector_from_raw(
            record["predicted_six_node_log2fc"], name="predicted_six_node_log2fc"
        )
        empirical = _six_vector_from_raw(
            record["empirical_six_node_log2fc"], name="empirical_six_node_log2fc"
        )
        baseline = _six_vector_from_raw(
            record["baseline_six_node_log2fc"], name="baseline_six_node_log2fc"
        )
        coverage_raw = record["bridge_coverage"]
        if not isinstance(coverage_raw, Mapping):
            raise ValueError("bridge_coverage must be an object")
        _exact_keys(coverage_raw, set(ABSTRACT_GENE_NAMES), name="bridge_coverage")
        predicted_gene_map = dict(predicted_gene)
        empirical_gene_map = dict(empirical_gene)
        for node, coverage in coverage_raw.items():
            if not isinstance(coverage, Mapping):
                raise ValueError("bridge node coverage must be an object")
            _exact_keys(
                coverage,
                {"genes", "gene_count", "gene_digest"},
                name=f"coverage {node}",
            )
            genes_raw = coverage["genes"]
            if not isinstance(genes_raw, list):
                raise ValueError("bridge coverage genes must be a list")
            genes = tuple(
                _gene_name(gene, name=f"coverage {node} gene")
                for gene in genes_raw
            )
            if not genes or genes != tuple(sorted(genes)) or len(genes) != len(set(genes)):
                raise ValueError("bridge coverage genes must be non-empty, unique, and sorted")
            if not set(genes) <= set(predicted_gene_map):
                raise ValueError("bridge coverage genes must belong to the explicit gene universe")
            if (
                isinstance(coverage["gene_count"], bool)
                or not isinstance(coverage["gene_count"], int)
                or coverage["gene_count"] != len(genes)
            ):
                raise ValueError("bridge coverage count must match its gene list")
            coverage_digest = _sha256_text(
                coverage["gene_digest"], name=f"coverage {node} digest"
            )
            if coverage_digest != digest_payload(genes):
                raise ValueError("bridge coverage digest does not match its gene list")
            predicted_value = fmean(predicted_gene_map[gene] for gene in genes)
            empirical_value = fmean(empirical_gene_map[gene] for gene in genes)
            if dict(predicted)[node] != predicted_value:
                raise ValueError("stored prediction does not match gene-level bridge aggregation")
            if dict(empirical)[node] != empirical_value:
                raise ValueError("stored target does not match gene-level bridge aggregation")

        model_metrics = _metrics_from_raw(record["model_metrics"], name="model_metrics")
        baseline_metrics = _metrics_from_raw(
            record["baseline_metrics"], name="baseline_metrics"
        )
        if not _metrics_equal(model_metrics, _vector_metrics(predicted, empirical)):
            raise ValueError("record model metrics do not match stored six-node vectors")
        if not _metrics_equal(baseline_metrics, _vector_metrics(baseline, empirical)):
            raise ValueError("record baseline metrics do not match stored six-node vectors")
        verified_records.append(
            {
                "split": split,
                "predicted": predicted,
                "empirical": empirical,
                "baseline": baseline,
                "model_metrics": model_metrics,
                "baseline_metrics": baseline_metrics,
            }
        )

    if observation_ids != sorted(observation_ids) or len(observation_ids) != len(set(observation_ids)):
        raise ValueError("anchor records must have unique sorted observation_id values")
    if not split_units[TRAIN_SPLIT] or not split_units[HOLDOUT_SPLIT]:
        raise ValueError("anchor requires non-empty train and holdout splits")
    overlap = split_units[TRAIN_SPLIT] & split_units[HOLDOUT_SPLIT]
    if overlap:
        raise ValueError(f"train/holdout split units overlap: {sorted(overlap)}")

    train_empirical = [
        dict(item["empirical"])
        for item in verified_records
        if item["split"] == TRAIN_SPLIT
    ]
    centroid = tuple(
        (node, fmean(item[node] for item in train_empirical))
        for node in ABSTRACT_GENE_NAMES
    )
    if any(item["baseline"] != centroid for item in verified_records):
        raise ValueError("baseline vectors are not the train-only empirical centroid")

    comparison_raw = raw["split_comparisons"]
    if not isinstance(comparison_raw, list) or len(comparison_raw) != 2:
        raise ValueError("split_comparisons must contain train and holdout")
    verified_comparisons = []
    for expected_split, item in zip(SPLITS, comparison_raw, strict=True):
        if not isinstance(item, Mapping):
            raise ValueError("split comparison must be an object")
        _exact_keys(
            item,
            {"split", "record_count", "model_metrics", "baseline_metrics"},
            name="split comparison",
        )
        if item["split"] != expected_split:
            raise ValueError("split comparisons must be train then holdout")
        group = [record for record in verified_records if record["split"] == expected_split]
        if item["record_count"] != len(group):
            raise ValueError("split comparison record_count mismatch")
        model_metrics = _metrics_from_raw(item["model_metrics"], name="split model metrics")
        baseline_metrics = _metrics_from_raw(
            item["baseline_metrics"], name="split baseline metrics"
        )
        if not _metrics_equal(
            model_metrics, _mean_metrics([record["model_metrics"] for record in group])
        ):
            raise ValueError("split model metrics mismatch")
        if not _metrics_equal(
            baseline_metrics,
            _mean_metrics([record["baseline_metrics"] for record in group]),
        ):
            raise ValueError("split baseline metrics mismatch")
        verified_comparisons.append((expected_split, model_metrics, baseline_metrics))

    holdout = dict((split, (model, baseline)) for split, model, baseline in verified_comparisons)[
        HOLDOUT_SPLIT
    ]
    improvement = holdout[1].six_node_mae - holdout[0].six_node_mae
    passed = improvement > _EPSILON
    expected_decision = AnchorDecision(
        passed=passed,
        holdout_mae_improvement=improvement,
        reason=(
            "holdout OCellus MAE is strictly lower than the train-only centroid baseline"
            if passed
            else "holdout OCellus MAE did not strictly improve on the train-only centroid baseline"
        ),
    ).as_dict()
    if raw["decision"] != expected_decision:
        raise ValueError("anchor decision does not match the frozen holdout rule")

    digest = _sha256_text(raw["anchor_digest"], name="anchor_digest")
    core = {
        key: value
        for key, value in raw.items()
        if key not in {"anchor_id", "anchor_digest"}
    }
    expected_digest = digest_payload(core)
    if digest != expected_digest:
        raise ValueError("OCellus anchor digest mismatch")
    if raw["anchor_id"] != f"ocellus-anchor-{digest[:16]}":
        raise ValueError("OCellus anchor_id does not match its digest")
    return json.loads(json.dumps(raw, ensure_ascii=False, allow_nan=False))


def verify_ocellus_perturbation_anchor(path: str | Path) -> dict[str, Any]:
    try:
        raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid OCellus perturbation anchor: {error}") from error
    return verify_ocellus_anchor_payload(raw)


def _write_json_once(path: Path, payload: dict[str, Any], *, artifact_name: str) -> None:
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"cannot verify existing {artifact_name}: {error}") from error
        if existing != payload:
            raise ValueError(f"refusing to overwrite a different {artifact_name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def save_ocellus_perturbation_anchor(
    path: str | Path, anchor: OCellusPerturbationAnchor
) -> Path:
    """Save a passing or negative anchor with idempotent write-once semantics."""

    if not isinstance(anchor, OCellusPerturbationAnchor):
        raise TypeError("save_ocellus_perturbation_anchor requires an anchor")
    payload = anchor.as_dict()
    verify_ocellus_anchor_payload(payload)
    output = Path(path)
    _write_json_once(output, payload, artifact_name="OCellus perturbation anchor")
    return output


@dataclass(frozen=True, slots=True)
class HumanAnchorApproval:
    reviewed_anchor_digest: str
    reviewer_id: str
    decision_note: str
    approved: bool

    def __post_init__(self) -> None:
        _sha256_text(self.reviewed_anchor_digest, name="reviewed_anchor_digest")
        _required_text(self.reviewer_id, name="reviewer_id")
        _required_text(self.decision_note, name="decision_note")
        if not isinstance(self.approved, bool):
            raise TypeError("approved must be bool")


@dataclass(frozen=True, slots=True)
class PerturbationScheduleCandidateSpec:
    evidence_observation_id: str
    abstract_node: str
    target_cell_ids: tuple[str, ...]
    l0_update_ticks: tuple[int, ...]
    clamp_value: float

    def __post_init__(self) -> None:
        _required_text(self.evidence_observation_id, name="evidence_observation_id")
        if self.abstract_node not in ABSTRACT_GENE_NAMES:
            raise ValueError("abstract_node must be one of the six frozen L0 nodes")
        if (
            not self.target_cell_ids
            or self.target_cell_ids != tuple(sorted(self.target_cell_ids))
            or len(self.target_cell_ids) != len(set(self.target_cell_ids))
        ):
            raise ValueError("target_cell_ids must be non-empty, unique, and sorted")
        for cell_id in self.target_cell_ids:
            _required_text(cell_id, name="target cell_id")
        if (
            not self.l0_update_ticks
            or self.l0_update_ticks != tuple(sorted(self.l0_update_ticks))
            or len(self.l0_update_ticks) != len(set(self.l0_update_ticks))
            or any(
                isinstance(tick, bool) or not isinstance(tick, int) or tick < 1
                for tick in self.l0_update_ticks
            )
        ):
            raise ValueError("l0_update_ticks must be positive, unique, and sorted")
        value = _finite(self.clamp_value, name="clamp_value")
        if not 0.0 <= value <= 1.0:
            raise ValueError("clamp_value must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class PerturbationScheduleReviewCandidate:
    anchor_id: str
    anchor_digest: str
    evidence_observation_id: str
    evidence_split: str
    abstract_node: str
    predicted_node_log2fc: float
    target_cell_ids: tuple[str, ...]
    l0_update_ticks: tuple[int, ...]
    clamp_value: float
    reviewer_id: str
    approval_note: str

    def __post_init__(self) -> None:
        _required_text(self.anchor_id, name="candidate anchor_id")
        digest = _sha256_text(self.anchor_digest, name="candidate anchor_digest")
        if self.anchor_id != f"ocellus-anchor-{digest[:16]}":
            raise ValueError("candidate anchor_id does not match anchor_digest")
        _required_text(
            self.evidence_observation_id, name="candidate evidence_observation_id"
        )
        if self.evidence_split != HOLDOUT_SPLIT:
            raise ValueError("review candidates require held-out evidence")
        if self.abstract_node not in ABSTRACT_GENE_NAMES:
            raise ValueError("candidate abstract_node is not a frozen L0 node")
        _finite(self.predicted_node_log2fc, name="candidate predicted_node_log2fc")
        PerturbationScheduleCandidateSpec(
            evidence_observation_id=self.evidence_observation_id,
            abstract_node=self.abstract_node,
            target_cell_ids=self.target_cell_ids,
            l0_update_ticks=self.l0_update_ticks,
            clamp_value=self.clamp_value,
        )
        _required_text(self.reviewer_id, name="candidate reviewer_id")
        _required_text(self.approval_note, name="candidate approval_note")

    @property
    def perturbation_schedule(self) -> dict[int, dict[str, dict[str, float]]]:
        return {
            tick: {
                cell_id: {self.abstract_node: self.clamp_value}
                for cell_id in self.target_cell_ids
            }
            for tick in self.l0_update_ticks
        }

    def core_dict(self) -> dict[str, Any]:
        return {
            "anchor_id": self.anchor_id,
            "anchor_digest": self.anchor_digest,
            "evidence_observation_id": self.evidence_observation_id,
            "evidence_split": self.evidence_split,
            "abstract_node": self.abstract_node,
            "predicted_node_log2fc": self.predicted_node_log2fc,
            "target_cell_ids": list(self.target_cell_ids),
            "l0_update_ticks": list(self.l0_update_ticks),
            "clamp_value": self.clamp_value,
            "human_approval": {
                "approved": True,
                "reviewed_anchor_digest": self.anchor_digest,
                "reviewer_id": self.reviewer_id,
                "decision_note": self.approval_note,
            },
            "perturbation_schedule": [
                {
                    "logical_time": tick,
                    "cell_perturbations": self.perturbation_schedule[tick],
                }
                for tick in self.l0_update_ticks
            ],
            "executed": False,
            "scientific_level": SCIENTIFIC_LEVEL,
        }

    @property
    def candidate_id(self) -> str:
        return f"l0-review-{digest_payload(self.core_dict())[:16]}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PERTURBATION_REVIEW_SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            **self.core_dict(),
        }


def compile_perturbation_schedule_candidate(
    anchor: OCellusPerturbationAnchor,
    *,
    approval: HumanAnchorApproval,
    spec: PerturbationScheduleCandidateSpec,
) -> PerturbationScheduleReviewCandidate:
    """Compile an approved passing holdout anchor into an unexecuted candidate."""

    if not isinstance(anchor, OCellusPerturbationAnchor):
        raise TypeError("anchor must be an OCellusPerturbationAnchor")
    if not isinstance(approval, HumanAnchorApproval):
        raise TypeError("approval must be a HumanAnchorApproval")
    if not isinstance(spec, PerturbationScheduleCandidateSpec):
        raise TypeError("spec must be a PerturbationScheduleCandidateSpec")
    verify_ocellus_anchor_payload(anchor.as_dict())
    if not anchor.decision.passed:
        raise ValueError("a negative OCellus anchor cannot produce a schedule candidate")
    if approval.approved is not True:
        raise ValueError("the exact passing anchor requires explicit human approval")
    if approval.reviewed_anchor_digest != anchor.anchor_digest:
        raise ValueError("human approval does not cover this anchor digest")
    by_id = {
        item.observation.observation_id: item
        for item in anchor.records
    }
    if spec.evidence_observation_id not in by_id:
        raise ValueError("schedule candidate references an unknown anchor observation")
    evidence = by_id[spec.evidence_observation_id]
    if evidence.observation.split != HOLDOUT_SPLIT:
        raise ValueError("schedule candidates require held-out evidence")
    return PerturbationScheduleReviewCandidate(
        anchor_id=anchor.anchor_id,
        anchor_digest=anchor.anchor_digest,
        evidence_observation_id=spec.evidence_observation_id,
        evidence_split=HOLDOUT_SPLIT,
        abstract_node=spec.abstract_node,
        predicted_node_log2fc=dict(evidence.predicted_six_node_log2fc)[
            spec.abstract_node
        ],
        target_cell_ids=spec.target_cell_ids,
        l0_update_ticks=spec.l0_update_ticks,
        clamp_value=spec.clamp_value,
        reviewer_id=approval.reviewer_id,
        approval_note=approval.decision_note,
    )


def save_perturbation_schedule_candidate(
    path: str | Path, candidate: PerturbationScheduleReviewCandidate
) -> Path:
    if not isinstance(candidate, PerturbationScheduleReviewCandidate):
        raise TypeError("candidate must be a PerturbationScheduleReviewCandidate")
    payload = candidate.as_dict()
    if payload["executed"] is not False:
        raise ValueError("review candidates must remain unexecuted")
    output = Path(path)
    _write_json_once(output, payload, artifact_name="L0 perturbation review candidate")
    return output
