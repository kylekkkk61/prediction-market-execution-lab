#!/usr/bin/env python3
"""Day-level walk-forward LightGBM backtest using full tick replay."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

import backtest_ticks as bt
from ml_filter import FEATURE_NAMES
from train_ml_filter import prediction_unit_for_target, require_ml_libs, train_model


def parse_day_list(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def parse_float_list(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def next_day(day: str) -> str:
    dt = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    return (dt + timedelta(days=1)).date().isoformat()


def validate_model_cache_dir(path: Path) -> None:
    cache_dir = path.resolve()
    live_models_dir = Path("models").resolve()
    if cache_dir == live_models_dir or live_models_dir in cache_dir.parents:
        raise SystemExit(
            "--model-cache-dir must not point to models/ or a subdirectory of models/. "
            "Walk-forward models are research artifacts and must not overwrite live models."
        )


def write_features_metadata(
    *,
    path: Path,
    feature_names: list[str],
    args: argparse.Namespace,
    train_days: Sequence[str],
    test_day: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_type": "lightgbm_regressor",
        "target": args.target_column,
        "prediction_unit": prediction_unit_for_target(args.target_column),
        "feature_names": feature_names,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "walkforward": {
            "test_day": test_day,
            "train_days": list(train_days),
        },
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


def load_filtered_dataset(args: argparse.Namespace, pd: Any) -> Any:
    df = pd.read_csv(args.dataset_csv)
    missing = [name for name in FEATURE_NAMES if name not in df.columns]
    if missing:
        raise SystemExit(f"Dataset is missing feature columns: {missing}")
    if args.target_column not in df.columns:
        raise SystemExit(f"Dataset is missing target column: {args.target_column}")
    df = df.sort_values(["market_start_utc", "recorded_at"]).reset_index(drop=True)
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
    if df.empty:
        raise SystemExit("Dataset is empty after day filters.")
    return df


def base_replay_config(args: argparse.Namespace) -> bt.ReplayConfig:
    return bt.ReplayConfig(
        edge_prob_threshold=args.edge_prob_threshold,
        edge_reference_price=args.edge_reference_price,
        max_spread=args.max_spread,
        min_entry_ask_price=args.min_entry_ask_price,
        min_edge_after_fill=args.min_edge_after_fill,
        exec_slippage_ticks=args.exec_slippage_ticks,
        exec_price_mode=args.exec_price_mode,
        exec_price_cap=args.exec_price_cap,
        tick_size=args.tick_size,
        trade_amount_usd=args.trade_amount_usd,
        order_cooldown_seconds=args.order_cooldown_seconds,
        signal_cooldown_seconds=args.signal_cooldown_seconds,
        market_max_total_cost=args.market_max_total_cost,
        market_max_side_cost=args.market_max_side_cost,
        side_extension_enabled=args.side_extension_enabled,
        side_extension_start_cost=args.side_extension_start_cost,
        side_extension_max_side_cost=args.side_extension_max_side_cost,
        side_extension_min_seconds=args.side_extension_min_seconds,
        side_extension_cooldown_seconds=args.side_extension_cooldown_seconds,
        side_extension_min_edge=args.side_extension_min_edge,
        side_extension_min_edge_after_fill=args.side_extension_min_edge_after_fill,
        side_extension_min_ask_price=args.side_extension_min_ask_price,
        side_extension_max_ask_price=args.side_extension_max_ask_price,
        side_extension_max_opposite_cost=args.side_extension_max_opposite_cost,
        fair_mode=args.fair_mode,
        sigma_short_weight=args.sigma_short_weight,
        sigma_long_weight=args.sigma_long_weight,
        sigma_min=args.sigma_min,
        tau_floor_seconds=args.tau_floor_seconds,
        z_cap=args.z_cap,
        entry_time_windows=(),
        block_time_windows=(),
        tail_reversal_lookback_seconds=0.0,
        tail_reversal_trigger_count=0,
        tail_reversal_cooldown_seconds=0.0,
        tail_reversal_min_anchor_prob=0.55,
        tail_reversal_min_prob_drop=0.10,
        tail_reversal_min_mid_gain=0.03,
        ml_filter_enabled=False,
        ml_model_path=Path(""),
        ml_features_path=Path(""),
        ml_min_ev=0.0,
        ml_fail_open=False,
    )


def snapshot_paths_for_test_day(snapshot_dir: Path, test_day: str) -> list[Path]:
    wanted = {test_day, next_day(test_day)}
    paths: list[Path] = []
    for path in bt.iter_snapshot_paths(snapshot_dir, "*.jsonl*"):
        identity = path.name[:-3] if path.name.endswith(".gz") else path.name
        day = identity.split(".", 1)[0]
        if day in wanted:
            paths.append(path)
    return paths


def replay_test_day(
    *,
    args: argparse.Namespace,
    settlements: dict[str, bt.Settlement],
    test_day: str,
    configs: Sequence[bt.ReplayConfig],
) -> tuple[list[bt.ReplayResult], int, int]:
    runners = [
        bt.ReplayRunner(settlements=settlements, tail_profiles={}, cfg=cfg)
        for cfg in configs
    ]
    stats = bt.SnapshotLoadStats()
    active_slugs: set[str] = set()
    loaded_rows = 0
    source_mode = (
        "all" if args.evaluate_sources.strip().lower() == "all" else "selected"
    )
    evaluate_sources = set(
        bt.DEFAULT_EVALUATE_SOURCES
        if source_mode == "all"
        else bt.parse_str_list(args.evaluate_sources)
    )

    for path in snapshot_paths_for_test_day(args.snapshot_dir, test_day):
        snapshots = bt.load_snapshots_for_path(
            path=path,
            settlements=settlements,
            evaluate_sources=evaluate_sources,
            source_mode=source_mode,
            strict_jsonl=args.strict_jsonl,
            stats=stats,
        )
        for snapshot in snapshots:
            day = bt.market_day_from_row(snapshot)
            if day != test_day:
                continue
            loaded_rows += 1
            slug = str(snapshot.get("market_slug") or "")
            if slug:
                active_slugs.add(slug)
            for runner in runners:
                runner.process_snapshot(snapshot)

    results = [
        runner.result(settled_markets_count=len(active_slugs)) for runner in runners
    ]
    return results, loaded_rows, len(active_slugs)


def result_to_daily_row(
    *,
    result: bt.ReplayResult,
    test_day: str,
    strategy: str,
    target_column: str,
    prediction_unit: str,
    train_days: Sequence[str],
    train_rows: int,
    loaded_snapshots: int,
    active_markets: int,
) -> dict[str, Any]:
    return {
        "test_day": test_day,
        "strategy": strategy,
        "target_column": target_column,
        "prediction_unit": prediction_unit,
        "ml_min_ev": result.config.ml_min_ev if result.config.ml_filter_enabled else "",
        "train_days": len(train_days),
        "train_rows": train_rows,
        "loaded_snapshots": loaded_snapshots,
        "active_markets": active_markets,
        "settled_markets": result.settled_markets,
        "traded_markets": result.traded_markets,
        "orders": result.orders,
        "total_cost": round(result.total_cost, 8),
        "total_pnl": round(result.total_pnl, 8),
        "roi": round(result.roi, 8),
        "wins": result.wins,
        "losses": result.losses,
        "win_rate": round(result.win_rate, 8),
        "max_drawdown": round(result.max_drawdown, 8),
        "skipped_due_ml_filter": result.skipped_due_ml_filter,
        "ml_evaluated_signals": result.ml_evaluated_signals,
        "ml_passed_signals": result.ml_passed_signals,
        "ml_blocked_signals": result.ml_blocked_signals,
        "ml_error_signals": result.ml_error_signals,
        "ml_pass_rate": round(result.ml_pass_rate, 8),
    }


def max_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def summarize_daily_rows(daily_rows: list[dict[str, Any]], pd: Any) -> Any:
    daily = pd.DataFrame(daily_rows)
    rows: list[dict[str, Any]] = []
    for (strategy, ml_min_ev), group in daily.groupby(
        ["strategy", "ml_min_ev"], dropna=False, sort=False
    ):
        total_cost = float(group["total_cost"].sum())
        total_pnl = float(group["total_pnl"].sum())
        wins = int(group["wins"].sum())
        losses = int(group["losses"].sum())
        ml_eval = int(group["ml_evaluated_signals"].sum())
        ml_passed = int(group["ml_passed_signals"].sum())
        day_pnls = [float(item) for item in group.sort_values("test_day")["total_pnl"]]
        rows.append(
            {
                "strategy": strategy,
                "ml_min_ev": ml_min_ev,
                "target_column": str(group["target_column"].iloc[0]),
                "prediction_unit": str(group["prediction_unit"].iloc[0]),
                "day_count": int(group["test_day"].nunique()),
                "orders": int(group["orders"].sum()),
                "traded_markets": int(group["traded_markets"].sum()),
                "total_cost": total_cost,
                "total_pnl": total_pnl,
                "roi": total_pnl / total_cost if total_cost else 0.0,
                "wins": wins,
                "losses": losses,
                "win_rate": wins / (wins + losses) if wins + losses else 0.0,
                "median_day_roi": float(group["roi"].median()),
                "worst_day_roi": float(group["roi"].min()),
                "best_day_roi": float(group["roi"].max()),
                "day_equity_max_drawdown": max_drawdown(day_pnls),
                "max_daily_drawdown": float(group["max_drawdown"].max()),
                "skipped_due_ml_filter": int(group["skipped_due_ml_filter"].sum()),
                "ml_evaluated_signals": ml_eval,
                "ml_passed_signals": ml_passed,
                "avg_ml_pass_rate": ml_passed / ml_eval if ml_eval else 0.0,
            }
        )
    return pd.DataFrame(rows).sort_values(["roi", "total_pnl"], ascending=False)


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run day-level walk-forward LightGBM training with full tick replay."
    )
    parser.add_argument("--dataset-csv", type=Path, default=Path("analysis/ml_signal_dataset.csv"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("tick_snapshots"))
    parser.add_argument("--ledger-dir", type=Path, default=Path("ledger"))
    parser.add_argument("--evaluate-sources", default=",".join(bt.DEFAULT_EVALUATE_SOURCES))
    parser.add_argument("--start-day", default="")
    parser.add_argument("--end-day", default="")
    parser.add_argument("--include-days", default="")
    parser.add_argument("--exclude-days", default="")
    parser.add_argument("--min-train-days", type=int, default=2)
    parser.add_argument(
        "--target-column",
        choices=["single_order_pnl", "single_order_pnl_per_usd"],
        default="single_order_pnl",
    )
    parser.add_argument("--ml-min-ev-values", default="-0.05,0,0.05,0.10,0.15,0.20,0.25")
    parser.add_argument("--output-csv", type=Path, default=Path("analysis/backtest_ml_walkforward_ticks.csv"))
    parser.add_argument("--daily-output-csv", type=Path, default=Path("analysis/backtest_ml_walkforward_ticks_daily.csv"))
    parser.add_argument("--model-cache-dir", type=Path, default=Path("analysis/ml_walkforward_tick_models"))
    parser.add_argument("--strict-jsonl", action="store_true")

    parser.add_argument("--n-estimators", type=int, default=300)
    parser.add_argument("--learning-rate", type=float, default=0.03)
    parser.add_argument("--num-leaves", type=int, default=31)
    parser.add_argument("--min-child-samples", type=int, default=50)
    parser.add_argument("--subsample", type=float, default=0.9)
    parser.add_argument("--colsample-bytree", type=float, default=0.9)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--n-jobs", type=int, default=-1)

    parser.add_argument("--edge-prob-threshold", type=float, default=0.18)
    parser.add_argument("--edge-reference-price", choices=["bid", "ask"], default="ask")
    parser.add_argument("--max-spread", type=float, default=0.02)
    parser.add_argument("--min-entry-ask-price", type=float, default=0.0)
    parser.add_argument("--min-edge-after-fill", type=float, default=0.24)
    parser.add_argument("--exec-price-mode", choices=["book", "edge", "hybrid"], default="hybrid")
    parser.add_argument("--exec-slippage-ticks", type=int, default=2)
    parser.add_argument("--exec-price-cap", type=float, default=0.99)
    parser.add_argument("--tick-size", type=float, default=0.01)
    parser.add_argument("--trade-amount-usd", type=float, default=1.0)
    parser.add_argument("--order-cooldown-seconds", type=float, default=3.0)
    parser.add_argument("--signal-cooldown-seconds", type=float, default=3.0)
    parser.add_argument("--market-max-total-cost", type=float, default=12.0)
    parser.add_argument("--market-max-side-cost", type=float, default=6.0)
    parser.add_argument("--side-extension-enabled", action="store_true", default=True)
    parser.add_argument("--no-side-extension", dest="side_extension_enabled", action="store_false")
    parser.add_argument("--side-extension-start-cost", type=float, default=6.0)
    parser.add_argument("--side-extension-max-side-cost", type=float, default=9.0)
    parser.add_argument("--side-extension-min-seconds", type=float, default=20.0)
    parser.add_argument("--side-extension-cooldown-seconds", type=float, default=15.0)
    parser.add_argument("--side-extension-min-edge", type=float, default=0.20)
    parser.add_argument("--side-extension-min-edge-after-fill", type=float, default=0.18)
    parser.add_argument("--side-extension-min-ask-price", type=float, default=0.40)
    parser.add_argument("--side-extension-max-ask-price", type=float, default=0.80)
    parser.add_argument("--side-extension-max-opposite-cost", type=float, default=1.0)
    parser.add_argument("--fair-mode", choices=["snapshot", "recompute"], default="snapshot")
    parser.add_argument("--sigma-short-weight", type=float, default=0.75)
    parser.add_argument("--sigma-long-weight", type=float, default=0.25)
    parser.add_argument("--sigma-min", type=float, default=0.000015)
    parser.add_argument("--tau-floor-seconds", type=float, default=5.0)
    parser.add_argument("--z-cap", type=float, default=6.0)
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    validate_model_cache_dir(args.model_cache_dir)
    lgb, pd, _, _ = require_ml_libs()
    df = load_filtered_dataset(args, pd)
    feature_names = list(FEATURE_NAMES)
    days = sorted(str(day) for day in df["market_day"].dropna().unique())
    thresholds = parse_float_list(args.ml_min_ev_values)
    settlements = bt.load_settlements(args.ledger_dir)
    base_cfg = base_replay_config(args)
    daily_rows: list[dict[str, Any]] = []

    for idx, test_day in enumerate(days):
        train_days = days[:idx]
        if len(train_days) < args.min_train_days:
            continue
        train_df = df[df["market_day"].isin(train_days)].copy()
        if train_df.empty:
            continue

        day_cache_dir = args.model_cache_dir / test_day
        model_path = day_cache_dir / "model.txt"
        features_path = day_cache_dir / "features.json"
        day_cache_dir.mkdir(parents=True, exist_ok=True)
        model = train_model(lgb, train_df, feature_names, args)
        model.booster_.save_model(str(model_path))
        write_features_metadata(
            path=features_path,
            feature_names=feature_names,
            args=args,
            train_days=train_days,
            test_day=test_day,
        )

        configs = [base_cfg]
        for threshold in thresholds:
            configs.append(
                replace(
                    base_cfg,
                    ml_filter_enabled=True,
                    ml_model_path=model_path,
                    ml_features_path=features_path,
                    ml_min_ev=threshold,
                    ml_fail_open=False,
                )
            )

        results, loaded_snapshots, active_markets = replay_test_day(
            args=args,
            settlements=settlements,
            test_day=test_day,
            configs=configs,
        )
        for result in results:
            strategy = (
                "baseline"
                if not result.config.ml_filter_enabled
                else f"ml_ev>={result.config.ml_min_ev:g}"
            )
            daily_rows.append(
                result_to_daily_row(
                    result=result,
                    test_day=test_day,
                    strategy=strategy,
                    target_column=args.target_column,
                    prediction_unit=prediction_unit_for_target(args.target_column),
                    train_days=train_days,
                    train_rows=len(train_df),
                    loaded_snapshots=loaded_snapshots,
                    active_markets=active_markets,
                )
            )
        print(
            f"{test_day}: train_days={len(train_days)} train_rows={len(train_df)} "
            f"snapshots={loaded_snapshots} strategies={len(results)}"
        )

    if not daily_rows:
        raise SystemExit("No walk-forward replay rows produced.")

    write_csv(daily_rows, args.daily_output_csv)
    summary = summarize_daily_rows(daily_rows, pd)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.output_csv, index=False)
    print(f"Wrote summary CSV: {args.output_csv}")
    print(f"Wrote daily CSV: {args.daily_output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
