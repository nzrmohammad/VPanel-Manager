import logging
from telebot import types, apihelper
from typing import Optional, Dict, Any
from ..database import db
from ..menu import menu
from .. import combined_handler
from ..admin_formatters import fmt_admin_user_summary, fmt_user_payment_history
from ..utils import _safe_edit, escape_markdown, load_service_plans, save_service_plans

from ..config import LOYALTY_REWARDS, REFERRAL_REWARD_GB, REFERRAL_REWARD_DAYS

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
    # <<<<<<< START OF FIX: Correctly parse params from the callback >>>>>>>>>
    # The callback is formatted as "admin:us:{panel_short}:{identifier}:{context}"
    # So, params[0] is panel_short, params[1] is the identifier.
    identifier = params[1] 
    back_target = params[2] if len(params) > 2 else 'management_menu'
    # <<<<<<< END OF FIX >>>>>>>>>
    
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

    # This function now generates the new desired format
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
    # تشخیص اینکه آیا از منوی جستجو آمده‌ایم یا نه
    context = "search" if len(params) > 1 and params[1] == 'search' else None
    context_suffix = f":{context}" if context else ""

    info = combined_handler.get_combined_user_info(identifier)
    if not info:
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد.", show_alert=True)
        return

    breakdown = info.get('breakdown', {})
    on_hiddify = any(p.get('type') == 'hiddify' for p in breakdown.values())
    on_marzban = any(p.get('type') == 'marzban' for p in breakdown.values())

    # اگر کاربر فقط در یک نوع پنل حضور داشت، مستقیماً به مرحله پرسیدن مقدار می‌رویم
    single_panel_type = None
    if on_hiddify and not on_marzban:
        single_panel_type = 'hiddify'
    elif on_marzban and not on_hiddify:
        single_panel_type = 'marzban'

    prompt = "🔧 لطفاً نوع ویرایش را انتخاب کنید:"
    kb = types.InlineKeyboardMarkup(row_width=2)
    
    # اگر کاربر در هر دو پنل بود، ابتدا از او می‌پرسیم که ویرایش برای کدام پنل است
    if single_panel_type:
        btn_add_gb = types.InlineKeyboardButton("➕ افزودن حجم", callback_data=f"admin:ae:agb:{single_panel_type}:{identifier}{context_suffix}")
        btn_add_days = types.InlineKeyboardButton("➕ افزودن روز", callback_data=f"admin:ae:ady:{single_panel_type}:{identifier}{context_suffix}")
    else:
        # callback 'ep' (edit panel) برای نمایش منوی انتخاب پنل است
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

    prompt = f"⚙️ لطفاً پنلی که می‌خواهید «{edit_type_name}» به آن اضافه شود را انتخاب کنید:"
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    # نام پنل‌ها به جای hiddify/marzban برای خوانایی بهتر به کار رفته است
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
    
    # اطلاعات لازم برای مرحله بعد در حافظه موقت ذخیره می‌شود
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
    panel_type = convo.get('panel_type') # نام پنل (hiddify یا marzban)
    msg_id = convo.get('msg_id')
    context = convo.get('context')

    if not all([identifier, edit_type, panel_type, msg_id]): return

    try:
        value = float(text)
        add_gb = value if edit_type == "agb" else 0
        add_days = int(value) if edit_type == "ady" else 0
        
        # این تابع به صورت هوشمند عمل کرده و فقط پنل مشخص شده را ویرایش می‌کند
        success = combined_handler.modify_user_on_all_panels(
            identifier=identifier, add_gb=add_gb, add_days=add_days, target_panel_type=panel_type
        )

        if success:
            new_info = combined_handler.get_combined_user_info(identifier)
            # (بخش ارسال نوتیفیکیشن به کاربر و نمایش اطلاعات جدید)
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

    # If user is only on one type of panel, toggle it directly
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
    
    # If user is on both, show a selection menu
    prompt = "⚙️ *وضعیت کدام پنل تغییر کند؟*"
    # We can reuse the reset_usage_selection_menu for this purpose
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
    
    # Get all active panels to find the correct handler
    active_panels = {p['name']: p for p in db.get_active_panels()}

    for panel_name, panel_details in info.get('breakdown', {}).items():
        panel_type = panel_details.get('type')
        panel_data = panel_details.get('data', {})
        
        # Check if this panel should be toggled
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
        # Refresh and display updated user info
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
            # Re-register for another search attempt
            admin_conversations[uid] = {'msg_id': original_msg_id}
            bot.register_next_step_handler_by_chat_id(uid, _handle_global_search_response)
            return

        if len(results) == 1:
            # If only one user is found, show summary directly
            user = results[0]
            identifier = user.get('uuid') or user.get('name')
            # (The logic for showing a single user remains the same)
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
            # If multiple users are found, show a selection list
            kb = types.InlineKeyboardMarkup(row_width=1)
            prompt = "چندین کاربر یافت شد. لطفاً یکی را انتخاب کنید:"
            
            for user in results:
                identifier_for_callback = user.get('uuid') or user.get('name')
                status_emoji = "✅" if user.get('is_active') else "❌"
                button_text = f"{status_emoji} {user.get('name', 'کاربر ناشناس')}"
                
                # We need a panel hint for the callback, 'h' or 'm'
                panel_short = 'h' if any(p.get('type') == 'hiddify' for p in user.get('breakdown', {}).values()) else 'm'
                
                callback_data = f"admin:us:{panel_short}:{identifier_for_callback}:search"
                kb.add(types.InlineKeyboardButton(button_text, callback_data=callback_data))

            kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی جستجو", callback_data="admin:search_menu"))
            _safe_edit(uid, original_msg_id, prompt, reply_markup=kb, parse_mode=None)

    except Exception as e:
        logger.error(f"Global search failed for query '{query}': {e}", exc_info=True)
        _safe_edit(uid, original_msg_id, "❌ خطایی در هنگام جستجو رخ داد.", reply_markup=menu.admin_search_menu())



def handle_log_payment(call, params):
    identifier = params[0]
    context = "search" if len(params) > 1 and params[1] == 'search' else None
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
        back_callback = "admin:search_menu" if context == "search" else None
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

    # --- بخش اصلی اصلاح شده ---
    # از یک تابع جامع‌تر برای گرفتن اطلاعات پرداخت استفاده می‌کنیم
    all_payments = db.get_all_payments_with_user_info()
    # لیست پرداخت‌ها را فقط برای UUID کاربر مورد نظر فیلتر می‌کنیم
    user_payments = [p for p in all_payments if p.get('uuid') == info['uuid']]
    
    user_name_raw = info.get('name', 'کاربر ناشناس')
    # لیست فیلتر شده را به تابع قالب‌بندی ارسال می‌کنیم
    text = fmt_user_payment_history(user_payments, user_name_raw, page)
    # --- پایان بخش اصلاح شده ---

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


def _notify_user(user_id: Optional[int], message: str):
    if not user_id:
        return
    try:
        bot.send_message(user_id, message, parse_mode="MarkdownV2")
        logger.info(f"Sent notification to user {user_id}")
    except Exception as e:
        logger.warning(f"Failed to send notification to user {user_id}: {e}")


def handle_search_by_telegram_id_convo(call, params):
    uid, msg_id = call.from_user.id, call.message.message_id
    prompt = escape_markdown("لطفاً شناسه عددی (ID) کاربر تلگرام مورد نظر را وارد کنید:")

    admin_conversations[uid] = {'action_type': 'search_by_tid', 'msg_id': msg_id}

    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_cancel_action("admin:search_menu"))
    bot.register_next_step_handler_by_chat_id(uid, _find_user_by_telegram_id)


def _find_user_by_telegram_id(message: types.Message):
    admin_id, text = message.from_user.id, message.text.strip()
    bot.delete_message(admin_id, message.message_id)

    if admin_id not in admin_conversations: return

    # <<<<<<< FIX START >>>>>>>>>
    # Don't pop the conversation yet, so we can check/set a flag.
    convo = admin_conversations[admin_id]
    msg_id = convo['msg_id']

    try:
        target_user_id = int(text)
        # On success, now we pop the conversation.
        admin_conversations.pop(admin_id, None)
        
        _safe_edit(admin_id, msg_id, escape_markdown("⏳ در حال جستجو..."))

        user_uuids = db.uuids(target_user_id)
        if not user_uuids:
            kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت به منوی جستجو", callback_data="admin:search_menu"))
            _safe_edit(admin_id, msg_id, escape_markdown(f"❌ هیچ اکانتی برای کاربر با شناسه {target_user_id} یافت نشد."), reply_markup=kb)
            # Put conversation back to allow another try
            admin_conversations[admin_id] = {'action_type': 'search_by_tid', 'msg_id': msg_id}
            bot.register_next_step_handler_by_chat_id(admin_id, _find_user_by_telegram_id)
            return

        # (The rest of the success logic for finding one or multiple users remains the same)
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
        prompt = f"چندین اکانت برای کاربر *{first_name}* یافت شد. لطفاً یکی را انتخاب کنید:"
        _safe_edit(admin_id, msg_id, escape_markdown(prompt), reply_markup=kb)


    except ValueError:
        # Only edit the message to show the error if it hasn't been shown before.
        if not convo.get('invalid_id_error_sent'):
            kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت به جستجو", callback_data="admin:search_menu"))
            _safe_edit(admin_id, msg_id, escape_markdown("❌ شناسه وارد شده نامعتبر است. لطفاً یک عدد وارد کنید."), reply_markup=kb)
            # Set the flag in the conversation to prevent re-editing.
            admin_conversations[admin_id]['invalid_id_error_sent'] = True
        
        # Re-register the handler to wait for the next input.
        bot.register_next_step_handler_by_chat_id(admin_id, _find_user_by_telegram_id)
        return


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
    bot.delete_message(admin_id, message.message_id)

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
    # پارامترها به درستی خوانده می‌شوند
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
    
    # --- ✨ شروع اصلاح اصلی ---
    # در این بخش، پارامترهای مورد نیاز برای بازگشت صحیح به صفحه کاربر را بازسازی می‌کنیم
    
    # 1. نوع پنل کاربر را برای ساخت دکمه‌ها تشخیص می‌دهیم
    panel_short = 'h' if any(p.get('type') == 'hiddify' for p in info.get('breakdown', {}).values()) else 'm'
    
    # 2. لیست پارامترهای جدید را مطابق با فرمت تابع `handle_show_user_summary` می‌سازیم
    new_params_for_summary = [panel_short, identifier]
    if context:
        new_params_for_summary.append(context)
        
    # 3. صفحه اطلاعات کاربر را با پارامترهای صحیح دوباره فراخوانی و به‌روزرسانی می‌کنیم
    handle_show_user_summary(call, new_params_for_summary)
    # --- ✨ پایان اصلاح اصلی ---

def _check_and_apply_loyalty_reward(user_telegram_id: int, uuid_id: int, user_uuid: str, user_name: str):
    """
    وضعیت وفاداری کاربر را بررسی کرده و در صورت واجد شرایط بودن، پاداش را اعمال می‌کند.
    """
    if not LOYALTY_REWARDS:
        return

    try:
        # تعداد کل پرداخت‌های ثبت‌شده برای این اکانت را می‌شماریم
        payment_count = len(db.get_user_payment_history(uuid_id))
        
        # بررسی می‌کنیم آیا شماره تمدید فعلی، در لیست پاداش‌های ما وجود دارد یا نه
        reward = LOYALTY_REWARDS.get(payment_count)

        if reward:
            add_gb = reward.get("gb", 0)
            add_days = reward.get("days", 0)

            # اعمال تغییرات (افزودن حجم و روز) به تمام پنل‌های کاربر
            if combined_handler.modify_user_on_all_panels(user_uuid, add_gb=add_gb, add_days=add_days):
                # ساخت پیام تبریک برای ارسال به کاربر
                notification_text = (
                    f"🎉 *هدیه وفاداری* 🎉\n\n"
                    f"از همراهی صمیمانه شما سپاسگزاریم\\! به مناسبت *{payment_count}* امین تمدید سرویس، هدیه زیر برای شما فعال شد:\n\n"
                    f"🎁 `{add_gb} GB` حجم و `{add_days}` روز اعتبار اضافی\n\n"
                    f"این هدیه به صورت خودکار به اکانت شما اضافه شد\\. امیدواریم از آن لذت ببرید\\."
                )
                _notify_user(user_telegram_id, notification_text)
                logger.info(f"Applied loyalty reward to user_id {user_telegram_id} for {payment_count} payments.")

    except Exception as e:
        logger.error(f"Error checking/applying loyalty reward for user_id {user_telegram_id}: {e}", exc_info=True)


def _check_and_apply_referral_reward(user_telegram_id: int):
    """بررسی و اعمال پاداش معرفی پس از اولین پرداخت."""
    try:
        referrer_info = db.get_referrer_info(user_telegram_id)
        # پاداش فقط در صورتی اعمال می‌شود که کاربر معرف داشته باشد و قبلاً پاداش نگرفته باشد
        if referrer_info and not referrer_info.get('referral_reward_applied'):
            referrer_id = referrer_info['referred_by_user_id']

            # پیدا کردن UUID های هر دو کاربر
            new_user_uuid = db.uuids(user_telegram_id)[0]['uuid']
            referrer_uuid = db.uuids(referrer_id)[0]['uuid']

            # اعمال پاداش به هر دو
            combined_handler.modify_user_on_all_panels(new_user_uuid, add_gb=REFERRAL_REWARD_GB, add_days=REFERRAL_REWARD_DAYS)
            combined_handler.modify_user_on_all_panels(referrer_uuid, add_gb=REFERRAL_REWARD_GB, add_days=REFERRAL_REWARD_DAYS)

            # ثبت اعمال پاداش در دیتابیس
            db.mark_referral_reward_as_applied(user_telegram_id)

            # ارسال پیام تبریک
            new_user_name = escape_markdown(db.user(user_telegram_id).get('first_name', ''))
            referrer_name = escape_markdown(db.user(referrer_id).get('first_name', ''))

            _notify_user(user_telegram_id, f"🎁 هدیه اولین خرید شما ({REFERRAL_REWARD_GB}GB) به دلیل معرفی توسط *{referrer_name}* فعال شد\\!")
            _notify_user(referrer_id, f"🎉 تبریک\\! کاربر *{new_user_name}* اولین خرید خود را انجام داد و هدیه معرفی ({REFERRAL_REWARD_GB}GB) برای شما فعال شد\\.")

            logger.info(f"Referral reward applied for user {user_telegram_id} and referrer {referrer_id}.")

    except Exception as e:
        logger.error(f"Error applying referral reward for user {user_telegram_id}: {e}", exc_info=True)


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
        bot.answer_callback_query(call.id, f"✅ محدودیت انتقال برای کاربر «{info.get('name', '')}» ریست شد.", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "ℹ️ این کاربر تاریخچه انتقالی برای ریست کردن نداشت.", show_alert=True)

    # --- ✅ بخش اصلاح شده برای بازگشت صحیح ---
    # پارامترها را برای فراخوانی صحیح تابع اطلاعات کاربر، بازسازی می‌کنیم
    panel_short = 'h' if any(p.get('type') == 'hiddify' for p in info.get('breakdown', {}).values()) else 'm'
    new_params_for_summary = [panel_short, identifier]
    if context:
        new_params_for_summary.append(context)
        
    handle_show_user_summary(call, new_params_for_summary)