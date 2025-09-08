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
    یک کلید متنی را ترجمه می‌کند.
    """
    if lang_code not in _translations:
        # اگر زبان درخواستی موجود نبود، به زبان فارسی برمی‌گردد
        lang_code = 'fa'
    
    # تلاش برای یافتن کلید در زبان مشخص شده. اگر یافت نشد، خود کلید را برمی‌گرداند.
    translation = _translations.get(lang_code, {}).get(key, key)
    
    if translation == key and lang_code != 'fa':
        # اگر کلید در زبان انتخابی نبود، یک بار هم در زبان فارسی جستجو می‌کند
        translation = _translations.get('fa', {}).get(key, key)

    return translation

# در ابتدای اجرای ربات، تمام فایل‌های زبان را بارگذاری می‌کنیم
load_translations()