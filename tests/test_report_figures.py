from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
FIGURE_DIR = ROOT / "reports" / "figures"


def test_generate_report_figures_creates_expected_pngs():
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_report_figures.py")],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        check=True,
    )
    expected = {
        "signal_funnel.png",
        "execution_status_breakdown.png",
        "spread_distribution.png",
        "fill_rate_by_edge_bucket.png",
        "calibration_curve.png",
        "monte_carlo_terminal_pnl.png",
        "monte_carlo_drawdown.png",
    }
    for filename in expected:
        path = FIGURE_DIR / filename
        assert path.exists()
        assert path.stat().st_size > 0
