import logging

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
)

# Root logger config
logging.basicConfig(level=logging.DEBUG, handlers=[console_handler])

# ── Main app logger ──────────────────────────────────────────────────────────
logger = logging.getLogger("jio_bot")
logger.addHandler(console_handler)
logger.propagate = False

# ── Live video chat logger ───────────────────────────────────────────────────
live_logger = logging.getLogger("jio_bot.live")
live_logger.addHandler(console_handler)
live_logger.propagate = False
