import logging
from telebot import types, telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import io
import qrcode
import jdatetime
from .config import ADMIN_IDS, EMOJIS, ADMIN_SUPPORT_CONTACT, CARD_PAYMENT_INFO, ADMIN_SUPPORT_CONTACT, TUTORIAL_LINKS
from .database import db
from . import combined_handler
from .menu import menu
from .utils import validate_uuid, escape_markdown, _safe_edit
from .user_formatters import fmt_one, quick_stats, fmt_service_plans, fmt_panel_quick_stats, fmt_user_payment_history, fmt_registered_birthday_info, fmt_user_usage_history
from .utils import load_service_plans
from .language import get_string
import urllib.parse
import time


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
        "tutorials": _show_tutorial_main_menu,
        "back": _go_back_to_main,
        "birthday_gift": _handle_birthday_gift_request,
        "view_plans": _show_plan_categories,
        "change_language": _handle_change_language_request,
        "show_payment_options": _show_payment_options_menu,
        "coming_soon": _handle_coming_soon,
        "web_login": _handle_web_login_request
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

    elif data.startswith("changename_"):
            _handle_change_name_request(call)

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

        try:
            user_uuid = row['uuid']
            # نام کانفیگ را از دیتابیس خوانده و برای استفاده در URL انکود می‌کنیم
            config_name_encoded = urllib.parse.quote(row.get('name', 'CloudVibe'))
            
            WEBAPP_BASE_URL = "https://panel.cloudvibe.ir" 
            
            is_base64 = (link_type == 'b64')
            
            normal_sub_link = f"{WEBAPP_BASE_URL.rstrip('/')}/user/sub/{user_uuid}"
            b64_sub_link = f"{WEBAPP_BASE_URL.rstrip('/')}/user/sub/b64/{user_uuid}"
            
            final_sub_link = b64_sub_link if is_base64 else normal_sub_link

            qr_img = qrcode.make(final_sub_link)
            stream = io.BytesIO()
            qr_img.save(stream, 'PNG')
            stream.seek(0)
            
            raw_template = get_string("msg_link_ready", lang_code)
            escaped_link = f"`{escape_markdown(final_sub_link)}`"
            message_text = f'*{escape_markdown(raw_template.splitlines()[0].format(link_type=link_type.capitalize()))}*\n\n' + \
                           f'{escape_markdown(raw_template.splitlines()[2])}\n{escaped_link}'

            kb = types.InlineKeyboardMarkup(row_width=2)
            
            def create_redirect_button(app_name: str, deep_link: str):
                redirect_page_url = f"{WEBAPP_BASE_URL}/app/redirect?url={urllib.parse.quote(deep_link)}&app_name={urllib.parse.quote(app_name)}"
                return types.InlineKeyboardButton(f"📲 افزودن به {app_name}", url=redirect_page_url)

            if not is_base64:
                v2rayng_deep_link = f"v2rayng://install-sub/?url={b64_sub_link}&name={config_name_encoded}"
                kb.add(create_redirect_button("V2rayNG", v2rayng_deep_link))
                kb.add(create_redirect_button("HAP", f"happ://add/{normal_sub_link}"))
                kb.add(create_redirect_button("HiddifyNext", f"hiddify://import/{normal_sub_link}"))
            else:
                v2rayng_deep_link = f"v2rayng://install-sub/?url={b64_sub_link}&name={config_name_encoded}"
                kb.add(create_redirect_button("V2rayNG", v2rayng_deep_link))
                kb.add(create_redirect_button("Streisand", f"streisand://import/{b64_sub_link}"))
                kb.add(create_redirect_button("HiddifyNext", f"hiddify://import/{b64_sub_link}"))

            kb.add(types.InlineKeyboardButton(get_string("back", lang_code), callback_data=f"getlinks_{uuid_id}"))

            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception as e:
                logger.warning(f"Could not delete old message {call.message.message_id}: {e}")

            bot.send_photo(uid, photo=stream, caption=message_text, reply_markup=kb, parse_mode="MarkdownV2")

        except Exception as e:
            logger.error(f"Failed to generate/send subscription link for UUID {row.get('uuid')}: {e}", exc_info=True)
            bot.answer_callback_query(call.id, escape_markdown(get_string("err_link_generation", lang_code)), show_alert=True)
            _safe_edit(uid, msg_id, escape_markdown(get_string("err_try_again", lang_code)), reply_markup=menu.get_links_menu(uuid_id, lang_code=lang_code))
    # --- END OF MODIFIED SECTION ---

    elif data.startswith("del_"):
        uuid_id = int(data.split("_")[1])
        db.deactivate_uuid(uuid_id)
        _show_manage_menu(call=call, override_text=get_string("msg_account_deleted", lang_code))

    elif data.startswith("win_select_"):
        uuid_id = int(data.split("_")[2])
        row = db.uuid_by_id(uid, uuid_id)
        if row:
            has_access_de = bool(row.get('has_access_de'))
            has_access_fr = bool(row.get('has_access_fr'))
            has_access_tr = bool(row.get('has_access_tr'))
            
            text = get_string("prompt_select_server_stats", lang_code)
            
            reply_markup = menu.server_selection_menu(
                uuid_id,
                show_germany=has_access_de,
                show_france=has_access_fr,
                show_turkey=has_access_tr,
                lang_code=lang_code
            )
            _safe_edit(uid, msg_id, text, reply_markup=reply_markup, parse_mode=None)

    elif data.startswith(("win_hiddify_", "win_marzban_")):
        parts = data.split("_")
        panel_code, uuid_id = parts[1], int(parts[2])
        if db.uuid_by_id(uid, uuid_id):
            panel_db_name = f"{panel_code}_usage_gb"
            panel_display_name = get_string('server_de' if panel_code == "hiddify" else 'server_fr', lang_code)
            stats = db.get_panel_usage_in_intervals(uuid_id, panel_db_name)
            text = fmt_panel_quick_stats(panel_display_name, stats, lang_code=lang_code)
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data=f"win_select_{uuid_id}"))
            _safe_edit(uid, msg_id, text, reply_markup=markup)

    elif data.startswith("qstats_acc_page_"):
        page = int(data.split("_")[3])
        text, menu_data = quick_stats(db.uuids(uid), page=page, lang_code=lang_code)
        reply_markup = menu.quick_stats_menu(menu_data['num_accounts'], menu_data['current_page'], lang_code=lang_code)
        _safe_edit(uid, msg_id, text, reply_markup=reply_markup)

    elif data.startswith("payment_history_"):
        parts = data.split('_'); uuid_id, page = int(parts[2]), int(parts[3])
        row = db.uuid_by_id(uid, uuid_id)
        if row:
            payment_history = db.get_user_payment_history(uuid_id)
            text = fmt_user_payment_history(payment_history, row.get('name', get_string('unknown_user', lang_code)), page, lang_code=lang_code)
            kb = menu.create_pagination_menu(f"payment_history_{uuid_id}", page, len(payment_history), f"acc_{uuid_id}", lang_code)
            _safe_edit(uid, msg_id, text, reply_markup=kb)
        else:
            bot.answer_callback_query(call.id, get_string("err_acc_not_found", lang_code), show_alert=True)

    elif data.startswith("show_plans:"):
        _show_filtered_plans(call)

    elif data == "show_card_details":
        if not (CARD_PAYMENT_INFO and CARD_PAYMENT_INFO.get("card_number")):
            return

        title = get_string("payment_card_details_title", lang_code)
        holder_label = get_string("payment_card_holder", lang_code)
        number_label = get_string("payment_card_number", lang_code)
        instructions = get_string("payment_card_instructions", lang_code)
        
        holder_name = escape_markdown(CARD_PAYMENT_INFO.get("card_holder", ""))
        card_number = escape_markdown(CARD_PAYMENT_INFO.get("card_number", ""))

        text = (
            f"*{escape_markdown(title)}*\n\n"
            f"*{escape_markdown(holder_label)}* `{holder_name}`\n\n"
            f"*{escape_markdown(number_label)}*\n`{card_number}`\n\n"
            f"{escape_markdown(instructions)}"
        )

        kb = types.InlineKeyboardMarkup(row_width=1)
        support_url = f"https://t.me/{ADMIN_SUPPORT_CONTACT.replace('@', '')}"
        kb.add(types.InlineKeyboardButton(f"💬 {get_string('btn_contact_support', lang_code)}", url=support_url))
        kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="show_payment_options"))
        
        _safe_edit(uid, msg_id, text, reply_markup=kb, parse_mode="MarkdownV2")
    
    elif data.startswith("usage_history_"):
        uuid_id = int(data.split("_")[2])
        row = db.uuid_by_id(uid, uuid_id)
        if row:
            history = db.get_user_daily_usage_history(uuid_id)
            text = fmt_user_usage_history(history, row.get('name', 'اکانت'), lang_code)
            kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data=f"acc_{uuid_id}"))
            _safe_edit(uid, msg_id, text, reply_markup=kb)

    elif data.startswith("tutorial_os:"):
        os_type = data.split(":")[1]
        _show_tutorial_os_menu(call, os_type)
        return
    elif data.startswith("tutorial_app:"):
        _, os_type, app_name = data.split(":")
        _send_tutorial_link(call, os_type, app_name)
        return


    if data.startswith("share_confirm:"):
        parts = data.split(":")
        decision, requester_id_str, uuid_id_str, requester_msg_id_str = parts[1], parts[2], parts[3], parts[4]
        
        owner_info = call.from_user
        owner_id = owner_info.id
        requester_id = int(requester_id_str)
        uuid_id = int(uuid_id_str)
        requester_msg_id = int(requester_msg_id_str)
        
        bot.edit_message_reply_markup(chat_id=owner_id, message_id=call.message.message_id, reply_markup=None)

        uuid_record = db.uuid_by_id(owner_id, uuid_id)
        if not uuid_record:
            bot.send_message(owner_id, "خطا: اطلاعات اکانت یافت نشد.")
            return

        uuid_str = uuid_record['uuid']
        config_name = uuid_record['name']
        config_name_escaped = escape_markdown(config_name)

        if decision == "yes":
            try:
                # --- *** START OF CHANGES *** ---
                # از تابع جدید و امن برای افزودن اکانت اشتراکی استفاده می‌کنیم
                db.add_shared_uuid(requester_id, uuid_str, config_name)
                # --- *** END OF CHANGES *** ---
                
                bot.send_message(owner_id, f"✅ تایید شد\. کاربر `{requester_id}` اکنون به اکانت «{config_name_escaped}» دسترسی دارد\.", parse_mode="MarkdownV2")
                
                _safe_edit(requester_id, requester_msg_id, "✅ درخواست تایید شد. در حال به‌روزرسانی لیست اکانت‌ها...")
                
                time.sleep(1) 
                
                success_text = f"اکانت «{config_name}» با موفقیت به لیست شما اضافه شد."
                _show_manage_menu(call=call, override_text=success_text, target_user_id=requester_id, target_msg_id=requester_msg_id)

            except Exception as e:
                logger.error(f"Error during account sharing confirmation: {e}")
                _safe_edit(requester_id, requester_msg_id, "خطایی در ثبت اطلاعات رخ داد. لطفاً با پشتیبانی تماس بگیرید.")
        
        else: # decision == "no"
            # ... (منطق رد کردن درخواست بدون تغییر باقی می‌ماند) ...
            owner_name_escaped = escape_markdown(owner_info.first_name)
            bot.send_message(owner_id, "❌ درخواست رد شد\.", parse_mode="MarkdownV2")
            requester_message = (
                f"❌ متاسفانه درخواست شما برای اکانت «{config_name_escaped}» توسط کاربر زیر رد شد:\n\n"
                f"نام: {owner_name_escaped}\n"
                f"آیدی: `{owner_id}`"
            )
            kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت به مدیریت اکانت", callback_data="manage"))
            _safe_edit(requester_id, requester_msg_id, requester_message, reply_markup=kb, parse_mode="MarkdownV2")

    elif data.startswith("cancel_share_req:"):
        parts = data.split(":")
        owner_id, owner_msg_id = int(parts[1]), int(parts[2])
        
        try:
            bot.edit_message_text("❌ این درخواست توسط کاربر لغو شد.", chat_id=owner_id, message_id=owner_msg_id, reply_markup=None)
        except Exception as e:
            logger.warning(f"Could not edit owner's message upon cancellation: {e}")
            
        _show_manage_menu(call=call, override_text="✅ درخواست شما با موفقیت لغو شد.")




# =============================================================================
# Helper Functions (Next Step Handlers & Menu Builders)
# =============================================================================

def _build_formatted_prompt(raw_text: str) -> str:
    """Helper to format prompts with backticks for `UUID`."""
    return escape_markdown(raw_text).replace("UUID", "`UUID`")


def _add_uuid_step(message: types.Message, original_msg_id: int):
    global bot
    uid, uuid_str = message.from_user.id, message.text.strip().lower()
    lang_code = db.get_user_language(uid)

    bot.clear_step_handler_by_chat_id(uid)
    
    # پیام کاربر که حاوی UUID است را حذف می‌کنیم
    try:
        bot.delete_message(chat_id=uid, message_id=message.message_id)
    except Exception as e:
        logger.warning(f"Could not delete user's UUID message: {e}")

    # پیام اصلی ("لطفاً UUID بفرستید") را به حالت "در حال بررسی" ویرایش می‌کنیم
    _safe_edit(uid, original_msg_id, "⏳ در حال بررسی...")

    if not validate_uuid(uuid_str):
        prompt = get_string("uuid_invalid_cancel", lang_code)
        # message.message_id را با original_msg_id جایگزین می‌کنیم تا پیام اصلی ویرایش شود
        _show_manage_menu(message=message, override_text=prompt, target_user_id=uid, target_msg_id=original_msg_id)
        return

    if not (info := combined_handler.get_combined_user_info(uuid_str)):
        prompt = get_string("uuid_not_found_panel_cancel", lang_code)
        _show_manage_menu(message=message, override_text=prompt, target_user_id=uid, target_msg_id=original_msg_id)
        return
    
    result = db.add_uuid(uid, uuid_str, info.get("name", get_string('unknown_user', lang_code)))
    
    if isinstance(result, dict) and result.get("status") == "confirmation_required":
        owner_id = result["owner_id"]
        uuid_id = result["uuid_id"]
        requester_info = message.from_user
        
        config_name_escaped = escape_markdown(info.get('name', ''))
        requester_name_escaped = escape_markdown(requester_info.first_name)
        
        requester_details = [f"نام: {requester_name_escaped}", f"آیدی: `{requester_info.id}`"]
        if requester_info.username:
            requester_details.append(f"یوزرنیم: @{escape_markdown(requester_info.username)}")
        
        requester_details_str = "\n".join(requester_details)

        owner_text = (
            f"⚠️ یک کاربر دیگر قصد دارد به اکانت «{config_name_escaped}» شما متصل شود\.\n\n"
            f"اطلاعات درخواست دهنده:\n{requester_details_str}\n\n"
            f"آیا اجازه می‌دهید این کاربر به صورت **مشترک** از این اکانت استفاده کند؟"
        )
        
        try:
            owner_msg = bot.send_message(owner_id, owner_text, parse_mode="MarkdownV2")
            owner_msg_id = owner_msg.message_id

            wait_message_text = "این اکانت متعلق به کاربر دیگری است. درخواست شما برای استفاده مشترک به ایشان ارسال شد. لطفاً منتظر تایید بمانید..."
            kb_cancel = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("✖️ لغو درخواست", callback_data=f"cancel_share_req:{owner_id}:{owner_msg_id}")
            )
            _safe_edit(uid, original_msg_id, wait_message_text, reply_markup=kb_cancel, parse_mode=None)

            kb_owner = types.InlineKeyboardMarkup(row_width=2)
            yes_callback = f"share_confirm:yes:{uid}:{uuid_id}:{original_msg_id}"
            no_callback = f"share_confirm:no:{uid}:{uuid_id}:{original_msg_id}"
            kb_owner.add(
                types.InlineKeyboardButton("✅ بله", callback_data=yes_callback),
                types.InlineKeyboardButton("❌ خیر", callback_data=no_callback)
            )
            bot.edit_message_reply_markup(chat_id=owner_id, message_id=owner_msg_id, reply_markup=kb_owner)

        except Exception as e:
            logger.error(f"Failed to send share confirmation message to owner {owner_id}: {e}")
            _safe_edit(uid, original_msg_id, "خطا در ارسال درخواست به صاحب اکانت. لطفاً بعدا تلاش کنید.")
        
    elif isinstance(result, str):
        _show_manage_menu(message=message, override_text=get_string(result, lang_code), target_user_id=uid, target_msg_id=original_msg_id)

def _get_birthday_step(message: types.Message, original_msg_id: int):
    global bot
    uid, birthday_str = message.from_user.id, message.text.strip()
    lang_code = db.get_user_language(uid)

    # ۱. پیام کاربر (که حاوی تاریخ است) حذف می‌شود
    try:
        bot.delete_message(chat_id=uid, message_id=message.message_id)
    except Exception as e:
        logger.warning(f"Could not delete user message {message.message_id} for user {uid}: {e}")

    try:
        gregorian_date = jdatetime.datetime.strptime(birthday_str, '%Y/%m/%d').togregorian().date()
        db.update_user_birthday(uid, gregorian_date)
        
        # ۲. پیام اصلی ربات با استفاده از original_msg_id ویرایش می‌شود
        success_text = escape_markdown(get_string("birthday_success", lang_code))
        back_button_text = get_string('back_to_main_menu', lang_code)
        kb = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(f"🔙 {back_button_text}", callback_data="back")
        )
        _safe_edit(uid, original_msg_id, success_text, reply_markup=kb, parse_mode="MarkdownV2")

    except ValueError:
        # در صورت خطا، پیام اصلی ویرایش شده و دوباره راهنمایی نمایش داده می‌شود
        prompt = escape_markdown(get_string("birthday_invalid_format", lang_code)).replace("YYYY/MM/DD", "`YYYY/MM/DD`")
        _safe_edit(uid, original_msg_id, prompt, parse_mode="MarkdownV2")
        
        # ربات دوباره منتظر پاسخ صحیح می‌ماند
        bot.register_next_step_handler_by_chat_id(uid, _get_birthday_step, original_msg_id=original_msg_id)

def _handle_add_uuid_request(call: types.CallbackQuery):
    global bot
    uid = call.from_user.id
    lang_code = db.get_user_language(uid)
    
    _safe_edit(uid, call.message.message_id, get_string("prompt_add_uuid", lang_code), 
               reply_markup=menu.user_cancel_action(back_callback="manage", lang_code=lang_code), 
               parse_mode=None)
               
    # --- *** START OF CHANGES (TypeError Fix) *** ---
    # به تابع بعدی، message_id پیام اصلی ("لطفاً UUID بفرستید") را پاس می‌دهیم
    bot.register_next_step_handler(call.message, _add_uuid_step, original_msg_id=call.message.message_id)
    # --- *** END OF CHANGES *** ---

def _show_manage_menu(call: types.CallbackQuery = None, message: types.Message = None, override_text: str = None, target_user_id: int = None, target_msg_id: int = None):
    uid = target_user_id or (call.from_user.id if call else message.from_user.id)
    msg_id = target_msg_id or (call.message.message_id if call else (message.message_id if message else None))
    
    lang_code = db.get_user_language(uid)
    
    user_uuids = db.uuids(uid)
    user_accounts_details = []
    if user_uuids:
        user_accounts_details = [info for row in user_uuids if (info := combined_handler.get_combined_user_info(row["uuid"]))]
        if user_accounts_details and len(user_uuids) == len(user_accounts_details):
             for i, info in enumerate(user_accounts_details): info['id'] = user_uuids[i]['id']
    
    if override_text:
        text = escape_markdown(override_text)
    else:
        text = f'*{escape_markdown(get_string("account_list_title", lang_code))}*'
        
    reply_markup = menu.accounts(user_accounts_details, lang_code)

    if msg_id:
        _safe_edit(uid, msg_id, text, reply_markup=reply_markup)
    elif message:
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


def _go_back_to_main(call: types.CallbackQuery = None, message: types.Message = None, original_msg_id: int = None):

    uid = call.from_user.id if call else message.from_user.id
    msg_id = original_msg_id or (call.message.message_id if call else None)
    
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
    admin_contact = escape_markdown(ADMIN_SUPPORT_CONTACT)
    
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


def _show_payment_options_menu(call: types.CallbackQuery):
    uid = call.from_user.id
    msg_id = call.message.message_id
    lang_code = db.get_user_language(uid)
    
    text = f"*{escape_markdown(get_string('prompt_select_payment_method', lang_code))}*"
    _safe_edit(uid, msg_id, text, reply_markup=menu.payment_options_menu(lang_code=lang_code), parse_mode="MarkdownV2")


def _handle_coming_soon(call: types.CallbackQuery):
    """با نمایش یک آلرت، به کلیک روی دکمههای "به زودی" پاسخ میدهد."""
    lang_code = db.get_user_language(call.from_user.id)
    alert_text = get_string('msg_coming_soon_alert', lang_code)
    # نمایش پیغام به صورت پاپآپ (Alert)
    bot.answer_callback_query(call.id, text=alert_text, show_alert=True)

def _handle_web_login_request(call: types.CallbackQuery):
    uid = call.from_user.id
    user_uuids = db.uuids(uid)
    if not user_uuids:
        bot.answer_callback_query(call.id, "ابتدا باید یک اکانت ثبت کنید.", show_alert=True)
        return

    # از اولین UUID کاربر برای ورود استفاده می‌کنیم
    user_uuid = user_uuids[0]['uuid']
    token = db.create_login_token(user_uuid)
    
    # آدرس اصلی پنل وب خود را اینجا وارد کنید
    # اگر برنامه شما روی دامنه دیگری است، آن را جایگزین کنید
    base_url = "https://panel.cloudvibe.ir" # <--- !!! این آدرس را حتماً تغییر دهید
    
    login_url = f"{base_url}/login/token/{token}"

    text = "✅ لینک ورود یکبار مصرف شما ایجاد شد.\n\nاین لینک به مدت ۵ دقیقه معتبر است و پس از یکبار استفاده منقضی می‌شود."
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("ورود به پنل کاربری", url=login_url))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="back"))
    
    _safe_edit(uid, call.message.message_id, text, reply_markup=kb, parse_mode=None)


def _handle_change_name_request(call: types.CallbackQuery):
    """Asks the user for a new config name."""
    global bot
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)
    
    try:
        uuid_id = int(call.data.split("_")[1])
        prompt = get_string("prompt_enter_new_name", lang_code)
        
        # از منوی "لغو عملیات" استفاده می‌کنیم که به منوی اکانت بازگردد
        back_callback = f"acc_{uuid_id}"
        kb = menu.user_cancel_action(back_callback=back_callback, lang_code=lang_code)
        
        _safe_edit(uid, msg_id, escape_markdown(prompt), reply_markup=kb, parse_mode="MarkdownV2")
        
        # ثبت مرحله بعدی برای دریافت پاسخ کاربر
        bot.register_next_step_handler_by_chat_id(uid, _process_new_name, uuid_id=uuid_id, original_msg_id=msg_id)
    except (ValueError, IndexError) as e:
        logger.error(f"Error handling change name request for call data '{call.data}': {e}")
        bot.answer_callback_query(call.id, get_string("err_try_again", lang_code), show_alert=True)

# ✅ تابع جدید برای پردازش و ذخیره نام جدید
def _process_new_name(message: types.Message, uuid_id: int, original_msg_id: int):
    """Processes the new name sent by the user, updates the DB, and confirms."""
    global bot
    uid, new_name = message.from_user.id, message.text.strip()
    lang_code = db.get_user_language(uid)

    # ۱. پیام کاربر که حاوی نام جدید است حذف می‌شود
    try:
        bot.delete_message(chat_id=uid, message_id=message.message_id)
    except Exception as e:
        logger.warning(f"Could not delete user's new name message {message.message_id}: {e}")

    # ۲. اعتبار سنجی نام
    if len(new_name) < 3:
        err_text = escape_markdown(get_string("err_name_too_short", lang_code))
        _safe_edit(uid, original_msg_id, err_text, reply_markup=menu.account_menu(uuid_id, lang_code))
        return

    # ۳. به‌روزرسانی نام در دیتابیس
    if db.update_config_name(uuid_id, new_name):
        # ۴. ارسال پیام موفقیت‌آمیز
        success_text = escape_markdown(get_string("msg_name_changed_success", lang_code))
        
        # دکمه بازگشت به منوی اکانت
        back_button_text = get_string('back', lang_code)
        kb = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(f"🔙 {back_button_text}", callback_data=f"acc_{uuid_id}")
        )
        
        _safe_edit(uid, original_msg_id, success_text, reply_markup=kb, parse_mode="MarkdownV2")
    else:
        # در صورت بروز خطا در دیتابیس
        _safe_edit(uid, original_msg_id, escape_markdown(get_string("err_try_again", lang_code)), 
                   reply_markup=menu.account_menu(uuid_id, lang_code))

def _show_tutorial_main_menu(call: types.CallbackQuery):
    lang_code = db.get_user_language(call.from_user.id)
    prompt = get_string("prompt_select_os", lang_code)
    _safe_edit(call.from_user.id, call.message.message_id, prompt, reply_markup=menu.tutorial_main_menu(lang_code))

def _show_tutorial_os_menu(call: types.CallbackQuery, os_type: str):
    lang_code = db.get_user_language(call.from_user.id)
    prompt = get_string("prompt_select_app", lang_code)
    _safe_edit(call.from_user.id, call.message.message_id, prompt, reply_markup=menu.tutorial_os_menu(os_type, lang_code))

def _send_tutorial_link(call: types.CallbackQuery, os_type: str, app_name: str):
    lang_code = db.get_user_language(call.from_user.id)
    try:
        link = TUTORIAL_LINKS[os_type][app_name]
        app_display_name = f"{os_type.capitalize()} - {app_name.capitalize().replace('_', ' ')}"
        
        header = get_string("tutorial_ready_header", lang_code).format(app_display_name=app_display_name)
        body = get_string("tutorial_ready_body", lang_code)
        text = f"<b>{header}</b>\n\n{body}"
               
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(get_string("btn_view_tutorial", lang_code), url=link))
        kb.add(types.InlineKeyboardButton(get_string("btn_back_to_apps", lang_code), callback_data=f"tutorial_os:{os_type}"))
        
        _safe_edit(call.from_user.id, call.message.message_id, text, reply_markup=kb, parse_mode="HTML")

    except KeyError:
        bot.answer_callback_query(call.id, "خطا: لینک آموزشی برای این مورد یافت نشد.", show_alert=True)
    except Exception as e:
        logger.error(f"Error sending tutorial link: {e}")
        bot.answer_callback_query(call.id, "خطایی در ارسال لینک رخ داد.", show_alert=True)


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
            bot.send_message(uid, "Please select your language:\n\nلطفا زبان خود را انتخاب کنید:", reply_markup=language_selection_menu())

    def process_uuid_step_after_lang(message: types.Message, original_msg_id: int):
        uid, uuid_str = message.chat.id, message.text.strip().lower()
        lang_code = db.get_user_language(uid)

        try:
            bot.delete_message(chat_id=uid, message_id=message.message_id)
        except Exception as e:
            logger.warning(f"Could not delete user's message {message.message_id}: {e}")

        if not validate_uuid(uuid_str):
            prompt = _build_formatted_prompt(get_string("uuid_invalid", lang_code))
            _safe_edit(uid, original_msg_id, prompt)
            bot.register_next_step_handler_by_chat_id(uid, process_uuid_step_after_lang, original_msg_id=original_msg_id)
            return

        info = combined_handler.get_combined_user_info(uuid_str)
        if not info:
            prompt = _build_formatted_prompt(get_string("uuid_not_found", lang_code))
            _safe_edit(uid, original_msg_id, prompt)
            bot.register_next_step_handler_by_chat_id(uid, process_uuid_step_after_lang, original_msg_id=original_msg_id)
            return

        db.add_uuid(uid, uuid_str, info.get("name", get_string('unknown_user', lang_code)))
        _go_back_to_main(message=message, original_msg_id=original_msg_id)


    @bot.callback_query_handler(func=lambda call: call.data.startswith('set_lang:'))
    def handle_language_selection(call: types.CallbackQuery):
        uid, lang_code = call.from_user.id, call.data.split(':')[1]
        db.set_user_language(uid, lang_code)
        bot.answer_callback_query(call.id, get_string("lang_selected", lang_code))

        if db.uuids(uid):
            _go_back_to_main(call=call)
        else:
            raw_text = get_string("start_prompt", lang_code)
            formatted_text = _build_formatted_prompt(raw_text)
            
            _safe_edit(uid, call.message.message_id, formatted_text)
            bot.register_next_step_handler_by_chat_id(uid, process_uuid_step_after_lang, original_msg_id=call.message.message_id)
