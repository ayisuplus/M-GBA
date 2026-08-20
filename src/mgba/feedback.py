"""L4→L3 homeostatic feedback controller (FeedbackPolicy reference model).

This module implements the first concrete ``FeedbackPolicy`` for the
five-layer main chain.  It closes the slow macro-to-meso loop promised by
the architecture document (L4 → L3) while respecting every adjacency and
auditability constraint:

* The controller **only consumes** the formal ``OrganismState`` produced by
  the adjacent L4 observer.  It never reads L0–L2 internals.
* The controller **only produces** a ``FeedbackConstraint`` consumed by the
  adjacent L3 tissue model.  It never names a cell or prescribes L2 actions.
* Every observation is time-stamped, monotonically ordered, and serialized
  into the L3 ``TissueState.metadata.source_digest`` hash chain, making the
  downward action auditable.

Mathematical formulation
------------------------

At each slow-clock observation tick the controller reads the homeostasis
scalar $H_k \\in [0,1]$ from ``OrganismState`` and compares it to a
set-point $H^* \\in (0,1)$.

**Error with dead-zone.**  A dead-zone $\\varepsilon$ suppresses limit-cycle
chatter near the set-point:

.. math::

    e_k = \\mathrm{dz}_\\varepsilon(H^* - H_k), \\qquad
    \\mathrm{dz}_\\varepsilon(x) =
    \\begin{cases} x, & |x| > \\varepsilon \\\\ 0, & |x| \\le \\varepsilon
    \\end{cases}

**Discrete PI with back-calculation anti-windup.**  The raw control signal
is a proportional-plus-integral law; the actuator saturates at $[0,1]$; the
back-calculation term $K_t(u_k - \\tilde u_k)$ pulls the integrator back
into the feasible region whenever the actuator saturates, preventing windup
(Aström–Hägglund form; cf. Lavretsky, arXiv:2504.12207, 2025):

.. math::

    \\tilde u_k = K_p\\, e_k + I_k, \\qquad
    u_k = \\mathrm{sat}(\\tilde u_k,\\, 0,\\, 1)

.. math::

    I_{k+1} = \\mathrm{clip}\\!\\bigl(
        I_k + K_i\\, e_k + K_t\\,(u_k - \\tilde u_k),\\;
        -I_{\\max},\\; I_{\\max}\\bigr)

For a constant disturbance the integral action drives $e_k \\to 0$
(robust perfect adaptation in the discrete sense; cf. Aoki et al.,
*Universal biomolecular integral feedback controller*, Nat. Chem. Biol.
2019).

**Economic channel (resource ceiling).**  The control effort $u_k$ tightens
resource availability to enforce conservation under stress:

.. math::

    r_k = \\mathrm{clamp}(r_0 - \\gamma_r\\, u_k,\\; r_{\\min},\\; 1)

**Safety channel (stress floor).**  A memoryless proportional barrier lifts
the tissue stress floor whenever homeostasis drops below the alarm level.
This is the discrete analogue of a control-barrier-function constraint:
monotone, instantaneous, and free of windup risk.

.. math::

    s_k = \\min\\!\\bigl(s_{\\max},\\;
        s_0 + \\gamma_s\\,\\mathrm{ReLU}(H_{\\text{alarm}} - H_k)\\bigr)

Both channels are pure functions of the current observation (plus the
integrator state for the economic channel), so the controller is fully
deterministic given the observation sequence.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .experiment import digest_payload
from .layers.contracts import (
    FeedbackConstraint,
    OrganismState,
    StateMetadata,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FeedbackControllerConfig:
    """Frozen parameter set for the homeostatic feedback controller.

    Every parameter is validated at construction time; invalid values raise
    immediately (fail-fast, no silent degradation).
    """

    model_version: str

    # --- PI controller ---
    setpoint: float  # H* in (0,1)
    proportional_gain: float  # K_p in [0,1]
    integral_gain: float  # K_i in [0,1]
    back_calculation_gain: float  # K_t in [0,1]
    deadband: float  # epsilon in [0,1)
    integral_bound: float  # I_max in [0,1]

    # --- Economic channel (resource ceiling) ---
    resource_ceiling_idle: float  # r_0 in (0,1]
    resource_gain: float  # gamma_r in [0,1]
    resource_ceiling_min: float  # r_min in (0, r_0]

    # --- Safety channel (stress floor) ---
    stress_floor_idle: float  # s_0 in [0,1]
    stress_gain: float  # gamma_s in [0,1]
    stress_floor_max: float  # s_max in [s_0, 1]
    alarm_homeostasis: float  # H_alarm in [0, setpoint)

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("feedback model_version must not be empty")
        _finite_unit(self.setpoint, "setpoint", open_low=True, open_high=True)
        _finite_unit(self.proportional_gain, "proportional_gain")
        _finite_unit(self.integral_gain, "integral_gain")
        _finite_unit(self.back_calculation_gain, "back_calculation_gain")
        _finite_unit(self.integral_bound, "integral_bound")
        if not math.isfinite(self.deadband) or not 0.0 <= self.deadband < 1.0:
            raise ValueError("deadband must be finite and in [0, 1)")

        # Economic channel
        _finite_unit(self.resource_ceiling_idle, "resource_ceiling_idle", open_low=True)
        _finite_unit(self.resource_gain, "resource_gain")
        _finite_unit(self.resource_ceiling_min, "resource_ceiling_min", open_low=True)
        if self.resource_ceiling_min > self.resource_ceiling_idle:
            raise ValueError("resource_ceiling_min must not exceed resource_ceiling_idle")

        # Safety channel
        _finite_unit(self.stress_floor_idle, "stress_floor_idle")
        _finite_unit(self.stress_gain, "stress_gain")
        _finite_unit(self.stress_floor_max, "stress_floor_max")
        if self.stress_floor_idle > self.stress_floor_max:
            raise ValueError("stress_floor_idle must not exceed stress_floor_max")
        _finite_unit(self.alarm_homeostasis, "alarm_homeostasis")
        if self.alarm_homeostasis >= self.setpoint:
            raise ValueError("alarm_homeostasis must be strictly below setpoint")


def _finite_unit(
    value: float, name: str, *, open_low: bool = False, open_high: bool = False
) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    low_ok = value > 0.0 if open_low else value >= 0.0
    high_ok = value < 1.0 if open_high else value <= 1.0
    if not (low_ok and high_ok):
        lo = "(0" if open_low else "[0"
        hi = "1)" if open_high else "1]"
        raise ValueError(f"{name} must be in {lo}, {hi}")


def load_feedback_config(path: str | Path) -> FeedbackControllerConfig:
    """Load and validate a feedback controller config from JSON."""
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return FeedbackControllerConfig(
            model_version=str(raw["model_version"]),
            setpoint=float(raw["setpoint"]),
            proportional_gain=float(raw["proportional_gain"]),
            integral_gain=float(raw["integral_gain"]),
            back_calculation_gain=float(raw["back_calculation_gain"]),
            deadband=float(raw["deadband"]),
            integral_bound=float(raw["integral_bound"]),
            resource_ceiling_idle=float(raw["resource_ceiling_idle"]),
            resource_gain=float(raw["resource_gain"]),
            resource_ceiling_min=float(raw["resource_ceiling_min"]),
            stress_floor_idle=float(raw["stress_floor_idle"]),
            stress_gain=float(raw["stress_gain"]),
            stress_floor_max=float(raw["stress_floor_max"]),
            alarm_homeostasis=float(raw["alarm_homeostasis"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid feedback controller config: {error}") from error


# ---------------------------------------------------------------------------
# Homeostatic (state-dependent) controller
# ---------------------------------------------------------------------------


class HomeostaticFeedbackController:
    """Discrete PI + anti-windup + safety barrier feedback policy.

    Stateful: holds the integrator $I_k$.  Deterministic given the
    observation sequence.  Thread-unsafe by design (single-runner contract).
    """

    def __init__(self, config: FeedbackControllerConfig) -> None:
        if not isinstance(config, FeedbackControllerConfig):
            raise TypeError("HomeostaticFeedbackController requires a config")
        self.config = config
        self._integral: float = 0.0
        self._last_time: int | None = None

    @property
    def model_version(self) -> str:
        return f"{self.config.model_version}+{digest_payload(self.config)[:12]}"

    def reset(self) -> None:
        """Restore the pristine integrator so the policy is reusable."""
        self._integral = 0.0
        self._last_time = None

    def observe(
        self, organism: OrganismState, *, logical_time: int
    ) -> FeedbackConstraint:
        """Consume one L4 observation and emit the next L3 constraint.

        Raises on type violations, non-positive time, or time regression.
        """
        if not isinstance(organism, OrganismState):
            raise TypeError("feedback controller consumes OrganismState")
        if isinstance(logical_time, bool) or not isinstance(logical_time, int):
            raise TypeError("logical_time must be an int")
        if logical_time < 1:
            raise ValueError("logical_time must be positive")
        if self._last_time is not None and logical_time <= self._last_time:
            raise ValueError(
                f"feedback observations must advance time: "
                f"got {logical_time} after {self._last_time}"
            )
        self._last_time = logical_time

        cfg = self.config
        homeostasis = organism.homeostasis

        # --- Error with dead-zone ---
        raw_error = cfg.setpoint - homeostasis
        error = raw_error if abs(raw_error) > cfg.deadband else 0.0

        # --- PI + saturation ---
        raw_control = cfg.proportional_gain * error + self._integral
        control = max(0.0, min(1.0, raw_control))
        saturated = control != raw_control

        # --- Back-calculation anti-windup integrator update ---
        integral_update = (
            self._integral
            + cfg.integral_gain * error
            + cfg.back_calculation_gain * (control - raw_control)
        )
        self._integral = max(
            -cfg.integral_bound, min(cfg.integral_bound, integral_update)
        )

        # --- Economic channel: resource ceiling ---
        resource_ceiling = max(
            cfg.resource_ceiling_min,
            min(1.0, cfg.resource_ceiling_idle - cfg.resource_gain * control),
        )

        # --- Safety channel: stress floor (memoryless barrier) ---
        alarm_deficit = max(0.0, cfg.alarm_homeostasis - homeostasis)
        stress_floor = min(
            cfg.stress_floor_max,
            cfg.stress_floor_idle + cfg.stress_gain * alarm_deficit,
        )

        return FeedbackConstraint(
            metadata=StateMetadata(
                logical_time=logical_time,
                model_version=self.model_version,
                source_digest=digest_payload(
                    {
                        "organism": organism,
                        "config": self.config,
                        "integral_before": self._integral,
                    }
                ),
            ),
            resource_ceiling=resource_ceiling,
            stress_floor=stress_floor,
            error=error,
            integral=self._integral,
            saturated=saturated,
        )


# ---------------------------------------------------------------------------
# Fixed (open-loop) constraint policy — E4 control condition
# ---------------------------------------------------------------------------


class FixedConstraintPolicy:
    """Constant constraint output; used as the E4 'fixed feedback' control.

    This policy ignores the organism state entirely and always emits the
    same constraint.  It isolates the effect of a static environment change
    from the state-dependent controller.
    """

    def __init__(
        self,
        *,
        resource_ceiling: float,
        stress_floor: float,
        model_version: str = "fixed-constraint-policy-0.1",
    ) -> None:
        if not model_version.strip():
            raise ValueError("fixed policy model_version must not be empty")
        if not math.isfinite(resource_ceiling) or not 0.0 < resource_ceiling <= 1.0:
            raise ValueError("resource_ceiling must be finite and in (0, 1]")
        if not math.isfinite(stress_floor) or not 0.0 <= stress_floor < 1.0:
            raise ValueError("stress_floor must be finite and in [0, 1)")
        self._resource_ceiling = resource_ceiling
        self._stress_floor = stress_floor
        self._model_version = model_version
        self._last_time: int | None = None

    @property
    def model_version(self) -> str:
        return self._model_version

    def reset(self) -> None:
        """Fixed policy is memoryless apart from the time guard."""
        self._last_time = None

    def observe(
        self, organism: OrganismState, *, logical_time: int
    ) -> FeedbackConstraint:
        if not isinstance(organism, OrganismState):
            raise TypeError("fixed policy consumes OrganismState")
        if isinstance(logical_time, bool) or not isinstance(logical_time, int):
            raise TypeError("logical_time must be an int")
        if logical_time < 1:
            raise ValueError("logical_time must be positive")
        if self._last_time is not None and logical_time <= self._last_time:
            raise ValueError("fixed policy observations must advance time")
        self._last_time = logical_time

        return FeedbackConstraint(
            metadata=StateMetadata(
                logical_time=logical_time,
                model_version=self._model_version,
                source_digest=digest_payload(
                    {
                        "resource_ceiling": self._resource_ceiling,
                        "stress_floor": self._stress_floor,
                    }
                ),
            ),
            resource_ceiling=self._resource_ceiling,
            stress_floor=self._stress_floor,
            error=0.0,
            integral=0.0,
            saturated=False,
        )
