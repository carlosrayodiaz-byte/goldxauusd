"""
Configuracion del notificador de Telegram (Fase 3), TOTALMENTE independiente
de config.py / smc_engine.py / database.py / mt5_client.py de la Fase 1 y de
macro_config.py / macro_engine.py de la Fase 2. No importa nada de esos
modulos y nada de esos modulos deberia importar esto todavia: la conexion
real (enviar un mensaje cuando se inserta una senal en la tabla `signals`,
o cuando cambia algo en la capa macro) es trabajo de una fase posterior.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# Credenciales -- ver README para como crear el bot con @BotFather y sacar
# el chat_id.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TELEGRAM_API_BASE = "https://api.telegram.org/bot"
HTTP_TIMEOUT_SECONDS = 15

# Rate limiting: Telegram permite ~1 mensaje/seg por chat_id. Dos capas:
# 1. Throttling del lado del cliente (MIN_SECONDS_BETWEEN_MESSAGES): antes de
#    cada envio se espera lo necesario para no llamar mas seguido que esto.
# 2. Reactivo (DEFAULT_RETRY_AFTER_SECONDS): si aun asi Telegram devuelve 429,
#    se usa el `retry_after` que manda en el body; este valor es solo el
#    fallback por si la API no lo incluye.
MIN_SECONDS_BETWEEN_MESSAGES = 1.0
DEFAULT_RETRY_AFTER_SECONDS = 1.0

LOG_PATH = os.getenv("TELEGRAM_LOG_PATH", str(BASE_DIR / "logs" / "telegram.log"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
