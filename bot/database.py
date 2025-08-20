import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import pytz
import uuid as uuid_generator
import secrets

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, path: str = "bot_data.db"):
        self.path = path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as c:
            try:
                cursor = c.execute("PRAGMA table_info(user_uuids);")
                columns = [row['name'] for row in cursor.fetchall()]

                # یک تابع داخلی برای اضافه کردن ستون با مدیریت خطا
                def add_column_if_not_exists(column_name, column_definition):
                    if column_name not in columns:
                        try:
                            logger.info(f"Database Update: Adding '{column_name}' column...")
                            c.execute(f"ALTER TABLE user_uuids ADD COLUMN {column_name} {column_definition};")
                        except sqlite3.OperationalError as e:
                            # اگر ستون از قبل وجود داشت (توسط یک worker دیگر اضافه شده)، خطا را نادیده بگیر
                            if "duplicate column name" in str(e):
                                logger.warning(f"Column '{column_name}' already exists, likely added by another worker. Ignoring.")
                            else:
                                raise e # اگر خطا چیز دیگری بود، آن را نمایش بده

                # اضافه کردن ستون‌ها با استفاده از تابع جدید
                add_column_if_not_exists("has_access_de", "INTEGER DEFAULT 1")
                add_column_if_not_exists("has_access_fr", "INTEGER DEFAULT 0")
                add_column_if_not_exists("has_access_tr", "INTEGER DEFAULT 0")
                
                logger.info("Database schema migration check complete.")

            except sqlite3.OperationalError as e:
                if "no such table" not in str(e):
                    logger.error(f"Failed to update database schema: {e}")
                    raise
            except Exception as e:
                logger.error(f"An unexpected error occurred during schema migration: {e}")
                raise
            # --- END: Robust Database Migration Logic ---

            except Exception as e:
                logger.error(f"Failed to update database schema: {e}")
                # If something goes wrong, we stop to avoid further issues.
                raise

            c.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    birthday DATE,
                    last_name TEXT,
                    daily_reports INTEGER DEFAULT 1,
                    expiry_warnings INTEGER DEFAULT 1,
                    data_warning_hiddify INTEGER DEFAULT 1,
                    data_warning_marzban INTEGER DEFAULT 1,
                    show_info_config INTEGER DEFAULT 1,        
                    admin_note TEXT,
                    lang_code TEXT DEFAULT 'fa'
                );
                CREATE TABLE IF NOT EXISTS user_uuids (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    uuid TEXT UNIQUE,
                    name TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP,
                    first_connection_time TIMESTAMP,
                    welcome_message_sent INTEGER DEFAULT 0,
                    is_vip INTEGER DEFAULT 0,
                    has_access_de INTEGER DEFAULT 1,
                    has_access_fr INTEGER DEFAULT 0,
                    has_access_tr INTEGER DEFAULT 0,        
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS usage_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid_id INTEGER,
                    hiddify_usage_gb REAL DEFAULT 0,
                    marzban_usage_gb REAL DEFAULT 0,
                    taken_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(uuid_id) REFERENCES user_uuids(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS scheduled_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_type TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(job_type, chat_id)
                );
                CREATE TABLE IF NOT EXISTS warning_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid_id INTEGER NOT NULL,
                    warning_type TEXT NOT NULL,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(uuid_id, warning_type)
                );
                CREATE TABLE IF NOT EXISTS payments (
                    payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid_id INTEGER NOT NULL,
                    payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(uuid_id) REFERENCES user_uuids(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS config_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_str TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    is_special INTEGER DEFAULT 0,
                    server_type TEXT DEFAULT 'none',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS user_generated_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_uuid_id INTEGER NOT NULL,
                    template_id INTEGER NOT NULL,
                    generated_uuid TEXT NOT NULL UNIQUE,
                    FOREIGN KEY(user_uuid_id) REFERENCES user_uuids(id) ON DELETE CASCADE,
                    FOREIGN KEY(template_id) REFERENCES config_templates(id) ON DELETE CASCADE,
                    UNIQUE(user_uuid_id, template_id)
                );
                CREATE TABLE IF NOT EXISTS marzban_mapping (
                    hiddify_uuid TEXT PRIMARY KEY,
                    marzban_username TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS login_tokens (
                    token TEXT PRIMARY KEY,
                    uuid TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS panels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    panel_type TEXT NOT NULL, -- 'hiddify' or 'marzban'
                    api_url TEXT NOT NULL,
                    api_token1 TEXT, -- Hiddify UUID or Marzban Username
                    api_token2 TEXT, -- Marzban Password (NULL for Hiddify)
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_user_uuids_uuid ON user_uuids(uuid);
                CREATE INDEX IF NOT EXISTS idx_user_uuids_user_id ON user_uuids(user_id);
                CREATE INDEX IF NOT EXISTS idx_snapshots_uuid_id_taken_at ON usage_snapshots(uuid_id, taken_at);
            """)
        logger.info("SQLite schema is fresh and ready.")

    def add_usage_snapshot(self, uuid_id: int, hiddify_usage: float, marzban_usage: float) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO usage_snapshots (uuid_id, hiddify_usage_gb, marzban_usage_gb, taken_at) VALUES (?, ?, ?, ?)",
                (uuid_id, hiddify_usage, marzban_usage, datetime.now(pytz.utc))
            )

    def get_usage_since_midnight(self, uuid_id: int) -> Dict[str, float]:
        """Calculates daily usage for both panels with a more robust method."""
        tehran_tz = pytz.timezone("Asia/Tehran")
        now_in_tehran = datetime.now(tehran_tz)
        today_midnight_tehran = now_in_tehran.replace(hour=0, minute=0, second=0, microsecond=0)
        
        today_midnight_utc = today_midnight_tehran.astimezone(pytz.utc)

        result = {'hiddify': 0.0, 'marzban': 0.0}

        with self._conn() as c:
            # Get the last snapshot from *before* today's midnight
            yesterday_last_snapshot_query = """
                SELECT hiddify_usage_gb, marzban_usage_gb
                FROM usage_snapshots
                WHERE uuid_id = ? AND taken_at < ?
                ORDER BY taken_at DESC
                LIMIT 1;
            """
            yesterday_row = c.execute(yesterday_last_snapshot_query, (uuid_id, today_midnight_utc)).fetchone()
            
            start_hiddify = yesterday_row['hiddify_usage_gb'] if yesterday_row else 0
            start_marzban = yesterday_row['marzban_usage_gb'] if yesterday_row else 0

            # Get the first and last snapshots from *today*
            today_snapshots_query = """
                SELECT 
                    MIN(hiddify_usage_gb) as h_min, MAX(hiddify_usage_gb) as h_max,
                    MIN(marzban_usage_gb) as m_min, MAX(marzban_usage_gb) as m_max
                FROM usage_snapshots
                WHERE uuid_id = ? AND taken_at >= ?
            """
            today_row = c.execute(today_snapshots_query, (uuid_id, today_midnight_utc)).fetchone()

            if today_row and today_row['h_max'] is not None:
                # If the first snapshot of today is smaller than yesterday's last, it means usage was reset
                if today_row['h_min'] < start_hiddify:
                    start_hiddify = 0
                result['hiddify'] = max(0, today_row['h_max'] - start_hiddify)

            if today_row and today_row['m_max'] is not None:
                if today_row['m_min'] < start_marzban:
                    start_marzban = 0
                result['marzban'] = max(0, today_row['m_max'] - start_marzban)

        return result
    
    def get_panel_usage_in_intervals(self, uuid_id: int, panel_name: str) -> Dict[int, float]:
        if panel_name not in ['hiddify_usage_gb', 'marzban_usage_gb']:
            return {}

        now_utc = datetime.now(pytz.utc)
        intervals = {3: 0.0, 6: 0.0, 12: 0.0, 24: 0.0}
        
        with self._conn() as c:
            for hours in intervals.keys():
                time_ago = now_utc - timedelta(hours=hours)
                
                query = f"""
                    SELECT
                        (SELECT {panel_name} FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ? ORDER BY taken_at ASC LIMIT 1) as start_usage,
                        (SELECT {panel_name} FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ? ORDER BY taken_at DESC LIMIT 1) as end_usage
                """
                params = (uuid_id, time_ago, uuid_id, time_ago)
                row = c.execute(query, params).fetchone()
                
                if row and row['start_usage'] is not None and row['end_usage'] is not None:
                    intervals[hours] = max(0, row['end_usage'] - row['start_usage'])
                    
        return intervals
        
    def log_warning(self, uuid_id: int, warning_type: str):
        with self._conn() as c:
            c.execute(
                "INSERT INTO warning_log (uuid_id, warning_type, sent_at) VALUES (?, ?, ?) "
                "ON CONFLICT(uuid_id, warning_type) DO UPDATE SET sent_at=excluded.sent_at",
                (uuid_id, warning_type, datetime.now(pytz.utc))
            )

    def has_recent_warning(self, uuid_id: int, warning_type: str, hours: int = 24) -> bool:
        time_ago = datetime.now(pytz.utc) - timedelta(hours=hours)
        with self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM warning_log WHERE uuid_id = ? AND warning_type = ? AND sent_at >= ?",
                (uuid_id, warning_type, time_ago)
            ).fetchone()
            return row is not None

    def get_user_ids_by_uuids(self, uuids: List[str]) -> List[int]:
        if not uuids: return []
        placeholders = ','.join('?' for _ in uuids)
        query = f"SELECT DISTINCT user_id FROM user_uuids WHERE uuid IN ({placeholders})"
        with self._conn() as c:
            rows = c.execute(query, uuids).fetchall()
            return [row['user_id'] for row in rows]
        
    def get_uuid_id_by_uuid(self, uuid_str: str) -> Optional[int]:
        with self._conn() as c:
            row = c.execute("SELECT id FROM user_uuids WHERE uuid = ?", (uuid_str,)).fetchone()
            return row['id'] if row else None

    def get_usage_since_midnight_by_uuid(self, uuid_str: str) -> Dict[str, float]:
        """Convenience function to get daily usage directly by UUID string."""
        uuid_id = self.get_uuid_id_by_uuid(uuid_str)
        if uuid_id:
            return self.get_usage_since_midnight(uuid_id)
        return {'hiddify': 0.0, 'marzban': 0.0}


    def add_or_update_scheduled_message(self, job_type: str, chat_id: int, message_id: int):
        with self._conn() as c:
            c.execute(
                "INSERT INTO scheduled_messages(job_type, chat_id, message_id) VALUES(?,?,?) "
                "ON CONFLICT(job_type, chat_id) DO UPDATE SET message_id=excluded.message_id, created_at=CURRENT_TIMESTAMP",
                (job_type, chat_id, message_id)
            )

    def get_scheduled_messages(self, job_type: str) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM scheduled_messages WHERE job_type=?", (job_type,)).fetchall()
            return [dict(r) for r in rows]

    def delete_scheduled_message(self, job_id: int):
        with self._conn() as c:
            c.execute("DELETE FROM scheduled_messages WHERE id=?", (job_id,))
            
    def user(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            return dict(row) if row else None

    def add_or_update_user(self, user_id: int, username: Optional[str], first: Optional[str], last: Optional[str]) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO users(user_id, username, first_name, last_name) VALUES(?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, last_name=excluded.last_name",
                (user_id, username, first, last),
            )

    def get_user_settings(self, user_id: int) -> Dict[str, bool]:
        with self._conn() as c:
            row = c.execute("SELECT daily_reports, expiry_warnings, data_warning_hiddify, data_warning_marzban, show_info_config FROM users WHERE user_id=?", (user_id,)).fetchone()
            if row:
                return {
                    'daily_reports': bool(row['daily_reports']), 
                    'expiry_warnings': bool(row['expiry_warnings']),
                    'data_warning_hiddify': bool(row['data_warning_hiddify']),
                    'data_warning_marzban': bool(row['data_warning_marzban']),
                    'show_info_config': bool(row['show_info_config'])
                }
            return {
                'daily_reports': True, 'expiry_warnings': True, 
                'data_warning_hiddify': True, 'data_warning_marzban': True,
                'show_info_config': True
            }

    def update_user_setting(self, user_id: int, setting: str, value: bool) -> None:
            if setting not in ['daily_reports', 'expiry_warnings', 'data_warning_hiddify', 'data_warning_marzban', 'show_info_config']: return
            with self._conn() as c:
                c.execute(f"UPDATE users SET {setting}=? WHERE user_id=?", (int(value), user_id))

    def add_uuid(self, user_id: int, uuid_str: str, name: str) -> str:
        uuid_str = uuid_str.lower()
        with self._conn() as c:
            existing = c.execute("SELECT * FROM user_uuids WHERE uuid = ?", (uuid_str,)).fetchone()
            if existing:
                if existing['is_active']:
                    if existing['user_id'] == user_id:
                        return "db_err_uuid_already_active_self"
                    else:
                        return "db_err_uuid_already_active_other"
                else:
                    if existing['user_id'] == user_id:
                        c.execute("UPDATE user_uuids SET is_active = 1, name = ?, updated_at = CURRENT_TIMESTAMP WHERE uuid = ?", (name, uuid_str))
                        return "db_msg_uuid_reactivated"
                    else:
                        return "db_err_uuid_inactive_other"
            else:
                c.execute(
                    "INSERT INTO user_uuids (user_id, uuid, name) VALUES (?, ?, ?)",
                    (user_id, uuid_str, name)
                )
                return "db_msg_uuid_added"

    def uuids(self, user_id: int) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM user_uuids WHERE user_id=? AND is_active=1 ORDER BY created_at", (user_id,)).fetchall()
            return [dict(r) for r in rows]

    def uuid_by_id(self, user_id: int, uuid_id: int) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM user_uuids WHERE user_id=? AND id=? AND is_active=1", (user_id, uuid_id)).fetchone()
            return dict(row) if row else None

    def deactivate_uuid(self, uuid_id: int) -> bool:
        with self._conn() as c:
            res = c.execute("UPDATE user_uuids SET is_active = 0 WHERE id = ?", (uuid_id,))
            return res.rowcount > 0

    def delete_user_by_uuid(self, uuid: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM user_uuids WHERE uuid=?", (uuid,))

    def all_active_uuids(self) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT id, user_id, uuid, created_at FROM user_uuids WHERE is_active=1").fetchall()
            return [dict(r) for r in rows]
            
    def get_all_user_ids(self) -> list[int]:
        with self._conn() as c:
            return [r['user_id'] for r in c.execute("SELECT user_id FROM users")]
        
    def get_all_bot_users(self) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT user_id, username, first_name, last_name FROM users ORDER BY user_id").fetchall()
            return [dict(r) for r in rows]
        
    def update_user_birthday(self, user_id: int, birthday_date: datetime.date):
        with self._conn() as c:
            c.execute("UPDATE users SET birthday = ? WHERE user_id = ?", (birthday_date, user_id))

    def get_users_with_birthdays(self) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT user_id, first_name, username, birthday FROM users
                WHERE birthday IS NOT NULL
                ORDER BY strftime('%m-%d', birthday)
            """).fetchall()
            return [dict(r) for r in rows]
        
    def get_user_id_by_uuid(self, uuid: str) -> Optional[int]:
        with self._conn() as c:
            row = c.execute("SELECT user_id FROM user_uuids WHERE uuid = ?", (uuid,)).fetchone()
            return row['user_id'] if row else None

    def reset_user_birthday(self, user_id: int) -> None:
        with self._conn() as c:
            c.execute("UPDATE users SET birthday = NULL WHERE user_id = ?", (user_id,))

    def delete_user_snapshots(self, uuid_id: int) -> int:
        with self._conn() as c:
            cursor = c.execute("DELETE FROM usage_snapshots WHERE uuid_id = ?", (uuid_id,))
            return cursor.rowcount
    
    def get_todays_birthdays(self) -> list:
        today = datetime.now(pytz.utc)
        today_month_day = f"{today.month:02d}-{today.day:02d}"
        with self._conn() as c:
            rows = c.execute(
                "SELECT user_id FROM users WHERE strftime('%m-%d', birthday) = ?",
                (today_month_day,)
            ).fetchall()
            return [row['user_id'] for row in rows]

    def vacuum_db(self) -> None:
        with self._conn() as c:
            c.execute("VACUUM")

    def get_bot_user_by_uuid(self, uuid: str) -> Optional[Dict[str, Any]]:
        query = """
            SELECT u.user_id, u.first_name, u.username
            FROM users u
            JOIN user_uuids uu ON u.user_id = uu.user_id
            WHERE uu.uuid = ?
        """
        with self._conn() as c:
            row = c.execute(query, (uuid,)).fetchone()
            return dict(row) if row else None

    def get_uuid_to_user_id_map(self) -> Dict[str, int]:
        with self._conn() as c:
            rows = c.execute("SELECT uuid, user_id FROM user_uuids WHERE is_active=1").fetchall()
            return {row['uuid']: row['user_id'] for row in rows}
        
    def get_uuid_to_bot_user_map(self) -> Dict[str, Dict[str, Any]]:
        query = """
            SELECT uu.uuid, u.user_id, u.first_name, u.username
            FROM user_uuids uu
            LEFT JOIN users u ON uu.user_id = u.user_id
            WHERE uu.is_active = 1
        """
        result_map = {}
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            for row in rows:
                if row['uuid'] not in result_map:
                    result_map[row['uuid']] = dict(row)
        return result_map
    
    def delete_daily_snapshots(self, uuid_id: int) -> None:
        """Deletes all usage snapshots for a given uuid_id that were taken today (UTC)."""
        today_start_utc = datetime.now(pytz.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        with self._conn() as c:
            c.execute("DELETE FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ?", (uuid_id, today_start_utc))
            logger.info(f"Deleted daily snapshots for uuid_id {uuid_id}.")

    def set_first_connection_time(self, uuid_id: int, time: datetime):
        with self._conn() as c:
            c.execute("UPDATE user_uuids SET first_connection_time = ? WHERE id = ?", (time, uuid_id))

    def mark_welcome_message_as_sent(self, uuid_id: int):
        with self._conn() as c:
            c.execute("UPDATE user_uuids SET welcome_message_sent = 1 WHERE id = ?", (uuid_id,))

    def add_payment_record(self, uuid_id: int) -> bool:
        """یک رکورد پرداخت برای کاربر با تاریخ فعلی ثبت می‌کند."""
        with self._conn() as c:
            c.execute("INSERT INTO payments (uuid_id, payment_date) VALUES (?, ?)",
                      (uuid_id, datetime.now(pytz.utc)))
            return True

    def get_payment_counts(self) -> Dict[str, int]:
            """تعداد کل پرداختی‌ها را به ازای هر نام کاربری برمی‌گرداند."""
            query = """
                SELECT uu.name, COUNT(p.payment_id) as payment_count
                FROM user_uuids uu
                LEFT JOIN payments p ON uu.id = p.uuid_id
                WHERE uu.is_active = 1
                GROUP BY uu.name
            """
            with self._conn() as c:
                results = c.execute(query).fetchall()
                return {row['name']: row['payment_count'] for row in results if row['name']}

    def get_payment_history(self) -> List[Dict[str, Any]]:
        """لیست آخرین پرداخت ثبت‌شده برای تمام کاربران فعال را برمی‌گرداند."""
        query = """
            SELECT
                uu.name,
                p.payment_date
            FROM payments p
            JOIN user_uuids uu ON p.uuid_id = uu.id
            WHERE p.payment_date = (
                SELECT MAX(sub_p.payment_date)
                FROM payments sub_p
                WHERE sub_p.uuid_id = p.uuid_id
            ) AND uu.is_active = 1
            ORDER BY p.payment_date DESC;
        """
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]
        
    def get_user_payment_history(self, uuid_id: int) -> List[Dict[str, Any]]:
            """تمام رکوردهای پرداخت برای یک کاربر خاص را برمی‌گرداند."""
            with self._conn() as c:
                rows = c.execute("SELECT payment_date FROM payments WHERE uuid_id = ? ORDER BY payment_date DESC", (uuid_id,)).fetchall()
                return [dict(r) for r in rows]

    def get_all_payments_with_user_info(self) -> List[Dict[str, Any]]:
        """
        لیست تمام رکوردهای پرداخت را به همراه اطلاعات کاربر مربوطه
        (شامل دسترسی به پنل‌ها برای تشخیص صحیح) برمی‌گرداند.
        """
        query = """
            SELECT
                p.payment_id,
                p.payment_date,
                uu.name AS config_name,
                uu.uuid,
                u.user_id,
                u.first_name,
                u.username,
                uu.has_access_de,
                uu.has_access_fr
            FROM payments p
            JOIN user_uuids uu ON p.uuid_id = uu.id
            LEFT JOIN users u ON uu.user_id = u.user_id
            ORDER BY p.payment_date DESC;
        """
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]

    def update_user_note(self, user_id: int, note: Optional[str]) -> None:
        """Updates or removes the admin note for a given user."""
        with self._conn() as c:
            c.execute("UPDATE users SET admin_note = ? WHERE user_id = ?", (note, user_id))

    def add_batch_templates(self, templates: list[str]) -> int:
        """
        لیستی از رشته‌های الگو را به صورت دسته‌ای به دیتابیس اضافه می‌کند.
        تمام ورودی‌ها، حتی تکراری، اضافه خواهند شد.
        تعداد ردیف‌های اضافه شده را برمی‌گرداند.
        """
        if not templates:
            return 0
        
        with self._conn() as c:
            cursor = c.cursor()
            # استفاده از INSERT ساده برای افزودن تمام موارد
            cursor.executemany(
                "INSERT INTO config_templates (template_str) VALUES (?)",
                [(tpl,) for tpl in templates]
            )
            return cursor.rowcount
        
    def update_template(self, template_id: int, new_template_str: str):
        """محتوای یک قالب کانفیگ مشخص را در دیتابیس به‌روزرسانی می‌کند."""
        # در اینجا مشکل برطرف شده و از متد صحیح _conn() استفاده می‌شود
        sql = "UPDATE config_templates SET template_str = ? WHERE id = ?"
        try:
            with self._conn() as conn: # <-- مشکل اینجا بود و تصحیح شد
                cursor = conn.cursor()
                cursor.execute(sql, (new_template_str, template_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Database error in update_template for id={template_id}: {e}")
            raise

    def get_all_config_templates(self) -> list[dict]:
        """تمام الگوهای کانفیگ تعریف شده توسط ادمین را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM config_templates ORDER BY id DESC").fetchall()
            return [dict(r) for r in rows]

    def get_active_config_templates(self) -> list[dict]:
        """فقط الگوهای کانفیگ فعال را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM config_templates WHERE is_active = 1").fetchall()
            return [dict(r) for r in rows]

    def toggle_template_status(self, template_id: int) -> None:
        """وضعیت فعال/غیرفعال یک الگو را تغییر می‌دهد."""
        with self._conn() as c:
            c.execute("UPDATE config_templates SET is_active = 1 - is_active WHERE id = ?", (template_id,))

    def delete_template(self, template_id: int) -> None:
        """یک الگو و تمام کانفیگ‌های تولید شده از آن را حذف می‌کند."""
        with self._conn() as c:
            c.execute("DELETE FROM config_templates WHERE id = ?", (template_id,))

    def get_user_config(self, user_uuid_id: int, template_id: int) -> dict | None:
        """کانفیگ تولید شده برای یک کاربر و یک الگوی خاص را بازیابی می‌کند."""
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM user_generated_configs WHERE user_uuid_id = ? AND template_id = ?",
                (user_uuid_id, template_id)
            ).fetchone()
            return dict(row) if row else None

    def add_user_config(self, user_uuid_id: int, template_id: int, generated_uuid: str) -> None:
        """یک رکورد جدید برای UUID تولید شده ثبت می‌کند."""
        with self._conn() as c:
            c.execute(
                "INSERT INTO user_generated_configs (user_uuid_id, template_id, generated_uuid) VALUES (?, ?, ?)",
                (user_uuid_id, template_id, generated_uuid)
            )

    def get_user_uuid_record(self, uuid_str: str) -> dict | None:
        """اطلاعات کامل یک رکورد UUID را بر اساس رشته آن برمی‌گرداند."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM user_uuids WHERE uuid = ? AND is_active = 1", (uuid_str,)).fetchone()
            return dict(row) if row else None
        
    def get_all_user_uuids(self) -> List[Dict[str, Any]]:
        """
        تمام رکوردهای UUID را از دیتابیس برمی‌گرداند.
        این تابع برای پنل ادمین جهت نمایش همه کاربران استفاده می‌شود.
        """
        with self._conn() as c:
            # ✅ **تغییر اصلی:** ستون‌های is_vip, has_access_de, has_access_fr به کوئری اضافه شدند
            query = """
                SELECT id, user_id, uuid, name, is_active, created_at, is_vip, has_access_de, has_access_fr, has_access_tr
                FROM user_uuids
                ORDER BY created_at DESC
            """
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]
        
    def check_connection(self) -> bool:
        """بررسی می‌کند که آیا اتصال به دیتابیس برقرار است یا نه."""
        try:
            with self._conn() as c:
                c.execute("SELECT 1")
            logger.info("Database connection check successful.")
            return True
        except Exception as e:
            logger.error(f"Database connection check FAILED: {e}")
            return False

    def get_all_daily_usage_since_midnight(self) -> Dict[str, Dict[str, float]]:
        """
        مصرف روزانه تمام UUID ها را از نیمه‌شب به صورت یک‌جا و با در نظر گرفتن ریست شدن حجم محاسبه می‌کند.
        """
        tehran_tz = pytz.timezone("Asia/Tehran")
        today_midnight_tehran = datetime.now(tehran_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        today_midnight_utc = today_midnight_tehran.astimezone(pytz.utc)

        query = """
            SELECT
                uu.uuid,
                MIN(s.hiddify_usage_gb) as h_min,
                MAX(s.hiddify_usage_gb) as h_max,
                MIN(s.marzban_usage_gb) as m_min,
                MAX(s.marzban_usage_gb) as m_max
            FROM usage_snapshots s
            JOIN user_uuids uu ON s.uuid_id = uu.id
            WHERE s.taken_at >= ?
            GROUP BY uu.uuid;
        """

        usage_map = {}
        with self._conn() as c:
            rows = c.execute(query, (today_midnight_utc,)).fetchall()
            for row in rows:
                h_min = row['h_min'] if row['h_min'] is not None else 0.0
                h_max = row['h_max'] if row['h_max'] is not None else 0.0
                m_min = row['m_min'] if row['m_min'] is not None else 0.0
                m_max = row['m_max'] if row['m_max'] is not None else 0.0

                # اگر ماکسیمم کمتر از مینیمم باشد یعنی حجم ریست شده است
                h_diff = h_max if h_max < h_min else h_max - h_min
                m_diff = m_max if m_max < m_min else m_max - m_min

                usage_map[row['uuid']] = {
                    'hiddify': max(0, h_diff),
                    'marzban': max(0, m_diff)
                }
        return usage_map


    def get_daily_usage_summary(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Calculates the total daily usage (sum of Hiddify and Marzban) for a specified number of days, handling usage resets.
        This function is designed for use in the admin dashboard usage chart.
        Output: A list of dictionaries, each containing 'date' and 'total_gb'.
        """
        logger.info(f"Calculating daily usage summary for the last {days} days.")
        tehran_tz = pytz.timezone("Asia/Tehran")
        summary = []

        query = """
            SELECT
                SUM(CASE
                    WHEN h_max < h_min THEN h_max
                    ELSE h_max - h_min
                END) as total_h,
                SUM(CASE
                    WHEN m_max < m_min THEN m_max
                    ELSE m_max - m_min
                END) as total_m
            FROM (
                SELECT
                    uuid_id,
                    MAX(hiddify_usage_gb) as h_max,
                    MIN(hiddify_usage_gb) as h_min,
                    MAX(marzban_usage_gb) as m_max,
                    MIN(marzban_usage_gb) as m_min
                FROM usage_snapshots
                WHERE taken_at >= ? AND taken_at < ?
                GROUP BY uuid_id
            )
        """

        with self._conn() as c:
            # --- START OF FIX ---
            # ابتدا نیمه‌شب امروز را به عنوان مبنا در نظر می‌گیریم
            today_start_tehran = datetime.now(tehran_tz).replace(hour=0, minute=0, second=0, microsecond=0)

            # حلقه را برعکس اجرا می‌کنیم تا تاریخ‌ها برای نمودار به ترتیب صعودی باشند
            for i in range(days - 1, -1, -1):
                # شروع و پایان روز مورد نظر را با کم کردن روز از مبنا محاسبه می‌کنیم
                day_start_tehran = today_start_tehran - timedelta(days=i)
                day_end_tehran = day_start_tehran + timedelta(days=1)
            # --- END OF FIX ---
                
                day_start_utc = day_start_tehran.astimezone(pytz.utc)
                day_end_utc = day_end_tehran.astimezone(pytz.utc)

                row = c.execute(query, (day_start_utc, day_end_utc)).fetchone()
                
                total_gb = 0
                if row and (row['total_h'] is not None or row['total_m'] is not None):
                    total_gb = (row['total_h'] or 0) + (row['total_m'] or 0)

                summary.append({
                    'date': day_start_tehran.strftime('%Y-%m-%d'),
                    'total_gb': round(total_gb, 2)
                })

        return summary

    def update_config_name(self, uuid_id: int, new_name: str) -> bool:
        """نام نمایشی یک کانفیگ (UUID) را در دیتابیس تغییر می‌دهد."""
        if not new_name or len(new_name) < 2:
            # جلوگیری از ثبت نام‌های خالی یا بسیار کوتاه
            return False
        
        with self._conn() as c:
            cursor = c.execute(
                "UPDATE user_uuids SET name = ? WHERE id = ?",
                (new_name, uuid_id)
            )
            return cursor.rowcount > 0

    def get_daily_payment_stats(self, days: int = 30) -> List[Dict[str, Any]]:
        """آمار تعداد پرداخت‌های روزانه را برای نمودار باز می‌گرداند."""
        date_limit = datetime.now(pytz.utc) - timedelta(days=days)
        query = """
            SELECT
                DATE(payment_date) as date,
                COUNT(payment_id) as count
            FROM payments
            WHERE payment_date >= ?
            GROUP BY date
            ORDER BY date ASC;
        """
        with self._conn() as c:
            rows = c.execute(query, (date_limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_new_users_per_month_stats(self, months: int = 6) -> List[Dict[str, Any]]:
        """آمار کاربران جدید در هر ماه را برای نمودار باز می‌گرداند."""
        # This query might need adjustment based on the exact database dialect for date functions
        query = f"""
            SELECT
                strftime('%Y-%m', created_at) as month,
                COUNT(id) as count
            FROM user_uuids
            GROUP BY month
            ORDER BY month DESC
            LIMIT {months};
        """
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            # Reverse the result to have it in ascending order for the chart
            return [dict(r) for r in reversed(rows)]
        
    def get_revenue_by_month(self, months: int = 6) -> List[Dict[str, Any]]:
        """درآمد ماهانه را برای نمودار MRR محاسبه می‌کند."""
        # نکته: فرض شده هر پرداخت معادل یک واحد درآمد است.
        # برای محاسبه واقعی، باید یک ستون قیمت به جدول payments اضافه شود.
        query = f"""
            SELECT
                strftime('%Y-%m', payment_date) as month,
                COUNT(payment_id) as revenue_unit
            FROM payments
            GROUP BY month
            ORDER BY month DESC
            LIMIT {months};
        """
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            return [dict(r) for r in reversed(rows)]

    def get_daily_active_users_count(self, days: int = 30) -> List[Dict[str, Any]]:
        """تعداد کاربران فعال یکتا در هر روز را بر اساس اسنپ‌شات‌های مصرف محاسبه می‌کند."""
        date_limit = datetime.now(pytz.utc) - timedelta(days=days)
        query = """
            SELECT
                DATE(taken_at) as date,
                COUNT(DISTINCT uuid_id) as active_users
            FROM usage_snapshots
            WHERE taken_at >= ?
            GROUP BY date
            ORDER BY date ASC;
        """
        with self._conn() as c:
            rows = c.execute(query, (date_limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_top_consumers_by_usage(self, days: int = 30, limit: int = 10) -> List[Dict[str, Any]]:
        """لیست پرمصرف‌ترین کاربران را در یک بازه زمانی برمی‌گرداند."""
        date_limit = datetime.now(pytz.utc) - timedelta(days=days)
        query = f"""
            SELECT
                uu.name,
                MAX(s.hiddify_usage_gb) - MIN(s.hiddify_usage_gb) as h_usage,
                MAX(s.marzban_usage_gb) - MIN(s.marzban_usage_gb) as m_usage
            FROM usage_snapshots s
            JOIN user_uuids uu ON s.uuid_id = uu.id
            WHERE s.taken_at >= ?
            GROUP BY uu.name
            ORDER BY (h_usage + m_usage) DESC
            LIMIT {limit};
        """
        with self._conn() as c:
            rows = c.execute(query, (date_limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_total_payments_in_range(self, start_date: datetime, end_date: datetime) -> int:
        """تعداد کل پرداخت‌ها در یک بازه زمانی مشخص را برمی‌گرداند."""
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(payment_id) as count FROM payments WHERE payment_date >= ? AND payment_date < ?",
                (start_date, end_date)
            ).fetchone()
            return row['count'] if row else 0

    def get_new_users_in_range(self, start_date: datetime, end_date: datetime) -> int:
        """تعداد کاربران جدید در یک بازه زمانی را برمی‌گرداند."""
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(id) as count FROM user_uuids WHERE created_at >= ? AND created_at < ?",
                (start_date, end_date)
            ).fetchone()
            return row['count'] if row else 0
        
    def get_daily_usage_per_panel(self, days: int = 30) -> list[dict[str, Any]]:
        """
        مصرف روزانه تفکیک شده برای هر پنل را جهت استفاده در نمودار جدید برمی‌گرداند.
        """
        tehran_tz = pytz.timezone("Asia/Tehran")
        summary = []
        
        # تاریخ‌ها را از امروز به گذشته محاسبه می‌کنیم
        for i in range(days - 1, -1, -1):
            target_date = datetime.now(tehran_tz).date() - timedelta(days=i)
            day_start_utc = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tehran_tz).astimezone(pytz.utc)
            day_end_utc = day_start_utc + timedelta(days=1)
            
            query = """
                SELECT
                    SUM(COALESCE(h_diff, 0)) as total_h,
                    SUM(COALESCE(m_diff, 0)) as total_m
                FROM (
                    SELECT
                        MAX(hiddify_usage_gb) - MIN(hiddify_usage_gb) as h_diff,
                        MAX(marzban_usage_gb) - MIN(marzban_usage_gb) as m_diff
                    FROM usage_snapshots
                    WHERE taken_at >= ? AND taken_at < ?
                    GROUP BY uuid_id
                )
            """
            with self._conn() as c:
                row = c.execute(query, (day_start_utc, day_end_utc)).fetchone()
                summary.append({
                    'date': target_date.strftime('%Y-%m-%d'),
                    'total_h_gb': round(row['total_h'] if row and row['total_h'] else 0, 2),
                    'total_m_gb': round(row['total_m'] if row and row['total_m'] else 0, 2)
                })
        return summary

    def get_activity_heatmap_data(self) -> List[Dict[str, Any]]:
        """
        داده‌های مورد نیاز برای نقشه حرارتی مصرف را بر اساس روز هفته و ساعت برمی‌گرداند.
        روز هفته در پایتون: 0=دوشنبه, 6=یکشنبه. ما آن را برای نمایش تنظیم می‌کنیم.
        """
        # فقط داده‌های ۷ روز گذشته برای بهینه‌سازی
        time_limit = datetime.now(pytz.utc) - timedelta(days=7)
        query = """
            SELECT
                strftime('%w', taken_at) as day_of_week, -- 0=Sunday, 1=Monday ... 6=Saturday
                strftime('%H', taken_at) as hour_of_day,
                SUM(hiddify_usage_gb) + SUM(marzban_usage_gb) as total_usage
            FROM usage_snapshots
            WHERE taken_at >= ?
            GROUP BY day_of_week, hour_of_day
        """
        with self._conn() as c:
            rows = c.execute(query, (time_limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_daily_active_users_by_panel(self, days: int = 30) -> List[Dict[str, Any]]:
        """تعداد کاربران فعال یکتا در هر پنل را به صورت روزانه برمی‌گرداند."""
        date_limit = datetime.now(pytz.utc) - timedelta(days=days)
        query = """
            SELECT
                DATE(taken_at) as date,
                COUNT(DISTINCT CASE WHEN hiddify_usage_gb > 0 THEN uuid_id END) as hiddify_users,
                COUNT(DISTINCT CASE WHEN marzban_usage_gb > 0 THEN uuid_id END) as marzban_users
            FROM usage_snapshots
            WHERE taken_at >= ?
            GROUP BY date
            ORDER BY date ASC;
        """
        with self._conn() as c:
            rows = c.execute(query, (date_limit,)).fetchall()
            return [dict(r) for r in rows]
        
    def toggle_user_vip(self, uuid: str) -> None:
        """وضعیت VIP یک کاربر را بر اساس UUID تغییر می‌دهد."""
        with self._conn() as c:
            c.execute("UPDATE user_uuids SET is_vip = 1 - is_vip WHERE uuid = ?", (uuid,))

    def toggle_template_special(self, template_id: int) -> None:
        """وضعیت "ویژه" بودن یک قالب کانفیگ را تغییر می‌دهد."""
        with self._conn() as c:
            c.execute("UPDATE config_templates SET is_special = 1 - is_special WHERE id = ?", (template_id,))

    def set_template_server_type(self, template_id: int, server_type: str) -> None:
        """نوع سرور یک قالب کانفیگ را تنظیم می‌کند."""
        if server_type not in ['de', 'fr', 'tr', 'none']:
            return
        with self._conn() as c:
            c.execute("UPDATE config_templates SET server_type = ? WHERE id = ?", (server_type, template_id))

    def reset_templates_table(self) -> None:
        """تمام رکوردها را از جدول config_templates حذف کرده و شمارنده ID را ریست می‌کند."""
        with self._conn() as c:
            c.execute("DELETE FROM config_templates;")
            # این دستور شمارنده auto-increment را برای جدول ریست می‌کند
            c.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'config_templates';")
        logger.info("Config templates table has been reset.")

    def set_user_language(self, user_id: int, lang_code: str):
        """زبان انتخابی کاربر را در دیتابیس ذخیره می‌کند."""
        with self._conn() as c:
            c.execute("UPDATE users SET lang_code = ? WHERE user_id = ?", (lang_code, user_id))

    def get_user_language(self, user_id: int) -> str:
        """کد زبان کاربر را از دیتابیس می‌خواند."""
        with self._conn() as c:
            row = c.execute("SELECT lang_code FROM users WHERE user_id = ?", (user_id,)).fetchone()
            # اگر زبانی ثبت نشده بود، فارسی را به عنوان پیش‌فرض برمی‌گرداند
            return row['lang_code'] if row and row['lang_code'] else 'fa'

    def add_marzban_mapping(self, hiddify_uuid: str, marzban_username: str) -> bool:
        """یک ارتباط جدید بین UUID هیدیفای و یوزرنیم مرزبان اضافه یا جایگزین می‌کند."""
        with self._conn() as c:
            try:
                c.execute("INSERT OR REPLACE INTO marzban_mapping (hiddify_uuid, marzban_username) VALUES (?, ?)", (hiddify_uuid.lower(), marzban_username))
                return True
            except sqlite3.IntegrityError:
                logger.warning(f"Marzban username '{marzban_username}' might already be mapped.")
                return False

    def get_marzban_username_by_uuid(self, hiddify_uuid: str) -> Optional[str]:
        """یوزرنیم مرزبان را بر اساس UUID هیدیفای از دیتابیس دریافت می‌کند."""
        with self._conn() as c:
            row = c.execute("SELECT marzban_username FROM marzban_mapping WHERE hiddify_uuid = ?", (hiddify_uuid.lower(),)).fetchone()
            return row['marzban_username'] if row else None

    def get_uuid_by_marzban_username(self, marzban_username: str) -> Optional[str]:
        """UUID هیدیفای را بر اساس یوزرنیم مرزبان از دیتابیس دریافت می‌کند."""
        with self._conn() as c:
            row = c.execute("SELECT hiddify_uuid FROM marzban_mapping WHERE marzban_username = ?", (marzban_username,)).fetchone()
            return row['hiddify_uuid'] if row else None
            
    def get_all_marzban_mappings(self) -> List[Dict[str, str]]:
        """تمام ارتباط‌های مرزبان را برای نمایش در پنل وب برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute("SELECT hiddify_uuid, marzban_username FROM marzban_mapping ORDER BY marzban_username").fetchall()
            return [dict(r) for r in rows]

    def delete_marzban_mapping(self, hiddify_uuid: str) -> bool:
        """یک ارتباط را بر اساس UUID هیدیفای حذف می‌کند."""
        with self._conn() as c:
            res = c.execute("DELETE FROM marzban_mapping WHERE hiddify_uuid = ?", (hiddify_uuid.lower(),))
            return res.rowcount > 0
        
    def purge_user_by_telegram_id(self, user_id: int) -> bool:
        """
        یک کاربر را به طور کامل از جدول users بر اساس شناسه تلگرام حذف می‌کند.
        به دلیل وجود ON DELETE CASCADE، تمام رکوردهای مرتبط نیز حذف خواهند شد.
        """
        with self._conn() as c:
            cursor = c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            return cursor.rowcount > 0

    def get_user_daily_usage_history(self, uuid_id: int, days: int = 7) -> list:
        """تاریخچه مصرف روزانه یک کاربر را برای تعداد روز مشخص شده برمی‌گرداند."""
        tehran_tz = pytz.timezone("Asia/Tehran")
        history = []
        with self._conn() as c:
            for i in range(days):
                target_date = datetime.now(tehran_tz).date() - timedelta(days=i)
                day_start_utc = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tehran_tz).astimezone(pytz.utc)
                day_end_utc = day_start_utc + timedelta(days=1)
                
                query = """
                    SELECT
                        (MAX(hiddify_usage_gb) - MIN(hiddify_usage_gb)) as h_usage,
                        (MAX(marzban_usage_gb) - MIN(marzban_usage_gb)) as m_usage
                    FROM usage_snapshots
                    WHERE uuid_id = ? AND taken_at >= ? AND taken_at < ?
                """
                row = c.execute(query, (uuid_id, day_start_utc, day_end_utc)).fetchone()
                
                h_usage = max(0, row['h_usage'] if row and row['h_usage'] else 0)
                m_usage = max(0, row['m_usage'] if row and row['m_usage'] else 0)
                
                history.append({
                    "date": target_date,
                    "total_usage": h_usage + m_usage
                })
        return history

    def create_login_token(self, user_uuid: str) -> str:
        """یک توکن یکبار مصرف برای ورود به پنل وب ایجاد می‌کند."""
        token = secrets.token_urlsafe(32)
        with self._conn() as c:
            c.execute("INSERT INTO login_tokens (token, uuid) VALUES (?, ?)", (token, user_uuid))
        return token

    def validate_login_token(self, token: str) -> Optional[str]:
        """یک توکن را اعتبارسنجی کرده و در صورت اعتبار، UUID کاربر را برمی‌گرداند."""
        five_minutes_ago = datetime.now(pytz.utc) - timedelta(minutes=5)
        with self._conn() as c:
            # ابتدا توکن‌های منقضی شده را حذف می‌کنیم
            c.execute("DELETE FROM login_tokens WHERE created_at < ?", (five_minutes_ago,))
            
            # سپس توکن معتبر را پیدا می‌کنیم
            row = c.execute("SELECT uuid FROM login_tokens WHERE token = ?", (token,)).fetchone()
            if row:
                # توکن پس از یکبار استفاده باید حذف شود
                c.execute("DELETE FROM login_tokens WHERE token = ?", (token,))
                return row['uuid']
        return None

    def delete_old_snapshots(self, days_to_keep: int = 3) -> int:
        """Deletes usage snapshots older than a specified number of days."""
        time_limit = datetime.now(pytz.utc) - timedelta(days=days_to_keep)
        with self._conn() as c:
            cursor = c.execute("DELETE FROM usage_snapshots WHERE taken_at < ?", (time_limit,))
            logger.info(f"Cleaned up {cursor.rowcount} old usage snapshots (older than {days_to_keep} days).")
            return cursor.rowcount

    def add_panel(self, name: str, panel_type: str, api_url: str, token1: str, token2: Optional[str] = None) -> bool:
        """Adds a new panel to the database."""
        with self._conn() as c:
            try:
                c.execute(
                    "INSERT INTO panels (name, panel_type, api_url, api_token1, api_token2) VALUES (?, ?, ?, ?, ?)",
                    (name, panel_type, api_url, token1, token2)
                )
                return True
            except sqlite3.IntegrityError:
                logger.warning(f"Attempted to add a panel with a duplicate name: {name}")
                return False

    def get_all_panels(self) -> List[Dict[str, Any]]:
        """Retrieves all configured panels from the database."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM panels ORDER BY name ASC").fetchall()
            return [dict(r) for r in rows]

    def get_active_panels(self) -> List[Dict[str, Any]]:
        """Retrieves only the active panels from the database."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM panels WHERE is_active = 1 ORDER BY name ASC").fetchall()
            return [dict(r) for r in rows]

    def delete_panel(self, panel_id: int) -> bool:
        """Deletes a panel by its ID."""
        with self._conn() as c:
            cursor = c.execute("DELETE FROM panels WHERE id = ?", (panel_id,))
            return cursor.rowcount > 0

    def toggle_panel_status(self, panel_id: int) -> bool:
        """Toggles the active status of a panel."""
        with self._conn() as c:
            cursor = c.execute("UPDATE panels SET is_active = 1 - is_active WHERE id = ?", (panel_id,))
            return cursor.rowcount > 0

    def get_panel_by_id(self, panel_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a single panel's details by its ID."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM panels WHERE id = ?", (panel_id,)).fetchone()
            return dict(row) if row else None

    def update_panel_name(self, panel_id: int, new_name: str) -> bool:
        """Updates the name of a specific panel."""
        with self._conn() as c:
            try:
                cursor = c.execute("UPDATE panels SET name = ? WHERE id = ?", (new_name, panel_id))
                return cursor.rowcount > 0
            except sqlite3.IntegrityError: # In case new name is a duplicate
                logger.warning(f"Attempted to rename panel {panel_id} to an existing name: {new_name}")
                return False

    def get_all_bot_users_with_uuids(self) -> List[Dict[str, Any]]:
        query = """
            SELECT
                u.user_id,
                u.first_name,
                u.username,
                uu.id as uuid_id,
                uu.name as config_name,
                uu.uuid,
                uu.is_vip,
                uu.has_access_de,
                uu.has_access_fr,
                uu.has_access_tr,
                -- Check if a mapping exists for the user's UUID
                CASE WHEN mm.hiddify_uuid IS NOT NULL THEN 1 ELSE 0 END as is_on_marzban
            FROM users u
            JOIN user_uuids uu ON u.user_id = uu.user_id
            -- Use LEFT JOIN to include all users from user_uuids, even if they don't have a mapping
            LEFT JOIN marzban_mapping mm ON uu.uuid = mm.hiddify_uuid
            WHERE uu.is_active = 1
            ORDER BY u.user_id, uu.created_at;
        """
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]

    # تابع دوم برای آپدیت دسترسی
    def update_user_server_access(self, uuid_id: int, server: str, status: bool) -> bool:
        """Updates a user's access status for a specific server."""
        if server not in ['de', 'fr', 'tr']:
            return False
        
        column_name = f"has_access_{server}"
        
        with self._conn() as c:
            cursor = c.execute(
                f"UPDATE user_uuids SET {column_name} = ? WHERE id = ?",
                (int(status), uuid_id)
            )
            return cursor.rowcount > 0

    def get_panel_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single panel's details by its unique name."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM panels WHERE name = ?", (name,)).fetchone()
            return dict(row) if row else None

db = DatabaseManager()