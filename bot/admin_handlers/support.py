# bot/admin_handlers/support.py

import logging
from telebot import types
from ..database import db
from ..utils import escape_markdown, _safe_edit
from ..config import ADMIN_IDS

logger = logging.getLogger(__name__)
bot = None
admin_conversations = None # <--- (جدید) برای next_step_handler

def initialize_support_handlers(b, conv_dict): # <--- (اصلاح شده)
    """مقادیر bot و admin_conversations را دریافت می‌کند."""
    global bot, admin_conversations
    bot = b
    admin_conversations = conv_dict

def prompt_for_reply(call: types.CallbackQuery, params: list):
    """
    (تابع جدید)
    Handles admin clicking '✍️ پاسخ به این تیکت'.
    Asks the admin to type their reply.
    """
    admin_id = call.from_user.id
    msg_id = call.message.message_id
    
    try:
        # params[0] = ticket_id, params[1] = user_id
        ticket_id, user_id_to_reply = int(params[0]), int(params[1])
    except (IndexError, ValueError):
        bot.answer_callback_query(call.id, "خطا: اطلاعات دکمه ناقص است.", show_alert=True)
        return

    # ذخیره وضعیت برای گام بعدی
    admin_conversations[admin_id] = {
        'action': 'support_reply',
        'user_id': user_id_to_reply,
        'ticket_id': ticket_id,
        'original_msg_id': msg_id # شناسه پیام تیکت در چت ادمین
    }

    # دکمه را از پیام تیکت حذف می‌کنیم تا دوباره کلیک نشود
    try:
        bot.edit_message_reply_markup(admin_id, msg_id, reply_markup=None)
    except Exception:
        pass # اگر ویرایش نشد مهم نیست

    # از ادمین می‌خواهیم که پاسخ را تایپ کند
    bot.send_message(admin_id, 
                     f"✍️ لطفاً پاسخ خود را برای تیکت شماره `{ticket_id}` تایپ و ارسال کنید\\.\n\\(برای لغو، دستور /cancel را ارسال کنید\\)",
                     parse_mode="MarkdownV2")
    
    # ثبت هندلر برای دریافت پیام بعدی ادمین
    bot.register_next_step_handler(call.message, send_reply_to_user)

def send_reply_to_user(message: types.Message):
    """
    (تابع جدید)
    پاسخ متنی ادمین را دریافت کرده و برای کاربر ارسال می‌کند.
    """
    admin_id = message.from_user.id
    
    # بررسی دستور لغو
    if message.text == '/cancel':
        if admin_id in admin_conversations:
            convo_data = admin_conversations.pop(admin_id, None)
            # دکمه را به پیام تیکت بازمی‌گردانیم
            try:
                kb_admin = types.InlineKeyboardMarkup()
                kb_admin.add(types.InlineKeyboardButton(
                    "✍️ پاسخ به این تیکت", 
                    callback_data=f"admin:support_reply:{convo_data['ticket_id']}:{convo_data['user_id']}"
                ))
                bot.edit_message_reply_markup(admin_id, convo_data['original_msg_id'], reply_markup=kb_admin)
            except Exception:
                pass
        bot.send_message(admin_id, "عملیات لغو شد. تیکت دوباره باز شد.")
        return

    # بررسی اینکه آیا ادمین در وضعیت «پاسخ به تیکت» است یا خیر
    if admin_id not in admin_conversations or admin_conversations[admin_id].get('action') != 'support_reply':
        # اگر ادمین در حال چت عادی بود، پیامش را نادیده می‌گیریم (یا می‌توانیم به ادمین بگوییم)
        return 

    convo_data = admin_conversations.pop(admin_id, None)
    if not convo_data:
        return

    user_id_to_reply = convo_data['user_id']
    ticket_id = convo_data['ticket_id']
    original_msg_id = convo_data['original_msg_id']
    admin_name = escape_markdown(message.from_user.first_name)
    
    try:
        # فرمت کردن پیام برای کاربر
        reply_text_lines = [
            f"💬 *پاسخ پشتیبانی از طرف {admin_name}*",
            f"`──────────────────`",
            f"{escape_markdown(message.text)}"
        ]
        reply_text = "\n".join(reply_text_lines)

        # ارسال پاسخ به کاربر
        bot.send_message(user_id_to_reply, reply_text, parse_mode="MarkdownV2")
        
        # تایید ارسال برای ادمین
        bot.reply_to(message, "✅ پاسخ شما با موفقیت به کاربر ارسال شد.")
        
        # بستن تیکت در دیتابیس
        db.close_ticket(ticket_id)
        
        # ویرایش پیام اصلی تیکت در چت ادمین برای نشان دادن اینکه بسته شده
        try:
            original_text = bot.get_chat(admin_id).get_message(original_msg_id).text
            closed_text = f"✅ (بسته شد)\n\n" + original_text
            bot.edit_message_text(closed_text, admin_id, original_msg_id, parse_mode="MarkdownV2", reply_markup=None)
        except Exception:
            pass # اگر ویرایش نشد هم مهم نیست

    except Exception as e:
        logger.error(f"Failed to send admin reply to user {user_id_to_reply}: {e}")
        bot.reply_to(message, "❌ خطایی در ارسال پاسخ به کاربر رخ داد. لطفاً دوباره تلاش کنید.")
        # (اختیاری) می‌توانیم مکالمه را برای تلاش مجدد باز نگه داریم
        admin_conversations[admin_id] = convo_data
        bot.register_next_step_handler(message, send_reply_to_user)