"""RSI W/M + SuperTrend Bot: escanea BingX (spot y perpetuos) y envía señales detalladas a Telegram."""
from __future__ import annotations

import asyncio
import html
import logging
import time

from config import load_config
from exchange import BingXClient
from indicators import TF_MS
from notifier import (Telegram, exit_message, fmt, heartbeat_message, signal_message,
                      summary_message)
from state import State
from strategy import MIN_BARS, analyze, exit_reason

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bot")

CANDLES = 300        # velas por consulta (pivotes del RSI + SuperTrend)
CLOSE_DELAY = 10     # segundos tras el cierre de vela antes de leer los datos


def seconds_to_next_candle(tf: str) -> float:
    period = TF_MS[tf] // 1000
    return period - (time.time() % period) + CLOSE_DELAY


async def retry(fn, *args, tries: int = 2):
    for attempt in range(tries):
        try:
            return await fn(*args)
        except Exception:
            if attempt == tries - 1:
                raise
            await asyncio.sleep(1.5)


async def fetch_many(ex, cfg, symbols):
    sem = asyncio.Semaphore(cfg.concurrency)
    out = {}

    async def one(sym):
        async with sem:
            try:
                out[sym] = await retry(ex.ohlcv, sym, cfg.timeframe, CANDLES)
            except Exception as e:
                log.warning("%s: %s", sym, e)

    await asyncio.gather(*(one(s) for s in symbols))
    return out


async def process_exits(st, tg, results):
    """Cierra el seguimiento de señales cuando el SuperTrend gira en contra."""
    for sym in list(st.positions):
        a = results.get(sym)
        if a is None:
            continue
        pos = st.positions[sym]
        reason = exit_reason(a, pos)
        if reason:
            await tg.send(exit_message(sym, pos, a.price, reason))
            del st.positions[sym]
    st.save()


async def dispatch(cfg, st, tg, signals):
    now = time.time()
    detailed, extra = 0, []
    for s in signals:
        if s.side == "SHORT":
            if not cfg.notify_shorts:
                continue
            if s.market == "spot" and not cfg.notify_spot_shorts:
                continue
        pos = st.positions.get(s.symbol)
        if pos and pos["side"] == s.side:      # pyramiding = 0
            continue
        key = f"{s.symbol}:{s.side}"
        if now - st.last_signal.get(key, 0) < cfg.cooldown_min * 60:
            continue
        st.last_signal[key] = now

        if not (s.side == "SHORT" and s.market == "spot"):
            st.positions[s.symbol] = {
                "side": s.side, "entry": s.price, "ts": s.ts,
                "market": s.market, "time": now,
            }
        if detailed < cfg.max_alerts:
            await tg.send(signal_message(s, cfg.tp_r_mult))
            detailed += 1
        else:
            extra.append(s)
    if extra:
        await tg.send(summary_message(extra))
    st.save()


async def run_scan(ex, cfg, st, tg) -> dict:
    stats = {"pairs": 0, "signals": 0}
    symbols = await ex.symbols()
    symbols += [s for s in st.positions if s not in symbols]
    if not symbols:
        log.warning("Ningún par cumple los filtros (mercado, quote, volumen, blacklist)")
        return stats

    raw = await fetch_many(ex, cfg, symbols)
    results, signals = {}, []
    for sym, df in raw.items():
        if len(df) < MIN_BARS:
            continue
        try:
            a = analyze(sym, ex.market_type(sym), df, cfg)
        except Exception:
            log.exception("Error analizando %s", sym)
            continue
        if a is None:
            continue
        results[sym] = a
        if a.signal:
            signals.append(a.signal)

    stats["pairs"], stats["signals"] = len(results), len(signals)
    log.info("Pares analizados: %d de %d · señales: %d", len(results), len(symbols), len(signals))

    await process_exits(st, tg, results)
    signals.sort(key=lambda x: x.vol_ratio, reverse=True)
    if signals:
        await dispatch(cfg, st, tg, signals)
    return stats


async def main():
    cfg = load_config()
    st = State(cfg.state_file)
    tg = Telegram(cfg.tg_token, cfg.tg_chat_id)
    ex = BingXClient(cfg)

    try:
        while True:
            try:
                await ex.load()
                break
            except Exception:
                log.exception("No se pudieron cargar los mercados de BingX; reintento en 30 s")
                await asyncio.sleep(30)

        extra = ""
        if not os_volume():
            extra = ("\n⚠️ Sin volumen persistente: si Railway reinicia, se olvida el "
                     "seguimiento de señales abiertas (ver README).")
        await tg.send(
            f"🚀 <b>Bot iniciado</b> · RSI W/M + SuperTrend · TF {cfg.timeframe}\n"
            f"Mercado: {cfg.market} · {cfg.quote} · volumen mín. {fmt(cfg.min_quote_volume)} · "
            f"cooldown {cfg.cooldown_min} min{extra}"
        )

        last_hb = 0.0
        while True:
            stats, ok = {}, False
            try:
                stats = await run_scan(ex, cfg, st, tg)
                ok = True
            except Exception as e:
                log.exception("Error en ciclo")
                await tg.send(f"⚠️ Error en ciclo: {html.escape(str(e))[:300]}")
            now = time.time()
            if ok and cfg.heartbeat_min > 0 and now - last_hb >= cfg.heartbeat_min * 60:
                await tg.send(heartbeat_message(stats, len(st.positions)))
                last_hb = now
            await asyncio.sleep(seconds_to_next_candle(cfg.timeframe))
    finally:
        await ex.close()


def os_volume() -> bool:
    import os
    return bool(os.getenv("RAILWAY_VOLUME_MOUNT_PATH"))


async def supervisor():
    """Si main() falla por cualquier motivo, lo registra y reinicia sin que caiga el servicio."""
    while True:
        try:
            await main()
        except Exception as e:
            log.exception("ERROR FATAL en main(): %s", e)
            try:
                cfg = load_config()
                await Telegram(cfg.tg_token, cfg.tg_chat_id).send(
                    f"💥 Error fatal: {html.escape(type(e).__name__)}: "
                    f"{html.escape(str(e))[:300]}\nReinicio en 30 s."
                )
            except Exception:
                pass
            await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(supervisor())
