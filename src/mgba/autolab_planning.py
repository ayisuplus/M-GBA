"""Deterministic, non-executing Autolab planning control plane.

This module is an OCellus-inspired Planner--Router--Verifier boundary for
M-GBA's existing :mod:`mgba.autolab` meta-layer.  It deliberately does not
execute experiments: a plan can only name tools from the frozen inventory,
and all experiment execution remains behind the existing injected evaluator.

The verifier is fail-closed in three stages:

1. closed JSON schema plus dependency-complete, acyclic DAG;
2. registry, architecture, paired-baseline, seed, and budget policy;
3. completed-session manifest/history anchors and scientific claim boundary.

Nothing in this module imports ``mgba.runner`` or enters the L0--L4 tick loop.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .autolab import AutolabConfig, AutolabSessionResult, HypothesisEvaluation
from .experiment import write_json_once
from .hashing import digest_payload


PLAN_SCHEMA_VERSION = "mgba-autolab-plan-0.1"
VERIFICATION_SCHEMA_VERSION = "mgba-autolab-plan-verification-0.1"
PLAN_STRATEGY = "screen_then_confirm"
REFERENCE_CLAIM_LEVEL = "reference_model"

_PLAN_PREFIX = "autolab-plan-"
_REPORT_PREFIX = "autolab-plan-verification-"
_HEX = frozenset("0123456789abcdef")
_PHASES = ("probe", "select", "confirm", "verify")
_LAYERS = ("L0", "L1", "L2", "L3", "L4")
_STAGES = ("schema_dag", "architecture_policy", "post_result")
_STATUSES = ("passed", "failed", "not_run", "not_requested")

PAIRED_SWAP_TOOL = "evaluate_paired_layer_static_swap"
SELECT_TOOL = "select_top_probe_effects"
VERIFY_TOOL = "verify_manifest_history"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One immutable tool contract exposed to a plan author."""

    name: str
    phases: tuple[str, ...]
    hypothesis_kind: str | None
    allowed_layers: tuple[str, ...]
    evaluator_call: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "phases": list(self.phases),
            "hypothesis_kind": self.hypothesis_kind,
            "allowed_layers": list(self.allowed_layers),
            "evaluator_call": self.evaluator_call,
        }


# Tuple rather than a mutable mapping: callers can inspect but cannot extend the
# inventory in-place.  Its order is part of the public, digested contract.
FIXED_TOOL_INVENTORY: tuple[ToolSpec, ...] = (
    ToolSpec(
        name=PAIRED_SWAP_TOOL,
        phases=("probe", "confirm"),
        hypothesis_kind="layer_static_swap",
        allowed_layers=("L1", "L2", "L3"),
        evaluator_call=True,
    ),
    ToolSpec(
        name=SELECT_TOOL,
        phases=("select",),
        hypothesis_kind=None,
        allowed_layers=(),
        evaluator_call=False,
    ),
    ToolSpec(
        name=VERIFY_TOOL,
        phases=("verify",),
        hypothesis_kind=None,
        allowed_layers=(),
        evaluator_call=False,
    ),
)
_TOOLS = {item.name: item for item in FIXED_TOOL_INVENTORY}
TOOL_INVENTORY_DIGEST = digest_payload(
    [item.as_dict() for item in FIXED_TOOL_INVENTORY]
)


def _is_plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _is_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in _HEX for character in value)
    )


def _clean_id(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty trimmed string")
    if any(character.isspace() for character in value):
        raise ValueError(f"{name} must not contain whitespace")
    return value


def _require_exact_keys(
    raw: Mapping[str, Any], expected: set[str], *, name: str
) -> None:
    actual = set(raw)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing {missing}")
        if unknown:
            details.append(f"unknown {unknown}")
        raise ValueError(f"{name} has a non-closed schema: {'; '.join(details)}")


@dataclass(frozen=True, slots=True)
class PlanStep:
    """One node in the closed Autolab plan DAG.

    Confirm steps refer to a deterministic one-based ``selected_rank`` rather
    than guessing the winning hypothesis before probe evidence exists.
    """

    step_id: str
    phase: str
    tool: str
    hypothesis_id: str | None
    selected_rank: int | None
    layer: str | None
    ticks: int
    seeds: tuple[int, ...]
    paired_baseline: bool
    depends_on: tuple[str, ...]

    _JSON_KEYS = frozenset(
        {
            "step_id",
            "phase",
            "tool",
            "hypothesis_id",
            "selected_rank",
            "layer",
            "ticks",
            "seeds",
            "paired_baseline",
            "depends_on",
        }
    )

    def __post_init__(self) -> None:
        _clean_id(self.step_id, name="step_id")
        if self.phase not in _PHASES:
            raise ValueError(f"phase must be one of {_PHASES}")
        _clean_id(self.tool, name="tool")
        if self.hypothesis_id is not None:
            _clean_id(self.hypothesis_id, name="hypothesis_id")
        if self.selected_rank is not None and (
            not _is_plain_int(self.selected_rank) or self.selected_rank < 1
        ):
            raise ValueError("selected_rank must be null or a positive integer")
        if self.layer is not None and self.layer not in _LAYERS:
            raise ValueError(f"layer must be null or one of {_LAYERS}")
        if not _is_plain_int(self.ticks) or self.ticks < 0:
            raise ValueError("ticks must be a non-negative integer")
        if not isinstance(self.seeds, tuple):
            raise ValueError("seeds must be a tuple")
        if any(not _is_plain_int(seed) or seed < 0 for seed in self.seeds):
            raise ValueError("seeds must contain non-negative integers")
        if self.seeds != tuple(sorted(set(self.seeds))):
            raise ValueError("seeds must be unique and sorted")
        if not isinstance(self.paired_baseline, bool):
            raise ValueError("paired_baseline must be a boolean")
        if not isinstance(self.depends_on, tuple) or any(
            not isinstance(item, str) for item in self.depends_on
        ):
            raise ValueError("depends_on must be a tuple of strings")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("depends_on must not contain duplicates")
        if self.step_id in self.depends_on:
            raise ValueError("a step cannot depend on itself")

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "phase": self.phase,
            "tool": self.tool,
            "hypothesis_id": self.hypothesis_id,
            "selected_rank": self.selected_rank,
            "layer": self.layer,
            "ticks": self.ticks,
            "seeds": list(self.seeds),
            "paired_baseline": self.paired_baseline,
            "depends_on": list(self.depends_on),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PlanStep:
        if not isinstance(raw, Mapping):
            raise ValueError("plan step must be a JSON object")
        _require_exact_keys(raw, set(cls._JSON_KEYS), name="plan step")
        if not isinstance(raw["seeds"], list):
            raise ValueError("plan step seeds must be a JSON array")
        if not isinstance(raw["depends_on"], list):
            raise ValueError("plan step depends_on must be a JSON array")
        return cls(
            step_id=raw["step_id"],
            phase=raw["phase"],
            tool=raw["tool"],
            hypothesis_id=raw["hypothesis_id"],
            selected_rank=raw["selected_rank"],
            layer=raw["layer"],
            ticks=raw["ticks"],
            seeds=tuple(raw["seeds"]),
            paired_baseline=raw["paired_baseline"],
            depends_on=tuple(raw["depends_on"]),
        )


def _registry_payload(config: AutolabConfig) -> list[dict[str, Any]]:
    return [
        {
            "hypothesis_id": item.hypothesis_id,
            "kind": item.kind,
            "layer": item.layer,
            "priority": item.priority,
        }
        for item in config.hypotheses
    ]


def registry_digest(config: AutolabConfig) -> str:
    """Digest the full registry, including layer, kind, and priority."""
    if not isinstance(config, AutolabConfig):
        raise TypeError("registry_digest requires an AutolabConfig")
    return digest_payload(_registry_payload(config))


@dataclass(frozen=True, slots=True)
class AutolabPlan:
    """Closed, deterministic plan; it is never an execution record."""

    strategy: str
    model_version: str
    seeds: tuple[int, ...]
    budget: int
    registry_digest: str
    tool_inventory_digest: str
    claim_level: str
    executed: bool
    pending_hypotheses: tuple[str, ...]
    steps: tuple[PlanStep, ...]

    _JSON_KEYS = frozenset(
        {
            "schema_version",
            "plan_id",
            "strategy",
            "model_version",
            "seeds",
            "budget",
            "registry_digest",
            "tool_inventory_digest",
            "claim_level",
            "executed",
            "pending_hypotheses",
            "steps",
        }
    )

    def __post_init__(self) -> None:
        if self.strategy != PLAN_STRATEGY:
            raise ValueError(f"strategy must be {PLAN_STRATEGY!r}")
        if not isinstance(self.model_version, str) or not self.model_version.strip():
            raise ValueError("model_version must be a non-empty string")
        if not isinstance(self.seeds, tuple) or len(self.seeds) < 2:
            raise ValueError("plan requires at least two seeds")
        if any(not _is_plain_int(seed) or seed < 0 for seed in self.seeds):
            raise ValueError("plan seeds must be non-negative integers")
        if self.seeds != tuple(sorted(set(self.seeds))):
            raise ValueError("plan seeds must be unique and sorted")
        if not _is_plain_int(self.budget) or self.budget < 1:
            raise ValueError("budget must be a positive integer")
        if not _is_digest(self.registry_digest):
            raise ValueError("registry_digest must be a lowercase SHA-256 digest")
        if not _is_digest(self.tool_inventory_digest):
            raise ValueError(
                "tool_inventory_digest must be a lowercase SHA-256 digest"
            )
        if self.claim_level != REFERENCE_CLAIM_LEVEL:
            raise ValueError("claim_level must be reference_model")
        if self.executed is not False:
            raise ValueError("an AutolabPlan must have executed=false")
        if not isinstance(self.pending_hypotheses, tuple) or any(
            not isinstance(item, str) for item in self.pending_hypotheses
        ):
            raise ValueError("pending_hypotheses must be a tuple of strings")
        if len(set(self.pending_hypotheses)) != len(self.pending_hypotheses):
            raise ValueError("pending_hypotheses must not contain duplicates")
        if not isinstance(self.steps, tuple) or not self.steps:
            raise ValueError("plan must contain steps")
        if any(not isinstance(item, PlanStep) for item in self.steps):
            raise ValueError("steps must contain PlanStep values")

    def _identity_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PLAN_SCHEMA_VERSION,
            "strategy": self.strategy,
            "model_version": self.model_version,
            "seeds": list(self.seeds),
            "budget": self.budget,
            "registry_digest": self.registry_digest,
            "tool_inventory_digest": self.tool_inventory_digest,
            "claim_level": self.claim_level,
            "executed": self.executed,
            "pending_hypotheses": list(self.pending_hypotheses),
            "steps": [item.as_dict() for item in self.steps],
        }

    @property
    def plan_id(self) -> str:
        return f"{_PLAN_PREFIX}{digest_payload(self._identity_dict())[:16]}"

    def as_dict(self) -> dict[str, Any]:
        return {"plan_id": self.plan_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> AutolabPlan:
        if not isinstance(raw, Mapping):
            raise ValueError("Autolab plan must be a JSON object")
        _require_exact_keys(raw, set(cls._JSON_KEYS), name="Autolab plan")
        if raw["schema_version"] != PLAN_SCHEMA_VERSION:
            raise ValueError("unsupported Autolab plan schema_version")
        if not isinstance(raw["seeds"], list):
            raise ValueError("plan seeds must be a JSON array")
        if not isinstance(raw["pending_hypotheses"], list):
            raise ValueError("pending_hypotheses must be a JSON array")
        if not isinstance(raw["steps"], list):
            raise ValueError("steps must be a JSON array")
        plan = cls(
            strategy=raw["strategy"],
            model_version=raw["model_version"],
            seeds=tuple(raw["seeds"]),
            budget=raw["budget"],
            registry_digest=raw["registry_digest"],
            tool_inventory_digest=raw["tool_inventory_digest"],
            claim_level=raw["claim_level"],
            executed=raw["executed"],
            pending_hypotheses=tuple(raw["pending_hypotheses"]),
            steps=tuple(PlanStep.from_dict(item) for item in raw["steps"]),
        )
        if raw["plan_id"] != plan.plan_id:
            raise ValueError("plan_id does not match the plan content")
        return plan


def compile_autolab_plan(config: AutolabConfig) -> AutolabPlan:
    """Compile the frozen registry/protocol into a budget-respecting DAG.

    Probe nodes follow ``AutolabConfig.screening_order``.  Confirm nodes are
    rank slots chosen only after probe evidence; the plan never predicts a
    winner.  Meta nodes do not consume experiment budget.
    """
    if not isinstance(config, AutolabConfig):
        raise TypeError("compile_autolab_plan requires an AutolabConfig")

    ordered = config.screening_order
    probe_count = min(len(ordered), config.budget)
    probed = ordered[:probe_count]
    steps: list[PlanStep] = []
    previous_probe: str | None = None
    probe_ids: list[str] = []
    for index, hypothesis in enumerate(probed, start=1):
        step_id = f"probe-{index:03d}-{hypothesis.hypothesis_id}"
        steps.append(
            PlanStep(
                step_id=step_id,
                phase="probe",
                tool=PAIRED_SWAP_TOOL,
                hypothesis_id=hypothesis.hypothesis_id,
                selected_rank=None,
                layer=hypothesis.layer,
                ticks=config.probe_ticks,
                seeds=config.seeds,
                paired_baseline=True,
                depends_on=(() if previous_probe is None else (previous_probe,)),
            )
        )
        probe_ids.append(step_id)
        previous_probe = step_id

    select_id = "select-confirm-candidates"
    steps.append(
        PlanStep(
            step_id=select_id,
            phase="select",
            tool=SELECT_TOOL,
            hypothesis_id=None,
            selected_rank=None,
            layer=None,
            ticks=0,
            seeds=(),
            paired_baseline=False,
            depends_on=tuple(probe_ids),
        )
    )

    remaining = max(0, config.budget - probe_count)
    confirm_count = min(config.confirm_top_k, probe_count, remaining)
    previous_confirm = select_id
    confirm_ids: list[str] = []
    for rank in range(1, confirm_count + 1):
        step_id = f"confirm-rank-{rank:03d}"
        steps.append(
            PlanStep(
                step_id=step_id,
                phase="confirm",
                tool=PAIRED_SWAP_TOOL,
                hypothesis_id=None,
                selected_rank=rank,
                layer=None,
                ticks=config.confirm_ticks,
                seeds=config.seeds,
                paired_baseline=True,
                depends_on=(previous_confirm,),
            )
        )
        confirm_ids.append(step_id)
        previous_confirm = step_id

    steps.append(
        PlanStep(
            step_id="verify-session-evidence",
            phase="verify",
            tool=VERIFY_TOOL,
            hypothesis_id=None,
            selected_rank=None,
            layer=None,
            ticks=0,
            seeds=(),
            paired_baseline=False,
            depends_on=(confirm_ids[-1] if confirm_ids else select_id,),
        )
    )
    return AutolabPlan(
        strategy=PLAN_STRATEGY,
        model_version=config.model_version,
        seeds=config.seeds,
        budget=config.budget,
        registry_digest=registry_digest(config),
        tool_inventory_digest=TOOL_INVENTORY_DIGEST,
        claim_level=REFERENCE_CLAIM_LEVEL,
        executed=False,
        pending_hypotheses=tuple(
            item.hypothesis_id for item in ordered[probe_count:]
        ),
        steps=tuple(steps),
    )


@dataclass(frozen=True, slots=True)
class VerificationIssue:
    """One deterministic, machine-readable verification failure."""

    stage: str
    code: str
    message: str
    step_id: str | None = None

    def __post_init__(self) -> None:
        if self.stage not in _STAGES:
            raise ValueError("unknown verification issue stage")
        _clean_id(self.code, name="verification issue code")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("verification issue message must not be empty")

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
        }
        if self.step_id is not None:
            payload["step_id"] = self.step_id
        return payload


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """Three-stage report.  Reporting itself never executes a plan."""

    plan_id: str
    mode: str
    schema_status: str
    architecture_status: str
    result_status: str
    issues: tuple[VerificationIssue, ...]
    evidence_digest: str | None = None
    claim_level: str = REFERENCE_CLAIM_LEVEL
    executed: bool = False

    def __post_init__(self) -> None:
        if self.mode not in ("preflight", "post_result"):
            raise ValueError("verification mode must be preflight or post_result")
        for status in (
            self.schema_status,
            self.architecture_status,
            self.result_status,
        ):
            if status not in _STATUSES:
                raise ValueError("unknown verification status")
        if self.evidence_digest is not None and not _is_digest(
            self.evidence_digest
        ):
            raise ValueError("evidence_digest must be null or SHA-256")
        if self.claim_level != REFERENCE_CLAIM_LEVEL:
            raise ValueError("verification claim_level must be reference_model")
        if self.executed is not False:
            raise ValueError("verification reports must have executed=false")

    @property
    def valid(self) -> bool:
        return (
            self.schema_status == "passed"
            and self.architecture_status == "passed"
            and self.result_status != "failed"
        )

    @property
    def fully_verified(self) -> bool:
        return self.valid and self.result_status == "passed"

    def _identity_dict(self) -> dict[str, Any]:
        return {
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "mode": self.mode,
            "executed": self.executed,
            "claim_level": self.claim_level,
            "verdict": "accepted" if self.valid else "rejected",
            "fully_verified": self.fully_verified,
            "layers": [
                {"layer": "schema_dag", "status": self.schema_status},
                {
                    "layer": "architecture_policy",
                    "status": self.architecture_status,
                },
                {"layer": "post_result", "status": self.result_status},
            ],
            "issues": [item.as_dict() for item in self.issues],
            "evidence_digest": self.evidence_digest,
        }

    @property
    def report_id(self) -> str:
        return f"{_REPORT_PREFIX}{digest_payload(self._identity_dict())[:16]}"

    def summary_dict(self) -> dict[str, Any]:
        return {"report_id": self.report_id, **self._identity_dict()}


def _issue(
    stage: str, code: str, message: str, step_id: str | None = None
) -> VerificationIssue:
    return VerificationIssue(
        stage=stage, code=code, message=message, step_id=step_id
    )


def _dag_issues(plan: AutolabPlan) -> list[VerificationIssue]:
    issues: list[VerificationIssue] = []
    identifiers = [item.step_id for item in plan.steps]
    known = set(identifiers)
    if len(known) != len(identifiers):
        issues.append(
            _issue("schema_dag", "duplicate_step_id", "step ids must be unique")
        )
    for step in plan.steps:
        for dependency in step.depends_on:
            if dependency not in known:
                issues.append(
                    _issue(
                        "schema_dag",
                        "missing_dependency",
                        f"dependency {dependency!r} is not a plan step",
                        step.step_id,
                    )
                )

    # Kahn's algorithm, using plan order as a deterministic tie-breaker.
    dependencies = {
        step.step_id: set(item for item in step.depends_on if item in known)
        for step in plan.steps
    }
    completed: set[str] = set()
    while len(completed) < len(known):
        ready = [
            step_id
            for step_id in identifiers
            if step_id not in completed
            and dependencies.get(step_id, set()) <= completed
        ]
        if not ready:
            issues.append(
                _issue(
                    "schema_dag", "cyclic_dag", "plan dependencies contain a cycle"
                )
            )
            break
        completed.update(ready)
    return issues


def _architecture_issues(
    plan: AutolabPlan, config: AutolabConfig
) -> list[VerificationIssue]:
    issues: list[VerificationIssue] = []
    registry = {item.hypothesis_id: item for item in config.hypotheses}

    root_checks = (
        (plan.model_version == config.model_version, "model_version_mismatch"),
        (plan.seeds == config.seeds, "seed_protocol_mismatch"),
        (plan.budget == config.budget, "budget_protocol_mismatch"),
        (plan.registry_digest == registry_digest(config), "registry_digest_mismatch"),
        (
            plan.tool_inventory_digest == TOOL_INVENTORY_DIGEST,
            "tool_inventory_mismatch",
        ),
        (plan.claim_level == REFERENCE_CLAIM_LEVEL, "claim_level_mismatch"),
        (plan.executed is False, "plan_marked_executed"),
    )
    for passed, code in root_checks:
        if not passed:
            issues.append(
                _issue(
                    "architecture_policy",
                    code,
                    code.replace("_", " "),
                )
            )

    for step in plan.steps:
        spec = _TOOLS.get(step.tool)
        if spec is None:
            issues.append(
                _issue(
                    "architecture_policy",
                    "unknown_tool",
                    f"tool {step.tool!r} is not in the fixed inventory",
                    step.step_id,
                )
            )
            continue
        if step.phase not in spec.phases:
            issues.append(
                _issue(
                    "architecture_policy",
                    "tool_phase_mismatch",
                    f"tool {step.tool!r} cannot serve phase {step.phase!r}",
                    step.step_id,
                )
            )
        if step.phase == "probe":
            hypothesis = registry.get(step.hypothesis_id or "")
            if hypothesis is None:
                issues.append(
                    _issue(
                        "architecture_policy",
                        "unregistered_hypothesis",
                        "probe hypothesis is absent from the frozen registry",
                        step.step_id,
                    )
                )
            else:
                if hypothesis.kind != spec.hypothesis_kind:
                    issues.append(
                        _issue(
                            "architecture_policy",
                            "hypothesis_kind_mismatch",
                            "registered hypothesis kind is not supported by the tool",
                            step.step_id,
                        )
                    )
                if step.layer != hypothesis.layer or step.layer not in spec.allowed_layers:
                    issues.append(
                        _issue(
                            "architecture_policy",
                            "layer_scope_violation",
                            "step must replace exactly its registered L1, L2, or L3 layer",
                            step.step_id,
                        )
                    )
            if step.selected_rank is not None:
                issues.append(
                    _issue(
                        "architecture_policy",
                        "probe_has_selected_rank",
                        "probe steps cannot select a ranked hypothesis",
                        step.step_id,
                    )
                )
        elif step.phase == "confirm":
            if step.hypothesis_id is not None or step.layer is not None:
                issues.append(
                    _issue(
                        "architecture_policy",
                        "confirm_preselected_hypothesis",
                        "confirm must resolve a registered hypothesis by probe rank",
                        step.step_id,
                    )
                )
            if step.selected_rank is None:
                issues.append(
                    _issue(
                        "architecture_policy",
                        "confirm_rank_missing",
                        "confirm requires selected_rank",
                        step.step_id,
                    )
                )
        else:
            if (
                step.hypothesis_id is not None
                or step.selected_rank is not None
                or step.layer is not None
            ):
                issues.append(
                    _issue(
                        "architecture_policy",
                        "meta_step_scope_violation",
                        "meta steps cannot read or replace an L0--L4 layer",
                        step.step_id,
                    )
                )

        if spec.evaluator_call:
            if not step.paired_baseline:
                issues.append(
                    _issue(
                        "architecture_policy",
                        "paired_baseline_missing",
                        "experiment steps require a paired baseline",
                        step.step_id,
                    )
                )
            if step.seeds != config.seeds or len(step.seeds) < 2:
                issues.append(
                    _issue(
                        "architecture_policy",
                        "paired_seeds_missing",
                        "experiment steps require exactly the registered multi-seed set",
                        step.step_id,
                    )
                )
            expected_ticks = (
                config.probe_ticks if step.phase == "probe" else config.confirm_ticks
            )
            if step.ticks != expected_ticks:
                issues.append(
                    _issue(
                        "architecture_policy",
                        "tick_protocol_mismatch",
                        "experiment ticks differ from the frozen protocol",
                        step.step_id,
                    )
                )
        elif step.seeds or step.paired_baseline or step.ticks != 0:
            issues.append(
                _issue(
                    "architecture_policy",
                    "meta_step_executes_experiment",
                    "selection and verification steps must be pure metadata operations",
                    step.step_id,
                )
            )

    expected = compile_autolab_plan(config)
    expected_steps = tuple(item.as_dict() for item in expected.steps)
    actual_steps = tuple(item.as_dict() for item in plan.steps)
    if actual_steps != expected_steps:
        issues.append(
            _issue(
                "architecture_policy",
                "noncanonical_plan",
                "plan steps differ from the deterministic registry compilation",
            )
        )
    if plan.pending_hypotheses != expected.pending_hypotheses:
        issues.append(
            _issue(
                "architecture_policy",
                "pending_registry_mismatch",
                "pending hypotheses differ from budget-constrained screening order",
            )
        )
    calls = sum(
        1 for step in plan.steps if _TOOLS.get(step.tool, None) is not None
        and _TOOLS[step.tool].evaluator_call
    )
    if calls > config.budget:
        issues.append(
            _issue(
                "architecture_policy",
                "budget_exceeded",
                f"plan requests {calls} evaluator calls for budget {config.budget}",
            )
        )
    return issues


def _coerce_plan(raw: AutolabPlan | Mapping[str, Any]) -> AutolabPlan:
    if isinstance(raw, AutolabPlan):
        return raw
    return AutolabPlan.from_dict(raw)


def verify_autolab_plan(
    plan: AutolabPlan | Mapping[str, Any], registry: AutolabConfig
) -> VerificationReport:
    """Run schema/DAG and architecture preflight without executing anything."""
    if not isinstance(registry, AutolabConfig):
        raise TypeError("verify_autolab_plan requires an AutolabConfig registry")
    try:
        parsed = _coerce_plan(plan)
    except (TypeError, ValueError, KeyError) as error:
        issue = _issue("schema_dag", "invalid_schema", str(error))
        return VerificationReport(
            plan_id="unresolved",
            mode="preflight",
            schema_status="failed",
            architecture_status="not_run",
            result_status="not_requested",
            issues=(issue,),
        )
    schema_issues = _dag_issues(parsed)
    if schema_issues:
        return VerificationReport(
            plan_id=parsed.plan_id,
            mode="preflight",
            schema_status="failed",
            architecture_status="not_run",
            result_status="not_requested",
            issues=tuple(schema_issues),
        )
    architecture_issues = _architecture_issues(parsed, registry)
    return VerificationReport(
        plan_id=parsed.plan_id,
        mode="preflight",
        schema_status="passed",
        architecture_status=("failed" if architecture_issues else "passed"),
        result_status="not_requested",
        issues=tuple(architecture_issues),
    )


_RESULT_KEYS = frozenset(
    {
        "schema_version",
        "session_id",
        "config",
        "registry",
        "evaluations",
        "decision_log",
        "confirmed",
        "pending",
        "leader",
    }
)
_RESULT_CONFIG_KEYS = frozenset(
    {
        "model_version",
        "seeds",
        "probe_ticks",
        "confirm_ticks",
        "confirm_top_k",
        "budget",
    }
)
_EVALUATION_KEYS = frozenset(
    {
        "hypothesis_id",
        "phase",
        "ticks",
        "seeds",
        "effect",
        "per_seed_effects",
        "history_digests",
    }
)
_DECISION_KEYS = frozenset(
    {"round", "phase", "hypothesis_id", "rationale", "effect"}
)
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "session_id",
        "model_version",
        "registry_digest",
        "evaluations",
    }
)

_PROHIBITED_CLAIM_FRAGMENTS = (
    "digital life",
    "数字生命",
    "validated emergence",
    "已验证涌现",
    "clinical",
    "临床",
    "therapeutic efficacy",
    "疗效预测",
    "reverse-compile real dna",
    "逆向编译真实 dna",
    "solves gnn oversmoothing",
    "天然免疫 gnn",
    "autonomous scientific discovery",
    "自主科学发现",
)


def _result_mapping(result: AutolabSessionResult | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(result, AutolabSessionResult):
        return result.summary_dict()
    if not isinstance(result, Mapping):
        raise ValueError("result must be an AutolabSessionResult or JSON object")
    return result


def _safe_evidence_digest(payload: Mapping[str, Any]) -> str:
    """Return a stable digest even when rejected evidence is not JSON-safe."""
    try:
        return digest_payload(payload)
    except (TypeError, ValueError):
        return digest_payload(
            {
                "invalid_evidence": True,
                "value_types": {
                    str(key): type(value).__name__ for key, value in payload.items()
                },
            }
        )


def _post_result_issues(
    plan: AutolabPlan,
    config: AutolabConfig,
    result: AutolabSessionResult | Mapping[str, Any],
    manifest: Mapping[str, Any],
    claim_level: str,
    claims: Sequence[str],
) -> tuple[list[VerificationIssue], str]:
    issues: list[VerificationIssue] = []
    try:
        summary = _result_mapping(result)
    except ValueError as error:
        return [
            _issue("post_result", "invalid_result_schema", str(error))
        ], _safe_evidence_digest({"invalid_result": str(error)})

    if claim_level != REFERENCE_CLAIM_LEVEL:
        issues.append(
            _issue(
                "post_result",
                "claim_level_violation",
                "completed plans can only report reference_model claims",
            )
        )
    if (
        isinstance(claims, (str, bytes))
        or not isinstance(claims, Sequence)
        or any(not isinstance(claim, str) for claim in claims)
    ):
        issues.append(
            _issue(
                "post_result",
                "invalid_claims",
                "claims must be a sequence of strings",
            )
        )
        normalized_claims: tuple[str, ...] = ()
    else:
        normalized_claims = tuple(claims)
        for claim in normalized_claims:
            folded = claim.casefold()
            matches = [
                fragment
                for fragment in _PROHIBITED_CLAIM_FRAGMENTS
                if fragment.casefold() in folded
            ]
            if matches:
                issues.append(
                    _issue(
                        "post_result",
                        "prohibited_claim",
                        f"claim contains prohibited fragment {matches[0]!r}",
                    )
                )

    try:
        _require_exact_keys(summary, set(_RESULT_KEYS), name="Autolab result")
        if summary["schema_version"] != "mgba-autolab-artifact-0.1":
            raise ValueError("unsupported Autolab result schema_version")
        result_config = summary["config"]
        if not isinstance(result_config, Mapping):
            raise ValueError("Autolab result config must be an object")
        _require_exact_keys(
            result_config, set(_RESULT_CONFIG_KEYS), name="Autolab result config"
        )
        expected_config = {
            "model_version": config.model_version,
            "seeds": list(config.seeds),
            "probe_ticks": config.probe_ticks,
            "confirm_ticks": config.confirm_ticks,
            "confirm_top_k": config.confirm_top_k,
            "budget": config.budget,
        }
        if dict(result_config) != expected_config:
            issues.append(
                _issue(
                    "post_result",
                    "result_config_mismatch",
                    "session result config differs from the planned protocol",
                )
            )
        if summary["registry"] != _registry_payload(config):
            issues.append(
                _issue(
                    "post_result",
                    "result_registry_mismatch",
                    "session result registry differs from the frozen registry",
                )
            )
        if not isinstance(summary["evaluations"], list):
            raise ValueError("Autolab result evaluations must be an array")
        if not isinstance(summary["decision_log"], list):
            raise ValueError("Autolab result decision_log must be an array")
        if not isinstance(summary["confirmed"], list) or not isinstance(
            summary["pending"], list
        ):
            raise ValueError("confirmed and pending must be arrays")
    except (KeyError, TypeError, ValueError) as error:
        issues.append(
            _issue("post_result", "invalid_result_schema", str(error))
        )
        evidence = _safe_evidence_digest(
            {
                "result": summary,
                "manifest": manifest,
                "claim_level": claim_level,
                "claims": list(normalized_claims),
            }
        )
        return issues, evidence

    probe_steps = [item for item in plan.steps if item.phase == "probe"]
    confirm_steps = [item for item in plan.steps if item.phase == "confirm"]
    evaluations = summary["evaluations"]
    parsed_evaluations: list[HypothesisEvaluation] = []
    probe_effects: list[tuple[str, float]] = []
    histories: list[dict[str, Any]] = []
    actual_order: list[tuple[str, str]] = []

    for index, raw in enumerate(evaluations):
        try:
            if not isinstance(raw, Mapping):
                raise ValueError("evaluation must be an object")
            _require_exact_keys(raw, set(_EVALUATION_KEYS), name="evaluation")
            hypothesis_id = _clean_id(raw["hypothesis_id"], name="hypothesis_id")
            phase = raw["phase"]
            ticks = raw["ticks"]
            seeds = raw["seeds"]
            if phase not in ("probe", "confirm"):
                raise ValueError("evaluation phase must be probe or confirm")
            if not _is_plain_int(ticks) or ticks < 1:
                raise ValueError("evaluation ticks must be a positive integer")
            if not isinstance(seeds, list) or tuple(seeds) != config.seeds:
                raise ValueError("evaluation seeds differ from the plan")
            if not _is_number(raw["effect"]) or float(raw["effect"]) < 0.0:
                raise ValueError("evaluation effect must be finite and non-negative")
            per_seed = raw["per_seed_effects"]
            anchors = raw["history_digests"]
            if not isinstance(per_seed, list) or not isinstance(anchors, list):
                raise ValueError("evaluation evidence fields must be arrays")
            per_seed_pairs: list[tuple[int, float]] = []
            anchor_pairs: list[tuple[int, str]] = []
            for item in per_seed:
                if not isinstance(item, Mapping) or set(item) != {"seed", "effect"}:
                    raise ValueError("per_seed_effect entry has invalid schema")
                if not _is_plain_int(item["seed"]) or not _is_number(item["effect"]):
                    raise ValueError("per_seed_effect entry has invalid values")
                value = float(item["effect"])
                if value < 0.0:
                    raise ValueError("per-seed effect must be non-negative")
                per_seed_pairs.append((item["seed"], value))
            for item in anchors:
                if not isinstance(item, Mapping) or set(item) != {
                    "seed",
                    "history_digest",
                }:
                    raise ValueError("history digest entry has invalid schema")
                if not _is_plain_int(item["seed"]) or not _is_digest(
                    item["history_digest"]
                ):
                    raise ValueError("history digest entry has invalid values")
                anchor_pairs.append((item["seed"], item["history_digest"]))
            if tuple(seed for seed, _ in per_seed_pairs) != config.seeds:
                raise ValueError("per-seed effects do not cover the planned seeds")
            if tuple(seed for seed, _ in anchor_pairs) != config.seeds:
                raise ValueError("history digests do not cover the planned seeds")
            recomputed_effect = sum(value for _, value in per_seed_pairs) / len(
                per_seed_pairs
            )
            if not math.isclose(
                recomputed_effect,
                float(raw["effect"]),
                rel_tol=1e-12,
                abs_tol=1e-15,
            ):
                raise ValueError("evaluation effect differs from per-seed evidence")
            parsed = HypothesisEvaluation(
                hypothesis_id=hypothesis_id,
                phase=phase,
                ticks=ticks,
                seeds=tuple(seeds),
                effect=float(raw["effect"]),
                per_seed_effects=tuple(per_seed_pairs),
                history_digests=tuple(anchor_pairs),
            )
            parsed_evaluations.append(parsed)
            actual_order.append((phase, hypothesis_id))
            histories.append(
                {
                    "hypothesis_id": hypothesis_id,
                    "phase": phase,
                    "ticks": ticks,
                    "seeds": list(seeds),
                    "history_digests": [dict(item) for item in anchors],
                }
            )
            if phase == "probe":
                probe_effects.append((hypothesis_id, float(raw["effect"])))
        except (KeyError, TypeError, ValueError) as error:
            issues.append(
                _issue(
                    "post_result",
                    "invalid_evaluation",
                    f"evaluation {index}: {error}",
                )
            )

    expected_probe = [
        ("probe", step.hypothesis_id or "") for step in probe_steps
    ]
    selected = [
        hypothesis_id
        for hypothesis_id, _ in sorted(
            probe_effects, key=lambda item: (-item[1], item[0])
        )[: len(confirm_steps)]
    ]
    expected_order = expected_probe + [
        ("confirm", hypothesis_id) for hypothesis_id in selected
    ]
    if actual_order != expected_order:
        issues.append(
            _issue(
                "post_result",
                "evaluation_order_mismatch",
                "evaluation order does not reproduce probe order and adaptive confirmation",
            )
        )
    for raw, step in zip(evaluations[: len(probe_steps)], probe_steps):
        if isinstance(raw, Mapping) and raw.get("ticks") != step.ticks:
            issues.append(
                _issue(
                    "post_result",
                    "probe_ticks_mismatch",
                    "probe evaluation ticks differ from the plan",
                    step.step_id,
                )
            )
    for offset, step in enumerate(confirm_steps, start=len(probe_steps)):
        if offset < len(evaluations):
            raw = evaluations[offset]
            if isinstance(raw, Mapping) and raw.get("ticks") != step.ticks:
                issues.append(
                    _issue(
                        "post_result",
                        "confirm_ticks_mismatch",
                        "confirm evaluation ticks differ from the plan",
                        step.step_id,
                    )
                )

    confirmed_evaluations = [
        item for item in parsed_evaluations if item.phase == "confirm"
    ]
    expected_confirmed = [
        item.hypothesis_id
        for item in sorted(
            confirmed_evaluations,
            key=lambda item: (-item.effect, item.hypothesis_id),
        )
    ]
    expected_leader = expected_confirmed[0] if expected_confirmed else None
    if summary["confirmed"] != expected_confirmed or summary["leader"] != expected_leader:
        issues.append(
            _issue(
                "post_result",
                "leader_mismatch",
                "confirmed order or leader differs from confirmed effects",
            )
        )
    if tuple(summary["pending"]) != plan.pending_hypotheses:
        issues.append(
            _issue(
                "post_result",
                "pending_mismatch",
                "session pending hypotheses differ from the plan",
            )
        )
    if len(evaluations) > config.budget:
        issues.append(
            _issue(
                "post_result",
                "result_budget_exceeded",
                "session contains more evaluations than the frozen budget",
            )
        )

    try:
        decisions = summary["decision_log"]
        if len(decisions) != len(evaluations):
            raise ValueError("decision_log length differs from evaluations")
        for index, (decision, evaluation) in enumerate(
            zip(decisions, evaluations), start=1
        ):
            if not isinstance(decision, Mapping):
                raise ValueError("decision must be an object")
            _require_exact_keys(decision, set(_DECISION_KEYS), name="decision")
            if (
                decision["round"] != index
                or decision["phase"] != evaluation["phase"]
                or decision["hypothesis_id"] != evaluation["hypothesis_id"]
                or not _is_number(decision["effect"])
                or not math.isclose(
                    float(decision["effect"]),
                    float(evaluation["effect"]),
                    rel_tol=1e-12,
                    abs_tol=1e-15,
                )
            ):
                raise ValueError("decision does not match its evaluation")
            if not isinstance(decision["rationale"], str) or not decision[
                "rationale"
            ].strip():
                raise ValueError("decision rationale must not be empty")
    except (KeyError, TypeError, ValueError) as error:
        issues.append(
            _issue("post_result", "decision_log_mismatch", str(error))
        )

    if len(parsed_evaluations) == len(evaluations):
        expected_session_id = (
            "autolab-"
            + digest_payload(
                {"config": config, "evaluations": parsed_evaluations}
            )[:16]
        )
        if summary["session_id"] != expected_session_id:
            issues.append(
                _issue(
                    "post_result",
                    "session_id_mismatch",
                    "session_id does not match config and evaluations",
                )
            )

    try:
        if not isinstance(manifest, Mapping):
            raise ValueError("Autolab manifest must be an object")
        _require_exact_keys(manifest, set(_MANIFEST_KEYS), name="Autolab manifest")
        expected_manifest = {
            "schema_version": "mgba-autolab-artifact-0.1",
            "session_id": summary["session_id"],
            "model_version": config.model_version,
            # Existing ADR-0020 manifest semantics intentionally use ids only.
            "registry_digest": digest_payload(
                [item.hypothesis_id for item in config.hypotheses]
            ),
            "evaluations": histories,
        }
        if dict(manifest) != expected_manifest:
            issues.append(
                _issue(
                    "post_result",
                    "manifest_history_mismatch",
                    "manifest identity or history anchors differ from the session result",
                )
            )
    except (KeyError, TypeError, ValueError) as error:
        issues.append(
            _issue("post_result", "invalid_manifest_schema", str(error))
        )

    evidence = _safe_evidence_digest(
        {
            "plan_id": plan.plan_id,
            "result": summary,
            "manifest": manifest,
            "claim_level": claim_level,
            "claims": list(normalized_claims),
        }
    )
    return issues, evidence


def verify_autolab_result(
    plan: AutolabPlan | Mapping[str, Any],
    result: AutolabSessionResult | Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    registry: AutolabConfig,
    claim_level: str = REFERENCE_CLAIM_LEVEL,
    claims: Sequence[str] = (),
) -> VerificationReport:
    """Run all three verification stages over an already completed session.

    ``result`` and ``manifest`` are evidence only.  This function has no
    evaluator argument and cannot run or modify an experiment.
    """
    preflight = verify_autolab_plan(plan, registry)
    if not preflight.valid:
        return VerificationReport(
            plan_id=preflight.plan_id,
            mode="post_result",
            schema_status=preflight.schema_status,
            architecture_status=preflight.architecture_status,
            result_status="not_run",
            issues=preflight.issues,
        )
    parsed = _coerce_plan(plan)
    result_issues, evidence_digest = _post_result_issues(
        parsed, registry, result, manifest, claim_level, claims
    )
    return VerificationReport(
        plan_id=parsed.plan_id,
        mode="post_result",
        schema_status="passed",
        architecture_status="passed",
        result_status=("failed" if result_issues else "passed"),
        issues=tuple(result_issues),
        evidence_digest=evidence_digest,
    )


def load_autolab_plan(path: str | Path) -> AutolabPlan:
    """Load a closed-schema plan JSON file."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid Autolab plan file: {error}") from error
    try:
        return AutolabPlan.from_dict(raw)
    except (TypeError, ValueError, KeyError) as error:
        raise ValueError(f"invalid Autolab plan: {error}") from error




def save_autolab_plan(path: str | Path, plan: AutolabPlan) -> Path:
    """Write a plan idempotently; a different existing file is rejected."""
    if not isinstance(plan, AutolabPlan):
        raise TypeError("save_autolab_plan requires an AutolabPlan")
    target = Path(path)
    write_json_once(target, plan.as_dict(), artifact="Autolab planning artifact")
    return target


def save_verification_report(
    path: str | Path, report: VerificationReport
) -> Path:
    """Write a verification report idempotently."""
    if not isinstance(report, VerificationReport):
        raise TypeError("save_verification_report requires a VerificationReport")
    target = Path(path)
    write_json_once(target, report.summary_dict(), artifact="Autolab planning artifact")
    return target


__all__ = [
    "AutolabPlan",
    "FIXED_TOOL_INVENTORY",
    "PAIRED_SWAP_TOOL",
    "PLAN_SCHEMA_VERSION",
    "PLAN_STRATEGY",
    "PlanStep",
    "REFERENCE_CLAIM_LEVEL",
    "SELECT_TOOL",
    "TOOL_INVENTORY_DIGEST",
    "ToolSpec",
    "VERIFICATION_SCHEMA_VERSION",
    "VERIFY_TOOL",
    "VerificationIssue",
    "VerificationReport",
    "compile_autolab_plan",
    "load_autolab_plan",
    "registry_digest",
    "save_autolab_plan",
    "save_verification_report",
    "verify_autolab_plan",
    "verify_autolab_result",
]
