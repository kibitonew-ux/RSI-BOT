"""Estrategia «RSI W/M + SuperTrend» de TradingView, evaluada sobre la última vela cerrada."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from indicators import TF_MS, candle_open_ms, closed, rsi as rsi_fn, supertrend, atr as atr_fn

MIN_BARS = 100  # historial mínimo (RSI, ATR, SuperTrend y pivotes)


@dataclass
class Signal:
    symbol: str
    market: str               # "spot" o "swap"
    timeframe: str
    side: str                 # "LONG" o "SHORT"
    trigger: str
    ts: int                   # apertura (ms) de la vela que da la señal
    price: float              # cierre de esa vela
    st_line: float
    stop: float
    tp: float
    rsi: float
    rsi_prev: float
    pivot1: float             # último pivote del RSI (fondo si LONG, techo si SHORT)
    pivot2: float | None      # pivote anterior
    pivot_gap: int | None     # velas entre ambos pivotes
    atr: float
    vol_ratio: float
    checks: list = field(default_factory=list)   # (texto, ok)


@dataclass
class Analysis:
    symbol: str
    ts: int
    price: float
    direction: int            # dirección SuperTrend: -1 alcista, +1 bajista
    signal: Signal | None


def _pivots(values: pd.Series, left: int, right: int, kind: str) -> list:
    """Equivalente a ta.pivotlow/ta.pivothigh. Devuelve [(valor, barra_del_pivote), ...],
    el más reciente primero (máximo dos). Un pivote se confirma `right` velas después."""
    w = left + right + 1
    roll = values.rolling(w).min() if kind == "low" else values.rolling(w).max()
    centre = values.shift(right)
    hits = centre[centre == roll].dropna()
    out = [(float(v), int(i) - right) for i, v in hits.iloc[-2:].items()]
    out.reverse()
    return out


def analyze(symbol: str, market: str, raw: pd.DataFrame, cfg) -> Analysis | None:
    tf = cfg.timeframe
    d = closed(raw, tf)
    if len(d) < MIN_BARS:
        return None
    # datos obsoletos (par sin actividad o retirado): no se analiza
    if int(d["ts"].iloc[-1]) < candle_open_ms(tf) - 2 * TF_MS[tf]:
        return None

    close = d["close"].to_numpy(float)
    open_ = d["open"].to_numpy(float)
    high = d["high"].to_numpy(float)
    low = d["low"].to_numpy(float)
    ts = int(d["ts"].iloc[-1])
    i = len(d) - 1

    rsi = rsi_fn(d["close"], cfg.rsi_len)
    line, dirs = supertrend(d, cfg.st_factor, cfg.st_atr_len)
    dir_now, dir_prev = dirs[-1], dirs[-2]
    r, rp = float(rsi.iloc[-1]), float(rsi.iloc[-2])
    if any(math.isnan(x) for x in (dir_now, dir_prev, r, rp)):
        return None

    c = float(close[-1])
    base = Analysis(symbol, ts, c, int(dir_now), None)

    bull, bear = dir_now < 0, dir_now > 0
    flip_up = dir_prev > 0 and dir_now < 0
    flip_dn = dir_prev < 0 and dir_now > 0
    p_bull = (not cfg.price_confirm) or (low[-1] > low[-2] or close[-1] > open_[-1])
    p_bear = (not cfg.price_confirm) or (high[-1] < high[-2] or close[-1] < open_[-1])

    tol = cfg.tol_pct / 100.0
    pls = _pivots(rsi, cfg.pivot_left, cfg.pivot_right, "low")
    phs = _pivots(rsi, cfg.pivot_left, cfg.pivot_right, "high")

    w_formed = False
    recent_w = False
    if pls:
        pl1, b1 = pls[0]
        if len(pls) > 1:
            pl2, b2 = pls[1]
            w_formed = ((b1 - b2) >= cfg.min_bars_between and pl1 >= pl2 * (1 - tol)
                        and r > pl1 and rp <= pl1)
        recent_w = w_formed or ((i - b1) <= cfg.recent_bars and r > pl1 and bull)

    m_formed = False
    recent_m = False
    if phs:
        ph1, bh1 = phs[0]
        if len(phs) > 1:
            ph2, bh2 = phs[1]
            m_formed = ((bh1 - bh2) >= cfg.min_bars_between and ph1 <= ph2 * (1 + tol)
                        and r < ph1 and rp >= ph1)
        recent_m = m_formed or ((i - bh1) <= cfg.recent_bars and r < ph1 and bear)

    main_long = w_formed and bull and p_bull and (not cfg.require_flip or flip_up)
    main_short = m_formed and bear and p_bear and (not cfg.require_flip or flip_dn)
    long_ = main_long or (flip_up and recent_w)
    short_ = main_short or (flip_dn and recent_m)
    if not (long_ or short_):
        return base

    side = "LONG" if long_ else "SHORT"
    if side == "LONG":
        trigger = ("Doble fondo W en RSI + SuperTrend alcista" if main_long
                   else "Giro del SuperTrend al alza + W reciente en RSI")
        pv = pls
        checks = [
            ("Doble fondo W formado en el RSI", w_formed),
            ("SuperTrend alcista", bull),
            ("Giro del SuperTrend al alza en esta vela", flip_up),
            (f"W reciente (≤{cfg.recent_bars} velas)", recent_w),
        ]
        if cfg.price_confirm:
            checks.insert(2, ("Precio confirma (mínimo mayor o vela alcista)", bool(p_bull)))
    else:
        trigger = ("Doble techo M en RSI + SuperTrend bajista" if main_short
                   else "Giro del SuperTrend a la baja + M reciente en RSI")
        pv = phs
        checks = [
            ("Doble techo M formado en el RSI", m_formed),
            ("SuperTrend bajista", bear),
            ("Giro del SuperTrend a la baja en esta vela", flip_dn),
            (f"M reciente (≤{cfg.recent_bars} velas)", recent_m),
        ]
        if cfg.price_confirm:
            checks.insert(2, ("Precio confirma (máximo menor o vela bajista)", bool(p_bear)))

    atr_v = float(atr_fn(d, cfg.st_atr_len).iloc[-1])
    st_line = float(line[-1])
    risk = abs(c - st_line)
    if not risk > 0:
        risk = 3.0 * atr_v
    if not risk > 0:
        return base
    stop = c - risk if side == "LONG" else c + risk
    tp = c + cfg.tp_r_mult * risk if side == "LONG" else c - cfg.tp_r_mult * risk
    if stop <= 0 and side == "LONG":
        stop = st_line

    vols = d["volume"].iloc[-21:-1]
    mean_vol = float(vols.mean()) if len(vols) else 0.0
    vol_ratio = float(d["volume"].iloc[-1]) / mean_vol if mean_vol > 0 else 0.0

    base.signal = Signal(
        symbol=symbol, market=market, timeframe=tf, side=side, trigger=trigger,
        ts=ts, price=c, st_line=st_line, stop=stop, tp=tp,
        rsi=r, rsi_prev=rp,
        pivot1=pv[0][0],
        pivot2=pv[1][0] if len(pv) > 1 else None,
        pivot_gap=(pv[0][1] - pv[1][1]) if len(pv) > 1 else None,
        atr=atr_v, vol_ratio=vol_ratio, checks=checks,
    )
    return base


def exit_reason(a: Analysis, pos: dict) -> str | None:
    """La estrategia cierra cuando el SuperTrend gira en contra de la posición.
    Solo cuentan velas cerradas posteriores a la de la señal."""
    if a.ts <= int(pos.get("ts") or 0):
        return None
    if pos["side"] == "LONG" and a.direction > 0:
        return "El SuperTrend giró a bajista (salida de la estrategia)"
    if pos["side"] == "SHORT" and a.direction < 0:
        return "El SuperTrend giró a alcista (salida de la estrategia)"
    return None
