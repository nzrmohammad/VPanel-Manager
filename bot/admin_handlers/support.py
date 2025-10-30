# bot/admin_handlers/support.py

import logging
from telebot import types
from ..database import db
from ..utils import escape_markdown
from ..config import ADMIN_IDS

logger = logging.getLogger(__name__)
bot = None

def initialize_support_handlers(b):
    global bot
    bot = b

def handle_admin_reply_to_ticket(message: types.Message):
    """
    زمانی که ادمین به پیام تیکت کاربر Reply می‌زند، این تابع فراخوانی می‌شود.
    """
    admin_id = message.from_user.id
    
    # 1. مطمئن شویم که این پیام، ریپلای است
    if not message.reply_to_message:
        return

    # 2. پیام اصلی که ادمین به آن ریپلای زده را واکشی می‌کنیم
    replied_to_msg_id = message.reply_to_message.message_id
    
    # 3. چک می‌کنیم آیا این پیام ریپلای شده، همان پیام اطلاعاتی تیکت است
    #    (پیامی که حاوی "🎫 تیکت شماره: ..." بود)
    ticket = db.get_ticket_by_admin_message_id(replied_to_msg_id)
    
    if not ticket:
        # اگر نبود، شاید ادمین به پیام فوروارد شده ریپلای زده
        # (این منطق کمی پیچیده‌تر است و فعلاً آن را نادیده می‌گیریم)
        # فقط در صورتی که به پیام اصلی ریپلای زده باشد کار می‌کنیم
        return

    try:
        user_id_to_reply = ticket['user_id']
        admin_name = escape_markdown(message.from_user.first_name)
        
        # 4. ساخت پیام برای ارسال به کاربر
        reply_text_lines = [
            f"💬 *پاسخ پشتیبانی از طرف {admin_name}*",
            f"`──────────────────`",
            f"{escape_markdown(message.text)}"
        ]
        reply_text = "\n".join(reply_text_lines)

        # 5. ارسال پیام ادمین به کاربر
        bot.send_message(user_id_to_reply, reply_text, parse_mode="MarkdownV2")
        
        # 6. اطلاع به ادمین که پاسخش ارسال شد
        bot.reply_to(message, "✅ پاسخ شما با موفقیت به کاربر ارسال شد.")
        
        # (اختیاری) می‌توانیم تیکت را پس از اولین پاسخ ادمین ببندیم
        # db.close_ticket(ticket['id'])

    except Exception as e:
        logger.error(f"Failed to send admin reply to user {ticket['user_id']}: {e}")
        bot.reply_to(message, "❌ خطایی در ارسال پاسخ به کاربر رخ داد.")