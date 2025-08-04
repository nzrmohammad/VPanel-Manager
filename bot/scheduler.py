import logging
import threading
import time
from datetime import datetime
import schedule
import pytz
from telebot import apihelper, TeleBot
from .settings_manager import settings
from .database import db
from . import combined_handler
from .utils import escape_markdown, format_daily_usage
from .menu import menu
from .admin_formatters import fmt_admin_report, fmt_online_users_list
from .user_formatters import fmt_user_report
from .config import ADMIN_IDS
import jdatetime

logger = logging.getLogger(__name__)

class SchedulerManager:
    def __init__(self, bot: TeleBot) -> None:
        self.bot = bot
        self.running = False
        self.tz = pytz.timezone("Asia/Tehran")
        self.tz_str = str(self.tz)

    def _hourly_snapshots(self) -> None:
        logger.info("Scheduler: Running hourly usage snapshot job.")
        
        all_users_info = combined_handler.get_all_users_combined()
        if not all_users_info:
            return
            
        user_info_map = {user['uuid']: user for user in all_users_info}

        all_uuids_from_db = db.all_active_uuids()
        if not all_uuids_from_db:
            return

        for u_row in all_uuids_from_db:
            try:
                uuid_str = u_row['uuid']
                if uuid_str in user_info_map:
                    info = user_info_map[uuid_str]
                    
                    breakdown = info.get('breakdown', {})
                    h_info = breakdown.get('hiddify', {})
                    m_info = breakdown.get('marzban', {})
                    
                    h_usage = h_info.get('current_usage_GB', 0.0) if h_info else 0.0
                    m_usage = m_info.get('current_usage_GB', 0.0) if m_info else 0.0

                    db.add_usage_snapshot(u_row['id'], h_usage, m_usage)

            except Exception as e:
                logger.error(f"Scheduler: Failed to process snapshot for uuid_id {u_row['id']}: {e}")

    def _check_for_warnings(self) -> None:
        logger.info("Scheduler: Running warnings check job.")
        
        all_uuids_from_db = db.all_active_uuids()
        if not all_uuids_from_db:
            logger.info("SCHEDULER: No active UUIDs in DB to check warnings for. JOB STOPPED.")
            return

        all_users_info_map = {u['uuid']: u for u in combined_handler.get_all_users_combined()}
        
        for u_row in all_uuids_from_db:
            uuid_str = u_row['uuid']
            uuid_id_in_db = u_row['id']
            user_id_in_telegram = u_row['user_id']
            logger.info(f"SCHEDULER: Checking warnings for UUID: {uuid_str} (User ID: {user_id_in_telegram})")
            
            info = all_users_info_map.get(uuid_str)
            if not info:
                continue

            user_settings = db.get_user_settings(user_id_in_telegram)
            user_name = escape_markdown(info.get('name', 'کاربر ناشناس'))

            # 1. Welcome Message Logic
            if info.get('last_online') and not u_row.get('first_connection_time'):
                db.set_first_connection_time(uuid_id_in_db, datetime.now(pytz.utc))
            
            if u_row.get('first_connection_time') and not u_row.get('welcome_message_sent'):
                first_conn_time = u_row['first_connection_time'].replace(tzinfo=pytz.utc)
                delay_minutes = settings.get('WELCOME_MESSAGE_DELAY_MINUTES', 2880)
                if (datetime.now(pytz.utc) - first_conn_time).total_seconds() >= delay_minutes * 60:
                    welcome_text = (
                        f"🎉 *به جمع ما خوش آمدی\\!* 🎉\n\n"
                        f"از اینکه به ما اعتماد کردی خوشحالیم\\. امیدواریم از کیفیت سرویس لذت ببری\\.\n\n"
                        f"💬 در صورت داشتن هرگونه سوال یا نیاز به پشتیبانی، ما همیشه در کنار شما هستیم\\.\n\n"
                        f"با آرزوی بهترین‌ها ✨"
                    )
                    try:
                        self.bot.send_message(user_id_in_telegram, welcome_text, parse_mode="MarkdownV2")
                        db.mark_welcome_message_as_sent(uuid_id_in_db)
                        logger.info(f"Welcome message sent to user {user_id_in_telegram}")
                    except Exception as e:
                        logger.error(f"Failed to send welcome message to user {user_id_in_telegram}: {e}")

            # 2. Expiry Warning
            if user_settings.get('expiry_warnings'):
                expire_days = info.get('expire')
                warning_days = settings.get('WARNING_DAYS_BEFORE_EXPIRY', 7)
                if expire_days is not None and 0 <= expire_days <= warning_days:
                    if not db.has_recent_warning(uuid_id_in_db, 'expiry', hours=24):
                        msg = (f"⚠️ *هشدار انقضای اکانت*\n\n"
                               f"اکانت *{user_name}* شما تا *{escape_markdown(str(expire_days))}* روز دیگر منقضی می‌شود\\.")
                        try:
                            self.bot.send_message(user_id_in_telegram, msg, parse_mode="MarkdownV2")
                            db.log_warning(uuid_id_in_db, 'expiry')
                        except Exception as e:
                            logger.error(f"Failed to send expiry warning to user {user_id_in_telegram}: {e}")

            # 3. Data Usage Warning
            breakdown = info.get('breakdown', {})
            server_map = {
                'hiddify': {'name': 'آلمان 🇩🇪', 'setting': 'data_warning_hiddify'},
                'marzban': {'name': 'فرانسه 🇫🇷', 'setting': 'data_warning_marzban'}
            }
            usage_threshold = settings.get('WARNING_USAGE_THRESHOLD', 90)
            for code, details in server_map.items():
                if user_settings.get(details['setting']) and code in breakdown and breakdown[code]:
                    server_info = breakdown[code]
                    limit = server_info.get('usage_limit_GB', 0.0)
                    usage = server_info.get('current_usage_GB', 0.0)
                    if limit > 0 and (usage / limit * 100) >= usage_threshold:
                        warning_type = f'low_data_{code}'
                        if not db.has_recent_warning(uuid_id_in_db, warning_type, hours=24):
                            remaining_gb = max(0, limit - usage)
                            msg = (f"⚠️ *هشدار اتمام حجم*\n\n"
                                   f"کاربر گرامی، حجم اکانت *{user_name}* شما در سرور *{escape_markdown(details['name'])}* رو به اتمام است\\.\n"
                                   f"\\- حجم باقیمانده: *{escape_markdown(f'{remaining_gb:.2f}')} GB*")
                            try:
                                self.bot.send_message(user_id_in_telegram, msg, parse_mode="MarkdownV2")
                                db.log_warning(uuid_id_in_db, warning_type)
                            except Exception as e:
                                logger.error(f"Failed to send data warning to user {user_id_in_telegram}: {e}")

    def _nightly_report(self) -> None:
        tehran_tz = pytz.timezone("Asia/Tehran")
        now_gregorian = datetime.now(tehran_tz)
        now_shamsi = jdatetime.datetime.fromgregorian(datetime=now_gregorian)
        now_str = now_shamsi.strftime("%Y/%m/%d - %H:%M")
        logger.info(f"SCHEDULER: ----- Running nightly report at {now_str} -----")
        
        all_users_info_from_api = combined_handler.get_all_users_combined()
        if not all_users_info_from_api:
            logger.warning("SCHEDULER: Could not fetch any user info from API. JOB STOPPED.")
            return
            
        logger.info(f"SCHEDULER: Fetched {len(all_users_info_from_api)} total users from API.")
        
        user_info_map = {user['uuid']: user for user in all_users_info_from_api}
        all_bot_users = db.get_all_user_ids()
        separator = '\n' + '─' * 18 + '\n'

        for user_id in all_bot_users:
            logger.info(f"SCHEDULER: ----- Processing user_id: {user_id} -----")
                
            try:
                user_settings = db.get_user_settings(user_id)
                if not user_settings.get('daily_reports', True):
                    logger.info(f"SCHEDULER: User {user_id} has disabled daily reports. Skipping.")
                    continue
                    
                # --- Admin Report ---
                if user_id in ADMIN_IDS:
                    logger.info(f"SCHEDULER: User {user_id} is an ADMIN. Generating admin report.")
                    # FIX 1: کاراکتر '-' به درستی escape شده است
                    header = f"👑 *گزارش جامع* {escape_markdown('-')} {escape_markdown(now_str)}{separator}"
                    report_text = fmt_admin_report(all_users_info_from_api, db)
                    try:
                        self.bot.send_message(user_id, header + report_text, parse_mode="MarkdownV2")
                        logger.info(f"SCHEDULER: Admin report sent to {user_id}.")
                    except Exception as e:
                        logger.error(f"SCHEDULER: Failed to send ADMIN report to {user_id}: {e}", exc_info=True)

                # --- User Report (for ALL users, including admins) ---
                logger.info(f"SCHEDULER: Now checking for personal user report for user_id: {user_id}.")
                user_uuids_from_db = db.uuids(user_id)
                user_infos_for_report = []
                    
                if not user_uuids_from_db:
                    logger.warning(f"SCHEDULER: User {user_id} has no UUIDs registered in the bot's DB. Skipping user report.")
                else:
                    logger.info(f"SCHEDULER: User {user_id} has {len(user_uuids_from_db)} UUID(s) in DB. Matching with API data...")
                    for u_row in user_uuids_from_db:
                        if u_row['uuid'] in user_info_map:
                            user_data = user_info_map[u_row['uuid']]
                            user_data['db_id'] = u_row['id'] 
                            user_infos_for_report.append(user_data)
                        
                    if user_infos_for_report:
                        logger.info(f"SCHEDULER: Found {len(user_infos_for_report)} active account(s) for user {user_id}. Generating report.")
                        # FIX 1: کاراکتر '-' به درستی escape شده است
                        header = f"🌙 *گزارش روزانه* {escape_markdown('-')} {escape_markdown(now_str)}{separator}"
                        
                        # FIX 2: کد زبان کاربر از دیتابیس خوانده شده و به تابع ارسال می‌شود
                        lang_code = db.get_user_language(user_id)
                        report_text = fmt_user_report(user_infos_for_report, lang_code)
                        
                        try:
                            self.bot.send_message(user_id, header + report_text, parse_mode="MarkdownV2")
                            logger.info(f"SCHEDULER: Personal user report sent to {user_id}.")
                        except Exception as e:
                            logger.error(f"SCHEDULER: Failed to send USER report to {user_id}: {e}", exc_info=True)
                    else:
                        logger.warning(f"SCHEDULER: No active accounts found in API for user {user_id} after matching. No user report will be sent.")

                # --- Cleanup Snapshots ---
                if user_uuids_from_db:
                    for info in user_uuids_from_db:
                        db.delete_daily_snapshots(info['id'])
                    logger.info(f"Scheduler: Cleaned up daily snapshots for user {user_id}.")
                            
            except Exception as e:
                logger.error(f"SCHEDULER: CRITICAL FAILURE while processing main loop for user {user_id}: {e}", exc_info=True)
                continue # Go to the next user

    def _update_online_reports(self) -> None:
        logger.info("Scheduler: Running 3-hourly online user report update.")
        
        messages_to_update = db.get_scheduled_messages('online_users_report')
        
        for msg_info in messages_to_update:
            try:
                chat_id = msg_info['chat_id']
                message_id = msg_info['message_id']
                
                online_list = [u for u in combined_handler.get_all_users_combined() if u.get('last_online') and (datetime.now(pytz.utc) - u['last_online']).total_seconds() < 180]

                for user in online_list:
                    if user.get('uuid'):
                        user['daily_usage_GB'] = sum(db.get_usage_since_midnight_by_uuid(user['uuid']).values())
                
                text = fmt_online_users_list(online_list, 0)
                # Note: The back button here is a placeholder as this is an automated update.
                kb = menu.create_pagination_menu("admin:list:online_users:both", 0, len(online_list), "admin:reports_menu") 
                
                self.bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="MarkdownV2")
                time.sleep(0.5)
            except apihelper.ApiTelegramException as e:
                if 'message to edit not found' in str(e) or 'message is not modified' in str(e):
                    db.delete_scheduled_message(msg_info['id'])
                else:
                    logger.error(f"Scheduler: Failed to update online report for chat {chat_id}: {e}")
            except Exception as e:
                logger.error(f"Scheduler: Generic error updating online report for chat {chat_id}: {e}")

    def _birthday_gifts_job(self) -> None:
        logger.info("Scheduler: Running daily birthday gift job.")
        today_birthday_users = db.get_todays_birthdays()
        
        if not today_birthday_users:
            return

        gift_gb = settings.get('BIRTHDAY_GIFT_GB', 15)
        gift_days = settings.get('BIRTHDAY_GIFT_DAYS', 15)

        for user_id in today_birthday_users:
            user_uuids = db.uuids(user_id)
            if not user_uuids: continue
            
            gift_applied_successfully = False
            for row in user_uuids:
                if combined_handler.modify_user_on_all_panels(row['uuid'], add_gb=gift_gb, add_days=gift_days):
                    gift_applied_successfully = True
            
            if gift_applied_successfully:
                try:
                    gift_message = (
                        f"🎉 *تولدت مبارک\\!* 🎉\n\n"
                        f"امیدواریم سالی پر از شادی و موفقیت پیش رو داشته باشی\\.\n"
                        f"ما به همین مناسبت، هدیه‌ای برای شما فعال کردیم:\n\n"
                        f"🎁 `{escape_markdown(str(gift_gb))} GB` حجم و `{escape_markdown(str(gift_days))}` روز به تمام اکانت‌های شما **به صورت خودکار اضافه شد\\!**\n\n"
                        f"می‌توانی با مراجعه به بخش مدیریت اکانت، جزئیات جدید را مشاهده کنی\\."
                    )
                    self.bot.send_message(user_id, gift_message, parse_mode="MarkdownV2")
                except Exception as e:
                    logger.error(f"Scheduler: Failed to send birthday message to user {user_id}: {e}")
                    
    def _run_monthly_vacuum(self) -> None:
        today = datetime.now(self.tz)
        if today.day == 1:
            logger.info("Scheduler: It's the first of the month, running database VACUUM job.")
            try:
                db.vacuum_db()
                logger.info("Scheduler: Database VACUUM completed successfully.")
            except Exception as e:
                logger.error(f"Scheduler: Database VACUUM failed: {e}")

    def reschedule_jobs(self):
        logger.info("SCHEDULER: Rescheduling jobs due to settings change...")
        settings.reload()
        
        schedule.clear()
        
        report_time_str = settings.get('DAILY_REPORT_TIME', "23:59")
        warning_check_minutes = settings.get('USAGE_WARNING_CHECK_MINUTES', 60)
        
        schedule.every().hour.at(":01").do(self._hourly_snapshots)
        schedule.every(warning_check_minutes).minutes.do(self._check_for_warnings)
        schedule.every().day.at(report_time_str, self.tz_str).do(self._nightly_report)
        schedule.every(3).hours.do(self._update_online_reports)
        schedule.every().day.at("00:05", self.tz_str).do(self._birthday_gifts_job)
        schedule.every().day.at("04:00", self.tz_str).do(self._run_monthly_vacuum)
        
        logger.info(f"Scheduler jobs re-configured. New report time: {report_time_str}")

    def start(self) -> None:
        if self.running: return
        
        report_time_str = settings.get('DAILY_REPORT_TIME', "23:59")
        warning_check_minutes = settings.get('USAGE_WARNING_CHECK_MINUTES', 60)
        
        schedule.every().hour.at(":01").do(self._hourly_snapshots)
        schedule.every(warning_check_minutes).minutes.do(self._check_for_warnings)
        schedule.every().day.at(report_time_str, self.tz_str).do(self._nightly_report)
        schedule.every(3).hours.do(self._update_online_reports)
        schedule.every().day.at("00:05", self.tz_str).do(self._birthday_gifts_job)
        schedule.every().day.at("04:00", self.tz_str).do(self._run_monthly_vacuum)
        
        self.running = True
        threading.Thread(target=self._runner, daemon=True).start()
        logger.info(f"Scheduler started. Nightly report at {report_time_str} ({self.tz_str}).")

    def shutdown(self) -> None:
        logger.info("Scheduler: Shutting down...")
        schedule.clear()
        self.running = False

    def _runner(self) -> None:
        while self.running:
            try:
                schedule.run_pending()
            except Exception as exc:
                logger.error(f"Scheduler loop error: {exc}")
            time.sleep(60)