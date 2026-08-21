"""TCGA-proxy-anchored CAR-M vertical slice for M-GBA v0.2."""

from .data import (
    CarmCohortProfile,
    build_carm_profile,
    load_carm_profile,
    save_carm_profile,
)
from .models import CarmCellModel, CarmTissueModel
from .spatial import (
    CarmSpatialConfig,
    CarmSpatialMechanisms,
    SpatialCarmTissueModel,
    load_carm_spatial_config,
)
from .scenario import (
    CarmScenarioConfig,
    CellRole,
    CompiledCarmScenario,
    compile_carm_scenario,
    load_carm_scenario_config,
)
from .workflow import (
    CARM_MODEL_STATUS,
    build_carm_runners,
    run_carm_matrix,
    save_carm_artifacts,
)

__all__ = [
    "CARM_MODEL_STATUS",
    "CarmCellModel",
    "CarmCohortProfile",
    "CarmScenarioConfig",
    "CarmSpatialConfig",
    "CarmSpatialMechanisms",
    "CarmTissueModel",
    "CellRole",
    "CompiledCarmScenario",
    "SpatialCarmTissueModel",
    "build_carm_profile",
    "build_carm_runners",
    "compile_carm_scenario",
    "load_carm_profile",
    "load_carm_scenario_config",
    "load_carm_spatial_config",
    "run_carm_matrix",
    "save_carm_artifacts",
    "save_carm_profile",
]
