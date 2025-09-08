# bot/user_handlers/account.py
import logging
import time
from telebot import types
from datetime import datetime, timedelta
import pytz

# --- Local Imports ---
from ..database import db
from .. import combined_handler
from ..menu import menu
from ..utils import validate_uuid, escape_markdown, _safe_edit
from ..language import get_string
from .info import show_manage_menu  # برای نمایش مجدد لیست اکانت‌ها
from ..config import ADMIN_IDS, MIN_TRANSFER_GB, MAX_TRANSFER_GB, TRANSFER_COOLDOWN_DAYS

logger = logging.getLogger(__name__)
bot, admin_conversations = None, None


def initialize_handlers(b, conv_dict):
    """مقادیر bot و admin_conversations را از فایل اصلی دریافت می‌کند."""
    global bot, admin_conversations
    bot = b
    admin_conversations = conv_dict


# =============================================================================
# 1. Add New Account (UUID)
# =============================================================================

def handle_add_uuid_request(call: types.CallbackQuery):
    """از کاربر می‌خواهد تا UUID جدید را برای افزودن به لیست اکانت‌هایش ارسال کند."""
    uid = call.from_user.id
    lang_code = db.get_user_language(uid)
    
    # اگر کاربر اکانتی نداشته باشد، دکمه لغو او را به منوی اولیه برمی‌گرداند
    cancel_callback = "back_to_start_menu" if not db.uuids(uid) else "manage"
    
    _safe_edit(uid, call.message.message_id, get_string("prompt_add_uuid", lang_code),
               reply_markup=menu.user_cancel_action(back_callback=cancel_callback, lang_code=lang_code),
               parse_mode=None)
               
    bot.register_next_step_handler(call.message, add_uuid_step, original_msg_id=call.message.message_id)


def add_uuid_step(message: types.Message, original_msg_id: int):
    """UUID ارسال شده توسط کاربر را پردازش، اعتبارسنجی و ثبت می‌کند."""
    uid, uuid_str = message.from_user.id, message.text.strip().lower()
    lang_code = db.get_user_language(uid)

    bot.clear_step_handler_by_chat_id(uid)
    
    try:
        bot.delete_message(chat_id=uid, message_id=message.message_id)
    except Exception as e:
        logger.warning(f"Could not delete user's UUID message: {e}")

    _safe_edit(uid, original_msg_id, "⏳ در حال بررسی...", parse_mode=None)

    if not validate_uuid(uuid_str):
        prompt = get_string("uuid_invalid_cancel", lang_code)
        show_manage_menu(message=message, override_text=prompt, target_user_id=uid, target_msg_id=original_msg_id)
        return

    info = combined_handler.get_combined_user_info(uuid_str)
    if not info:
        prompt = get_string("uuid_not_found_panel_cancel", lang_code)
        show_manage_menu(message=message, override_text=prompt, target_user_id=uid, target_msg_id=original_msg_id)
        return
    
    result = db.add_uuid(uid, uuid_str, info.get("name", get_string('unknown_user', lang_code)))
    
    if isinstance(result, dict) and result.get("status") == "confirmation_required":
        handle_shared_account_request(message, result, info, original_msg_id)
    elif isinstance(result, str):
        show_manage_menu(message=message, override_text=get_string(result, lang_code), target_user_id=uid, target_msg_id=original_msg_id)

# =============================================================================
# 2. Change Account Name
# =============================================================================

def handle_change_name_request(call: types.CallbackQuery):
    """از کاربر نام جدیدی برای کانفیگش درخواست می‌کند."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)
    
    try:
        uuid_id = int(call.data.split("_")[1])
        prompt = get_string("prompt_enter_new_name", lang_code)
        
        back_callback = f"acc_{uuid_id}"
        kb = menu.user_cancel_action(back_callback=back_callback, lang_code=lang_code)
        
        _safe_edit(uid, msg_id, escape_markdown(prompt), reply_markup=kb, parse_mode="MarkdownV2")
        
        bot.register_next_step_handler_by_chat_id(uid, process_new_name, uuid_id=uuid_id, original_msg_id=msg_id)
    except (ValueError, IndexError) as e:
        logger.error(f"Error handling change name request for call data '{call.data}': {e}")
        bot.answer_callback_query(call.id, get_string("err_try_again", lang_code), show_alert=True)


def process_new_name(message: types.Message, uuid_id: int, original_msg_id: int):
    """نام جدید را پردازش، در دیتابیس ذخیره و نتیجه را به کاربر اعلام می‌کند."""
    uid, new_name = message.from_user.id, message.text.strip()
    lang_code = db.get_user_language(uid)

    try:
        bot.delete_message(chat_id=uid, message_id=message.message_id)
    except Exception as e:
        logger.warning(f"Could not delete user's new name message {message.message_id}: {e}")

    if len(new_name) < 3:
        err_text = escape_markdown(get_string("err_name_too_short", lang_code))
        _safe_edit(uid, original_msg_id, err_text, reply_markup=menu.account_menu(uuid_id, lang_code))
        return

    if db.update_config_name(uuid_id, new_name):
        success_text = escape_markdown(get_string("msg_name_changed_success", lang_code))
        
        back_button_text = get_string('back', lang_code)
        kb = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(f"🔙 {back_button_text}", callback_data=f"acc_{uuid_id}")
        )
        
        _safe_edit(uid, original_msg_id, success_text, reply_markup=kb, parse_mode="MarkdownV2")
    else:
        _safe_edit(uid, original_msg_id, escape_markdown(get_string("err_try_again", lang_code)),
                   reply_markup=menu.account_menu(uuid_id, lang_code))

# =============================================================================
# 3. Delete/Deactivate Account
# =============================================================================

def handle_delete_account(call: types.CallbackQuery):
    """یک اکانت (UUID) را از لیست کاربر غیرفعال می‌کند."""
    uid = call.from_user.id
    lang_code = db.get_user_language(uid)
    uuid_id = int(call.data.split("_")[1])
    
    db.deactivate_uuid(uuid_id)
    show_manage_menu(call=call, override_text=get_string("msg_account_deleted", lang_code))

# =============================================================================
# 4. Shared Account Management
# =============================================================================

def handle_shared_account_request(message, db_result, user_info, original_msg_id):
    """فرآیند درخواست دسترسی اشتراکی به اکانت را مدیریت می‌کند."""
    owner_id = db_result["owner_id"]
    uuid_id = db_result["uuid_id"]
    requester_info = message.from_user
    uid = requester_info.id

    config_name_escaped = escape_markdown(user_info.get('name', ''))
    requester_name_escaped = escape_markdown(requester_info.first_name)

    requester_details = [f"نام: {requester_name_escaped}", f"آیدی: `{requester_info.id}`"]
    if requester_info.username:
        requester_details.append(f"یوزرنیم: @{escape_markdown(requester_info.username)}")

    requester_details_str = "\n".join(requester_details)
    owner_text = (
        f"⚠️ یک کاربر دیگر قصد دارد به اکانت «{config_name_escaped}» شما متصل شود\\.\n\n"
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


def handle_share_confirmation(call: types.CallbackQuery):
    """پاسخ صاحب اکانت به درخواست اشتراک را پردازش می‌کند."""
    parts = call.data.split(":")
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
            db.add_shared_uuid(requester_id, uuid_str, config_name)
            
            bot.send_message(owner_id, f"✅ تایید شد\\. کاربر `{requester_id}` اکنون به اکانت «{config_name_escaped}» دسترسی دارد\\.", parse_mode="MarkdownV2")
            _safe_edit(requester_id, requester_msg_id, "✅ درخواست تایید شد. در حال به‌روزرسانی لیست اکانت‌ها...", parse_mode=None)
            
            time.sleep(1) 
            
            success_text = f"اکانت «{config_name}» با موفقیت به لیست شما اضافه شد."
            show_manage_menu(call=call, override_text=success_text, target_user_id=requester_id, target_msg_id=requester_msg_id)

        except Exception as e:
            logger.error(f"Error during account sharing confirmation: {e}")
            _safe_edit(requester_id, requester_msg_id, "خطایی در ثبت اطلاعات رخ داد. لطفاً با پشتیبانی تماس بگیرید.")
    
    else: # decision == "no"
        owner_name_escaped = escape_markdown(owner_info.first_name)
        bot.send_message(owner_id, "❌ درخواست رد شد\\.", parse_mode="MarkdownV2")
        requester_message = (
            f"❌ متاسفانه درخواست شما برای اکانت «{config_name_escaped}» توسط کاربر زیر رد شد:\n\n"
            f"نام: {owner_name_escaped}\n"
            f"آیدی: `{owner_id}`"
        )
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت به مدیریت اکانت", callback_data="manage"))
        _safe_edit(requester_id, requester_msg_id, requester_message, reply_markup=kb, parse_mode="MarkdownV2")


def handle_cancel_share_request(call: types.CallbackQuery):
    """درخواست اشتراک ارسال شده را توسط درخواست‌دهنده لغو می‌کند."""
    parts = call.data.split(":")
    owner_id, owner_msg_id = int(parts[1]), int(parts[2])
    
    try:
        bot.edit_message_text("❌ این درخواست توسط کاربر لغو شد.", chat_id=owner_id, message_id=owner_msg_id, reply_markup=None)
    except Exception as e:
        logger.warning(f"Could not edit owner's message upon cancellation: {e}")
        
    show_manage_menu(call=call, override_text="✅ درخواست شما با موفقیت لغو شد.")

# =============================================================================
# 5. Traffic Transfer
# =============================================================================
def start_traffic_transfer(call: types.CallbackQuery):
    """مرحله اول انتقال: بررسی محدودیت زمانی و نمایش منوی انتخاب پنل."""
    uid, msg_id = call.from_user.id, call.message.message_id
    uuid_id = int(call.data.split("_")[2])
    
    last_transfer_time = db.get_last_transfer_timestamp(uuid_id)
    cooldown_period = timedelta(days=TRANSFER_COOLDOWN_DAYS)
    
    if last_transfer_time and (datetime.now(pytz.utc) - last_transfer_time.replace(tzinfo=pytz.utc) < cooldown_period):
        remaining_time = cooldown_period - (datetime.now(pytz.utc) - last_transfer_time.replace(tzinfo=pytz.utc))
        days, rem = divmod(remaining_time.total_seconds(), 86400)
        hours, _ = divmod(rem, 3600)
        error_msg = (f"*{escape_markdown('⏳ محدودیت انتقال ترافیک')}*\n`──────────────────`\n{escape_markdown('شما به تازگی انتقال داشته‌اید.')}\n\n"
                     f"⏱️ {escape_markdown('زمان باقیمانده:')} *{escape_markdown(f'{int(days)} روز و {int(hours)} ساعت')}*")
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔙 {get_string('back', db.get_user_language(uid))}", callback_data=f"acc_{uuid_id}"))
        _safe_edit(uid, msg_id, error_msg, reply_markup=kb)
        return

    ask_for_transfer_panel(uid, msg_id, uuid_id)


def ask_for_transfer_panel(uid: int, msg_id: int, uuid_id: int):
    """از کاربر می‌پرسد که از کدام پنل قصد انتقال دارد."""
    lang_code = db.get_user_language(uid)

    title = get_string("transfer_traffic_title", lang_code)
    rules_title = get_string("transfer_rules_title", lang_code)
    min_rule = get_string("min_transfer_rule", lang_code).format(min_gb=MIN_TRANSFER_GB)
    max_rule = get_string("max_transfer_rule", lang_code).format(max_gb=MAX_TRANSFER_GB)
    cooldown_rule = get_string("cooldown_rule", lang_code).format(days=TRANSFER_COOLDOWN_DAYS)
    select_prompt = get_string("select_server_prompt", lang_code)
    intro = get_string("transfer_traffic_body", lang_code).split('\n\n*')[0]

    # --- ✨ شروع اصلاح اصلی ---
    # ساختن متن به صورت بخش‌بخش برای کنترل کامل روی استایل‌دهی
    prompt = (
        f"*{escape_markdown(title)}*\n"
        f"`──────────────────`\n"
        f"{escape_markdown(intro)}\n\n"
        f"*{escape_markdown(rules_title)}*\n"
        f"`•` {escape_markdown(min_rule)}\n"
        f"`•` {escape_markdown(max_rule)}\n"
        f"`•` {escape_markdown(cooldown_rule)}\n\n"
        f"{escape_markdown(select_prompt)}"
    )
    # --- ✨ پایان اصلاح اصلی ---

    user_uuid_record = db.uuid_by_id(uid, uuid_id)
    kb = types.InlineKeyboardMarkup(row_width=1)
    if user_uuid_record.get('has_access_de'):
        kb.add(types.InlineKeyboardButton(f"{get_string('server_de', lang_code)} 🇩🇪", callback_data=f"transfer_panel_hiddify_{uuid_id}"))
    if user_uuid_record.get('has_access_fr') or user_uuid_record.get('has_access_tr'):
        kb.add(types.InlineKeyboardButton(f"{get_string('server_fr', lang_code)}/ترکیه 🇫🇷🇹🇷", callback_data=f"transfer_panel_marzban_{uuid_id}"))

    kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data=f"acc_{uuid_id}"))
    _safe_edit(uid, msg_id, prompt, reply_markup=kb, parse_mode="MarkdownV2")


def ask_for_transfer_amount(call: types.CallbackQuery):
    """از کاربر مقدار حجم برای انتقال را می‌پرسد."""
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
    
    bot.register_next_step_handler(call.message, get_transfer_amount)


def get_transfer_amount(message: types.Message):
    """مقدار حجم را دریافت و اعتبارسنجی کرده، سپس UUID گیرنده را می‌پرسد."""
    uid, text = message.from_user.id, message.text.strip()
    try:
        bot.delete_message(uid, message.message_id)
    except Exception:
        pass
        
    if uid not in admin_conversations or admin_conversations[uid].get('action') != 'transfer_amount':
        return

    convo = admin_conversations[uid]
    msg_id, uuid_id, panel_type = convo['msg_id'], convo['uuid_id'], convo['panel_type']

    try:
        amount_gb = float(text)
        if not (MIN_TRANSFER_GB <= amount_gb <= MAX_TRANSFER_GB):
            raise ValueError("Amount out of range")

        sender_uuid_record = db.uuid_by_id(uid, uuid_id)
        sender_info = combined_handler.get_combined_user_info(sender_uuid_record['uuid'])
        panel_data = next((p['data'] for p in sender_info.get('breakdown', {}).values() if p.get('type') == panel_type), None)

        if not panel_data or amount_gb > panel_data.get('remaining_GB', 0):
            remaining_gb = panel_data.get('remaining_GB', 0) if panel_data else 0
            error_msg = f"موجودی حجم شما در این سرور ({remaining_gb:.2f} گیگابایت) برای انتقال این مقدار کافی نیست. لطفاً مقدار کمتری وارد کنید:"
            _safe_edit(uid, msg_id, escape_markdown(error_msg), reply_markup=menu.user_cancel_action(f"acc_{uuid_id}", db.get_user_language(uid)))
            bot.register_next_step_handler(message, get_transfer_amount)
            return

        convo.update({'amount_gb': amount_gb, 'action': 'transfer_receiver'})
        prompt = "اکنون لطفاً UUID کاربر گیرنده را ارسال کنید:"
        _safe_edit(uid, msg_id, escape_markdown(prompt), reply_markup=menu.user_cancel_action(f"acc_{uuid_id}", db.get_user_language(uid)))
        bot.register_next_step_handler(message, get_receiver_uuid)

    except (ValueError, TypeError):
        error_msg = f"مقدار وارد شده نامعتبر است. لطفاً عددی بین {MIN_TRANSFER_GB} و {MAX_TRANSFER_GB} وارد کنید."
        _safe_edit(uid, msg_id, escape_markdown(error_msg), reply_markup=menu.user_cancel_action(f"acc_{uuid_id}", db.get_user_language(uid)))
        bot.register_next_step_handler(message, get_transfer_amount)
    except Exception as e:
        logger.error(f"Error in get_transfer_amount: {e}", exc_info=True)
        _safe_edit(uid, msg_id, "خطایی در پردازش اطلاعات رخ داد. عملیات لغو شد.", reply_markup=menu.user_cancel_action(f"acc_{uuid_id}", db.get_user_language(uid)))
        admin_conversations.pop(uid, None)


def get_receiver_uuid(message: types.Message):
    """UUID گیرنده را دریافت و اعتبارسنجی کرده و منوی تایید نهایی را نمایش می‌دهد."""
    uid, receiver_uuid = message.from_user.id, message.text.strip().lower()
    
    try:
        bot.delete_message(uid, message.message_id)
    except Exception:
        pass

    if uid not in admin_conversations or admin_conversations[uid].get('action') != 'transfer_receiver':
        return

    convo = admin_conversations[uid]
    msg_id, uuid_id, panel_type = convo['msg_id'], convo['uuid_id'], convo['panel_type']
    
    sender_uuid_record = db.uuid_by_id(uid, uuid_id)
    if receiver_uuid == sender_uuid_record['uuid']:
        prompt = "شما نمی‌توانید به خودتان ترافیک انتقال دهید. لطفاً UUID کاربر دیگری را وارد کنید:"
        _safe_edit(uid, msg_id, escape_markdown(prompt), reply_markup=menu.user_cancel_action(f"acc_{uuid_id}", db.get_user_language(uid)))
        bot.register_next_step_handler(message, get_receiver_uuid)
        return

    receiver_info = combined_handler.get_combined_user_info(receiver_uuid)
    if not receiver_info:
        prompt = "کاربری با این UUID یافت نشد. لطفاً دوباره تلاش کنید یا عملیات را لغو کنید:"
        _safe_edit(uid, msg_id, escape_markdown(prompt), reply_markup=menu.user_cancel_action(f"acc_{uuid_id}", db.get_user_language(uid)))
        bot.register_next_step_handler(message, get_receiver_uuid)
        return
        
    receiver_has_panel_access = any(p.get('type') == panel_type for p in receiver_info.get('breakdown', {}).values())
    if not receiver_has_panel_access:
        server_name = "آلمان" if panel_type == 'hiddify' else "فرانسه/ترکیه"
        _safe_edit(uid, msg_id, f"کاربر مقصد به سرور {server_name} دسترسی ندارد. لطفاً UUID کاربر دیگری را وارد کنید:", reply_markup=menu.user_cancel_action(f"acc_{uuid_id}", db.get_user_language(uid)))
        bot.register_next_step_handler(message, get_receiver_uuid)
        return

    convo.update({'receiver_uuid': receiver_uuid, 'receiver_name': receiver_info.get('name', 'کاربر ناشناس')})
    
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


def confirm_and_execute_transfer(call: types.CallbackQuery):
    """انتقال را نهایی کرده، حجم‌ها را در پنل‌ها آپدیت و به طرفین اطلاع‌رسانی می‌کند."""
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
    
    try:
        sender_name = sender_uuid_record.get('name', 'کاربر ناشناس')
        
        receiver_uuid_record = db.get_user_uuid_record(receiver_uuid)
        receiver_uuid_id = receiver_uuid_record['id']
        receiver_user_id = receiver_uuid_record['user_id']
        receiver_name = receiver_uuid_record.get('name', 'کاربر ناشناس')

        if not combined_handler.modify_user_on_all_panels(sender_uuid, add_gb=-amount_gb, target_panel_type=panel_type):
            raise Exception(f"Failed to deduct {amount_gb}GB from sender {sender_uuid}")

        if not combined_handler.modify_user_on_all_panels(receiver_uuid, add_gb=amount_gb, target_panel_type=panel_type):
            logger.warning(f"Rolling back traffic transfer. Could not add to receiver. Refunding {amount_gb}GB to {sender_uuid}")
            combined_handler.modify_user_on_all_panels(sender_uuid, add_gb=amount_gb, target_panel_type=panel_type)
            raise Exception(f"Failed to add {amount_gb}GB to receiver {receiver_uuid}")
        
        db.log_traffic_transfer(sender_uuid_id, receiver_uuid_id, panel_type, amount_gb)
        
        def format_amount(gb):
            val_str = str(int(gb)) if gb == int(gb) else str(gb).replace('.', ',')
            return escape_markdown(val_str)

        amount_str = format_amount(amount_gb)
        receiver_name_str = escape_markdown(receiver_name)
        sender_name_str = escape_markdown(sender_name)
        
        sender_final_msg = f"✅ انتقال *{amount_str}* گیگابایت حجم به کاربر *{receiver_name_str}* با موفقیت انجام شد\\."
        kb_back_to_account = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(f"🔙 {get_string('back', db.get_user_language(uid))}", callback_data=f"acc_{sender_uuid_id}")
        )
        _safe_edit(uid, msg_id, sender_final_msg, reply_markup=kb_back_to_account)
        
        receiver_message = f"🎁 شما *{amount_str}* گیگابایت حجم هدیه از طرف کاربر *{sender_name_str}* دریافت کردید\\!"
        _notify_user(receiver_user_id, receiver_message)
        
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


def _notify_user(user_id, message):
    """یک پیام را برای کاربر مشخصی ارسال می‌کند و خطاهای احتمالی را مدیریت می‌کند."""
    if not user_id:
        return
    try:
        bot.send_message(user_id, message, parse_mode="MarkdownV2")
        logger.info(f"Sent notification to user {user_id}")
    except Exception as e:
        logger.warning(f"Failed to send notification to user {user_id}: {e}")