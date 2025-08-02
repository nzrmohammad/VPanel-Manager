import json
import os
from typing import Dict

# دیکشنری برای نگهداری تمام ترجمه‌ها در حافظه
_translations: Dict[str, Dict[str, str]] = {}

def load_translations():
    """
    فایل‌های زبان (JSON) را از پوشه locales بارگذاری می‌کند.
    """
    global _translations
    locales_dir = os.path.join(os.path.dirname(__file__), 'locales')
    if not os.path.exists(locales_dir):
        print(f"Warning: Directory '{locales_dir}' not found.")
        return

    for filename in os.listdir(locales_dir):
        if filename.endswith(".json"):
            lang_code = filename.split(".")[0]
            file_path = os.path.join(locales_dir, filename)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    _translations[lang_code] = json.load(f)
                print(f"Loaded language: {lang_code}")
            except Exception as e:
                print(f"Error loading language file {filename}: {e}")

def get_string(key: str, lang_code: str = 'fa') -> str:
    """
    یک کلید متنی را بر اساس زبان کاربر ترجمه می‌کند.
    اگر کلید یا زبان موجود نباشد، خود کلید را برمی‌گرداند.
    """
    # اگر زبان کاربر در ترجمه‌ها نبود، به فارسی برمی‌گردیم
    if lang_code not in _translations:
        lang_code = 'fa'
    
    return _translations.get(lang_code, {}).get(key, key)

# در ابتدای اجرای ربات، تمام فایل‌های زبان را بارگذاری می‌کنیم
load_translations()