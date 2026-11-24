"""Lectura de variables de entorno. En Railway se usan las del servicio; en local, el archivo .env."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

from indicators import TF_MS

load_dotenv()
log = logging.getLogger("config")

# Activos que no se analizan (stablecoins y divisas fiat)
STABLES = {
    "USDT", "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDD", "USDE", "PYUSD",
    "EUR", "EURT", "GBP", "BRL", "TRY",
}


def _get(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _float(name: str, default: float) -> float:
    raw = _get(name, str(default))
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        log.warning("Variable %s=%r no es un número; uso %s", name, raw, default)
        return float(default)


def _int(name: str, default: int) -> int:
    return int(_float(name, default))


def _bool(name: str, default: bool) -> bool:
    return _get(name, "true" if default else "false").lower() in ("1", "true", "yes", "on", "si", "sí")


@dataclass(frozen=True)
class Config:
    tg_token: str
    tg_chat_id: str
    market: str            # spot | swap | both
    quote: str
    timeframe: str
    min_quote_volume: float
    max_symbols: int
    concurrency: int
    cooldown_min: int
    max_alerts: int
    heartbeat_min: int
    notify_shorts: bool
    notify_spot_shorts: bool
    blacklist: frozenset
    state_file: str
    # estrategia (mismos nombres que los inputs del script de TradingView)
    rsi_len: int
    pivot_left: int
    pivot_right: int
    tol_pct: float
    min_bars_between: int
    price_confirm: bool
    require_flip: bool
    st_factor: float
    st_atr_len: int
    recent_bars: int
    tp_r_mult: float


def load_config() -> Config:
    market = _get("MARKET", "both").lower()
    if market not in ("spot", "swap", "both"):
        log.warning("MARKET=%r no válido; uso 'both'", market)
        market = "both"
    tf = _get("TIMEFRAME", "5m").lower()
    if tf not in TF_MS:
        log.warning("TIMEFRAME=%r no válido (usa %s); uso 5m", tf, ", ".join(TF_MS))
        tf = "5m"

    default_state = os.path.join(os.getenv("RAILWAY_VOLUME_MOUNT_PATH") or ".", "state.json")

    return Config(
        tg_token=_get("TELEGRAM_BOT_TOKEN", ""),
        tg_chat_id=_get("TELEGRAM_CHAT_ID", ""),
        market=market,
        quote=_get("QUOTE", "USDT").upper(),
        timeframe=tf,
        min_quote_volume=_float("MIN_QUOTE_VOLUME", 0),
        max_symbols=_int("MAX_SYMBOLS", 0),
        concurrency=max(1, _int("CONCURRENCY", 5)),
        cooldown_min=_int("COOLDOWN_MIN", 30),
        max_alerts=_int("MAX_ALERTS", 10),
        heartbeat_min=_int("HEARTBEAT_MIN", 60),
        notify_shorts=_bool("NOTIFY_SHORTS", True),
        notify_spot_shorts=_bool("NOTIFY_SPOT_SHORTS", False),
        blacklist=frozenset(
            x.strip().upper() for x in _get("BLACKLIST", "").split(",") if x.strip()
        ),
        state_file=_get("STATE_FILE", default_state),
        rsi_len=max(2, _int("RSI_LEN", 14)),
        pivot_left=max(2, _int("PIVOT_LEFT", 5)),
        pivot_right=max(2, _int("PIVOT_RIGHT", 5)),
        tol_pct=max(0.5, _float("TOL_PCT", 3.0)),
        min_bars_between=max(3, _int("MIN_BARS_BETWEEN", 10)),
        price_confirm=_bool("PRICE_CONFIRM", True),
        require_flip=_bool("REQUIRE_FLIP", False),
        st_factor=max(0.5, _float("ST_FACTOR", 3.0)),
        st_atr_len=max(1, _int("ST_ATR_LEN", 10)),
        recent_bars=max(1, _int("RECENT_BARS", 8)),
        tp_r_mult=max(0.5, _float("TP_R_MULT", 2.0)),
    )
