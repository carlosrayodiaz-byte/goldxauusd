"""
Orquestador del bucle en vivo. Fase 1: SOLO deteccion tecnica + journaling.
No ejecuta ordenes, no envia alertas, no usa datos macro/social.

Cada minuto, alineado al cierre de la vela M1 (no a un timer arbitrario):
  1. Descarga M15/H1 -> calcula bias.
  2. Descarga M1/M5 -> calcula TODOS los triggers (fvg/order_block/liquidity_sweep),
     marcando cuales son confluentes con el bias.
  3. Guarda todo en SQLite (idempotente).
"""
import logging
import logging.handlers
import time
from datetime import datetime, timedelta, timezone

import config
import database
import smc_engine
from mt5_client import MT5Client, MT5ConnectionError

logger = logging.getLogger("xauusd_bot")


def setup_logging() -> None:
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        config.LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


def seconds_until_next_m1_close(buffer_seconds: int = config.POLL_ALIGN_SECONDS) -> float:
    now = datetime.now(timezone.utc)
    next_close = (now.replace(second=0, microsecond=0) + timedelta(minutes=1))
    target = next_close + timedelta(seconds=buffer_seconds)
    return (target - now).total_seconds()


def run_cycle(client: MT5Client, conn) -> None:
    df_m15 = client.get_ohlc(config.SYMBOL, "M15", config.CANDLES_TO_FETCH["M15"])
    df_h1 = client.get_ohlc(config.SYMBOL, "H1", config.CANDLES_TO_FETCH["H1"])
    if df_m15.empty or df_h1.empty:
        logger.warning("Sin datos suficientes en M15/H1 todavia, se omite este ciclo.")
        return

    bias = smc_engine.compute_bias(df_m15, df_h1)
    logger.info(
        "Bias actual: %s (determinado en %s) | detalle H1=%s M15=%s",
        bias.direction, bias.timeframe, bias.details.get("H1"), bias.details.get("M15"),
    )

    total_new, total_dup, total_confluent = 0, 0, 0

    for tf in config.TRIGGER_TIMEFRAMES:
        df = client.get_ohlc(config.SYMBOL, tf, config.CANDLES_TO_FETCH[tf])
        if df.empty:
            logger.warning("Sin datos en %s todavia, se omite.", tf)
            continue

        signals = smc_engine.compute_triggers(df, tf, bias)
        logger.info(
            "%s: procesada vela %s | %d triggers en la ventana actual",
            tf, df["time"].iloc[-1], len(signals),
        )

        for s in signals:
            record = database.SignalRecord(
                symbol=config.SYMBOL,
                source="live",
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
            if inserted:
                total_new += 1
                total_confluent += int(s.confluente)
                logger.info(
                    "NUEVA senal: %s %s %s @ %s precio=%.3f confluente=%s",
                    s.trigger_timeframe, s.trigger_type, s.trigger_direction,
                    s.candle_time, s.price_at_detection, s.confluente,
                )
            else:
                total_dup += 1
                logger.debug(
                    "Descartada (ya existia): %s %s %s @ %s",
                    s.trigger_timeframe, s.trigger_type, s.trigger_direction, s.candle_time,
                )

    logger.info(
        "Ciclo completo: %d senales nuevas (%d confluentes), %d duplicadas descartadas.",
        total_new, total_confluent, total_dup,
    )


def main() -> None:
    setup_logging()
    logger.info("Iniciando bot de señales XAUUSD - Fase 1 (solo deteccion + journaling, sin ordenes ni alertas)")

    client = MT5Client()
    client.connect()
    conn = database.init_db(config.DB_PATH)

    try:
        while True:
            wait_s = seconds_until_next_m1_close()
            if wait_s > 0:
                time.sleep(wait_s)
            try:
                run_cycle(client, conn)
            except MT5ConnectionError as exc:
                logger.error("Error de conexion MT5: %s", exc)
            except Exception:
                logger.exception("Error inesperado durante el ciclo; se continua en el proximo minuto.")
    except KeyboardInterrupt:
        logger.info("Interrumpido por el usuario, cerrando...")
    finally:
        conn.close()
        client.disconnect()


if __name__ == "__main__":
    main()
