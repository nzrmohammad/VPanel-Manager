import logging
import time
from datetime import datetime, timedelta
import pytz
import jdatetime
from telebot import types, apihelper
from ..menu import menu

from bot import combined_handler
from bot.database import db
from bot.utils import escape_markdown
from bot.admin_formatters import fmt_admin_report, fmt_weekly_admin_summary, fmt_daily_achievements_report
from bot.user_formatters import fmt_user_report, fmt_user_weekly_report
from bot.config import ADMIN_IDS, ACHIEVEMENTS
from bot.language import get_string

logger = logging.getLogger(__name__)

def nightly_report(bot, target_user_id: int = None) -> None:
    """
    گزارش شبانه را برای کاربران و گزارش جامع را برای ادمین‌ها ارسال می‌کند.
    (نسخه اصلاح شده با مدیریت خطا در حلقه)
    """
    tehran_tz = pytz.timezone("Asia/Tehran")
    now_gregorian = datetime.now(tehran_tz)
    
    is_friday = jdatetime.datetime.fromgregorian(datetime=now_gregorian).weekday() == 6

    now_str = jdatetime.datetime.fromgregorian(datetime=now_gregorian).strftime("%Y/%m/%d - %H:%M")
    logger.info(f"SCHEDULER: ----- Running nightly report at {now_str} -----")

    all_users_info_from_api = combined_handler.get_all_users_combined()
    if not all_users_info_from_api:
        logger.warning("SCHEDULER: Could not fetch API user info for nightly report. JOB STOPPED.")
        return
        
    user_info_map = {user['uuid']: user for user in all_users_info_from_api}
    
    user_ids_to_process = [target_user_id] if target_user_id else list(db.get_all_user_ids())
    separator = '\n' + '─' * 18 + '\n'

    for user_id in user_ids_to_process:
        try:
            # گزارش جامع برای ادمین‌ها (همیشه ارسال می‌شود)
            if user_id in ADMIN_IDS:
                admin_header = f"👑 *گزارش جامع* {escape_markdown('-')} {escape_markdown(now_str)}{separator}"
                admin_report_text = fmt_admin_report(all_users_info_from_api, db)
                admin_full_message = admin_header + admin_report_text
                
                if len(admin_full_message) > 4096:
                    chunks = [admin_full_message[i:i + 4090] for i in range(0, len(admin_full_message), 4090)]
                    for i, chunk in enumerate(chunks):
                        if i > 0:
                            chunk = f"*{escape_markdown('(ادامه گزارش جامع)')}*\n\n" + chunk
                        bot.send_message(user_id, chunk, parse_mode="MarkdownV2")
                        time.sleep(0.5)
                else:
                    bot.send_message(user_id, admin_full_message, parse_mode="MarkdownV2")

            # اگر جمعه بود و کاربر ادمین نبود، گزارش شخصی برای او ارسال نمی‌شود
            if is_friday and user_id not in ADMIN_IDS and not target_user_id:
                continue

            # گزارش شخصی برای همه کاربران (شامل ادمین‌ها)
            user_settings = db.get_user_settings(user_id)
            if not user_settings.get('daily_reports', True) and not target_user_id:
                continue

            user_uuids_from_db = db.uuids(user_id)
            user_infos_for_report = []
            
            for u_row in user_uuids_from_db:
                if u_row['uuid'] in user_info_map:
                    user_data = user_info_map[u_row['uuid']]
                    user_data['db_id'] = u_row['id'] 
                    user_infos_for_report.append(user_data)
            
            if user_infos_for_report:
                user_header = f"🌙 *گزارش شبانه* {escape_markdown('-')} {escape_markdown(now_str)}{separator}"
                lang_code = db.get_user_language(user_id)
                user_report_text = fmt_user_report(user_infos_for_report, lang_code)
                user_full_message = user_header + user_report_text
                
                sent_message = bot.send_message(user_id, user_full_message, parse_mode="MarkdownV2")
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


def weekly_report(bot, target_user_id: int = None) -> None:
    """
    گزارش هفتگی مصرف را برای کاربران ارسال می‌کند.
    (نسخه اصلاح شده با مدیریت خطا در حلقه)
    """
    now_str = jdatetime.datetime.fromgregorian(datetime=datetime.now(pytz.timezone("Asia/Tehran"))).strftime("%Y/%m/%d - %H:%M")
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
                sent_message = bot.send_message(user_id, final_message, parse_mode="MarkdownV2")
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


def send_weekly_admin_summary(bot) -> None:
    """
    گزارش هفتگی پرمصرف‌ترین کاربران را برای ادمین‌ها ارسال می‌کند و به ۱۰ نفر اول پیام تبریک/انگیزشی می‌فرستد.
    (نسخه نهایی با منطق قهرمانی متوالی)
    """
    from .rewards import notify_user_achievement 
    from .warnings import send_warning_message

    logger.info("SCHEDULER: Sending weekly admin summary and top user notifications.")
    try:
        report_data = db.get_weekly_top_consumers_report()
        report_text = fmt_weekly_admin_summary(report_data)

        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, report_text, parse_mode="MarkdownV2")
            except Exception as e:
                logger.error(f"Failed to send weekly admin summary to {admin_id}: {e}")

        top_users = report_data.get('top_10_overall', [])
        if top_users:
            all_bot_users_with_uuids = db.get_all_bot_users_with_uuids()
            user_map = {}
            for user in all_bot_users_with_uuids:
                name = user.get('config_name')
                if name and name not in user_map:
                    user_map[name] = user['user_id']

            if len(top_users) > 0:
                champion = top_users[0]
                champion_name = champion.get('name')
                champion_id = user_map.get(champion_name)
                if champion_id:
                    # ثبت قهرمانی این هفته
                    db.log_weekly_champion_win(champion_id)
                    
                    is_first_time_win = db.add_achievement(champion_id, 'weekly_champion')
                    
                    if is_first_time_win:
                        notify_user_achievement(bot, champion_id, 'weekly_champion')
                    else:
                        badge = ACHIEVEMENTS.get('weekly_champion')
                        if badge and badge.get("points", 0) > 0:
                            points = badge["points"]
                            db.add_achievement_points(champion_id, points)
                            recurring_win_message = (
                                f"🏆 *قهرمانی دوباره\\!* 🏆\n\n"
                                f"شما این هفته نیز به عنوان *پرمصرف‌ترین کاربر* انتخاب شدید و *{points} امتیاز* دیگر دریافت کردید\\.\n\n"
                                f"به این روند فوق‌العاده ادامه بده\\!"
                            )
                            send_warning_message(bot, champion_id, recurring_win_message)
                    
                    consecutive_wins = db.count_consecutive_weekly_wins(champion_id)
                    if consecutive_wins == 8:
                        if db.add_achievement(champion_id, 'serial_champion'):
                            notify_user_achievement(bot, champion_id, 'serial_champion')

            for i, user in enumerate(top_users):
                try:
                    if i == 0: continue
                    rank = i + 1
                    user_name = user.get('name')
                    usage = user.get('total_usage', 0)
                    
                    user_id = user_map.get(user_name)

                    if user_id:
                        lang_code = db.get_user_language(user_id)
                        message_key = f"weekly_top_user_rank_{rank}" if 2 <= rank <= 3 else "weekly_top_user_rank_4_to_10"
                        fun_message_template = get_string(message_key, lang_code)
                        final_message = fun_message_template.format(
                            usage=escape_markdown(f"{usage:.2f} GB"),
                            rank=rank
                        )
                        send_warning_message(bot, user_id, final_message, name=user_name)
                        time.sleep(0.5)
                except Exception as e:
                    logger.error(f"Failed to send weekly top user notification to user: {user.get('name')}. Error: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"Failed to generate or process weekly admin summary: {e}", exc_info=True)


def send_daily_achievements_report(bot) -> None:
    """
    گزارش روزانه دستاوردهای کسب شده را برای ادمین‌ها ارسال می‌کند.
    (نسخه اصلاح شده با لاگینگ دقیق برای دیباگ)
    """
    logger.info("SCHEDULER: Starting daily achievements report job.")
    try:
        daily_achievements = db.get_daily_achievements()
        if not daily_achievements:
            logger.info("SCHEDULER: No achievements today. Skipping report.")
            return

        report_text = fmt_daily_achievements_report(daily_achievements)

        if not report_text or "هیچ کاربری" in report_text:
             logger.info("SCHEDULER: Formatted achievement report is empty. Skipping sending.")
             return

        for admin_id in ADMIN_IDS:
            try:
                logger.debug(f"Attempting to send daily achievements report to admin {admin_id}. Content length: {len(report_text)}.")
                logger.debug(f"--- START REPORT CONTENT FOR ADMIN {admin_id} ---\n{report_text}\n--- END REPORT CONTENT ---")
                bot.send_message(admin_id, report_text, parse_mode="MarkdownV2")
                logger.info(f"Successfully sent daily achievements report to admin {admin_id}.")

            except Exception as e:
                logger.error(f"Failed to send daily achievements report to admin {admin_id}: {e}", exc_info=True)
                logger.error(f"====== PROBLEMATIC REPORT TEXT START ======\n{report_text}\n====== PROBLEMATIC REPORT TEXT END ======")

    except Exception as e:
        logger.error(f"Failed to generate or process daily achievements report: {e}", exc_info=True)

def send_monthly_satisfaction_survey(bot):
    """
    در آخرین جمعه هر ماه شمسی، پیام نظرسنجی رضایت را برای کاربران فعال ارسال می‌کند.
    """
    logger.info("SCHEDULER: Checking for monthly satisfaction survey...")
    try:
        # --- منطق بررسی آخرین جمعه شمسی ---
        tehran_tz = pytz.timezone("Asia/Tehran")
        now_gregorian = datetime.now(tehran_tz)
        now_shamsi = jdatetime.datetime.fromgregorian(datetime=now_gregorian)
        
        # یک هفته به تاریخ فعلی اضافه کن
        next_week_gregorian = now_gregorian + timedelta(days=7)
        next_week_shamsi = jdatetime.datetime.fromgregorian(datetime=next_week_gregorian)

        # اگر ماه شمسی هفته بعد با ماه شمسی الان فرق داشت،
        # یعنی این آخرین جمعه ماه شمسی است
        is_last_shamsi_friday = (now_shamsi.month != next_week_shamsi.month)
        
        if not is_last_shamsi_friday:
            logger.info(f"SCHEDULER: It's a Friday, but not the last Shamsi Friday. Skipping monthly survey.")
            return
        # --- پایان منطق بررسی ---

        logger.info("SCHEDULER: It's the last Shamsi Friday! Starting monthly satisfaction survey job...")
        
        user_ids = list(db.get_all_user_ids())
        kb = menu.feedback_rating_menu()
        prompt = "🗓 *گزارش ماهانه*\n\nچقدر از عملکرد و پایداری سرویس ما در این ماه راضی بودید؟\n\nلطفاً با انتخاب ستاره‌ها، به ما امتیاز دهید:"
        
        sent_count = 0
        failed_count = 0
        
        for uid in user_ids:
            try:
                bot.send_message(uid, prompt, reply_markup=kb, parse_mode="Markdown")
                sent_count += 1
            except Exception as e:
                logger.warning(f"Failed to send feedback poll to user {uid}: {e}")
                failed_count += 1
        
        logger.info(f"SCHEDULER: Monthly feedback poll finished. Sent: {sent_count}, Failed: {failed_count}")

    except Exception as e:
        logger.error(f"Error in scheduled job send_monthly_satisfaction_survey: {e}", exc_info=True)