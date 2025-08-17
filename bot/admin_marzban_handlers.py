# bot/admin_handlers/admin_marzban_handlers.py
from telebot import types
import pytz
import logging
from datetime import datetime

# --- START: MODIFIED IMPORTS ---
from .menu import menu
from .marzban_api_handler import MarzbanAPIHandler # Import the Class
from .database import db # Import db
from .utils import _safe_edit, escape_markdown
from .admin_formatters import fmt_admin_user_summary
# --- END: MODIFIED IMPORTS ---

logger = logging.getLogger(__name__)
bot = None
admin_conversations = {}

def initialize_marzban_handlers(b_instance, conversations_dict):
    global bot, admin_conversations
    bot = b_instance
    admin_conversations = conversations_dict

def _delete_user_message(msg: types.Message):
    try: bot.delete_message(msg.chat.id, msg.message_id)
    except Exception: pass

def _update_conversation(uid, data):
    admin_conversations.setdefault(uid, {}).update(data)

# --- The conversation flow (_ask_for_username, etc.) remains the same ---

def _ask_for_username(uid, msg_id, is_retry=False):
    prompt = "افزودن کاربر به پنل Marzban 🇫🇷\n\n"
    if is_retry: prompt += "⚠️ نام کاربری باید حداقل ۳ کاراکتر باشد. لطفاً دوباره وارد کنید.\n\n"
    prompt += "1. لطفاً یک **نام کاربری** وارد کنید (فقط حروف و اعداد انگلیسی):"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_cancel_action("admin:management_menu"), parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, _get_username_for_add_user)

def _get_username_for_add_user(msg: types.Message):
    uid, name = msg.from_user.id, msg.text.strip()
    _delete_user_message(msg)
    if uid not in admin_conversations: return
    convo = admin_conversations[uid]
    if len(name) < 3:
        _ask_for_username(uid, convo['msg_id'], is_retry=True)
        return
    _update_conversation(uid, {'username': name, 'step': 'limit'})
    _ask_for_limit(uid, convo['msg_id'], name)

def _ask_for_limit(uid, msg_id, username, is_retry=False):
    prompt = f"نام کاربری: `{escape_markdown(username)}`\n\n"
    if is_retry: prompt += "⚠️ ورودی قبلی نامعتبر بود. لطفاً یک عدد وارد کنید.\n\n"
    prompt += "2. حالا **حجم کل مصرف** (به گیگابایت) را وارد کنید (عدد `0` برای نامحدود):"
    kb = menu.back_or_cancel("admin:add_user_back:marzban:username", "admin:management_menu")
    _safe_edit(uid, msg_id, prompt, reply_markup=kb, parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, _get_limit_for_add_user)

def _get_limit_for_add_user(msg: types.Message):
    uid, limit_text = msg.from_user.id, msg.text.strip()
    _delete_user_message(msg)
    if uid not in admin_conversations: return
    convo = admin_conversations[uid]
    try:
        limit = float(limit_text)
        _update_conversation(uid, {'usage_limit_GB': limit, 'step': 'days'})
        _ask_for_days(uid, convo['msg_id'], convo['username'], limit)
    except (ValueError, TypeError):
        _ask_for_limit(uid, convo['msg_id'], convo['username'], is_retry=True)

def _ask_for_days(uid, msg_id, username, limit, is_retry=False):
    limit_str = f"{limit:.1f}" if limit is not None else "0"
    prompt = f"نام کاربری: `{escape_markdown(username)}`, حجم: `{limit_str} GB`\n\n"
    if is_retry: prompt += "⚠️ ورودی قبلی نامعتبر بود. لطفاً یک عدد صحیح وارد کنید.\n\n"
    prompt += "3. در نهایت، **مدت زمان** پلن (به روز) را وارد کنید (عدد `0` برای نامحدود):"
    kb = menu.back_or_cancel("admin:add_user_back:marzban:limit", "admin:management_menu")
    _safe_edit(uid, msg_id, prompt, reply_markup=kb, parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, _get_days_for_add_user)

def _get_days_for_add_user(msg: types.Message):
    uid, days_text = msg.from_user.id, msg.text.strip()
    _delete_user_message(msg)
    if uid not in admin_conversations: return
    convo = admin_conversations[uid]
    try:
        days = int(days_text)
        _update_conversation(uid, {'package_days': days})
        _finish_marzban_user_creation(uid, admin_conversations[uid])
    except (ValueError, TypeError):
        _ask_for_days(uid, convo['msg_id'], convo['username'], convo['usage_limit_GB'], is_retry=True)

def _finish_marzban_user_creation(uid, user_data):
    """تابع نهایی برای ساخت کاربر که با سیستم داینامیک هماهنگ شده است."""
    msg_id = user_data.get('msg_id')

    # --- START: NEW DYNAMIC LOGIC ---
    active_marzban_panels = [p for p in db.get_active_panels() if p['panel_type'] == 'marzban']
    if not active_marzban_panels:
        err_msg = "❌ خطا: هیچ پنل فعال Marzban در سیستم ثبت نشده است."
        _safe_edit(uid, msg_id, err_msg, reply_markup=menu.admin_management_menu())
        return
        
    target_panel_config = active_marzban_panels[0]
    _safe_edit(uid, msg_id, f"⏳ در حال ساخت کاربر در پنل: {escape_markdown(target_panel_config['name'])}...")

    handler = MarzbanAPIHandler(target_panel_config)
    new_user_info = handler.add_user(user_data)
    # --- END: NEW DYNAMIC LOGIC ---

    admin_conversations.pop(uid, None)
    
    if new_user_info and new_user_info.get('username'):
        fresh_user_info = handler.get_user_by_username(new_user_info['username'])
        
        expire_days = user_data.get('package_days')
        if expire_days == 0:
            expire_days = None

        final_info = {
            'name': fresh_user_info.get('username'),
            'is_active': True,
            'breakdown': {target_panel_config['name']: fresh_user_info},
            'expire': expire_days
        }

        text = fmt_admin_user_summary(final_info)
        success_text = f"✅ کاربر با موفقیت در پنل {escape_markdown(target_panel_config['name'])} ساخته شد.\n\n{text}"
        _safe_edit(uid, msg_id, success_text, reply_markup=menu.admin_management_menu(), parse_mode="Markdown")
    else:
        err_msg = f"❌ خطا در ساخت کاربر در پنل {escape_markdown(target_panel_config['name'])}. ممکن است نام تکراری باشد."
        _safe_edit(uid, msg_id, err_msg, reply_markup=menu.admin_management_menu())

def _start_add_marzban_user_convo(uid, msg_id):
    """Starts the conversation for adding a user to a Marzban panel."""
    _update_conversation(uid, {'step': 'username', 'msg_id': msg_id, 'panel_type': 'marzban'})
    _ask_for_username(uid, msg_id)