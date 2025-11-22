# bot/user_handlers/feedback.py

import logging
from telebot import types
from ..database import db
from ..menu import menu
from ..utils import escape_markdown, _safe_edit
from ..config import ADMIN_IDS 

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
    
    # --- دکمه لغو عملیات ---
    if data == "feedback:cancel":
        msg = escape_markdown("از اینکه وقت گذاشتید متشکریم.")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu"))
        
        _safe_edit(uid, msg_id, msg, reply_markup=kb)
        return

    # --- ثبت امتیاز ستاره‌ای ---
    if data.startswith("feedback:rating:"):
        rating = int(data.split(":")[-1])
        
        # ثبت امتیاز اولیه و دریافت ID رکورد
        try:
            feedback_id = db.add_feedback_rating(uid, rating)
        except Exception as e:
            logger.error(f"Failed to add feedback rating for user {uid}: {e}")
            error_msg = escape_markdown("خطایی در ثبت امتیاز رخ داد.")
            kb_error = types.InlineKeyboardMarkup()
            kb_error.add(types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu"))
            _safe_edit(uid, msg_id, error_msg, reply_markup=kb_error)
            return

        # نمایش پیام مناسب بر اساس امتیاز
        if rating >= 4:
            prompt = escape_markdown("😍 عالیه! از رضایت شما خوشحالیم.\n\nآیا پیشنهاد یا نظری برای بهتر شدن سرویس ما دارید؟ لطفاً برای ما بنویسید:")
        else:
            prompt = escape_markdown("😞 متاسفیم که تجربه خوبی نداشتید.\n\nلطفاً دلیل نارضایتی خود را برای ما بنویسید تا مستقیماً توسط مدیریت بررسی شود:")
        
        # ساخت کیبورد (شامل دکمه جدید "ثبت بدون نظر")
        kb = types.InlineKeyboardMarkup()
        kb.row(types.InlineKeyboardButton("ثبت بدون نظر (Skip)", callback_data="feedback:skip_comment"))
        kb.row(types.InlineKeyboardButton("لغو عملیات", callback_data="feedback:cancel_comment"))
        
        _safe_edit(uid, msg_id, prompt, reply_markup=kb)
        
        # ثبت گام بعدی برای دریافت نظر متنی
        bot.register_next_step_handler(call.message, get_feedback_comment, feedback_id=feedback_id, original_msg_id=msg_id)

    # --- دکمه لغو هنگام نوشتن نظر ---
    elif data == "feedback:cancel_comment":
        msg = escape_markdown("از ثبت امتیاز شما متشکریم.")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu"))
        
        _safe_edit(uid, msg_id, msg, reply_markup=kb)
        bot.clear_step_handler_by_chat_id(uid)

    # --- دکمه "ثبت بدون نظر" (پیشنهاد جدید) ---
    elif data == "feedback:skip_comment":
        msg = escape_markdown("از ثبت امتیاز شما متشکریم. نظر شما بدون توضیحات متنی نهایی شد.")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu"))
        
        _safe_edit(uid, msg_id, msg, reply_markup=kb)
        bot.clear_step_handler_by_chat_id(uid)


def get_feedback_comment(message: types.Message, feedback_id: int, original_msg_id: int):
    """
    نظر متنی کاربر را دریافت و در دیتابیس ذخیره می‌کند.
    (با اعتبارسنجی ورودی و مدیریت دستورات)
    """
    uid = message.from_user.id

    # ۱. جلوگیری از دریافت استیکر، عکس و فایل (فقط متن مجاز است)
    if not message.text:
        error_msg = bot.send_message(uid, "❌ لطفاً فقط متن ارسال کنید (استیکر یا عکس پذیرفته نمی‌شود).", parse_mode="Markdown")
        # دوباره منتظر دریافت پیام صحیح می‌مانیم
        bot.register_next_step_handler(error_msg, get_feedback_comment, feedback_id=feedback_id, original_msg_id=original_msg_id)
        return

    # ۲. مدیریت دستورات ربات (اگر کاربر پشیمان شد و دستوری مثل /start فرستاد)
    if message.text.startswith("/"):
        bot.clear_step_handler_by_chat_id(uid)
        cancel_msg = escape_markdown("عملیات لغو شد. بازگشت به منوی اصلی.")
        
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu"))
        
        bot.send_message(uid, cancel_msg, parse_mode="MarkdownV2", reply_markup=kb)
        return

    comment = message.text.strip()
    
    # حذف پیام ارسالی کاربر برای تمیز ماندن چت
    try:
        bot.delete_message(uid, message.message_id)
    except Exception:
        pass

    try:
        # ۳. آپدیت دیتابیس
        db.update_feedback_comment(feedback_id, comment)

        # ۴. اطلاع‌رسانی آنی به ادمین‌ها
        try:
            user_name = escape_markdown(message.from_user.first_name or "User")
            safe_comment = escape_markdown(comment)
            
            admin_text = (
                f"📣 *بازخورد جدید دریافت شد*\n\n"
                f"👤 کاربر: [{user_name}](tg://user?id={uid})\n"
                f"🆔 شناسه: `{uid}`\n"
                f"💬 نظر: {safe_comment}"
            )
            for admin_id in ADMIN_IDS:
                try:
                    bot.send_message(admin_id, admin_text, parse_mode="MarkdownV2")
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Failed to notify admins about feedback: {e}")

        # ۵. پیام موفقیت و دکمه بازگشت
        success_msg = escape_markdown("✅ نظر شما با موفقیت ثبت شد. از بازخورد شما سپاسگزاریم!")
        
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu"))
        
        _safe_edit(uid, original_msg_id, success_msg, reply_markup=kb)

    except Exception as e:
        logger.error(f"Failed to update feedback comment {feedback_id}: {e}")
        error_msg = escape_markdown("خطایی در ثبت نظر شما رخ داد.")
        
        kb_error = types.InlineKeyboardMarkup()
        kb_error.add(types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu"))
        
        _safe_edit(uid, original_msg_id, error_msg, reply_markup=kb_error)
    
    bot.clear_step_handler_by_chat_id(uid)