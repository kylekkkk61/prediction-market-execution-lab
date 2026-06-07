#!/usr/bin/env python3
"""Train a LightGBM EV model for the signal filter."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml_filter import FEATURE_NAMES


def require_ml_libs():
    try:
        import lightgbm as lgb  # type: ignore
        import pandas as pd  # type: ignore
        from sklearn.metrics import mean_absolute_error, mean_squared_error  # type: ignore
    except Exception as exc:
        raise SystemExit(
            "Missing ML dependencies. Install them with: "
            "python3 -m pip install -r requirements-ml.txt\n"
            f"Original error: {exc}"
        )
    return lgb, pd, mean_absolute_error, mean_squared_error


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
            "orders": 0,
            "traded_markets": 0,
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
        "orders": int(len(frame)),
        "traded_markets": int(frame["market_slug"].nunique()),
        "total_cost": total_cost,
        "total_pnl": total_pnl,
        "roi": total_pnl / total_cost if total_cost > 0 else 0.0,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / (wins + losses) if wins + losses > 0 else 0.0,
        "max_drawdown": max_drawdown(list(market_pnl)),
    }


def prediction_unit_for_target(target_column: str) -> str:
    if target_column.endswith("_per_usd"):
        return "pnl_per_usd"
    return "usdc"


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
    model.fit(train_df[feature_names], train_df[args.target_column])
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


def write_feature_metadata(path: Path, feature_names: list[str], args: argparse.Namespace) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_type": "lightgbm_regressor",
        "target": args.target_column,
        "prediction_unit": prediction_unit_for_target(args.target_column),
        "feature_names": feature_names,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "params": {
            "n_estimators": args.n_estimators,
            "learning_rate": args.learning_rate,
            "num_leaves": args.num_leaves,
            "min_child_samples": args.min_child_samples,
            "subsample": args.subsample,
            "colsample_bytree": args.colsample_bytree,
            "random_state": args.random_state,
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_walkforward(
    *,
    lgb: Any,
    pd: Any,
    df: Any,
    feature_names: list[str],
    args: argparse.Namespace,
    mean_absolute_error: Any,
    mean_squared_error: Any,
) -> Any:
    rows = []
    days = sorted(str(day) for day in df["market_day"].dropna().unique())
    for idx, day in enumerate(days):
        train_days = days[:idx]
        if len(train_days) < args.min_train_days:
            continue
        train_df = df[df["market_day"].isin(train_days)].copy()
        test_df = df[df["market_day"] == day].copy()
        if train_df.empty or test_df.empty:
            continue
        model = train_model(lgb, train_df, feature_names, args)
        predictions = model.predict(test_df[feature_names])
        test_df["predicted_order_ev"] = predictions
        baseline = aggregate_orders(test_df)
        mae = float(mean_absolute_error(test_df[args.target_column], predictions))
        rmse = float(mean_squared_error(test_df[args.target_column], predictions) ** 0.5)
        rows.append(
            {
                "segment": day,
                "filter_type": "baseline",
                "target_column": args.target_column,
                "prediction_unit": prediction_unit_for_target(args.target_column),
                "threshold": "",
                "mae": mae,
                "rmse": rmse,
                "skipped_by_ml": 0,
                **baseline,
            }
        )
        for threshold in args.ev_thresholds:
            selected = test_df[test_df["predicted_order_ev"] >= threshold]
            metrics = aggregate_orders(selected)
            rows.append(
                {
                    "segment": day,
                    "filter_type": "ev_threshold",
                    "target_column": args.target_column,
                    "prediction_unit": prediction_unit_for_target(args.target_column),
                    "threshold": threshold,
                    "mae": mae,
                    "rmse": rmse,
                    "skipped_by_ml": int(len(test_df) - len(selected)),
                    **metrics,
                }
            )
        for keep_fraction in args.keep_fractions:
            if not 0 < keep_fraction <= 1:
                continue
            threshold = float(test_df["predicted_order_ev"].quantile(1.0 - keep_fraction))
            selected = test_df[test_df["predicted_order_ev"] >= threshold]
            metrics = aggregate_orders(selected)
            rows.append(
                {
                    "segment": day,
                    "filter_type": "keep_fraction",
                    "target_column": args.target_column,
                    "prediction_unit": prediction_unit_for_target(args.target_column),
                    "threshold": keep_fraction,
                    "mae": mae,
                    "rmse": rmse,
                    "skipped_by_ml": int(len(test_df) - len(selected)),
                    **metrics,
                }
            )
    return pd.DataFrame(rows)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train a LightGBM signal filter.")
    parser.add_argument("--dataset-csv", type=Path, default=Path("analysis/ml_signal_dataset.csv"))
    parser.add_argument("--model-output", type=Path, default=Path("models/signal_filter_lgbm_v1.txt"))
    parser.add_argument("--features-output", type=Path, default=Path("models/signal_filter_lgbm_v1_features.json"))
    parser.add_argument("--walkforward-output", type=Path, default=Path("analysis/ml_filter_walkforward_report.csv"))
    parser.add_argument("--feature-importance-output", type=Path, default=Path("analysis/ml_filter_feature_importance.csv"))
    parser.add_argument("--min-train-days", type=int, default=2)
    parser.add_argument("--start-day", default="")
    parser.add_argument("--end-day", default="")
    parser.add_argument("--include-days", default="")
    parser.add_argument("--exclude-days", default="")
    parser.add_argument(
        "--target-column",
        choices=["single_order_pnl", "single_order_pnl_per_usd"],
        default="single_order_pnl",
    )
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
    args.ev_thresholds = [float(item) for item in args.ev_thresholds.split(",") if item.strip()]
    args.keep_fractions = [float(item) for item in args.keep_fractions.split(",") if item.strip()]
    lgb, pd, mean_absolute_error, mean_squared_error = require_ml_libs()
    df = pd.read_csv(args.dataset_csv)
    missing = [name for name in FEATURE_NAMES if name not in df.columns]
    if missing:
        raise SystemExit(f"Dataset is missing feature columns: {missing}")
    if args.target_column not in df.columns:
        raise SystemExit(f"Dataset is missing target column: {args.target_column}")
    df = df.sort_values(["market_start_utc", "recorded_at"]).reset_index(drop=True)
    df = apply_day_filters(df, args)
    if df.empty:
        raise SystemExit("Dataset is empty after day filters.")
    feature_names = list(FEATURE_NAMES)

    walkforward = run_walkforward(
        lgb=lgb,
        pd=pd,
        df=df,
        feature_names=feature_names,
        args=args,
        mean_absolute_error=mean_absolute_error,
        mean_squared_error=mean_squared_error,
    )
    args.walkforward_output.parent.mkdir(parents=True, exist_ok=True)
    walkforward.to_csv(args.walkforward_output, index=False)

    model = train_model(lgb, df, feature_names, args)
    args.model_output.parent.mkdir(parents=True, exist_ok=True)
    model.booster_.save_model(str(args.model_output))
    write_feature_metadata(args.features_output, feature_names, args)

    importance = pd.DataFrame(
        {
            "feature": feature_names,
            "importance": model.booster_.feature_importance(importance_type="gain"),
        }
    ).sort_values("importance", ascending=False)
    args.feature_importance_output.parent.mkdir(parents=True, exist_ok=True)
    importance.to_csv(args.feature_importance_output, index=False)

    print(f"Wrote model: {args.model_output}")
    print(f"Wrote features: {args.features_output}")
    print(f"Wrote walk-forward report: {args.walkforward_output}")
    print(f"Wrote feature importance: {args.feature_importance_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
