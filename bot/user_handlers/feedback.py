# bot/user_handlers/feedback.py

import logging
from telebot import types
from ..database import db
from ..menu import menu
from ..utils import escape_markdown, _safe_edit

logger = logging.getLogger(__name__)
bot, admin_conversations = None, None

def initialize_handlers(b, conv_dict):
    """مقادیر bot و admin_conversations را از فایل اصلی دریافت می‌کند."""
    global bot, admin_conversations
    bot = b
    admin_conversations = conv_dict

def handle_feedback_callbacks(call: types.CallbackQuery):
    """
    پردازش کلیک‌های مربوط به نظرسنجی رضایت.
    """
    uid, msg_id, data = call.from_user.id, call.message.message_id, call.data
    
    if data == "feedback:cancel":
        _safe_edit(uid, msg_id, "از اینکه وقت گذاشتید متشکریم.", reply_markup=None)
        return

    if data.startswith("feedback:rating:"):
        rating = int(data.split(":")[-1])
        
        # ثبت امتیاز اولیه و دریافت ID رکورد
        try:
            feedback_id = db.add_feedback_rating(uid, rating)
        except Exception as e:
            logger.error(f"Failed to add feedback rating for user {uid}: {e}")
            _safe_edit(uid, msg_id, "خطایی در ثبت امتیاز رخ داد.", reply_markup=None)
            return

        if rating >= 4:
            prompt = escape_markdown("😍 عالیه! از رضایت شما خوشحالیم.\n\nآیا پیشنهاد یا نظری برای بهتر شدن سرویس ما دارید؟ لطفاً برای ما بنویسید:")
        else:
            prompt = escape_markdown("😞 متاسفیم که تجربه خوبی نداشتید.\n\nلطفاً دلیل نارضایتی خود را برای ما بنویسید تا مستقیماً توسط مدیریت بررسی شود:")
        
        kb = menu.user_cancel_action("feedback:cancel_comment", "fa") # دکمه لغو
        _safe_edit(uid, msg_id, prompt, reply_markup=kb)
        
        # ثبت گام بعدی برای دریافت نظر متنی
        bot.register_next_step_handler(call.message, get_feedback_comment, feedback_id=feedback_id, original_msg_id=msg_id)

    elif data == "feedback:cancel_comment":
        _safe_edit(uid, msg_id, "از ثبت امتیاز شما متشکریم.", reply_markup=None)
        bot.clear_step_handler_by_chat_id(uid)


def get_feedback_comment(message: types.Message, feedback_id: int, original_msg_id: int):
    """
    نظر متنی کاربر را دریافت و در دیتابیس ذخیره می‌کند.
    """
    uid = message.from_user.id
    comment = message.text.strip()
    
    try:
        bot.delete_message(uid, message.message_id)
    except Exception:
        pass

    try:
        db.update_feedback_comment(feedback_id, comment)
        success_msg = escape_markdown("✅ نظر شما با موفقیت ثبت شد. از بازخورد شما سپاسگزاریم!")
        _safe_edit(uid, original_msg_id, success_msg, reply_markup=None)
    except Exception as e:
        logger.error(f"Failed to update feedback comment {feedback_id}: {e}")
        _safe_edit(uid, original_msg_id, "خطایی در ثبت نظر شما رخ داد.", reply_markup=None)
    
    bot.clear_step_handler_by_chat_id(uid)