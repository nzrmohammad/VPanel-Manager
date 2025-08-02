# bot/admin_handlers/backup.py

import logging
import os
import json
from datetime import datetime
from telebot import types

# هندلرهای هر دو پنل را برای دسترسی به لیست کاربران وارد می‌کنیم
from ..hiddify_api_handler import hiddify_handler
from ..marzban_api_handler import marzban_handler

from ..menu import menu
from ..utils import _safe_edit, escape_markdown
from ..config import DATABASE_PATH, TELEGRAM_FILE_SIZE_LIMIT_BYTES

logger = logging.getLogger(__name__)
bot = None

def initialize_backup_handlers(b):
    global bot
    bot = b

def handle_backup_menu(call, params):
    """این تابع منوی انتخاب نوع پشتیبان را نمایش می‌دهد."""
    _safe_edit(call.from_user.id, call.message.message_id, "🗄️ لطفاً نوع پشتیبان‌گیری را انتخاب کنید:", reply_markup=menu.admin_backup_selection_menu())

def handle_backup_action(call, params):
    """
    این تابع اصلی است که بر اساس پارامتر دریافتی، نوع پشتیبان‌گیری را تشخیص می‌دهد.
    """
    backup_type = params[0]
    if backup_type == "bot_db":
        _handle_bot_db_backup_request(call)
    elif backup_type == "marzban":
        _handle_marzban_backup_request(call)
    # <<<<<<<<<<<<<<<< تغییر اصلی اینجاست >>>>>>>>>>>>>>>>
    # شرط جدید برای رسیدگی به پشتیبان‌گیری از هیدیفای
    elif backup_type == "hiddify":
        _handle_hiddify_backup_request(call)

def _handle_bot_db_backup_request(call):
    """منطق پشتیبان‌گیری از دیتابیس ربات."""
    chat_id = call.from_user.id
    bot.answer_callback_query(call.id, "در حال پردازش...")
    
    if not os.path.exists(DATABASE_PATH):
        bot.send_message(chat_id, "❌ فایل دیتابیس ربات یافت نشد.")
        return
        
    try:
        file_size = os.path.getsize(DATABASE_PATH)
        if file_size > TELEGRAM_FILE_SIZE_LIMIT_BYTES:
            bot.send_message(chat_id, f"❌ خطا: حجم فایل دیتابیس ({escape_markdown(f'{file_size / (1024*1024):.2f}')} MB) زیاد است.")
            return
            
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_filename = f"backup_bot_db_{timestamp}.db"
        
        with open(DATABASE_PATH, "rb") as db_file:
            bot.send_document(
                chat_id, 
                db_file, 
                caption="✅ فایل پشتیبان دیتابیس ربات.",
                visible_file_name=backup_filename
            )
            
    except Exception as e:
        logger.error(f"Bot DB Backup failed: {e}")
        bot.send_message(chat_id, f"❌ خطای ناشناخته: {escape_markdown(str(e))}")

# <<<<<<<<<<<<<<<< تابع جدید برای پشتیبان‌گیری از هیدیفای >>>>>>>>>>>>>>>>
def _handle_hiddify_backup_request(call):
    """منطق پشتیبان‌گیری از کاربران پنل آلمان (Hiddify)."""
    chat_id, msg_id = call.from_user.id, call.message.message_id
    bot.answer_callback_query(call.id, "در حال دریافت اطلاعات...")
    _safe_edit(chat_id, msg_id, "⏳ در حال دریافت لیست کاربران از پنل آلمان (Hiddify)...")
    
    try:
        hiddify_users = hiddify_handler.get_all_users()
        if not hiddify_users:
            _safe_edit(chat_id, msg_id, "❌ هیچ کاربری در پنل آلمان یافت نشد.", reply_markup=menu.admin_backup_selection_menu())
            return
            
        backup_filename = f"hiddify_backup_{datetime.now().strftime('%Y-%m-%d')}.json"
        
        # فایل جیسون را به صورت موقت می‌سازیم
        with open(backup_filename, 'w', encoding='utf-8') as f:
            json.dump(hiddify_users, f, ensure_ascii=False, indent=4, default=str)
            
        # فایل را ارسال کرده و سپس حذف می‌کنیم
        with open(backup_filename, "rb") as backup_file:
            bot.send_document(chat_id, backup_file, caption=f"✅ فایل پشتیبان کاربران پنل آلمان ({len(hiddify_users)} کاربر).")
            
        os.remove(backup_filename)
        
    except Exception as e:
        logger.error(f"Hiddify backup failed: {e}")
        _safe_edit(chat_id, msg_id, f"❌ خطای ناشناخته: {escape_markdown(str(e))}", reply_markup=menu.admin_backup_selection_menu())

def _handle_marzban_backup_request(call):
    """منطق پشتیبان‌گیری از کاربران پنل فرانسه (Marzban)."""
    chat_id, msg_id = call.from_user.id, call.message.message_id
    bot.answer_callback_query(call.id, "در حال دریافت اطلاعات...")
    _safe_edit(chat_id, msg_id, "⏳ در حال دریافت لیست کاربران از پنل فرانسه (Marzban)...")
    
    try:
        marzban_users = marzban_handler.get_all_users()
        if not marzban_users:
            _safe_edit(chat_id, msg_id, "❌ هیچ کاربری در پنل فرانسه یافت نشد.", reply_markup=menu.admin_backup_selection_menu())
            return
            
        backup_filename = f"marzban_backup_{datetime.now().strftime('%Y-%m-%d')}.json"
        
        with open(backup_filename, 'w', encoding='utf-8') as f:
            # استفاده از default=str برای مدیریت آبجکت‌های datetime
            json.dump(marzban_users, f, ensure_ascii=False, indent=4, default=str)
            
        with open(backup_filename, "rb") as backup_file:
            bot.send_document(chat_id, backup_file, caption=f"✅ فایل پشتیبان کاربران پنل فرانسه ({len(marzban_users)} کاربر).")
            
        os.remove(backup_filename)
        
    except Exception as e:
        logger.error(f"Marzban backup failed: {e}")
        _safe_edit(chat_id, msg_id, f"❌ خطای ناشناخته: {escape_markdown(str(e))}", reply_markup=menu.admin_backup_selection_menu())