# Prediction Market Execution Lab｜公開展示版執行順序

> 本文件是給我自己看的執行順序，不是公開 README。目標是把目前測試用的 Polymarket-Taker-Bot，整理、刪減、重構成一個可以公開展示、可以放在 GitHub / LinkedIn / CV 的作品。

---

## 0. 定稿主題

### 建議公開作品名稱

**Prediction Market Execution Lab**

### 建議副標題

**Testing Executable Edge in Polymarket BTC Short-Horizon Markets**

### 中文定位

這是一個研究短週期預測市場中，「理論上的價格優勢」經過 bid-ask spread、slippage、成交機率、latency、倉位限制與結算結果後，是否仍能轉化成「可執行 edge」的市場微結構與執行品質分析專案。

### 作品不主打什麼

- 不主打「自動下注機器人」
- 不主打「穩定獲利策略」
- 不主打「Polymarket 賭盤工具」
- 不公開完整 production execution / wallet / allowance / deploy 細節
- 不公開真實 private ledger、wallet、API key、策略敏感參數

### 作品主打什麼

- Prediction market microstructure
- Fair probability modeling
- Executable edge analysis
- Execution-quality diagnostics
- Tick-level replay backtesting
- PnL attribution
- ML-assisted signal filtering
- Risk and Monte Carlo simulation

---

## 1. 新 repo 建立與命名

### 建議 repo 名稱

```text
prediction-market-execution-lab
```

### 備選名稱

```text
polymarket-execution-quality-lab
prediction-market-microstructure-lab
polymarket-btc-market-efficiency-lab
```

### Repo 建立後第一步

先建立乾淨的公開 repo，不要直接把舊專案整包搬過去。

初始結構建議：

```text
prediction-market-execution-lab/
├── README.md
├── docs/
├── notebooks/
├── reports/
├── reports/figures/
├── src/
├── data/sample/
├── dashboard/
├── scripts/
├── tests/
├── .env.example
├── pyproject.toml
└── LICENSE
```

---

## 2. 第一階段：公開版範圍切割

### 目標

把原本測試用專案切成「可公開」與「不公開」兩部分。

### 建議保留到公開版的內容

| 類型 | 是否保留 | 說明 |
|---|---:|---|
| Binance BTC 價格資料串流邏輯 | 保留並簡化 | 可作為 reference price data source |
| Polymarket market / quote data 讀取 | 保留並簡化 | 作為 prediction market CLOB data source |
| fair probability model | 保留 | 是整個作品的核心模型 |
| signal / edge calculation | 保留 | 但要避免寫成可直接下注工具 |
| tick snapshot replay backtest | 保留 | 非常適合展示研究能力 |
| execution-quality analysis | 保留 | 本作品核心 |
| PnL attribution | 保留 | 但使用 sample / anonymized data |
| ML filter | 保留為 optional module | 不要讓 ML 成為主敘事 |
| Monte Carlo ledger simulation | 保留 | 作為 risk analysis |
| sample data | 保留 | 用假資料或匿名化後資料 |

### 建議不公開或重度刪減的內容

| 類型 | 建議 | 原因 |
|---|---|---|
| wallet / private key / signer 相關邏輯 | 不公開 | 安全風險 |
| allowance maintenance | 不公開或只保留 mock 說明 | 過於接近 production operation |
| auto claim | 不公開 | 與研究作品關聯低，且敏感 |
| deploy.sh | 不公開或改成 demo-only | 避免被看成可直接部署下注工具 |
| 真實 ledger / orders / settlements | 不公開 | 隱私與策略敏感 |
| 真實 API / relayer / proxy 細節 | 不公開 | 安全與濫用風險 |
| 過度精準的 live strategy thresholds | 模糊化 | 避免公開 alpha-sensitive 參數 |

---

## 3. 第二階段：程式碼重構順序

### 目標

把原本偏實戰測試的 bot，拆成適合公開閱讀的 research codebase。

### 優先處理順序

#### 3.1 建立 src 核心模組

建議拆成：

```text
src/
├── data_sources/
│   ├── binance.py
│   └── polymarket.py
├── models/
│   ├── fair_probability.py
│   └── ml_filter.py
├── execution_quality/
│   ├── edge.py
│   ├── spread.py
│   ├── fill_analysis.py
│   └── pnl_attribution.py
├── backtesting/
│   ├── tick_replay.py
│   └── walk_forward.py
├── risk/
│   └── monte_carlo.py
└── utils/
    ├── config.py
    └── plotting.py
```

#### 3.2 簡化原本的 bot.py

原本的 `bot.py` 不建議完整公開。建議拆成：

| 原功能 | 公開版處理方式 |
|---|---|
| live execution 主循環 | 移除或改成 dry-run demo |
| market data collection | 保留 |
| fair probability calculation | 保留並獨立成 module |
| edge calculation | 保留 |
| actual order submission | 移除或 mock |
| risk gates | 保留概念與簡化版 |
| ledger logging | 保留 sample 版本 |

#### 3.3 保留的 script

建議保留：

```text
scripts/collect_sample_quotes.py
scripts/build_signal_dataset.py
scripts/run_tick_replay_backtest.py
scripts/run_execution_quality_report.py
scripts/run_monte_carlo_simulation.py
scripts/train_ml_filter_demo.py
```

#### 3.4 不建議公開的 script

```text
polymarket_auto_claim.py
polymarket_allowance_maintenance.py
deploy.sh
production live taker execution script
private wallet / proxy / relayer maintenance script
```

---

## 4. 第三階段：文件撰寫順序

### 目標

先把作品「講清楚」，再補程式與報告。

### 4.1 README.md

README 是公開 repo 最重要的文件，優先寫。

建議結構：

```text
# Prediction Market Execution Lab

## 1. Project Overview
## 2. Research Question
## 3. Why Prediction Markets?
## 4. System Architecture
## 5. Data Sources
## 6. Fair Probability Model
## 7. Executable Edge Definition
## 8. Execution Quality Analysis
## 9. Backtesting Methodology
## 10. Key Findings
## 11. Limitations
## 12. Repository Structure
## 13. How to Run Demo
## 14. Disclaimer
```

### 4.2 docs/project_brief.md

用途：用 1–2 頁講清楚這個作品到底在解決什麼問題。

內容：

- 背景：prediction market 價格代表市場隱含機率
- 問題：表面 mispricing 不一定代表可交易 edge
- 研究目標：測試 edge 是否能穿越 execution friction
- 專案範圍：Polymarket BTC short-horizon markets
- 主要輸出：report、notebooks、demo dashboard、sample pipeline

### 4.3 docs/methodology.md

用途：解釋方法，不寫太多業務包裝。

內容：

- Market price 與 implied probability
- Fair probability model
- Edge definition
- Spread / slippage / fill probability
- Tick replay backtest
- PnL attribution
- Monte Carlo simulation
- ML filter validation

### 4.4 docs/architecture.md

用途：讓讀者 1 分鐘看懂系統流。

內容：

- Mermaid 架構圖
- Data flow
- Signal flow
- Backtest flow
- Report generation flow

### 4.5 docs/limitations.md

用途：增加專業可信度，避免作品像在吹噓交易策略。

內容：

- short-horizon market noise 很高
- backtest 不等於 live execution
- liquidity 與 fill probability 會造成偏差
- public sample data 不代表完整 live trading data
- 本作品僅作研究與教育展示，不構成交易建議

---

## 5. 第四階段：Report 撰寫順序

### 目標

讓作品有結論，不只是有程式碼。

### 5.1 reports/execution_quality_report.md

第一優先。

內容：

- Candidate signal funnel
- Signal → passed risk gates → attempted → filled → settled
- Spread distribution
- Edge before execution vs edge after execution
- Fill rate by edge bucket
- PnL by time-to-expiry bucket
- Failed / rejected / no-fill reason analysis
- Main conclusion

### 5.2 reports/probability_calibration_report.md

第二優先。

內容：

- Polymarket implied probability vs realized outcome
- Fair probability model vs realized outcome
- Calibration buckets
- Brier score / log loss
- Market efficiency discussion

### 5.3 reports/ml_filter_report.md

第三優先。

內容：

- 為什麼加入 ML filter
- Features used
- Walk-forward validation
- Before / after comparison
- 是否真的改善 PnL / drawdown / trade quality
- Overfitting limitation

### 5.4 reports/risk_simulation_report.md

第四優先。

內容：

- Monte Carlo bootstrap
- Drawdown distribution
- Losing streak analysis
- Position cap impact
- Sensitivity analysis

---

## 6. 第五階段：Notebook 撰寫順序

### 目標

讓 reviewer 可以用 notebook 快速理解分析流程。

### 建議 notebook

```text
notebooks/01_data_overview.ipynb
notebooks/02_fair_probability_model.ipynb
notebooks/03_execution_quality_analysis.ipynb
notebooks/04_probability_calibration.ipynb
notebooks/05_ml_filter_walkforward.ipynb
notebooks/06_risk_simulation.ipynb
```

### 每份 notebook 的目的

| Notebook | 目的 |
|---|---|
| 01_data_overview | 介紹 sample data schema、market、quotes、settlements |
| 02_fair_probability_model | 解釋 fair probability 如何產生 |
| 03_execution_quality_analysis | 核心 notebook，展示 edge 如何被 execution friction 侵蝕 |
| 04_probability_calibration | 分析市場價格與結果是否校準 |
| 05_ml_filter_walkforward | 展示 ML filter 是否改善 signal quality |
| 06_risk_simulation | 展示 drawdown / Monte Carlo / sensitivity |

---

## 7. 第六階段：圖表與封裝

### 目標

讓 GitHub / LinkedIn / 面試展示更容易被理解。

### 必做圖表

```text
reports/figures/system_architecture.png
reports/figures/signal_funnel.png
reports/figures/spread_distribution.png
reports/figures/edge_decay.png
reports/figures/fill_rate_by_edge_bucket.png
reports/figures/pnl_by_time_bucket.png
reports/figures/calibration_curve.png
reports/figures/monte_carlo_drawdown.png
```

### 圖表優先順序

1. System architecture
2. Signal funnel
3. Edge decay
4. Spread distribution
5. Fill rate by edge bucket
6. PnL attribution
7. Calibration curve
8. Monte Carlo drawdown

---

## 8. 第七階段：Dashboard / 網站封裝

### 目標

做一個很簡單但能展示作品的互動頁面。

### 建議工具

優先用 Streamlit。

### Dashboard 內容

```text
dashboard/app.py
```

頁面建議：

1. Project overview
2. Signal funnel
3. Execution quality metrics
4. Edge decay chart
5. Calibration chart
6. Risk simulation summary
7. Key findings

### 不需要做的事

- 不需要做完整前後端
- 不需要登入系統
- 不需要 live trading mode
- 不需要連真實 wallet
- 不需要讓使用者輸入策略參數去下單

---

## 9. 第八階段：Sample Data 準備

### 目標

讓公開 repo 可以跑 demo，但不暴露真實資料。

### 建議 sample data

```text
data/sample/markets_sample.csv
data/sample/quotes_sample.csv
data/sample/candidates_sample.csv
data/sample/executions_sample.csv
data/sample/settlements_sample.csv
data/sample/tick_snapshots_sample.parquet
```

### 處理原則

- 移除 wallet address
- 移除 order id 或改成 fake id
- 移除真實交易金額或做比例化
- 保留必要欄位讓 notebook / report 可以跑
- 明確標註 sample data is anonymized / simplified

---

## 10. 第九階段：測試與品質整理

### 目標

讓 repo 看起來不是臨時拼裝。

### 建議補最低限度測試

```text
tests/test_fair_probability.py
tests/test_edge_calculation.py
tests/test_pnl_attribution.py
tests/test_monte_carlo.py
```

### 建議補工具

```text
pyproject.toml
ruff
pytest
mypy optional
```

### 不需要過度做的事

- 不需要完整 CI/CD 到 production
- 不需要 Docker deployment 到雲端
- 不需要 live execution 測試

---

## 11. 第十階段：GitHub 首頁完成

### 目標

讓陌生 reviewer 3–5 分鐘看懂。

### README 最終必須回答

1. 這個作品研究什麼？
2. 為什麼這個問題重要？
3. 用了什麼資料？
4. 模型怎麼估 fair probability？
5. 怎麼定義 executable edge？
6. execution friction 包含哪些？
7. 回測與 live-like 分析怎麼做？
8. 主要發現是什麼？
9. 限制是什麼？
10. 怎麼跑 demo？

### README 最終一句話

建議使用：

```text
This project studies whether apparent short-horizon prediction-market mispricings can survive real execution frictions such as spread, slippage, fill probability, latency, and position limits.
```

---

## 12. 第十一階段：LinkedIn 發布準備

### 目標

公開作品後，在 LinkedIn 上用專業角度發布。

### 發布前準備

- GitHub repo public
- README 完整
- 至少一份 report 完成
- 至少三張圖表完成
- 至少一個 notebook 可打開閱讀
- LinkedIn post 草稿完成
- CV bullet 更新完成

### LinkedIn 主軸

不要寫：

```text
I built a Polymarket trading bot.
```

要寫：

```text
I built a prediction-market execution research framework to study whether apparent pricing edges survive real execution frictions.
```

### LinkedIn 文章結構

1. 作品背景
2. 核心問題
3. 技術方法
4. 主要發現
5. 對 FinTech / market infrastructure 的理解
6. GitHub link

---

## 13. 第十二階段：CV / 面試敘事整理

### CV bullet 初版

```text
Built a prediction-market execution research framework using Polymarket BTC short-horizon markets and Binance BTCUSDT reference prices to evaluate whether apparent pricing edges survive spread, slippage, fill probability, latency, and position-risk constraints.
```

### 面試時的 30 秒說法

```text
This project started from a Polymarket BTC short-horizon trading experiment, but I reframed it into a market microstructure and execution-quality research project. Instead of simply asking whether a model can predict BTC direction, I studied whether apparent prediction-market mispricings can actually be converted into executable edge after accounting for spread, slippage, fill probability, latency, and risk limits.
```

---

## 14. 總執行順序總覽

```text
Step 1：建立新 repo，命名為 prediction-market-execution-lab
Step 2：切分公開 / 不公開內容
Step 3：重構核心程式碼到 src/
Step 4：先寫 README、project_brief、methodology、architecture
Step 5：準備 anonymized sample data
Step 6：製作 execution_quality_report
Step 7：製作 data overview 與 execution quality notebooks
Step 8：補 probability calibration report / notebook
Step 9：整理 ML filter 與 risk simulation 為 optional modules
Step 10：生成核心圖表
Step 11：製作簡單 Streamlit dashboard
Step 12：補最低限度 tests / pyproject / linting
Step 13：完成 GitHub README final
Step 14：準備 LinkedIn post 與 CV bullet
Step 15：公開 repo 並發布
```

---

## 15. 目前最先做的 5 件事

1. 新建 repo：`prediction-market-execution-lab`
2. 寫 README 第一版，只寫定位、研究問題、架構、預計輸出
3. 從舊 repo 搬出 fair probability、edge calculation、tick replay、PnL attribution 的乾淨版本
4. 建立 sample data schema，不急著放完整資料
5. 先完成 `reports/execution_quality_report.md` 的大綱

---

## 16. 最終判斷

這個作品的公開版本應該是一個「prediction market execution research lab」，不是「Polymarket taker bot」。

核心價值不在於它能不能自動下注，而在於它能展示：

- 我理解 prediction market price 代表 implied probability
- 我能建立 fair-value model
- 我能把 theoretical edge 和 executable edge 分開
- 我知道 spread、slippage、fill probability、latency 會侵蝕交易結果
- 我能用資料、回測、ledger、PnL attribution 和 Monte Carlo 做策略診斷
- 我能把實戰交易經驗轉化成可公開、可面試、可討論的 FinTech 作品
