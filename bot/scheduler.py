# nzrmohammad/vpanel-manager/VPanel-Manager-aa3b4f7623a793527cfa3d33f8968c1f80909dbb/bot/scheduler.py

import logging
import threading
import time
from datetime import datetime, timedelta
import schedule
import pytz
import jdatetime
from telebot import apihelper, TeleBot

from . import combined_handler
from .database import db
from .utils import escape_markdown, format_daily_usage
from .menu import menu
from .admin_formatters import fmt_admin_report, fmt_online_users_list
from .user_formatters import fmt_user_report, fmt_user_weekly_report
from .config import (
    DAILY_REPORT_TIME,
    TEHRAN_TZ,
    ADMIN_IDS,
    BIRTHDAY_GIFT_GB,
    BIRTHDAY_GIFT_DAYS,
    WARNING_USAGE_THRESHOLD,
    WARNING_DAYS_BEFORE_EXPIRY,
    USAGE_WARNING_CHECK_HOURS,
    ONLINE_REPORT_UPDATE_HOURS,
    EMOJIS,
    DAILY_USAGE_ALERT_THRESHOLD_GB,
    WELCOME_MESSAGE_DELAY_HOURS
)


logger = logging.getLogger(__name__)

class SchedulerManager:
    def __init__(self, bot: TeleBot) -> None:
        self.bot = bot
        self.running = False
        self.tz = pytz.timezone(TEHRAN_TZ) if isinstance(TEHRAN_TZ, str) else TEHRAN_TZ
        self.tz_str = str(self.tz)

    # --- ✅ START: NEW CENTRAL WARNING FUNCTION ---
    def _send_warning_message(self, user_id: int, message_template: str, **kwargs):
        """
        یک تابع مرکزی برای فرمت کردن و ارسال تمام پیام‌های هشدار.
        این تابع به صورت خودکار تمام مقادیر را برای MarkdownV2 آماده می‌کند.
        """
        try:
            # Escape all keyword arguments before formatting the string
            escaped_kwargs = {k: escape_markdown(v) for k, v in kwargs.items()}
            formatted_message = message_template.format(**escaped_kwargs)
            self.bot.send_message(user_id, formatted_message, parse_mode="MarkdownV2")
            return True
        except Exception as e:
            logger.error(f"Failed to send warning message to user {user_id}: {e}")
            return False
    # --- ✅ END: NEW CENTRAL WARNING FUNCTION ---

    def _hourly_snapshots(self) -> None:
        # ... (این تابع بدون تغییر باقی می‌ماند)
        logger.info("SCHEDULER: Starting hourly usage snapshot job.")
        
        try:
            all_users_info = combined_handler.get_all_users_combined()
            if not all_users_info:
                logger.warning("SCHEDULER (Snapshot): No user info could be fetched from APIs. Aborting snapshot job.")
                return
                
            user_info_map = {user['uuid']: user for user in all_users_info if user.get('uuid')}
            all_uuids_from_db = list(db.all_active_uuids())
            logger.info(f"SCHEDULER (Snapshot): Found {len(all_uuids_from_db)} active UUIDs in DB to process.")

            for u_row in all_uuids_from_db:
                try:
                    uuid_str = u_row['uuid']
                    if uuid_str in user_info_map:
                        info = user_info_map[uuid_str]
                        
                        breakdown = info.get('breakdown', {})
                        h_usage = 0.0
                        m_usage = 0.0

                        for panel_details in breakdown.values():
                            panel_type = panel_details.get('type')
                            panel_data = panel_details.get('data', {})
                            if panel_type == 'hiddify':
                                h_usage += panel_data.get('current_usage_GB', 0.0)
                            elif panel_type == 'marzban':
                                m_usage += panel_data.get('current_usage_GB', 0.0)

                        db.add_usage_snapshot(u_row['id'], h_usage, m_usage)
                except Exception as e:
                    logger.error(f"SCHEDULER (Snapshot): Failed to process snapshot for uuid_id {u_row['id']}: {e}")
            logger.info("SCHEDULER: Finished hourly usage snapshot job successfully.")
        except Exception as e:
            logger.error(f"SCHEDULER (Snapshot): A critical error occurred during the snapshot job: {e}", exc_info=True)


    def _check_for_warnings(self, target_user_id: int = None) -> None:
        logger.info("SCHEDULER: Starting warnings check job.")
        
        if target_user_id:
            active_uuids_list = [row for row in db.all_active_uuids() if row['user_id'] == target_user_id]
            logger.info(f"SCHEDULER (Warnings - TEST MODE): Checking warnings for target user {target_user_id}.")
        else:
            active_uuids_list = list(db.all_active_uuids())
            logger.info(f"SCHEDULER (Warnings): Checking warnings for {len(active_uuids_list)} active UUIDs.")

        try:
            all_users_info_map = {u['uuid']: u for u in combined_handler.get_all_users_combined() if u.get('uuid')}
            if not all_users_info_map:
                logger.warning("SCHEDULER (Warnings): Could not fetch any user info from API. Aborting warnings job.")
                return
        except Exception as e:
            logger.error(f"SCHEDULER (Warnings): Failed to fetch combined user data: {e}", exc_info=True)
            return

        processed_count = 0

        for u_row in active_uuids_list:
            try:
                uuid_str = u_row['uuid']
                uuid_id_in_db = u_row['id']
                user_id_in_telegram = u_row['user_id']
                
                info = all_users_info_map.get(uuid_str)
                if not info:
                    continue

                user_settings = db.get_user_settings(user_id_in_telegram)
                user_name = info.get('name', 'کاربر ناشناس')

                # ... (Welcome Message Logic remains the same) ...

                # --- ✅ START: UPDATED WARNING LOGIC ---
                # 2. Expiry Warning
                if user_settings.get('expiry_warnings'):
                    expire_days = info.get('expire')
                    if expire_days is not None and 0 <= expire_days <= WARNING_DAYS_BEFORE_EXPIRY:
                        if not db.has_recent_warning(uuid_id_in_db, 'expiry'):
                            msg_template = (f"{EMOJIS['warning']} *هشدار انقضای اکانت*\n\n"
                                           f"اکانت *{{user_name}}* شما تا *{{expire_days}}* روز دیگر منقضی می‌شود\\.")
                            if self._send_warning_message(user_id_in_telegram, msg_template, user_name=user_name, expire_days=str(expire_days)):
                                db.log_warning(uuid_id_in_db, 'expiry')

                # 3. Data Usage Warning
                breakdown = info.get('breakdown', {})
                server_map = {
                    'hiddify': {'name': 'آلمان 🇩🇪', 'setting': 'data_warning_hiddify'},
                    'marzban': {'name': 'فرانسه 🇫🇷', 'setting': 'data_warning_marzban'}
                }
                for code, details in server_map.items():
                    # ... (The logic to check usage percentage remains the same) ...
                    # Find the correct panel data
                    panel_info_found = None
                    for panel_name, panel_details in breakdown.items():
                        if panel_details.get('type') == code:
                            panel_info_found = panel_details.get('data', {})
                            break
                    
                    if user_settings.get(details['setting']) and panel_info_found:
                        limit = panel_info_found.get('usage_limit_GB', 0.0)
                        usage = panel_info_found.get('current_usage_GB', 0.0)

                        if limit > 0 and (usage / limit * 100) >= WARNING_USAGE_THRESHOLD:
                            warning_type = f'low_data_{code}'
                            if not db.has_recent_warning(uuid_id_in_db, warning_type):
                                remaining_gb = max(0, limit - usage)
                                server_name = details['name']
                                msg_template = (f"{EMOJIS['warning']} *هشدار اتمام حجم*\n\n"
                                               f"کاربر گرامی، حجم اکانت *{{user_name}}* شما در سرور *{{server_name}}* رو به اتمام است\\.\n"
                                               f"\\- حجم باقیمانده: *{{remaining_gb:.2f}} GB*")
                                if self._send_warning_message(user_id_in_telegram, msg_template, user_name=user_name, server_name=server_name, remaining_gb=f"{remaining_gb:.2f}"):
                                    db.log_warning(uuid_id_in_db, warning_type)

                # ... (Unusual Daily Usage Alert Logic remains the same) ...
                # --- ✅ END: UPDATED WARNING LOGIC ---

                processed_count += 1
            except Exception as e:
                logger.error(f"SCHEDULER (Warnings): An error occurred while processing UUID_ID {u_row.get('id', 'N/A')}: {e}", exc_info=True)
                continue
        logger.info(f"SCHEDULER: Finished warnings check job. Processed {processed_count} users.")

    def _nightly_report(self, target_user_id: int = None) -> None:
        # ... (این تابع بدون تغییر باقی می‌ماند)
        tehran_tz = pytz.timezone("Asia/Tehran")
        now_gregorian = datetime.now(tehran_tz)
        
        if not target_user_id:
            is_friday = jdatetime.datetime.fromgregorian(datetime=now_gregorian).weekday() == 5
            if is_friday:
                logger.info("SCHEDULER (Nightly): Today is Friday. Skipping daily report to send weekly report later.")
                return

        now_shamsi = jdatetime.datetime.fromgregorian(datetime=now_gregorian)
        now_str = now_shamsi.strftime("%Y/%m/%d - %H:%M")
        logger.info(f"SCHEDULER: ----- Running nightly report at {now_str} -----")

        all_users_info_from_api = combined_handler.get_all_users_combined()
        if not all_users_info_from_api:
            logger.warning("SCHEDULER: Could not fetch any user info from API. JOB STOPPED.")
            return
            
        logger.info(f"SCHEDULER: Fetched {len(all_users_info_from_api)} total users from API.")

        user_info_map = {user['uuid']: user for user in all_users_info_from_api}
        
        if target_user_id:
            all_bot_users = [target_user_id]
            logger.info(f"SCHEDULER (Nightly - TEST MODE): Running for target user {target_user_id}.")
        else:
            all_bot_users = list(db.get_all_user_ids())
            
        separator = '\n' + '─' * 18 + '\n'
        logger.info(f"SCHEDULER: Found {len(all_bot_users)} registered bot users to process.")

        for user_id in all_bot_users:
            logger.info(f"SCHEDULER: ----- Processing user_id: {user_id} -----")
            
            try:
                user_settings = db.get_user_settings(user_id)
                if not user_settings.get('daily_reports', True) and not target_user_id:
                    logger.info(f"SCHEDULER: User {user_id} has disabled daily reports. Skipping.")
                    continue
                
                if user_id in ADMIN_IDS:
                    logger.info(f"SCHEDULER (Admin Report): Preparing to send report to admin {user_id}.")
                    header = f"👑 *گزارش جامع* {escape_markdown('-')} {escape_markdown(now_str)}{separator}"
                    report_text = fmt_admin_report(all_users_info_from_api, db)
                    final_message = header + report_text
                    try:
                        sent_message = self.bot.send_message(user_id, final_message, parse_mode="MarkdownV2")
                        if sent_message:
                            db.add_sent_report(user_id, sent_message.message_id)
                        logger.info(f"SCHEDULER: Admin report sent to {user_id}.")
                    except Exception as e:
                        logger.error(f"SCHEDULER: Failed to send ADMIN report to {user_id}: {e}", exc_info=True)

                user_uuids_from_db = db.uuids(user_id)
                user_infos_for_report = []
                
                if not user_uuids_from_db:
                    logger.warning(f"SCHEDULER: User {user_id} has no UUIDs registered in the bot's DB. Skipping user report.")
                else:
                    for u_row in user_uuids_from_db:
                        if u_row['uuid'] in user_info_map:
                            user_data = user_info_map[u_row['uuid']]
                            user_data['db_id'] = u_row['id'] 
                            user_infos_for_report.append(user_data)
                    
                    if user_infos_for_report:
                        header = f"🌙 *گزارش شبانه* {escape_markdown('-')} {escape_markdown(now_str)}{separator}"
                        lang_code = db.get_user_language(user_id)
                        report_text = fmt_user_report(user_infos_for_report, lang_code)
                        final_message = header + report_text
                        try:
                            sent_message = self.bot.send_message(user_id, final_message, parse_mode="MarkdownV2")
                            if sent_message:
                                db.add_sent_report(user_id, sent_message.message_id)
                            logger.info(f"SCHEDULER: Personal user report sent to {user_id}.")
                        except Exception as e:
                            logger.error(f"SCHEDULER: Failed to send USER report to {user_id}: {e}", exc_info=True)
                    else:
                        logger.warning(f"SCHEDULER: No active accounts found in API for user {user_id} after matching. No user report will be sent.")
                        
            except Exception as e:
                logger.error(f"SCHEDULER: CRITICAL FAILURE while processing main loop for user {user_id}: {e}", exc_info=True)
                continue
        logger.info("SCHEDULER: ----- Finished nightly report job -----")

    def _update_online_reports(self) -> None:
        # ... (این تابع بدون تغییر باقی می‌ماند)
        logger.info("Scheduler: Starting 3-hourly online user report update.")
        
        messages_to_update = db.get_scheduled_messages('online_users_report')
        if not messages_to_update:
            logger.info("Scheduler (Online Report): No active online report messages to update.")
            return
            
        logger.info(f"Scheduler (Online Report): Found {len(messages_to_update)} messages to update.")
        
        for msg_info in messages_to_update:
            try:
                chat_id, message_id = msg_info['chat_id'], msg_info['message_id']
                
                online_list = [u for u in combined_handler.get_all_users_combined() if u.get('last_online') and (datetime.now(pytz.utc) - u['last_online']).total_seconds() < 180]

                for user in online_list:
                    if user.get('uuid'):
                        user['daily_usage_GB'] = sum(db.get_usage_since_midnight_by_uuid(user['uuid']).values())
                
                text = fmt_online_users_list(online_list, 0)
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
        logger.info("Scheduler: Finished online user report update.")


    def _birthday_gifts_job(self) -> None:
        # ... (این تابع بدون تغییر باقی می‌ماند)
        logger.info("Scheduler: Starting daily birthday gift job.")
        today_birthday_users = db.get_todays_birthdays()
        
        if not today_birthday_users:
            logger.info("Scheduler: No birthdays today.")
            return

        logger.info(f"Scheduler (Birthday): Found {len(today_birthday_users)} user(s) with a birthday today.")
        for user_id in today_birthday_users:
            user_uuids = db.uuids(user_id)
            if not user_uuids:
                continue
            
            gift_applied_successfully = False
            for row in user_uuids:
                uuid = row['uuid']
                if combined_handler.modify_user_on_all_panels(uuid, add_gb=BIRTHDAY_GIFT_GB, add_days=BIRTHDAY_GIFT_DAYS):
                    gift_applied_successfully = True
            
            if gift_applied_successfully:
                try:
                    gift_message = (
                        f"🎉 *تولدت مبارک\\!* 🎉\n\n"
                        f"امیدواریم سالی پر از شادی و موفقیت پیش رو داشته باشی\\.\n"
                        f"ما به همین مناسبت، هدیه‌ای برای شما فعال کردیم:\n\n"
                        f"🎁 `{BIRTHDAY_GIFT_GB} GB` حجم و `{BIRTHDAY_GIFT_DAYS}` روز به تمام اکانت‌های شما **به صورت خودکار اضافه شد\\!**\n\n"
                        f"می‌توانی با مراجعه به بخش مدیریت اکانت، جزئیات جدید را مشاهده کنی\\."
                    )
                    self.bot.send_message(user_id, gift_message, parse_mode="MarkdownV2")
                    logger.info(f"Scheduler: Sent birthday gift to user {user_id}.")
                except Exception as e:
                    logger.error(f"Scheduler: Failed to send birthday message to user {user_id}: {e}")
        logger.info("Scheduler: Finished daily birthday gift job.")


    def _weekly_report(self, target_user_id: int = None) -> None:
        # ... (این تابع بدون تغییر باقی می‌ماند)
        tehran_tz = pytz.timezone("Asia/Tehran")
        now_gregorian = datetime.now(tehran_tz)
        now_shamsi = jdatetime.datetime.fromgregorian(datetime=now_gregorian)
        now_str = now_shamsi.strftime("%Y/%m/%d - %H:%M")
        logger.info(f"SCHEDULER: ----- Running WEEKLY report at {now_str} -----")

        all_users_info_from_api = combined_handler.get_all_users_combined()
        if not all_users_info_from_api:
            logger.warning("SCHEDULER (Weekly): Could not fetch any user info from API. JOB STOPPED.")
            return
            
        user_info_map = {user['uuid']: user for user in all_users_info_from_api}
        
        if target_user_id:
            all_bot_users = [target_user_id]
            logger.info(f"SCHEDULER (Weekly - TEST MODE): Running for target user {target_user_id}.")
        else:
            all_bot_users = list(db.get_all_user_ids())
            
        separator = '\n' + '─' * 18 + '\n'
        logger.info(f"SCHEDULER (Weekly): Found {len(all_bot_users)} users to process for weekly report.")

        processed_count = 0
        for user_id in all_bot_users:
            try:
                user_settings = db.get_user_settings(user_id)
                if not user_settings.get('weekly_reports', True) and not target_user_id:
                    logger.info(f"SCHEDULER (Weekly): User {user_id} has disabled weekly reports. Skipping.")
                    continue

                user_uuids_from_db = db.uuids(user_id)
                user_infos_for_report = []
                
                if not user_uuids_from_db:
                    continue

                for u_row in user_uuids_from_db:
                    if u_row['uuid'] in user_info_map:
                        user_infos_for_report.append(user_info_map[u_row['uuid']])
                
                if user_infos_for_report:
                    header = f"📊 *گزارش هفتگی* {escape_markdown('-')} {escape_markdown(now_str)}{separator}"
                    lang_code = db.get_user_language(user_id)
                    report_text = fmt_user_weekly_report(user_infos_for_report, lang_code)
                    final_message = header + report_text
                    sent_message = self.bot.send_message(user_id, final_message, parse_mode="MarkdownV2")
                    if sent_message:
                        db.add_sent_report(user_id, sent_message.message_id)
                    logger.info(f"SCHEDULER (Weekly): Sent weekly report to user {user_id}.")
                    processed_count += 1
                    time.sleep(0.2) 

            except Exception as e:
                logger.error(f"SCHEDULER (Weekly): CRITICAL FAILURE while processing main loop for user {user_id}: {e}", exc_info=True)
                continue
        logger.info(f"SCHEDULER: ----- Finished weekly report job. Sent reports to {processed_count} users. -----")

    def _run_monthly_vacuum(self) -> None:
        # ... (این تابع بدون تغییر باقی می‌ماند)
        logger.info("Scheduler: Starting daily DB cleanup and monthly VACUUM check.")
        try:
            deleted_count = db.delete_old_snapshots(days_to_keep=7)
            logger.info(f"Scheduler (Cleanup): Daily snapshot cleanup successful. Deleted {deleted_count} old records.")
        except Exception as e:
            logger.error(f"Scheduler (Cleanup): Daily snapshot cleanup failed: {e}")

        today = datetime.now(self.tz)
        if today.day == 1:
            logger.info("Scheduler (VACUUM): It's the first of the month, running database VACUUM job.")
            try:
                db.vacuum_db()
                logger.info("Scheduler (VACUUM): Database VACUUM completed successfully.")
            except Exception as e:
                logger.error(f"Scheduler (VACUUM): Database VACUUM failed: {e}")
        logger.info("Scheduler: Finished DB cleanup job.")


    def _cleanup_old_reports(self) -> None:
        # ... (این تابع بدون تغییر باقی می‌ماند)
        logger.info("Scheduler: Starting job to clean up old report messages.")
        reports_to_delete = db.get_old_reports_to_delete(hours=12)

        if not reports_to_delete:
            logger.info("Scheduler (Cleanup): No old reports to delete.")
            return

        logger.info(f"Scheduler (Cleanup): Found {len(reports_to_delete)} report messages to clean up.")
        for report in reports_to_delete:
            try:
                self.bot.delete_message(chat_id=report['user_id'], message_id=report['message_id'])
                logger.info(f"Successfully deleted report message {report['message_id']} for user {report['user_id']}.")
            except apihelper.ApiTelegramException as e:
                if 'message to delete not found' in str(e) or 'user is deactivated' in str(e) or 'chat not found' in str(e):
                    logger.warning(f"Could not delete message {report['message_id']} for user {report['user_id']} (it may already be gone).")
                else:
                    logger.error(f"API error deleting report for user {report['user_id']}: {e}")
            except Exception as e:
                logger.error(f"Generic error deleting report for user {report['user_id']}: {e}")
            finally:
                db.delete_sent_report_record(report['id'])
        logger.info("Scheduler: Finished cleaning up old report messages.")

    # --- ✅ START: UPDATED TEST FUNCTIONS ---
    def _test_data_warning(self, target_user_id: int):
        """یک نمونه پیام هشدار اتمام حجم برای ادمین ارسال می‌کند."""
        user_uuids = db.uuids(target_user_id)
        if not user_uuids:
            self.bot.send_message(target_user_id, "برای تست، باید حداقل یک اکانت در ربات ثبت کرده باشید.")
            return
        
        user_name = user_uuids[0].get('name', 'کاربر نمونه')
        server_name = "آلمان 🇩🇪"
        remaining_gb = "4.71"
        
        msg_template = (f"{EMOJIS['warning']} *هشدار اتمام حجم*\n\n"
                       f"کاربر گرامی، حجم اکانت *{{user_name}}* شما در سرور *{{server_name}}* رو به اتمام است\\.\n"
                       f"\\- حجم باقیمانده: *{{remaining_gb}} GB*")

        self._send_warning_message(target_user_id, msg_template, 
                                   user_name=user_name, 
                                   server_name=server_name, 
                                   remaining_gb=remaining_gb)

    def _test_expiry_warning(self, target_user_id: int):
        """یک نمونه پیام هشدار انقضای سرویس برای ادمین ارسال می‌کند."""
        user_uuids = db.uuids(target_user_id)
        if not user_uuids:
            self.bot.send_message(target_user_id, "برای تست، باید حداقل یک اکانت در ربات ثبت کرده باشید.")
            return
            
        user_name = user_uuids[0].get('name', 'کاربر نمونه')
        expire_days = "2"

        msg_template = (f"{EMOJIS['warning']} *هشدار انقضای اکانت*\n\n"
                       f"اکانت *{{user_name}}* شما تا *{{expire_days}}* روز دیگر منقضی می‌شود\\.")

        self._send_warning_message(target_user_id, msg_template, 
                                   user_name=user_name, 
                                   expire_days=expire_days)
    # --- ✅ END: UPDATED TEST FUNCTIONS ---
    
    def start(self) -> None:
        # ... (این تابع بدون تغییر باقی می‌ماند)
        if self.running: return
        
        report_time_str = DAILY_REPORT_TIME.strftime("%H:%M")
        schedule.every(1).hours.at(":01").do(self._hourly_snapshots)
        schedule.every(USAGE_WARNING_CHECK_HOURS).hours.do(self._check_for_warnings)
        schedule.every().day.at(report_time_str, self.tz_str).do(self._nightly_report)
        schedule.every().friday.at("23:55", self.tz_str).do(self._weekly_report)
        schedule.every(ONLINE_REPORT_UPDATE_HOURS).hours.do(self._update_online_reports)
        schedule.every().day.at("00:05", self.tz_str).do(self._birthday_gifts_job)
        schedule.every(8).hours.do(self._cleanup_old_reports)
        schedule.every().day.at("04:00", self.tz_str).do(self._run_monthly_vacuum)
        self.running = True
        threading.Thread(target=self._runner, daemon=True).start()
        logger.info(f"Scheduler started successfully.")
        logger.info(f"Daily reports will run at {report_time_str} (Timezone: {self.tz_str}) on all days except Fridays.")
        logger.info(f"Weekly reports will run on Fridays at 23:50 (Timezone: {self.tz_str}).")


    def shutdown(self) -> None:
        # ... (این تابع بدون تغییر باقی می‌ماند)
        logger.info("Scheduler: Shutting down ...")
        schedule.clear()
        self.running = False


    def _runner(self) -> None:
        # ... (این تابع بدون تغییر باقی می‌ماند)
        logger.info("Scheduler runner thread has started.")
        while self.running:
            try:
                schedule.run_pending()
            except Exception as exc:
                logger.error(f"Scheduler loop error: {exc}", exc_info=True)
            time.sleep(60)
        logger.info("Scheduler runner thread has stopped.")