# bot/database.py

import logging

# وارد کردن تمام کلاس‌های پایه‌ای که ساختیم
from .db.user import UserDB
from .db.usage import UsageDB
from .db.wallet import WalletDB
from .db.achievement import AchievementDB
from .db.panel import PanelDB
from .db.financials import FinancialsDB  # <--- اضافه شد
from .db.transfer import TransferDB      # <--- اضافه شد
from .db.notifications import NotificationsDB # <--- اضافه شد


logger = logging.getLogger(__name__)

# کلاس اصلی دیتابیس که از تمام کلاس‌های دیگر ارث‌بری می‌کند
class Database(UserDB, UsageDB, WalletDB, AchievementDB, PanelDB, FinancialsDB, TransferDB, NotificationsDB):
    """
    کلاس جامع برای مدیریت دیتابیس.
    این کلاس تمام کلاس‌های مدیریتی دیگر را ترکیب کرده و یک نقطه دسترسی واحد
    برای تمام عملیات دیتابیس در برنامه فراهم می‌کند.
    """
    def __init__(self, path: str = "bot_data.db"):
        """
        سازنده کلاس که تنها یک بار فراخوانی شده و اتصال اولیه به دیتابیس را برقرار می‌کند.
        """
        # فراخوانی سازنده کلاس پایه (DatabaseManager)
        super().__init__(path)
        logger.info("Database connection established and all modules are integrated.")

# --- ساخت یک نمونه واحد از کلاس دیتابیس ---
# این نمونه (instance) در تمام بخش‌های ربات شما import شده و استفاده می‌شود.
db = Database()