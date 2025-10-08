import logging
from telebot import types, apihelper
from typing import Optional, Dict, Any
from ..database import db
from ..menu import menu
from .. import combined_handler
from ..admin_formatters import fmt_admin_user_summary, fmt_user_payment_history
from ..utils import _safe_edit, escape_markdown, load_service_plans, save_service_plans, parse_volume_string

from ..user_handlers.wallet import _check_and_apply_loyalty_reward, _check_and_apply_referral_reward
from ..config import ACHIEVEMENTS
from ..scheduler_jobs.rewards import notify_user_achievement
from ..language import get_string
from ..user_formatters import fmt_purchase_summary


logger = logging.getLogger(__name__)
bot, admin_conversations = None, None


def initialize_user_management_handlers(b, conv_dict):
    global bot, admin_conversations
    bot = b
    admin_conversations = conv_dict

def handle_show_user_summary(call, params):
    """
    CORRECTED: Parses parameters correctly to fetch user info using the full identifier.
    The identifier is now correctly retrieved from params[1].
    """
    identifier = params[1] 
    back_target = params[2] if len(params) > 2 else 'management_menu'
    
    info = combined_handler.get_combined_user_info(identifier)
    if not info:
        _safe_edit(call.from_user.id, call.message.message_id, escape_markdown("خطا در دریافت اطلاعات کاربر."),
                   reply_markup=menu.admin_search_menu()) 
        return

    db_user = None
    if info.get('uuid'):
        user_telegram_id = db.get_user_id_by_uuid(info['uuid'])
        if user_telegram_id:
            db_user = db.user(user_telegram_id)

    text = fmt_admin_user_summary(info, db_user)
    
    back_callback = f"admin:{back_target}" if back_target in ['search_menu', 'management_menu'] else "admin:search_menu"
    
    panel_type = 'hiddify' if any(p.get('type') == 'hiddify' for p in info.get('breakdown', {}).values()) else 'marzban'
    kb = menu.admin_user_interactive_management(identifier, info.get('is_active', False), panel_type, back_callback=back_callback)
    
    _safe_edit(call.from_user.id, call.message.message_id, text, reply_markup=kb)


def handle_edit_user_menu(call, params):
    """
    منوی اصلی ویرایش کاربر را با گزینه‌های "افزودن حجم" و "افزودن روز" نمایش می‌دهد.
    """
    identifier = params[0]
    context = "search" if len(params) > 1 and params[1] == 'search' else None
    context_suffix = f":{context}" if context else ""

    info = combined_handler.get_combined_user_info(identifier)
    if not info:
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد.", show_alert=True)
        return

    breakdown = info.get('breakdown', {})
    on_hiddify = any(p.get('type') == 'hiddify' for p in breakdown.values())
    on_marzban = any(p.get('type') == 'marzban' for p in breakdown.values())

    single_panel_type = None
    if on_hiddify and not on_marzban:
        single_panel_type = 'hiddify'
    elif on_marzban and not on_hiddify:
        single_panel_type = 'marzban'

    prompt = "🔧 لطفاً نوع ویرایش را انتخاب کنید:"
    kb = types.InlineKeyboardMarkup(row_width=2)
    
    if single_panel_type:
        btn_add_gb = types.InlineKeyboardButton("➕ افزودن حجم", callback_data=f"admin:ae:agb:{single_panel_type}:{identifier}{context_suffix}")
        btn_add_days = types.InlineKeyboardButton("➕ افزودن روز", callback_data=f"admin:ae:ady:{single_panel_type}:{identifier}{context_suffix}")
    else:
        btn_add_gb = types.InlineKeyboardButton("➕ افزودن حجم", callback_data=f"admin:ep:agb:{identifier}{context_suffix}")
        btn_add_days = types.InlineKeyboardButton("➕ افزودن روز", callback_data=f"admin:ep:ady:{identifier}{context_suffix}")

    panel_short_for_back = 'h' if on_hiddify else 'm'
    btn_back = types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"admin:us:{panel_short_for_back}:{identifier}{context_suffix}")
    
    kb.add(btn_add_gb, btn_add_days)
    kb.add(btn_back)
    
    _safe_edit(call.from_user.id, call.message.message_id, escape_markdown(prompt), reply_markup=kb)


def handle_select_panel_for_edit(call, params):
    """
    اگر کاربر در هر دو پنل باشد، این منو برای انتخاب پنل مقصد (آلمان یا فرانسه) نمایش داده می‌شود.
    """
    edit_type, identifier = params[0], params[1]
    context = "search" if len(params) > 2 and params[2] == 'search' else None
    context_suffix = f":{context}" if context else ""

    edit_type_map = {"agb": "افزودن حجم", "ady": "افزودن روز"}
    edit_type_name = edit_type_map.get(edit_type, "ویرایش")

    prompt = "⚙️ " + f"لطفاً پنلی که می‌خواهید «{edit_type_name}» به آن اضافه شود را انتخاب کنید:"
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    btn_h = types.InlineKeyboardButton("آلمان 🇩🇪", callback_data=f"admin:ae:{edit_type}:hiddify:{identifier}{context_suffix}")
    btn_m = types.InlineKeyboardButton("فرانسه 🇫🇷", callback_data=f"admin:ae:{edit_type}:marzban:{identifier}{context_suffix}")
    
    kb.add(btn_h, btn_m)
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"admin:edt:{identifier}{context_suffix}"))
    
    _safe_edit(call.from_user.id, call.message.message_id, escape_markdown(prompt), reply_markup=kb)


def handle_ask_edit_value(call, params):
    """
    از ادمین می‌پرسد که چه مقدار حجم یا روز می‌خواهد اضافه کند.
    """
    edit_type, panel_type, identifier = params[0], params[1], params[2]
    context = "search" if len(params) > 3 and params[3] == "search" else None
    
    prompt_map = {
        "agb": "مقدار حجم برای افزودن (به GB) را وارد کنید:",
        "ady": "تعداد روز برای افزودن را وارد کنید:"
    }
    prompt = prompt_map.get(edit_type, "مقدار جدید را وارد کنید:")
    
    uid, msg_id = call.from_user.id, call.message.message_id
    back_cb = f"admin:edt:{identifier}{ (':' + context) if context else '' }"
    
    admin_conversations[uid] = {
        'edit_type': edit_type, 
        'panel_type': panel_type, 
        'identifier': identifier, 
        'msg_id': msg_id,
        'context': context 
    }
    _safe_edit(uid, msg_id, escape_markdown(prompt), reply_markup=menu.admin_cancel_action(back_callback=back_cb), parse_mode=None)
    bot.register_next_step_handler_by_chat_id(uid, apply_user_edit)


def apply_user_edit(msg: types.Message):
    """
    مقدار وارد شده توسط ادمین را دریافت کرده و با API پنل، کاربر را ویرایش می‌کند.
    """
    uid, text = msg.from_user.id, msg.text.strip()
    bot.delete_message(uid, msg.message_id) 
    if uid not in admin_conversations: return

    convo = admin_conversations.pop(uid, {})
    identifier = convo.get('identifier')
    edit_type = convo.get('edit_type')
    panel_type = convo.get('panel_type')
    msg_id = convo.get('msg_id')
    context = convo.get('context')

    if not all([identifier, edit_type, panel_type, msg_id]): return

    try:
        value = float(text)
        add_gb = value if edit_type == "agb" else 0
        add_days = int(value) if edit_type == "ady" else 0
        
        success = combined_handler.modify_user_on_all_panels(
            identifier=identifier, add_gb=add_gb, add_days=add_days, target_panel_type=panel_type
        )

        if success:
            new_info = combined_handler.get_combined_user_info(identifier)
            text_to_show = fmt_admin_user_summary(new_info) + "\n\n*✅ کاربر با موفقیت ویرایش شد\\.*"
            back_callback = "admin:search_menu" if context == "search" else None
            kb = menu.admin_user_interactive_management(identifier, new_info['is_active'], panel_type, back_callback=back_callback)
            _safe_edit(uid, msg_id, text_to_show, reply_markup=kb)
        else:
            raise Exception("API call failed")

    except Exception as e:
        logger.error(f"Failed to apply user edit for {identifier}: {e}")
        _safe_edit(uid, msg_id, escape_markdown("❌ خطا در ویرایش کاربر."), reply_markup=menu.admin_panel())


def handle_toggle_status(call, params):
    """
    Handles the initial "Change Status" button press.
    If the user is on multiple panels, it shows a selection menu.
    """
    identifier = params[0]
    context = "search" if len(params) > 1 and params[1] == 'search' else None

    info = combined_handler.get_combined_user_info(identifier)
    if not info:
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد.", show_alert=True)
        return

    breakdown = info.get('breakdown', {})
    on_hiddify = any(p.get('type') == 'hiddify' for p in breakdown.values())
    on_marzban = any(p.get('type') == 'marzban' for p in breakdown.values())

    if on_hiddify and not on_marzban:
        action_params = ['hiddify', identifier]
        if context: action_params.append(context)
        handle_toggle_status_action(call, action_params)
        return
    elif on_marzban and not on_hiddify:
        action_params = ['marzban', identifier]
        if context: action_params.append(context)
        handle_toggle_status_action(call, action_params)
        return
    
    prompt = "⚙️ *وضعیت کدام پنل تغییر کند؟*"
    kb = menu.admin_reset_usage_selection_menu(identifier, base_callback="tglA", context=context)
    _safe_edit(call.from_user.id, call.message.message_id, prompt, reply_markup=kb)


def handle_toggle_status_action(call, params):
    """
    Executes the status change on the selected panel(s) after admin makes a choice.
    """
    panel_to_toggle, identifier = params[0], params[1]
    context = "search" if len(params) > 2 and params[2] == 'search' else None

    info = combined_handler.get_combined_user_info(identifier)
    if not info:
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد.", show_alert=True)
        return

    success = True
    
    active_panels = {p['name']: p for p in db.get_active_panels()}

    for panel_name, panel_details in info.get('breakdown', {}).items():
        panel_type = panel_details.get('type')
        panel_data = panel_details.get('data', {})
        
        if panel_type == panel_to_toggle or panel_to_toggle == 'both':
            panel_config = active_panels.get(panel_name)
            if not panel_config: continue

            handler = combined_handler._get_handler_for_panel(panel_config)
            if not handler: continue
            
            current_status = panel_data.get('is_active', False)
            new_status = not current_status
            
            if panel_type == 'hiddify' and info.get('uuid'):
                if not handler.modify_user(info['uuid'], data={'enable': new_status}):
                    success = False
            
            elif panel_type == 'marzban' and panel_data.get('username'):
                marzban_status = 'active' if new_status else 'disabled'
                if not handler.modify_user(panel_data['username'], data={'status': marzban_status}):
                    success = False
    
    if success:
        bot.answer_callback_query(call.id, "✅ وضعیت با موفقیت تغییر کرد.")
        new_info = combined_handler.get_combined_user_info(identifier)
        if new_info:
            back_callback = "admin:search_menu" if context == "search" else "admin:management_menu"
            db_user = None
            if new_info.get('uuid'):
                user_telegram_id = db.get_user_id_by_uuid(new_info['uuid'])
                if user_telegram_id: db_user = db.user(user_telegram_id)
            
            text = fmt_admin_user_summary(new_info, db_user)
            panel_type_for_menu = 'hiddify' if any(p.get('type') == 'hiddify' for p in new_info.get('breakdown', {}).values()) else 'marzban'
            kb = menu.admin_user_interactive_management(identifier, new_info.get('is_active', False), panel_type_for_menu, back_callback=back_callback)
            _safe_edit(call.from_user.id, call.message.message_id, text, reply_markup=kb)
    else:
        bot.answer_callback_query(call.id, "❌ عملیات در یک یا چند پنل ناموفق بود.", show_alert=True)


def handle_reset_birthday(call, params):
    identifier = params[0]
    context = "search" if len(params) > 1 and params[1] == 'search' else None
    context_suffix = f":{context}" if context else ""

    info = combined_handler.get_combined_user_info(identifier)
    if not info or not info.get('uuid'):
        bot.answer_callback_query(call.id, "❌ خطا: UUID کاربر برای یافتن در دیتابیس موجود نیست.", show_alert=True)
        return

    user_id_to_reset = db.get_user_id_by_uuid(info['uuid'])
    if not user_id_to_reset:
        panel_for_back = 'h' if bool(info.get('breakdown', {}).get('hiddify')) else 'm'
        back_cb = f"admin:us:{panel_for_back}:{identifier}{context_suffix}"
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb))
        _safe_edit(call.from_user.id, call.message.message_id, "❌ کاربر در دیتابیس ربات یافت نشد.", reply_markup=kb)
        return

    db.reset_user_birthday(user_id_to_reset)
    new_info = combined_handler.get_combined_user_info(identifier)
    
    panel_for_menu = 'hiddify' if bool(new_info.get('breakdown', {}).get('hiddify')) else 'marzban'
    text_to_show = fmt_admin_user_summary(new_info) + "\n\n*✅ تاریخ تولد کاربر با موفقیت ریست شد\\.*"
    back_callback = "admin:search_menu" if context == "search" else None
    
    kb = menu.admin_user_interactive_management(identifier, new_info['is_active'], panel_for_menu, back_callback=back_callback)
    _safe_edit(call.from_user.id, call.message.message_id, text_to_show, reply_markup=kb)


def handle_reset_usage_menu(call, params):
    identifier = params[0]
    info = combined_handler.get_combined_user_info(identifier)
    if not info:
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد.", show_alert=True)
        return

    _safe_edit(call.from_user.id, call.message.message_id, escape_markdown("⚙️ *مصرف کدام پنل صفر شود؟*"),
               reply_markup=menu.admin_reset_usage_selection_menu(identifier, base_callback="rsa"))


def handle_reset_usage_action(call, params):
    panel_to_reset, identifier = params[0], params[1]

    info = combined_handler.get_combined_user_info(identifier)
    if not info:
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد.", show_alert=True)
        return

    h_success, m_success = True, True
    uuid_id_in_db = db.get_uuid_id_by_uuid(info.get('uuid', ''))

    if panel_to_reset in ['hiddify', 'both'] and 'hiddify' in info.get('breakdown', {}):
        h_success = combined_handler.hiddify_handler.reset_user_usage(info['uuid'])

    if panel_to_reset in ['marzban', 'both'] and 'marzban' in info.get('breakdown', {}):
        m_success = combined_handler.marzban_handler.reset_user_usage(info['name'])

    if h_success and m_success:
        if uuid_id_in_db:
            db.delete_user_snapshots(uuid_id_in_db)
            db.add_usage_snapshot(uuid_id_in_db, 0.0, 0.0)
            db.delete_user_agents_by_uuid_id(uuid_id_in_db)

        new_info = combined_handler.get_combined_user_info(identifier)
        if new_info:
            user_telegram_id = db.get_user_id_by_uuid(new_info.get('uuid', ''))
            panel_name_map = {'hiddify': 'آلمان 🇩🇪', 'marzban': 'فرانسه 🇫🇷', 'both': 'هر دو پنل'}
            panel_name = panel_name_map.get(panel_to_reset, 'اکانت شما')
            notification_text = f"🔄 مصرف دیتای اکانت شما برای *{escape_markdown(panel_name)}* با موفقیت صفر شد\\."
            _notify_user(user_telegram_id, notification_text)

            text_to_show = fmt_admin_user_summary(new_info) + "\n\n*✅ مصرف کاربر با موفقیت صفر شد\\.*"
            original_panel = 'hiddify' if bool(new_info.get('breakdown', {}).get('hiddify')) else 'marzban'
            kb = menu.admin_user_interactive_management(identifier, new_info['is_active'], original_panel)
            _safe_edit(call.from_user.id, call.message.message_id, text_to_show, reply_markup=kb)
    else:
        bot.answer_callback_query(call.id, "❌ عملیات ناموفق بود.", show_alert=True)


def handle_delete_user_confirm(call, params):
    identifier = params[0]
    info = combined_handler.get_combined_user_info(identifier)
    if not info:
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد.", show_alert=True)
        return
    panel = 'hiddify' if bool(info.get('breakdown', {}).get('hiddify')) else 'marzban'

    text = f"⚠️ *آیا از حذف کامل کاربر با شناسه زیر اطمینان دارید؟*\n`{escape_markdown(identifier)}`"
    kb = menu.confirm_delete(identifier, panel)
    _safe_edit(call.from_user.id, call.message.message_id, text, reply_markup=kb)


def handle_delete_user_action(call, params):
    action, panel, identifier = params[0], params[1], params[2]

    uid, msg_id = call.from_user.id, call.message.message_id
    if action == "cancel":
        info = combined_handler.get_combined_user_info(identifier)
        if info:
            current_panel = 'hiddify' if bool(info.get('breakdown', {}).get('hiddify')) else 'marzban'
            kb = menu.admin_user_interactive_management(identifier, info['is_active'], current_panel)
            _safe_edit(uid, msg_id, fmt_admin_user_summary(info), reply_markup=kb)
        else:
            _safe_edit(uid, msg_id, "عملیات لغو شد و کاربر یافت نشد.", reply_markup=menu.admin_search_menu())
        return

    if action == "confirm":
        _safe_edit(uid, msg_id, "⏳ در حال حذف کامل کاربر...")
        success = combined_handler.delete_user_from_all_panels(identifier)
        if success:
            _safe_edit(uid, msg_id, "✅ کاربر با موفقیت از تمام پنل‌ها و ربات حذف شد.",
                       reply_markup=menu.admin_search_menu())
        else:
            _safe_edit(uid, msg_id, "❌ خطا در حذف کاربر.", reply_markup=menu.admin_search_menu())


def handle_global_search_convo(call, params):
    uid, msg_id = call.from_user.id, call.message.message_id
    prompt = "لطفاً نام یا UUID کاربر مورد نظر برای جستجو در هر دو پنل را وارد کنید:"
    admin_conversations[uid] = {'msg_id': msg_id}
    _safe_edit(uid, msg_id, escape_markdown(prompt), reply_markup=menu.admin_cancel_action("admin:search_menu"))
    bot.register_next_step_handler_by_chat_id(uid, _handle_global_search_response)


def _handle_global_search_response(message: types.Message):
    """
    Handles the admin's response to the global search prompt.
    Searches for users and displays results as a list of buttons if multiple are found.
    """
    uid, query = message.from_user.id, message.text.strip()
    try:
        bot.delete_message(uid, message.message_id)
    except apihelper.ApiTelegramException as e:
        if "message to delete not found" in e.description:
            logger.warning(f"Message {message.message_id} already deleted, proceeding with search.")
        else:
            raise e
    convo_data = admin_conversations.pop(uid, None)
    if not convo_data: return

    original_msg_id = convo_data['msg_id']
    _safe_edit(uid, original_msg_id, "در حال جستجو...", parse_mode=None)

    try:
        results = combined_handler.search_user(query)

        if not results:
            prompt = f"❌ کاربری با مشخصات `{escape_markdown(query)}` یافت نشد\\."
            kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت به جستجو", callback_data="admin:search_menu"))
            _safe_edit(uid, original_msg_id, prompt, reply_markup=kb)
            admin_conversations[uid] = {'msg_id': original_msg_id}
            bot.register_next_step_handler_by_chat_id(uid, _handle_global_search_response)
            return

        if len(results) == 1:
            user = results[0]
            identifier = user.get('uuid') or user.get('name')
            db_user = None
            if user.get('uuid'):
                user_telegram_id = db.get_user_id_by_uuid(user['uuid'])
                if user_telegram_id:
                    db_user = db.user(user_telegram_id)
            text = fmt_admin_user_summary(user, db_user)
            panel_type = 'hiddify' if any(p.get('type') == 'hiddify' for p in user.get('breakdown', {}).values()) else 'marzban'
            kb = menu.admin_user_interactive_management(identifier, user.get('is_active', False), panel_type, back_callback="admin:search_menu")
            _safe_edit(uid, original_msg_id, text, reply_markup=kb)
        else:
            kb = types.InlineKeyboardMarkup(row_width=1)
            prompt = "چندین کاربر یافت شد. لطفاً یکی را انتخاب کنید:"
            
            for user in results:
                identifier_for_callback = user.get('uuid') or user.get('name')
                status_emoji = "✅" if user.get('is_active') else "❌"
                button_text = f"{status_emoji} {user.get('name', 'کاربر ناشناس')}"
                
                panel_short = 'h' if any(p.get('type') == 'hiddify' for p in user.get('breakdown', {}).values()) else 'm'
                
                callback_data = f"admin:us:{panel_short}:{identifier_for_callback}:search"
                kb.add(types.InlineKeyboardButton(button_text, callback_data=callback_data))

            kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی جستجو", callback_data="admin:search_menu"))
            _safe_edit(uid, original_msg_id, prompt, reply_markup=kb, parse_mode=None)

    except Exception as e:
        logger.error(f"Global search failed for query '{query}': {e}", exc_info=True)
        _safe_edit(uid, original_msg_id, "❌ خطایی در هنگام جستجو رخ داد.", reply_markup=menu.admin_search_menu())

def handle_log_payment(call, params):
    """
    (نسخه کامل و اصلاح شده)
    پرداخت دستی را برای یک کاربر ثبت کرده و او را به منوی صحیح (جستجو یا مدیریت) بازمی‌گرداند.
    """
    identifier = params[0]
    context = "search" if len(params) > 1 and params[1] == 's' else None
    context_suffix = f":{context}" if context else ""
    
    uid, msg_id = call.from_user.id, call.message.message_id

    info = combined_handler.get_combined_user_info(identifier)
    if not info or not info.get('uuid'):
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد یا UUID ندارد.", show_alert=True)
        return

    uuid_id = db.get_uuid_id_by_uuid(info['uuid'])
    if not uuid_id:
        panel_for_back = 'h' if bool(info.get('breakdown', {}).get('hiddify')) else 'm'
        back_cb = f"admin:us:{panel_for_back}:{identifier}{context_suffix}"
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb))
        _safe_edit(uid, msg_id, "❌ کاربر در دیتابیس ربات یافت نشد.", reply_markup=kb)
        return

    previous_payments_count = len(db.get_user_payment_history(uuid_id))
    
    if db.add_payment_record(uuid_id):
        user_telegram_id = db.get_user_id_by_uuid(info['uuid'])
        user_name = escape_markdown(info.get('name', ''))
        
        action_text = "خریداری شد" if previous_payments_count == 0 else "تمدید شد"
        
        notification_text = (
            f"با تشکر از شما 🙏\n\n"
            f"✅ پرداخت شما برای اکانت *{user_name}* با موفقیت ثبت و سرویس شما *{action_text}*\\."
        )
        _notify_user(user_telegram_id, notification_text)

        if previous_payments_count == 0:
            _check_and_apply_referral_reward(user_telegram_id)

        panel_for_menu = 'hiddify' if bool(info.get('breakdown', {}).get('hiddify')) else 'marzban'
        back_callback = "admin:search_menu" if context == "search" else "admin:management_menu"
        text_to_show = fmt_admin_user_summary(info) + f"\n\n*✅ پرداخت با موفقیت ثبت شد\\.*"
        kb = menu.admin_user_interactive_management(identifier, info['is_active'], panel_for_menu,
                                                    back_callback=back_callback)
        _safe_edit(uid, msg_id, text_to_show, reply_markup=kb)
    else:
        bot.answer_callback_query(call.id, "❌ خطا در ثبت پرداخت.", show_alert=True)


def handle_payment_history(call, params):
    identifier = params[0]
    page = int(params[1])
    context = "search" if len(params) > 2 and params[2] == 'search' else None
    context_suffix = ":search" if context else ""
    
    uid, msg_id = call.from_user.id, call.message.message_id

    info = combined_handler.get_combined_user_info(identifier)
    if not info or not info.get('uuid'):
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد یا UUID ندارد.", show_alert=True)
        return

    all_payments = db.get_all_payments_with_user_info()
    user_payments = [p for p in all_payments if p.get('uuid') == info['uuid']]
    
    user_name_raw = info.get('name', 'کاربر ناشناس')
    text = fmt_user_payment_history(user_payments, user_name_raw, page)

    panel_short = 'h' if any(p.get('type') == 'hiddify' for p in info.get('breakdown', {}).values()) else 'm'
    base_cb = f"admin:phist:{identifier}"
    back_cb_pagination = f"admin:us:{panel_short}:{identifier}{context_suffix}"
    
    kb = menu.create_pagination_menu(base_cb, page, len(user_payments), back_cb_pagination, context=context)
    _safe_edit(uid, msg_id, text, reply_markup=kb)


def handle_ask_for_note(call, params):
    identifier = params[0]
    context = "search" if len(params) > 1 and params[1] == 'search' else None
    panel_short = params[2] if len(params) > 2 else 'h'
    panel = 'marzban' if panel_short == 'm' else 'hiddify'
    context_suffix = f":{context}" if context else ""
    
    uid, msg_id = call.from_user.id, call.message.message_id

    info = combined_handler.get_combined_user_info(identifier)
    if not info or not info.get('uuid'):
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد یا UUID ندارد.", show_alert=True)
        return

    user_telegram_id = db.get_user_id_by_uuid(info['uuid'])
    if not user_telegram_id:
        panel_for_back = 'h' if bool(info.get('breakdown', {}).get('hiddify')) else 'm'
        back_cb = f"admin:us:{panel_for_back}:{identifier}{context_suffix}"
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb))
        _safe_edit(uid, msg_id, "❌ کاربر در دیتابیس ربات یافت نشد.", reply_markup=kb)
        return

    db_user = db.user(user_telegram_id)
    current_note = db_user.get('admin_note') if db_user else None

    prompt = "لطفاً یادداشت جدید را برای این کاربر وارد کنید\\.\n\n"
    if current_note:
        prompt += f"*یادداشت فعلی:*\n`{escape_markdown(current_note)}`\n\n"
    prompt += "برای حذف یادداشت فعلی، کلمه `حذف` را ارسال کنید\\."

    admin_conversations[uid] = {
        'action_type': 'add_note',
        'identifier': identifier,
        'panel': panel,
        'user_telegram_id': user_telegram_id,
        'msg_id': msg_id,
        'context': context
    }
    
    back_cb = f"admin:us:{panel_short}:{identifier}{context_suffix}"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_cancel_action(back_callback=back_cb))
    bot.register_next_step_handler_by_chat_id(uid, _save_user_note)


def _save_user_note(message: types.Message):
    uid, text = message.from_user.id, message.text.strip()
    bot.delete_message(uid, message.message_id)

    if uid not in admin_conversations: return

    convo = admin_conversations.pop(uid, {})
    if convo.get('action_type') != 'add_note': return

    msg_id = convo['msg_id']
    user_telegram_id = convo['user_telegram_id']
    identifier = convo['identifier']
    panel = convo['panel']
    context = convo.get('context')

    note_to_save = text
    if text.lower() in ['حذف', 'delete', 'remove', 'del']:
        note_to_save = None

    db.update_user_note(user_telegram_id, note_to_save)

    info = combined_handler.get_combined_user_info(identifier)
    if info:
        db_user = db.user(user_telegram_id)
        text_to_show = fmt_admin_user_summary(info, db_user)
        
        back_callback = "admin:search_menu" if context == "search" else None
        kb = menu.admin_user_interactive_management(
            identifier, 
            info.get('is_active', False), 
            panel,
            back_callback=back_callback
        )
        _safe_edit(uid, msg_id, text_to_show, reply_markup=kb)


def _notify_user(user_id: Optional[int], message: str) -> bool:
    """Notifies a user and returns True on success, False on failure."""
    if not user_id:
        return False
    try:
        bot.send_message(user_id, message, parse_mode="MarkdownV2")
        logger.info(f"Sent notification to user {user_id}")
        return True
    except Exception as e:
        logger.warning(f"Failed to send notification to user {user_id}: {e}")
        return False


def handle_search_by_telegram_id_convo(call, params):
    uid, msg_id = call.from_user.id, call.message.message_id
    prompt = escape_markdown("لطفاً شناسه عددی (ID) کاربر تلگرام مورد نظر را وارد کنید:")

    admin_conversations[uid] = {'action_type': 'search_by_tid', 'msg_id': msg_id}

    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_cancel_action("admin:search_menu"))
    bot.register_next_step_handler_by_chat_id(uid, _find_user_by_telegram_id)


def _find_user_by_telegram_id(message: types.Message):
    """
    کاربر را بر اساس شناسه تلگرام جستجو کرده و در صورت یافتن، اطلاعات او را نمایش می‌دهد.
    (نسخه نهایی و اصلاح شده با مدیریت خطا)
    """
    admin_id, text = message.from_user.id, message.text.strip()

    try:
        bot.delete_message(admin_id, message.message_id)
    except apihelper.ApiTelegramException as e:
        if "message to delete not found" in str(e):
            logger.warning(f"Message {message.message_id} already deleted, proceeding with search.")
        else:
            raise e

    if admin_id not in admin_conversations:
        return

    convo = admin_conversations.pop(admin_id, {})
    msg_id = convo.get('msg_id')

    try:
        target_user_id = int(text)
        _safe_edit(admin_id, msg_id, escape_markdown("⏳ در حال جستجو..."))

        user_uuids = db.uuids(target_user_id)
        if not user_uuids:
            kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت به منوی جستجو", callback_data="admin:search_menu"))
            _safe_edit(admin_id, msg_id, escape_markdown(f"❌ هیچ اکانتی برای کاربر با شناسه {target_user_id} یافت نشد."), reply_markup=kb)
            admin_conversations[admin_id] = {'action_type': 'search_by_tid', 'msg_id': msg_id}
            bot.register_next_step_handler_by_chat_id(admin_id, _find_user_by_telegram_id)
            return

        if len(user_uuids) == 1:
            uuid_str = user_uuids[0]['uuid']
            info = combined_handler.get_combined_user_info(uuid_str)
            if info:
                db_user = db.user(target_user_id)
                panel = 'hiddify' if any(p.get('type') == 'hiddify' for p in info.get('breakdown', {}).values()) else 'marzban'
                text = fmt_admin_user_summary(info, db_user)
                kb = menu.admin_user_interactive_management(uuid_str, info.get('is_active', False), panel, back_callback="admin:search_menu")
                _safe_edit(admin_id, msg_id, text, reply_markup=kb)
            else:
                _safe_edit(admin_id, msg_id, escape_markdown("❌ خطا در دریافت اطلاعات از پنل."), reply_markup=menu.admin_search_menu())
            return

        kb = types.InlineKeyboardMarkup()
        db_user = db.user(target_user_id)
        first_name = escape_markdown(db_user.get('first_name', f"کاربر {target_user_id}"))

        for row in user_uuids:
            button_text = f"👤 {row.get('name', 'اکانت ناشناس')}"
            info = combined_handler.get_combined_user_info(row['uuid'])
            if info:
                panel = 'hiddify' if any(p.get('type') == 'hiddify' for p in info.get('breakdown', {}).values()) else 'marzban'
                panel_short = 'h' if panel == 'hiddify' else 'm'
                kb.add(types.InlineKeyboardButton(button_text, callback_data=f"admin:us:{panel_short}:{row['uuid']}:search"))

        kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی جستجو", callback_data="admin:search_menu"))
        
        prompt_template = f"چندین اکانت برای کاربر *{first_name}* یافت شد. لطفاً یکی را انتخاب کنید:"
        prompt = escape_markdown(prompt_template).replace(f'*{first_name}*', f'*{first_name}*') # برای حفظ استایل بولد
        _safe_edit(admin_id, msg_id, prompt, reply_markup=kb)

    except ValueError:
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت به جستجو", callback_data="admin:search_menu"))
        _safe_edit(admin_id, msg_id, escape_markdown("❌ شناسه وارد شده نامعتبر است. لطفاً یک عدد وارد کنید."), reply_markup=kb)
        admin_conversations[admin_id] = {'action_type': 'search_by_tid', 'msg_id': msg_id}
        bot.register_next_step_handler_by_chat_id(admin_id, _find_user_by_telegram_id)


def handle_select_panel_for_edit(call, params):
    edit_type, identifier = params[0], params[1]
    context = "search" if len(params) > 2 and params[2] == 'search' else None
    context_suffix = f":{context}" if context else ""

    edit_type_map = {"agb": "افزودن حجم", "ady": "افزودن روز"}
    edit_type_name = edit_type_map.get(edit_type, edit_type)

    prompt = f"⚙️ لطفاً پنلی که می‌خواهید «{edit_type_name}» به آن اضافه شود را انتخاب کنید:"
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    
    btn_h = types.InlineKeyboardButton("آلمان 🇩🇪", callback_data=f"admin:ae:{edit_type}:hiddify:{identifier}{context_suffix}")
    btn_m = types.InlineKeyboardButton("فرانسه 🇫🇷", callback_data=f"admin:ae:{edit_type}:marzban:{identifier}{context_suffix}")
    
    kb.add(btn_h, btn_m)
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"admin:edt:{identifier}{context_suffix}"))
    
    _safe_edit(call.from_user.id, call.message.message_id, escape_markdown(prompt), reply_markup=kb)

def handle_purge_user_convo(call, params):
    uid, msg_id = call.from_user.id, call.message.message_id
    prompt = escape_markdown("⚠️ توجه: این عمل کاربر را به طور کامل از دیتابیس ربات حذف می‌کند و غیرقابل بازگشت است.\n\nلطفاً شناسه عددی (ID) کاربر تلگرام برای پاکسازی کامل را وارد کنید:")

    admin_conversations[uid] = {'action_type': 'purge_user', 'msg_id': msg_id}

    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_cancel_action("admin:search_menu"))
    bot.register_next_step_handler_by_chat_id(uid, _confirm_and_purge_user)

def _confirm_and_purge_user(message: types.Message):
    admin_id, text = message.from_user.id, message.text.strip()
    
    try:
        bot.delete_message(admin_id, message.message_id)
    except apihelper.ApiTelegramException as e:
        if "message to delete not found" not in str(e):
            logger.warning(f"Could not delete admin message {message.message_id}: {e}")

    if admin_id not in admin_conversations: return

    convo = admin_conversations.pop(admin_id, {})
    msg_id = convo['msg_id']

    try:
        target_user_id = int(text)
    except ValueError:
        _safe_edit(admin_id, msg_id, escape_markdown("❌ شناسه وارد شده نامعتبر است. عملیات لغو شد."), reply_markup=menu.admin_search_menu())
        return

    _safe_edit(admin_id, msg_id, escape_markdown("⏳ در حال پاکسازی کامل کاربر..."))

    if db.purge_user_by_telegram_id(target_user_id):
        success_msg = f"✅ کاربر با شناسه {target_user_id} به طور کامل از دیتابیس ربات پاکسازی شد. اکنون می‌تواند دوباره ثبت نام کند."
        _safe_edit(admin_id, msg_id, escape_markdown(success_msg), reply_markup=menu.admin_search_menu())
    else:
        error_msg = f"❌ کاربری با شناسه {target_user_id} در جدول اصلی کاربران یافت نشد."
        _safe_edit(admin_id, msg_id, escape_markdown(error_msg), reply_markup=menu.admin_search_menu())


def handle_delete_devices_confirm(call, params):
    """
    Asks for confirmation before deleting devices and checks if there are any.
    """
    identifier = params[0]
    context = "search" if len(params) > 1 and params[1] == 'search' else None
    uid, msg_id = call.from_user.id, call.message.message_id

    info = combined_handler.get_combined_user_info(identifier)
    if not info or not info.get('uuid'):
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد یا UUID ندارد.", show_alert=True)
        return

    uuid_id_in_db = db.get_uuid_id_by_uuid(info['uuid'])
    if not uuid_id_in_db:
        bot.answer_callback_query(call.id, "❌ کاربر در دیتابیس ربات یافت نشد.", show_alert=True)
        return

    device_count = db.count_user_agents(uuid_id_in_db)
    
    panel_short_for_back = 'h' if any(p.get('type') == 'hiddify' for p in info.get('breakdown', {}).values()) else 'm'
    context_suffix = f":{context}" if context else ""
    back_callback = f"admin:us:{panel_short_for_back}:{identifier}{context_suffix}"

    if device_count == 0:
        prompt = "ℹ️ هیچ دستگاهی برای این کاربر ثبت نشده است."
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=back_callback))
        _safe_edit(uid, msg_id, escape_markdown(prompt), reply_markup=kb)
        return

    prompt = f"⚠️ آیا از حذف *{device_count}* دستگاه ثبت شده برای کاربر «{escape_markdown(info.get('name', ''))}» اطمینان دارید؟"
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    confirm_callback = f"admin:del_devs_exec:{identifier}{context_suffix}"
    kb.add(
        types.InlineKeyboardButton("✅ بله، حذف کن", callback_data=confirm_callback),
        types.InlineKeyboardButton("❌ انصراف", callback_data=back_callback)
    )
    _safe_edit(uid, msg_id, prompt, reply_markup=kb)


def handle_delete_devices_action(call, params):
    """Deletes all recorded devices for a user and confirms."""
    identifier = params[0]
    context = "search" if len(params) > 1 and params[1] == 'search' else None
    uid, msg_id = call.from_user.id, call.message.message_id

    info = combined_handler.get_combined_user_info(identifier)
    if not info or not info.get('uuid'):
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد یا UUID ندارد.", show_alert=True)
        return

    uuid_id_in_db = db.get_uuid_id_by_uuid(info['uuid'])
    if not uuid_id_in_db:
        bot.answer_callback_query(call.id, "❌ کاربر در دیتابیس ربات یافت نشد.", show_alert=True)
        return

    deleted_count = db.delete_user_agents_by_uuid_id(uuid_id_in_db)
    bot.answer_callback_query(call.id, f"✅ {deleted_count} دستگاه با موفقیت حذف شد.", show_alert=True)
    panel_short = 'h' if any(p.get('type') == 'hiddify' for p in info.get('breakdown', {}).values()) else 'm'
    
    new_params_for_summary = [panel_short, identifier]
    if context:
        new_params_for_summary.append(context)
        
    handle_show_user_summary(call, new_params_for_summary)

def handle_reset_transfer_cooldown(call, params):
    """محدودیت زمانی انتقال ترافیک را برای یک کاربر ریست می‌کند."""
    identifier = params[0]
    context = "search" if len(params) > 1 and params[1] == 'search' else None
    
    info = combined_handler.get_combined_user_info(identifier)
    if not info or not info.get('uuid'):
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد یا UUID ندارد.", show_alert=True)
        return

    uuid_id_to_reset = db.get_uuid_id_by_uuid(info['uuid'])
    if not uuid_id_to_reset:
        bot.answer_callback_query(call.id, "❌ کاربر در دیتابیس ربات برای ریست کردن یافت نشد.", show_alert=True)
        return
        
    deleted_count = db.delete_transfer_history(uuid_id_to_reset)
    
    if deleted_count > 0:
        feedback_text = f"\n\n*✅ محدودیت انتقال برای این کاربر با موفقیت ریست شد\\.*"
    else:
        feedback_text = f"\n\n*ℹ️ این کاربر تاریخچه انتقالی برای ریست کردن نداشت\\.*"
    
    db_user = db.get_bot_user_by_uuid(info['uuid'])
    text_to_show = fmt_admin_user_summary(info, db_user) + feedback_text
    
    panel_short = 'h' if any(p.get('type') == 'hiddify' for p in info.get('breakdown', {}).values()) else 'm'
    back_callback = "admin:search_menu" if context == "search" else "admin:management_menu"
    kb = menu.admin_user_interactive_management(identifier, info.get('is_active', False), panel_short, back_callback=back_callback)
    _safe_edit(call.from_user.id, call.message.message_id, text_to_show, reply_markup=kb)
    
    bot.answer_callback_query(call.id, "✅ عملیات انجام شد.")

def handle_system_tools_menu(call, params):
    """(نسخه اصلاح شده) منوی جدید ابزارهای سیستمی را با استایل صحیح نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    prompt = (
        f"🛠️ *{escape_markdown('ابزارهای سیستمی')}*\n\n"
        f"{escape_markdown('لطفاً دستور مورد نظر خود را انتخاب کنید. در استفاده از این ابزارها دقت کنید.')}"
    )
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_system_tools_menu(), parse_mode="MarkdownV2")

def handle_reset_all_daily_usage_confirm(call, params):
    """(نسخه اصلاح شده) از ادمین برای صفر کردن مصرف روزانه همه کاربران تاییدیه می‌گیرد."""
    prompt = (
        f"⚠️ *{escape_markdown('توجه بسیار مهم!')}*\n\n"
        f"{escape_markdown('آیا مطمئن هستید که می‌خواهید آمار مصرف')} *{escape_markdown('امروز')}* {escape_markdown('برای')} "
        f"*{escape_markdown('تمام کاربران')}* {escape_markdown('را صفر کنید؟ این عمل غیرقابل بازگشت است.')}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ بله، ریست کن", callback_data="admin:reset_all_daily_usage_exec"),
        types.InlineKeyboardButton("❌ انصراف", callback_data="admin:system_tools_menu")   
    )
    _safe_edit(call.from_user.id, call.message.message_id, prompt, reply_markup=kb, parse_mode="MarkdownV2")


def handle_reset_all_daily_usage_action(call, params):
    """(نسخه نهایی) مصرف روزانه همه کاربران را صفر کرده و یک نقطه شروع جدید ثبت می‌کند."""
    uid, msg_id = call.from_user.id, call.message.message_id
    _safe_edit(uid, msg_id, escape_markdown("⏳ در حال حذف اسنپ‌شات‌های امروز..."), reply_markup=None)

    deleted_count = db.delete_all_daily_snapshots()

    _safe_edit(uid, msg_id, escape_markdown(f"✅ {deleted_count} رکورد حذف شد. حالا در حال ثبت نقطه شروع جدید..."), reply_markup=None)

    try:
        # این بخش، همان پروسه نیمه‌شب را به صورت دستی اجرا می‌کند
        all_users_info = combined_handler.get_all_users_combined()
        user_info_map = {user['uuid']: user for user in all_users_info if user.get('uuid')}
        # این تابع در دیتابیس شما به درستی از user_uuids استفاده می‌کند
        all_uuids_from_db = list(db.all_active_uuids())

        reset_count = 0
        for u_row in all_uuids_from_db:
            uuid_str = u_row['uuid']
            if uuid_str in user_info_map:
                info = user_info_map[uuid_str]
                breakdown = info.get('breakdown', {})
                h_usage = sum(p.get('data', {}).get('current_usage_GB', 0.0) for p in breakdown.values() if p.get('type') == 'hiddify')
                m_usage = sum(p.get('data', {}).get('current_usage_GB', 0.0) for p in breakdown.values() if p.get('type') == 'marzban')
                # u_row['id'] در اینجا به درستی به id جدول user_uuids اشاره دارد
                db.add_usage_snapshot(u_row['id'], h_usage, m_usage)
                reset_count += 1

        success_msg = (
            f"✅ *{escape_markdown('عملیات با موفقیت کامل شد.')}*\n\n"
            f"{escape_markdown('مصرف روزانه برای')} `{reset_count}` {escape_markdown('کاربر فعال با موفقیت ریست شد.')}"
        )
        _safe_edit(uid, msg_id, success_msg, reply_markup=menu.admin_system_tools_menu(), parse_mode="MarkdownV2")

    except Exception as e:
        logger.error(f"Error while creating new baseline snapshot after reset: {e}", exc_info=True)
        error_msg = escape_markdown("❌ خطا در ثبت نقطه شروع جدید. لطفاً لاگ‌ها را بررسی کنید.")
        _safe_edit(uid, msg_id, error_msg, reply_markup=menu.admin_system_tools_menu(), parse_mode="MarkdownV2")


def handle_force_snapshot(call, params):
    """
    به صورت دستی فرآیند ذخیره آمار مصرف (snapshot) را برای تمام کاربران فعال اجرا می‌کند.
    """
    uid, msg_id = call.from_user.id, call.message.message_id
    _safe_edit(uid, msg_id, escape_markdown("⏳ در حال دریافت اطلاعات از پنل‌ها و به‌روزرسانی آمار مصرف... لطفاً چند لحظه صبر کنید."), reply_markup=None)

    try:
        all_users_info = combined_handler.get_all_users_combined()
        if not all_users_info:
            bot.answer_callback_query(call.id, "هیچ کاربری در پنل‌ها یافت نشد.", show_alert=True)
            _safe_edit(uid, msg_id, escape_markdown("هیچ کاربری برای به‌روزرسانی یافت نشد."), reply_markup=menu.admin_system_tools_menu())
            return
            
        user_info_map = {user['uuid']: user for user in all_users_info if user.get('uuid')}
        all_uuids_from_db = list(db.all_active_uuids())
        
        updated_count = 0
        for u_row in all_uuids_from_db:
            try:
                uuid_str = u_row['uuid']
                if uuid_str in user_info_map:
                    info = user_info_map[uuid_str]
                    breakdown = info.get('breakdown', {})
                    h_usage, m_usage = 0.0, 0.0

                    for panel_details in breakdown.values():
                        panel_type = panel_details.get('type')
                        panel_data = panel_details.get('data', {})
                        if panel_type == 'hiddify':
                            h_usage += panel_data.get('current_usage_GB', 0.0)
                        elif panel_type == 'marzban':
                            m_usage += panel_data.get('current_usage_GB', 0.0)
                    
                    db.add_usage_snapshot(u_row['id'], h_usage, m_usage)
                    updated_count += 1
            except Exception as e:
                logger.error(f"ADMIN_FORCE_SNAPSHOT: Failed to process for uuid_id {u_row['id']}: {e}")

        success_msg = f"✅ عملیات با موفقیت انجام شد.\n\nآمار مصرف برای {updated_count} کاربر فعال به‌روزرسانی گردید."
        bot.answer_callback_query(call.id, "✅ آمار با موفقیت به‌روز شد.", show_alert=True)
        _safe_edit(uid, msg_id, escape_markdown(success_msg), reply_markup=menu.admin_system_tools_menu())

    except Exception as e:
        logger.error(f"Error in handle_force_snapshot: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "❌ خطایی در هنگام اجرای عملیات رخ داد.", show_alert=True)
        _safe_edit(uid, msg_id, escape_markdown("❌ خطایی در ارتباط با پنل‌ها یا دیتابیس رخ داد."), reply_markup=menu.admin_system_tools_menu())

def handle_reset_all_points_confirm(call, params):
    """از ادمین برای ریست کردن تمام امتیازها و دستاوردها تاییدیه می‌گیرد."""
    prompt = (
        f"⚠️ *{escape_markdown('توجه بسیار مهم!')}*\n\n"
        f"{escape_markdown('آیا مطمئن هستید که می‌خواهید امتیازات و دستاوردهای')} "
        f"*{escape_markdown('تمام کاربران')}* {escape_markdown('را صفر کنید؟')}\n\n"
        f"{escape_markdown('این عمل غیرقابل بازگشت است و کاربران باید دستاوردها را دوباره کسب کنند.')}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ بله، ریست کن", callback_data="admin:reset_all_points_exec"),
        types.InlineKeyboardButton("❌ انصراف", callback_data="admin:system_tools_menu")
    )
    _safe_edit(call.from_user.id, call.message.message_id, prompt, reply_markup=kb, parse_mode="MarkdownV2")

def handle_reset_all_points_execute(call, params):
    """تمام امتیازات و دستاوردهای کاربران را ریست می‌کند."""
    uid, msg_id = call.from_user.id, call.message.message_id
    _safe_edit(uid, msg_id, escape_markdown("⏳ در حال ریست کردن امتیازات و دستاوردها..."), reply_markup=None)

    try:
        deleted_achievements = db.delete_all_achievements()
        reset_users_count = db.reset_all_achievement_points()

        success_msg = (
            f"✅ *{escape_markdown('عملیات با موفقیت کامل شد.')}*\n\n"
            f"{escape_markdown(f'امتیازات برای')} `{reset_users_count}` {escape_markdown('کاربر صفر شد.')}\n"
            f"{escape_markdown(f'تعداد')} `{deleted_achievements}` {escape_markdown('دستاورد حذف شد.')}"
        )
        _safe_edit(uid, msg_id, success_msg, reply_markup=menu.admin_system_tools_menu(), parse_mode="MarkdownV2")

    except Exception as e:
        logger.error(f"Error while resetting all points and achievements: {e}", exc_info=True)
        error_msg = escape_markdown("❌ خطا در هنگام ریست کردن. لطفاً لاگ‌ها را بررسی کنید.")
        _safe_edit(uid, msg_id, error_msg, reply_markup=menu.admin_system_tools_menu(), parse_mode="MarkdownV2")

def handle_delete_all_devices_confirm(call, params):
    """از ادمین برای حذف تمام دستگاه‌های ثبت‌شده تاییدیه می‌گیرد."""
    prompt = (
        f"⚠️ *{escape_markdown('توجه بسیار مهم!')}*\n\n"
        f"{escape_markdown('آیا مطمئن هستید که می‌خواهید تاریخچه دستگاه‌های متصل')} "
        f"*{escape_markdown('تمام کاربران')}* {escape_markdown('را حذف کنید؟')}\n\n"
        f"{escape_markdown('این عمل غیرقابل بازگشت است و پس از آن، دستگاه‌ها با اولین اتصال مجدد ثبت خواهند شد.')}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ بله، حذف کن", callback_data="admin:delete_all_devices_exec"),
        types.InlineKeyboardButton("❌ انصراف", callback_data="admin:system_tools_menu")
    )
    _safe_edit(call.from_user.id, call.message.message_id, prompt, reply_markup=kb, parse_mode="MarkdownV2")

def handle_delete_all_devices_execute(call, params):
    """تمام دستگاه‌های ثبت‌شده کاربران را حذف می‌کند."""
    uid, msg_id = call.from_user.id, call.message.message_id
    _safe_edit(uid, msg_id, escape_markdown("⏳ در حال حذف تاریخچه تمام دستگاه‌ها..."), reply_markup=None)

    try:
        deleted_count = db.delete_all_user_agents()
        success_msg = (
            f"✅ *{escape_markdown('عملیات با موفقیت کامل شد.')}*\n\n"
            f"{escape_markdown(f'تعداد')} `{deleted_count}` {escape_markdown('رکورد دستگاه حذف شد.')}"
        )
        _safe_edit(uid, msg_id, success_msg, reply_markup=menu.admin_system_tools_menu(), parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Error while deleting all user agents: {e}", exc_info=True)
        error_msg = escape_markdown("❌ خطا در هنگام حذف دستگاه‌ها. لطفاً لاگ‌ها را بررسی کنید.")
        _safe_edit(uid, msg_id, error_msg, reply_markup=menu.admin_system_tools_menu(), parse_mode="MarkdownV2")

def handle_reset_all_balances_confirm(call, params):
    """از ادمین برای ریست کردن موجودی تمام کاربران تاییدیه می‌گیرد."""
    prompt = (
        f"⚠️ *{escape_markdown('توجه بسیار بسیار مهم!')}*\n\n"
        f"{escape_markdown('آیا مطمئن هستید که می‌خواهید موجودی کیف پول و تاریخچه تراکنش‌های')} "
        f"*{escape_markdown('تمام کاربران')}* {escape_markdown('را برای همیشه پاک کنید؟')}\n\n"
        f"*{escape_markdown('این عمل به هیچ عنوان قابل بازگشت نیست.')}*"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ بله، ریست کن", callback_data="admin:reset_all_balances_exec"),
        types.InlineKeyboardButton("❌ انصراف", callback_data="admin:system_tools_menu")
    )
    _safe_edit(call.from_user.id, call.message.message_id, prompt, reply_markup=kb, parse_mode="MarkdownV2")

def handle_reset_all_balances_execute(call, params):
    """موجودی تمام کاربران را ریست می‌کند."""
    uid, msg_id = call.from_user.id, call.message.message_id
    _safe_edit(uid, msg_id, escape_markdown("⏳ در حال ریست کردن موجودی تمام کاربران..."), reply_markup=None)

    try:
        reset_count = db.reset_all_wallet_balances()
        success_msg = (
            f"✅ *{escape_markdown('عملیات با موفقیت کامل شد.')}*\n\n"
            f"{escape_markdown('موجودی کیف پول برای')} `{reset_count}` {escape_markdown('کاربر صفر شد و تمام تاریخچه تراکنش‌ها پاک گردید.')}"
        )
        _safe_edit(uid, msg_id, success_msg, reply_markup=menu.admin_system_tools_menu(), parse_mode="MarkdownV2")

    except Exception as e:
        logger.error(f"Error while resetting all wallet balances: {e}", exc_info=True)
        error_msg = escape_markdown("❌ خطا در هنگام ریست کردن موجودی‌ها. لطفاً لاگ‌ها را بررسی کنید.")
        _safe_edit(uid, msg_id, error_msg, reply_markup=menu.admin_system_tools_menu(), parse_mode="MarkdownV2")

def handle_award_badge(call, params):
    """
    Awards a specific badge to a user, initiated by an admin.
    """
    badge_short_code, identifier = params[0], params[1]
    context = "search" if len(params) > 2 and params[2] == 'search' else None
    
    badge_map = {
        'mp': 'media_partner',
        'sc': 'support_contributor'
    }
    badge_code = badge_map.get(badge_short_code)

    if not badge_code:
        bot.answer_callback_query(call.id, "❌ کد نشان نامعتبر است.", show_alert=True)
        return
    
    info = combined_handler.get_combined_user_info(identifier)
    if not info or not info.get('uuid'):
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد یا UUID ندارد.", show_alert=True)
        return

    user_telegram_id = db.get_user_id_by_uuid(info['uuid'])
    if not user_telegram_id:
        bot.answer_callback_query(call.id, "❌ کاربر در دیتابیس ربات یافت نشد.", show_alert=True)
        return

    if db.add_achievement(user_telegram_id, badge_code):
        notify_user_achievement(bot, user_telegram_id, badge_code)
        bot.answer_callback_query(call.id, f"✅ نشان «{ACHIEVEMENTS.get(badge_code, {}).get('name', '')}» با موفقیت اهدا شد.", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "ℹ️ این کاربر قبلاً این نشان را دریافت کرده است.", show_alert=True)

def handle_award_badge_menu(call: types.CallbackQuery, params: list):
    """منوی اهدای دستی نشان‌ها را نمایش می‌دهد."""
    identifier = params[0]
    context_suffix = f":{params[1]}" if len(params) > 1 else ""
    uid, msg_id = call.from_user.id, call.message.message_id
    
    prompt = "کدام نشان را می‌خواهید به این کاربر اهدا کنید؟"
    kb = menu.admin_award_badge_menu(identifier, context_suffix)
    _safe_edit(uid, msg_id, prompt, reply_markup=kb, parse_mode=None)

def handle_achievement_request_callback(call: types.CallbackQuery, params: list):
    """پاسخ ادمین به درخواست نشان را پردازش می‌کند."""
    action = call.data.split(':')[1]
    decision = 'approve' if 'approve' in action else 'reject'
    
    if not params:
        bot.answer_callback_query(call.id, "خطا: شناسه درخواست یافت نشد.", show_alert=True)
        return
        
    request_id_str = params[0]
    request_id = int(request_id_str)
    admin_id = call.from_user.id

    request_data = db.get_achievement_request(request_id)
    if not request_data or request_data['status'] != 'pending':
        bot.answer_callback_query(call.id, "این درخواست قبلاً پردازش شده است.", show_alert=True)
        bot.edit_message_reply_markup(chat_id=admin_id, message_id=call.message.message_id, reply_markup=None)
        return

    user_id = request_data['user_id']
    badge_code = request_data['badge_code']

    all_users = db.get_all_bot_users()
    user_info = next((user for user in all_users if user['user_id'] == user_id), None)

    if not user_info:
        bot.answer_callback_query(call.id, "خطا: کاربر درخواست دهنده یافت نشد.", show_alert=True)
        return
        
    user_name = escape_markdown(user_info.get('first_name', str(user_id)))
    badge_name = escape_markdown(ACHIEVEMENTS.get(badge_code, {}).get('name', badge_code))
    
    base_admin_message = (
        f"🏅 *درخواست نشان جدید*\n\n"
        f"کاربر *{user_name}* \\(`{user_id}`\\) درخواست دریافت نشان «*{badge_name}*» را دارد\\."
    )

    if decision == 'approve':
        db.update_achievement_request_status(request_id, 'approved', admin_id)
        if db.add_achievement(user_id, badge_code):
            badge_info = ACHIEVEMENTS.get(badge_code, {})
            
            creative_messages = {
                "swimming_champion": "🌊 بهت افتخار می‌کنیم قهرمان\\! سرعت و استقامتت در آب الهام‌بخش است\\. نشان «قهرمان شنا» به پاس تلاشت به تو اهدا شد\\.",
                "bodybuilder": "💪 تلاش و انضباط تو در باشگاه ستودنی است\\! نشان «بدن‌ساز» به پروفایل افتخاراتت اضافه شد\\. به ساختن ادامه بده\\!",
                "water_athlete": "🤽‍♂️ انرژی بی‌پایانت در آب، تحسین‌برانگیزه\\! نشان «ورزشکار آب‌ها» برای تو\\. همیشه پرتوان باشی\\!",
                "aerialist": "🤸‍♀️ هنر و قدرت تو در آسمان، نفس‌گیر است\\! نشان «ورزشکار هوایی» به پاس استعدادت به تو تعلق گرفت\\."
            }
            default_message = "🎉 تبریک\\! درخواست شما برای نشان «*{badge_name}*» تایید شد\\."
            
            message_template = creative_messages.get(badge_code, default_message)
            approval_message = (
                f"{badge_info.get('icon', '🏅')} *{escape_markdown('یک دستاورد جدید!')}*\n\n"
                f"{message_template.format(badge_name=escape_markdown(badge_info.get('name', '')))}\n\n"
                f"*{badge_info.get('points', 0)} امتیاز* به حساب شما اضافه شد\\. به افتخارآفرینی ادامه بده\\!"
            )
            bot.send_message(user_id, approval_message, parse_mode="MarkdownV2")
        
        bot.edit_message_text(
            text=base_admin_message + "\n\n✅ *توسط شما تایید شد*",
            chat_id=admin_id, message_id=call.message.message_id,
            reply_markup=None, parse_mode="MarkdownV2"
        )
        bot.answer_callback_query(call.id, "درخواست تایید شد.")
    else:
        db.update_achievement_request_status(request_id, 'rejected', admin_id)
        bot.edit_message_text(
            text=base_admin_message + "\n\n❌ *توسط شما رد شد*",
            chat_id=admin_id, message_id=call.message.message_id,
            reply_markup=None, parse_mode="MarkdownV2"
        )
        bot.answer_callback_query(call.id, "درخواست رد شد.")
        badge_name = ACHIEVEMENTS.get(badge_code, {}).get('name', 'درخواستی')
        rejection_message = f"با سلام، درخواست شما برای نشان «{badge_name}» بررسی شد اما در حال حاضر مورد تایید قرار نگرفت. لطفاً در صورت تمایل، بعداً دوباره تلاش کنید یا با پشتیبانی در تماس باشید."
        bot.send_message(user_id, rejection_message)

def handle_reset_payment_history_confirm(call, params):
    """(نسخه اصلاح شده) از ادمین برای حذف تاریخچه پرداخت تاییدیه می‌گیرد."""
    identifier = params[0]
    context = "search" if len(params) > 1 and params[1] == 'search' else None
    uid, msg_id = call.from_user.id, call.message.message_id

    info = combined_handler.get_combined_user_info(identifier)
    if not info or not info.get('uuid'):
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد یا UUID ندارد.", show_alert=True)
        return

    uuid_id_in_db = db.get_uuid_id_by_uuid(info['uuid'])
    if not uuid_id_in_db:
        bot.answer_callback_query(call.id, "❌ کاربر در دیتابیس ربات یافت نشد.", show_alert=True)
        return

    payment_count = len(db.get_user_payment_history(uuid_id_in_db))
    panel_short_for_back = 'h' if any(p.get('type') == 'hiddify' for p in info.get('breakdown', {}).values()) else 'm'
    context_suffix = f":{context}" if context else ""
    back_callback = f"admin:us:{panel_short_for_back}:{identifier}{context_suffix}"

    if payment_count == 0:
        prompt = "ℹ️ این کاربر هیچ سابقه پرداختی برای ریست کردن ندارد."
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=back_callback))
        _safe_edit(uid, msg_id, escape_markdown(prompt), reply_markup=kb)
        return

    prompt = (
        f"⚠️ آیا از حذف کامل تاریخچه پرداخت \\({payment_count} مورد\\) برای کاربر «{escape_markdown(info.get('name', ''))}» "
        f"اطمینان دارید؟ این عمل شمارنده تمدید را صفر می‌کند و غیرقابل بازگشت است\\."
    )
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    confirm_callback = f"admin:do_reset_phist:{identifier}{context_suffix}"
    kb.add(
        types.InlineKeyboardButton("✅ بله، ریست کن", callback_data=confirm_callback),
        types.InlineKeyboardButton("❌ انصراف", callback_data=back_callback)
    )
    _safe_edit(uid, msg_id, prompt, reply_markup=kb)


def handle_reset_payment_history_action(call, params):
    """(بدون تغییر) رکوردهای پرداخت کاربر را حذف کرده و نتیجه را اعلام می‌کند."""
    identifier = params[0]
    context = "search" if len(params) > 1 and params[1] == 'search' else None
    
    info = combined_handler.get_combined_user_info(identifier)
    if not info or not info.get('uuid'):
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد یا UUID ندارد.", show_alert=True)
        return

    uuid_id_in_db = db.get_uuid_id_by_uuid(info['uuid'])
    if not uuid_id_in_db:
        bot.answer_callback_query(call.id, "❌ کاربر در دیتابیس ربات یافت نشد.", show_alert=True)
        return

    deleted_count = db.delete_user_payment_history(uuid_id_in_db)
    bot.answer_callback_query(call.id, f"✅ {deleted_count} رکورد پرداخت با موفقیت حذف شد. شمارنده تمدید صفر شد.", show_alert=True)
    
    summary_params = ['h', identifier]
    if context:
        summary_params.append(context)
    
    handle_show_user_summary(call, summary_params)

def handle_send_payment_reminder(call, params):
    """
    Handles sending a payment reminder to the user and updates the admin's view.
    """
    identifier = params[0]
    context = "search" if len(params) > 1 and params[1] == 's' else None
    uid, msg_id = call.from_user.id, call.message.message_id

    info = combined_handler.get_combined_user_info(identifier)
    if not info or not info.get('uuid'):
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد یا UUID ندارد.", show_alert=True)
        return

    user_telegram_id = db.get_user_id_by_uuid(info['uuid'])
    if not user_telegram_id:
        bot.answer_callback_query(call.id, "❌ کاربر در دیتابیس ربات یافت نشد.", show_alert=True)
        return

    lang_code = db.get_user_language(user_telegram_id)
    reminder_message = escape_markdown(get_string("payment_reminder_message", lang_code))

    # We use the _notify_user function which returns True on success
    success = _notify_user(user_telegram_id, reminder_message)

    if success:
        bot.answer_callback_query(call.id, "✅ پیام با موفقیت ارسال شد.")
        
        # After successfully sending the message, we rebuild the admin's view with a confirmation text.
        db_user = db.user(user_telegram_id)
        text_to_show = fmt_admin_user_summary(info, db_user) + "\n\n*✅ هشدار اولیه یادآوری عدم پرداخت با موفقیت ارسال شد\\.*"
        
        panel_for_menu = 'hiddify' if any(p.get('type') == 'hiddify' for p in info.get('breakdown', {}).values()) else 'marzban'
        back_callback = "admin:search_menu" if context == "search" else "admin:management_menu"
        kb = menu.admin_user_interactive_management(identifier, info.get('is_active', False), panel_for_menu, back_callback=back_callback)
        
        # Now we edit the admin's message to show the confirmation
        _safe_edit(uid, msg_id, text_to_show, reply_markup=kb)
    else:
        bot.answer_callback_query(call.id, "❌ خطا در ارسال پیام به کاربر.", show_alert=True)


def handle_send_disconnection_warning(call, params):
    """
    Handles sending a final disconnection warning to the user.
    """
    identifier = params[0]
    context = "search" if len(params) > 1 and params[1] == 's' else None
    uid, msg_id = call.from_user.id, call.message.message_id

    info = combined_handler.get_combined_user_info(identifier)
    if not info or not info.get('uuid'):
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد یا UUID ندارد.", show_alert=True)
        return

    user_telegram_id = db.get_user_id_by_uuid(info['uuid'])
    if not user_telegram_id:
        bot.answer_callback_query(call.id, "❌ کاربر در دیتابیس ربات یافت نشد.", show_alert=True)
        return

    lang_code = db.get_user_language(user_telegram_id)
    warning_message = escape_markdown(get_string("disconnection_warning_message", lang_code))

    success = False
    try:
        bot.send_message(user_telegram_id, warning_message, parse_mode="MarkdownV2")
        logger.info(f"Successfully sent disconnection warning to user {user_telegram_id}")
        success = True
    except Exception as e:
        logger.warning(f"Failed to send disconnection warning to user {user_telegram_id}: {e}")
        bot.answer_callback_query(call.id, "❌ خطا در ارسال پیام به کاربر.", show_alert=True)
        return

    if success:
        admin_lang_code = db.get_user_language(uid)
        bot.answer_callback_query(call.id, get_string("disconnection_warning_sent_confirmation", admin_lang_code))
        
        db_user = db.user(user_telegram_id)
        fresh_info = combined_handler.get_combined_user_info(identifier)
        
        confirmation_msg = get_string("disconnection_warning_sent_confirmation", admin_lang_code)
        text_to_show = fmt_admin_user_summary(fresh_info, db_user) + f"\n\n*{escape_markdown(confirmation_msg)}*"
        
        panel_for_menu = 'hiddify' if any(p.get('type') == 'hiddify' for p in fresh_info.get('breakdown', {}).values()) else 'marzban'
        back_callback = "admin:search_menu" if context == "search" else "admin:management_menu"
        kb = menu.admin_user_interactive_management(identifier, fresh_info.get('is_active', False), panel_for_menu, back_callback=back_callback)
        
        _safe_edit(uid, msg_id, text_to_show, reply_markup=kb)

def handle_renew_subscription_menu(call: types.CallbackQuery, params: list):
    """منوی گزینه‌های تمدید اشتراک (ریست یا انتخاب پلن) را نمایش می‌دهد."""
    identifier = params[0]
    context_suffix = f":{params[1]}" if len(params) > 1 else ""
    uid, msg_id = call.from_user.id, call.message.message_id
    
    prompt = "لطفاً یکی از گزینه‌های زیر را برای تمدید اشتراک انتخاب کنید:"
    kb = menu.admin_renew_subscription_menu(identifier, context_suffix)
    _safe_edit(uid, msg_id, prompt, reply_markup=kb, parse_mode=None)

def handle_renew_select_plan_menu(call: types.CallbackQuery, params: list):
    """منوی انتخاب پلن برای تمدید اشتراک را نمایش می‌دهد."""
    identifier = params[0]
    context_suffix = f":{params[1]}" if len(params) > 1 else ""
    uid, msg_id = call.from_user.id, call.message.message_id
    
    prompt = "لطفاً پلن مورد نظر برای اعمال روی کاربر را انتخاب کنید:"
    kb = menu.admin_select_plan_for_renew_menu(identifier, context_suffix)
    _safe_edit(uid, msg_id, prompt, reply_markup=kb, parse_mode=None)

def handle_renew_apply_plan(call: types.CallbackQuery, params: list):
    """یک پلن جدید را روی کاربر اعمال می‌کند."""
    plan_index, identifier = int(params[0]), params[1]
    context_suffix = f":{params[2]}" if len(params) > 2 else ""
    uid, msg_id = call.from_user.id, call.message.message_id

    _safe_edit(uid, msg_id, "⏳ در حال اعمال پلن جدید...", reply_markup=None)

    all_plans = load_service_plans()
    if not (0 <= plan_index < len(all_plans)):
        bot.answer_callback_query(call.id, "❌ پلن نامعتبر است.", show_alert=True)
        return

    selected_plan = all_plans[plan_index]
    plan_name = selected_plan.get('name', 'N/A')
    
    set_gb = parse_volume_string(selected_plan.get('total_volume', '0'))
    set_days = parse_volume_string(selected_plan.get('duration', '0'))

    success = combined_handler.modify_user_on_all_panels(
        identifier, set_gb=set_gb, set_days=set_days
    )

    if success:
        bot.answer_callback_query(call.id, f"✅ پلن {plan_name} با موفقیت اعمال شد.", show_alert=True)
        # Refresh user summary
        new_params = [None, identifier, context_suffix.replace(':', '')]
        handle_show_user_summary(call, new_params)
    else:
        bot.answer_callback_query(call.id, "❌ خطا در اعمال پلن.", show_alert=True)

def handle_renew_reset_subscription(call: types.CallbackQuery, params: list):
    """
    پیش‌نمایش دقیق برای عملیات ریست اشتراک کاربر را با پیشوند صحیح ادمین نمایش می‌دهد.
    """
    identifier = params[0]
    context_suffix = f":{params[1]}" if len(params) > 1 else ""
    uid, msg_id = call.from_user.id, call.message.message_id
    
    info = combined_handler.get_combined_user_info(identifier)
    if not info:
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد.", show_alert=True)
        return

    current_total_limit_gb = info.get('usage_limit_GB', 0)
    all_plans = load_service_plans()
    matched_plan = None
    
    for plan in all_plans:
        plan_volume_gb = 0
        volume_keys = ['total_volume', 'volume_de', 'volume_fr', 'volume_tr', 'volume_us', 'volume_ro']
        found_key = next((key for key in volume_keys if key in plan), None)
        if found_key:
            plan_volume_str = plan.get(found_key, '0')
            plan_volume_gb = parse_volume_string(plan_volume_str)
        
        if abs(plan_volume_gb - current_total_limit_gb) < 0.01:
            matched_plan = plan
            break

    if not matched_plan:
        bot.answer_callback_query(call.id, "❌ پلن فعلی کاربر برای اعمال مجدد یافت نشد.", show_alert=True)
        handle_show_user_summary(call, [None, identifier, context_suffix.replace(':', '')])
        return

    plan_name = matched_plan.get('name', 'بدون نام')
    plan_price = matched_plan.get('price', 0)
    plan_duration_str = matched_plan.get('duration', '0 روز')
    
    volume_keys = ['total_volume', 'volume_de', 'volume_fr', 'volume_tr', 'volume_us', 'volume_ro']
    found_key = next((key for key in volume_keys if key in matched_plan), None)
    plan_volume_str = matched_plan.get(found_key, '0 گیگابایت') if found_key else '0 گیگابایت'
    
    plan_duration_days = parse_volume_string(plan_duration_str)
    plan_volume_gb = parse_volume_string(plan_volume_str)

    current_limit_gb = info.get('usage_limit_GB', 0)
    current_days_left = info.get('days_left', 0)

    preview_text = (
        f"🔍 **پیش‌نمایش ریست اشتراک**\n"
        f"──────────────────\n"
        f"**وضعیت فعلی کاربر:**\n"
        f"▫️ **حجم کل:** `{current_limit_gb:.1f}` گیگابایت\n"
        f"▫️ **روزهای باقی‌مانده:** `{current_days_left}` روز\n\n"
        f"**پلن انتخابی جهت ریست:**\n"
        f"▫️ **نام:** {plan_name}\n"
        f"▫️ **حجم:** {plan_volume_str}\n"
        f"▫️ **مدت:** {plan_duration_str}\n\n"
        f"**وضعیت پس از ریست:**\n"
        f"▪️ **حجم کل:** `{plan_volume_gb:.1f}` گیگابایت\n"
        f"▪️ **روزهای باقی‌مانده:** `{plan_duration_days}` روز\n"
        f"──────────────────\n"
        f"❓ **تایید نهایی**\n"
        f"مبلغ **{plan_price:,.0f} تومان** بابت تمدید این پلن محاسبه خواهد شد. آیا ادامه می‌دهید؟"
    )

    markup = types.InlineKeyboardMarkup()
    # --- START: کد اصلاح شده ---
    # پیشوند "admin:" به ابتدای شناسه‌ها اضافه شد
    confirm_button = types.InlineKeyboardButton("✅ تایید و ریست", callback_data=f"admin:renew_confirm:{identifier}{context_suffix}")
    cancel_button = types.InlineKeyboardButton("❌ لغو", callback_data=f"admin:user_summary:{identifier}{context_suffix}")
    # --- END: کد اصلاح شده ---
    markup.add(confirm_button, cancel_button)

    _safe_edit(uid, msg_id, preview_text, reply_markup=markup, parse_mode='Markdown')

    _safe_edit(uid, msg_id, preview_text, reply_markup=markup, parse_mode='Markdown')

# این کد جایگزین تابع handle_confirm_renew_subscription می‌شود
def handle_confirm_renew_subscription(call: types.CallbackQuery, params: list):
    """
    عملیات ریست اشتراک (شامل حجم و زمان) را پس از تایید ادمین انجام می‌دهد.
    """
    identifier = params[0]
    context_suffix = f":{params[1]}" if len(params) > 1 else ""
    uid, msg_id = call.from_user.id, call.message.message_id

    _safe_edit(uid, msg_id, "⏳ در حال ریست کردن اشتراک کاربر...", reply_markup=None)

    info = combined_handler.get_combined_user_info(identifier)
    if not info:
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد.", show_alert=True)
        return

    current_total_limit_gb = info.get('usage_limit_GB', 0)
    all_plans = load_service_plans()
    matched_plan = None
    
    for plan in all_plans:
        plan_volume_gb = 0
        volume_keys = ['total_volume', 'volume_de', 'volume_fr', 'volume_tr', 'volume_us', 'volume_ro']
        found_key = next((key for key in volume_keys if key in plan), None)
        if found_key:
            plan_volume_str = plan.get(found_key, '0')
            plan_volume_gb = parse_volume_string(plan_volume_str)
        
        if abs(plan_volume_gb - current_total_limit_gb) < 0.01:
            matched_plan = plan
            break
            
    if not matched_plan:
        bot.answer_callback_query(call.id, "❌ پلن فعلی کاربر برای اعمال مجدد یافت نشد.", show_alert=True)
        handle_show_user_summary(call, [None, identifier, context_suffix.replace(':', '')])
        return

    # صفر کردن مصرف فعلی کاربر
    reset_success = combined_handler.reset_user_usage_on_all_panels(identifier)

    if not reset_success:
        bot.answer_callback_query(call.id, "❌ خطا در صفر کردن مصرف فعلی کاربر.", show_alert=True)
        handle_show_user_summary(call, [None, identifier, context_suffix.replace(':', '')])
        return

    # استخراج مقادیر جدید حجم و زمان از پلن
    duration_str = matched_plan.get('duration', '0')
    set_days = parse_volume_string(duration_str)

    volume_keys = ['total_volume', 'volume_de', 'volume_fr', 'volume_tr', 'volume_us', 'volume_ro']
    found_key = next((key for key in volume_keys if key in matched_plan), None)
    volume_str = matched_plan.get(found_key, '0') if found_key else '0'
    set_gb = parse_volume_string(volume_str)
    
    # اعمال حجم و زمان جدید به تمام پنل‌های کاربر
    apply_success = combined_handler.modify_user_on_all_panels(
        identifier, 
        set_days=set_days,
        set_volume_gb=set_gb
    )
    
    if apply_success:
        # اینجا می‌توانید منطق کسر هزینه از کیف پول را اضافه کنید
        bot.answer_callback_query(call.id, f"✅ اشتراک کاربر با موفقیت به پلن '{matched_plan.get('name')}' ریست شد.", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "❌ خطا در اعمال مقادیر جدید پلن.", show_alert=True)

    handle_show_user_summary(call, [None, identifier, context_suffix.replace(':', '')])