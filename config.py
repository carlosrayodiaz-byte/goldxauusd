"""
Configuracion central del bot. Nada de credenciales aqui (eso va en .env).
Todos los parametros de deteccion SMC se pueden tocar sin tocar codigo.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# --- MT5 (solo lectura de mercado, cuenta demo) ---
MT5_LOGIN = os.getenv("MT5_LOGIN")
MT5_PASSWORD = os.getenv("MT5_PASSWORD")
MT5_SERVER = os.getenv("MT5_SERVER")
MT5_TERMINAL_PATH = os.getenv("MT5_TERMINAL_PATH")  # opcional, ej. "C:/Program Files/MetaTrader 5/terminal64.exe"

# --- Simbolo y timeframes ---
SYMBOL = os.getenv("SYMBOL", "XAUUSD")

BIAS_TIMEFRAMES = ["M15", "H1"]
TRIGGER_TIMEFRAMES = ["M1", "M5"]
ALL_TIMEFRAMES = BIAS_TIMEFRAMES + TRIGGER_TIMEFRAMES

# Timeframe dominante para el bias cuando M15 y H1 estan en conflicto o
# uno de los dos esta neutral. H1 manda; si H1 esta neutral, se usa M15.
DOMINANT_BIAS_TIMEFRAME = "H1"

# --- Velas a descargar por ciclo (modo live) ---
CANDLES_TO_FETCH = {
    "M1": 500,
    "M5": 500,
    "M15": 500,
    "H1": 500,
}

# --- Parametros de smartmoneyconcepts, configurables por timeframe ---
# swing_length: lookback/forward para swing_highs_lows. Mas grande = estructura
# mas "mayor"/limpia (apto para bias). Mas chico = mas sensible (apto para triggers).
SWING_LENGTH = {
    "M1": 5,
    "M5": 5,
    "M15": 50,
    "H1": 50,
}

BOS_CLOSE_BREAK = True          # usar cierre (no mecha) para validar BOS/CHoCH
FVG_JOIN_CONSECUTIVE = False    # no fusionar FVGs consecutivos
OB_CLOSE_MITIGATION = False     # mitigacion de OB por mecha (no por cierre)
LIQUIDITY_RANGE_PERCENT = 0.01  # % de rango para agrupar liquidez en clusters

# --- Backtest ---
BACKTEST_MONTHS = 3

# --- Bucle live ---
POLL_ALIGN_SECONDS = 2  # margen tras el cierre de vela M1 antes de consultar MT5
MT5_RECONNECT_RETRIES = 5
MT5_RECONNECT_DELAY_SECONDS = 5

# --- Base de datos / logging ---
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "signals.db"))
LOG_PATH = os.getenv("LOG_PATH", str(BASE_DIR / "logs" / "bot.log"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
