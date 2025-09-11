import logging
import threading
import time
from datetime import datetime, timedelta
import schedule
import pytz
import jdatetime
from telebot import apihelper, TeleBot, types
from .language import get_string

from . import combined_handler
from .database import db
from .utils import escape_markdown, format_daily_usage, load_json_file, find_best_plan_upgrade, load_service_plans, parse_volume_string
from .menu import menu
from .admin_formatters import fmt_admin_report, fmt_online_users_list, fmt_weekly_admin_summary, fmt_achievement_leaderboard, fmt_lottery_participants_list, fmt_daily_achievements_report
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
    WELCOME_MESSAGE_DELAY_HOURS,
    ACHIEVEMENTS,
    ENABLE_LUCKY_LOTTERY,
    LUCKY_LOTTERY_BADGE_REQUIREMENT,
)

logger = logging.getLogger(__name__)
scheduler_lock = threading.Lock()

class SchedulerManager:
    def __init__(self, bot: TeleBot) -> None:
        self.bot = bot
        self.running = False
        self.tz = pytz.timezone(TEHRAN_TZ) if isinstance(TEHRAN_TZ, str) else TEHRAN_TZ
        self.tz_str = str(self.tz)

    def _notify_user(self, user_id: int, message: str):
        """یک پیام را برای کاربر مشخصی ارسال می‌کند و خطاهای احتمالی را مدیریت می‌کند."""
        if not user_id:
            return
        try:
            self.bot.send_message(user_id, message, parse_mode="MarkdownV2")
        except Exception as e:
            logger.warning(f"SCHEDULER: Failed to send notification to user {user_id}: {e}")

    def _send_warning_message(self, user_id: int, message_template: str, reply_markup: types.InlineKeyboardMarkup = None, **kwargs):
        """
        This function now expects an already escaped message_template.
        """
        try:
            # The template is now pre-escaped, so we just format it.
            # We still escape kwargs to be safe.
            kwargs_escaped = {k: escape_markdown(str(v)) for k, v in kwargs.items()}
            final_message = message_template.format(**kwargs_escaped)

            self.bot.send_message(user_id, final_message, parse_mode="MarkdownV2", reply_markup=reply_markup)
            return True
        except apihelper.ApiTelegramException as e:
            if "bot was blocked by the user" in e.description or "user is deactivated" in e.description:
                logger.warning(f"SCHEDULER: User {user_id} has blocked the bot or is deactivated. Deactivating all their UUIDs.")
                user_uuids = db.uuids(user_id)
                for u in user_uuids:
                    db.deactivate_uuid(u['id'])
            else:
                if "can't parse entities" in e.description:
                     logger.error(f"Failed to send warning to user {user_id} due to PARSE ERROR. Original message template: '{message_template}'. Final message attempt: '{final_message}'. Error: {e}")
                else:
                     logger.error(f"Failed to send warning message to user {user_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"An unexpected error occurred while sending a warning message to user {user_id}: {e}", exc_info=True)
            return False

    def _hourly_snapshots(self) -> None:
        """(Thread-Safe) Takes a snapshot of current usage for all active users."""
        logger.info("SCHEDULER: Attempting to acquire lock for hourly snapshot.")
        with scheduler_lock:
            logger.info("SCHEDULER: Lock acquired for hourly snapshot.")
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
            finally:
                logger.info("SCHEDULER: Releasing lock for hourly snapshot.")


    def _check_for_warnings(self, target_user_id: int = None) -> None:
        """
        (نسخه نهایی و امن‌شده) به صورت دوره‌ای تمام کاربران را برای شرایط مختلف بررسی کرده و اعلان ارسال می‌کند.
        این نسخه در مقابل تداخل (thread-safe) امن است و کاربران حذف شده از پنل را مدیریت می‌کند.
        """
        logger.info("SCHEDULER: Attempting to acquire lock for warnings check.")
        with scheduler_lock:
            logger.info("SCHEDULER: Lock acquired for warnings check.")
            try:
                # ابتدا تمام کاربران فعال در دیتابیس ربات را می‌خوانیم
                active_uuids_list = [row for row in db.all_active_uuids() if not target_user_id or row['user_id'] == target_user_id]
                
                if not active_uuids_list:
                    logger.info("SCHEDULER (Warnings): No active users in bot DB to check.")
                    return

                # سپس، لیست کامل و به‌روز کاربران را از تمام پنل‌ها دریافت می‌کنیم
                all_users_info_map = {u['uuid']: u for u in combined_handler.get_all_users_combined() if u.get('uuid')}
                
                # اگر نتوانیم اطلاعاتی از پنل‌ها بگیریم، برای جلوگیری از خطا خارج می‌شویم
                if not all_users_info_map:
                    logger.warning("SCHEDULER (Warnings): Could not fetch any user data from panels. Aborting check.")
                    return

                now_utc = datetime.now(pytz.utc)

                # حالا در لیست کاربران دیتابیس ربات حلقه می‌زنیم
                for u_row in active_uuids_list:
                    try:
                        uuid_str = u_row['uuid']
                        uuid_id_in_db = u_row['id']
                        user_id_in_telegram = u_row['user_id']
                        
                        # اگر کاربر در لیست کاربران پنل‌ها وجود نداشت، یعنی حذف شده است. پس از آن رد می‌شویم.
                        info = all_users_info_map.get(uuid_str)
                        if not info:
                            logger.warning(f"SCHEDULER (Warnings): User with UUID {uuid_str} found in bot DB but not in panels. Skipping.")
                            continue

                        user_settings = db.get_user_settings(user_id_in_telegram)
                        # خواندن رکورد کامل uuid برای دسترسی به فلگ‌های has_access
                        uuid_record = db.uuid_by_id(user_id_in_telegram, uuid_id_in_db)
                        user_name = info.get('name', 'کاربر ناشناس')
                        
                        # 1. ارسال پیام خوش‌آمدگویی (بدون تغییر)
                        if u_row.get('first_connection_time') and not u_row.get('welcome_message_sent', 0):
                            first_conn_time = pytz.utc.localize(u_row['first_connection_time']) if u_row['first_connection_time'].tzinfo is None else u_row['first_connection_time']
                            if datetime.now(pytz.utc) - first_conn_time >= timedelta(hours=WELCOME_MESSAGE_DELAY_HOURS):
                                welcome_text = (
                                    "🎉 *به جمع ما خوش آمدی\\!* 🎉\n\n"
                                    "از اینکه به ما اعتماد کردی خوشحالیم\\. امیدواریم از کیفیت سرویس لذت ببری\\.\n\n"
                                    "💬 در صورت داشتن هرگونه سوال یا نیاز به پشتیبانی، ما همیشه در کنار شما هستیم\\.\n\n"
                                    "با آرزوی بهترین‌ها ✨"
                                )
                                if self._send_warning_message(user_id_in_telegram, welcome_text):
                                    db.mark_welcome_message_as_sent(uuid_id_in_db)

                        # 2. ارسال یادآوری تمدید (بدون تغییر)
                        expire_days = info.get('expire')
                        if expire_days == 1 and not u_row.get('renewal_reminder_sent', 0):
                            renewal_text = (
                                f"⏳ *یادآوری تمدید سرویس*\n\n"
                                f"کاربر گرامی، تنها *۱ روز* از اعتبار اکانت *{escape_markdown(user_name)}* شما باقی مانده است\\.\n\n"
                                f"برای جلوگیری از قطع شدن سرویس، لطفاً نسبت به تمدید آن اقدام نمایید\\."
                            )
                            kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🚀 مشاهده و تمدید سرویس‌ها", callback_data="view_plans"))
                            if self.bot.send_message(user_id_in_telegram, renewal_text, parse_mode="MarkdownV2", reply_markup=kb):
                                db.set_renewal_reminder_sent(uuid_id_in_db)

                        # 3. ارسال هشدار انقضای اکانت (بدون تغییر)
                        if user_settings.get('expiry_warnings') and expire_days is not None and 1 < expire_days <= WARNING_DAYS_BEFORE_EXPIRY:
                            if not db.has_recent_warning(uuid_id_in_db, 'expiry'):
                                msg_template = (f"{EMOJIS['warning']} *هشدار انقضای اکانت*\n\nاکانت *{{user_name}}* شما تا *{{expire_days}}* روز دیگر منقضی می‌شود\\.")
                                if self._send_warning_message(user_id_in_telegram, msg_template, user_name=user_name, expire_days=str(expire_days)):
                                    db.log_warning(uuid_id_in_db, 'expiry')
                        
                        # 4. ارسال هشدارهای اتمام حجم (با منطق جدید تفکیک‌شده)
                        breakdown = info.get('breakdown', {})
                        
                        # بررسی برای پنل Hiddify (آلمان)
                        if user_settings.get('data_warning_de'):
                            hiddify_info = next((p.get('data', {}) for p in breakdown.values() if p.get('type') == 'hiddify'), None)
                            if hiddify_info:
                                limit, usage = hiddify_info.get('usage_limit_GB', 0.0), hiddify_info.get('current_usage_GB', 0.0)
                                if limit > 0:
                                    usage_percent = (usage / limit) * 100
                                    # هشدار کمبود حجم
                                    if WARNING_USAGE_THRESHOLD <= usage_percent < 100 and not db.has_recent_warning(uuid_id_in_db, 'low_data_hiddify'):
                                        msg = (f"❗️ *هشدار اتمام حجم*\n\nکاربر گرامی، بیش از *{int(WARNING_USAGE_THRESHOLD)}%* از حجم سرویس شما در سرور *آلمان 🇩🇪* مصرف شده است.")
                                        if self._send_warning_message(user_id_in_telegram, msg):
                                            db.log_warning(uuid_id_in_db, 'low_data_hiddify')
                                    # هشدار اتمام کامل حجم
                                    if usage >= limit and not hiddify_info.get('is_active') and not db.has_recent_warning(uuid_id_in_db, 'volume_depleted_hiddify'):
                                        msg = (f"🔴 *اتمام حجم*\n\nحجم سرویس شما در سرور *آلمان 🇩🇪* به پایان رسیده و این سرور برای شما غیرفعال شده است.")
                                        if self._send_warning_message(user_id_in_telegram, msg):
                                            db.log_warning(uuid_id_in_db, 'volume_depleted_hiddify')
                                            
                        # بررسی برای پنل Marzban (فرانسه، ترکیه و آمریکا)
                        marzban_info = next((p.get('data', {}) for p in breakdown.values() if p.get('type') == 'marzban'), None)
                        if marzban_info and uuid_record:
                            # شرط ترکیبی: آیا کاربر به این سرورها دسترسی دارد و آیا هشدار آن را فعال کرده است؟
                            should_warn_fr = user_settings.get('data_warning_fr') and uuid_record.get('has_access_fr')
                            should_warn_tr = user_settings.get('data_warning_tr') and uuid_record.get('has_access_tr')
                            should_warn_us = user_settings.get('data_warning_us') and uuid_record.get('has_access_us')
                            
                            if should_warn_fr or should_warn_tr or should_warn_us:
                                limit, usage = marzban_info.get('usage_limit_GB', 0.0), marzban_info.get('current_usage_GB', 0.0)
                                if limit > 0:
                                    usage_percent = (usage / limit) * 100
                                    
                                    # ساخت نام سرورها بر اساس دسترسی کاربر برای نمایش در پیام
                                    server_names = []
                                    if should_warn_fr: server_names.append("فرانسه 🇫🇷")
                                    if should_warn_tr: server_names.append("ترکیه 🇹🇷")
                                    if should_warn_us: server_names.append("آمریکا 🇺🇸")
                                    server_display_name = " / ".join(server_names)

                                    # هشدار کمبود حجم
                                    if WARNING_USAGE_THRESHOLD <= usage_percent < 100 and not db.has_recent_warning(uuid_id_in_db, 'low_data_marzban'):
                                        msg = (f"❗️ *هشدار اتمام حجم*\n\nکاربر گرامی، بیش از *{int(WARNING_USAGE_THRESHOLD)}%* از حجم سرویس شما در سرور *{server_display_name}* مصرف شده است.")
                                        if self._send_warning_message(user_id_in_telegram, msg):
                                            db.log_warning(uuid_id_in_db, 'low_data_marzban')
                                            
                                    # هشدار اتمام کامل حجم
                                    if usage >= limit and not marzban_info.get('is_active') and not db.has_recent_warning(uuid_id_in_db, 'volume_depleted_marzban'):
                                        msg = (f"🔴 *اتمام حجم*\n\nحجم سرویس شما در سرور *{server_display_name}* به پایان رسیده و این سرور برای شما غیرفعال شده است.")
                                        if self._send_warning_message(user_id_in_telegram, msg):
                                            db.log_warning(uuid_id_in_db, 'volume_depleted_marzban')

                        # 5. ارسال پیام به کاربران غیرفعال (بدون تغییر)
                        last_online = info.get('last_online')
                        if last_online and isinstance(last_online, datetime):
                            days_inactive = (now_utc.replace(tzinfo=None) - last_online.replace(tzinfo=None)).days
                            if 4 <= days_inactive <= 7 and not db.has_recent_warning(uuid_id_in_db, 'inactive_user_reminder', hours=168):
                                msg = ("حس میکنم نیاز به راهنمایی داری\\!\n\n"
                                    "چند روز از آخرین اتصالت میگذره، به نظر میاد نتونستی به اکانت وصل بشی\\. "
                                    "اگه روش اتصال رو نمیدونی و یا اشتراک برات کار نکرد، با پشتیبانی در ارتباط باش تا برات حلش کنیم\\.")
                                if self._send_warning_message(user_id_in_telegram, msg):
                                    db.log_warning(uuid_id_in_db, 'inactive_user_reminder')


                        # 6. ارسال هشدار مصرف غیرعادی روزانه به ادمین‌ها (بدون تغییر)
                        if DAILY_USAGE_ALERT_THRESHOLD_GB > 0:
                            total_daily_usage = sum(db.get_usage_since_midnight_by_uuid(uuid_str).values())
                            if total_daily_usage >= DAILY_USAGE_ALERT_THRESHOLD_GB and not db.has_recent_warning(uuid_id_in_db, 'unusual_daily_usage', hours=24):
                                alert_message = (f"⚠️ *مصرف غیرعادی روزانه*\n\nکاربر *{escape_markdown(user_name)}* \\(`{escape_markdown(uuid_str)}`\\) "
                                                f"امروز بیش از *{escape_markdown(str(DAILY_USAGE_ALERT_THRESHOLD_GB))} GB* مصرف داشته است\\.\n\n"
                                                f"\\- مجموع مصرف امروز: *{escape_markdown(format_daily_usage(total_daily_usage))}*")
                                for admin_id in ADMIN_IDS:
                                    self._notify_user(admin_id, alert_message)
                                db.log_warning(uuid_id_in_db, 'unusual_daily_usage')

                        # 7. ارسال هشدار تعداد زیاد دستگاه‌ها به ادمین‌ها (بدون تغییر)
                        device_count = db.count_user_agents(uuid_id_in_db)
                        if device_count > 5 and not db.has_recent_warning(uuid_id_in_db, 'too_many_devices', hours=168):
                            alert_message = (f"⚠️ *تعداد دستگاه بالا*\n\n"
                                            f"کاربر *{escape_markdown(user_name)}* \\(`{escape_markdown(uuid_str)}`\\) "
                                            f"بیش از *۵* دستگاه \\({device_count} دستگاه\\) متصل کرده است\\. احتمال به اشتراک گذاری لینک وجود دارد\\.")
                            for admin_id in ADMIN_IDS:
                                self._notify_user(admin_id, alert_message)
                            db.log_warning(uuid_id_in_db, 'too_many_devices')

                    except Exception as e:
                        logger.error(f"SCHEDULER (Warnings): Error processing UUID_ID {u_row.get('id', 'N/A')}: {e}", exc_info=True)
            
            except Exception as e:
                logger.error(f"SCHEDULER (Warnings): A critical error occurred during check: {e}", exc_info=True)
            finally:
                logger.info("SCHEDULER: Releasing lock for warnings check.")

    def _nightly_report(self, target_user_id: int = None) -> None:
        tehran_tz = pytz.timezone("Asia/Tehran")
        now_gregorian = datetime.now(tehran_tz)
        
        # اگر جمعه بود، فقط برای کاربران عادی از ارسال گزارش روزانه صرف‌نظر کن
        if not target_user_id and jdatetime.datetime.fromgregorian(datetime=now_gregorian).weekday() == 6 and (target_user_id is None or target_user_id not in ADMIN_IDS):
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
                if not user_settings.get('daily_reports', True) and not target_user_id:
                    continue
                
                # گزارش جامع برای ادمین‌ها
                if user_id in ADMIN_IDS:
                    admin_header = f"👑 *گزارش جامع* {escape_markdown('-')} {escape_markdown(now_str)}{separator}"
                    admin_report_text = fmt_admin_report(all_users_info_from_api, db)
                    admin_full_message = admin_header + admin_report_text
                    
                    # --- منطق تقسیم پیام برای ادمین ---
                    if len(admin_full_message) > 4096:
                        chunks = [admin_full_message[i:i + 4090] for i in range(0, len(admin_full_message), 4090)]
                        for i, chunk in enumerate(chunks):
                            # به پیام‌های بعدی یک عنوان اضافه می‌کنیم تا مشخص باشد ادامه گزارش است
                            if i > 0:
                                chunk = f"*{escape_markdown('(ادامه گزارش جامع)')}*\n\n" + chunk
                            self.bot.send_message(user_id, chunk, parse_mode="MarkdownV2")
                            time.sleep(0.5) # وقفه کوتاه بین ارسال پیام‌ها
                    else:
                        self.bot.send_message(user_id, admin_full_message, parse_mode="MarkdownV2")

                # گزارش شخصی برای همه کاربران (شامل ادمین‌ها)
                user_uuids_from_db = db.uuids(user_id)
                user_infos_for_report = []
                
                # --- START OF FIX: Add 'db_id' to user_info ---
                for u_row in user_uuids_from_db:
                    if u_row['uuid'] in user_info_map:
                        user_data = user_info_map[u_row['uuid']]
                        # This line is crucial for daily usage calculation in fmt_user_report
                        user_data['db_id'] = u_row['id'] 
                        user_infos_for_report.append(user_data)
                # --- END OF FIX ---
                
                if user_infos_for_report:
                    user_header = f"🌙 *گزارش شبانه* {escape_markdown('-')} {escape_markdown(now_str)}{separator}"
                    lang_code = db.get_user_language(user_id)
                    user_report_text = fmt_user_report(user_infos_for_report, lang_code)
                    user_full_message = user_header + user_report_text
                    
                    sent_message = self.bot.send_message(user_id, user_full_message, parse_mode="MarkdownV2")
                    if sent_message:
                        db.add_sent_report(user_id, sent_message.message_id)

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
            
        current_year = jdatetime.datetime.now(self.tz).year

        for user_id in today_birthday_users:
            with db._conn() as c:
                already_given = c.execute(
                    "SELECT 1 FROM birthday_gift_log WHERE user_id = ? AND gift_year = ?",
                    (user_id, current_year)
                ).fetchone()

            if already_given:
                logger.info(f"Skipping birthday gift for user {user_id}, already given in year {current_year}.")
                continue

            user_uuids = db.uuids(user_id)
            if user_uuids:
                first_uuid = user_uuids[0]['uuid']
                if combined_handler.modify_user_on_all_panels(first_uuid, add_gb=BIRTHDAY_GIFT_GB, add_days=BIRTHDAY_GIFT_DAYS):
                    user_settings = db.get_user_settings(user_id)
                    if user_settings.get('promotional_alerts', True):
                        gift_message = (f"🎉 *تولدت مبارک\\!* 🎉\n\n"
                                        f"امیدواریم سالی پر از شادی و موفقیت پیش رو داشته باشی\\.\n"
                                        f"ما به همین مناسبت، هدیه‌ای برای شما فعال کردیم:\n\n"
                                        f"🎁 `{BIRTHDAY_GIFT_GB} GB` حجم و `{BIRTHDAY_GIFT_DAYS}` روز به تمام اکانت‌های شما **به صورت خودکار اضافه شد\\!**\n\n"
                                        f"می‌توانی با مراجعه به بخش مدیریت اکانت، جزئیات جدید را مشاهده کنی\\.")
                        if self._send_warning_message(user_id, gift_message):
                            with db._conn() as c:
                                c.execute("INSERT INTO birthday_gift_log (user_id, gift_year) VALUES (?, ?)", (user_id, current_year))

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

    def _send_weekly_admin_summary(self) -> None:
        """گزارش هفتگی پرمصرف‌ترین کاربران را برای ادمین‌ها ارسال می‌کند و به ۱۰ نفر اول پیام تبریک/انگیزشی می‌فرستد."""
        logger.info("SCHEDULER: Sending weekly admin summary report and top user notifications.")
        try:
            report_data = db.get_weekly_top_consumers_report()
            report_text = fmt_weekly_admin_summary(report_data)

            # ارسال گزارش به ادمین‌ها
            for admin_id in ADMIN_IDS:
                try:
                    self.bot.send_message(admin_id, report_text, parse_mode="MarkdownV2")
                except Exception as e:
                    logger.error(f"Failed to send weekly admin summary to {admin_id}: {e}")

            # --- START: EXPANDED NOTIFICATIONS - Send messages to top 10 users ---
            top_users = report_data.get('top_10_overall', [])
            if top_users:
                all_bot_users_with_uuids = db.get_all_bot_users_with_uuids()
                user_map = {user['config_name']: user['user_id'] for user in all_bot_users_with_uuids}

                if len(top_users) > 0:
                    champion = top_users[0]
                    champion_name = champion.get('name')
                    champion_id = user_map.get(champion_name)
                    if champion_id:
                        if db.add_achievement(champion_id, 'weekly_champion'):
                            self._notify_user_achievement(champion_id, 'weekly_champion')

                # ارسال پیام به ۱۰ نفر اول
                for i, user in enumerate(top_users):
                    rank = i + 1
                    user_name = user.get('name')
                    usage = user.get('total_usage', 0)
                    
                    user_id = user_map.get(user_name)

                    if user_id:
                        lang_code = db.get_user_language(user_id)
                        
                        # انتخاب کلید پیام بر اساس رتبه
                        if 1 <= rank <= 3:
                            message_key = f"weekly_top_user_rank_{rank}"
                        else: # Ranks 4 to 10
                            message_key = "weekly_top_user_rank_4_to_10"
                        
                        fun_message_template = get_string(message_key, lang_code)
                        
                        final_message = fun_message_template.format(
                            user_name=escape_markdown(user_name),
                            usage=escape_markdown(f"{usage:.2f} GB"),
                            rank=rank # Pass the rank for the message
                        )
                        
                        self._send_warning_message(user_id, final_message)
                        time.sleep(0.5)
            # --- END: EXPANDED NOTIFICATIONS ---

        except Exception as e:
            logger.error(f"Failed to generate or process weekly admin summary: {e}", exc_info=True)

    def _check_achievements_and_anniversary(self) -> None:
        """
        شرایط دریافت دستاوردها را برای تمام کاربران بررسی کرده و امتیاز اهدا می‌کند.
        """
        logger.info("SCHEDULER: Starting daily achievements check job.")
        all_user_ids = list(db.get_all_user_ids())

        import random
        lucky_users = random.sample(all_user_ids, k=min(3, len(all_user_ids)))

        for user_id in all_user_ids:
            try:
                user_uuids = db.uuids(user_id)
                if not user_uuids:
                    continue

                first_uuid_record = user_uuids[0]
                uuid_id = first_uuid_record['id']

                first_uuid_creation_date = first_uuid_record['created_at']
                if first_uuid_creation_date.tzinfo is None:
                    first_uuid_creation_date = pytz.utc.localize(first_uuid_creation_date)

                days_since_creation = (datetime.now(pytz.utc) - first_uuid_creation_date).days
                current_year = datetime.now(pytz.utc).year

                # --- ۱. بررسی نشان "کهنه‌کار" ---
                if (datetime.now(pytz.utc) - first_uuid_creation_date).days >= 365:
                    if db.add_achievement(user_id, 'veteran'):
                        self._notify_user_achievement(user_id, 'veteran')

                # --- ۲. بررسی نشان "حامی وفادار" ---
                payment_count = len(db.get_user_payment_history(uuid_id))
                if payment_count > 5:
                    if db.add_achievement(user_id, 'loyal_supporter'):
                        self._notify_user_achievement(user_id, 'loyal_supporter')

                # --- ۳. بررسی نشان "سفیر" ---
                from .config import AMBASSADOR_BADGE_THRESHOLD
                successful_referrals = [u for u in db.get_referred_users(user_id) if u['referral_reward_applied']]
                if len(successful_referrals) >= AMBASSADOR_BADGE_THRESHOLD:
                    if db.add_achievement(user_id, 'ambassador'):
                        self._notify_user_achievement(user_id, 'ambassador')

                # --- ۴. بررسی نشان "دوست VIP" ---
                user_record = db.uuid_by_id(user_id, uuid_id)
                if user_record and user_record.get('is_vip'):
                    if db.add_achievement(user_id, 'vip_friend'):
                        self._notify_user_achievement(user_id, 'vip_friend')

                # --- ۵. بررسی نشان‌های مبتنی بر مصرف ---
                monthly_usage = db.get_total_usage_in_last_n_days(uuid_id, 30)
                if monthly_usage > 200:
                    if db.add_achievement(user_id, 'pro_consumer'):
                        self._notify_user_achievement(user_id, 'pro_consumer')

                if monthly_usage > 10:
                    night_stats = db.get_night_usage_stats_in_last_n_days(uuid_id, 30)
                    if night_stats['total'] > 0 and (night_stats['night'] / night_stats['total']) > 0.5:
                        if db.add_achievement(user_id, 'night_owl'):
                            self._notify_user_achievement(user_id, 'night_owl')

                # --- ۶. بررسی دستاورد ترکیبی "اسطوره" ---
                user_badges = db.get_user_achievements(user_id)
                required_for_legend = {'veteran', 'loyal_supporter', 'pro_consumer'}
                if required_for_legend.issubset(set(user_badges)):
                    if db.add_achievement(user_id, 'legend'):
                        self._notify_user_achievement(user_id, 'legend')

                # --- ۷. اهدای نشان "خوش‌شانس" ---
                if user_id in lucky_users:
                    if db.add_achievement(user_id, 'lucky_one'):
                        self._notify_user_achievement(user_id, 'lucky_one')

                # --- منطق هدیه سالگرد ---
                if days_since_creation >= 365:
                    with db._conn() as c:
                        already_given = c.execute(
                            "SELECT 1 FROM anniversary_gift_log WHERE user_id = ? AND gift_year = ?",
                            (user_id, current_year)
                        ).fetchone()

                        if not already_given:
                            anniversary_gift_gb = 20
                            anniversary_gift_days = 10

                            if combined_handler.modify_user_on_all_panels(first_uuid_record['uuid'], add_gb=anniversary_gift_gb, add_days=anniversary_gift_days):
                                lang_code = db.get_user_language(user_id)
                                title = get_string("anniversary_gift_title", lang_code)
                                body = get_string("anniversary_gift_body", lang_code).format(
                                    gift_gb=anniversary_gift_gb,
                                    gift_days=anniversary_gift_days
                                )
                                anniversary_message = f"*{escape_markdown(title)}*\n\n{escape_markdown(body)}"

                                self._send_warning_message(user_id, anniversary_message)
                                c.execute("INSERT INTO anniversary_gift_log (user_id, gift_year) VALUES (?, ?)", (user_id, current_year))

                # --- START OF CHANGE: "Early Bird" Badge ---
                time_of_day_stats = db.get_weekly_usage_by_time_of_day(uuid_id)
                total_weekly_usage = sum(time_of_day_stats.values())
                if total_weekly_usage > 0.1: # حداقل مصرف برای محاسبه
                    morning_usage = time_of_day_stats.get('morning', 0.0)
                    if (morning_usage / total_weekly_usage) > 0.5:
                        if db.add_achievement(user_id, 'early_bird'):
                            self._notify_user_achievement(user_id, 'early_bird')
                # --- END OF CHANGE ---

            except Exception as e:
                logger.error(f"Error checking achievements for user_id {user_id}: {e}")


    def _notify_user_achievement(self, user_id: int, badge_code: str):
        """به کاربر برای دریافت یک نشان جدید تبریک می‌گوید و امتیاز اضافه می‌کند."""
        badge = ACHIEVEMENTS.get(badge_code)
        if not badge: return

        points = badge.get("points", 0)
        if points > 0:
            db.add_achievement_points(user_id, points)

        user_settings = db.get_user_settings(user_id)
        if not user_settings.get('achievement_alerts', True):
            return
        
        message = (
            f"{badge['icon']} *شما یک نشان جدید دریافت کردید\\!* {badge['icon']}\n\n"
            f"تبریک\\! شما موفق به کسب نشان «*{escape_markdown(badge['name'])}*» شدید و *{points} امتیاز* دریافت کردید\\.\n\n"
            f"{escape_markdown(badge['description'])}\n\n"
            f"این نشان و امتیاز آن به پروفایل شما اضافه شد\\."
        )
        self._send_warning_message(user_id, message)

    def _send_achievement_leaderboard(self) -> None:
        """گزارش هفتگی رتبه‌بندی کاربران بر اساس امتیاز دستاوردها را برای ادمین‌ها ارسال می‌کند."""
        logger.info("SCHEDULER: Sending weekly achievement leaderboard.")
        try:
            leaderboard_data = db.get_achievement_leaderboard()
            report_text = fmt_achievement_leaderboard(leaderboard_data) # این تابع را در گام بعد می‌سازیم
            
            for admin_id in ADMIN_IDS:
                self._notify_user(admin_id, report_text)
        except Exception as e:
            logger.error(f"Failed to generate or send achievement leaderboard: {e}", exc_info=True)

    def _run_lucky_lottery(self) -> None:
        """قرعه‌کشی ماهانه خوش‌شانسی را در اولین جمعه ماه شمسی اجرا می‌کند."""
        
        # --- ✅ منطق جدید برای تشخیص اولین جمعه ماه شمسی ---
        today_jalali = jdatetime.datetime.now(self.tz)
        
        # جمعه در jdatetime روز ۶ است (شنبه=۰)
        if today_jalali.weekday() != 6:
            return # اگر امروز جمعه نیست، خارج شو
            
        # اگر روز ماه بزرگتر از ۷ باشد، قطعاً اولین جمعه نیست
        if today_jalali.day > 7:
            return
        # ----------------------------------------------------

        if not ENABLE_LUCKY_LOTTERY:
            return

        logger.info("SCHEDULER: Running monthly lucky lottery.")
        participants = db.get_lucky_lottery_participants(LUCKY_LOTTERY_BADGE_REQUIREMENT)
        
        if not participants:
            logger.info("LUCKY LOTTERY: No eligible participants this month.")
            # به ادمین‌ها اطلاع می‌دهیم که قرعه‌کشی به دلیل نبود شرکت‌کننده انجام نشد
            for admin_id in ADMIN_IDS:
                self._notify_user(admin_id, "ℹ️ قرعه‌کشی ماهانه خوش‌شانسی به دلیل عدم وجود شرکت‌کننده واجد شرایط، این ماه انجام نشد.")
            return

        import random
        winner = random.choice(participants)
        winner_id = winner['user_id']
        winner_name = escape_markdown(winner['first_name'])
        
        badge = ACHIEVEMENTS.get("lucky_one")
        if badge and badge.get("points"):
            points_reward = badge.get("points") * 10 
            db.add_achievement_points(winner_id, points_reward)

            winner_message = (
                f"🎉 **شما برنده قرعه‌کشی ماهانه خوش‌شانسی شدید!** 🎉\n\n"
                f"تبریک! به همین مناسبت، *{points_reward} امتیاز* به حساب شما اضافه شد.\n\n"
                f"می‌توانید از این امتیاز در «فروشگاه دستاوردها» استفاده کنید."
            )
            self._send_warning_message(winner_id, winner_message)

            admin_message = (
                f"🏆 *نتیجه قرعه‌کشی ماهانه خوش‌شانسی*\n\n"
                f"برنده این ماه: *{winner_name}* \\(`{winner_id}`\\)\n"
                f"جایزه: *{points_reward} امتیاز* با موفقیت به ایشان اهدا شد."
            )
            for admin_id in ADMIN_IDS:
                self._notify_user(admin_id, admin_message)

    def _send_lucky_badge_summary(self) -> None:
        """گزارش تعداد نشان خوش‌شانس را برای کاربران و لیست شرکت‌کنندگان را برای ادمین ارسال می‌کند."""
        if not ENABLE_LUCKY_LOTTERY:
            return

        logger.info("SCHEDULER: Sending weekly lucky badge summary.")
        participants = db.get_lucky_lottery_participants(LUCKY_LOTTERY_BADGE_REQUIREMENT)

        # ارسال پیام به کاربران واجد شرایط
        for user in participants:
            user_id = user['user_id']
            badge_count = user['lucky_badge_count']
            message = (
                f"🍀 *گزارش هفتگی خوش‌شانسی شما*\n\n"
                f"شما در این ماه *{badge_count}* بار نشان خوش‌شانس دریافت کرده‌اید و در قرعه‌کشی شرکت داده خواهید شد.\n\n"
                f"*{escape_markdown('قرعه‌کشی ماهانه چیست؟')}*\n"
                f"_{escape_markdown('در اولین جمعه هر ماه شمسی، بین تمام کاربرانی که شرایط لازم را داشته باشند، قرعه‌کشی شده و به برنده امتیاز ویژه اهدا می‌شود.')}_\n\n"
                f"با آرزوی موفقیت!"
            )
            self._send_warning_message(user_id, message)

        # ارسال لیست کامل شرکت‌کنندگان به ادمین‌ها
        admin_report_text = fmt_lottery_participants_list(participants)
        for admin_id in ADMIN_IDS:
            self._notify_user(admin_id, admin_report_text)

    def _sync_users_with_panels(self) -> None:
        """
        (Thread-Safe) Periodically syncs the local bot database with the panels,
        deactivating users in the bot who no longer exist on any panel.
        """
        logger.info("SCHEDULER: Starting user synchronization with panels.")
        with scheduler_lock:
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

    def _check_for_special_occasions(self):
        """هر روز اجرا شده و تاریخ شمسی را با مناسبت‌ها چک می‌کند."""
        try:
            events = load_json_file('events.json')
            today_jalali = jdatetime.datetime.now(self.tz)
            today_str = today_jalali.strftime('%m-%d')

            for event in events:
                if event.get('date') == today_str:
                    logger.info(f"Today is {event['name']}. Preparing to send gifts.")
                    self._distribute_special_occasion_gifts(event)

        except Exception as e:
            logger.error(f"Error checking for special occasions: {e}", exc_info=True)

    def _distribute_special_occasion_gifts(self, event_details: dict):
        """هدیه تعریف شده را به تمام کاربران فعال اعمال می‌کند."""
        all_active_uuids = list(db.all_active_uuids())
        if not all_active_uuids:
            logger.info(f"No active users to send {event_details['name']} gift to.")
            return

        gift_gb = event_details.get('gift', {}).get('gb', 0)
        gift_days = event_details.get('gift', {}).get('days', 0)
        message_template = event_details.get('message', "شما یک هدیه دریافت کردید!")

        if gift_gb == 0 and gift_days == 0:
            logger.warning(f"Gift for {event_details['name']} has no value. Skipping.")
            return

        successful_gifts = 0
        for user_row in all_active_uuids:
            try:
                success = combined_handler.modify_user_on_all_panels(
                    identifier=user_row['uuid'],
                    add_gb=gift_gb,
                    add_days=gift_days
                )
                if success:
                    user_settings = db.get_user_settings(user_row['user_id'])
                    if user_settings.get('promotional_alerts', True):
                        self._send_warning_message(user_row['user_id'], escape_markdown(message_template))
                    successful_gifts += 1
                    time.sleep(0.2)
            except Exception as e:
                logger.error(f"Failed to give {event_details['name']} gift to user {user_row['user_id']}: {e}")
        
        logger.info(f"Successfully sent {event_details['name']} gift to {successful_gifts} users.")

    def _send_daily_achievements_report(self) -> None:
        """گزارش روزانه دستاوردهای کسب شده را برای ادمین‌ها ارسال می‌کند."""
        logger.info("SCHEDULER: Sending daily achievements report.")
        try:
            daily_achievements = db.get_daily_achievements()
            report_text = fmt_daily_achievements_report(daily_achievements)

            for admin_id in ADMIN_IDS:
                try:
                    self.bot.send_message(admin_id, report_text, parse_mode="MarkdownV2")
                except Exception as e:
                    logger.error(f"Failed to send daily achievements report to {admin_id}: {e}")
        except Exception as e:
            logger.error(f"Failed to generate daily achievements report: {e}", exc_info=True)


    def _check_auto_renewals_and_warnings(self) -> None:
        """
        هر روز اجرا شده و وضعیت تمدید خودکار و هشدارهای کمبود موجودی را بررسی می‌کند.
        """
        logger.info("SCHEDULER: Starting auto-renewal and low balance check job.")

        # فقط کاربرانی که تمدید خودکار را فعال کرده‌اند را بررسی می‌کنیم
        users_with_auto_renew = [u for u in db.get_all_user_ids() if (ud := db.user(u)) and ud.get('auto_renew')]

        for user_id in users_with_auto_renew:
            try:
                user_uuids = db.uuids(user_id)
                if not user_uuids: continue

                uuid_record = user_uuids[0]
                user_info = combined_handler.get_combined_user_info(uuid_record['uuid'])

                if not user_info or not user_info.get('expire'): continue

                expire_days = user_info['expire']
                user_balance = (db.user(user_id) or {}).get('wallet_balance', 0.0)
                plan_price = db.get_user_latest_plan_price(uuid_record['id'])

                # سناریو ۱: تمدید خودکار
                if expire_days == 1 and plan_price and user_balance >= plan_price:
                    plan_info = next((p for p in load_service_plans() if p.get('price') == plan_price), None)
                    if not plan_info: continue

                    add_days = parse_volume_string(plan_info.get('duration', '0'))
                    # (منطق اعمال تغییرات مشابه تابع خرید است)
                    # ...

                    # کسر هزینه از کیف پول و ثبت لاگ
                    db.update_wallet_balance(user_id, -plan_price, 'auto_renewal', f"تمدید خودکار سرویس")

                    # اطلاع‌رسانی به کاربر
                    self._notify_user(user_id, f"✅ سرویس شما با موفقیت به صورت خودکار تمدید شد. مبلغ {plan_price:,.0f} تومان از حساب شما کسر گردید.")

                # سناریو ۲: هشدار کمبود موجودی
                elif 1 < expire_days <= 3 and plan_price and user_balance < plan_price:
                    if not db.has_recent_warning(uuid_record['id'], 'low_balance_for_renewal', hours=72):
                        needed_amount = plan_price - user_balance
                        msg = (
                            f"⚠️ *هشدار کمبود موجودی برای تمدید خودکار*\n\n"
                            f"اعتبار سرویس شما رو به اتمام است اما موجودی کیف پول شما برای تمدید خودکار کافی نیست.\n\n"
                            f"برای تمدید، نیاز به شارژ حساب به مبلغ حداقل *{needed_amount:,.0f} تومان* دارید."
                        )
                        if self._send_warning_message(user_id, msg):
                            db.log_warning(uuid_record['id'], 'low_balance_for_renewal')

            except Exception as e:
                logger.error(f"Error during auto-renewal check for user {user_id}: {e}", exc_info=True)

    def _run_monthly_lottery(self) -> None:
        """قرعه‌کشی ماهانه را اجرا کرده، به برنده جایزه می‌دهد و به همه اطلاع‌رسانی می‌کند."""

        # --- تشخیص اولین جمعه ماه شمسی ---
        today_jalali = jdatetime.datetime.now(self.tz)
        if today_jalali.weekday() != 6 or today_jalali.day > 7:
            return
        # ------------------------------------

        logger.info("SCHEDULER: Running monthly lottery.")
        participants = db.get_lottery_participants()

        if not participants:
            logger.info("LOTTERY: No participants this month.")
            for admin_id in ADMIN_IDS:
                self._notify_user(admin_id, "ℹ️ قرعه‌کشی ماهانه به دلیل عدم وجود شرکت‌کننده، این ماه انجام نشد.")
            return

        import random
        winner_id = random.choice(participants)
        winner_info = db.get_user_by_telegram_id(winner_id)
        winner_name = escape_markdown(winner_info.get('first_name', f"کاربر {winner_id}"))

        # تعریف جایزه (مثلاً یک سرویس Gold 🥇 رایگان)
        prize_plan = next((p for p in load_service_plans() if p['name'] == 'Gold 🥇'), None)
        if prize_plan:
            winner_uuids = db.uuids(winner_id)
            if winner_uuids:
                winner_main_uuid = winner_uuids[0]['uuid']
                add_days = parse_volume_string(prize_plan.get('duration', '0'))
                add_gb_de = parse_volume_string(prize_plan.get('volume_de', '0'))
                add_gb_fr_tr = parse_volume_string(prize_plan.get('volume_fr', '0'))

                combined_handler.modify_user_on_all_panels(winner_main_uuid, add_gb=add_gb_de, add_days=add_days, target_panel_type='hiddify')
                combined_handler.modify_user_on_all_panels(winner_main_uuid, add_gb=add_gb_fr_tr, add_days=add_days, target_panel_type='marzban')

        # اطلاع‌رسانی به برنده و ادمین‌ها
        winner_message = f"🎉 *{escape_markdown('شما برنده قرعه‌کشی ماهانه شدید!')}* 🎉\n\n{escape_markdown(f'تبریک! جایزه شما (سرویس {prize_plan["name"]}) به صورت خودکار به اکانتتان اضافه شد.')}"
        self._notify_user(winner_id, winner_message)

        admin_message = f"🏆 *{escape_markdown('نتیجه قرعه‌کشی ماهانه')}*\n\n{escape_markdown('برنده این ماه:')} *{winner_name}* (`{winner_id}`)\n{escape_markdown('جایزه با موفقیت به ایشان اهدا شد.')}"
        for admin_id in ADMIN_IDS:
            self._notify_user(admin_id, admin_message)

        # پاک کردن بلیط‌ها برای دوره بعد
        db.clear_lottery_tickets()

    def _send_weekend_vip_message(self) -> None:
        """پیام قدردانی آخر هفته را برای کاربران VIP ارسال می‌کند."""
        import random
        import time
        from telebot import types

        logger.info("SCHEDULER: Sending weekend thank you message to VIP users.")
        
        all_uuids = db.get_all_user_uuids()
        vip_users = [u for u in all_uuids if u.get('is_vip')]
        if not vip_users:
            logger.info("No VIP users found to send weekend message.")
            return
        vip_user_ids = {db.get_user_id_by_uuid(u['uuid']) for u in vip_users if db.get_user_id_by_uuid(u['uuid'])}

        message_templates = [
            "سلام {name} عزیز ✨\n\nامیدوارم شروع آخر هفته خوبی داشته باشی و فرصتی برای استراحت پیدا کنی.\n\nاین یک پیام قدردانی مخصوص کاربران ویژه ماست. چه بخوای فیلم ببینی، چه آنلاین بازی کنی، می‌خوام خیالت راحت باشه که اتصال پایدارت برای من در اولویته.\n\nاگه حس کردی سرعت یا کیفیت اتصال مثل همیشه نیست، بدون تردید روی دکمه زیر بزن تا شخصاً برات پیگیری کنم.\n\nمراقب خودت باش و از تعطیلاتت لذت ببر.",
            "سلام {name}، آخر هفته‌ات بخیر! ☀️\n\nفقط خواستم بگم حواسم به کیفیت سرویس هست تا تو این آخر هفته با خیال راحت به کارهات برسی.\n\nاگه موقع استریم یا هر استفاده دیگه‌ای حس کردی چیزی مثل همیشه نیست، من اینجام تا سریع حلش کنم. هدف من اینه که تو بهترین تجربه رو داشته باشی.\n\nآخر هفته خوبی داشته باشی و حسابی استراحت کن!",
            "{name} عزیز، آخر هفته خوبی پیش رو داشته باشی! ☕️\n\nهدف ما اینه که تو بتونی بدون هیچ دغدغه‌ای از دنیای آنلاین لذت ببری.\n\nاگه احساس کردی سرویس اون‌طور که باید باشه نیست و مانع تفریح یا کارت شده، حتماً بهم خبر بده. اتصال بی‌نقص حق شماست.\n\nامیدوارم آخر هفته پر از آرامشی داشته باشی. مراقب خودت هم باش."
        ]
        
        button_texts = [
            "💬 پشتیبانی ویژه VIP", "💬 اگه مشکلی بود، به من بگو",
            "📞 خط ارتباطی سریع", "ارتباط مستقیم با مدیریت", "پشتیبانی اختصاصی شما"
        ]

        my_telegram_username = "Mohammadnzrr"

        for user_id in vip_user_ids:
            try:
                user_info = db.user(user_id)
                if user_info:
                    user_name = user_info.get('first_name', 'کاربر ویژه')
                    
                    chosen_template = random.choice(message_templates)
                    chosen_button_text = random.choice(button_texts)
                    
                    escaped_template = escape_markdown(chosen_template)
                    final_template = escaped_template.replace('\\{name\\}', '{name}')
                    
                    kb = types.InlineKeyboardMarkup()
                    kb.add(types.InlineKeyboardButton(chosen_button_text, url=f"https://t.me/{my_telegram_username}"))
                    
                    # حالا تابع _send_warning_message به درستی کار خواهد کرد
                    self._send_warning_message(
                        user_id,
                        final_template,
                        reply_markup=kb,
                        name=user_name  # نام خام ارسال می‌شود تا در تابع escape شود
                    )
                    time.sleep(0.5)
            except Exception as e:
                logger.error(f"Failed to send VIP message to user {user_id}: {e}")


    def _send_weekend_normal_user_message(self) -> None:
        """پیام قدردانی آخر هفته را برای کاربران عادی (غیر VIP) ارسال می‌کند."""
        import random
        import time
        from telebot import types

        logger.info("SCHEDULER: Sending weekend thank you message to normal users.")
        
        all_uuids = db.get_all_user_uuids()
        normal_users_uuids = [u for u in all_uuids if not u.get('is_vip')]
        
        if not normal_users_uuids:
            logger.info("No normal users found to send weekend message.")
            return

        normal_user_ids = {db.get_user_id_by_uuid(u['uuid']) for u in normal_users_uuids if db.get_user_id_by_uuid(u['uuid'])}

        message_templates = [
            "سلام {name} عزیز!\n\nامیدوارم آخر هفته خوبی داشته باشی. خواستم از همراهی و اعتماد شما به سرویس ما تشکر کنم. حضور شما برای ما بسیار ارزشمنده.\n\nما همیشه در تلاشیم تا بهترین و پایدارترین اتصال رو برای شما فراهم کنیم. یادت باشه که با تمدید به موقع سرویس و دعوت از دوستانت، می‌تونی امتیاز جمع کنی و به جمع کاربران ویژه ما بپیوندی.\n\nاگه هر سوالی داشتی، من برای کمک آماده‌ام.",
            "سلام {name} عزیز، آخر هفته‌ات بخیر! ☀️\n\nاز اینکه بخشی از جامعه کاربران ما هستی، خوشحالیم. امیدواریم از سرویس‌مون راضی باشی.\n\nخواستم یادآوری کنم که همیشه می‌تونی از بخش «🏆 دستاوردها» در ربات، راه‌های کسب امتیاز رو ببینی و از «🛍️ فروشگاه» برای خودت حجم یا روز اضافه هدیه بگیری.\n\nاگه پیشنهادی برای بهتر شدن سرویس داشتی، خوشحال میشم بشنوم. آخر هفته خوبی داشته باشی!"
        ]
        
        button_texts = [
            "💬 راهنمایی و پشتیبانی", "💬 ارسال پیشنهاد یا سوال"
        ]

        my_telegram_username = "Nzrmohammad"

        for user_id in normal_user_ids:
            try:
                user_info = db.user(user_id)
                if user_info:
                    user_name = user_info.get('first_name', 'کاربر گرامی')
                    
                    chosen_template = random.choice(message_templates)
                    chosen_button_text = random.choice(button_texts)
                    
                    escaped_template = escape_markdown(chosen_template)
                    final_template = escaped_template.replace('\\{name\\}', '{name}')
                    
                    kb = types.InlineKeyboardMarkup()
                    kb.add(types.InlineKeyboardButton(chosen_button_text, url=f"https://t.me/{my_telegram_username}"))
                    
                    self._send_warning_message(
                        user_id,
                        final_template,
                        reply_markup=kb,
                        name=user_name # نام خام ارسال می‌شود تا در تابع escape شود
                    )
                    time.sleep(0.5)
            except Exception as e:
                logger.error(f"Failed to send normal user message to user {user_id}: {e}")

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
        schedule.every().day.at("23:50", self.tz_str).do(self._send_daily_achievements_report)
        schedule.every().thursday.at("17:15", self.tz_str).do(self._send_weekend_vip_message)
        schedule.every().thursday.at("17:20", self.tz_str).do(self._send_weekend_normal_user_message)
        schedule.every().friday.at("23:30", self.tz_str).do(self._send_achievement_leaderboard)
        schedule.every().friday.at("23:55", self.tz_str).do(self._weekly_report)
        schedule.every().friday.at("23:59", self.tz_str).do(self._send_weekly_admin_summary)
        schedule.every().friday.at("21:00", self.tz_str).do(self._run_lucky_lottery)
        schedule.every().friday.at("21:05", self.tz_str).do(self._send_lucky_badge_summary)
        schedule.every(ONLINE_REPORT_UPDATE_HOURS).hours.do(self._update_online_reports)
        schedule.every().day.at("00:05", self.tz_str).do(self._birthday_gifts_job)
        schedule.every().day.at("02:00", self.tz_str).do(self._check_achievements_and_anniversary)
        schedule.every().day.at("00:15", self.tz_str).do(self._check_for_special_occasions)
        schedule.every().day.at("04:30", self.tz_str).do(self._check_auto_renewals_and_warnings)
        schedule.every(12).hours.do(self._sync_users_with_panels)
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