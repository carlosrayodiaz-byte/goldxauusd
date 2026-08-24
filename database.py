"""
Esquema SQLite y funciones de insercion/consulta para la tabla `signals`.
No conoce MT5 ni smartmoneyconcepts: solo recibe valores ya calculados.

Idempotencia: hay un indice UNIQUE sobre las columnas que identifican de forma
natural una deteccion concreta (mismo simbolo, mismo origen live/backtest,
mismo timeframe/tipo/direccion de trigger, misma vela y mismos limites de
precio). Reiniciar el bot y volver a procesar la misma ventana de velas no
genera duplicados: se usa INSERT OR IGNORE.
"""
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at TEXT NOT NULL,
    candle_time TEXT NOT NULL,
    symbol TEXT NOT NULL,
    source TEXT NOT NULL,
    bias_direction TEXT NOT NULL,
    bias_timeframe TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    trigger_direction TEXT NOT NULL,
    trigger_timeframe TEXT NOT NULL,
    price_at_detection REAL NOT NULL,
    top REAL,
    bottom REAL,
    confluente INTEGER NOT NULL,
    notas TEXT,
    UNIQUE (
        symbol, source, trigger_timeframe, trigger_type,
        trigger_direction, candle_time, top, bottom
    )
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_time ON signals (symbol, candle_time);
CREATE INDEX IF NOT EXISTS idx_signals_source ON signals (source);
"""


@dataclass
class SignalRecord:
    symbol: str
    source: str  # "live" | "backtest"
    bias_direction: str
    bias_timeframe: str
    trigger_type: str
    trigger_direction: str
    trigger_timeframe: str
    candle_time: str  # ISO 8601 UTC
    price_at_detection: float
    top: Optional[float]
    bottom: Optional[float]
    confluente: bool
    notas: str


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: str) -> sqlite3.Connection:
    conn = get_connection(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    logger.info("Base de datos inicializada en %s", db_path)
    return conn


@contextmanager
def connect(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = init_db(db_path)
    try:
        yield conn
    finally:
        conn.close()


def insert_signal(conn: sqlite3.Connection, record: SignalRecord) -> bool:
    """Inserta una senal. Devuelve True si se inserto, False si ya existia
    (duplicado ignorado por el indice UNIQUE)."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO signals (
            detected_at, candle_time, symbol, source,
            bias_direction, bias_timeframe,
            trigger_type, trigger_direction, trigger_timeframe,
            price_at_detection, top, bottom, confluente, notas
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            record.candle_time,
            record.symbol,
            record.source,
            record.bias_direction,
            record.bias_timeframe,
            record.trigger_type,
            record.trigger_direction,
            record.trigger_timeframe,
            record.price_at_detection,
            record.top,
            record.bottom,
            int(record.confluente),
            record.notas,
        ),
    )
    conn.commit()
    return cur.rowcount > 0


def count_signals(conn: sqlite3.Connection, **filters) -> int:
    where, params = _build_where(filters)
    row = conn.execute(f"SELECT COUNT(*) AS n FROM signals {where}", params).fetchone()
    return row["n"]


def fetch_signals(conn: sqlite3.Connection, limit: int = 100, **filters) -> list:
    where, params = _build_where(filters)
    rows = conn.execute(
        f"SELECT * FROM signals {where} ORDER BY candle_time DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    return [dict(r) for r in rows]


def _build_where(filters: dict):
    if not filters:
        return "", []
    clauses = [f"{col} = ?" for col in filters]
    return "WHERE " + " AND ".join(clauses), list(filters.values())
