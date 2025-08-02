# filename: bot/settings_manager.py

import json
import logging
import os

logger = logging.getLogger(__name__)

# --- ساخت مسیر مطلق برای فایل تنظیمات ---
try:
    BOT_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(BOT_DIR)
    SETTINGS_FILE_PATH = os.path.join(PROJECT_ROOT, "bot_settings.json")
except NameError:
    SETTINGS_FILE_PATH = "bot_settings.json"

class SettingsManager:
    def __init__(self, path: str = SETTINGS_FILE_PATH):
        self.path = path
        self.defaults = {
            "daily_report_time": "23:59",
            "birthday_gift_gb": 15,
            "birthday_gift_days": 15,
            "warning_usage_threshold": 90,
            "warning_days_before_expiry": 7,
            "usage_warning_check_minutes": 60,
            "welcome_message_delay_minutes": 2880,
            "admin_support_contact": "@username",
            "PAGE_SIZE": 15
        }
        self.settings = self._load_settings()

    def _load_settings(self) -> dict:
        """تنظیمات را از فایل JSON بارگذاری میکند یا اگر وجود نداشت، فایل را با پیشفرضها ایجاد میکند."""
        if not os.path.exists(self.path):
            logger.info(f"Settings file not found at {self.path}. Creating with default values.")
            try:
                with open(self.path, 'w', encoding='utf-8') as f:
                    json.dump(self.defaults, f, ensure_ascii=False, indent=4)
                return self.defaults.copy()
            except Exception as e:
                logger.error(f"FATAL: Could not create settings file at {self.path}. Error: {e}")
                return self.defaults.copy()

        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                loaded_settings = json.load(f)
            
            # اطمینان از اینکه تمام کلیدهای پیشفرض در فایل تنظیمات وجود دارند
            for key, value in self.defaults.items():
                loaded_settings.setdefault(key, value)
            return loaded_settings
        except (json.JSONDecodeError, IOError, TypeError) as e:
            logger.error(f"Failed to load or parse settings file: {e}. Using default settings.")
            return self.defaults.copy()

    def get(self, key: str, default=None):
        """یک مقدار را از تنظیمات دریافت میکند."""
        return self.settings.get(key, self.defaults.get(key, default))

    # --- START: متد جدید برای خواندن مستقیم از فایل ---
    def get_all_from_disk(self) -> dict:
        """
        تمام تنظیمات را مستقیماً از فایل روی دیسک میخواند و حافظه داخلی را نادیده میگیرد.
        این روش برای نمایش دادههای ۱۰۰٪ به‌روز در صفحه تنظیمات ایده‌آل است.
        """
        logger.info(f"Reading settings directly from disk: {self.path}")
        final_settings = self.defaults.copy()
        try:
            if os.path.exists(self.path):
                with open(self.path, 'r', encoding='utf-8') as f:
                    data_from_file = json.load(f)
                    final_settings.update(data_from_file)
            else:
                logger.warning(f"Settings file not found at {self.path} during disk read. Returning defaults.")
            return final_settings
        except (json.JSONDecodeError, IOError, TypeError) as e:
            logger.error(f"Failed to read or parse settings file from disk: {e}. Returning defaults.")
            return self.defaults.copy()
    # --- END: پایان متد جدید ---

    def save_settings(self, new_settings: dict) -> bool:
        """تنظیمات جدید را در فایل JSON ذخیره کرده و حافظه پردازش فعلی را بهروز میکند."""
        try:
            # برای جلوگیری از ذخیره کلیدهای ناخواسته، فقط از کلیدهای موجود در پیشفرضها استفاده میکنیم
            current_settings = self.get_all_from_disk()
            current_settings.update(new_settings)

            sanitized_settings = {key: current_settings.get(key) for key in self.defaults}

            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(sanitized_settings, f, ensure_ascii=False, indent=4)
            
            # حافظه پردازش فعلی را هم بهروز میکنیم
            self.settings = sanitized_settings
            logger.info("Settings have been successfully saved to file and reloaded in current process.")
            return True
        except Exception as e:
            logger.error(f"Failed to save settings file: {e}", exc_info=True)
            return False

# یک نمونه سراسری از مدیر تنظیمات که در کل برنامه استفاده خواهد شد
settings = SettingsManager()

