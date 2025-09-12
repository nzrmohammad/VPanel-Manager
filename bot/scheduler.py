import logging
import threading
import time
import schedule
import pytz
from telebot import TeleBot

from bot.config import DAILY_REPORT_TIME, TEHRAN_TZ, USAGE_WARNING_CHECK_HOURS, ONLINE_REPORT_UPDATE_HOURS
from bot.scheduler_jobs import reports, warnings, rewards, maintenance

logger = logging.getLogger(__name__)
scheduler_lock = threading.Lock()

class SchedulerManager:
    def __init__(self, bot: TeleBot) -> None:
        self.bot = bot
        self.running = False
        self.tz = pytz.timezone(TEHRAN_TZ) if isinstance(TEHRAN_TZ, str) else TEHRAN_TZ
        self.tz_str = str(self.tz)

    def _run_job(self, job_func, *args, **kwargs):
        """یک پوشش امن (thread-safe) برای اجرای تمام وظایف زمان‌بندی شده."""
        logger.info(f"SCHEDULER: Attempting to run job: {job_func.__name__}")
        with scheduler_lock:
            try:
                # نمونه bot را به عنوان اولین آرگومان به تابع وظیفه پاس می‌دهیم
                job_func(self.bot, *args, **kwargs)
            except Exception as e:
                logger.error(f"SCHEDULER: A critical error occurred in job '{job_func.__name__}': {e}", exc_info=True)
        logger.info(f"SCHEDULER: Job finished: {job_func.__name__}")

    def start(self) -> None:
        if self.running: return
        
        report_time_str = DAILY_REPORT_TIME.strftime("%H:%M")

        # --- زمان‌بندی تمام وظایف از ماژول‌های مربوطه ---
        schedule.every(1).hours.at(":01").do(self._run_job, maintenance.hourly_snapshots)
        schedule.every(USAGE_WARNING_CHECK_HOURS).hours.do(self._run_job, warnings.check_for_warnings)
        schedule.every().day.at(report_time_str, self.tz_str).do(self._run_job, reports.nightly_report)
        schedule.every().day.at("23:50", self.tz_str).do(self._run_job, reports.send_daily_achievements_report)
        schedule.every().thursday.at("17:15", self.tz_str).do(self._run_job, rewards.send_weekend_vip_message)
        schedule.every().thursday.at("17:20", self.tz_str).do(self._run_job, rewards.send_weekend_normal_user_message)
        schedule.every().friday.at("23:30", self.tz_str).do(self._run_job, rewards.send_achievement_leaderboard)
        schedule.every().friday.at("23:55", self.tz_str).do(self._run_job, reports.weekly_report)
        schedule.every().friday.at("23:59", self.tz_str).do(self._run_job, reports.send_weekly_admin_summary)
        schedule.every().friday.at("21:00", self.tz_str).do(self._run_job, rewards.run_lucky_lottery)
        schedule.every().friday.at("21:05", self.tz_str).do(self._run_job, rewards.send_lucky_badge_summary)
        schedule.every(ONLINE_REPORT_UPDATE_HOURS).hours.do(self._run_job, maintenance.update_online_reports)
        schedule.every().day.at("00:05", self.tz_str).do(self._run_job, rewards.birthday_gifts_job)
        schedule.every().day.at("02:00", self.tz_str).do(self._run_job, rewards.check_achievements_and_anniversary)
        schedule.every().day.at("00:15", self.tz_str).do(self._run_job, rewards.check_for_special_occasions)
        schedule.every().day.at("04:30", self.tz_str).do(self._run_job, rewards.check_auto_renewals_and_warnings)
        schedule.every(12).hours.do(self._run_job, maintenance.sync_users_with_panels)
        schedule.every(8).hours.do(self._run_job, maintenance.cleanup_old_reports)
        schedule.every().day.at("04:00", self.tz_str).do(self._run_job, maintenance.run_monthly_vacuum)
        
        self.running = True
        threading.Thread(target=self._runner, daemon=True).start()
        logger.info("Scheduler started successfully with modular jobs.")

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

    # --- توابع تست برای ادمین ---
    def _nightly_report(self, target_user_id: int = None):
        self._run_job(reports.nightly_report, target_user_id=target_user_id)

    def _weekly_report(self, target_user_id: int = None):
        self._run_job(reports.weekly_report, target_user_id=target_user_id)

    def _check_for_warnings(self, target_user_id: int = None):
        self._run_job(warnings.check_for_warnings, target_user_id=target_user_id)
        
    def _check_achievements_and_anniversary(self):
        self._run_job(rewards.check_achievements_and_anniversary)

    def _birthday_gifts_job(self):
        self._run_job(rewards.birthday_gifts_job)