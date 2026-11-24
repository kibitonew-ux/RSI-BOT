# RSI W/M + SuperTrend Bot · BingX → Telegram

Convierte la estrategia de TradingView «RSI W/M + SuperTrend | 5min Long/Short» en un bot
que escanea **todas las monedas de BingX** (spot y futuros perpetuos contra USDT) y envía
señales detalladas a Telegram cada vez que cierra una vela. **No opera: solo avisa.**

## Archivos (todos en la raíz del repositorio, sin carpetas)

| Archivo | Función |
|---|---|
| `bot.py` | Bucle principal: escaneo, señales, salidas y latidos |
| `strategy.py` | Lógica de la estrategia (W/M del RSI, SuperTrend, giros) |
| `indicators.py` | RSI y ATR de Wilder y SuperTrend, igual que `ta.*` de Pine |
| `exchange.py` | Conexión con BingX (ccxt, solo datos públicos) |
| `notifier.py` | Mensajes de Telegram |
| `config.py` | Variables de entorno |
| `state.py` | Señales en seguimiento y cooldowns (JSON) |
| `requirements.txt`, `Procfile`, `railway.json` | Despliegue en Railway |
| `_env.example`, `_gitignore` | Renómbralos a `.env.example` y `.gitignore` si quieres (opcional) |

## Reglas de la señal (idénticas al script)

**LONG**
- RSI(14) forma un doble fondo **W**: dos pivotes bajos (5 velas a cada lado) separados al menos 10 velas, el último no más de 3 % por debajo del anterior, y el RSI sube por encima del último pivote.
- SuperTrend (factor 3, ATR 10) alcista y precio confirmando (mínimo mayor o vela verde).
- O bien: el SuperTrend gira al alza y hay una W reciente (últimas 8 velas).

**SHORT**: versión simétrica con doble techo **M** y SuperTrend bajista.

**Salida:** cuando el SuperTrend gira en contra. El bot avisa de la salida con el PnL aproximado de la señal.
El script no tiene stop ni objetivo; los que aparecen en el mensaje (línea SuperTrend y objetivo en múltiplos de R) son solo referencia.

Todo se evalúa sobre velas **cerradas**; las alertas llegan unos segundos después del cierre.

## Puesta en marcha

1. **Telegram.** Habla con @BotFather, crea el bot y copia el token. Escribe un mensaje a tu bot y abre `https://api.telegram.org/bot<TOKEN>/getUpdates` para ver tu `chat.id`.
2. **GitHub.** Sube todos los archivos a la raíz del repositorio (Add file → Upload files). No subas el `.env`.
3. **Railway.** New Project → Deploy from GitHub repo. En Variables añade como mínimo `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` (el resto son opcionales; mira `_env.example`).
4. **Volumen (recomendado).** Añade un Volume con mount path `/data`. Así el seguimiento de señales abiertas sobrevive a reinicios.
5. Revisa los logs: debe llegar «Bot iniciado» y después «Escaneo OK».

No necesitas API key de BingX: solo se leen datos públicos.

## Variables útiles

- `MARKET`: `both` (por defecto), `spot` o `swap`. Con `both`, cada moneda se analiza una vez y se prefiere el perpetuo, que permite largos y cortos.
- `MIN_QUOTE_VOLUME`: 0 analiza todo. Subirlo (por ejemplo 100000) reduce el ruido de pares ilíquidos.
- `TIMEFRAME`: `1m`, `3m`, `5m`, `15m`, `30m` o `1h`.
- `NOTIFY_SPOT_SHORTS`: avisos de cortos en pares que solo existen en spot (desactivado por defecto, no se pueden operar).
- `MAX_ALERTS`: señales con detalle por vela; el resto va en un resumen.

## Limitaciones

- No está backtesteado y no garantiza resultados. No es consejo financiero.
- Los pivotes del RSI se confirman 5 velas después, igual que en TradingView.
- RSI, ATR y SuperTrend se calculan sobre las últimas 300 velas. Puede haber pequeñas diferencias con TradingView en las primeras velas.
- Los parámetros `RSI Overbought/Oversold` del script no se usan en ninguna condición, así que el bot tampoco los tiene.
- BingX lista también contratos de acciones, divisas y materias primas con USDT; si no los quieres, añádelos a `BLACKLIST`.
- Si BingX cambia su API, actualiza `ccxt` en `requirements.txt`.
