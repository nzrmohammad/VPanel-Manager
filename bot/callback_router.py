# bot/callback_router.py

from telebot import types, telebot
from .config import ADMIN_IDS
from .admin_router import handle_admin_callbacks
# تابع جدید را از user_handlers وارد می‌کنیم
from .user_handlers import handle_user_callbacks, handle_language_selection

def register_callback_router(bot: telebot.TeleBot):

    @bot.callback_query_handler(func=lambda call: True)
    def main_callback_router(call: types.CallbackQuery):
        uid = call.from_user.id
        data = call.data
        is_admin = uid in ADMIN_IDS

        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        
        # <<<<<<<<<<<<<<<<<<<< START OF CHANGES >>>>>>>>>>>>>>>>>>
        # این شرط جدید، درخواست‌های تغییر زبان را مدیریت می‌کند
        if data.startswith("set_lang:"):
            handle_language_selection(call)
            return
        # <<<<<<<<<<<<<<<<<<<< END OF CHANGES >>>>>>>>>>>>>>>>>>

        if is_admin and data.startswith("admin:"):
            handle_admin_callbacks(call)
        else:
            handle_user_callbacks(call)