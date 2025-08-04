import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

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
            "warning_days_before_expiry": 3,
            "usage_warning_check_minutes": 60,
            "welcome_message_delay_minutes": 2880,
            "admin_support_contact": "@username",
            "PAGE_SIZE": 15
        }
        self.settings = {}
        self.reload() # در اولین ساخت، تنظیمات را از فایل بخوان

    # <<<<<<<<<<<< متد جدید و کلیدی برای حل مشکل >>>>>>>>>>>>>
    def reload(self) -> None:
        """
        تنظیمات را از فایل روی دیسک مجدداً بارگذاری کرده و حافظه را به‌روز می‌کند.
        """
        logger.info(f"Reloading settings from disk: {self.path}")
        try:
            if os.path.exists(self.path):
                with open(self.path, 'r', encoding='utf-8') as f:
                    loaded_settings = json.load(f)
                
                # اطمینان از اینکه کلیدهای پیشفرض در فایل وجود دارند
                defaults_copy = self.defaults.copy()
                defaults_copy.update(loaded_settings)
                self.settings = defaults_copy
            else:
                logger.warning(f"Settings file not found at {self.path}. Creating with default values.")
                self._create_default_file()

        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load settings, using defaults. Error: {e}")
            self.settings = self.defaults.copy()
    
    def _create_default_file(self):
        """فایل تنظیمات را با مقادیر پیش‌فرض ایجاد می‌کند."""
        self.settings = self.defaults.copy()
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"FATAL: Could not create settings file at {self.path}. Error: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, self.defaults.get(key, default))

    def get_all_from_disk(self) -> dict:
        self.reload() # برای اطمینان، قبل از خواندن مستقیم هم رفرش می‌کنیم
        return self.settings

    def save_settings(self, new_settings: dict) -> bool:
        """تنظیمات جدید را در فایل JSON ذخیره کرده و حافظه پردازش فعلی را بهروز میکند."""
        try:
            # ابتدا حافظه را با مقادیر جدید آپدیت کن
            self.settings.update(new_settings)
            
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=4)
            
            logger.info("Settings have been successfully saved to file.")
            return True
        except Exception as e:
            logger.error(f"Failed to save settings file: {e}", exc_info=True)
            return False

settings = SettingsManager()