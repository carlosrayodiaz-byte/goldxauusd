"""
Configuracion de la capa macro (Fase 2), TOTALMENTE independiente de
config.py / smc_engine.py / database.py de la Fase 1. No importa nada de
esos modulos y nada de esos modulos deberia importar esto todavia: la
integracion (score combinado, ventana de no-trade, tabla `signals`) es
trabajo de una fase posterior, pendiente de revisar el backtest de Fase 1.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# --- FRED (real yields + calendario NFP/CPI) ---
# Clave gratuita: https://fredaccount.stlouisfed.org/apikeys (ver README).
FRED_API_KEY = os.getenv("FRED_API_KEY")
FRED_BASE_URL = "https://api.stlouisfed.org/fred"

REAL_YIELD_SERIES_ID = "DFII10"   # TIPS 10 anos, yield real ya calculado por FRED
NOMINAL_YIELD_SERIES_ID = "DGS10"  # Treasury 10 anos nominal, para contexto

# release_id de FRED para el calendario de publicaciones (confirmados via
# fred.stlouisfed.org/release?rid=<id>):
#   50 = Employment Situation (el reporte que contiene el NFP)
#   10 = Consumer Price Index (CPI)
FRED_RELEASE_ID_NFP = 50
FRED_RELEASE_ID_CPI = 10

# Hora de publicacion ESTANDAR (no viene de la API de FRED, que solo da la
# fecha): BLS publica NFP y CPI a las 8:30 AM hora del este de EEUU salvo
# excepciones puntuales que FRED no distingue. Documentado en el README.
US_BLS_RELEASE_TIME_ET = (8, 30)
US_TIMEZONE = "America/New_York"

# --- DXY (indice dolar) ---
# yfinance es la primera opcion mas simple, pero el ticker DX-Y.NYB tiene
# fallos documentados de fiabilidad en Yahoo Finance (HTTP 500/429
# especificos de este ticker mientras otros funcionan bien -- ver
# https://github.com/ranaroussi/yfinance/issues/2721). Por eso hay un
# fallback automatico a Stooq (CSV publico, sin API key, sin limite
# documentado) si yfinance falla o devuelve datos vacios.
DXY_YFINANCE_TICKER = "DX-Y.NYB"
DXY_STOOQ_SYMBOL = "dx.f"  # ICE US Dollar Index en Stooq
DXY_STOOQ_URL = f"https://stooq.com/q/d/l/?s={DXY_STOOQ_SYMBOL}&i=d"

# Rango plausible del DXY (nunca estuvo fuera de ~70-130 en su historia).
# Un valor 200 OK pero fuera de este rango (ej. 0.0 por un glitch de la API)
# se trata como fuente fallida, no como dato valido -- ver _is_plausible_dxy
# en macro_engine.py, usado tanto en el camino real de fetch como en
# sanity_check_dxy().
DXY_PLAUSIBLE_MIN = 70.0
DXY_PLAUSIBLE_MAX = 130.0

# --- COT (CFTC Disaggregated Futures-Only, oro) ---
# Dataset publico en el portal Socrata del CFTC, sin API key.
CFTC_SOCRATA_BASE_URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
# Codigo de contrato CFTC para GOLD - COMMODITY EXCHANGE INC. (COMEX, 100 oz).
CFTC_GOLD_CONTRACT_CODE = "088691"
# Filtro de respaldo por nombre si el filtro por codigo no devuelve filas
# (por si el codigo cambia de formato en el dataset).
CFTC_GOLD_NAME_FILTER = "GOLD - COMMODITY EXCHANGE INC."
COT_LOOKBACK_YEARS = 3
COT_PERCENTILE_HIGH = 90  # percentil >= esto: posicionamiento extremo largo
COT_PERCENTILE_LOW = 10   # percentil <= esto: posicionamiento extremo corto

# --- Calendario de eventos de alto impacto ---
# FOMC: no encontramos una fuente gratuita con API estable para las fechas
# futuras de decision de tipos (Trading Economics exige plan de pago para
# el calendario forward; el "guest key" gratuito solo expone series de
# muestra, no el calendario). El propio Fed publica el calendario anual de
# reuniones con muchos meses de antelacion en federalreserve.gov, asi que
# por ahora se mantiene aqui como lista estatica a refrescar manualmente
# 1-2 veces al ano (ver README para el enlace y el procedimiento).
# Formato: (fecha_reunion_dia_decision, hora_decision_ET) -- FOMC anuncia a
# las 14:00 ET.
FOMC_DECISION_TIME_ET = (14, 0)
FOMC_MEETING_DATES = [
    # Actualizar desde https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
    "2026-01-28",
    "2026-03-18",
    "2026-04-29",
    "2026-06-17",
    "2026-07-29",
    "2026-09-16",
    "2026-10-28",
    "2026-12-09",
]

HIGH_IMPACT_EVENTS_LOOKAHEAD_DAYS = 30

# --- Cache local (SQLite propia, separada de data/signals.db de Fase 1) ---
MACRO_DB_PATH = os.getenv("MACRO_DB_PATH", str(BASE_DIR / "data" / "macro_cache.db"))

# Cuanto tiempo se considera "fresco" un snapshot cacheado antes de volver a
# golpear la API correspondiente.
CACHE_MAX_AGE_HOURS = {
    "real_yields": 20,      # FRED actualiza DFII10 una vez por dia habil
    "dxy": 20,              # dato diario
    "cot_gold": 24 * 4,     # el CFTC publica una vez por semana (viernes)
    "econ_calendar": 12,    # barato de recalcular, pero evita golpear FRED constantemente
}

HTTP_TIMEOUT_SECONDS = 20

LOG_PATH = os.getenv("MACRO_LOG_PATH", str(BASE_DIR / "logs" / "macro.log"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
