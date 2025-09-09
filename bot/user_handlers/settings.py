import logging
from telebot import types

# --- Local Imports ---
from ..database import db
from ..menu import menu
from ..utils import escape_markdown, _safe_edit
from ..language import get_string

logger = logging.getLogger(__name__)
bot = None


def initialize_handlers(b):
    """نمونه bot را از فایل اصلی دریافت می‌کند."""
    global bot
    bot = b


def language_selection_menu() -> types.InlineKeyboardMarkup:
    """کیبورد انتخاب زبان را ایجاد می‌کند."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🇮🇷 Persian", callback_data="set_lang:fa"),
        types.InlineKeyboardButton("🇬🇧 English", callback_data="set_lang:en")
    )
    return kb


def show_settings(call: types.CallbackQuery):
    """منوی تنظیمات را با توجه به زبان و دسترسی‌های کاربر نمایش می‌دهد."""
    uid = call.from_user.id
    msg_id = call.message.message_id
    lang_code = db.get_user_language(uid)
    settings_data = db.get_user_settings(uid)

    access_rights = db.get_user_access_rights(uid)

    title_text = f'*{escape_markdown(get_string("settings_title", lang_code))}*'
    reply_markup = menu.settings(settings_data, lang_code=lang_code, access=access_rights)

    _safe_edit(uid, msg_id, text=title_text, reply_markup=reply_markup)


def handle_toggle_setting(call: types.CallbackQuery):
    """وضعیت یک تنظیم خاص را برای کاربر تغییر می‌دهد."""
    uid = call.from_user.id
    msg_id = call.message.message_id
    lang_code = db.get_user_language(uid)
    
    setting_key = call.data.replace("toggle_", "")
    current_settings = db.get_user_settings(uid)
    
    if setting_key == "data_warning_fr_tr":
        current_status = current_settings.get('data_warning_fr', True) and current_settings.get('data_warning_tr', True)
        new_value = not current_status
        db.update_user_setting(uid, 'data_warning_fr', new_value)
        db.update_user_setting(uid, 'data_warning_tr', new_value)
    else:
        new_value = not current_settings.get(setting_key, True)
        db.update_user_setting(uid, setting_key, new_value)
    
    text = f'*{escape_markdown(get_string("settings_updated", lang_code))}*'
    show_settings(call)


def handle_change_language_request(call: types.CallbackQuery):
    """منوی انتخاب زبان را نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)
    
    prompt = get_string("select_language", lang_code)
    _safe_edit(uid, msg_id, prompt, reply_markup=language_selection_menu(), parse_mode=None)


def handle_language_selection(call: types.CallbackQuery):
    """
    زبان انتخابی کاربر را ذخیره کرده و او را به منوی مناسب بازمی‌گرداند.
    """
    uid, lang_code = call.from_user.id, call.data.split(':')[1]
    
    db.set_user_language(uid, lang_code)
    bot.answer_callback_query(call.id, get_string("lang_selected", lang_code))

    if not db.uuids(uid):
        from .various import show_initial_menu 
        show_initial_menu(uid=uid, msg_id=call.message.message_id)
    else:
        show_settings(call)