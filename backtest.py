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

Uso:
    python backtest.py --months 3
"""
import argparse
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

import config
import database
import smc_engine
from main import setup_logging
from mt5_client import MT5Client

logger = logging.getLogger("xauusd_backtest")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest del motor SMC sobre historico de MT5.")
    parser.add_argument(
        "--months", type=int, default=config.BACKTEST_MONTHS,
        help=f"Meses de historico a descargar (default: {config.BACKTEST_MONTHS})",
    )
    parser.add_argument("--symbol", type=str, default=config.SYMBOL)
    return parser.parse_args()


def run_backtest(months: int, symbol: str) -> None:
    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=months * 30)
    logger.info("Backtest de %s: %s -> %s (%d meses)", symbol, date_from, date_to, months)

    client = MT5Client()
    client.connect()
    conn = database.init_db(config.DB_PATH)

    try:
        logger.info("Descargando historico de MT5 (puede tardar varios minutos en M1)...")
        dataframes = {}
        for tf in config.ALL_TIMEFRAMES:
            df = client.get_ohlc_range(symbol, tf, date_from, date_to)
            logger.info("%s: %d velas descargadas", tf, len(df))
            if df.empty:
                raise RuntimeError(
                    f"No se recibieron velas de {tf} para {symbol}. "
                    "Revisa el nombre del simbolo en el Market Watch de MT5 y el rango de fechas."
                )
            dataframes[tf] = df

        logger.info("Calculando linea de tiempo de bias (M15/H1)...")
        bias_timeline = smc_engine.compute_bias_timeline(dataframes["M15"], dataframes["H1"])

        stats = Counter()
        by_type_conf = Counter()

        for tf in config.TRIGGER_TIMEFRAMES:
            df = dataframes[tf]
            logger.info("Calculando triggers en %s (%d velas)...", tf, len(df))
            signals = smc_engine.compute_triggers_with_bias_timeline(df, tf, bias_timeline)
            logger.info("%s: %d triggers detectados en todo el historico", tf, len(signals))

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

    finally:
        conn.close()
        client.disconnect()


def main() -> None:
    setup_logging()
    args = parse_args()
    run_backtest(months=args.months, symbol=args.symbol)


if __name__ == "__main__":
    main()
