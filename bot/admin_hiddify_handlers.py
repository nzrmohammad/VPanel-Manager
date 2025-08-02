from telebot import types
from .menu import menu
from .hiddify_api_handler import hiddify_handler
from .marzban_api_handler import marzban_handler
from . import combined_handler
from .admin_formatters import fmt_admin_user_summary
from .user_formatters import fmt_one
from .utils import _safe_edit, escape_markdown, load_service_plans, parse_volume_string
import logging

logger = logging.getLogger(__name__)
bot = None
admin_conversations = {}

def initialize_hiddify_handlers(b_instance, conversations_dict):
    global bot, admin_conversations
    bot = b_instance
    admin_conversations = conversations_dict

def _delete_user_message(msg: types.Message):
    try:
        bot.delete_message(msg.chat.id, msg.message_id)
    except Exception as e:
        logger.warning(f"Could not delete user message {msg.message_id}: {e}")

# --- User Creation Flow (Manual) ---

def _start_add_user_convo(uid, msg_id):
    admin_conversations[uid] = {'msg_id': msg_id, 'panel': 'hiddify'}
    # تغيير: escape کردن پرانتز و نقطه
    prompt = "افزودن کاربر به پنل آلمان \\(Hiddify\\) 🇩🇪\n\n1\\. لطفاً یک **نام** برای کاربر جدید وارد کنید:"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.cancel_action("admin:manage_panel:hiddify"))
    bot.register_next_step_handler_by_chat_id(uid, _get_name_for_add_user)

def _get_name_for_add_user(msg: types.Message):
    uid, name = msg.from_user.id, msg.text.strip()
    _delete_user_message(msg)
    try:
        if uid not in admin_conversations: return
        if name.startswith('/'):
            _safe_edit(uid, admin_conversations[uid]['msg_id'], "عملیات ساخت کاربر لغو شد\\.", reply_markup=menu.admin_panel_management_menu('hiddify'))
            return
        
        msg_id = admin_conversations[uid].get('msg_id')
        admin_conversations[uid]['name'] = name
        # تغيير: escape کردن نقطه و پرانتزها
        prompt = f"نام کاربر: `{escape_markdown(name)}`\n\n2\\. حالا **مدت زمان** پلن \\(به روز\\) را وارد کنید \\(مثلاً: `30`\\):"
        _safe_edit(uid, msg_id, prompt, reply_markup=menu.cancel_action("admin:manage_panel:hiddify"))
        bot.register_next_step_handler_by_chat_id(uid, _get_days_for_add_user)
    finally:
        if name.startswith('/'):
            admin_conversations.pop(uid, None)


def _get_days_for_add_user(msg: types.Message):
    uid, days_text = msg.from_user.id, msg.text.strip()
    _delete_user_message(msg)
    try:
        if uid not in admin_conversations: return
        if days_text.startswith('/'):
            _safe_edit(uid, admin_conversations[uid]['msg_id'], "عملیات ساخت کاربر لغو شد\\.", reply_markup=menu.admin_panel_management_menu('hiddify'))
            return
        
        days = int(days_text)
        admin_conversations[uid]['package_days'] = days
        name = admin_conversations[uid]['name']
        # تغيير: escape کردن نقطه و پرانتزها
        prompt = f"نام: `{escape_markdown(name)}`, مدت: `{days}` روز\n\n3\\. در نهایت، **حجم کل مصرف** \\(به گیگابایت\\) را وارد کنید \\(عدد `0` برای نامحدود\\):"
        _safe_edit(uid, admin_conversations[uid]['msg_id'], prompt, reply_markup=menu.cancel_action("admin:manage_panel:hiddify"))
        bot.register_next_step_handler_by_chat_id(uid, _get_limit_for_add_user)

    except (ValueError, TypeError):
        bot.send_message(uid, "❌ ورودی نامعتبر\\. لطفاً یک عدد صحیح برای روز وارد کنید\\.")
        bot.register_next_step_handler_by_chat_id(uid, _get_days_for_add_user)

    finally:
        if days_text.startswith('/'):
            admin_conversations.pop(uid, None)

def _get_limit_for_add_user(msg: types.Message):
    uid, limit_text = msg.from_user.id, msg.text.strip()
    _delete_user_message(msg)
    try:
        if uid not in admin_conversations: return
        if limit_text.startswith('/'):
            _safe_edit(uid, admin_conversations[uid]['msg_id'], "عملیات ساخت کاربر لغو شد\\.", reply_markup=menu.admin_panel_management_menu('hiddify'))
            return

        limit = float(limit_text)
        admin_conversations[uid]['usage_limit_GB'] = limit
        # تغيير: escape کردن نقطه
        prompt = (
            "4\\. لطفاً **حالت مصرف** را با ارسال عدد مورد نظر انتخاب کنید:\n\n"
            "`1` \\- ماهانه \\(monthly\\)\n"
            "`2` \\- هفتگی \\(weekly\\)\n"
            "`3` \\- روزانه \\(daily\\)\n"
            "`4` \\- بدون ریست \\(حجم کل برای تمام دوره\\)"
        )
        _safe_edit(uid, admin_conversations[uid]['msg_id'], prompt, reply_markup=menu.cancel_action("admin:manage_panel:hiddify"))
        bot.register_next_step_handler_by_chat_id(uid, _get_mode_for_add_user)

    except (ValueError, TypeError):
        bot.send_message(uid, "❌ ورودی نامعتبر\\. لطفاً یک عدد برای حجم وارد کنید\\.")
        bot.register_next_step_handler_by_chat_id(uid, _get_limit_for_add_user)
    finally:
        if limit_text.startswith('/'):
            admin_conversations.pop(uid, None)

def _get_mode_for_add_user(msg: types.Message):
    uid, choice = msg.from_user.id, msg.text.strip()
    _delete_user_message(msg)

    if uid not in admin_conversations: return
    try:
        if choice.startswith('/'):
            _safe_edit(uid, admin_conversations[uid]['msg_id'], "عملیات ساخت کاربر لغو شد\\.", reply_markup=menu.admin_panel_management_menu('hiddify'))
            return
        
        mode_map = {'1': 'monthly', '2': 'weekly', '3': 'daily', '4': 'no_reset'}
        if choice not in mode_map:
            bot.send_message(uid, "❌ انتخاب نامعتبر است\\. لطفاً عددی بین ۱ تا ۴ وارد کنید\\.")
            bot.register_next_step_handler_by_chat_id(uid, _get_mode_for_add_user)
            return
        
        convo_data = admin_conversations[uid]
        convo_data['mode'] = mode_map[choice]
        _finish_user_creation(uid, convo_data)
    finally:
        if choice.startswith('/') or choice in {'1', '2', '3', '4'}:
             admin_conversations.pop(uid, None)

def _finish_user_creation(uid, user_data):
    msg_id = user_data['msg_id']
    name_escaped = escape_markdown(user_data.get('name', 'N/A'))
    limit_gb_escaped = escape_markdown(f"{user_data.get('usage_limit_GB', 0.0):.1f}")
    days_escaped = escape_markdown(str(user_data.get('package_days', 'N/A')))
    mode_escaped = escape_markdown(user_data.get('mode', 'N/A'))
    
    list_bullet = escape_markdown("> ")
    wait_msg_text = (
        f"⏳ در حال ساخت کاربر با اطلاعات زیر:\n"
        f"{list_bullet}نام: `{name_escaped}`\n"
        f"{list_bullet}حجم: `{limit_gb_escaped} GB`\n"
        f"{list_bullet}مدت: `{days_escaped}` روز\n"
        f"{list_bullet}حالت: `{mode_escaped}`"
    )
    _safe_edit(uid, msg_id, wait_msg_text)

    new_user_info = hiddify_handler.add_user(user_data)
    if new_user_info and new_user_info.get('uuid'):
        final_info = combined_handler.get_combined_user_info(new_user_info['uuid'])
        text = fmt_admin_user_summary(final_info)
        success_text = f"✅ کاربر با موفقیت ساخته شد\\.\n\n{text}"
        _safe_edit(uid, msg_id, success_text, reply_markup=menu.admin_panel_management_menu('hiddify'))
    else:
        err_msg = "❌ خطا در ساخت کاربر\\. ممکن است نام تکراری باشد یا پنل در دسترس نباشد\\."
        _safe_edit(uid, msg_id, err_msg, reply_markup=menu.admin_panel_management_menu('hiddify'))

# --- User Creation Flow (From Plan) ---

def _start_add_user_from_plan_convo(call, params):
    panel = params[0]
    uid, msg_id = call.from_user.id, call.message.message_id
    
    plans = load_service_plans()
    if not plans:
        _safe_edit(uid, msg_id, "❌ هیچ پلنی در فایل `plans\\.json` یافت نشد\\.", reply_markup=menu.admin_panel_management_menu(panel))
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for i, plan in enumerate(plans):
        callback = f"admin:plan_select:{panel}:{i}"
        kb.add(types.InlineKeyboardButton(plan.get('name', f'Plan {i+1}'), callback_data=callback))
    
    kb.add(types.InlineKeyboardButton("🔙 لغو و بازگشت", callback_data=f"admin:manage_panel:{panel}"))

    panel_name = "آلمان 🇩🇪" if panel == "hiddify" else "فرانسه 🇫🇷"
    prompt = f"افزودن کاربر به پنل *{panel_name}*\n\nلطفاً یک پلن را انتخاب کنید:"
    _safe_edit(uid, msg_id, prompt, reply_markup=kb)

def _handle_plan_selection(call, params):
    panel, plan_index = int(params[0]), int(params[1]) if len(params) > 1 else 0
    uid, msg_id = call.from_user.id, call.message.message_id
    
    plans = load_service_plans()
    selected_plan = plans[plan_index]
    
    admin_conversations[uid] = {'panel': panel, 'plan': selected_plan, 'msg_id': msg_id}

    plan_name_escaped = escape_markdown(selected_plan.get('name', ''))
    
    # تغيير: escape کردن نقطه
    prompt = f"شما پلن *{plan_name_escaped}* را انتخاب کردید\\.\n\nحالا لطفاً یک **نام کاربری** برای کاربر جدید وارد کنید:"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.cancel_action(f"admin:manage_panel:{panel}"))
    bot.register_next_step_handler_by_chat_id(uid, _get_name_for_plan_user)

def _get_name_for_plan_user(msg: types.Message):
    uid, name = msg.from_user.id, msg.text.strip()
    _delete_user_message(msg)

    if uid not in admin_conversations: return
    try:
        if name.startswith('/'):
            # تغيير: escape کردن نقطه
            _safe_edit(uid, admin_conversations[uid]['msg_id'], "عملیات لغو شد\\.", reply_markup=menu.admin_panel_management_menu(admin_conversations[uid]['panel']))
            return

        convo_data = admin_conversations[uid]
        convo_data['name'] = name
        _finish_user_creation_from_plan(uid, convo_data)

    finally:
        admin_conversations.pop(uid, None)

def _finish_user_creation_from_plan(uid, convo_data):
    msg_id = convo_data['msg_id']
    panel = convo_data['panel']
    plan = convo_data['plan']
    name = convo_data['name']
    
    duration = parse_volume_string(plan.get('duration', '30'))
    
    if panel == 'hiddify':
        limit_gb = parse_volume_string(plan.get('volume_de', '0'))
        user_data = {"name": name, "usage_limit_GB": limit_gb, "package_days": duration, "mode": "no_reset"}
        new_user_info = hiddify_handler.add_user(user_data)
        identifier = new_user_info.get('uuid') if new_user_info else None
        
    elif panel == 'marzban':
        limit_gb = parse_volume_string(plan.get('volume_fr', '0'))
        user_data = {"username": name, "usage_limit_GB": limit_gb, "package_days": duration}
        new_user_info = marzban_handler.add_user(user_data)
        identifier = new_user_info.get('username') if new_user_info else None

    if identifier:
        final_info = combined_handler.get_combined_user_info(identifier)
        text = fmt_admin_user_summary(final_info)
        # تغيير: escape کردن نقطه
        success_text = f"✅ کاربر *{escape_markdown(name)}* با موفقیت از روی پلن ساخته شد\\.\n\n{text}"
        _safe_edit(uid, msg_id, success_text, reply_markup=menu.admin_panel_management_menu(panel))
    else:
        # تغيير: escape کردن نقطه
        err_msg = "❌ خطا در ساخت کاربر\\. ممکن است نام تکراری باشد یا پنل در دسترس نباشد\\."
        _safe_edit(uid, msg_id, err_msg, reply_markup=menu.admin_panel_management_menu(panel))