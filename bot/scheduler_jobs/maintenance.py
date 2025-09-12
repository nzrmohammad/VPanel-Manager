import logging
from datetime import datetime
import pytz

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


def sync_users_with_panels(bot) -> None:
    """
    به صورت دوره‌ای، کاربرانی که از پنل‌ها حذف شده‌اند را در دیتابیس ربات غیرفعال می‌کند.
    """
    logger.info("SCHEDULER: Starting user synchronization with panels.")
    try:
        panel_uuids = {user['uuid'] for user in combined_handler.get_all_users_combined() if user.get('uuid')}
        if not panel_uuids:
            logger.warning("SYNC: Could not fetch any users from panels. Aborting sync.")
            return

        bot_uuids = {row['uuid'] for row in db.all_active_uuids()}
        
        uuids_to_deactivate = bot_uuids - panel_uuids
        
        if uuids_to_deactivate:
            logger.warning(f"SYNC: Found {len(uuids_to_deactivate)} orphan UUIDs to deactivate.")
            for uuid_str in uuids_to_deactivate:
                uuid_record = db.get_user_uuid_record(uuid_str)
                if uuid_record:
                    db.deactivate_uuid(uuid_record['id'])
                    logger.info(f"SYNC: Deactivated orphan user with UUID: {uuid_str}")
        else:
            logger.info("SYNC: Database is already in sync with panels.")

    except Exception as e:
        logger.error(f"Error during user synchronization: {e}", exc_info=True)
    finally:
        logger.info("SCHEDULER: User synchronization finished.")


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