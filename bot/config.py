import os
from cachetools import TTLCache
from dotenv import load_dotenv
from datetime import time
import pytz

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

TEHRAN_TZ = pytz.timezone("Asia/Tehran")
DAILY_REPORT_TIME = time(23, 59)
CLEANUP_TIME = time(00, 1)

ADMIN_SUPPORT_CONTACT = os.getenv("ADMIN_SUPPORT_CONTACT", "@Nzrmohammad")
PAGE_SIZE = 35

BIRTHDAY_GIFT_GB = 30
BIRTHDAY_GIFT_DAYS = 15

NOTIFY_ADMIN_ON_USAGE = True
USAGE_WARNING_CHECK_HOURS = 6  
ONLINE_REPORT_UPDATE_HOURS = 3

WARNING_USAGE_THRESHOLD = 85  
WARNING_DAYS_BEFORE_EXPIRY = 3
DAILY_USAGE_ALERT_THRESHOLD_GB = 5

WELCOME_MESSAGE_DELAY_HOURS = 48

RANDOM_SERVERS_COUNT = 10

# --- Payment Information ---
# اطلاعات پرداخت کارت به کارت (در صورت خالی بودن، این گزینه نمایش داده نمی‌شود)
CARD_PAYMENT_INFO = {
    "bank_name": "بلوبانک",
    "card_holder": "محمد جواد نظری",
    "card_number": "6219-8618-1954-7695"
}

ONLINE_PAYMENT_LINK = ""

TUTORIAL_LINKS = {
    "android": {
        "v2rayng": "https://telegra.ph/Your-V2rayNG-Tutorial-Link-Here-01-01",
        "hiddify": "https://telegra.ph/Hiddify-08-19",
        "happ": "https://telegra.ph/Happ-08-08-5"
    },
    "windows": {
        "v2rayn": "https://telegra.ph/V2rayN-08-18-2",
        "hiddify": "https://telegra.ph/Hiddify-08-19"
    },
    "ios": {
        "streisand": "https://telegra.ph/Your-Streisand-Tutorial-Link-Here-01-01",
        "shadowrocket": "https://telegra.ph/Your-Shadowrocket-Tutorial-Link-Here-01-01",
        "hiddify": "https://telegra.ph/Hiddify-08-19",
        "happ": "https://telegra.ph/Happ-08-08-5"
    }
}

# --- Loyalty Program ---
# دیکشنری برای تعریف پاداش‌ها
# کلید: شماره پرداخت (تمدید)
# مقدار: یک دیکشنری شامل حجم (gb) و روز (days) هدیه
LOYALTY_REWARDS = {
    3: {"gb": 6, "days": 3},  # هدیه در سومین تمدید
    6: {"gb": 12, "days": 6}, # هدیه در ششمین تمدید
    9: {"gb": 18, "days": 9}, # هدیه در دهمین تمدید
    12: {"gb": 24, "days": 12}
}

# --- Traffic Transfer Settings ---
ENABLE_TRAFFIC_TRANSFER = True  # قابلیت را فعال یا غیرفعال می‌کند
MIN_TRANSFER_GB = 1             # حداقل حجم قابل انتقال
MAX_TRANSFER_GB = 20             # حداکثر حجم قابل انتقال
TRANSFER_COOLDOWN_DAYS = 10     # هر کاربر هر چند روز یکبار می‌تواند انتقال دهد

# --- Referral System Settings ---
ENABLE_REFERRAL_SYSTEM = True
REFERRAL_REWARD_GB = 10          # حجم هدیه برای هر معرفی موفق (به گیگابایت)
REFERRAL_REWARD_DAYS = 5        # روز هدیه برای هر معرفی موفق
AMBASSADOR_BADGE_THRESHOLD = 5  # تعداد معرفی لازم برای دریافت نشان سفیر

ACHIEVEMENTS = {
    "veteran": {
        "name": "کهنه‌کار", "icon": "🎖️", "points": 200,
        "description": "به کاربرانی که بیش از ۳۶۵ روز از اولین اتصالشان گذشته باشد، اهدا می‌شود."
    },
    "pro_consumer": {
        "name": "مصرف‌کننده حرفه‌ای", "icon": "🔥", "points": 100,
        "description": "به کاربرانی که در یک دوره ۳۰ روزه، بیش از ۲۰۰ گیگابایت ترافیک مصرف کنند."
    },
    "night_owl": {
        "name": "شب‌زنده‌دار", "icon": "🦉", "points": 25,
        "description": "به کاربرانی که بیش از ۵۰٪ ترافیک ماهانه خود را بین ساعت ۰۰:۰۰ تا ۰۶:۰۰ بامداد مصرف کنند."
    },
    "loyal_supporter": {
        "name": "حامی وفادار", "icon": "💖", "points": 50,
        "description": "به کاربرانی که بیش از ۵ بار سرویس خود را تمدید کرده باشند، اهدا می‌شود."
    },
    "ambassador": {
        "name": "سفیر", "icon": "🤝", "points": 150,
        "description": f"به کاربرانی که بیش از {AMBASSADOR_BADGE_THRESHOLD} نفر را با موفقیت به سرویس دعوت کرده باشند."
    },
    "vip_friend": {
        "name": "دوست VIP", "icon": "👑", "points": 250,
        "description": "این نشان به تمام کاربران VIP به نشانه قدردانی از حمایت ویژه‌شان اهدا می‌شود."
    },
    "lucky_one": {
        "name": "خوش‌شانس", "icon": "🍀", "points": 10,
        "description": "این نشان به صورت کاملاً تصادفی به برخی از کاربران اهدا می‌شود!"
    },
    "legend": {
        "name": "اسطوره", "icon": "🌟", "points": 500,
        "description": "به کاربرانی که همزمان نشان‌های کهنه‌کار، حامی وفادار و مصرف‌کننده حرفه‌ای را داشته باشند."
    }
}

ENABLE_LUCKY_LOTTERY = True
LUCKY_LOTTERY_BADGE_REQUIREMENT = 20

# --- Achievement Shop Settings ---
ACHIEVEMENT_SHOP_ITEMS = {
    "buy_10gb": {"name": "خرید ۱۰ گیگابایت حجم", "cost": 100, "gb": 10, "days": 0},
    "buy_25gb": {"name": "خرید ۲۵ گیگابایت حجم", "cost": 220, "gb": 25, "days": 0},
    "buy_7days": {"name": "خرید ۷ روز اعتبار", "cost": 150, "gb": 0, "days": 7},
    "buy_30days": {"name": "خرید ۳۰ روز اعتبار", "cost": 450, "gb": 0, "days": 30}
}

# --- Emojis & Visuals ---
EMOJIS = {
    "fire": "🔥", "chart": "📊", "warning": "⚠️", "error": "❌",
    "success": "✅", "info": "ℹ️", "key": "🔑", "bell": "🔔",
    "time": "⏰", "calendar": "📅", "money": "💰", "lightning": "⚡",
    "star": "⭐", "rocket": "🚀", "gear": "⚙️", "book": "📖",
    "home": "🏠", "user": "👤", "globe": "🌍", "wifi": "📡",
    "download": "📥", "upload": "📤", "database": "💾",
    "shield": "🛡️", "crown": "👑", "trophy": "🏆",
    "database": "🗂️", "back": "🔙"
}

PROGRESS_COLORS = {
    "safe": "🟢", "warning": "🟡", "danger": "🟠", "critical": "🔴"
}

# --- Logging ---
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s — %(name)s — %(levelname)s — %(message)s"
