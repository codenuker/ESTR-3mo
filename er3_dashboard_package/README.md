# ER3 Fly6-Fly10 Statistical Dashboard

A local Streamlit dashboard for ER3 3-month Euribor futures butterflies. It computes rolling statistics, range/percentile signals, mean-reversion backtests, correlations, OLS hedges and PCA loadings for Fly6-Fly10.

## Files

- `app.py` - interactive dashboard website.
- `er3_analysis.py` - reusable analytics library.
- `analysis_notebook.py` - standalone script that generates all requested tables and PNG charts.
- `data/er3_flies_updated.csv` - current input file bundled from the uploaded CSV.
- `outputs/` - generated current-analysis tables and plots.
- `requirements.txt` - Python package requirements.

## Quick start

```bash
cd er3_dashboard_package
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Streamlit will open a local website in your browser. Use the sidebar to upload a refreshed CSV at any time.

## Daily update workflow

You have two options:

1. Upload a refreshed full CSV in the sidebar. The app cleans it, renames `FER1`...`FER12` to `ER1`...`ER12`, and recomputes `Fly1`...`Fly10` from the ER curve where possible.
2. Use the **Daily Update** tab to manually enter the next settlement date and `ER1`...`ER12`. The dashboard appends/replaces that date, recomputes all flies and refreshes all signals. Download the updated CSV and use that as tomorrow's input.

## Trading and P&L conventions

- `FlyN = ERN - 2*ER(N+1) + ER(N+2)`.
- Position convention: `+1` means long the fly value; `-1` means short the fly value.
- P&L convention: `PnL ticks = position * (exit - entry) / 0.005`.
- EUR P&L uses `EUR 12.50` per tick per 1-lot package.
- No transaction costs, slippage, bid/offer or margin constraints are included.

## Roll-date assumption

The roll-window chart uses a simple monthly approximation: last trading day equals two business days before the third Wednesday of each delivery month. This is suitable for a statistical roll-window diagnostic, but the app does not model exchange holidays.

## Standalone analysis script

```bash
cd er3_dashboard_package
python analysis_notebook.py --csv data/er3_flies_updated.csv --out outputs
```

The script writes all current tables and charts to `outputs/`, including rolling bands, signal regimes, backtest trades/equity, correlation matrices, hedge matrices and PCA loadings.
