# bot/admin_handlers/backup.py

import logging
import os
import json
from datetime import datetime
from telebot import types

# --- START: MODIFIED IMPORTS ---
# هندلرهای API را به صورت کلاس وارد می‌کنیم، نه نمونه‌های آماده
from ..hiddify_api_handler import HiddifyAPIHandler
from ..marzban_api_handler import MarzbanAPIHandler
from ..database import db # دیتابیس برای خواندن پنل‌ها
# --- END: MODIFIED IMPORTS ---

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
    این تابع اصلی است که بر اساس پارامטר دریافتی، نوع پشتیبان‌گیری را تشخیص می‌دهد.
    """
    backup_type = params[0]
    if backup_type == "bot_db":
        _handle_bot_db_backup_request(call)
    elif backup_type == "marzban":
        _handle_panel_backup_request(call, 'marzban') # نوع پنل پاس داده می‌شود
    elif backup_type == "hiddify":
        _handle_panel_backup_request(call, 'hiddify') # نوع پنل پاس داده می‌شود

def _handle_bot_db_backup_request(call):
    """منطق پشتیبان‌گیری از دیتابیس ربات."""
    chat_id, msg_id = call.from_user.id, call.message.message_id
    bot.answer_callback_query(call.id, "در حال پردازش...")
    
    _safe_edit(chat_id, msg_id, "⏳ در حال ساخت پشتیبان از دیتابیس ربات...")

    if not os.path.exists(DATABASE_PATH):
        _safe_edit(chat_id, msg_id, "❌ فایل دیتابیس ربات یافت نشد.", reply_markup=menu.admin_backup_selection_menu())
        return
        
    try:
        file_size = os.path.getsize(DATABASE_PATH)
        if file_size > TELEGRAM_FILE_SIZE_LIMIT_BYTES:
            _safe_edit(chat_id, msg_id, f"❌ خطا: حجم فایل دیتابیس ({escape_markdown(f'{file_size / (1024*1024):.2f}')} MB) زیاد است.", reply_markup=menu.admin_backup_selection_menu())
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
        
        _safe_edit(chat_id, msg_id, "🗄️ لطفاً نوع پشتیبان‌گیری را انتخاب کنید:", reply_markup=menu.admin_backup_selection_menu())
            
    except Exception as e:
        logger.error(f"Bot DB Backup failed: {e}")
        _safe_edit(chat_id, msg_id, f"❌ خطای ناشناخته: {escape_markdown(str(e))}", reply_markup=menu.admin_backup_selection_menu())

def _handle_panel_backup_request(call, panel_type_to_backup: str):
    """منطق پشتیبان‌گیری داینامیک برای کاربران یک نوع پنل خاص (Hiddify یا Marzban)."""
    chat_id, msg_id = call.from_user.id, call.message.message_id
    bot.answer_callback_query(call.id, "در حال دریافت اطلاعات...")
    
    panel_name_fa = "Hiddify" if panel_type_to_backup == 'hiddify' else "Marzban"
    _safe_edit(chat_id, msg_id, f"⏳ در حال دریافت لیست کاربران از تمام پنل‌های نوع {panel_name_fa}...")
    
    try:
        all_users_for_type = []
        # ۱. تمام پنل‌های فعال را از دیتابیس بخوان
        active_panels = db.get_active_panels()
        
        # ۲. فقط پنل‌هایی که از نوع درخواستی هستند را فیلتر کن
        target_panels = [p for p in active_panels if p['panel_type'] == panel_type_to_backup]

        if not target_panels:
            _safe_edit(chat_id, msg_id, f"❌ هیچ پنل فعالی از نوع {panel_name_fa} یافت نشد.", reply_markup=menu.admin_backup_selection_menu())
            return

        # ۳. برای هر پنل، یک handler بساز و کاربرانش را بگیر
        for panel_config in target_panels:
            handler = None
            if panel_type_to_backup == 'hiddify':
                handler = HiddifyAPIHandler(panel_config)
            elif panel_type_to_backup == 'marzban':
                handler = MarzbanAPIHandler(panel_config)

            if handler:
                users = handler.get_all_users()
                if users:
                    all_users_for_type.extend(users)
        
        if not all_users_for_type:
            _safe_edit(chat_id, msg_id, f"❌ هیچ کاربری در پنل‌های {panel_name_fa} یافت نشد.", reply_markup=menu.admin_backup_selection_menu())
            return
            
        backup_filename = f"{panel_type_to_backup}_backup_{datetime.now().strftime('%Y-%m-%d')}.json"
        
        with open(backup_filename, 'w', encoding='utf-8') as f:
            json.dump(all_users_for_type, f, ensure_ascii=False, indent=4, default=str)
            
        with open(backup_filename, "rb") as backup_file:
            bot.send_document(chat_id, backup_file, caption=f"✅ فایل پشتیبان کاربران پنل‌های {panel_name_fa} ({len(all_users_for_type)} کاربر).")
            
        os.remove(backup_filename)

        _safe_edit(chat_id, msg_id, "🗄️ لطفاً نوع پشتیبان‌گیری را انتخاب کنید:", reply_markup=menu.admin_backup_selection_menu())
        
    except Exception as e:
        logger.error(f"{panel_name_fa} backup failed: {e}", exc_info=True)
        _safe_edit(chat_id, msg_id, f"❌ خطای ناشناخته: {escape_markdown(str(e))}", reply_markup=menu.admin_backup_selection_menu())