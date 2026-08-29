"""Competition virtual-lab contracts and observation-only bundle export.

The lab sits outside the L0--L4 tick loop.  It either projects immutable run
artifacts into a compact display contract or invokes the existing runner
through one frozen, allow-listed CAR-M protocol.  It never accepts model
objects, file paths, target Cell ids, or arbitrary perturbation payloads from
web clients.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

from .demo import BOUNDARY_NOTE, _build_layout, _condition_ticks
from .collective_dynamics import (
    COLLECTIVE_DYNAMICS_SCHEMA,
    COLLECTIVE_OBSERVER_VERSION,
    CollectiveDynamicsConfig,
    analyze_collective_dynamics_lab_condition,
    collective_response,
    compare_collective_dynamics,
)
from .experiment import canonical_json, digest_payload
from .experiments import CausalRunRecord, ConditionKind, _compare_runs
from .intervention_experiments import build_carm_intervention_runner
from .runner import MultirateRun, load_runner_config
from .scenarios.carm import (
    compile_carm_scenario,
    load_carm_scenario_config,
)
from .scenarios.carm.scenario import CellRole


LAB_REQUEST_SCHEMA = "mgba-lab-experiment-request-0.1"
LAB_BUNDLE_SCHEMA = "mgba-lab-run-bundle-0.1"
LAB_CATALOG_SCHEMA = "mgba-lab-catalog-0.1"
LAB_FILES_SCHEMA = "mgba-lab-files-0.1"
LAB_EXECUTION_REVISION = "carm-state-conditioned-paired-0.3"

_SCENARIO_ID = "carm_high_immune_her2"
_PROTOCOL_ID = "state_conditioned_signal_expression"
_DOSES = (0.0, 0.7, 1.0)
_ONSETS = ("early", "late")
_EXPOSURES = ("short", "long")
_L0_FIELDS = (
    "damage_response",
    "signal_expression",
    "repair_expression",
    "metabolic_expression",
    "death_expression",
    "negative_feedback_expression",
)
_L1_FIELDS = (
    "damage_receptor",
    "signal_protein",
    "repair_protein",
    "metabolic_capacity",
    "death_effector",
    "feedback_inhibitor",
)
_L3_FIELDS = (
    "edge_density",
    "mean_activation",
    "mean_viability",
    "mean_resource",
    "mean_signal",
    "dead_fraction",
    "repair_activity",
    "coordinated_signal",
    "tissue_damage",
)
_L4_FIELDS = (
    "vitality",
    "damage_burden",
    "inflammation",
    "homeostasis",
    "recovery_capacity",
)


def _round4(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("lab bundle values must be finite")
    rounded = round(number, 4)
    return 0.0 if rounded == 0.0 else rounded


def _compact_json(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _load_json_object(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid lab source JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("lab source JSON root must be an object")
    return payload


def _role_for_cell(cell_id: str) -> str:
    if cell_id.startswith("eng-mac-"):
        return "engineered_macrophage"
    if cell_id.startswith("wt-mac-"):
        return "wild_type_macrophage"
    if cell_id.startswith("tumor-"):
        return "tumor"
    if cell_id.startswith("cd8-"):
        return "cd8_t_cell"
    raise ValueError(f"unrecognized CAR-M Cell id in lab source: {cell_id}")


@dataclass(frozen=True, slots=True)
class LabExperimentRequest:
    schema_version: str
    scenario_id: str
    protocol_id: str
    dose: float
    onset: str
    exposure: str

    def __post_init__(self) -> None:
        if self.schema_version != LAB_REQUEST_SCHEMA:
            raise ValueError("unsupported lab request schema")
        if self.scenario_id != _SCENARIO_ID:
            raise ValueError("unsupported lab scenario")
        if self.protocol_id != _PROTOCOL_ID:
            raise ValueError("unsupported lab protocol")
        if isinstance(self.dose, bool) or self.dose not in _DOSES:
            raise ValueError("dose must be one of 0.0, 0.7, or 1.0")
        if self.onset not in _ONSETS:
            raise ValueError("onset must be early or late")
        if self.exposure not in _EXPOSURES:
            raise ValueError("exposure must be short or long")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "LabExperimentRequest":
        fields = {
            "schema_version",
            "scenario_id",
            "protocol_id",
            "dose",
            "onset",
            "exposure",
        }
        if not isinstance(raw, Mapping) or set(raw) != fields:
            raise ValueError("lab request fields do not match the frozen schema")
        dose = raw["dose"]
        if isinstance(dose, bool) or not isinstance(dose, (int, float)):
            raise ValueError("dose must be numeric")
        return cls(
            schema_version=str(raw["schema_version"]),
            scenario_id=str(raw["scenario_id"]),
            protocol_id=str(raw["protocol_id"]),
            dose=float(dose),
            onset=str(raw["onset"]),
            exposure=str(raw["exposure"]),
        )

    @property
    def schedule_ticks(self) -> tuple[int, ...]:
        first = 1 if self.onset == "early" else 31
        count = 3 if self.exposure == "short" else 6
        return tuple(first + 5 * index for index in range(count))

    @property
    def condition_id(self) -> str:
        dose = f"{round(self.dose * 100):03d}"
        return f"live_{dose}_{self.onset}_{self.exposure}"

    @property
    def run_id(self) -> str:
        identity = {
            "execution_revision": LAB_EXECUTION_REVISION,
            "request": {
                **asdict(self),
                # Keep cross-language identity stable: JavaScript serializes
                # integer-valued floats without a decimal point.
                "dose": f"{self.dose:.1f}",
            },
        }
        return f"lab-run-{digest_payload(identity)[:16]}"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _terminal_l4(raw: Mapping[str, Any]) -> dict[str, float]:
    return {name: _round4(raw[name]) for name in _L4_FIELDS}


def _display_condition(
    *,
    condition_id: str,
    label: str,
    experiment_id: str,
    history_digest: str,
    outcome: str,
    terminal_observation: Mapping[str, Any],
    ticks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the frozen per-condition display shape shared by both sources."""
    return {
        "condition_id": condition_id,
        "label": label,
        "experiment_id": experiment_id,
        "history_digest": history_digest,
        "outcome": outcome,
        "terminal_l4": _terminal_l4(terminal_observation),
        "ticks": ticks,
    }


def _condition_from_run(
    run: MultirateRun,
    *,
    condition_id: str,
    label: str,
) -> dict[str, Any]:
    return _condition_with_collective_response(
        _display_condition(
            condition_id=condition_id,
            label=label,
            experiment_id=run.manifest.experiment_id,
            history_digest=run.history_digest,
            outcome=run.phenotype_window.outcome.value,
            terminal_observation=asdict(run.terminal_observation),
            ticks=_condition_ticks(run),
        )
    )


def _condition_with_collective_response(
    condition: Mapping[str, Any],
) -> dict[str, Any]:
    """Copy a display condition and append the frozen per-Cell proxy."""

    result = dict(condition)
    ticks: list[dict[str, Any]] = []
    for raw_tick in condition["ticks"]:
        tick = dict(raw_tick)
        tick["cells"] = {
            str(cell_id): {
                **dict(cell),
                "collective_response": collective_response(
                    cell["activation"], cell["stress_load"]
                ),
            }
            for cell_id, cell in raw_tick["cells"].items()
        }
        ticks.append(tick)
    result["ticks"] = ticks
    return result


def _analysis_with_collective_dynamics(
    analysis: Mapping[str, Any],
    *,
    conditions: Sequence[Mapping[str, Any]],
    roles: Mapping[str, str],
    reference_condition: str,
    default_cohort: str,
) -> dict[str, Any]:
    if "collective_dynamics" in analysis:
        raise ValueError("lab analysis must not predeclare collective dynamics")
    config = CollectiveDynamicsConfig()
    reports = {
        str(condition["condition_id"]): analyze_collective_dynamics_lab_condition(
            condition, roles, config
        )
        for condition in conditions
    }
    if reference_condition not in reports:
        raise ValueError("collective dynamics reference condition is unknown")
    reference = reports[reference_condition]
    payload = dict(analysis)
    payload["collective_dynamics"] = {
        "schema_version": COLLECTIVE_DYNAMICS_SCHEMA,
        "observer_version": COLLECTIVE_OBSERVER_VERSION,
        "config_digest": config.config_digest,
        "default_cohort": default_cohort,
        "scientific_boundary": (
            "activation-stress 群体状态是 reference proxy；"
            "不是物理相变、真实生物机制或临床预测。"
        ),
        "conditions": {
            condition_id: report.as_dict()
            for condition_id, report in reports.items()
        },
        "comparisons": {
            condition_id: compare_collective_dynamics(reference, report).as_dict()
            for condition_id, report in reports.items()
            if condition_id != reference_condition
        },
    }
    return payload


def _comparison_payload(
    baseline: MultirateRun,
    comparison: MultirateRun,
    *,
    condition_id: str,
) -> dict[str, Any]:
    left = CausalRunRecord(
        condition_id="baseline",
        condition_kind=ConditionKind.BASELINE,
        seed=42,
        run=baseline,
    )
    right = CausalRunRecord(
        condition_id=condition_id,
        condition_kind=ConditionKind.PERTURBATION,
        seed=42,
        run=comparison,
    )
    return json.loads(canonical_json(_compare_runs(left, right)))


def _finish_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    if "bundle_digest" in payload:
        raise ValueError("bundle payload must not predeclare its digest")
    finished = dict(payload)
    finished["bundle_digest"] = digest_payload(payload)
    return finished


def verify_lab_bundle(raw: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "schema_version",
        "bundle_id",
        "kind",
        "title",
        "description",
        "model_status",
        "boundary_note",
        "target_status",
        "seed",
        "roles",
        "layout",
        "reference_condition",
        "default_comparison_condition",
        "conditions",
        "analysis",
        "evidence",
        "config_summary",
        "bundle_digest",
    }
    if not isinstance(raw, Mapping) or set(raw) != expected:
        raise ValueError("lab bundle fields do not match its schema")
    if raw["schema_version"] != LAB_BUNDLE_SCHEMA:
        raise ValueError("unsupported lab bundle schema")
    conditions = raw["conditions"]
    if not isinstance(conditions, list) or len(conditions) < 2:
        raise ValueError("lab bundle must contain paired conditions")
    ids = [item.get("condition_id") for item in conditions if isinstance(item, dict)]
    if len(ids) != len(conditions) or len(ids) != len(set(ids)):
        raise ValueError("lab bundle condition ids must be unique")
    if raw["reference_condition"] not in ids or raw["default_comparison_condition"] not in ids:
        raise ValueError("lab bundle references an unknown condition")
    payload = {key: value for key, value in raw.items() if key != "bundle_digest"}
    if raw["bundle_digest"] != digest_payload(payload):
        raise ValueError("lab bundle digest mismatch")
    return dict(raw)


def run_lab_experiment(
    request: LabExperimentRequest,
    *,
    project_root: str | Path,
) -> dict[str, Any]:
    """Run one frozen baseline/intervention pair for the public lab API."""

    if not isinstance(request, LabExperimentRequest):
        raise TypeError("run_lab_experiment requires a validated request")
    root = Path(project_root).resolve()
    scenario_path = root / "configs/scenarios/carm/high_immune_her2.json"
    compiled = compile_carm_scenario(load_carm_scenario_config(scenario_path))
    runner = build_carm_intervention_runner(
        compiled,
        runner_config=load_runner_config(root / "configs/runner_reference.json"),
        l0_config=root / "configs/layers/l0_reference_grn.json",
        l1_config=root / "configs/layers/l1_reference_molecular.json",
        l4_config=root / "configs/layers/l4_reference_phenotype.json",
    )
    scenario = replace(compiled.scenario, seed=42)
    baseline = runner.run(scenario, ticks=60)
    targets = tuple(
        cell_id
        for cell_id, role in compiled.roles
        if role is CellRole.ENGINEERED_MACROPHAGE
    )
    schedule = {
        tick: {
            target: {"signal_expression": request.dose}
            for target in targets
        }
        for tick in request.schedule_ticks
    }
    intervention = runner.run(
        scenario,
        ticks=60,
        perturbation_schedule=schedule,
    )
    observed_ticks = tuple(
        tick.logical_time for tick in intervention.ticks if tick.l0_perturbation_events
    )
    if observed_ticks != request.schedule_ticks:
        raise RuntimeError("public lab intervention schedule drifted")
    role_map = {cell_id: role.value for cell_id, role in compiled.roles}
    conditions = [
        _condition_from_run(baseline, condition_id="baseline", label="Baseline"),
        _condition_from_run(
            intervention,
            condition_id=request.condition_id,
            label=f"{request.onset.title()} · {request.exposure.title()} · {request.dose:.1f}",
        ),
    ]
    analysis = _analysis_with_collective_dynamics(
        _comparison_payload(
            baseline,
            intervention,
            condition_id=request.condition_id,
        ),
        conditions=conditions,
        roles=role_map,
        reference_condition="baseline",
        default_cohort="engineered_macrophage",
    )
    bundle = _finish_bundle(
        {
            "schema_version": LAB_BUNDLE_SCHEMA,
            "bundle_id": request.run_id,
            "kind": "live_state_intervention",
            "title": "CAR-M 在线状态条件干预",
            "description": "同一 L0 clamp 在冻结状态窗口内与 baseline 做单 seed 配对。",
            "model_status": "reference-model paired run; not a clinical predictor",
            "boundary_note": BOUNDARY_NOTE,
            "target_status": "真实数据 Target 已于 2026-08-28 生成（spatial-anchor-29c87ba1411d4fc8）；首次评估未锚定，ADR-0043 calibration 确认 improved。",
            "seed": 42,
            "roles": role_map,
            "layout": _build_layout(role_map),
            "reference_condition": "baseline",
            "default_comparison_condition": request.condition_id,
            "conditions": conditions,
            "analysis": analysis,
            "evidence": {
                "execution_revision": LAB_EXECUTION_REVISION,
                "runner_model_versions": dict(runner.model_versions),
                "baseline_history_digest": baseline.history_digest,
                "comparison_history_digest": intervention.history_digest,
            },
            "config_summary": {
                "request": request.as_dict(),
                "schedule_ticks": list(request.schedule_ticks),
                "target_role": "engineered_macrophage",
                "target_count": len(targets),
                "gene": "signal_expression",
                "ticks": 60,
            },
        }
    )
    return verify_lab_bundle(bundle)


def _raw_tick_to_display(raw: Mapping[str, Any]) -> dict[str, Any]:
    l0 = {str(item["cell_id"]): item for item in raw["l0"]}
    l1 = {str(item["cell_id"]): item for item in raw["l1"]}
    l2 = {str(item["cell_id"]): item for item in raw["l2"]}
    nodes = {str(item["cell_id"]): item for item in raw["l3"]["nodes"]}
    cell_ids = sorted(l0)
    if not (set(cell_ids) == set(l1) == set(l2) == set(nodes)):
        raise ValueError("raw lab tick has misaligned Cell ids")
    cells: dict[str, Any] = {}
    for cell_id in cell_ids:
        cell = l2[cell_id]
        node = nodes[cell_id]
        cells[cell_id] = {
            "phase": str(cell["phase"]),
            "viability": _round4(cell["viability"]),
            "activation": _round4(cell["activation"]),
            "stress_load": _round4(cell["stress_load"]),
            "collective_response": collective_response(
                cell["activation"], cell["stress_load"]
            ),
            "l0": {name: _round4(l0[cell_id][name]) for name in _L0_FIELDS},
            "l1": {name: _round4(l1[cell_id][name]) for name in _L1_FIELDS},
            "node": {
                "resource_level": _round4(node["resource_level"]),
                "signal": _round4(node["signal"]),
                "stress": _round4(node["stress"]),
            },
        }
    l3 = raw["l3"]
    result: dict[str, Any] = {
        "t": int(raw["logical_time"]),
        "l0_updated": bool(raw["l0_updated"]),
        "l4_observed": bool(raw["l4_observed"]),
        "audit": {
            "transition_count": len(raw["transitions"]),
            "l0_perturbation_count": len(raw["l0_perturbation_events"]),
            "layer_paths": [
                f"{item['source_layer']}->{item['target_layer']}"
                for item in raw["transitions"]
            ],
        },
        "cells": cells,
        "l3": {name: _round4(l3[name]) for name in _L3_FIELDS},
        "l4": None if raw["l4"] is None else _terminal_l4(raw["l4"]),
        "edges": [[str(source), str(target)] for source, target in l3["edges"]],
    }
    if "coordinates" in l3:
        result["coordinates"] = {
            str(item["cell_id"]): [_round4(item["x"]), _round4(item["y"])]
            for item in l3["coordinates"]
        }
        result["field"] = {
            "rows": int(l3["field_rows"]),
            "columns": int(l3["field_columns"]),
            "cells": [
                [
                    int(item["row"]),
                    int(item["column"]),
                    _round4(item["stress"]),
                    _round4(item["resource_level"]),
                    _round4(item["signal"]),
                ]
                for item in l3["field_cells"]
            ],
        }
    return result


def _condition_from_raw(
    raw: Mapping[str, Any],
    *,
    condition_id: str,
    label: str,
) -> dict[str, Any]:
    experiment = raw["experiment"]
    return _display_condition(
        condition_id=condition_id,
        label=label,
        experiment_id=str(experiment["experiment_id"]),
        history_digest=str(raw["history_digest"]),
        outcome=str(raw["phenotype_window"]["outcome"]),
        terminal_observation=raw["terminal_observation"],
        ticks=[_raw_tick_to_display(tick) for tick in raw["ticks"]],
    )


def _roles_from_condition(condition: Mapping[str, Any]) -> dict[str, str]:
    ticks = condition["ticks"]
    if not isinstance(ticks, list) or not ticks:
        raise ValueError("lab condition must contain ticks")
    return {cell_id: _role_for_cell(cell_id) for cell_id in ticks[0]["cells"]}


def _bundle_from_playbook(playbook: Mapping[str, Any]) -> dict[str, Any]:
    # Playbook-era display ticks predate per-tick edges; the CAR-M graph is
    # static, so the root edge list applies to every tick. Newer playbooks
    # that already carry per-tick edges keep them.
    edges = [[str(source), str(target)] for source, target in playbook["edges"]]
    conditions = []
    for item in playbook["conditions"]:
        condition = dict(item)
        condition["label"] = {
            "baseline": "Baseline",
            "car_off_000": "CAR off · 0.0",
            "car_affinity_070": "CAR affinity · 0.7",
            "car_max_100": "CAR max · 1.0",
        }.get(condition["condition_id"], condition["condition_id"])
        condition["ticks"] = [
            dict(tick, edges=tick.get("edges", edges))
            for tick in condition["ticks"]
        ]
        conditions.append(_condition_with_collective_response(condition))
    baseline = conditions[0]["terminal_l4"]
    analysis = _analysis_with_collective_dynamics(
        {
            "terminal_deltas": {
                item["condition_id"]: {
                    name: _round4(item["terminal_l4"][name] - baseline[name])
                    for name in _L4_FIELDS
                }
                for item in conditions[1:]
            }
        },
        conditions=conditions,
        roles=playbook["roles"],
        reference_condition="baseline",
        default_cohort="engineered_macrophage",
    )
    return verify_lab_bundle(_finish_bundle(
        {
            "schema_version": LAB_BUNDLE_SCHEMA,
            "bundle_id": "dose-response",
            "kind": "dose_response",
            "title": "CAR 信号剂量对照",
            "description": "0.0 / 0.7 / 1.0 L0 signal_expression 与 baseline 的冻结配对回放。",
            "model_status": "CAR-M reference-model dose comparison",
            "boundary_note": str(playbook["boundary_note"]),
            "target_status": "真实数据 Target 已于 2026-08-28 生成（spatial-anchor-29c87ba1411d4fc8）；首次评估未锚定，ADR-0043 calibration 确认 improved。",
            "seed": int(playbook["seed"]),
            "roles": dict(playbook["roles"]),
            "layout": dict(playbook["layout"]),
            "reference_condition": "baseline",
            "default_comparison_condition": "car_affinity_070",
            "conditions": conditions,
            "analysis": analysis,
            "evidence": {
                "source_schema": str(playbook["schema_version"]),
                "source_digest": str(playbook["playbook_digest"]),
            },
            "config_summary": {
                "ticks": len(conditions[0]["ticks"]),
                "condition_count": len(conditions),
                "field_semantics": playbook.get("observer", {}).get(
                    "spatial_semantics", "display_projection_only"
                ),
            },
        }
    ))


def _bundle_from_raw_set(
    *,
    bundle_id: str,
    kind: str,
    title: str,
    description: str,
    raw_conditions: Sequence[tuple[str, str, Mapping[str, Any]]],
    default_comparison: str,
    analysis: Mapping[str, Any],
    config_summary: Mapping[str, Any],
) -> dict[str, Any]:
    conditions = [
        _condition_from_raw(raw, condition_id=condition_id, label=label)
        for condition_id, label, raw in raw_conditions
    ]
    roles = _roles_from_condition(conditions[0])
    default_cohort = "all_cells" if kind == "spatial_l3" else "engineered_macrophage"
    complete_analysis = _analysis_with_collective_dynamics(
        analysis,
        conditions=conditions,
        roles=roles,
        reference_condition=raw_conditions[0][0],
        default_cohort=default_cohort,
    )
    layout = _build_layout(roles)
    spatial = next(
        (
            condition
            for condition in conditions
            if "coordinates" in condition["ticks"][0]
        ),
        None,
    )
    if spatial is not None:
        layout = dict(spatial["ticks"][0]["coordinates"])
    evidence = {
        "source_experiment_ids": [item["experiment_id"] for item in conditions],
        "source_history_digests": [item["history_digest"] for item in conditions],
    }
    bundle = _finish_bundle(
        {
            "schema_version": LAB_BUNDLE_SCHEMA,
            "bundle_id": bundle_id,
            "kind": kind,
            "title": title,
            "description": description,
            "model_status": "reference-model precomputed experiment; not a clinical predictor",
            "boundary_note": BOUNDARY_NOTE,
            "target_status": "真实数据 Target 已生成并评估（ADR-0026/0027/0043）；邻域与场指标距离见证据页。",
            "seed": 42,
            "roles": roles,
            "layout": layout,
            "reference_condition": raw_conditions[0][0],
            "default_comparison_condition": default_comparison,
            "conditions": conditions,
            "analysis": complete_analysis,
            "evidence": evidence,
            "config_summary": dict(config_summary),
        }
    )
    return verify_lab_bundle(bundle)


def _seed_42_analysis(summary: Mapping[str, Any]) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for key in ("comparisons", "context_audits", "timing_contrasts"):
        value = summary.get(key)
        if isinstance(value, list):
            selected[key] = [
                item for item in value if isinstance(item, dict) and item.get("seed") == 42
            ]
    for key in ("spatial_metric_records", "paired_comparisons"):
        value = summary.get(key)
        if isinstance(value, list):
            selected[key] = [
                item for item in value if not isinstance(item, dict) or item.get("seed", 42) == 42
            ]
    return selected


def write_lab_bundle_set(
    output_dir: str | Path,
    bundles: Sequence[Mapping[str, Any]],
) -> dict[str, Path]:
    """Write a deterministic catalog, bundle set, and file manifest."""

    if len(bundles) < 1:
        raise ValueError("lab bundle set must not be empty")
    verified = tuple(verify_lab_bundle(bundle) for bundle in bundles)
    bundle_ids = [str(bundle["bundle_id"]) for bundle in verified]
    if len(bundle_ids) != len(set(bundle_ids)):
        raise ValueError("lab bundle ids must be unique")
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    file_digests: dict[str, str] = {}
    for bundle in verified:
        name = f"{bundle['bundle_id']}.json"
        path = output / name
        content = _compact_json(bundle)
        path.write_bytes(content)
        paths[str(bundle["bundle_id"])] = path
        file_digests[name] = _sha256_bytes(content)

    catalog = {
        "schema_version": LAB_CATALOG_SCHEMA,
        "title": "M-GBA 跨尺度虚拟实验室",
        "live_request_schema": LAB_REQUEST_SCHEMA,
        "live_execution_revision": LAB_EXECUTION_REVISION,
        "target_status": "真实数据 Target 已生成（2026-08-28）；首次评估未锚定 → calibration improved（ADR-0043）",
        "experiments": [
            {
                "bundle_id": bundle["bundle_id"],
                "kind": bundle["kind"],
                "title": bundle["title"],
                "description": bundle["description"],
                "path": f"/lab-data/{bundle['bundle_id']}.json",
                "ticks": len(bundle["conditions"][0]["ticks"]),
                "cell_count": len(bundle["roles"]),
                "condition_count": len(bundle["conditions"]),
                "default_comparison_condition": bundle["default_comparison_condition"],
                "bundle_digest": bundle["bundle_digest"],
            }
            for bundle in verified
        ],
    }
    catalog["catalog_digest"] = digest_payload(catalog)
    catalog_content = _compact_json(catalog)
    catalog_path = output / "catalog.json"
    catalog_path.write_bytes(catalog_content)
    paths["catalog"] = catalog_path
    file_digests["catalog.json"] = _sha256_bytes(catalog_content)

    manifest = {
        "schema_version": LAB_FILES_SCHEMA,
        "catalog_digest": catalog["catalog_digest"],
        "files": dict(sorted(file_digests.items())),
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_bytes(_compact_json(manifest))
    paths["manifest"] = manifest_path
    return paths


def export_competition_lab_data(
    *,
    output_dir: str | Path,
    dose_playbook: str | Path,
    intervention_root: str | Path,
    spatial_root: str | Path,
) -> dict[str, Path]:
    """Build three deterministic, lazy-loadable competition bundles."""

    dose = verify_lab_bundle(_bundle_from_playbook(_load_json_object(dose_playbook)))

    intervention_path = Path(intervention_root)
    intervention_summary = _load_json_object(intervention_path / "derived/summary.json")
    intervention_specs = (
        ("baseline", "Baseline"),
        ("early_short", "Early · Short"),
        ("late_short", "Late · Short"),
        ("early_long", "Early · Long"),
        ("late_long", "Late · Long"),
    )
    intervention = _bundle_from_raw_set(
        bundle_id="state-intervention",
        kind="state_intervention",
        title="状态条件序列干预",
        description="相同 L0 clamp 的 early/late 与 short/long 时序对照。",
        raw_conditions=[
            (
                condition_id,
                label,
                _load_json_object(
                    intervention_path / "raw" / f"{condition_id}-seed-42.json"
                ),
            )
            for condition_id, label in intervention_specs
        ],
        default_comparison="late_long",
        analysis=_seed_42_analysis(intervention_summary),
        config_summary={
            "protocol": intervention_summary.get("config", {}),
            "source_experiment_id": intervention_summary.get("experiment_id"),
        },
    )

    spatial_path = Path(spatial_root)
    spatial_summary = _load_json_object(spatial_path / "derived/summary.json")
    spatial = _bundle_from_raw_set(
        bundle_id="spatial-l3",
        kind="spatial_l3",
        title="固定图与空间 L3 对照",
        description="只替换 L3，比较固定图与因果空间场的配对轨迹。",
        raw_conditions=[
            (
                "fixed_graph",
                "Fixed graph L3",
                _load_json_object(spatial_path / "raw/fixed_graph/seed-42.json"),
            ),
            (
                "spatial_field",
                "Spatial field L3",
                _load_json_object(spatial_path / "raw/spatial_field/seed-42.json"),
            ),
        ],
        default_comparison="spatial_field",
        analysis=_seed_42_analysis(spatial_summary),
        config_summary={
            "source_experiment_id": spatial_summary.get("experiment_id"),
            "condition_count": spatial_summary.get("condition_count"),
            "run_count": spatial_summary.get("run_count"),
        },
    )

    return write_lab_bundle_set(output_dir, (dose, intervention, spatial))
