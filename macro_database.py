"""
Cache local para la capa macro (Fase 2). Base de datos SQLite PROPIA
(data/macro_cache.db por defecto), separada de data/signals.db de Fase 1.
No importa ni depende de database.py -- este modulo es independiente.

Tabla `macro_snapshots`: un snapshot por (source, as_of). `as_of` es la
fecha/periodo que representa el dato (fecha de la observacion FRED, fecha
del reporte COT, etc.), no la fecha en que lo descargamos -- eso es
`fetched_at`. El payload completo se guarda como JSON en `payload_json`
para no tener que migrar el esquema cada vez que una fuente cambia de
forma.
"""
import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS macro_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    as_of TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE (source, as_of)
);
CREATE INDEX IF NOT EXISTS idx_macro_source_fetched ON macro_snapshots (source, fetched_at);
"""


@dataclass
class MacroSnapshot:
    source: str
    as_of: str
    fetched_at: datetime
    payload: Dict[str, Any]


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db(db_path: str) -> sqlite3.Connection:
    conn = get_connection(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


@contextmanager
def connect(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = init_db(db_path)
    try:
        yield conn
    finally:
        conn.close()


def save_snapshot(conn: sqlite3.Connection, source: str, as_of: str, payload: Dict[str, Any]) -> None:
    """Guarda (o sobreescribe si ya existia el mismo source+as_of) un
    snapshot. Idempotente: reintentar la misma descarga no crea filas
    duplicadas, solo actualiza `fetched_at` y el payload."""
    conn.execute(
        """
        INSERT INTO macro_snapshots (source, as_of, fetched_at, payload_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (source, as_of) DO UPDATE SET
            fetched_at = excluded.fetched_at,
            payload_json = excluded.payload_json
        """,
        (source, as_of, datetime.now(timezone.utc).isoformat(), json.dumps(payload)),
    )
    conn.commit()


def get_latest_snapshot(conn: sqlite3.Connection, source: str) -> Optional[MacroSnapshot]:
    row = conn.execute(
        "SELECT * FROM macro_snapshots WHERE source = ? ORDER BY as_of DESC LIMIT 1",
        (source,),
    ).fetchone()
    if row is None:
        return None
    return MacroSnapshot(
        source=row["source"],
        as_of=row["as_of"],
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
        payload=json.loads(row["payload_json"]),
    )


def get_fresh_snapshot(conn: sqlite3.Connection, source: str, max_age_hours: float) -> Optional[MacroSnapshot]:
    """Devuelve el ultimo snapshot de `source` solo si se descargo hace
    menos de `max_age_hours`; si no, devuelve None (hay que refrescar)."""
    snapshot = get_latest_snapshot(conn, source)
    if snapshot is None:
        return None
    age = datetime.now(timezone.utc) - snapshot.fetched_at
    if age > timedelta(hours=max_age_hours):
        return None
    return snapshot


def get_history(conn: sqlite3.Connection, source: str, limit: int = 500) -> list:
    """Historial de snapshots de una fuente, mas reciente primero. Uso, por
    ejemplo, para reconstruir la serie historica de COT sin volver a pedirla
    al CFTC en cada corrida."""
    rows = conn.execute(
        "SELECT * FROM macro_snapshots WHERE source = ? ORDER BY as_of DESC LIMIT ?",
        (source, limit),
    ).fetchall()
    return [
        MacroSnapshot(
            source=r["source"],
            as_of=r["as_of"],
            fetched_at=datetime.fromisoformat(r["fetched_at"]),
            payload=json.loads(r["payload_json"]),
        )
        for r in rows
    ]
