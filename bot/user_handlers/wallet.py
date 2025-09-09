# nzrmohammad/vpanel-manager/VPanel-Manager-063e72609384d4f0fb543665c1d1c7f6335ca45d/bot/user_handlers/wallet.py
import logging
from telebot import types
from ..database import db
from ..menu import menu
from ..utils import escape_markdown, _safe_edit, load_service_plans, to_shamsi, parse_volume_string
from ..language import get_string
from ..config import ADMIN_IDS, CARD_PAYMENT_INFO
from .. import combined_handler
from telebot.apihelper import ApiTelegramException


logger = logging.getLogger(__name__)
bot, admin_conversations = None, None

def initialize_handlers(b, conv_dict):
    """مقادیر bot و admin_conversations را از فایل اصلی دریافت می‌کند."""
    global bot, admin_conversations
    bot = b
    admin_conversations = conv_dict

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
            plan_name = action_parts[2]
            confirm_purchase(call, plan_name)
        elif action == 'buy_execute':
            plan_name = action_parts[2]
            execute_purchase(call, plan_name)
        elif action == 'insufficient':
            bot.answer_callback_query(call.id, "موجودی کیف پول شما کافی نیست. لطفاً ابتدا حساب خود را شارژ کنید.", show_alert=True)
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
            amount_str = f"{abs(amount):,.0f}"
            date_str = to_shamsi(trans['transaction_date'], include_time=True)
            description = escape_markdown(trans.get('description', ''))
            
            lines.append(f"`──────────────────`\n{emoji} *{amount_str} تومان* \n`{description}`\n_{escape_markdown(date_str)}_")

    _safe_edit(uid, call.message.message_id, "\n".join(lines),
               reply_markup=menu.user_cancel_action("wallet:main", lang_code))

def confirm_purchase(call: types.CallbackQuery, plan_name: str):
    """از کاربر برای خرید سرویس با کیف پول تاییدیه می‌گیرد."""
    uid = call.from_user.id
    plans = load_service_plans()
    plan_to_buy = next((p for p in plans if p.get('name') == plan_name), None)

    if not plan_to_buy:
        bot.answer_callback_query(call.id, "خطا: پلن مورد نظر یافت نشد.", show_alert=True)
        return

    price = plan_to_buy.get('price', 0)
    confirm_text = (
        f"❓ *{escape_markdown('تایید خرید')}*\n\n"
        f"{escape_markdown('شما در حال خرید پلن زیر هستید:')}\n"
        f"*{escape_markdown(plan_name)}* - {price:,.0f} {escape_markdown('تومان')}\n\n"
        f"{escape_markdown('مبلغ از کیف پول شما کسر خواهد شد. آیا ادامه می‌دهید؟')}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ بله، خرید", callback_data=f"wallet:buy_execute:{plan_name}"),
        types.InlineKeyboardButton("❌ انصراف", callback_data="view_plans")
    )
    _safe_edit(uid, call.message.message_id, confirm_text, reply_markup=kb)

def execute_purchase(call: types.CallbackQuery, plan_name: str):
    """خرید را نهایی کرده، حجم را اضافه و از کیف پول کم می‌کند."""
    uid = call.from_user.id
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
        
    if db.update_wallet_balance(uid, -price, 'purchase', f"خرید پلن: {plan_name}"):
        user_main_uuid = user_uuids[0]['uuid']
        add_gb_de = parse_volume_string(plan_to_buy.get('volume_de', '0'))
        add_gb_fr = parse_volume_string(plan_to_buy.get('volume_fr', '0'))
        add_days = parse_volume_string(plan_to_buy.get('duration', '0'))
        
        combined_handler.modify_user_on_all_panels(user_main_uuid, add_gb=add_gb_de, add_days=add_days, target_panel_type='hiddify')
        combined_handler.modify_user_on_all_panels(user_main_uuid, add_gb=add_gb_fr, add_days=add_days, target_panel_type='marzban')
        
        success_text = f"✅ خرید شما با موفقیت انجام شد! پلن *{escape_markdown(plan_name)}* برای شما فعال گردید."
        _safe_edit(uid, call.message.message_id, success_text, reply_markup=menu.user_cancel_action("back", db.get_user_language(uid)))
    else:
        bot.answer_callback_query(call.id, "خطا: موجودی کیف پول شما در لحظه آخر کافی نبود. لطفاً دوباره تلاش کنید.", show_alert=True)
        from .info import show_plan_categories
        show_plan_categories(call)