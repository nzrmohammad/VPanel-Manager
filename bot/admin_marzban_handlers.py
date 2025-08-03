from telebot import types
from .menu import menu
from .marzban_api_handler import marzban_handler
from .utils import _safe_edit, escape_markdown
from datetime import datetime
import pytz
import logging
from .admin_formatters import fmt_admin_user_summary

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

def _ask_for_username(uid, msg_id, is_retry=False):
    prompt = "افزودن کاربر به پنل فرانسه (مرزبان) 🇫🇷\n\n"
    if is_retry: prompt += "⚠️ نام کاربری باید حداقل ۳ کاراکتر باشد. لطفاً دوباره وارد کنید.\n\n"
    prompt += "1. لطفاً یک **نام کاربری** وارد کنید (فقط حروف و اعداد انگلیسی):"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.cancel_action("admin:manage_panel:marzban"), parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, _get_username_for_add_user)

def _ask_for_limit(uid, msg_id, username, is_retry=False):
    prompt = f"نام کاربری: `{username}`\n\n"
    if is_retry: prompt += "⚠️ ورودی قبلی نامعتبر بود. لطفاً یک عدد وارد کنید.\n\n"
    prompt += "2. حالا **حجم کل مصرف** (به گیگابایت) را وارد کنید (عدد `0` برای نامحدود):"
    kb = menu.back_or_cancel("admin:add_user_back:marzban:username", "admin:manage_panel:marzban")
    # FIX: Removed escape_markdown and added parse_mode="Markdown" for correct rendering.
    _safe_edit(uid, msg_id, prompt, reply_markup=kb, parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, _get_limit_for_add_user)

def _ask_for_days(uid, msg_id, username, limit, is_retry=False):
    limit_str = f"{limit:.1f}" if limit is not None else "0"
    prompt = f"نام کاربری: `{username}`, حجم: `{limit_str} GB`\n\n"
    if is_retry: prompt += "⚠️ ورودی قبلی نامعتبر بود. لطفاً یک عدد صحیح وارد کنید.\n\n"
    prompt += "3. در نهایت، **مدت زمان** پلن (به روز) را وارد کنید (عدد `0` برای نامحدود):"
    kb = menu.back_or_cancel("admin:add_user_back:marzban:limit", "admin:manage_panel:marzban")
    # FIX: Removed escape_markdown and added parse_mode="Markdown" for correct rendering.
    _safe_edit(uid, msg_id, prompt, reply_markup=kb, parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, _get_days_for_add_user)

def _start_add_marzban_user_convo(uid, msg_id):
    _update_conversation(uid, {'step': 'username', 'msg_id': msg_id, 'panel': 'marzban'})
    _ask_for_username(uid, msg_id)

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
    msg_id = user_data.get('msg_id')
    _safe_edit(uid, msg_id, "⏳ در حال ساخت کاربر در پنل مرزبان...")
    
    new_user_info = marzban_handler.add_user(user_data)
    admin_conversations.pop(uid, None)
    
    if new_user_info and new_user_info.get('username'):
        fresh_user_info = marzban_handler.get_user_by_username(new_user_info['username'])

        # --- شروع اصلاح باگ ---
        # به جای محاسبه مجدد، مستقیماً از روزهای وارد شده توسط ادمین استفاده می‌کنیم
        expire_days = user_data.get('package_days')

        # اگر کاربر 0 روز را برای نامحدود وارد کرده بود، expire_days را None در نظر می‌گیریم
        if expire_days == 0:
            expire_days = None

        final_info = {
            'name': fresh_user_info.get('username'),
            'is_active': True,
            'on_marzban': True,
            'breakdown': {'marzban': fresh_user_info},
            'expire': expire_days # <-- استفاده از مقدار صحیح
        }
        # --- پایان اصلاح باگ ---

        text = fmt_admin_user_summary(final_info)
        success_text = f"✅ کاربر با موفقیت در پنل فرانسه ساخته شد.\n\n{text}"
        _safe_edit(uid, msg_id, success_text, reply_markup=menu.admin_panel_management_menu('marzban'), parse_mode="Markdown")
    else:
        err_msg = "❌ خطا در ساخت کاربر. ممکن است نام تکراری باشد یا پنل در دسترس نباشد."
        _safe_edit(uid, msg_id, err_msg, reply_markup=menu.admin_panel_management_menu('marzban'), parse_mode="Markdown")