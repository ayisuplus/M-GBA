"""Shared pure-stdlib neural primitives for opt-in layer variants.

These kernels back the frozen-weight heterogeneous-layer contract
demonstrators (ADR-0017): an MLP-shaped L0 GRN variant and a
message-passing L3 GNN variant.  They exist to prove that a
neural-shaped layer can satisfy the same formal DTO/Protocol contracts
as the rule reference models — they are **not** trained models.  The
repository holds no supervision targets or training data (ADR-0005),
so every weight is derived deterministically from an explicit seed and
no training loop exists here.

Determinism contract
--------------------

Every weight element is drawn from its own seeded stream, reusing the
sha256-derived RNG pattern of ``layers/l0_noisy.py``:

.. math::

    w_{ij} \\sim \\mathcal{U}(-s, s), \\qquad s = \\frac{1}{\\sqrt{n_{in}}}

    \\mathrm{rng}_{ij} = \\mathrm{Random}\\!\\Bigl(
        \\mathrm{int}_{0..2^{64}}\\!\\bigl(
            \\mathrm{sha256}(seed\\,\\|\\,salt\\,\\|\\,i\\,\\|\\,j)[:8]\\bigr)\\Bigr)

This is a Xavier/Glorot-style uniform bound with the fan-in scale
:math:`s = 1/\\sqrt{n_{in}}`, so saturated forward passes stay bounded
without any floating-point overflow risk.  Same ``(seed, salt, rows,
cols)`` reproduces the same matrix bit-for-bit on any platform; no
global random state is touched.

All functions are pure: they read their arguments, return new objects,
and fail fast on invalid input instead of silently coercing it.
"""

from __future__ import annotations

import hashlib
import math
import random
from typing import Mapping, Sequence

__all__ = ["message_passing_step", "mlp_forward", "seeded_matrix", "sigmoid"]


def _require_positive_int(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an int")
    if value < 1:
        raise ValueError(f"{field_name} must be a positive integer")


def _require_finite_vector(values: Sequence[float], field_name: str) -> int:
    if not values:
        raise ValueError(f"{field_name} must not be empty")
    if any(not math.isfinite(value) for value in values):
        raise ValueError(f"{field_name} must contain only finite values")
    return len(values)


def _tanh(value: float) -> float:
    return math.tanh(value)


def sigmoid(value: float) -> float:
    # Overflow-safe logistic: exp never sees a positive argument.
    if value >= 0.0:
        return 1.0 / (1.0 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


_ACTIVATIONS = {"tanh": _tanh, "sigmoid": sigmoid}


def seeded_matrix(
    seed: int, salt: str, rows: int, cols: int
) -> tuple[tuple[float, ...], ...]:
    """Deterministically derive a ``rows`` x ``cols`` weight matrix.

    Each element is an independent uniform draw in
    ``[-1/sqrt(cols), 1/sqrt(cols)]`` from the sha256-derived stream of
    ``(seed, salt, i, j)``.  The ``salt`` namespaces matrices that share
    a seed (e.g. ``"l0-neural-hidden"`` vs ``"l0-neural-output"``).
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an int")
    if seed < 0:
        raise ValueError("seed must be non-negative")
    if not isinstance(salt, str) or not salt.strip():
        raise ValueError("salt must be a non-empty string")
    _require_positive_int(rows, "rows")
    _require_positive_int(cols, "cols")
    scale = 1.0 / math.sqrt(cols)
    matrix: list[tuple[float, ...]] = []
    for row in range(rows):
        values: list[float] = []
        for col in range(cols):
            payload = f"{seed}|{salt}|{row}|{col}".encode("utf-8")
            stream_seed = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
            values.append(random.Random(stream_seed).uniform(-scale, scale))
        matrix.append(tuple(values))
    return tuple(matrix)


def mlp_forward(
    x: Sequence[float],
    *,
    weights: tuple[tuple[tuple[float, ...], ...], ...],
    activation: str,
) -> tuple[float, ...]:
    """Run one deterministic feed-forward pass through layered matrices.

    ``weights`` is a per-layer tuple of matrices; layer ``k`` maps
    :math:`v \\mapsto \\phi_k(W_k v)` with no bias term.  Hidden layers
    use the ``activation`` nonlinearity (``"tanh"`` or ``"sigmoid"``);
    the output layer always uses the overflow-safe sigmoid so the
    result stays in :math:`[0, 1]^n`, matching the unit-interval
    contracts of the L0/L3 boundary DTOs.  Saturating inputs therefore
    cannot crash or produce NaN: ``tanh`` and the logistic are bounded
    on the whole real line and on ``+-inf`` intermediates.
    """
    if not isinstance(activation, str) or activation not in _ACTIVATIONS:
        raise ValueError('activation must be "tanh" or "sigmoid"')
    if not weights:
        raise ValueError("weights must contain at least one layer")
    hidden = _ACTIVATIONS[activation]
    current = tuple(float(value) for value in x)
    _require_finite_vector(current, "mlp input")
    last_layer = len(weights) - 1
    for layer_index, matrix in enumerate(weights):
        if not matrix:
            raise ValueError(f"weight layer {layer_index} must not be empty")
        for row in matrix:
            if not isinstance(row, (tuple, list)) or not row:
                raise ValueError(
                    f"weight layer {layer_index} rows must be non-empty sequences"
                )
            if any(not math.isfinite(value) for value in row):
                raise ValueError(f"weight layer {layer_index} must be finite")
        row_width = len(matrix[0])
        if row_width != len(current):
            raise ValueError(
                f"weight layer {layer_index} expects {row_width} inputs, "
                f"got {len(current)}"
            )
        phi = sigmoid if layer_index == last_layer else hidden
        next_values: list[float] = []
        for row in matrix:
            if len(row) != row_width:
                raise ValueError(f"weight layer {layer_index} must be rectangular")
            preactivation = math.fsum(
                weight * value for weight, value in zip(row, current, strict=True)
            )
            next_values.append(phi(preactivation))
        current = tuple(next_values)
    return current


def message_passing_step(
    x: Mapping[str, tuple[float, ...]],
    edges: tuple[tuple[str, str], ...],
) -> dict[str, tuple[float, ...]]:
    """Aggregate in-neighbour mean messages over a directed graph.

    For each node ``i`` the message is

    .. math::

        m_i = \\frac{1}{|\\{j : (j, i) \\in E\\}|}
              \\sum_{j \\to i} x_j

    and the zero vector when ``i`` has no incoming edges.  This is the
    mean aggregator of a graph-convolution update with the
    neighbourhood combination left to the caller.  Unknown endpoints,
    self-loops, duplicate edges, and ragged or non-finite feature
    vectors fail fast.
    """
    if not x:
        raise ValueError("message passing requires at least one node")
    width: int | None = None
    features: dict[str, tuple[float, ...]] = {}
    for node, vector in x.items():
        if not isinstance(node, str) or not node.strip():
            raise ValueError("node ids must be non-empty strings")
        values = tuple(float(item) for item in vector)
        _require_finite_vector(values, f"features of node {node}")
        if width is None:
            width = len(values)
        elif len(values) != width:
            raise ValueError("all node feature vectors must share one width")
        features[node] = values
    assert width is not None

    incoming: dict[str, list[tuple[float, ...]]] = {node: [] for node in features}
    seen_edges: set[tuple[str, str]] = set()
    for source, target in edges:
        if source == target:
            raise ValueError("message passing rejects self-loops")
        if source not in features or target not in features:
            raise ValueError("message passing edges must connect known nodes")
        if (source, target) in seen_edges:
            raise ValueError("message passing rejects duplicate edges")
        seen_edges.add((source, target))
        incoming[target].append(features[source])

    messages: dict[str, tuple[float, ...]] = {}
    for node in features:
        sources = incoming[node]
        if not sources:
            messages[node] = (0.0,) * width
            continue
        messages[node] = tuple(
            math.fsum(vector[index] for vector in sources) / len(sources)
            for index in range(width)
        )
    return messages
