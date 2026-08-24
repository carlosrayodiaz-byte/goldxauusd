"""
Wrapper sobre `smartmoneyconcepts` (smc). No conoce MT5 ni SQLite: recibe
DataFrames OHLC "limpios" (columnas open/high/low/close/volume en minuscula,
columna `time` con timestamps, index posicional 0..n-1) y devuelve estructuras
de datos propias (BiasResult / TriggerSignal).

Notas de causalidad (importante para el backtest, ver README):
- BOS/CHoCH: la libreria marca el evento en la vela del pivote (pasado), pero
  solo lo confirma si `BrokenIndex` esta seteado (la vela donde el precio
  realmente rompio el nivel). Usamos `BrokenIndex` como el instante real en
  que el bias "se conoce" -> sin look-ahead.
- FVG: el hueco se marca en la vela intermedia de un patron de 3 velas, pero
  solo es visible una vez cierra la vela siguiente (shift(-1) en la libreria).
  Usamos esa vela siguiente como `candle_time` real de la senal.
- Liquidity sweep: solo emitimos señales donde `Swept` ya tiene un indice
  valido (barrido confirmado), usando esa vela como `candle_time`.
- Order Block: la libreria marca el bloque en su propia vela de origen, pero
  la ruptura de estructura que lo confirma ocurre unas velas despues (no hay
  un indice de "confirmado" explicito en la libreria, a diferencia de BOS y
  FVG). Aproximacion documentada: usamos la vela del propio OB como
  `candle_time`. Esto es estandar en herramientas de charting SMC, pero en
  backtest puede adelantar en unas pocas velas el bias comparado en la
  confluencia. Si el analisis posterior muestra que esto distorsiona las
  estadisticas de confluencia para order_block, revisar en una fase futura.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from smartmoneyconcepts import smc

import config

DIRECTION_MAP = {1: "bullish", -1: "bearish"}
REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


@dataclass
class BiasResult:
    direction: str  # "bullish" | "bearish" | "neutral"
    timeframe: str  # timeframe que determino el bias final (H1 o M15)
    candle_time: Optional[pd.Timestamp]
    details: Dict[str, str] = field(default_factory=dict)  # {"H1": ..., "M15": ...}


@dataclass
class TriggerSignal:
    trigger_type: str  # fvg | order_block | liquidity_sweep
    trigger_direction: str  # bullish | bearish
    trigger_timeframe: str  # M1 | M5
    candle_time: pd.Timestamp
    price_at_detection: float
    top: Optional[float]
    bottom: Optional[float]
    confluente: bool
    bias_direction: str  # bias vigente en el candle_time de este trigger
    bias_timeframe: str  # timeframe que determino ese bias (H1 o M15)
    notas: str


@dataclass
class _RawTrigger:
    trigger_type: str
    direction: str
    timeframe: str
    candle_time: pd.Timestamp
    price: float
    top: Optional[float]
    bottom: Optional[float]
    notas: str


def _validate_ohlc(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas OHLC requeridas: {missing}")
    if "time" not in df.columns:
        raise ValueError("El DataFrame OHLC debe tener una columna 'time'")
    if not df.index.equals(pd.RangeIndex(len(df))):
        raise ValueError("El DataFrame OHLC debe tener un RangeIndex 0..n-1 (usar reset_index)")


def _swing_highs_lows(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    return smc.swing_highs_lows(df, swing_length=config.SWING_LENGTH[timeframe])


def _bias_events(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Eventos BOS/CHoCH ya confirmados (BrokenIndex valido), en orden temporal."""
    sw = _swing_highs_lows(df, timeframe)
    bc = smc.bos_choch(df, sw, close_break=config.BOS_CLOSE_BREAK)

    event_dir = bc["BOS"].combine_first(bc["CHOCH"])
    events = pd.DataFrame(
        {"direction_code": event_dir, "confirmed_pos": bc["BrokenIndex"]}
    ).dropna(subset=["direction_code", "confirmed_pos"])

    if events.empty:
        return pd.DataFrame(columns=["confirmed_pos", "confirmed_time", "direction"])

    events["confirmed_pos"] = events["confirmed_pos"].astype(int)
    events["confirmed_time"] = df["time"].iloc[events["confirmed_pos"]].values
    events["direction"] = events["direction_code"].astype(int).map(DIRECTION_MAP)
    events = events.sort_values("confirmed_pos").reset_index(drop=True)
    return events[["confirmed_pos", "confirmed_time", "direction"]]


def _bias_timeline_single(df: pd.DataFrame, timeframe: str) -> pd.Series:
    """Serie alineada a df.index con la direccion de bias vigente en cada vela
    (forward-fill causal desde cada evento BOS/CHoCH confirmado)."""
    events = _bias_events(df, timeframe)
    code = pd.Series(np.nan, index=df.index, dtype=float)
    for pos, direction in zip(events["confirmed_pos"], events["direction"]):
        code.iloc[pos] = 1.0 if direction == "bullish" else -1.0
    code = code.ffill()
    return code.map(DIRECTION_MAP).fillna("neutral")


def compute_bias_timeline(df_m15: pd.DataFrame, df_h1: pd.DataFrame) -> pd.DataFrame:
    """Linea de tiempo de bias combinado (H1 domina, cae a M15 si H1 neutral),
    indexada por tiempo. Usada tanto por compute_bias (live, ultima fila) como
    por backtest.py (merge_asof contra el tiempo de cada trigger)."""
    _validate_ohlc(df_m15)
    _validate_ohlc(df_h1)

    h1_dir = _bias_timeline_single(df_h1, "H1")
    m15_dir = _bias_timeline_single(df_m15, "M15")

    h1_tl = pd.DataFrame({"time": df_h1["time"], "h1_dir": h1_dir}).sort_values("time")
    m15_tl = pd.DataFrame({"time": df_m15["time"], "m15_dir": m15_dir}).sort_values("time")

    timeline = pd.merge_asof(m15_tl, h1_tl, on="time", direction="backward")
    timeline["h1_dir"] = timeline["h1_dir"].fillna("neutral")
    timeline["m15_dir"] = timeline["m15_dir"].fillna("neutral")

    use_h1 = timeline["h1_dir"] != "neutral"
    timeline["direction"] = np.where(use_h1, timeline["h1_dir"], timeline["m15_dir"])
    timeline["bias_timeframe"] = np.where(use_h1, "H1", "M15")

    return timeline[["time", "direction", "bias_timeframe", "h1_dir", "m15_dir"]]


def compute_bias(df_m15: pd.DataFrame, df_h1: pd.DataFrame) -> BiasResult:
    """Bias vigente 'ahora' (ultima vela disponible). Para uso en el bucle live."""
    timeline = compute_bias_timeline(df_m15, df_h1)
    last = timeline.iloc[-1]
    return BiasResult(
        direction=last["direction"],
        timeframe=last["bias_timeframe"],
        candle_time=last["time"],
        details={"H1": last["h1_dir"], "M15": last["m15_dir"]},
    )


def _fvg_triggers(df: pd.DataFrame, timeframe: str) -> List[_RawTrigger]:
    result = smc.fvg(df, join_consecutive=config.FVG_JOIN_CONSECUTIVE)
    n = len(df)
    triggers = []
    for i in result.index[result["FVG"].notna()]:
        confirm_pos = i + 1
        if confirm_pos >= n:
            continue
        direction = DIRECTION_MAP[int(result.at[i, "FVG"])]
        top = float(result.at[i, "Top"])
        bottom = float(result.at[i, "Bottom"])
        candle_time = df["time"].iloc[confirm_pos]
        price = float(df["close"].iloc[confirm_pos])
        notas = f"FVG originado en vela {df['time'].iloc[i]}, confirmado (vela siguiente) en {candle_time}."
        triggers.append(_RawTrigger("fvg", direction, timeframe, candle_time, price, top, bottom, notas))
    return triggers


def _ob_triggers(df: pd.DataFrame, timeframe: str) -> List[_RawTrigger]:
    sw = _swing_highs_lows(df, timeframe)
    result = smc.ob(df, sw, close_mitigation=config.OB_CLOSE_MITIGATION)
    triggers = []
    for i in result.index[result["OB"].notna()]:
        direction = DIRECTION_MAP[int(result.at[i, "OB"])]
        top = float(result.at[i, "Top"])
        bottom = float(result.at[i, "Bottom"])
        candle_time = df["time"].iloc[i]
        price = float(df["close"].iloc[i])
        pct = result.at[i, "Percentage"]
        notas = f"Order block (fuerza {pct:.1f}%). Confirmacion de ruptura ocurre unas velas despues (ver limitaciones)."
        triggers.append(_RawTrigger("order_block", direction, timeframe, candle_time, price, top, bottom, notas))
    return triggers


def _liquidity_triggers(df: pd.DataFrame, timeframe: str) -> List[_RawTrigger]:
    sw = _swing_highs_lows(df, timeframe)
    result = smc.liquidity(df, sw, range_percent=config.LIQUIDITY_RANGE_PERCENT)
    n = len(df)
    triggers = []
    mask = result["Liquidity"].notna() & result["Swept"].notna() & (result["Swept"] > 0)
    for i in result.index[mask]:
        swept_pos = int(result.at[i, "Swept"])
        if swept_pos >= n:
            continue
        direction = DIRECTION_MAP[int(result.at[i, "Liquidity"])]
        level = float(result.at[i, "Level"])
        candle_time = df["time"].iloc[swept_pos]
        price = float(df["close"].iloc[swept_pos])
        notas = f"Pool de liquidez en ~{level:.3f} (formado en vela {df['time'].iloc[i]}), barrido en {candle_time}."
        triggers.append(_RawTrigger("liquidity_sweep", direction, timeframe, candle_time, price, level, None, notas))
    return triggers


def _all_raw_triggers(df: pd.DataFrame, timeframe: str) -> List[_RawTrigger]:
    _validate_ohlc(df)
    return _fvg_triggers(df, timeframe) + _ob_triggers(df, timeframe) + _liquidity_triggers(df, timeframe)


def compute_triggers(df: pd.DataFrame, timeframe: str, bias: BiasResult) -> List[TriggerSignal]:
    """Todos los triggers M1/M5 detectados en la ventana, marcados confluentes
    o no contra un bias FIJO (uso en vivo: el bias del instante actual).
    Se registran TODOS los triggers, confluentes o no."""
    raw = _all_raw_triggers(df, timeframe)
    signals = []
    for r in raw:
        confluente = bias.direction != "neutral" and r.direction == bias.direction
        notas = f"{r.notas} | bias_al_detectar={bias.direction}({bias.timeframe})"
        signals.append(
            TriggerSignal(
                trigger_type=r.trigger_type,
                trigger_direction=r.direction,
                trigger_timeframe=r.timeframe,
                candle_time=r.candle_time,
                price_at_detection=r.price,
                top=r.top,
                bottom=r.bottom,
                confluente=confluente,
                bias_direction=bias.direction,
                bias_timeframe=bias.timeframe,
                notas=notas,
            )
        )
    return signals


def compute_triggers_with_bias_timeline(
    df: pd.DataFrame, timeframe: str, bias_timeline: pd.DataFrame
) -> List[TriggerSignal]:
    """Igual que compute_triggers pero resolviendo, para cada trigger, el bias
    vigente EN SU PROPIO candle_time (merge_asof causal). Uso en backtest."""
    raw = _all_raw_triggers(df, timeframe)
    if not raw:
        return []

    trig_df = pd.DataFrame([r.__dict__ for r in raw]).sort_values("candle_time").reset_index(drop=True)
    tl = bias_timeline[["time", "direction", "bias_timeframe"]].sort_values("time")

    merged = pd.merge_asof(
        trig_df, tl, left_on="candle_time", right_on="time", direction="backward", suffixes=("_x", "_y")
    )
    # merge_asof: la columna 'direction' existe en ambos lados (trigger y bias)
    # y queda suffijada automaticamente; la renombramos para dejarlo explicito.
    merged = merged.rename(columns={"direction_x": "trigger_direction", "direction_y": "bias_direction"})
    merged["bias_direction"] = merged["bias_direction"].fillna("neutral")
    merged["bias_timeframe"] = merged["bias_timeframe"].fillna("")

    signals = []
    for row in merged.itertuples(index=False):
        confluente = row.bias_direction != "neutral" and row.trigger_direction == row.bias_direction
        notas = f"{row.notas} | bias_al_detectar={row.bias_direction}({row.bias_timeframe})"
        signals.append(
            TriggerSignal(
                trigger_type=row.trigger_type,
                trigger_direction=row.trigger_direction,
                trigger_timeframe=row.timeframe,
                candle_time=row.candle_time,
                price_at_detection=row.price,
                top=row.top if pd.notna(row.top) else None,
                bottom=row.bottom if pd.notna(row.bottom) else None,
                confluente=confluente,
                bias_direction=row.bias_direction,
                bias_timeframe=row.bias_timeframe,
                notas=notas,
            )
        )
    return signals
