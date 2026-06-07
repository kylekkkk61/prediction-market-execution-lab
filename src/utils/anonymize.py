"""Public-sample anonymization helpers.

The functions here are intentionally small and deterministic so public sample
outputs can be regenerated without exposing raw private identifiers or exact
amounts.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any


def stable_hash(value: Any, *, prefix: str = "id", length: int = 12) -> str:
    """Return a deterministic short hash for an arbitrary private value."""

    if value is None or value == "":
        return ""
    raw = str(value).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:length]
    return f"{prefix}_{digest}"


def to_float_or_none(value: Any) -> float | None:
    """Convert common CSV values to float, returning None for blanks/invalids."""

    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def bucket_amount(value: Any) -> str:
    """Map exact monetary amounts to broad public-safe buckets."""

    amount = to_float_or_none(value)
    if amount is None:
        return "unknown"
    absolute = abs(amount)
    if absolute == 0:
        return "zero"
    if absolute < 10:
        return "lt_10"
    if absolute < 50:
        return "10_50"
    if absolute < 100:
        return "50_100"
    if absolute < 250:
        return "100_250"
    return "gte_250"


def normalize_signed_amount(value: Any, *, scale: float = 100.0) -> float | None:
    """Normalize a signed amount to reduce exact private amount exposure."""

    amount = to_float_or_none(value)
    if amount is None:
        return None
    return round(amount / scale, 4)


def safe_probability(value: Any) -> float | None:
    """Return a rounded probability in [0, 1], or None for invalid values."""

    probability = to_float_or_none(value)
    if probability is None:
        return None
    if probability < 0 or probability > 1:
        return None
    return round(probability, 6)


def safe_numeric(value: Any, *, digits: int = 6) -> float | None:
    """Return a rounded numeric value, or None for invalid values."""

    number = to_float_or_none(value)
    if number is None:
        return None
    return round(number, digits)
