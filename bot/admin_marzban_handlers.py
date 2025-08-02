from telebot import types
from .menu import menu
from .marzban_api_handler import marzban_handler
from .utils import _safe_edit, escape_markdown
import logging
from .admin_formatters import fmt_admin_user_summary
from . import combined_handler


logger = logging.getLogger(__name__)
bot = None
admin_conversations = {}

def initialize_marzban_handlers(b_instance, conversations_dict):
    global bot, admin_conversations
    bot = b_instance
    admin_conversations = conversations_dict

def _delete_user_message(msg: types.Message):
    try:
        bot.delete_message(msg.chat.id, msg.message_id)
    except Exception as e:
        logger.warning(f"Could not delete user message {msg.message_id}: {e}")

def _start_add_marzban_user_convo(uid, msg_id):
    admin_conversations[uid] = {'msg_id': msg_id, 'panel': 'marzban'}
    prompt = "افزودن کاربر به پنل فرانسه \\(مرزبان\\) 🇫🇷\n\n1\\. لطفاً یک **نام کاربری** وارد کنید \\(حروف انگلیسی، اعداد و آندرلاین\\):"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.cancel_action("admin:manage_panel:marzban"))
    bot.register_next_step_handler_by_chat_id(uid, _get_name_for_add_marzban_user)

def _get_name_for_add_marzban_user(msg: types.Message):
    uid, name = msg.from_user.id, msg.text.strip()
    _delete_user_message(msg)

    try:
        if uid not in admin_conversations: return
        if name.startswith('/'):
            _safe_edit(uid, admin_conversations[uid]['msg_id'], "عملیات ساخت کاربر لغو شد\\.", reply_markup=menu.admin_panel_management_menu('marzban'))
            return

        # FIX: Add validation for username length to prevent 422 error
        if len(name) < 3:
            bot.send_message(uid, "❌ نام کاربری باید حداقل ۳ کاراکتر باشد\\. لطفاً نام دیگری وارد کنید\\.")
            bot.register_next_step_handler_by_chat_id(uid, _get_name_for_add_marzban_user)
            # We don't pop the conversation here, so the user can retry.
            return

        msg_id = admin_conversations[uid].get('msg_id')
        admin_conversations[uid]['username'] = name
        prompt = f"نام کاربری: `{escape_markdown(name)}`\n\n2\\. حالا **حجم کل مصرف** \\(به گیگابایت\\) را وارد کنید \\(عدد `0` برای نامحدود\\):"
        _safe_edit(uid, msg_id, prompt, reply_markup=menu.cancel_action("admin:manage_panel:marzban"))
        bot.register_next_step_handler_by_chat_id(uid, _get_limit_for_add_marzban_user)
    finally:
        # Cleanup only if the operation is canceled
        if name.startswith('/'):
            admin_conversations.pop(uid, None)

def _get_limit_for_add_marzban_user(msg: types.Message):
    uid, limit_text = msg.from_user.id, msg.text.strip()
    _delete_user_message(msg)

    try:
        if uid not in admin_conversations: return
        if limit_text.startswith('/'):
            _safe_edit(uid, admin_conversations[uid]['msg_id'], "عملیات ساخت کاربر لغو شد\\.", reply_markup=menu.admin_panel_management_menu('marzban'))
            return

        limit = float(limit_text)
        admin_conversations[uid]['usage_limit_GB'] = limit
        name = admin_conversations[uid]['username']
        limit_str = escape_markdown(f"{limit:.1f}")
        prompt = f"نام کاربری: `{escape_markdown(name)}`, حجم: `{limit_str} GB`\n\n3\\. در نهایت، **مدت زمان** پلن \\(به روز\\) را وارد کنید \\(عدد `0` برای نامحدود\\):"
        _safe_edit(uid, admin_conversations[uid]['msg_id'], prompt, reply_markup=menu.cancel_action("admin:manage_panel:marzban"))
        bot.register_next_step_handler_by_chat_id(uid, _get_days_for_add_marzban_user)

    except (ValueError, TypeError):
        bot.send_message(uid, "❌ ورودی نامعتبر\\. لطفاً یک عدد برای حجم وارد کنید\\.")
        bot.register_next_step_handler_by_chat_id(uid, _get_limit_for_add_marzban_user)
    finally:
        if limit_text.startswith('/'):
            admin_conversations.pop(uid, None)

def _get_days_for_add_marzban_user(msg: types.Message):
    uid, days_text = msg.from_user.id, msg.text.strip()
    _delete_user_message(msg)

    if uid not in admin_conversations: return
    
    try:
        if days_text.startswith('/'):
            _safe_edit(uid, admin_conversations[uid]['msg_id'], "عملیات ساخت کاربر لغو شد\\.", reply_markup=menu.admin_panel_management_menu('marzban'))
            return

        days = int(days_text)
        admin_conversations[uid]['package_days'] = days
        _finish_marzban_user_creation(uid, admin_conversations[uid]['msg_id'])

    except (ValueError, TypeError):
        bot.send_message(uid, "❌ ورودی نامعتبر. لطفاً یک عدد صحیح برای روز وارد کنید\\.")
        bot.register_next_step_handler_by_chat_id(uid, _get_days_for_add_marzban_user)
    finally:
        # Cleanup if canceled or finished
        if days_text.startswith('/') or days_text.isdigit():
            admin_conversations.pop(uid, None)


def _finish_marzban_user_creation(uid, msg_id):
    user_data = admin_conversations.get(uid, {}).copy()
    
    if not user_data:
        _safe_edit(uid, msg_id, "⚠️ عملیات به دلیل وقفه در ربات لغو شد\\. لطفاً دوباره شروع کنید\\.", reply_markup=menu.admin_panel_management_menu('marzban'))
        return

    username_escaped = escape_markdown(user_data.get('username', ''))
    list_bullet = escape_markdown("> ")
    wait_msg = f"⏳ در حال ساخت کاربر در پنل مرzبان\\.\\.\\.\n{list_bullet}نام کاربری: `{username_escaped}`"
    _safe_edit(uid, msg_id, wait_msg)
    
    new_user_info = marzban_handler.add_user(user_data)
    
    if new_user_info and new_user_info.get('username'):
        final_info = combined_handler.get_combined_user_info(new_user_info['username'])
        text = fmt_admin_user_summary(final_info)
        success_text = f"✅ کاربر با موفقیت ساخته شد\\.\n\n{text}"
        _safe_edit(uid, msg_id, success_text, reply_markup=menu.admin_panel_management_menu('marzban'))
    else:
        logger.error(f"Marzban user creation failed. API response: {new_user_info}")
        err_msg = "❌ خطا در ساخت کاربر\\. ممکن است نام تکراری باشد یا پنل در دسترس نباشد\\. لطفاً لاگ ربات را برای اطلاعات بیشتر بررسی کنید\\."
        _safe_edit(uid, msg_id, err_msg, reply_markup=menu.admin_panel_management_menu('marzban'))