# bot/admin_hiddify_handlers.py

import logging
from telebot import types
from datetime import datetime
import pytz

# --- START: MODIFIED IMPORTS ---
from .menu import menu
from .hiddify_api_handler import HiddifyAPIHandler # Import the Class, not the instance
from .database import db # Import db to get panel configs
from .utils import _safe_edit, escape_markdown
from .admin_formatters import fmt_admin_user_summary
# --- END: MODIFIED IMPORTS ---

logger = logging.getLogger(__name__)
bot = None
admin_conversations = {}

def initialize_hiddify_handlers(b_instance, conversations_dict):
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
    prompt = "افزودن کاربر به پنل Hiddify 🇩🇪\n\n"
    if is_retry: prompt += "⚠️ نام کاربری باید حداقل ۳ کاراکتر باشد. لطفاً دوباره وارد کنید.\n\n"
    prompt += "1. لطفاً یک **نام کاربری** وارد کنید:"
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
    _update_conversation(uid, {'name': name, 'step': 'days'})
    _ask_for_days(uid, convo['msg_id'], name)

def _ask_for_days(uid, msg_id, username, is_retry=False):
    prompt = f"نام کاربر: `{escape_markdown(username)}`\n\n"
    if is_retry: prompt += "⚠️ ورودی قبلی نامعتبر بود. لطفاً یک عدد صحیح وارد کنید.\n\n"
    prompt += "2. حالا **مدت زمان** پلن (به روز) را وارد کنید (عدد `0` برای نامحدود):"
    kb = menu.back_or_cancel("admin:add_user_back:hiddify:username", "admin:management_menu")
    _safe_edit(uid, msg_id, prompt, reply_markup=kb, parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, _get_days_for_add_user)
    
def _get_days_for_add_user(msg: types.Message):
    uid, days_text = msg.from_user.id, msg.text.strip()
    _delete_user_message(msg)
    if uid not in admin_conversations: return
    convo = admin_conversations[uid]
    try:
        days = int(days_text)
        _update_conversation(uid, {'package_days': days, 'step': 'limit'})
        _ask_for_limit(uid, convo['msg_id'], convo['name'], days)
    except (ValueError, TypeError):
        _ask_for_days(uid, convo['msg_id'], convo['name'], is_retry=True)

def _ask_for_limit(uid, msg_id, username, days, is_retry=False):
    days_str = f"{days}" if days is not None else "0"
    prompt = f"نام: `{escape_markdown(username)}`, مدت: `{days_str} روز`\n\n"
    if is_retry: prompt += "⚠️ ورودی قبلی نامعتبر بود. لطفاً یک عدد وارد کنید.\n\n"
    prompt += "3. در نهایت، **حجم کل مصرف** (به گیگابایت) را وارد کنید (عدد `0` برای نامحدود):"
    kb = menu.back_or_cancel("admin:add_user_back:hiddify:days", "admin:management_menu")
    _safe_edit(uid, msg_id, prompt, reply_markup=kb, parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, _get_limit_for_add_user)

def _get_limit_for_add_user(msg: types.Message):
    uid, limit_text = msg.from_user.id, msg.text.strip()
    _delete_user_message(msg)
    if uid not in admin_conversations: return
    convo = admin_conversations[uid]
    try:
        limit = float(limit_text)
        _update_conversation(uid, {'usage_limit_GB': limit})
        _finish_user_creation(uid, admin_conversations[uid])
    except (ValueError, TypeError):
        _ask_for_limit(uid, convo['msg_id'], convo['name'], convo['package_days'], is_retry=True)


def _finish_user_creation(uid, user_data):
    """تابع نهایی برای ساخت کاربر که با سیستم داینامیک هماهنگ شده است."""
    msg_id = user_data.get('msg_id')
    
    # --- START: NEW DYNAMIC LOGIC ---
    # ۱. پیدا کردن اولین پنل هیدیفای فعال از دیتابیس
    active_hiddify_panels = [p for p in db.get_active_panels() if p['panel_type'] == 'hiddify']
    if not active_hiddify_panels:
        err_msg = "❌ خطا: هیچ پنل فعال Hiddify در سیستم ثبت نشده است."
        _safe_edit(uid, msg_id, err_msg, reply_markup=menu.admin_panel_management_menu('hiddify'))
        return
        
    # در این نسخه، ما کاربر را به اولین پنل یافت شده اضافه می‌کنیم.
    # در آینده می‌توان منویی برای انتخاب پنل به کاربر نمایش داد.
    target_panel_config = active_hiddify_panels[0]
    
    _safe_edit(uid, msg_id, f"⏳ در حال ساخت کاربر در پنل: {escape_markdown(target_panel_config['name'])}...")

    # ۲. ساخت یک handler مخصوص برای این پنل
    handler = HiddifyAPIHandler(target_panel_config)
    
    # ۳. استفاده از handler جدید برای افزودن کاربر
    new_user_info = handler.add_user(user_data)
    # --- END: NEW DYNAMIC LOGIC ---
    
    admin_conversations.pop(uid, None)
    
    if new_user_info and new_user_info.get('uuid'):
        # بخش فرمت کردن پیام موفقیت بدون تغییر باقی می‌ماند
        final_info = {
            'name': new_user_info.get('name'),
            'uuid': new_user_info.get('uuid'),
            'is_active': True,
            'breakdown': {target_panel_config['name']: new_user_info},
            'expire': new_user_info.get('expire')
        }
        
        text = fmt_admin_user_summary(final_info)
        success_text = f"✅ کاربر با موفقیت در پنل {escape_markdown(target_panel_config['name'])} ساخته شد.\n\n{text}"
        _safe_edit(uid, msg_id, success_text, reply_markup=menu.admin_management_menu(), parse_mode="Markdown")
    else:
        err_msg = f"❌ خطا در ساخت کاربر در پنل {escape_markdown(target_panel_config['name'])}. ممکن است پنل در دسترس نباشد."
        _safe_edit(uid, msg_id, err_msg, reply_markup=menu.admin_management_menu())


def _start_add_hiddify_user_convo(uid, msg_id):
    """Starts the conversation for adding a user to a Hiddify panel."""
    _update_conversation(uid, {'step': 'username', 'msg_id': msg_id, 'panel_type': 'hiddify'})
    _ask_for_username(uid, msg_id)

def handle_add_user_back_step(call: types.CallbackQuery, params: list):
    """Handles the 'back' button during the multi-step user creation process."""
    uid = call.from_user.id
    if uid not in admin_conversations: return
    
    convo = admin_conversations[uid]
    msg_id = convo.get('msg_id')
    back_to_step = params[1] if len(params) > 1 else 'username'

    if back_to_step == 'username':
        _update_conversation(uid, {'step': 'username'})
        _ask_for_username(uid, msg_id)
    elif back_to_step == 'days':
        _update_conversation(uid, {'step': 'days'})
        _ask_for_days(uid, msg_id, convo.get('name'))


# --- The commented-out code for creating users from a plan remains here ---
# --- You can uncomment it when you are ready to continue with the feature ---

# --- User Creation Flow (From Plan) ---
# ... (your commented-out functions) ...


# --- User Creation Flow (From Plan) ---

# def _start_add_user_from_plan_convo(call, params):
#     panel = params[0]
#     uid, msg_id = call.from_user.id, call.message.message_id
    
#     plans = load_service_plans()
#     if not plans:
#         _safe_edit(uid, msg_id, "❌ هیچ پلنی در فایل `plans\\.json` یافت نشد\\.", reply_markup=menu.admin_panel_management_menu(panel))
#         return

#     kb = types.InlineKeyboardMarkup(row_width=1)
#     for i, plan in enumerate(plans):
#         callback = f"admin:plan_select:{panel}:{i}"
#         kb.add(types.InlineKeyboardButton(plan.get('name', f'Plan {i+1}'), callback_data=callback))
    
#     kb.add(types.InlineKeyboardButton("🔙 لغو و بازگشت", callback_data=f"admin:manage_panel:{panel}"))

#     panel_name = "آلمان 🇩🇪" if panel == "hiddify" else "فرانسه 🇫🇷"
#     prompt = f"افزودن کاربر به پنل *{panel_name}*\n\nلطفاً یک پلن را انتخاب کنید:"
#     _safe_edit(uid, msg_id, prompt, reply_markup=kb)

# def _handle_plan_selection(call, params):
#     panel, plan_index = int(params[0]), int(params[1]) if len(params) > 1 else 0
#     uid, msg_id = call.from_user.id, call.message.message_id
    
#     plans = load_service_plans()
#     selected_plan = plans[plan_index]
    
#     admin_conversations[uid] = {'panel': panel, 'plan': selected_plan, 'msg_id': msg_id}

#     plan_name_escaped = escape_markdown(selected_plan.get('name', ''))
    
#     # تغيير: escape کردن نقطه
#     prompt = f"شما پلن *{plan_name_escaped}* را انتخاب کردید\\.\n\nحالا لطفاً یک **نام کاربری** برای کاربر جدید وارد کنید:"
#     _safe_edit(uid, msg_id, prompt, reply_markup=menu.cancel_action(f"admin:manage_panel:{panel}"))
#     bot.register_next_step_handler_by_chat_id(uid, _get_name_for_plan_user)

# def _get_name_for_plan_user(msg: types.Message):
#     uid, name = msg.from_user.id, msg.text.strip()
#     _delete_user_message(msg)

#     if uid not in admin_conversations: return
#     try:
#         if name.startswith('/'):
#             # تغيير: escape کردن نقطه
#             _safe_edit(uid, admin_conversations[uid]['msg_id'], "عملیات لغو شد\\.", reply_markup=menu.admin_panel_management_menu(admin_conversations[uid]['panel']))
#             return

#         convo_data = admin_conversations[uid]
#         convo_data['name'] = name
#         _finish_user_creation_from_plan(uid, convo_data)

#     finally:
#         admin_conversations.pop(uid, None)

# def _finish_user_creation_from_plan(uid, convo_data):
#     msg_id = convo_data['msg_id']
#     panel = convo_data['panel']
#     plan = convo_data['plan']
#     name = convo_data['name']
    
#     duration = parse_volume_string(plan.get('duration', '30'))
    
#     if panel == 'hiddify':
#         limit_gb = parse_volume_string(plan.get('volume_de', '0'))
#         user_data = {"name": name, "usage_limit_GB": limit_gb, "package_days": duration, "mode": "no_reset"}
#         new_user_info = hiddify_handler.add_user(user_data)
#         identifier = new_user_info.get('uuid') if new_user_info else None
        
#     elif panel == 'marzban':
#         limit_gb = parse_volume_string(plan.get('volume_fr', '0'))
#         user_data = {"username": name, "usage_limit_GB": limit_gb, "package_days": duration}
#         new_user_info = marzban_handler.add_user(user_data)
#         identifier = new_user_info.get('username') if new_user_info else None

#     if identifier:
#         final_info = combined_handler.get_combined_user_info(identifier)
#         text = fmt_admin_user_summary(final_info)
#         # تغيير: escape کردن نقطه
#         success_text = f"✅ کاربر *{escape_markdown(name)}* با موفقیت از روی پلن ساخته شد\\.\n\n{text}"
#         _safe_edit(uid, msg_id, success_text, reply_markup=menu.admin_panel_management_menu(panel))
#     else:
#         # تغيير: escape کردن نقطه
#         err_msg = "❌ خطا در ساخت کاربر\\. ممکن است نام تکراری باشد یا پنل در دسترس نباشد\\."
#         _safe_edit(uid, msg_id, err_msg, reply_markup=menu.admin_panel_management_menu(panel))