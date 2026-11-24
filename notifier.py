"""Mensajes a Telegram (HTML) con reintentos ante límites de velocidad."""
from __future__ import annotations

import asyncio
import html
import logging
import math
import time
from datetime import datetime, timezone

import httpx

log = logging.getLogger("telegram")
MAX_CHARS = 3900


def split_text(text: str, limit: int = MAX_CHARS) -> list[str]:
    """Parte el texto por saltos de línea para no cortar etiquetas HTML."""
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        candidate = f"{cur}\n{line}" if cur else line
        if len(candidate) > limit and cur:
            parts.append(cur)
            cur = line
        else:
            cur = candidate
    if cur:
        parts.append(cur)
    return parts


class Telegram:
    def __init__(self, token: str, chat_id: str):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage" if token else None
        self.chat_id = chat_id

    async def send(self, text: str):
        if not (self.url and self.chat_id):
            log.info("[Telegram desactivado] %s", text.replace("\n", " | ")[:300])
            return
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                for part in split_text(text):
                    await self._post(client, part)
        except Exception as e:  # token mal escrito, URL inválida, etc.
            log.warning("Telegram falló (%s): %s", type(e).__name__, e)

    async def _post(self, client, text: str):
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        for _ in range(3):
            try:
                r = await client.post(self.url, json=payload)
            except httpx.HTTPError as e:
                log.warning("Telegram (red): %s", e)
                await asyncio.sleep(2)
                continue
            if r.status_code == 200:
                return
            if r.status_code == 429:
                try:
                    wait = int(r.json().get("parameters", {}).get("retry_after", 3))
                except Exception:
                    wait = 3
                await asyncio.sleep(wait + 1)
                continue
            log.warning("Telegram %s: %s", r.status_code, r.text[:200])
            return
        log.warning("Telegram: mensaje descartado tras 3 intentos")


def fmt(x) -> str:
    """Formatea precios con los decimales adecuados para cada magnitud."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "n/d"
    if not math.isfinite(x):
        return "n/d"
    if x == 0:
        return "0"
    digits = min(12, max(2, 6 - int(math.floor(math.log10(abs(x))))))
    return f"{x:.{digits}f}"


def pct(a, b) -> str:
    if not b:
        return "n/d"
    return f"{(a - b) / b * 100:+.2f}%"


MARKET_LABEL = {"swap": "Perpetuo", "spot": "Spot"}


def signal_message(s, tp_r: float, note: str = "") -> str:
    long_ = s.side == "LONG"
    emoji = "🟢" if long_ else "🔴"
    risk = abs(s.price - s.stop)
    risk_pct = risk / s.price * 100 if s.price else 0.0
    rr = abs(s.tp - s.price) / risk if risk else 0.0
    when = datetime.fromtimestamp(s.ts / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")

    lines = [
        f"{emoji} <b>SEÑAL {s.side}</b> · <b>{html.escape(s.symbol)}</b>",
        f"🕒 Vela {when} UTC · TF {s.timeframe} (cerrada) · {MARKET_LABEL.get(s.market, s.market)}",
        f"⚡ {html.escape(s.trigger)}",
        "",
        f"💰 Entrada: <code>{fmt(s.price)}</code>",
        f"🛑 Stop de referencia (SuperTrend): <code>{fmt(s.stop)}</code> ({pct(s.stop, s.price)})",
        f"🎯 Objetivo {tp_r:g}R: <code>{fmt(s.tp)}</code> ({pct(s.tp, s.price)})",
        f"📐 R:R 1:{rr:.1f} · Riesgo {risk_pct:.2f}%",
        "🔚 La estrategia sale cuando el SuperTrend gira en contra.",
        "",
        "<b>RSI</b>",
        f"RSI actual {s.rsi:.1f} (vela anterior {s.rsi_prev:.1f})",
    ]
    nombre = "Fondos" if long_ else "Techos"
    if s.pivot2 is not None:
        lines.append(
            f"{nombre} del RSI: {s.pivot2:.1f} → {s.pivot1:.1f} "
            f"(separados {s.pivot_gap} velas)"
        )
    else:
        lines.append(f"Último pivote del RSI: {s.pivot1:.1f}")
    lines += [
        "",
        f"📊 SuperTrend: <code>{fmt(s.st_line)}</code> · ATR {fmt(s.atr)}",
        f"📈 Volumen vs media 20: {s.vol_ratio:.2f}×",
        "",
        "<b>Condiciones</b>",
    ]
    for text, ok in s.checks:
        lines.append(f"{'✅' if ok else '➖'} {html.escape(text)}")
    if s.side == "SHORT" and s.market == "spot":
        lines.append("\n⚠️ Par spot: no se puede operar en corto.")
    if note:
        lines.append(f"\n{note}")
    lines.append("\n<i>Señal automática basada en RSI W/M + SuperTrend. No es consejo financiero.</i>")
    return "\n".join(lines)


def exit_message(sym: str, pos: dict, price: float, reason: str) -> str:
    entry = float(pos.get("entry") or 0)
    if entry:
        pnl = (price - entry) / entry * 100
        if pos["side"] == "SHORT":
            pnl = -pnl
        pnl_txt = f"{pnl:+.2f}%"
    else:
        pnl_txt = "n/d"
    mins = int((time.time() - float(pos.get("time") or time.time())) / 60)
    dur = f"{mins // 60} h {mins % 60} min" if mins >= 60 else f"{mins} min"
    return (
        f"🔚 <b>SALIDA {pos['side']}</b> · {html.escape(sym)}\n"
        f"Motivo: {html.escape(reason)}\n"
        f"Entrada: <code>{fmt(entry)}</code> → Cierre de vela: <code>{fmt(price)}</code>\n"
        f"PnL aprox. sin comisiones: <b>{pnl_txt}</b> · Duración {dur}"
    )


def summary_message(signals) -> str:
    lines = ["📋 <b>Más señales (resumen)</b>"]
    for s in signals:
        icon = "🟢" if s.side == "LONG" else "🔴"
        lines.append(
            f"{icon} {html.escape(s.symbol)} {s.side} · RSI {s.rsi:.1f} · "
            f"entrada {fmt(s.price)} · stop {fmt(s.stop)}"
        )
    return "\n".join(lines)


def heartbeat_message(stats: dict, open_positions: int) -> str:
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    return (
        f"💓 <b>Escaneo OK</b> · {now}\n"
        f"Pares analizados: {stats.get('pairs', 0)} · Señales en esta vela: {stats.get('signals', 0)}\n"
        f"Señales en seguimiento: {open_positions}"
    )
