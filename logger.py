import logging
import logging_loki
import os
from dotenv import load_dotenv

load_dotenv()

LOKI_URL = os.getenv("LOKI_URL", "http://localhost:3100/loki/api/v1/push")
APP_ENV  = os.getenv("APP_ENV", "development")

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)
console_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
)

# Root logger config
logging.basicConfig(level=logging.WARNING, handlers=[console_handler])

# ── Main app logger (chat, audio, PDF, sessions) ──────────────────────────────
loki_handler = logging_loki.LokiHandler(
    url=LOKI_URL,
    tags={"app": "jio_bot", "env": APP_ENV},
    version="1",
)
loki_handler.setLevel(logging.INFO)

logger = logging.getLogger("jio_bot")
logger.addHandler(loki_handler)
logger.addHandler(console_handler)
logger.propagate = False

# ── Live video chat logger (separate Loki stream) ─────────────────────────────
live_loki_handler = logging_loki.LokiHandler(
    url=LOKI_URL,
    tags={"app": "jio_bot_live", "env": APP_ENV},
    version="1",
)
live_loki_handler.setLevel(logging.INFO)

live_logger = logging.getLogger("jio_bot.live")
live_logger.addHandler(live_loki_handler)
live_logger.addHandler(console_handler)
live_logger.propagate = False
