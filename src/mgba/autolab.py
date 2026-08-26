"""Deterministic autonomous experiment scheduler (meta-layer, Phase 1).

``AutolabSession`` is the first slice of the self-driving-lab direction
(ADR-0020): an *experimentation* loop that sits **outside** the L0–L4
layer stack.  It never enters the tick loop and never mutates layer
dynamics; its only actuation channel is asking an injected evaluator to
run paired baseline-vs-condition experiments through the existing formal
boundaries (here: layer-internal static-model swaps, the WP8 ablation
family).

Design invariants
-----------------

1. **Pre-registered hypothesis space.**  The session can only evaluate
   hypotheses enumerated in a frozen registry (config JSON).  It cannot
   invent new experiments; open-ended hypothesis *generation* is the
   reserved proposal channel below.
2. **Frozen selection policy.**  ``screen_then_confirm``: evaluate every
   registry hypothesis at ``probe_ticks`` in frozen priority order, rank
   by a frozen effect scalar, then re-evaluate the top ``confirm_top_k``
   at the longer ``confirm_ticks`` horizon.  Round two's choices depend
   on round one's measurements — the loop is genuinely closed — but the
   rule is fixed before any run, so the session is bit-exact
   reproducible from config + evaluator.
3. **Runner-free core.**  The core never imports the runner; the caller
   injects ``evaluate(hypothesis, ticks, seeds)``.  Tests substitute a
   scripted evaluator; the CLI substitutes the real paired-run machinery
   (WP8 ``_compare_runs``).
4. **Frozen effect scalar.**  Per seed, the effect is the mean absolute
   directed final L4 metric effect (the five WP8 metrics); the
   hypothesis effect is the mean over seeds.  Frozen here so no later
   stage can quietly redefine "effect".
5. **Proposal channel (reserved LLM interface).**  A proposal is a JSON
   document conforming to the registry-entry schema plus provenance
   (``proposed_by``).  ``validate_proposals`` is fail-closed: it returns
   per-proposal verdicts and **never executes anything**.  An accepted
   proposal is merely eligible for a human to copy into a registry; this
   is the only path by which a future LLM proposer may contribute, and
   it stays human-gated in Phase 1.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .experiment import digest_payload

_SUPPORTED_KINDS = ("layer_static_swap",)
_SWAPPABLE_LAYERS = ("L1", "L2", "L3")
_L4_METRIC_COUNT = 5  # WP8 final_metric_effects arity


@dataclass(frozen=True, slots=True)
class Hypothesis:
    """One pre-registered, executable experiment hypothesis."""

    hypothesis_id: str
    kind: str
    layer: str
    priority: float

    def __post_init__(self) -> None:
        if not isinstance(self.hypothesis_id, str) or not self.hypothesis_id.strip():
            raise ValueError("hypothesis_id must be a non-empty string")
        if self.hypothesis_id != self.hypothesis_id.strip() or any(
            char.isspace() for char in self.hypothesis_id
        ):
            raise ValueError("hypothesis_id must not contain whitespace")
        if self.kind not in _SUPPORTED_KINDS:
            raise ValueError(
                f"unsupported hypothesis kind {self.kind!r}; "
                f"supported: {sorted(_SUPPORTED_KINDS)}"
            )
        if self.layer not in _SWAPPABLE_LAYERS:
            raise ValueError(
                f"hypothesis layer must be one of {_SWAPPABLE_LAYERS}"
            )
        if not math.isfinite(self.priority):
            raise ValueError("hypothesis priority must be finite")


@dataclass(frozen=True, slots=True)
class AutolabConfig:
    """Frozen protocol parameters for one autonomous session."""

    model_version: str
    seeds: tuple[int, ...]
    probe_ticks: int
    confirm_ticks: int
    confirm_top_k: int
    budget: int
    hypotheses: tuple[Hypothesis, ...]

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("autolab model_version must not be empty")
        if len(self.seeds) < 2:
            raise ValueError("autolab requires at least two seeds")
        if self.seeds != tuple(sorted(self.seeds)) or len(set(self.seeds)) != len(
            self.seeds
        ):
            raise ValueError("autolab seeds must be unique and sorted")
        if any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in self.seeds
        ):
            raise ValueError("autolab seeds must be non-negative integers")
        for name in ("probe_ticks", "confirm_ticks", "confirm_top_k", "budget"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"autolab {name} must be a positive integer")
        if not self.hypotheses:
            raise ValueError("autolab requires at least one hypothesis")
        ids = [item.hypothesis_id for item in self.hypotheses]
        if len(set(ids)) != len(ids):
            raise ValueError("autolab hypothesis ids must be unique")

    @property
    def screening_order(self) -> tuple[Hypothesis, ...]:
        """Frozen screening order: priority descending, then id ascending."""
        return tuple(
            sorted(
                self.hypotheses,
                key=lambda item: (-item.priority, item.hypothesis_id),
            )
        )


def _parse_hypothesis(raw: Mapping[str, Any]) -> Hypothesis:
    return Hypothesis(
        hypothesis_id=str(raw["hypothesis_id"]),
        kind=str(raw["kind"]),
        layer=str(raw["layer"]),
        priority=float(raw["priority"]),
    )


def load_autolab_config(path: str | Path) -> AutolabConfig:
    """Load the frozen registry + protocol; any failure is a ValueError."""
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return AutolabConfig(
            model_version=str(raw["model_version"]),
            seeds=tuple(int(item) for item in raw["seeds"]),
            probe_ticks=int(raw["probe_ticks"]),
            confirm_ticks=int(raw["confirm_ticks"]),
            confirm_top_k=int(raw["confirm_top_k"]),
            budget=int(raw["budget"]),
            hypotheses=tuple(
                _parse_hypothesis(item) for item in raw["hypotheses"]
            ),
        )
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid autolab config: {error}") from error


@dataclass(frozen=True, slots=True)
class EvaluatorResult:
    """Raw paired-comparison evidence returned by the injected evaluator.

    ``per_seed_metric_effects`` carries, per seed, the directed final L4
    metric effects of the condition against the baseline (WP8 family).
    ``history_digests`` anchors each condition run for audit replay.
    """

    per_seed_metric_effects: tuple[tuple[int, tuple[tuple[str, float], ...]], ...]
    history_digests: tuple[tuple[int, str], ...]


@dataclass(frozen=True, slots=True)
class HypothesisEvaluation:
    """One scored hypothesis at one horizon."""

    hypothesis_id: str
    phase: str
    ticks: int
    seeds: tuple[int, ...]
    effect: float
    per_seed_effects: tuple[tuple[int, float], ...]
    history_digests: tuple[tuple[int, str], ...]

    def __post_init__(self) -> None:
        if self.phase not in ("probe", "confirm"):
            raise ValueError("evaluation phase must be probe or confirm")
        if not math.isfinite(self.effect) or self.effect < 0.0:
            raise ValueError("evaluation effect must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class DecisionEntry:
    """One scheduler decision, kept for the audit log."""

    round_index: int
    phase: str
    hypothesis_id: str
    rationale: str
    effect: float


@dataclass(frozen=True, slots=True)
class AutolabSessionResult:
    """Complete, deterministic record of one autonomous session."""

    config: AutolabConfig
    session_id: str
    evaluations: tuple[HypothesisEvaluation, ...]
    decision_log: tuple[DecisionEntry, ...]
    confirmed: tuple[str, ...]
    pending: tuple[str, ...]
    leader: str | None

    def summary_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "mgba-autolab-artifact-0.1",
            "session_id": self.session_id,
            "config": {
                "model_version": self.config.model_version,
                "seeds": list(self.config.seeds),
                "probe_ticks": self.config.probe_ticks,
                "confirm_ticks": self.config.confirm_ticks,
                "confirm_top_k": self.config.confirm_top_k,
                "budget": self.config.budget,
            },
            "registry": [
                {
                    "hypothesis_id": item.hypothesis_id,
                    "kind": item.kind,
                    "layer": item.layer,
                    "priority": item.priority,
                }
                for item in self.config.hypotheses
            ],
            "evaluations": [
                {
                    "hypothesis_id": item.hypothesis_id,
                    "phase": item.phase,
                    "ticks": item.ticks,
                    "seeds": list(item.seeds),
                    "effect": item.effect,
                    "per_seed_effects": [
                        {"seed": seed, "effect": effect}
                        for seed, effect in item.per_seed_effects
                    ],
                    "history_digests": [
                        {"seed": seed, "history_digest": digest}
                        for seed, digest in item.history_digests
                    ],
                }
                for item in self.evaluations
            ],
            "decision_log": [
                {
                    "round": entry.round_index,
                    "phase": entry.phase,
                    "hypothesis_id": entry.hypothesis_id,
                    "rationale": entry.rationale,
                    "effect": entry.effect,
                }
                for entry in self.decision_log
            ],
            "confirmed": list(self.confirmed),
            "pending": list(self.pending),
            "leader": self.leader,
        }


Evaluator = Callable[[Hypothesis, int, tuple[int, ...]], EvaluatorResult]


def _effect_scalar(result: EvaluatorResult) -> tuple[float, tuple[tuple[int, float], ...]]:
    """Frozen effect scalar: mean over seeds of mean |final L4 metric effect|."""
    per_seed: list[tuple[int, float]] = []
    for seed, metrics in result.per_seed_metric_effects:
        if len(metrics) != _L4_METRIC_COUNT:
            raise ValueError("evaluator returned an incomplete metric effect vector")
        if any(not math.isfinite(value) for _, value in metrics):
            raise ValueError("evaluator returned a non-finite metric effect")
        per_seed.append(
            (seed, sum(abs(value) for _, value in metrics) / len(metrics))
        )
    effect = sum(value for _, value in per_seed) / len(per_seed)
    return effect, tuple(per_seed)


class AutolabSession:
    """Runs the frozen screen-then-confirm autonomous experiment loop."""

    def __init__(
        self,
        config: AutolabConfig,
        *,
        evaluate: Evaluator,
    ) -> None:
        if not isinstance(config, AutolabConfig):
            raise TypeError("AutolabSession requires an AutolabConfig")
        if not callable(evaluate):
            raise TypeError("AutolabSession requires a callable evaluator")
        self.config = config
        self._evaluate = evaluate

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    def _run_one(
        self, hypothesis: Hypothesis, *, phase: str, ticks: int
    ) -> HypothesisEvaluation:
        result = self._evaluate(hypothesis, ticks, self.config.seeds)
        returned_seeds = tuple(
            seed for seed, _ in result.per_seed_metric_effects
        )
        if returned_seeds != self.config.seeds:
            raise ValueError(
                "evaluator must return metric effects for exactly the session seeds"
            )
        effect, per_seed = _effect_scalar(result)
        return HypothesisEvaluation(
            hypothesis_id=hypothesis.hypothesis_id,
            phase=phase,
            ticks=ticks,
            seeds=self.config.seeds,
            effect=effect,
            per_seed_effects=per_seed,
            history_digests=result.history_digests,
        )

    def run(self) -> AutolabSessionResult:
        spent = 0
        evaluations: list[HypothesisEvaluation] = []
        decision_log: list[DecisionEntry] = []
        pending: list[str] = []
        round_index = 0

        # Screening round: frozen priority order, probe horizon.
        probed: list[HypothesisEvaluation] = []
        for hypothesis in self.config.screening_order:
            if spent >= self.config.budget:
                pending.append(hypothesis.hypothesis_id)
                continue
            evaluation = self._run_one(
                hypothesis, phase="probe", ticks=self.config.probe_ticks
            )
            spent += 1
            round_index += 1
            probed.append(evaluation)
            evaluations.append(evaluation)
            decision_log.append(
                DecisionEntry(
                    round_index=round_index,
                    phase="probe",
                    hypothesis_id=hypothesis.hypothesis_id,
                    rationale="screening: frozen priority order",
                    effect=evaluation.effect,
                )
            )

        # Confirmation round: adaptive choice — top-k by probe effect,
        # re-evaluated at the longer confirm horizon.
        leaders = tuple(
            sorted(probed, key=lambda item: (-item.effect, item.hypothesis_id))[
                : self.config.confirm_top_k
            ]
        )
        confirmed: list[HypothesisEvaluation] = []
        for leader in leaders:
            if spent >= self.config.budget:
                # Budget exhausted: probed-but-unconfirmed hypotheses are
                # not "pending" (they were evaluated); the session simply
                # reports no confirmed leader.
                continue
            hypothesis = next(
                item
                for item in self.config.hypotheses
                if item.hypothesis_id == leader.hypothesis_id
            )
            evaluation = self._run_one(
                hypothesis, phase="confirm", ticks=self.config.confirm_ticks
            )
            spent += 1
            round_index += 1
            confirmed.append(evaluation)
            evaluations.append(evaluation)
            decision_log.append(
                DecisionEntry(
                    round_index=round_index,
                    phase="confirm",
                    hypothesis_id=hypothesis.hypothesis_id,
                    rationale=(
                        f"confirmation: top-{self.config.confirm_top_k} by probe "
                        f"effect ({leader.effect:.6g}) at longer horizon"
                    ),
                    effect=evaluation.effect,
                )
            )

        final_order = tuple(
            item.hypothesis_id
            for item in sorted(
                confirmed, key=lambda item: (-item.effect, item.hypothesis_id)
            )
        )
        leader = final_order[0] if final_order else None
        session_id = f"autolab-{digest_payload({'config': self.config, 'evaluations': evaluations})[:16]}"
        return AutolabSessionResult(
            config=self.config,
            session_id=session_id,
            evaluations=tuple(evaluations),
            decision_log=tuple(decision_log),
            confirmed=final_order,
            pending=tuple(pending),
            leader=leader,
        )


def save_autolab_artifacts(
    artifact_root: str | Path, result: AutolabSessionResult
) -> dict[str, Path]:
    """Persist the session manifest and summary (append-only, write-once).

    Raw runs are not duplicated: every evaluation is bit-exact
    reproducible from the config, and each run's ``history_digest`` is
    stored as the audit anchor.
    """
    if not isinstance(result, AutolabSessionResult):
        raise TypeError("save_autolab_artifacts requires an AutolabSessionResult")
    root = Path(artifact_root) / result.session_id
    manifest_path = root / "manifest.json"
    summary_path = root / "derived" / "summary.json"
    manifest = build_autolab_manifest(result)
    _write_json_once(manifest_path, manifest)
    _write_json_once(summary_path, result.summary_dict())
    return {"root": root, "manifest": manifest_path, "summary": summary_path}


def build_autolab_manifest(result: AutolabSessionResult) -> dict[str, Any]:
    """Rebuild the audit manifest without writing or executing anything."""

    if not isinstance(result, AutolabSessionResult):
        raise TypeError("build_autolab_manifest requires an AutolabSessionResult")
    return {
        "schema_version": "mgba-autolab-artifact-0.1",
        "session_id": result.session_id,
        "model_version": result.config.model_version,
        "registry_digest": digest_payload(
            [item.hypothesis_id for item in result.config.hypotheses]
        ),
        "evaluations": [
            {
                "hypothesis_id": item.hypothesis_id,
                "phase": item.phase,
                "ticks": item.ticks,
                "seeds": list(item.seeds),
                "history_digests": [
                    {"seed": seed, "history_digest": digest}
                    for seed, digest in item.history_digests
                ],
            }
            for item in result.evaluations
        ],
    }


def _write_json_once(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("existing autolab artifact is invalid JSON") from error
        if existing != payload:
            raise ValueError("refusing to overwrite a different autolab artifact")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True, slots=True)
class ProposalVerdict:
    """Fail-closed verdict for one proposed hypothesis (never executed)."""

    proposal_id: str
    status: str
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in ("accepted_for_registry_review", "rejected"):
            raise ValueError("unknown proposal verdict status")
        if self.status == "rejected" and not self.reasons:
            raise ValueError("a rejected proposal must carry reasons")


@dataclass(frozen=True, slots=True)
class ProposalReport:
    """Validation report over a proposal file; nothing was executed."""

    verdicts: tuple[ProposalVerdict, ...]

    def summary_dict(self) -> dict[str, Any]:
        accepted = [
            item
            for item in self.verdicts
            if item.status == "accepted_for_registry_review"
        ]
        return {
            "schema_version": "mgba-autolab-proposals-0.1",
            "executed": False,
            "accepted": [
                {"proposal_id": item.proposal_id} for item in accepted
            ],
            "rejected": [
                {"proposal_id": item.proposal_id, "reasons": list(item.reasons)}
                for item in self.verdicts
                if item.status == "rejected"
            ],
            "counts": {
                "total": len(self.verdicts),
                "accepted": len(accepted),
                "rejected": len(self.verdicts) - len(accepted),
            },
        }


def load_proposal_file(path: str | Path) -> Any:
    """Read a proposal JSON document; unreadable/invalid input is a ValueError."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid proposal file: {error}") from error
    if not isinstance(raw, dict) or not isinstance(raw.get("proposals"), list):
        raise ValueError("proposal file must be an object with a proposals list")
    return raw["proposals"]


def validate_proposals(
    proposals: Iterable[Any], *, registry_ids: Sequence[str]
) -> ProposalReport:
    """Validate proposals against the executable hypothesis schema.

    Fail-closed by construction: malformed content produces rejection
    reasons, never an exception, and validation never runs an experiment.
    """
    known_ids = set(registry_ids)
    seen: set[str] = set()
    verdicts: list[ProposalVerdict] = []
    for index, proposal in enumerate(proposals):
        reasons: list[str] = []
        proposal_id = f"proposal-{index}"
        if not isinstance(proposal, dict):
            verdicts.append(
                ProposalVerdict(
                    proposal_id=proposal_id,
                    status="rejected",
                    reasons=("proposal must be a JSON object",),
                )
            )
            continue
        raw_id = proposal.get("proposal_id")
        if isinstance(raw_id, str) and raw_id.strip():
            proposal_id = raw_id
        else:
            reasons.append("proposal_id must be a non-empty string")
        proposed_by = proposal.get("proposed_by")
        if not isinstance(proposed_by, str) or not proposed_by.strip():
            reasons.append("proposed_by must be a non-empty string")
        hypothesis = proposal.get("hypothesis")
        hypothesis_id = None
        if not isinstance(hypothesis, dict):
            reasons.append("hypothesis must be a JSON object")
        else:
            try:
                parsed = _parse_hypothesis(hypothesis)
                hypothesis_id = parsed.hypothesis_id
            except (KeyError, TypeError, ValueError) as error:
                reasons.append(f"hypothesis invalid: {error}")
        if hypothesis_id is not None:
            if hypothesis_id in known_ids:
                reasons.append("hypothesis_id already exists in the registry")
            if hypothesis_id in seen:
                reasons.append("hypothesis_id is duplicated within this file")
        if hypothesis_id:
            seen.add(hypothesis_id)
        verdicts.append(
            ProposalVerdict(
                proposal_id=proposal_id,
                status=(
                    "rejected" if reasons else "accepted_for_registry_review"
                ),
                reasons=tuple(reasons),
            )
        )
    return ProposalReport(verdicts=tuple(verdicts))
