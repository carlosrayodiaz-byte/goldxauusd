"""Pruebas de sanity de database.py: esquema e idempotencia (requisito
explicito: reiniciar el bot y reprocesar la misma ventana no debe duplicar)."""
import database


def _make_record(**overrides):
    base = dict(
        symbol="XAUUSD",
        source="live",
        bias_direction="bullish",
        bias_timeframe="H1",
        trigger_type="fvg",
        trigger_direction="bullish",
        trigger_timeframe="M1",
        candle_time="2024-01-01T00:05:00+00:00",
        price_at_detection=2000.5,
        top=2001.0,
        bottom=2000.0,
        confluente=True,
        notas="test",
    )
    base.update(overrides)
    return database.SignalRecord(**base)


def test_insert_and_duplicate_is_ignored(tmp_path):
    db_path = str(tmp_path / "test.db")
    with database.connect(db_path) as conn:
        record = _make_record()
        assert database.insert_signal(conn, record) is True
        assert database.insert_signal(conn, record) is False
        assert database.count_signals(conn) == 1


def test_reopening_db_keeps_idempotency(tmp_path):
    db_path = str(tmp_path / "test.db")
    record = _make_record()
    with database.connect(db_path) as conn:
        database.insert_signal(conn, record)

    # Simula un reinicio del bot: se reabre la conexion y se reprocesa la
    # misma vela/senal.
    with database.connect(db_path) as conn:
        inserted = database.insert_signal(conn, record)
        assert inserted is False
        assert database.count_signals(conn) == 1


def test_different_candle_time_is_not_a_duplicate(tmp_path):
    db_path = str(tmp_path / "test.db")
    with database.connect(db_path) as conn:
        database.insert_signal(conn, _make_record(candle_time="2024-01-01T00:05:00+00:00"))
        database.insert_signal(conn, _make_record(candle_time="2024-01-01T00:06:00+00:00"))
        assert database.count_signals(conn) == 2


def test_live_and_backtest_do_not_collide(tmp_path):
    db_path = str(tmp_path / "test.db")
    with database.connect(db_path) as conn:
        database.insert_signal(conn, _make_record(source="live"))
        database.insert_signal(conn, _make_record(source="backtest"))
        assert database.count_signals(conn) == 2
        assert database.count_signals(conn, source="live") == 1
        assert database.count_signals(conn, source="backtest") == 1
