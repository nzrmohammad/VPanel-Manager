import telebot
from .config import BOT_TOKEN

bot = telebot.TeleBot(BOT_TOKEN)
admin_conversations = {}