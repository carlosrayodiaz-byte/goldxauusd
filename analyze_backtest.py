"""
Analiza una base de datos de señales (`signals.db`, generada por
backtest.py o main.py) y genera un informe legible en consola. Solo lee: no
modifica ni la base de datos ni ningun otro archivo.

Uso:
    python analyze_backtest.py --db data/signals.db
    python analyze_backtest.py --dry-run          # atajo -> data/dry_run_signals.db
    python analyze_backtest.py --db data/signals.db --source all   # incluye tambien source=live
"""
import argparse
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import config

DIAGNOSTICS_CANDIDATES = ["backtest_diagnostics.txt", "dry_run_diagnostics.txt"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Informe legible sobre una base de datos de señales (signals.db)."
    )
    parser.add_argument(
        "--db", type=str, default=None,
        help="Ruta a la base de datos SQLite (default: data/signals.db, o "
             "data/dry_run_signals.db si se pasa --dry-run).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Atajo: usa data/dry_run_signals.db en vez de data/signals.db.",
    )
    parser.add_argument(
        "--source", type=str, default="backtest",
        help="Filtra por source ('backtest', 'live', o 'all' para no filtrar). Default: backtest.",
    )
    parser.add_argument("--sample-size", type=int, default=18, help="Tamaño de la muestra aleatoria (15-20 recomendado).")
    parser.add_argument("--min-gap-days", type=int, default=2, help="Umbral de dias seguidos sin señales para reportarlo como hueco.")
    return parser.parse_args()


def resolve_db_path(args: argparse.Namespace) -> Path:
    if args.db:
        return Path(args.db)
    if args.dry_run:
        return Path(config.DB_PATH).parent / "dry_run_signals.db"
    return Path(config.DB_PATH)


def find_diagnostics_path(db_path: Path) -> Optional[Path]:
    candidates = DIAGNOSTICS_CANDIDATES
    if "dry_run" in db_path.stem:
        candidates = ["dry_run_diagnostics.txt", "backtest_diagnostics.txt"]
    for name in candidates:
        p = db_path.parent / name
        if p.exists():
            return p
    return None


def fetch_rows(conn: sqlite3.Connection, source: str) -> List[sqlite3.Row]:
    if source == "all":
        return conn.execute("SELECT * FROM signals").fetchall()
    return conn.execute("SELECT * FROM signals WHERE source = ?", (source,)).fetchall()


def fetch_random_confluent_sample(conn: sqlite3.Connection, source: str, n: int) -> List[sqlite3.Row]:
    where = "confluente = 1" if source == "all" else "confluente = 1 AND source = ?"
    params = () if source == "all" else (source,)
    return conn.execute(
        f"SELECT candle_time, trigger_type, trigger_direction, trigger_timeframe, "
        f"bias_direction, bias_timeframe, price_at_detection "
        f"FROM signals WHERE {where} ORDER BY RANDOM() LIMIT ?",
        (*params, n),
    ).fetchall()


def compute_date_range(rows: List[sqlite3.Row]):
    if not rows:
        return None
    times = [datetime.fromisoformat(r["candle_time"]) for r in rows]
    return min(times), max(times)


def compute_gap_windows(rows: List[sqlite3.Row], min_gap_days: int) -> List[dict]:
    if not rows:
        return []
    days_with_signals = {datetime.fromisoformat(r["candle_time"]).date() for r in rows}
    start, end = min(days_with_signals), max(days_with_signals)
    all_days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    missing = [d for d in all_days if d not in days_with_signals]

    windows: List[List] = []
    current: List = []
    for d in missing:
        if current and (d - current[-1]).days == 1:
            current.append(d)
        else:
            if current:
                windows.append(current)
            current = [d]
    if current:
        windows.append(current)

    return [{"start": w[0], "end": w[-1], "days": len(w)} for w in windows if len(w) >= min_gap_days]


def parse_m1_coverage_from_diagnostics(text: str) -> Optional[str]:
    """Extrae la linea de cobertura de M1 del reporte de backtest.py
    (formato: 'M1: 14400 velas | <inicio> -> <fin> | timestamps duplicados: N')."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("M1:") and "velas" in stripped:
            return stripped
    return None


def print_header(title: str) -> None:
    print()
    print(f"== {title} ==")


def main() -> int:
    args = parse_args()
    db_path = resolve_db_path(args)

    if not db_path.exists():
        print(f"[ERROR] No existe la base de datos: {db_path}")
        print("        Corre backtest.py (o backtest.py --dry-run) primero.")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    print(f"Analizando: {db_path}  (source={args.source})")

    rows = fetch_rows(conn, args.source)
    if not rows:
        print(f"\nSin señales en {db_path} con source={args.source!r}. Nada que reportar.")
        conn.close()
        return 0

    # --- 1. Rango de fechas y velas M1 totales -----------------------------
    print_header("1. Rango de fechas y cobertura de datos")
    date_range = compute_date_range(rows)
    if date_range:
        print(f"Rango cubierto por las señales: {date_range[0].isoformat()} -> {date_range[1].isoformat()}")

    diagnostics_path = find_diagnostics_path(db_path)
    diagnostics_text = None
    if diagnostics_path:
        diagnostics_text = diagnostics_path.read_text(encoding="utf-8")
        m1_line = parse_m1_coverage_from_diagnostics(diagnostics_text)
        if m1_line:
            print(f"Velas M1 procesadas (de {diagnostics_path.name}): {m1_line}")
        else:
            print(f"No se encontro la linea de cobertura de M1 en {diagnostics_path.name}.")
    else:
        print(
            "No se encontro backtest_diagnostics.txt / dry_run_diagnostics.txt junto a la base de datos: "
            "no se puede reportar el total de velas M1 procesadas, solo el rango cubierto por las señales."
        )

    # --- 2. Triggers totales por tipo ---------------------------------------
    print_header("2. Triggers totales por tipo")
    by_type = Counter(r["trigger_type"] for r in rows)
    for trigger_type in ("fvg", "order_block", "liquidity_sweep"):
        print(f"  {trigger_type:16s} {by_type.get(trigger_type, 0)}")
    otros = set(by_type) - {"fvg", "order_block", "liquidity_sweep"}
    for t in sorted(otros):
        print(f"  {t:16s} {by_type[t]} (tipo no reconocido)")
    print(f"  {'TOTAL':16s} {len(rows)}")

    # --- 3. Confluentes vs no confluentes -----------------------------------
    print_header("3. Confluencia")
    n_confluent = sum(1 for r in rows if r["confluente"])
    n_total = len(rows)
    n_non_confluent = n_total - n_confluent
    pct = (n_confluent / n_total * 100) if n_total else 0.0
    print(f"Confluentes:     {n_confluent} ({pct:.1f}%)")
    print(f"No confluentes:  {n_non_confluent} ({100 - pct:.1f}%)")

    # --- 4. Muestra aleatoria de señales confluentes ------------------------
    print_header(f"4. Muestra aleatoria de hasta {args.sample_size} señales confluentes")
    sample = fetch_random_confluent_sample(conn, args.source, args.sample_size)
    if not sample:
        print("(no hay señales confluentes con este filtro)")
    else:
        header = f"{'fecha/hora (UTC)':<26} {'tipo':<16} {'direccion':<9} {'bias':<9} {'bias_tf':<8} {'precio':>10}"
        print(header)
        print("-" * len(header))
        for r in sample:
            print(
                f"{r['candle_time']:<26} {r['trigger_type']:<16} {r['trigger_direction']:<9} "
                f"{r['bias_direction']:<9} {r['bias_timeframe']:<8} {r['price_at_detection']:>10.3f}"
            )

    # --- 5. Huecos de varios dias sin ninguna señal -------------------------
    print_header(f"5. Huecos de {args.min_gap_days}+ dias seguidos sin ninguna señal")
    gaps = compute_gap_windows(rows, args.min_gap_days)
    if not gaps:
        print("(ninguno)")
    else:
        for g in gaps:
            print(f"  {g['start'].isoformat()} -> {g['end'].isoformat()}  ({g['days']} dias)")
    print(
        "(calculado sobre los dias con/sin señales en la propia tabla `signals`; "
        "si backtest_diagnostics.txt esta disponible, cruzalo con la seccion de "
        "huecos de datos crudos de ahi para distinguir 'sin datos' de 'con datos pero sin señales')"
    )

    # --- 6. Resumen de backtest_diagnostics.txt -----------------------------
    print_header("6. backtest_diagnostics.txt")
    if diagnostics_text:
        print(f"(contenido de {diagnostics_path})\n")
        print(diagnostics_text)
    else:
        print("No existe. Correlo con: python backtest.py --months 3 (o --dry-run).")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
