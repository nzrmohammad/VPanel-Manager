from telebot import types, telebot
from .config import ADMIN_IDS
from .admin_router import handle_admin_callbacks
from .user_handlers import handle_user_callbacks

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
        if is_admin and data.startswith("admin:"):
            handle_admin_callbacks(call)
        else:
            handle_user_callbacks(call)
