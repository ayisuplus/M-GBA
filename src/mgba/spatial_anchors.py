"""Build de-identified L3 spatial anchor targets from observation bundles.

This module is deliberately outside the L0--L4 tick loop.  Raw spatial
transcriptomic or imaging formats must first be converted to one of the two
small, explicit observation-bundle schemas accepted here.  The output keeps
only per-sample aggregate metrics under irreversible sample aliases; no spot,
cell, coordinate, image, or public sample identifier survives.
"""

from __future__ import annotations

import heapq
import json
import math
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any, Mapping, Sequence

from .experiment import write_json_once
from .hashing import digest_payload
from .layers import SpatialTissueState
from .scenarios.carm.scenario import CellRole
from .validation import finite, required_text, sha256_text


OBSERVATION_SCHEMA_VERSION = "mgba-spatial-observation-bundle-0.1"
TARGET_SCHEMA_VERSION = "mgba-spatial-anchor-target-0.1"
FIELD_CHANNELS = ("stress", "resource", "signal")
NEIGHBORHOOD_LABELS = ("immune", "other", "tumor")
SAMPLE_ROLES = ("calibration", "external_validation", "holdout")
MODALITIES = ("field", "neighborhood")
FIELD_MEASURES = (
    "cv",
    "gradient_q50",
    "gradient_q95",
    "morans_i",
    "region_variance_fraction",
)
FIELD_METRIC_IDS = tuple(
    sorted(
        f"field.{channel}.{measure}"
        for channel in FIELD_CHANNELS
        for measure in FIELD_MEASURES
    )
)
NEIGHBORHOOD_METRIC_IDS = tuple(
    sorted(
        (
            "neighborhood.adjacency_radius",
            "neighborhood.cross_type_adjacency_enrichment",
            "neighborhood.degree_cv",
            "neighborhood.degree_mean",
            "neighborhood.degree_q95",
            "neighborhood.immune_tumor_distance_q25",
            "neighborhood.immune_tumor_distance_q50",
            "neighborhood.immune_tumor_distance_q75",
            "neighborhood.mixing_score",
        )
    )
)






def _unit(value: Any, *, name: str) -> float:
    number = finite(value, name=name)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")
    return number




def _exact_keys(raw: Mapping[str, Any], expected: set[str], *, name: str) -> None:
    keys = set(raw)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise ValueError(f"{name} keys differ; missing={missing}, extra={extra}")




@dataclass(frozen=True, slots=True)
class SpatialSourceArtifact:
    file_id: str
    sha256: str
    bytes: int
    license: str
    rights_verified: bool

    def __post_init__(self) -> None:
        required_text(self.file_id, name="source file_id")
        sha256_text(self.sha256, name="source sha256")
        if isinstance(self.bytes, bool) or not isinstance(self.bytes, int) or self.bytes < 1:
            raise ValueError("source bytes must be a positive integer")
        required_text(self.license, name="source license")
        if self.rights_verified is not True:
            raise ValueError("every source artifact needs explicit rights verification")

    def public_dict(self) -> dict[str, Any]:
        # file_id is intentionally omitted: only content identity survives.
        return {
            "sha256": self.sha256,
            "bytes": self.bytes,
            "license": self.license,
            "rights_verified": True,
        }


@dataclass(frozen=True, slots=True)
class FieldObservation:
    observation_id: str
    x: float
    y: float
    region: str
    channels: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        required_text(self.observation_id, name="field observation_id")
        _unit(self.x, name="field x")
        _unit(self.y, name="field y")
        required_text(self.region, name="field region")
        if tuple(name for name, _ in self.channels) != FIELD_CHANNELS:
            raise ValueError("field channels must be stress/resource/signal in order")
        for name, value in self.channels:
            _unit(value, name=f"field channel {name}")

    def channel(self, name: str) -> float:
        return dict(self.channels)[name]


@dataclass(frozen=True, slots=True)
class NeighborhoodObservation:
    observation_id: str
    x: float
    y: float
    label: str

    def __post_init__(self) -> None:
        required_text(self.observation_id, name="neighborhood observation_id")
        _unit(self.x, name="neighborhood x")
        _unit(self.y, name="neighborhood y")
        if self.label not in NEIGHBORHOOD_LABELS:
            raise ValueError("neighborhood label must be immune/other/tumor")


@dataclass(frozen=True, slots=True)
class SpatialObservationSample:
    sample_id: str
    field_observations: tuple[FieldObservation, ...] = ()
    neighborhood_observations: tuple[NeighborhoodObservation, ...] = ()

    def __post_init__(self) -> None:
        required_text(self.sample_id, name="sample_id")
        populated = bool(self.field_observations), bool(self.neighborhood_observations)
        if populated not in ((True, False), (False, True)):
            raise ValueError("a sample must contain exactly one observation modality")
        observations: Sequence[FieldObservation | NeighborhoodObservation] = (
            self.field_observations or self.neighborhood_observations
        )
        ids = [item.observation_id for item in observations]
        if len(ids) != len(set(ids)):
            raise ValueError("observation_id values must be unique within a sample")
        coordinates = [(item.x, item.y) for item in observations]
        if len(coordinates) != len(set(coordinates)):
            raise ValueError("observation coordinates must be unique within a sample")


@dataclass(frozen=True, slots=True)
class SpatialObservationBundle:
    dataset_id: str
    modality: str
    source_artifacts: tuple[SpatialSourceArtifact, ...]
    samples: tuple[SpatialObservationSample, ...]

    def __post_init__(self) -> None:
        required_text(self.dataset_id, name="dataset_id")
        if self.modality not in MODALITIES:
            raise ValueError("bundle modality must be field or neighborhood")
        if not self.source_artifacts:
            raise ValueError("bundle needs at least one source artifact")
        if not self.samples:
            raise ValueError("bundle needs at least one sample")
        file_ids = [item.file_id for item in self.source_artifacts]
        if len(file_ids) != len(set(file_ids)):
            raise ValueError("source file_id values must be unique")
        source_digests = [item.sha256 for item in self.source_artifacts]
        if len(source_digests) != len(set(source_digests)):
            raise ValueError("source artifact SHA-256 values must be unique")
        sample_ids = [item.sample_id for item in self.samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("sample_id values must be unique")
        for sample in self.samples:
            if self.modality == "field" and not sample.field_observations:
                raise ValueError("field bundle contains a non-field sample")
            if self.modality == "neighborhood" and not sample.neighborhood_observations:
                raise ValueError("neighborhood bundle contains a non-neighborhood sample")

    def identity_dict(self) -> dict[str, Any]:
        return {
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            "dataset_id": self.dataset_id,
            "modality": self.modality,
            "source_artifacts": [
                {
                    "file_id": item.file_id,
                    **item.public_dict(),
                }
                for item in self.source_artifacts
            ],
            "samples": [
                {
                    "sample_id": sample.sample_id,
                    "observations": [
                        {
                            "observation_id": item.observation_id,
                            "x": item.x,
                            "y": item.y,
                            **(
                                {
                                    "region": item.region,
                                    "channels": dict(item.channels),
                                }
                                if isinstance(item, FieldObservation)
                                else {"label": item.label}
                            ),
                        }
                        for item in (
                            sample.field_observations
                            or sample.neighborhood_observations
                        )
                    ],
                }
                for sample in self.samples
            ],
        }

    @property
    def input_digest(self) -> str:
        return digest_payload(self.identity_dict())


def load_spatial_observation_bundle(path: str | Path) -> SpatialObservationBundle:
    try:
        raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("observation bundle root must be an object")
        _exact_keys(
            raw,
            {"schema_version", "dataset_id", "modality", "source_artifacts", "samples"},
            name="observation bundle",
        )
        if raw["schema_version"] != OBSERVATION_SCHEMA_VERSION:
            raise ValueError("unsupported observation bundle schema")
        modality = required_text(raw["modality"], name="bundle modality")
        if not isinstance(raw["source_artifacts"], list):
            raise ValueError("source_artifacts must be a list")
        source_artifacts = []
        for index, item in enumerate(raw["source_artifacts"]):
            if not isinstance(item, dict):
                raise ValueError(f"source_artifacts[{index}] must be an object")
            _exact_keys(
                item,
                {"file_id", "sha256", "bytes", "license", "rights_verified"},
                name=f"source_artifacts[{index}]",
            )
            source_artifacts.append(SpatialSourceArtifact(**item))
        if not isinstance(raw["samples"], list):
            raise ValueError("samples must be a list")
        samples = []
        for sample_index, item in enumerate(raw["samples"]):
            if not isinstance(item, dict):
                raise ValueError(f"samples[{sample_index}] must be an object")
            _exact_keys(item, {"sample_id", "observations"}, name=f"samples[{sample_index}]")
            if not isinstance(item["observations"], list):
                raise ValueError("sample observations must be a list")
            field_items = []
            neighborhood_items = []
            for observation_index, observation in enumerate(item["observations"]):
                if not isinstance(observation, dict):
                    raise ValueError("observation must be an object")
                label = f"samples[{sample_index}].observations[{observation_index}]"
                if modality == "field":
                    _exact_keys(
                        observation,
                        {"observation_id", "x", "y", "region", "channels"},
                        name=label,
                    )
                    channels = observation["channels"]
                    if not isinstance(channels, dict):
                        raise ValueError("field channels must be an object")
                    _exact_keys(channels, set(FIELD_CHANNELS), name=f"{label}.channels")
                    field_items.append(
                        FieldObservation(
                            observation_id=observation["observation_id"],
                            x=observation["x"],
                            y=observation["y"],
                            region=observation["region"],
                            channels=tuple(
                                (name, channels[name]) for name in FIELD_CHANNELS
                            ),
                        )
                    )
                elif modality == "neighborhood":
                    _exact_keys(
                        observation,
                        {"observation_id", "x", "y", "label"},
                        name=label,
                    )
                    neighborhood_items.append(NeighborhoodObservation(**observation))
                else:
                    raise ValueError("bundle modality must be field or neighborhood")
            samples.append(
                SpatialObservationSample(
                    sample_id=item["sample_id"],
                    field_observations=tuple(
                        sorted(field_items, key=lambda value: value.observation_id)
                    ),
                    neighborhood_observations=tuple(
                        sorted(
                            neighborhood_items,
                            key=lambda value: value.observation_id,
                        )
                    ),
                )
            )
        return SpatialObservationBundle(
            dataset_id=raw["dataset_id"],
            modality=modality,
            source_artifacts=tuple(
                sorted(source_artifacts, key=lambda value: value.file_id)
            ),
            samples=tuple(sorted(samples, key=lambda value: value.sample_id)),
        )
    except (OSError, json.JSONDecodeError, TypeError, KeyError) as error:
        raise ValueError(f"invalid spatial observation bundle: {error}") from error


@dataclass(frozen=True, slots=True)
class SpatialAnchorProtocol:
    model_version: str
    field_dataset_id: str
    neighborhood_dataset_id: str
    expected_field_samples: int
    field_calibration_count: int
    field_knn_k: int
    neighborhood_radius_factor: float
    model_tumor_region_quantile: float
    split_salt: str

    def __post_init__(self) -> None:
        for name in ("model_version", "field_dataset_id", "neighborhood_dataset_id", "split_salt"):
            required_text(getattr(self, name), name=name)
        if self.field_dataset_id == self.neighborhood_dataset_id:
            raise ValueError("field and neighborhood dataset ids must differ")
        for name in ("expected_field_samples", "field_calibration_count", "field_knn_k"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.expected_field_samples <= self.field_calibration_count:
            raise ValueError("field protocol needs at least one holdout sample")
        if self.field_knn_k < 2:
            raise ValueError("field_knn_k must be at least two")
        radius_factor = finite(
            self.neighborhood_radius_factor,
            name="neighborhood_radius_factor",
        )
        if not 1.0 <= radius_factor <= 5.0:
            raise ValueError("neighborhood_radius_factor must be in [1, 5]")
        region_quantile = finite(
            self.model_tumor_region_quantile,
            name="model_tumor_region_quantile",
        )
        if not 0.1 <= region_quantile <= 0.9:
            raise ValueError("model_tumor_region_quantile must be in [0.1, 0.9]")

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "field_dataset_id": self.field_dataset_id,
            "neighborhood_dataset_id": self.neighborhood_dataset_id,
            "expected_field_samples": self.expected_field_samples,
            "field_calibration_count": self.field_calibration_count,
            "field_knn_k": self.field_knn_k,
            "neighborhood_radius_factor": self.neighborhood_radius_factor,
            "model_tumor_region_quantile": self.model_tumor_region_quantile,
            "split_salt": self.split_salt,
        }


def load_spatial_anchor_protocol(path: str | Path) -> SpatialAnchorProtocol:
    try:
        raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("spatial anchor protocol root must be an object")
        _exact_keys(
            raw,
            {
                "model_version",
                "field_dataset_id",
                "neighborhood_dataset_id",
                "expected_field_samples",
                "field_calibration_count",
                "field_knn_k",
                "neighborhood_radius_factor",
                "model_tumor_region_quantile",
                "split_salt",
            },
            name="spatial anchor protocol",
        )
        return SpatialAnchorProtocol(**raw)
    except (OSError, json.JSONDecodeError, TypeError, KeyError) as error:
        raise ValueError(f"invalid spatial anchor protocol: {error}") from error


@dataclass(frozen=True, slots=True)
class SampleMetricRecord:
    dataset_id: str
    sample_alias: str
    modality: str
    role: str
    observation_count: int
    metrics: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        required_text(self.dataset_id, name="metric dataset_id")
        if not self.sample_alias.startswith("sample-") or len(self.sample_alias) != 19:
            raise ValueError("sample alias must be sample- plus twelve hex characters")
        if self.modality not in MODALITIES or self.role not in SAMPLE_ROLES:
            raise ValueError("invalid sample modality or role")
        if isinstance(self.observation_count, bool) or self.observation_count < 1:
            raise ValueError("observation_count must be positive")
        names = [name for name, _ in self.metrics]
        if names != sorted(names) or len(names) != len(set(names)):
            raise ValueError("sample metrics must have unique sorted names")
        expected_metrics = (
            FIELD_METRIC_IDS if self.modality == "field" else NEIGHBORHOOD_METRIC_IDS
        )
        if tuple(names) != expected_metrics:
            raise ValueError("sample metrics do not match the frozen modality contract")
        for name, value in self.metrics:
            required_text(name, name="metric name")
            finite(value, name=f"metric {name}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "sample_alias": self.sample_alias,
            "modality": self.modality,
            "role": self.role,
            "observation_count": self.observation_count,
            "metrics": dict(self.metrics),
        }


@dataclass(frozen=True, slots=True)
class MetricDistribution:
    role: str
    metric_id: str
    sample_count: int
    mean: float
    standard_deviation: float
    minimum: float
    q25: float
    median: float
    q75: float
    maximum: float

    def __post_init__(self) -> None:
        if self.role not in SAMPLE_ROLES:
            raise ValueError("invalid distribution role")
        required_text(self.metric_id, name="distribution metric_id")
        if isinstance(self.sample_count, bool) or self.sample_count < 1:
            raise ValueError("distribution sample_count must be positive")
        values = (
            self.mean,
            self.standard_deviation,
            self.minimum,
            self.q25,
            self.median,
            self.q75,
            self.maximum,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("distribution values must be finite")
        if self.standard_deviation < 0.0:
            raise ValueError("distribution standard deviation must be non-negative")
        if not self.minimum <= self.q25 <= self.median <= self.q75 <= self.maximum:
            raise ValueError(
                f"distribution quantiles are out of order for {self.role}/{self.metric_id}: "
                f"{self.minimum}, {self.q25}, {self.median}, {self.q75}, {self.maximum}"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "metric_id": self.metric_id,
            "sample_count": self.sample_count,
            "mean": self.mean,
            "standard_deviation": self.standard_deviation,
            "minimum": self.minimum,
            "q25": self.q25,
            "median": self.median,
            "q75": self.q75,
            "maximum": self.maximum,
        }


@dataclass(frozen=True, slots=True)
class SpatialAnchorProfile:
    protocol: SpatialAnchorProtocol
    target_id: str
    sources: tuple[dict[str, Any], ...]
    samples: tuple[SampleMetricRecord, ...]
    distributions: tuple[MetricDistribution, ...]

    def __post_init__(self) -> None:
        if not self.target_id.startswith("spatial-anchor-") or len(self.target_id) != 31:
            raise ValueError("invalid spatial target id")
        if len(self.sources) != 2 or not self.samples or not self.distributions:
            raise ValueError("spatial target needs two sources, samples, and distributions")
        aliases = [item.sample_alias for item in self.samples]
        if len(aliases) != len(set(aliases)):
            raise ValueError("sample aliases must be unique")
        if any(
            item.modality == "neighborhood" and item.role != "external_validation"
            for item in self.samples
        ):
            raise ValueError("neighborhood observations are external validation only")

    def _core_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TARGET_SCHEMA_VERSION,
            "protocol": self.protocol.as_dict(),
            "sources": list(self.sources),
            "samples": [item.as_dict() for item in self.samples],
            "distributions": [item.as_dict() for item in self.distributions],
            "scientific_boundary": (
                "de-identified aggregate L3 anchor targets; not raw spatial data, "
                "cell identity, clinical truth, treatment outcome, or a runtime input"
            ),
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self._core_dict(), "target_id": self.target_id}

    def verify_identity(self) -> None:
        expected = f"spatial-anchor-{digest_payload(self._core_dict())[:16]}"
        if self.target_id != expected:
            raise ValueError("spatial target identity mismatch")


@dataclass(slots=True)
class _KdNode:
    point_index: int
    axis: int
    left: _KdNode | None = None
    right: _KdNode | None = None


def _build_kd_tree(
    points: Sequence[tuple[float, float]], indices: Sequence[int], depth: int = 0
) -> _KdNode | None:
    if not indices:
        return None
    axis = depth % 2
    ordered = sorted(indices, key=lambda index: (points[index][axis], points[index][1 - axis], index))
    middle = len(ordered) // 2
    return _KdNode(
        point_index=ordered[middle],
        axis=axis,
        left=_build_kd_tree(points, ordered[:middle], depth + 1),
        right=_build_kd_tree(points, ordered[middle + 1 :], depth + 1),
    )


def _k_nearest(
    points: Sequence[tuple[float, float]],
    tree: _KdNode | None,
    target: tuple[float, float],
    count: int,
    *,
    excluded_index: int | None = None,
) -> tuple[tuple[float, int], ...]:
    heap: list[tuple[float, int, int]] = []

    def visit(node: _KdNode | None) -> None:
        if node is None:
            return
        index = node.point_index
        point = points[index]
        delta_x = point[0] - target[0]
        delta_y = point[1] - target[1]
        distance_squared = delta_x * delta_x + delta_y * delta_y
        if index != excluded_index:
            candidate = (-distance_squared, -index, index)
            if len(heap) < count:
                heapq.heappush(heap, candidate)
            elif candidate > heap[0]:
                heapq.heapreplace(heap, candidate)
        axis_delta = target[node.axis] - point[node.axis]
        near, far = (node.left, node.right) if axis_delta < 0.0 else (node.right, node.left)
        visit(near)
        worst = math.inf if len(heap) < count else -heap[0][0]
        if axis_delta * axis_delta <= worst:
            visit(far)

    visit(tree)
    result = tuple(
        sorted(
            ((math.sqrt(-negative_distance), index) for negative_distance, _, index in heap),
            key=lambda item: (item[0], item[1]),
        )
    )
    if len(result) != count:
        raise ValueError("not enough spatial observations for the requested neighbors")
    return result


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("quantile requires at least one value")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("quantile probability must be in [0, 1]")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _coefficient_of_variation(values: Sequence[float]) -> float:
    mean = fmean(values)
    if abs(mean) <= 1e-15:
        return 0.0
    return pstdev(values) / abs(mean)


def _field_metrics(
    observations: Sequence[FieldObservation], *, knn_k: int
) -> tuple[tuple[str, float], ...]:
    if len(observations) <= knn_k:
        raise ValueError("field sample has too few observations for the frozen kNN")
    points = tuple((item.x, item.y) for item in observations)
    tree = _build_kd_tree(points, tuple(range(len(points))))
    directed_edges = tuple(
        (index, neighbor)
        for index, point in enumerate(points)
        for _, neighbor in _k_nearest(
            points, tree, point, knn_k, excluded_index=index
        )
    )
    undirected_edges = tuple(sorted({tuple(sorted(edge)) for edge in directed_edges}))
    metrics: dict[str, float] = {}
    for channel in FIELD_CHANNELS:
        values = tuple(item.channel(channel) for item in observations)
        mean = fmean(values)
        deviations = tuple(value - mean for value in values)
        denominator = sum(value * value for value in deviations)
        if denominator <= 1e-30:
            morans_i = 0.0
        else:
            numerator = sum(
                deviations[left] * deviations[right]
                for left, right in directed_edges
            )
            morans_i = len(values) / len(directed_edges) * numerator / denominator
        gradients = []
        for left, right in undirected_edges:
            distance = math.dist(points[left], points[right])
            if distance <= 0.0:
                raise ValueError("field observations contain duplicate coordinates")
            gradients.append(abs(values[left] - values[right]) / distance)
        regions: dict[str, list[float]] = {}
        for observation, value in zip(observations, values):
            regions.setdefault(observation.region, []).append(value)
        if len(regions) < 2:
            raise ValueError("field sample needs at least two pathology regions")
        total_sum_squares = sum((value - mean) ** 2 for value in values)
        between_sum_squares = sum(
            len(group) * (fmean(group) - mean) ** 2 for group in regions.values()
        )
        region_fraction = (
            between_sum_squares / total_sum_squares
            if total_sum_squares > 1e-30
            else 0.0
        )
        prefix = f"field.{channel}"
        metrics[f"{prefix}.cv"] = _coefficient_of_variation(values)
        metrics[f"{prefix}.gradient_q50"] = _quantile(gradients, 0.50)
        metrics[f"{prefix}.gradient_q95"] = _quantile(gradients, 0.95)
        metrics[f"{prefix}.morans_i"] = morans_i
        metrics[f"{prefix}.region_variance_fraction"] = region_fraction
    return tuple(sorted(metrics.items()))


def _radius_edges(
    points: Sequence[tuple[float, float]], radius: float
) -> tuple[tuple[int, int], ...]:
    if not math.isfinite(radius) or radius <= 0.0:
        raise ValueError("neighborhood radius must be positive")
    buckets: dict[tuple[int, int], list[int]] = {}
    for index, (x, y) in enumerate(points):
        key = (math.floor(x / radius), math.floor(y / radius))
        buckets.setdefault(key, []).append(index)
    edges = []
    for index, (x, y) in enumerate(points):
        column, row = math.floor(x / radius), math.floor(y / radius)
        for delta_column in (-1, 0, 1):
            for delta_row in (-1, 0, 1):
                for other in buckets.get((column + delta_column, row + delta_row), ()):
                    if other <= index:
                        continue
                    if math.dist(points[index], points[other]) <= radius:
                        edges.append((index, other))
    return tuple(sorted(edges))


def _neighborhood_metrics(
    observations: Sequence[NeighborhoodObservation], *, radius_factor: float
) -> tuple[tuple[str, float], ...]:
    if len(observations) < 3:
        raise ValueError("neighborhood sample needs at least three cells")
    points = tuple((item.x, item.y) for item in observations)
    labels = tuple(item.label for item in observations)
    immune_indices = tuple(index for index, label in enumerate(labels) if label == "immune")
    tumor_indices = tuple(index for index, label in enumerate(labels) if label == "tumor")
    if not immune_indices or not tumor_indices:
        raise ValueError("neighborhood sample needs both immune and tumor cells")
    tree = _build_kd_tree(points, tuple(range(len(points))))
    nearest_all = tuple(
        _k_nearest(points, tree, point, 1, excluded_index=index)[0][0]
        for index, point in enumerate(points)
    )
    radius = min(math.sqrt(2.0), radius_factor * _quantile(nearest_all, 0.5))
    edges = _radius_edges(points, radius)
    if not edges:
        raise ValueError("derived neighborhood radius produced no edges")

    tumor_points = tuple(points[index] for index in tumor_indices)
    tumor_tree = _build_kd_tree(tumor_points, tuple(range(len(tumor_points))))
    diagonal = math.sqrt(2.0)
    immune_tumor_distances = tuple(
        _k_nearest(tumor_points, tumor_tree, points[index], 1)[0][0] / diagonal
        for index in immune_indices
    )
    cross_edges = tuple(
        (left, right)
        for left, right in edges
        if {labels[left], labels[right]} == {"immune", "tumor"}
    )
    expected_probability = (
        2.0 * len(immune_indices) * len(tumor_indices)
        / (len(points) * (len(points) - 1))
    )
    observed_probability = len(cross_edges) / len(edges)
    enrichment = observed_probability / expected_probability
    mixed_immune = {
        left if labels[left] == "immune" else right for left, right in cross_edges
    }
    degrees = [0] * len(points)
    for left, right in edges:
        degrees[left] += 1
        degrees[right] += 1
    metrics = {
        "neighborhood.adjacency_radius": radius / diagonal,
        "neighborhood.cross_type_adjacency_enrichment": enrichment,
        "neighborhood.degree_cv": _coefficient_of_variation(degrees),
        "neighborhood.degree_mean": fmean(degrees),
        "neighborhood.degree_q95": _quantile(degrees, 0.95),
        "neighborhood.immune_tumor_distance_q25": _quantile(
            immune_tumor_distances, 0.25
        ),
        "neighborhood.immune_tumor_distance_q50": _quantile(
            immune_tumor_distances, 0.50
        ),
        "neighborhood.immune_tumor_distance_q75": _quantile(
            immune_tumor_distances, 0.75
        ),
        "neighborhood.mixing_score": len(mixed_immune) / len(immune_indices),
    }
    return tuple(sorted(metrics.items()))


def _sample_alias(protocol: SpatialAnchorProtocol, dataset_id: str, sample_id: str) -> str:
    digest = sha256(
        f"{protocol.split_salt}|alias|{dataset_id}|{sample_id}".encode("utf-8")
    ).hexdigest()
    return f"sample-{digest[:12]}"


def _field_calibration_ids(
    protocol: SpatialAnchorProtocol, samples: Sequence[SpatialObservationSample]
) -> set[str]:
    ranked = sorted(
        samples,
        key=lambda sample: (
            sha256(
                f"{protocol.split_salt}|split|{protocol.field_dataset_id}|{sample.sample_id}".encode(
                    "utf-8"
                )
            ).hexdigest(),
            sample.sample_id,
        ),
    )
    return {sample.sample_id for sample in ranked[: protocol.field_calibration_count]}


def _distribution(
    role: str, metric_id: str, values: Sequence[float]
) -> MetricDistribution:
    return MetricDistribution(
        role=role,
        metric_id=metric_id,
        sample_count=len(values),
        mean=fmean(values),
        standard_deviation=pstdev(values),
        minimum=min(values),
        q25=_quantile(values, 0.25),
        median=_quantile(values, 0.50),
        q75=_quantile(values, 0.75),
        maximum=max(values),
    )


def build_spatial_anchor_profile(
    protocol: SpatialAnchorProtocol,
    *,
    field_bundle: SpatialObservationBundle,
    neighborhood_bundle: SpatialObservationBundle,
) -> SpatialAnchorProfile:
    if field_bundle.dataset_id != protocol.field_dataset_id or field_bundle.modality != "field":
        raise ValueError("field bundle does not match the frozen protocol")
    if (
        neighborhood_bundle.dataset_id != protocol.neighborhood_dataset_id
        or neighborhood_bundle.modality != "neighborhood"
    ):
        raise ValueError("neighborhood bundle does not match the frozen protocol")
    if len(field_bundle.samples) != protocol.expected_field_samples:
        raise ValueError("field bundle sample count differs from the frozen protocol")

    calibration_ids = _field_calibration_ids(protocol, field_bundle.samples)
    sample_records = []
    for sample in field_bundle.samples:
        metrics = _field_metrics(
            sample.field_observations, knn_k=protocol.field_knn_k
        )
        sample_records.append(
            SampleMetricRecord(
                dataset_id=field_bundle.dataset_id,
                sample_alias=_sample_alias(protocol, field_bundle.dataset_id, sample.sample_id),
                modality="field",
                role="calibration" if sample.sample_id in calibration_ids else "holdout",
                observation_count=len(sample.field_observations),
                metrics=metrics,
            )
        )
    for sample in neighborhood_bundle.samples:
        metrics = _neighborhood_metrics(
            sample.neighborhood_observations,
            radius_factor=protocol.neighborhood_radius_factor,
        )
        sample_records.append(
            SampleMetricRecord(
                dataset_id=neighborhood_bundle.dataset_id,
                sample_alias=_sample_alias(
                    protocol, neighborhood_bundle.dataset_id, sample.sample_id
                ),
                modality="neighborhood",
                role="external_validation",
                observation_count=len(sample.neighborhood_observations),
                metrics=metrics,
            )
        )
    sample_records = sorted(
        sample_records,
        key=lambda item: (item.role, item.dataset_id, item.sample_alias),
    )
    grouped: dict[tuple[str, str], list[float]] = {}
    for sample in sample_records:
        for metric_id, value in sample.metrics:
            grouped.setdefault((sample.role, metric_id), []).append(value)
    distributions = tuple(
        _distribution(role, metric_id, values)
        for (role, metric_id), values in sorted(grouped.items())
    )
    sources = tuple(
        {
            "dataset_id": bundle.dataset_id,
            "modality": bundle.modality,
            "input_digest": bundle.input_digest,
            "sample_count": len(bundle.samples),
            "artifacts": [item.public_dict() for item in bundle.source_artifacts],
        }
        for bundle in (field_bundle, neighborhood_bundle)
    )
    provisional = SpatialAnchorProfile(
        protocol=protocol,
        target_id="spatial-anchor-" + "0" * 16,
        sources=sources,
        samples=tuple(sample_records),
        distributions=distributions,
    )
    target_id = f"spatial-anchor-{digest_payload(provisional._core_dict())[:16]}"
    profile = SpatialAnchorProfile(
        protocol=protocol,
        target_id=target_id,
        sources=sources,
        samples=tuple(sample_records),
        distributions=distributions,
    )
    profile.verify_identity()
    return profile


@dataclass(frozen=True, slots=True)
class SpatialModelProjection:
    logical_time: int
    model_version: str
    source_digest: str
    metrics: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.logical_time, bool)
            or not isinstance(self.logical_time, int)
            or self.logical_time < 0
        ):
            raise ValueError("projection logical_time must be non-negative")
        required_text(self.model_version, name="projection model_version")
        required_text(self.source_digest, name="projection source_digest")
        expected = tuple(sorted((*FIELD_METRIC_IDS, *NEIGHBORHOOD_METRIC_IDS)))
        if tuple(name for name, _ in self.metrics) != expected:
            raise ValueError("model projection must cover every frozen metric")
        for name, value in self.metrics:
            finite(value, name=f"projected metric {name}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "logical_time": self.logical_time,
            "model_version": self.model_version,
            "source_digest": self.source_digest,
            "metrics": dict(self.metrics),
            "projection_boundary": (
                "same-metric projection of one dimensionless SpatialTissueState; "
                "not a reconstruction of an external tissue sample"
            ),
        }


def project_spatial_tissue_state(
    state: SpatialTissueState,
    *,
    roles: tuple[tuple[str, CellRole], ...],
    protocol: SpatialAnchorProtocol,
) -> SpatialModelProjection:
    """Project one formal spatial L3 state into the target metric space."""

    if not isinstance(state, SpatialTissueState):
        raise TypeError("spatial target projection requires SpatialTissueState")
    role_map = dict(roles)
    if len(role_map) != len(roles) or set(role_map) != {
        item.cell_id for item in state.coordinates
    }:
        raise ValueError("projection roles must align exactly with spatial coordinates")
    if any(not isinstance(role, CellRole) for role in role_map.values()):
        raise TypeError("projection roles must be CellRole values")

    coordinate_map = {
        item.cell_id: (item.x, item.y) for item in state.coordinates
    }
    tumor_points = tuple(
        coordinate_map[cell_id]
        for cell_id, role in sorted(role_map.items())
        if role is CellRole.TUMOR
    )
    if not tumor_points:
        raise ValueError("CAR-M projection needs at least one tumor coordinate")

    field_centers = tuple(
        (
            (item.column + 0.5) / state.field_columns,
            (item.row + 0.5) / state.field_rows,
        )
        for item in state.field_cells
    )
    tumor_distances = tuple(
        min(math.dist(center, tumor) for tumor in tumor_points)
        for center in field_centers
    )
    region_threshold = _quantile(
        tumor_distances, protocol.model_tumor_region_quantile
    )
    field_observations = tuple(
        FieldObservation(
            observation_id=f"model-field-{item.row}-{item.column}",
            x=center[0],
            y=center[1],
            region=(
                "tumor_proximal"
                if distance <= region_threshold
                else "tumor_distal"
            ),
            channels=(
                ("stress", item.stress),
                ("resource", item.resource_level),
                ("signal", item.signal),
            ),
        )
        for item, center, distance in zip(
            state.field_cells, field_centers, tumor_distances
        )
    )
    if len({item.region for item in field_observations}) != 2:
        raise ValueError("model field projection did not form two tumor-distance regions")

    immune_roles = {
        CellRole.ENGINEERED_MACROPHAGE,
        CellRole.WILD_TYPE_MACROPHAGE,
        CellRole.CD8_T_CELL,
    }
    neighborhood_observations = tuple(
        NeighborhoodObservation(
            observation_id=f"model-cell-{cell_id}",
            x=coordinate_map[cell_id][0],
            y=coordinate_map[cell_id][1],
            label=("tumor" if role is CellRole.TUMOR else "immune"),
        )
        for cell_id, role in sorted(role_map.items())
        if role in immune_roles or role is CellRole.TUMOR
    )
    field_metrics = _field_metrics(
        field_observations, knn_k=protocol.field_knn_k
    )
    neighborhood_metrics = _neighborhood_metrics(
        neighborhood_observations,
        radius_factor=protocol.neighborhood_radius_factor,
    )
    return SpatialModelProjection(
        logical_time=state.metadata.logical_time,
        model_version=state.metadata.model_version,
        source_digest=state.metadata.source_digest,
        metrics=tuple(sorted((*field_metrics, *neighborhood_metrics))),
    )


@dataclass(frozen=True, slots=True)
class TargetMetricComparison:
    role: str
    metric_id: str
    model_value: float
    target_median: float
    target_minimum: float
    target_maximum: float
    normalization_scale: float
    normalized_absolute_error: float
    in_observed_range: bool

    def __post_init__(self) -> None:
        if self.role not in SAMPLE_ROLES:
            raise ValueError("comparison role is invalid")
        required_text(self.metric_id, name="comparison metric_id")
        values = (
            self.model_value,
            self.target_median,
            self.target_minimum,
            self.target_maximum,
            self.normalization_scale,
            self.normalized_absolute_error,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("comparison values must be finite")
        if self.normalization_scale <= 0.0 or self.normalized_absolute_error < 0.0:
            raise ValueError("comparison scale/error must be positive/non-negative")
        if self.target_minimum > self.target_median or self.target_median > self.target_maximum:
            raise ValueError("comparison target bounds are inconsistent")
        if not isinstance(self.in_observed_range, bool):
            raise TypeError("comparison range flag must be boolean")

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "metric_id": self.metric_id,
            "model_value": self.model_value,
            "target_median": self.target_median,
            "target_minimum": self.target_minimum,
            "target_maximum": self.target_maximum,
            "normalization_scale": self.normalization_scale,
            "normalized_absolute_error": self.normalized_absolute_error,
            "in_observed_range": self.in_observed_range,
        }


@dataclass(frozen=True, slots=True)
class TargetRoleScore:
    role: str
    metric_count: int
    mean_normalized_absolute_error: float
    maximum_normalized_absolute_error: float
    observed_range_fraction: float

    def __post_init__(self) -> None:
        if self.role not in SAMPLE_ROLES:
            raise ValueError("role score role is invalid")
        if isinstance(self.metric_count, bool) or self.metric_count < 1:
            raise ValueError("role score metric_count must be positive")
        for name in (
            "mean_normalized_absolute_error",
            "maximum_normalized_absolute_error",
            "observed_range_fraction",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"role score {name} must be finite and non-negative")
        if self.observed_range_fraction > 1.0:
            raise ValueError("observed_range_fraction must be in [0, 1]")

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "metric_count": self.metric_count,
            "mean_normalized_absolute_error": self.mean_normalized_absolute_error,
            "maximum_normalized_absolute_error": self.maximum_normalized_absolute_error,
            "observed_range_fraction": self.observed_range_fraction,
        }


@dataclass(frozen=True, slots=True)
class SpatialTargetScore:
    score_id: str
    target_id: str
    projection: SpatialModelProjection
    comparisons: tuple[TargetMetricComparison, ...]
    role_scores: tuple[TargetRoleScore, ...]

    def __post_init__(self) -> None:
        if not self.score_id.startswith("spatial-score-") or len(self.score_id) != 30:
            raise ValueError("invalid spatial score id")
        if not self.target_id.startswith("spatial-anchor-"):
            raise ValueError("invalid target id in score")
        if not self.comparisons or tuple(item.role for item in self.role_scores) != (
            "calibration",
            "holdout",
            "external_validation",
        ):
            raise ValueError("spatial score role coverage is incomplete")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "mgba-spatial-target-score-0.1",
            "score_id": self.score_id,
            "target_id": self.target_id,
            "projection": self.projection.as_dict(),
            "comparisons": [item.as_dict() for item in self.comparisons],
            "role_scores": [item.as_dict() for item in self.role_scores],
            "interpretation_boundary": (
                "descriptive distance from observed aggregate distributions; "
                "not a likelihood, p-value, biological validation, or efficacy score"
            ),
        }


def score_spatial_projection(
    projection: SpatialModelProjection,
    target: Mapping[str, Any],
) -> SpatialTargetScore:
    """Compare a model projection with an already verified target payload."""

    if target.get("schema_version") != TARGET_SCHEMA_VERSION:
        raise ValueError("score requires a verified spatial anchor target")
    target_id = required_text(target.get("target_id"), name="score target_id")
    target_core = dict(target)
    del target_core["target_id"]
    expected_target_id = f"spatial-anchor-{digest_payload(target_core)[:16]}"
    if target_id != expected_target_id:
        raise ValueError("score target digest mismatch")
    raw_distributions = target.get("distributions")
    if not isinstance(raw_distributions, list):
        raise ValueError("score target distributions must be a list")
    distributions = tuple(MetricDistribution(**item) for item in raw_distributions)
    distribution_map = {
        (item.role, item.metric_id): item for item in distributions
    }
    required = {
        *(("calibration", metric_id) for metric_id in FIELD_METRIC_IDS),
        *(("holdout", metric_id) for metric_id in FIELD_METRIC_IDS),
        *(("external_validation", metric_id) for metric_id in NEIGHBORHOOD_METRIC_IDS),
    }
    if set(distribution_map) != required:
        raise ValueError("target distributions do not cover the frozen score space")
    model_metrics = dict(projection.metrics)
    comparisons = []
    for role, metric_id in sorted(required):
        distribution = distribution_map[(role, metric_id)]
        model_value = model_metrics[metric_id]
        scale = max(
            distribution.q75 - distribution.q25,
            distribution.standard_deviation,
            0.05 * max(abs(distribution.median), 1.0),
            1e-9,
        )
        error = abs(model_value - distribution.median) / scale
        comparisons.append(
            TargetMetricComparison(
                role=role,
                metric_id=metric_id,
                model_value=model_value,
                target_median=distribution.median,
                target_minimum=distribution.minimum,
                target_maximum=distribution.maximum,
                normalization_scale=scale,
                normalized_absolute_error=error,
                in_observed_range=(
                    distribution.minimum <= model_value <= distribution.maximum
                ),
            )
        )
    role_scores = []
    for role in ("calibration", "holdout", "external_validation"):
        group = [item for item in comparisons if item.role == role]
        role_scores.append(
            TargetRoleScore(
                role=role,
                metric_count=len(group),
                mean_normalized_absolute_error=fmean(
                    item.normalized_absolute_error for item in group
                ),
                maximum_normalized_absolute_error=max(
                    item.normalized_absolute_error for item in group
                ),
                observed_range_fraction=fmean(
                    float(item.in_observed_range) for item in group
                ),
            )
        )
    identity = {
        "target_id": target_id,
        "projection": projection.as_dict(),
        "comparisons": [item.as_dict() for item in comparisons],
        "role_scores": [item.as_dict() for item in role_scores],
    }
    return SpatialTargetScore(
        score_id=f"spatial-score-{digest_payload(identity)[:16]}",
        target_id=target_id,
        projection=projection,
        comparisons=tuple(comparisons),
        role_scores=tuple(role_scores),
    )




def save_spatial_anchor_profile(path: str | Path, profile: SpatialAnchorProfile) -> Path:
    output = Path(path)
    if "raw" in {part.lower() for part in output.parts}:
        raise ValueError("aggregate spatial targets must not be written under a raw directory")
    profile.verify_identity()
    write_json_once(output, profile.as_dict(), artifact="spatial anchor target")
    return output


def verify_spatial_anchor_target(path: str | Path) -> dict[str, Any]:
    try:
        raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid spatial anchor target: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("spatial anchor target root must be an object")
    _exact_keys(
        raw,
        {
            "schema_version",
            "protocol",
            "sources",
            "samples",
            "distributions",
            "scientific_boundary",
            "target_id",
        },
        name="spatial anchor target",
    )
    if raw["schema_version"] != TARGET_SCHEMA_VERSION:
        raise ValueError("unsupported spatial anchor target schema")
    protocol_raw = raw["protocol"]
    if not isinstance(protocol_raw, dict):
        raise ValueError("spatial target protocol must be an object")
    _exact_keys(
        protocol_raw,
        {
            "model_version",
            "field_dataset_id",
            "neighborhood_dataset_id",
            "expected_field_samples",
            "field_calibration_count",
            "field_knn_k",
            "neighborhood_radius_factor",
            "model_tumor_region_quantile",
            "split_salt",
        },
        name="target protocol",
    )
    protocol = SpatialAnchorProtocol(**protocol_raw)
    target_id = required_text(raw["target_id"], name="target_id")
    core = dict(raw)
    del core["target_id"]
    expected = f"spatial-anchor-{digest_payload(core)[:16]}"
    if target_id != expected:
        raise ValueError("spatial anchor target digest mismatch")
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True)
    forbidden = ('"sample_id"', '"observation_id"', '"coordinates"', '"cells"', '"spots"')
    if any(token in encoded for token in forbidden):
        raise ValueError("spatial target contains forbidden raw identifiers or observations")

    sources_raw = raw["sources"]
    if not isinstance(sources_raw, list) or len(sources_raw) != 2:
        raise ValueError("spatial target must contain exactly two sources")
    expected_dataset_by_modality = {
        "field": protocol.field_dataset_id,
        "neighborhood": protocol.neighborhood_dataset_id,
    }
    seen_modalities = set()
    for source_index, source in enumerate(sources_raw):
        if not isinstance(source, dict):
            raise ValueError(f"target source {source_index} must be an object")
        _exact_keys(
            source,
            {"dataset_id", "modality", "input_digest", "sample_count", "artifacts"},
            name=f"target source {source_index}",
        )
        modality = source["modality"]
        if modality not in MODALITIES or modality in seen_modalities:
            raise ValueError("target source modalities must be unique field/neighborhood")
        seen_modalities.add(modality)
        if source["dataset_id"] != expected_dataset_by_modality[modality]:
            raise ValueError("target source dataset differs from the frozen protocol")
        sha256_text(source["input_digest"], name="target source input_digest")
        if (
            isinstance(source["sample_count"], bool)
            or not isinstance(source["sample_count"], int)
            or source["sample_count"] < 1
        ):
            raise ValueError("target source sample_count must be positive")
        if not isinstance(source["artifacts"], list) or not source["artifacts"]:
            raise ValueError("target source artifacts must be a non-empty list")
        artifact_digests = []
        for artifact_index, artifact in enumerate(source["artifacts"]):
            if not isinstance(artifact, dict):
                raise ValueError("target source artifact must be an object")
            _exact_keys(
                artifact,
                {"sha256", "bytes", "license", "rights_verified"},
                name=f"target source {source_index} artifact {artifact_index}",
            )
            SpatialSourceArtifact(
                file_id=f"verified-{source_index}-{artifact_index}",
                **artifact,
            )
            artifact_digests.append(artifact["sha256"])
        if len(artifact_digests) != len(set(artifact_digests)):
            raise ValueError("target source artifact digests must be unique")

    samples = raw["samples"]
    if not isinstance(samples, list) or not samples:
        raise ValueError("spatial target samples must be a non-empty list")
    sample_records = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ValueError(f"target sample {index} must be an object")
        _exact_keys(
            sample,
            {"dataset_id", "sample_alias", "modality", "role", "observation_count", "metrics"},
            name=f"target sample {index}",
        )
        if not isinstance(sample["metrics"], dict) or not sample["metrics"]:
            raise ValueError("target sample metrics must be a non-empty object")
        for name, value in sample["metrics"].items():
            required_text(name, name="target metric name")
            finite(value, name=f"target metric {name}")
        sample_records.append(
            SampleMetricRecord(
                dataset_id=sample["dataset_id"],
                sample_alias=sample["sample_alias"],
                modality=sample["modality"],
                role=sample["role"],
                observation_count=sample["observation_count"],
                metrics=tuple(sorted(sample["metrics"].items())),
            )
        )

    field_records = [item for item in sample_records if item.modality == "field"]
    neighborhood_records = [
        item for item in sample_records if item.modality == "neighborhood"
    ]
    if len(field_records) != protocol.expected_field_samples:
        raise ValueError("target field sample count differs from the frozen protocol")
    if sum(item.role == "calibration" for item in field_records) != protocol.field_calibration_count:
        raise ValueError("target field calibration count differs from the frozen protocol")
    if any(item.dataset_id != protocol.field_dataset_id for item in field_records):
        raise ValueError("target field sample dataset mismatch")
    if not neighborhood_records or any(
        item.dataset_id != protocol.neighborhood_dataset_id
        for item in neighborhood_records
    ):
        raise ValueError("target neighborhood sample dataset mismatch")
    source_counts = {source["dataset_id"]: source["sample_count"] for source in sources_raw}
    observed_counts = {
        protocol.field_dataset_id: len(field_records),
        protocol.neighborhood_dataset_id: len(neighborhood_records),
    }
    if source_counts != observed_counts:
        raise ValueError("target source sample counts do not match sample records")

    distributions_raw = raw["distributions"]
    if not isinstance(distributions_raw, list) or not distributions_raw:
        raise ValueError("spatial target distributions must be a non-empty list")
    distribution_records = []
    for index, distribution in enumerate(distributions_raw):
        if not isinstance(distribution, dict):
            raise ValueError(f"target distribution {index} must be an object")
        _exact_keys(
            distribution,
            {
                "role",
                "metric_id",
                "sample_count",
                "mean",
                "standard_deviation",
                "minimum",
                "q25",
                "median",
                "q75",
                "maximum",
            },
            name=f"target distribution {index}",
        )
        distribution_records.append(MetricDistribution(**distribution))
    grouped: dict[tuple[str, str], list[float]] = {}
    for sample in sample_records:
        for metric_id, value in sample.metrics:
            grouped.setdefault((sample.role, metric_id), []).append(value)
    expected_distributions = tuple(
        _distribution(role, metric_id, values).as_dict()
        for (role, metric_id), values in sorted(grouped.items())
    )
    if tuple(item.as_dict() for item in distribution_records) != expected_distributions:
        raise ValueError("target distributions do not recompute from sample metrics")

    profile = SpatialAnchorProfile(
        protocol=protocol,
        target_id=target_id,
        sources=tuple(sources_raw),
        samples=tuple(sample_records),
        distributions=tuple(distribution_records),
    )
    profile.verify_identity()
    return raw
