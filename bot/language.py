# bot/language.py

import json
import os
from typing import Dict
import logging

# لاگر را برای این فایل تعریف می‌کنیم
logger = logging.getLogger(__name__)

# دیکشنری برای نگهداری تمام ترجمه‌ها در حافظه
_translations: Dict[str, Dict[str, str]] = {}

def load_translations():
    """
    فایل‌های زبان (JSON) را از پوشه locales بارگذاری می‌کند و لاگ دقیق ثبت می‌کند.
    """
    global _translations
    locales_dir = os.path.join(os.path.dirname(__file__), 'locales')
    if not os.path.exists(locales_dir):
        logger.error(f"FATAL: Locales directory not found at '{locales_dir}'")
        return

    for filename in os.listdir(locales_dir):
        if filename.endswith(".json"):
            lang_code = filename.split(".")[0]
            file_path = os.path.join(locales_dir, filename)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    _translations[lang_code] = json.load(f)
                logger.info(f"Successfully loaded language file: {filename}")
            except Exception as e:
                logger.error(f"Error loading language file {filename}: {e}")
    
    # نتیجه نهایی بارگذاری را لاگ می‌کنیم
    logger.info(f"Translation loading complete. Loaded languages: {list(_translations.keys())}")


def get_string(key: str, lang_code: str = 'fa') -> str:
    """
    یک کلید متنی را ترجمه می‌کند و مراحل کار خود را با جزئیات لاگ می‌کند.
    """
    # <<<<<<<<<<<<<<<<<<<< START OF DIAGNOSTIC LOGGING >>>>>>>>>>>>>>>>>>
    logger.info(f"GET_STRING: Attempting to get key '{key}' for lang_code '{lang_code}'.")
    
    original_lang_code = lang_code
    
    if lang_code not in _translations:
        logger.warning(f"GET_STRING: lang_code '{lang_code}' not found in loaded translations ({list(_translations.keys())}). Defaulting to 'fa'.")
        lang_code = 'fa'
    
    translation = _translations.get(lang_code, {}).get(key, key)
    
    if translation == key:
        logger.warning(f"GET_STRING: Key '{key}' not found for lang_code '{lang_code}'. Returning the key itself.")
    
    # فقط ۳۰ کاراکتر اول ترجمه را لاگ می‌کنیم تا لاگ‌ها شلوغ نشوند
    logger.info(f"GET_STRING: For key '{key}' with original lang '{original_lang_code}', returning: '{translation[:30]}...'")
    # <<<<<<<<<<<<<<<<<<<< END OF DIAGNOSTIC LOGGING >>>>>>>>>>>>>>>>>>
    return translation

# در ابتدای اجرای ربات، تمام فایل‌های زبان را بارگذاری می‌کنیم
load_translations()