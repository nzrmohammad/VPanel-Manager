# bot/db/base.py

import sqlite3
import logging
import threading
from contextlib import contextmanager
from typing import Iterator # <--- این import اضافه شده است

# برای جلوگیری از تداخل در دسترسی به دیتابیس در محیط‌های چندنخی (multi-threaded)
db_lock = threading.RLock()
logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    کلاس پایه برای مدیریت عملیات دیتابیس SQLite.
    این کلاس اتصال به دیتابیس، مقداردهی اولیه و اجرای کوئری‌ها
    به صورت thread-safe را مدیریت می‌کند.
    """
    def __init__(self, path: str = "bot_data.db"):
        """
        مقداردهی اولیه مدیر دیتابیس.

        Args:
            path (str): مسیر فایل دیتابیس SQLite.
        """
        self.path = path
        self._user_cache = {}  # کش برای نگهداری اطلاعات کاربران و کاهش کوئری‌ها
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]: # <--- نوع خروجی در اینجا اصلاح شد
        """
        یک context manager برای اتصال به دیتابیس.
        این متد اتصال امن و خودکار commit و close را تضمین می‌کند.
        """
        with db_lock:
            try:
                conn = sqlite3.connect(self.path, detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
                conn.execute("PRAGMA journal_mode=WAL")  # حالت Write-Ahead Logging برای بهبود همزمانی
                conn.execute("PRAGMA foreign_keys = ON;")
                conn.row_factory = sqlite3.Row  # دسترسی به ستون‌ها با نام آن‌ها
                yield conn
                conn.commit()
            except sqlite3.Error as e:
                logger.error(f"Database error: {e}")
                if 'conn' in locals():
                    conn.rollback()
                raise  # ارور را مجدداً ایجاد می‌کند تا در لایه‌های بالاتر مدیریت شود
            finally:
                if 'conn' in locals():
                    conn.close()

    def write_conn(self, query: str, params: tuple = ()):
        """
        برای اجرای کوئری‌های نوشتنی (INSERT, UPDATE, DELETE).

        Args:
            query (str): کوئری SQL.
            params (tuple): پارامترهای کوئری برای جلوگیری از SQL Injection.

        Returns:
            int: شناسه آخرین ردیف درج شده (lastrowid).
        """
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.lastrowid

    def check_connection(self) -> bool:
            """Checks if the database connection is alive and well."""
            try:
                # یک کوئری ساده برای اطمینان از باز بودن و سالم بودن اتصال
                with self._conn() as c:
                    c.execute("SELECT 1")
                return True
            except sqlite3.Error as e:
                logger.error(f"Database connection check failed: {e}", exc_info=True)
                return False

    def clear_user_cache(self, user_id: int):
        """
        کش یک کاربر خاص را پاک می‌کند.
        این متد زمانی فراخوانی می‌شود که اطلاعات کاربر در دیتابیس تغییر کرده باشد.
        """
        if user_id in self._user_cache:
            with db_lock:
                if user_id in self._user_cache:
                    del self._user_cache[user_id]


    def _init_db(self):
        """
        جداول دیتابیس را در صورت عدم وجود ایجاد می‌کند.
        این متد در زمان ساخت نمونه اولیه کلاس فراخوانی می‌شود.
        """
        tables_to_create = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_admin BOOLEAN DEFAULT 0,
                is_banned BOOLEAN DEFAULT 0,
                lang TEXT DEFAULT 'fa',
                wallet_balance REAL DEFAULT 0,
                referral_code TEXT,
                referred_by INTEGER,
                points INTEGER DEFAULT 0,
                notif_on_login BOOLEAN DEFAULT 1,
                notif_on_almost_expire BOOLEAN DEFAULT 1,
                notif_on_expire BOOLEAN DEFAULT 1,
                notif_on_limit BOOLEAN DEFAULT 1,
                notif_on_news BOOLEAN DEFAULT 1,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referred_by) REFERENCES users(id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS panels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                api_url TEXT NOT NULL,
                api_token_1 TEXT NOT NULL,
                api_token_2 TEXT,
                is_active BOOLEAN DEFAULT 1
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS uuids (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                panel_id INTEGER,
                uuid_str TEXT NOT NULL,
                name TEXT,
                hiddify_user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (panel_id) REFERENCES panels(id) ON DELETE SET NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS usage_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid_id INTEGER,
                hiddify_usage REAL,
                marzban_usage REAL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (uuid_id) REFERENCES uuids(id) ON DELETE CASCADE
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS wallet_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                transaction_type TEXT,
                description TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS charge_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                screenshot_id TEXT,
                is_approved BOOLEAN,
                approved_by INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (approved_by) REFERENCES users(id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                badge_code TEXT,
                achieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS config_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                panel_type TEXT,
                url_template TEXT,
                qr_template TEXT,
                is_default BOOLEAN DEFAULT 0
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS sent_warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                warning_type TEXT,
                uuid_id INTEGER,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (uuid_id) REFERENCES uuids(id) ON DELETE CASCADE
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS sent_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                report_type TEXT,
                uuid_id INTEGER,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (uuid_id) REFERENCES uuids(id) ON DELETE CASCADE
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """
        ]
        with self._conn() as conn:
            for table in tables_to_create:
                conn.execute(table)