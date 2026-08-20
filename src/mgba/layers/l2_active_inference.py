"""Active-inference (free-energy) Cell policy for L2.

This module implements a second, opt-in ``CellModel``: a deterministic
discrete-time Active Inference (AIF) agent that selects its phase by
minimizing the Expected Free Energy (EFE) of candidate actions, instead of
the frozen threshold-priority rule machine in ``l2.py``.

The rule baseline ``CellStateMachineModel`` is untouched and remains the
default; this model only replaces the *decision rule* (phase selection)
while reusing the rule model's drive semantics and state bookkeeping, so an
E2-style layer-swap isolates exactly one variable: how the cell chooses.

Mathematical formulation
------------------------

Let :math:`S = O = \\{\\text{quiescent, activated, repairing, stressed,
dead}\\}` be the phase (latent-state and observation) alphabet and let
:math:`A` be the candidate-action set, one action per phase:

.. math::

    A = \\{\\text{quiesce, activate, repair, stress\\_response, apoptose}\\}.

**Interoceptive observation.**  From the L1 molecular state and the L3
local environment the cell computes four drive scalars (identical to the
rule model): stress load :math:`\\sigma`, activation drive :math:`\\alpha`,
repair drive :math:`\\rho` and death drive :math:`\\delta`.  These form the
interoceptive vector :math:`x_t = (\\sigma, \\alpha, \\rho, \\delta)`.

**Belief (state inference).**  Each phase :math:`s` carries an expected
interoceptive signature :math:`\\mu_s \\in [0,1]^4` (frozen constants).
The likelihood is an isotropic Gaussian in drive space with precision
:math:`\\beta = 1/\\tau^2`:

.. math::

    \\ln A(x_t \\mid s) \\;\\propto\\;
    -\\frac{\\|x_t - \\mu_s\\|^2}{2\\tau^2}.

With a prior :math:`D(s)` — a point mass on the previous phase (uniform on
the first tick) — the posterior belief is

.. math::

    q(s_t) \\;=\\; \\frac{D(s_t)\\,A(x_t\\mid s_t)}
                       {\\sum_{s'} D(s')\\,A(x_t\\mid s')}.

**Predictive model.**  Choosing action :math:`a` with intended phase
:math:`p_a` yields a predicted next-state distribution

.. math::

    \\hat q(s'\\mid a) \\;=\\;
    (1-\\varepsilon_a)\\,\\delta_{p_a}(s') \\;+\\;
    \\varepsilon_a\\, f_a(s'),

where :math:`\\varepsilon_a` is the drive-dependent failure probability of
the action and :math:`f_a` spreads the failure mass over adverse phases
(stress / death) in proportion to the stress and death drives.  Each
:math:`\\hat q(\\cdot\\mid a)` is a proper distribution by construction.

**Expected Free Energy.**  With the phase preference
:math:`C(s) = \\mathrm{softmax}(u)_s` built from frozen utility logits
:math:`u` (a layer-internal constant, never read from L4), the EFE of an
action decomposes into risk and ambiguity:

.. math::

    G(a) \\;=\\;
    \\underbrace{\\sum_{s'} \\hat q(s'\\mid a)
        \\bigl[\\ln \\hat q(s'\\mid a) - \\ln C(s')\\bigr]}_{\\text{risk}}
    \\;+\\;
    \\underbrace{\\sum_{s'} \\hat q(s'\\mid a)\\, H[A(\\cdot\\mid s')]}_
        {\\text{ambiguity}}.

Here :math:`H[A(\\cdot\\mid s')]` is the entropy of the observation
likelihood for phase :math:`s'`; it is high for ambiguous phases (stressed)
and zero for unambiguous ones (dead), so the ambiguity term varies with the
action through :math:`\\hat q`.  All logarithms use the log-sum-exp trick
with an :math:`\\epsilon` floor for numerical safety.

**Action selection.**  The policy posterior
:math:`P(a) \\propto \\sigma(-\\gamma G(a))` is taken in the deterministic
limit :math:`\\gamma\\to\\infty`:

.. math::

    a^{*} \\;=\\; \\arg\\min_{a} G(a),

with ties resolved by a frozen action-priority order.  There is no sampling
and no randomness anywhere, preserving the project's reproducibility
invariant.

**State bookkeeping.**  Viability, stress load and the apoptosis absorbing
state follow the same first-order equations as the rule model; only the
phase decision differs.  The emitted ``CellState`` / ``CellAction`` are
contract-identical to the rule baseline.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..experiment import digest_payload
from .contracts import (
    CellAction,
    CellPhase,
    CellState,
    LocalEnvironment,
    MolecularState,
    StateMetadata,
)
from .l2 import CellTrajectory, _dead_action, _validate_inputs

_EPS = 1e-12

_PHASES = tuple(CellPhase)
_PHASE_INDEX = {phase: index for index, phase in enumerate(_PHASES)}
_N_PHASES = len(_PHASES)

# Candidate actions, one per phase, in deterministic tie-break priority order.
_ACTIONS = (
    CellPhase.QUIESCENT,
    CellPhase.ACTIVATED,
    CellPhase.REPAIRING,
    CellPhase.STRESSED,
    CellPhase.DEAD,
)
_ACTION_NAMES = {
    CellPhase.QUIESCENT: "quiesce",
    CellPhase.ACTIVATED: "activate",
    CellPhase.REPAIRING: "repair",
    CellPhase.STRESSED: "stress_response",
    CellPhase.DEAD: "apoptose",
}

# Expected interoceptive signature mu_s for each phase, in the drive order
# (stress_load, activation_drive, repair_drive, death_drive).  Frozen
# reference constants documented in ADR-0013.
_PHASE_SIGNATURES: dict[CellPhase, tuple[float, float, float, float]] = {
    CellPhase.QUIESCENT: (0.20, 0.10, 0.10, 0.10),
    CellPhase.ACTIVATED: (0.20, 0.80, 0.10, 0.10),
    CellPhase.REPAIRING: (0.30, 0.30, 0.80, 0.10),
    CellPhase.STRESSED: (0.80, 0.40, 0.10, 0.20),
    CellPhase.DEAD: (0.90, 0.00, 0.00, 0.90),
}

# Observation-likelihood entropy weight per phase: how ambiguous it is to
# be in that phase.  Dead is unambiguous; stressed is the most ambiguous.
_PHASE_OBSERVATION_NOISE: dict[CellPhase, float] = {
    CellPhase.DEAD: 0.0,
    CellPhase.QUIESCENT: 0.2,
    CellPhase.ACTIVATED: 0.2,
    CellPhase.REPAIRING: 0.3,
    CellPhase.STRESSED: 0.5,
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _metadata(
    *, logical_time: int, model_version: str, source: Any
) -> StateMetadata:
    return StateMetadata(
        logical_time=logical_time,
        model_version=model_version,
        source_digest=digest_payload(source),
    )


@dataclass(frozen=True, slots=True)
class ActiveInferenceCellConfig:
    """Frozen parameter set for the active-inference L2 policy."""

    model_version: str

    # Drive weights: identical semantics to the rule CellConfig.
    stress_environment_weight: float
    resource_deficit_weight: float
    death_stress_weight: float
    metabolic_buffer_weight: float
    signal_activation_weight: float
    incoming_signal_weight: float
    death_effector_weight: float
    stress_mortality_weight: float
    repair_recovery_rate: float
    stress_damage_rate: float
    death_damage_rate: float
    basal_consumption: float
    activation_consumption_rate: float
    repair_consumption_rate: float
    death_viability_threshold: float
    death_drive_threshold: float

    # Active-inference parameters.
    belief_precision: float  # beta = 1 / tau^2, sharpness of A(x|s)
    ambiguity_weight: float  # weight on the ambiguity term of G
    phase_utilities: tuple[tuple[CellPhase, float], ...]  # preference logits
    secretion_multipliers: tuple[tuple[CellPhase, float], ...]

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("cell model_version must not be empty")
        scalar_names = (
            "stress_environment_weight",
            "resource_deficit_weight",
            "death_stress_weight",
            "metabolic_buffer_weight",
            "signal_activation_weight",
            "incoming_signal_weight",
            "death_effector_weight",
            "stress_mortality_weight",
            "repair_recovery_rate",
            "stress_damage_rate",
            "death_damage_rate",
            "basal_consumption",
            "activation_consumption_rate",
            "repair_consumption_rate",
            "death_viability_threshold",
            "death_drive_threshold",
        )
        for name in scalar_names:
            value = getattr(self, name)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and in [0, 1]")
        if not math.isfinite(self.belief_precision) or self.belief_precision <= 0.0:
            raise ValueError("belief_precision must be finite and positive")
        if not math.isfinite(self.ambiguity_weight) or self.ambiguity_weight < 0.0:
            raise ValueError("ambiguity_weight must be finite and non-negative")

        utility_phases = tuple(phase for phase, _ in self.phase_utilities)
        if utility_phases != _PHASES:
            raise ValueError("phase utilities must match every CellPhase in order")
        for _, value in self.phase_utilities:
            if not math.isfinite(value):
                raise ValueError("phase utilities must be finite")

        multiplier_phases = tuple(phase for phase, _ in self.secretion_multipliers)
        if multiplier_phases != _PHASES:
            raise ValueError("secretion multipliers must match every CellPhase in order")
        for _, value in self.secretion_multipliers:
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError("secretion multipliers must be finite and in [0, 1]")

    @property
    def utility_map(self) -> dict[CellPhase, float]:
        return dict(self.phase_utilities)

    @property
    def secretion_multiplier_map(self) -> dict[CellPhase, float]:
        return dict(self.secretion_multipliers)


def load_active_inference_config(
    path: str | Path,
) -> ActiveInferenceCellConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        raw_utilities: dict[str, Any] = raw["phase_utilities"]
        raw_multipliers: dict[str, Any] = raw["secretion_multipliers"]
        if set(raw_utilities) != {phase.value for phase in _PHASES}:
            raise ValueError("cell config has missing or unknown utility phases")
        if set(raw_multipliers) != {phase.value for phase in _PHASES}:
            raise ValueError("cell config has missing or unknown secretion phases")
        return ActiveInferenceCellConfig(
            model_version=str(raw["model_version"]),
            stress_environment_weight=float(raw["stress_environment_weight"]),
            resource_deficit_weight=float(raw["resource_deficit_weight"]),
            death_stress_weight=float(raw["death_stress_weight"]),
            metabolic_buffer_weight=float(raw["metabolic_buffer_weight"]),
            signal_activation_weight=float(raw["signal_activation_weight"]),
            incoming_signal_weight=float(raw["incoming_signal_weight"]),
            death_effector_weight=float(raw["death_effector_weight"]),
            stress_mortality_weight=float(raw["stress_mortality_weight"]),
            repair_recovery_rate=float(raw["repair_recovery_rate"]),
            stress_damage_rate=float(raw["stress_damage_rate"]),
            death_damage_rate=float(raw["death_damage_rate"]),
            basal_consumption=float(raw["basal_consumption"]),
            activation_consumption_rate=float(raw["activation_consumption_rate"]),
            repair_consumption_rate=float(raw["repair_consumption_rate"]),
            death_viability_threshold=float(raw["death_viability_threshold"]),
            death_drive_threshold=float(raw["death_drive_threshold"]),
            belief_precision=float(raw["belief_precision"]),
            ambiguity_weight=float(raw["ambiguity_weight"]),
            phase_utilities=tuple(
                (phase, float(raw_utilities[phase.value])) for phase in _PHASES
            ),
            secretion_multipliers=tuple(
                (phase, float(raw_multipliers[phase.value])) for phase in _PHASES
            ),
        )
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid active inference cell config: {error}") from error


def _logsumexp(values: list[float]) -> float:
    maximum = max(values)
    return maximum + math.log(sum(math.exp(value - maximum) for value in values))

class ActiveInferenceCellModel:
    """Deterministic expected-free-energy Cell policy for L2."""

    def __init__(self, config: ActiveInferenceCellConfig) -> None:
        self.config = config
        self._preference = self._build_preference()
        self._ambiguity = self._build_ambiguity()

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    def _build_preference(self) -> list[float]:
        logits = [self.config.utility_map[phase] for phase in _PHASES]
        normalizer = _logsumexp(logits)
        return [math.exp(logit - normalizer) for logit in logits]

    def _build_ambiguity(self) -> list[float]:
        """Entropy H[A(.|s)] of the observation likelihood per phase."""
        entropies = []
        for phase in _PHASES:
            noise = _PHASE_OBSERVATION_NOISE[phase]
            diagonal = max(_EPS, 1.0 - noise)
            off_diagonal = max(_EPS, noise / (_N_PHASES - 1))
            entropy = -(diagonal * math.log(diagonal))
            entropy -= (_N_PHASES - 1) * off_diagonal * math.log(off_diagonal)
            entropies.append(entropy)
        return entropies

    def _drives(
        self, molecular: MolecularState, environment: LocalEnvironment
    ) -> tuple[float, float, float, float]:
        config = self.config
        stress_load = _clamp(
            config.stress_environment_weight * environment.stress
            + config.resource_deficit_weight * (1.0 - environment.resource_level)
            + config.death_stress_weight * molecular.death_effector
            - config.metabolic_buffer_weight * molecular.metabolic_capacity
        )
        activation_drive = _clamp(
            config.signal_activation_weight * molecular.signal_protein
            + config.incoming_signal_weight * environment.incoming_signal
        )
        repair_drive = _clamp(
            molecular.repair_protein
            * stress_load
            * environment.resource_level
        )
        death_drive = _clamp(
            config.death_effector_weight * molecular.death_effector
            + config.stress_mortality_weight
            * stress_load
            * (1.0 - molecular.metabolic_capacity)
        )
        return stress_load, activation_drive, repair_drive, death_drive

    def _belief(
        self,
        drives: tuple[float, float, float, float],
        previous_phase: CellPhase | None,
    ) -> list[float]:
        precision = self.config.belief_precision
        log_likelihoods = []
        for phase in _PHASES:
            signature = _PHASE_SIGNATURES[phase]
            squared = sum(
                (observed - expected) ** 2
                for observed, expected in zip(drives, signature)
            )
            log_likelihoods.append(-0.5 * precision * squared)

        if previous_phase is None:
            log_prior = [math.log(1.0 / _N_PHASES)] * _N_PHASES
        else:
            log_prior = [
                0.0 if phase is previous_phase else math.log(_EPS)
                for phase in _PHASES
            ]

        posterior_logits = [
            log_prior[index] + log_likelihoods[index]
            for index in range(_N_PHASES)
        ]
        normalizer = _logsumexp(posterior_logits)
        return [
            math.exp(logit - normalizer) for logit in posterior_logits
        ]

    def _predicted_next(
        self,
        action: CellPhase,
        drives: tuple[float, float, float, float],
    ) -> list[float]:
        """Return the predicted next-state distribution q̂(s'|a)."""
        stress_load, _, _, death_drive = drives
        distribution = [0.0] * _N_PHASES
        target_index = _PHASE_INDEX[action]

        if action is CellPhase.DEAD:
            distribution[target_index] = 1.0
            return distribution

        failure = _clamp(
            stress_load * 0.5 + death_drive * 0.5
        )
        success = 1.0 - failure
        distribution[target_index] = success

        adverse_total = failure
        if adverse_total <= _EPS:
            return self._normalize(distribution)
        stress_share = (
            stress_load / (stress_load + death_drive)
            if (stress_load + death_drive) > _EPS
            else 0.5
        )
        distribution[_PHASE_INDEX[CellPhase.STRESSED]] += (
            adverse_total * stress_share
        )
        distribution[_PHASE_INDEX[CellPhase.DEAD]] += adverse_total * (
            1.0 - stress_share
        )
        return self._normalize(distribution)

    @staticmethod
    def _normalize(distribution: list[float]) -> list[float]:
        total = sum(distribution)
        if total <= _EPS:
            return [1.0 / _N_PHASES] * _N_PHASES
        return [value / total for value in distribution]

    def _expected_free_energy(
        self, predicted: list[float]
    ) -> tuple[float, float]:
        """Return (risk, ambiguity) for one predicted distribution."""
        risk = 0.0
        ambiguity = 0.0
        for index in range(_N_PHASES):
            probability = predicted[index]
            if probability <= _EPS:
                continue
            log_probability = math.log(max(probability, _EPS))
            log_preference = math.log(
                max(self._preference[index], _EPS)
            )
            risk += probability * (log_probability - log_preference)
            ambiguity += probability * self._ambiguity[index]
        return risk, self.config.ambiguity_weight * ambiguity

    def _select_action(
        self,
        drives: tuple[float, float, float, float],
        previous_phase: CellPhase | None,
    ) -> tuple[CellPhase, dict[str, float]]:
        belief = self._belief(drives, previous_phase)
        diagnostics: dict[str, float] = {}
        best_action = _ACTIONS[0]
        best_free_energy = math.inf
        for action in _ACTIONS:
            predicted = [0.0] * _N_PHASES
            for source_index in range(_N_PHASES):
                weight = belief[source_index]
                if weight <= _EPS:
                    continue
                single = self._predicted_next_from_state(
                    action, drives, source_index
                )
                for target_index in range(_N_PHASES):
                    predicted[target_index] += weight * single[target_index]
            predicted = self._normalize(predicted)
            risk, ambiguity = self._expected_free_energy(predicted)
            free_energy = risk + ambiguity
            diagnostics[_ACTION_NAMES[action]] = free_energy
            if free_energy < best_free_energy - _EPS:
                best_free_energy = free_energy
                best_action = action
        return best_action, diagnostics

    def _predicted_next_from_state(
        self,
        action: CellPhase,
        drives: tuple[float, float, float, float],
        source_index: int,
    ) -> list[float]:
        """Predicted next state when acting from a specific latent phase.

        The dead absorbing state propagates regardless of the chosen action.
        """
        if _PHASES[source_index] is CellPhase.DEAD:
            distribution = [0.0] * _N_PHASES
            distribution[_PHASE_INDEX[CellPhase.DEAD]] = 1.0
            return distribution
        return self._predicted_next(action, drives)

    def step(
        self,
        molecular: MolecularState,
        environment: LocalEnvironment,
        *,
        previous_state: CellState | None,
        logical_time: int,
    ) -> tuple[CellState, CellAction]:
        _validate_inputs(
            molecular=molecular,
            environment=environment,
            previous_state=previous_state,
            logical_time=logical_time,
        )
        stress_load, activation_drive, repair_drive, death_drive = self._drives(
            molecular, environment
        )
        source = {
            "molecular": molecular,
            "environment": environment,
            "previous_state": previous_state,
            "config": self.config,
        }
        metadata = _metadata(
            logical_time=logical_time,
            model_version=self.model_version,
            source=source,
        )

        previous_phase = (
            previous_state.phase if previous_state is not None else None
        )
        if previous_phase is CellPhase.DEAD:
            state = CellState(
                metadata=metadata,
                cell_id=molecular.cell_id,
                phase=CellPhase.DEAD,
                activation=0.0,
                viability=previous_state.viability,
                stress_load=stress_load,
            )
            return state, _dead_action(metadata, molecular.cell_id)

        viability_base = (
            previous_state.viability
            if previous_state is not None
            else 0.5 * molecular.repair_protein
            + 0.5 * molecular.metabolic_capacity
        )
        viability = _clamp(
            viability_base
            + self.config.repair_recovery_rate * repair_drive
            - self.config.stress_damage_rate * stress_load
            - self.config.death_damage_rate * death_drive
        )

        if (
            viability <= self.config.death_viability_threshold
            or death_drive >= self.config.death_drive_threshold
        ):
            phase = CellPhase.DEAD
        else:
            phase, _ = self._select_action(
                (stress_load, activation_drive, repair_drive, death_drive),
                previous_phase,
            )
            if phase is CellPhase.DEAD:
                viability = min(viability, self.config.death_viability_threshold)

        state = CellState(
            metadata=metadata,
            cell_id=molecular.cell_id,
            phase=phase,
            activation=activation_drive,
            viability=viability,
            stress_load=stress_load,
        )
        if phase is CellPhase.DEAD:
            return state, _dead_action(metadata, molecular.cell_id)

        repair_effort = repair_drive if phase is CellPhase.REPAIRING else 0.0
        action = CellAction(
            metadata=metadata,
            cell_id=molecular.cell_id,
            secretion=_clamp(
                self.config.secretion_multiplier_map[phase]
                * activation_drive
                * molecular.metabolic_capacity
            ),
            resource_consumption=_clamp(
                self.config.basal_consumption
                + self.config.activation_consumption_rate * activation_drive
                + self.config.repair_consumption_rate * repair_effort
            ),
            repair_effort=repair_effort,
            apoptosis=False,
        )
        return state, action

    def simulate(
        self,
        *,
        molecular: MolecularState,
        stress: float,
        resource_level: float,
        incoming_signal: float,
        steps: int,
    ) -> CellTrajectory:
        if steps < 1:
            raise ValueError("steps must be positive")
        states: list[CellState] = []
        actions: list[CellAction] = []
        previous_state: CellState | None = None
        for logical_time in range(1, steps + 1):
            environment = LocalEnvironment(
                metadata=_metadata(
                    logical_time=logical_time,
                    model_version="l3-to-l2-local-boundary-aif-0.1",
                    source={
                        "cell_id": molecular.cell_id,
                        "stress": stress,
                        "resource_level": resource_level,
                        "incoming_signal": incoming_signal,
                    },
                ),
                cell_id=molecular.cell_id,
                stress=stress,
                resource_level=resource_level,
                incoming_signal=incoming_signal,
            )
            state, action = self.step(
                molecular,
                environment,
                previous_state=previous_state,
                logical_time=logical_time,
            )
            states.append(state)
            actions.append(action)
            previous_state = state
        return CellTrajectory(states=tuple(states), actions=tuple(actions))
