from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from ...hashing import digest_payload
from ...layers.l0 import ABSTRACT_GENE_NAMES
from ...models import Genome
from ...multiscale import MultiscaleScenario
from .data import CarmCohortProfile, load_carm_profile


SCENARIO_SCHEMA_VERSION = "mgba-carm-scenario-0.1"


def _require_text(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be empty")


def _require_unit(value: float, name: str) -> None:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and in [0, 1]")


def _validate_weights(weights: tuple[tuple[str, float], ...], names: set[str]) -> None:
    if {name for name, _ in weights} != names or len(weights) != len(names):
        raise ValueError("environment weights must contain the frozen names")
    for _, value in weights:
        _require_unit(value, "environment weight")
    if not math.isclose(sum(value for _, value in weights), 1.0, abs_tol=1e-12):
        raise ValueError("environment weights must sum to 1")


class CellRole(StrEnum):
    ENGINEERED_MACROPHAGE = "engineered_macrophage"
    WILD_TYPE_MACROPHAGE = "wild_type_macrophage"
    TUMOR = "tumor"
    CD8_T_CELL = "cd8_t_cell"


class SignalingDomain(StrEnum):
    CD3_ZETA = "CD3ζ"
    FC_R_GAMMA = "FcRγ"
    CD147 = "CD147"
    MERTK = "MerTK"


class TargetAntigen(StrEnum):
    HER2 = "HER2"
    CD19 = "CD19"
    EGFR = "EGFR"


@dataclass(frozen=True, slots=True)
class CarmDesign:
    signaling_domain: SignalingDomain
    target_antigen: TargetAntigen
    affinity: float
    cd47_sirpa_blockade: bool
    cd24_siglec10_blockade: bool

    def __post_init__(self) -> None:
        if not math.isfinite(self.affinity) or not 0.0 <= self.affinity <= 10.0:
            raise ValueError("CAR affinity must be finite and in [0, 10]")
        if not isinstance(self.cd47_sirpa_blockade, bool) or not isinstance(
            self.cd24_siglec10_blockade, bool
        ):
            raise TypeError("checkpoint blockade flags must be booleans")


@dataclass(frozen=True, slots=True)
class CarmPopulation:
    engineered_macrophages: int
    wild_type_macrophages: int
    tumor_cells: int
    cd8_t_cells: int

    def __post_init__(self) -> None:
        values = (
            self.engineered_macrophages,
            self.wild_type_macrophages,
            self.tumor_cells,
            self.cd8_t_cells,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in values):
            raise ValueError("every CAR-M population count must be a positive integer")

    @property
    def total(self) -> int:
        return (
            self.engineered_macrophages
            + self.wild_type_macrophages
            + self.tumor_cells
            + self.cd8_t_cells
        )


@dataclass(frozen=True, slots=True)
class CarmMicroenvironment:
    oxygen: float
    lactate: float
    tgf_beta: float
    stress_weights: tuple[tuple[str, float], ...]
    signal_weights: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        for name in ("oxygen", "lactate", "tgf_beta"):
            _require_unit(getattr(self, name), name)
        _validate_weights(
            self.stress_weights, {"hypoxia", "lactate", "m2_ratio", "tgf_beta"}
        )
        _validate_weights(self.signal_weights, {"cd8", "m1"})

    @property
    def stress_weight_map(self) -> dict[str, float]:
        return dict(self.stress_weights)

    @property
    def signal_weight_map(self) -> dict[str, float]:
        return dict(self.signal_weights)


@dataclass(frozen=True, slots=True)
class CarmCellConfig:
    model_version: str
    feedback_suppression: float
    macrophage_signal_weight: float
    macrophage_repair_gain: float
    cd8_signal_weight: float
    tumor_growth_rate: float
    immune_recovery_rate: float
    immune_stress_rate: float
    tumor_stress_rate: float
    apoptosis_threshold: float
    activation_threshold: float
    stress_threshold: float

    def __post_init__(self) -> None:
        _require_text(self.model_version, "CAR-M Cell model version")
        for name in (
            "feedback_suppression",
            "macrophage_signal_weight",
            "macrophage_repair_gain",
            "cd8_signal_weight",
            "tumor_growth_rate",
            "immune_recovery_rate",
            "immune_stress_rate",
            "tumor_stress_rate",
            "apoptosis_threshold",
            "activation_threshold",
            "stress_threshold",
        ):
            _require_unit(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class CarmTissueConfig:
    model_version: str
    resource_recovery: float
    resource_consumption_gain: float
    stress_retention: float
    signal_retention: float
    secretion_coupling: float
    macrophage_effector_gain: float
    cd8_effector_gain: float
    tumor_suppression_gain: float
    immune_stress_recovery: float
    tumor_burden_weight: float

    def __post_init__(self) -> None:
        _require_text(self.model_version, "CAR-M Tissue model version")
        for name in (
            "resource_recovery",
            "resource_consumption_gain",
            "stress_retention",
            "signal_retention",
            "secretion_coupling",
            "macrophage_effector_gain",
            "cd8_effector_gain",
            "tumor_suppression_gain",
            "immune_stress_recovery",
            "tumor_burden_weight",
        ):
            _require_unit(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class CarmScenarioConfig:
    schema_version: str
    model_version: str
    seed: int
    profile: CarmCohortProfile
    design: CarmDesign
    population: CarmPopulation
    microenvironment: CarmMicroenvironment
    genome_templates: tuple[tuple[CellRole, Genome], ...]
    tumor_neighbors_per_immune: int
    cell_model: CarmCellConfig
    tissue_model: CarmTissueConfig

    def __post_init__(self) -> None:
        if self.schema_version != SCENARIO_SCHEMA_VERSION:
            raise ValueError("unsupported CAR-M scenario schema")
        _require_text(self.model_version, "CAR-M scenario model version")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("CAR-M scenario seed must be a non-negative integer")
        roles = tuple(role for role, _ in self.genome_templates)
        if roles != tuple(CellRole):
            raise ValueError("genome templates must match every Cell role in order")
        if self.genome_template_map[CellRole.ENGINEERED_MACROPHAGE].traits != self.genome_template_map[
            CellRole.WILD_TYPE_MACROPHAGE
        ].traits:
            raise ValueError("engineered and wild-type macrophages need the same base genome")
        if (
            isinstance(self.tumor_neighbors_per_immune, bool)
            or not isinstance(self.tumor_neighbors_per_immune, int)
            or self.tumor_neighbors_per_immune < 1
            or self.tumor_neighbors_per_immune > self.population.tumor_cells
        ):
            raise ValueError("invalid tumor neighbor count")

    @property
    def genome_template_map(self) -> dict[CellRole, Genome]:
        return dict(self.genome_templates)


@dataclass(frozen=True, slots=True)
class CompiledCarmScenario:
    config: CarmScenarioConfig
    scenario: MultiscaleScenario
    roles: tuple[tuple[str, CellRole], ...]
    environment_stress: float
    incoming_signal: float

    def __post_init__(self) -> None:
        ids = tuple(cell_id for cell_id, _ in self.roles)
        scenario_ids = tuple(cell_id for cell_id, _ in self.scenario.genomes)
        if ids != scenario_ids or ids != tuple(sorted(ids)):
            raise ValueError("compiled CAR-M roles must align with scenario Cell ids")

    @property
    def role_map(self) -> dict[str, CellRole]:
        return dict(self.roles)

    @property
    def engineered_targets(self) -> tuple[str, ...]:
        return tuple(
            cell_id
            for cell_id, role in self.roles
            if role is CellRole.ENGINEERED_MACROPHAGE
        )

    @property
    def profile_digest(self) -> str:
        return digest_payload(self.config.profile)


def _load_weights(raw: Any) -> tuple[tuple[str, float], ...]:
    if not isinstance(raw, Mapping):
        raise ValueError("environment weights must be an object")
    return tuple(sorted((str(name), float(value)) for name, value in raw.items()))


def _load_genome(raw: Any, role: CellRole) -> tuple[CellRole, Genome]:
    if not isinstance(raw, Mapping):
        raise ValueError("genome template must be an object")
    traits = raw.get("traits")
    if not isinstance(traits, Mapping) or set(traits) != set(ABSTRACT_GENE_NAMES):
        raise ValueError("CAR-M genome template must contain the six abstract genes")
    return (
        role,
        Genome(
            version=str(raw["version"]),
            traits={str(name): float(value) for name, value in traits.items()},
        ),
    )

def load_carm_scenario_config(path: str | Path) -> CarmScenarioConfig:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("CAR-M scenario root must be an object")
        profile_path = (source.parent / str(raw["cohort_profile"])).resolve()
        design = raw["car_design"]
        checkpoints = design["checkpoint_blockade"]
        population = raw["population"]
        environment = raw["microenvironment"]
        genomes = raw["genome_templates"]
        cell = raw["cell_model"]
        tissue = raw["tissue_model"]
        return CarmScenarioConfig(
            schema_version=str(raw["schema_version"]),
            model_version=str(raw["model_version"]),
            seed=int(raw["seed"]),
            profile=load_carm_profile(profile_path),
            design=CarmDesign(
                signaling_domain=SignalingDomain(str(design["signaling_domain"])),
                target_antigen=TargetAntigen(str(design["target_antigen"])),
                affinity=float(design["affinity"]),
                cd47_sirpa_blockade=checkpoints["CD47_SIRPa"],
                cd24_siglec10_blockade=checkpoints["CD24_Siglec10"],
            ),
            population=CarmPopulation(
                engineered_macrophages=population["engineered_macrophages"],
                wild_type_macrophages=population["wild_type_macrophages"],
                tumor_cells=population["tumor_cells"],
                cd8_t_cells=population["cd8_t_cells"],
            ),
            microenvironment=CarmMicroenvironment(
                oxygen=float(environment["oxygen"]),
                lactate=float(environment["lactate"]),
                tgf_beta=float(environment["tgf_beta"]),
                stress_weights=_load_weights(environment["stress_weights"]),
                signal_weights=_load_weights(environment["signal_weights"]),
            ),
            genome_templates=tuple(
                _load_genome(genomes[role.value], role) for role in CellRole
            ),
            tumor_neighbors_per_immune=raw["topology"][
                "tumor_neighbors_per_immune"
            ],
            cell_model=CarmCellConfig(
                **{
                    name: (str(value) if name == "model_version" else float(value))
                    for name, value in cell.items()
                }
            ),
            tissue_model=CarmTissueConfig(
                **{
                    name: (str(value) if name == "model_version" else float(value))
                    for name, value in tissue.items()
                }
            ),
        )
    except (KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        raise ValueError("invalid CAR-M scenario config") from error


def _role_ids(config: CarmScenarioConfig) -> tuple[tuple[str, CellRole], ...]:
    counts = {
        CellRole.ENGINEERED_MACROPHAGE: config.population.engineered_macrophages,
        CellRole.WILD_TYPE_MACROPHAGE: config.population.wild_type_macrophages,
        CellRole.TUMOR: config.population.tumor_cells,
        CellRole.CD8_T_CELL: config.population.cd8_t_cells,
    }
    prefixes = {
        CellRole.ENGINEERED_MACROPHAGE: "eng-mac",
        CellRole.WILD_TYPE_MACROPHAGE: "wt-mac",
        CellRole.TUMOR: "tumor",
        CellRole.CD8_T_CELL: "cd8",
    }
    return tuple(
        sorted(
            (f"{prefixes[role]}-{index:03d}", role)
            for role in CellRole
            for index in range(1, counts[role] + 1)
        )
    )


def _fixed_edges(
    roles: tuple[tuple[str, CellRole], ...], tumor_neighbors: int
) -> tuple[tuple[str, str], ...]:
    groups = {
        role: tuple(cell_id for cell_id, item_role in roles if item_role is role)
        for role in CellRole
    }
    edges: set[tuple[str, str]] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        for index, source in enumerate(group):
            target = group[(index + 1) % len(group)]
            edges.add((source, target))
            edges.add((target, source))

    tumors = groups[CellRole.TUMOR]
    immune = tuple(
        cell_id
        for cell_id, role in roles
        if role is not CellRole.TUMOR
    )
    for index, immune_id in enumerate(immune):
        for offset in range(tumor_neighbors):
            tumor_id = tumors[(index + offset) % len(tumors)]
            edges.add((immune_id, tumor_id))
            edges.add((tumor_id, immune_id))
    return tuple(sorted(edges))


def compile_carm_scenario(config: CarmScenarioConfig) -> CompiledCarmScenario:
    if not isinstance(config, CarmScenarioConfig):
        raise TypeError("compile_carm_scenario requires a CarmScenarioConfig")
    infiltration = config.profile.infiltration
    required = {"Macrophages_M1", "Macrophages_M2", "T_cells_CD8"}
    if not required <= set(infiltration):
        raise ValueError("CAR-M profile lacks required immune proxy values")
    macrophage_total = infiltration["Macrophages_M1"] + infiltration["Macrophages_M2"]
    m2_ratio = (
        infiltration["Macrophages_M2"] / macrophage_total
        if macrophage_total > 0.0
        else 0.5
    )
    stress_terms = {
        "hypoxia": 1.0 - config.microenvironment.oxygen,
        "lactate": config.microenvironment.lactate,
        "m2_ratio": m2_ratio,
        "tgf_beta": config.microenvironment.tgf_beta,
    }
    environment_stress = sum(
        config.microenvironment.stress_weight_map[name] * value
        for name, value in stress_terms.items()
    )
    signal_terms = {
        "cd8": infiltration["T_cells_CD8"],
        "m1": infiltration["Macrophages_M1"],
    }
    incoming_signal = min(
        1.0,
        sum(
            config.microenvironment.signal_weight_map[name] * value
            for name, value in signal_terms.items()
        ),
    )
    roles = _role_ids(config)
    templates = config.genome_template_map
    scenario = MultiscaleScenario(
        seed=config.seed,
        environment_stress=environment_stress,
        resource_level=config.microenvironment.oxygen,
        incoming_signal=incoming_signal,
        genomes=tuple(
            (
                cell_id,
                Genome(
                    version=(
                        f"{templates[role].version}+{config.profile.cohort_id}"
                    ),
                    traits=dict(templates[role].traits),
                ),
            )
            for cell_id, role in roles
        ),
        edges=_fixed_edges(roles, config.tumor_neighbors_per_immune),
    )
    return CompiledCarmScenario(
        config=config,
        scenario=scenario,
        roles=roles,
        environment_stress=environment_stress,
        incoming_signal=incoming_signal,
    )
