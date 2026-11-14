"""Core analytics for ER3 butterfly dashboard.

Assumptions
-----------
- Butterfly value = ER(N) - 2*ER(N+1) + ER(N+2) for FlyN.
- P&L is measured on the quoted butterfly value. One fly tick = 0.005 price points.
- EUR P&L uses the user-specified tick value of EUR 12.50 per tick per 1-lot package.
- Roll windows use a simple exchange-business-day approximation: last trading day is two
  business days before the third Wednesday of each month. This ignores exchange holidays.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.decomposition import PCA
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler

TICK_SIZE = 0.005
TICK_VALUE_EUR = 12.50
DEFAULT_FLY_UNIVERSE = [f"Fly{i}" for i in range(6, 11)]
ALL_FLIES = [f"Fly{i}" for i in range(1, 11)]
ALL_ERS = [f"ER{i}" for i in range(1, 13)]


@dataclass(frozen=True)
class SignalThresholds:
    z_entry: float = 1.5
    bb_std: float = 2.0
    pct_low: float = 10.0
    pct_high: float = 90.0
    pct_exit: float = 50.0
    z_window: int = 60
    bb_window: int = 20
    pct_window: int = 252


def _detect_date_column(df: pd.DataFrame) -> str:
    candidates = ["Date", "date", "Timestamp", "timestamp", "TradeDate", "trade_date"]
    for c in candidates:
        if c in df.columns:
            return c
    return str(df.columns[0])


def clean_data(raw: pd.DataFrame, dayfirst: bool = True) -> pd.DataFrame:
    """Clean uploaded ER3/fly CSV and return a Date-indexed DataFrame.

    The function accepts either ER1...ER12 or FER1...FER12 column names. If ER columns are
    available, it recomputes Fly1...Fly10 from the futures curve, which fixes spreadsheet
    artefacts such as '#VALUE!' in historical fly columns.
    """
    df = raw.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~pd.Index(df.columns).str.match(r"^Unnamed")]

    rename = {c: c.replace("FER", "ER", 1) for c in df.columns if c.startswith("FER")}
    df = df.rename(columns=rename)

    date_col = _detect_date_column(df)
    df[date_col] = pd.to_datetime(df[date_col], dayfirst=dayfirst, errors="coerce")
    df = df.dropna(subset=[date_col]).rename(columns={date_col: "Date"})

    for c in df.columns:
        if c != "Date":
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Recompute flies from ER futures when possible.
    for i in range(1, 11):
        er_cols = [f"ER{i}", f"ER{i+1}", f"ER{i+2}"]
        if all(c in df.columns for c in er_cols):
            df[f"Fly{i}"] = df[er_cols[0]] - 2.0 * df[er_cols[1]] + df[er_cols[2]]

    df = df.sort_values("Date").drop_duplicates("Date", keep="last").set_index("Date")
    return df


def load_csv(path_or_buffer, dayfirst: bool = True) -> pd.DataFrame:
    return clean_data(pd.read_csv(path_or_buffer), dayfirst=dayfirst)


def available_flies(df: pd.DataFrame, universe: Optional[Sequence[str]] = None) -> List[str]:
    base = list(universe) if universe is not None else ALL_FLIES
    return [f for f in base if f in df.columns]


def rolling_stats(df: pd.DataFrame, flies: Sequence[str], windows: Sequence[int] = (20, 60)) -> Dict[int, pd.DataFrame]:
    """Return rolling mean/std/z-score panels keyed by rolling window."""
    out: Dict[int, pd.DataFrame] = {}
    for window in windows:
        px = df.loc[:, flies]
        mean = px.rolling(window).mean().add_suffix(f"_mean{window}")
        std = px.rolling(window).std(ddof=1).add_suffix(f"_std{window}")
        z = ((px - px.rolling(window).mean()) / px.rolling(window).std(ddof=1)).add_suffix(f"_z{window}")
        out[window] = pd.concat([mean, std, z], axis=1)
    return out


def rolling_mean_shift_regimes(
    df: pd.DataFrame,
    flies: Sequence[str],
    window: int,
    gap_days: int = 7,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Identify rolling-mean regimes where |rolling_mean - long_run_mean| > long_run_std.

    Returns
    -------
    daily_flags: one row per fly/date where the condition is true.
    regimes: consecutive flagged periods with start, end, length and direction.
    """
    rs = rolling_stats(df, flies, [window])[window]
    flag_rows = []
    regime_rows = []

    for fly in flies:
        s = df[fly].dropna()
        lr_mean = s.mean()
        lr_std = s.std(ddof=1)
        rm = rs[f"{fly}_mean{window}"].dropna()
        flag = rm[(rm - lr_mean).abs() > lr_std]
        for date, value in flag.items():
            flag_rows.append(
                {
                    "Fly": fly,
                    "Date": date,
                    "Window": window,
                    "RollingMean": value,
                    "LongRunMean": lr_mean,
                    "LongRunStd": lr_std,
                    "ShiftSigma": (value - lr_mean) / lr_std if lr_std else np.nan,
                    "Direction": "rich/wide" if value > lr_mean else "cheap/compressed",
                }
            )
        if flag.empty:
            continue
        start = prev = flag.index[0]
        values = [flag.iloc[0]]
        for date, value in flag.iloc[1:].items():
            if (date - prev).days > gap_days:
                avg_value = float(np.mean(values))
                regime_rows.append(
                    {
                        "Fly": fly,
                        "Window": window,
                        "Start": start,
                        "End": prev,
                        "TradingDays": len(values),
                        "AverageRollingMean": avg_value,
                        "ShiftSigma": (avg_value - lr_mean) / lr_std if lr_std else np.nan,
                        "Direction": "rich/wide" if avg_value > lr_mean else "cheap/compressed",
                    }
                )
                start = date
                values = []
            values.append(value)
            prev = date
        avg_value = float(np.mean(values))
        regime_rows.append(
            {
                "Fly": fly,
                "Window": window,
                "Start": start,
                "End": prev,
                "TradingDays": len(values),
                "AverageRollingMean": avg_value,
                "ShiftSigma": (avg_value - lr_mean) / lr_std if lr_std else np.nan,
                "Direction": "rich/wide" if avg_value > lr_mean else "cheap/compressed",
            }
        )

    return pd.DataFrame(flag_rows), pd.DataFrame(regime_rows)


def percentile_rank(series: pd.Series, value: Optional[float] = None, window: Optional[int] = None) -> float:
    s = series.dropna()
    if s.empty:
        return np.nan
    if window is not None and len(s) > window:
        s = s.iloc[-window:]
    if value is None:
        value = float(s.iloc[-1])
    return float((s <= value).mean() * 100.0)


def ar1_half_life(series: pd.Series) -> Dict[str, float]:
    """Estimate mean-reversion half-life from delta x = alpha + beta*x_lag + eps."""
    s = series.dropna().astype(float)
    if len(s) < 20:
        return {"phi": np.nan, "beta": np.nan, "half_life_days": np.nan, "p_value": np.nan, "r2": np.nan}
    y = s.diff().dropna()
    x = s.shift(1).reindex(y.index)
    lr = stats.linregress(x.values, y.values)
    phi = 1.0 + lr.slope
    if lr.slope < 0 and phi > 0:
        half_life = float(-np.log(2.0) / np.log(phi))
    else:
        half_life = np.inf
    return {
        "phi": float(phi),
        "beta": float(lr.slope),
        "half_life_days": half_life,
        "p_value": float(lr.pvalue),
        "r2": float(lr.rvalue**2),
    }


def current_summary(
    df: pd.DataFrame,
    flies: Sequence[str] = DEFAULT_FLY_UNIVERSE,
    thresholds: SignalThresholds = SignalThresholds(),
) -> pd.DataFrame:
    flies = available_flies(df, flies)
    rs60 = rolling_stats(df, flies, [thresholds.z_window])[thresholds.z_window]
    rs20 = rolling_stats(df, flies, [thresholds.bb_window])[thresholds.bb_window]
    rows = []
    for fly in flies:
        s = df[fly].dropna()
        if s.empty:
            continue
        cur = float(s.iloc[-1])
        date = s.index[-1]
        mean60 = float(rs60[f"{fly}_mean{thresholds.z_window}"].iloc[-1])
        std60 = float(rs60[f"{fly}_std{thresholds.z_window}"].iloc[-1])
        z60 = float(rs60[f"{fly}_z{thresholds.z_window}"].iloc[-1])
        mean20 = float(rs20[f"{fly}_mean{thresholds.bb_window}"].iloc[-1])
        std20 = float(rs20[f"{fly}_std{thresholds.bb_window}"].iloc[-1])
        upper20 = mean20 + thresholds.bb_std * std20
        lower20 = mean20 - thresholds.bb_std * std20
        pct_all = percentile_rank(s, cur)
        pct252 = percentile_rank(s, cur, thresholds.pct_window)
        hl = ar1_half_life(s)

        z_signal = "SHORT" if z60 > thresholds.z_entry else "LONG" if z60 < -thresholds.z_entry else "NEUTRAL"
        bb_signal = "SHORT" if cur >= upper20 else "LONG" if cur <= lower20 else "NEUTRAL"
        pct_signal = "SHORT" if pct252 >= thresholds.pct_high else "LONG" if pct252 <= thresholds.pct_low else "NEUTRAL"

        # Combine signals conservatively. Require at least one hard trigger; conflict is flagged.
        bullish = [z_signal, bb_signal, pct_signal].count("LONG")
        bearish = [z_signal, bb_signal, pct_signal].count("SHORT")
        if bullish and bearish:
            combined = "CONFLICT"
        elif bearish:
            combined = "SHORT"
        elif bullish:
            combined = "LONG"
        else:
            combined = "NO ENTRY"

        rows.append(
            {
                "Date": date,
                "Fly": fly,
                "Observations": int(s.shape[0]),
                "Current Value": cur,
                "Current Ticks": cur / TICK_SIZE,
                "Historical Min": float(s.min()),
                "Historical Max": float(s.max()),
                "P05": float(s.quantile(0.05)),
                "P95": float(s.quantile(0.95)),
                "Percentile Rank": pct_all,
                "Percentile Rank 252d": pct252,
                "Long Run Mean": float(s.mean()),
                "Long Run Std": float(s.std(ddof=1)),
                "Mean 20d": mean20,
                "Std 20d": std20,
                "Lower BB 20d": lower20,
                "Upper BB 20d": upper20,
                "Mean 60d": mean60,
                "Std 60d": std60,
                "Z-Score 60d": z60,
                "AR1 Phi": hl["phi"],
                "Half-Life Days": hl["half_life_days"],
                "Half-Life p-value": hl["p_value"],
                "Z Signal": z_signal,
                "BB Signal": bb_signal,
                "Percentile Signal": pct_signal,
                "Signal": combined,
            }
        )
    return pd.DataFrame(rows)


def strategy_state(
    price: float,
    z60: float,
    mean20: float,
    lower20: float,
    upper20: float,
    pct252: float,
    thresholds: SignalThresholds,
) -> Dict[str, str]:
    return {
        "Z60 Entry": "SHORT" if z60 > thresholds.z_entry else "LONG" if z60 < -thresholds.z_entry else "NEUTRAL",
        "BB20 Entry": "SHORT" if price >= upper20 else "LONG" if price <= lower20 else "NEUTRAL",
        "Pct252 Entry": "SHORT" if pct252 >= thresholds.pct_high else "LONG" if pct252 <= thresholds.pct_low else "NEUTRAL",
    }


def rolling_percentile(series: pd.Series, window: int, min_periods: int = 60) -> pd.Series:
    return series.rolling(window, min_periods=min_periods).apply(lambda x: (x <= x[-1]).mean() * 100.0, raw=True)


def backtest_strategy(
    df: pd.DataFrame,
    fly: str,
    strategy: str,
    thresholds: SignalThresholds = SignalThresholds(),
    tick_size: float = TICK_SIZE,
    tick_value_eur: float = TICK_VALUE_EUR,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Backtest a mean-reversion rule.

    Position convention: +1 is long the fly; -1 is short the fly.
    Exit convention:
    - zscore: exit long when z >= 0, exit short when z <= 0.
    - Bollinger: exit when price crosses the 20d mean.
    - percentile: exit when percentile crosses 50.
    """
    s = df[fly].dropna().astype(float)
    if s.empty:
        return pd.DataFrame(), pd.DataFrame()

    mean20 = s.rolling(thresholds.bb_window).mean()
    std20 = s.rolling(thresholds.bb_window).std(ddof=1)
    upper = mean20 + thresholds.bb_std * std20
    lower = mean20 - thresholds.bb_std * std20
    mean60 = s.rolling(thresholds.z_window).mean()
    std60 = s.rolling(thresholds.z_window).std(ddof=1)
    z60 = (s - mean60) / std60
    pct = rolling_percentile(s, thresholds.pct_window)

    trades = []
    equity = []
    pos = 0
    entry_date = None
    entry_price = np.nan
    realised_ticks = 0.0

    for date, price in s.items():
        enter = 0
        exit_now = False

        if strategy == "zscore":
            z = z60.loc[date]
            if pos == 0 and pd.notna(z):
                if z > thresholds.z_entry:
                    enter = -1
                elif z < -thresholds.z_entry:
                    enter = 1
            elif pos != 0 and pd.notna(z):
                if (pos == 1 and z >= 0.0) or (pos == -1 and z <= 0.0):
                    exit_now = True
        elif strategy == "bollinger":
            m = mean20.loc[date]
            if pos == 0 and pd.notna(upper.loc[date]):
                if price >= upper.loc[date]:
                    enter = -1
                elif price <= lower.loc[date]:
                    enter = 1
            elif pos != 0 and pd.notna(m):
                if (pos == 1 and price >= m) or (pos == -1 and price <= m):
                    exit_now = True
        elif strategy == "percentile":
            p = pct.loc[date]
            if pos == 0 and pd.notna(p):
                if p >= thresholds.pct_high:
                    enter = -1
                elif p <= thresholds.pct_low:
                    enter = 1
            elif pos != 0 and pd.notna(p):
                if (pos == 1 and p >= thresholds.pct_exit) or (pos == -1 and p <= thresholds.pct_exit):
                    exit_now = True
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        if pos != 0 and exit_now:
            pnl_ticks = (price - entry_price) * pos / tick_size
            trades.append(
                {
                    "Fly": fly,
                    "Strategy": strategy,
                    "Entry Date": entry_date,
                    "Exit Date": date,
                    "Direction": "LONG" if pos == 1 else "SHORT",
                    "Entry": entry_price,
                    "Exit": price,
                    "PnL_ticks": pnl_ticks,
                    "PnL_EUR": pnl_ticks * tick_value_eur,
                    "Holding_days": (date - entry_date).days,
                }
            )
            realised_ticks += pnl_ticks
            pos = 0
            entry_date = None
            entry_price = np.nan
        elif pos == 0 and enter != 0:
            pos = enter
            entry_date = date
            entry_price = price

        open_ticks = 0.0 if pos == 0 else (price - entry_price) * pos / tick_size
        equity.append(
            {
                "Date": date,
                "Fly": fly,
                "Strategy": strategy,
                "Equity_ticks": realised_ticks + open_ticks,
                "Equity_EUR": (realised_ticks + open_ticks) * tick_value_eur,
                "Position": pos,
            }
        )

    return pd.DataFrame(trades), pd.DataFrame(equity)


def backtest_all(
    df: pd.DataFrame,
    flies: Sequence[str] = DEFAULT_FLY_UNIVERSE,
    strategies: Sequence[str] = ("zscore", "bollinger", "percentile"),
    thresholds: SignalThresholds = SignalThresholds(),
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    flies = available_flies(df, flies)
    trades_list = []
    equity_list = []
    for fly in flies:
        for strategy in strategies:
            trades, equity = backtest_strategy(df, fly, strategy, thresholds)
            trades_list.append(trades)
            equity_list.append(equity)
    trades_all = pd.concat([x for x in trades_list if not x.empty], ignore_index=True) if trades_list else pd.DataFrame()
    equity_all = pd.concat([x for x in equity_list if not x.empty], ignore_index=True) if equity_list else pd.DataFrame()

    stats_rows = []
    if not trades_all.empty:
        for (fly, strategy), g in trades_all.groupby(["Fly", "Strategy"]):
            stats_rows.append(
                {
                    "Fly": fly,
                    "Strategy": strategy,
                    "Trades": int(len(g)),
                    "Win Rate": float((g["PnL_ticks"] > 0).mean()),
                    "Avg PnL ticks": float(g["PnL_ticks"].mean()),
                    "Avg PnL EUR": float(g["PnL_EUR"].mean()),
                    "Median PnL ticks": float(g["PnL_ticks"].median()),
                    "Total PnL ticks": float(g["PnL_ticks"].sum()),
                    "Total PnL EUR": float(g["PnL_EUR"].sum()),
                    "Avg Holding Days": float(g["Holding_days"].mean()),
                    "Last Exit": g["Exit Date"].max(),
                }
            )
    return trades_all, equity_all, pd.DataFrame(stats_rows)


def correlation_and_pvalues(df: pd.DataFrame, flies: Sequence[str] = ALL_FLIES) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    flies = available_flies(df, flies)
    changes = df.loc[:, flies].diff().dropna(how="all")
    corr = changes.corr()
    pvals = pd.DataFrame(np.nan, index=flies, columns=flies)
    for a in flies:
        for b in flies:
            if a == b:
                pvals.loc[a, b] = 0.0
                continue
            pair = changes[[a, b]].dropna()
            if len(pair) > 2:
                res = stats.pearsonr(pair[a].to_numpy(), pair[b].to_numpy())
                pvals.loc[a, b] = float(res.pvalue if hasattr(res, "pvalue") else res[1])
    return changes, corr, pvals


def rolling_correlations(df: pd.DataFrame, flies: Sequence[str] = DEFAULT_FLY_UNIVERSE, window: int = 60) -> pd.DataFrame:
    flies = available_flies(df, flies)
    changes = df.loc[:, flies].diff()
    rows = []
    for i, a in enumerate(flies):
        for b in flies[i + 1 :]:
            rc = changes[a].rolling(window).corr(changes[b])
            rows.append(pd.DataFrame({"Date": rc.index, "Pair": f"{a}/{b}", "Correlation": rc.values}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def hedge_matrix_and_pca(df: pd.DataFrame, flies: Sequence[str] = DEFAULT_FLY_UNIVERSE) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """OLS hedge ratios and PCA loadings on daily changes.

    Matrix rows are target flies. For a long +1 lot in the row fly, trade the displayed
    number of lots in each column fly to hedge the OLS fitted exposure.
    """
    flies = available_flies(df, flies)
    changes = df.loc[:, flies].diff().dropna()
    hedge = pd.DataFrame(0.0, index=flies, columns=flies)
    residual_rows = []
    for target in flies:
        others = [f for f in flies if f != target]
        y = changes[target].values
        X = changes[others].values
        lr = LinearRegression().fit(X, y)
        residual = y - lr.predict(X)
        for col, beta in zip(others, lr.coef_):
            hedge.loc[target, col] = -float(beta)
        target_var = float(np.var(y, ddof=1))
        residual_var = float(np.var(residual, ddof=1))
        residual_rows.append(
            {
                "Fly": target,
                "Residual Variance": residual_var,
                "Target Variance": target_var,
                "Residual Var %": residual_var / target_var if target_var else np.nan,
                "Variance Reduction %": 1.0 - residual_var / target_var if target_var else np.nan,
                "R2": float(lr.score(X, y)),
            }
        )

    if changes.empty:
        explained = pd.DataFrame()
        loadings = pd.DataFrame()
    else:
        Xz = StandardScaler().fit_transform(changes.values)
        pca = PCA(n_components=min(3, Xz.shape[1])).fit(Xz)
        pcs = [f"PC{i}" for i in range(1, pca.components_.shape[0] + 1)]
        explained = pd.DataFrame({"PC": pcs, "Explained Variance": pca.explained_variance_ratio_})
        loadings = pd.DataFrame(pca.components_.T, index=flies, columns=pcs)
    return hedge, pd.DataFrame(residual_rows), explained, loadings


def third_wednesday(year: int, month: int) -> pd.Timestamp:
    days = pd.date_range(pd.Timestamp(year, month, 1), pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0), freq="D")
    return days[days.weekday == 2][2]


def approximate_monthly_roll_dates(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    months = pd.date_range(start=start.replace(day=1), end=end, freq="MS")
    dates = []
    for m in months:
        ltd = third_wednesday(m.year, m.month) - pd.offsets.BDay(2)
        dates.append(pd.Timestamp(ltd).normalize())
    return pd.DatetimeIndex(dates)


def roll_pattern(
    df: pd.DataFrame,
    flies: Sequence[str] = DEFAULT_FLY_UNIVERSE,
    window: int = 5,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    flies = available_flies(df, flies)
    roll_dates = approximate_monthly_roll_dates(df.index.min(), df.index.max())
    rows = []
    dates = df.index
    for roll_date in roll_dates:
        if roll_date in dates:
            center = roll_date
        else:
            pos = dates.searchsorted(roll_date)
            candidates = []
            if pos < len(dates):
                candidates.append(dates[pos])
            if pos > 0:
                candidates.append(dates[pos - 1])
            if not candidates:
                continue
            center = min(candidates, key=lambda x: abs((x - roll_date).days))
            if abs((center - roll_date).days) > 3:
                continue
        center_pos = dates.get_loc(center)
        for rel in range(-window, window + 1):
            idx = center_pos + rel
            if 0 <= idx < len(dates):
                obs_date = dates[idx]
                for fly in flies:
                    rows.append({"Roll Date": roll_date, "Obs Date": obs_date, "Relative Day": rel, "Fly": fly, "Level": df.loc[obs_date, fly]})
    aligned = pd.DataFrame(rows)
    if aligned.empty:
        return aligned, pd.DataFrame(), pd.DataFrame()

    avg_window = aligned.groupby(["Fly", "Relative Day"], as_index=False)["Level"].mean()
    pre = aligned[aligned["Relative Day"].between(-window, -1)].groupby("Fly")["Level"].mean()
    post = aligned[aligned["Relative Day"].between(1, window)].groupby("Fly")["Level"].mean()
    tminus = aligned[aligned["Relative Day"] == -1].set_index(["Fly", "Roll Date"])["Level"]
    tplus = aligned[aligned["Relative Day"] == 1].set_index(["Fly", "Roll Date"])["Level"]
    jump = (tplus - tminus).dropna().groupby("Fly").agg(["mean", "std", "count"]).rename(columns={"mean": "T+1 minus T-1 mean", "std": "T+1 minus T-1 std", "count": "Roll Count"})
    summary = pd.DataFrame({"Pre Roll Avg": pre, "Post Roll Avg": post, "Post minus Pre": post - pre}).join(jump, how="left").reset_index()
    return aligned, avg_window, summary


def key_hedges(hedge: pd.DataFrame) -> pd.Series:
    """Pick the largest absolute hedge coefficient for each target fly."""
    out = {}
    for fly in hedge.index:
        row = hedge.loc[fly].drop(labels=[fly], errors="ignore")
        if row.empty or row.abs().max() == 0:
            out[fly] = "None"
        else:
            col = row.abs().idxmax()
            out[fly] = f"{row[col]:+.2f} {col} per +1 {fly}"
    return pd.Series(out, name="Key Hedge")


def suggested_action(summary: pd.DataFrame, hedge: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    out = summary.copy()
    actions = []
    for _, r in out.iterrows():
        fly = r["Fly"]
        sig = r["Signal"]
        z = r["Z-Score 60d"]
        pct = r["Percentile Rank 252d"]
        bb = r["BB Signal"]
        if sig == "SHORT":
            if z > 1.5 and pct >= 90:
                action = f"Short {fly}: z and percentile both rich"
            elif z > 1.5:
                action = f"Short {fly} tactically; signal is recent-regime rich"
            else:
                action = f"Short watch {fly}; percentile rich"
        elif sig == "LONG":
            if z < -1.5 and pct <= 10:
                action = f"Long {fly}: z and percentile both cheap"
            elif z < -1.5:
                action = f"Long {fly}: z cheap"
            else:
                action = f"Long watch {fly}; percentile cheap"
        elif sig == "CONFLICT":
            action = f"No fresh trade in {fly}: signal conflict"
        else:
            action = f"No fresh trade in {fly}"
        if bb != "NEUTRAL":
            action += f"; BB confirms {bb.lower()}"
        actions.append(action)
    out["Suggested Action"] = actions
    if hedge is not None and not hedge.empty:
        out = out.merge(key_hedges(hedge).rename("Key Hedge"), left_on="Fly", right_index=True, how="left")
    return out


def append_manual_row(df: pd.DataFrame, date, er_values: Dict[str, float]) -> pd.DataFrame:
    """Append/replace one row using ER1...ER12 values; fly columns are recomputed."""
    row = {k: float(v) for k, v in er_values.items() if k in ALL_ERS}
    if len(row) < 12:
        missing = [c for c in ALL_ERS if c not in row]
        raise ValueError(f"Missing ER values: {missing}")
    for i in range(1, 11):
        row[f"Fly{i}"] = row[f"ER{i}"] - 2.0 * row[f"ER{i+1}"] + row[f"ER{i+2}"]
    new = pd.DataFrame([row], index=[pd.to_datetime(date)])
    new.index.name = "Date"
    out = pd.concat([df, new])
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def to_download_csv(df: pd.DataFrame) -> str:
    out = df.copy()
    out.index.name = "Date"
    return out.reset_index().to_csv(index=False)
