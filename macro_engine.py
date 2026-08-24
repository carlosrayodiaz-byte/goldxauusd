"""
Capa de ingesta de datos macro para el bot de XAUUSD -- Fase 2, SOLO INGESTA.

Modulo TOTALMENTE independiente: no importa smc_engine.py ni database.py de
la Fase 1, y nada de lo que hay aqui calcula un "score" ni un bias
combinado ni una ventana de no-trade. Eso es trabajo de una fase posterior,
pendiente de revisar el backtest de Fase 1. Este archivo solo descarga,
parsea, cachea y valida cuatro fuentes de datos de forma aislada entre si.

Cuatro fuentes, cada una con su propia funcion de fetch + parseo + cache +
manejo de errores (si una falla, no tumba a las demas):

1. Real yields: FRED, DFII10 (TIPS 10y, real ya calculado) + DGS10 (nominal,
   contexto).
2. DXY: yfinance primero (ticker DX-Y.NYB), con fallback automatico a Stooq
   si yfinance falla -- DX-Y.NYB tiene fallos de fiabilidad documentados en
   Yahoo Finance (ver macro_config.py).
3. COT: CFTC Disaggregated Futures-Only para oro (COMEX, codigo 088691),
   posicion neta de "managed money" (largos - cortos) y su percentil sobre
   los ultimos ~3 anos.
4. Calendario: proximos NFP y CPI via el calendario de publicaciones de
   FRED (release_id 50 y 10), y proximas reuniones FOMC via una lista
   estatica en macro_config.py (no encontramos una fuente gratuita con API
   estable para el calendario forward de la Fed -- ver README).

Uso:
    python macro_engine.py --check      # sanity check en vivo de las 4 fuentes
    python macro_engine.py --collect    # descarga (o usa cache) y guarda
    python macro_engine.py --collect --no-cache   # fuerza descarga fresca
"""
import argparse
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

import macro_config as cfg
import macro_database as macrodb

logger = logging.getLogger("macro_engine")


class MacroDataError(RuntimeError):
    """Error al obtener o parsear datos de una fuente macro concreta."""


# ---------------------------------------------------------------------------
# 1. Real yields (FRED)
# ---------------------------------------------------------------------------

@dataclass
class RealYieldSnapshot:
    date: str                  # YYYY-MM-DD, fecha de la observacion FRED
    dfii10: Optional[float]    # real yield TIPS 10y
    dgs10: Optional[float]     # nominal yield 10y, contexto


def _fred_get(endpoint: str, params: dict) -> dict:
    if not cfg.FRED_API_KEY:
        raise MacroDataError("FRED_API_KEY no configurada (ver .env.example / README)")
    query = dict(params)
    query["api_key"] = cfg.FRED_API_KEY
    query["file_type"] = "json"
    resp = requests.get(f"{cfg.FRED_BASE_URL}/{endpoint}", params=query, timeout=cfg.HTTP_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json()


def parse_fred_latest_observation(payload: dict, series_id: str) -> Optional[float]:
    """Ultimo valor no-nulo de una serie FRED. FRED usa "." para dias sin
    dato (feriados, etc.); se ignoran y se toma el ultimo valor real."""
    observations = payload.get("observations")
    if not observations:
        raise MacroDataError(f"Respuesta de FRED sin 'observations' para {series_id}: {payload}")
    for obs in reversed(observations):
        value = obs.get("value")
        if value not in (None, ".", ""):
            return float(value)
    return None


def fetch_real_yields(use_cache: bool = True) -> RealYieldSnapshot:
    """DFII10 (real) + DGS10 (nominal, contexto) de FRED. Cachea por dia."""
    conn = macrodb.init_db(cfg.MACRO_DB_PATH)
    try:
        cached = macrodb.get_fresh_snapshot(conn, "real_yields", cfg.CACHE_MAX_AGE_HOURS["real_yields"])
        if use_cache and cached is not None:
            logger.info("real_yields: usando cache (%s, fetched_at=%s)", cached.as_of, cached.fetched_at)
            return RealYieldSnapshot(**cached.payload)

        params_common = {"sort_order": "desc", "limit": 5}
        real_payload = _fred_get("series/observations", {"series_id": cfg.REAL_YIELD_SERIES_ID, **params_common})
        dfii10 = parse_fred_latest_observation(real_payload, cfg.REAL_YIELD_SERIES_ID)

        nominal_value = None
        try:
            nominal_payload = _fred_get("series/observations", {"series_id": cfg.NOMINAL_YIELD_SERIES_ID, **params_common})
            nominal_value = parse_fred_latest_observation(nominal_payload, cfg.NOMINAL_YIELD_SERIES_ID)
        except MacroDataError as exc:
            logger.warning("real_yields: no se pudo obtener DGS10 (nominal, no bloqueante): %s", exc)

        observations = real_payload.get("observations", [])
        as_of = next((o["date"] for o in reversed(observations) if o.get("value") not in (None, ".", "")), None)
        if as_of is None:
            raise MacroDataError(f"Ninguna observacion valida de {cfg.REAL_YIELD_SERIES_ID} en la respuesta")

        snapshot = RealYieldSnapshot(date=as_of, dfii10=dfii10, dgs10=nominal_value)
        macrodb.save_snapshot(conn, "real_yields", as_of, asdict(snapshot))
        logger.info("real_yields: DFII10=%s DGS10=%s (%s)", dfii10, nominal_value, as_of)
        return snapshot
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. DXY (indice dolar)
# ---------------------------------------------------------------------------

@dataclass
class DxySnapshot:
    date: str
    close: float
    source: str  # "yfinance" | "stooq"


def _fetch_dxy_yfinance() -> Optional[DxySnapshot]:
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("dxy: paquete yfinance no instalado, se salta a stooq")
        return None
    try:
        hist = yf.Ticker(cfg.DXY_YFINANCE_TICKER).history(period="5d", interval="1d")
    except Exception as exc:  # yfinance lanza varios tipos segun el fallo (HTTP, parseo, etc.)
        logger.warning("dxy: yfinance fallo para %s: %s", cfg.DXY_YFINANCE_TICKER, exc)
        return None
    if hist is None or hist.empty or "Close" not in hist.columns:
        logger.warning("dxy: yfinance devolvio datos vacios/incompletos para %s", cfg.DXY_YFINANCE_TICKER)
        return None
    closes = hist.dropna(subset=["Close"])
    if closes.empty:
        return None
    last = closes.iloc[-1]
    as_of = closes.index[-1]
    return DxySnapshot(date=as_of.strftime("%Y-%m-%d"), close=float(last["Close"]), source="yfinance")


def parse_stooq_csv(text: str) -> Optional[DxySnapshot]:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        logger.warning("dxy: respuesta de stooq sin filas de datos: %r", text[:200])
        return None
    header = lines[0].split(",")
    expected = {"Date", "Open", "High", "Low", "Close", "Volume"}
    if not expected.issubset(set(header)):
        raise MacroDataError(f"Formato de CSV de stooq inesperado, columnas: {header}")
    row = dict(zip(header, lines[-1].split(",")))
    try:
        close = float(row["Close"])
    except (KeyError, ValueError) as exc:
        raise MacroDataError(f"No se pudo parsear el cierre de stooq: {row}") from exc
    return DxySnapshot(date=row["Date"], close=close, source="stooq")


def _fetch_dxy_stooq() -> Optional[DxySnapshot]:
    try:
        resp = requests.get(cfg.DXY_STOOQ_URL, timeout=cfg.HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("dxy: stooq fallo: %s", exc)
        return None
    return parse_stooq_csv(resp.text)


def fetch_dxy(use_cache: bool = True) -> DxySnapshot:
    """DXY diario: yfinance primero, fallback automatico a stooq (ver
    macro_config.py para por que)."""
    conn = macrodb.init_db(cfg.MACRO_DB_PATH)
    try:
        cached = macrodb.get_fresh_snapshot(conn, "dxy", cfg.CACHE_MAX_AGE_HOURS["dxy"])
        if use_cache and cached is not None:
            logger.info("dxy: usando cache (%s, fuente=%s)", cached.as_of, cached.payload.get("source"))
            return DxySnapshot(**cached.payload)

        snapshot = _fetch_dxy_yfinance()
        if snapshot is None:
            logger.info("dxy: yfinance no disponible, probando fallback stooq")
            snapshot = _fetch_dxy_stooq()
        if snapshot is None:
            raise MacroDataError("No se pudo obtener DXY ni por yfinance ni por stooq")

        macrodb.save_snapshot(conn, "dxy", snapshot.date, asdict(snapshot))
        logger.info("dxy: close=%.3f (%s, fuente=%s)", snapshot.close, snapshot.date, snapshot.source)
        return snapshot
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. COT (CFTC Disaggregated Futures-Only, oro)
# ---------------------------------------------------------------------------

@dataclass
class CotSnapshot:
    report_date: str           # posiciones al martes; el CFTC publica el viernes siguiente
    managed_money_long: int
    managed_money_short: int
    managed_money_net: int
    percentile_3y: float       # percentil 0-100 del net actual vs ~3 anos de historia
    n_reports_in_window: int
    extreme: Optional[str]     # "long" | "short" | None


_MM_LONG_FIELD_CANDIDATES = ["m_money_positions_long_all", "m_money_positions_long_old"]
_MM_SHORT_FIELD_CANDIDATES = ["m_money_positions_short_all", "m_money_positions_short_old"]


def extract_cftc_field(row: dict, candidates: List[str]) -> int:
    for name in candidates:
        if name in row and row[name] not in (None, ""):
            return int(float(row[name]))
    raise MacroDataError(
        f"Ninguno de los campos esperados {candidates} esta presente en la fila del CFTC. "
        f"Campos disponibles: {sorted(row.keys())}. El dataset pudo haber cambiado de esquema "
        "(ver https://publicreporting.cftc.gov/resource/72hh-3qpy.json)."
    )


def _fetch_cftc_rows(where_clause: str, limit: int) -> List[dict]:
    params = {"$where": where_clause, "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": limit}
    resp = requests.get(cfg.CFTC_SOCRATA_BASE_URL, params=params, timeout=cfg.HTTP_TIMEOUT_SECONDS)
    resp.raise_for_status()
    rows = resp.json()
    if not isinstance(rows, list):
        raise MacroDataError(f"Respuesta inesperada del CFTC (se esperaba una lista JSON): {type(rows)}")
    return rows


def _fetch_cftc_gold_history(lookback_years: int) -> List[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=365 * lookback_years + 14)).strftime("%Y-%m-%dT00:00:00")
    where_by_code = f"cftc_contract_market_code='{cfg.CFTC_GOLD_CONTRACT_CODE}' AND report_date_as_yyyy_mm_dd > '{since}'"
    rows = _fetch_cftc_rows(where_by_code, limit=500)
    if not rows:
        logger.warning("cot_gold: filtro por codigo de contrato no devolvio filas, probando por nombre")
        where_by_name = f"market_and_exchange_names='{cfg.CFTC_GOLD_NAME_FILTER}' AND report_date_as_yyyy_mm_dd > '{since}'"
        rows = _fetch_cftc_rows(where_by_name, limit=500)
    if not rows:
        raise MacroDataError(
            "El CFTC no devolvio ninguna fila para oro (ni por codigo de contrato ni por nombre). "
            "El dataset o el filtro pudieron cambiar; revisar "
            "https://publicreporting.cftc.gov/resource/72hh-3qpy.json manualmente."
        )
    return rows


def percentile_of_last(values: List[float]) -> float:
    """Percentil (0-100) del ultimo valor de la serie respecto a toda la
    serie (incluyendose a si mismo). Sin dependencia de scipy."""
    if not values:
        raise MacroDataError("Serie vacia, no se puede calcular percentil")
    current = values[-1]
    rank = sum(1 for v in values if v <= current)
    return round(rank / len(values) * 100, 1)


def fetch_cot_gold(use_cache: bool = True) -> CotSnapshot:
    conn = macrodb.init_db(cfg.MACRO_DB_PATH)
    try:
        cached = macrodb.get_fresh_snapshot(conn, "cot_gold", cfg.CACHE_MAX_AGE_HOURS["cot_gold"])
        if use_cache and cached is not None:
            logger.info("cot_gold: usando cache (report_date=%s)", cached.as_of)
            return CotSnapshot(**cached.payload)

        rows = _fetch_cftc_gold_history(cfg.COT_LOOKBACK_YEARS)
        rows_chrono = list(reversed(rows))  # la API devuelve DESC; para el percentil hace falta ASC

        nets = [
            extract_cftc_field(row, _MM_LONG_FIELD_CANDIDATES) - extract_cftc_field(row, _MM_SHORT_FIELD_CANDIDATES)
            for row in rows_chrono
        ]

        latest_row = rows_chrono[-1]
        latest_long = extract_cftc_field(latest_row, _MM_LONG_FIELD_CANDIDATES)
        latest_short = extract_cftc_field(latest_row, _MM_SHORT_FIELD_CANDIDATES)
        report_date = str(latest_row.get("report_date_as_yyyy_mm_dd", ""))[:10]
        if not report_date:
            raise MacroDataError(f"Fila del CFTC sin report_date_as_yyyy_mm_dd: {latest_row}")

        percentile = percentile_of_last(nets)
        extreme = None
        if percentile >= cfg.COT_PERCENTILE_HIGH:
            extreme = "long"
        elif percentile <= cfg.COT_PERCENTILE_LOW:
            extreme = "short"

        snapshot = CotSnapshot(
            report_date=report_date,
            managed_money_long=latest_long,
            managed_money_short=latest_short,
            managed_money_net=latest_long - latest_short,
            percentile_3y=percentile,
            n_reports_in_window=len(nets),
            extreme=extreme,
        )
        macrodb.save_snapshot(conn, "cot_gold", report_date, asdict(snapshot))
        logger.info(
            "cot_gold: net=%d percentil_3y=%.1f (%d reportes) extreme=%s (%s)",
            snapshot.managed_money_net, percentile, len(nets), extreme, report_date,
        )
        return snapshot
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. Calendario de eventos de alto impacto
# ---------------------------------------------------------------------------

@dataclass
class CalendarEvent:
    name: str           # "NFP" | "CPI" | "FOMC"
    datetime_utc: str    # ISO 8601 UTC
    source: str


def _fred_release_dates(release_id: int, event_name: str) -> List[CalendarEvent]:
    payload = _fred_get(
        "releases/dates",
        {
            "release_id": release_id,
            "include_release_dates_with_no_data": "true",
            "sort_order": "desc",
            "limit": 100,
        },
    )
    dates = payload.get("release_dates")
    if dates is None:
        raise MacroDataError(f"Respuesta de FRED sin 'release_dates' para release_id={release_id}: {payload}")

    tz = ZoneInfo(cfg.US_TIMEZONE)
    hour, minute = cfg.US_BLS_RELEASE_TIME_ET
    events = []
    for d in dates:
        date_str = d.get("date")
        if not date_str:
            continue
        local_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hour, minute=minute, tzinfo=tz)
        events.append(CalendarEvent(
            name=event_name,
            datetime_utc=local_dt.astimezone(timezone.utc).isoformat(),
            source=f"FRED release_id={release_id} (fecha) + hora estandar BLS {hour:02d}:{minute:02d} ET (no viene de la API)",
        ))
    return events


def _fomc_events() -> List[CalendarEvent]:
    tz = ZoneInfo(cfg.US_TIMEZONE)
    hour, minute = cfg.FOMC_DECISION_TIME_ET
    events = []
    for date_str in cfg.FOMC_MEETING_DATES:
        local_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hour, minute=minute, tzinfo=tz)
        events.append(CalendarEvent(
            name="FOMC",
            datetime_utc=local_dt.astimezone(timezone.utc).isoformat(),
            source="lista estatica en macro_config.py (actualizar manualmente, ver README)",
        ))
    return events


def fetch_economic_calendar(use_cache: bool = True, lookahead_days: int = cfg.HIGH_IMPACT_EVENTS_LOOKAHEAD_DAYS) -> List[CalendarEvent]:
    """Proximos eventos NFP/CPI/FOMC dentro de `lookahead_days`."""
    conn = macrodb.init_db(cfg.MACRO_DB_PATH)
    try:
        today = datetime.now(timezone.utc).date().isoformat()
        cached = macrodb.get_fresh_snapshot(conn, "econ_calendar", cfg.CACHE_MAX_AGE_HOURS["econ_calendar"])
        if use_cache and cached is not None:
            logger.info("econ_calendar: usando cache (%s)", cached.as_of)
            events = [CalendarEvent(**e) for e in cached.payload["events"]]
        else:
            events = []
            try:
                events.extend(_fred_release_dates(cfg.FRED_RELEASE_ID_NFP, "NFP"))
            except MacroDataError as exc:
                logger.error("econ_calendar: fallo NFP (FRED release_id=%d): %s", cfg.FRED_RELEASE_ID_NFP, exc)
            try:
                events.extend(_fred_release_dates(cfg.FRED_RELEASE_ID_CPI, "CPI"))
            except MacroDataError as exc:
                logger.error("econ_calendar: fallo CPI (FRED release_id=%d): %s", cfg.FRED_RELEASE_ID_CPI, exc)
            try:
                events.extend(_fomc_events())
            except Exception as exc:
                logger.error("econ_calendar: fallo FOMC (lista estatica): %s", exc)

            macrodb.save_snapshot(conn, "econ_calendar", today, {"events": [asdict(e) for e in events]})

        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=lookahead_days)
        upcoming = [e for e in events if now <= datetime.fromisoformat(e.datetime_utc) <= cutoff]
        upcoming.sort(key=lambda e: e.datetime_utc)
        logger.info("econ_calendar: %d eventos en los proximos %d dias", len(upcoming), lookahead_days)
        return upcoming
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Orquestador -- SOLO ingesta, no combina ni califica nada
# ---------------------------------------------------------------------------

def collect_all(use_cache: bool = True) -> Dict[str, Dict[str, Any]]:
    """Descarga (o usa cache) las 4 fuentes, cada una aislada en su propio
    try/except: si una falla, las demas se siguen intentando. Devuelve
    {source: {"ok", "data", "error"}}. NO calcula ningun score ni bias."""
    results: Dict[str, Dict[str, Any]] = {}
    sources = {
        "real_yields": lambda: fetch_real_yields(use_cache),
        "dxy": lambda: fetch_dxy(use_cache),
        "cot_gold": lambda: fetch_cot_gold(use_cache),
        "econ_calendar": lambda: fetch_economic_calendar(use_cache),
    }
    for source, fn in sources.items():
        try:
            results[source] = {"ok": True, "data": fn(), "error": None}
        except Exception as exc:  # aislamiento deliberado: una fuente caida no tumba a las demas
            logger.exception("%s: fallo la descarga", source)
            results[source] = {"ok": False, "data": None, "error": str(exc)}
    return results


# ---------------------------------------------------------------------------
# Sanity checks -- descargan en vivo (sin cache) y validan forma/rango
# ---------------------------------------------------------------------------

def sanity_check_real_yields() -> None:
    snap = fetch_real_yields(use_cache=False)
    assert isinstance(snap.dfii10, float), f"dfii10 deberia ser float, es {type(snap.dfii10)}"
    assert -3.0 < snap.dfii10 < 6.0, f"dfii10={snap.dfii10} fuera de rango plausible"
    assert len(snap.date) == 10, f"fecha con formato inesperado: {snap.date}"


def sanity_check_dxy() -> None:
    snap = fetch_dxy(use_cache=False)
    assert isinstance(snap.close, float), f"close deberia ser float, es {type(snap.close)}"
    assert 70.0 < snap.close < 130.0, f"DXY={snap.close} fuera de rango plausible"
    assert snap.source in ("yfinance", "stooq"), f"fuente inesperada: {snap.source}"


def sanity_check_cot_gold() -> None:
    snap = fetch_cot_gold(use_cache=False)
    assert isinstance(snap.managed_money_net, int)
    assert 0 <= snap.percentile_3y <= 100, f"percentil fuera de rango: {snap.percentile_3y}"
    assert snap.n_reports_in_window >= 20, (
        f"solo {snap.n_reports_in_window} reportes en la ventana -- "
        "muy pocos para que el percentil de 3 anos sea representativo"
    )


def sanity_check_econ_calendar() -> None:
    events = fetch_economic_calendar(use_cache=False)
    assert isinstance(events, list)
    now = datetime.now(timezone.utc)
    for e in events:
        assert e.name in ("NFP", "CPI", "FOMC"), f"nombre de evento inesperado: {e.name}"
        assert datetime.fromisoformat(e.datetime_utc) > now, f"evento en el pasado devuelto como proximo: {e}"


def run_sanity_checks() -> Dict[str, Dict[str, Any]]:
    checks = {
        "real_yields": sanity_check_real_yields,
        "dxy": sanity_check_dxy,
        "cot_gold": sanity_check_cot_gold,
        "econ_calendar": sanity_check_econ_calendar,
    }
    results: Dict[str, Dict[str, Any]] = {}
    for name, check_fn in checks.items():
        try:
            check_fn()
            results[name] = {"ok": True, "error": None}
            logger.info("[OK] %s", name)
        except Exception as exc:
            results[name] = {"ok": False, "error": str(exc)}
            logger.error("[FALLO] %s: %s", name, exc)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _to_jsonable(value: Any) -> Any:
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value


def _setup_logging() -> None:
    level = getattr(logging, cfg.LOG_LEVEL.upper(), logging.INFO)
    from pathlib import Path
    Path(cfg.LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(cfg.LOG_PATH, encoding="utf-8")],
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingesta de datos macro (Fase 2, SOLO ingesta -- no calcula score ni bias)."
    )
    parser.add_argument("--check", action="store_true", help="Sanity check en vivo de las 4 fuentes (ignora cache).")
    parser.add_argument("--collect", action="store_true", help="Descarga (o usa cache) las 4 fuentes y las cachea.")
    parser.add_argument("--no-cache", action="store_true", help="Con --collect, fuerza descarga fresca.")
    args = parser.parse_args()

    _setup_logging()

    if not args.check and not args.collect:
        parser.print_help()
        return 0

    any_failure = False

    if args.check:
        print("== Sanity check en vivo (ignora cache) ==")
        for source, result in run_sanity_checks().items():
            print(f"[{'OK' if result['ok'] else 'FALLO'}] {source}" + (f": {result['error']}" if result["error"] else ""))
            any_failure = any_failure or not result["ok"]

    if args.collect:
        print("== Recoleccion (usa cache si esta fresca, salvo --no-cache) ==")
        for source, result in collect_all(use_cache=not args.no_cache).items():
            if result["ok"]:
                print(f"[OK] {source}: {json.dumps(_to_jsonable(result['data']), indent=2, default=str, ensure_ascii=False)}")
            else:
                print(f"[FALLO] {source}: {result['error']}")
            any_failure = any_failure or not result["ok"]

    return 1 if any_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
