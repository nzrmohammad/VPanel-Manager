import os
from cachetools import TTLCache
from dotenv import load_dotenv

load_dotenv()

def _parse_admin_ids(raw_ids: str | None) -> set[int]:
    if not raw_ids:
        return set()
    try:
        return {int(admin_id.strip()) for admin_id in raw_ids.split(',')}
    except ValueError:
        print("Warning: ADMIN_IDS environment variable contains non-integer values.")
        return set()

BOT_TOKEN = os.getenv("BOT_TOKEN")
HIDDIFY_DOMAIN_RAW = os.getenv("HIDDIFY_DOMAIN", "")
HIDDIFY_DOMAIN = HIDDIFY_DOMAIN_RAW.rstrip("/") if HIDDIFY_DOMAIN_RAW else ""
ADMIN_PROXY_PATH_RAW = os.getenv("ADMIN_PROXY_PATH", "")
ADMIN_PROXY_PATH = ADMIN_PROXY_PATH_RAW.strip("/") if ADMIN_PROXY_PATH_RAW else ""
ADMIN_UUID = os.getenv("ADMIN_UUID")
ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS")) or {265455450}
MARZBAN_API_BASE_URL = os.getenv("MARZBAN_API_BASE_URL", "https://panel2.fox1.eu.org:8000")
MARZBAN_API_USERNAME = os.getenv("MARZBAN_API_USERNAME")
MARZBAN_API_PASSWORD = os.getenv("MARZBAN_API_PASSWORD")
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY")

DATABASE_PATH = "bot_data.db"
TELEGRAM_FILE_SIZE_LIMIT_BYTES = 50 * 1024 * 1024
api_cache = TTLCache(maxsize=2, ttl=60)
API_TIMEOUT = 15
API_RETRY_COUNT = 3

# --- Emojis & Visuals ---
EMOJIS = {
    "fire": "🔥", "chart": "📊", "warning": "⚠️", "error": "❌",
    "success": "✅", "info": "ℹ️", "key": "🔑", "bell": "🔔",
    "time": "⏰", "calendar": "📅", "money": "💰", "lightning": "⚡",
    "star": "⭐", "rocket": "🚀", "gear": "⚙️", "book": "📖",
    "home": "🏠", "user": "👤", "globe": "🌍", "wifi": "📡",
    "download": "📥", "upload": "📤", "database": "💾",
    "shield": "🛡️", "crown": "👑", 'trophy': '🏆',
    'database': '🗂️', 'back': '🔙'
}

PROGRESS_COLORS = {
    "safe": "🟢", "warning": "🟡", "danger": "🟠", "critical": "🔴"
}

# --- Logging ---
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s — %(name)s — %(levelname)s — %(message)s"
