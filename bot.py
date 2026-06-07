import asyncio
import csv
import json
import math
import os
import ssl
import statistics
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import certifi
import requests
import websockets
from dotenv import load_dotenv
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import BuilderConfig, MarketOrderArgs, OrderType
from py_clob_client_v2.order_builder.constants import BUY

from ml_filter import FEATURE_NAMES, MLSignalFilter, build_live_feature_values


# ====================== 配置區 ======================
load_dotenv()

PRIVATE_KEY = os.getenv("PRIVATE_KEY")
FUNDER_ADDRESS = os.getenv("FUNDER_ADDRESS")
CLOB_HOST = (
    os.getenv("CLOB_HOST", "https://clob-v2.polymarket.com").strip()
    or "https://clob-v2.polymarket.com"
)
HOST = CLOB_HOST
CHAIN_ID = 137
POLY_SIGNATURE_TYPE = int(os.getenv("POLY_SIGNATURE_TYPE", "2"))
POLY_BUILDER_CODE = os.getenv("POLY_BUILDER_CODE", "").strip() or None

TRADE_AMOUNT_USD = float(os.getenv("TRADE_AMOUNT_USD", "1.0"))
MARKET_BUCKET_MINUTES = int(os.getenv("MARKET_BUCKET_MINUTES", "15"))
if MARKET_BUCKET_MINUTES not in {5, 15}:
    raise ValueError("MARKET_BUCKET_MINUTES 只支援 5 或 15")
MARKET_DURATION_SECONDS = MARKET_BUCKET_MINUTES * 60
MARKET_SLUG_PREFIX = f"btc-updown-{MARKET_BUCKET_MINUTES}m"
MARKET_LABEL = f"BTC {MARKET_BUCKET_MINUTES}m"
MARKET_WINDOW_LABEL = f"{MARKET_BUCKET_MINUTES} 分鐘"
POLYMARKET_CRYPTO_PRICE_VARIANT = (
    "fiveminute" if MARKET_BUCKET_MINUTES == 5 else "fifteen"
)

# 以 fair - bid 的 edge 為交易門檻
EDGE_PROB_THRESHOLD = float(os.getenv("EDGE_PROB_THRESHOLD", "0.03"))
EDGE_REFERENCE_PRICE = os.getenv("EDGE_REFERENCE_PRICE", "bid").strip().lower()
if EDGE_REFERENCE_PRICE not in {"bid", "ask"}:
    EDGE_REFERENCE_PRICE = "bid"

# 訂單冷卻：避免過度下單
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "15"))

# 訊號冷卻：同一個 side 在冷卻期內只印一次
SIGNAL_COOLDOWN_SECONDS = int(
    os.getenv("SIGNAL_COOLDOWN_SECONDS", str(COOLDOWN_SECONDS))
)

MAX_SPREAD = float(os.getenv("MAX_SPREAD", "0.02"))
MIN_ENTRY_ASK_PRICE = max(float(os.getenv("MIN_ENTRY_ASK_PRICE", "0.0")), 0.0)
MIN_ENTRY_REMAINING_SECONDS = max(
    float(os.getenv("MIN_ENTRY_REMAINING_SECONDS", "0")),
    0.0,
)
ENTRY_TIME_BUCKET_SECONDS = 30
ENTRY_TIME_BUCKETS_RAW = os.getenv("ENTRY_TIME_BUCKETS", "").strip()
DRY_RUN = os.getenv("DRY_RUN", "true").strip().lower() == "true"
OPEN_ANCHOR_MODE = os.getenv("OPEN_ANCHOR_MODE", "pm").strip().lower()
if OPEN_ANCHOR_MODE not in {"pm", "bn", "mix"}:
    raise ValueError("OPEN_ANCHOR_MODE 只支援 pm、bn 或 mix")
OPEN_ANCHOR_WEIGHT = min(
    max(float(os.getenv("OPEN_ANCHOR_WEIGHT", "0.5")), 0.0),
    1.0,
)
TAKER_ORDER_TYPE = os.getenv("TAKER_ORDER_TYPE", "FOK").strip().upper()
if TAKER_ORDER_TYPE not in {"FOK", "FAK"}:
    raise ValueError("TAKER_ORDER_TYPE 只支援 FOK 或 FAK")
TAKER_ORDER_TYPE_ENUM = getattr(OrderType, TAKER_ORDER_TYPE)
EXEC_PRICE_MODE = os.getenv("EXEC_PRICE_MODE", "hybrid").strip().lower()
if EXEC_PRICE_MODE not in {"book", "edge", "hybrid", "market"}:
    raise ValueError("EXEC_PRICE_MODE 只支援 book、edge、hybrid 或 market")
EXEC_SLIPPAGE_TICKS = max(int(os.getenv("EXEC_SLIPPAGE_TICKS", "1")), 0)
MIN_EDGE_AFTER_FILL = max(float(os.getenv("MIN_EDGE_AFTER_FILL", "0.03")), 0.0)
EXEC_PRICE_CAP = min(max(float(os.getenv("EXEC_PRICE_CAP", "0.99")), 0.0), 1.0)
ML_FILTER_ENABLED = os.getenv("ML_FILTER_ENABLED", "false").strip().lower() == "true"
ML_FILTER_MODEL_PATH = Path(
    os.getenv("ML_FILTER_MODEL_PATH", "models/signal_filter_lgbm_v1.txt")
)
ML_FILTER_FEATURES_PATH = Path(
    os.getenv("ML_FILTER_FEATURES_PATH", "models/signal_filter_lgbm_v1_features.json")
)
ML_FILTER_MIN_EV = float(os.getenv("ML_FILTER_MIN_EV", "0.0"))
ML_FILTER_FAIL_OPEN = os.getenv("ML_FILTER_FAIL_OPEN", "false").strip().lower() == "true"
RAW_CANDIDATE_LOG_ENABLED = (
    os.getenv("RAW_CANDIDATE_LOG_ENABLED", "false").strip().lower() == "true"
)
FILL_PROB_FILTER_ENABLED = (
    os.getenv("FILL_PROB_FILTER_ENABLED", "false").strip().lower() == "true"
)
FILL_PROB_MODEL_PATH = Path(
    os.getenv(
        "FILL_PROB_MODEL_PATH",
        "models/live_candidate_research_weekdays_2026-05-21_30/fill_probability_model.txt",
    )
)
FILL_PROB_FEATURES_PATH = Path(
    os.getenv(
        "FILL_PROB_FEATURES_PATH",
        "models/live_candidate_research_weekdays_2026-05-21_30/features.json",
    )
)
FILL_PROB_MIN_PROBABILITY = float(os.getenv("FILL_PROB_MIN_PROBABILITY", "0.75"))
FILL_PROB_FAIL_OPEN = (
    os.getenv("FILL_PROB_FAIL_OPEN", "false").strip().lower() == "true"
)
MARKET_MAX_TOTAL_COST = max(float(os.getenv("MARKET_MAX_TOTAL_COST", "12.0")), 0.0)
MARKET_MAX_SIDE_COST = max(float(os.getenv("MARKET_MAX_SIDE_COST", "8.0")), 0.0)
SIDE_EXTENSION_ENABLED = (
    os.getenv("SIDE_EXTENSION_ENABLED", "false").strip().lower() == "true"
)
SIDE_EXTENSION_START_COST = max(
    float(os.getenv("SIDE_EXTENSION_START_COST", str(MARKET_MAX_SIDE_COST))),
    0.0,
)
SIDE_EXTENSION_MAX_SIDE_COST = max(
    float(os.getenv("SIDE_EXTENSION_MAX_SIDE_COST", str(MARKET_MAX_SIDE_COST))),
    0.0,
)
SIDE_EXTENSION_MIN_SECONDS = max(
    int(os.getenv("SIDE_EXTENSION_MIN_SECONDS", "20")),
    0,
)
SIDE_EXTENSION_COOLDOWN_SECONDS = max(
    int(os.getenv("SIDE_EXTENSION_COOLDOWN_SECONDS", "15")),
    0,
)
SIDE_EXTENSION_MIN_EDGE = max(
    float(os.getenv("SIDE_EXTENSION_MIN_EDGE", "0.22")),
    0.0,
)
SIDE_EXTENSION_MIN_EDGE_AFTER_FILL = max(
    float(os.getenv("SIDE_EXTENSION_MIN_EDGE_AFTER_FILL", "0.20")),
    0.0,
)
SIDE_EXTENSION_MIN_ASK_PRICE = max(
    float(os.getenv("SIDE_EXTENSION_MIN_ASK_PRICE", "0.40")),
    0.0,
)
SIDE_EXTENSION_MAX_ASK_PRICE = min(
    max(float(os.getenv("SIDE_EXTENSION_MAX_ASK_PRICE", "0.80")), 0.0),
    1.0,
)
SIDE_EXTENSION_MAX_OPPOSITE_COST = max(
    float(os.getenv("SIDE_EXTENSION_MAX_OPPOSITE_COST", "1.0")),
    0.0,
)
SIDE_EXTENSION_EFFECTIVE_START_COST = max(
    MARKET_MAX_SIDE_COST,
    SIDE_EXTENSION_START_COST,
)
SIDE_EXTENSION_EFFECTIVE_MAX_SIDE_COST = max(
    SIDE_EXTENSION_EFFECTIVE_START_COST,
    SIDE_EXTENSION_MAX_SIDE_COST,
)

TAIL_REVERSAL_COOLDOWN_ENABLED = (
    os.getenv("TAIL_REVERSAL_COOLDOWN_ENABLED", "false").strip().lower() == "true"
)
TAIL_REVERSAL_LOOKBACK_SECONDS = max(
    float(os.getenv("TAIL_REVERSAL_LOOKBACK_SECONDS", "5400")),
    0.0,
)
TAIL_REVERSAL_TRIGGER_COUNT = max(
    int(os.getenv("TAIL_REVERSAL_TRIGGER_COUNT", "2")),
    0,
)
TAIL_REVERSAL_COOLDOWN_SECONDS = max(
    float(os.getenv("TAIL_REVERSAL_COOLDOWN_SECONDS", "1800")),
    0.0,
)
TAIL_REVERSAL_ANCHOR_SECONDS = max(
    float(os.getenv("TAIL_REVERSAL_ANCHOR_SECONDS", "30")),
    0.0,
)
TAIL_REVERSAL_CONFIRM_SECONDS = max(
    float(os.getenv("TAIL_REVERSAL_CONFIRM_SECONDS", "5")),
    0.0,
)
TAIL_REVERSAL_MIN_ANCHOR_PROB = min(
    max(float(os.getenv("TAIL_REVERSAL_MIN_ANCHOR_PROB", "0.55")), 0.0),
    1.0,
)
TAIL_REVERSAL_MIN_PROB_DROP = max(
    float(os.getenv("TAIL_REVERSAL_MIN_PROB_DROP", "0.10")),
    0.0,
)
TAIL_REVERSAL_MIN_MID_GAIN = max(
    float(os.getenv("TAIL_REVERSAL_MIN_MID_GAIN", "0.03")),
    0.0,
)

# 雙尺度外部 anchor 機率模型參數
VOL_WINDOW_SHORT_SECONDS = max(
    int(os.getenv("VOL_WINDOW_SHORT_SECONDS", os.getenv("VOL_WINDOW_SECONDS", "30"))),
    3,
)
VOL_WINDOW_LONG_SECONDS = max(
    int(os.getenv("VOL_WINDOW_LONG_SECONDS", "240")),
    VOL_WINDOW_SHORT_SECONDS,
)
SIGMA_SHORT_WEIGHT = max(float(os.getenv("SIGMA_SHORT_WEIGHT", "0.6")), 0.0)
SIGMA_LONG_WEIGHT = max(float(os.getenv("SIGMA_LONG_WEIGHT", "0.4")), 0.0)
SIGMA_MIN = max(
    float(os.getenv("SIGMA_MIN", os.getenv("SIGMA_FLOOR", "0.00001"))), 0.0
)
TAU_FLOOR_SECONDS = int(os.getenv("TAU_FLOOR_SECONDS", "5"))
Z_CAP = max(float(os.getenv("Z_CAP", "6.0")), 0.1)
SIGNAL_MODEL_NAME = "v2_dual_sigma"
BN_PRICE_BUFFER_SECONDS = max(300, VOL_WINDOW_LONG_SECONDS + 5)

SIGMA_WEIGHT_SUM = SIGMA_SHORT_WEIGHT + SIGMA_LONG_WEIGHT
if SIGMA_WEIGHT_SUM <= 0:
    SIGMA_SHORT_WEIGHT = 1.0
    SIGMA_LONG_WEIGHT = 0.0
    SIGMA_WEIGHT_SUM = 1.0

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@trade"
PM_WS_URL = (
    os.getenv("PM_WS_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/market").strip()
    or "wss://ws-subscriptions-clob.polymarket.com/ws/market"
)

ET_TZ = ZoneInfo("America/New_York")

SHOW_BN_TICK_LOG = os.getenv("SHOW_BN_TICK_LOG", "false").strip().lower() == "true"
SHOW_PM_QUOTE_LOG = os.getenv("SHOW_PM_QUOTE_LOG", "false").strip().lower() == "true"
SHOW_LEDGER_SNAPSHOT_LOG = (
    os.getenv("SHOW_LEDGER_SNAPSHOT_LOG", "true").strip().lower() == "true"
)

# 內部帳本輸出
LEDGER_DIR = Path(os.getenv("LEDGER_DIR", "ledger"))
ORDERS_CSV_PATH = LEDGER_DIR / "orders.csv"
MARKET_SETTLEMENTS_CSV_PATH = LEDGER_DIR / "market_settlements.csv"
SIGNAL_REJECTIONS_CSV_PATH = LEDGER_DIR / "signal_rejections.csv"
EXECUTION_ATTEMPTS_CSV_PATH = LEDGER_DIR / "execution_attempts.csv"
RAW_CANDIDATES_CSV_PATH = LEDGER_DIR / "raw_candidates.csv"
MARKET_STATE_JSON_PATH = LEDGER_DIR / "market_state.json"

# Tick-level market snapshots for offline replay/backtesting.
TICK_SNAPSHOT_ENABLED = (
    os.getenv("TICK_SNAPSHOT_ENABLED", "false").strip().lower() == "true"
)
TICK_SNAPSHOT_MODE = os.getenv("TICK_SNAPSHOT_MODE", "event").strip().lower()
if TICK_SNAPSHOT_MODE not in {"event", "interval", "both"}:
    raise ValueError("TICK_SNAPSHOT_MODE 只支援 event、interval 或 both")
TICK_SNAPSHOT_MIN_INTERVAL_MS = max(
    int(os.getenv("TICK_SNAPSHOT_MIN_INTERVAL_MS", "250")), 0
)
TICK_SNAPSHOT_INTERVAL_SECONDS = max(
    float(os.getenv("TICK_SNAPSHOT_INTERVAL_SECONDS", "3")), 0.1
)
TICK_SNAPSHOT_DIR = Path(os.getenv("TICK_SNAPSHOT_DIR", "tick_snapshots"))

ml_signal_filter = MLSignalFilter(
    enabled=ML_FILTER_ENABLED,
    model_path=ML_FILTER_MODEL_PATH,
    features_path=ML_FILTER_FEATURES_PATH,
    min_ev=ML_FILTER_MIN_EV,
    fail_open=ML_FILTER_FAIL_OPEN,
)
fill_probability_filter = MLSignalFilter(
    enabled=FILL_PROB_FILTER_ENABLED,
    model_path=FILL_PROB_MODEL_PATH,
    features_path=FILL_PROB_FEATURES_PATH,
    min_ev=FILL_PROB_MIN_PROBABILITY,
    fail_open=FILL_PROB_FAIL_OPEN,
)
ml_feature_metadata_cache: Optional[Dict[str, Any]] = None
fill_prob_feature_metadata_cache: Optional[Dict[str, Any]] = None

ORDERS_FIELDNAMES = [
    "recorded_at",
    "market_slug",
    "market_question",
    "market_start_utc",
    "market_end_utc",
    "mode",
    "status",
    "included_in_position",
    "resolution_side_intended",
    "outcome_bought",
    "amount_usd",
    "requested_amount_usd",
    "filled_amount_usd",
    "fill_ratio",
    "execution_price_estimate",
    "estimated_shares_gross",
    "estimated_fee_usdc",
    "estimated_fee_shares",
    "estimated_shares_net",
    "fee_rate_bps",
    "fees_enabled",
    "signal_model",
    "signal_fair",
    "signal_edge",
    "signal_edge_reference",
    "signal_reference_price",
    "signal_bid",
    "signal_ask",
    "signal_spread",
    "signal_open_anchor_mode",
    "signal_open_anchor_weight",
    "signal_open_anchor_price",
    "signal_pm_open_price",
    "signal_bn_open_price",
    "signal_order_type",
    "signal_exec_price_mode",
    "signal_max_execution_price",
    "signal_order_price_hint",
    "signal_edge_after_fill_estimate",
    "bn_price",
    "bn_open_price",
    "sigma",
    "sigma_short",
    "sigma_long",
    "sigma_eff",
    "tau_seconds",
    "z",
    "response_order_id",
    "error",
]

MARKET_SETTLEMENTS_FIELDNAMES = [
    "settled_at",
    "market_slug",
    "market_question",
    "market_start_utc",
    "market_end_utc",
    "open_price",
    "open_price_source",
    "resolution_price",
    "resolution_price_source",
    "bn_resolution_price_fallback",
    "resolved_side",
    "yes_fee_rate_bps",
    "down_fee_rate_bps",
    "fees_enabled",
    "settlement_reason",
    "yes_orders",
    "down_orders",
    "yes_shares",
    "down_shares",
    "yes_cost",
    "down_cost",
    "total_cost",
    "estimated_fee_total",
    "gross_payout_estimate",
    "net_pnl_estimate",
    "pnl_if_up_estimate",
    "pnl_if_down_estimate",
    "mode_observed",
]

SIGNAL_REJECTIONS_FIELDNAMES = [
    "recorded_at",
    "market_slug",
    "market_question",
    "market_start_utc",
    "market_end_utc",
    "mode",
    "rejection_stage",
    "rejection_reason",
    "side",
    "outcome_bought",
    "amount_usd",
    "signal_model",
    "signal_fair",
    "signal_edge",
    "signal_edge_reference",
    "signal_reference_price",
    "signal_bid",
    "signal_ask",
    "signal_spread",
    "signal_order_type",
    "signal_exec_price_mode",
    "signal_max_execution_price",
    "signal_edge_after_fill_estimate",
    "signal_open_anchor_mode",
    "signal_open_anchor_weight",
    "signal_open_anchor_price",
    "signal_pm_open_price",
    "signal_bn_open_price",
    "bn_price",
    "bn_open_price",
    "sigma",
    "sigma_short",
    "sigma_long",
    "sigma_eff",
    "tau_seconds",
    "z",
    "yes_cost",
    "down_cost",
    "total_cost",
    "is_extension_zone",
]

EXECUTION_ATTEMPTS_FIELDNAMES = [
    "recorded_at",
    "candidate_id",
    "market_slug",
    "market_question",
    "market_start_utc",
    "market_end_utc",
    "elapsed_seconds",
    "time_bucket",
    "mode",
    "dry_run",
    "status",
    "attempt_stage",
    "side",
    "outcome_bought",
    "token_id",
    "amount_usd",
    "order_type",
    "exec_price_mode",
    "is_extension_order",
    "signal_model",
    "signal_fair",
    "signal_edge",
    "signal_edge_reference",
    "signal_reference_price",
    "signal_bid",
    "signal_ask",
    "signal_spread",
    "signal_open_anchor_mode",
    "signal_open_anchor_weight",
    "signal_open_anchor_price",
    "signal_pm_open_price",
    "signal_bn_open_price",
    "bn_price",
    "bn_open_price",
    "sigma",
    "sigma_short",
    "sigma_long",
    "sigma_eff",
    "tau_seconds",
    "z",
    "limit_price",
    "order_price_hint",
    "signal_edge_after_fill_estimate",
    "ml_filter_enabled",
    "ml_predicted_ev",
    "ml_min_ev",
    "ml_passed",
    "ml_reason",
    "ml_model_path",
    "ml_features_path",
    "ml_model_target",
    "ml_prediction_unit",
    "ml_feature_names",
    "ml_feature_values_json",
    "fill_prob_filter_enabled",
    "fill_probability",
    "fill_prob_min_probability",
    "fill_prob_passed",
    "fill_prob_reason",
    "fill_prob_model_path",
    "fill_prob_features_path",
    "fill_prob_model_target",
    "fill_prob_prediction_unit",
    "fill_prob_feature_names",
    "fill_prob_feature_values_json",
    "order_sent",
    "order_accepted",
    "filled",
    "fill_inferred",
    "fill_amount_usd",
    "fill_shares",
    "fill_avg_price",
    "fill_ratio",
    "fill_price",
    "fill_size",
    "response_order_id",
    "latency_ms",
    "failed_reason",
    "raw_response",
]

RAW_CANDIDATES_FIELDNAMES = [
    "recorded_at",
    "candidate_id",
    "market_slug",
    "market_question",
    "market_start_utc",
    "market_end_utc",
    "elapsed_seconds",
    "time_bucket",
    "mode",
    "dry_run",
    "candidate_stage",
    "candidate_action",
    "side",
    "outcome_bought",
    "token_id",
    "amount_usd",
    "order_type",
    "exec_price_mode",
    "is_extension_order",
    "signal_model",
    "signal_fair",
    "signal_edge",
    "signal_edge_reference",
    "signal_reference_price",
    "signal_bid",
    "signal_ask",
    "signal_spread",
    "signal_open_anchor_mode",
    "signal_open_anchor_weight",
    "signal_open_anchor_price",
    "signal_pm_open_price",
    "signal_bn_open_price",
    "bn_price",
    "bn_open_price",
    "sigma",
    "sigma_short",
    "sigma_long",
    "sigma_eff",
    "tau_seconds",
    "z",
    "limit_price",
    "order_price_hint",
    "signal_edge_after_fill_estimate",
    "yes_cost",
    "down_cost",
    "total_cost",
    "ml_filter_enabled",
    "ml_predicted_ev",
    "ml_min_ev",
    "ml_passed",
    "ml_reason",
    "ml_model_path",
    "ml_features_path",
    "ml_model_target",
    "ml_prediction_unit",
    "ml_feature_names",
    "ml_feature_values_json",
    "fill_prob_filter_enabled",
    "fill_probability",
    "fill_prob_min_probability",
    "fill_prob_passed",
    "fill_prob_reason",
    "fill_prob_model_path",
    "fill_prob_features_path",
    "fill_prob_model_target",
    "fill_prob_prediction_unit",
    "fill_prob_feature_names",
    "fill_prob_feature_values_json",
]

# 依官方規則動態抓 fee rate：
# - 透過 /fee-rate?token_id={token_id} 取得 base_fee (bps)
# - 若市場 fee-free，會回 0
# - 費用四捨五入到 5 位小數 USDC；買單以 shares 扣除
FEE_FETCH_TIMEOUT_SECONDS = float(os.getenv("FEE_FETCH_TIMEOUT_SECONDS", "5.0"))
FEE_FETCH_RETRY_ON_SWITCH = (
    os.getenv("FEE_FETCH_RETRY_ON_SWITCH", "true").strip().lower() == "true"
)
PM_OPEN_FETCH_TIMEOUT_SECONDS = float(
    os.getenv("PM_OPEN_FETCH_TIMEOUT_SECONDS", "5.0")
)
PM_OPEN_RETRY_SECONDS = float(os.getenv("PM_OPEN_RETRY_SECONDS", "3.0"))


# ====================== TLS / HTTP ======================
CA_BUNDLE = certifi.where()
SSL_CONTEXT = ssl.create_default_context(cafile=CA_BUNDLE)

HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "Mozilla/5.0"})
HTTP.verify = CA_BUNDLE


# ====================== 全域狀態 ======================
pm_yes_token = None  # 本市場對應 Up token
pm_no_token = None  # 本市場對應 Down token

pm_yes_best_bid = None
pm_yes_best_ask = None
pm_no_best_bid = None
pm_no_best_ask = None

bn_last_price = None
last_tick_snapshot_event_ms = 0.0
last_tick_snapshot_error_time = 0.0

client = None
condition_id = None
tick_size = None
neg_risk = None
current_clob_market_info = None

current_market_slug = None
current_market_question = None
current_market_start_dt = None  # 由 slug timestamp 推回
current_market_end_dt = None  # start + MARKET_BUCKET_MINUTES

# 策略 / 帳本開盤價狀態
bn_second_prices = deque(maxlen=BN_PRICE_BUFFER_SECONDS)
bn_last_sampled_second = None
bn_last_warmup_log_time = 0.0
sigma_long_warmup_complete = False
pm_bucket_open_price = None
bn_bucket_open_price = None
pm_open_price_retry_task = None

# order layer 狀態
last_order_time = 0.0
order_lock = asyncio.Lock()

# signal layer 狀態：side-based cooldown
signal_state = {
    "UP": {"last_emit_time": 0.0},
    "DOWN": {"last_emit_time": 0.0},
}
entry_gate_rejection_state: Dict[Tuple[str, str], float] = {}

# 市場帳本：以市場 slug 為 key
market_ledgers: Dict[str, Dict[str, Any]] = {}
pending_settlement: Optional[Dict[str, Any]] = None
tail_reversal_recent_hit_times: deque[datetime] = deque()
tail_reversal_cooldown_until: Optional[datetime] = None

# 本次系統啟動期間的累計結算收益（不回讀歷史帳本）
session_net_pnl_total = 0.0

# 當前市場 fee 狀態（動態抓取）
current_yes_fee_rate_bps = 0
current_down_fee_rate_bps = 0
current_fee_rules_source = "uninitialized"
current_fees_enabled = False
current_fee_taker_only = True


# ====================== 工具函數 ======================
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utcnow().isoformat()


def parse_dt(value: Optional[Any]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return (
            value.astimezone(timezone.utc)
            if value.tzinfo
            else value.replace(tzinfo=timezone.utc)
        )
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except Exception:
        return None


def parse_jsonish_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            return [s]
    return []


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def pick_first_value(obj: Any, *keys: str) -> Any:
    if isinstance(obj, dict):
        for key in keys:
            if key in obj and obj[key] is not None:
                return obj[key]

    for key in keys:
        if hasattr(obj, key):
            value = getattr(obj, key)
            if value is not None:
                return value

    return None


def build_builder_config() -> Optional[BuilderConfig]:
    if not POLY_BUILDER_CODE:
        return None
    return BuilderConfig(builder_code=POLY_BUILDER_CODE)


def create_clob_client_instance(
    *,
    key: Optional[str] = None,
    funder: Optional[str] = None,
    read_only: bool = False,
) -> Any:
    builder_config = build_builder_config()
    attempts: List[Dict[str, Any]] = []

    if read_only:
        attempts = [{"host": CLOB_HOST, "chain_id": CHAIN_ID}]
    else:
        base_payload = {
            "host": CLOB_HOST,
            "key": key,
            "signature_type": POLY_SIGNATURE_TYPE,
            "funder": funder,
        }
        attempts = [{**base_payload, "chain_id": CHAIN_ID}]
        if builder_config:
            attempts.insert(0, {**base_payload, "chain_id": CHAIN_ID, "builder_config": builder_config})

    last_error = None
    for kwargs in attempts:
        try:
            return ClobClient(**kwargs)
        except TypeError as exc:
            last_error = exc
            continue

    if last_error is not None:
        raise last_error
    raise RuntimeError("Unable to initialize ClobClient")


def create_or_derive_api_credentials(active_client: Any) -> Any:
    return active_client.create_or_derive_api_key()


def normalize_fee_rate_bps(raw_rate: Any, raw_exponent: Any) -> int:
    rate_value = safe_float(raw_rate, 0.0)
    if rate_value <= 0:
        return 0

    exponent = 0
    try:
        exponent = int(raw_exponent)
    except Exception:
        exponent = 0

    if exponent > 0 and rate_value > 1:
        rate_decimal = rate_value / (10**exponent)
    else:
        rate_decimal = rate_value

    if rate_decimal > 1:
        rate_decimal = rate_decimal / 10000.0

    return max(int(round(rate_decimal * 10000)), 0)


def extract_clob_market_fee_details(clob_market_info: Any) -> Optional[Dict[str, Any]]:
    raw_fee_details = pick_first_value(clob_market_info, "fd", "feeDetails", "fee_details")
    if raw_fee_details is None:
        return None

    fee_rate_bps = normalize_fee_rate_bps(
        pick_first_value(raw_fee_details, "r", "rate"),
        pick_first_value(raw_fee_details, "e", "exponent"),
    )
    taker_only = bool(pick_first_value(raw_fee_details, "to", "takerOnly", "taker_only"))

    return {
        "raw": raw_fee_details,
        "fee_rate_bps": fee_rate_bps,
        "taker_only": taker_only,
    }


def extract_clob_market_tokens(clob_market_info: Any) -> Dict[str, str]:
    tokens = pick_first_value(clob_market_info, "t", "tokens") or []
    if not isinstance(tokens, list):
        return {}

    outcome_to_token: Dict[str, str] = {}
    for token in tokens:
        token_id = pick_first_value(token, "t", "tokenID", "token_id", "tokenId")
        outcome = pick_first_value(token, "o", "outcome")
        if token_id is None or outcome is None:
            continue
        outcome_to_token[str(outcome).strip().lower()] = str(token_id)
    return outcome_to_token


def fetch_clob_market_info(
    condition_id_value: Optional[str],
    target_client: Optional[Any] = None,
) -> Optional[Any]:
    if not condition_id_value:
        return None

    active_client = target_client or client
    if active_client is None:
        return None

    try:
        return active_client.get_clob_market_info(condition_id_value)
    except Exception:
        return None


def apply_clob_market_info_overrides(
    market_data: Dict[str, Any],
    target_client: Optional[Any] = None,
) -> Dict[str, Any]:
    global current_clob_market_info

    condition_id_value = market_data.get("conditionId")
    clob_market_info = fetch_clob_market_info(condition_id_value, target_client=target_client)
    if clob_market_info is None:
        return market_data

    current_clob_market_info = clob_market_info
    outcome_to_token = extract_clob_market_tokens(clob_market_info)
    up_token = outcome_to_token.get("up") or outcome_to_token.get("yes")
    down_token = outcome_to_token.get("down") or outcome_to_token.get("no")
    tick_size_value = pick_first_value(
        clob_market_info,
        "mts",
        "minimumTickSize",
        "minimum_tick_size",
    )

    if up_token:
        market_data["up_token_id"] = up_token
    if down_token:
        market_data["down_token_id"] = down_token
    if tick_size_value is not None:
        market_data["tick_size"] = tick_size_value

    market_data["clob_market_info"] = clob_market_info
    return market_data


def format_utc_iso_z(dt: datetime) -> str:
    return (
        dt.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def format_optional_price(price: Optional[float]) -> str:
    value = safe_float(price, 0.0)
    return f"{value:,.2f}" if value > 0 else "pending"


def resolve_effective_open_price(
    pm_open_price: Optional[float], bn_open_price: Optional[float]
) -> Tuple[float, str]:
    pm_open = safe_float(pm_open_price, 0.0)
    if pm_open > 0:
        return pm_open, "pm"

    bn_open = safe_float(bn_open_price, 0.0)
    if bn_open > 0:
        return bn_open, "bn_fallback"

    return 0.0, "missing"


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def get_spread(best_bid: Optional[Any], best_ask: Optional[Any]) -> Optional[float]:
    if best_bid is None or best_ask is None:
        return None
    try:
        return float(best_ask) - float(best_bid)
    except Exception:
        return None


def get_edge_reference_price(
    *, bid: float, ask: float
) -> Tuple[str, float]:
    if EDGE_REFERENCE_PRICE == "ask":
        return "ask", ask
    return "bid", bid


def format_time_bucket(bucket: Tuple[int, int]) -> str:
    return f"{bucket[0]}-{bucket[1]}"


def parse_entry_time_buckets_config(value: str) -> Tuple[Tuple[int, int], ...]:
    if not value:
        return tuple()

    buckets: List[Tuple[int, int]] = []
    seen = set()
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        return tuple()

    for part in parts:
        bounds = part.split("-", 1)
        if len(bounds) != 2:
            raise ValueError(
                "ENTRY_TIME_BUCKETS 格式錯誤，需為逗號分隔的 start-end，例如 60-90,90-120"
            )

        try:
            start = int(bounds[0])
            end = int(bounds[1])
        except ValueError as exc:
            raise ValueError(
                f"ENTRY_TIME_BUCKETS 含非整數 bucket: {part}"
            ) from exc

        if start < 0 or end <= start:
            raise ValueError(f"ENTRY_TIME_BUCKETS bucket 範圍無效: {part}")
        if (end - start) != ENTRY_TIME_BUCKET_SECONDS:
            raise ValueError(
                f"ENTRY_TIME_BUCKETS 每個 bucket 必須固定 {ENTRY_TIME_BUCKET_SECONDS} 秒: {part}"
            )
        if (start % ENTRY_TIME_BUCKET_SECONDS) != 0 or (end % ENTRY_TIME_BUCKET_SECONDS) != 0:
            raise ValueError(
                f"ENTRY_TIME_BUCKETS 需對齊 {ENTRY_TIME_BUCKET_SECONDS} 秒邊界: {part}"
            )
        if start >= MARKET_DURATION_SECONDS or end > MARKET_DURATION_SECONDS:
            raise ValueError(
                f"ENTRY_TIME_BUCKETS 超出市場時間範圍 0-{MARKET_DURATION_SECONDS}: {part}"
            )

        bucket = (start, end)
        if bucket not in seen:
            seen.add(bucket)
            buckets.append(bucket)

    buckets.sort()
    return tuple(buckets)


ENTRY_TIME_BUCKETS = parse_entry_time_buckets_config(ENTRY_TIME_BUCKETS_RAW)
ENTRY_TIME_BUCKETS_ENABLED = bool(ENTRY_TIME_BUCKETS)
ENTRY_TIME_BUCKETS_LABEL = (
    ",".join(format_time_bucket(bucket) for bucket in ENTRY_TIME_BUCKETS)
    if ENTRY_TIME_BUCKETS_ENABLED
    else "off"
)


def get_current_time_bucket_context(
    now_dt: Optional[datetime] = None,
) -> Tuple[Optional[float], Optional[Tuple[int, int]], str]:
    if current_market_start_dt is None:
        return None, None, "missing_market_start"

    ref_dt = now_dt or utcnow()
    elapsed_seconds = (ref_dt - current_market_start_dt).total_seconds()
    if elapsed_seconds < 0:
        return elapsed_seconds, None, "before_market_start"
    if elapsed_seconds >= MARKET_DURATION_SECONDS:
        return elapsed_seconds, None, "out_of_range"

    bucket_start = int(elapsed_seconds // ENTRY_TIME_BUCKET_SECONDS) * ENTRY_TIME_BUCKET_SECONDS
    bucket = (bucket_start, bucket_start + ENTRY_TIME_BUCKET_SECONDS)
    return elapsed_seconds, bucket, ""


def evaluate_entry_time_bucket_gate(
    now_dt: Optional[datetime] = None,
) -> Tuple[bool, str, Optional[float], str]:
    elapsed_seconds, bucket, context_error = get_current_time_bucket_context(now_dt)
    bucket_label = format_time_bucket(bucket) if bucket is not None else context_error
    elapsed_text = f"{elapsed_seconds:.1f}s" if elapsed_seconds is not None else "n/a"

    if MIN_ENTRY_REMAINING_SECONDS > 0 and elapsed_seconds is not None:
        remaining_seconds = MARKET_DURATION_SECONDS - elapsed_seconds
        if remaining_seconds < MIN_ENTRY_REMAINING_SECONDS:
            return (
                False,
                "min_entry_remaining_not_met | "
                f"elapsed={elapsed_text} | "
                f"remaining={remaining_seconds:.1f}s | "
                f"min_remaining={MIN_ENTRY_REMAINING_SECONDS:.1f}s",
                elapsed_seconds,
                bucket_label,
            )

    if not ENTRY_TIME_BUCKETS_ENABLED:
        return True, "", elapsed_seconds, bucket_label

    if bucket is None:
        return (
            False,
            "time_bucket_not_allowed | "
            f"elapsed={elapsed_text} | "
            f"bucket={bucket_label} | "
            f"allowed={ENTRY_TIME_BUCKETS_LABEL}",
            elapsed_seconds,
            bucket_label,
        )

    if bucket not in ENTRY_TIME_BUCKETS:
        return (
            False,
            "time_bucket_not_allowed | "
            f"elapsed={elapsed_text} | "
            f"bucket={bucket_label} | "
            f"allowed={ENTRY_TIME_BUCKETS_LABEL}",
            elapsed_seconds,
            bucket_label,
        )

    return True, "", elapsed_seconds, bucket_label


def classify_entry_time_gate_rejection(reject_reason: str) -> Tuple[str, str, str]:
    if reject_reason.startswith("min_entry_remaining_not_met"):
        return (
            "min_entry_remaining_gate",
            "blocked_min_entry_remaining",
            "尾盤 remaining gate",
        )
    return "time_bucket_gate", "blocked_time_bucket", "時間 bucket"


def can_log_entry_time_gate_rejection(side: str, gate_stage: str) -> bool:
    now = time.time()
    key = (side, gate_stage)
    last_logged = entry_gate_rejection_state.get(key, 0.0)
    if now - last_logged < SIGNAL_COOLDOWN_SECONDS:
        return False
    entry_gate_rejection_state[key] = now
    return True


def get_tick_size_float() -> float:
    tick = safe_float(tick_size, 0.01)
    return tick if tick > 0 else 0.01


def get_tick_decimals(tick: float) -> int:
    tick_str = f"{tick:.12f}".rstrip("0")
    if "." not in tick_str:
        return 0
    return len(tick_str.split(".", 1)[1])


def quantize_price_down(price: float, tick: float) -> float:
    if tick <= 0:
        return price
    decimals = get_tick_decimals(tick)
    steps = math.floor((price / tick) + 1e-9)
    return round(steps * tick, decimals)


def compute_execution_plan(*, fair: float, ask: float) -> Optional[Dict[str, Any]]:
    ask = safe_float(ask, 0.0)
    fair = safe_float(fair, 0.0)
    if ask <= 0 or fair <= 0:
        return None

    tick = get_tick_size_float()
    max_book_price = ask + (EXEC_SLIPPAGE_TICKS * tick)
    max_edge_price = fair - MIN_EDGE_AFTER_FILL

    if EXEC_PRICE_MODE == "book":
        max_execution_price = max_book_price
    elif EXEC_PRICE_MODE == "edge":
        max_execution_price = max_edge_price
    else:
        # In market mode this is a local guard/estimate only; the order is sent
        # without a price hint.
        max_execution_price = min(max_book_price, max_edge_price)

    if EXEC_PRICE_CAP > 0:
        max_execution_price = min(max_execution_price, EXEC_PRICE_CAP)

    max_execution_price = min(max_execution_price, 1.0 - tick)
    max_execution_price = quantize_price_down(max_execution_price, tick)
    if max_execution_price < ask:
        return None

    return {
        "order_type": TAKER_ORDER_TYPE,
        "exec_price_mode": EXEC_PRICE_MODE,
        "max_execution_price": max_execution_price,
        "order_price_hint": (
            None if EXEC_PRICE_MODE == "market" else max_execution_price
        ),
        "edge_after_fill_estimate": fair - max_execution_price,
    }


def ensure_ledger_files() -> None:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)

    if not ORDERS_CSV_PATH.exists():
        with ORDERS_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=ORDERS_FIELDNAMES,
            )
            writer.writeheader()
    else:
        migrate_orders_csv_if_needed()

    if not MARKET_SETTLEMENTS_CSV_PATH.exists():
        with MARKET_SETTLEMENTS_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=MARKET_SETTLEMENTS_FIELDNAMES,
            )
            writer.writeheader()
    else:
        migrate_market_settlements_csv_if_needed()

    if not SIGNAL_REJECTIONS_CSV_PATH.exists():
        with SIGNAL_REJECTIONS_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=SIGNAL_REJECTIONS_FIELDNAMES,
            )
            writer.writeheader()

    if not EXECUTION_ATTEMPTS_CSV_PATH.exists():
        with EXECUTION_ATTEMPTS_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=EXECUTION_ATTEMPTS_FIELDNAMES,
            )
            writer.writeheader()
    else:
        migrate_execution_attempts_csv_if_needed()

    if RAW_CANDIDATE_LOG_ENABLED:
        if not RAW_CANDIDATES_CSV_PATH.exists():
            with RAW_CANDIDATES_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=RAW_CANDIDATES_FIELDNAMES)
                writer.writeheader()
        else:
            migrate_raw_candidates_csv_if_needed()

    if not MARKET_STATE_JSON_PATH.exists():
        MARKET_STATE_JSON_PATH.write_text("{}", encoding="utf-8")


def append_csv_row(path: Path, row: Dict[str, Any], fieldnames: List[str]) -> None:
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writerow(row)


def migrate_csv_fieldnames_if_needed(path: Path, fieldnames: List[str]) -> None:
    if not path.exists():
        return

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        current_fieldnames = reader.fieldnames or []
        if current_fieldnames == fieldnames:
            return
        rows = list(reader)

    backup_path = path.with_name(f"{path.stem}.legacy_backup{path.suffix}")
    if not backup_path.exists():
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def migrate_execution_attempts_csv_if_needed() -> None:
    migrate_csv_fieldnames_if_needed(
        EXECUTION_ATTEMPTS_CSV_PATH,
        EXECUTION_ATTEMPTS_FIELDNAMES,
    )


def migrate_raw_candidates_csv_if_needed() -> None:
    migrate_csv_fieldnames_if_needed(
        RAW_CANDIDATES_CSV_PATH,
        RAW_CANDIDATES_FIELDNAMES,
    )


def migrate_orders_csv_if_needed() -> None:
    migrate_csv_fieldnames_if_needed(
        ORDERS_CSV_PATH,
        ORDERS_FIELDNAMES,
    )


def optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except Exception:
        return None
    return number if math.isfinite(number) else None


def compact_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        return str(value)


def load_ml_feature_metadata() -> Dict[str, Any]:
    global ml_feature_metadata_cache

    if ml_feature_metadata_cache is not None:
        return ml_feature_metadata_cache

    metadata: Dict[str, Any] = {}
    try:
        if ML_FILTER_FEATURES_PATH.exists():
            raw = json.loads(ML_FILTER_FEATURES_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                metadata = raw
    except Exception as exc:
        metadata = {"load_error": str(exc)}

    ml_feature_metadata_cache = metadata
    return metadata


def load_fill_prob_feature_metadata() -> Dict[str, Any]:
    global fill_prob_feature_metadata_cache

    if fill_prob_feature_metadata_cache is not None:
        return fill_prob_feature_metadata_cache

    metadata: Dict[str, Any] = {}
    try:
        if FILL_PROB_FEATURES_PATH.exists():
            raw = json.loads(FILL_PROB_FEATURES_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                metadata = raw
    except Exception as exc:
        metadata = {"load_error": str(exc)}

    fill_prob_feature_metadata_cache = metadata
    return metadata


def get_ml_feature_names_for_logging() -> List[str]:
    metadata = load_ml_feature_metadata()
    feature_names = metadata.get("feature_names")
    if isinstance(feature_names, list) and feature_names:
        return [str(name) for name in feature_names]
    return list(ml_signal_filter.feature_names or FEATURE_NAMES)


def get_fill_prob_feature_names_for_logging() -> List[str]:
    metadata = load_fill_prob_feature_metadata()
    feature_names = metadata.get("feature_names")
    if isinstance(feature_names, list) and feature_names:
        return [str(name) for name in feature_names]
    return list(fill_probability_filter.feature_names or FEATURE_NAMES)


def ensure_signal_candidate_id(source_signal: Optional[Dict[str, Any]]) -> str:
    if source_signal is None:
        return ""
    candidate_id = str(source_signal.get("candidate_id") or "").strip()
    if not candidate_id:
        candidate_id = uuid.uuid4().hex
        source_signal["candidate_id"] = candidate_id
    return candidate_id


def metadata_nested_value(
    metadata: Dict[str, Any],
    section_key: str,
    value_key: str,
) -> str:
    section = metadata.get(section_key)
    if isinstance(section, dict):
        return str(section.get(value_key, ""))
    return ""


def finite_difference(
    left: Optional[float],
    right: Optional[float],
) -> Optional[float]:
    if left is None or right is None:
        return None
    return left - right


def build_signal_filter_feature_values(
    *,
    signal_side: str,
    source_signal: Dict[str, Any],
    ledger: Dict[str, Any],
) -> Dict[str, Optional[float]]:
    rolling_6_roi, _ = recent_settled_market_metrics(6)
    rolling_10_roi, rolling_10_win_rate = recent_settled_market_metrics(10)
    return build_live_feature_values(
        source_signal=source_signal,
        ledger=ledger,
        signal_side=signal_side,
        yes_bid=optional_float(pm_yes_best_bid),
        yes_ask=optional_float(pm_yes_best_ask),
        down_bid=optional_float(pm_no_best_bid),
        down_ask=optional_float(pm_no_best_ask),
        rolling_6_market_roi=rolling_6_roi,
        rolling_10_market_roi=rolling_10_roi,
        rolling_10_market_win_rate=rolling_10_win_rate,
    )


def add_live_candidate_extra_features(
    features: Dict[str, Optional[float]],
    *,
    source_signal: Dict[str, Any],
    amount_usd: float,
) -> None:
    order_type = str(source_signal.get("order_type") or TAKER_ORDER_TYPE).upper()
    exec_mode = str(source_signal.get("exec_price_mode") or EXEC_PRICE_MODE).lower()
    limit_price = optional_float(source_signal.get("max_execution_price"))
    ask = optional_float(source_signal.get("ask"))
    bid = optional_float(source_signal.get("bid"))
    remaining_seconds = features.get("remaining_seconds")

    features.update(
        {
            "amount_usd": amount_usd,
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
            "limit_minus_ask": finite_difference(limit_price, ask),
            "limit_minus_bid": finite_difference(limit_price, bid),
            "ask_x_amount": ask * amount_usd if ask is not None else None,
        }
    )


def midpoint(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2.0


def optional_diff(left: Optional[float], right: Optional[float]) -> Optional[float]:
    if left is None or right is None:
        return None
    return left - right


def build_tick_snapshot(source_event: str) -> Optional[Dict[str, Any]]:
    if not current_market_slug:
        return None

    yes_bid = optional_float(pm_yes_best_bid)
    yes_ask = optional_float(pm_yes_best_ask)
    down_bid = optional_float(pm_no_best_bid)
    down_ask = optional_float(pm_no_best_ask)
    yes_mid = midpoint(yes_bid, yes_ask)
    down_mid = midpoint(down_bid, down_ask)
    fair = compute_fair_yes_from_bn()
    fair_yes = optional_float(fair.get("fair_yes") if fair else None)
    fair_no = optional_float(fair.get("fair_no") if fair else None)
    ledger = market_ledgers.get(current_market_slug) if current_market_slug else None

    return {
        "schema_version": 1,
        "ts": now_iso(),
        "ts_ms": int(time.time() * 1000),
        "source_event": source_event,
        "runtime_mode": "dry_run" if DRY_RUN else "live",
        "market_slug": current_market_slug,
        "market_question": current_market_question,
        "market_bucket_minutes": MARKET_BUCKET_MINUTES,
        "market_start_utc": (
            current_market_start_dt.isoformat() if current_market_start_dt else None
        ),
        "market_end_utc": (
            current_market_end_dt.isoformat() if current_market_end_dt else None
        ),
        "remaining_seconds": get_bucket_remaining_seconds(),
        "bn_price": optional_float(bn_last_price),
        "pm_open_price": optional_float(pm_bucket_open_price),
        "bn_open_price": optional_float(bn_bucket_open_price),
        "open_anchor_mode": fair.get("open_anchor_mode") if fair else OPEN_ANCHOR_MODE,
        "open_anchor_weight": (
            optional_float(fair.get("open_anchor_weight") if fair else OPEN_ANCHOR_WEIGHT)
        ),
        "open_anchor_price": optional_float(fair.get("open_anchor_price") if fair else None),
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "yes_mid": yes_mid,
        "yes_spread": optional_diff(yes_ask, yes_bid),
        "down_bid": down_bid,
        "down_ask": down_ask,
        "down_mid": down_mid,
        "down_spread": optional_diff(down_ask, down_bid),
        "pm_implied_up": yes_mid,
        "pm_implied_down": down_mid,
        "pm_complement_down_from_yes": (
            1.0 - yes_mid if yes_mid is not None else None
        ),
        "pm_mid_sum": (
            yes_mid + down_mid if yes_mid is not None and down_mid is not None else None
        ),
        "fair_yes": fair_yes,
        "fair_no": fair_no,
        "edge_yes_bid": optional_diff(fair_yes, yes_bid),
        "edge_yes_ask": optional_diff(fair_yes, yes_ask),
        "edge_down_bid": optional_diff(fair_no, down_bid),
        "edge_down_ask": optional_diff(fair_no, down_ask),
        "sigma_short": optional_float(fair.get("sigma_short") if fair else None),
        "sigma_long": optional_float(fair.get("sigma_long") if fair else None),
        "sigma_eff": optional_float(fair.get("sigma_eff") if fair else None),
        "tau_seconds": optional_float(fair.get("tau_seconds") if fair else None),
        "z": optional_float(fair.get("z") if fair else None),
        "quote_complete": all(
            value is not None for value in [yes_bid, yes_ask, down_bid, down_ask]
        ),
        "config": {
            "edge_prob_threshold": EDGE_PROB_THRESHOLD,
            "edge_reference_price": EDGE_REFERENCE_PRICE,
            "max_spread": MAX_SPREAD,
            "min_entry_ask_price": MIN_ENTRY_ASK_PRICE,
            "min_edge_after_fill": MIN_EDGE_AFTER_FILL,
            "exec_slippage_ticks": EXEC_SLIPPAGE_TICKS,
            "exec_price_mode": EXEC_PRICE_MODE,
            "taker_order_type": TAKER_ORDER_TYPE,
            "tau_floor_seconds": TAU_FLOOR_SECONDS,
            "sigma_min": SIGMA_MIN,
            "z_cap": Z_CAP,
            "vol_window_short_seconds": VOL_WINDOW_SHORT_SECONDS,
            "vol_window_long_seconds": VOL_WINDOW_LONG_SECONDS,
            "open_anchor_mode": OPEN_ANCHOR_MODE,
            "open_anchor_weight": OPEN_ANCHOR_WEIGHT,
            "market_max_total_cost": MARKET_MAX_TOTAL_COST,
            "market_max_side_cost": MARKET_MAX_SIDE_COST,
            "side_extension_enabled": SIDE_EXTENSION_ENABLED,
        },
        "ledger": {
            "yes_cost": optional_float(ledger.get("yes_cost") if ledger else None),
            "down_cost": optional_float(ledger.get("down_cost") if ledger else None),
            "total_cost": optional_float(ledger.get("total_cost") if ledger else None),
            "yes_orders": ledger.get("yes_orders") if ledger else None,
            "down_orders": ledger.get("down_orders") if ledger else None,
        },
    }


def tick_snapshot_file_path() -> Path:
    return TICK_SNAPSHOT_DIR / f"{utcnow().date().isoformat()}.jsonl"


def should_record_tick_snapshot(source_event: str) -> bool:
    if not TICK_SNAPSHOT_ENABLED:
        return False
    if source_event == "interval_heartbeat":
        return TICK_SNAPSHOT_MODE in {"interval", "both"}
    return TICK_SNAPSHOT_MODE in {"event", "both"}


def warn_tick_snapshot_error(error: Exception) -> None:
    global last_tick_snapshot_error_time

    now = time.time()
    if now - last_tick_snapshot_error_time < 10:
        return
    last_tick_snapshot_error_time = now
    print(f"⚠️ tick snapshot 寫入失敗，略過本筆: {error}")


def record_tick_snapshot(source_event: str, *, force: bool = False) -> None:
    global last_tick_snapshot_event_ms

    if not should_record_tick_snapshot(source_event):
        return

    now_ms = time.time() * 1000.0
    is_interval = source_event == "interval_heartbeat"
    if (
        not force
        and not is_interval
        and now_ms - last_tick_snapshot_event_ms < TICK_SNAPSHOT_MIN_INTERVAL_MS
    ):
        return

    try:
        snapshot = build_tick_snapshot(source_event)
        if snapshot is None:
            return
        TICK_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        with tick_snapshot_file_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n")
        if not is_interval:
            last_tick_snapshot_event_ms = now_ms
    except Exception as error:
        warn_tick_snapshot_error(error)


def migrate_market_settlements_csv_if_needed() -> None:
    if not MARKET_SETTLEMENTS_CSV_PATH.exists():
        return

    with MARKET_SETTLEMENTS_CSV_PATH.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        current_fieldnames = reader.fieldnames or []
        if current_fieldnames == MARKET_SETTLEMENTS_FIELDNAMES:
            return
        rows = list(reader)

    backup_path = (
        LEDGER_DIR
        / f"{MARKET_SETTLEMENTS_CSV_PATH.stem}.legacy_backup{MARKET_SETTLEMENTS_CSV_PATH.suffix}"
    )
    if not backup_path.exists():
        backup_path.write_text(
            MARKET_SETTLEMENTS_CSV_PATH.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    migrated_rows = []
    for row in rows:
        open_price = row.get("open_price") or row.get("bn_open_price") or ""
        resolution_price = (
            row.get("resolution_price") or row.get("bn_resolution_price_proxy") or ""
        )
        resolution_source = row.get("resolution_price_source")
        if not resolution_source:
            resolution_source = (
                "next_pm_open" if row.get("open_price_source") else "bn_proxy_legacy"
            )
        migrated_rows.append(
            {
                "settled_at": row.get("settled_at", ""),
                "market_slug": row.get("market_slug", ""),
                "market_question": row.get("market_question", ""),
                "market_start_utc": row.get("market_start_utc", ""),
                "market_end_utc": row.get("market_end_utc", ""),
                "open_price": open_price,
                "open_price_source": row.get("open_price_source", "legacy_unknown"),
                "resolution_price": resolution_price,
                "resolution_price_source": resolution_source,
                "bn_resolution_price_fallback": (
                    row.get("bn_resolution_price_fallback")
                    or row.get("bn_resolution_price_proxy")
                    or ""
                ),
                "resolved_side": row.get("resolved_side", ""),
                "yes_fee_rate_bps": row.get("yes_fee_rate_bps", ""),
                "down_fee_rate_bps": row.get("down_fee_rate_bps", ""),
                "fees_enabled": row.get("fees_enabled", ""),
                "settlement_reason": row.get("settlement_reason", ""),
                "yes_orders": row.get("yes_orders", ""),
                "down_orders": row.get("down_orders", ""),
                "yes_shares": row.get("yes_shares", ""),
                "down_shares": row.get("down_shares", ""),
                "yes_cost": row.get("yes_cost", ""),
                "down_cost": row.get("down_cost", ""),
                "total_cost": row.get("total_cost", ""),
                "estimated_fee_total": row.get("estimated_fee_total", ""),
                "gross_payout_estimate": row.get("gross_payout_estimate", ""),
                "net_pnl_estimate": row.get("net_pnl_estimate", ""),
                "pnl_if_up_estimate": row.get("pnl_if_up_estimate", ""),
                "pnl_if_down_estimate": row.get("pnl_if_down_estimate", ""),
                "mode_observed": row.get("mode_observed", ""),
            }
        )

    with MARKET_SETTLEMENTS_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MARKET_SETTLEMENTS_FIELDNAMES)
        writer.writeheader()
        for row in migrated_rows:
            writer.writerow(row)


def build_ledger_defaults() -> Dict[str, Any]:
    return {
        "market_slug": current_market_slug,
        "market_question": current_market_question,
        "condition_id": condition_id,
        "market_start_utc": (
            current_market_start_dt.isoformat() if current_market_start_dt else ""
        ),
        "market_end_utc": (
            current_market_end_dt.isoformat() if current_market_end_dt else ""
        ),
        "pm_open_price": pm_bucket_open_price,
        "bn_open_price": bn_bucket_open_price,
        "effective_open_price": 0.0,
        "open_price_source": "missing",
        "mode_observed": "dry_run" if DRY_RUN else "live_estimated",
        "yes_fee_rate_bps": current_yes_fee_rate_bps,
        "down_fee_rate_bps": current_down_fee_rate_bps,
        "fees_enabled": current_fees_enabled,
        "fee_rules_source": current_fee_rules_source,
        "created_at": now_iso(),
        "settled": False,
        "resolved_side": None,
        "resolution_price": None,
        "resolution_price_source": None,
        "bn_resolution_price_fallback": None,
        "settlement_reason": None,
        "settled_at": None,
        "yes_orders": 0,
        "down_orders": 0,
        "yes_shares": 0.0,
        "down_shares": 0.0,
        "yes_cost": 0.0,
        "down_cost": 0.0,
        "total_cost": 0.0,
        "yes_extension_start_at": None,
        "down_extension_start_at": None,
        "yes_last_extension_order_at": None,
        "down_last_extension_order_at": None,
        "estimated_fee_total": 0.0,
        "gross_payout_estimate": 0.0,
        "net_pnl_estimate": 0.0,
        "pnl_if_up_estimate": 0.0,
        "pnl_if_down_estimate": 0.0,
        "tail_reversal_anchor": None,
        "tail_reversal_confirm": None,
        "tail_reversal_final": None,
        "tail_reversal_anchor_abs_seconds": None,
        "tail_reversal_confirm_abs_seconds": None,
        "tail_reversal_final_remaining_seconds": None,
        "tail_reversal_hit": False,
        "tail_reversal_hit_details": None,
        "orders": [],
    }


def normalize_loaded_ledger(
    slug: str, raw_ledger: Dict[str, Any]
) -> Dict[str, Any]:
    defaults = build_ledger_defaults()
    defaults["market_slug"] = slug
    defaults["market_question"] = raw_ledger.get("market_question", "")
    defaults["condition_id"] = raw_ledger.get("condition_id")
    defaults["market_start_utc"] = raw_ledger.get("market_start_utc", "")
    defaults["market_end_utc"] = raw_ledger.get("market_end_utc", "")
    defaults["pm_open_price"] = raw_ledger.get("pm_open_price")
    defaults["bn_open_price"] = raw_ledger.get("bn_open_price")
    defaults["effective_open_price"] = safe_float(
        raw_ledger.get("effective_open_price"), 0.0
    )
    defaults["open_price_source"] = raw_ledger.get("open_price_source", "missing")
    defaults["mode_observed"] = raw_ledger.get("mode_observed", "dry_run")
    defaults["yes_fee_rate_bps"] = int(safe_float(raw_ledger.get("yes_fee_rate_bps"), 0))
    defaults["down_fee_rate_bps"] = int(
        safe_float(raw_ledger.get("down_fee_rate_bps"), 0)
    )
    defaults["fees_enabled"] = bool(raw_ledger.get("fees_enabled", False))
    defaults["fee_rules_source"] = raw_ledger.get("fee_rules_source", "unknown")
    defaults["created_at"] = raw_ledger.get("created_at", "")
    defaults["settled"] = bool(raw_ledger.get("settled", False))
    defaults["resolved_side"] = raw_ledger.get("resolved_side")
    defaults["resolution_price"] = raw_ledger.get("resolution_price")
    defaults["resolution_price_source"] = raw_ledger.get("resolution_price_source")
    defaults["bn_resolution_price_fallback"] = raw_ledger.get(
        "bn_resolution_price_fallback",
        raw_ledger.get("bn_resolution_price_proxy"),
    )
    defaults["settlement_reason"] = raw_ledger.get("settlement_reason")
    defaults["settled_at"] = raw_ledger.get("settled_at")
    defaults["yes_orders"] = int(safe_float(raw_ledger.get("yes_orders"), 0))
    defaults["down_orders"] = int(safe_float(raw_ledger.get("down_orders"), 0))
    defaults["yes_shares"] = safe_float(raw_ledger.get("yes_shares"), 0.0)
    defaults["down_shares"] = safe_float(raw_ledger.get("down_shares"), 0.0)
    defaults["yes_cost"] = safe_float(raw_ledger.get("yes_cost"), 0.0)
    defaults["down_cost"] = safe_float(raw_ledger.get("down_cost"), 0.0)
    defaults["total_cost"] = safe_float(raw_ledger.get("total_cost"), 0.0)
    defaults["yes_extension_start_at"] = raw_ledger.get("yes_extension_start_at")
    defaults["down_extension_start_at"] = raw_ledger.get("down_extension_start_at")
    defaults["yes_last_extension_order_at"] = raw_ledger.get(
        "yes_last_extension_order_at"
    )
    defaults["down_last_extension_order_at"] = raw_ledger.get(
        "down_last_extension_order_at"
    )
    defaults["estimated_fee_total"] = safe_float(
        raw_ledger.get("estimated_fee_total"), 0.0
    )
    defaults["gross_payout_estimate"] = safe_float(
        raw_ledger.get("gross_payout_estimate"), 0.0
    )
    defaults["net_pnl_estimate"] = safe_float(raw_ledger.get("net_pnl_estimate"), 0.0)
    defaults["pnl_if_up_estimate"] = safe_float(
        raw_ledger.get("pnl_if_up_estimate"), 0.0
    )
    defaults["pnl_if_down_estimate"] = safe_float(
        raw_ledger.get("pnl_if_down_estimate"), 0.0
    )
    defaults["tail_reversal_anchor"] = (
        raw_ledger.get("tail_reversal_anchor")
        if isinstance(raw_ledger.get("tail_reversal_anchor"), dict)
        else None
    )
    defaults["tail_reversal_confirm"] = (
        raw_ledger.get("tail_reversal_confirm")
        if isinstance(raw_ledger.get("tail_reversal_confirm"), dict)
        else None
    )
    defaults["tail_reversal_final"] = (
        raw_ledger.get("tail_reversal_final")
        if isinstance(raw_ledger.get("tail_reversal_final"), dict)
        else None
    )
    defaults["tail_reversal_anchor_abs_seconds"] = optional_float(
        raw_ledger.get("tail_reversal_anchor_abs_seconds")
    )
    defaults["tail_reversal_confirm_abs_seconds"] = optional_float(
        raw_ledger.get("tail_reversal_confirm_abs_seconds")
    )
    defaults["tail_reversal_final_remaining_seconds"] = optional_float(
        raw_ledger.get("tail_reversal_final_remaining_seconds")
    )
    defaults["tail_reversal_hit"] = bool(raw_ledger.get("tail_reversal_hit", False))
    defaults["tail_reversal_hit_details"] = (
        raw_ledger.get("tail_reversal_hit_details")
        if isinstance(raw_ledger.get("tail_reversal_hit_details"), dict)
        else None
    )
    defaults["orders"] = parse_jsonish_list(raw_ledger.get("orders"))
    return defaults


def load_market_state_json() -> None:
    global market_ledgers, pending_settlement
    global tail_reversal_recent_hit_times, tail_reversal_cooldown_until

    if not MARKET_STATE_JSON_PATH.exists():
        return

    try:
        raw_state = json.loads(MARKET_STATE_JSON_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ 載入 market_state.json 失敗，略過恢復: {e}")
        return

    if not isinstance(raw_state, dict):
        return

    raw_ledgers = raw_state.get("market_ledgers")
    if raw_ledgers is None:
        raw_ledgers = raw_state

    if isinstance(raw_ledgers, dict):
        loaded_ledgers: Dict[str, Dict[str, Any]] = {}
        for slug, ledger in raw_ledgers.items():
            if not isinstance(ledger, dict):
                continue
            loaded_ledgers[slug] = normalize_loaded_ledger(str(slug), ledger)
        market_ledgers = loaded_ledgers

    raw_pending = raw_state.get("pending_settlement")
    if isinstance(raw_pending, dict) and raw_pending.get("market_slug"):
        pending_settlement = {
            "market_slug": str(raw_pending.get("market_slug")),
            "market_end_utc": str(raw_pending.get("market_end_utc", "")),
            "expected_resolution_market_start_utc": str(
                raw_pending.get("expected_resolution_market_start_utc", "")
            ),
            "pending_reason": str(raw_pending.get("pending_reason", "restored")),
            "marked_at": str(raw_pending.get("marked_at", "")),
        }
    else:
        pending_settlement = None

    tail_reversal_recent_hit_times = deque()
    tail_reversal_cooldown_until = None
    raw_tail_state = raw_state.get("tail_reversal_state")
    if isinstance(raw_tail_state, dict):
        raw_recent_hits = raw_tail_state.get("recent_hit_times")
        if isinstance(raw_recent_hits, list):
            for raw_hit in raw_recent_hits:
                hit_dt = parse_dt(raw_hit)
                if hit_dt is not None:
                    tail_reversal_recent_hit_times.append(hit_dt)
        tail_reversal_cooldown_until = parse_dt(raw_tail_state.get("cooldown_until"))

    if pending_settlement is None:
        unresolved_ledgers = []
        for ledger in market_ledgers.values():
            if ledger.get("settled"):
                continue
            market_end_dt = parse_dt(ledger.get("market_end_utc"))
            if market_end_dt is None or market_end_dt > utcnow():
                continue
            unresolved_ledgers.append((market_end_dt, ledger))

        if unresolved_ledgers:
            unresolved_ledgers.sort(key=lambda item: item[0])
            _, latest_ledger = unresolved_ledgers[-1]
            pending_settlement = {
                "market_slug": latest_ledger["market_slug"],
                "market_end_utc": latest_ledger["market_end_utc"],
                "expected_resolution_market_start_utc": latest_ledger["market_end_utc"],
                "pending_reason": "restored_legacy_unsettled_market",
                "marked_at": now_iso(),
            }
            print(
                f"ℹ️ 從舊 state 恢復待結算市場: {latest_ledger['market_slug']}"
            )

    if not tail_reversal_feature_enabled():
        tail_reversal_recent_hit_times = deque()
        tail_reversal_cooldown_until = None
    else:
        prune_tail_reversal_recent_hits()


def round_fee_usdc(value: float) -> float:
    """
    官方規則：
    - fee 以 USDC 計算
    - 四捨五入到 5 位小數
    - 小於 0.00001 的費用視為 0
    """
    rounded = round(max(value, 0.0), 5)
    return rounded if rounded >= 0.00001 else 0.0


def fetch_fee_rate_bps(token_id: Optional[str]) -> Optional[int]:
    if not token_id:
        return None

    url = f"{CLOB_HOST.rstrip('/')}/fee-rate"
    params = {"token_id": token_id}

    try:
        resp = HTTP.get(url, params=params, timeout=FEE_FETCH_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
        return int(data.get("base_fee", 0))
    except Exception:
        return None


def refresh_current_fee_rates() -> None:
    """
    依官方建議動態抓 fee rate，不硬編碼市場類別。
    fee-enabled 市場通常會回非 0 的 base_fee；fee-free 市場回 0。
    """
    global current_yes_fee_rate_bps, current_down_fee_rate_bps
    global current_fee_rules_source, current_fees_enabled, current_fee_taker_only

    fee_details = extract_clob_market_fee_details(fetch_clob_market_info(condition_id))
    if fee_details is not None:
        fee_rate_bps = int(fee_details["fee_rate_bps"])
        current_yes_fee_rate_bps = fee_rate_bps
        current_down_fee_rate_bps = fee_rate_bps
        current_fee_taker_only = bool(fee_details["taker_only"])
        current_fee_rules_source = "clob_market_info"
        current_fees_enabled = fee_rate_bps > 0
        return

    yes_bps = fetch_fee_rate_bps(pm_yes_token)
    down_bps = fetch_fee_rate_bps(pm_no_token)

    if yes_bps is None or down_bps is None:
        if FEE_FETCH_RETRY_ON_SWITCH:
            current_fee_rules_source = "fee_rate_endpoint_unavailable"
        else:
            current_fee_rules_source = "fee_rate_endpoint_skipped"
        current_yes_fee_rate_bps = 0 if yes_bps is None else yes_bps
        current_down_fee_rate_bps = 0 if down_bps is None else down_bps
        current_fee_taker_only = True
    else:
        current_yes_fee_rate_bps = yes_bps
        current_down_fee_rate_bps = down_bps
        current_fee_rules_source = "fee_rate_endpoint"
        current_fee_taker_only = True

    current_fees_enabled = (current_yes_fee_rate_bps > 0) or (
        current_down_fee_rate_bps > 0
    )


def estimate_taker_buy_execution(
    *,
    amount_usd: float,
    price: float,
    fee_rate_bps: int,
) -> Dict[str, float]:
    """
    依官方 fee 公式估算 BUY taker 成交：
        fee_usdc = C × feeRate × p × (1 - p)
    其中：
        C = gross shares = amount_usd / price
        feeRate = fee_rate_bps / 10000

    官方說明：
    - fee 先以 USDC 計算
    - BUY 訂單以 shares 扣除
    - fee 四捨五入到 5 位 USDC
    """
    price = safe_float(price, 0.0)
    amount_usd = safe_float(amount_usd, 0.0)
    fee_rate = max(safe_float(fee_rate_bps, 0.0) / 10000.0, 0.0)

    if price <= 0 or amount_usd <= 0:
        return {
            "gross_shares": 0.0,
            "fee_usdc": 0.0,
            "fee_shares": 0.0,
            "net_shares": 0.0,
        }

    gross_shares = amount_usd / price
    fee_usdc_raw = gross_shares * fee_rate * price * (1.0 - price)
    fee_usdc = round_fee_usdc(fee_usdc_raw)
    fee_shares = fee_usdc / price if fee_usdc > 0 else 0.0
    net_shares = max(gross_shares - fee_shares, 0.0)

    return {
        "gross_shares": gross_shares,
        "fee_usdc": fee_usdc,
        "fee_shares": fee_shares,
        "net_shares": net_shares,
    }


def estimate_taker_buy_execution_from_fill(
    *,
    amount_usd: float,
    gross_shares: float,
    price: float,
    fee_rate_bps: int,
) -> Dict[str, float]:
    price = safe_float(price, 0.0)
    amount_usd = safe_float(amount_usd, 0.0)
    gross_shares = safe_float(gross_shares, 0.0)
    fee_rate = max(safe_float(fee_rate_bps, 0.0) / 10000.0, 0.0)

    if price <= 0 or amount_usd <= 0 or gross_shares <= 0:
        return {
            "gross_shares": 0.0,
            "fee_usdc": 0.0,
            "fee_shares": 0.0,
            "net_shares": 0.0,
        }

    fee_usdc_raw = gross_shares * fee_rate * price * (1.0 - price)
    fee_usdc = round_fee_usdc(fee_usdc_raw)
    fee_shares = fee_usdc / price if fee_usdc > 0 else 0.0
    net_shares = max(gross_shares - fee_shares, 0.0)

    return {
        "gross_shares": gross_shares,
        "fee_usdc": fee_usdc,
        "fee_shares": fee_shares,
        "net_shares": net_shares,
    }


def parse_buy_fill_from_order_response(
    resp: Optional[Dict[str, Any]],
    *,
    requested_amount_usd: float,
    fallback_price: float,
) -> Dict[str, Any]:
    requested_amount = safe_float(requested_amount_usd, 0.0)
    fallback_price = safe_float(fallback_price, 0.0)

    if not isinstance(resp, dict):
        return {
            "amount_usd": 0.0,
            "gross_shares": 0.0,
            "avg_price": 0.0,
            "fill_ratio": 0.0,
            "has_explicit_fill": False,
        }

    making_amount = optional_float(
        pick_first_value(
            resp,
            "makingAmount",
            "making_amount",
            "makerAmount",
            "maker_amount",
            "filledValue",
            "filled_value",
            "matchedValue",
            "matched_value",
        )
    )
    taking_amount = optional_float(
        pick_first_value(
            resp,
            "takingAmount",
            "taking_amount",
            "takerAmount",
            "taker_amount",
            "filledAmount",
            "filled_amount",
            "filledSize",
            "filled_size",
            "sizeMatched",
            "size_matched",
            "matchedSize",
            "matched_size",
        )
    )
    explicit_price = optional_float(
        pick_first_value(
            resp,
            "fillPrice",
            "fill_price",
            "avgPrice",
            "avg_price",
            "price",
            "matchedPrice",
            "matched_price",
        )
    )
    avg_price = explicit_price if explicit_price and explicit_price > 0 else 0.0

    amount_usd = making_amount if making_amount and making_amount > 0 else 0.0
    gross_shares = taking_amount if taking_amount and taking_amount > 0 else 0.0

    if amount_usd > 0 and gross_shares > 0:
        derived_price = amount_usd / gross_shares
        if 0 < derived_price <= 1.0:
            avg_price = derived_price
        elif 0 < gross_shares / amount_usd <= 1.0:
            # Defensive fallback for APIs that report maker/taker from the opposite side.
            amount_usd, gross_shares = gross_shares, amount_usd
            avg_price = amount_usd / gross_shares

    if avg_price <= 0:
        avg_price = fallback_price

    if amount_usd <= 0 and gross_shares > 0 and avg_price > 0:
        amount_usd = gross_shares * avg_price
    if gross_shares <= 0 and amount_usd > 0 and avg_price > 0:
        gross_shares = amount_usd / avg_price

    has_explicit_fill = amount_usd > 0 and gross_shares > 0
    if not has_explicit_fill and TAKER_ORDER_TYPE == "FOK":
        # Older FOK responses may only indicate success. For FAK we require explicit fill size.
        status = str(
            pick_first_value(resp, "status", "state", "orderStatus", "order_status")
            or ""
        ).strip().lower()
        success = resp.get("success")
        if (
            (status in {"filled", "matched", "mined", "confirmed", "success"})
            or success is True
        ) and requested_amount > 0 and fallback_price > 0:
            amount_usd = requested_amount
            gross_shares = requested_amount / fallback_price
            avg_price = fallback_price

    if requested_amount > 0 and amount_usd > requested_amount * 1.001:
        amount_usd = requested_amount
        if avg_price > 0:
            gross_shares = amount_usd / avg_price

    return {
        "amount_usd": amount_usd if amount_usd > 0 else 0.0,
        "gross_shares": gross_shares if gross_shares > 0 else 0.0,
        "avg_price": avg_price if avg_price > 0 else 0.0,
        "fill_ratio": (
            min(amount_usd / requested_amount, 1.0)
            if requested_amount > 0 and amount_usd > 0
            else 0.0
        ),
        "has_explicit_fill": has_explicit_fill,
    }


def reset_runtime_state():
    """
    換市場時重置：
    - PM quote
    - signal cooldown
    - order cooldown
    - PM 開盤價 / fee 狀態

    注意：
    - BN 秒級價格緩衝不重置，讓外部價格波動模型可跨市場延續
    - sigma_long 暖機只在系統啟動初期做一次
    """
    global pm_yes_best_bid, pm_yes_best_ask, pm_no_best_bid, pm_no_best_ask
    global signal_state, last_order_time
    global entry_gate_rejection_state
    global pm_bucket_open_price, bn_bucket_open_price
    global pm_open_price_retry_task
    global current_yes_fee_rate_bps, current_down_fee_rate_bps
    global current_fee_rules_source, current_fees_enabled
    global current_fee_taker_only, current_clob_market_info

    pm_yes_best_bid = None
    pm_yes_best_ask = None
    pm_no_best_bid = None
    pm_no_best_ask = None

    signal_state = {
        "UP": {"last_emit_time": 0.0},
        "DOWN": {"last_emit_time": 0.0},
    }
    entry_gate_rejection_state = {}

    last_order_time = 0.0

    pm_bucket_open_price = None
    bn_bucket_open_price = None

    if pm_open_price_retry_task is not None and not pm_open_price_retry_task.done():
        pm_open_price_retry_task.cancel()
    pm_open_price_retry_task = None

    current_yes_fee_rate_bps = 0
    current_down_fee_rate_bps = 0
    current_fee_rules_source = "reset"
    current_fees_enabled = False
    current_fee_taker_only = True
    current_clob_market_info = None


def can_emit_signal(side: str) -> bool:
    """
    side-based signal cooldown：
    UP / DOWN 各自獨立節流。
    """
    global signal_state

    now = time.time()
    last_emit = signal_state.get(side, {}).get("last_emit_time", 0.0)

    if now - last_emit < SIGNAL_COOLDOWN_SECONDS:
        return False

    signal_state[side]["last_emit_time"] = now
    return True


def is_market_live_now(
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    now: Optional[datetime] = None,
) -> bool:
    if not start_dt or not end_dt:
        return False
    now = now or utcnow()
    return start_dt <= now < end_dt


def get_bucket_remaining_seconds() -> Optional[float]:
    if current_market_end_dt is None:
        return None
    remaining = (current_market_end_dt - utcnow()).total_seconds()
    return max(remaining, 0.0)


def sample_bn_price_once_per_second(price: float) -> None:
    """
    只保留每秒一筆價格。
    """
    global bn_last_sampled_second

    sec = int(time.time())
    if bn_last_sampled_second != sec:
        bn_second_prices.append((sec, float(price)))
        bn_last_sampled_second = sec


def get_recent_bn_prices(
    window_seconds: int = VOL_WINDOW_SHORT_SECONDS,
) -> List[float]:
    return [price for _, price in get_recent_bn_samples(window_seconds)]


def get_recent_bn_samples(
    window_seconds: int = VOL_WINDOW_SHORT_SECONDS,
) -> List[Tuple[int, float]]:
    now_sec = int(time.time())
    cutoff = now_sec - window_seconds
    return [(sec, price) for sec, price in bn_second_prices if sec >= cutoff]


def compute_log_return_sigma(prices: List[float]) -> Optional[float]:
    if len(prices) < 3:
        return None

    rets = []
    for i in range(1, len(prices)):
        p0 = prices[i - 1]
        p1 = prices[i]
        if p0 > 0 and p1 > 0:
            rets.append(math.log(p1 / p0))

    if len(rets) < 2:
        return None

    return statistics.pstdev(rets)


def get_sigma_long_warmup_progress() -> Tuple[bool, int]:
    global sigma_long_warmup_complete

    if sigma_long_warmup_complete:
        return True, VOL_WINDOW_LONG_SECONDS

    long_samples = get_recent_bn_samples(VOL_WINDOW_LONG_SECONDS)
    if len(long_samples) < 3:
        return False, 0

    covered_seconds = max(long_samples[-1][0] - long_samples[0][0], 0)
    if covered_seconds >= (VOL_WINDOW_LONG_SECONDS - 1):
        sigma_long_warmup_complete = True
        return True, VOL_WINDOW_LONG_SECONDS

    return False, covered_seconds


def maybe_log_sigma_long_warmup(covered_seconds: int) -> None:
    global bn_last_warmup_log_time

    now = time.time()
    if now - bn_last_warmup_log_time < 15:
        return

    bn_last_warmup_log_time = now
    print(
        f"⏳ sigma_long 暖機中... {covered_seconds}/{VOL_WINDOW_LONG_SECONDS}s | "
        "暖機完成前不交易"
    )


def compute_dual_scale_sigma() -> Optional[Dict[str, Any]]:
    is_warmed_up, covered_seconds = get_sigma_long_warmup_progress()
    if not is_warmed_up:
        maybe_log_sigma_long_warmup(covered_seconds)
        return None

    short_prices = get_recent_bn_prices(VOL_WINDOW_SHORT_SECONDS)
    sigma_short = compute_log_return_sigma(short_prices)
    if sigma_short is None:
        return None

    long_prices = get_recent_bn_prices(VOL_WINDOW_LONG_SECONDS)
    sigma_long = compute_log_return_sigma(long_prices)
    if sigma_long is None:
        return None

    short_weight = SIGMA_SHORT_WEIGHT / SIGMA_WEIGHT_SUM
    long_weight = SIGMA_LONG_WEIGHT / SIGMA_WEIGHT_SUM
    sigma_eff = math.sqrt(
        (short_weight * (sigma_short**2))
        + (long_weight * (sigma_long**2))
        + (SIGMA_MIN**2)
    )

    return {
        "sigma_short": sigma_short,
        "sigma_long": sigma_long,
        "sigma_eff": sigma_eff,
        "n_prices_short": len(short_prices),
        "n_prices_long": len(long_prices),
    }


# ====================== 市場 slug 邏輯 ======================
def floor_to_market_bucket_et(dt_utc: Optional[datetime] = None) -> datetime:
    dt_utc = dt_utc or utcnow()
    dt_et = dt_utc.astimezone(ET_TZ)
    floored_minute = (dt_et.minute // MARKET_BUCKET_MINUTES) * MARKET_BUCKET_MINUTES
    return dt_et.replace(minute=floored_minute, second=0, microsecond=0)


def market_slug_from_bucket_start(bucket_start_et: datetime) -> str:
    ts = int(bucket_start_et.timestamp())
    return f"{MARKET_SLUG_PREFIX}-{ts}"


def parse_bucket_times_from_slug(
    slug: str,
) -> tuple[Optional[datetime], Optional[datetime]]:
    try:
        ts = int(slug.rsplit("-", 1)[1])
        start_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        end_dt = start_dt + timedelta(minutes=MARKET_BUCKET_MINUTES)
        return start_dt, end_dt
    except Exception:
        return None, None


def candidate_market_slugs(now_utc: Optional[datetime] = None) -> List[str]:
    now_utc = now_utc or utcnow()
    current_bucket_et = floor_to_market_bucket_et(now_utc)

    buckets = [
        current_bucket_et,
        current_bucket_et - timedelta(minutes=MARKET_BUCKET_MINUTES),
        current_bucket_et + timedelta(minutes=MARKET_BUCKET_MINUTES),
    ]

    result: List[str] = []
    seen = set()
    for bucket in buckets:
        slug = market_slug_from_bucket_start(bucket)
        if slug not in seen:
            seen.add(slug)
            result.append(slug)
    return result


# ====================== 市場偵測 ======================
def fetch_market_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    url = f"https://gamma-api.polymarket.com/markets/slug/{slug}"
    resp = HTTP.get(url, timeout=10)

    if resp.status_code == 404:
        return None

    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, list):
        if not data:
            return None
        return data[0]
    if isinstance(data, dict):
        return data
    return None


def normalize_market_from_slug_response(
    market_obj: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    slug = str(market_obj.get("slug", "") or "")
    question = str(market_obj.get("question", "") or "")

    if not slug.startswith(f"{MARKET_SLUG_PREFIX}-"):
        return None

    start_dt, end_dt = parse_bucket_times_from_slug(slug)
    if not start_dt or not end_dt:
        return None

    outcomes = [str(x) for x in parse_jsonish_list(market_obj.get("outcomes"))]
    token_ids = [str(x) for x in parse_jsonish_list(market_obj.get("clobTokenIds"))]

    if len(outcomes) != 2 or len(token_ids) != 2:
        return None

    outcome_to_token = {
        str(outcome).strip().lower(): token_id
        for outcome, token_id in zip(outcomes, token_ids)
    }

    up_token = outcome_to_token.get("up")
    down_token = outcome_to_token.get("down")

    if not up_token and not down_token:
        if "yes" in outcome_to_token and "no" in outcome_to_token:
            up_token = outcome_to_token["yes"]
            down_token = outcome_to_token["no"]

    if not up_token or not down_token:
        return None

    return {
        "market_id": str(market_obj.get("id")),
        "conditionId": market_obj.get("conditionId"),
        "slug": slug,
        "question": question,
        "startDate": market_obj.get("startDate"),
        "endDate": market_obj.get("endDate"),
        "start_dt": start_dt,
        "end_dt": end_dt,
        "up_token_id": up_token,
        "down_token_id": down_token,
        "outcomes": outcomes,
        "clobTokenIds": token_ids,
        "acceptingOrders": bool(market_obj.get("acceptingOrders")),
        "active": bool(market_obj.get("active")),
        "closed": bool(market_obj.get("closed")),
        "archived": bool(market_obj.get("archived", False)),
        "volume": safe_float(market_obj.get("volumeNum") or market_obj.get("volume")),
        "liquidity": safe_float(
            market_obj.get("liquidityNum") or market_obj.get("liquidity")
        ),
        "tick_size": market_obj.get("orderPriceMinTickSize"),
        "neg_risk": bool(market_obj.get("negRisk", False)),
    }


def get_current_live_market() -> Optional[Dict[str, Any]]:
    now = utcnow()
    slugs = candidate_market_slugs(now)

    for slug in slugs:
        try:
            market_obj = fetch_market_by_slug(slug)
            if not market_obj:
                print(f"ℹ️ slug 不存在或無資料: {slug}")
                continue

            normalized = normalize_market_from_slug_response(market_obj)
            if not normalized:
                print(f"⚠️ slug 資料格式不符預期: {slug}")
                continue

            if not normalized["active"]:
                print(f"ℹ️ 市場非 active: {slug}")
                continue
            if normalized["closed"]:
                print(f"ℹ️ 市場已 closed: {slug}")
                continue
            if normalized["archived"]:
                print(f"ℹ️ 市場已 archived: {slug}")
                continue
            if not normalized["acceptingOrders"]:
                print(f"ℹ️ 市場暫不接單: {slug}")
                continue
            if not is_market_live_now(
                normalized["start_dt"], normalized["end_dt"], now=now
            ):
                print(
                    f"ℹ️ 市場不在 live 視窗內: {slug} | "
                    f"derived_window={normalized['start_dt']} -> {normalized['end_dt']}"
                )
                continue

            print(f"✅ 找到目前 live 的 {MARKET_LABEL} 市場: {normalized['question']}")
            print(f"   Slug : {normalized['slug']}")
            print(f"   Derived Start UTC: {normalized['start_dt']}")
            print(f"   Derived End UTC  : {normalized['end_dt']}")
            print(f"   API Start        : {normalized['startDate']}")
            print(f"   API End          : {normalized['endDate']}")
            print(
                f"   Volume: {normalized['volume']} | Liquidity: {normalized['liquidity']}"
            )
            print(f"   UP token  : {normalized['up_token_id'][:12]}...")
            print(f"   DOWN token: {normalized['down_token_id'][:12]}...")
            print(f"   ConditionId: {normalized['conditionId']}")
            return normalized

        except Exception as e:
            print(f"❌ 查詢 slug 失敗 {slug}: {e}")

    print(f"⚠️  目前沒有找到『正在 live 中』的 {MARKET_LABEL} 市場")
    return None

# ====================== Polymarket bucket open price ======================
def fetch_polymarket_bucket_open_price(
    bucket_start_dt: datetime, bucket_end_dt: datetime
) -> Optional[float]:
    url = "https://polymarket.com/api/crypto/crypto-price"
    params = {
        "symbol": "BTC",
        "eventStartTime": format_utc_iso_z(bucket_start_dt),
        "variant": POLYMARKET_CRYPTO_PRICE_VARIANT,
        "endDate": format_utc_iso_z(bucket_end_dt),
    }

    resp = HTTP.get(url, params=params, timeout=PM_OPEN_FETCH_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()

    open_price = safe_float(data.get("openPrice"), 0.0)
    return open_price if open_price > 0 else None


def initialize_pm_bucket_open_price() -> None:
    global pm_bucket_open_price

    pm_bucket_open_price = None

    if current_market_start_dt is None or current_market_end_dt is None:
        return

    try:
        pm_bucket_open_price = fetch_polymarket_bucket_open_price(
            current_market_start_dt, current_market_end_dt
        )
        if pm_bucket_open_price is not None:
            print(f"📌 PM bucket open price = {pm_bucket_open_price:,.2f}")
            attempt_finalize_pending_settlement_from_current_pm_open()
        else:
            print("⚠️ 無法取得 PM bucket open price，策略暫停交易並持續重試")
    except Exception as e:
        print(f"⚠️ 初始化 PM bucket open price 失敗: {e}")


async def retry_pm_bucket_open_price_until_ready(expected_market_slug: str) -> None:
    global pm_bucket_open_price, pm_open_price_retry_task

    try:
        while True:
            if expected_market_slug != current_market_slug:
                return

            if pm_bucket_open_price is not None and safe_float(pm_bucket_open_price) > 0:
                return

            if current_market_start_dt is None or current_market_end_dt is None:
                return

            try:
                open_price = await asyncio.to_thread(
                    fetch_polymarket_bucket_open_price,
                    current_market_start_dt,
                    current_market_end_dt,
                )
                if expected_market_slug != current_market_slug:
                    return
                if open_price is not None and open_price > 0:
                    pm_bucket_open_price = open_price
                    ensure_market_ledger()
                    persist_market_state_json()
                    print(
                        f"✅ PM bucket open price 就緒 = {pm_bucket_open_price:,.2f} | "
                        f"市場: {current_market_slug}"
                    )
                    attempt_finalize_pending_settlement_from_current_pm_open()
                    return

                print("⌛ 尚未取得 PM bucket open price，策略暫停交易，稍後重試...")
            except Exception as e:
                if expected_market_slug != current_market_slug:
                    return
                print(
                    f"⌛ 取得 PM bucket open price 失敗，策略暫停交易，"
                    f"{PM_OPEN_RETRY_SECONDS:.1f} 秒後重試: {e}"
                )

            await asyncio.sleep(PM_OPEN_RETRY_SECONDS)
    except asyncio.CancelledError:
        return
    finally:
        current_task = asyncio.current_task()
        if pm_open_price_retry_task is current_task:
            pm_open_price_retry_task = None


def start_pm_open_price_retry_task() -> None:
    global pm_open_price_retry_task

    if pm_bucket_open_price is not None and safe_float(pm_bucket_open_price) > 0:
        return

    if not current_market_slug:
        return

    if pm_open_price_retry_task is not None and not pm_open_price_retry_task.done():
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    pm_open_price_retry_task = loop.create_task(
        retry_pm_bucket_open_price_until_ready(current_market_slug)
    )


# ====================== Binance bucket open price ======================
def fetch_binance_bucket_open_price(bucket_start_dt: datetime) -> Optional[float]:
    start_ms = int(bucket_start_dt.timestamp() * 1000)
    end_ms = start_ms + 30_000

    url = "https://api.binance.com/api/v3/aggTrades"
    params = {
        "symbol": "BTCUSDT",
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": 1000,
    }

    resp = HTTP.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if not data:
        return None

    return float(data[0]["p"])


def initialize_bn_bucket_open_price() -> None:
    global bn_bucket_open_price

    bn_bucket_open_price = None

    if current_market_start_dt is None:
        return

    try:
        bn_bucket_open_price = fetch_binance_bucket_open_price(current_market_start_dt)
        if bn_bucket_open_price is not None:
            print(f"📌 BN bucket open price (fallback) = {bn_bucket_open_price:,.2f}")
        else:
            print("⚠️ 無法取得 BN bucket open price (fallback)")
    except Exception as e:
        print(f"⚠️ 初始化 BN bucket open price (fallback) 失敗: {e}")


def resolve_signal_anchor_open_price() -> Optional[Dict[str, float | str]]:
    pm_open = safe_float(pm_bucket_open_price, 0.0)
    bn_open = safe_float(bn_bucket_open_price, 0.0)

    if OPEN_ANCHOR_MODE == "pm":
        if pm_open <= 0:
            return None
        return {
            "open_anchor_mode": "pm",
            "open_anchor_weight": 1.0,
            "open_anchor_price": pm_open,
            "pm_open_price": pm_open,
            "bn_open_price": bn_open,
        }

    if OPEN_ANCHOR_MODE == "bn":
        if bn_open <= 0:
            return None
        return {
            "open_anchor_mode": "bn",
            "open_anchor_weight": 0.0,
            "open_anchor_price": bn_open,
            "pm_open_price": pm_open,
            "bn_open_price": bn_open,
        }

    if pm_open <= 0 or bn_open <= 0:
        return None

    open_anchor_price = (OPEN_ANCHOR_WEIGHT * pm_open) + (
        (1.0 - OPEN_ANCHOR_WEIGHT) * bn_open
    )
    if open_anchor_price <= 0:
        return None

    return {
        "open_anchor_mode": "mix",
        "open_anchor_weight": OPEN_ANCHOR_WEIGHT,
        "open_anchor_price": open_anchor_price,
        "pm_open_price": pm_open,
        "bn_open_price": bn_open,
    }


def compute_fair_yes_from_bn() -> Optional[Dict[str, Any]]:
    global bn_last_price

    if bn_last_price is None:
        return None

    anchor_open = resolve_signal_anchor_open_price()
    if anchor_open is None:
        return None

    sigma_metrics = compute_dual_scale_sigma()
    if sigma_metrics is None:
        return None

    tau_seconds = get_bucket_remaining_seconds()
    if tau_seconds is None:
        return None
    tau_seconds = max(tau_seconds, TAU_FLOOR_SECONDS)

    p_now = float(bn_last_price)
    p_open = float(anchor_open["open_anchor_price"])

    if p_now <= 0 or p_open <= 0:
        return None

    log_move = math.log(p_now / p_open)
    sigma_eff = sigma_metrics["sigma_eff"]
    denom = sigma_eff * math.sqrt(tau_seconds)

    if denom <= 0:
        return None

    z = log_move / denom
    z = max(min(z, Z_CAP), -Z_CAP)

    fair_yes = normal_cdf(z)
    fair_no = 1.0 - fair_yes

    return {
        "signal_model": SIGNAL_MODEL_NAME,
        "fair_yes": fair_yes,
        "fair_no": fair_no,
        "p_now": p_now,
        "p_open": p_open,
        "open_price_source": str(anchor_open["open_anchor_mode"]),
        "open_anchor_mode": str(anchor_open["open_anchor_mode"]),
        "open_anchor_weight": float(anchor_open["open_anchor_weight"]),
        "open_anchor_price": float(anchor_open["open_anchor_price"]),
        "pm_open_price": float(anchor_open["pm_open_price"]),
        "bn_open_price": float(anchor_open["bn_open_price"]),
        "sigma": sigma_eff,
        "sigma_short": sigma_metrics["sigma_short"],
        "sigma_long": sigma_metrics["sigma_long"],
        "sigma_eff": sigma_eff,
        "tau_seconds": tau_seconds,
        "z": z,
        "n_prices_short": sigma_metrics["n_prices_short"],
        "n_prices_long": sigma_metrics["n_prices_long"],
    }


# ====================== 內部帳本 ======================
def ensure_market_ledger() -> Optional[Dict[str, Any]]:
    global market_ledgers

    if not current_market_slug:
        return None

    if current_market_slug not in market_ledgers:
        market_ledgers[current_market_slug] = build_ledger_defaults()

    ledger = market_ledgers[current_market_slug]
    ledger["market_question"] = current_market_question
    ledger["condition_id"] = condition_id
    ledger["market_start_utc"] = (
        current_market_start_dt.isoformat() if current_market_start_dt else ""
    )
    ledger["market_end_utc"] = (
        current_market_end_dt.isoformat() if current_market_end_dt else ""
    )
    if pm_bucket_open_price is not None:
        ledger["pm_open_price"] = pm_bucket_open_price
    if bn_bucket_open_price is not None:
        ledger["bn_open_price"] = bn_bucket_open_price
    effective_open_price, open_price_source = resolve_effective_open_price(
        ledger.get("pm_open_price"), ledger.get("bn_open_price")
    )
    ledger["effective_open_price"] = effective_open_price
    ledger["open_price_source"] = open_price_source
    ledger["yes_fee_rate_bps"] = current_yes_fee_rate_bps
    ledger["down_fee_rate_bps"] = current_down_fee_rate_bps
    ledger["fees_enabled"] = current_fees_enabled
    ledger["fee_rules_source"] = current_fee_rules_source
    refresh_side_extension_state(ledger)

    return ledger


def tail_reversal_feature_enabled() -> bool:
    return (
        TAIL_REVERSAL_COOLDOWN_ENABLED
        and TAIL_REVERSAL_LOOKBACK_SECONDS > 0
        and TAIL_REVERSAL_TRIGGER_COUNT > 0
        and TAIL_REVERSAL_COOLDOWN_SECONDS > 0
    )


def prune_tail_reversal_recent_hits(
    reference_dt: Optional[datetime] = None,
) -> None:
    global tail_reversal_cooldown_until

    if not tail_reversal_feature_enabled():
        tail_reversal_recent_hit_times.clear()
        tail_reversal_cooldown_until = None
        return

    now_dt = reference_dt or utcnow()
    while tail_reversal_recent_hit_times:
        elapsed = (now_dt - tail_reversal_recent_hit_times[0]).total_seconds()
        if elapsed <= TAIL_REVERSAL_LOOKBACK_SECONDS:
            break
        tail_reversal_recent_hit_times.popleft()

    if (
        tail_reversal_cooldown_until is not None
        and now_dt >= tail_reversal_cooldown_until
    ):
        tail_reversal_cooldown_until = None


def get_tail_reversal_recent_hit_count(
    reference_dt: Optional[datetime] = None,
) -> int:
    prune_tail_reversal_recent_hits(reference_dt)
    return len(tail_reversal_recent_hit_times)


def get_tail_reversal_cooldown_status(
    reference_dt: Optional[datetime] = None,
) -> Tuple[bool, float]:
    if not tail_reversal_feature_enabled():
        return False, 0.0

    now_dt = reference_dt or utcnow()
    prune_tail_reversal_recent_hits(now_dt)
    if tail_reversal_cooldown_until is None or now_dt >= tail_reversal_cooldown_until:
        return False, 0.0
    remaining = (tail_reversal_cooldown_until - now_dt).total_seconds()
    return True, max(remaining, 0.0)


def get_tail_reversal_side_mid(
    point: Optional[Dict[str, Any]], side: str
) -> Optional[float]:
    if not isinstance(point, dict):
        return None
    key = "yes_mid" if side == "UP" else "down_mid"
    return optional_float(point.get(key))


def get_tail_reversal_side_prob(
    point: Optional[Dict[str, Any]], side: str
) -> Optional[float]:
    if not isinstance(point, dict):
        return None
    key = "pm_implied_up" if side == "UP" else "pm_implied_down"
    return optional_float(point.get(key))


def build_tail_reversal_point(
    *,
    fair: Optional[Dict[str, Any]],
    yes_bid: float,
    yes_ask: float,
    down_bid: float,
    down_ask: float,
) -> Optional[Dict[str, Any]]:
    remaining_seconds = get_bucket_remaining_seconds()
    if remaining_seconds is None:
        return None

    yes_mid = midpoint(yes_bid, yes_ask)
    down_mid = midpoint(down_bid, down_ask)
    if yes_mid is None or down_mid is None:
        return None

    return {
        "ts": now_iso(),
        "remaining_seconds": remaining_seconds,
        "yes_mid": yes_mid,
        "down_mid": down_mid,
        "pm_implied_up": yes_mid,
        "pm_implied_down": down_mid,
        "fair_yes": optional_float(fair.get("fair_yes") if fair else None),
        "fair_no": optional_float(fair.get("fair_no") if fair else None),
    }


def update_tail_reversal_markers(
    *,
    fair: Optional[Dict[str, Any]],
    yes_bid: float,
    yes_ask: float,
    down_bid: float,
    down_ask: float,
) -> None:
    if not tail_reversal_feature_enabled():
        return

    ledger = ensure_market_ledger()
    if ledger is None or ledger.get("settled"):
        return

    point = build_tail_reversal_point(
        fair=fair,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        down_bid=down_bid,
        down_ask=down_ask,
    )
    if point is None:
        return

    remaining_seconds = optional_float(point.get("remaining_seconds"))
    if remaining_seconds is None:
        return

    anchor_abs = abs(remaining_seconds - TAIL_REVERSAL_ANCHOR_SECONDS)
    current_anchor_abs = optional_float(ledger.get("tail_reversal_anchor_abs_seconds"))
    if current_anchor_abs is None or anchor_abs < current_anchor_abs:
        ledger["tail_reversal_anchor"] = dict(point)
        ledger["tail_reversal_anchor_abs_seconds"] = anchor_abs

    confirm_abs = abs(remaining_seconds - TAIL_REVERSAL_CONFIRM_SECONDS)
    current_confirm_abs = optional_float(
        ledger.get("tail_reversal_confirm_abs_seconds")
    )
    if current_confirm_abs is None or confirm_abs < current_confirm_abs:
        ledger["tail_reversal_confirm"] = dict(point)
        ledger["tail_reversal_confirm_abs_seconds"] = confirm_abs

    current_final_remaining = optional_float(
        ledger.get("tail_reversal_final_remaining_seconds")
    )
    if current_final_remaining is None or remaining_seconds < current_final_remaining:
        ledger["tail_reversal_final"] = dict(point)
        ledger["tail_reversal_final_remaining_seconds"] = remaining_seconds


def determine_tail_reversal_position_side(
    ledger: Dict[str, Any]
) -> Tuple[Optional[str], float, float]:
    yes_shares = safe_float(ledger.get("yes_shares"), 0.0)
    down_shares = safe_float(ledger.get("down_shares"), 0.0)
    yes_cost = safe_float(ledger.get("yes_cost"), 0.0)
    down_cost = safe_float(ledger.get("down_cost"), 0.0)

    if yes_shares > down_shares:
        return "UP", yes_cost, yes_shares
    if down_shares > yes_shares:
        return "DOWN", down_cost, down_shares
    if yes_cost >= down_cost and yes_cost > 0:
        return "UP", yes_cost, yes_shares
    if down_cost > 0:
        return "DOWN", down_cost, down_shares
    return None, 0.0, 0.0


def evaluate_tail_reversal_hit(ledger: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not tail_reversal_feature_enabled():
        return None
    if not ledger.get("settled"):
        return None

    resolved_side = str(ledger.get("resolved_side") or "")
    if resolved_side not in {"UP", "DOWN"}:
        return None

    total_cost = safe_float(ledger.get("total_cost"), 0.0)
    if total_cost <= 0:
        return None

    side, side_cost, side_shares = determine_tail_reversal_position_side(ledger)
    if side is None or side_cost <= 0 or side_shares <= 0:
        return None
    if side == resolved_side:
        return None

    anchor_point = ledger.get("tail_reversal_anchor")
    end_point = ledger.get("tail_reversal_final") or ledger.get("tail_reversal_confirm")
    anchor_prob = get_tail_reversal_side_prob(anchor_point, side)
    end_prob = get_tail_reversal_side_prob(end_point, side)
    if anchor_prob is None or end_prob is None:
        return None

    avg_entry_price = side_cost / side_shares
    anchor_mid = get_tail_reversal_side_mid(anchor_point, side)
    favorable_at_anchor = (
        (
            anchor_mid is not None
            and (anchor_mid - avg_entry_price) >= TAIL_REVERSAL_MIN_MID_GAIN
        )
        or anchor_prob >= TAIL_REVERSAL_MIN_ANCHOR_PROB
    )
    if not favorable_at_anchor:
        return None

    prob_drop = anchor_prob - end_prob
    if prob_drop < TAIL_REVERSAL_MIN_PROB_DROP or end_prob > 0.5:
        return None

    net_pnl_estimate = safe_float(ledger.get("net_pnl_estimate"), 0.0)
    if net_pnl_estimate >= 0:
        return None

    return {
        "market_slug": ledger.get("market_slug"),
        "primary_side": side,
        "resolved_side": resolved_side,
        "avg_entry_price": round(avg_entry_price, 8),
        "anchor_mid": round(anchor_mid, 8) if anchor_mid is not None else None,
        "anchor_prob": round(anchor_prob, 8),
        "end_prob": round(end_prob, 8),
        "prob_drop": round(prob_drop, 8),
        "anchor_remaining_seconds": optional_float(
            anchor_point.get("remaining_seconds") if isinstance(anchor_point, dict) else None
        ),
        "final_remaining_seconds": optional_float(
            end_point.get("remaining_seconds") if isinstance(end_point, dict) else None
        ),
        "anchor_ts": (
            str(anchor_point.get("ts")) if isinstance(anchor_point, dict) else None
        ),
        "end_ts": str(end_point.get("ts")) if isinstance(end_point, dict) else None,
        "net_pnl_estimate": round(net_pnl_estimate, 8),
    }


def process_tail_reversal_settlement(ledger: Dict[str, Any]) -> None:
    global tail_reversal_cooldown_until

    ledger["tail_reversal_hit"] = False
    ledger["tail_reversal_hit_details"] = None

    if not tail_reversal_feature_enabled():
        return

    hit_details = evaluate_tail_reversal_hit(ledger)
    if hit_details is None:
        prune_tail_reversal_recent_hits()
        return

    ledger["tail_reversal_hit"] = True
    hit_dt = parse_dt(ledger.get("market_end_utc")) or parse_dt(ledger.get("settled_at")) or utcnow()
    tail_reversal_recent_hit_times.append(hit_dt)
    prune_tail_reversal_recent_hits(hit_dt)

    recent_hit_count = len(tail_reversal_recent_hit_times)
    hit_details["recent_hit_count"] = recent_hit_count
    hit_details["cooldown_triggered"] = False
    hit_details["cooldown_until"] = (
        tail_reversal_cooldown_until.isoformat()
        if tail_reversal_cooldown_until is not None
        else None
    )

    print(
        f"⚠️ 尾盤反轉命中 | market={ledger['market_slug']} | "
        f"side={hit_details['primary_side']} -> resolved={hit_details['resolved_side']} | "
        f"anchor_prob={safe_float(hit_details.get('anchor_prob')):.3f} | "
        f"end_prob={safe_float(hit_details.get('end_prob')):.3f} | "
        f"drop={safe_float(hit_details.get('prob_drop')):.3f} | "
        f"recent_hits={recent_hit_count}/{TAIL_REVERSAL_TRIGGER_COUNT}"
    )

    if recent_hit_count >= TAIL_REVERSAL_TRIGGER_COUNT:
        new_until = hit_dt + timedelta(seconds=TAIL_REVERSAL_COOLDOWN_SECONDS)
        if tail_reversal_cooldown_until is None or new_until > tail_reversal_cooldown_until:
            tail_reversal_cooldown_until = new_until
        hit_details["cooldown_triggered"] = True
        hit_details["cooldown_until"] = tail_reversal_cooldown_until.isoformat()
        print(
            f"🧊 啟用 tail reversal cooldown | until={tail_reversal_cooldown_until.isoformat()} | "
            f"lookback={TAIL_REVERSAL_LOOKBACK_SECONDS:.0f}s | "
            f"trigger_count={TAIL_REVERSAL_TRIGGER_COUNT}"
        )

    ledger["tail_reversal_hit_details"] = hit_details


def recalc_market_estimates(ledger: Dict[str, Any]) -> None:
    yes_shares = safe_float(ledger.get("yes_shares"))
    down_shares = safe_float(ledger.get("down_shares"))
    yes_cost = safe_float(ledger.get("yes_cost"))
    down_cost = safe_float(ledger.get("down_cost"))
    total_cost = yes_cost + down_cost
    fee_total = safe_float(ledger.get("estimated_fee_total"))

    ledger["total_cost"] = total_cost
    ledger["pnl_if_up_estimate"] = yes_shares - total_cost - fee_total
    ledger["pnl_if_down_estimate"] = down_shares - total_cost - fee_total


def refresh_side_extension_state(ledger: Dict[str, Any]) -> None:
    if SIDE_EXTENSION_EFFECTIVE_START_COST <= 0:
        return

    if (
        safe_float(ledger.get("yes_cost"), 0.0) >= SIDE_EXTENSION_EFFECTIVE_START_COST
        and not ledger.get("yes_extension_start_at")
    ):
        ledger["yes_extension_start_at"] = now_iso()

    if (
        safe_float(ledger.get("down_cost"), 0.0) >= SIDE_EXTENSION_EFFECTIVE_START_COST
        and not ledger.get("down_extension_start_at")
    ):
        ledger["down_extension_start_at"] = now_iso()


def get_side_extension_keys(signal_side: str) -> Tuple[str, str]:
    if signal_side == "UP":
        return "yes_extension_start_at", "yes_last_extension_order_at"
    return "down_extension_start_at", "down_last_extension_order_at"


def persist_market_state_json() -> None:
    global pending_settlement

    ledgers_state = {}
    for slug, ledger in market_ledgers.items():
        ledgers_state[slug] = {
            "market_slug": ledger["market_slug"],
            "market_question": ledger["market_question"],
            "condition_id": ledger.get("condition_id"),
            "market_start_utc": ledger["market_start_utc"],
            "market_end_utc": ledger["market_end_utc"],
            "pm_open_price": ledger.get("pm_open_price"),
            "bn_open_price": ledger.get("bn_open_price"),
            "effective_open_price": ledger.get("effective_open_price"),
            "open_price_source": ledger.get("open_price_source"),
            "mode_observed": ledger.get("mode_observed"),
            "yes_fee_rate_bps": ledger.get("yes_fee_rate_bps", 0),
            "down_fee_rate_bps": ledger.get("down_fee_rate_bps", 0),
            "fees_enabled": ledger.get("fees_enabled", False),
            "fee_rules_source": ledger.get("fee_rules_source"),
            "created_at": ledger.get("created_at"),
            "settled": ledger["settled"],
            "resolved_side": ledger["resolved_side"],
            "resolution_price": ledger.get("resolution_price"),
            "resolution_price_source": ledger.get("resolution_price_source"),
            "bn_resolution_price_fallback": ledger.get(
                "bn_resolution_price_fallback"
            ),
            "settlement_reason": ledger.get("settlement_reason"),
            "yes_orders": ledger["yes_orders"],
            "down_orders": ledger["down_orders"],
            "yes_shares": ledger["yes_shares"],
            "down_shares": ledger["down_shares"],
            "yes_cost": ledger["yes_cost"],
            "down_cost": ledger["down_cost"],
            "total_cost": ledger["total_cost"],
            "yes_extension_start_at": ledger.get("yes_extension_start_at"),
            "down_extension_start_at": ledger.get("down_extension_start_at"),
            "yes_last_extension_order_at": ledger.get("yes_last_extension_order_at"),
            "down_last_extension_order_at": ledger.get("down_last_extension_order_at"),
            "estimated_fee_total": ledger["estimated_fee_total"],
            "pnl_if_up_estimate": ledger["pnl_if_up_estimate"],
            "pnl_if_down_estimate": ledger["pnl_if_down_estimate"],
            "gross_payout_estimate": ledger["gross_payout_estimate"],
            "net_pnl_estimate": ledger["net_pnl_estimate"],
            "settled_at": ledger["settled_at"],
            "tail_reversal_anchor": ledger.get("tail_reversal_anchor"),
            "tail_reversal_confirm": ledger.get("tail_reversal_confirm"),
            "tail_reversal_final": ledger.get("tail_reversal_final"),
            "tail_reversal_anchor_abs_seconds": ledger.get(
                "tail_reversal_anchor_abs_seconds"
            ),
            "tail_reversal_confirm_abs_seconds": ledger.get(
                "tail_reversal_confirm_abs_seconds"
            ),
            "tail_reversal_final_remaining_seconds": ledger.get(
                "tail_reversal_final_remaining_seconds"
            ),
            "tail_reversal_hit": ledger.get("tail_reversal_hit", False),
            "tail_reversal_hit_details": ledger.get("tail_reversal_hit_details"),
            "orders": ledger.get("orders", []),
        }

    state = {
        "market_ledgers": ledgers_state,
        "pending_settlement": pending_settlement,
        "tail_reversal_state": {
            "recent_hit_times": [
                hit_dt.isoformat() for hit_dt in tail_reversal_recent_hit_times
            ],
            "cooldown_until": (
                tail_reversal_cooldown_until.isoformat()
                if tail_reversal_cooldown_until is not None
                else None
            ),
        },
    }

    MARKET_STATE_JSON_PATH.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def print_ledger_snapshot(ledger: Dict[str, Any]) -> None:
    if not SHOW_LEDGER_SNAPSHOT_LOG:
        return

    print(
        f"📒 帳本 | {ledger['market_slug']} | "
        f"YES shares={ledger['yes_shares']:.4f} cost={ledger['yes_cost']:.4f} | "
        f"DOWN shares={ledger['down_shares']:.4f} cost={ledger['down_cost']:.4f} | "
        f"fees={ledger['estimated_fee_total']:.5f} | "
        f"PnL_if_UP={ledger['pnl_if_up_estimate']:+.4f} | "
        f"PnL_if_DOWN={ledger['pnl_if_down_estimate']:+.4f}"
    )


def check_market_exposure_limits(
    signal_side: str,
    source_signal: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, bool]:
    ledger = ensure_market_ledger()
    if ledger is None:
        return True, "", False

    yes_cost = safe_float(ledger.get("yes_cost"), 0.0)
    down_cost = safe_float(ledger.get("down_cost"), 0.0)
    total_cost = safe_float(ledger.get("total_cost"), 0.0)

    if MARKET_MAX_TOTAL_COST > 0 and total_cost >= MARKET_MAX_TOTAL_COST:
        return (
            False,
            "market_total_cap_reached | "
            f"total_cost={total_cost:.2f} | "
            f"market_cap={MARKET_MAX_TOTAL_COST:.2f} | "
            f"yes_cost={yes_cost:.2f} | down_cost={down_cost:.2f}",
            False,
        )

    side_cost = yes_cost if signal_side == "UP" else down_cost
    opposite_cost = down_cost if signal_side == "UP" else yes_cost

    if MARKET_MAX_SIDE_COST <= 0 or side_cost < MARKET_MAX_SIDE_COST:
        return True, "", False

    if not SIDE_EXTENSION_ENABLED:
        return (
            False,
            "market_side_cap_reached | "
            f"side={signal_side} | side_cost={side_cost:.2f} | "
            f"side_cap={MARKET_MAX_SIDE_COST:.2f} | "
            f"yes_cost={yes_cost:.2f} | down_cost={down_cost:.2f}",
            False,
        )

    if (
        SIDE_EXTENSION_EFFECTIVE_MAX_SIDE_COST > 0
        and side_cost >= SIDE_EXTENSION_EFFECTIVE_MAX_SIDE_COST
    ):
        return (
            False,
            "market_side_extension_cap_reached | "
            f"side={signal_side} | side_cost={side_cost:.2f} | "
            f"extension_cap={SIDE_EXTENSION_EFFECTIVE_MAX_SIDE_COST:.2f} | "
            f"yes_cost={yes_cost:.2f} | down_cost={down_cost:.2f}",
            False,
        )

    if source_signal is None:
        return (
            False,
            "extension_signal_missing | "
            f"side={signal_side} | side_cost={side_cost:.2f}",
            False,
        )

    ask = safe_float(source_signal.get("ask"), 0.0)
    signal_edge = safe_float(source_signal.get("diff"), 0.0)
    edge_after_fill = safe_float(source_signal.get("edge_after_fill_estimate"), 0.0)
    if ask < SIDE_EXTENSION_MIN_ASK_PRICE or ask > SIDE_EXTENSION_MAX_ASK_PRICE:
        return (
            False,
            "extension_ask_out_of_range | "
            f"side={signal_side} | ask={ask:.3f} | "
            f"range={SIDE_EXTENSION_MIN_ASK_PRICE:.3f}-{SIDE_EXTENSION_MAX_ASK_PRICE:.3f}",
            False,
        )

    if signal_edge < SIDE_EXTENSION_MIN_EDGE:
        return (
            False,
            "extension_edge_too_low | "
            f"side={signal_side} | edge={signal_edge:.3f} | "
            f"min_edge={SIDE_EXTENSION_MIN_EDGE:.3f}",
            False,
        )

    if edge_after_fill < SIDE_EXTENSION_MIN_EDGE_AFTER_FILL:
        return (
            False,
            "extension_edge_after_fill_too_low | "
            f"side={signal_side} | edge_after_fill={edge_after_fill:.3f} | "
            f"min_edge_after_fill={SIDE_EXTENSION_MIN_EDGE_AFTER_FILL:.3f}",
            False,
        )

    if (
        SIDE_EXTENSION_MAX_OPPOSITE_COST > 0
        and opposite_cost > SIDE_EXTENSION_MAX_OPPOSITE_COST
    ):
        return (
            False,
            "extension_opposite_cost_too_high | "
            f"side={signal_side} | opposite_cost={opposite_cost:.2f} | "
            f"max_opposite_cost={SIDE_EXTENSION_MAX_OPPOSITE_COST:.2f}",
            False,
        )

    start_key, last_key = get_side_extension_keys(signal_side)
    reached_dt = parse_dt(ledger.get(start_key))
    if reached_dt is None:
        ledger[start_key] = now_iso()
        persist_market_state_json()
        return (
            False,
            "extension_timer_started | "
            f"side={signal_side} | start_cost={SIDE_EXTENSION_EFFECTIVE_START_COST:.2f} | "
            f"wait_seconds={SIDE_EXTENSION_MIN_SECONDS}",
            False,
        )

    elapsed_since_start = (utcnow() - reached_dt).total_seconds()
    if elapsed_since_start < SIDE_EXTENSION_MIN_SECONDS:
        return (
            False,
            "extension_min_seconds_not_met | "
            f"side={signal_side} | elapsed={elapsed_since_start:.1f}s | "
            f"min_seconds={SIDE_EXTENSION_MIN_SECONDS}",
            False,
        )

    last_extension_dt = parse_dt(ledger.get(last_key))
    if last_extension_dt is not None:
        elapsed_since_last_extension = (utcnow() - last_extension_dt).total_seconds()
        if elapsed_since_last_extension < SIDE_EXTENSION_COOLDOWN_SECONDS:
            return (
                False,
                "extension_cooldown_not_met | "
                f"side={signal_side} | elapsed={elapsed_since_last_extension:.1f}s | "
                f"cooldown={SIDE_EXTENSION_COOLDOWN_SECONDS}",
                False,
            )

    return True, "", True


def compute_settlement_win_loss_stats() -> Dict[str, Any]:
    win_count = 0
    loss_count = 0
    skipped_count = 0
    up_market_count = 0
    down_market_count = 0
    traded_market_count = 0
    total_amount_sum = 0.0
    total_win_pnl = 0.0
    total_loss_pnl = 0.0

    for ledger in market_ledgers.values():
        if not ledger.get("settled"):
            continue

        total_cost = safe_float(ledger.get("total_cost"), 0.0)
        if total_cost <= 0:
            skipped_count += 1
            continue

        traded_market_count += 1
        total_amount_sum += total_cost

        yes_shares = safe_float(ledger.get("yes_shares"), 0.0)
        down_shares = safe_float(ledger.get("down_shares"), 0.0)
        if yes_shares > down_shares:
            up_market_count += 1
        elif down_shares > yes_shares:
            down_market_count += 1

        net_pnl_estimate = safe_float(ledger.get("net_pnl_estimate"), 0.0)
        if net_pnl_estimate > 0:
            win_count += 1
            total_win_pnl += net_pnl_estimate
        else:
            loss_count += 1

            total_loss_pnl += net_pnl_estimate

    settled_count = win_count + loss_count + skipped_count
    decisive_count = win_count + loss_count
    win_rate_pct = (win_count / decisive_count * 100.0) if decisive_count > 0 else 0.0
    avg_amount_per_market = (
        total_amount_sum / traded_market_count if traded_market_count > 0 else 0.0
    )
    avg_win_pnl = total_win_pnl / win_count if win_count > 0 else 0.0
    avg_loss_pnl = total_loss_pnl / loss_count if loss_count > 0 else 0.0

    return {
        "settled_count": settled_count,
        "win_count": win_count,
        "loss_count": loss_count,
        "skipped_count": skipped_count,
        "win_rate_pct": win_rate_pct,
        "up_market_count": up_market_count,
        "down_market_count": down_market_count,
        "traded_market_count": traded_market_count,
        "avg_amount_per_market": avg_amount_per_market,
        "avg_win_pnl": avg_win_pnl,
        "avg_loss_pnl": avg_loss_pnl,
    }


def record_order_event(
    *,
    status: str,
    included_in_position: bool,
    signal_side: str,
    amount_usd: float,
    source_signal: Optional[Dict[str, Any]],
    response_order_id: str = "",
    error: str = "",
    requested_amount_usd: Optional[float] = None,
    execution_price: Optional[float] = None,
    execution_estimate: Optional[Dict[str, float]] = None,
) -> None:
    ledger = ensure_market_ledger()
    if ledger is None:
        return

    row_amount_usd = safe_float(amount_usd, 0.0)
    position_amount_usd = row_amount_usd if included_in_position else 0.0
    requested_amount = safe_float(
        requested_amount_usd if requested_amount_usd is not None else amount_usd,
        row_amount_usd,
    )
    execution_price_estimate = safe_float(execution_price, 0.0)
    if execution_price_estimate <= 0:
        execution_price_estimate = safe_float(
            (
                source_signal.get("max_execution_price")
                if source_signal
                else None
            ),
            safe_float(source_signal.get("ask") if source_signal else None, 0.0),
        )
    fee_rate_bps = (
        current_yes_fee_rate_bps if signal_side == "UP" else current_down_fee_rate_bps
    )
    exec_estimate = execution_estimate if included_in_position else None
    exec_estimate = exec_estimate or estimate_taker_buy_execution(
        amount_usd=position_amount_usd,
        price=execution_price_estimate,
        fee_rate_bps=fee_rate_bps,
    )

    gross_shares = exec_estimate["gross_shares"]
    fee_usdc = exec_estimate["fee_usdc"]
    fee_shares = exec_estimate["fee_shares"]
    net_shares = exec_estimate["net_shares"]

    outcome_bought = "YES" if signal_side == "UP" else "DOWN"
    previous_yes_cost = safe_float(ledger.get("yes_cost"), 0.0)
    previous_down_cost = safe_float(ledger.get("down_cost"), 0.0)

    if included_in_position:
        if signal_side == "UP":
            ledger["yes_orders"] += 1
            ledger["yes_shares"] += net_shares
            ledger["yes_cost"] += position_amount_usd
        else:
            ledger["down_orders"] += 1
            ledger["down_shares"] += net_shares
            ledger["down_cost"] += position_amount_usd

        ledger["estimated_fee_total"] += fee_usdc
        recalc_market_estimates(ledger)
        refresh_side_extension_state(ledger)

        start_key, last_key = get_side_extension_keys(signal_side)
        previous_side_cost = previous_yes_cost if signal_side == "UP" else previous_down_cost
        if (
            SIDE_EXTENSION_ENABLED
            and previous_side_cost >= SIDE_EXTENSION_EFFECTIVE_START_COST
        ):
            ledger[last_key] = now_iso()

    row = {
        "recorded_at": now_iso(),
        "market_slug": ledger["market_slug"],
        "market_question": ledger["market_question"],
        "market_start_utc": ledger["market_start_utc"],
        "market_end_utc": ledger["market_end_utc"],
        "mode": "dry_run" if DRY_RUN else "live_estimated",
        "status": status,
        "included_in_position": included_in_position,
        "resolution_side_intended": signal_side,
        "outcome_bought": outcome_bought,
        "amount_usd": round(row_amount_usd, 8),
        "requested_amount_usd": round(requested_amount, 8),
        "filled_amount_usd": round(position_amount_usd, 8),
        "fill_ratio": (
            round(position_amount_usd / requested_amount, 8)
            if requested_amount > 0
            else ""
        ),
        "execution_price_estimate": round(execution_price_estimate, 8),
        "estimated_shares_gross": round(gross_shares, 8),
        "estimated_fee_usdc": round(fee_usdc, 8),
        "estimated_fee_shares": round(fee_shares, 8),
        "estimated_shares_net": round(net_shares, 8),
        "fee_rate_bps": int(fee_rate_bps),
        "fees_enabled": bool(fee_rate_bps > 0),
        "signal_model": (
            str(source_signal.get("signal_model", SIGNAL_MODEL_NAME))
            if source_signal
            else SIGNAL_MODEL_NAME
        ),
        "signal_fair": round(
            safe_float(source_signal.get("fair") if source_signal else None), 8
        ),
        "signal_edge": round(
            safe_float(source_signal.get("diff") if source_signal else None), 8
        ),
        "signal_edge_reference": (
            str(source_signal.get("edge_reference") if source_signal else "")
        ),
        "signal_reference_price": round(
            safe_float(source_signal.get("reference_price") if source_signal else None),
            8,
        ),
        "signal_bid": round(
            safe_float(source_signal.get("bid") if source_signal else None), 8
        ),
        "signal_ask": round(
            safe_float(source_signal.get("ask") if source_signal else None), 8
        ),
        "signal_spread": round(
            safe_float(source_signal.get("spread") if source_signal else None), 8
        ),
        "signal_open_anchor_mode": (
            str(source_signal.get("open_anchor_mode") if source_signal else "")
        ),
        "signal_open_anchor_weight": round(
            safe_float(
                source_signal.get("open_anchor_weight") if source_signal else None
            ),
            8,
        ),
        "signal_open_anchor_price": round(
            safe_float(
                source_signal.get("open_anchor_price") if source_signal else None
            ),
            8,
        ),
        "signal_pm_open_price": round(
            safe_float(source_signal.get("pm_open_price") if source_signal else None),
            8,
        ),
        "signal_bn_open_price": round(
            safe_float(source_signal.get("bn_open_price") if source_signal else None),
            8,
        ),
        "signal_order_type": (
            str(source_signal.get("order_type") if source_signal else TAKER_ORDER_TYPE)
        ),
        "signal_exec_price_mode": (
            str(source_signal.get("exec_price_mode") if source_signal else "")
        ),
        "signal_max_execution_price": round(
            safe_float(
                source_signal.get("max_execution_price") if source_signal else None
            ),
            8,
        ),
        "signal_order_price_hint": (
            round(safe_float(source_signal.get("order_price_hint")), 8)
            if source_signal and source_signal.get("order_price_hint") is not None
            else ""
        ),
        "signal_edge_after_fill_estimate": round(
            safe_float(
                source_signal.get("edge_after_fill_estimate")
                if source_signal
                else None
            ),
            8,
        ),
        "bn_price": round(
            safe_float(source_signal.get("bn_price") if source_signal else None), 8
        ),
        "bn_open_price": round(
            safe_float(source_signal.get("bn_open_price") if source_signal else None),
            8,
        ),
        "sigma": round(
            safe_float(source_signal.get("sigma") if source_signal else None), 12
        ),
        "sigma_short": round(
            safe_float(source_signal.get("sigma_short") if source_signal else None), 12
        ),
        "sigma_long": round(
            safe_float(source_signal.get("sigma_long") if source_signal else None), 12
        ),
        "sigma_eff": round(
            safe_float(source_signal.get("sigma_eff") if source_signal else None), 12
        ),
        "tau_seconds": round(
            safe_float(source_signal.get("tau_seconds") if source_signal else None), 6
        ),
        "z": round(safe_float(source_signal.get("z") if source_signal else None), 8),
        "response_order_id": response_order_id,
        "error": error,
    }
    append_csv_row(ORDERS_CSV_PATH, row, ORDERS_FIELDNAMES)

    ledger["orders"].append(row)
    persist_market_state_json()
    print_ledger_snapshot(ledger)


def infer_fill_from_order_response(resp: Optional[Dict[str, Any]]) -> Tuple[bool, bool]:
    if not isinstance(resp, dict):
        return False, False

    explicit_fill = parse_buy_fill_from_order_response(
        resp,
        requested_amount_usd=TRADE_AMOUNT_USD,
        fallback_price=0.0,
    )
    if (
        safe_float(explicit_fill.get("amount_usd"), 0.0) > 0
        and safe_float(explicit_fill.get("gross_shares"), 0.0) > 0
    ):
        return True, False

    status = str(
        pick_first_value(resp, "status", "state", "orderStatus", "order_status") or ""
    ).strip().lower()
    success = resp.get("success")

    fill_markers = {
        "filled",
        "matched",
        "mined",
        "confirmed",
        "success",
        "live_success",
    }
    reject_markers = {
        "failed",
        "rejected",
        "cancelled",
        "canceled",
        "expired",
        "unmatched",
    }

    if status in fill_markers:
        return True, False
    if status in reject_markers:
        return False, False
    if success is True and TAKER_ORDER_TYPE == "FOK":
        return True, True
    if success is False:
        return False, False

    return False, True


def record_execution_attempt(
    *,
    status: str,
    attempt_stage: str,
    signal_side: str,
    token_id: str,
    amount_usd: float,
    source_signal: Optional[Dict[str, Any]],
    order_sent: bool = False,
    order_accepted: bool = False,
    filled: bool = False,
    fill_inferred: bool = False,
    fill_amount_usd: Optional[float] = None,
    fill_shares: Optional[float] = None,
    fill_avg_price: Optional[float] = None,
    fill_ratio: Optional[float] = None,
    fill_price: Optional[float] = None,
    fill_size: Optional[float] = None,
    response_order_id: str = "",
    latency_ms: Optional[float] = None,
    failed_reason: str = "",
    raw_response: Optional[Any] = None,
) -> None:
    ledger = ensure_market_ledger()
    if ledger is None:
        return

    candidate_id = ensure_signal_candidate_id(source_signal)
    limit_price = safe_float(
        source_signal.get("max_execution_price") if source_signal else None,
        safe_float(source_signal.get("ask") if source_signal else None, 0.0),
    )
    raw_response_text = ""
    if raw_response is not None:
        raw_response_text = compact_json(raw_response)
    ml_enabled = (
        source_signal.get("ml_filter_enabled", ML_FILTER_ENABLED)
        if source_signal
        else ML_FILTER_ENABLED
    )
    ml_predicted_ev = (
        optional_float(source_signal.get("ml_predicted_ev")) if source_signal else None
    )
    ml_min_ev = (
        optional_float(source_signal.get("ml_min_ev"))
        if source_signal and source_signal.get("ml_min_ev") is not None
        else (ML_FILTER_MIN_EV if ml_enabled else None)
    )
    ml_passed = (
        source_signal.get("ml_passed") if source_signal and "ml_passed" in source_signal else ""
    )
    ml_feature_names_text = (
        compact_json(source_signal.get("ml_feature_names"))
        if source_signal and source_signal.get("ml_feature_names")
        else ""
    )
    ml_feature_values_text = (
        compact_json(source_signal.get("ml_feature_values"))
        if source_signal and source_signal.get("ml_feature_values")
        else ""
    )
    fill_prob_enabled = (
        source_signal.get("fill_prob_filter_enabled", FILL_PROB_FILTER_ENABLED)
        if source_signal
        else FILL_PROB_FILTER_ENABLED
    )
    fill_probability = (
        optional_float(source_signal.get("fill_probability")) if source_signal else None
    )
    fill_prob_min_probability = (
        optional_float(source_signal.get("fill_prob_min_probability"))
        if source_signal and source_signal.get("fill_prob_min_probability") is not None
        else (FILL_PROB_MIN_PROBABILITY if fill_prob_enabled else None)
    )
    fill_prob_passed = (
        source_signal.get("fill_prob_passed")
        if source_signal and "fill_prob_passed" in source_signal
        else ""
    )
    fill_prob_feature_names_text = (
        compact_json(source_signal.get("fill_prob_feature_names"))
        if source_signal and source_signal.get("fill_prob_feature_names")
        else ""
    )
    fill_prob_feature_values_text = (
        compact_json(source_signal.get("fill_prob_feature_values"))
        if source_signal and source_signal.get("fill_prob_feature_values")
        else ""
    )

    row = {
        "recorded_at": now_iso(),
        "candidate_id": candidate_id,
        "market_slug": ledger["market_slug"],
        "market_question": ledger["market_question"],
        "market_start_utc": ledger["market_start_utc"],
        "market_end_utc": ledger["market_end_utc"],
        "elapsed_seconds": round(
            safe_float(source_signal.get("elapsed_seconds") if source_signal else None),
            3,
        ),
        "time_bucket": str(source_signal.get("time_bucket") if source_signal else ""),
        "mode": "dry_run" if DRY_RUN else "live",
        "dry_run": DRY_RUN,
        "status": status,
        "attempt_stage": attempt_stage,
        "side": signal_side,
        "outcome_bought": "YES" if signal_side == "UP" else "DOWN",
        "token_id": token_id,
        "amount_usd": round(amount_usd, 8),
        "order_type": str(
            source_signal.get("order_type") if source_signal else TAKER_ORDER_TYPE
        ),
        "exec_price_mode": str(
            source_signal.get("exec_price_mode") if source_signal else EXEC_PRICE_MODE
        ),
        "is_extension_order": bool(
            source_signal.get("is_extension_order") if source_signal else False
        ),
        "signal_model": (
            str(source_signal.get("signal_model", SIGNAL_MODEL_NAME))
            if source_signal
            else SIGNAL_MODEL_NAME
        ),
        "signal_fair": round(
            safe_float(source_signal.get("fair") if source_signal else None), 8
        ),
        "signal_edge": round(
            safe_float(source_signal.get("diff") if source_signal else None), 8
        ),
        "signal_edge_reference": (
            str(source_signal.get("edge_reference") if source_signal else "")
        ),
        "signal_reference_price": round(
            safe_float(source_signal.get("reference_price") if source_signal else None),
            8,
        ),
        "signal_bid": round(
            safe_float(source_signal.get("bid") if source_signal else None), 8
        ),
        "signal_ask": round(
            safe_float(source_signal.get("ask") if source_signal else None), 8
        ),
        "signal_spread": round(
            safe_float(source_signal.get("spread") if source_signal else None), 8
        ),
        "signal_open_anchor_mode": (
            str(source_signal.get("open_anchor_mode") if source_signal else "")
        ),
        "signal_open_anchor_weight": round(
            safe_float(
                source_signal.get("open_anchor_weight") if source_signal else None
            ),
            8,
        ),
        "signal_open_anchor_price": round(
            safe_float(
                source_signal.get("open_anchor_price") if source_signal else None
            ),
            8,
        ),
        "signal_pm_open_price": round(
            safe_float(source_signal.get("pm_open_price") if source_signal else None),
            8,
        ),
        "signal_bn_open_price": round(
            safe_float(source_signal.get("bn_open_price") if source_signal else None),
            8,
        ),
        "bn_price": round(
            safe_float(source_signal.get("bn_price") if source_signal else None), 8
        ),
        "bn_open_price": round(
            safe_float(source_signal.get("bn_open_price") if source_signal else None),
            8,
        ),
        "sigma": round(
            safe_float(source_signal.get("sigma") if source_signal else None), 12
        ),
        "sigma_short": round(
            safe_float(source_signal.get("sigma_short") if source_signal else None), 12
        ),
        "sigma_long": round(
            safe_float(source_signal.get("sigma_long") if source_signal else None), 12
        ),
        "sigma_eff": round(
            safe_float(source_signal.get("sigma_eff") if source_signal else None), 12
        ),
        "tau_seconds": round(
            safe_float(source_signal.get("tau_seconds") if source_signal else None), 6
        ),
        "z": round(safe_float(source_signal.get("z") if source_signal else None), 8),
        "limit_price": round(limit_price, 8),
        "order_price_hint": (
            round(safe_float(source_signal.get("order_price_hint")), 8)
            if source_signal and source_signal.get("order_price_hint") is not None
            else ""
        ),
        "signal_edge_after_fill_estimate": round(
            safe_float(
                source_signal.get("edge_after_fill_estimate")
                if source_signal
                else None
            ),
            8,
        ),
        "ml_filter_enabled": bool(ml_enabled),
        "ml_predicted_ev": (
            round(ml_predicted_ev, 8) if ml_predicted_ev is not None else ""
        ),
        "ml_min_ev": round(ml_min_ev, 8) if ml_min_ev is not None else "",
        "ml_passed": ml_passed,
        "ml_reason": str(source_signal.get("ml_reason", "")) if source_signal else "",
        "ml_model_path": (
            str(source_signal.get("ml_model_path", "")) if source_signal else ""
        ),
        "ml_features_path": (
            str(source_signal.get("ml_features_path", "")) if source_signal else ""
        ),
        "ml_model_target": (
            str(source_signal.get("ml_model_target", "")) if source_signal else ""
        ),
        "ml_prediction_unit": (
            str(source_signal.get("ml_prediction_unit", "")) if source_signal else ""
        ),
        "ml_feature_names": ml_feature_names_text,
        "ml_feature_values_json": ml_feature_values_text,
        "fill_prob_filter_enabled": bool(fill_prob_enabled),
        "fill_probability": (
            round(fill_probability, 8) if fill_probability is not None else ""
        ),
        "fill_prob_min_probability": (
            round(fill_prob_min_probability, 8)
            if fill_prob_min_probability is not None
            else ""
        ),
        "fill_prob_passed": fill_prob_passed,
        "fill_prob_reason": (
            str(source_signal.get("fill_prob_reason", "")) if source_signal else ""
        ),
        "fill_prob_model_path": (
            str(source_signal.get("fill_prob_model_path", "")) if source_signal else ""
        ),
        "fill_prob_features_path": (
            str(source_signal.get("fill_prob_features_path", ""))
            if source_signal
            else ""
        ),
        "fill_prob_model_target": (
            str(source_signal.get("fill_prob_model_target", "")) if source_signal else ""
        ),
        "fill_prob_prediction_unit": (
            str(source_signal.get("fill_prob_prediction_unit", ""))
            if source_signal
            else ""
        ),
        "fill_prob_feature_names": fill_prob_feature_names_text,
        "fill_prob_feature_values_json": fill_prob_feature_values_text,
        "order_sent": bool(order_sent),
        "order_accepted": bool(order_accepted),
        "filled": bool(filled),
        "fill_inferred": bool(fill_inferred),
        "fill_amount_usd": (
            round(safe_float(fill_amount_usd), 8)
            if fill_amount_usd is not None
            else ""
        ),
        "fill_shares": (
            round(safe_float(fill_shares), 8) if fill_shares is not None else ""
        ),
        "fill_avg_price": (
            round(safe_float(fill_avg_price), 8)
            if fill_avg_price is not None
            else ""
        ),
        "fill_ratio": (
            round(safe_float(fill_ratio), 8) if fill_ratio is not None else ""
        ),
        "fill_price": round(safe_float(fill_price), 8) if fill_price is not None else "",
        "fill_size": round(safe_float(fill_size), 8) if fill_size is not None else "",
        "response_order_id": response_order_id,
        "latency_ms": round(safe_float(latency_ms), 3) if latency_ms is not None else "",
        "failed_reason": failed_reason,
        "raw_response": raw_response_text,
    }
    append_csv_row(EXECUTION_ATTEMPTS_CSV_PATH, row, EXECUTION_ATTEMPTS_FIELDNAMES)


def record_raw_candidate(
    *,
    candidate_stage: str,
    candidate_action: str,
    signal_side: str,
    token_id: str,
    amount_usd: float,
    source_signal: Optional[Dict[str, Any]],
) -> None:
    if not RAW_CANDIDATE_LOG_ENABLED:
        return

    ledger = ensure_market_ledger()
    if ledger is None:
        return

    candidate_id = ensure_signal_candidate_id(source_signal)
    yes_cost = safe_float(ledger.get("yes_cost"), 0.0)
    down_cost = safe_float(ledger.get("down_cost"), 0.0)
    total_cost = safe_float(ledger.get("total_cost"), 0.0)
    limit_price = safe_float(
        source_signal.get("max_execution_price") if source_signal else None,
        safe_float(source_signal.get("ask") if source_signal else None, 0.0),
    )
    ml_enabled = (
        source_signal.get("ml_filter_enabled", ML_FILTER_ENABLED)
        if source_signal
        else ML_FILTER_ENABLED
    )
    ml_predicted_ev = (
        optional_float(source_signal.get("ml_predicted_ev")) if source_signal else None
    )
    ml_min_ev = (
        optional_float(source_signal.get("ml_min_ev"))
        if source_signal and source_signal.get("ml_min_ev") is not None
        else (ML_FILTER_MIN_EV if ml_enabled else None)
    )
    fill_prob_enabled = (
        source_signal.get("fill_prob_filter_enabled", FILL_PROB_FILTER_ENABLED)
        if source_signal
        else FILL_PROB_FILTER_ENABLED
    )
    fill_probability = (
        optional_float(source_signal.get("fill_probability")) if source_signal else None
    )
    fill_prob_min_probability = (
        optional_float(source_signal.get("fill_prob_min_probability"))
        if source_signal and source_signal.get("fill_prob_min_probability") is not None
        else (FILL_PROB_MIN_PROBABILITY if fill_prob_enabled else None)
    )

    row = {
        "recorded_at": now_iso(),
        "candidate_id": candidate_id,
        "market_slug": ledger["market_slug"],
        "market_question": ledger["market_question"],
        "market_start_utc": ledger["market_start_utc"],
        "market_end_utc": ledger["market_end_utc"],
        "elapsed_seconds": round(
            safe_float(source_signal.get("elapsed_seconds") if source_signal else None),
            3,
        ),
        "time_bucket": str(source_signal.get("time_bucket") if source_signal else ""),
        "mode": "dry_run" if DRY_RUN else "live",
        "dry_run": DRY_RUN,
        "candidate_stage": candidate_stage,
        "candidate_action": candidate_action,
        "side": signal_side,
        "outcome_bought": "YES" if signal_side == "UP" else "DOWN",
        "token_id": token_id,
        "amount_usd": round(amount_usd, 8),
        "order_type": str(
            source_signal.get("order_type") if source_signal else TAKER_ORDER_TYPE
        ),
        "exec_price_mode": str(
            source_signal.get("exec_price_mode") if source_signal else EXEC_PRICE_MODE
        ),
        "is_extension_order": bool(
            source_signal.get("is_extension_order") if source_signal else False
        ),
        "signal_model": (
            str(source_signal.get("signal_model", SIGNAL_MODEL_NAME))
            if source_signal
            else SIGNAL_MODEL_NAME
        ),
        "signal_fair": round(
            safe_float(source_signal.get("fair") if source_signal else None), 8
        ),
        "signal_edge": round(
            safe_float(source_signal.get("diff") if source_signal else None), 8
        ),
        "signal_edge_reference": (
            str(source_signal.get("edge_reference") if source_signal else "")
        ),
        "signal_reference_price": round(
            safe_float(source_signal.get("reference_price") if source_signal else None),
            8,
        ),
        "signal_bid": round(
            safe_float(source_signal.get("bid") if source_signal else None), 8
        ),
        "signal_ask": round(
            safe_float(source_signal.get("ask") if source_signal else None), 8
        ),
        "signal_spread": round(
            safe_float(source_signal.get("spread") if source_signal else None), 8
        ),
        "signal_open_anchor_mode": (
            str(source_signal.get("open_anchor_mode") if source_signal else "")
        ),
        "signal_open_anchor_weight": round(
            safe_float(
                source_signal.get("open_anchor_weight") if source_signal else None
            ),
            8,
        ),
        "signal_open_anchor_price": round(
            safe_float(
                source_signal.get("open_anchor_price") if source_signal else None
            ),
            8,
        ),
        "signal_pm_open_price": round(
            safe_float(source_signal.get("pm_open_price") if source_signal else None),
            8,
        ),
        "signal_bn_open_price": round(
            safe_float(source_signal.get("bn_open_price") if source_signal else None),
            8,
        ),
        "bn_price": round(
            safe_float(source_signal.get("bn_price") if source_signal else None), 8
        ),
        "bn_open_price": round(
            safe_float(source_signal.get("bn_open_price") if source_signal else None),
            8,
        ),
        "sigma": round(
            safe_float(source_signal.get("sigma") if source_signal else None), 12
        ),
        "sigma_short": round(
            safe_float(source_signal.get("sigma_short") if source_signal else None), 12
        ),
        "sigma_long": round(
            safe_float(source_signal.get("sigma_long") if source_signal else None), 12
        ),
        "sigma_eff": round(
            safe_float(source_signal.get("sigma_eff") if source_signal else None), 12
        ),
        "tau_seconds": round(
            safe_float(source_signal.get("tau_seconds") if source_signal else None), 6
        ),
        "z": round(safe_float(source_signal.get("z") if source_signal else None), 8),
        "limit_price": round(limit_price, 8),
        "order_price_hint": (
            round(safe_float(source_signal.get("order_price_hint")), 8)
            if source_signal and source_signal.get("order_price_hint") is not None
            else ""
        ),
        "signal_edge_after_fill_estimate": round(
            safe_float(
                source_signal.get("edge_after_fill_estimate")
                if source_signal
                else None
            ),
            8,
        ),
        "yes_cost": round(yes_cost, 8),
        "down_cost": round(down_cost, 8),
        "total_cost": round(total_cost, 8),
        "ml_filter_enabled": bool(ml_enabled),
        "ml_predicted_ev": (
            round(ml_predicted_ev, 8) if ml_predicted_ev is not None else ""
        ),
        "ml_min_ev": round(ml_min_ev, 8) if ml_min_ev is not None else "",
        "ml_passed": (
            source_signal.get("ml_passed")
            if source_signal and "ml_passed" in source_signal
            else ""
        ),
        "ml_reason": str(source_signal.get("ml_reason", "")) if source_signal else "",
        "ml_model_path": (
            str(source_signal.get("ml_model_path", "")) if source_signal else ""
        ),
        "ml_features_path": (
            str(source_signal.get("ml_features_path", "")) if source_signal else ""
        ),
        "ml_model_target": (
            str(source_signal.get("ml_model_target", "")) if source_signal else ""
        ),
        "ml_prediction_unit": (
            str(source_signal.get("ml_prediction_unit", "")) if source_signal else ""
        ),
        "ml_feature_names": (
            compact_json(source_signal.get("ml_feature_names"))
            if source_signal and source_signal.get("ml_feature_names")
            else ""
        ),
        "ml_feature_values_json": (
            compact_json(source_signal.get("ml_feature_values"))
            if source_signal and source_signal.get("ml_feature_values")
            else ""
        ),
        "fill_prob_filter_enabled": bool(fill_prob_enabled),
        "fill_probability": (
            round(fill_probability, 8) if fill_probability is not None else ""
        ),
        "fill_prob_min_probability": (
            round(fill_prob_min_probability, 8)
            if fill_prob_min_probability is not None
            else ""
        ),
        "fill_prob_passed": (
            source_signal.get("fill_prob_passed")
            if source_signal and "fill_prob_passed" in source_signal
            else ""
        ),
        "fill_prob_reason": (
            str(source_signal.get("fill_prob_reason", "")) if source_signal else ""
        ),
        "fill_prob_model_path": (
            str(source_signal.get("fill_prob_model_path", "")) if source_signal else ""
        ),
        "fill_prob_features_path": (
            str(source_signal.get("fill_prob_features_path", ""))
            if source_signal
            else ""
        ),
        "fill_prob_model_target": (
            str(source_signal.get("fill_prob_model_target", "")) if source_signal else ""
        ),
        "fill_prob_prediction_unit": (
            str(source_signal.get("fill_prob_prediction_unit", ""))
            if source_signal
            else ""
        ),
        "fill_prob_feature_names": (
            compact_json(source_signal.get("fill_prob_feature_names"))
            if source_signal and source_signal.get("fill_prob_feature_names")
            else ""
        ),
        "fill_prob_feature_values_json": (
            compact_json(source_signal.get("fill_prob_feature_values"))
            if source_signal and source_signal.get("fill_prob_feature_values")
            else ""
        ),
    }
    append_csv_row(RAW_CANDIDATES_CSV_PATH, row, RAW_CANDIDATES_FIELDNAMES)


def recent_settled_market_metrics(limit: int) -> Tuple[Optional[float], Optional[float]]:
    rows: List[Tuple[datetime, float, bool]] = []
    for ledger in market_ledgers.values():
        if not ledger.get("settled"):
            continue
        total_cost = safe_float(ledger.get("total_cost"), 0.0)
        if total_cost <= 0:
            continue
        net_pnl = safe_float(ledger.get("net_pnl_estimate"), 0.0)
        settled_dt = (
            parse_dt(ledger.get("settled_at"))
            or parse_dt(ledger.get("market_end_utc"))
            or datetime.min.replace(tzinfo=timezone.utc)
        )
        rows.append((settled_dt, net_pnl / total_cost, net_pnl > 0))

    if not rows:
        return None, None

    rows.sort(key=lambda item: item[0])
    selected = rows[-limit:]
    avg_roi = sum(item[1] for item in selected) / len(selected)
    win_rate = sum(1 for item in selected if item[2]) / len(selected)
    return avg_roi, win_rate


def evaluate_ml_filter_for_signal(
    *,
    signal_side: str,
    source_signal: Dict[str, Any],
    ledger: Dict[str, Any],
) -> Tuple[bool, str]:
    features = build_signal_filter_feature_values(
        signal_side=signal_side,
        source_signal=source_signal,
        ledger=ledger,
    )
    metadata = load_ml_feature_metadata()
    feature_names = get_ml_feature_names_for_logging()
    source_signal["ml_model_path"] = str(ML_FILTER_MODEL_PATH)
    source_signal["ml_features_path"] = str(ML_FILTER_FEATURES_PATH)
    source_signal["ml_model_target"] = str(metadata.get("target", ""))
    source_signal["ml_prediction_unit"] = str(metadata.get("prediction_unit", ""))
    source_signal["ml_feature_names"] = feature_names
    source_signal["ml_feature_values"] = {
        name: features.get(name) for name in feature_names
    }
    decision = ml_signal_filter.evaluate(features)
    source_signal["ml_filter_enabled"] = decision.enabled
    source_signal["ml_predicted_ev"] = decision.predicted_ev
    source_signal["ml_min_ev"] = decision.min_ev
    source_signal["ml_passed"] = decision.passed
    source_signal["ml_reason"] = decision.reason
    return decision.passed, decision.reason


def evaluate_fill_probability_filter_for_signal(
    *,
    signal_side: str,
    source_signal: Dict[str, Any],
    ledger: Dict[str, Any],
    amount_usd: float,
) -> Tuple[bool, str]:
    features = build_signal_filter_feature_values(
        signal_side=signal_side,
        source_signal=source_signal,
        ledger=ledger,
    )
    add_live_candidate_extra_features(
        features,
        source_signal=source_signal,
        amount_usd=amount_usd,
    )
    metadata = load_fill_prob_feature_metadata()
    feature_names = get_fill_prob_feature_names_for_logging()
    source_signal["fill_prob_model_path"] = str(FILL_PROB_MODEL_PATH)
    source_signal["fill_prob_features_path"] = str(FILL_PROB_FEATURES_PATH)
    source_signal["fill_prob_model_target"] = metadata_nested_value(
        metadata,
        "targets",
        "fill_probability",
    )
    source_signal["fill_prob_prediction_unit"] = metadata_nested_value(
        metadata,
        "prediction_units",
        "score_fill_probability",
    )
    source_signal["fill_prob_feature_names"] = feature_names
    source_signal["fill_prob_feature_values"] = {
        name: features.get(name) for name in feature_names
    }
    decision = fill_probability_filter.evaluate(features)
    source_signal["fill_prob_filter_enabled"] = decision.enabled
    source_signal["fill_probability"] = decision.predicted_ev
    source_signal["fill_prob_min_probability"] = decision.min_ev
    source_signal["fill_prob_passed"] = decision.passed
    source_signal["fill_prob_reason"] = decision.reason
    return decision.passed, decision.reason


def record_signal_rejection(
    *,
    rejection_stage: str,
    rejection_reason: str,
    signal_side: str,
    amount_usd: float,
    source_signal: Optional[Dict[str, Any]],
) -> None:
    ledger = ensure_market_ledger()
    if ledger is None:
        return

    yes_cost = safe_float(ledger.get("yes_cost"), 0.0)
    down_cost = safe_float(ledger.get("down_cost"), 0.0)
    total_cost = safe_float(ledger.get("total_cost"), 0.0)
    side_cost = yes_cost if signal_side == "UP" else down_cost

    row = {
        "recorded_at": now_iso(),
        "market_slug": ledger["market_slug"],
        "market_question": ledger["market_question"],
        "market_start_utc": ledger["market_start_utc"],
        "market_end_utc": ledger["market_end_utc"],
        "mode": "dry_run" if DRY_RUN else "live_estimated",
        "rejection_stage": rejection_stage,
        "rejection_reason": rejection_reason,
        "side": signal_side,
        "outcome_bought": "YES" if signal_side == "UP" else "DOWN",
        "amount_usd": round(amount_usd, 8),
        "signal_model": (
            str(source_signal.get("signal_model", SIGNAL_MODEL_NAME))
            if source_signal
            else SIGNAL_MODEL_NAME
        ),
        "signal_fair": round(
            safe_float(source_signal.get("fair") if source_signal else None), 8
        ),
        "signal_edge": round(
            safe_float(source_signal.get("diff") if source_signal else None), 8
        ),
        "signal_edge_reference": (
            str(source_signal.get("edge_reference") if source_signal else "")
        ),
        "signal_reference_price": round(
            safe_float(source_signal.get("reference_price") if source_signal else None),
            8,
        ),
        "signal_bid": round(
            safe_float(source_signal.get("bid") if source_signal else None), 8
        ),
        "signal_ask": round(
            safe_float(source_signal.get("ask") if source_signal else None), 8
        ),
        "signal_spread": round(
            safe_float(source_signal.get("spread") if source_signal else None), 8
        ),
        "signal_order_type": (
            str(source_signal.get("order_type") if source_signal else TAKER_ORDER_TYPE)
        ),
        "signal_exec_price_mode": (
            str(source_signal.get("exec_price_mode") if source_signal else "")
        ),
        "signal_max_execution_price": round(
            safe_float(
                source_signal.get("max_execution_price") if source_signal else None
            ),
            8,
        ),
        "signal_edge_after_fill_estimate": round(
            safe_float(
                source_signal.get("edge_after_fill_estimate")
                if source_signal
                else None
            ),
            8,
        ),
        "signal_open_anchor_mode": (
            str(source_signal.get("open_anchor_mode") if source_signal else "")
        ),
        "signal_open_anchor_weight": round(
            safe_float(
                source_signal.get("open_anchor_weight") if source_signal else None
            ),
            8,
        ),
        "signal_open_anchor_price": round(
            safe_float(
                source_signal.get("open_anchor_price") if source_signal else None
            ),
            8,
        ),
        "signal_pm_open_price": round(
            safe_float(source_signal.get("pm_open_price") if source_signal else None),
            8,
        ),
        "signal_bn_open_price": round(
            safe_float(source_signal.get("bn_open_price") if source_signal else None),
            8,
        ),
        "bn_price": round(
            safe_float(source_signal.get("bn_price") if source_signal else None), 8
        ),
        "bn_open_price": round(
            safe_float(source_signal.get("bn_open_price") if source_signal else None),
            8,
        ),
        "sigma": round(
            safe_float(source_signal.get("sigma") if source_signal else None), 12
        ),
        "sigma_short": round(
            safe_float(source_signal.get("sigma_short") if source_signal else None), 12
        ),
        "sigma_long": round(
            safe_float(source_signal.get("sigma_long") if source_signal else None), 12
        ),
        "sigma_eff": round(
            safe_float(source_signal.get("sigma_eff") if source_signal else None), 12
        ),
        "tau_seconds": round(
            safe_float(source_signal.get("tau_seconds") if source_signal else None), 6
        ),
        "z": round(safe_float(source_signal.get("z") if source_signal else None), 8),
        "yes_cost": round(yes_cost, 8),
        "down_cost": round(down_cost, 8),
        "total_cost": round(total_cost, 8),
        "is_extension_zone": bool(
            MARKET_MAX_SIDE_COST > 0 and side_cost >= MARKET_MAX_SIDE_COST
        ),
    }
    append_csv_row(
        SIGNAL_REJECTIONS_CSV_PATH,
        row,
        SIGNAL_REJECTIONS_FIELDNAMES,
    )


def get_resolution_price_proxy(end_dt: Optional[datetime]) -> Optional[float]:
    """
    用系統內部 BN 一秒抽樣近似結算價：
    - 優先取最後一筆 <= end_dt 的價格
    - 若沒有，取最接近 end_dt 的價格
    - 再沒有就 fallback 到 bn_last_price
    """
    global bn_last_price

    if end_dt is None:
        return safe_float(bn_last_price, 0.0) or None

    end_ts = int(end_dt.timestamp())

    if bn_second_prices:
        before_or_equal = [
            (sec, price) for sec, price in bn_second_prices if sec <= end_ts
        ]
        if before_or_equal:
            sec, price = max(before_or_equal, key=lambda x: x[0])
            return float(price)

        nearest = min(bn_second_prices, key=lambda x: abs(x[0] - end_ts))
        return float(nearest[1])

    if bn_last_price is not None:
        return float(bn_last_price)

    return None


def finalize_market_settlement(
    *,
    ledger: Dict[str, Any],
    resolution_price: float,
    resolution_price_source: str,
    settlement_reason: str,
    bn_resolution_price_fallback: Optional[float] = None,
) -> bool:
    global session_net_pnl_total

    open_price, open_price_source = resolve_effective_open_price(
        ledger.get("pm_open_price"), ledger.get("bn_open_price")
    )

    if ledger["settled"]:
        return False
    if open_price <= 0 or resolution_price <= 0:
        print(f"⚠️ 無法結算市場 {ledger['market_slug']}：缺少 open/resolution 價格")
        return False

    # 依 Polymarket BTC Up/Down 規則做內部粗估：end >= open 視為 UP，否則 DOWN
    resolved_side = "UP" if resolution_price >= open_price else "DOWN"

    yes_shares = safe_float(ledger["yes_shares"])
    down_shares = safe_float(ledger["down_shares"])
    total_cost = safe_float(ledger["total_cost"])
    fee_total = safe_float(ledger["estimated_fee_total"])

    gross_payout = yes_shares if resolved_side == "UP" else down_shares
    net_pnl_estimate = gross_payout - total_cost - fee_total

    ledger["settled"] = True
    ledger["resolved_side"] = resolved_side
    ledger["resolution_price"] = resolution_price
    ledger["resolution_price_source"] = resolution_price_source
    ledger["bn_resolution_price_fallback"] = bn_resolution_price_fallback
    ledger["settlement_reason"] = settlement_reason
    ledger["settled_at"] = now_iso()
    ledger["effective_open_price"] = open_price
    ledger["open_price_source"] = open_price_source
    ledger["gross_payout_estimate"] = gross_payout
    ledger["net_pnl_estimate"] = net_pnl_estimate
    session_net_pnl_total += net_pnl_estimate
    process_tail_reversal_settlement(ledger)

    settlement_row = {
        "settled_at": ledger["settled_at"],
        "market_slug": ledger["market_slug"],
        "market_question": ledger["market_question"],
        "market_start_utc": ledger["market_start_utc"],
        "market_end_utc": ledger["market_end_utc"],
        "open_price": round(open_price, 8),
        "open_price_source": open_price_source,
        "resolution_price": round(resolution_price, 8),
        "resolution_price_source": resolution_price_source,
        "bn_resolution_price_fallback": (
            round(bn_resolution_price_fallback, 8)
            if safe_float(bn_resolution_price_fallback, 0.0) > 0
            else ""
        ),
        "resolved_side": resolved_side,
        "yes_fee_rate_bps": ledger.get("yes_fee_rate_bps", 0),
        "down_fee_rate_bps": ledger.get("down_fee_rate_bps", 0),
        "fees_enabled": ledger.get("fees_enabled", False),
        "settlement_reason": settlement_reason,
        "yes_orders": ledger["yes_orders"],
        "down_orders": ledger["down_orders"],
        "yes_shares": round(yes_shares, 8),
        "down_shares": round(down_shares, 8),
        "yes_cost": round(safe_float(ledger["yes_cost"]), 8),
        "down_cost": round(safe_float(ledger["down_cost"]), 8),
        "total_cost": round(total_cost, 8),
        "estimated_fee_total": round(fee_total, 8),
        "gross_payout_estimate": round(gross_payout, 8),
        "net_pnl_estimate": round(net_pnl_estimate, 8),
        "pnl_if_up_estimate": round(safe_float(ledger["pnl_if_up_estimate"]), 8),
        "pnl_if_down_estimate": round(safe_float(ledger["pnl_if_down_estimate"]), 8),
        "mode_observed": ledger["mode_observed"],
    }
    append_csv_row(
        MARKET_SETTLEMENTS_CSV_PATH,
        settlement_row,
        MARKET_SETTLEMENTS_FIELDNAMES,
    )
    persist_market_state_json()
    win_loss_stats = compute_settlement_win_loss_stats()

    print(
        f"🏁 市場結算(內部估算) | {ledger['market_slug']} | "
        f"resolved={resolved_side} | open={open_price:.2f}({open_price_source}) | "
        f"resolution={resolution_price:.2f}({resolution_price_source}) | "
        f"fees={fee_total:.5f} | net_pnl_est={net_pnl_estimate:+.4f} | "
        f"session_net_pnl_total={session_net_pnl_total:+.4f}"
    )
    print(
        f"📊 勝率統計 | win_rate={win_loss_stats['win_rate_pct']:.2f}% | "
        f"wins={win_loss_stats['win_count']} | "
        f"losses={win_loss_stats['loss_count']} | "
        f"skipped={win_loss_stats['skipped_count']} | "
        f"settled={win_loss_stats['settled_count']} | "
        f"up_markets={win_loss_stats['up_market_count']} | "
        f"down_markets={win_loss_stats['down_market_count']} | "
        f"avg_amount_per_market={win_loss_stats['avg_amount_per_market']:.2f} | "
        f"avg_win_pnl={win_loss_stats['avg_win_pnl']:+.2f} | "
        f"avg_loss_pnl={win_loss_stats['avg_loss_pnl']:+.2f}"
    )
    return True


def mark_current_market_pending_settlement(reason: str) -> None:
    global pending_settlement

    ledger = ensure_market_ledger()
    if ledger is None or ledger["settled"]:
        return

    if pending_settlement is not None:
        existing_slug = pending_settlement.get("market_slug")
        if existing_slug == ledger["market_slug"]:
            pending_settlement["pending_reason"] = reason
            persist_market_state_json()
            return

        print(
            f"⚠️ 待結算市場 {existing_slug} 尚未完成，改用 BN fallback 避免被覆蓋"
        )
        fallback_pending_settlement("pending_overrun_bn_fallback")

    pending_settlement = {
        "market_slug": ledger["market_slug"],
        "market_end_utc": ledger["market_end_utc"],
        "expected_resolution_market_start_utc": ledger["market_end_utc"],
        "pending_reason": reason,
        "marked_at": now_iso(),
    }
    persist_market_state_json()
    print(
        f"🕓 市場待結算 | {ledger['market_slug']} | "
        f"等待下一盤 PM open 作為結算價"
    )


def finalize_pending_settlement(
    *,
    resolution_price: float,
    resolution_price_source: str,
    settlement_reason: str,
    bn_resolution_price_fallback: Optional[float] = None,
) -> bool:
    global pending_settlement

    if pending_settlement is None:
        return False

    pending_slug = str(pending_settlement.get("market_slug", ""))
    ledger = market_ledgers.get(pending_slug)
    if ledger is None:
        print(f"⚠️ 找不到待結算市場帳本，清除 pending 狀態: {pending_slug}")
        pending_settlement = None
        persist_market_state_json()
        return False

    ok = finalize_market_settlement(
        ledger=ledger,
        resolution_price=resolution_price,
        resolution_price_source=resolution_price_source,
        settlement_reason=settlement_reason,
        bn_resolution_price_fallback=bn_resolution_price_fallback,
    )
    if ok:
        pending_settlement = None
        persist_market_state_json()
    return ok


def fallback_pending_settlement(reason: str) -> bool:
    if pending_settlement is None:
        return False

    pending_slug = str(pending_settlement.get("market_slug", ""))
    ledger = market_ledgers.get(pending_slug)
    if ledger is None:
        return False

    market_end_dt = parse_dt(ledger.get("market_end_utc"))
    resolution_price = get_resolution_price_proxy(market_end_dt)
    if resolution_price is None or resolution_price <= 0:
        print(f"⚠️ 無法對待結算市場做 BN fallback：{pending_slug}")
        return False

    print(
        f"⚠️ 待結算市場改用 BN fallback | {pending_slug} | "
        f"resolution={resolution_price:,.2f}"
    )
    return finalize_pending_settlement(
        resolution_price=resolution_price,
        resolution_price_source="bn_fallback",
        settlement_reason=reason,
        bn_resolution_price_fallback=resolution_price,
    )


def attempt_finalize_pending_settlement_from_current_pm_open() -> bool:
    if pending_settlement is None:
        return False
    if pm_bucket_open_price is None or safe_float(pm_bucket_open_price, 0.0) <= 0:
        return False
    if current_market_start_dt is None:
        return False

    expected_start_dt = parse_dt(
        pending_settlement.get("expected_resolution_market_start_utc")
    )
    if expected_start_dt is None:
        print("⚠️ 待結算狀態缺少 expected start，改用 BN fallback")
        return fallback_pending_settlement("pending_invalid_state_bn_fallback")

    if current_market_start_dt == expected_start_dt:
        return finalize_pending_settlement(
            resolution_price=float(pm_bucket_open_price),
            resolution_price_source="next_pm_open",
            settlement_reason=str(
                pending_settlement.get("pending_reason", "next_pm_open_settlement")
            ),
        )

    if current_market_start_dt > expected_start_dt:
        print("⚠️ 已錯過上一盤對應的下一盤 PM open，改用 BN fallback")
        return fallback_pending_settlement("missed_next_pm_open_bn_fallback")

    return False


def settle_current_market(reason: str) -> None:
    mark_current_market_pending_settlement(reason)


# ====================== CLOB Client 初始化 ======================
def init_polymarket_client():
    global client, condition_id, tick_size, neg_risk
    global pm_yes_token, pm_no_token
    global current_market_slug, current_market_question, current_market_start_dt, current_market_end_dt

    if not PRIVATE_KEY or not FUNDER_ADDRESS:
        raise ValueError("請在 .env 設定 PRIVATE_KEY 和 FUNDER_ADDRESS")

    clob_client = create_clob_client_instance(
        key=PRIVATE_KEY,
        funder=FUNDER_ADDRESS,
        read_only=False,
    )

    api_creds = create_or_derive_api_credentials(clob_client)
    clob_client.set_api_creds(api_creds)

    market_data = get_current_live_market()
    if not market_data:
        raise ValueError(f"無法取得目前 live 的 {MARKET_LABEL} 市場")
    market_data = apply_clob_market_info_overrides(market_data, target_client=clob_client)

    pm_yes_token = market_data["up_token_id"]
    pm_no_token = market_data["down_token_id"]

    condition_id = market_data["conditionId"]
    tick_size = str(market_data.get("tick_size") or "0.01")
    neg_risk = bool(market_data.get("neg_risk", False))

    current_market_slug = market_data["slug"]
    current_market_question = market_data["question"]
    current_market_start_dt = market_data["start_dt"]
    current_market_end_dt = market_data["end_dt"]

    reset_runtime_state()
    initialize_pm_bucket_open_price()
    initialize_bn_bucket_open_price()
    refresh_current_fee_rates()
    ensure_market_ledger()
    persist_market_state_json()
    start_pm_open_price_retry_task()

    print("✅ Polymarket Client 初始化完成")
    print(f"   Market : {current_market_question}")
    print(f"   Slug   : {current_market_slug}")
    print(f"   Window : {current_market_start_dt} -> {current_market_end_dt}")
    print(f"   UP Token   : {pm_yes_token[:12]}...")
    print(f"   DOWN Token : {pm_no_token[:12]}...")
    print(f"   Tick Size  : {tick_size} | Neg Risk: {neg_risk}")
    print(f"   DRY_RUN    : {DRY_RUN}")
    print(f"   CLOB Host  : {CLOB_HOST}")
    print(f"   Sig Type   : {POLY_SIGNATURE_TYPE}")
    print(f"   BuilderCode: {POLY_BUILDER_CODE or '(none)'}")
    print(
        f"   Fee rules  : yes_bps={current_yes_fee_rate_bps} | "
        f"down_bps={current_down_fee_rate_bps} | enabled={current_fees_enabled} | "
        f"source={current_fee_rules_source}"
    )
    print(f"   Strategy open(PM) : {format_optional_price(pm_bucket_open_price)}")
    print(f"   Ledger open(BN fb): {format_optional_price(bn_bucket_open_price)}")
    print(f"   CA bundle  : {CA_BUNDLE}")
    print(f"   LEDGER_DIR : {LEDGER_DIR.resolve()}")

    return clob_client


async def refresh_live_market(force: bool = False) -> bool:
    global condition_id, tick_size, neg_risk
    global pm_yes_token, pm_no_token
    global current_market_slug, current_market_question, current_market_start_dt, current_market_end_dt

    now = utcnow()
    if not force and current_market_end_dt and now < current_market_end_dt:
        return False

    if current_market_slug and current_market_end_dt and now >= current_market_end_dt:
        mark_current_market_pending_settlement("refresh_before_switch")

    market_data = await asyncio.to_thread(get_current_live_market)
    if not market_data:
        return False
    market_data = apply_clob_market_info_overrides(market_data, target_client=client)

    new_slug = market_data["slug"]
    if not force and new_slug == current_market_slug:
        return False

    pm_yes_token = market_data["up_token_id"]
    pm_no_token = market_data["down_token_id"]

    condition_id = market_data["conditionId"]
    tick_size = str(market_data.get("tick_size") or "0.01")
    neg_risk = bool(market_data.get("neg_risk", False))

    current_market_slug = market_data["slug"]
    current_market_question = market_data["question"]
    current_market_start_dt = market_data["start_dt"]
    current_market_end_dt = market_data["end_dt"]

    reset_runtime_state()
    initialize_pm_bucket_open_price()
    initialize_bn_bucket_open_price()
    refresh_current_fee_rates()
    ensure_market_ledger()
    persist_market_state_json()
    start_pm_open_price_retry_task()

    print(f"🔁 已切換到新的 live {MARKET_LABEL} 市場")
    print(f"   Market : {current_market_question}")
    print(f"   Slug   : {current_market_slug}")
    print(f"   Window : {current_market_start_dt} -> {current_market_end_dt}")
    print(f"   UP Token   : {pm_yes_token[:12]}...")
    print(f"   DOWN Token : {pm_no_token[:12]}...")
    print(f"   Strategy open(PM) : {format_optional_price(pm_bucket_open_price)}")
    print(f"   Ledger open(BN fb): {format_optional_price(bn_bucket_open_price)}")

    return True


# ====================== Signal Layer ======================
def build_trade_signals() -> List[Dict[str, Any]]:
    if (
        pm_yes_best_bid is None
        or pm_yes_best_ask is None
        or pm_no_best_bid is None
        or pm_no_best_ask is None
    ):
        return []

    fair = compute_fair_yes_from_bn()
    if fair is None:
        return []

    fair_yes = fair["fair_yes"]
    fair_no = fair["fair_no"]

    yes_bid = safe_float(pm_yes_best_bid, default=-1)
    yes_ask = safe_float(pm_yes_best_ask, default=-1)
    no_bid = safe_float(pm_no_best_bid, default=-1)
    no_ask = safe_float(pm_no_best_ask, default=-1)

    if yes_bid <= 0 or yes_ask <= 0 or no_bid <= 0 or no_ask <= 0:
        return []

    yes_spread = get_spread(yes_bid, yes_ask)
    no_spread = get_spread(no_bid, no_ask)

    update_tail_reversal_markers(
        fair=fair,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        down_bid=no_bid,
        down_ask=no_ask,
    )

    signals: List[Dict[str, Any]] = []
    elapsed_seconds, current_time_bucket, _ = get_current_time_bucket_context()
    remaining_seconds = get_bucket_remaining_seconds()
    time_bucket_label = (
        format_time_bucket(current_time_bucket)
        if current_time_bucket is not None
        else ""
    )
    time_bucket_allowed = (
        not ENTRY_TIME_BUCKETS_ENABLED
        or (
            current_time_bucket is not None
            and current_time_bucket in ENTRY_TIME_BUCKETS
        )
    )

    if (
        yes_spread is not None
        and yes_spread <= MAX_SPREAD
        and yes_ask >= MIN_ENTRY_ASK_PRICE
    ):
        yes_edge_reference, yes_reference_price = get_edge_reference_price(
            bid=yes_bid,
            ask=yes_ask,
        )
        edge_yes = fair_yes - yes_reference_price
        if edge_yes > EDGE_PROB_THRESHOLD:
            execution_plan = compute_execution_plan(fair=fair_yes, ask=yes_ask)
            if execution_plan is not None:
                signals.append(
                    {
                        "side": "UP",
                        "signal_model": fair["signal_model"],
                        "token_id": pm_yes_token,
                        "outcome": "YES",
                        "ask": yes_ask,
                        "bid": yes_bid,
                        "edge_reference": yes_edge_reference,
                        "reference_price": yes_reference_price,
                        "spread": yes_spread,
                        "fair": fair_yes,
                        "diff": edge_yes,
                        "bn_price": fair["p_now"],
                        "open_price": fair["p_open"],
                        "open_anchor_mode": fair["open_anchor_mode"],
                        "open_anchor_weight": fair["open_anchor_weight"],
                        "open_anchor_price": fair["open_anchor_price"],
                        "pm_open_price": fair["pm_open_price"],
                        "bn_open_price": fair["bn_open_price"],
                        "order_type": execution_plan["order_type"],
                        "exec_price_mode": execution_plan["exec_price_mode"],
                        "max_execution_price": execution_plan["max_execution_price"],
                        "order_price_hint": execution_plan["order_price_hint"],
                        "edge_after_fill_estimate": execution_plan[
                            "edge_after_fill_estimate"
                        ],
                        "sigma": fair["sigma"],
                        "sigma_short": fair["sigma_short"],
                        "sigma_long": fair["sigma_long"],
                        "sigma_eff": fair["sigma_eff"],
                        "tau_seconds": fair["tau_seconds"],
                        "z": fair["z"],
                        "market_slug": current_market_slug,
                        "remaining_seconds": round(remaining_seconds, 3)
                        if remaining_seconds is not None
                        else None,
                        "elapsed_seconds": round(elapsed_seconds, 3)
                        if elapsed_seconds is not None
                        else None,
                        "time_bucket": time_bucket_label,
                        "time_bucket_allowed": time_bucket_allowed,
                    }
                )

    if (
        no_spread is not None
        and no_spread <= MAX_SPREAD
        and no_ask >= MIN_ENTRY_ASK_PRICE
    ):
        no_edge_reference, no_reference_price = get_edge_reference_price(
            bid=no_bid,
            ask=no_ask,
        )
        edge_no = fair_no - no_reference_price
        if edge_no > EDGE_PROB_THRESHOLD:
            execution_plan = compute_execution_plan(fair=fair_no, ask=no_ask)
            if execution_plan is not None:
                signals.append(
                    {
                        "side": "DOWN",
                        "signal_model": fair["signal_model"],
                        "token_id": pm_no_token,
                        "outcome": "DOWN",
                        "ask": no_ask,
                        "bid": no_bid,
                        "edge_reference": no_edge_reference,
                        "reference_price": no_reference_price,
                        "spread": no_spread,
                        "fair": fair_no,
                        "diff": edge_no,
                        "bn_price": fair["p_now"],
                        "open_price": fair["p_open"],
                        "open_anchor_mode": fair["open_anchor_mode"],
                        "open_anchor_weight": fair["open_anchor_weight"],
                        "open_anchor_price": fair["open_anchor_price"],
                        "pm_open_price": fair["pm_open_price"],
                        "bn_open_price": fair["bn_open_price"],
                        "order_type": execution_plan["order_type"],
                        "exec_price_mode": execution_plan["exec_price_mode"],
                        "max_execution_price": execution_plan["max_execution_price"],
                        "order_price_hint": execution_plan["order_price_hint"],
                        "edge_after_fill_estimate": execution_plan[
                            "edge_after_fill_estimate"
                        ],
                        "sigma": fair["sigma"],
                        "sigma_short": fair["sigma_short"],
                        "sigma_long": fair["sigma_long"],
                        "sigma_eff": fair["sigma_eff"],
                        "tau_seconds": fair["tau_seconds"],
                        "z": fair["z"],
                        "market_slug": current_market_slug,
                        "remaining_seconds": round(remaining_seconds, 3)
                        if remaining_seconds is not None
                        else None,
                        "elapsed_seconds": round(elapsed_seconds, 3)
                        if elapsed_seconds is not None
                        else None,
                        "time_bucket": time_bucket_label,
                        "time_bucket_allowed": time_bucket_allowed,
                    }
                )

    return signals


def log_signal(signal: Dict[str, Any]) -> None:
    outcome = signal["outcome"]
    edge_reference = str(signal.get("edge_reference", EDGE_REFERENCE_PRICE))
    reference_price = safe_float(
        signal.get("reference_price"),
        safe_float(signal.get(edge_reference), 0.0),
    )
    elapsed_seconds = signal.get("elapsed_seconds")
    elapsed_label = (
        f"{safe_float(elapsed_seconds, 0.0):.1f}s"
        if elapsed_seconds is not None
        else "n/a"
    )
    order_price_hint = signal.get("order_price_hint")
    order_price_hint_label = (
        f"{safe_float(order_price_hint, 0.0):.3f}"
        if order_price_hint is not None
        else "none"
    )
    print(
        f"✅ 有利買 {outcome}: 買價={signal['fair']:.3f} "
        f"vs 當前 {outcome} {edge_reference}={reference_price:.3f} "
        f"（差={signal['diff']:+.3f}） | "
        f"bid={signal['bid']:.3f} | "
        f"ask={signal['ask']:.3f} | spread={signal['spread']:.3f}"
    )
    print(
        f"   BN now={signal['bn_price']:.2f} | "
        f"anchor({signal.get('open_anchor_mode', OPEN_ANCHOR_MODE)})="
        f"{safe_float(signal.get('open_anchor_price'), 0.0):.2f} | "
        f"PM open={format_optional_price(signal.get('pm_open_price'))} | "
        f"BN open={format_optional_price(signal.get('bn_open_price'))} | "
        f"order_type={signal.get('order_type', TAKER_ORDER_TYPE)} | "
        f"exec_mode={signal.get('exec_price_mode', EXEC_PRICE_MODE)} | "
        f"max_price={safe_float(signal.get('max_execution_price'), 0.0):.3f} | "
        f"price_hint={order_price_hint_label} | "
        f"edge_after_fill={safe_float(signal.get('edge_after_fill_estimate'), 0.0):+.3f} | "
        f"model={signal.get('signal_model', SIGNAL_MODEL_NAME)} | "
        f"sigma_s={signal['sigma_short']:.6f} | "
        f"sigma_l={signal['sigma_long']:.6f} | "
        f"sigma_eff={signal['sigma_eff']:.6f} | "
        f"tau={signal['tau_seconds']:.1f}s | z={signal['z']:.3f} | "
        f"anchor_w={safe_float(signal.get('open_anchor_weight'), 0.0):.2f} | "
        f"elapsed={elapsed_label} | "
        f"bucket={signal.get('time_bucket') or 'n/a'}"
    )


def emit_signal(signal: Dict[str, Any]) -> None:
    side = signal["side"]

    time_allowed, reject_reason, elapsed_seconds, bucket_label = evaluate_entry_time_bucket_gate()
    signal["elapsed_seconds"] = (
        round(elapsed_seconds, 3) if elapsed_seconds is not None else None
    )
    signal["time_bucket"] = bucket_label
    signal["time_bucket_allowed"] = time_allowed
    if not time_allowed:
        gate_stage, _, gate_label = classify_entry_time_gate_rejection(reject_reason)
        if can_log_entry_time_gate_rejection(side, gate_stage):
            print(
                f"🕒 {gate_label} 阻擋訊號 | side={side} | "
                f"bucket={bucket_label} | market={current_market_slug} | "
                f"reason={reject_reason}"
            )
            record_signal_rejection(
                rejection_stage=gate_stage,
                rejection_reason=reject_reason,
                signal_side=side,
                amount_usd=TRADE_AMOUNT_USD,
                source_signal=signal,
            )
        return

    if not can_emit_signal(side):
        return

    cooldown_active, cooldown_remaining = get_tail_reversal_cooldown_status()
    if cooldown_active:
        until_text = (
            tail_reversal_cooldown_until.isoformat()
            if tail_reversal_cooldown_until is not None
            else ""
        )
        rejection_reason = (
            "tail_reversal_cooldown_active | "
            f"remaining={cooldown_remaining:.1f}s | "
            f"until={until_text} | "
            f"recent_hits={get_tail_reversal_recent_hit_count()}"
        )
        print(
            f"🧊 Tail reversal cooldown 阻擋訊號 | side={side} | "
            f"remaining={cooldown_remaining:.1f}s | market={current_market_slug}"
        )
        record_signal_rejection(
            rejection_stage="tail_reversal_cooldown",
            rejection_reason=rejection_reason,
            signal_side=side,
            amount_usd=TRADE_AMOUNT_USD,
            source_signal=signal,
        )
        return

    log_signal(signal)
    asyncio.create_task(execute_signal(signal))


async def execute_signal(signal: Dict[str, Any]) -> None:
    await place_taker_order(
        token_id=signal["token_id"],
        side=BUY,
        signal_side=signal["side"],
        source_signal=signal,
    )


def evaluate_and_dispatch_signals() -> None:
    signals = build_trade_signals()
    if not signals:
        return

    for signal in signals:
        emit_signal(signal)


# ====================== Order Layer ======================
async def place_taker_order(
    token_id: str,
    side: str,
    signal_side: str,
    source_signal: Optional[Dict[str, Any]] = None,
):
    global last_order_time

    async with order_lock:
        now = time.time()

        cooldown_active, cooldown_remaining = get_tail_reversal_cooldown_status()
        if cooldown_active:
            print(
                f"🧊 Tail reversal cooldown 中，略過下單 | side={signal_side} | "
                f"remaining={cooldown_remaining:.1f}s | market={current_market_slug}"
            )
            record_execution_attempt(
                status="blocked_tail_reversal_cooldown",
                attempt_stage="tail_reversal_cooldown",
                signal_side=signal_side,
                token_id=token_id,
                amount_usd=TRADE_AMOUNT_USD,
                source_signal=source_signal,
                failed_reason=f"tail_reversal_cooldown:{cooldown_remaining:.3f}s",
            )
            return

        time_allowed, reject_reason, elapsed_seconds, bucket_label = evaluate_entry_time_bucket_gate()
        if source_signal is not None:
            source_signal["elapsed_seconds"] = (
                round(elapsed_seconds, 3) if elapsed_seconds is not None else None
            )
            source_signal["time_bucket"] = bucket_label
            source_signal["time_bucket_allowed"] = time_allowed
        if not time_allowed:
            gate_stage, blocked_status, gate_label = classify_entry_time_gate_rejection(
                reject_reason
            )
            print(
                f"🕒 {gate_label} 阻擋下單 | side={signal_side} | "
                f"bucket={bucket_label} | market={current_market_slug} | "
                f"reason={reject_reason}"
            )
            record_execution_attempt(
                status=blocked_status,
                attempt_stage=gate_stage,
                signal_side=signal_side,
                token_id=token_id,
                amount_usd=TRADE_AMOUNT_USD,
                source_signal=source_signal,
                failed_reason=reject_reason,
            )
            record_signal_rejection(
                rejection_stage=gate_stage,
                rejection_reason=reject_reason,
                signal_side=signal_side,
                amount_usd=TRADE_AMOUNT_USD,
                source_signal=source_signal,
            )
            return

        if now - last_order_time < COOLDOWN_SECONDS:
            remain = COOLDOWN_SECONDS - (now - last_order_time)
            print(
                f"⏳ 訂單冷卻中... side={signal_side} | "
                f"距離下次可下單還有 {remain:.1f} 秒"
            )
            record_execution_attempt(
                status="blocked_order_cooldown",
                attempt_stage="order_cooldown",
                signal_side=signal_side,
                token_id=token_id,
                amount_usd=TRADE_AMOUNT_USD,
                source_signal=source_signal,
                failed_reason=f"order_cooldown:{remain:.3f}s",
            )
            return

        allowed, reject_reason, is_extension_order = check_market_exposure_limits(
            signal_side,
            source_signal=source_signal,
        )
        if not allowed:
            print(f"🛑 市場暴露上限阻擋下單 | {reject_reason} | 市場: {current_market_slug}")
            record_execution_attempt(
                status="blocked_exposure",
                attempt_stage="exposure_gate",
                signal_side=signal_side,
                token_id=token_id,
                amount_usd=TRADE_AMOUNT_USD,
                source_signal=source_signal,
                failed_reason=reject_reason,
            )
            record_signal_rejection(
                rejection_stage="exposure_gate",
                rejection_reason=reject_reason,
                signal_side=signal_side,
                amount_usd=TRADE_AMOUNT_USD,
                source_signal=source_signal,
            )
            return

        if source_signal is not None:
            source_signal["is_extension_order"] = is_extension_order
            ensure_signal_candidate_id(source_signal)
            ledger = ensure_market_ledger()
            if ledger is None:
                return
            ml_allowed, ml_reason = evaluate_ml_filter_for_signal(
                signal_side=signal_side,
                source_signal=source_signal,
                ledger=ledger,
            )
            fill_prob_allowed, fill_prob_reason = (
                evaluate_fill_probability_filter_for_signal(
                    signal_side=signal_side,
                    source_signal=source_signal,
                    ledger=ledger,
                    amount_usd=TRADE_AMOUNT_USD,
                )
            )
            if not ml_allowed:
                print(
                    f"🤖 ML filter 阻擋下單 | side={signal_side} | "
                    f"pred_ev={source_signal.get('ml_predicted_ev')} | "
                    f"min_ev={source_signal.get('ml_min_ev')} | reason={ml_reason}"
                )
                record_raw_candidate(
                    candidate_stage="post_hard_gates",
                    candidate_action="blocked_ml_filter",
                    signal_side=signal_side,
                    token_id=token_id,
                    amount_usd=TRADE_AMOUNT_USD,
                    source_signal=source_signal,
                )
                record_execution_attempt(
                    status="blocked_ml_filter",
                    attempt_stage="ml_filter",
                    signal_side=signal_side,
                    token_id=token_id,
                    amount_usd=TRADE_AMOUNT_USD,
                    source_signal=source_signal,
                    failed_reason=ml_reason,
                )
                return
            if not fill_prob_allowed:
                print(
                    f"🎯 Fill probability filter 阻擋下單 | side={signal_side} | "
                    f"prob={source_signal.get('fill_probability')} | "
                    f"min_prob={source_signal.get('fill_prob_min_probability')} | "
                    f"reason={fill_prob_reason}"
                )
                record_raw_candidate(
                    candidate_stage="post_hard_gates",
                    candidate_action="blocked_fill_prob_filter",
                    signal_side=signal_side,
                    token_id=token_id,
                    amount_usd=TRADE_AMOUNT_USD,
                    source_signal=source_signal,
                )
                record_execution_attempt(
                    status="blocked_fill_prob_filter",
                    attempt_stage="fill_prob_filter",
                    signal_side=signal_side,
                    token_id=token_id,
                    amount_usd=TRADE_AMOUNT_USD,
                    source_signal=source_signal,
                    failed_reason=fill_prob_reason,
                )
                return
            record_raw_candidate(
                candidate_stage="post_hard_gates",
                candidate_action="send_allowed",
                signal_side=signal_side,
                token_id=token_id,
                amount_usd=TRADE_AMOUNT_USD,
                source_signal=source_signal,
            )

        side_cn = "買 YES" if signal_side == "UP" else "買 DOWN"
        order_type_label = (
            str(source_signal.get("order_type")) if source_signal else TAKER_ORDER_TYPE
        )
        max_execution_price = safe_float(
            source_signal.get("max_execution_price") if source_signal else None,
            safe_float(source_signal.get("ask") if source_signal else None, 0.0),
        )
        exec_mode = (
            str(source_signal.get("exec_price_mode")) if source_signal else EXEC_PRICE_MODE
        )
        order_price_hint = (
            None
            if exec_mode == "market"
            else safe_float(
                source_signal.get("order_price_hint")
                if source_signal and source_signal.get("order_price_hint") is not None
                else max_execution_price,
                max_execution_price,
            )
        )
        if source_signal is not None:
            source_signal["order_price_hint"] = order_price_hint
        order_price_hint_label = (
            f"{safe_float(order_price_hint, 0.0):.3f}"
            if order_price_hint is not None
            else "none"
        )

        if DRY_RUN:
            last_order_time = now
            dry_run_fill_size = (
                TRADE_AMOUNT_USD / max_execution_price if max_execution_price > 0 else None
            )
            print(
                f"🧪 DRY_RUN：模擬下單 | {side_cn} | 金額: ${TRADE_AMOUNT_USD} | "
                f"order_type={order_type_label} | max_price={max_execution_price:.3f} | "
                f"price_hint={order_price_hint_label} | "
                f"exec_mode={exec_mode} | extension={'yes' if is_extension_order else 'no'} | "
                f"市場: {current_market_slug}"
            )
            record_execution_attempt(
                status="simulated",
                attempt_stage="dry_run",
                signal_side=signal_side,
                token_id=token_id,
                amount_usd=TRADE_AMOUNT_USD,
                source_signal=source_signal,
                order_sent=False,
                order_accepted=True,
                filled=True,
                fill_inferred=True,
                fill_amount_usd=TRADE_AMOUNT_USD,
                fill_shares=dry_run_fill_size,
                fill_avg_price=max_execution_price,
                fill_ratio=1.0,
                fill_price=max_execution_price,
                fill_size=dry_run_fill_size,
            )
            record_order_event(
                status="simulated",
                included_in_position=True,
                signal_side=signal_side,
                amount_usd=TRADE_AMOUNT_USD,
                source_signal=source_signal,
                requested_amount_usd=TRADE_AMOUNT_USD,
                execution_price=max_execution_price,
            )
            return

        order_sent = False
        send_started_at = time.perf_counter()
        try:
            order_args = {
                "token_id": token_id,
                "amount": TRADE_AMOUNT_USD,
                "side": side,
                "order_type": TAKER_ORDER_TYPE_ENUM,
            }
            if order_price_hint is not None:
                order_args["price"] = order_price_hint
            try:
                mo = MarketOrderArgs(**order_args)
            except TypeError:
                if order_price_hint is not None:
                    raise
                order_args["price"] = None
                mo = MarketOrderArgs(**order_args)
            signed_order = client.create_market_order(mo)
            order_sent = True
            resp = client.post_order(signed_order, TAKER_ORDER_TYPE_ENUM)
            latency_ms = (time.perf_counter() - send_started_at) * 1000.0

            response_order_id = str(resp.get("orderID", "") or resp.get("id", ""))
            if not response_order_id and resp.get("success") is False:
                raise ValueError(f"訂單未成功建立: {resp}")
            fill_info = parse_buy_fill_from_order_response(
                resp,
                requested_amount_usd=TRADE_AMOUNT_USD,
                fallback_price=max_execution_price,
            )
            filled, fill_inferred = infer_fill_from_order_response(resp)
            actual_amount_usd = safe_float(fill_info.get("amount_usd"), 0.0)
            actual_gross_shares = safe_float(fill_info.get("gross_shares"), 0.0)
            actual_avg_price = safe_float(fill_info.get("avg_price"), 0.0)
            actual_fill_ratio = safe_float(fill_info.get("fill_ratio"), 0.0)

            if actual_amount_usd <= 0 or actual_gross_shares <= 0:
                filled = False
                fill_inferred = False

            fee_rate_bps = (
                current_yes_fee_rate_bps
                if signal_side == "UP"
                else current_down_fee_rate_bps
            )
            actual_execution_estimate = estimate_taker_buy_execution_from_fill(
                amount_usd=actual_amount_usd,
                gross_shares=actual_gross_shares,
                price=actual_avg_price,
                fee_rate_bps=fee_rate_bps,
            )

            last_order_time = now
            status_label = "live_success" if filled else "live_no_fill"
            print(
                f"🚀 TAKER 下單回應！{side_cn} | requested=${TRADE_AMOUNT_USD:.4f} | "
                f"filled=${actual_amount_usd:.4f} ({actual_fill_ratio:.1%}) | "
                f"shares={actual_gross_shares:.6f} | avg_price={actual_avg_price:.4f} | "
                f"order_type={order_type_label} | max_price={max_execution_price:.3f} | "
                f"price_hint={order_price_hint_label} | "
                f"exec_mode={exec_mode} | extension={'yes' if is_extension_order else 'no'} | "
                f"status={status_label} | 市場: {current_market_slug}"
            )
            print(f"   回應: {json.dumps(resp, indent=2, ensure_ascii=False)}")

            record_execution_attempt(
                status=status_label,
                attempt_stage="post_order",
                signal_side=signal_side,
                token_id=token_id,
                amount_usd=TRADE_AMOUNT_USD,
                source_signal=source_signal,
                order_sent=True,
                order_accepted=True,
                filled=filled,
                fill_inferred=fill_inferred,
                fill_amount_usd=actual_amount_usd,
                fill_shares=actual_gross_shares,
                fill_avg_price=actual_avg_price,
                fill_ratio=actual_fill_ratio,
                fill_price=actual_avg_price,
                fill_size=actual_gross_shares,
                response_order_id=response_order_id,
                latency_ms=latency_ms,
                raw_response=resp,
            )
            record_order_event(
                status=status_label,
                included_in_position=filled,
                signal_side=signal_side,
                amount_usd=actual_amount_usd if filled else TRADE_AMOUNT_USD,
                source_signal=source_signal,
                response_order_id=response_order_id,
                requested_amount_usd=TRADE_AMOUNT_USD,
                execution_price=actual_avg_price if filled else max_execution_price,
                execution_estimate=actual_execution_estimate if filled else None,
            )

        except Exception as e:
            print(
                f"❌ 下單失敗: {e} | order_type={order_type_label} | "
                f"max_price={max_execution_price:.3f} | "
                f"price_hint={order_price_hint_label} | exec_mode={exec_mode}"
            )
            latency_ms = (time.perf_counter() - send_started_at) * 1000.0
            record_execution_attempt(
                status="live_failed",
                attempt_stage="post_order" if order_sent else "create_order",
                signal_side=signal_side,
                token_id=token_id,
                amount_usd=TRADE_AMOUNT_USD,
                source_signal=source_signal,
                order_sent=order_sent,
                order_accepted=False,
                filled=False,
                latency_ms=latency_ms,
                failed_reason=str(e),
            )
            record_order_event(
                status="live_failed",
                included_in_position=False,
                signal_side=signal_side,
                amount_usd=TRADE_AMOUNT_USD,
                source_signal=source_signal,
                error=str(e),
            )


# ====================== PM WS 訊息處理 ======================
def process_pm_event(data: Dict[str, Any]):
    global pm_yes_best_bid, pm_yes_best_ask, pm_no_best_bid, pm_no_best_ask

    event_type = data.get("event_type")

    if event_type == "best_bid_ask":
        asset_id = data.get("asset_id")
        best_bid = data.get("best_bid")
        best_ask = data.get("best_ask")

        if asset_id == pm_yes_token:
            pm_yes_best_bid = best_bid
            pm_yes_best_ask = best_ask
        elif asset_id == pm_no_token:
            pm_no_best_bid = best_bid
            pm_no_best_ask = best_ask

        if SHOW_PM_QUOTE_LOG:
            print(
                f"📊 PM 報價 | "
                f"YES ask={pm_yes_best_ask} bid={pm_yes_best_bid} | "
                f"DOWN ask={pm_no_best_ask} bid={pm_no_best_bid} | "
                f"BN={bn_last_price}"
            )
        record_tick_snapshot("pm_best_bid_ask")
        evaluate_and_dispatch_signals()

    elif event_type in ("price_change", "last_trade_price"):
        record_tick_snapshot(f"pm_{event_type}")
        evaluate_and_dispatch_signals()


# ====================== WebSocket 處理 ======================
async def tick_snapshot_interval_handler():
    while True:
        await asyncio.sleep(TICK_SNAPSHOT_INTERVAL_SECONDS)
        record_tick_snapshot("interval_heartbeat", force=True)


async def pm_websocket_handler():
    while True:
        try:
            now = utcnow()
            if (
                pm_yes_token is None
                or pm_no_token is None
                or current_market_end_dt is None
                or now >= current_market_end_dt
            ):
                ok = await refresh_live_market(force=True)
                if not ok:
                    print(f"⌛ 目前沒有 live {MARKET_LABEL} 市場，5 秒後重試...")
                    await asyncio.sleep(5)
                    continue

            async with websockets.connect(
                PM_WS_URL,
                ssl=SSL_CONTEXT,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
                max_size=None,
            ) as ws:
                print("🔌 連線 Polymarket Market WS 成功")
                print(f"📍 當前市場: {current_market_question}")
                print(f"📡 訂閱資產 IDs: {pm_yes_token}, {pm_no_token}")

                subscribe_msg = {
                    "type": "market",
                    "assets_ids": [pm_yes_token, pm_no_token],
                    "custom_feature_enabled": True,
                }
                await ws.send(json.dumps(subscribe_msg))
                print(
                    f"📡 已訂閱 YES({pm_yes_token[:8]}...) + DOWN({pm_no_token[:8]}...)"
                )

                while True:
                    if current_market_end_dt and utcnow() >= current_market_end_dt:
                        mark_current_market_pending_settlement("time_window_elapsed")
                        print(
                            f"⏭️ 目前市場時窗已結束，重新抓下一個 live {MARKET_LABEL} 市場..."
                        )
                        break

                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    except asyncio.TimeoutError:
                        continue

                    data = json.loads(message)

                    if isinstance(data, list):
                        for item in data:
                            if not isinstance(item, dict):
                                continue
                            if item.get("event_type") == "market_resolved":
                                mark_current_market_pending_settlement(
                                    "market_resolved_event"
                                )
                                print("🏁 收到 market_resolved，重新抓下一個市場...")
                                raise RuntimeError("market_resolved")
                            process_pm_event(item)

                    elif isinstance(data, dict):
                        if data.get("event_type") == "market_resolved":
                            mark_current_market_pending_settlement(
                                "market_resolved_event"
                            )
                            print("🏁 收到 market_resolved，重新抓下一個市場...")
                            raise RuntimeError("market_resolved")
                        process_pm_event(data)

        except RuntimeError as e:
            if str(e) == "market_resolved":
                await asyncio.sleep(1)
                continue
            print(f"❌ PM WS runtime error: {e}，5 秒後重連...")
            await asyncio.sleep(5)

        except Exception as e:
            print(f"❌ PM WS 斷線: {e}，5 秒後重連...")
            await asyncio.sleep(5)


async def binance_websocket_handler():
    global bn_last_price

    while True:
        try:
            async with websockets.connect(
                BINANCE_WS_URL,
                ssl=SSL_CONTEXT,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
                max_size=None,
            ) as ws:
                print("🔌 連線 Binance WS 成功")

                while True:
                    message = await ws.recv()
                    data = json.loads(message)
                    bn_last_price = float(data["p"])

                    sample_bn_price_once_per_second(bn_last_price)

                    if SHOW_BN_TICK_LOG and int(time.time()) % 3 == 0:
                        print(f"💰 BN BTC 即時價: ${bn_last_price:,.2f}")

        except Exception as e:
            print(f"❌ BN WS 斷線: {e}，5 秒後重連...")
            await asyncio.sleep(5)


# ====================== 啟動 ======================
async def wait_for_initial_market():
    global client
    while True:
        try:
            client = init_polymarket_client()
            return
        except Exception as e:
            print(f"⌛ 初始化時尚未抓到 live {MARKET_LABEL} 市場：{e}")
            print("   5 秒後重試...")
            await asyncio.sleep(5)


async def main():
    ensure_ledger_files()
    load_market_state_json()

    print(f"🚀 Polymarket {MARKET_LABEL} live Taker Bot 啟動")
    print(
        f"   特點：依 ET 當前 {MARKET_WINDOW_LABEL} bucket 反推 slug，再直接查單一市場"
    )
    print("   架構：BN 機率模型 V1 + Signal Layer + Execution Layer + PM/BN 雙 WS")
    print(
        "   帳本：自動記錄每筆下單與每個市場結算後的內部估算收益（含官方 fee 規則估算）"
    )
    print("   累計：本次啟動收益從 0 開始，只加總本次執行期間的市場結算結果")
    print("   提醒：預設 DRY_RUN=true，確認無誤後再把 .env 設成 DRY_RUN=false")
    print(
        f"   設定：ORDER_COOLDOWN={COOLDOWN_SECONDS}s | "
        f"SIGNAL_COOLDOWN={SIGNAL_COOLDOWN_SECONDS}s | "
        f"MARKET_BUCKET={MARKET_BUCKET_MINUTES}m | "
        f"MIN_ENTRY_ASK_PRICE={MIN_ENTRY_ASK_PRICE:.3f} | "
        f"MIN_ENTRY_REMAINING={MIN_ENTRY_REMAINING_SECONDS:.1f}s | "
        f"OPEN_ANCHOR={OPEN_ANCHOR_MODE} | "
        f"OPEN_ANCHOR_WEIGHT={OPEN_ANCHOR_WEIGHT:.2f} | "
        f"ORDER_TYPE={TAKER_ORDER_TYPE} | "
        f"EXEC_MODE={EXEC_PRICE_MODE} | "
        f"SLIPPAGE_TICKS={EXEC_SLIPPAGE_TICKS} | "
        f"MIN_EDGE_AFTER_FILL={MIN_EDGE_AFTER_FILL:.3f} | "
        f"EXEC_PRICE_CAP={EXEC_PRICE_CAP:.3f} | "
        f"MARKET_MAX_TOTAL_COST={MARKET_MAX_TOTAL_COST:.2f} | "
        f"MARKET_MAX_SIDE_COST={MARKET_MAX_SIDE_COST:.2f} | "
        f"SIDE_EXTENSION_ENABLED={SIDE_EXTENSION_ENABLED} | "
        f"SIDE_EXTENSION_START_COST={SIDE_EXTENSION_EFFECTIVE_START_COST:.2f} | "
        f"SIDE_EXTENSION_MAX_SIDE_COST={SIDE_EXTENSION_EFFECTIVE_MAX_SIDE_COST:.2f} | "
        f"SIDE_EXTENSION_MIN_SECONDS={SIDE_EXTENSION_MIN_SECONDS}s | "
        f"SIDE_EXTENSION_COOLDOWN={SIDE_EXTENSION_COOLDOWN_SECONDS}s | "
        f"SIDE_EXTENSION_MIN_EDGE={SIDE_EXTENSION_MIN_EDGE:.3f} | "
        f"SIDE_EXTENSION_MIN_EAF={SIDE_EXTENSION_MIN_EDGE_AFTER_FILL:.3f} | "
        f"SIDE_EXTENSION_ASK_RANGE={SIDE_EXTENSION_MIN_ASK_PRICE:.2f}-{SIDE_EXTENSION_MAX_ASK_PRICE:.2f} | "
        f"SIDE_EXTENSION_MAX_OPPOSITE_COST={SIDE_EXTENSION_MAX_OPPOSITE_COST:.2f} | "
        f"VOL_SHORT={VOL_WINDOW_SHORT_SECONDS}s | "
        f"VOL_LONG={VOL_WINDOW_LONG_SECONDS}s | "
        f"SIGMA_MIN={SIGMA_MIN} | Z_CAP={Z_CAP} | "
        f"EDGE_THRESHOLD={EDGE_PROB_THRESHOLD} | "
        f"EDGE_REF={EDGE_REFERENCE_PRICE} | "
        f"ENTRY_TIME_BUCKETS={ENTRY_TIME_BUCKETS_LABEL} | "
        f"ML_FILTER_ENABLED={ML_FILTER_ENABLED} | "
        f"ML_MIN_EV={ML_FILTER_MIN_EV:.4f} | "
        f"RAW_CANDIDATE_LOG_ENABLED={RAW_CANDIDATE_LOG_ENABLED} | "
        f"FILL_PROB_FILTER_ENABLED={FILL_PROB_FILTER_ENABLED} | "
        f"FILL_PROB_MIN_PROBABILITY={FILL_PROB_MIN_PROBABILITY:.4f}"
    )
    if not DRY_RUN and TAKER_ORDER_TYPE == "FAK":
        print("   注意：FAK live 可能部分成交；目前帳本仍以估算成交記錄，未做 partial fill 精算")
    print(f"   暖機：需先累積滿 {VOL_WINDOW_LONG_SECONDS}s BN 秒級價格後才會開始交易")
    print(f"   LEDGER_DIR={LEDGER_DIR.resolve()}")

    await wait_for_initial_market()

    pm_task = asyncio.create_task(pm_websocket_handler())
    bn_task = asyncio.create_task(binance_websocket_handler())
    tasks = [pm_task, bn_task]

    if TICK_SNAPSHOT_ENABLED and TICK_SNAPSHOT_MODE in {"interval", "both"}:
        snapshot_task = asyncio.create_task(tick_snapshot_interval_handler())
        tasks.append(snapshot_task)

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 使用者中斷，Bot 已停止")
        try:
            if current_market_end_dt and utcnow() >= current_market_end_dt:
                mark_current_market_pending_settlement("keyboard_interrupt")
            fallback_pending_settlement("keyboard_interrupt_bn_fallback")
        except Exception:
            pass
    except Exception as e:
        print(f"❌ 致命錯誤: {e}")
