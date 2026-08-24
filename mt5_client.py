"""
Conexion de solo lectura a un terminal MetaTrader 5 ya instalado en la
maquina, y descarga de velas OHLC. No se usa ninguna funcion de trading
(order_send, etc.) en todo este modulo: unicamente copy_rates_*.
"""
import logging
import time
from datetime import datetime
from typing import Optional

import pandas as pd

import config

logger = logging.getLogger(__name__)

TIMEFRAME_NAMES = ["M1", "M5", "M15", "H1"]


def _timeframe_map():
    # Import perezoso: MetaTrader5 solo existe en la maquina del usuario con
    # el terminal instalado, y asi config.py / smc_engine.py se pueden
    # importar (p.ej. en tests) sin tener el paquete disponible.
    import MetaTrader5 as mt5

    return {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "H1": mt5.TIMEFRAME_H1,
    }


class MT5ConnectionError(RuntimeError):
    pass


class MT5Client:
    """Envoltorio fino sobre el paquete MetaTrader5. Cuenta demo, solo lectura
    de mercado (velas). Maneja reconexion si se cae la sesion del terminal."""

    def __init__(
        self,
        login: Optional[str] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        terminal_path: Optional[str] = None,
    ):
        self.login = login or config.MT5_LOGIN
        self.password = password or config.MT5_PASSWORD
        self.server = server or config.MT5_SERVER
        self.terminal_path = terminal_path or config.MT5_TERMINAL_PATH
        self._mt5 = None

    def connect(self) -> None:
        import MetaTrader5 as mt5

        self._mt5 = mt5
        kwargs = {}
        if self.terminal_path:
            kwargs["path"] = self.terminal_path
        if self.login:
            kwargs["login"] = int(self.login)
        if self.password:
            kwargs["password"] = self.password
        if self.server:
            kwargs["server"] = self.server

        if not mt5.initialize(**kwargs):
            code, desc = mt5.last_error()
            raise MT5ConnectionError(f"No se pudo inicializar MT5 (codigo {code}): {desc}")

        info = mt5.account_info()
        if info is None:
            code, desc = mt5.last_error()
            raise MT5ConnectionError(f"MT5 inicializado pero sin cuenta activa (codigo {code}): {desc}")

        logger.info(
            "Conectado a MT5: cuenta %s en %s (%s), trade_mode=%s",
            info.login, info.server, info.company, info.trade_mode,
        )

    def ensure_connected(self) -> None:
        """Verifica la conexion y reconecta con reintentos si hace falta."""
        if self._mt5 is not None and self._mt5.terminal_info() is not None:
            return

        last_exc = None
        for attempt in range(1, config.MT5_RECONNECT_RETRIES + 1):
            try:
                logger.warning("Sesion MT5 caida, reconectando (intento %d/%d)...",
                                attempt, config.MT5_RECONNECT_RETRIES)
                self.connect()
                return
            except MT5ConnectionError as exc:
                last_exc = exc
                time.sleep(config.MT5_RECONNECT_DELAY_SECONDS)
        raise MT5ConnectionError(f"No se pudo reconectar a MT5 tras {config.MT5_RECONNECT_RETRIES} intentos") from last_exc

    def disconnect(self) -> None:
        if self._mt5 is not None:
            self._mt5.shutdown()
            logger.info("Desconectado de MT5.")

    def __enter__(self) -> "MT5Client":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.disconnect()

    def _rates_to_df(self, rates) -> pd.DataFrame:
        if rates is None or len(rates) == 0:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.rename(columns={"tick_volume": "volume"})
        df = df[["time", "open", "high", "low", "close", "volume"]]
        df = df.sort_values("time").reset_index(drop=True)
        return df

    def get_ohlc(self, symbol: str, timeframe_key: str, count: int) -> pd.DataFrame:
        """Ultimas `count` velas cerradas de `symbol` en el timeframe dado
        ("M1"/"M5"/"M15"/"H1"). La vela en curso (aun sin cerrar) se excluye."""
        self.ensure_connected()
        mt5 = self._mt5
        tf = _timeframe_map()[timeframe_key]

        # start_pos=1 salta la vela en formacion (posicion 0 = vela actual, sin cerrar)
        rates = mt5.copy_rates_from_pos(symbol, tf, 1, count)
        if rates is None:
            code, desc = mt5.last_error()
            raise MT5ConnectionError(
                f"copy_rates_from_pos fallo para {symbol}/{timeframe_key} (codigo {code}): {desc}"
            )
        return self._rates_to_df(rates)

    def get_ohlc_range(
        self, symbol: str, timeframe_key: str, date_from: datetime, date_to: datetime
    ) -> pd.DataFrame:
        """Velas historicas de `symbol` entre dos fechas (UTC). Uso en backtest."""
        self.ensure_connected()
        mt5 = self._mt5
        tf = _timeframe_map()[timeframe_key]

        rates = mt5.copy_rates_range(symbol, tf, date_from, date_to)
        if rates is None:
            code, desc = mt5.last_error()
            raise MT5ConnectionError(
                f"copy_rates_range fallo para {symbol}/{timeframe_key} (codigo {code}): {desc}"
            )
        return self._rates_to_df(rates)
