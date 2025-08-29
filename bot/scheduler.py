import logging
import threading
import time
from datetime import datetime, timedelta
import schedule
import pytz
import jdatetime
from telebot import apihelper, TeleBot, types

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

    def _send_warning_message(self, user_id: int, message_template: str, **kwargs):
        """
        A central function to format and send all warning messages,
        and handle cases where the user has blocked the bot.
        """
        try:
            escaped_kwargs = {k: escape_markdown(v) for k, v in kwargs.items()}
            formatted_message = message_template.format(**escaped_kwargs)
            self.bot.send_message(user_id, formatted_message, parse_mode="MarkdownV2")
            return True
        except apihelper.ApiTelegramException as e:
            if "bot was blocked by the user" in e.description:
                logger.warning(f"SCHEDULER: User {user_id} has blocked the bot. Deactivating all their UUIDs.")
                user_uuids = db.uuids(user_id)
                for u in user_uuids:
                    db.deactivate_uuid(u['id'])
            else:
                logger.error(f"Failed to send warning message to user {user_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send warning message to user {user_id}: {e}")
            return False

    def _hourly_snapshots(self) -> None:
        """Takes a snapshot of current usage for all active users."""
        logger.info("SCHEDULER: Starting hourly usage snapshot job.")
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
            logger.info("SCHEDULER: Finished hourly usage snapshot job successfully.")
        except Exception as e:
            logger.error(f"SCHEDULER (Snapshot): A critical error occurred: {e}", exc_info=True)

    def _check_for_warnings(self, target_user_id: int = None) -> None:
        """Periodically checks all users for various conditions and sends notifications."""
        logger.info("SCHEDULER: Starting warnings check job.")
        active_uuids_list = [row for row in db.all_active_uuids() if not target_user_id or row['user_id'] == target_user_id]
        
        try:
            all_users_info_map = {u['uuid']: u for u in combined_handler.get_all_users_combined() if u.get('uuid')}
        except Exception as e:
            logger.error(f"SCHEDULER (Warnings): Failed to fetch combined user data: {e}", exc_info=True)
            return

        for u_row in active_uuids_list:
            try:
                uuid_str = u_row['uuid']
                uuid_id_in_db = u_row['id']
                user_id_in_telegram = u_row['user_id']
                info = all_users_info_map.get(uuid_str)
                if not info: continue

                user_settings = db.get_user_settings(user_id_in_telegram)
                user_name = info.get('name', 'کاربر ناشناس')
                
                # 1. Welcome Message
                if u_row.get('first_connection_time') and not u_row.get('welcome_message_sent', 0):
                    first_conn_time = pytz.utc.localize(u_row['first_connection_time']) if u_row['first_connection_time'].tzinfo is None else u_row['first_connection_time']
                    if datetime.now(pytz.utc) - first_conn_time >= timedelta(hours=WELCOME_MESSAGE_DELAY_HOURS):
                        welcome_text = (f"🎉 *به جمع ما خوش آمدی\\!* 🎉\n\nاز اینکه به ما اعتماد کردی خوشحالیم\\. امیدواریم از کیفیت سرویس لذت ببری\\.\n\n"
                                        f"💬 در صورت داشتن هرگونه سوال یا نیاز به پشتیبانی، ما همیشه در کنار شما هستیم\\.\n\nبا آرزوی بهترین‌ها ✨")
                        if self.bot.send_message(user_id_in_telegram, welcome_text, parse_mode="MarkdownV2"):
                            db.mark_welcome_message_as_sent(uuid_id_in_db)

                # 2. Renewal Reminder
                expire_days = info.get('expire')
                if expire_days == 1 and not u_row.get('renewal_reminder_sent', 0):
                    renewal_text = (f"⏳ *یادآوری تمدید سرویس*\n\n"
                                    f"کاربر گرامی، تنها *۱ روز* از اعتبار اکانت *{escape_markdown(user_name)}* شما باقی مانده است\\.\n\n"
                                    f"برای جلوگیری از قطع شدن سرویس، لطفاً نسبت به تمدید آن اقدام نمایید\\.")
                    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🚀 مشاهده و تمدید سرویس‌ها", callback_data="view_plans"))
                    if self.bot.send_message(user_id_in_telegram, renewal_text, parse_mode="MarkdownV2", reply_markup=kb):
                        db.set_renewal_reminder_sent(uuid_id_in_db)

                # 3. Expiry Warning
                if user_settings.get('expiry_warnings') and expire_days is not None and 1 < expire_days <= WARNING_DAYS_BEFORE_EXPIRY:
                    if not db.has_recent_warning(uuid_id_in_db, 'expiry'):
                        msg_template = (f"{EMOJIS['warning']} *هشدار انقضای اکانت*\n\nاکانت *{{user_name}}* شما تا *{{expire_days}}* روز دیگر منقضی می‌شود\\.")
                        if self._send_warning_message(user_id_in_telegram, msg_template, user_name=user_name, expire_days=str(expire_days)):
                            db.log_warning(uuid_id_in_db, 'expiry')

                # 4. Data Usage Warning
                server_map = {'hiddify': {'name': 'آلمان 🇩🇪', 'setting': 'data_warning_hiddify'}, 'marzban': {'name': 'فرانسه/ترکیه 🇫🇷🇹🇷', 'setting': 'data_warning_fr_tr'}}
                for code, details in server_map.items():
                    panel_info = next((p.get('data', {}) for p in info.get('breakdown', {}).values() if p.get('type') == code), None)
                    if user_settings.get(details['setting']) and panel_info:
                        limit, usage = panel_info.get('usage_limit_GB', 0.0), panel_info.get('current_usage_GB', 0.0)
                        if limit > 0 and (usage / limit * 100) >= WARNING_USAGE_THRESHOLD:
                            warning_type = f'low_data_{code}'
                            if not db.has_recent_warning(uuid_id_in_db, warning_type):
                                msg_template = (f"{EMOJIS['warning']} *هشدار اتمام حجم*\n\nکاربر گرامی، حجم اکانت *{{user_name}}* شما در سرور *{{server_name}}* رو به اتمام است\\.\n"
                                                f"\\- حجم باقیمانده: *{{remaining_gb}} GB*")
                                if self._send_warning_message(user_id_in_telegram, msg_template, user_name=user_name, server_name=details['name'], remaining_gb=f"{max(0, limit - usage):.2f}"):
                                    db.log_warning(uuid_id_in_db, warning_type)
                
                # 5. Unusual Daily Usage Alert (for Admins)
                if DAILY_USAGE_ALERT_THRESHOLD_GB > 0:
                    total_daily_usage = sum(db.get_usage_since_midnight_by_uuid(uuid_str).values())
                    if total_daily_usage >= DAILY_USAGE_ALERT_THRESHOLD_GB and not db.has_recent_warning(uuid_id_in_db, 'unusual_daily_usage', hours=24):
                        alert_message = (f"⚠️ *مصرف غیرعادی روزانه*\n\nکاربر *{escape_markdown(user_name)}* \\(`{escape_markdown(uuid_str)}`\\) "
                                         f"امروز بیش از *{escape_markdown(str(DAILY_USAGE_ALERT_THRESHOLD_GB))} GB* مصرف داشته است\\.\n\n"
                                         f"\\- مجموع مصرف امروز: *{escape_markdown(format_daily_usage(total_daily_usage))}*")
                        for admin_id in ADMIN_IDS:
                            self.bot.send_message(admin_id, alert_message, parse_mode="MarkdownV2")
                        db.log_warning(uuid_id_in_db, 'unusual_daily_usage')

                # 6. Too Many Devices Alert (for Admins)
                device_count = db.count_user_agents(uuid_id_in_db)
                if device_count > 5 and not db.has_recent_warning(uuid_id_in_db, 'too_many_devices', hours=168): # Check once a week
                    alert_message = (f"⚠️ *تعداد دستگاه بالا*\n\n"
                                     f"کاربر *{escape_markdown(user_name)}* \\(`{escape_markdown(uuid_str)}`\\) "
                                     f"بیش از *۵* دستگاه \\({device_count} دستگاه\\) متصل کرده است\\. احتمال به اشتراک گذاری لینک وجود دارد\\.")
                    for admin_id in ADMIN_IDS:
                        self.bot.send_message(admin_id, alert_message, parse_mode="MarkdownV2")
                    db.log_warning(uuid_id_in_db, 'too_many_devices')
                # --- END: NEW CHANGE ---

            except Exception as e:
                logger.error(f"SCHEDULER (Warnings): Error processing UUID_ID {u_row.get('id', 'N/A')}: {e}", exc_info=True)

    def _nightly_report(self, target_user_id: int = None) -> None:
        tehran_tz = pytz.timezone("Asia/Tehran")
        now_gregorian = datetime.now(tehran_tz)
        
        if not target_user_id and jdatetime.datetime.fromgregorian(datetime=now_gregorian).weekday() == 6:
            logger.info("SCHEDULER (Nightly): Friday, skipping daily for weekly report.")
            return

        now_str = jdatetime.datetime.fromgregorian(datetime=now_gregorian).strftime("%Y/%m/%d - %H:%M")
        logger.info(f"SCHEDULER: ----- Running nightly report at {now_str} -----")

        all_users_info_from_api = combined_handler.get_all_users_combined()
        if not all_users_info_from_api:
            logger.warning("SCHEDULER: Could not fetch API user info. JOB STOPPED.")
            return
            
        user_info_map = {user['uuid']: user for user in all_users_info_from_api}
        
        user_ids_to_process = [target_user_id] if target_user_id else list(db.get_all_user_ids())
        separator = '\n' + '─' * 18 + '\n'

        for user_id in user_ids_to_process:
            try:
                user_settings = db.get_user_settings(user_id)
                # Skip non-targeted users if daily reports are off
                if not user_settings.get('daily_reports', True) and not target_user_id:
                    continue
                
                # --- START OF FIX: Separate Admin and User Report Sending ---
                
                # 1. Send Admin-specific comprehensive report if the user is an admin
                if user_id in ADMIN_IDS:
                    admin_header = f"👑 *گزارش جامع* {escape_markdown('-')} {escape_markdown(now_str)}{separator}"
                    admin_report_text = fmt_admin_report(all_users_info_from_api, db)
                    admin_full_message = admin_header + admin_report_text
                    self.bot.send_message(user_id, admin_full_message, parse_mode="MarkdownV2")

                # 2. Send the personal user report for EVERY user (including admins)
                user_uuids_from_db = db.uuids(user_id)
                user_infos_for_report = []
                for u in user_uuids_from_db:
                    if u['uuid'] in user_info_map:
                        user_data = user_info_map[u['uuid']]
                        user_data['db_id'] = u['id']
                        user_infos_for_report.append(user_data)
                
                if user_infos_for_report:
                    user_header = f"🌙 *گزارش شبانه* {escape_markdown('-')} {escape_markdown(now_str)}{separator}"
                    lang_code = db.get_user_language(user_id)
                    user_report_text = fmt_user_report(user_infos_for_report, lang_code)
                    user_full_message = user_header + user_report_text
                    
                    sent_message = self.bot.send_message(user_id, user_full_message, parse_mode="MarkdownV2")
                    if sent_message:
                        db.add_sent_report(user_id, sent_message.message_id)

                # --- END OF FIX ---

            except apihelper.ApiTelegramException as e:
                if "bot was blocked by the user" in e.description:
                    logger.warning(f"SCHEDULER: User {user_id} blocked bot. Deactivating UUIDs.")
                    for u in db.uuids(user_id):
                        db.deactivate_uuid(u['id'])
                else:
                    logger.error(f"SCHEDULER: API error for user {user_id}: {e}")
            except Exception as e:
                logger.error(f"SCHEDULER: CRITICAL FAILURE for user {user_id}: {e}", exc_info=True)
        logger.info("SCHEDULER: ----- Finished nightly report job -----")

    def _update_online_reports(self) -> None:
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
                self.bot.edit_message_text(text, msg_info['chat_id'], msg_info['message_id'], reply_markup=kb, parse_mode="MarkdownV2")
                time.sleep(0.5)
            except apihelper.ApiTelegramException as e:
                if 'message to edit not found' in str(e) or 'message is not modified' in str(e):
                    db.delete_scheduled_message(msg_info['id'])
                else:
                    logger.error(f"Scheduler: Failed to update online report for chat {msg_info['chat_id']}: {e}")

    def _birthday_gifts_job(self) -> None:
        today_birthday_users = db.get_todays_birthdays()
        if not today_birthday_users:
            return
            
        for user_id in today_birthday_users:
            user_uuids = db.uuids(user_id)
            if any(combined_handler.modify_user_on_all_panels(row['uuid'], add_gb=BIRTHDAY_GIFT_GB, add_days=BIRTHDAY_GIFT_DAYS) for row in user_uuids):
                gift_message = (f"🎉 *تولدت مبارک\\!* 🎉\n\n"
                                f"امیدواریم سالی پر از شادی و موفقیت پیش رو داشته باشی\\.\n"
                                f"ما به همین مناسبت، هدیه‌ای برای شما فعال کردیم:\n\n"
                                f"🎁 `{BIRTHDAY_GIFT_GB} GB` حجم و `{BIRTHDAY_GIFT_DAYS}` روز به تمام اکانت‌های شما **به صورت خودکار اضافه شد\\!**\n\n"
                                f"می‌توانی با مراجعه به بخش مدیریت اکانت، جزئیات جدید را مشاهده کنی\\.")
                self._send_warning_message(user_id, gift_message)

    def _weekly_report(self, target_user_id: int = None) -> None:
        now_str = jdatetime.datetime.fromgregorian(datetime=datetime.now(self.tz)).strftime("%Y/%m/%d - %H:%M")
        all_users_info = combined_handler.get_all_users_combined()
        if not all_users_info:
            return
        user_info_map = {u['uuid']: u for u in all_users_info}
        
        user_ids_to_process = [target_user_id] if target_user_id else list(db.get_all_user_ids())
        separator = '\n' + '─' * 18 + '\n'

        for user_id in user_ids_to_process:
            try:
                user_settings = db.get_user_settings(user_id)
                if not user_settings.get('weekly_reports', True) and not target_user_id:
                    continue

                user_uuids = db.uuids(user_id)
                user_infos = [user_info_map[u['uuid']] for u in user_uuids if u['uuid'] in user_info_map]
                
                if user_infos:
                    header = f"📊 *گزارش هفتگی* {escape_markdown('-')} {escape_markdown(now_str)}{separator}"
                    lang_code = db.get_user_language(user_id)
                    report_text = fmt_user_weekly_report(user_infos, lang_code)
                    final_message = header + report_text
                    sent_message = self.bot.send_message(user_id, final_message, parse_mode="MarkdownV2")
                    if sent_message:
                        db.add_sent_report(user_id, sent_message.message_id)
            except apihelper.ApiTelegramException as e:
                if "bot was blocked by the user" in e.description:
                    logger.warning(f"SCHEDULER (Weekly): User {user_id} blocked bot. Deactivating.")
                    for u in db.uuids(user_id):
                        db.deactivate_uuid(u['id'])
                else:
                    logger.error(f"SCHEDULER (Weekly): API error for user {user_id}: {e}")
            except Exception as e:
                logger.error(f"SCHEDULER (Weekly): Failure for user {user_id}: {e}", exc_info=True)

    def _run_monthly_vacuum(self) -> None:
        db.delete_old_snapshots(days_to_keep=7)
        if datetime.now(self.tz).day == 1:
            db.vacuum_db()

    def _cleanup_old_reports(self) -> None:
        reports_to_delete = db.get_old_reports_to_delete(hours=12)
        for report in reports_to_delete:
            try:
                self.bot.delete_message(chat_id=report['user_id'], message_id=report['message_id'])
            except apihelper.ApiTelegramException as e:
                if 'message to delete not found' not in str(e):
                    logger.error(f"API error deleting report for user {report['user_id']}: {e}")
            finally:
                db.delete_sent_report_record(report['id'])
    
    def start(self) -> None:
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
        logger.info("Scheduler started successfully.")

    def shutdown(self) -> None:
        logger.info("Scheduler: Shutting down ...")
        schedule.clear()
        self.running = False

    def _runner(self) -> None:
        while self.running:
            try:
                schedule.run_pending()
            except Exception as exc:
                logger.error(f"Scheduler loop error: {exc}", exc_info=True)
            time.sleep(60)
        logger.info("Scheduler runner thread has stopped.")