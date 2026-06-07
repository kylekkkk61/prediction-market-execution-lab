"""Fair-probability utilities for short-horizon binary prediction markets.

The functions in this module are intentionally research-oriented and contain no
order placement, wallet, or live execution logic.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class FairProbabilityConfig:
    """Configuration for the BTC reference-price fair-probability model.

    The model treats the event as a binary question: whether the reference price
    will finish above the market's opening anchor. Volatility inputs are expected
    to be expressed in the same time unit as ``remaining_seconds``.
    """

    sigma_short_weight: float = 0.7
    sigma_long_weight: float = 0.3
    sigma_min: float = 0.00001
    tau_floor_seconds: float = 1.0
    z_cap: float = 8.0


def normal_cdf(x: float) -> float:
    """Return the standard normal cumulative distribution value."""

    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def blended_sigma(
    sigma_short: float,
    sigma_long: float,
    config: FairProbabilityConfig | None = None,
) -> float:
    """Blend short- and long-window volatility estimates.

    The blend follows the legacy replay logic: normalize the configured weights,
    combine variances, and add a small variance floor.
    """

    cfg = config or FairProbabilityConfig()
    weight_sum = cfg.sigma_short_weight + cfg.sigma_long_weight
    if weight_sum <= 0:
        short_weight = 1.0
        long_weight = 0.0
    else:
        short_weight = cfg.sigma_short_weight / weight_sum
        long_weight = cfg.sigma_long_weight / weight_sum

    return math.sqrt(
        short_weight * sigma_short**2
        + long_weight * sigma_long**2
        + cfg.sigma_min**2
    )


def estimate_up_probability(
    *,
    current_price: float,
    open_anchor_price: float,
    sigma_short: float,
    sigma_long: float,
    remaining_seconds: float,
    config: FairProbabilityConfig | None = None,
) -> float:
    """Estimate the fair probability that the reference price finishes above anchor.

    This is a compact extraction of the replay model used in the legacy research
    scripts. It is suitable for notebooks, reports, and dry-run analysis.
    """

    cfg = config or FairProbabilityConfig()
    if current_price <= 0:
        raise ValueError("current_price must be positive")
    if open_anchor_price <= 0:
        raise ValueError("open_anchor_price must be positive")
    if remaining_seconds < 0:
        raise ValueError("remaining_seconds must be non-negative")

    sigma_eff = blended_sigma(sigma_short, sigma_long, cfg)
    tau = max(remaining_seconds, cfg.tau_floor_seconds)
    if sigma_eff <= 0 or tau <= 0:
        raise ValueError("effective volatility and time horizon must be positive")

    z_score = math.log(current_price / open_anchor_price) / (sigma_eff * math.sqrt(tau))
    capped_z = max(min(z_score, cfg.z_cap), -cfg.z_cap)
    return normal_cdf(capped_z)


def estimate_binary_probabilities(
    *,
    current_price: float,
    open_anchor_price: float,
    sigma_short: float,
    sigma_long: float,
    remaining_seconds: float,
    config: FairProbabilityConfig | None = None,
) -> tuple[float, float]:
    """Return ``(up_probability, down_probability)`` for a binary market."""

    up_probability = estimate_up_probability(
        current_price=current_price,
        open_anchor_price=open_anchor_price,
        sigma_short=sigma_short,
        sigma_long=sigma_long,
        remaining_seconds=remaining_seconds,
        config=config,
    )
    return up_probability, 1.0 - up_probability
