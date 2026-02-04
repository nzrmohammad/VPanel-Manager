# bot/db/base.py

import sqlite3
import logging
import threading
from contextlib import contextmanager
from typing import Iterator

# قفل برای جلوگیری از تداخل در محیط‌های چندنخی
db_lock = threading.RLock()
logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    کلاس پایه برای مدیریت عملیات دیتابیس SQLite.
    این نسخه اصلاح‌شده است و جداول قدیمی و ناسازگار را نمی‌سازد.
    """
    def __init__(self, path: str = "bot_data.db"):
        self.path = path
        self._user_cache = {}
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        with db_lock:
            try:
                conn = sqlite3.connect(self.path, detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys = ON;")
                conn.row_factory = sqlite3.Row
                yield conn
                conn.commit()
            except sqlite3.Error as e:
                logger.error(f"Database error: {e}")
                if 'conn' in locals():
                    conn.rollback()
                raise
            finally:
                if 'conn' in locals():
                    conn.close()

    def write_conn(self, query: str, params: tuple = ()):
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.lastrowid

    def check_connection(self) -> bool:
        try:
            with self._conn() as c:
                c.execute("SELECT 1")
            return True
        except sqlite3.Error as e:
            logger.error(f"Database connection check failed: {e}", exc_info=True)
            return False

    def clear_user_cache(self, user_id: int):
        if user_id in self._user_cache:
            with db_lock:
                if user_id in self._user_cache:
                    del self._user_cache[user_id]

    def _init_db(self):
        """
        ایجاد جداول ضروری دیتابیس.
        جداول قدیمی و ناسازگار از این لیست حذف شده‌اند.
        تمام کلیدهای خارجی به درستی به users(user_id) اشاره می‌کنند.
        """
        tables_queries = [
            # 1. جدول کاربران
            """CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                birthday DATE,
                daily_reports INTEGER DEFAULT 1,
                expiry_warnings INTEGER DEFAULT 1,
                data_warning_de INTEGER DEFAULT 1,
                data_warning_fr INTEGER DEFAULT 1,
                data_warning_tr INTEGER DEFAULT 1,
                data_warning_us INTEGER DEFAULT 1,
                data_warning_nl INTEGER DEFAULT 1,
                data_warning_al INTEGER DEFAULT 1,
                data_warning_ro INTEGER DEFAULT 1,
                data_warning_supp INTEGER DEFAULT 1,
                show_info_config INTEGER DEFAULT 1,
                admin_note TEXT,
                lang_code TEXT,
                last_checkin DATE,
                streak_count INTEGER DEFAULT 0,
                weekly_reports INTEGER DEFAULT 1,
                monthly_reports INTEGER DEFAULT 1,
                auto_delete_reports INTEGER DEFAULT 0,
                referral_code TEXT,
                referred_by_user_id INTEGER,
                referral_reward_applied INTEGER DEFAULT 0,
                achievement_points INTEGER DEFAULT 0,
                achievement_alerts INTEGER DEFAULT 1,
                promotional_alerts INTEGER DEFAULT 1,
                wallet_balance REAL DEFAULT 0.0,
                auto_renew INTEGER DEFAULT 0
            );""",

            # 2. جدول کانفیگ‌ها
            """CREATE TABLE IF NOT EXISTS user_uuids (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                uuid TEXT,
                name TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP,
                first_connection_time TIMESTAMP,
                welcome_message_sent INTEGER DEFAULT 0,
                renewal_reminder_sent INTEGER DEFAULT 0,
                is_vip INTEGER DEFAULT 0,
                has_access_ir INTEGER DEFAULT 0,
                has_access_de INTEGER DEFAULT 1,
                has_access_fr INTEGER DEFAULT 0,
                has_access_tr INTEGER DEFAULT 0,
                has_access_us INTEGER DEFAULT 0,
                has_access_al INTEGER DEFAULT 0,
                has_access_nl INTEGER DEFAULT 0,
                has_access_ro INTEGER DEFAULT 0,
                has_access_supp INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );""",

            # 3. جدول اسنپ‌شات‌های مصرف
            """CREATE TABLE IF NOT EXISTS usage_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid_id INTEGER,
                hiddify_usage_gb REAL DEFAULT 0,
                marzban_usage_gb REAL DEFAULT 0,
                taken_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(uuid_id) REFERENCES user_uuids(id) ON DELETE CASCADE
            );""",

            # 4. پیام‌های زمان‌بندی شده
            """CREATE TABLE IF NOT EXISTS scheduled_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_type TEXT,
                chat_id INTEGER,
                message_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",

            # 5. لاگ هشدارها
            """CREATE TABLE IF NOT EXISTS warning_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid_id INTEGER,
                warning_type TEXT,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",

            # 6. پرداخت‌ها
            """CREATE TABLE IF NOT EXISTS payments (
                payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid_id INTEGER,
                payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",

            # 7. قالب‌های کانفیگ
            """CREATE TABLE IF NOT EXISTS config_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_str TEXT,
                is_active INTEGER DEFAULT 1,
                is_special INTEGER DEFAULT 0,
                is_random_pool INTEGER DEFAULT 0,
                server_type TEXT DEFAULT 'none',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",

            # 8. کانفیگ‌های تولید شده
            """CREATE TABLE IF NOT EXISTS user_generated_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_uuid_id INTEGER,
                template_id INTEGER,
                generated_uuid TEXT
            );""",

            # 9. نگاشت مرزبان
            """CREATE TABLE IF NOT EXISTS marzban_mapping (
                hiddify_uuid TEXT,
                marzban_username TEXT
            );""",

            # 10. توکن‌های ورود
            """CREATE TABLE IF NOT EXISTS login_tokens (
                token TEXT PRIMARY KEY,
                uuid TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",

            # 11. گزارش‌های ارسال شده
            """CREATE TABLE IF NOT EXISTS sent_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message_id INTEGER,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",

            # 12. دستگاه‌های کاربر
            """CREATE TABLE IF NOT EXISTS client_user_agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid_id INTEGER,
                user_agent TEXT,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",

            # 13. پنل‌ها
            """CREATE TABLE IF NOT EXISTS panels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                panel_type TEXT,
                api_url TEXT,
                api_token1 TEXT,
                api_token2 TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",

            # 14. انتقال ترافیک
            """CREATE TABLE IF NOT EXISTS traffic_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_uuid_id INTEGER,
                receiver_uuid_id INTEGER,
                panel_type TEXT,
                amount_gb REAL,
                transferred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",

            # 15. دستاوردهای کاربر (جدید)
            """CREATE TABLE IF NOT EXISTS user_achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                badge_code TEXT,
                awarded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",

            # 16. لاگ خرید فروشگاه
            """CREATE TABLE IF NOT EXISTS achievement_shop_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item_key TEXT,
                cost INTEGER,
                purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",

            # 17. لاگ هدیه تولد
            """CREATE TABLE IF NOT EXISTS birthday_gift_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                gift_year INTEGER,
                given_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",

            # 18. لاگ هدیه سالگرد
            """CREATE TABLE IF NOT EXISTS anniversary_gift_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                gift_year INTEGER,
                given_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",

            # 19. تراکنش‌های کیف پول (اصلی)
            """CREATE TABLE IF NOT EXISTS wallet_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                type TEXT,
                description TEXT,
                transaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );""",

            # 20. درخواست‌های شارژ
            """CREATE TABLE IF NOT EXISTS charge_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                message_id INTEGER,
                request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_pending INTEGER DEFAULT 1,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );""",

            # 21. انتقال‌های کیف پول
            """CREATE TABLE IF NOT EXISTS wallet_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_user_id INTEGER,
                receiver_user_id INTEGER,
                amount REAL,
                transferred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",

            # 22. لاگ تمدید خودکار
            """CREATE TABLE IF NOT EXISTS auto_renewal_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                uuid_id INTEGER,
                plan_price REAL,
                renewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",

            # 23. بلیط‌های قرعه‌کشی
            """CREATE TABLE IF NOT EXISTS lottery_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",

            # 24. اعلان‌ها
            """CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                message TEXT,
                category TEXT DEFAULT 'info',
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );""",

            # 25. لاگ قهرمان هفتگی
            """CREATE TABLE IF NOT EXISTS weekly_champion_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                win_date DATE
            );""",

            # 26. درخواست‌های دستاورد
            """CREATE TABLE IF NOT EXISTS achievement_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                badge_code TEXT,
                status TEXT DEFAULT 'pending',
                requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_by INTEGER,
                reviewed_at TIMESTAMP
            );""",

            # 27. هزینه‌های ماهانه
            """CREATE TABLE IF NOT EXISTS monthly_costs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                year INTEGER,
                month INTEGER,
                cost REAL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",
            
            # 28. بازخورد کاربران
            """CREATE TABLE IF NOT EXISTS user_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                rating INTEGER,
                comment TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );""",

            # 29. تیکت‌های پشتیبانی
            """CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                status TEXT DEFAULT 'open',
                initial_admin_message_id INTEGER,
                last_message_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );"""
        ]

        # ایندکس‌های ضروری
        indices_queries = [
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code);",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_uuids_uuid_user ON user_uuids(user_id, uuid);",
            "CREATE INDEX IF NOT EXISTS idx_user_uuids_uuid ON user_uuids(uuid);",
            "CREATE INDEX IF NOT EXISTS idx_user_uuids_user_id ON user_uuids(user_id);",
            "CREATE INDEX IF NOT EXISTS idx_usage_snapshots_uuid_taken ON usage_snapshots(uuid_id, taken_at);",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_marzban_mapping_uuid ON marzban_mapping(hiddify_uuid);",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_marzban_mapping_username ON marzban_mapping(marzban_username);"
        ]

        with self._conn() as conn:
            for query in tables_queries:
                try:
                    conn.execute(query)
                except sqlite3.Error as e:
                    logger.error(f"Error checking/creating table: {e}")
            
            for idx_query in indices_queries:
                try:
                    conn.execute(idx_query)
                except sqlite3.Error as e:
                    logger.warning(f"Index creation notice: {e}")