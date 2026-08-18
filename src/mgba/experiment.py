from __future__ import annotations

import json
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from .layers import LayerId


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def digest_payload(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExperimentManifest:
    schema_version: str
    experiment_name: str
    seed: int
    code_version: str
    config_digest: str
    model_versions: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.schema_version.strip() or not self.experiment_name.strip():
            raise ValueError("schema_version and experiment_name must not be empty")
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if not self.code_version.strip() or not self.config_digest.strip():
            raise ValueError("code_version and config_digest must not be empty")
        if self.model_versions != tuple(sorted(self.model_versions)):
            raise ValueError("model_versions must be sorted by layer")
        if any(not layer or not version for layer, version in self.model_versions):
            raise ValueError("model layer and version names must not be empty")
        if len({layer for layer, _ in self.model_versions}) != len(self.model_versions):
            raise ValueError("model layer names must be unique")

    @classmethod
    def create(
        cls,
        *,
        experiment_name: str,
        seed: int,
        code_version: str,
        config: Any,
        model_versions: Mapping[str, str],
    ) -> ExperimentManifest:
        return cls(
            schema_version="mgba-manifest-0.1",
            experiment_name=experiment_name,
            seed=seed,
            code_version=code_version,
            config_digest=digest_payload(config),
            model_versions=tuple(sorted(model_versions.items())),
        )

    @property
    def experiment_id(self) -> str:
        return f"mgba-{digest_payload(self)[:16]}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "experiment_name": self.experiment_name,
            "seed": self.seed,
            "code_version": self.code_version,
            "config_digest": self.config_digest,
            "model_versions": dict(self.model_versions),
        }


_NEXT_LAYER = {
    LayerId.L0: LayerId.L1,
    LayerId.L1: LayerId.L2,
    LayerId.L2: LayerId.L3,
    LayerId.L3: LayerId.L4,
}


@dataclass(frozen=True, slots=True)
class LayerTransitionEvent:
    logical_time: int
    source_layer: LayerId
    target_layer: LayerId
    model_version: str
    input_digest: str
    output_digest: str
    timescale: str
    reason: str

    def __post_init__(self) -> None:
        if self.logical_time < 0:
            raise ValueError("logical_time must be non-negative")
        if _NEXT_LAYER.get(self.source_layer) != self.target_layer:
            raise ValueError("layer transitions must target the adjacent upper layer")
        for value in (
            self.model_version,
            self.input_digest,
            self.output_digest,
            self.timescale,
            self.reason,
        ):
            if not value.strip():
                raise ValueError("transition event text fields must not be empty")

    @property
    def event_id(self) -> str:
        return f"transition-{digest_payload(self)[:16]}"

    def as_dict(self) -> dict[str, Any]:
        result = _jsonable(self)
        result["event_id"] = self.event_id
        return result


@dataclass(frozen=True, slots=True)
class ExperimentPaths:
    root: Path
    manifest: Path
    events: Path
    states: Path
    derived: Path


def initialize_experiment_artifacts(
    artifact_root: str | Path, manifest: ExperimentManifest
) -> ExperimentPaths:
    root = Path(artifact_root) / manifest.experiment_id
    raw = root / "raw"
    states = raw / "states"
    derived = root / "derived"
    manifest_path = root / "manifest.json"
    events_path = raw / "events.ndjson"

    states.mkdir(parents=True, exist_ok=True)
    derived.mkdir(parents=True, exist_ok=True)
    expected_manifest = manifest.as_dict()
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing != expected_manifest:
            raise ValueError("existing artifact directory has a different manifest")
    else:
        manifest_path.write_text(
            json.dumps(expected_manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    events_path.touch(exist_ok=True)
    return ExperimentPaths(
        root=root,
        manifest=manifest_path,
        events=events_path,
        states=states,
        derived=derived,
    )


def append_transition_event(
    paths: ExperimentPaths, event: LayerTransitionEvent
) -> None:
    with paths.events.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(event.as_dict()) + "\n")
