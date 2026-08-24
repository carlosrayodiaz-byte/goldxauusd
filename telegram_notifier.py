"""
Notificador de Telegram -- Fase 3, SOLO infraestructura.

Modulo TOTALMENTE independiente: no importa smc_engine.py ni database.py ni
config.py ni mt5_client.py de la Fase 1, ni macro_engine.py de la Fase 2.
Nada de aqui esta conectado todavia a la tabla `signals` ni a la capa
macro -- eso es trabajo de una fase posterior. Hoy esto solo sabe formatear
un mensaje a partir de un dict con forma de fila de `signals` (pasado a
mano, de ejemplo) y enviarlo a un chat de Telegram.

Se eligio `requests` en vez de `python-telegram-bot`: la libreria oficial
(v20+) es asincrona (asyncio) y trae bastante mas superficie de la que hace
falta para "mandar un mensaje de texto a un chat_id fijo". Una llamada HTTP
directa al endpoint sendMessage es mas simple de mantener para este caso de
uso minimo.

Uso:
    python telegram_notifier.py --test-message
"""
import argparse
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import requests

import telegram_config as cfg

logger = logging.getLogger("telegram_notifier")

_TRIGGER_TYPE_LABELS = {
    "fvg": "FVG",
    "order_block": "Order Block",
    "liquidity_sweep": "Liquidity Sweep",
}

EXAMPLE_SIGNAL: Dict[str, Any] = {
    "symbol": "XAUUSD",
    "trigger_type": "fvg",
    "trigger_direction": "bullish",
    "trigger_timeframe": "M1",
    "bias_direction": "bullish",
    "bias_timeframe": "H1",
    "price_at_detection": 2015.23,
    "top": 2015.10,
    "bottom": 2014.80,
    "confluente": True,
}


def _fmt_trigger_type(value: Optional[str]) -> str:
    if not value:
        return "trigger desconocido"
    return _TRIGGER_TYPE_LABELS.get(value, str(value).replace("_", " ").title())


def _fmt_price(value: Any) -> str:
    if value is None:
        return "N/D"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


def format_signal_message(signal: Dict[str, Any]) -> str:
    """Texto plano, compacto, legible de un vistazo en el movil. Ningun
    campo es obligatorio: uno faltante o de tipo inesperado degrada a un
    valor por defecto razonable en vez de lanzar una excepcion -- esta
    funcion recibe datos de ejemplo hoy, pero en una fase posterior
    recibira filas reales de la tabla `signals`, que pueden venir
    incompletas o con un trigger_type nuevo que el formateador no conoce
    todavia."""
    symbol = signal.get("symbol") or "?"
    trigger_type = _fmt_trigger_type(signal.get("trigger_type"))
    trigger_direction = signal.get("trigger_direction") or "?"
    trigger_timeframe = signal.get("trigger_timeframe") or "?"
    bias_direction = signal.get("bias_direction") or "?"
    bias_timeframe = signal.get("bias_timeframe") or "?"
    confluente = signal.get("confluente")
    price = signal.get("price_at_detection")
    top = signal.get("top")
    bottom = signal.get("bottom")

    lines = [f"{symbol} | {trigger_type} {trigger_direction} | {trigger_timeframe}"]

    if confluente is True:
        conf_txt = "CONFLUENTE"
    elif confluente is False:
        conf_txt = "no confluente"
    else:
        conf_txt = "confluencia: ?"
    lines.append(f"Bias: {bias_direction} ({bias_timeframe}) -> {conf_txt}")

    lines.append(f"Precio: {_fmt_price(price)}")

    if top is not None or bottom is not None:
        lines.append(f"Zona: {_fmt_price(bottom)} - {_fmt_price(top)}")

    notas = signal.get("notas")
    if notas:
        lines.append(str(notas))

    return "\n".join(lines)


class TelegramNotifier:
    """Cliente minimo sobre la Bot API de Telegram (solo sendMessage)."""

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or cfg.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or cfg.TELEGRAM_CHAT_ID

    def send_message(self, text: str) -> bool:
        """Envia `text` al chat configurado. Nunca lanza: si Telegram no
        responde, el token es invalido, o faltan credenciales, lo registra
        en el log y devuelve False -- no debe tumbar nada mas (mismo
        criterio de aislamiento que las 4 fuentes de macro_engine.py)."""
        if not self.bot_token or not self.chat_id:
            logger.error("telegram: falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID (ver .env.example / README)")
            return False

        url = f"{cfg.TELEGRAM_API_BASE}{self.bot_token}/sendMessage"
        try:
            resp = requests.post(
                url, data={"chat_id": self.chat_id, "text": text}, timeout=cfg.HTTP_TIMEOUT_SECONDS
            )
        except requests.RequestException as exc:
            logger.error("telegram: fallo de red enviando el mensaje: %s", exc)
            return False

        if resp.status_code != 200:
            logger.error("telegram: la API devolvio HTTP %d: %s", resp.status_code, resp.text[:300])
            return False

        try:
            payload = resp.json()
        except ValueError:
            logger.error("telegram: respuesta no-JSON de la API: %s", resp.text[:300])
            return False

        if not payload.get("ok"):
            logger.error("telegram: respuesta no-ok de la API: %s", payload)
            return False

        message_id = payload.get("result", {}).get("message_id")
        logger.info("telegram: mensaje enviado (message_id=%s)", message_id)
        return True

    def send_signal_message(self, signal: Dict[str, Any]) -> bool:
        """Formatea y envia un dict con forma de fila de `signals`."""
        return self.send_message(format_signal_message(signal))


def _setup_logging() -> None:
    level = getattr(logging, cfg.LOG_LEVEL.upper(), logging.INFO)
    Path(cfg.LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(cfg.LOG_PATH, encoding="utf-8")],
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Notificador de Telegram (Fase 3, SOLO infraestructura -- sin conexion a signals ni a macro_engine)."
    )
    parser.add_argument(
        "--test-message", action="store_true",
        help="Formatea y envia un mensaje de ejemplo (datos ficticios) al chat configurado.",
    )
    args = parser.parse_args()

    _setup_logging()

    if not args.test_message:
        parser.print_help()
        return 0

    text = format_signal_message(EXAMPLE_SIGNAL)
    print("Mensaje de prueba:\n" + text + "\n")

    notifier = TelegramNotifier()
    ok = notifier.send_signal_message(EXAMPLE_SIGNAL)
    if ok:
        print("[OK] Mensaje enviado correctamente. Revisa tu chat de Telegram.")
    else:
        print("[FALLO] No se pudo enviar el mensaje. Revisa el log y TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID en .env.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
