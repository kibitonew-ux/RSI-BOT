"""Conexión con BingX (spot y futuros perpetuos) mediante ccxt. Solo datos públicos."""
from __future__ import annotations

import logging

import ccxt.async_support as ccxt
import pandas as pd

from config import STABLES

log = logging.getLogger("exchange")
COLS = ["ts", "open", "high", "low", "close", "volume"]


class BingXClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.ex = ccxt.bingx({"enableRateLimit": True})

    async def load(self):
        await self.ex.load_markets()
        log.info("Mercados cargados: %d", len(self.ex.markets))

    async def close(self):
        await self.ex.close()

    def market_type(self, sym: str) -> str:
        m = self.ex.markets.get(sym) or {}
        return "swap" if m.get("swap") else "spot"

    async def _volumes(self, kind: str) -> dict:
        try:
            tickers = await self.ex.fetch_tickers(None, {"type": kind})
        except Exception as e:
            log.warning("No se pudieron leer los tickers (%s): %s; no se filtra por volumen", kind, e)
            return {}
        vols = {}
        for sym, t in tickers.items():
            vol = float(t.get("quoteVolume") or 0)
            if vol <= 0:
                vol = float(t.get("baseVolume") or 0) * float(t.get("last") or 0)
            vols[sym] = vol
        return vols

    async def symbols(self) -> list[str]:
        """Pares activos contra QUOTE, de mayor a menor volumen.
        Con MARKET=both, cada moneda aparece una vez y se prefiere el perpetuo (permite largos y cortos)."""
        c = self.cfg
        kinds = {"spot": ["spot"], "swap": ["swap"], "both": ["swap", "spot"]}[c.market]
        seen_bases: set = set()
        ranked = []
        for kind in kinds:
            vols = await self._volumes(kind)
            bases_now = set()
            for sym, m in self.ex.markets.items():
                if kind == "spot" and not m.get("spot"):
                    continue
                if kind == "swap" and not (m.get("swap") and m.get("linear") is not False):
                    continue
                if m.get("quote") != c.quote or m.get("active") is False:
                    continue
                base = m.get("base") or ""
                if base in STABLES or base in c.blacklist or base in seen_bases:
                    continue
                vol = vols.get(sym, 0.0)
                if vols and vol < c.min_quote_volume:
                    continue
                bases_now.add(base)
                ranked.append((vol, sym))
            seen_bases |= bases_now
        ranked.sort(reverse=True)
        syms = [s for _, s in ranked]
        return syms[: c.max_symbols] if c.max_symbols > 0 else syms

    async def ohlcv(self, sym: str, tf: str, limit: int = 300) -> pd.DataFrame:
        raw = await self.ex.fetch_ohlcv(sym, tf, limit=limit)
        return pd.DataFrame(raw, columns=COLS)
