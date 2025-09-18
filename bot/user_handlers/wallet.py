import logging
from telebot import types
from ..database import db
from ..menu import menu
from ..utils import escape_markdown, _safe_edit, load_service_plans, to_shamsi, parse_volume_string
from ..user_formatters import fmt_purchase_summary
from ..admin_formatters import fmt_admin_purchase_notification
from ..language import get_string
from ..config import LOYALTY_REWARDS, REFERRAL_REWARD_GB, REFERRAL_REWARD_DAYS, ACHIEVEMENTS, ADMIN_IDS, CARD_PAYMENT_INFO, ADMIN_SUPPORT_CONTACT
from .. import combined_handler
from telebot.apihelper import ApiTelegramException
from html import escape


logger = logging.getLogger(__name__)
bot, admin_conversations = None, None

def initialize_handlers(b, conv_dict):
    """مقادیر bot و admin_conversations را از فایل اصلی دریافت می‌کند."""
    global bot, admin_conversations
    bot = b
    admin_conversations = conv_dict

def _notify_user(user_id, message):
    """یک پیام را برای کاربر مشخصی ارسال می‌کند و خطاهای احتمالی را مدیریت می‌کند."""
    if not user_id:
        return
    try:
        bot.send_message(user_id, message, parse_mode="MarkdownV2")
        logger.info(f"Sent notification to user {user_id}")
    except Exception as e:
        logger.warning(f"Failed to send notification to user {user_id}: {e}")

def handle_wallet_callbacks(call: types.CallbackQuery):
    """مسیریاب اصلی برای تمام callback های مربوط به کیف پول."""
    try:
        action_parts = call.data.split(':')
        action = action_parts[1]

        if action == 'main':
            show_wallet_main(call)
        elif action == 'charge':
            start_charge_flow(call)
        elif action == 'history':
            show_wallet_history(call)
        elif action == 'buy_confirm':
            plan_name = ":".join(action_parts[2:])
            confirm_purchase(call, plan_name)
        elif action == 'buy_execute':
            plan_name = ":".join(action_parts[2:])
            execute_purchase(call, plan_name)
        elif action == 'insufficient':
            uid, msg_id = call.from_user.id, call.message.message_id
            lang_code = db.get_user_language(uid)
            user_balance = (db.user(uid) or {}).get('wallet_balance', 0.0)
            
            error_text = (
                f"*{escape_markdown('موجودی ناکافی!')}*\n\n"
                f"{escape_markdown(f'موجودی فعلی کیف پول شما ({user_balance:,.0f} تومان) برای انجام این خرید کافی نیست.')}"
            )
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton(f"➕ {get_string('charge_wallet', lang_code)}", callback_data="wallet:charge"))
            kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="view_plans"))
            
            _safe_edit(uid, msg_id, error_text, reply_markup=kb)
        elif action == 'settings':
            show_wallet_settings(call)
        elif action == 'toggle_auto_renew':
            toggle_auto_renew(call)
        elif action == 'transfer_start':
            start_transfer_flow(call)
        elif action == 'transfer_execute':
            execute_wallet_transfer(call)
        elif action == 'gift_start':
            start_gift_flow(call)
        elif action == 'gift_plan_select':
            plan_name = ":".join(action_parts[2:])
            confirm_gift_purchase(call, plan_name)
        elif action == 'gift_execute':
            plan_name = ":".join(action_parts[2:])
            execute_gift_purchase(call)
    except IndexError:
        logger.warning(f"Invalid wallet callback received: {call.data}")
        bot.answer_callback_query(call.id, "دستور نامعتبر است.", show_alert=True)

def show_wallet_main(call: types.CallbackQuery):
    """منوی اصلی کیف پول را نمایش می‌دهد."""
    uid = call.from_user.id
    user_data = db.user(uid)
    balance = user_data.get('wallet_balance', 0.0) if user_data else 0.0
    lang_code = db.get_user_language(uid)
    
    _safe_edit(uid, call.message.message_id, f"*{escape_markdown(get_string('wallet', lang_code))}*",
               reply_markup=menu.wallet_main_menu(balance, lang_code))

def start_charge_flow(call: types.CallbackQuery):
    """از کاربر می‌خواهد مبلغ مورد نظر برای شارژ را وارد کند."""
    uid = call.from_user.id
    lang_code = db.get_user_language(uid)
    prompt = "لطفاً مبلغی که می‌خواهید کیف پول خود را شارژ کنید \\(به تومان\\) وارد نمایید:\n\n*مثال: 50000*"
    _safe_edit(uid, call.message.message_id, prompt,
               reply_markup=menu.user_cancel_action("wallet:main", lang_code=lang_code))
    bot.register_next_step_handler(call.message, get_charge_amount, original_msg_id=call.message.message_id)

def get_charge_amount(message: types.Message, original_msg_id: int):
    """مبلغ شارژ را دریافت کرده و اطلاعات کارت را برای کاربر ارسال می‌کند."""
    uid = message.from_user.id
    lang_code = db.get_user_language(uid)
    try:
        bot.delete_message(uid, message.message_id)
    except Exception:
        pass

    try:
        amount = int(message.text.strip())
        if amount < 1000: 
            raise ValueError("مبلغ کمتر از حد مجاز است")
        
        db.create_charge_request(uid, amount, original_msg_id)
        
        card_info = (
            f"*{escape_markdown('اطلاعات پرداخت')}*\n\n"
            f"لطفاً مبلغ `{amount:,.0f}` تومان به کارت زیر واریز کرده و سپس از رسید پرداخت اسکرین‌شات گرفته و آن را در همین صفحه ارسال کنید\\.\n\n"
            f"*{escape_markdown(CARD_PAYMENT_INFO.get('card_holder', ''))}*\n"
            f"`{escape_markdown(CARD_PAYMENT_INFO.get('card_number', ''))}`\n\n"
            f"⚠️ {escape_markdown('توجه: پس از ارسال رسید، باید منتظر تایید ادمین بمانید.')}"
        )
        _safe_edit(uid, original_msg_id, card_info,
                         reply_markup=menu.user_cancel_action("wallet:main", lang_code))
        bot.register_next_step_handler(message, get_receipt, original_msg_id=original_msg_id)

    except (ValueError, TypeError):
        error_prompt = escape_markdown("❌ مبلغ وارد شده نامعتبر است. لطفاً فقط عدد و حداقل ۱,۰۰۰ تومان وارد کنید.\n\n*مثال صحیح: 50000*")
        # ✅ اصلاح اصلی: parse_mode="MarkdownV2" اضافه شد تا استایل صحیح اعمال شود
        _safe_edit(uid, original_msg_id, error_prompt, 
                   reply_markup=menu.user_cancel_action("wallet:main", lang_code), parse_mode="MarkdownV2")
        bot.register_next_step_handler(message, get_charge_amount, original_msg_id=original_msg_id)

def get_receipt(message: types.Message, original_msg_id: int):
    """رسید پرداخت را از کاربر دریافت کرده و برای ادمین ارسال می‌کند."""
    uid = message.from_user.id
    lang_code = db.get_user_language(uid)
    try:
        bot.delete_message(uid, message.message_id)
    except Exception:
        pass

    charge_request = db.get_pending_charge_request(uid, original_msg_id)
    if not charge_request or not message.photo:
        bot.clear_step_handler_by_chat_id(uid)
        return

    amount = charge_request['amount']
    
    wait_message = escape_markdown("✅ رسید شما دریافت شد. پس از تایید توسط ادمین، حساب شما شارژ خواهد شد.")
    _safe_edit(uid, original_msg_id, wait_message, 
               reply_markup=menu.user_cancel_action("wallet:main", lang_code))
    
    user_info = message.from_user
    user_db_data = db.user(uid)
    current_balance = user_db_data.get('wallet_balance', 0.0) if user_db_data else 0.0

    caption_lines = [
        "💸 *درخواست شارژ کیف پول جدید*",
        f"🆔 *شناسه درخواست:* `{charge_request['id']}`",
        "",
        f"👤 *نام کاربر:* {escape_markdown(user_info.first_name)}",
        f"🆔 *ایدی:* `{user_info.id}`"
    ]
    if user_info.username:
        caption_lines.append(f"🔗 *یوزرنیم:* @{escape_markdown(user_info.username)}")
    
    caption_lines.extend([
        f"💰 *موجودی فعلی:* `{current_balance:,.0f}` تومان",
        "",
        f"💳 *مبلغ درخواستی:* `{amount:,.0f}` تومان"
    ])
    
    caption = "\n".join(caption_lines)
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ تایید", callback_data=f"admin:charge_confirm:{charge_request['id']}"),
        types.InlineKeyboardButton("❌ رد", callback_data=f"admin:charge_reject:{charge_request['id']}")
    )
    
    for admin_id in ADMIN_IDS:
        try:
            bot.send_photo(admin_id, message.photo[-1].file_id, caption=caption, reply_markup=kb, parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"Failed to forward receipt to admin {admin_id}: {e}")

def cancel_charge_request(call: types.CallbackQuery):
    """درخواست شارژ را توسط کاربر لغو می‌کند."""
    uid = call.from_user.id
    admin_msg_ids_str = call.data.split(':')[2]
    admin_msg_ids = admin_msg_ids_str.split('_')
    
    # ویرایش پیام خود کاربر
    _safe_edit(uid, call.message.message_id, escape_markdown("❌ درخواست شارژ شما با موفقیت لغو شد."),
               reply_markup=menu.user_cancel_action("wallet:main", db.get_user_language(uid)))
    
    # ویرایش تمام پیام‌های ارسال شده به ادمین‌ها
    for msg_id_info in admin_msg_ids:
        try:
            admin_id, msg_id = msg_id_info.split('-')
            original_caption = bot.get_chat(int(admin_id)).photo.caption if bot.get_chat(int(admin_id)).photo else ""
            bot.edit_message_caption(caption=f"{original_caption}\n\n❌ این درخواست توسط کاربر لغو شد.",
                                     chat_id=int(admin_id), message_id=int(msg_id))
        except Exception as e:
            logger.warning(f"Could not edit admin message {msg_id_info} upon cancellation: {e}")

def show_wallet_history(call: types.CallbackQuery):
    """تاریخچه تراکنش‌های کیف پول را نمایش می‌دهد."""
    uid = call.from_user.id
    history = db.get_wallet_history(uid)
    lang_code = db.get_user_language(uid)
    
    lines = [f"📜 *{escape_markdown(get_string('transaction_history', lang_code))}*"]
    if not history:
        lines.append(f"\n{escape_markdown('هیچ تراکنشی برای نمایش وجود ندارد.')}")
    else:
        for trans in history:
            amount = trans['amount']
            trans_type = trans['type']
            emoji = "➕" if trans_type == 'deposit' else "➖"
            amount_str = f"{abs(amount) :,.0f}"
            date_str = to_shamsi(trans['transaction_date'], include_time=True)
            description = escape_markdown(trans.get('description', ''))
            
            lines.append(f"──────────────────\n{emoji} *{amount_str} تومان* \n {description} \n {escape_markdown(date_str)}")

    _safe_edit(uid, call.message.message_id, "\n".join(lines),
               reply_markup=menu.user_cancel_action("wallet:main", lang_code))

def confirm_purchase(call: types.CallbackQuery, plan_name: str):
    """از کاربر برای خرید سرویس با کیف پول تاییدیه می‌گیرد و پیش‌نمایش خرید را نمایش می‌دهد."""
    uid = call.from_user.id
    lang_code = db.get_user_language(uid)
    plans = load_service_plans()
    plan_to_buy = next((p for p in plans if p.get('name') == plan_name), None)

    if not plan_to_buy:
        bot.answer_callback_query(call.id, "خطا: پلن مورد نظر یافت نشد.", show_alert=True)
        return

    user_uuids = db.uuids(uid)
    if not user_uuids:
        bot.answer_callback_query(call.id, "خطا: شما هیچ اکانت فعالی برای اعمال پلن ندارید.", show_alert=True)
        return
        
    user_main_uuid = user_uuids[0]['uuid']
    info_before = combined_handler.get_combined_user_info(user_main_uuid)
    user_uuid_record = db.get_user_uuid_record(user_main_uuid)
    plan_type = plan_to_buy.get('type')

    has_access = False
    if plan_type == 'germany' and user_uuid_record.get('has_access_de'):
        has_access = True
    elif plan_type in ['france', 'turkey'] and (user_uuid_record.get('has_access_fr') or user_uuid_record.get('has_access_tr')):
        has_access = True
    elif plan_type == 'combined' and user_uuid_record.get('has_access_de') and (user_uuid_record.get('has_access_fr') or user_uuid_record.get('has_access_tr')):
        has_access = True
    
    access_text = ""
    if has_access:
        access_text = f"✅ *{escape_markdown('دسترسی به سرور:')}* {escape_markdown('شما به این سرور دسترسی دارید.')}"
    else:
        access_text = f"⚠️ *{escape_markdown('دسترسی به سرور:')}* {escape_markdown('شما به این سرور دسترسی ندارید. پس از خرید، برای فعال‌سازی با پشتیبانی تماس بگیرید.')}"

    limit_before = info_before.get('usage_limit_GB', 0)
    expire_before = info_before.get('expire', 0) if info_before.get('expire') is not None else 'نامحدود'
    escaped_expire_before = escape_markdown(str(expire_before))
    price = plan_to_buy.get('price', 0)
    
    confirm_text = (
        f"*{escape_markdown('🔍 پیش‌نمایش خرید')}*\n"
        f"`──────────────────`\n"
        f"*{escape_markdown('سرویس فعلی شما:')}*\n"
        f"`•` {escape_markdown('📊 حجم کل:')} *{info_before.get('usage_limit_GB', 0):g} GB*\n"
        f"`•` {escape_markdown('📅 اعتبار:')} *{escaped_expire_before} روز*\n\n" # <--- مشکل با این تغییر حل شد
        f"*{escape_markdown('پلن انتخابی:')}*\n"
        f"`•` {escape_markdown('🛍️ نام:')} *{escape_markdown(plan_name)}*\n"
        f"`•` {access_text}\n"
        f"`──────────────────`\n"
        f"❓ *{escape_markdown('تایید نهایی')}*\n"
        f"{escape_markdown(f'مبلغ {plan_to_buy.get("price", 0):,.0f} تومان از کیف پول شما کسر خواهد شد. آیا ادامه می‌دهید؟')}"
    )

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ بله، خرید", callback_data=f"wallet:buy_execute:{plan_name}"),
        types.InlineKeyboardButton("❌ انصراف", callback_data=f"show_plans:{plan_to_buy.get('type')}"))
    
    _safe_edit(uid, call.message.message_id, confirm_text, reply_markup=kb)

def execute_purchase(call: types.CallbackQuery, plan_name: str):
    """(نسخه نهایی) خرید را نهایی کرده، رکورد پرداخت و پاداش‌ها را ثبت و به ادمین اطلاع می‌دهد."""
    uid = call.from_user.id
    lang_code = db.get_user_language(uid)
    plans = load_service_plans()
    plan_to_buy = next((p for p in plans if p.get('name') == plan_name), None)

    if not plan_to_buy:
        bot.answer_callback_query(call.id, "خطا: پلن مورد نظر یافت نشد.", show_alert=True)
        return

    price = plan_to_buy.get('price', 0)
    user_uuids = db.uuids(uid)
    if not user_uuids:
        bot.answer_callback_query(call.id, "خطا: شما هیچ اکانت فعالی برای اعمال پلن ندارید.", show_alert=True)
        return

    user_main_uuid_record = user_uuids[0]
    user_main_uuid = user_main_uuid_record['uuid']
    uuid_id = user_main_uuid_record['id']
    is_vip = user_main_uuid_record.get('is_vip', False)

    info_before = combined_handler.get_combined_user_info(user_main_uuid)

    if not db.update_wallet_balance(uid, -price, 'purchase', f"خرید پلن: {plan_name}"):
        bot.answer_callback_query(call.id, "خطا: موجودی کیف پول شما کافی نبود.", show_alert=True)
        return
    
    db.add_payment_record(uuid_id)
    payment_count = len(db.get_user_payment_history(uuid_id))

    if payment_count == 1:
        _check_and_apply_referral_reward(uid)
    _check_and_apply_loyalty_reward(uid, uuid_id, user_main_uuid, call.from_user.first_name)
    
    add_days = parse_volume_string(plan_to_buy.get('duration', '0'))
    plan_type = plan_to_buy.get('type')
    
    if add_days > 0:
        combined_handler.modify_user_on_all_panels(user_main_uuid, add_days=add_days)

    if plan_type == 'combined':
        add_gb_de = parse_volume_string(plan_to_buy.get('volume_de', '0'))
        add_gb_fr_tr = parse_volume_string(plan_to_buy.get('volume_fr', '0'))
        combined_handler.modify_user_on_all_panels(user_main_uuid, add_gb=add_gb_de, target_panel_type='hiddify')
        combined_handler.modify_user_on_all_panels(user_main_uuid, add_gb=add_gb_fr_tr, target_panel_type='marzban')
    else:
        target_panel = 'hiddify' if plan_type == 'germany' else 'marzban'
        volume_key = 'volume_de' if plan_type == 'germany' else 'volume_fr' if plan_type == 'france' else 'volume_tr'
        add_gb = parse_volume_string(plan_to_buy.get(volume_key, '0'))
        combined_handler.modify_user_on_all_panels(user_main_uuid, add_gb=add_gb, target_panel_type=target_panel)
    
    info_after = combined_handler.get_combined_user_info(user_main_uuid)
    
    try:
        user_db_info_after = db.user(uid)
        new_balance = user_db_info_after.get('wallet_balance', 0.0) if user_db_info_after else 0.0
        
        admin_notification_text = fmt_admin_purchase_notification(
            user_info=call.from_user,
            plan=plan_to_buy,
            new_balance=new_balance,
            info_before=info_before,
            info_after=info_after,
            payment_count=payment_count,
            is_vip=is_vip
        )
        
        panel_short = 'h' if any(p.get('type') == 'hiddify' for p in info_after.get('breakdown', {}).values()) else 'm'
        kb_admin = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("👤 مدیریت کاربر", callback_data=f"admin:us:{panel_short}:{user_main_uuid}:search")
        )
        
        for admin_id in ADMIN_IDS:
            bot.send_message(admin_id, admin_notification_text, parse_mode="MarkdownV2", reply_markup=kb_admin)
    except Exception as e:
        logger.error(f"Failed to send purchase notification to admins for user {uid}: {e}")


    summary_text = fmt_purchase_summary(info_before, info_after, plan_to_buy, lang_code)
    success_header = f"✅ خرید شما با موفقیت انجام شد\\! پلن *{escape_markdown(plan_name)}* برای شما فعال گردید\\."
    final_message = f"{success_header}\n{summary_text}"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(f"🔙 بازگشت به کیف پول", callback_data="wallet:main"))
    _safe_edit(uid, call.message.message_id, final_message, reply_markup=kb)


def show_wallet_settings(call: types.CallbackQuery):
    """منوی تنظیمات کیف پول را نمایش می‌دهد."""
    uid = call.from_user.id
    user_data = db.user(uid)
    auto_renew_status = user_data.get('auto_renew', False) if user_data else False
    lang_code = db.get_user_language(uid)

    prompt = (
        f"*{escape_markdown('تنظیمات تمدید خودکار')}*\n\n"
        f"{escape_markdown('با فعال کردن این گزینه، در صورتی که سرویس شما رو به اتمام باشد و موجودی کیف پولتان کافی باشد، سرویس به صورت خودکار برای شما تمدید خواهد شد.')}"
    )

    _safe_edit(uid, call.message.message_id, prompt,
            reply_markup=menu.wallet_settings_menu(auto_renew_status, lang_code))

def toggle_auto_renew(call: types.CallbackQuery):
    """وضعیت تمدید خودکار را تغییر می‌دهد."""
    uid = call.from_user.id
    user_data = db.user(uid)
    new_status = not (user_data.get('auto_renew', False) if user_data else False)
    db.update_auto_renew_setting(uid, new_status)

    status_text = "فعال" if new_status else "غیرفعال"
    bot.answer_callback_query(call.id, f"تمدید خودکار {status_text} شد.")
    show_wallet_settings(call)

def start_transfer_flow(call: types.CallbackQuery):
    """شروع فرآیند انتقال وجه: درخواست شناسه کاربر مقصد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    prompt = escape_markdown("لطفاً شناسه عددی (ID) کاربری که می‌خواهید به او موجودی انتقال دهید را وارد کنید:")

    admin_conversations[uid] = {'action': 'transfer_get_id', 'msg_id': msg_id}

    _safe_edit(uid, msg_id, prompt, reply_markup=menu.user_cancel_action("wallet:main", db.get_user_language(uid)))
    bot.register_next_step_handler(call.message, get_recipient_id)

def get_recipient_id(message: types.Message):
    """شناسه کاربر مقصد را دریافت و اعتبارسنجی می‌کند."""
    uid, text = message.from_user.id, message.text.strip()
    bot.delete_message(uid, message.message_id)
    if uid not in admin_conversations or admin_conversations[uid]['action'] != 'transfer_get_id':
        return

    convo = admin_conversations[uid]
    msg_id = convo['msg_id']

    try:
        recipient_id = int(text)
        if recipient_id == uid:
            _safe_edit(uid, msg_id, escape_markdown("شما نمی‌توانید به خودتان موجودی انتقال دهید. لطفاً دوباره تلاش کنید."), reply_markup=menu.user_cancel_action("wallet:main", db.get_user_language(uid)))
            bot.register_next_step_handler(message, get_recipient_id)
            return

        recipient = db.get_user_by_telegram_id(recipient_id)
        if not recipient:
            raise ValueError("کاربر یافت نشد")

        convo['recipient_id'] = recipient_id
        convo['recipient_name'] = recipient.get('first_name', 'کاربر')
        convo['action'] = 'transfer_get_amount'

        prompt = escape_markdown(f"قصد انتقال به «{recipient.get('first_name')}» را دارید. لطفاً مبلغ مورد نظر (به تومان) را وارد کنید:")
        _safe_edit(uid, msg_id, prompt, reply_markup=menu.user_cancel_action("wallet:main", db.get_user_language(uid)))
        bot.register_next_step_handler(message, get_transfer_amount)

    except (ValueError, TypeError):
        _safe_edit(uid, msg_id, escape_markdown("❌ شناسه وارد شده نامعتبر است یا کاربر یافت نشد. لطفاً دوباره تلاش کنید."), reply_markup=menu.user_cancel_action("wallet:main", db.get_user_language(uid)))
        bot.register_next_step_handler(message, get_recipient_id)

def get_transfer_amount(message: types.Message):
    """مبلغ انتقال را دریافت و تایید نهایی را از کاربر می‌گیرد."""
    uid, text = message.from_user.id, message.text.strip()
    bot.delete_message(uid, message.message_id)
    if uid not in admin_conversations or admin_conversations[uid]['action'] != 'transfer_get_amount':
        return

    convo = admin_conversations[uid]
    msg_id = convo['msg_id']

    try:
        amount = float(text)
        user_data = db.user(uid)
        balance = user_data.get('wallet_balance', 0.0) if user_data else 0.0

        if amount <= 0 or amount > balance:
            raise ValueError("مبلغ نامعتبر یا ناکافی")

        convo['amount'] = amount

        confirm_prompt = (
            f"❓ *{escape_markdown('تایید انتقال')}*\n\n"
            f"{escape_markdown(f'آیا از انتقال مبلغ {amount:,.0f} تومان به کاربر «{convo["recipient_name"]}» اطمینان دارید؟')}"
        )
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("✅ بله", callback_data="wallet:transfer_execute"),
               types.InlineKeyboardButton("❌ خیر", callback_data="wallet:main"))

        _safe_edit(uid, msg_id, confirm_prompt, reply_markup=kb)

    except (ValueError, TypeError):
        _safe_edit(uid, msg_id, escape_markdown("❌ مبلغ وارد شده نامعتبر یا بیشتر از موجودی شماست. لطفاً دوباره تلاش کنید."), reply_markup=menu.user_cancel_action("wallet:main", db.get_user_language(uid)))
        bot.register_next_step_handler(message, get_transfer_amount)

def execute_wallet_transfer(call: types.CallbackQuery):
    """(نسخه نهایی) انتقال موجودی را نهایی کرده و پیام موفقیت را با دکمه صحیح نمایش می‌دهد."""
    sender_id = call.from_user.id
    if sender_id not in admin_conversations or admin_conversations[sender_id].get('action') != 'transfer_get_amount':
        return

    convo = admin_conversations.pop(sender_id)
    msg_id = convo['msg_id']
    recipient_id = convo['recipient_id']
    amount = convo['amount']

    db.update_wallet_balance(sender_id, -amount, 'transfer_out', f"انتقال به کاربر {recipient_id}")
    db.update_wallet_balance(recipient_id, amount, 'transfer_in', f"دریافت از کاربر {sender_id}")
    db.log_wallet_transfer(sender_id, recipient_id, amount)

    sender_name = escape_markdown(call.from_user.first_name)
    sender_message = escape_markdown(f"✅ مبلغ {amount:,.0f} تومان با موفقیت انتقال یافت.")
    
    back_to_wallet_kb = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton(f"🔙 {get_string('back', db.get_user_language(sender_id))}", callback_data="wallet:main")
    )
    
    _safe_edit(sender_id, msg_id, sender_message, reply_markup=back_to_wallet_kb)

    try:
        recipient_message = f"🎁 شما مبلغ *{amount:,.0f} تومان* از طرف کاربر *{sender_name}* دریافت کردید\\."
        bot.send_message(recipient_id, recipient_message, parse_mode="MarkdownV2")
    except Exception as e:
        logger.warning(f"Could not send transfer notification to recipient {recipient_id}: {e}")



def start_gift_flow(call: types.CallbackQuery):
    """شروع فرآیند خرید برای دیگران: درخواست شناسه کاربر مقصد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    prompt = escape_markdown("🎁 شما در حال خرید هدیه برای کاربر دیگری هستید.\n\nلطفاً شناسه عددی (ID) کاربر مورد نظر را وارد کنید:")

    admin_conversations[uid] = {'action': 'gift_get_id', 'msg_id': msg_id}

    _safe_edit(uid, msg_id, prompt, reply_markup=menu.user_cancel_action("wallet:main", db.get_user_language(uid)))
    bot.register_next_step_handler(call.message, get_recipient_id_for_gift)

def get_recipient_id_for_gift(message: types.Message):
    """شناسه کاربر هدیه‌گیرنده را دریافت کرده و لیست پلن‌ها را نمایش می‌دهد."""
    uid, text = message.from_user.id, message.text.strip()
    bot.delete_message(uid, message.message_id)
    if uid not in admin_conversations or admin_conversations[uid]['action'] != 'gift_get_id':
        return

    convo = admin_conversations[uid]
    msg_id = convo['msg_id']

    try:
        recipient_id = int(text)
        recipient = db.get_user_by_telegram_id(recipient_id)
        if not recipient or not db.uuids(recipient_id):
            raise ValueError("کاربر یافت نشد یا اکانتی ندارد")

        convo['recipient_id'] = recipient_id
        convo['recipient_name'] = recipient.get('first_name', 'کاربر')

        all_plans = load_service_plans()
        user_balance = (db.user(uid) or {}).get('wallet_balance', 0.0)

        kb = types.InlineKeyboardMarkup(row_width=1)
        for plan in all_plans:
            price = plan.get('price', 0)
            is_affordable = user_balance >= price
            emoji = "✅" if is_affordable else "❌"
            price_str = "{:,.0f}".format(price)
            button_text = f"{emoji} {plan.get('name')} ({price_str} تومان)"

            callback_data = f"wallet:gift_plan_select:{plan.get('name')}" if is_affordable else "wallet:insufficient"
            kb.add(types.InlineKeyboardButton(button_text, callback_data=callback_data))

        kb.add(types.InlineKeyboardButton("🔙 بازگشت به کیف پول", callback_data="wallet:main"))

        prompt = escape_markdown(f"لطفاً پلنی که می‌خواهید برای «{convo['recipient_name']}» خریداری کنید را انتخاب نمایید:")
        _safe_edit(uid, msg_id, prompt, reply_markup=kb)

    except (ValueError, TypeError):
        _safe_edit(uid, msg_id, escape_markdown("❌ شناسه وارد شده نامعتبر است یا کاربر اکانتی در ربات ندارد. لطفاً دوباره تلاش کنید."), reply_markup=menu.user_cancel_action("wallet:main", db.get_user_language(uid)))
        bot.register_next_step_handler(message, get_recipient_id_for_gift)

def confirm_gift_purchase(call: types.CallbackQuery, plan_name: str):
    """از کاربر برای هدیه دادن پلن تاییدیه می‌گیرد."""
    uid = call.from_user.id
    if uid not in admin_conversations: return
    convo = admin_conversations[uid]
    recipient_name = convo.get('recipient_name', 'کاربر')

    plans = load_service_plans()
    plan_to_buy = next((p for p in plans if p.get('name') == plan_name), None)
    if not plan_to_buy: return

    convo['plan_to_buy'] = plan_to_buy
    price = plan_to_buy.get('price', 0)

    confirm_prompt = (
        f"🎁 *{escape_markdown('تایید هدیه')}*\n\n"
        f"{escape_markdown(f'آیا از خرید پلن «{plan_name}» به مبلغ {price:,.0f} تومان برای کاربر «{recipient_name}» اطمینان دارید؟')}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("✅ بله، هدیه می‌دهم", callback_data=f"wallet:gift_execute:{plan_name}"),
           types.InlineKeyboardButton("❌ انصراف", callback_data="wallet:main"))

    _safe_edit(uid, call.message.message_id, confirm_prompt, reply_markup=kb)

def execute_gift_purchase(call: types.CallbackQuery):
    """(نسخه نهایی) خرید هدیه را نهایی کرده و سناریوی عدم دسترسی را به درستی مدیریت می‌کند."""
    sender_id = call.from_user.id
    if sender_id not in admin_conversations: return

    convo = admin_conversations.pop(sender_id)
    msg_id = convo['msg_id']
    recipient_id = convo['recipient_id']
    plan_to_buy = convo['plan_to_buy']
    price = plan_to_buy.get('price', 0)

    # ۱. کسر هزینه و ثبت لاگ
    db.update_wallet_balance(sender_id, -price, 'gift_purchase', f"خرید هدیه برای کاربر {recipient_id}")

    recipient_uuids = db.uuids(recipient_id)
    recipient_main_uuid = recipient_uuids[0]['uuid']
    recipient_uuid_record = db.get_user_uuid_record(recipient_main_uuid)
    plan_type = plan_to_buy.get('type')

    # ۲. بررسی دسترسی کاربر مقصد به سرورهای پلن
    has_access = False
    if plan_type == 'germany' and recipient_uuid_record.get('has_access_de'):
        has_access = True
    elif plan_type in ['france', 'turkey'] and (recipient_uuid_record.get('has_access_fr') or recipient_uuid_record.get('has_access_tr')):
        has_access = True
    elif plan_type == 'combined' and recipient_uuid_record.get('has_access_de') and (recipient_uuid_record.get('has_access_fr') or recipient_uuid_record.get('has_access_tr')):
        has_access = True

    sender_name = escape_markdown(call.from_user.first_name)
    recipient_name = escape_markdown(convo.get('recipient_name', ''))
    plan_name_escaped = escape_markdown(plan_to_buy.get('name', ''))

    # کیبورد بازگشت برای پیام‌های موفقیت‌آمیز
    back_to_wallet_kb = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton(f"🔙 {get_string('back', db.get_user_language(sender_id))}", callback_data="wallet:main")
    )

    # ۳. اجرای سناریوی مناسب بر اساس دسترسی
    if has_access:
        # اگر کاربر دسترسی داشت، هم حجم و هم روز را اضافه کن
        add_days = parse_volume_string(plan_to_buy.get('duration', '0'))
        if add_days > 0:
            combined_handler.modify_user_on_all_panels(recipient_main_uuid, add_days=add_days)

        if plan_type == 'combined':
            add_gb_de = parse_volume_string(plan_to_buy.get('volume_de', '0'))
            add_gb_fr_tr = parse_volume_string(plan_to_buy.get('volume_fr', '0'))
            combined_handler.modify_user_on_all_panels(recipient_main_uuid, add_gb=add_gb_de, target_panel_type='hiddify')
            combined_handler.modify_user_on_all_panels(recipient_main_uuid, add_gb=add_gb_fr_tr, target_panel_type='marzban')
        else:
            target_panel = 'hiddify' if plan_type == 'germany' else 'marzban'
            volume_key = 'volume_de' if plan_type == 'germany' else 'volume_fr' if plan_type == 'france' else 'volume_tr'
            add_gb = parse_volume_string(plan_to_buy.get(volume_key, '0'))
            combined_handler.modify_user_on_all_panels(recipient_main_uuid, add_gb=add_gb, target_panel_type=target_panel)
        
        # اطلاع‌رسانی به طرفین
        sender_message = f"✅ هدیه شما \\(پلن *{plan_name_escaped}*\\) با موفقیت برای *{recipient_name}* فعال شد\\."
        _safe_edit(sender_id, msg_id, sender_message, reply_markup=back_to_wallet_kb)
        
        try:
            recipient_message = f"🎁 شما یک هدیه \\(پلن *{plan_name_escaped}*\\) از طرف کاربر *{sender_name}* دریافت کردید\\. این پلن به سرویس شما اضافه شد\\."
            bot.send_message(recipient_id, recipient_message, parse_mode="MarkdownV2")
        except Exception as e:
            logger.warning(f"Could not send gift notification to recipient {recipient_id}: {e}")

    else:
        import time
        tracking_code = f"GIFT-{recipient_id}-{int(time.time())}"
        support_link = f"https://t.me/{ADMIN_SUPPORT_CONTACT.replace('@', '')}"

        # پیام به فرستنده
        sender_message = (
            f"✅ هدیه شما برای *{recipient_name}* ثبت شد\\.\n\n"
            f"از آنجایی که ایشان به سرور این پلن دسترسی ندارند، پیامی برایشان ارسال شد تا برای فعال‌سازی با پشتیبانی تماس بگیرند\\."
        )
        _safe_edit(sender_id, msg_id, sender_message, reply_markup=back_to_wallet_kb)
        
        # پیام به گیرنده
        recipient_message = (
            f"🎁 شما یک هدیه \\(پلن *{plan_name_escaped}*\\) از طرف کاربر *{sender_name}* دریافت کرده‌اید\\!\n\n"
            f"برای فعال‌سازی کامل این هدیه \\(حجم و روز\\)، لطفاً با پشتیبانی تماس بگیرید و کد پیگیری زیر را ارسال کنید:\n\n"
            f"`{tracking_code}`"
        )
        kb_recipient = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("💬 تماس با پشتیبانی", url=support_link))
        try:
            bot.send_message(recipient_id, recipient_message, parse_mode="MarkdownV2", reply_markup=kb_recipient)
        except Exception as e:
            logger.warning(f"Could not send 'activate gift' notification to recipient {recipient_id}: {e}")
            
        admin_message = (
            f"🔵 *{escape_markdown('نیاز به فعال‌سازی کامل هدیه')}*\n\n"
            f"کاربر *{sender_name}* \\(`{sender_id}`\\) پلن *{plan_name_escaped}* را برای کاربر *{recipient_name}* \\(`{recipient_id}`\\) هدیه خریده است\\.\n"
            f"کاربر مقصد به سرورهای این پلن دسترسی ندارد\\.\n\n"
            f"کد پیگیری: `{tracking_code}`\n\n"
            f"لطفاً پس از تماس کاربر، دسترسی لازم را فعال کرده و **کل پلن \\(حجم و روز\\)** را به صورت دستی برایش اعمال کنید\\."
        )
        for admin_id in ADMIN_IDS:
            _notify_user(admin_id, admin_message)

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
