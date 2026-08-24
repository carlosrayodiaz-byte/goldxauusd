"""Fixtures compartidas: generadores de OHLC sintetico (NUNCA datos reales de
mercado) para las pruebas de sanity de smc_engine.py."""
import numpy as np
import pandas as pd
import pytest


def make_synthetic_ohlc(
    n: int = 300,
    start: float = 2000.0,
    freq: str = "1min",
    seed: int = 0,
    trend: float = 0.0,
    volatility: float = 0.5,
) -> pd.DataFrame:
    """Random walk con forma de vela OHLC valida (high >= max(open,close),
    low <= min(open,close)), suficiente para ejercitar swings/BOS/CHoCH/FVG/OB
    sin depender de datos reales de bróker."""
    rng = np.random.default_rng(seed)
    times = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")

    closes = np.empty(n)
    closes[0] = start
    steps = rng.normal(trend, volatility, n - 1)
    closes[1:] = start + np.cumsum(steps)

    opens = np.empty(n)
    opens[0] = start
    opens[1:] = closes[:-1]

    wick = rng.uniform(0, volatility, n)
    highs = np.maximum(opens, closes) + wick
    lows = np.minimum(opens, closes) - wick
    volumes = rng.integers(10, 1000, n).astype(float)

    df = pd.DataFrame(
        {"time": times, "open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}
    )
    return df.reset_index(drop=True)


@pytest.fixture
def trending_ohlc() -> pd.DataFrame:
    """Tendencia alcista clara: suficiente para generar swings, BOS/CHoCH,
    FVGs y order blocks de forma consistente."""
    return make_synthetic_ohlc(n=400, trend=0.3, volatility=0.6, seed=1)


@pytest.fixture
def choppy_ohlc() -> pd.DataFrame:
    """Rango lateral sin tendencia clara (bias deberia tender a neutral)."""
    return make_synthetic_ohlc(n=400, trend=0.0, volatility=0.8, seed=2)


@pytest.fixture
def gapped_ohlc() -> pd.DataFrame:
    """Datos con un hueco de precio grande (ej. reapertura tras fin de semana)
    insertado a mitad de la serie."""
    df = make_synthetic_ohlc(n=300, trend=0.1, volatility=0.5, seed=3)
    gap_start = 150
    jump = 25.0  # salto brusco de precio
    df.loc[gap_start:, ["open", "high", "low", "close"]] += jump
    # asegurar que la vela del hueco en si tenga un rango consistente
    df.loc[gap_start, "low"] = min(df.loc[gap_start, "low"], df.loc[gap_start - 1, "close"])
    return df.reset_index(drop=True)


@pytest.fixture
def flat_candles_ohlc() -> pd.DataFrame:
    """Tramo largo de velas completamente planas (open=high=low=close),
    tipico de baja liquidez o feed congelado del broker."""
    df = make_synthetic_ohlc(n=300, trend=0.1, volatility=0.5, seed=4)
    flat_price = df.loc[100, "close"]
    df.loc[100:150, ["open", "high", "low", "close"]] = flat_price
    df.loc[100:150, "volume"] = 0.0
    return df.reset_index(drop=True)


@pytest.fixture
def tiny_ohlc() -> pd.DataFrame:
    """Ventana demasiado corta (menos velas que el swing_length configurado)."""
    return make_synthetic_ohlc(n=8, trend=0.1, volatility=0.5, seed=5)
