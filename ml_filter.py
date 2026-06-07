#!/usr/bin/env python3
"""LightGBM signal filter runtime helpers."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


FEATURE_NAMES = [
    "side_is_up",
    "elapsed_seconds",
    "remaining_seconds",
    "fair",
    "edge",
    "edge_after_fill",
    "bid",
    "ask",
    "spread",
    "limit_price",
    "bn_price",
    "bn_open_price",
    "bn_return_from_open",
    "sigma_short",
    "sigma_long",
    "sigma_eff",
    "tau_seconds",
    "z",
    "yes_bid",
    "yes_ask",
    "down_bid",
    "down_ask",
    "yes_mid",
    "down_mid",
    "side_cost",
    "opposite_cost",
    "total_cost",
    "is_extension_order",
    "utc_hour",
    "utc_day_of_week",
    "rolling_6_market_roi",
    "rolling_10_market_roi",
    "rolling_10_market_win_rate",
]


def optional_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value in (None, ""):
        return default
    try:
        result = float(value)
    except Exception:
        return default
    return result if math.isfinite(result) else default


def parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _mid(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2.0


def _ratio_return(price: Optional[float], anchor: Optional[float]) -> Optional[float]:
    if price is None or anchor is None or anchor <= 0:
        return None
    return (price / anchor) - 1.0


def build_live_feature_values(
    *,
    source_signal: Dict[str, Any],
    ledger: Dict[str, Any],
    signal_side: str,
    yes_bid: Optional[float],
    yes_ask: Optional[float],
    down_bid: Optional[float],
    down_ask: Optional[float],
    rolling_6_market_roi: Optional[float],
    rolling_10_market_roi: Optional[float],
    rolling_10_market_win_rate: Optional[float],
    now_dt: Optional[datetime] = None,
) -> Dict[str, Optional[float]]:
    side_is_up = 1.0 if signal_side == "UP" else 0.0
    bn_price = optional_float(source_signal.get("bn_price"))
    bn_open_price = optional_float(source_signal.get("bn_open_price"))
    yes_cost = optional_float(ledger.get("yes_cost")) or 0.0
    down_cost = optional_float(ledger.get("down_cost")) or 0.0
    side_cost = yes_cost if signal_side == "UP" else down_cost
    opposite_cost = down_cost if signal_side == "UP" else yes_cost
    dt = now_dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)

    return {
        "side_is_up": side_is_up,
        "elapsed_seconds": optional_float(source_signal.get("elapsed_seconds")),
        "remaining_seconds": optional_float(source_signal.get("remaining_seconds")),
        "fair": optional_float(source_signal.get("fair")),
        "edge": optional_float(source_signal.get("diff")),
        "edge_after_fill": optional_float(source_signal.get("edge_after_fill_estimate")),
        "bid": optional_float(source_signal.get("bid")),
        "ask": optional_float(source_signal.get("ask")),
        "spread": optional_float(source_signal.get("spread")),
        "limit_price": optional_float(source_signal.get("max_execution_price")),
        "bn_price": bn_price,
        "bn_open_price": bn_open_price,
        "bn_return_from_open": _ratio_return(bn_price, bn_open_price),
        "sigma_short": optional_float(source_signal.get("sigma_short")),
        "sigma_long": optional_float(source_signal.get("sigma_long")),
        "sigma_eff": optional_float(source_signal.get("sigma_eff")),
        "tau_seconds": optional_float(source_signal.get("tau_seconds")),
        "z": optional_float(source_signal.get("z")),
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "down_bid": down_bid,
        "down_ask": down_ask,
        "yes_mid": _mid(yes_bid, yes_ask),
        "down_mid": _mid(down_bid, down_ask),
        "side_cost": side_cost,
        "opposite_cost": opposite_cost,
        "total_cost": yes_cost + down_cost,
        "is_extension_order": 1.0 if source_signal.get("is_extension_order") else 0.0,
        "utc_hour": float(dt.hour),
        "utc_day_of_week": float(dt.weekday()),
        "rolling_6_market_roi": rolling_6_market_roi,
        "rolling_10_market_roi": rolling_10_market_roi,
        "rolling_10_market_win_rate": rolling_10_market_win_rate,
    }


@dataclass(frozen=True)
class MLFilterDecision:
    passed: bool
    predicted_ev: Optional[float]
    min_ev: float
    enabled: bool
    reason: str = ""


class MLSignalFilter:
    def __init__(
        self,
        *,
        enabled: bool,
        model_path: Path,
        features_path: Path,
        min_ev: float,
        fail_open: bool = False,
    ) -> None:
        self.enabled = enabled
        self.model_path = model_path
        self.features_path = features_path
        self.min_ev = min_ev
        self.fail_open = fail_open
        self._booster: Any = None
        self._feature_names: list[str] = []
        self._load_error: Optional[str] = None

    @property
    def feature_names(self) -> list[str]:
        return self._feature_names or FEATURE_NAMES

    def load(self) -> None:
        if not self.enabled or self._booster is not None or self._load_error:
            return
        try:
            import lightgbm as lgb  # type: ignore

            if self.features_path.exists():
                payload = json.loads(self.features_path.read_text(encoding="utf-8"))
                names = payload.get("feature_names") if isinstance(payload, dict) else None
                self._feature_names = [str(item) for item in names] if names else FEATURE_NAMES
            else:
                self._feature_names = FEATURE_NAMES
            self._booster = lgb.Booster(model_file=str(self.model_path))
        except Exception as exc:
            self._load_error = str(exc)

    def evaluate(self, features: Dict[str, Any]) -> MLFilterDecision:
        if not self.enabled:
            return MLFilterDecision(
                passed=True,
                predicted_ev=None,
                min_ev=self.min_ev,
                enabled=False,
                reason="disabled",
            )

        self.load()
        if self._booster is None:
            reason = f"model_unavailable:{self._load_error or 'unknown'}"
            return MLFilterDecision(
                passed=self.fail_open,
                predicted_ev=None,
                min_ev=self.min_ev,
                enabled=True,
                reason=reason,
            )

        try:
            row = [
                optional_float(features.get(name), float("nan"))
                for name in self.feature_names
            ]
            predicted = float(self._booster.predict([row])[0])
        except Exception as exc:
            reason = f"prediction_failed:{exc}"
            return MLFilterDecision(
                passed=self.fail_open,
                predicted_ev=None,
                min_ev=self.min_ev,
                enabled=True,
                reason=reason,
            )

        return MLFilterDecision(
            passed=predicted >= self.min_ev,
            predicted_ev=predicted,
            min_ev=self.min_ev,
            enabled=True,
            reason="" if predicted >= self.min_ev else "predicted_ev_below_threshold",
        )
