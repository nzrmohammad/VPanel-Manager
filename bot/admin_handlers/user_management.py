import logging
from telebot import types
from typing import Optional, Dict, Any
from ..database import db
from ..menu import menu
from .. import combined_handler
from ..admin_formatters import fmt_admin_user_summary, fmt_user_payment_history
from ..utils import _safe_edit, escape_markdown
from ..language import get_string

logger = logging.getLogger(__name__)
bot, admin_conversations = None, None


def initialize_user_management_handlers(b, conv_dict):
    global bot, admin_conversations
    bot = b
    admin_conversations = conv_dict


def handle_show_user_summary(call, params):
    panel_map = {'h': 'hiddify', 'm': 'marzban'}
    back_map = {'mgt': 'management_menu', 'search': 'search_menu'}

    panel_short = params[0]
    identifier = params[1]
    panel = panel_map.get(panel_short, 'hiddify')

    back_callback = None

    if len(params) > 2 and params[2] in back_map:
        back_callback = f"admin:{back_map[params[2]]}"

    info = combined_handler.get_combined_user_info(identifier)
    if info:
        db_user = None
        if info.get('uuid'):
            user_telegram_id = db.get_user_id_by_uuid(info['uuid'])
            if user_telegram_id:
                db_user = db.user(user_telegram_id)

        text = fmt_admin_user_summary(info, db_user)
        kb = menu.admin_user_interactive_management(identifier, info.get('is_active', False), panel,
                                                    back_callback=back_callback)
        _safe_edit(call.from_user.id, call.message.message_id, text, reply_markup=kb)
    else:
        _safe_edit(call.from_user.id, call.message.message_id, escape_markdown("خطا در دریافت اطلاعات کاربر."),
                   reply_markup=menu.admin_panel_management_menu(panel))


def handle_edit_user_menu(call, params):
    identifier = params[0]
    context = "search" if len(params) > 1 and params[1] == 'search' else None
    context_suffix = f":{context}" if context else ""

    info = combined_handler.get_combined_user_info(identifier)
    if not info:
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد.", show_alert=True)
        return

    breakdown = info.get('breakdown', {})
    on_hiddify = bool(breakdown.get('hiddify'))
    on_marzban = bool(breakdown.get('marzban'))

    single_panel = None
    if on_hiddify and not on_marzban:
        single_panel = 'hiddify'
    elif on_marzban and not on_hiddify:
        single_panel = 'marzban'

    prompt = "🔧 لطفاً نوع ویرایش را انتخاب کنید:"
    kb = types.InlineKeyboardMarkup(row_width=2)
    
    if single_panel:
        btn_add_gb = types.InlineKeyboardButton("➕ افزودن حجم", callback_data=f"admin:ae:agb:{single_panel}:{identifier}{context_suffix}")
        btn_add_days = types.InlineKeyboardButton("➕ افزودن روز", callback_data=f"admin:ae:ady:{single_panel}:{identifier}{context_suffix}")
    else:
        btn_add_gb = types.InlineKeyboardButton("➕ افزودن حجم", callback_data=f"admin:ep:agb:{identifier}{context_suffix}")
        btn_add_days = types.InlineKeyboardButton("➕ افزودن روز", callback_data=f"admin:ep:ady:{identifier}{context_suffix}")

    panel_for_back = 'h' if on_hiddify else 'm'
    btn_back = types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"admin:us:{panel_for_back}:{identifier}{context_suffix}")
    
    kb.add(btn_add_gb, btn_add_days)
    kb.add(btn_back)
    
    _safe_edit(call.from_user.id, call.message.message_id, escape_markdown(prompt), reply_markup=kb)

def handle_ask_edit_value(call, params):
    edit_type, panel, identifier = params[0], params[1], params[2]
    context = "search" if len(params) > 3 and params[3] == "search" else None
    context_suffix = f":{context}" if context else ""

    prompt_map = {"agb": "مقدار حجم برای افزودن (GB) را وارد کنید:", "ady": "تعداد روز برای افزودن را وارد کنید:"}
    prompt = prompt_map.get(edit_type, "مقدار جدید را وارد کنید:")
    
    uid, msg_id = call.from_user.id, call.message.message_id
    
    back_cb = f"admin:edt:{identifier}{context_suffix}"
    
    admin_conversations[uid] = {
        'edit_type': edit_type, 
        'panel': panel, 
        'identifier': identifier, 
        'msg_id': msg_id,
        'context': context 
    }
    _safe_edit(uid, msg_id, escape_markdown(prompt), reply_markup=menu.admin_cancel_action(back_callback=back_cb), parse_mode=None)
    bot.register_next_step_handler_by_chat_id(uid, apply_user_edit)

def apply_user_edit(msg: types.Message):
    uid, text = msg.from_user.id, msg.text.strip()
    bot.delete_message(uid, msg.message_id) 
    if uid not in admin_conversations: return

    convo = admin_conversations.pop(uid, {})
    identifier, edit_type, panel, msg_id = convo.get('identifier'), convo.get('edit_type'), convo.get('panel'), convo.get('msg_id')
    
    context = convo.get('context')
    back_callback = "admin:search_menu" if context == "search" else None
    
    if not all([identifier, edit_type, panel, msg_id]): return

    try:
        value = float(text)
        add_gb = value if edit_type == "agb" else 0
        add_days = int(value) if edit_type == "ady" else 0
        
        success = combined_handler.modify_user_on_all_panels(
            identifier=identifier, add_gb=add_gb, add_days=add_days, target_panel=panel
        )

        if success:
            new_info = combined_handler.get_combined_user_info(identifier)
            user_telegram_id = db.get_user_id_by_uuid(new_info.get('uuid', ''))
            notification_text = ""
            if add_gb > 0:
                notification_text = f"✅ *{escape_markdown(str(add_gb))} GB* حجم به اکانت شما اضافه شد\\."
            elif add_days > 0:
                notification_text = f"✅ *{escape_markdown(str(add_days))}* روز به اعتبار اکانت شما اضافه شد\\."

            if user_telegram_id and notification_text:
                _notify_user(user_telegram_id, notification_text)

            text_to_show = fmt_admin_user_summary(new_info) + "\n\n*✅ کاربر با موفقیت ویرایش شد\\.*"
            original_panel_for_menu = 'hiddify' if bool(new_info.get('breakdown', {}).get('hiddify')) else 'marzban'
            
            kb = menu.admin_user_interactive_management(identifier, new_info['is_active'], original_panel_for_menu, back_callback=back_callback)
            _safe_edit(uid, msg_id, text_to_show, reply_markup=kb)
        else:
            raise Exception("API call failed or user not found")

    except Exception as e:
        logger.error(f"Failed to apply user edit for {identifier}: {e}")
        info = combined_handler.get_combined_user_info(identifier)
        is_active = info.get('is_active', False) if info else False
        _safe_edit(uid, msg_id, "❌ خطا در ویرایش کاربر.",
                   reply_markup=menu.admin_user_interactive_management(identifier, is_active, panel, back_callback=back_callback))


def handle_toggle_status(call, params):
    identifier = params[0]
    context = "search" if len(params) > 1 and params[1] == 'search' else None

    info = combined_handler.get_combined_user_info(identifier)
    if not info:
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد.", show_alert=True)
        return

    breakdown = info.get('breakdown', {})
    on_hiddify = bool(breakdown.get('hiddify'))
    on_marzban = bool(breakdown.get('marzban'))

    if on_hiddify and not on_marzban:
        action_params = ['hiddify', identifier]
        if context:
            action_params.append(context)
        handle_toggle_status_action(call, action_params)
        return
    elif on_marzban and not on_hiddify:
        action_params = ['marzban', identifier]
        if context:
            action_params.append(context)
        handle_toggle_status_action(call, action_params)
        return
    
    prompt = "⚙️ *وضعیت کدام پنل تغییر کند؟*"
    kb = menu.admin_reset_usage_selection_menu(identifier, base_callback="tglA", context=context)
    _safe_edit(call.from_user.id, call.message.message_id, prompt, reply_markup=kb)


def handle_toggle_status_action(call, params):
    panel_to_toggle, identifier = params[0], params[1]
    context = "search" if len(params) > 2 and params[2] == 'search' else None

    info = combined_handler.get_combined_user_info(identifier)
    if not info:
        bot.answer_callback_query(call.id, "❌ کاربر یافت نشد.", show_alert=True)
        return

    h_success, m_success = True, True
    breakdown = info.get('breakdown', {})

    if panel_to_toggle in ['hiddify', 'both'] and 'hiddify' in breakdown:
        current_status_h = breakdown['hiddify'].get('is_active', False)
        new_status_h = not current_status_h
        h_success = combined_handler.hiddify_handler.modify_user(info['uuid'], data={'enable': new_status_h})

    if panel_to_toggle in ['marzban', 'both'] and 'marzban' in breakdown:
        current_status_m = breakdown['marzban'].get('is_active', False)
        new_status_m = not current_status_m
        m_success = combined_handler.marzban_handler.modify_user(info['name'], data={'status': 'active' if new_status_m else 'disabled'})

    if h_success and m_success:
        bot.answer_callback_query(call.id, "✅ وضعیت با موفقیت تغییر کرد.")
        new_info = combined_handler.get_combined_user_info(identifier)
        if new_info:
            back_callback = "admin:search_menu" if context == "search" else None
            panel_for_menu = 'hiddify' if bool(new_info.get('breakdown', {}).get('hiddify')) else 'marzban'
            kb = menu.admin_user_interactive_management(identifier, new_info['is_active'], panel_for_menu, back_callback=back_callback)
            _safe_edit(call.from_user.id, call.message.message_id, fmt_admin_user_summary(new_info), reply_markup=kb)
    else:
        bot.answer_callback_query(call.id, "❌ عملیات در یک یا هر دو پنل ناموفق بود.", show_alert=True)


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
    uid, query = message.from_user.id, message.text.strip()
    bot.delete_message(uid, message.message_id)
    convo_data = admin_conversations.pop(uid, None)
    if not convo_data: return

    original_msg_id = convo_data['msg_id']
    _safe_edit(uid, original_msg_id, "در حال جستجو...", parse_mode=None)

    try:
        results = combined_handler.search_user(query)

        if not results:
            kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت به جستجو", callback_data="admin:search_menu"))
            _safe_edit(uid, original_msg_id, f"❌ کاربری با مشخصات `{escape_markdown(query)}` یافت نشد\\.", reply_markup=kb)
            admin_conversations[uid] = {'msg_id': original_msg_id}
            bot.register_next_step_handler_by_chat_id(uid, _handle_global_search_response)
            return

        if len(results) == 1:
            user = results[0]
            identifier = user.get('uuid') or user.get('name')
            info = combined_handler.get_combined_user_info(identifier)
            if info:
                db_user = None
                if info.get('uuid'):
                    user_telegram_id = db.get_user_id_by_uuid(info['uuid'])
                    if user_telegram_id:
                        db_user = db.user(user_telegram_id)

                panel = user.get('panel', 'hiddify')
                text = fmt_admin_user_summary(info, db_user)
                kb = menu.admin_user_interactive_management(identifier, info.get('is_active', False), panel,
                                                            back_callback="admin:search_menu")
                _safe_edit(uid, original_msg_id, text, reply_markup=kb)
        else:
            kb = types.InlineKeyboardMarkup()
            for user in results:
                breakdown = user.get('breakdown', {})
                on_hiddify = bool(breakdown.get('hiddify'))
                on_marzban = bool(breakdown.get('marzban'))

                panel_flags = ""
                if on_hiddify and on_marzban:
                    panel_flags = "🇩🇪🇫🇷"
                elif on_hiddify:
                    panel_flags = "🇩🇪"
                elif on_marzban:
                    panel_flags = "🇫🇷"

                identifier = user.get('uuid') or user.get('name')
                limit = user.get('usage_limit_GB', 0)
                usage = user.get('current_usage_GB', 0)
                status_emoji = "🟢" if user.get('is_active') else "🔴"

                usage_str = f"{usage:.1f}"
                limit_str = f"{limit:.1f}"
                button_text = f"{status_emoji} {panel_flags} {user['name']} ({usage_str}/{limit_str} GB)"

                panel = user.get('panel', 'hiddify')
                panel_short = 'h' if panel == 'hiddify' else 'm'
                callback_data = f"admin:us:{panel_short}:{identifier}:search"

                kb.add(types.InlineKeyboardButton(button_text, callback_data=callback_data))

            back_to_search_btn = types.InlineKeyboardButton("🔎 جستجوی جدید", callback_data="admin:sg")
            back_to_menu_btn = types.InlineKeyboardButton("🔙 بازگشت به منوی جستجو", callback_data="admin:search_menu")
            kb.row(back_to_search_btn, back_to_menu_btn)

            _safe_edit(uid, original_msg_id, "چندین کاربر یافت شد. لطفاً یکی را انتخاب کنید:", reply_markup=kb,
                       parse_mode=None)

    except Exception as e:
        logger.error(f"Global search failed for query '{query}': {e}", exc_info=True)
        _safe_edit(uid, original_msg_id, "❌ خطایی در هنگام جستجو رخ داد. ممکن است پنل‌ها در دسترس نباشند.",
                   reply_markup=menu.admin_search_menu())



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

    panel_short = 'h' if bool(info.get('breakdown', {}).get('hiddify')) else 'm'
    
    uuid_id = db.get_uuid_id_by_uuid(info['uuid'])
    if not uuid_id:
        back_cb = f"admin:us:{panel_short}:{identifier}{context_suffix}"
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb))
        _safe_edit(uid, msg_id, "❌ کاربر در دیتابیس ربات یافت نشد.", reply_markup=kb)
        return

    payment_history = db.get_user_payment_history(uuid_id)
    user_name_raw = info.get('name', 'کاربر ناشناس')
    text = fmt_user_payment_history(payment_history, user_name_raw, page)

    base_cb = f"admin:phist:{identifier}"
    back_cb_pagination = f"admin:us:{panel_short}:{identifier}{context_suffix}"
    
    kb = menu.create_pagination_menu(base_cb, page, len(payment_history), back_cb_pagination, context=context)
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

    convo = admin_conversations.pop(admin_id, {})
    msg_id = convo['msg_id']

    try:
        target_user_id = int(text)
    except ValueError:
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت به جستجو", callback_data="admin:search_menu"))
        _safe_edit(admin_id, msg_id, escape_markdown("❌ شناسه وارد شده نامعتبر است. لطفاً یک عدد وارد کنید."), reply_markup=kb)
        admin_conversations[admin_id] = {'action_type': 'search_by_tid', 'msg_id': msg_id}
        bot.register_next_step_handler_by_chat_id(admin_id, _find_user_by_telegram_id)
        return

    _safe_edit(admin_id, msg_id, escape_markdown("⏳ در حال جستجو..."))

    user_uuids = db.uuids(target_user_id)
    if not user_uuids:
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت به منوی جستجو", callback_data="admin:search_menu"))
        _safe_edit(admin_id,msg_id,escape_markdown(f"❌ هیچ اکانتی برای کاربر با شناسه {target_user_id} یافت نشد."),reply_markup=kb)
        admin_conversations[admin_id] = {'action_type': 'search_by_tid', 'msg_id': msg_id}
        bot.register_next_step_handler_by_chat_id(admin_id, _find_user_by_telegram_id)
        return

    if len(user_uuids) == 1:
        uuid_str = user_uuids[0]['uuid']
        info = combined_handler.get_combined_user_info(uuid_str)
        if info:
            db_user = db.user(target_user_id)
            panel = 'hiddify' if bool(info.get('breakdown', {}).get('hiddify')) else 'marzban'
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
            panel = 'hiddify' if bool(info.get('breakdown', {}).get('hiddify')) else 'marzban'
            panel_short = 'h' if panel == 'hiddify' else 'm'
            kb.add(types.InlineKeyboardButton(button_text, callback_data=f"admin:us:{panel_short}:{row['uuid']}:search"))

    kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی جستجو", callback_data="admin:search_menu"))

    prompt = f"چندین اکانت برای کاربر *{first_name}* یافت شد. لطفاً یکی را انتخاب کنید:"
    _safe_edit(admin_id, msg_id, escape_markdown(prompt), reply_markup=kb)


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