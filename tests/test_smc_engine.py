"""
Pruebas de sanity para smc_engine.py. Usan OHLC sintetico (ver conftest.py),
NUNCA datos reales de mercado. El objetivo no es validar la calidad de las
senales (eso lo hace backtest.py contra historico real), sino que el motor
no rompa con datos "raros": huecos de precio, velas planas, ventanas cortas.
"""
import math

import pandas as pd
import pytest

import smc_engine
from smc_engine import BiasResult, TriggerSignal

VALID_DIRECTIONS = {"bullish", "bearish", "neutral"}
VALID_TRIGGER_TYPES = {"fvg", "order_block", "liquidity_sweep"}


def _assert_valid_bias(bias: BiasResult):
    assert isinstance(bias, BiasResult)
    assert bias.direction in VALID_DIRECTIONS
    assert bias.timeframe in {"H1", "M15"}
    assert "H1" in bias.details and "M15" in bias.details
    assert bias.details["H1"] in VALID_DIRECTIONS
    assert bias.details["M15"] in VALID_DIRECTIONS


def _assert_valid_triggers(signals, df: pd.DataFrame):
    assert isinstance(signals, list)
    min_time, max_time = df["time"].iloc[0], df["time"].iloc[-1]
    for s in signals:
        assert isinstance(s, TriggerSignal)
        assert s.trigger_type in VALID_TRIGGER_TYPES
        assert s.trigger_direction in {"bullish", "bearish"}
        assert isinstance(s.confluente, bool)
        assert min_time <= s.candle_time <= max_time
        assert not math.isnan(s.price_at_detection)
        if s.top is not None:
            assert not math.isnan(s.top)
        if s.bottom is not None:
            assert not math.isnan(s.bottom)
        assert s.bias_direction in VALID_DIRECTIONS
        assert s.notas  # nunca vacio, debe explicar el porque


class TestComputeBias:
    def test_trending_data_produces_valid_bias(self, trending_ohlc):
        bias = smc_engine.compute_bias(trending_ohlc, trending_ohlc)
        _assert_valid_bias(bias)

    def test_choppy_data_does_not_crash(self, choppy_ohlc):
        bias = smc_engine.compute_bias(choppy_ohlc, choppy_ohlc)
        _assert_valid_bias(bias)

    def test_gapped_data_does_not_crash(self, gapped_ohlc):
        bias = smc_engine.compute_bias(gapped_ohlc, gapped_ohlc)
        _assert_valid_bias(bias)

    def test_flat_candles_does_not_crash(self, flat_candles_ohlc):
        bias = smc_engine.compute_bias(flat_candles_ohlc, flat_candles_ohlc)
        _assert_valid_bias(bias)

    def test_tiny_window_falls_back_to_neutral(self, tiny_ohlc):
        # Con menos velas que el swing_length configurado no deberia haber
        # suficiente estructura para confirmar ningun BOS/CHoCH.
        bias = smc_engine.compute_bias(tiny_ohlc, tiny_ohlc)
        _assert_valid_bias(bias)
        assert bias.direction == "neutral"


class TestComputeBiasTimeline:
    def test_timeline_shape_and_values(self, trending_ohlc):
        timeline = smc_engine.compute_bias_timeline(trending_ohlc, trending_ohlc)
        assert len(timeline) == len(trending_ohlc)
        assert timeline["time"].is_monotonic_increasing
        assert set(timeline["direction"].unique()) <= VALID_DIRECTIONS
        assert set(timeline["bias_timeframe"].unique()) <= {"H1", "M15"}

    def test_timeline_matches_compute_bias_on_last_row(self, trending_ohlc):
        timeline = smc_engine.compute_bias_timeline(trending_ohlc, trending_ohlc)
        bias = smc_engine.compute_bias(trending_ohlc, trending_ohlc)
        last = timeline.iloc[-1]
        assert last["direction"] == bias.direction
        assert last["bias_timeframe"] == bias.timeframe


class TestComputeTriggers:
    @pytest.fixture
    def neutral_bias(self):
        return BiasResult(direction="neutral", timeframe="H1", candle_time=None, details={"H1": "neutral", "M15": "neutral"})

    @pytest.fixture
    def bullish_bias(self):
        return BiasResult(direction="bullish", timeframe="H1", candle_time=None, details={"H1": "bullish", "M15": "bullish"})

    def test_trending_data_valid_output(self, trending_ohlc, bullish_bias):
        signals = smc_engine.compute_triggers(trending_ohlc, "M1", bullish_bias)
        _assert_valid_triggers(signals, trending_ohlc)

    def test_neutral_bias_never_confluent(self, trending_ohlc, neutral_bias):
        signals = smc_engine.compute_triggers(trending_ohlc, "M1", neutral_bias)
        _assert_valid_triggers(signals, trending_ohlc)
        assert all(not s.confluente for s in signals)

    def test_all_triggers_recorded_not_only_confluent(self, trending_ohlc, bullish_bias):
        # Requisito explicito: se registran TODOS los triggers, no solo los
        # confluentes con el bias.
        signals = smc_engine.compute_triggers(trending_ohlc, "M1", bullish_bias)
        directions = {s.trigger_direction for s in signals}
        # Con suficiente data deberia haber triggers en ambas direcciones,
        # y no todos pueden ser confluentes si hay triggers bajistas.
        if "bearish" in directions:
            assert any(not s.confluente for s in signals)

    def test_gapped_data_does_not_crash(self, gapped_ohlc, bullish_bias):
        signals = smc_engine.compute_triggers(gapped_ohlc, "M1", bullish_bias)
        _assert_valid_triggers(signals, gapped_ohlc)

    def test_flat_candles_does_not_crash(self, flat_candles_ohlc, bullish_bias):
        signals = smc_engine.compute_triggers(flat_candles_ohlc, "M1", bullish_bias)
        _assert_valid_triggers(signals, flat_candles_ohlc)

    def test_tiny_window_returns_empty_or_valid(self, tiny_ohlc, bullish_bias):
        signals = smc_engine.compute_triggers(tiny_ohlc, "M1", bullish_bias)
        _assert_valid_triggers(signals, tiny_ohlc)

    def test_zero_volume_does_not_crash_order_block_percentage(self, flat_candles_ohlc, bullish_bias):
        # flat_candles_ohlc tiene un tramo con volume=0: la formula de OB
        # (min/max de volumenes) divide por max_vol y debe evitar division por 0.
        signals = smc_engine.compute_triggers(flat_candles_ohlc, "M5", bullish_bias)
        _assert_valid_triggers(signals, flat_candles_ohlc)


class TestComputeTriggersWithBiasTimeline:
    def test_backtest_path_matches_schema(self, trending_ohlc):
        bias_timeline = smc_engine.compute_bias_timeline(trending_ohlc, trending_ohlc)
        signals = smc_engine.compute_triggers_with_bias_timeline(trending_ohlc, "M1", bias_timeline)
        _assert_valid_triggers(signals, trending_ohlc)

    def test_backtest_path_no_lookahead_bias_before_first_event(self, trending_ohlc):
        bias_timeline = smc_engine.compute_bias_timeline(trending_ohlc, trending_ohlc)
        signals = smc_engine.compute_triggers_with_bias_timeline(trending_ohlc, "M1", bias_timeline)
        first_bias_time = bias_timeline.loc[bias_timeline["direction"] != "neutral", "time"]
        if first_bias_time.empty:
            pytest.skip("No hubo ningun cambio de bias confirmado en la data sintetica")
        first_bias_time = first_bias_time.iloc[0]
        # Ningun trigger anterior al primer bias confirmado deberia figurar
        # como confluente (todavia no habia bias direccional conocido).
        early = [s for s in signals if s.candle_time < first_bias_time]
        assert all(not s.confluente for s in early)


class TestValidateOhlc:
    def test_missing_column_raises(self):
        df = pd.DataFrame({"time": [1, 2], "open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0]})
        with pytest.raises(ValueError):
            smc_engine._validate_ohlc(df)

    def test_bad_index_raises(self, trending_ohlc):
        df = trending_ohlc.set_index("time", drop=False)
        with pytest.raises(ValueError):
            smc_engine._validate_ohlc(df)
