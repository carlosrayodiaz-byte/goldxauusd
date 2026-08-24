"""
Pruebas de la parte pura de mt5_client.py que no requiere el paquete
MetaTrader5 (que solo existe junto a un terminal instalado). Cubre el fix
de auditoria: get_ohlc_range no debe incluir una vela que en tiempo real
todavia no habria cerrado.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from mt5_client import _trim_unclosed_candle


def _make_df(times):
    n = len(times)
    return pd.DataFrame({
        "time": pd.to_datetime(times, utc=True),
        "open": [1.0] * n,
        "high": [1.0] * n,
        "low": [1.0] * n,
        "close": [1.0] * n,
        "volume": [1.0] * n,
    })


class TestTrimUnclosedCandle:
    def test_drops_last_candle_still_forming(self):
        now = datetime(2024, 1, 1, 10, 3, 30, tzinfo=timezone.utc)
        df = _make_df(["2024-01-01 10:00", "2024-01-01 10:01", "2024-01-01 10:02", "2024-01-01 10:03"])
        out = _trim_unclosed_candle(df, "M1", now=now)
        # la vela de las 10:03 cierra a las 10:04, que aun no ha llegado -> se descarta
        assert list(out["time"].dt.strftime("%H:%M")) == ["10:00", "10:01", "10:02"]

    def test_keeps_all_when_last_candle_already_closed(self):
        now = datetime(2024, 1, 1, 10, 5, 0, tzinfo=timezone.utc)
        df = _make_df(["2024-01-01 10:00", "2024-01-01 10:01", "2024-01-01 10:02", "2024-01-01 10:03"])
        out = _trim_unclosed_candle(df, "M1", now=now)
        assert len(out) == 4

    def test_exact_close_boundary_is_kept(self):
        # la vela de las 10:03 (M1) cierra exactamente a las 10:04:00; si "ahora"
        # es exactamente ese instante, ya cerro -> se mantiene (no >, sino >=)
        now = datetime(2024, 1, 1, 10, 4, 0, tzinfo=timezone.utc)
        df = _make_df(["2024-01-01 10:03"])
        out = _trim_unclosed_candle(df, "M1", now=now)
        assert len(out) == 1

    def test_respects_timeframe_duration(self):
        # una vela H1 de las 09:00 no cierra hasta las 10:00, aunque para M1
        # a esa misma hora ya haria rato que cerro
        now = datetime(2024, 1, 1, 9, 30, 0, tzinfo=timezone.utc)
        df = _make_df(["2024-01-01 09:00"])
        assert len(_trim_unclosed_candle(df, "H1", now=now)) == 0
        assert len(_trim_unclosed_candle(df, "M1", now=now)) == 1

    def test_empty_dataframe_returns_empty(self):
        df = _make_df([])
        out = _trim_unclosed_candle(df, "M1")
        assert out.empty

    def test_only_trims_trailing_candle_not_earlier_ones(self):
        # Solo la mas reciente puede estar "en formacion"; si por algun motivo
        # una vela intermedia pareciera no cerrada (no deberia pasar en la
        # practica, pero probamos que el filtro es por vela, no solo la ultima)
        now = datetime(2024, 1, 1, 10, 1, 30, tzinfo=timezone.utc)
        df = _make_df(["2024-01-01 09:00", "2024-01-01 10:00", "2024-01-01 10:01"])
        out = _trim_unclosed_candle(df, "M1", now=now)
        assert list(out["time"].dt.strftime("%H:%M")) == ["09:00", "10:00"]
