from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from .hashing import jsonable, canonical_json, digest_payload
from .layers import LayerId


def source_tree_digest(root: str | Path) -> str:
    """Hash Python source paths and contents below ``root``."""
    source_root = Path(root)
    files = sorted(
        source_root.rglob("*.py"),
        key=lambda path: path.relative_to(source_root).as_posix(),
    )
    if not files:
        raise ValueError("source tree contains no Python files")
    return digest_payload(
        tuple(
            (
                path.relative_to(source_root).as_posix(),
                sha256(path.read_bytes()).hexdigest(),
            )
            for path in files
        )
    )


@lru_cache(maxsize=1)
def package_source_digest() -> str:
    return source_tree_digest(Path(__file__).resolve().parent)


@dataclass(frozen=True, slots=True)
class ExperimentManifest:
    schema_version: str
    experiment_name: str
    seed: int
    code_version: str
    config_digest: str
    model_versions: tuple[tuple[str, str], ...]
    source_digest: str | None = None

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
        if (
            self.schema_version == "mgba-manifest-0.1"
            and self.source_digest is not None
        ):
            raise ValueError("legacy manifests must not define source_digest")
        if self.schema_version == "mgba-manifest-0.2" and not _is_sha256(
            self.source_digest
        ):
            raise ValueError("source_digest must be a lowercase SHA-256 digest")

    @classmethod
    def create(
        cls,
        *,
        experiment_name: str,
        seed: int,
        code_version: str,
        config: Any,
        model_versions: Mapping[str, str],
        source_digest: str | None = None,
    ) -> ExperimentManifest:
        return cls(
            schema_version="mgba-manifest-0.2",
            experiment_name=experiment_name,
            seed=seed,
            code_version=code_version,
            config_digest=digest_payload(config),
            model_versions=tuple(sorted(model_versions.items())),
            source_digest=(
                package_source_digest() if source_digest is None else source_digest
            ),
        )

    @property
    def experiment_id(self) -> str:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "experiment_name": self.experiment_name,
            "seed": self.seed,
            "code_version": self.code_version,
            "config_digest": self.config_digest,
            "model_versions": self.model_versions,
        }
        if self.source_digest is not None:
            payload["source_digest"] = self.source_digest
        return f"mgba-{digest_payload(payload)[:16]}"

    def as_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "experiment_name": self.experiment_name,
            "seed": self.seed,
            "code_version": self.code_version,
            "config_digest": self.config_digest,
            "model_versions": dict(self.model_versions),
        }
        if self.source_digest is not None:
            result["source_digest"] = self.source_digest
        return result


def _is_sha256(value: str | None) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


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
        result = jsonable(self)
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


def write_json_once(
    path: str | Path, payload: Mapping[str, Any], *, artifact: str = "artifact"
) -> Path:
    """Write ``payload`` as canonical JSON unless ``path`` holds different content.

    Shared append-only artifact protocol (previously copied per experiment
    module as ``_write_json_once``): rewriting identical content is a no-op,
    a corrupt or different existing file is refused, and the write is atomic
    (temporary file + replace) so a crash cannot leave a truncated artifact.
    """
    target = Path(path)
    encoded = (
        json.dumps(
            payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
        )
        + "\n"
    )
    if target.exists():
        try:
            existing = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ValueError(f"cannot verify existing {artifact}: {error}") from error
        if existing != encoded:
            raise ValueError(f"refusing to overwrite a different {artifact}")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(target)
    return target
