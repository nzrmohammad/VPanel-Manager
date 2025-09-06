import logging
from telebot import types, telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import io
import qrcode
import jdatetime
from .config import ADMIN_IDS, ADMIN_SUPPORT_CONTACT, CARD_PAYMENT_INFO, ADMIN_SUPPORT_CONTACT, TUTORIAL_LINKS, MIN_TRANSFER_GB, MAX_TRANSFER_GB, TRANSFER_COOLDOWN_DAYS, ACHIEVEMENTS 
from .database import db
from . import combined_handler
from .menu import menu
from .utils import validate_uuid, escape_markdown, _safe_edit, get_loyalty_progress_message
from .user_formatters import fmt_one, quick_stats, fmt_service_plans, fmt_panel_quick_stats, fmt_user_payment_history, fmt_registered_birthday_info, fmt_user_usage_history, fmt_referral_page, fmt_user_account_page
from .utils import load_service_plans
from .language import get_string
import urllib.parse
import time
from datetime import datetime, timedelta
import pytz
from typing import Optional
from .hiddify_api_handler import HiddifyAPIHandler
from .marzban_api_handler import MarzbanAPIHandler


logger = logging.getLogger(__name__)
bot = None
admin_conversations = {}

# ======================================================================================
#  اصل کلی: تمام قالب‌بندی‌ها (*, `, _, \) در این فایل انجام می‌شود.
#  فایل‌های JSON فقط حاوی متن خام و بدون قالب‌بندی هستند.
# ======================================================================================
def initialize_user_handlers(b_instance, conversations_dict):
    global bot, admin_conversations
    bot = b_instance
    admin_conversations = conversations_dict

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
        "web_login": _handle_web_login_request,
        "achievements": _show_achievements_page,
        "request_service": _handle_request_service,
        "connection_doctor": _handle_connection_doctor,
        "user_account": _show_user_account_page
    }
    
    handler = USER_CALLBACK_MAP.get(data)
    if handler:
        bot.clear_step_handler_by_chat_id(uid)
        handler(call)
        return
    
    elif data == "show_features_guide":
        _show_features_guide(call)
        return
    elif data == "back_to_start_menu":
        _show_initial_menu(uid=call.from_user.id, msg_id=call.message.message_id)
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

    elif data.startswith("transfer_start_"):
        _start_traffic_transfer(call)
        return
        
    elif data.startswith("transfer_panel_"):
        _ask_for_transfer_amount(call)
        return

    elif data.startswith("transfer_confirm_"):
        _confirm_and_execute_transfer(call)
        return
    
    elif data.startswith("shop:"):
        handle_shop_callbacks(call)
        return
    
    elif data.startswith("referral:"):
        handle_referral_callbacks(call)
        return

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
            config_name = row.get('name', 'CloudVibe')
            WEBAPP_BASE_URL = "https://panel.cloudvibe.ir" 
            
            # ساخت لینک‌های Normal و Base64 با افزودن نام کانفیگ در انتها
            normal_sub_link = f"{WEBAPP_BASE_URL.rstrip('/')}/user/sub/{user_uuid}#{urllib.parse.quote(config_name)}"
            b64_sub_link = f"{WEBAPP_BASE_URL.rstrip('/')}/user/sub/b64/{user_uuid}#{urllib.parse.quote(config_name)}"
            
            # لینک نهایی برای نمایش و QR Code بر اساس انتخاب کاربر
            final_sub_link = b64_sub_link if link_type == 'b64' else normal_sub_link

            # ساخت QR Code
            qr_img = qrcode.make(final_sub_link)
            stream = io.BytesIO()
            qr_img.save(stream, 'PNG')
            stream.seek(0)
            
            # آماده‌سازی متن پیام
            raw_template = get_string("msg_link_ready", lang_code)
            escaped_link = f"`{escape_markdown(final_sub_link)}`"
            message_text = f'*{escape_markdown(raw_template.splitlines()[0].format(link_type=link_type.capitalize()))}*\n\n' + \
                           f'{escape_markdown(raw_template.splitlines()[2])}\n{escaped_link}'

            # ساخت دکمه‌ها
            kb = types.InlineKeyboardMarkup(row_width=2)
            
            # تابع کمکی برای ساخت دکمه‌های افزودن خودکار
            def create_redirect_button(app_name: str, deep_link: str):
                params = {'url': deep_link, 'app_name': app_name}
                query_string = urllib.parse.urlencode(params)
                redirect_page_url = f"{WEBAPP_BASE_URL}/app/redirect?{query_string}"
                return types.InlineKeyboardButton(f"📲 افزودن به {app_name}", url=redirect_page_url)

            # ساخت deep link صحیح برای v2rayng (همیشه با لینک Base64)
            v2rayng_deep_link = f"v2rayng://install-sub/?url={urllib.parse.quote(b64_sub_link)}"
            kb.add(create_redirect_button("V2rayNG", v2rayng_deep_link))

            # ساخت deep link برای سایر اپلیکیشن‌ها
            if link_type == 'b64':
                streisand_deep_link = f"streisand://import/{b64_sub_link}"
                kb.add(create_redirect_button("Streisand", streisand_deep_link))

                v2box_deep_link = f"v2box://import/?url={urllib.parse.quote(b64_sub_link)}"
                kb.add(create_redirect_button("V2Box", v2box_deep_link))

            else: # Normal
                happ_deep_link = f"happ://add/{normal_sub_link}"
                kb.add(create_redirect_button("HAPP", happ_deep_link))

            hiddify_deep_link = f"hiddify://import/{normal_sub_link}"
            kb.add(create_redirect_button("Hiddify", hiddify_deep_link))
            
            # دکمه بازگشت
            kb.add(types.InlineKeyboardButton(get_string("back", lang_code), callback_data=f"getlinks_{uuid_id}"))

            # حذف پیام قبلی و ارسال پیام جدید با عکس
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception as e:
                logger.warning(f"Could not delete old message {call.message.message_id}: {e}")

            bot.send_photo(uid, photo=stream, caption=message_text, reply_markup=kb, parse_mode="MarkdownV2")

        except Exception as e:
            logger.error(f"Failed to generate/send subscription link for UUID {row.get('uuid')}: {e}", exc_info=True)
            bot.answer_callback_query(call.id, escape_markdown(get_string("err_link_generation", lang_code)), show_alert=True)
            _safe_edit(uid, msg_id, escape_markdown(get_string("err_try_again", lang_code)), reply_markup=menu.get_links_menu(uuid_id, lang_code=lang_code))

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
                
                _safe_edit(requester_id, requester_msg_id, "✅ درخواست تایید شد. در حال به‌روزرسانی لیست اکانت‌ها...", parse_mode=None)
                
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
    _safe_edit(uid, original_msg_id, "⏳ در حال بررسی...", parse_mode=None)

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
    """
    Displays the settings menu with the user's current language preference.
    """
    uid = call.from_user.id
    lang_code = db.get_user_language(uid)
    settings_data = db.get_user_settings(uid)
    
    title_text = f'*{escape_markdown(get_string("settings_title", lang_code))}*'
    reply_markup = menu.settings(settings_data, lang_code=lang_code)
    
    _safe_edit(uid, call.message.message_id, text=title_text, reply_markup=reply_markup)


def _go_back_to_main(call: types.CallbackQuery = None, message: types.Message = None, original_msg_id: int = None):
    uid = call.from_user.id if call else message.from_user.id
    msg_id = original_msg_id or (call.message.message_id if call else None)
    
    lang_code = db.get_user_language(uid)
    
    user_db_info = db.user(uid)
    user_points = user_db_info.get('achievement_points', 0) if user_db_info else 0
    
    text_lines = [
        f"*{escape_markdown(get_string('main_menu_title', lang_code))}*",
        "`-----------------`",
        f"💰 {escape_markdown(get_string('fmt_your_points', lang_code))} *{user_points}*"
    ]
    
    loyalty_data = get_loyalty_progress_message(uid)
    if loyalty_data:        
        line1_template = get_string('loyalty_message_line1', lang_code)
        line1_formatted = line1_template.format(payment_count=loyalty_data['payment_count'])
        
        line2_template = get_string('loyalty_message_line2', lang_code)
        renewals_left_str = str(loyalty_data['renewals_left'])
        
        line2_formatted = line2_template.format(
            renewals_left=renewals_left_str,
            gb_reward=loyalty_data['gb_reward'],
            days_reward=loyalty_data['days_reward']
        )
        
        line2_escaped = escape_markdown(line2_formatted)
        
        loyalty_message = line2_escaped.replace(
            escape_markdown(renewals_left_str), 
            f"*{escape_markdown(renewals_left_str)}*"
        )

        text_lines.append(f"{escape_markdown(line1_formatted)}\n{loyalty_message}")
        
    text_lines.append("\n`──────────────────`")
    text_lines.append(f"💡 {escape_markdown(get_string('main_menu_tip', lang_code))}")
    
    text = "\n".join(text_lines)

    reply_markup = menu.main(uid in ADMIN_IDS, lang_code=lang_code)

    if msg_id:
        _safe_edit(uid, msg_id, text, reply_markup=reply_markup)
    else:
        bot.send_message(uid, text, reply_markup=reply_markup, parse_mode="MarkdownV2")

def _show_initial_menu(uid: int, msg_id: int = None):
    """
    منوی خوشامدگویی اولیه را برای کاربران جدید نمایش می‌دهد یا ویرایش می‌کند.
    """
    lang_code = db.get_user_language(uid)
    welcome_text = (
        "<b>Welcome!</b> 👋\n\n"
        "Please choose one of the options below to get started:"
    )
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(f"💳 {get_string('btn_have_service', lang_code)}", callback_data="add"),
        types.InlineKeyboardButton(f"🚀 {get_string('btn_request_service', lang_code)}", callback_data="request_service")
    )
    kb.add(types.InlineKeyboardButton(get_string('btn_features_guide', lang_code), callback_data="show_features_guide"))

    if msg_id:
        _safe_edit(uid, msg_id, welcome_text, reply_markup=kb, parse_mode="HTML")
    else:
        bot.send_message(uid, welcome_text, reply_markup=kb, parse_mode="HTML")

def _handle_birthday_gift_request(call: types.CallbackQuery):
    global bot 
    uid = call.from_user.id
    msg_id = call.message.message_id 
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

def create_redirect_button(app_name: str, deep_link: str, lang_code: str):
    """
    یک دکمه برای ریدایرکت به اپلیکیشن می‌سازد و URL را به درستی encode می‌کند.
    """
    # ✅ **تغییر اصلی:** آدرس دامنه به صورت مستقیم در اینجا تعریف شده است
    WEBAPP_BASE_URL = "https://panel.cloudvibe.ir"
    
    params = {
        'url': deep_link,
        'app_name': app_name
    }
    # استفاده از urlencode برای ساخت صحیح query string
    query_string = urllib.parse.urlencode(params)
    redirect_page_url = f"{WEBAPP_BASE_URL}/app/redirect?{query_string}"
    
    button_text = f"📲 افزودن به {app_name}"
    return types.InlineKeyboardButton(button_text, url=redirect_page_url)

def _notify_user(user_id: Optional[int], message: str):
    if not user_id:
        return
    try:
        bot.send_message(user_id, message, parse_mode="MarkdownV2")
        logger.info(f"Sent notification to user {user_id}")
    except Exception as e:
        logger.warning(f"Failed to send notification to user {user_id}: {e}")

def _start_traffic_transfer(call: types.CallbackQuery):
    """مرحله اول: شروع فرآیند و بررسی محدودیت زمانی."""
    global bot
    uid, msg_id = call.from_user.id, call.message.message_id
    uuid_id = int(call.data.split("_")[2])
    
    last_transfer_time = db.get_last_transfer_timestamp(uuid_id)
    cooldown_period = timedelta(days=TRANSFER_COOLDOWN_DAYS)
    
    if last_transfer_time:
            if last_transfer_time.tzinfo is None:
                last_transfer_time = pytz.utc.localize(last_transfer_time)

            time_since_last_transfer = datetime.now(pytz.utc) - last_transfer_time
            if time_since_last_transfer < cooldown_period:
                remaining_time = cooldown_period - time_since_last_transfer
                days, remainder = divmod(remaining_time.total_seconds(), 86400)
                hours, _ = divmod(remainder, 3600)
                
                error_msg = (
                    f"*{escape_markdown('⏳ محدودیت انتقال ترافیک')}*\n"
                    f"`──────────────────`\n"
                    f"{escape_markdown('شما به تازگی یک انتقال ترافیک داشته‌اید. لطفاً تا پایان این محدودیت صبر کنید.')}\n\n"
                    f"⏱️ {escape_markdown('زمان باقیمانده:')} *{escape_markdown(f'{int(days)} روز و {int(hours)} ساعت')}*"
                )
                
                kb = types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton(f"🔙 {get_string('back', db.get_user_language(uid))}", callback_data=f"acc_{uuid_id}")
                )
                _safe_edit(uid, msg_id, error_msg, reply_markup=kb)
                return

    _ask_for_transfer_panel(uid, msg_id, uuid_id)


def _ask_for_transfer_panel(uid: int, msg_id: int, uuid_id: int):
    """مرحله دوم: از کاربر می‌پرسد از کدام سرور قصد انتقال دارد."""
    from .config import MIN_TRANSFER_GB, MAX_TRANSFER_GB, TRANSFER_COOLDOWN_DAYS
    lang_code = db.get_user_language(uid)

    title = get_string("transfer_traffic_title", lang_code)
    rules_title = get_string("transfer_rules_title", lang_code)
    min_rule = get_string("min_transfer_rule", lang_code).format(min_gb=MIN_TRANSFER_GB)
    max_rule = get_string("max_transfer_rule", lang_code).format(max_gb=MAX_TRANSFER_GB)
    cooldown_rule = get_string("cooldown_rule", lang_code).format(days=TRANSFER_COOLDOWN_DAYS)
    select_prompt = get_string("select_server_prompt", lang_code)

    body = get_string("transfer_traffic_body", lang_code).format(
        rules_title=rules_title,
        min_transfer_rule=min_rule,
        max_transfer_rule=max_rule,
        cooldown_rule=cooldown_rule,
        select_server_prompt=select_prompt
    )

    prompt = f"{title}\n`──────────────────`\n{body}"

    user_uuid_record = db.uuid_by_id(uid, uuid_id)
    kb = types.InlineKeyboardMarkup(row_width=1)
    if user_uuid_record.get('has_access_de'):
        kb.add(types.InlineKeyboardButton(f"{get_string('server_de', lang_code)} 🇩🇪", callback_data=f"transfer_panel_hiddify_{uuid_id}"))
    if user_uuid_record.get('has_access_fr') or user_uuid_record.get('has_access_tr'):
        kb.add(types.InlineKeyboardButton(f"{get_string('server_fr', lang_code)}/ترکیه 🇫🇷🇹🇷", callback_data=f"transfer_panel_marzban_{uuid_id}"))

    kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data=f"acc_{uuid_id}"))
    _safe_edit(uid, msg_id, escape_markdown(prompt), reply_markup=kb)


def _ask_for_transfer_amount(call: types.CallbackQuery):
    """مرحله سوم: پرسیدن مقدار حجم برای انتقال."""
    global bot
    uid, msg_id = call.from_user.id, call.message.message_id
    parts = call.data.split("_")
    panel_type, uuid_id = parts[2], int(parts[3])

    admin_conversations[uid] = {'action': 'transfer_amount', 'msg_id': msg_id, 'uuid_id': uuid_id, 'panel_type': panel_type}
    
    prompt = (
        f"{escape_markdown('لطفاً مقدار حجمی که می‌خواهید انتقال دهید را به گیگابایت وارد کنید.')}\n\n"
        f"🔸 {escape_markdown('حداقل:')} *{escape_markdown(str(MIN_TRANSFER_GB))} {escape_markdown('گیگابایت')}*\n"
        f"🔸 {escape_markdown('حداکثر:')} *{escape_markdown(str(MAX_TRANSFER_GB))} {escape_markdown('گیگابایت')}*"
    )
              
    kb = menu.user_cancel_action(back_callback=f"acc_{uuid_id}", lang_code=db.get_user_language(uid))
    _safe_edit(uid, msg_id, prompt, reply_markup=kb)
    
    bot.register_next_step_handler(call.message, _get_transfer_amount)


def _get_transfer_amount(message: types.Message):
    """مقدار حجم را دریافت، اعتبار‌سنجی کرده و UUID گیرنده را می‌پرسد."""
    global bot
    uid, text = message.from_user.id, message.text.strip()
    try:
        bot.delete_message(uid, message.message_id)
    except Exception:
        pass
        
    if uid not in admin_conversations or admin_conversations[uid].get('action') != 'transfer_amount':
        return

    convo = admin_conversations[uid]
    msg_id = convo['msg_id']
    uuid_id = convo['uuid_id']
    panel_type_to_transfer_from = convo['panel_type']

    try:
        amount_gb = float(text)
        if not (MIN_TRANSFER_GB <= amount_gb <= MAX_TRANSFER_GB):
            raise ValueError("Amount out of range")

        sender_uuid_record = db.uuid_by_id(uid, uuid_id)
        sender_info = combined_handler.get_combined_user_info(sender_uuid_record['uuid'])
        
        panel_data = next((p['data'] for p in sender_info.get('breakdown', {}).values() if p.get('type') == panel_type_to_transfer_from), None)

        if not panel_data:
            raise Exception("Panel data not found for the specified type.")
            
        sender_remaining_gb = panel_data.get('remaining_GB', 0)

        if amount_gb > sender_remaining_gb:
            error_msg = f"موجودی حجم شما در این سرور ({sender_remaining_gb:.2f} گیگابایت) برای انتقال این مقدار کافی نیست. لطفاً مقدار کمتری وارد کنید:"
            _safe_edit(uid, msg_id, escape_markdown(error_msg), reply_markup=menu.user_cancel_action(f"acc_{uuid_id}", db.get_user_language(uid)))
            bot.register_next_step_handler(message, _get_transfer_amount)
            return

        convo['amount_gb'] = amount_gb
        convo['action'] = 'transfer_receiver'
        
        prompt = "اکنون لطفاً UUID کاربر گیرنده را ارسال کنید:"
        _safe_edit(uid, msg_id, escape_markdown(prompt), reply_markup=menu.user_cancel_action(f"acc_{uuid_id}", db.get_user_language(uid)))
        bot.register_next_step_handler(message, _get_receiver_uuid)

    except (ValueError, TypeError):
        error_msg = f"مقدار وارد شده نامعتبر است. لطفاً عددی بین {MIN_TRANSFER_GB} و {MAX_TRANSFER_GB} وارد کنید."
        _safe_edit(uid, msg_id, escape_markdown(error_msg), reply_markup=menu.user_cancel_action(f"acc_{uuid_id}", db.get_user_language(uid)))
        bot.register_next_step_handler(message, _get_transfer_amount)
    except Exception as e:
        logger.error(f"Error in _get_transfer_amount: {e}", exc_info=True)
        _safe_edit(uid, msg_id, "خطایی در پردازش اطلاعات رخ داد. عملیات لغو شد.", reply_markup=menu.user_cancel_action(f"acc_{uuid_id}", db.get_user_language(uid)))
        admin_conversations.pop(uid, None)


def _get_receiver_uuid(message: types.Message):
    """UUID گیرنده را دریافت، اعتبار‌سنجی کرده و منوی تایید نهایی را نمایش می‌دهد."""
    global bot
    uid, receiver_uuid = message.from_user.id, message.text.strip().lower()
    
    # --- ✅ مدیریت خطای حذف پیام ---
    try:
        bot.delete_message(uid, message.message_id)
    except Exception:
        pass # اگر پیام قبلاً حذف شده بود، مشکلی نیست

    if uid not in admin_conversations or admin_conversations[uid].get('action') != 'transfer_receiver':
        return

    convo = admin_conversations[uid]
    msg_id = convo['msg_id']
    uuid_id = convo['uuid_id']
    panel_type = convo['panel_type']
    
    sender_uuid_record = db.uuid_by_id(uid, uuid_id)
    if receiver_uuid == sender_uuid_record['uuid']:
        prompt = "شما نمی‌توانید به خودتان ترافیک انتقال دهید. لطفاً UUID کاربر دیگری را وارد کنید:"
        _safe_edit(uid, msg_id, escape_markdown(prompt), reply_markup=menu.user_cancel_action(f"acc_{uuid_id}", db.get_user_language(uid)))
        bot.register_next_step_handler(message, _get_receiver_uuid) # دوباره منتظر پاسخ می‌مانیم
        return

    receiver_info = combined_handler.get_combined_user_info(receiver_uuid)
    if not receiver_info:
        # --- ✅ مدیریت UUID اشتباه ---
        prompt = "کاربری با این UUID یافت نشد. لطفاً دوباره تلاش کنید یا عملیات را لغو کنید:"
        _safe_edit(uid, msg_id, escape_markdown(prompt), reply_markup=menu.user_cancel_action(f"acc_{uuid_id}", db.get_user_language(uid)))
        bot.register_next_step_handler(message, _get_receiver_uuid) # دوباره منتظر پاسخ می‌مانیم
        return
        
    receiver_has_panel_access = any(p.get('type') == panel_type for p in receiver_info.get('breakdown', {}).values())

    if not receiver_has_panel_access:
        server_name = "آلمان" if panel_type == 'hiddify' else "فرانسه/ترکیه"
        _safe_edit(uid, msg_id, f"کاربر مقصد به سرور {server_name} دسترسی ندارد. لطفاً UUID کاربر دیگری را وارد کنید:", reply_markup=menu.user_cancel_action(f"acc_{uuid_id}", db.get_user_language(uid)))
        bot.register_next_step_handler(message, _get_receiver_uuid) # دوباره منتظر پاسخ می‌مانیم
        return

    convo['receiver_uuid'] = receiver_uuid
    convo['receiver_name'] = receiver_info.get('name', 'کاربر ناشناس')
    
    amount_gb = convo['amount_gb']
    amount_str = str(int(amount_gb)) if amount_gb == int(amount_gb) else str(amount_gb)
    amount_str_safe = amount_str.replace('.', ',')
    
    server_name = "آلمان 🇩🇪" if panel_type == 'hiddify' else "فرانسه/ترکیه 🇫🇷🇹🇷"
    confirm_prompt = (
        f"🚨 *{escape_markdown('تایید نهایی انتقال')}*\n\n"
        f"{escape_markdown('شما در حال انتقال')} *{escape_markdown(amount_str_safe)} {escape_markdown('گیگابایت')}* {escape_markdown('حجم از سرور')} *{escape_markdown(server_name)}* {escape_markdown('به کاربر زیر هستید:')}\n\n"
        f"👤 {escape_markdown('نام:')} *{escape_markdown(convo['receiver_name'])}*\n"
        f"🔑 {escape_markdown('شناسه:')} `{escape_markdown(receiver_uuid)}`\n\n"
        f"{escape_markdown('آیا این اطلاعات را تایید می‌کنید؟ این عمل غیرقابل بازگشت است.')}"
    )
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ بله، انتقال بده", callback_data="transfer_confirm_yes"),
        types.InlineKeyboardButton("❌ خیر، لغو کن", callback_data=f"acc_{uuid_id}")
    )
    _safe_edit(uid, msg_id, confirm_prompt, reply_markup=kb)


# In bot/user_handlers.py

def _confirm_and_execute_transfer(call: types.CallbackQuery):
    """(Transaction-Safe) انتقال را نهایی کرده، حجم‌ها را به دقت محاسبه و به همه طرفین اطلاع‌رسانی می‌کند."""
    global bot
    uid, msg_id = call.from_user.id, call.message.message_id
    if uid not in admin_conversations: return
    
    convo = admin_conversations.pop(uid)
    sender_uuid_id = convo['uuid_id']
    receiver_uuid = convo['receiver_uuid']
    panel_type = convo['panel_type']
    amount_gb = convo['amount_gb']

    _safe_edit(uid, msg_id, escape_markdown("⏳ در حال انجام انتقال لطفا صبر کنید..."), reply_markup=None)

    sender_uuid_record = db.uuid_by_id(uid, sender_uuid_id)
    sender_uuid = sender_uuid_record['uuid']
    
    # --- START OF FIX: Transaction Logic ---
    try:
        # --- دریافت اطلاعات اولیه ---
        sender_name = sender_uuid_record.get('name', 'کاربر ناشناس')
        
        receiver_uuid_record = db.get_user_uuid_record(receiver_uuid)
        receiver_uuid_id = receiver_uuid_record['id']
        receiver_user_id = receiver_uuid_record['user_id']
        receiver_name = receiver_uuid_record.get('name', 'کاربر ناشناس')

        # ۱. کم کردن حجم از فرستنده
        success1 = combined_handler.modify_user_on_all_panels(sender_uuid, add_gb=-amount_gb, target_panel_type=panel_type)
        if not success1:
            raise Exception(f"Failed to deduct {amount_gb}GB from sender {sender_uuid}")

        # ۲. اضافه کردن حجم به گیرنده
        success2 = combined_handler.modify_user_on_all_panels(receiver_uuid, add_gb=amount_gb, target_panel_type=panel_type)
        if not success2:
            # اگر اضافه کردن به گیرنده با خطا مواجه شد، حجم را به فرستنده بازگردان (Rollback)
            logger.warning(f"Rolling back traffic transfer. Could not add to receiver. Refunding {amount_gb}GB to {sender_uuid}")
            combined_handler.modify_user_on_all_panels(sender_uuid, add_gb=amount_gb, target_panel_type=panel_type)
            raise Exception(f"Failed to add {amount_gb}GB to receiver {receiver_uuid}")
        
        # ۳. ثبت لاگ در دیتابیس فقط در صورت موفقیت کامل
        db.log_traffic_transfer(sender_uuid_id, receiver_uuid_id, panel_type, amount_gb)
        
        # ۴. ارسال پیام‌های موفقیت
        def format_amount(gb):
            val_str = str(int(gb)) if gb == int(gb) else str(gb).replace('.', ',')
            return escape_markdown(val_str)

        amount_str = format_amount(amount_gb)
        receiver_name_str = escape_markdown(receiver_name)
        sender_name_str = escape_markdown(sender_name)
        
        # پیام به فرستنده
        sender_final_msg = (
            f"✅ انتقال *{amount_str}* گیگابایت حجم به کاربر *{receiver_name_str}* با موفقیت انجام شد\\."
        )
        kb_back_to_account = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(f"🔙 {get_string('back', db.get_user_language(uid))}", callback_data=f"acc_{sender_uuid_id}")
        )
        _safe_edit(uid, msg_id, sender_final_msg, reply_markup=kb_back_to_account)
        
        # پیام به گیرنده
        receiver_message = (
            f"🎁 شما *{amount_str}* گیگابایت حجم هدیه از طرف کاربر *{sender_name_str}* دریافت کردید\\!"
        )
        _notify_user(receiver_user_id, receiver_message)
        
        # پیام به ادمین‌ها
        server_name = 'آلمان 🇩🇪' if panel_type == 'hiddify' else 'فرانسه/ترکیه 🇫🇷🇹🇷'
        admin_message = (
            f"💸 *اطلاع‌رسانی انتقال ترافیک*\n\n"
            f"*{escape_markdown('فرستنده:')}* {sender_name_str} \\(`{uid}`\\)\n"
            f"*{escape_markdown('گیرنده:')}* {receiver_name_str} \\(`{receiver_user_id}`\\)\n"
            f"*{escape_markdown('مقدار:')}* {amount_str} {escape_markdown('گیگابایت')}\n"
            f"*{escape_markdown('سرور:')}* {escape_markdown(server_name)}"
        )
        for admin_id in ADMIN_IDS:
            _notify_user(admin_id, admin_message)
            
    except Exception as e:
        logger.error(f"Error during traffic transfer execution: {e}", exc_info=True)
        _safe_edit(uid, msg_id, escape_markdown("❌ خطایی در هنگام انتقال رخ داد. لطفاً با پشتیبانی تماس بگیرید."), reply_markup=menu.user_cancel_action(f"acc_{sender_uuid_id}", db.get_user_language(uid)))
    # --- END OF FIX ---


def _show_achievements_page(call: types.CallbackQuery):
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)
    
    user_badges = db.get_user_achievements(uid)
    unlocked_lines = []
    
    for code in user_badges:
        badge_data = ACHIEVEMENTS.get(code, {})
        unlocked_lines.append(f"{badge_data.get('icon', '🎖️')} *{escape_markdown(badge_data.get('name', code))}*\n{escape_markdown(badge_data.get('description', '...'))}")

    title = f"*{escape_markdown(get_string('achievements_page_title', lang_code))}*"
    
    if not unlocked_lines:
        intro_text = get_string("achievements_intro", lang_code)
        final_text = f"{title}\n\n{escape_markdown(intro_text)}"
    else:
        unlocked_section_title = get_string("achievements_unlocked_section", lang_code)
        unlocked_section = f"*{escape_markdown(unlocked_section_title)}*\n" + "\n\n".join(unlocked_lines)
        final_text = f"{title}\n\n{unlocked_section}"
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
    
    _safe_edit(uid, msg_id, final_text, reply_markup=kb)


def _handle_connection_doctor(call: types.CallbackQuery):
    """
    (نسخه نهایی و امن‌شده) وضعیت سرویس کاربر و سرورها را با escape کردن صحیح تمام کاراکترها بررسی می‌کند.
    """
    uid = call.from_user.id
    msg_id = call.message.message_id
    lang_code = db.get_user_language(uid)

    _safe_edit(uid, msg_id, escape_markdown(get_string("doctor_checking_status", lang_code)), reply_markup=None)
    
    report_lines = [
        f"*{escape_markdown(get_string('doctor_report_title', lang_code))}*",
        "`──────────────────`"
    ]
    
    user_uuids = db.uuids(uid)
    if not user_uuids:
        _go_back_to_main(call=call)
        return
        
    user_info = combined_handler.get_combined_user_info(user_uuids[0]['uuid'])
    account_status_label = escape_markdown(get_string('doctor_account_status_label', lang_code))
    
    if user_info and user_info.get('is_active') and (user_info.get('expire') is None or user_info.get('expire') >= 0):
        status_text = f"*{escape_markdown(get_string('fmt_status_active', lang_code))}*"
        report_lines.append(f"✅ {account_status_label} {status_text}")
    else:
        status_text = f"*{escape_markdown(get_string('fmt_status_inactive', lang_code))}*"
        report_lines.append(f"❌ {account_status_label} {status_text}")

    active_panels = db.get_active_panels()
    for panel in active_panels:
        panel_name = escape_markdown(panel.get('name', '...'))
        server_status_label = escape_markdown(get_string('doctor_server_status_label', lang_code).format(panel_name=panel_name))
        
        handler = HiddifyAPIHandler(panel) if panel['panel_type'] == 'hiddify' else MarzbanAPIHandler(panel)
        if handler.check_connection():
            status_text = f"*{escape_markdown(get_string('server_status_online', lang_code))}*"
            report_lines.append(f"✅ {server_status_label} {status_text}")
        else:
            status_text = f"*{escape_markdown(get_string('server_status_offline', lang_code))}*"
            report_lines.append(f"🚨 {server_status_label} {status_text}")

    online_hiddify_count, online_marzban_fr_count, online_marzban_tr_count = 'N/A', 'N/A', 'N/A'
    try:
        all_users = combined_handler.get_all_users_combined()
        now_utc = datetime.now(pytz.utc)
        online_deadline = now_utc - timedelta(minutes=15)
        online_hiddify_count, online_marzban_fr_count, online_marzban_tr_count = 0, 0, 0
        for user in all_users:
            last_online = user.get('last_online')
            if not last_online or not isinstance(last_online, datetime): continue
            last_online_aware = last_online if last_online.tzinfo else pytz.utc.localize(last_online)
            if last_online_aware > online_deadline:
                breakdown = user.get('breakdown', {})
                h_online = next((p['data'].get('last_online') for p in breakdown.values() if p.get('type') == 'hiddify'), None)
                m_online = next((p['data'].get('last_online') for p in breakdown.values() if p.get('type') == 'marzban'), None)
                if h_online and (not m_online or h_online >= m_online): online_hiddify_count += 1
                elif m_online:
                    db_record = db.get_user_uuid_record(user.get('uuid'))
                    if db_record:
                        if db_record.get('has_access_fr'): online_marzban_fr_count += 1
                        if db_record.get('has_access_tr'): online_marzban_tr_count += 1
    except Exception as e:
        logger.error(f"Error calculating online users for connection doctor: {e}", exc_info=True)
    
    analysis_title = escape_markdown(get_string('doctor_analysis_title_v2', lang_code))
    line_template = get_string('doctor_online_users_line_v2', lang_code)
    
    report_lines.extend([
        "`──────────────────`",
        f"📈 *{analysis_title}*",
        escape_markdown(line_template.format(count=online_hiddify_count, server_name="آلمان 🇩🇪")),
        escape_markdown(line_template.format(count=online_marzban_fr_count, server_name="فرانسه 🇫🇷")),
        escape_markdown(line_template.format(count=online_marzban_tr_count, server_name="ترکیه 🇹🇷"))
    ])
    
    report_lines.extend([
        "`──────────────────`",
        f"💡 *{escape_markdown(get_string('doctor_suggestion_title', lang_code))}*\n{escape_markdown(get_string('doctor_suggestion_body', lang_code))}"
    ])
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
    _safe_edit(uid, msg_id, "\n".join(report_lines), reply_markup=kb)


def _handle_request_service(call: types.CallbackQuery):
    """درخواست کاربر جدید را به ادمین‌ها اطلاع می‌دهد."""
    user_info = call.from_user
    uid = user_info.id
    msg_id = call.message.message_id

    # اطلاع‌رسانی به کاربر
    _safe_edit(uid, msg_id, escape_markdown("✅ درخواست شما برای مدیران ارسال شد. لطفاً منتظر بمانید تا با شما تماس بگیرند."), reply_markup=None)

    # ساخت پیام برای ادمین‌ها
    user_name = escape_markdown(user_info.first_name)
    admin_message = [f"👤 *درخواست سرویس جدید*\n\n*کاربر:* {user_name} \\(`{uid}`\\)"]
    if user_info.username:
        admin_message.append(f"*یوزرنیم:* @{escape_markdown(user_info.username)}")


    # بررسی اینکه آیا کاربر معرف داشته یا نه
    referrer_info = db.get_referrer_info(uid)
    if referrer_info:
        referrer_name = escape_markdown(referrer_info['referrer_name'])
        admin_message.append(f"*معرف:* {referrer_name} \\(`{referrer_info['referred_by_user_id']}`\\)")

    # ارسال پیام به تمام ادمین‌ها
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, "\n".join(admin_message), parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"Failed to send new service request to admin {admin_id}: {e}")

def handle_shop_callbacks(call: types.CallbackQuery):
    """تمام callback های مربوط به فروشگاه دستاوردها را مدیریت می‌کند."""
    uid, msg_id, data = call.from_user.id, call.message.message_id, call.data
    
    if data == "shop:main":
        user = db.user(uid)
        user_points = user.get('achievement_points', 0) if user else 0
        
        prompt = (
            f"🛍️ *{escape_markdown('فروشگاه دستاوردها')}*\n\n"
            f"{escape_markdown('با امتیازهایی که از کسب دستاوردها به دست آورده‌اید، می‌توانید جوایز زیر را خریداری کنید.')}\n\n"
            f"💰 *{escape_markdown('موجودی امتیاز شما:')} {user_points}*"
        )
        _safe_edit(uid, msg_id, prompt, reply_markup=menu.achievement_shop_menu(user_points))

    elif data.startswith("shop:buy:"):
        item_key = data.split(":")[2]
        from .config import ACHIEVEMENT_SHOP_ITEMS
        item = ACHIEVEMENT_SHOP_ITEMS.get(item_key)
        
        if not item:
            bot.answer_callback_query(call.id, "❌ آیتم مورد نظر یافت نشد.", show_alert=True)
            return

        if db.spend_achievement_points(uid, item['cost']):
            user_uuids = db.uuids(uid)
            if user_uuids:
                # جایزه به اولین اکانت کاربر اضافه می‌شود
                combined_handler.modify_user_on_all_panels(user_uuids[0]['uuid'], add_gb=item['gb'], add_days=item['days'])
                db.log_shop_purchase(uid, item_key, item['cost'])
                bot.answer_callback_query(call.id, f"✅ خرید شما با موفقیت انجام و به اکانتتان اضافه شد.", show_alert=True)
                
                # رفرش کردن منوی فروشگاه
                user = db.user(uid)
                user_points = user.get('achievement_points', 0) if user else 0
                _safe_edit(uid, msg_id, escape_markdown(f"🛍️ *فروشگاه دستاوردها*\n\nموجودی امتیاز شما: {user_points}"), reply_markup=menu.achievement_shop_menu(user_points))
        else:
            bot.answer_callback_query(call.id, "❌ امتیاز شما برای خرید این آیتم کافی نیست.", show_alert=True)

    elif data == "shop:insufficient_points":
        bot.answer_callback_query(call.id, "❌ امتیاز شما برای خرید این آیتم کافی نیست.", show_alert=False)

def handle_referral_callbacks(call: types.CallbackQuery):
    """تمام callback های مربوط به سیستم معرفی کاربران را مدیریت می‌کند."""
    uid, msg_id, data = call.from_user.id, call.message.message_id, call.data

    if data == "referral:info":
        bot_username = bot.get_me().username
        text = fmt_referral_page(uid, bot_username)

        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', db.get_user_language(uid))}", callback_data="back"))

        _safe_edit(uid, msg_id, text, reply_markup=kb)

def _show_features_guide(call: types.CallbackQuery):
    """یک پیام راهنمای کلی درباره امکانات ربات نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)

    guide_title = get_string("features_guide_title", lang_code)
    guide_body = get_string("features_guide_body", lang_code)
    guide_text = f"{guide_title}\n\n{guide_body}"

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back_to_start_menu"))

    _safe_edit(uid, msg_id, escape_markdown(guide_text), reply_markup=kb)

# In bot/user_handlers.py

def _show_user_account_page(call: types.CallbackQuery):
    """صفحه کامل حساب کاربری را نمایش می‌دهد."""
    uid = call.from_user.id
    msg_id = call.message.message_id
    lang_code = db.get_user_language(uid)
    
    text = fmt_user_account_page(uid, lang_code)
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
    
    _safe_edit(uid, msg_id, text, reply_markup=kb)

# =============================================================================
# Main Registration Function
# =============================================================================
def register_user_handlers(b: telebot.TeleBot):
    """Registers all the message and callback handlers for user interactions."""
    global bot
    bot = b

    @bot.message_handler(commands=['start'])
    def cmd_start(message: types.Message):
        uid = message.from_user.id
        db.add_or_update_user(uid, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
        
        # بررسی وجود کد معرف در دستور استارت
        parts = message.text.split()
        if len(parts) > 1:
            referral_code = parts[1]
            # فقط در صورتی کد معرف را ثبت کن که کاربر از قبل معرف نداشته باشد
            if not db.user(uid).get('referred_by_user_id'):
                db.set_referrer(uid, referral_code)

        if db.uuids(uid):
            # اگر کاربر از قبل اکانت دارد، مستقیم به منوی اصلی برود
            _go_back_to_main(message=message)
        else:
            # اگر کاربر جدید است، از تابع کمکی برای نمایش منو استفاده می‌کنیم
            _show_initial_menu(uid=uid)

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
        """
        Handles language selection and ensures the user is returned to the settings menu.
        """
        uid, lang_code = call.from_user.id, call.data.split(':')[1]
        db.set_user_language(uid, lang_code)
        bot.answer_callback_query(call.id, get_string("lang_selected", lang_code))

        # FIX: Always show the settings menu again after changing the language.
        # This provides a better user experience as they remain in the same context.
        _show_settings(call)
