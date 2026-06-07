#!/usr/bin/env python3
"""Validate an ML filter against actual live execution attempts."""

from __future__ import annotations

import argparse
import bisect
import csv
import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import backtest_ticks as bt
from ml_filter import FEATURE_NAMES, build_live_feature_values, optional_float
from train_ml_filter import prediction_unit_for_target, require_ml_libs


@dataclass
class ModelBundle:
    model: Any
    feature_names: list[str]
    target_column: str
    prediction_unit: str


def parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def parse_day_list(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def parse_float_list(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def normalize_side(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"YES", "UP"}:
        return "UP"
    if text in {"NO", "DOWN"}:
        return "DOWN"
    return text


def parse_dt(value: Any) -> Optional[datetime]:
    return bt.parse_dt(value)


def day_from_path(path: Path) -> str:
    name = path.name[:-3] if path.name.endswith(".gz") else path.name
    return name.split(".", 1)[0]


def safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def load_model_bundle(
    *,
    lgb: Any,
    model_path: Path,
    features_path: Path,
    fallback_target_column: str,
) -> ModelBundle:
    feature_names = list(FEATURE_NAMES)
    target_column = fallback_target_column
    prediction_unit = prediction_unit_for_target(target_column)
    if features_path.exists():
        payload = json.loads(features_path.read_text(encoding="utf-8"))
        names = payload.get("feature_names") if isinstance(payload, dict) else None
        if names:
            feature_names = [str(item) for item in names]
        target_column = str(payload.get("target") or target_column)
        prediction_unit = str(
            payload.get("prediction_unit") or prediction_unit_for_target(target_column)
        )
    model = lgb.Booster(model_file=str(model_path))
    return ModelBundle(
        model=model,
        feature_names=feature_names,
        target_column=target_column,
        prediction_unit=prediction_unit,
    )


def apply_day_filters(frame: Any, args: argparse.Namespace) -> Any:
    df = frame.copy()
    day_series = df["market_day"].astype(str)
    if args.start_day:
        df = df[day_series >= args.start_day].copy()
        day_series = df["market_day"].astype(str)
    if args.end_day:
        df = df[day_series <= args.end_day].copy()
        day_series = df["market_day"].astype(str)
    include_days = parse_day_list(args.include_days)
    if include_days:
        df = df[day_series.isin(include_days)].copy()
        day_series = df["market_day"].astype(str)
    exclude_days = parse_day_list(args.exclude_days)
    if exclude_days:
        df = df[~day_series.isin(exclude_days)].copy()
    return df


def load_attempts(args: argparse.Namespace, pd: Any) -> Any:
    path = args.ledger_dir / "execution_attempts.csv"
    df = pd.read_csv(path, dtype=str).fillna("")
    df["recorded_at_dt"] = pd.to_datetime(df["recorded_at"], errors="coerce", utc=True)
    df["market_start_dt"] = pd.to_datetime(
        df["market_start_utc"], errors="coerce", utc=True
    )
    df["market_end_dt"] = pd.to_datetime(df["market_end_utc"], errors="coerce", utc=True)
    df["market_day"] = df["market_start_dt"].dt.strftime("%Y-%m-%d")
    df["order_sent_bool"] = df["order_sent"].map(parse_bool)
    df["filled_bool"] = df["filled"].map(parse_bool)
    df["dry_run_bool"] = df["dry_run"].map(parse_bool)
    df = df[
        (df["mode"] == "live")
        & (~df["dry_run_bool"])
        & (df["order_sent_bool"])
        & df["recorded_at_dt"].notna()
    ].copy()
    return apply_day_filters(df, args)


def load_orders_with_pnl(args: argparse.Namespace, pd: Any) -> Any:
    orders = pd.read_csv(args.ledger_dir / "orders.csv", dtype=str).fillna("")
    settlements = pd.read_csv(args.ledger_dir / "market_settlements.csv", dtype=str).fillna("")
    settlements = settlements[["market_slug", "resolved_side"]].drop_duplicates(
        "market_slug", keep="last"
    )
    orders["recorded_at_dt"] = pd.to_datetime(
        orders["recorded_at"], errors="coerce", utc=True
    )
    orders = orders.merge(settlements, on="market_slug", how="left")
    live = orders[
        (orders["mode"] == "live_estimated")
        & (orders["status"] == "live_success")
        & (orders["included_in_position"].map(parse_bool))
    ].copy()
    for column in [
        "amount_usd",
        "requested_amount_usd",
        "filled_amount_usd",
        "fill_ratio",
        "estimated_shares_net",
    ]:
        live[column + "_num"] = live[column].map(optional_float)
    live["entry_side"] = live["outcome_bought"].map(normalize_side)
    live["fill_cost"] = live["filled_amount_usd_num"]
    fallback_amount = live["amount_usd_num"]
    live.loc[live["fill_cost"].isna() | (live["fill_cost"] <= 0), "fill_cost"] = (
        fallback_amount
    )
    live["effective_fill_ratio"] = live["fill_ratio_num"]
    live.loc[
        live["effective_fill_ratio"].isna() & (live["fill_cost"] > 0),
        "effective_fill_ratio",
    ] = 1.0
    live["win"] = live["entry_side"] == live["resolved_side"]
    live["payout"] = live["estimated_shares_net_num"].where(live["win"], 0.0)
    live["actual_pnl"] = live["payout"].fillna(0.0) - live["fill_cost"].fillna(0.0)
    return live


def load_settlement_metrics(args: argparse.Namespace, pd: Any) -> Any:
    settlements = pd.read_csv(args.ledger_dir / "market_settlements.csv", dtype=str).fillna("")
    settlements["settled_at_dt"] = pd.to_datetime(
        settlements["settled_at"], errors="coerce", utc=True
    )
    for column in ["total_cost", "net_pnl_estimate"]:
        settlements[column + "_num"] = settlements[column].map(optional_float)
    settlements = settlements[
        settlements["settled_at_dt"].notna() & (settlements["total_cost_num"] > 0)
    ].copy()
    settlements["roi"] = settlements["net_pnl_estimate_num"] / settlements["total_cost_num"]
    settlements["is_win"] = settlements["net_pnl_estimate_num"] > 0
    return settlements.sort_values("settled_at_dt")


def rolling_metrics_before(settlements: Any, now: datetime, limit: int) -> tuple[Optional[float], Optional[float]]:
    prior = settlements[settlements["settled_at_dt"] < now]
    if prior.empty:
        return None, None
    selected = prior.tail(limit)
    return float(selected["roi"].mean()), float(selected["is_win"].mean())


def build_order_history(live_orders: Any) -> dict[str, list[dict[str, Any]]]:
    history: dict[str, list[dict[str, Any]]] = {}
    for row in live_orders.sort_values("recorded_at_dt").to_dict("records"):
        slug = str(row.get("market_slug") or "")
        history.setdefault(slug, []).append(row)
    return history


def exposure_before(
    order_history: dict[str, list[dict[str, Any]]],
    slug: str,
    now: datetime,
) -> dict[str, float]:
    yes_cost = 0.0
    down_cost = 0.0
    for row in order_history.get(slug, []):
        recorded_at = row.get("recorded_at_dt")
        if recorded_at is None or recorded_at >= now:
            break
        cost = optional_float(row.get("fill_cost")) or 0.0
        if row.get("entry_side") == "UP":
            yes_cost += cost
        elif row.get("entry_side") == "DOWN":
            down_cost += cost
    return {"yes_cost": yes_cost, "down_cost": down_cost}


def load_quote_index(
    *,
    args: argparse.Namespace,
    target_slugs: set[str],
    target_days: set[str],
) -> dict[str, dict[str, list[Any]]]:
    quote_index: dict[str, dict[str, list[Any]]] = {}
    for path in bt.iter_snapshot_paths(args.snapshot_dir, args.snapshot_glob):
        if day_from_path(path) not in target_days:
            continue
        with bt.open_snapshot_text(path) as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    item = json.loads(text)
                except json.JSONDecodeError:
                    continue
                slug = str(item.get("market_slug") or "")
                if slug not in target_slugs:
                    continue
                ts = parse_dt(item.get("ts"))
                if ts is None:
                    continue
                values = {
                    "yes_bid": optional_float(item.get("yes_bid")),
                    "yes_ask": optional_float(item.get("yes_ask")),
                    "down_bid": optional_float(item.get("down_bid")),
                    "down_ask": optional_float(item.get("down_ask")),
                }
                if any(value is None for value in values.values()):
                    continue
                bucket = quote_index.setdefault(slug, {"ts": [], "values": []})
                bucket["ts"].append(ts)
                bucket["values"].append(values)
    return quote_index


def quote_at_or_before(
    quote_index: dict[str, dict[str, list[Any]]],
    slug: str,
    now: datetime,
) -> dict[str, Optional[float]]:
    bucket = quote_index.get(slug)
    if not bucket:
        return {"yes_bid": None, "yes_ask": None, "down_bid": None, "down_ask": None}
    idx = bisect.bisect_right(bucket["ts"], now) - 1
    if idx < 0:
        idx = 0
    return dict(bucket["values"][idx])


def source_signal_from_attempt(row: dict[str, Any]) -> dict[str, Any]:
    recorded_at = row.get("recorded_at_dt")
    market_end = row.get("market_end_dt")
    remaining_seconds = None
    if recorded_at is not None and market_end is not None:
        remaining_seconds = (market_end - recorded_at).total_seconds()
    return {
        "elapsed_seconds": optional_float(row.get("elapsed_seconds")),
        "remaining_seconds": remaining_seconds,
        "fair": optional_float(row.get("signal_fair")),
        "diff": optional_float(row.get("signal_edge")),
        "edge_after_fill_estimate": optional_float(
            row.get("signal_edge_after_fill_estimate")
        ),
        "bid": optional_float(row.get("signal_bid")),
        "ask": optional_float(row.get("signal_ask")),
        "spread": optional_float(row.get("signal_spread")),
        "max_execution_price": optional_float(row.get("limit_price")),
        "bn_price": optional_float(row.get("bn_price")),
        "bn_open_price": optional_float(row.get("bn_open_price")),
        "sigma_short": optional_float(row.get("sigma_short")),
        "sigma_long": optional_float(row.get("sigma_long")),
        "sigma_eff": optional_float(row.get("sigma_eff")),
        "tau_seconds": optional_float(row.get("tau_seconds")),
        "z": optional_float(row.get("z")),
        "is_extension_order": parse_bool(row.get("is_extension_order")),
    }


def score_attempts(
    *,
    args: argparse.Namespace,
    lgb: Any,
    attempts: Any,
    live_orders: Any,
    settlements: Any,
    quote_index: dict[str, dict[str, list[Any]]],
) -> Any:
    model_cache: dict[str, ModelBundle] = {}
    order_history = build_order_history(live_orders)
    order_pnl = live_orders.drop_duplicates("response_order_id", keep="last").set_index(
        "response_order_id"
    )
    details: list[dict[str, Any]] = []

    fixed_bundle: Optional[ModelBundle] = None
    if args.model_path:
        fixed_bundle = load_model_bundle(
            lgb=lgb,
            model_path=args.model_path,
            features_path=args.features_path,
            fallback_target_column=args.target_column,
        )

    for row in attempts.sort_values("recorded_at_dt").to_dict("records"):
        day = str(row.get("market_day") or "")
        bundle = fixed_bundle
        if bundle is None:
            model_path = args.model_cache_dir / day / "model.txt"
            features_path = args.model_cache_dir / day / "features.json"
            if not model_path.exists():
                continue
            if day not in model_cache:
                model_cache[day] = load_model_bundle(
                    lgb=lgb,
                    model_path=model_path,
                    features_path=features_path,
                    fallback_target_column=args.target_column,
                )
            bundle = model_cache[day]

        recorded_at = row["recorded_at_dt"].to_pydatetime()
        slug = str(row.get("market_slug") or "")
        side = normalize_side(row.get("side"))
        quote = quote_at_or_before(quote_index, slug, recorded_at)
        exposure = exposure_before(order_history, slug, recorded_at)
        rolling_6_roi, _ = rolling_metrics_before(settlements, recorded_at, 6)
        rolling_10_roi, rolling_10_win_rate = rolling_metrics_before(
            settlements, recorded_at, 10
        )
        features = build_live_feature_values(
            source_signal=source_signal_from_attempt(row),
            ledger=exposure,
            signal_side=side,
            yes_bid=quote["yes_bid"],
            yes_ask=quote["yes_ask"],
            down_bid=quote["down_bid"],
            down_ask=quote["down_ask"],
            rolling_6_market_roi=rolling_6_roi,
            rolling_10_market_roi=rolling_10_roi,
            rolling_10_market_win_rate=rolling_10_win_rate,
            now_dt=recorded_at,
        )
        feature_row = [
            optional_float(features.get(name), float("nan"))
            for name in bundle.feature_names
        ]
        predicted = float(bundle.model.predict([feature_row])[0])

        response_order_id = str(row.get("response_order_id") or "")
        pnl_row = (
            order_pnl.loc[response_order_id].to_dict()
            if response_order_id and response_order_id in order_pnl.index
            else {}
        )
        fill_cost = optional_float(pnl_row.get("fill_cost")) or 0.0
        actual_pnl = optional_float(pnl_row.get("actual_pnl"))
        effective_fill_ratio = optional_float(pnl_row.get("effective_fill_ratio"))
        win = pnl_row.get("win")
        filled = bool(pnl_row) or parse_bool(row.get("filled"))
        details.append(
            {
                "recorded_at": row.get("recorded_at"),
                "market_day": day,
                "market_slug": slug,
                "side": side,
                "order_type": row.get("order_type"),
                "exec_price_mode": row.get("exec_price_mode"),
                "amount_usd": optional_float(row.get("amount_usd")),
                "status": row.get("status"),
                "filled": filled,
                "response_order_id": response_order_id,
                "fill_cost": fill_cost,
                "actual_pnl": actual_pnl if actual_pnl is not None else 0.0,
                "win": bool(win) if win != "" else False,
                "effective_fill_ratio": effective_fill_ratio,
                "old_ml_predicted_ev": optional_float(row.get("ml_predicted_ev")),
                "old_ml_min_ev": optional_float(row.get("ml_min_ev")),
                "new_ml_predicted_ev": predicted,
                "target_column": bundle.target_column,
                "prediction_unit": bundle.prediction_unit,
                "quote_available": all(value is not None for value in quote.values()),
                "yes_bid": quote["yes_bid"],
                "yes_ask": quote["yes_ask"],
                "down_bid": quote["down_bid"],
                "down_ask": quote["down_ask"],
                "side_cost": features.get("side_cost"),
                "opposite_cost": features.get("opposite_cost"),
                "total_cost": features.get("total_cost"),
                "rolling_6_market_roi": rolling_6_roi,
                "rolling_10_market_roi": rolling_10_roi,
                "rolling_10_market_win_rate": rolling_10_win_rate,
            }
        )
    _, pd, _, _ = require_ml_libs()
    return pd.DataFrame(details)


def summarize(details: Any, thresholds: list[float], pd: Any) -> tuple[Any, Any]:
    rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []

    def metrics(frame: Any) -> dict[str, Any]:
        filled = frame[frame["filled"]].copy()
        pnl_values = [float(item) for item in filled.sort_values("recorded_at")["actual_pnl"]]
        fill_cost = float(filled["fill_cost"].sum())
        pnl = float(filled["actual_pnl"].sum())
        return {
            "sent_orders": int(len(frame)),
            "filled_orders": int(len(filled)),
            "fill_rate": safe_ratio(len(filled), len(frame)),
            "filled_amount_usd": fill_cost,
            "actual_pnl": pnl,
            "actual_roi": safe_ratio(pnl, fill_cost),
            "wins": int(filled["win"].sum()) if not filled.empty else 0,
            "losses": int(len(filled) - int(filled["win"].sum())) if not filled.empty else 0,
            "win_rate": float(filled["win"].mean()) if not filled.empty else 0.0,
            "avg_fill_ratio": float(filled["effective_fill_ratio"].mean())
            if not filled.empty
            else 0.0,
            "max_drawdown": max_drawdown(pnl_values),
        }

    total = len(details)
    all_metrics = metrics(details)
    rows.append(
        {
            "threshold": "all_sent",
            "threshold_value": "",
            "skipped_by_new_ml": 0,
            **all_metrics,
        }
    )
    for threshold in thresholds:
        selected = details[details["new_ml_predicted_ev"] >= threshold].copy()
        rows.append(
            {
                "threshold": f">={threshold:g}",
                "threshold_value": threshold,
                "skipped_by_new_ml": int(total - len(selected)),
                **metrics(selected),
            }
        )

    for day, group in details.groupby("market_day", sort=True):
        day_total = len(group)
        daily_rows.append(
            {
                "market_day": day,
                "threshold": "all_sent",
                "threshold_value": "",
                "skipped_by_new_ml": 0,
                **metrics(group),
            }
        )
        for threshold in thresholds:
            selected = group[group["new_ml_predicted_ev"] >= threshold].copy()
            daily_rows.append(
                {
                    "market_day": day,
                    "threshold": f">={threshold:g}",
                    "threshold_value": threshold,
                    "skipped_by_new_ml": int(day_total - len(selected)),
                    **metrics(selected),
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(daily_rows)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate an ML model against actual live execution attempts."
    )
    parser.add_argument("--ledger-dir", type=Path, default=Path("ledger"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("tick_snapshots"))
    parser.add_argument("--snapshot-glob", default="*.jsonl*")
    parser.add_argument("--start-day", default="")
    parser.add_argument("--end-day", default="")
    parser.add_argument("--include-days", default="")
    parser.add_argument("--exclude-days", default="")
    parser.add_argument("--thresholds", default="0,0.05,0.10,0.20,0.30,0.50,1.00")
    parser.add_argument("--target-column", default="single_order_pnl_per_usd")
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--features-path", type=Path)
    parser.add_argument(
        "--model-cache-dir",
        type=Path,
        default=Path("analysis/ml_walkforward_tick_models_per_usd_mixed_1u_defaultcap"),
    )
    parser.add_argument(
        "--detail-output-csv",
        type=Path,
        default=Path("analysis/live_ml_execution_validation_details.csv"),
    )
    parser.add_argument(
        "--summary-output-csv",
        type=Path,
        default=Path("analysis/live_ml_execution_validation_summary.csv"),
    )
    parser.add_argument(
        "--daily-output-csv",
        type=Path,
        default=Path("analysis/live_ml_execution_validation_daily.csv"),
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    if args.model_path and not args.features_path:
        raise SystemExit("--features-path is required when --model-path is used.")
    lgb, pd, _, _ = require_ml_libs()
    attempts = load_attempts(args, pd)
    if attempts.empty:
        raise SystemExit("No live sent attempts matched the filters.")
    live_orders = load_orders_with_pnl(args, pd)
    settlements = load_settlement_metrics(args, pd)
    target_slugs = set(str(item) for item in attempts["market_slug"].dropna().unique())
    target_days = set(str(item) for item in attempts["market_day"].dropna().unique())
    quote_index = load_quote_index(
        args=args,
        target_slugs=target_slugs,
        target_days=target_days,
    )
    details = score_attempts(
        args=args,
        lgb=lgb,
        attempts=attempts,
        live_orders=live_orders,
        settlements=settlements,
        quote_index=quote_index,
    )
    if details.empty:
        raise SystemExit("No attempts could be scored. Check model cache coverage.")
    thresholds = parse_float_list(args.thresholds)
    summary, daily = summarize(details, thresholds, pd)

    args.detail_output_csv.parent.mkdir(parents=True, exist_ok=True)
    details.to_csv(args.detail_output_csv, index=False)
    summary.to_csv(args.summary_output_csv, index=False)
    daily.to_csv(args.daily_output_csv, index=False)
    print(f"Scored attempts: {len(details)}")
    print(f"Wrote details: {args.detail_output_csv}")
    print(f"Wrote summary: {args.summary_output_csv}")
    print(f"Wrote daily: {args.daily_output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
