from __future__ import annotations

from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import er3_analysis as ea

st.set_page_config(page_title="ER3 Fly6-Fly10 Statistical Dashboard", layout="wide")

APP_DIR = Path(__file__).resolve().parent
DEFAULT_DATA = APP_DIR / "data" / "er3_flies_updated.csv"
FLIES = [f"Fly{i}" for i in range(6, 11)]
ALL_FLIES = [f"Fly{i}" for i in range(1, 11)]


def fmt_price(x: float) -> str:
    if pd.isna(x):
        return ""
    return f"{x:.4f}"


def fmt_pct(x: float) -> str:
    if pd.isna(x):
        return ""
    return f"{100*x:.1f}%" if abs(x) <= 1.0 else f"{x:.1f}%"


@st.cache_data(show_spinner=False)
def load_default_data(dayfirst: bool = True) -> pd.DataFrame:
    return ea.load_csv(DEFAULT_DATA, dayfirst=dayfirst)


@st.cache_data(show_spinner=False)
def load_uploaded_data(uploaded_file, dayfirst: bool = True) -> pd.DataFrame:
    return ea.load_csv(uploaded_file, dayfirst=dayfirst)


def get_data() -> pd.DataFrame:
    if "edited_df" in st.session_state:
        return st.session_state["edited_df"].copy()
    return load_default_data(dayfirst=st.session_state.get("dayfirst", True)).copy()


def signal_badge(signal: str) -> str:
    if signal == "LONG":
        return "🟢 LONG"
    if signal == "SHORT":
        return "🔴 SHORT"
    if signal == "CONFLICT":
        return "🟠 CONFLICT"
    return "⚪ NO ENTRY"


def annotated_corr(corr: pd.DataFrame, pvals: pd.DataFrame, p_cutoff: float = 0.05) -> pd.DataFrame:
    labels = corr.copy().astype(str)
    for r in corr.index:
        for c in corr.columns:
            marker = "†" if (r != c and pd.notna(pvals.loc[r, c]) and pvals.loc[r, c] > p_cutoff) else ""
            labels.loc[r, c] = f"{corr.loc[r, c]:.2f}{marker}"
    return labels


def plot_heatmap(matrix: pd.DataFrame, title: str, text: pd.DataFrame | None = None, zmin: float = -1, zmax: float = 1):
    fig = go.Figure(
        data=go.Heatmap(
            z=matrix.values,
            x=matrix.columns,
            y=matrix.index,
            text=text.values if text is not None else np.round(matrix.values, 2),
            texttemplate="%{text}",
            colorscale="RdBu",
            reversescale=False,
            zmin=zmin,
            zmax=zmax,
            colorbar=dict(title="Value"),
        )
    )
    fig.update_layout(title=title, height=520, margin=dict(l=40, r=40, t=70, b=40))
    return fig


def plot_rolling_band(df: pd.DataFrame, fly: str, window: int):
    s = df[fly].dropna()
    mean = s.rolling(window).mean()
    std = s.rolling(window).std(ddof=1)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=s.index, y=s, name=fly, mode="lines"))
    fig.add_trace(go.Scatter(x=mean.index, y=mean, name=f"{window}d mean", mode="lines"))
    fig.add_trace(go.Scatter(x=mean.index, y=mean + std, name="mean +1σ", mode="lines", line=dict(dash="dash")))
    fig.add_trace(go.Scatter(x=mean.index, y=mean - std, name="mean -1σ", mode="lines", line=dict(dash="dash")))
    fig.update_layout(title=f"{fly}: rolling {window}d mean ± 1σ", height=420, yaxis_title="Fly price", xaxis_title="Date")
    return fig


def make_current_tables(df: pd.DataFrame, thresholds: ea.SignalThresholds):
    summary = ea.current_summary(df, FLIES, thresholds)
    hedge, residuals, explained, loadings = ea.hedge_matrix_and_pca(df, FLIES)
    dashboard = ea.suggested_action(summary, hedge)
    trades, equity, bt_stats = ea.backtest_all(df, FLIES, thresholds=thresholds)

    if not equity.empty:
        latest_positions = (
            equity.sort_values("Date")
            .groupby(["Fly", "Strategy"])["Position"]
            .last()
            .unstack("Strategy")
            .rename(columns={"zscore": "Open Z60", "bollinger": "Open BB20", "percentile": "Open Pct252"})
        )
        dashboard = dashboard.merge(latest_positions, left_on="Fly", right_index=True, how="left")
    return summary, dashboard, hedge, residuals, explained, loadings, trades, equity, bt_stats


# ----------------------------- Sidebar -----------------------------
st.sidebar.title("ER3 Dashboard Controls")
st.sidebar.caption("Upload an updated CSV, or use the bundled sample file.")
st.session_state["dayfirst"] = st.sidebar.checkbox("Parse dates as day-first", value=True)
uploaded = st.sidebar.file_uploader("Upload full ER/fly CSV", type=["csv"])

if uploaded is not None:
    try:
        st.session_state["edited_df"] = load_uploaded_data(uploaded, dayfirst=st.session_state["dayfirst"])
        st.sidebar.success("Uploaded CSV loaded and flies recomputed from ER columns where possible.")
    except Exception as exc:
        st.sidebar.error(f"Could not read CSV: {exc}")

if st.sidebar.button("Reset to bundled sample"):
    st.session_state.pop("edited_df", None)
    st.rerun()

st.sidebar.divider()
st.sidebar.subheader("Signal thresholds")
z_entry = st.sidebar.number_input("Z-score entry", value=1.5, min_value=0.5, max_value=5.0, step=0.1)
bb_std = st.sidebar.number_input("Bollinger std multiplier", value=2.0, min_value=1.0, max_value=4.0, step=0.25)
pct_low = st.sidebar.number_input("Low percentile entry", value=10.0, min_value=1.0, max_value=49.0, step=1.0)
pct_high = st.sidebar.number_input("High percentile entry", value=90.0, min_value=51.0, max_value=99.0, step=1.0)
thresholds = ea.SignalThresholds(z_entry=z_entry, bb_std=bb_std, pct_low=pct_low, pct_high=pct_high)

df = get_data()
if df.empty:
    st.error("No data loaded.")
    st.stop()

latest_date = df.index.max().date()
first_date = df.index.min().date()

summary, dashboard, hedge, residuals, explained, loadings, trades, equity, bt_stats = make_current_tables(df, thresholds)
changes, corr_all, pvals_all = ea.correlation_and_pvalues(df, ALL_FLIES)
rolling_corr = ea.rolling_correlations(df, FLIES, 60)
_, roll_avg, roll_summary = ea.roll_pattern(df, FLIES)
flags20, regimes20 = ea.rolling_mean_shift_regimes(df, FLIES, 20)
flags60, regimes60 = ea.rolling_mean_shift_regimes(df, FLIES, 60)

# ----------------------------- Header -----------------------------
st.title("ER3 Fly6-Fly10 Statistical Trading Dashboard")
st.caption(
    f"Dataset: {first_date} to {latest_date}. Fly values are recomputed from ER columns when available. "
    "P&L: 1 tick = 0.005 price points = EUR 12.50."
)

cards = st.columns(5)
for col, (_, row) in zip(cards, dashboard.iterrows()):
    with col:
        st.metric(
            label=row["Fly"],
            value=f"{row['Current Value']:.4f}",
            delta=f"Z60 {row['Z-Score 60d']:+.2f} | pct252 {row['Percentile Rank 252d']:.1f}%",
        )
        st.write(signal_badge(row["Signal"]))

# ----------------------------- Tabs -----------------------------
tabs = st.tabs([
    "Dashboard",
    "Rolling Impact",
    "Range & Half-Life",
    "Signals & Backtests",
    "Correlations",
    "Hedging & PCA",
    "Daily Update",
])

with tabs[0]:
    st.subheader("One-page trading dashboard")
    view_cols = [
        "Fly",
        "Observations",
        "Current Value",
        "Current Ticks",
        "Percentile Rank 252d",
        "Z-Score 60d",
        "Z Signal",
        "BB Signal",
        "Percentile Signal",
        "Signal",
        "Suggested Action",
        "Key Hedge",
        "Open Z60",
        "Open BB20",
        "Open Pct252",
    ]
    display = dashboard[[c for c in view_cols if c in dashboard.columns]].copy()
    st.dataframe(
        display.style.format({
            "Observations": "{:.0f}",
            "Current Value": "{:.4f}",
            "Current Ticks": "{:.1f}",
            "Percentile Rank 252d": "{:.1f}%",
            "Z-Score 60d": "{:+.2f}",
            "Open Z60": "{:.0f}",
            "Open BB20": "{:.0f}",
            "Open Pct252": "{:.0f}",
        }),
        use_container_width=True,
        hide_index=True,
    )
    st.info("Open positions use convention +1 = long fly, -1 = short fly, 0 = flat under each historical rule.")

    left, right = st.columns([1.2, 1])
    with left:
        st.subheader("Current distribution snapshot")
        long_form = summary.melt(id_vars="Fly", value_vars=["Historical Min", "P05", "Current Value", "P95", "Historical Max"], var_name="Metric", value_name="Value")
        fig = px.line(long_form, x="Metric", y="Value", color="Fly", markers=True, title="Min / robust range / current / max")
        fig.update_layout(height=420)
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Best current hedge basket")
        st.dataframe(hedge.style.format("{:+.3f}"), use_container_width=True)

with tabs[1]:
    st.subheader("Rolling impact analysis")
    fly_select = st.selectbox("Fly", FLIES, index=0, key="rolling_fly")
    window_select = st.radio("Window", [20, 60], horizontal=True, key="rolling_window")
    st.plotly_chart(plot_rolling_band(df, fly_select, window_select), use_container_width=True)

    st.markdown("**Rolling mean shift regimes**: |rolling mean − long-run mean| > 1 long-run standard deviation.")
    rtab1, rtab2 = st.tabs(["20d regimes", "60d regimes"])
    with rtab1:
        st.dataframe(regimes20.sort_values(["Fly", "Start"]).style.format({"AverageRollingMean": "{:.4f}", "ShiftSigma": "{:+.2f}"}), use_container_width=True, hide_index=True)
    with rtab2:
        st.dataframe(regimes60.sort_values(["Fly", "Start"]).style.format({"AverageRollingMean": "{:.4f}", "ShiftSigma": "{:+.2f}"}), use_container_width=True, hide_index=True)

    st.subheader("Average behaviour around front-contract roll window")
    if not roll_avg.empty:
        fig = px.line(roll_avg, x="Relative Day", y="Level", color="Fly", markers=True, title="Average fly level around approximate monthly roll date")
        fig.add_vline(x=0, line_dash="dash")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(roll_summary.style.format({
            "Pre Roll Avg": "{:.4f}",
            "Post Roll Avg": "{:.4f}",
            "Post minus Pre": "{:+.4f}",
            "T+1 minus T-1 mean": "{:+.4f}",
            "T+1 minus T-1 std": "{:.4f}",
        }), use_container_width=True, hide_index=True)
    else:
        st.warning("Not enough data to compute roll pattern.")

with tabs[2]:
    st.subheader("Min / max / robust range / percentile / half-life")
    range_cols = [
        "Fly",
        "Current Value",
        "Historical Min",
        "Historical Max",
        "P05",
        "P95",
        "Percentile Rank",
        "Percentile Rank 252d",
        "Half-Life Days",
        "AR1 Phi",
        "Half-Life p-value",
    ]
    st.dataframe(summary[range_cols].style.format({
        "Current Value": "{:.4f}",
        "Historical Min": "{:.4f}",
        "Historical Max": "{:.4f}",
        "P05": "{:.4f}",
        "P95": "{:.4f}",
        "Percentile Rank": "{:.1f}%",
        "Percentile Rank 252d": "{:.1f}%",
        "Half-Life Days": "{:.1f}",
        "AR1 Phi": "{:.3f}",
        "Half-Life p-value": "{:.4f}",
    }), use_container_width=True, hide_index=True)

with tabs[3]:
    st.subheader("Entry / exit signals and backtests")
    c1, c2 = st.columns(2)
    with c1:
        strategy = st.selectbox("Strategy", ["zscore", "bollinger", "percentile"], index=0)
    with c2:
        fly_bt = st.selectbox("Fly", FLIES, index=0, key="bt_fly")

    if not bt_stats.empty:
        st.markdown("**Closed trade statistics**")
        st.dataframe(bt_stats.sort_values(["Fly", "Strategy"]).style.format({
            "Win Rate": "{:.1%}",
            "Avg PnL ticks": "{:+.2f}",
            "Avg PnL EUR": "€{:+.2f}",
            "Median PnL ticks": "{:+.2f}",
            "Total PnL ticks": "{:+.1f}",
            "Total PnL EUR": "€{:+.2f}",
            "Avg Holding Days": "{:.1f}",
        }), use_container_width=True, hide_index=True)

    eq_slice = equity[(equity["Strategy"] == strategy) & (equity["Fly"] == fly_bt)]
    if not eq_slice.empty:
        fig = px.line(eq_slice, x="Date", y="Equity_ticks", title=f"{fly_bt} {strategy} equity curve, ticks")
        st.plotly_chart(fig, use_container_width=True)
    tr_slice = trades[(trades["Strategy"] == strategy) & (trades["Fly"] == fly_bt)]
    st.dataframe(tr_slice.tail(25).style.format({"Entry": "{:.4f}", "Exit": "{:.4f}", "PnL_ticks": "{:+.1f}", "PnL_EUR": "€{:+.2f}"}), use_container_width=True, hide_index=True)
    st.download_button("Download all trades CSV", data=trades.to_csv(index=False), file_name="er3_fly_backtest_trades.csv", mime="text/csv")

with tabs[4]:
    st.subheader("Correlation of daily changes")
    labels_all = annotated_corr(corr_all, pvals_all)
    st.plotly_chart(plot_heatmap(corr_all, "All Fly1-Fly10 daily-change correlations († = p > 0.05)", labels_all), use_container_width=True)
    focus = corr_all.loc[FLIES, FLIES]
    labels_focus = annotated_corr(focus, pvals_all.loc[FLIES, FLIES])
    st.plotly_chart(plot_heatmap(focus, "Focused Fly6-Fly10 daily-change correlations († = p > 0.05)", labels_focus), use_container_width=True)

    if not rolling_corr.empty:
        fig = px.line(rolling_corr.dropna(), x="Date", y="Correlation", color="Pair", title="Rolling 60d correlations: Fly6-Fly10")
        fig.update_layout(height=520)
        st.plotly_chart(fig, use_container_width=True)

with tabs[5]:
    st.subheader("OLS hedge matrix")
    st.caption("Rows are target flies. For a long +1 lot in the row fly, trade the displayed number of lots in each column fly.")
    st.plotly_chart(plot_heatmap(hedge, "OLS hedge ratios, Fly6-Fly10", hedge.round(2).astype(str), zmin=-0.6, zmax=0.6), use_container_width=True)
    st.dataframe(hedge.style.format("{:+.3f}"), use_container_width=True)

    st.subheader("Residual variance after hedging")
    st.dataframe(residuals.style.format({
        "Residual Variance": "{:.8f}",
        "Target Variance": "{:.8f}",
        "Residual Var %": "{:.1%}",
        "Variance Reduction %": "{:.1%}",
        "R2": "{:.1%}",
    }), use_container_width=True, hide_index=True)

    st.subheader("PCA on standardized daily changes")
    col1, col2 = st.columns([1, 1])
    with col1:
        fig = px.bar(explained, x="PC", y="Explained Variance", title="Explained variance")
        fig.update_yaxes(tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        st.plotly_chart(plot_heatmap(loadings, "PCA loadings", loadings.round(2).astype(str), zmin=-1, zmax=1), use_container_width=True)

with tabs[6]:
    st.subheader("Daily update: upload or manually append a row")
    st.markdown(
        "Use the sidebar uploader for a complete refreshed CSV. For a single new settlement day, fill ER1–ER12 below; "
        "Fly1–Fly10 are recomputed automatically and the updated CSV can be downloaded."
    )
    last = df.loc[df.index.max()]
    default_next_date = pd.Timestamp(df.index.max()) + pd.offsets.BDay(1)

    with st.form("manual_row_form"):
        new_date = st.date_input("New settlement date", value=default_next_date.date())
        cols = st.columns(4)
        er_inputs = {}
        for idx, er in enumerate(ea.ALL_ERS):
            with cols[idx % 4]:
                default_val = float(last[er]) if er in last.index and pd.notna(last[er]) else 97.50
                er_inputs[er] = st.number_input(er, value=default_val, step=0.0025, format="%.4f")
        submitted = st.form_submit_button("Append / replace daily row and recompute signals")
        if submitted:
            try:
                st.session_state["edited_df"] = ea.append_manual_row(df, new_date, er_inputs)
                st.success(f"Row for {new_date} added/replaced. Signals recalculated.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not append row: {exc}")

    st.download_button(
        "Download current updated CSV",
        data=ea.to_download_csv(df),
        file_name="er3_flies_updated_with_signals_input.csv",
        mime="text/csv",
    )
    st.subheader("Latest 10 observations")
    st.dataframe(df.tail(10).reset_index(), use_container_width=True, hide_index=True)
