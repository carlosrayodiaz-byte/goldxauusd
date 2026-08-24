# Variables de entorno — referencia consolidada

Este documento junta en un solo lugar **todas** las variables de `.env` que
existen hoy en las tres ramas construidas del bot de XAUUSD:

- `claude/xauusd-trading-signals-phase1-kj0va4` — Fase 1 (MT5 + motor SMC + journaling)
- `claude/xauusd-macro-phase2` — Fase 2 (capa macro, `macro_engine.py`)
- `claude/xauusd-telegram-phase3` — Fase 3 (notificador de Telegram, `telegram_notifier.py`)

Es puramente informativo: no fusiona código de las tres ramas, no cambia
ninguna lógica. Cada rama sigue teniendo su propio `.env.example` con solo
las variables que le corresponden a ella; esto es la vista consolidada para
no tener que abrir los tres README por separado. Hoy, trabajando solo en la
rama de Fase 1, únicamente hacen falta las variables de MT5 — el resto se
documenta para cuando se conecten esas fases.

Todas las variables se leen vía `python-dotenv` (`load_dotenv()`) desde un
archivo `.env` en la raíz del repo, que nunca se sube a git (ya está en
`.gitignore` en las tres ramas).

## Fase 1 — MT5 (`config.py`) — las que necesitas HOY

| Variable | Obligatoriedad | Valor por defecto | De dónde se obtiene |
|---|---|---|---|
| `MT5_LOGIN` | Obligatoria | ninguno | Número de cuenta de tu cuenta **demo** de MT5. Te lo muestra el terminal al crear la cuenta (**Herramientas > Opciones > Servidor**) o el correo de bienvenida del bróker. |
| `MT5_PASSWORD` | Obligatoria | ninguno | Password de esa misma cuenta demo, mismo origen que `MT5_LOGIN`. |
| `MT5_SERVER` | Obligatoria | ninguno | Nombre **exacto** del servidor del bróker (ej. `ICMarkets-Demo`), mismo origen que `MT5_LOGIN`. |
| `MT5_TERMINAL_PATH` | Opcional | ninguno (usa la instalación por defecto) | Solo si tienes varios terminales MT5 instalados y necesitás apuntar a uno específico, ej. `C:/Program Files/MetaTrader 5/terminal64.exe`. |
| `SYMBOL` | Opcional | `XAUUSD` | Cambialo solo si el símbolo del oro en tu bróker no es exactamente `XAUUSD` (ej. `XAUUSD.m`, `GOLD`) — revisá el Market Watch del terminal. |
| `DB_PATH` | Opcional | `data/signals.db` | Ruta a la base de datos SQLite de señales. Normalmente no hace falta tocarla. |
| `LOG_PATH` | Opcional | `logs/bot.log` | Ruta del log del bucle en vivo (`main.py`). |
| `LOG_LEVEL` | Opcional | `INFO` | Nivel de logging. **Compartida por las tres ramas** (mismo nombre de variable en `config.py`, `macro_config.py` y `telegram_config.py`) — cambiarla afecta el logging de las tres fases a la vez. |

Nota: `MT5_LOGIN`/`MT5_PASSWORD`/`MT5_SERVER` están marcadas obligatorias
porque así lo asume el flujo documentado en el README de Fase 1 (paso 3,
"Configurar `.env`"). En el código, `mt5_client.py` solo pasa esas
credenciales a `mt5.initialize()` si están definidas; si se omiten, MT5 se
conecta con la sesión que ya esté logueada en el terminal — pero el README
no contempla ese camino, así que seguí el flujo documentado y usá las tres.

## Fase 2 — capa macro (`macro_config.py`) — solo si conectás `macro_engine.py`

| Variable | Obligatoriedad | Valor por defecto | De dónde se obtiene |
|---|---|---|---|
| `FRED_API_KEY` | Obligatoria para usar `macro_engine.py` (real yields DFII10/DGS10 y calendario NFP/CPI) | ninguno | Gratuita. Crear cuenta en https://fredaccount.stlouisfed.org/, luego ir a https://fredaccount.stlouisfed.org/apikeys y pulsar "Request API Key" (uso no comercial, instantáneo, sin aprobación manual). |
| `MACRO_DB_PATH` | Opcional | `data/macro_cache.db` | Ruta a la caché SQLite propia de la capa macro (tabla `macro_snapshots`, separada de `data/signals.db`). |
| `MACRO_LOG_PATH` | Opcional | `logs/macro.log` | Ruta del log de `macro_engine.py`. |
| `LOG_LEVEL` | Opcional | `INFO` | Ver nota de "compartida" arriba. |

Stooq (fallback de DXY) y el dataset Socrata del CFTC (COT) **no** requieren
API key — solo FRED la necesita.

## Fase 3 — notificador de Telegram (`telegram_config.py`) — solo si conectás `telegram_notifier.py`

| Variable | Obligatoriedad | Valor por defecto | De dónde se obtiene |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Obligatoria para usar `telegram_notifier.py` | ninguno | Hablar con **@BotFather** en Telegram, enviar `/newbot` y seguir las instrucciones (nombre + username terminado en `bot`). Te devuelve un token con forma `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`. |
| `TELEGRAM_CHAT_ID` | Obligatoria para usar `telegram_notifier.py` | ninguno | No es tu username, es un número. Opción A: enviale un mensaje a tu bot y abrí `https://api.telegram.org/bot<TU_TOKEN>/getUpdates` en el navegador, buscá `"chat":{"id":...}`. Opción B: hablale a **@userinfobot** (bot de terceros) y te devuelve tu id directamente. Si es un grupo, el id es negativo. |
| `TELEGRAM_LOG_PATH` | Opcional | `logs/telegram.log` | Ruta del log de `telegram_notifier.py`. |
| `LOG_LEVEL` | Opcional | `INFO` | Ver nota de "compartida" arriba. |

## Vista combinada (ilustrativa, no es un archivo del repo)

Esto es solo para visualizar cómo quedaría un `.env` que cubriera las tres
fases a la vez — no existe como archivo único en ninguna rama hoy; cada
rama mantiene su propio `.env.example` con el subconjunto que le
corresponde:

```
# --- Fase 1: MT5 (obligatorias) ---
MT5_LOGIN=12345678
MT5_PASSWORD=tu_password_demo
MT5_SERVER=NombreDelBroker-Demo
# MT5_TERMINAL_PATH=C:/Program Files/MetaTrader 5/terminal64.exe
# SYMBOL=XAUUSD
# DB_PATH=data/signals.db
# LOG_PATH=logs/bot.log
# LOG_LEVEL=INFO

# --- Fase 2: capa macro (solo si usás macro_engine.py) ---
FRED_API_KEY=tu_api_key_de_fred
# MACRO_DB_PATH=data/macro_cache.db
# MACRO_LOG_PATH=logs/macro.log

# --- Fase 3: Telegram (solo si usás telegram_notifier.py) ---
TELEGRAM_BOT_TOKEN=123456789:tu_token_de_botfather
TELEGRAM_CHAT_ID=tu_chat_id
# TELEGRAM_LOG_PATH=logs/telegram.log
```

## Dónde está cada `.env.example` real

- Fase 1: `.env.example` en `claude/xauusd-trading-signals-phase1-kj0va4` (solo variables de MT5).
- Fase 2: `.env.example` en `claude/xauusd-macro-phase2` (variables de MT5 + `FRED_API_KEY`/`MACRO_*`).
- Fase 3: `.env.example` en `claude/xauusd-telegram-phase3` (variables de MT5 + `TELEGRAM_*`).

Cada rama es independiente y no importa código de las otras (verificado con
`grep` de imports al construir cada una) — este documento es solo la
referencia de configuración, no cambia esa independencia.
