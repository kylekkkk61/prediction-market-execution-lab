"""Streamlit dashboard for the public sample execution-quality demo.

This app intentionally reads only repository-local public sample artifacts. It does
not connect to live markets, private ledgers, wallets, signers, or execution APIs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "sample"
REPORTS_DIR = ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"


@st.cache_data
def load_csv(filename: str) -> pd.DataFrame:
    """Load a public sample CSV file from data/sample."""
    path = DATA_DIR / filename
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def format_rate(value: float | None) -> str:
    """Format a decimal rate as a percentage string."""
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:.2%}"


def format_number(value: float | int | None, digits: int = 4) -> str:
    """Format a numeric metric for compact dashboard display."""
    if value is None or pd.isna(value):
        return "n/a"
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:,.{digits}f}"


def image_if_available(path: Path, caption: str) -> None:
    """Render an existing figure if it is present in the repository."""
    if path.exists():
        st.image(str(path), caption=caption, width="stretch")
    else:
        st.info(f"Figure not found: {path.relative_to(ROOT)}")


def compute_overview_metrics(
    candidates: pd.DataFrame,
    executions: pd.DataFrame,
    settlements: pd.DataFrame,
    ticks: pd.DataFrame,
) -> dict[str, str]:
    """Compute high-level public-sample metrics for the dashboard header."""
    fill_rate = None
    accepted_rate = None
    avg_spread = None
    avg_latency = None
    avg_pnl = None

    if not executions.empty:
        if "filled" in executions:
            fill_rate = executions["filled"].fillna(False).astype(bool).mean()
        if "order_accepted" in executions:
            accepted_rate = executions["order_accepted"].fillna(False).astype(bool).mean()
        if "signal_spread" in executions:
            avg_spread = pd.to_numeric(executions["signal_spread"], errors="coerce").mean()
        if "latency_ms" in executions:
            avg_latency = pd.to_numeric(executions["latency_ms"], errors="coerce").mean()

    if not settlements.empty and "net_pnl_normalized" in settlements:
        avg_pnl = pd.to_numeric(settlements["net_pnl_normalized"], errors="coerce").mean()

    return {
        "Candidate signals": format_number(len(candidates), digits=0),
        "Execution rows": format_number(len(executions), digits=0),
        "Tick rows": format_number(len(ticks), digits=0),
        "Settlement rows": format_number(len(settlements), digits=0),
        "Accepted rate": format_rate(accepted_rate),
        "Fill rate": format_rate(fill_rate),
        "Avg spread": format_number(avg_spread),
        "Avg latency ms": format_number(avg_latency, digits=1),
        "Avg normalized PnL": format_number(avg_pnl),
    }


def render_metric_grid(metrics: dict[str, str]) -> None:
    """Render a compact metric grid without implying performance claims."""
    rows = [
        ["Candidate signals", "Execution rows", "Tick rows", "Settlement rows"],
        ["Accepted rate", "Fill rate", "Avg spread", "Avg latency ms"],
        ["Avg normalized PnL"],
    ]
    for row in rows:
        columns = st.columns(len(row))
        for column, metric_name in zip(columns, row, strict=True):
            column.metric(metric_name, metrics.get(metric_name, "n/a"))


def render_status_breakdown(executions: pd.DataFrame) -> None:
    """Render execution-status diagnostics from public sample rows."""
    st.subheader("Execution status breakdown")
    if executions.empty or "status" not in executions:
        st.info("No execution status data available in the public sample.")
        return

    status_counts = executions["status"].fillna("unknown").value_counts().rename_axis("status")
    st.bar_chart(status_counts)
    st.dataframe(
        status_counts.reset_index(name="rows"),
        width="stretch",
        hide_index=True,
    )


def render_fill_rate_by_bucket(executions: pd.DataFrame) -> None:
    """Render fill-rate diagnostics by available public-sample buckets."""
    st.subheader("Fill rate by time bucket")
    required_columns = {"time_bucket", "filled"}
    if executions.empty or not required_columns.issubset(executions.columns):
        st.info("No time-bucket fill-rate data available in the public sample.")
        return

    grouped = (
        executions.assign(filled=executions["filled"].fillna(False).astype(bool))
        .groupby("time_bucket", dropna=False)
        .agg(rows=("filled", "size"), fill_rate=("filled", "mean"))
        .reset_index()
    )
    grouped["time_bucket"] = grouped["time_bucket"].fillna("unknown")
    grouped["fill_rate_pct"] = grouped["fill_rate"] * 100
    st.bar_chart(grouped.set_index("time_bucket")["fill_rate_pct"])
    st.dataframe(
        grouped[["time_bucket", "rows", "fill_rate"]],
        width="stretch",
        hide_index=True,
    )


def render_edge_and_spread(executions: pd.DataFrame, candidates: pd.DataFrame) -> None:
    """Render edge and spread diagnostics without new performance claims."""
    st.subheader("Edge and spread diagnostics")
    columns = st.columns(2)
    with columns[0]:
        image_if_available(FIGURES_DIR / "fill_rate_by_edge_bucket.png", "Fill rate by edge bucket")
    with columns[1]:
        image_if_available(FIGURES_DIR / "spread_distribution.png", "Spread distribution")

    diagnostics = []
    if not executions.empty and "signal_edge" in executions:
        edge = pd.to_numeric(executions["signal_edge"], errors="coerce")
        diagnostics.append({"metric": "Execution sample avg signal edge", "value": edge.mean()})
    if not executions.empty and "signal_spread" in executions:
        spread = pd.to_numeric(executions["signal_spread"], errors="coerce")
        diagnostics.append({"metric": "Execution sample avg spread", "value": spread.mean()})
    if not candidates.empty and "fill_probability" in candidates:
        fill_probability = pd.to_numeric(candidates["fill_probability"], errors="coerce")
        diagnostics.append({"metric": "Candidate sample avg fill probability", "value": fill_probability.mean()})

    if diagnostics:
        table = pd.DataFrame(diagnostics)
        table["value"] = table["value"].map(lambda value: format_number(value))
        st.dataframe(table, width="stretch", hide_index=True)


def render_calibration_and_risk() -> None:
    """Render existing calibration and risk figures."""
    st.subheader("Calibration and risk simulation")
    columns = st.columns(3)
    with columns[0]:
        image_if_available(FIGURES_DIR / "calibration_curve.png", "Probability calibration curve")
    with columns[1]:
        image_if_available(FIGURES_DIR / "monte_carlo_terminal_pnl.png", "Monte Carlo terminal PnL")
    with columns[2]:
        image_if_available(FIGURES_DIR / "monte_carlo_drawdown.png", "Monte Carlo drawdown")


@st.cache_data
def load_report_text(filename: str) -> str:
    """Load a generated report markdown file for quick dashboard review."""
    path = REPORTS_DIR / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


REPORT_IMAGE_PATTERN = re.compile(r"^!\[(?P<caption>[^\]]*)\]\((?P<path>[^)]+)\)\s*$")


def render_report_markdown_preview(text: str, max_chars: int = 4000) -> None:
    """Render report markdown previews and resolve report-relative images."""
    preview = text[:max_chars]
    markdown_buffer: list[str] = []

    def flush_markdown() -> None:
        if markdown_buffer:
            st.markdown("\n".join(markdown_buffer))
            markdown_buffer.clear()

    for line in preview.splitlines():
        match = REPORT_IMAGE_PATTERN.match(line.strip())
        if not match:
            markdown_buffer.append(line)
            continue

        flush_markdown()
        image_path = REPORTS_DIR / match.group("path")
        caption = match.group("caption") or image_path.name
        image_if_available(image_path, caption)

    flush_markdown()
    if len(text) > max_chars:
        st.caption("Preview truncated in dashboard. See the full markdown report in reports/.")


def render_report_links() -> None:
    """Render compact report previews for the demo dashboard."""
    st.subheader("Generated report artifacts")
    reports = [
        "execution_quality_report.md",
        "probability_calibration_report.md",
        "risk_simulation_report.md",
        "ml_filter_report.md",
    ]
    for report in reports:
        text = load_report_text(report)
        with st.expander(report):
            if text:
                render_report_markdown_preview(text)
            else:
                st.info(f"Report not found: reports/{report}")


def render_sample_tables(
    candidates: pd.DataFrame,
    executions: pd.DataFrame,
    settlements: pd.DataFrame,
    ticks: pd.DataFrame,
) -> None:
    """Render small public-sample previews for reviewers."""
    st.subheader("Public sample data preview")
    samples = {
        "candidates_sample.csv": candidates,
        "executions_sample.csv": executions,
        "settlements_sample.csv": settlements,
        "tick_snapshots_sample.csv": ticks,
    }
    for name, frame in samples.items():
        with st.expander(name):
            if frame.empty:
                st.info("No rows available.")
            else:
                st.caption(f"Rows: {len(frame):,}; Columns: {len(frame.columns):,}")
                st.dataframe(frame.head(50), width="stretch", hide_index=True)


def main() -> None:
    st.set_page_config(
        page_title="Prediction Market Execution Lab",
        page_icon="📊",
        layout="wide",
    )

    st.title("Prediction Market Execution Lab")
    st.caption("Testing Executable Edge in Polymarket BTC Short-Horizon Markets")

    st.info(
        "This dashboard uses anonymized, downsampled, and normalized public sample data only. "
        "It is a demonstration interface for execution-quality diagnostics, not a live trading "
        "tool, production execution system, or profitability claim."
    )

    candidates = load_csv("candidates_sample.csv")
    executions = load_csv("executions_sample.csv")
    settlements = load_csv("settlements_sample.csv")
    ticks = load_csv("tick_snapshots_sample.csv")

    st.header("Project overview")
    st.markdown(
        """
        This demo summarizes whether apparent short-horizon prediction-market pricing edges
        can survive execution frictions such as bid-ask spread, fill probability, latency,
        position limits, and settlement outcomes.

        The public dashboard is intentionally read-only and sample-backed. It does not expose
        wallet logic, signer logic, order submission, allowance maintenance, private ledgers,
        or live market connectivity.
        """
    )

    metrics = compute_overview_metrics(candidates, executions, settlements, ticks)
    render_metric_grid(metrics)

    st.header("Execution-quality diagnostics")
    image_if_available(FIGURES_DIR / "signal_funnel.png", "Signal funnel")
    render_status_breakdown(executions)
    render_fill_rate_by_bucket(executions)
    render_edge_and_spread(executions, candidates)

    st.header("Calibration and risk")
    render_calibration_and_risk()

    st.header("Reports and sample tables")
    render_report_links()
    render_sample_tables(candidates, executions, settlements, ticks)

    st.header("Limitations")
    st.markdown(
        """
        - Public samples are anonymized, downsampled, and normalized.
        - Dashboard metrics are demonstration diagnostics, not complete historical performance.
        - Backtests, reports, and visualizations are not equivalent to live execution.
        - The app does not provide strategy parameters, order routing, wallet operations, or trading advice.
        - ML and risk outputs are workflow demonstrations and require stricter validation before any serious use.
        """
    )


if __name__ == "__main__":
    main()
