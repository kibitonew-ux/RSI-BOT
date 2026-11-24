"""Indicadores calculados como en TradingView: RSI y ATR de Wilder (RMA) y SuperTrend."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

TF_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000,
}


def rma(series: pd.Series, n: int) -> pd.Series:
    """Media móvil de Wilder (ta.rma). Vale NaN hasta tener n datos."""
    return series.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """ta.rsi de Pine."""
    d = close.diff()
    up = rma(d.clip(lower=0), n)
    dn = rma((-d).clip(lower=0), n)
    out = 100 - 100 / (1 + up / dn)
    out = out.where(dn != 0, 100.0)
    return out.where(up.notna() & dn.notna())


def atr(df: pd.DataFrame, n: int = 10) -> pd.Series:
    """ta.atr de Pine (RMA del rango verdadero)."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return rma(tr, n)


def supertrend(df: pd.DataFrame, factor: float = 3.0, n: int = 10):
    """ta.supertrend de Pine. Devuelve (línea, dirección) como arrays numpy.
    Dirección -1 = tendencia alcista, +1 = bajista (igual que en Pine)."""
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy(float)
    close = df["close"].to_numpy(float)
    a = atr(df, n).to_numpy(float)
    size = len(df)
    upper = np.full(size, np.nan)
    lower = np.full(size, np.nan)
    line = np.full(size, np.nan)
    direction = np.full(size, np.nan)

    for i in range(size):
        if np.isnan(a[i]):
            continue
        up = hl2[i] + factor * a[i]
        lo = hl2[i] - factor * a[i]
        prev_lo = lower[i - 1] if i > 0 and not np.isnan(lower[i - 1]) else 0.0
        prev_up = upper[i - 1] if i > 0 and not np.isnan(upper[i - 1]) else 0.0
        prev_close = close[i - 1] if i > 0 else np.nan
        lo = lo if (lo > prev_lo or prev_close < prev_lo) else prev_lo
        up = up if (up < prev_up or prev_close > prev_up) else prev_up
        lower[i], upper[i] = lo, up

        if i == 0 or np.isnan(a[i - 1]):
            d = 1.0
        elif line[i - 1] == prev_up:
            d = -1.0 if close[i] > up else 1.0
        else:
            d = 1.0 if close[i] < lo else -1.0
        direction[i] = d
        line[i] = lo if d == -1.0 else up
    return line, direction


def closed(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Devuelve solo las velas ya cerradas; descarta la vela en formación."""
    now_ms = time.time() * 1000
    return df[df["ts"] + TF_MS[tf] <= now_ms].reset_index(drop=True)


def candle_open_ms(tf: str = "5m") -> int:
    """Hora de apertura (ms) de la vela que se está formando ahora."""
    step = TF_MS[tf]
    return int(time.time() * 1000) // step * step
