#!/usr/bin/env python3
"""Attribute live filled-order PnL by signal and execution features."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Optional

from ml_filter import optional_float


def require_pandas() -> Any:
    try:
        import pandas as pd  # type: ignore
    except Exception as exc:
        raise SystemExit(
            "pandas is required. Install with: python3 -m pip install pandas"
        ) from exc
    return pd


def parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def parse_day_list(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def normalize_side(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"YES", "UP"}:
        return "UP"
    if text in {"NO", "DOWN"}:
        return "DOWN"
    return text


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


def numeric_bin(value: Any, width: float, *, lower: Optional[float] = None, upper: Optional[float] = None) -> str:
    number = optional_float(value)
    if number is None or not math.isfinite(number):
        return "missing"
    if lower is not None and number < lower:
        return f"<{lower:g}"
    if upper is not None and number >= upper:
        return f">={upper:g}"
    start = math.floor(number / width) * width
    end = start + width
    return f"{start:.2f}-{end:.2f}"


def time_bucket(value: Any, width: int = 30) -> str:
    number = optional_float(value)
    if number is None or not math.isfinite(number):
        return "missing"
    if number < 0:
        return "<0"
    start = int(number // width) * width
    return f"{start}-{start + width}"


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


def load_attempt_metadata(args: argparse.Namespace, pd: Any) -> Any:
    path = args.ledger_dir / "execution_attempts.csv"
    if not path.exists():
        return pd.DataFrame()
    attempts = pd.read_csv(path, dtype=str).fillna("")
    if "response_order_id" not in attempts.columns:
        return pd.DataFrame()
    attempts = attempts[attempts["response_order_id"].astype(str) != ""].copy()
    if attempts.empty:
        return attempts
    attempts["attempt_recorded_at_dt"] = pd.to_datetime(
        attempts["recorded_at"], errors="coerce", utc=True
    )
    for column in [
        "ml_predicted_ev",
        "ml_min_ev",
        "latency_ms",
        "fill_amount_usd",
        "fill_ratio",
        "signal_edge_after_fill_estimate",
    ]:
        if column in attempts.columns:
            attempts[f"attempt_{column}_num"] = attempts[column].map(optional_float)
    keep = [
        "response_order_id",
        "attempt_recorded_at_dt",
        "order_type",
        "exec_price_mode",
        "status",
        "attempt_stage",
        "attempt_ml_predicted_ev_num",
        "attempt_ml_min_ev_num",
        "attempt_latency_ms_num",
        "attempt_fill_amount_usd_num",
        "attempt_fill_ratio_num",
        "attempt_signal_edge_after_fill_estimate_num",
    ]
    keep = [column for column in keep if column in attempts.columns]
    return attempts.sort_values("attempt_recorded_at_dt").drop_duplicates(
        "response_order_id",
        keep="last",
    )[keep]


def load_live_orders(args: argparse.Namespace, pd: Any) -> Any:
    orders = pd.read_csv(args.ledger_dir / "orders.csv", dtype=str).fillna("")
    settlements = pd.read_csv(args.ledger_dir / "market_settlements.csv", dtype=str).fillna("")
    settlements = settlements[["market_slug", "resolved_side"]].drop_duplicates(
        "market_slug",
        keep="last",
    )
    orders = orders.merge(settlements, on="market_slug", how="left")
    orders["recorded_at_dt"] = pd.to_datetime(
        orders["recorded_at"], errors="coerce", utc=True
    )
    orders["market_start_dt"] = pd.to_datetime(
        orders["market_start_utc"], errors="coerce", utc=True
    )
    orders["market_end_dt"] = pd.to_datetime(
        orders["market_end_utc"], errors="coerce", utc=True
    )
    orders["market_day"] = orders["market_start_dt"].dt.strftime("%Y-%m-%d")
    live = orders[
        (orders["mode"] == "live_estimated")
        & (orders["status"] == "live_success")
        & (orders["included_in_position"].map(parse_bool))
        & orders["recorded_at_dt"].notna()
    ].copy()
    live = apply_day_filters(live, args)
    for column in [
        "amount_usd",
        "requested_amount_usd",
        "filled_amount_usd",
        "fill_ratio",
        "execution_price_estimate",
        "estimated_shares_gross",
        "estimated_fee_usdc",
        "estimated_shares_net",
        "signal_fair",
        "signal_edge",
        "signal_reference_price",
        "signal_bid",
        "signal_ask",
        "signal_spread",
        "signal_max_execution_price",
        "signal_edge_after_fill_estimate",
        "bn_price",
        "bn_open_price",
        "sigma",
        "sigma_short",
        "sigma_long",
        "sigma_eff",
        "tau_seconds",
        "z",
    ]:
        if column in live.columns:
            live[f"{column}_num"] = live[column].map(optional_float)
    live["entry_side"] = live["outcome_bought"].map(normalize_side)
    live["fill_cost"] = live["filled_amount_usd_num"]
    live.loc[live["fill_cost"].isna() | (live["fill_cost"] <= 0), "fill_cost"] = (
        live["amount_usd_num"]
    )
    live["effective_fill_ratio"] = live["fill_ratio_num"]
    live.loc[
        live["effective_fill_ratio"].isna() & (live["fill_cost"] > 0),
        "effective_fill_ratio",
    ] = 1.0
    live["win"] = live["entry_side"] == live["resolved_side"]
    live["payout"] = live["estimated_shares_net_num"].where(live["win"], 0.0)
    live["actual_pnl"] = live["payout"].fillna(0.0) - live["fill_cost"].fillna(0.0)
    live["actual_roi"] = live["actual_pnl"] / live["fill_cost"]
    live["elapsed_seconds"] = (
        live["recorded_at_dt"] - live["market_start_dt"]
    ).dt.total_seconds()
    live["remaining_seconds"] = (
        live["market_end_dt"] - live["recorded_at_dt"]
    ).dt.total_seconds()
    live["last_30s"] = live["remaining_seconds"] <= 30
    live["utc_hour"] = live["recorded_at_dt"].dt.hour
    live["utc_day_of_week"] = live["recorded_at_dt"].dt.weekday

    attempts = load_attempt_metadata(args, pd)
    if not attempts.empty:
        live = live.merge(attempts, on="response_order_id", how="left")
    else:
        live["attempt_ml_predicted_ev_num"] = None

    live["order_type_final"] = live["signal_order_type"].where(
        live["signal_order_type"].astype(str) != "",
        live.get("order_type", ""),
    )
    live["exec_price_mode_final"] = live["signal_exec_price_mode"].where(
        live["signal_exec_price_mode"].astype(str) != "",
        live.get("exec_price_mode", ""),
    )
    live["time_bucket_30s"] = live["elapsed_seconds"].map(time_bucket)
    live["remaining_bucket_30s"] = live["remaining_seconds"].map(time_bucket)
    live["ask_bucket_0.05"] = live["signal_ask_num"].map(lambda value: numeric_bin(value, 0.05, lower=0.0, upper=1.0))
    live["fill_price_bucket_0.05"] = live["execution_price_estimate_num"].map(lambda value: numeric_bin(value, 0.05, lower=0.0, upper=1.0))
    live["fair_bucket_0.05"] = live["signal_fair_num"].map(lambda value: numeric_bin(value, 0.05, lower=0.0, upper=1.0))
    live["edge_bucket_0.05"] = live["signal_edge_num"].map(lambda value: numeric_bin(value, 0.05, lower=-0.50, upper=0.50))
    live["edge_after_fill_bucket_0.05"] = live["signal_edge_after_fill_estimate_num"].map(lambda value: numeric_bin(value, 0.05, lower=-0.50, upper=0.50))
    live["spread_bucket_0.01"] = live["signal_spread_num"].map(lambda value: numeric_bin(value, 0.01, lower=0.0, upper=0.10))
    live["ml_score_bucket_0.50"] = live["attempt_ml_predicted_ev_num"].map(lambda value: numeric_bin(value, 0.50, lower=-2.0, upper=5.0))
    live["amount_bucket_1"] = live["fill_cost"].map(lambda value: numeric_bin(value, 1.0, lower=0.0, upper=10.0))
    live["last_30s_label"] = live["last_30s"].map(lambda value: "last_30s" if value else "not_last_30s")
    live["side_time_bucket"] = live["entry_side"] + ":" + live["time_bucket_30s"]
    return live


def group_metrics(frame: Any, group_column: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for value, group in frame.groupby(group_column, dropna=False, sort=True):
        group = group.sort_values("recorded_at_dt")
        fill_cost = float(group["fill_cost"].sum())
        pnl = float(group["actual_pnl"].sum())
        wins = int(group["win"].sum())
        losses = int(len(group) - wins)
        rows.append(
            {
                "group": group_column,
                "value": value,
                "filled_orders": int(len(group)),
                "filled_amount_usd": fill_cost,
                "actual_pnl": pnl,
                "actual_roi": safe_ratio(pnl, fill_cost),
                "wins": wins,
                "losses": losses,
                "win_rate": safe_ratio(wins, len(group)),
                "avg_fill_ratio": float(group["effective_fill_ratio"].mean()),
                "avg_fill_price": float(group["execution_price_estimate_num"].mean()),
                "avg_signal_fair": float(group["signal_fair_num"].mean()),
                "avg_signal_edge": float(group["signal_edge_num"].mean()),
                "avg_edge_after_fill": float(group["signal_edge_after_fill_estimate_num"].mean()),
                "avg_ask": float(group["signal_ask_num"].mean()),
                "avg_spread": float(group["signal_spread_num"].mean()),
                "avg_ml_score": float(group["attempt_ml_predicted_ev_num"].mean())
                if "attempt_ml_predicted_ev_num" in group.columns
                else 0.0,
                "max_drawdown": max_drawdown([float(item) for item in group["actual_pnl"]]),
            }
        )
    rows.sort(key=lambda row: (row["group"], -row["filled_amount_usd"], row["value"]))
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_detail_csv(path: Path, frame: Any) -> None:
    detail_columns = [
        "recorded_at",
        "market_day",
        "market_slug",
        "entry_side",
        "resolved_side",
        "order_type_final",
        "exec_price_mode_final",
        "fill_cost",
        "execution_price_estimate_num",
        "effective_fill_ratio",
        "actual_pnl",
        "actual_roi",
        "win",
        "elapsed_seconds",
        "remaining_seconds",
        "last_30s",
        "signal_fair_num",
        "signal_edge_num",
        "signal_edge_after_fill_estimate_num",
        "signal_ask_num",
        "signal_spread_num",
        "attempt_ml_predicted_ev_num",
        "attempt_ml_min_ev_num",
        "response_order_id",
    ]
    detail_columns = [column for column in detail_columns if column in frame.columns]
    path.parent.mkdir(parents=True, exist_ok=True)
    frame[detail_columns].to_csv(path, index=False)


def write_report(
    *,
    path: Path,
    frame: Any,
    grouped: dict[str, list[dict[str, Any]]],
    args: argparse.Namespace,
) -> None:
    total_cost = float(frame["fill_cost"].sum())
    total_pnl = float(frame["actual_pnl"].sum())
    total_wins = int(frame["win"].sum())
    min_cost = args.report_min_cost

    all_group_rows = [row for rows in grouped.values() for row in rows]
    bad_rows = [
        row for row in all_group_rows
        if float(row["filled_amount_usd"]) >= min_cost and float(row["actual_pnl"]) < 0
    ]
    bad_rows.sort(key=lambda row: float(row["actual_pnl"]))
    good_rows = [
        row for row in all_group_rows
        if float(row["filled_amount_usd"]) >= min_cost and float(row["actual_pnl"]) > 0
    ]
    good_rows.sort(key=lambda row: float(row["actual_pnl"]), reverse=True)

    lines = [
        "# Live filled PnL attribution",
        "",
        f"- Ledger dir: `{args.ledger_dir}`",
        f"- Date range: `{args.start_day or 'begin'}` to `{args.end_day or 'end'}`",
        f"- Excluded days: `{args.exclude_days or '(none)'}`",
        f"- Filled orders: {len(frame)}",
        f"- Filled amount: {total_cost:.2f}",
        f"- Actual PnL: {total_pnl:+.2f}",
        f"- ROI: {safe_ratio(total_pnl, total_cost) * 100:+.2f}%",
        f"- Win rate: {safe_ratio(total_wins, len(frame)) * 100:.2f}%",
        "",
        "## Worst loss groups",
        "",
        "| Group | Value | Orders | Cost | PnL | ROI | Win rate |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in bad_rows[:20]:
        lines.append(
            f"| {row['group']} | {row['value']} | {row['filled_orders']} | "
            f"{float(row['filled_amount_usd']):.2f} | {float(row['actual_pnl']):+.2f} | "
            f"{float(row['actual_roi']) * 100:+.2f}% | {float(row['win_rate']) * 100:.2f}% |"
        )
    lines.extend([
        "",
        "## Best profit groups",
        "",
        "| Group | Value | Orders | Cost | PnL | ROI | Win rate |",
        "|---|---|---:|---:|---:|---:|---:|",
    ])
    for row in good_rows[:20]:
        lines.append(
            f"| {row['group']} | {row['value']} | {row['filled_orders']} | "
            f"{float(row['filled_amount_usd']):.2f} | {float(row['actual_pnl']):+.2f} | "
            f"{float(row['actual_roi']) * 100:+.2f}% | {float(row['win_rate']) * 100:.2f}% |"
        )
    lines.extend([
        "",
        "## Files",
        "",
        f"- Detail: `{args.detail_output_csv}`",
    ])
    for name, output_path in output_paths(args).items():
        lines.append(f"- {name}: `{output_path}`")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def output_paths(args: argparse.Namespace) -> dict[str, Path]:
    prefix = args.output_prefix
    return {
        "summary": Path(f"{prefix}_summary.csv"),
        "by_day": Path(f"{prefix}_by_day.csv"),
        "by_time": Path(f"{prefix}_by_time.csv"),
        "by_side_time": Path(f"{prefix}_by_side_time.csv"),
        "by_price": Path(f"{prefix}_by_price.csv"),
        "by_edge": Path(f"{prefix}_by_edge.csv"),
        "by_ml": Path(f"{prefix}_by_ml.csv"),
        "by_execution": Path(f"{prefix}_by_execution.csv"),
        "by_last30": Path(f"{prefix}_by_last30.csv"),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Attribute live filled-order PnL.")
    parser.add_argument("--ledger-dir", type=Path, default=Path("ledger"))
    parser.add_argument("--start-day", default="")
    parser.add_argument("--end-day", default="")
    parser.add_argument("--include-days", default="")
    parser.add_argument("--exclude-days", default="")
    parser.add_argument("--report-min-cost", type=float, default=25.0)
    parser.add_argument(
        "--output-prefix",
        default="analysis/live_pnl_attribution",
    )
    parser.add_argument(
        "--detail-output-csv",
        type=Path,
        default=Path("analysis/live_pnl_attribution_details.csv"),
    )
    parser.add_argument(
        "--report-md",
        type=Path,
        default=Path("analysis/live_pnl_attribution_report.md"),
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    pd = require_pandas()
    frame = load_live_orders(args, pd)
    if frame.empty:
        raise SystemExit("No live filled orders matched the filters.")

    group_sets = {
        "summary": ["entry_side"],
        "by_day": ["market_day"],
        "by_time": ["time_bucket_30s"],
        "by_side_time": ["side_time_bucket"],
        "by_price": ["ask_bucket_0.05", "fill_price_bucket_0.05", "fair_bucket_0.05"],
        "by_edge": ["edge_bucket_0.05", "edge_after_fill_bucket_0.05", "spread_bucket_0.01"],
        "by_ml": ["ml_score_bucket_0.50"],
        "by_execution": ["order_type_final", "exec_price_mode_final", "amount_bucket_1"],
        "by_last30": ["last_30s_label", "remaining_bucket_30s"],
    }
    outputs = output_paths(args)
    grouped_outputs: dict[str, list[dict[str, Any]]] = {}
    for name, columns in group_sets.items():
        rows: list[dict[str, Any]] = []
        for column in columns:
            rows.extend(group_metrics(frame, column))
        grouped_outputs[name] = rows
        write_csv(outputs[name], rows)

    write_detail_csv(args.detail_output_csv, frame)
    write_report(path=args.report_md, frame=frame, grouped=grouped_outputs, args=args)
    print(f"Filled orders: {len(frame)}")
    print(f"Filled amount: {float(frame['fill_cost'].sum()):.2f}")
    print(f"Actual PnL: {float(frame['actual_pnl'].sum()):+.2f}")
    print(f"Wrote report: {args.report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
