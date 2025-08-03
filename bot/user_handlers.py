import logging
from telebot import types, telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import io
import qrcode
import jdatetime
from .config import ADMIN_IDS, EMOJIS
from .settings_manager import settings
from .database import db
from . import combined_handler
from .menu import menu
from .utils import validate_uuid, escape_markdown, _safe_edit
from .user_formatters import fmt_one, quick_stats, fmt_service_plans, fmt_panel_quick_stats, fmt_user_payment_history, fmt_registered_birthday_info
from .utils import load_service_plans
from .language import get_string

logger = logging.getLogger(__name__)
bot = None

# ======================================================================================
#  اصل کلی: تمام قالب‌بندی‌ها (*, `, _, \) در این فایل انجام می‌شود.
#  فایل‌های JSON فقط حاوی متن خام و بدون قالب‌بندی هستند.
# ======================================================================================


def language_selection_menu() -> types.InlineKeyboardMarkup:
    """Creates the language selection keyboard."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🇮🇷 Persian", callback_data="set_lang:fa"),
        types.InlineKeyboardButton("🇬🇧 English", callback_data="set_lang:en")
    )
    return kb

# =============================================================================
# Callback Handler
# =============================================================================

def handle_user_callbacks(call: types.CallbackQuery):
    """Handles all non-admin, non-language-selection callbacks."""
    global bot
    uid, data, msg_id = call.from_user.id, call.data, call.message.message_id
    lang_code = db.get_user_language(uid)

    # Dictionary for simple, direct callbacks
    USER_CALLBACK_MAP = {
        "add": _handle_add_uuid_request,
        "manage": _show_manage_menu,
        "quick_stats": _show_quick_stats,
        "settings": _show_settings,
        "support": _handle_support_request,
        "back": _go_back_to_main,
        "birthday_gift": _handle_birthday_gift_request,
        "view_plans": _show_plan_categories,
        "change_language": _handle_change_language_request
    }
    
    handler = USER_CALLBACK_MAP.get(data)
    if handler:
        bot.clear_step_handler_by_chat_id(uid)
        handler(call)
        return
    
    # Handling for patterned callbacks
    if data.startswith("acc_"):
        uuid_id = int(data.split("_")[1])
        row = db.uuid_by_id(uid, uuid_id)
        if row and (info := combined_handler.get_combined_user_info(row["uuid"])):
            daily_usage_data = db.get_usage_since_midnight(uuid_id)
            # fmt_one is already refactored to handle its own formatting
            text = fmt_one(info, daily_usage_data, lang_code=lang_code)
            _safe_edit(uid, msg_id, text, reply_markup=menu.account_menu(uuid_id, lang_code=lang_code))
            
    elif data.startswith("toggle_"):
        setting_key = data.replace("toggle_", "")
        current_settings = db.get_user_settings(uid)
        db.update_user_setting(uid, setting_key, not current_settings.get(setting_key, True))
        text = f'*{escape_markdown(get_string("settings_updated", lang_code))}*'
        _safe_edit(uid, msg_id, text, reply_markup=menu.settings(db.get_user_settings(uid), lang_code=lang_code))

    elif data.startswith("getlinks_"):
        uuid_id = int(data.split("_")[1])
        raw_text = get_string("prompt_get_links", lang_code)
        lines = raw_text.split('\n')
        
        processed_lines = []
        for line in lines:
            if line.startswith("Normal:"):
                content = line.replace("Normal:", "").strip()
                processed_lines.append(f'*Normal:* {escape_markdown(content)}')
            elif line.startswith("Base64:"):
                content = line.replace("Base64:", "").strip()
                processed_lines.append(f'*Base64:* {escape_markdown(content)}')
            else:
                processed_lines.append(escape_markdown(line))
        
        text_to_send = "\n".join(processed_lines)

        if call.message.photo:
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception as e: logger.warning(f"Could not delete photo message on back action: {e}")
            bot.send_message(call.from_user.id, text_to_send, reply_markup=menu.get_links_menu(uuid_id, lang_code=lang_code), parse_mode="MarkdownV2")
        else:
            _safe_edit(chat_id=uid, msg_id=msg_id, text=text_to_send, reply_markup=menu.get_links_menu(uuid_id, lang_code=lang_code))
    
    elif data.startswith("getlink_normal_") or data.startswith("getlink_b64_"):
        parts = data.split("_")
        link_type, uuid_id = parts[1], int(parts[2])
        row = db.uuid_by_id(uid, uuid_id)
        if not row:
            bot.answer_callback_query(call.id, get_string("err_acc_not_found", lang_code), show_alert=True)
            return

        # Safely build the subscription link message
        try:
            user_uuid = row['uuid']
            WEBAPP_BASE_URL = "https://panel.cloudvibe.ir"
            link_path = f"user/sub/{user_uuid}"
            if link_type == 'b64':
                link_path = f"user/sub/b64/{user_uuid}"
                
            full_sub_link = f"{WEBAPP_BASE_URL.rstrip('/')}/{link_path}"

            qr_img = qrcode.make(full_sub_link)
            stream = io.BytesIO(); qr_img.save(stream, 'PNG'); stream.seek(0)
            
            raw_template = get_string("msg_link_ready", lang_code)
            escaped_link = f"`{escape_markdown(full_sub_link)}`"
            message_text = f'*{escape_markdown(raw_template.splitlines()[0].format(link_type=link_type.capitalize()))}*\n\n' + \
                           f'{escape_markdown(raw_template.splitlines()[2])}\n{escaped_link}\n\n' + \
                           f'{escape_markdown(raw_template.splitlines()[4])}'
            
            kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(get_string("back", lang_code), callback_data=f"getlinks_{uuid_id}"))
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_photo(uid, photo=stream, caption=message_text, reply_markup=kb, parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"Failed to generate/send subscription link for UUID {user_uuid}: {e}", exc_info=True)
            bot.answer_callback_query(call.id, escape_markdown(get_string("err_link_generation", lang_code)), show_alert=True)
            _safe_edit(uid, msg_id, escape_markdown(get_string("err_try_again", lang_code)), reply_markup=menu.get_links_menu(uuid_id, lang_code=lang_code))

    elif data.startswith("del_"):
        uuid_id = int(data.split("_")[1])
        db.deactivate_uuid(uuid_id)
        # Pass the raw string, _show_manage_menu will handle formatting.
        _show_manage_menu(call=call, override_text=get_string("msg_account_deleted", lang_code))

    elif data.startswith("win_select_"):
        uuid_id = int(data.split("_")[2])
        row = db.uuid_by_id(uid, uuid_id)
        if row:
            info = combined_handler.get_combined_user_info(row['uuid'])
            h_info = info.get('breakdown', {}).get('hiddify', {})
            m_info = info.get('breakdown', {}).get('marzban', {})
            text = get_string("prompt_select_server_stats", lang_code)
            # parse_mode=None is safe as the string is plain
            _safe_edit(uid, msg_id, text, reply_markup=menu.server_selection_menu(uuid_id, bool(h_info), bool(m_info), lang_code=lang_code), parse_mode=None)

    elif data.startswith(("win_hiddify_", "win_marzban_")):
        parts = data.split("_")
        panel_code, uuid_id = parts[1], int(parts[2])
        if db.uuid_by_id(uid, uuid_id):
            # fmt_panel_quick_stats is already refactored
            panel_db_name = f"{panel_code}_usage_gb"
            panel_display_name = get_string('server_de' if panel_code == "hiddify" else 'server_fr', lang_code)
            stats = db.get_panel_usage_in_intervals(uuid_id, panel_db_name)
            text = fmt_panel_quick_stats(panel_display_name, stats, lang_code=lang_code)
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data=f"win_select_{uuid_id}"))
            _safe_edit(uid, msg_id, text, reply_markup=markup)

    elif data.startswith("qstats_acc_page_"):
        page = int(data.split("_")[3])
        # quick_stats is already refactored
        text, menu_data = quick_stats(db.uuids(uid), page=page, lang_code=lang_code)
        reply_markup = menu.quick_stats_menu(menu_data['num_accounts'], menu_data['current_page'], lang_code=lang_code)
        _safe_edit(uid, msg_id, text, reply_markup=reply_markup)

    elif data.startswith("payment_history_"):
        parts = data.split('_'); uuid_id, page = int(parts[2]), int(parts[3])
        row = db.uuid_by_id(uid, uuid_id)
        if row:
            # fmt_user_payment_history is already refactored
            payment_history = db.get_user_payment_history(uuid_id)
            text = fmt_user_payment_history(payment_history, row.get('name', get_string('unknown_user', lang_code)), page, lang_code=lang_code)
            kb = menu.create_pagination_menu(f"payment_history_{uuid_id}", page, len(payment_history), f"acc_{uuid_id}", lang_code)
            _safe_edit(uid, msg_id, text, reply_markup=kb)
        else:
            bot.answer_callback_query(call.id, get_string("err_acc_not_found", lang_code), show_alert=True)

    elif data.startswith("show_plans:"):
        _show_filtered_plans(call)

# =============================================================================
# Helper Functions (Next Step Handlers & Menu Builders)
# =============================================================================

def _build_formatted_prompt(raw_text: str) -> str:
    """Helper to format prompts with backticks for `UUID`."""
    return escape_markdown(raw_text).replace("UUID", "`UUID`")

def _add_uuid_step(message: types.Message):
    global bot; uid, uuid_str = message.from_user.id, message.text.strip().lower()
    lang_code = db.get_user_language(uid)

    if uuid_str.startswith('/'):
        bot.clear_step_handler_by_chat_id(uid)
        bot.send_message(uid, get_string("add_account_cancelled", lang_code))
        _go_back_to_main(message=message)
        return

    if not validate_uuid(uuid_str):
        prompt = _build_formatted_prompt(get_string("uuid_invalid_cancel", lang_code))
        m = bot.send_message(uid, prompt, reply_markup=menu.user_cancel_action(lang_code, "manage"), parse_mode="MarkdownV2")
        if m: bot.register_next_step_handler(m, _add_uuid_step)
        return

    if not (info := combined_handler.get_combined_user_info(uuid_str)):
        prompt = _build_formatted_prompt(get_string("uuid_not_found_panel_cancel", lang_code))
        m = bot.send_message(uid, prompt, reply_markup=menu.user_cancel_action(lang_code, "manage"), parse_mode="MarkdownV2")
        if m: bot.register_next_step_handler(m, _add_uuid_step)
        return
    
    status_key = db.add_uuid(uid, uuid_str, info.get("name", get_string('unknown_user', lang_code)))
    _show_manage_menu(message=message, override_text=get_string(status_key, lang_code))

def _get_birthday_step(message: types.Message, original_msg_id: int):
    global bot
    uid, birthday_str = message.from_user.id, message.text.strip()
    lang_code = db.get_user_language(uid)

    # --- ۱. پیام کاربر حذف می‌شود ---
    try:
        bot.delete_message(chat_id=uid, message_id=message.message_id)
    except Exception as e:
        logger.warning(f"Could not delete user message {message.message_id} for user {uid}: {e}")

    try:
        gregorian_date = jdatetime.datetime.strptime(birthday_str, '%Y/%m/%d').togregorian().date()
        db.update_user_birthday(uid, gregorian_date)
        
        # --- ۲. پیام قبلی با استفاده از original_msg_id ویرایش می‌شود ---
        success_text = escape_markdown(get_string("birthday_success", lang_code))
        back_button_text = get_string('back_to_main_menu', lang_code)
        kb = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(f"🔙 {back_button_text}", callback_data="back")
        )
        _safe_edit(uid, original_msg_id, success_text, reply_markup=kb, parse_mode="MarkdownV2")

    except ValueError:
        # در صورت خطا، پیام قبلی ویرایش شده و دوباره راهنمایی نمایش داده می‌شود
        prompt = _build_formatted_prompt(get_string("birthday_invalid_format", lang_code))
        _safe_edit(uid, original_msg_id, prompt, parse_mode="MarkdownV2")
        
        # و ربات دوباره منتظر پاسخ صحیح می‌ماند
        bot.register_next_step_handler_by_chat_id(uid, _get_birthday_step, original_msg_id=original_msg_id)

def _handle_add_uuid_request(call: types.CallbackQuery):
    global bot
    uid = call.from_user.id
    lang_code = db.get_user_language(uid)
    
    # --- تغییر اصلی اینجاست: استفاده صحیح از تابع cancel_action ---
    _safe_edit(uid, call.message.message_id, get_string("prompt_add_uuid", lang_code), 
               reply_markup=menu.user_cancel_action(back_callback="manage", lang_code=lang_code), 
               parse_mode=None)
               
    bot.register_next_step_handler_by_chat_id(uid, _add_uuid_step)

def _show_manage_menu(call: types.CallbackQuery = None, message: types.Message = None, override_text: str = None):
    global bot; uid = call.from_user.id if call else message.from_user.id
    msg_id = call.message.message_id if call else None
    lang_code = db.get_user_language(uid)
    
    user_uuids = db.uuids(uid)
    user_accounts_details = [info for row in user_uuids if (info := combined_handler.get_combined_user_info(row["uuid"]))]
    for i, info in enumerate(user_accounts_details): info['id'] = user_uuids[i]['id']
    
    # Format the title
    if override_text:
        text = escape_markdown(override_text)
    else:
        text = f'*{escape_markdown(get_string("account_list_title", lang_code))}*'
        
    reply_markup = menu.accounts(user_accounts_details, lang_code)

    if call:
        _safe_edit(uid, msg_id, text, reply_markup=reply_markup)
    else:
        bot.send_message(uid, text, reply_markup=reply_markup, parse_mode="MarkdownV2")

def _show_quick_stats(call: types.CallbackQuery):
    uid = call.from_user.id
    lang_code =  db.get_user_language(uid)
    text, menu_data = quick_stats(db.uuids(uid), page=0, lang_code=lang_code)
    reply_markup = menu.quick_stats_menu(menu_data['num_accounts'], menu_data['current_page'], lang_code=lang_code)
    _safe_edit(uid, call.message.message_id, text, reply_markup=reply_markup)

def _show_settings(call: types.CallbackQuery):
    uid = call.from_user.id
    lang_code = db.get_user_language(uid)
    settings_data = db.get_user_settings(uid)
    text = f'*{escape_markdown(get_string("settings_title", lang_code))}*'
    _safe_edit(uid, call.message.message_id, text, reply_markup=menu.settings(settings_data, lang_code=lang_code))

def _go_back_to_main(call: types.CallbackQuery = None, message: types.Message = None):
    uid = call.from_user.id if call else message.from_user.id
    msg_id = call.message.message_id if call and not message else None
    lang_code = db.get_user_language(uid)
    text = f'*{escape_markdown(get_string("main_menu_title", lang_code))}*'
    reply_markup = menu.main(uid in ADMIN_IDS, lang_code=lang_code)
    if msg_id:
        _safe_edit(uid, msg_id, text, reply_markup=reply_markup)
    else:
        bot.send_message(uid, text, reply_markup=reply_markup, parse_mode="MarkdownV2")

def _handle_birthday_gift_request(call: types.CallbackQuery):
    global bot 
    uid = call.from_user.id
    msg_id = call.message.message_id  # <--- message_id را اینجا ذخیره می‌کنیم
    lang_code = db.get_user_language(uid)
    user_data = db.user(uid)
    
    if user_data and user_data.get('birthday'):
        text = fmt_registered_birthday_info(user_data, lang_code=lang_code)
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
        _safe_edit(uid, msg_id, text, reply_markup=kb, parse_mode="MarkdownV2")
    else:
        raw_text = get_string("prompt_birthday", lang_code)
        prompt = escape_markdown(raw_text).replace("YYYY/MM/DD", "`YYYY/MM/DD`")
        _safe_edit(uid, msg_id, prompt, reply_markup=menu.user_cancel_action(back_callback="back", lang_code=lang_code), parse_mode="MarkdownV2")
        
        # --- تغییر اصلی: message_id را به تابع بعدی پاس می‌دهیم ---
        bot.register_next_step_handler_by_chat_id(uid, _get_birthday_step, original_msg_id=msg_id)

def _show_plan_categories(call: types.CallbackQuery):
    lang_code = db.get_user_language(call.from_user.id)
    prompt = get_string("prompt_select_plan_category", lang_code)
    # parse_mode=None is safe as the string is plain
    _safe_edit(call.from_user.id, call.message.message_id, prompt, reply_markup=menu.plan_category_menu(lang_code=lang_code), parse_mode=None)

def _show_filtered_plans(call: types.CallbackQuery):
    lang_code = db.get_user_language(call.from_user.id)
    plan_type = call.data.split(":")[1]
    # fmt_service_plans is already refactored
    text = fmt_service_plans([p for p in load_service_plans() if p.get("type") == plan_type], plan_type, lang_code=lang_code)
    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="view_plans"))
    _safe_edit(call.from_user.id, call.message.message_id, text, reply_markup=kb)

def _handle_support_request(call: types.CallbackQuery):
    uid = call.from_user.id
    lang_code = db.get_user_language(uid)
    admin_contact = escape_markdown(settings.get('admin_support_contact', '@ExampleAdmin'))
    
    title = f'*{escape_markdown(get_string("support_guidance_title", lang_code))}*'
    body_template = get_string('support_guidance_body', lang_code)
    # The placeholder itself should not be escaped, but the final text should be
    body = escape_markdown(body_template).replace(escape_markdown('{admin_contact}'), f'*{admin_contact}*')
    
    text = f"{title}\n\n{body}"
    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
    _safe_edit(uid, call.message.message_id, text, reply_markup=kb, parse_mode="MarkdownV2")

def _handle_change_language_request(call: types.CallbackQuery):
    """Displays the language selection menu."""
    lang_code = db.get_user_language(call.from_user.id)
    # parse_mode=None is safe as the string is plain
    _safe_edit(call.from_user.id, call.message.message_id, get_string("select_language", lang_code), reply_markup=language_selection_menu(), parse_mode=None)

# =============================================================================
# Main Registration Function
# =============================================================================

def register_user_handlers(b: telebot.TeleBot):
    """Registers all the message and callback handlers for user interactions."""
    global bot; bot = b

    @bot.message_handler(commands=['start'])
    def cmd_start(message: types.Message):
        uid = message.from_user.id
        db.add_or_update_user(uid, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
        if db.uuids(uid):
            _go_back_to_main(message=message)
        else:
            # New user: Ask for language first (hardcoded bilingual prompt is fine here)
            bot.send_message(uid, "Please select your language:\n\nلطفا زبان خود را انتخاب کنید:", reply_markup=language_selection_menu())

    def process_uuid_step_after_lang(message: types.Message):
        uid, uuid_str = message.chat.id, message.text.strip().lower()
        lang_code = db.get_user_language(uid)
        
        if not validate_uuid(uuid_str):
            prompt = _build_formatted_prompt(get_string("uuid_invalid", lang_code))
            m = bot.send_message(uid, prompt, parse_mode="MarkdownV2")
            bot.register_next_step_handler(m, process_uuid_step_after_lang)
            return

        if not (info := combined_handler.get_combined_user_info(uuid_str)):
            prompt = _build_formatted_prompt(get_string("uuid_not_found", lang_code))
            m = bot.send_message(uid, prompt, parse_mode="MarkdownV2")
            bot.register_next_step_handler(m, process_uuid_step_after_lang)
            return
            
        db.add_uuid(uid, uuid_str, info.get("name", get_string('unknown_user', lang_code)))
        _go_back_to_main(message=message)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('set_lang:'))
    def handle_language_selection(call: types.CallbackQuery):
        uid, lang_code = call.from_user.id, call.data.split(':')[1]
        db.set_user_language(uid, lang_code)
        bot.answer_callback_query(call.id)
        # Simple, plain text message
        _safe_edit(uid, call.message.message_id, get_string("lang_selected", lang_code))
        
        if db.uuids(uid):
            _go_back_to_main(call=call)
        else:
            raw_text = get_string("start_prompt", lang_code)
            formatted_text = _build_formatted_prompt(raw_text)
            m = bot.send_message(uid, formatted_text, parse_mode="MarkdownV2")
            bot.register_next_step_handler(m, process_uuid_step_after_lang)