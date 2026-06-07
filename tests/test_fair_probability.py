from __future__ import annotations

import math

import pytest

from models.fair_probability import (
    FairProbabilityConfig,
    blended_sigma,
    estimate_binary_probabilities,
    estimate_up_probability,
    normal_cdf,
)


def test_normal_cdf_center_is_half() -> None:
    assert normal_cdf(0.0) == pytest.approx(0.5)


def test_estimate_up_probability_is_half_at_anchor() -> None:
    probability = estimate_up_probability(
        current_price=100_000.0,
        open_anchor_price=100_000.0,
        sigma_short=0.0004,
        sigma_long=0.0002,
        remaining_seconds=120.0,
    )

    assert probability == pytest.approx(0.5)


def test_estimate_up_probability_increases_when_price_above_anchor() -> None:
    probability = estimate_up_probability(
        current_price=100_100.0,
        open_anchor_price=100_000.0,
        sigma_short=0.0004,
        sigma_long=0.0002,
        remaining_seconds=120.0,
    )

    assert probability > 0.5


def test_estimate_binary_probabilities_sum_to_one() -> None:
    up_probability, down_probability = estimate_binary_probabilities(
        current_price=99_900.0,
        open_anchor_price=100_000.0,
        sigma_short=0.0004,
        sigma_long=0.0002,
        remaining_seconds=120.0,
    )

    assert up_probability + down_probability == pytest.approx(1.0)


def test_blended_sigma_uses_variance_blend_and_floor() -> None:
    config = FairProbabilityConfig(
        sigma_short_weight=1.0,
        sigma_long_weight=0.0,
        sigma_min=0.0001,
    )

    sigma = blended_sigma(0.0003, 0.0010, config)

    assert sigma == pytest.approx(math.sqrt(0.0003**2 + 0.0001**2))


def test_estimate_up_probability_rejects_invalid_prices() -> None:
    with pytest.raises(ValueError):
        estimate_up_probability(
            current_price=0.0,
            open_anchor_price=100_000.0,
            sigma_short=0.0004,
            sigma_long=0.0002,
            remaining_seconds=120.0,
        )
