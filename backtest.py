"""
Backtest offline: corre el mismo motor SMC (smc_engine.py) sobre datos
historicos descargados de MT5 y guarda las senales en la misma base de datos
que usa main.py, pero marcadas con source="backtest". Pensado para validar
el motor de deteccion ANTES de dejarlo corriendo en vivo.

Metodologia sin look-ahead (ver docstring de smc_engine.py para el detalle):
se construye una linea de tiempo de bias en M15/H1 donde cada cambio de bias
solo "existe" desde la vela que efectivamente lo confirma, y se le asigna a
cada trigger de M1/M5 el bias vigente en su propio candle_time via
merge_asof(direction="backward"). Esto reproduce lo que el bot habria visto
corriendo en vivo minuto a minuto, sin usar informacion futura.

Ademas de guardar las senales, escribe un reporte de diagnostico
(data/backtest_diagnostics.txt) con lo que NO cabe en la tabla `signals`:
cobertura real de datos por timeframe, huecos sospechosos en las velas
descargadas, duplicados, el offset estimado del reloj del servidor MT5 vs
UTC real, y ventanas de varios dias seguidos sin ninguna senal generada.

Uso:
    python backtest.py --months 3
"""
import argparse
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import pandas as pd

import config
import database
import smc_engine
from main import setup_logging
from mt5_client import MT5Client

logger = logging.getLogger("xauusd_backtest")

GAP_THRESHOLD_HOURS = 4.0  # huecos en las velas crudas por encima de esto se reportan
MIN_SIGNAL_GAP_DAYS = 2    # ventanas sin ninguna senal de al menos N dias seguidos


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest del motor SMC sobre historico de MT5.")
    parser.add_argument(
        "--months", type=int, default=config.BACKTEST_MONTHS,
        help=f"Meses de historico a descargar (default: {config.BACKTEST_MONTHS})",
    )
    parser.add_argument("--symbol", type=str, default=config.SYMBOL)
    return parser.parse_args()


def _diagnose_ohlc(df: pd.DataFrame, timeframe: str, gap_threshold_hours: float = GAP_THRESHOLD_HOURS) -> dict:
    """Metricas de sanidad sobre las velas crudas descargadas: cobertura real,
    timestamps duplicados y huecos de tiempo mayores al umbral (que pueden ser
    cierres de fin de semana normales, o caidas de feed del broker)."""
    if df.empty:
        return {
            "timeframe": timeframe, "n_candles": 0, "first_time": None, "last_time": None,
            "duplicate_timestamps": 0, "gaps": [],
        }

    times = df["time"]
    duplicate_timestamps = int(times.duplicated().sum())

    deltas = times.diff()
    threshold = pd.Timedelta(hours=gap_threshold_hours)
    gaps = []
    for i in deltas.index[1:]:
        if pd.notna(deltas.loc[i]) and deltas.loc[i] > threshold:
            gaps.append({
                "start": times.iloc[i - 1],
                "end": times.iloc[i],
                "duration_hours": deltas.loc[i].total_seconds() / 3600.0,
            })

    return {
        "timeframe": timeframe,
        "n_candles": len(df),
        "first_time": times.iloc[0],
        "last_time": times.iloc[-1],
        "duplicate_timestamps": duplicate_timestamps,
        "gaps": gaps,
    }


def _signal_gap_windows(
    df_m1: pd.DataFrame,
    all_signals: List[smc_engine.TriggerSignal],
    bias_timeline: pd.DataFrame,
    min_days: int = MIN_SIGNAL_GAP_DAYS,
) -> List[dict]:
    """Dias calendario (dentro del rango cubierto por M1) en los que el motor
    NO genero NINGUN trigger (ni M1 ni M5, confluente o no), agrupados en
    ventanas de `min_days` o mas dias consecutivos. Para cada ventana se
    reporta si hubo velas M1 ese dia (dato disponible o no) y que bias
    predomino, como contexto descriptivo, sin sacar conclusiones."""
    if df_m1.empty:
        return []

    all_days = pd.date_range(df_m1["time"].min().floor("D"), df_m1["time"].max().floor("D"), freq="D")
    m1_days = set(df_m1["time"].dt.floor("D"))
    signal_days = {pd.Timestamp(s.candle_time).floor("D") for s in all_signals}

    missing = [d for d in all_days if d not in signal_days]

    windows: List[List[pd.Timestamp]] = []
    current: List[pd.Timestamp] = []
    for d in missing:
        if current and (d - current[-1]).days == 1:
            current.append(d)
        else:
            if current:
                windows.append(current)
            current = [d]
    if current:
        windows.append(current)
    windows = [w for w in windows if len(w) >= min_days]

    result = []
    for w in windows:
        start, end = w[0], w[-1]
        m1_data_present_days = sum(1 for d in w if d in m1_days)
        mask = (bias_timeline["time"] >= start) & (bias_timeline["time"] <= end + pd.Timedelta(days=1))
        bias_counts = bias_timeline.loc[mask, "direction"].value_counts().to_dict()
        result.append({
            "start": start,
            "end": end,
            "days": len(w),
            "m1_data_present_days": m1_data_present_days,
            "m1_missing_days": len(w) - m1_data_present_days,
            "bias_direction_counts": bias_counts,
        })
    return result


def _write_diagnostics_report(
    path: Path,
    symbol: str,
    date_from: datetime,
    date_to: datetime,
    offset_hours: Optional[float],
    ohlc_diagnostics: List[dict],
    gap_windows: List[dict],
    stats: Counter,
    by_type_conf: Counter,
) -> None:
    lines = []
    lines.append(f"Backtest diagnostics — {symbol}")
    lines.append(f"Generado (UTC): {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"Rango solicitado: {date_from.isoformat()} -> {date_to.isoformat()}")
    if offset_hours is not None:
        lines.append(
            f"Offset estimado servidor MT5 vs UTC real: {offset_hours:+.2f} horas "
            "(ver 'Limitaciones conocidas' en README: los timestamps guardados estan "
            "en hora del servidor del broker, etiquetados como UTC)"
        )
    else:
        lines.append("Offset estimado servidor MT5 vs UTC real: no se pudo estimar (sin tick reciente)")
    lines.append("")

    lines.append("== Cobertura real de datos OHLC descargados ==")
    for d in ohlc_diagnostics:
        if d["n_candles"] == 0:
            lines.append(f"{d['timeframe']}: SIN VELAS")
            continue
        lines.append(
            f"{d['timeframe']}: {d['n_candles']} velas | {d['first_time']} -> {d['last_time']} "
            f"| timestamps duplicados: {d['duplicate_timestamps']}"
        )
        if d["gaps"]:
            lines.append(f"  huecos > {GAP_THRESHOLD_HOURS}h ({len(d['gaps'])}):")
            for g in d["gaps"]:
                lines.append(f"    {g['start']} -> {g['end']}  ({g['duration_hours']:.1f}h)")
        else:
            lines.append(f"  sin huecos > {GAP_THRESHOLD_HOURS}h")
    lines.append("")

    lines.append(f"== Ventanas de {MIN_SIGNAL_GAP_DAYS}+ dias seguidos sin NINGUNA senal (M1+M5) ==")
    if not gap_windows:
        lines.append("(ninguna)")
    for w in gap_windows:
        lines.append(
            f"{w['start'].date()} -> {w['end'].date()} ({w['days']} dias) | "
            f"dias con velas M1 presentes: {w['m1_data_present_days']}/{w['days']} | "
            f"dias sin velas M1: {w['m1_missing_days']}/{w['days']} | "
            f"bias observado en la ventana: {w['bias_direction_counts']}"
        )
    lines.append("")

    lines.append("== Resumen de senales (esta corrida) ==")
    lines.append(f"Nuevas insertadas: {stats['new']} | Confluentes (de las nuevas): {stats['confluent']} | Duplicadas ya existentes: {stats['dup']}")
    lines.append("Desglose por tipo (nuevas, confluente/no):")
    for (ttype, conf), n in sorted(by_type_conf.items()):
        lines.append(f"  {ttype:16s} confluente={conf!s:5s} -> {n}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Reporte de diagnostico escrito en %s", path)


def run_backtest(months: int, symbol: str) -> None:
    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=months * 30)
    logger.info("Backtest de %s: %s -> %s (%d meses solicitados)", symbol, date_from, date_to, months)

    client = MT5Client()
    client.connect()
    conn = database.init_db(config.DB_PATH)

    try:
        offset_hours = client.estimate_server_offset_hours(symbol)
        if offset_hours is not None:
            logger.info("Offset estimado servidor MT5 vs UTC real: %+.2f horas", offset_hours)

        logger.info("Descargando historico de MT5 (puede tardar varios minutos en M1)...")
        dataframes = {}
        ohlc_diagnostics = []
        for tf in config.ALL_TIMEFRAMES:
            df = client.get_ohlc_range(symbol, tf, date_from, date_to)
            diag = _diagnose_ohlc(df, tf)
            ohlc_diagnostics.append(diag)
            if df.empty:
                logger.warning("%s: SIN VELAS descargadas", tf)
            else:
                logger.info(
                    "%s: %d velas descargadas | cobertura real: %s -> %s | duplicados=%d | huecos>%sh=%d",
                    tf, diag["n_candles"], diag["first_time"], diag["last_time"],
                    diag["duplicate_timestamps"], GAP_THRESHOLD_HOURS, len(diag["gaps"]),
                )
            if df.empty:
                raise RuntimeError(
                    f"No se recibieron velas de {tf} para {symbol}. "
                    "Revisa el nombre del simbolo en el Market Watch de MT5 y el rango de fechas."
                )
            dataframes[tf] = df

        actual_days = (dataframes["M1"]["time"].max() - dataframes["M1"]["time"].min()).days
        logger.info(
            "Cobertura real de M1: %d dias (%d velas) — solicitados %d meses (~%d dias)",
            actual_days, len(dataframes["M1"]), months, months * 30,
        )

        logger.info("Calculando linea de tiempo de bias (M15/H1)...")
        bias_timeline = smc_engine.compute_bias_timeline(dataframes["M15"], dataframes["H1"])

        stats = Counter()
        by_type_conf = Counter()
        all_signals: List[smc_engine.TriggerSignal] = []

        for tf in config.TRIGGER_TIMEFRAMES:
            df = dataframes[tf]
            logger.info("Calculando triggers en %s (%d velas)...", tf, len(df))
            signals = smc_engine.compute_triggers_with_bias_timeline(df, tf, bias_timeline)
            logger.info("%s: %d triggers detectados en todo el historico", tf, len(signals))
            all_signals.extend(signals)

            for s in signals:
                record = database.SignalRecord(
                    symbol=symbol,
                    source="backtest",
                    bias_direction=s.bias_direction,
                    bias_timeframe=s.bias_timeframe,
                    trigger_type=s.trigger_type,
                    trigger_direction=s.trigger_direction,
                    trigger_timeframe=s.trigger_timeframe,
                    candle_time=s.candle_time.isoformat(),
                    price_at_detection=s.price_at_detection,
                    top=s.top,
                    bottom=s.bottom,
                    confluente=s.confluente,
                    notas=s.notas,
                )
                inserted = database.insert_signal(conn, record)
                stats["new" if inserted else "dup"] += 1
                if inserted:
                    stats["confluent"] += int(s.confluente)
                    by_type_conf[(s.trigger_type, s.confluente)] += 1

        logger.info(
            "Backtest completo: %d senales nuevas (%d confluentes), %d duplicadas descartadas.",
            stats["new"], stats["confluent"], stats["dup"],
        )
        logger.info("Desglose por tipo (nuevas, confluente/no):")
        for (ttype, conf), n in sorted(by_type_conf.items()):
            logger.info("  %-16s confluente=%-5s -> %d", ttype, conf, n)

        logger.info("Buscando ventanas de %d+ dias sin ninguna senal...", MIN_SIGNAL_GAP_DAYS)
        gap_windows = _signal_gap_windows(dataframes["M1"], all_signals, bias_timeline)
        for w in gap_windows:
            logger.info(
                "  SIN SENALES: %s -> %s (%d dias) | dias con M1: %d/%d | bias: %s",
                w["start"].date(), w["end"].date(), w["days"],
                w["m1_data_present_days"], w["days"], w["bias_direction_counts"],
            )

        diagnostics_path = Path(config.DB_PATH).parent / "backtest_diagnostics.txt"
        _write_diagnostics_report(
            diagnostics_path, symbol, date_from, date_to, offset_hours,
            ohlc_diagnostics, gap_windows, stats, by_type_conf,
        )

    finally:
        conn.close()
        client.disconnect()


def main() -> None:
    setup_logging()
    args = parse_args()
    run_backtest(months=args.months, symbol=args.symbol)


if __name__ == "__main__":
    main()
