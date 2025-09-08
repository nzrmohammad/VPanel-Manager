from telebot import types, telebot
from .config import ADMIN_IDS
from .admin_router import handle_admin_callbacks
from .user_router import handle_user_callbacks

def register_callback_router(bot: telebot.TeleBot):
    """
    یک هندلر جامع برای تمام callback query ها ثبت می‌کند.
    این تابع به عنوان یک مسیریاب مرکزی عمل می‌کند.
    """

    @bot.callback_query_handler(func=lambda call: True)
    def main_callback_router(call: types.CallbackQuery):
        """
        این تابع تمام کلیک‌های روی دکمه‌ها را دریافت می‌کند.
        """
        uid = call.from_user.id
        data = call.data
        is_admin = uid in ADMIN_IDS

        # پاسخ اولیه به تلگرام برای جلوگیری از نمایش حالت لودینگ روی دکمه
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

        # --- منطق اصلی مسیریابی ---
        # اگر کاربر ادمین باشد و callback با پیشوند "admin:" شروع شود،
        # درخواست به مسیریاب ادمین ارسال می‌شود.
        if is_admin and data.startswith("admin:"):
            handle_admin_callbacks(call)
        else:
            # در غیر این صورت، درخواست به مسیریاب کاربران عادی ارسال می‌شود.
            handle_user_callbacks(call)