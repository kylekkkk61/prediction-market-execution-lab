#!/usr/bin/env python3
"""Walk-forward backtest for the LightGBM signal filter."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any

from ml_filter import FEATURE_NAMES


def require_ml_libs():
    try:
        import lightgbm as lgb  # type: ignore
        import pandas as pd  # type: ignore
    except Exception as exc:
        raise SystemExit(
            "Missing ML dependencies. Install them with: "
            "python3 -m pip install -r requirements-ml.txt\n"
            f"Original error: {exc}"
        )
    return lgb, pd


def max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def aggregate_orders(frame: Any) -> dict[str, float]:
    if frame.empty:
        return {
            "traded_markets": 0,
            "orders": 0,
            "total_cost": 0.0,
            "total_pnl": 0.0,
            "roi": 0.0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
        }
    market_pnl = frame.groupby("market_slug", sort=False)["single_order_pnl"].sum()
    total_cost = float(frame["amount_usd"].sum())
    total_pnl = float(frame["single_order_pnl"].sum())
    wins = int((market_pnl > 0).sum())
    losses = int((market_pnl <= 0).sum())
    return {
        "traded_markets": int(frame["market_slug"].nunique()),
        "orders": int(len(frame)),
        "total_cost": total_cost,
        "total_pnl": total_pnl,
        "roi": total_pnl / total_cost if total_cost > 0 else 0.0,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / (wins + losses) if wins + losses else 0.0,
        "max_drawdown": max_drawdown(list(market_pnl)),
    }


def train_model(lgb: Any, train_df: Any, feature_names: list[str], args: argparse.Namespace) -> Any:
    model = lgb.LGBMRegressor(
        objective="regression",
        n_estimators=args.n_estimators,
        learning_rate=args.learning_rate,
        num_leaves=args.num_leaves,
        min_child_samples=args.min_child_samples,
        subsample=args.subsample,
        colsample_bytree=args.colsample_bytree,
        random_state=args.random_state,
        n_jobs=args.n_jobs,
        verbosity=-1,
    )
    model.fit(train_df[feature_names], train_df["single_order_pnl"])
    return model


def parse_day_list(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


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


def append_daily_result(
    rows: list[dict[str, Any]],
    *,
    segment: str,
    strategy: str,
    threshold_type: str,
    threshold_value: Any,
    baseline_orders: int,
    selected: Any,
) -> None:
    metrics = aggregate_orders(selected)
    rows.append(
        {
            "segment": segment,
            "strategy": strategy,
            "threshold_type": threshold_type,
            "threshold_value": threshold_value,
            "baseline_orders": baseline_orders,
            "skipped_by_ml": int(baseline_orders - metrics["orders"]),
            **metrics,
        }
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backtest a LightGBM signal filter with day-level walk-forward.")
    parser.add_argument("--dataset-csv", type=Path, default=Path("analysis/ml_signal_dataset.csv"))
    parser.add_argument("--output-csv", type=Path, default=Path("analysis/backtest_ml_filter_walkforward.csv"))
    parser.add_argument("--daily-output-csv", type=Path, default=Path("analysis/backtest_ml_filter_daily.csv"))
    parser.add_argument("--min-train-days", type=int, default=2)
    parser.add_argument("--start-day", default="")
    parser.add_argument("--end-day", default="")
    parser.add_argument("--include-days", default="")
    parser.add_argument("--exclude-days", default="")
    parser.add_argument("--ev-thresholds", default="-0.05,0,0.05,0.10,0.15")
    parser.add_argument("--keep-fractions", default="0.3,0.5,0.7")
    parser.add_argument("--n-estimators", type=int, default=300)
    parser.add_argument("--learning-rate", type=float, default=0.03)
    parser.add_argument("--num-leaves", type=int, default=31)
    parser.add_argument("--min-child-samples", type=int, default=50)
    parser.add_argument("--subsample", type=float, default=0.9)
    parser.add_argument("--colsample-bytree", type=float, default=0.9)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--n-jobs", type=int, default=-1)
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    ev_thresholds = [float(item) for item in args.ev_thresholds.split(",") if item.strip()]
    keep_fractions = [float(item) for item in args.keep_fractions.split(",") if item.strip()]
    lgb, pd = require_ml_libs()
    df = pd.read_csv(args.dataset_csv)
    missing = [name for name in FEATURE_NAMES if name not in df.columns]
    if missing:
        raise SystemExit(f"Dataset is missing feature columns: {missing}")
    df = df.sort_values(["market_start_utc", "recorded_at"]).reset_index(drop=True)
    df = apply_day_filters(df, args)
    if df.empty:
        raise SystemExit("Dataset is empty after day filters.")
    feature_names = list(FEATURE_NAMES)
    days = sorted(str(day) for day in df["market_day"].dropna().unique())

    daily_rows: list[dict[str, Any]] = []
    selected_by_strategy: dict[str, list[Any]] = defaultdict(list)

    for idx, day in enumerate(days):
        train_days = days[:idx]
        if len(train_days) < args.min_train_days:
            continue
        train_df = df[df["market_day"].isin(train_days)].copy()
        test_df = df[df["market_day"] == day].copy()
        if train_df.empty or test_df.empty:
            continue

        model = train_model(lgb, train_df, feature_names, args)
        test_df["predicted_order_ev"] = model.predict(test_df[feature_names])
        baseline_orders = len(test_df)

        append_daily_result(
            daily_rows,
            segment=day,
            strategy="baseline",
            threshold_type="none",
            threshold_value="",
            baseline_orders=baseline_orders,
            selected=test_df,
        )
        selected_by_strategy["baseline"].append(test_df)

        for threshold in ev_thresholds:
            selected = test_df[test_df["predicted_order_ev"] >= threshold].copy()
            strategy = f"ev>={threshold:g}"
            append_daily_result(
                daily_rows,
                segment=day,
                strategy=strategy,
                threshold_type="ev_threshold",
                threshold_value=threshold,
                baseline_orders=baseline_orders,
                selected=selected,
            )
            selected_by_strategy[strategy].append(selected)

        for keep_fraction in keep_fractions:
            if not 0 < keep_fraction <= 1:
                continue
            threshold = float(test_df["predicted_order_ev"].quantile(1.0 - keep_fraction))
            selected = test_df[test_df["predicted_order_ev"] >= threshold].copy()
            strategy = f"keep_top_{keep_fraction:g}"
            append_daily_result(
                daily_rows,
                segment=day,
                strategy=strategy,
                threshold_type="keep_fraction",
                threshold_value=keep_fraction,
                baseline_orders=baseline_orders,
                selected=selected,
            )
            selected_by_strategy[strategy].append(selected)

    daily = pd.DataFrame(daily_rows)
    if daily.empty:
        raise SystemExit("No walk-forward rows produced. Check dataset and --min-train-days.")

    combined_rows = []
    for strategy, frames in selected_by_strategy.items():
        combined = pd.concat(frames, ignore_index=True) if frames else df.iloc[0:0].copy()
        metrics = aggregate_orders(combined)
        day_rows = daily[daily["strategy"] == strategy]
        combined_rows.append(
            {
                "segment": "combined",
                "strategy": strategy,
                "day_count": int(day_rows["segment"].nunique()),
                "median_day_roi": float(day_rows["roi"].median()),
                "worst_day_roi": float(day_rows["roi"].min()),
                "best_day_roi": float(day_rows["roi"].max()),
                "skipped_by_ml": int(day_rows["skipped_by_ml"].sum()),
                **metrics,
            }
        )

    summary = pd.DataFrame(combined_rows).sort_values(
        ["roi", "total_pnl"], ascending=False
    )
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.output_csv, index=False)
    args.daily_output_csv.parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(args.daily_output_csv, index=False)
    print(f"Wrote combined walk-forward CSV: {args.output_csv}")
    print(f"Wrote daily walk-forward CSV: {args.daily_output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
