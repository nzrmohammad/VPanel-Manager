import logging
import sys
import signal
import time
from datetime import datetime
from telebot import TeleBot

from .bot_instance import bot, admin_conversations
from .config import LOG_LEVEL, ADMIN_IDS, BOT_TOKEN
from .database import db
from .scheduler import SchedulerManager
from .user_router import register_user_handlers, initialize_user_handlers
from .admin_router import register_admin_handlers 
from .callback_router import register_callback_router
from .utils import initialize_utils
from .inline_handlers import register_inline_handlers


logger = logging.getLogger(__name__)
scheduler = SchedulerManager(bot)

def setup_bot_logging():
    """تنظیمات مربوط به لاگ‌نویسی ربات را انجام می‌دهد."""
    class UserIdFilter(logging.Filter):
        def filter(self, record):
            if not hasattr(record, 'user_id'):
                record.user_id = 'SYSTEM'
            return True
    
    LOG_FORMAT = "%(asctime)s — %(name)s — %(levelname)s — [User:%(user_id)s] — %(message)s"
    
    logging.basicConfig(
        level=LOG_LEVEL,
        format=LOG_FORMAT,
        handlers=[
            logging.FileHandler("bot.log", encoding="utf-8"),
            logging.FileHandler("error.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ],
        force=True
    )

    root_logger = logging.getLogger()
    user_id_filter = UserIdFilter()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler):
            handler.addFilter(user_id_filter)
            if "error.log" in handler.baseFilename:
                handler.setLevel(logging.ERROR)
            else:
                handler.setLevel(logging.INFO)

def _notify_admins_start() -> None:
    """پس از اجرای موفقیت‌آمیز ربات، به ادمین‌ها پیام اطلاع‌رسانی ارسال می‌کند."""
    text = "🚀 ربات با موفقیت فعال شد"
    for aid in ADMIN_IDS:
        try:
            bot.send_message(aid, text, parse_mode=None)
        except Exception as e:
            logger.warning(f"Could not send start notification to admin {aid}: {e}")

class HiddifyBot:
    """کلاس اصلی ربات که مسئولیت اجرا و خاموش کردن آن را بر عهده دارد."""
    def __init__(self) -> None:
        self.bot = bot
        self.scheduler = scheduler
        self.running = False
        self.started_at: datetime | None = None
        # مدیریت سیگنال‌های خاموش شدن سیستم برای خروج امن
        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)

    def _on_signal(self, signum, _frame):
        logger.info(f"Received signal {signum} -> shutting down...")
        self.shutdown()
        sys.exit(0)

    def start(self) -> None:
        """متد اصلی برای اجرای ربات."""
        if self.running: return
        try:
            logger.info("Registering handlers ...")
            initialize_utils(self.bot)
            initialize_user_handlers(self.bot, admin_conversations)
            register_user_handlers(self.bot)
            register_admin_handlers(self.bot, self.scheduler)
            register_callback_router(self.bot)
            register_inline_handlers(self.bot)
            
            logger.info("✅ Handlers registered")
            
            # تست اتصال به دیتابیس
            logger.info("Testing Database connectivity ...")
            db.user(0) 
            logger.info("✅ SQLite ready")
            
            # شروع به کار زمان‌بند (Scheduler)
            self.scheduler.start()
            logger.info("✅ Scheduler thread started")
            
            # اطلاع‌رسانی به ادمین‌ها و شروع polling
            _notify_admins_start()
            self.running = True
            self.started_at = datetime.now()
            logger.info("🚀 Polling ...")
            
            # حلقه اصلی اجرای ربات
            while self.running:
                try:
                    self.bot.infinity_polling(timeout=20, skip_pending=True)
                except Exception as e:
                    logger.error(f"FATAL ERROR: Bot polling failed: {e}", exc_info=True)
                    logger.info("Restarting polling in 15 seconds...")
                    time.sleep(15)
        except Exception as exc:
            logger.exception(f"Start-up failed: {exc}")
            self.shutdown()
            raise

    def shutdown(self) -> None:
        """متد برای خاموش کردن امن ربات."""
        if not self.running: return
        logger.info("Graceful shutdown ...")
        self.running = False
        try:
            self.scheduler.shutdown()
            logger.info("Scheduler stopped")
            self.bot.stop_polling()
            logger.info("Telegram polling stopped")
            if self.started_at:
                uptime = datetime.now() - self.started_at
                logger.info(f"Uptime: {uptime}")
        finally:
            self.running = False
            logger.info("Shutdown complete")