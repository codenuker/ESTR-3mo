"""Standalone ER3 Fly6-Fly10 analysis script.

Run from this folder:
    python analysis_notebook.py --csv data/er3_flies_updated.csv --out outputs

It produces CSV tables and PNG plots corresponding to the six requested sections.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

import er3_analysis as ea


FLIES = [f"Fly{i}" for i in range(6, 11)]
ALL_FLIES = [f"Fly{i}" for i in range(1, 11)]


def save_table(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def section_1_rolling_impact(df: pd.DataFrame, out: Path) -> None:
    rolling = ea.rolling_stats(df, FLIES, windows=(20, 60))
    flags20, regimes20 = ea.rolling_mean_shift_regimes(df, FLIES, 20)
    flags60, regimes60 = ea.rolling_mean_shift_regimes(df, FLIES, 60)
    _, roll_avg, roll_summary = ea.roll_pattern(df, FLIES)

    save_table(flags20, out / "section1_rolling_shift_flags_20d.csv")
    save_table(flags60, out / "section1_rolling_shift_flags_60d.csv")
    save_table(regimes20, out / "section1_rolling_shift_regimes_20d.csv")
    save_table(regimes60, out / "section1_rolling_shift_regimes_60d.csv")
    save_table(roll_summary, out / "section1_roll_pattern_summary.csv")

    for fly in FLIES:
        for window in (20, 60):
            s = df[fly].dropna()
            mean = s.rolling(window).mean()
            std = s.rolling(window).std(ddof=1)
            plt.figure(figsize=(12, 5))
            plt.plot(s.index, s.values, label=fly, linewidth=1)
            plt.plot(mean.index, mean.values, label=f"{window}d mean", linewidth=1.4)
            plt.plot(mean.index, (mean + std).values, label="mean +1 std", linestyle="--", linewidth=1)
            plt.plot(mean.index, (mean - std).values, label="mean -1 std", linestyle="--", linewidth=1)
            plt.title(f"{fly}: rolling {window}d mean ± 1 std")
            plt.ylabel("Fly price")
            plt.legend()
            plt.tight_layout()
            plt.savefig(out / f"section1_{fly}_rolling_{window}d.png", dpi=160)
            plt.close()

    if not roll_avg.empty:
        plt.figure(figsize=(10, 5))
        for fly, g in roll_avg.groupby("Fly"):
            plt.plot(g["Relative Day"], g["Level"], marker="o", label=fly)
        plt.axvline(0, linestyle="--")
        plt.title("Average Fly6-Fly10 level around approximate monthly roll")
        plt.xlabel("Trading days around roll")
        plt.ylabel("Average fly level")
        plt.legend()
        plt.tight_layout()
        plt.savefig(out / "section1_average_roll_window.png", dpi=160)
        plt.close()

    print("\nSECTION 1: Rolling shift regimes, latest rows")
    print(regimes60.tail(10).to_string(index=False))
    print("\nRoll summary")
    print(roll_summary.to_string(index=False))


def section_2_range_half_life(df: pd.DataFrame, out: Path) -> pd.DataFrame:
    summary = ea.current_summary(df, FLIES)
    cols = [
        "Fly", "Current Value", "Historical Min", "Historical Max", "P05", "P95",
        "Percentile Rank", "Percentile Rank 252d", "Z-Score 60d", "Half-Life Days",
        "AR1 Phi", "Half-Life p-value", "Signal",
    ]
    summary_out = summary[cols].copy()
    save_table(summary_out, out / "section2_range_half_life_summary.csv")
    print("\nSECTION 2: Range / half-life summary")
    print(summary_out.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))
    return summary


def section_3_signals_backtests(df: pd.DataFrame, out: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    trades, equity, stats = ea.backtest_all(df, FLIES)
    save_table(trades, out / "section3_backtest_trades.csv")
    save_table(equity, out / "section3_equity_curves.csv")
    save_table(stats, out / "section3_backtest_stats.csv")

    for strategy in ["zscore", "bollinger", "percentile"]:
        g = equity[equity["Strategy"] == strategy]
        if g.empty:
            continue
        plt.figure(figsize=(12, 5))
        for fly, sub in g.groupby("Fly"):
            plt.plot(sub["Date"], sub["Equity_ticks"], label=fly)
        plt.title(f"Equity curves, {strategy} strategy")
        plt.ylabel("Cumulative P&L, ticks")
        plt.legend()
        plt.tight_layout()
        plt.savefig(out / f"section3_equity_{strategy}.png", dpi=160)
        plt.close()

    print("\nSECTION 3: Backtest stats")
    print(stats.sort_values(["Fly", "Strategy"]).to_string(index=False, float_format=lambda x: f"{x:,.4f}"))
    return trades, equity, stats


def corr_annotation(corr: pd.DataFrame, pvals: pd.DataFrame, p_cutoff: float = 0.05) -> pd.DataFrame:
    annot = corr.copy().astype(str)
    for r in corr.index:
        for c in corr.columns:
            marker = "†" if r != c and pd.notna(pvals.loc[r, c]) and pvals.loc[r, c] > p_cutoff else ""
            annot.loc[r, c] = f"{corr.loc[r, c]:.2f}{marker}"
    return annot


def section_4_5_correlations(df: pd.DataFrame, out: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    changes, corr, pvals = ea.correlation_and_pvalues(df, ALL_FLIES)
    rolling_corr = ea.rolling_correlations(df, FLIES, 60)
    save_table(corr.reset_index().rename(columns={"index": "Fly"}), out / "section4_5_correlation_matrix.csv")
    save_table(pvals.reset_index().rename(columns={"index": "Fly"}), out / "section4_5_correlation_pvalues.csv")
    save_table(rolling_corr, out / "section4_rolling_60d_correlations_fly6_10.csv")

    plt.figure(figsize=(10, 8))
    sns.heatmap(corr, annot=corr_annotation(corr, pvals), fmt="", center=0, cmap="vlag", vmin=-1, vmax=1, square=True)
    plt.title("Daily change correlation matrix, Fly1-Fly10 († = p > 0.05)")
    plt.tight_layout()
    plt.savefig(out / "section5_heatmap_all_flies.png", dpi=180)
    plt.close()

    focus = corr.loc[FLIES, FLIES]
    p_focus = pvals.loc[FLIES, FLIES]
    plt.figure(figsize=(7, 6))
    sns.heatmap(focus, annot=corr_annotation(focus, p_focus), fmt="", center=0, cmap="vlag", vmin=-1, vmax=1, square=True)
    plt.title("Daily change correlation matrix, Fly6-Fly10 († = p > 0.05)")
    plt.tight_layout()
    plt.savefig(out / "section5_heatmap_fly6_10.png", dpi=180)
    plt.close()

    if not rolling_corr.empty:
        plt.figure(figsize=(12, 5))
        for pair, g in rolling_corr.dropna().groupby("Pair"):
            plt.plot(g["Date"], g["Correlation"], label=pair, linewidth=1)
        plt.axhline(0, linewidth=1)
        plt.title("Rolling 60d correlations, Fly6-Fly10 daily changes")
        plt.ylabel("Correlation")
        plt.legend(ncol=2)
        plt.tight_layout()
        plt.savefig(out / "section4_rolling_60d_correlations.png", dpi=160)
        plt.close()

    print("\nSECTION 4/5: Focused correlation matrix")
    print(focus.to_string(float_format=lambda x: f"{x:,.3f}"))
    print("\nFocused p-values")
    print(p_focus.to_string(float_format=lambda x: f"{x:,.4g}"))
    return corr, pvals


def section_6_hedging_pca(df: pd.DataFrame, out: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    hedge, residuals, explained, loadings = ea.hedge_matrix_and_pca(df, FLIES)
    save_table(hedge.reset_index().rename(columns={"index": "Target Fly"}), out / "section6_hedge_matrix.csv")
    save_table(residuals, out / "section6_residual_variance.csv")
    save_table(explained, out / "section6_pca_explained_variance.csv")
    save_table(loadings.reset_index().rename(columns={"index": "Fly"}), out / "section6_pca_loadings.csv")

    plt.figure(figsize=(7, 6))
    sns.heatmap(hedge, annot=True, fmt="+.2f", center=0, cmap="vlag")
    plt.title("OLS hedge ratio matrix: lots to trade per +1 target fly")
    plt.tight_layout()
    plt.savefig(out / "section6_hedge_matrix_heatmap.png", dpi=180)
    plt.close()

    plt.figure(figsize=(6, 5))
    sns.heatmap(loadings, annot=True, fmt="+.2f", center=0, cmap="vlag", vmin=-1, vmax=1)
    plt.title("PCA factor loadings")
    plt.tight_layout()
    plt.savefig(out / "section6_pca_loadings_heatmap.png", dpi=180)
    plt.close()

    print("\nSECTION 6: Hedge matrix")
    print(hedge.to_string(float_format=lambda x: f"{x:+.3f}"))
    print("\nResidual variance")
    print(residuals.to_string(index=False, float_format=lambda x: f"{x:,.6f}"))
    print("\nPCA explained variance")
    print(explained.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))
    print("\nPCA loadings")
    print(loadings.to_string(float_format=lambda x: f"{x:+.3f}"))
    return hedge, residuals, explained, loadings


def final_dashboard_summary(summary: pd.DataFrame, hedge: pd.DataFrame, out: Path) -> pd.DataFrame:
    dash = ea.suggested_action(summary, hedge)
    final_cols = ["Fly", "Current Value", "Percentile Rank 252d", "Z-Score 60d", "Signal", "Suggested Action", "Key Hedge"]
    final = dash[final_cols].copy()
    save_table(final, out / "trading_dashboard_summary.csv")
    print("\nTRADING DASHBOARD SUMMARY")
    print(final.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))
    return final


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="data/er3_flies_updated.csv")
    parser.add_argument("--out", default="outputs")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    df = ea.load_csv(args.csv)
    print(f"Loaded {len(df):,} observations from {df.index.min().date()} to {df.index.max().date()}")

    section_1_rolling_impact(df, out)
    summary = section_2_range_half_life(df, out)
    section_3_signals_backtests(df, out)
    section_4_5_correlations(df, out)
    hedge, residuals, explained, loadings = section_6_hedging_pca(df, out)
    final_dashboard_summary(summary, hedge, out)


if __name__ == "__main__":
    main()
