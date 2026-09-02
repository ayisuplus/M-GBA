"""Optional L0 variant driven by the distilled empirical response table (ADR-0038).

Natural dynamics are delegated to the reference ``DiscreteGrnModel`` bit-for-bit.
Perturbation application differs by target name:

- abstract node name -> reference hard-clamp semantics (bit-identical fallback);
- unit present in the verified response table -> frozen empirical rule
  ``applied_i = clamp01(natural_i * 2 ** (dose * log2fc_i))`` per node, with one
  audited ``L0PerturbationEvent`` per node (kind by comparison with natural);
- anything else -> fail-closed.

The table is plain verified data; this module never touches torch/numpy/weights.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ..empirical_response import EmpiricalResponseTable
from ..hashing import digest_payload
from ..models import Genome
from .contracts import (
    GenomeStepResult,
    L0PerturbationEvent,
    PerturbationKind,
    RegulatoryInput,
    TranscriptState,
)
from .l0 import (
    ABSTRACT_GENE_NAMES,
    DiscreteGrnModel,
    GrnConfig,
    _build_state,
    _perturb,
    _state_values,
)

EMPIRICAL_L0_MODEL_VERSION = "empirical-l0-response-0.1"


def load_empirical_l0_config(path: str | Path) -> dict[str, str]:
    """Load the empirical L0 identity config; any read/parse failure is a ValueError."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid empirical L0 config: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("empirical L0 config must be a JSON object")
    if set(raw) != {"model_version", "response_table_path", "response_table_sha256"}:
        raise ValueError(
            "empirical L0 config keys must be model_version/response_table_path/response_table_sha256"
        )
    for key in raw:
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise ValueError(f"empirical L0 config {key} must be a non-empty string")
    if raw["model_version"] != EMPIRICAL_L0_MODEL_VERSION:
        raise ValueError("empirical L0 config model_version mismatch")
    return raw


class EmpiricalResponseGrnModel:
    """Reference GRN dynamics plus empirical six-node perturbation responses."""

    def __init__(
        self,
        config: GrnConfig,
        *,
        response_table: EmpiricalResponseTable,
        table_path: str,
    ) -> None:
        if not isinstance(config, GrnConfig):
            raise TypeError("empirical L0 requires the reference GrnConfig")
        if not isinstance(response_table, EmpiricalResponseTable):
            raise TypeError("empirical L0 requires an EmpiricalResponseTable")
        if not table_path.strip():
            raise ValueError("response table path must not be empty")
        self._reference = DiscreteGrnModel(config)
        self._table = response_table
        self._table_path = table_path

    @property
    def model_version(self) -> str:
        return f"{EMPIRICAL_L0_MODEL_VERSION}+{self._table.table_digest[:12]}"

    @property
    def response_table(self) -> EmpiricalResponseTable:
        return self._table

    def _apply(
        self,
        *,
        cell_id: str,
        logical_time: int,
        natural_values: Mapping[str, float],
        perturbations: Mapping[str, float],
    ) -> tuple[dict[str, float], tuple[L0PerturbationEvent, ...]]:
        abstract = {
            name: value
            for name, value in perturbations.items()
            if name in ABSTRACT_GENE_NAMES
        }
        empirical = {
            name: value
            for name, value in perturbations.items()
            if name not in ABSTRACT_GENE_NAMES
        }
        unknown = set(empirical) - set(self._table.units)
        if unknown:
            raise ValueError(f"perturbations target unknown genes/units: {sorted(unknown)}")

        applied, reference_events = _perturb(
            cell_id=cell_id,
            logical_time=logical_time,
            natural_values=natural_values,
            perturbations=abstract,
        )
        events = list(reference_events)
        for unit in sorted(empirical):
            dose = empirical[unit]
            if not 0.0 <= dose <= 1.0:
                raise ValueError("empirical perturbation dose must be in [0, 1]")
            for node, log2fc in self._table.as_node_dict(unit).items():
                natural = applied[node]
                requested = min(1.0, max(0.0, natural * (2.0 ** (dose * log2fc))))
                if requested < natural:
                    kind = PerturbationKind.KNOCKDOWN
                elif requested > natural:
                    kind = PerturbationKind.OVEREXPRESSION
                else:
                    kind = PerturbationKind.CLAMP_NO_CHANGE
                applied[node] = requested
                events.append(
                    L0PerturbationEvent(
                        cell_id=cell_id,
                        logical_time=logical_time,
                        gene=node,
                        unperturbed_value=natural,
                        applied_value=requested,
                        kind=kind,
                    )
                )
        return applied, tuple(events)

    def _source(self, *, phase: str, **fields: Any) -> dict[str, Any]:
        return {
            "phase": phase,
            "response_table": {
                "table_id": self._table.table_id,
                "sha256": self._table.table_digest,
                "path": self._table_path,
            },
            **fields,
        }

    def initialize(
        self,
        *,
        cell_id: str,
        genome: Genome,
        regulatory_input: RegulatoryInput,
        perturbations: Mapping[str, float],
        logical_time: int = 0,
    ) -> GenomeStepResult:
        natural_result = self._reference.initialize(
            cell_id=cell_id,
            genome=genome,
            regulatory_input=regulatory_input,
            perturbations={},
            logical_time=logical_time,
        )
        natural = _state_values(natural_result.state)
        applied, events = self._apply(
            cell_id=cell_id,
            logical_time=logical_time,
            natural_values=natural,
            perturbations=perturbations,
        )
        state = _build_state(
            cell_id=cell_id,
            logical_time=logical_time,
            model_version=self.model_version,
            source=self._source(
                phase="initial",
                genome=genome,
                regulatory_input=regulatory_input,
                perturbations=dict(perturbations),
                config=self._reference.config,
            ),
            values=applied,
        )
        return GenomeStepResult(state=state, perturbation_events=events)

    def step(
        self,
        *,
        cell_id: str,
        genome: Genome,
        previous_state: TranscriptState | None,
        regulatory_input: RegulatoryInput,
        perturbations: Mapping[str, float],
        logical_time: int,
    ) -> GenomeStepResult:
        natural_result = self._reference.step(
            cell_id=cell_id,
            genome=genome,
            previous_state=previous_state,
            regulatory_input=regulatory_input,
            perturbations={},
            logical_time=logical_time,
        )
        natural = _state_values(natural_result.state)
        applied, events = self._apply(
            cell_id=cell_id,
            logical_time=logical_time,
            natural_values=natural,
            perturbations=perturbations,
        )
        state = _build_state(
            cell_id=cell_id,
            logical_time=logical_time,
            model_version=self.model_version,
            source=self._source(
                phase="step",
                genome=genome,
                previous_state=previous_state,
                regulatory_input=regulatory_input,
                perturbations=dict(perturbations),
                config=self._reference.config,
            ),
            values=applied,
        )
        return GenomeStepResult(state=state, perturbation_events=events)

    def config_fingerprint(self) -> str:
        return digest_payload(
            {
                "model_version": self.model_version,
                "grn_config": self._reference.config,
                "table": self._table.table_digest,
            }
        )
