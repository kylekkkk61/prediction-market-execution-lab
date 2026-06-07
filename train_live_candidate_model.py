#!/usr/bin/env python3
"""Train and validate live EV/fill-aware candidate models from actual executions."""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

import backtest_ticks as bt
from ml_filter import FEATURE_NAMES, build_live_feature_values, optional_float
from validate_ml_on_live_executions import (
    build_order_history,
    exposure_before,
    load_attempts,
    load_orders_with_pnl,
    load_quote_index,
    load_settlement_metrics,
    max_drawdown,
    normalize_side,
    parse_float_list,
    quote_at_or_before,
    rolling_metrics_before,
    safe_ratio,
    source_signal_from_attempt,
)


EXTRA_FEATURE_NAMES = [
    "amount_usd",
    "order_type_is_fak",
    "order_type_is_fok",
    "exec_mode_is_market",
    "exec_mode_is_hybrid",
    "exec_mode_is_edge",
    "last_30s",
    "limit_minus_ask",
    "limit_minus_bid",
    "ask_x_amount",
]

LIVE_CANDIDATE_FEATURE_NAMES = FEATURE_NAMES + EXTRA_FEATURE_NAMES


def require_ml_libs() -> tuple[Any, Any]:
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


def parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def numeric(value: Any, default: float = 0.0) -> float:
    parsed = optional_float(value)
    return parsed if parsed is not None else default


def iso_or_empty(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value or "")


def load_live_candidate_dataset(args: argparse.Namespace, pd: Any) -> Any:
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
    order_history = build_order_history(live_orders)
    order_pnl = live_orders.drop_duplicates("response_order_id", keep="last").set_index(
        "response_order_id"
    )

    rows: list[dict[str, Any]] = []
    for row in attempts.sort_values("recorded_at_dt").to_dict("records"):
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

        response_order_id = str(row.get("response_order_id") or "")
        pnl_row = (
            order_pnl.loc[response_order_id].to_dict()
            if response_order_id and response_order_id in order_pnl.index
            else {}
        )
        amount_usd = numeric(row.get("amount_usd"))
        fill_cost = numeric(pnl_row.get("fill_cost"))
        actual_pnl = numeric(pnl_row.get("actual_pnl"))
        filled = bool(pnl_row) or parse_bool(row.get("filled"))
        filled_label = 1 if filled and fill_cost > 0 else 0
        target_pnl_per_sent_usd = actual_pnl / amount_usd if amount_usd > 0 else 0.0
        target_pnl_per_filled_usd = (
            actual_pnl / fill_cost if fill_cost > 0 else float("nan")
        )
        limit_price = numeric(row.get("limit_price"), float("nan"))
        ask = numeric(row.get("signal_ask"), float("nan"))
        bid = numeric(row.get("signal_bid"), float("nan"))
        remaining_seconds = features.get("remaining_seconds")
        order_type = str(row.get("order_type") or "").upper()
        exec_mode = str(row.get("exec_price_mode") or "").lower()

        output = {
            "recorded_at": iso_or_empty(row.get("recorded_at_dt")),
            "market_day": str(row.get("market_day") or ""),
            "market_slug": slug,
            "market_start_utc": row.get("market_start_utc"),
            "market_end_utc": row.get("market_end_utc"),
            "side": side,
            "order_type": order_type,
            "exec_price_mode": exec_mode,
            "status": row.get("status"),
            "response_order_id": response_order_id,
            "filled": filled_label,
            "fill_cost": fill_cost,
            "actual_pnl": actual_pnl,
            "amount_usd": amount_usd,
            "target_pnl_per_sent_usd": target_pnl_per_sent_usd,
            "target_pnl_per_filled_usd": target_pnl_per_filled_usd,
            "effective_fill_ratio": optional_float(
                pnl_row.get("effective_fill_ratio")
            ),
            "win": bool(pnl_row.get("win")) if pnl_row else False,
            "quote_available": all(value is not None for value in quote.values()),
            "old_ml_predicted_ev": optional_float(row.get("ml_predicted_ev")),
            "old_ml_min_ev": optional_float(row.get("ml_min_ev")),
            "order_type_is_fak": 1.0 if order_type == "FAK" else 0.0,
            "order_type_is_fok": 1.0 if order_type == "FOK" else 0.0,
            "exec_mode_is_market": 1.0 if exec_mode == "market" else 0.0,
            "exec_mode_is_hybrid": 1.0 if exec_mode == "hybrid" else 0.0,
            "exec_mode_is_edge": 1.0 if exec_mode == "edge" else 0.0,
            "last_30s": (
                1.0
                if remaining_seconds is not None and remaining_seconds <= 30
                else 0.0
            ),
            "limit_minus_ask": (
                limit_price - ask
                if math.isfinite(limit_price) and math.isfinite(ask)
                else float("nan")
            ),
            "limit_minus_bid": (
                limit_price - bid
                if math.isfinite(limit_price) and math.isfinite(bid)
                else float("nan")
            ),
            "ask_x_amount": ask * amount_usd if math.isfinite(ask) else float("nan"),
        }
        output.update(features)
        rows.append(output)

    df = pd.DataFrame(rows)
    for column in LIVE_CANDIDATE_FEATURE_NAMES + [
        "filled",
        "fill_cost",
        "actual_pnl",
        "amount_usd",
        "target_pnl_per_sent_usd",
        "target_pnl_per_filled_usd",
    ]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def max_drawdown_from_frame(frame: Any) -> float:
    if frame.empty:
        return 0.0
    values = [
        float(item)
        for item in frame.sort_values("recorded_at")["actual_pnl"].fillna(0.0)
    ]
    return max_drawdown(values)


def metrics(frame: Any, *, total_candidates: int) -> dict[str, Any]:
    selected = frame.copy()
    filled = selected[selected["filled"] == 1].copy()
    fill_cost = float(filled["fill_cost"].fillna(0.0).sum())
    pnl = float(filled["actual_pnl"].fillna(0.0).sum())
    wins = int(filled["win"].sum()) if "win" in filled else 0
    losses = int(len(filled) - wins)
    return {
        "selected_attempts": int(len(selected)),
        "skipped_attempts": int(total_candidates - len(selected)),
        "filled_orders": int(len(filled)),
        "fill_rate": safe_ratio(len(filled), len(selected)),
        "filled_amount_usd": fill_cost,
        "actual_pnl": pnl,
        "actual_roi": safe_ratio(pnl, fill_cost),
        "wins": wins,
        "losses": losses,
        "win_rate": safe_ratio(wins, len(filled)),
        "avg_fill_ratio": float(filled["effective_fill_ratio"].mean())
        if "effective_fill_ratio" in filled and not filled.empty
        else 0.0,
        "max_drawdown": max_drawdown_from_frame(filled),
    }


def train_direct_ev_model(lgb: Any, train_df: Any, args: argparse.Namespace) -> Any:
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
    model.fit(
        train_df[LIVE_CANDIDATE_FEATURE_NAMES],
        train_df["target_pnl_per_sent_usd"],
    )
    return model


def train_fill_model(lgb: Any, train_df: Any, args: argparse.Namespace) -> Optional[Any]:
    if train_df["filled"].nunique() < 2:
        return None
    model = lgb.LGBMClassifier(
        objective="binary",
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
    model.fit(train_df[LIVE_CANDIDATE_FEATURE_NAMES], train_df["filled"])
    return model


def train_filled_ev_model(lgb: Any, train_df: Any, args: argparse.Namespace) -> Optional[Any]:
    filled = train_df[
        (train_df["filled"] == 1)
        & train_df["target_pnl_per_filled_usd"].notna()
    ].copy()
    if len(filled) < args.min_filled_train_rows:
        return None
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
    model.fit(
        filled[LIVE_CANDIDATE_FEATURE_NAMES],
        filled["target_pnl_per_filled_usd"],
    )
    return model


def add_model_scores(lgb: Any, train_df: Any, test_df: Any, args: argparse.Namespace) -> Any:
    scored = test_df.copy()
    direct_model = train_direct_ev_model(lgb, train_df, args)
    scored["score_direct_ev"] = direct_model.predict(scored[LIVE_CANDIDATE_FEATURE_NAMES])

    fill_model = train_fill_model(lgb, train_df, args)
    if fill_model is None:
        fill_probability = float(train_df["filled"].mean()) if len(train_df) else 0.0
        scored["score_fill_probability"] = fill_probability
    else:
        scored["score_fill_probability"] = fill_model.predict_proba(
            scored[LIVE_CANDIDATE_FEATURE_NAMES]
        )[:, 1]

    filled_ev_model = train_filled_ev_model(lgb, train_df, args)
    if filled_ev_model is None:
        filled_train = train_df[
            (train_df["filled"] == 1)
            & train_df["target_pnl_per_filled_usd"].notna()
        ]
        fallback_ev = (
            float(filled_train["target_pnl_per_filled_usd"].mean())
            if not filled_train.empty
            else 0.0
        )
        scored["score_filled_ev"] = fallback_ev
    else:
        scored["score_filled_ev"] = filled_ev_model.predict(
            scored[LIVE_CANDIDATE_FEATURE_NAMES]
        )

    scored["score_fill_aware_ev"] = (
        scored["score_fill_probability"] * scored["score_filled_ev"]
    )
    return scored


def summarize_selection(
    *,
    rows: list[dict[str, Any]],
    scored: Any,
    segment: str,
    day: str,
    score_column: str,
    filter_type: str,
    threshold: Any,
    selected: Any,
) -> None:
    base = metrics(scored, total_candidates=len(scored))
    selected_metrics = metrics(selected, total_candidates=len(scored))
    rows.append(
        {
            "segment": segment,
            "market_day": day,
            "score_column": score_column,
            "filter_type": filter_type,
            "threshold": threshold,
            "baseline_attempts": base["selected_attempts"],
            "baseline_filled_orders": base["filled_orders"],
            "baseline_filled_amount_usd": base["filled_amount_usd"],
            "baseline_actual_pnl": base["actual_pnl"],
            "baseline_actual_roi": base["actual_roi"],
            "pnl_delta_vs_baseline": (
                selected_metrics["actual_pnl"] - base["actual_pnl"]
            ),
            "roi_delta_vs_baseline": (
                selected_metrics["actual_roi"] - base["actual_roi"]
            ),
            **selected_metrics,
        }
    )


def evaluate_scored_day(
    *,
    scored: Any,
    day: str,
    rows: list[dict[str, Any]],
    detail_frames: list[Any],
    args: argparse.Namespace,
) -> None:
    day_scored = scored.copy()
    day_scored["walkforward_test_day"] = day
    detail_frames.append(day_scored)
    for score_column in ["score_direct_ev", "score_fill_aware_ev", "score_fill_probability"]:
        summarize_selection(
            rows=rows,
            scored=day_scored,
            segment="daily",
            day=day,
            score_column=score_column,
            filter_type="all_sent",
            threshold="",
            selected=day_scored,
        )
        thresholds = (
            args.fill_probability_thresholds
            if score_column == "score_fill_probability"
            else args.ev_thresholds
        )
        for threshold in thresholds:
            selected = day_scored[day_scored[score_column] >= threshold].copy()
            summarize_selection(
                rows=rows,
                scored=day_scored,
                segment="daily",
                day=day,
                score_column=score_column,
                filter_type="threshold",
                threshold=threshold,
                selected=selected,
            )
        for keep_fraction in args.keep_fractions:
            if not 0 < keep_fraction <= 1:
                continue
            threshold = float(day_scored[score_column].quantile(1.0 - keep_fraction))
            selected = day_scored[day_scored[score_column] >= threshold].copy()
            summarize_selection(
                rows=rows,
                scored=day_scored,
                segment="daily",
                day=day,
                score_column=score_column,
                filter_type="keep_fraction",
                threshold=keep_fraction,
                selected=selected,
            )


def add_combined_rows(rows: list[dict[str, Any]], details: Any, args: argparse.Namespace) -> None:
    for score_column in ["score_direct_ev", "score_fill_aware_ev", "score_fill_probability"]:
        summarize_selection(
            rows=rows,
            scored=details,
            segment="combined",
            day="combined",
            score_column=score_column,
            filter_type="all_sent",
            threshold="",
            selected=details,
        )
        thresholds = (
            args.fill_probability_thresholds
            if score_column == "score_fill_probability"
            else args.ev_thresholds
        )
        for threshold in thresholds:
            selected = details[details[score_column] >= threshold].copy()
            summarize_selection(
                rows=rows,
                scored=details,
                segment="combined",
                day="combined",
                score_column=score_column,
                filter_type="threshold",
                threshold=threshold,
                selected=selected,
            )
        for keep_fraction in args.keep_fractions:
            if not 0 < keep_fraction <= 1:
                continue
            selected_parts = []
            for _, day_group in details.groupby("walkforward_test_day", sort=True):
                threshold = float(day_group[score_column].quantile(1.0 - keep_fraction))
                selected_parts.append(day_group[day_group[score_column] >= threshold])
            selected = (
                __import__("pandas").concat(selected_parts, ignore_index=True)
                if selected_parts
                else details.iloc[0:0].copy()
            )
            summarize_selection(
                rows=rows,
                scored=details,
                segment="combined",
                day="combined",
                score_column=score_column,
                filter_type="keep_fraction_by_day",
                threshold=keep_fraction,
                selected=selected,
            )


def run_walkforward(args: argparse.Namespace, lgb: Any, pd: Any, dataset: Any) -> tuple[Any, Any]:
    rows: list[dict[str, Any]] = []
    detail_frames: list[Any] = []
    days = sorted(str(day) for day in dataset["market_day"].dropna().unique())
    for idx, day in enumerate(days):
        train_days = days[:idx]
        if len(train_days) < args.min_train_days:
            continue
        train_df = dataset[dataset["market_day"].isin(train_days)].copy()
        test_df = dataset[dataset["market_day"] == day].copy()
        if train_df.empty or test_df.empty:
            continue
        scored = add_model_scores(lgb, train_df, test_df, args)
        evaluate_scored_day(
            scored=scored,
            day=day,
            rows=rows,
            detail_frames=detail_frames,
            args=args,
        )
        print(
            f"walk-forward day={day} train_days={len(train_days)} "
            f"train_rows={len(train_df)} test_rows={len(test_df)}"
        )
    if not detail_frames:
        raise SystemExit("No walk-forward test days. Lower --min-train-days or check filters.")
    details = pd.concat(detail_frames, ignore_index=True)
    add_combined_rows(rows, details, args)
    return pd.DataFrame(rows), details


def train_final_models(args: argparse.Namespace, lgb: Any, dataset: Any) -> dict[str, str]:
    args.model_output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}
    direct_model = train_direct_ev_model(lgb, dataset, args)
    direct_path = args.model_output_dir / "direct_ev_model.txt"
    direct_model.booster_.save_model(str(direct_path))
    outputs["direct_ev_model"] = str(direct_path)

    fill_model = train_fill_model(lgb, dataset, args)
    if fill_model is not None:
        fill_path = args.model_output_dir / "fill_probability_model.txt"
        fill_model.booster_.save_model(str(fill_path))
        outputs["fill_probability_model"] = str(fill_path)

    filled_ev_model = train_filled_ev_model(lgb, dataset, args)
    if filled_ev_model is not None:
        filled_ev_path = args.model_output_dir / "filled_ev_model.txt"
        filled_ev_model.booster_.save_model(str(filled_ev_path))
        outputs["filled_ev_model"] = str(filled_ev_path)
    return outputs


def write_feature_metadata(
    path: Path,
    args: argparse.Namespace,
    model_outputs: Optional[dict[str, str]] = None,
) -> None:
    payload = {
        "model_type": "live_candidate_ev_fill_aware_research",
        "targets": {
            "direct_ev": "target_pnl_per_sent_usd",
            "fill_probability": "filled",
            "filled_ev": "target_pnl_per_filled_usd",
        },
        "prediction_units": {
            "score_direct_ev": "actual_pnl_per_sent_usd",
            "score_fill_probability": "probability",
            "score_fill_aware_ev": "fill_probability_times_filled_pnl_per_usd",
        },
        "feature_names": LIVE_CANDIDATE_FEATURE_NAMES,
        "model_outputs": model_outputs or {},
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
        "recommended_research_filter": {
            "score": "score_fill_probability",
            "threshold": 0.75,
            "basis": "best combined pnl_delta_vs_baseline in current walk-forward run",
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_report(path: Path, summary: Any, details: Any, args: argparse.Namespace) -> None:
    combined = summary[summary["segment"] == "combined"].copy()
    baseline = combined[
        (combined["filter_type"] == "all_sent")
        & (combined["score_column"] == "score_direct_ev")
    ]
    best = combined[combined["filter_type"] != "all_sent"].sort_values(
        ["pnl_delta_vs_baseline", "actual_pnl", "actual_roi"],
        ascending=False,
    )
    lines = [
        "# Live EV/fill-aware candidate model report",
        "",
        f"- Ledger dir: `{args.ledger_dir}`",
        f"- Date range: `{args.start_day or 'begin'}` to `{args.end_day or 'end'}`",
        f"- Excluded days: `{args.exclude_days or '(none)'}`",
        f"- Min train days: {args.min_train_days}",
        f"- Walk-forward scored attempts: {len(details)}",
        "",
    ]
    if not baseline.empty:
        row = baseline.iloc[0]
        lines.extend(
            [
                "## Baseline",
                "",
                "| Attempts | Filled | Cost | PnL | ROI | Fill rate | Max DD |",
                "|---:|---:|---:|---:|---:|---:|---:|",
                (
                    f"| {int(row['selected_attempts'])} | {int(row['filled_orders'])} | "
                    f"{float(row['filled_amount_usd']):.2f} | {float(row['actual_pnl']):+.2f} | "
                    f"{float(row['actual_roi']) * 100:+.2f}% | "
                    f"{float(row['fill_rate']) * 100:.2f}% | {float(row['max_drawdown']):.2f} |"
                ),
                "",
            ]
        )
    if not best.empty:
        lines.extend(
            [
                "## Best Filters By PnL Delta",
                "",
                "| Score | Filter | Threshold | Attempts | Filled | PnL | ROI | Delta PnL | Fill rate |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for _, row in best.head(15).iterrows():
            lines.append(
                f"| {row['score_column']} | {row['filter_type']} | {row['threshold']} | "
                f"{int(row['selected_attempts'])} | {int(row['filled_orders'])} | "
                f"{float(row['actual_pnl']):+.2f} | {float(row['actual_roi']) * 100:+.2f}% | "
                f"{float(row['pnl_delta_vs_baseline']):+.2f} | {float(row['fill_rate']) * 100:.2f}% |"
            )
    lines.extend(
        [
            "",
            "## Files",
            "",
            f"- Dataset: `{args.dataset_output_csv}`",
            f"- Details: `{args.detail_output_csv}`",
            f"- Summary: `{args.summary_output_csv}`",
            f"- Daily: `{args.daily_output_csv}`",
            f"- Feature metadata: `{args.features_output}`",
            f"- Model output dir: `{args.model_output_dir}`",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train live EV/fill-aware candidate models and validate walk-forward."
    )
    parser.add_argument("--ledger-dir", type=Path, default=Path("ledger"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("tick_snapshots"))
    parser.add_argument("--snapshot-glob", default="*.jsonl*")
    parser.add_argument("--start-day", default="")
    parser.add_argument("--end-day", default="")
    parser.add_argument("--include-days", default="")
    parser.add_argument("--exclude-days", default="")
    parser.add_argument("--min-train-days", type=int, default=2)
    parser.add_argument("--min-filled-train-rows", type=int, default=40)
    parser.add_argument("--ev-thresholds", default="-0.50,-0.25,-0.10,0,0.05,0.10,0.20,0.30,0.50")
    parser.add_argument("--fill-probability-thresholds", default="0.10,0.25,0.40,0.50,0.60,0.75")
    parser.add_argument("--keep-fractions", default="0.25,0.40,0.50,0.60,0.75")
    parser.add_argument("--n-estimators", type=int, default=120)
    parser.add_argument("--learning-rate", type=float, default=0.04)
    parser.add_argument("--num-leaves", type=int, default=15)
    parser.add_argument("--min-child-samples", type=int, default=30)
    parser.add_argument("--subsample", type=float, default=0.9)
    parser.add_argument("--colsample-bytree", type=float, default=0.9)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--n-jobs", type=int, default=-1)
    parser.add_argument(
        "--dataset-output-csv",
        type=Path,
        default=Path("analysis/live_candidate_dataset.csv"),
    )
    parser.add_argument(
        "--detail-output-csv",
        type=Path,
        default=Path("analysis/live_candidate_model_walkforward_details.csv"),
    )
    parser.add_argument(
        "--summary-output-csv",
        type=Path,
        default=Path("analysis/live_candidate_model_walkforward_summary.csv"),
    )
    parser.add_argument(
        "--daily-output-csv",
        type=Path,
        default=Path("analysis/live_candidate_model_walkforward_daily.csv"),
    )
    parser.add_argument(
        "--features-output",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--model-output-dir",
        type=Path,
        default=Path("models/live_candidate_research_v1"),
    )
    parser.add_argument(
        "--report-md",
        type=Path,
        default=Path("analysis/live_candidate_model_report.md"),
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    if args.features_output is None:
        args.features_output = args.model_output_dir / "features.json"
    args.ev_thresholds = parse_float_list(args.ev_thresholds)
    args.fill_probability_thresholds = parse_float_list(args.fill_probability_thresholds)
    args.keep_fractions = parse_float_list(args.keep_fractions)

    lgb, pd = require_ml_libs()
    dataset = load_live_candidate_dataset(args, pd)
    if dataset.empty:
        raise SystemExit("Live candidate dataset is empty.")
    args.dataset_output_csv.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(args.dataset_output_csv, index=False)

    summary, details = run_walkforward(args, lgb, pd, dataset)
    args.detail_output_csv.parent.mkdir(parents=True, exist_ok=True)
    details.to_csv(args.detail_output_csv, index=False)
    summary.to_csv(args.summary_output_csv, index=False)
    daily = summary[summary["segment"] == "daily"].copy()
    daily.to_csv(args.daily_output_csv, index=False)
    model_outputs = train_final_models(args, lgb, dataset)
    write_feature_metadata(args.features_output, args, model_outputs)
    write_report(args.report_md, summary, details, args)

    combined = summary[summary["segment"] == "combined"].copy()
    best = combined[combined["filter_type"] != "all_sent"].sort_values(
        ["pnl_delta_vs_baseline", "actual_pnl", "actual_roi"],
        ascending=False,
    )
    print(f"Dataset rows: {len(dataset)}")
    print(f"Walk-forward details rows: {len(details)}")
    if not best.empty:
        row = best.iloc[0]
        print(
            "Best combined filter: "
            f"{row['score_column']} {row['filter_type']}={row['threshold']} "
            f"pnl={float(row['actual_pnl']):+.2f} "
            f"delta={float(row['pnl_delta_vs_baseline']):+.2f} "
            f"roi={float(row['actual_roi']) * 100:+.2f}%"
        )
    print(f"Wrote report: {args.report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
