from __future__ import annotations

import base64
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"


def img_tag(path: Path, alt: str, width: str = "100%") -> str:
    if not path.exists():
        return ""
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'<img src="data:image/png;base64,{data}" alt="{alt}" style="width:{width}; max-width:100%; border:1px solid #e5e7eb; border-radius:8px;" />'


def table_html(csv_name: str, cols=None, fmt=None, max_rows=None) -> str:
    p = OUT / csv_name
    if not p.exists():
        return ""
    df = pd.read_csv(p)
    if cols:
        df = df[[c for c in cols if c in df.columns]]
    if max_rows:
        df = df.head(max_rows)
    styler = df.style
    if fmt:
        styler = styler.format(fmt)
    return styler.hide(axis="index").to_html()


def main() -> None:
    dashboard = table_html(
        "trading_dashboard_summary.csv",
        fmt={
            "Current Value": "{:.4f}",
            "Percentile Rank 252d": "{:.1f}%",
            "Z-Score 60d": "{:+.2f}",
        },
    )
    range_table = table_html(
        "section2_range_half_life_summary.csv",
        fmt={
            "Current Value": "{:.4f}", "Historical Min": "{:.4f}", "Historical Max": "{:.4f}",
            "P05": "{:.4f}", "P95": "{:.4f}", "Percentile Rank": "{:.1f}%",
            "Percentile Rank 252d": "{:.1f}%", "Z-Score 60d": "{:+.2f}", "Half-Life Days": "{:.1f}",
        },
    )
    bt_table = table_html(
        "section3_backtest_stats.csv",
        fmt={
            "Win Rate": "{:.1%}", "Avg PnL ticks": "{:+.2f}", "Avg PnL EUR": "€{:+.2f}",
            "Total PnL ticks": "{:+.1f}", "Total PnL EUR": "€{:+.2f}", "Avg Holding Days": "{:.1f}",
        },
    )
    roll_table = table_html(
        "section1_roll_pattern_summary.csv",
        fmt={"Pre Roll Avg": "{:.4f}", "Post Roll Avg": "{:.4f}", "Post minus Pre": "{:+.4f}", "T+1 minus T-1 mean": "{:+.4f}", "T+1 minus T-1 std": "{:.4f}"},
    )
    resid_table = table_html(
        "section6_residual_variance.csv",
        fmt={"Residual Variance": "{:.8f}", "Target Variance": "{:.8f}", "Residual Var %": "{:.1%}", "Variance Reduction %": "{:.1%}", "R2": "{:.1%}"},
    )
    pca_table = table_html("section6_pca_explained_variance.csv", fmt={"Explained Variance": "{:.1%}"})

    rolling_imgs = "".join(
        f"<div class='chart-card'><h4>{fly} rolling 60d</h4>{img_tag(OUT / f'section1_{fly}_rolling_60d.png', fly)}</div>"
        for fly in ["Fly6", "Fly7", "Fly8", "Fly9", "Fly10"]
    )

    html = f"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>ER3 Fly6-Fly10 Current Dashboard</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; margin: 28px; color: #111827; background: #f9fafb; }}
h1 {{ margin-bottom: 0; }}
h2 {{ margin-top: 34px; border-bottom: 1px solid #d1d5db; padding-bottom: 6px; }}
h3, h4 {{ margin-bottom: 8px; }}
.note {{ color: #4b5563; margin-top: 6px; }}
.card {{ background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 18px; margin: 18px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }}
.grid2 {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }}
.grid3 {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }}
.chart-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }}
.chart-card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border: 1px solid #e5e7eb; padding: 7px 8px; text-align: right; }}
th {{ background: #111827; color: white; text-align: center; }}
td:first-child, th:first-child {{ text-align: left; }}
@media (max-width: 1000px) {{ .grid2, .grid3, .chart-grid {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<h1>ER3 Fly6-Fly10 Current Statistical Dashboard</h1>
<p class="note">Generated from uploaded CSV. Butterfly values are recomputed from ER columns where possible. P&L convention: 1 tick = 0.005 = €12.50 per 1-lot package.</p>

<div class="card">
<h2>Trading Dashboard Summary</h2>
{dashboard}
</div>

<div class="card">
<h2>Range, percentile and half-life</h2>
{range_table}
</div>

<div class="card">
<h2>Rolling impact and roll-window diagnostics</h2>
<div class="chart-grid">{rolling_imgs}</div>
<h3>Average roll-window behaviour</h3>
<div class="grid2">
<div>{img_tag(OUT / 'section1_average_roll_window.png', 'Average roll window')}</div>
<div>{roll_table}</div>
</div>
</div>

<div class="card">
<h2>Backtest statistics and equity curves</h2>
{bt_table}
<div class="grid3">
<div>{img_tag(OUT / 'section3_equity_zscore.png', 'Z-score equity')}</div>
<div>{img_tag(OUT / 'section3_equity_bollinger.png', 'Bollinger equity')}</div>
<div>{img_tag(OUT / 'section3_equity_percentile.png', 'Percentile equity')}</div>
</div>
</div>

<div class="card">
<h2>Correlation matrices</h2>
<p class="note">† on matrix annotations marks p-value &gt; 0.05.</p>
<div class="grid2">
<div>{img_tag(OUT / 'section5_heatmap_all_flies.png', 'All flies heatmap')}</div>
<div>{img_tag(OUT / 'section5_heatmap_fly6_10.png', 'Fly6-Fly10 heatmap')}</div>
</div>
<div style="margin-top:18px;">{img_tag(OUT / 'section4_rolling_60d_correlations.png', 'Rolling correlations')}</div>
</div>

<div class="card">
<h2>Hedging matrix and PCA</h2>
<div class="grid2">
<div>{img_tag(OUT / 'section6_hedge_matrix_heatmap.png', 'Hedge matrix')}</div>
<div>{img_tag(OUT / 'section6_pca_loadings_heatmap.png', 'PCA loadings')}</div>
</div>
<h3>Residual variance after OLS basket hedge</h3>
{resid_table}
<h3>PCA explained variance</h3>
{pca_table}
</div>

</body>
</html>
"""
    dest = OUT / "er3_current_dashboard_report.html"
    dest.write_text(html, encoding="utf-8")
    (ROOT.parent / "er3_current_dashboard_report.html").write_text(html, encoding="utf-8")
    print(dest)


if __name__ == "__main__":
    main()
