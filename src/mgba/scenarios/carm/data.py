from __future__ import annotations

import json
import math
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping


PROFILE_SCHEMA_VERSION = "mgba-carm-cohort-profile-0.1"
PROXY_LABEL_NOTICE = (
    "TCGA-BRCA immune values are legacy GAT predictions trained against "
    "gene-signature-derived proxy labels; they are not clinical ground truth."
)
ALLOWED_IMMUNE_SUBTYPES = ("high_immune", "low_immune", "normal")
ALLOWED_TARGET_ANTIGENS = ("CD19", "EGFR", "HER2")


def _require_text(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be empty")


def _require_probability(value: float, name: str) -> None:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and in [0, 1]")


@dataclass(frozen=True, slots=True)
class SourceArtifact:
    name: str
    sha256: str

    def __post_init__(self) -> None:
        _require_text(self.name, "source artifact name")
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise ValueError("source artifact sha256 must be lowercase hexadecimal")


@dataclass(frozen=True, slots=True)
class CarmCohortProfile:
    schema_version: str
    cohort_id: str
    cancer_type: str
    immune_subtype: str
    total_sample_count: int
    sample_count: int
    subtype_counts: tuple[tuple[str, int], ...]
    mean_immune_infiltration: tuple[tuple[str, float], ...]
    source_model: str
    source_backend: str
    subtype_accuracy: float
    survival_auc: float
    graph_source: str
    graph_node_count: int
    graph_edge_count: int
    legacy_preset_name: str
    legacy_reported_sample_count: int
    source_artifacts: tuple[SourceArtifact, ...]
    proxy_label_notice: str

    def __post_init__(self) -> None:
        if self.schema_version != PROFILE_SCHEMA_VERSION:
            raise ValueError("unsupported CAR-M cohort profile schema")
        for name, value in (
            ("cohort_id", self.cohort_id),
            ("cancer_type", self.cancer_type),
            ("source_model", self.source_model),
            ("source_backend", self.source_backend),
            ("graph_source", self.graph_source),
            ("legacy_preset_name", self.legacy_preset_name),
            ("proxy_label_notice", self.proxy_label_notice),
        ):
            _require_text(value, name)
        if self.immune_subtype not in ALLOWED_IMMUNE_SUBTYPES:
            raise ValueError("unknown immune subtype")
        if self.total_sample_count < 1 or self.sample_count < 1:
            raise ValueError("cohort sample counts must be positive")
        if self.sample_count > self.total_sample_count:
            raise ValueError("cohort sample count cannot exceed total samples")
        if self.legacy_reported_sample_count < 1:
            raise ValueError("legacy reported sample count must be positive")
        if self.graph_node_count < 1 or self.graph_edge_count < 1:
            raise ValueError("graph counts must be positive")
        _require_probability(self.subtype_accuracy, "subtype_accuracy")
        _require_probability(self.survival_auc, "survival_auc")
        if tuple(name for name, _ in self.subtype_counts) != tuple(
            sorted(ALLOWED_IMMUNE_SUBTYPES)
        ):
            raise ValueError("subtype counts must contain every supported subtype")
        if sum(count for _, count in self.subtype_counts) != self.total_sample_count:
            raise ValueError("subtype counts must sum to total samples")
        if dict(self.subtype_counts)[self.immune_subtype] != self.sample_count:
            raise ValueError("selected subtype count must equal cohort sample count")
        infiltration_names = tuple(name for name, _ in self.mean_immune_infiltration)
        if (
            not infiltration_names
            or infiltration_names != tuple(sorted(infiltration_names))
            or len(set(infiltration_names)) != len(infiltration_names)
        ):
            raise ValueError("immune infiltration names must be unique and sorted")
        for _, value in self.mean_immune_infiltration:
            _require_probability(value, "mean immune infiltration")
        artifact_names = tuple(item.name for item in self.source_artifacts)
        if (
            not artifact_names
            or artifact_names != tuple(sorted(artifact_names))
            or len(set(artifact_names)) != len(artifact_names)
        ):
            raise ValueError("source artifacts must be unique and sorted")

    @property
    def infiltration(self) -> dict[str, float]:
        return dict(self.mean_immune_infiltration)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "cohort_id": self.cohort_id,
            "cancer_type": self.cancer_type,
            "immune_subtype": self.immune_subtype,
            "total_sample_count": self.total_sample_count,
            "sample_count": self.sample_count,
            "subtype_counts": dict(self.subtype_counts),
            "mean_immune_infiltration": dict(self.mean_immune_infiltration),
            "source_model": self.source_model,
            "source_backend": self.source_backend,
            "subtype_accuracy": self.subtype_accuracy,
            "survival_auc": self.survival_auc,
            "graph_source": self.graph_source,
            "graph_node_count": self.graph_node_count,
            "graph_edge_count": self.graph_edge_count,
            "legacy_preset_name": self.legacy_preset_name,
            "legacy_reported_sample_count": self.legacy_reported_sample_count,
            "source_artifacts": [
                {"name": item.name, "sha256": item.sha256}
                for item in self.source_artifacts
            ],
            "proxy_label_notice": self.proxy_label_notice,
        }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read valid JSON from {path}") from error


def _file_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _legacy_data_root(legacy_root: str | Path) -> Path:
    root = Path(legacy_root)
    direct = root / "tcga_predictions.json"
    if direct.is_file():
        return root
    nested = root / "app" / "public" / "data" / "tcga"
    if nested.is_dir():
        return nested
    raise ValueError("legacy root does not contain the expected TCGA artifacts")


def build_carm_profile(
    legacy_root: str | Path, *, immune_subtype: str = "high_immune"
) -> CarmCohortProfile:
    if immune_subtype not in ALLOWED_IMMUNE_SUBTYPES:
        raise ValueError("unsupported CAR-M immune subtype")
    root = _legacy_data_root(legacy_root)
    predictions_path = root / "tcga_predictions.json"
    graph_path = root / "tcga_graph_info.json"
    scenarios_path = root / "tcga_patient_scenarios.json"
    predictions = _read_json(predictions_path)
    graph = _read_json(graph_path)
    scenarios = _read_json(scenarios_path)
    if not isinstance(predictions, dict) or not isinstance(graph, dict):
        raise ValueError("legacy TCGA prediction and graph roots must be objects")
    if not isinstance(scenarios, list):
        raise ValueError("legacy TCGA scenarios must be an array")

    metadata = predictions.get("metadata")
    records = predictions.get("predictions")
    immune_types = predictions.get("immune_cell_types")
    if not isinstance(metadata, dict) or not isinstance(records, list):
        raise ValueError("legacy TCGA predictions have an invalid schema")
    if (
        not isinstance(immune_types, list)
        or len(immune_types) != 22
        or any(not isinstance(name, str) or not name.strip() for name in immune_types)
        or len(set(immune_types)) != len(immune_types)
    ):
        raise ValueError("legacy immune cell types must contain 22 unique names")

    subtype_values: dict[str, list[list[float]]] = {
        name: [] for name in ALLOWED_IMMUNE_SUBTYPES
    }
    sample_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("legacy prediction records must be objects")
        sample_id = record.get("sample_id")
        subtype = record.get("immune_subtype")
        values = record.get("immune_infiltration")
        if not isinstance(sample_id, str) or not sample_id.strip():
            raise ValueError("legacy prediction sample ids must be non-empty")
        if sample_id in sample_ids:
            raise ValueError("legacy prediction sample ids must be unique")
        sample_ids.add(sample_id)
        if subtype not in subtype_values:
            raise ValueError("legacy prediction contains an unknown immune subtype")
        if not isinstance(values, list) or len(values) != len(immune_types):
            raise ValueError("legacy immune infiltration vector has the wrong size")
        normalized = [float(value) for value in values]
        for value in normalized:
            _require_probability(value, "legacy immune infiltration")
        subtype_values[subtype].append(normalized)

    total_sample_count = len(records)
    if int(metadata.get("n_samples", -1)) != total_sample_count:
        raise ValueError("legacy prediction metadata sample count is inconsistent")
    selected = subtype_values[immune_subtype]
    if not selected:
        raise ValueError("selected immune subtype has no samples")
    means = tuple(
        sorted(
            (
                name,
                fmean(row[index] for row in selected),
            )
            for index, name in enumerate(immune_types)
        )
    )

    selected_scenarios = [
        item
        for item in scenarios
        if isinstance(item, dict)
        and isinstance(item.get("tcga_source"), dict)
        and item["tcga_source"].get("subtype") == immune_subtype
        and isinstance(item.get("car_design"), dict)
        and item["car_design"].get("targetAntigen") == "HER2"
    ]
    if len(selected_scenarios) != 1:
        raise ValueError("legacy scenarios must contain one HER2 preset for the subtype")
    preset = selected_scenarios[0]
    target = str(preset["car_design"]["targetAntigen"])
    if target not in ALLOWED_TARGET_ANTIGENS:
        raise ValueError("legacy preset target antigen is unsupported")
    legacy_source = preset["tcga_source"]

    cv_scores = metadata.get("cv_scores")
    if not isinstance(cv_scores, Mapping):
        raise ValueError("legacy prediction metadata is missing CV scores")
    source_artifacts = tuple(
        sorted(
            (
                SourceArtifact(path.name, _file_digest(path))
                for path in (predictions_path, graph_path, scenarios_path)
            ),
            key=lambda item: item.name,
        )
    )
    return CarmCohortProfile(
        schema_version=PROFILE_SCHEMA_VERSION,
        cohort_id=f"tcga_brca_{immune_subtype}",
        cancer_type=str(metadata["cancer_type"]),
        immune_subtype=immune_subtype,
        total_sample_count=total_sample_count,
        sample_count=len(selected),
        subtype_counts=tuple(
            sorted((name, len(values)) for name, values in subtype_values.items())
        ),
        mean_immune_infiltration=means,
        source_model=str(metadata["model"]),
        source_backend=str(metadata["backend"]),
        subtype_accuracy=float(cv_scores["accuracy"]),
        survival_auc=float(cv_scores["auc_risk"]),
        graph_source=str(graph["source"]),
        graph_node_count=int(graph["n_nodes"]),
        graph_edge_count=int(graph["n_edges"]),
        legacy_preset_name=str(preset["name"]),
        legacy_reported_sample_count=int(legacy_source["sample_count"]),
        source_artifacts=source_artifacts,
        proxy_label_notice=PROXY_LABEL_NOTICE,
    )


def load_carm_profile(path: str | Path) -> CarmCohortProfile:
    raw = _read_json(Path(path))
    if not isinstance(raw, dict):
        raise ValueError("CAR-M cohort profile root must be an object")
    try:
        return CarmCohortProfile(
            schema_version=str(raw["schema_version"]),
            cohort_id=str(raw["cohort_id"]),
            cancer_type=str(raw["cancer_type"]),
            immune_subtype=str(raw["immune_subtype"]),
            total_sample_count=int(raw["total_sample_count"]),
            sample_count=int(raw["sample_count"]),
            subtype_counts=tuple(
                sorted((str(name), int(value)) for name, value in raw["subtype_counts"].items())
            ),
            mean_immune_infiltration=tuple(
                sorted(
                    (str(name), float(value))
                    for name, value in raw["mean_immune_infiltration"].items()
                )
            ),
            source_model=str(raw["source_model"]),
            source_backend=str(raw["source_backend"]),
            subtype_accuracy=float(raw["subtype_accuracy"]),
            survival_auc=float(raw["survival_auc"]),
            graph_source=str(raw["graph_source"]),
            graph_node_count=int(raw["graph_node_count"]),
            graph_edge_count=int(raw["graph_edge_count"]),
            legacy_preset_name=str(raw["legacy_preset_name"]),
            legacy_reported_sample_count=int(raw["legacy_reported_sample_count"]),
            source_artifacts=tuple(
                SourceArtifact(str(item["name"]), str(item["sha256"]))
                for item in raw["source_artifacts"]
            ),
            proxy_label_notice=str(raw["proxy_label_notice"]),
        )
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("invalid CAR-M cohort profile") from error


def save_carm_profile(path: str | Path, profile: CarmCohortProfile) -> None:
    if not isinstance(profile, CarmCohortProfile):
        raise TypeError("save_carm_profile requires a CarmCohortProfile")
    target = Path(path)
    payload = profile.as_dict()
    if target.exists():
        existing = _read_json(target)
        if existing != payload:
            raise ValueError("refusing to overwrite a different CAR-M profile")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
