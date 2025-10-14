import logging
from datetime import datetime
import pytz
import asyncio
import time
from ..database import Database

from telebot import apihelper

from bot import combined_handler
from bot.database import db
from bot.menu import menu
from bot.admin_formatters import fmt_online_users_list

logger = logging.getLogger(__name__)

def hourly_snapshots(bot) -> None:
    """
    به صورت ساعتی از مصرف تمام کاربران فعال یک اسنپ‌شات (عکس لحظه‌ای) تهیه می‌کند.
    """
    logger.info("SCHEDULER (Snapshot): Starting hourly usage snapshot job.")
    try:
        all_users_info = combined_handler.get_all_users_combined()
        if not all_users_info:
            logger.warning("SCHEDULER (Snapshot): No user info could be fetched. Aborting job.")
            return
        
        user_info_map = {user['uuid']: user for user in all_users_info if user.get('uuid')}
        all_uuids_from_db = list(db.all_active_uuids())
        
        for u_row in all_uuids_from_db:
            try:
                uuid_str = u_row['uuid']
                if uuid_str in user_info_map:
                    info = user_info_map[uuid_str]
                    breakdown = info.get('breakdown', {})
                    h_usage, m_usage = 0.0, 0.0

                    for panel_details in breakdown.values():
                        panel_type = panel_details.get('type')
                        panel_data = panel_details.get('data', {})
                        if panel_type == 'hiddify':
                            h_usage += panel_data.get('current_usage_GB', 0.0)
                        elif panel_type == 'marzban':
                            m_usage += panel_data.get('current_usage_GB', 0.0)
                    
                    db.add_usage_snapshot(u_row['id'], h_usage, m_usage)
            except Exception as e:
                logger.error(f"SCHEDULER (Snapshot): Failed to process for uuid_id {u_row['id']}: {e}")
        logger.info("SCHEDULER (Snapshot): Finished hourly usage snapshot job successfully.")
    except Exception as e:
        logger.error(f"SCHEDULER (Snapshot): A critical error occurred: {e}", exc_info=True)


def update_online_reports(bot) -> None:
    """
    پیام‌های گزارش کاربران آنلاین را (در صورت وجود) به‌روزرسانی می‌کند.
    """
    messages_to_update = db.get_scheduled_messages('online_users_report')
    if not messages_to_update:
        return
            
    online_list = [u for u in combined_handler.get_all_users_combined() if u.get('last_online') and (datetime.now(pytz.utc) - u['last_online']).total_seconds() < 180]
    for user in online_list:
        if user.get('uuid'):
            user['daily_usage_GB'] = sum(db.get_usage_since_midnight_by_uuid(user['uuid']).values())
    
    text = fmt_online_users_list(online_list, 0)
    kb = menu.create_pagination_menu("admin:list:online_users:both", 0, len(online_list), "admin:reports_menu") 
    
    for msg_info in messages_to_update:
        try:
            bot.edit_message_text(text, msg_info['chat_id'], msg_info['message_id'], reply_markup=kb, parse_mode="MarkdownV2")
        except apihelper.ApiTelegramException as e:
            if 'message to edit not found' in str(e) or 'message is not modified' in str(e):
                db.delete_scheduled_message(msg_info['id'])
            else:
                logger.error(f"Scheduler: Failed to update online report for chat {msg_info['chat_id']}: {e}")

def nightly_baseline_reset(bot) -> None:
    """
    Creates a new baseline snapshot for all active users shortly after midnight.
    This ensures accurate daily usage tracking.
    """
    logger.info("SCHEDULER: Running nightly baseline reset for usage stats.")
    db = Database()
    try:
        all_users_info = combined_handler.get_all_users_combined()
        if not all_users_info:
            logger.warning("NIGHTLY RESET: Could not fetch any user info from panels. Aborting baseline reset.")
            return

        user_info_map = {user['uuid']: user for user in all_users_info if user.get('uuid')}
        
        # با توجه به کد شما، تابع all_active_uuids لیست کاملی از کاربران فعال را برمی‌گرداند
        all_active_db_users = list(db.all_active_uuids())
        
        reset_count = 0
        for u_row in all_active_db_users:
            user_id = u_row['id']
            uuid_str = u_row['uuid']
            
            if uuid_str in user_info_map:
                info = user_info_map[uuid_str]
                breakdown = info.get('breakdown', {})
                
                # محاسبه مجموع مصرف از تمام پنل‌های هر نوع
                h_usage = sum(p.get('data', {}).get('current_usage_GB', 0.0) for p in breakdown.values() if p.get('type') == 'hiddify')
                m_usage = sum(p.get('data', {}).get('current_usage_GB', 0.0) for p in breakdown.values() if p.get('type') == 'marzban')
                
                db.add_usage_snapshot(user_id, h_usage, m_usage)
                reset_count += 1
        
        logger.info(f"NIGHTLY RESET: Successfully created new baseline snapshots for {reset_count} active users.")
    except Exception as e:
        logger.error(f"NIGHTLY RESET: A critical error occurred during the baseline reset job: {e}", exc_info=True)

def sync_users_with_panels(bot):
    """
    (نسخه اصلاح شده با اجرای غیرمسدود دیتابیس)
    اطلاعات کاربران را از پنل‌ها دریافت کرده و دیتابیس محلی را به‌روزرسانی می‌کند.
    عملیات دیتابیس در یک ترد جداگانه اجرا می‌شود تا از بلاک شدن برنامه اصلی جلوگیری شود.
    """
    async def async_sync():
        start_time = time.time()
        logger.info("SYNCER: Starting panel data synchronization cycle.")

        try:
            # ۱. دریافت تمام کاربران از پنل‌ها (عملیات تحت شبکه)
            all_users_from_api = combined_handler.get_all_users_combined()

            if not all_users_from_api:
                logger.warning("SYNCER: Fetched user list from panels is empty. Skipping sync cycle.")
                return

            # ۲. دریافت اطلاعات کاربران فعلی از دیتابیس (عملیات I/O)
            loop = asyncio.get_running_loop()
            
            # اجرای عملیات خواندن از دیتابیس در یک ترد جداگانه
            db_users = await loop.run_in_executor(
                None, db.get_all_user_uuids_and_panel_data
            )
            db_users_map = {user['uuid']: user for user in db_users} if db_users else {}

            logger.info(f"SYNCER: Fetched {len(all_users_from_api)} users from panels and {len(db_users_map)} users from local DB.")
            
            update_tasks = []

            # ۳. مقایسه و آماده‌سازی تسک‌های آپدیت
            for user_data in all_users_from_api:
                uuid = user_data.get('uuid')
                if not uuid:
                    continue

                db_user = db_users_map.get(uuid)
                
                # فقط در صورتی که داده‌ها تغییر کرده باشند، آپدیت کن
                if not db_user or \
                   db_user.get('used_traffic_hiddify') != user_data.get('used_traffic_hiddify', 0) or \
                   db_user.get('used_traffic_marzban') != user_data.get('used_traffic_marzban', 0) or \
                   db_user.get('last_online_jalali') != user_data.get('last_online_jalali', None):
                    
                    # بسته‌بندی تابع آپدیت و آرگومان‌های آن برای اجرا در ترد دیگر
                    task = loop.run_in_executor(
                        None,
                        db.add_or_update_user_from_panel,
                        uuid,
                        user_data.get('name'),
                        user_data.get('telegram_id'),
                        user_data.get('expire_days_hiddify'),
                        user_data.get('expire_days_marzban'),
                        user_data.get('last_online_jalali'),
                        user_data.get('used_traffic_hiddify', 0),
                        user_data.get('used_traffic_marzban', 0)
                    )
                    update_tasks.append(task)

            if not update_tasks:
                logger.info("SYNCER: No user data changes detected. Database is already up to date.")
            else:
                logger.info(f"SYNCER: Starting database update for {len(update_tasks)} users with changed data.")
                await asyncio.gather(*update_tasks)
                logger.info("SYNCER: Database update for all users completed successfully.")

        except Exception as e:
            logger.error(f"SYNCER: An unexpected error occurred during the async sync cycle: {e}", exc_info=True)
        
        end_time = time.time()
        logger.info(f"SYNCER: Synchronization cycle finished in {end_time - start_time:.2f} seconds.")

    # چون کتابخانه schedule به صورت async نیست، ما تابع async خود را در یک event loop جدید اجرا می‌کنیم.
    try:
        asyncio.run(async_sync())
    except RuntimeError: # اگر یک event loop از قبل در این ترد در حال اجرا باشد
        loop = asyncio.get_event_loop()
        loop.run_until_complete(async_sync())


def cleanup_old_reports(bot) -> None:
    """
    پیام‌های گزارش قدیمی را که توسط کاربران برای حذف خودکار تنظیم شده‌اند، پاک می‌کند.
    """
    reports_to_delete = db.get_old_reports_to_delete(hours=12)
    for report in reports_to_delete:
        try:
            bot.delete_message(chat_id=report['user_id'], message_id=report['message_id'])
        except apihelper.ApiTelegramException as e:
            if 'message to delete not found' not in str(e):
                logger.error(f"API error deleting report for user {report['user_id']}: {e}")
        finally:
            db.delete_sent_report_record(report['id'])


def run_monthly_vacuum(bot) -> None:
    """
    اسنپ‌شات‌های قدیمی را حذف کرده و در روز اول هر ماه، دیتابیس را بهینه‌سازی می‌کند.
    """
    db.delete_old_snapshots(days_to_keep=7)
    if datetime.now(pytz.timezone("Asia/Tehran")).day == 1:
        logger.info("SCHEDULER: It's the first day of the month. Running database VACUUM.")
        db.vacuum_db()