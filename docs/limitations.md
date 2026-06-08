# Limitations

This project is a public research and portfolio project. Its limitations should be explicit.

## 1. Backtests Are Not Live Results

Tick replay and historical analysis can help diagnose market behavior, but they do not prove future performance or live execution quality. A replay can show positive edge while live-like execution records show sparse realized fills after latency, quote staleness, failed order submission, and execution gates are included.

## 2. Market Liquidity Matters

Prediction-market quotes may not represent executable prices at meaningful size. Spread, depth, timing, and fill probability can materially change the result.

## 3. Short-Horizon Markets Are Noisy

BTC short-horizon markets can be highly sensitive to noise, latency, data timing, and settlement mechanics.

## 4. Public Sample Data May Be Simplified

The public repository may use anonymized, simplified, or synthetic sample data to protect private records and avoid exposing sensitive operational details.

## 5. Last-Time-Window Reversal Risk

The final resolution window can behave differently from the rest of a five-minute market. The last 30 seconds often contain more volume and sharper implied-probability movement, while the final 5-10 seconds can include reversals or repeated crossings of the opening anchor. These observations are treated as market microstructure risk, not as proof of manipulation.

## 6. Reference-Lag Assumption Is Not Fully Validated Here

The project uses Binance BTCUSDT spot ticks as a faster proxy for BTC movement while Polymarket BTC markets settle against an oracle-style reference. The short reference lag is a domain-informed working assumption, not a dedicated lead-lag result produced by this repository.

## 7. ML and Fill-Probability Filters Require Careful Validation

Any machine-learning or fill-probability component must be evaluated for leakage, overfitting, regime sensitivity, threshold sensitivity, and sample-size limitations. The fill-probability threshold in the public sample should be read as an unfinished execution-quality gate under tuning, not as a final production parameter.

## 8. No Production Operation Details

The public version intentionally excludes wallet operations, private keys, allowance management, production deployment details, and private runbooks.

## 9. No Financial Advice

This repository is for research, educational, and portfolio demonstration purposes only. It is not financial advice, trading advice, or a recommendation to participate in any market.
