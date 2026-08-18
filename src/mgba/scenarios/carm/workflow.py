from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ...experiment import canonical_json, digest_payload
from ...experiments import (
    CausalArtifactPaths,
    CausalExperimentConfig,
    CausalExperimentRunner,
    CausalMatrixResult,
    save_causal_artifacts,
)
from ...layers.l0 import DiscreteGrnModel, load_grn_config
from ...layers.l1 import (
    CoarseMolecularModel,
    StaticMolecularModel,
    load_molecular_config,
)
from ...layers.l2 import StaticCellModel
from ...layers.l3 import StaticTissueModel
from ...layers.l4 import PhenotypeObserverModel, load_phenotype_config
from ...runner import MultirateCrossScaleRunner, RunnerConfig
from .models import CarmCellModel, CarmTissueModel
from .scenario import CompiledCarmScenario


CARM_MODEL_STATUS = (
    "tcga-proxy-anchored-mechanism-informed-reference-model; "
    "not a validated biological or clinical predictor"
)


@dataclass(frozen=True, slots=True)
class CarmExperimentArtifacts:
    causal: CausalArtifactPaths
    provenance: Path


def build_carm_runners(
    compiled: CompiledCarmScenario,
    matrix_config: CausalExperimentConfig,
    *,
    runner_config: RunnerConfig,
    l0_config: str | Path,
    l1_config: str | Path,
    l4_config: str | Path,
) -> dict[str, MultirateCrossScaleRunner]:
    roles = compiled.roles
    profile_digest = compiled.profile_digest

    def build(variant: str) -> MultirateCrossScaleRunner:
        molecular_model = (
            StaticMolecularModel()
            if variant == "l1_static"
            else CoarseMolecularModel(load_molecular_config(l1_config))
        )
        cell_model = (
            StaticCellModel()
            if variant == "l2_static"
            else CarmCellModel(
                compiled.config.cell_model,
                roles=roles,
                source_profile_digest=profile_digest,
            )
        )
        tissue_model = (
            StaticTissueModel()
            if variant == "l3_static"
            else CarmTissueModel(
                compiled.config.tissue_model,
                roles=roles,
                source_profile_digest=profile_digest,
            )
        )
        return MultirateCrossScaleRunner(
            runner_config,
            genome_model=DiscreteGrnModel(load_grn_config(l0_config)),
            molecular_model=molecular_model,
            cell_model=cell_model,
            tissue_model=tissue_model,
            phenotype_model=PhenotypeObserverModel(
                load_phenotype_config(l4_config)
            ),
        )

    return {
        variant: build(variant)
        for variant in ("baseline", *matrix_config.ablations)
    }


def run_carm_matrix(
    compiled: CompiledCarmScenario,
    matrix_config: CausalExperimentConfig,
    *,
    runners: Mapping[str, MultirateCrossScaleRunner],
) -> CausalMatrixResult:
    expected_targets = set(compiled.engineered_targets)
    for condition in matrix_config.perturbations:
        targets = getattr(condition, "targets", (getattr(condition, "cell_id", ""),))
        if set(targets) != expected_targets:
            raise ValueError(
                "every CAR-M perturbation must target all engineered macrophages"
            )
        if condition.gene != "signal_expression":
            raise ValueError("CAR-M v0.2 perturbations must target signal_expression")
    return CausalExperimentRunner(matrix_config, runners=runners).run(
        compiled.scenario
    )


def _write_json_once(path: Path, payload: dict[str, object]) -> None:
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("existing CAR-M provenance is invalid JSON") from error
        if existing != payload:
            raise ValueError("refusing to overwrite different CAR-M provenance")
        return
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def save_carm_artifacts(
    artifact_root: str | Path,
    result: CausalMatrixResult,
    compiled: CompiledCarmScenario,
) -> CarmExperimentArtifacts:
    causal = save_causal_artifacts(artifact_root, result)
    provenance = causal.root / "carm-provenance.json"
    config_json = json.loads(canonical_json(compiled.config))
    payload: dict[str, object] = {
        "schema_version": "mgba-carm-provenance-0.1",
        "matrix_id": result.matrix_id,
        "model_status": CARM_MODEL_STATUS,
        "profile": compiled.config.profile.as_dict(),
        "profile_digest": compiled.profile_digest,
        "scenario_config_digest": digest_payload(compiled.config),
        "scenario_config": config_json,
        "compiled_environment": {
            "environment_stress": compiled.environment_stress,
            "resource_level": compiled.scenario.resource_level,
            "incoming_signal": compiled.incoming_signal,
        },
        "cell_roles": {cell_id: role.value for cell_id, role in compiled.roles},
        "tumor_burden_proxy_notice": (
            "L3 tissue_damage is a frozen model-internal proxy combining tumor "
            "viability and immune-cell injury; it is not a clinical endpoint."
        ),
    }
    _write_json_once(provenance, payload)
    return CarmExperimentArtifacts(causal=causal, provenance=provenance)
