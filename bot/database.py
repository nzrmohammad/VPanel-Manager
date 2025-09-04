import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import pytz
import jdatetime
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
        # START OF DEBUGGING CODE
        print("DEBUG: _init_db function has been called.")
        logger.critical("CRITICAL_DEBUG: _init_db function has been called.")
        # END OF DEBUGGING CODE
        with self._conn() as c:
            try:
                # START OF DEBUGGING CODE
                logger.critical("CRITICAL_DEBUG: Inside the 'try' block of _init_db.")
                # END OF DEBUGGING CODE
                def add_column_if_not_exists(table, column_name, column_definition):
                    cursor = c.execute(f"PRAGMA table_info({table});")
                    columns = [row['name'] for row in cursor.fetchall()]
                    
                    # START OF DEBUGGING CODE
                    logger.critical(f"CRITICAL_DEBUG: Columns found in table '{table}': {columns}")
                    # END OF DEBUGGING CODE

                    if column_name not in columns:
                        try:
                            # START OF DEBUGGING CODE
                            logger.critical(f"CRITICAL_DEBUG: Column '{column_name}' NOT FOUND. Attempting to add it now...")
                            # END OF DEBUGGING CODE
                            c.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_definition};")
                            # START OF DEBUGGING CODE
                            logger.critical(f"CRITICAL_DEBUG: SUCCESSFULLY ADDED column '{column_name}' to table '{table}'.")
                            # END OF DEBUGGING CODE
                        except sqlite3.OperationalError as e:
                            # START OF DEBUGGING CODE
                            logger.critical(f"CRITICAL_DEBUG: FAILED to add column '{column_name}'. Error: {e}")
                            # END OF DEBUGGING CODE
                            if "duplicate column name" in str(e):
                                logger.warning(f"Column '{column_name}' already exists in {table}. Ignoring.")
                            else:
                                raise e
                
                # ... (بقیه ستون‌ها)
                add_column_if_not_exists("users", "referral_code", "TEXT UNIQUE")
                add_column_if_not_exists("users", "referred_by_user_id", "INTEGER")
                add_column_if_not_exists("users", "referral_reward_applied", "INTEGER DEFAULT 0")
                # ... (بقیه ستون‌ها)

                logger.info("Database schema migration check complete.")

            except Exception as e:
                # START OF DEBUGGING CODE
                logger.critical(f"CRITICAL_DEBUG: An exception occurred in _init_db: {e}", exc_info=True)
                # END OF DEBUGGING CODE
                if "no such table" not in str(e):
                    logger.error(f"Failed to update database schema: {e}")

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
                    lang_code TEXT DEFAULT 'fa',
                    weekly_reports INTEGER DEFAULT 1,
                    auto_delete_reports INTEGER DEFAULT 0,
                    referral_code TEXT UNIQUE,
                    referred_by_user_id INTEGER,
                    referral_reward_applied INTEGER DEFAULT 0,
                    achievement_points INTEGER DEFAULT 0        
                );
                CREATE TABLE IF NOT EXISTS user_uuids (
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
                    has_access_de INTEGER DEFAULT 1,
                    has_access_fr INTEGER DEFAULT 0,
                    has_access_tr INTEGER DEFAULT 0,        
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    UNIQUE(user_id, uuid)
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
                    is_random_pool INTEGER DEFAULT 0,
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
               CREATE TABLE IF NOT EXISTS sent_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS client_user_agents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid_id INTEGER NOT NULL,
                    user_agent TEXT NOT NULL,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(uuid_id) REFERENCES user_uuids(id) ON DELETE CASCADE,
                    UNIQUE(uuid_id, user_agent)
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
                CREATE TABLE IF NOT EXISTS traffic_transfers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_uuid_id INTEGER NOT NULL,
                    receiver_uuid_id INTEGER NOT NULL,
                    panel_type TEXT NOT NULL,
                    amount_gb REAL NOT NULL,
                    transferred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(sender_uuid_id) REFERENCES user_uuids(id) ON DELETE CASCADE,
                    FOREIGN KEY(receiver_uuid_id) REFERENCES user_uuids(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS user_achievements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    badge_code TEXT NOT NULL, -- e.g., 'veteran', 'pro_consumer'
                    awarded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    UNIQUE(user_id, badge_code)
                );
                CREATE TABLE IF NOT EXISTS achievement_shop_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    item_key TEXT NOT NULL,
                    cost INTEGER NOT NULL,
                    purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_user_uuids_uuid ON user_uuids(uuid);
                CREATE INDEX IF NOT EXISTS idx_user_uuids_user_id ON user_uuids(user_id);
                CREATE INDEX IF NOT EXISTS idx_snapshots_taken_at ON usage_snapshots(taken_at);
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
        tehran_tz = pytz.timezone("Asia/Tehran")
        now_in_tehran = datetime.now(tehran_tz)
        today_midnight_tehran = now_in_tehran.replace(hour=0, minute=0, second=0, microsecond=0)
        today_midnight_utc = today_midnight_tehran.astimezone(pytz.utc)

        with self._conn() as c:
            today_snapshots = c.execute(
                "SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ? ORDER BY taken_at ASC",
                (uuid_id, today_midnight_utc)
            ).fetchall()

            if not today_snapshots:
                logger.info(f"DAILY_USAGE_V5 (uuid_id: {uuid_id}): No snapshots today. Usage is 0.")
                return {'hiddify': 0.0, 'marzban': 0.0}

            yesterday_last_snapshot = c.execute(
                "SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1",
                (uuid_id, today_midnight_utc)
            ).fetchone()

            if yesterday_last_snapshot:
                h_start = yesterday_last_snapshot['hiddify_usage_gb'] or 0.0
                m_start = yesterday_last_snapshot['marzban_usage_gb'] or 0.0
                logger.info(f"DAILY_USAGE_V5 (uuid_id: {uuid_id}): Baseline from yesterday -> H: {h_start:.3f}, M: {m_start:.3f}")
            else:
                h_start = today_snapshots[0]['hiddify_usage_gb'] or 0.0
                m_start = today_snapshots[0]['marzban_usage_gb'] or 0.0
                logger.info(f"DAILY_USAGE_V5 (uuid_id: {uuid_id}): No yesterday data. Using today's first snapshot as baseline -> H: {h_start:.3f}, M: {m_start:.3f}")

            h_end = today_snapshots[-1]['hiddify_usage_gb'] or 0.0
            m_end = today_snapshots[-1]['marzban_usage_gb'] or 0.0

            h_usage = h_end if h_end < h_start else h_end - h_start
            m_usage = m_end if m_end < m_start else m_end - m_start

            final_h_usage = max(0, h_usage)
            final_m_usage = max(0, m_usage)
            
        return {'hiddify': final_h_usage, 'marzban': final_m_usage}
    
    def get_weekly_usage_by_uuid(self, uuid_str: str) -> Dict[str, float]:
        """مصرف هفتگی کاربر را با محاسبه مجموع افزایش‌های مثبت مصرف برای مدیریت صحیح ریست شدن حجم محاسبه می‌کند."""
        uuid_id = self.get_uuid_id_by_uuid(uuid_str)
        if not uuid_id:
            return {'hiddify': 0.0, 'marzban': 0.0}

        tehran_tz = pytz.timezone("Asia/Tehran")
        now_in_tehran = datetime.now(tehran_tz)
        
        today_jalali = jdatetime.datetime.now(tz=tehran_tz)
        days_since_saturday = (today_jalali.weekday() + 1) % 7 # شنبه = 0
        week_start_tehran = (now_in_tehran - timedelta(days=days_since_saturday)).replace(hour=0, minute=0, second=0, microsecond=0)
        week_start_utc = week_start_tehran.astimezone(pytz.utc)

        with self._conn() as c:
            week_snapshots_query = """
                SELECT hiddify_usage_gb, marzban_usage_gb
                FROM usage_snapshots
                WHERE uuid_id = ? AND taken_at >= ?
                ORDER BY taken_at ASC;
            """
            week_rows = c.execute(week_snapshots_query, (uuid_id, week_start_utc)).fetchall()

            last_snapshot_before_week_query = """
                SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots
                WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1
            """
            last_week_row = c.execute(last_snapshot_before_week_query, (uuid_id, week_start_utc)).fetchone()

            last_h = last_week_row['hiddify_usage_gb'] if last_week_row else 0
            last_m = last_week_row['marzban_usage_gb'] if last_week_row else 0
            
            total_h = 0.0
            total_m = 0.0

            for row in week_rows:
                current_h = row['hiddify_usage_gb']
                current_m = row['marzban_usage_gb']

                if current_h is not None and last_h is not None:
                    h_diff = current_h - last_h
                    if h_diff > 0:
                        total_h += h_diff
                    last_h = current_h
                
                if current_m is not None and last_m is not None:
                    m_diff = current_m - last_m
                    if m_diff > 0:
                        total_m += m_diff
                    last_m = current_m
                    
            return {'hiddify': total_h, 'marzban': total_m}
    
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
            row = c.execute("SELECT daily_reports, weekly_reports, expiry_warnings, data_warning_hiddify, data_warning_marzban, show_info_config, auto_delete_reports FROM users WHERE user_id=?", (user_id,)).fetchone()
            if row:
                return {
                    'daily_reports': bool(row['daily_reports']), 
                    'weekly_reports': bool(row['weekly_reports']),
                    'expiry_warnings': bool(row['expiry_warnings']),
                    'data_warning_hiddify': bool(row['data_warning_hiddify']),
                    'data_warning_marzban': bool(row['data_warning_marzban']),
                    'show_info_config': bool(row['show_info_config']),
                    'auto_delete_reports': bool(row['auto_delete_reports'])
                }
            return {
                'daily_reports': True, 'weekly_reports': True, 'expiry_warnings': True, 
                'data_warning_hiddify': True, 'data_warning_marzban': True,
                'show_info_config': True, 'auto_delete_reports': True
            }

    def update_user_setting(self, user_id: int, setting: str, value: bool) -> None:
            if setting not in ['daily_reports', 'weekly_reports', 'expiry_warnings', 'data_warning_hiddify', 'data_warning_marzban', 'show_info_config', 'auto_delete_reports']: return
            with self._conn() as c:
                c.execute(f"UPDATE users SET {setting}=? WHERE user_id=?", (int(value), user_id))

    def add_uuid(self, user_id: int, uuid_str: str, name: str) -> any:
            uuid_str = uuid_str.lower()
            with self._conn() as c:
                # بررسی می‌کند آیا این کاربر قبلاً همین UUID را داشته و غیرفعال کرده
                existing_inactive_for_this_user = c.execute("SELECT * FROM user_uuids WHERE user_id = ? AND uuid = ? AND is_active = 0", (user_id, uuid_str)).fetchone()
                if existing_inactive_for_this_user:
                    # اگر כן، آن را دوباره فعال می‌کند
                    c.execute("UPDATE user_uuids SET is_active = 1, name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (name, existing_inactive_for_this_user['id']))
                    return "db_msg_uuid_reactivated"

                # حالا وجود UUID را به طور کلی بررسی می‌کند
                existing_active = c.execute("SELECT * FROM user_uuids WHERE uuid = ? AND is_active = 1", (uuid_str,)).fetchone()
                if existing_active:
                    if existing_active['user_id'] == user_id:
                        return "db_err_uuid_already_active_self"
                    else:
                        # اگر اکانت فعال متعلق به دیگری است، درخواست تایید ارسال می‌شود
                        return {
                            "status": "confirmation_required",
                            "owner_id": existing_active['user_id'],
                            "uuid_id": existing_active['id']
                        }
                
                # اگر اکانت اصلاً وجود نداشت یا غیرفعال و متعلق به دیگری بود، یک رکورد جدید می‌سازد
                c.execute(
                    "INSERT INTO user_uuids (user_id, uuid, name) VALUES (?, ?, ?)",
                    (user_id, uuid_str, name)
                )
                return "db_msg_uuid_added"

    def add_shared_uuid(self, user_id: int, uuid_str: str, name: str) -> bool:
        """
        یک اکانت اشتراکی را برای کاربر ثبت یا فعال‌سازی مجدد می‌کند.
        این تابع فاقد منطق بررسی مالکیت است و مستقیماً عمل می‌کند.
        """
        uuid_str = uuid_str.lower()
        with self._conn() as c:
            # بررسی می‌کند آیا کاربر قبلاً این اکانت را داشته و غیرفعال کرده است
            existing_inactive = c.execute("SELECT * FROM user_uuids WHERE user_id = ? AND uuid = ? AND is_active = 0", (user_id, uuid_str)).fetchone()
            
            if existing_inactive:
                # اگر وجود داشت، آن را دوباره فعال می‌کند
                c.execute("UPDATE user_uuids SET is_active = 1, name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (name, existing_inactive['id']))
            else:
                # در غیر این صورت، یک رکورد جدید برای کاربر ایجاد می‌کند
                c.execute("INSERT INTO user_uuids (user_id, uuid, name, is_active) VALUES (?, ?, ?, 1)", (user_id, uuid_str, name))
            return True
    # --- *** END OF CHANGES *** ---

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

    def all_active_uuids(self):
        """Yields all active UUIDs along with their reminder status."""
        with self._conn() as c:
            # Added renewal_reminder_sent to the selected columns
            cursor = c.execute("SELECT id, user_id, uuid, created_at, first_connection_time, welcome_message_sent, renewal_reminder_sent FROM user_uuids WHERE is_active=1")
            for row in cursor:
                yield dict(row)
            
    def get_all_user_ids(self):
        """تمام شناسه‌های کاربری را به صورت جریانی (generator) برمی‌گرداند."""
        with self._conn() as c:
            cursor = c.execute("SELECT user_id FROM users")
            for row in cursor:
                yield row['user_id']
        
    def get_all_bot_users(self):
        """تمام کاربران ربات را به صورت لیست برمی‌گرداند."""
        with self._conn() as c:
            cursor = c.execute("SELECT user_id, username, first_name, last_name FROM users ORDER BY user_id")
            # FIX: The generator is converted to a list before being returned.
            return [dict(r) for r in cursor.fetchall()]
        
    def update_user_birthday(self, user_id: int, birthday_date: datetime.date):
        with self._conn() as c:
            c.execute("UPDATE users SET birthday = ? WHERE user_id = ?", (birthday_date, user_id))

    def get_users_with_birthdays(self):
        """کاربران دارای تاریخ تولد را به صورت جریانی (generator) برمی‌گرداند."""
        with self._conn() as c:
            cursor = c.execute("""
                SELECT user_id, first_name, username, birthday FROM users
                WHERE birthday IS NOT NULL
                ORDER BY strftime('%m-%d', birthday)
            """)
            for row in cursor:
                yield dict(row)
        
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

    def reset_welcome_message_sent(self, uuid_id: int):
        """
        Resets the welcome message sent flag for a specific UUID. Used for testing purposes.
        """
        with self._conn() as c:
            c.execute("UPDATE user_uuids SET welcome_message_sent = 0 WHERE id = ?", (uuid_id,))

    def add_payment_record(self, uuid_id: int) -> bool:
        """یک رکورد پرداخت برای کاربر با تاریخ فعلی ثبت می‌کند."""
        with self._conn() as c:
            c.execute("INSERT INTO payments (uuid_id, payment_date) VALUES (?, ?)",
                      (uuid_id, datetime.now(pytz.utc)))
            return True

    def set_renewal_reminder_sent(self, uuid_id: int):
        """Sets the renewal reminder flag to 1 (sent)."""
        with self._conn() as c:
            c.execute("UPDATE user_uuids SET renewal_reminder_sent = 1 WHERE id = ?", (uuid_id,))

    def reset_renewal_reminder_sent(self, uuid_id: int):
        """Resets the renewal reminder flag to 0 (not sent)."""
        with self._conn() as c:
            c.execute("UPDATE user_uuids SET renewal_reminder_sent = 0 WHERE id = ?", (uuid_id,))

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

    def get_all_payments_with_user_info(self):
        """تمام پرداخت‌ها را به همراه اطلاعات کاربر به صورت جریانی (generator) برمی‌گرداند."""
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
            cursor = c.execute(query)
            for row in cursor:
                yield dict(row)

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
        (نسخه نهایی) مصرف روزانه تمام UUID ها را از نیمه‌شب به صورت یک‌جا و با مدیریت ریست شدن حجم محاسبه می‌کند.
        """
        tehran_tz = pytz.timezone("Asia/Tehran")
        today_midnight_tehran = datetime.now(tehran_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        today_midnight_utc = today_midnight_tehran.astimezone(pytz.utc)

        query = """
            WITH LastSnapshots AS (
                SELECT
                    s.uuid_id,
                    MAX(CASE WHEN s.taken_at >= ? THEN s.taken_at END) as last_ts_today,
                    MAX(CASE WHEN s.taken_at < ? THEN s.taken_at END) as last_ts_yesterday
                FROM usage_snapshots s
                GROUP BY s.uuid_id
            ),
            RelevantSnapshots AS (
                SELECT
                    ls.uuid_id,
                    s_today.hiddify_usage_gb as h_end,
                    s_today.marzban_usage_gb as m_end,
                    COALESCE(s_yesterday.hiddify_usage_gb, s_first_today.hiddify_usage_gb, 0) as h_start,
                    COALESCE(s_yesterday.marzban_usage_gb, s_first_today.marzban_usage_gb, 0) as m_start
                FROM LastSnapshots ls
                JOIN usage_snapshots s_today ON ls.uuid_id = s_today.uuid_id AND ls.last_ts_today = s_today.taken_at
                LEFT JOIN usage_snapshots s_yesterday ON ls.uuid_id = s_yesterday.uuid_id AND ls.last_ts_yesterday = s_yesterday.taken_at
                LEFT JOIN (
                    SELECT uuid_id, hiddify_usage_gb, marzban_usage_gb, taken_at FROM (
                        SELECT uuid_id, hiddify_usage_gb, marzban_usage_gb, taken_at, ROW_NUMBER() OVER(PARTITION BY uuid_id ORDER BY taken_at) as rn
                        FROM usage_snapshots WHERE taken_at >= ?
                    ) WHERE rn = 1
                ) s_first_today ON ls.uuid_id = s_first_today.uuid_id
            )
            SELECT
                uu.uuid,
                rs.h_end, rs.m_end,
                rs.h_start, rs.m_start
            FROM user_uuids uu
            JOIN RelevantSnapshots rs ON uu.id = rs.uuid_id
            WHERE uu.is_active = 1;
        """
        
        usage_map = {}
        with self._conn() as c:
            rows = c.execute(query, (today_midnight_utc, today_midnight_utc, today_midnight_utc)).fetchall()
            for row in rows:
                h_start, m_start = (row['h_start'] or 0.0), (row['m_start'] or 0.0)
                h_end, m_end = (row['h_end'] or 0.0), (row['m_end'] or 0.0)
                
                h_usage = h_end if h_end < h_start else h_end - h_start
                m_usage = m_end if m_end < m_start else m_end - m_start
                
                usage_map[row['uuid']] = {'hiddify': max(0, h_usage), 'marzban': max(0, m_usage)}
        return usage_map


    def get_daily_usage_summary(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        (نسخه نهایی و کامل شده) مجموع مصرف روزانه تمام کاربران را برای نمودار داشبورد ادمین، با مدیریت صحیح ریست شدن حجم، محاسبه می‌کند.
        """
        tehran_tz = pytz.timezone("Asia/Tehran")
        now_in_tehran = datetime.now(tehran_tz)
        start_date_utc = (now_in_tehran - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.utc)

        # ۱. یک دیکشنری برای نگهداری مجموع مصرف هر روز می‌سازیم
        daily_totals = {
            (now_in_tehran.date() - timedelta(days=i)): {'h': 0.0, 'm': 0.0}
            for i in range(days)
        }

        with self._conn() as c:
            # ۲. تمام اسنپ‌شات‌های دوره مورد نظر را بهینه دریافت می‌کنیم
            all_snapshots_query = "SELECT uuid_id, hiddify_usage_gb, marzban_usage_gb, taken_at FROM usage_snapshots WHERE taken_at >= ? ORDER BY uuid_id, taken_at ASC;"
            all_snapshots = c.execute(all_snapshots_query, (start_date_utc,)).fetchall()

            snapshots_by_user = {}
            for snap in all_snapshots:
                snapshots_by_user.setdefault(snap['uuid_id'], []).append(snap)

            # ۳. برای هر کاربر، مصرف روزانه را جداگانه محاسبه می‌کنیم
            for uuid_id, user_snaps in snapshots_by_user.items():
                # نقطه شروع محاسبه، آخرین رکورد قبل از این دوره است
                last_snap_before = c.execute("SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1", (uuid_id, start_date_utc)).fetchone()
                
                last_h = last_snap_before['hiddify_usage_gb'] if last_snap_before else 0.0
                last_m = last_snap_before['marzban_usage_gb'] if last_snap_before else 0.0

                # ۴. با حلقه روی اسنپ‌شات‌ها، مصرف هر روز را محاسبه و جمع می‌زنیم
                for snap in user_snaps:
                    snap_date_local = snap['taken_at'].astimezone(tehran_tz).date()
                    
                    current_h = snap['hiddify_usage_gb'] or 0.0
                    current_m = snap['marzban_usage_gb'] or 0.0

                    # اگر مصرف فعلی کمتر از قبلی بود (ریست)، مصرف از صفر شروع می‌شود
                    h_diff = current_h if current_h < last_h else current_h - last_h
                    m_diff = current_m if current_m < last_m else current_m - last_m
                    
                    if snap_date_local in daily_totals:
                        daily_totals[snap_date_local]['h'] += h_diff
                        daily_totals[snap_date_local]['m'] += m_diff
                    
                    last_h, last_m = current_h, current_m

        # ۵. نتیجه نهایی را برای ارسال به نمودار آماده می‌کنیم
        summary = []
        for dt, totals in sorted(daily_totals.items()):
            total_gb = totals['h'] + totals['m']
            summary.append({
                'date': dt.strftime('%Y-%m-%d'),
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
        
    def toggle_template_random_pool(self, template_id: int) -> bool:
        """وضعیت عضویت یک قالب در استخر انتخاب تصادفی را تغییر می‌دهد."""
        with self._conn() as c:
            cursor = c.execute("UPDATE config_templates SET is_random_pool = 1 - is_random_pool WHERE id = ?", (template_id,))
            return cursor.rowcount > 0
        
    def get_templates_by_pool_status(self) -> tuple[list[dict], list[dict]]:
        """قالب‌ها را به دو دسته عضو و غیرعضو در استخر تصادفی تقسیم می‌کند."""
        all_templates = self.get_active_config_templates()
        random_pool = [tpl for tpl in all_templates if tpl.get('is_random_pool')]
        fixed_pool = [tpl for tpl in all_templates if not tpl.get('is_random_pool')]
        return random_pool, fixed_pool
    
    def get_user_daily_usage_history_by_panel(self, uuid_id: int, days: int = 7) -> list:
        """تاریخچه مصرف روزانه کاربر را به تفکیک هر پنل برای تعداد روز مشخص شده برمی‌گرداند."""
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
                    "hiddify_usage": h_usage,
                    "marzban_usage": m_usage,
                    "total_usage": h_usage + m_usage
                })
        return history

    def add_sent_report(self, user_id: int, message_id: int):
        """یک رکورد برای پیام گزارش ارسال شده ثبت می‌کند."""
        with self._conn() as c:
            c.execute("INSERT INTO sent_reports (user_id, message_id, sent_at) VALUES (?, ?, ?)",
                      (user_id, message_id, datetime.now(pytz.utc)))

    def get_old_reports_to_delete(self, hours: int = 12) -> List[Dict[str, Any]]:
        """پیام‌های گزارشی که قدیمی‌تر از زمان مشخص شده هستند را برمی‌گرداند."""
        time_limit = datetime.now(pytz.utc) - timedelta(hours=hours)
        query = """
            SELECT sr.id, sr.user_id, sr.message_id
            FROM sent_reports sr
            JOIN users u ON sr.user_id = u.user_id
            WHERE sr.sent_at < ? AND u.auto_delete_reports = 1
        """
        with self._conn() as c:
            rows = c.execute(query, (time_limit,)).fetchall()
            return [dict(r) for r in rows]

    def delete_sent_report_record(self, record_id: int):
        """یک رکورد را از جدول sent_reports پس از تلاش برای حذف، پاک می‌کند."""
        with self._conn() as c:
            c.execute("DELETE FROM sent_reports WHERE id = ?", (record_id,))

    def get_sent_warnings_since_midnight(self) -> list:
        """
        گزارشی از هشدارهایی که از نیمه‌شب امروز ارسال شده‌اند را برمی‌گرداند.
        """
        tehran_tz = pytz.timezone("Asia/Tehran")
        today_midnight_tehran = datetime.now(tehran_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        today_midnight_utc = today_midnight_tehran.astimezone(pytz.utc)

        query = """
            SELECT
                uu.name,
                wl.warning_type
            FROM warning_log wl
            JOIN user_uuids uu ON wl.uuid_id = uu.id
            WHERE wl.sent_at >= ?
            ORDER BY uu.name;
        """
        with self._conn() as c:
            rows = c.execute(query, (today_midnight_utc,)).fetchall()
            return [dict(r) for r in rows]

    def record_user_agent(self, uuid_id: int, user_agent: str):
        """Saves or updates the user agent for a given UUID, resetting the last_seen timestamp."""
        with self._conn() as c:
            c.execute("""
                INSERT INTO client_user_agents (uuid_id, user_agent, last_seen)
                VALUES (?, ?, ?)
                ON CONFLICT(uuid_id, user_agent) DO UPDATE SET
                last_seen = excluded.last_seen;
            """, (uuid_id, user_agent, datetime.now(pytz.utc)))

    def get_user_agents_for_uuid(self, uuid_id: int) -> List[Dict[str, Any]]:
        """Retrieves all recorded user agents for a specific user UUID, ordered by last seen."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT user_agent, last_seen FROM client_user_agents
                WHERE uuid_id = ? ORDER BY last_seen DESC
            """, (uuid_id,)).fetchall()
            return [dict(r) for r in rows]
        
    def get_all_user_agents(self) -> List[Dict[str, Any]]:
        """
        تمام دستگاه‌های ثبت‌شده (user-agents) را به همراه اطلاعات کاربر مربوطه
        برای نمایش در گزارش ادمین برمی‌گرداند.
        """
        query = """
            SELECT
                ca.user_agent,
                ca.last_seen,
                uu.name as config_name,
                u.first_name,
                u.user_id
            FROM client_user_agents ca
            JOIN user_uuids uu ON ca.uuid_id = uu.id
            LEFT JOIN users u ON uu.user_id = u.user_id
            ORDER BY ca.last_seen DESC;
        """
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]

    def count_user_agents(self, uuid_id: int) -> int:
            """Counts the number of recorded user agents for a specific user UUID."""
            with self._conn() as c:
                row = c.execute("SELECT COUNT(id) FROM client_user_agents WHERE uuid_id = ?", (uuid_id,)).fetchone()
            return row[0] if row else 0
    
    def delete_user_agents_by_uuid_id(self, uuid_id: int) -> int:
        """Deletes all user agent records for a given uuid_id."""
        with self._conn() as c:
            cursor = c.execute("DELETE FROM client_user_agents WHERE uuid_id = ?", (uuid_id,))
            return cursor.rowcount

    def log_traffic_transfer(self, sender_uuid_id: int, receiver_uuid_id: int, panel_type: str, amount_gb: float):
        """یک رکورد جدید برای انتقال ترافیک ثبت می‌کند."""
        with self._conn() as c:
            c.execute(
                "INSERT INTO traffic_transfers (sender_uuid_id, receiver_uuid_id, panel_type, amount_gb, transferred_at) VALUES (?, ?, ?, ?, ?)",
                (sender_uuid_id, receiver_uuid_id, panel_type, amount_gb, datetime.now(pytz.utc))
            )

    def has_transferred_in_last_30_days(self, sender_uuid_id: int) -> bool:
        """بررسی می‌کند آیا کاربر در ۳۰ روز گذشته انتقالی داشته است یا خیر."""
        thirty_days_ago = datetime.now(pytz.utc) - timedelta(days=30)
        with self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM traffic_transfers WHERE sender_uuid_id = ? AND transferred_at >= ?",
                (sender_uuid_id, thirty_days_ago)
            ).fetchone()
            return row is not None

    def add_achievement(self, user_id: int, badge_code: str) -> bool:
        """یک دستاورد جدید برای کاربر ثبت می‌کند و در صورت موفقیت True برمی‌گرداند."""
        with self._conn() as c:
            try:
                c.execute(
                    "INSERT INTO user_achievements (user_id, badge_code) VALUES (?, ?)",
                    (user_id, badge_code)
                )
                return True
            except sqlite3.IntegrityError:
                # کاربر از قبل این نشان را داشته است
                return False

    def get_user_achievements(self, user_id: int) -> List[str]:
        """لیست کدهای تمام نشان‌های یک کاربر را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute("SELECT badge_code FROM user_achievements WHERE user_id = ?", (user_id,)).fetchall()
            return [row['badge_code'] for row in rows]

    def get_total_usage_in_last_n_days(self, uuid_id: int, days: int) -> float:
        """مجموع کل مصرف یک کاربر در N روز گذشته را محاسبه می‌کند."""
        time_limit = datetime.now(pytz.utc) - timedelta(days=days)
        with self._conn() as c:
            query = """
                SELECT
                    MAX(hiddify_usage_gb) - MIN(hiddify_usage_gb) as h_usage,
                    MAX(marzban_usage_gb) - MIN(marzban_usage_gb) as m_usage
                FROM usage_snapshots
                WHERE uuid_id = ? AND taken_at >= ?
            """
            row = c.execute(query, (uuid_id, time_limit)).fetchone()
            if not row:
                return 0.0
            
            h_usage = max(0, row['h_usage'] or 0)
            m_usage = max(0, row['m_usage'] or 0)
            return h_usage + m_usage

    def get_night_usage_stats_in_last_n_days(self, uuid_id: int, days: int) -> dict:
        """آمار مصرف شبانه (۰۰:۰۰ تا ۰۶:۰۰) را در N روز گذشته محاسبه می‌کند."""
        time_limit = datetime.now(pytz.utc) - timedelta(days=days)
        tehran_tz = pytz.timezone("Asia/Tehran")
        
        with self._conn() as c:
            query = """
                SELECT hiddify_usage_gb, marzban_usage_gb, taken_at
                FROM usage_snapshots
                WHERE uuid_id = ? AND taken_at >= ?
                ORDER BY taken_at ASC
            """
            snapshots = c.execute(query, (uuid_id, time_limit)).fetchall()
            
            total_usage = 0
            night_usage = 0
            last_h, last_m = 0, 0
            
            # مقدار اولیه را از آخرین اسنپ‌شات قبل از دوره می‌گیریم
            prev_snap = c.execute("SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1", (uuid_id, time_limit)).fetchone()
            if prev_snap:
                last_h, last_m = prev_snap['hiddify_usage_gb'], prev_snap['marzban_usage_gb']

            for snap in snapshots:
                h_diff = max(0, (snap['hiddify_usage_gb'] or 0) - (last_h or 0))
                m_diff = max(0, (snap['marzban_usage_gb'] or 0) - (last_m or 0))
                diff = h_diff + m_diff
                total_usage += diff
                
                snap_time_tehran = snap['taken_at'].astimezone(tehran_tz)
                if 0 <= snap_time_tehran.hour < 6:
                    night_usage += diff
                
                last_h, last_m = snap['hiddify_usage_gb'], snap['marzban_usage_gb']
            
            return {'total': total_usage, 'night': night_usage}


    def count_recently_active_users(self, minutes: int = 15) -> dict:
        """
        (نسخه نهایی و اصلاح شده) تعداد کاربران یکتایی که در N دقیقه گذشته مصرف داشته‌اند را با مقایسه دو اسنپ‌شات آخرشان محاسبه می‌کند.
        """
        time_limit = datetime.now(pytz.utc) - timedelta(minutes=minutes)
        results = {'hiddify': 0, 'marzban_fr': 0, 'marzban_tr': 0}
        active_users = {'hiddify': set(), 'marzban_fr': set(), 'marzban_tr': set()}

        with self._conn() as c:
            all_uuids = c.execute("SELECT id FROM user_uuids WHERE is_active = 1").fetchall()
            uuid_ids = [row['id'] for row in all_uuids]

            for uuid_id in uuid_ids:
                snapshots = c.execute(
                    """
                    SELECT s.hiddify_usage_gb, s.marzban_usage_gb, s.taken_at, uu.has_access_fr, uu.has_access_tr
                    FROM usage_snapshots s
                    JOIN user_uuids uu ON s.uuid_id = uu.id
                    WHERE s.uuid_id = ?
                    ORDER BY s.taken_at DESC
                    LIMIT 2
                    """, (uuid_id,)
                ).fetchall()

                if len(snapshots) < 2:
                    continue

                latest_snap, previous_snap = snapshots[0], snapshots[1]

                # 🔥 خط اصلاح شده اینجاست
                # اطمینان حاصل می‌کنیم که زمان خوانده شده از دیتابیس، دارای اطلاعات منطقه زمانی است
                latest_snap_time = latest_snap['taken_at']
                if latest_snap_time.tzinfo is None:
                    latest_snap_time = pytz.utc.localize(latest_snap_time)
                
                if latest_snap_time < time_limit:
                    continue

                h_increase = (latest_snap['hiddify_usage_gb'] or 0) - (previous_snap['hiddify_usage_gb'] or 0)
                m_increase = (latest_snap['marzban_usage_gb'] or 0) - (previous_snap['marzban_usage_gb'] or 0)

                if h_increase > 0.001:
                    active_users['hiddify'].add(uuid_id)

                if m_increase > 0.001:
                    if latest_snap['has_access_fr']:
                        active_users['marzban_fr'].add(uuid_id)
                    if latest_snap['has_access_tr']:
                        active_users['marzban_tr'].add(uuid_id)

        results['hiddify'] = len(active_users['hiddify'])
        results['marzban_fr'] = len(active_users['marzban_fr'])
        results['marzban_tr'] = len(active_users['marzban_tr'])
        return results


    def get_or_create_referral_code(self, user_id: int) -> str:
        """کد معرف کاربر را برمی‌گرداند یا اگر وجود نداشته باشد، یکی برای او می‌سازد."""
        with self._conn() as c:
            row = c.execute("SELECT referral_code FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if row and row['referral_code']:
                return row['referral_code']
            else:
                while True:
                    # یک کد ۶ حرفی تصادفی و خوانا ایجاد می‌کند
                    new_code = "REF-" + secrets.token_urlsafe(4).upper().replace("_", "").replace("-", "")
                    if not c.execute("SELECT 1 FROM users WHERE referral_code = ?", (new_code,)).fetchone():
                        c.execute("UPDATE users SET referral_code = ? WHERE user_id = ?", (new_code, user_id))
                        return new_code

    def set_referrer(self, user_id: int, referrer_code: str):
        """کاربر معرف را برای یک کاربر جدید ثبت می‌کند."""
        with self._conn() as c:
            referrer = c.execute("SELECT user_id FROM users WHERE referral_code = ?", (referrer_code,)).fetchone()
            if referrer:
                c.execute("UPDATE users SET referred_by_user_id = ? WHERE user_id = ?", (referrer['user_id'], user_id))
                logger.info(f"User {user_id} was referred by user {referrer['user_id']} (code: {referrer_code}).")

    def get_referrer_info(self, user_id: int) -> Optional[dict]:
        """اطلاعات کاربر معرف را (در صورت وجود) برمی‌گرداند."""
        with self._conn() as c:
            row = c.execute("""
                SELECT u.referred_by_user_id, u.referral_reward_applied, r.first_name as referrer_name
                FROM users u
                JOIN users r ON u.referred_by_user_id = r.user_id
                WHERE u.user_id = ?
            """, (user_id,)).fetchone()
            return dict(row) if row else None

    def mark_referral_reward_as_applied(self, user_id: int):
        """وضعیت پاداش معرفی را برای جلوگیری از اهدای مجدد، ثبت می‌کند."""
        with self._conn() as c:
            c.execute("UPDATE users SET referral_reward_applied = 1 WHERE user_id = ?", (user_id,))

    def get_last_transfer_timestamp(self, sender_uuid_id: int) -> Optional[datetime]:
        """آخرین زمان انتقال ترافیک توسط یک کاربر را برمی‌گرداند."""
        with self._conn() as c:
            row = c.execute(
                "SELECT transferred_at FROM traffic_transfers WHERE sender_uuid_id = ? ORDER BY transferred_at DESC LIMIT 1",
                (sender_uuid_id,)
            ).fetchone()
            return row['transferred_at'] if row else None

    def delete_transfer_history(self, sender_uuid_id: int) -> int:
        """تمام تاریخچه انتقال یک کاربر خاص را برای ریست کردن محدودیت حذف می‌کند."""
        with self._conn() as c:
            cursor = c.execute("DELETE FROM traffic_transfers WHERE sender_uuid_id = ?", (sender_uuid_id,))
            return cursor.rowcount

    def get_weekly_top_consumers_report(self) -> dict:
        """
        (نسخه اصلاح شده) گزارشی از پرمصرف‌ترین کاربران هفته و هر روز هفته را با محاسبه دقیق مصرف برمی‌گرداند.
        """
        tehran_tz = pytz.timezone("Asia/Tehran")
        today_jalali = jdatetime.datetime.now(tz=tehran_tz)
        days_since_saturday = (today_jalali.weekday() + 1) % 7
        week_start_utc = (datetime.now(tehran_tz) - timedelta(days=days_since_saturday)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.utc)

        report = {'top_10_overall': [], 'top_daily': {}}
        all_uuids = {row['id']: row['name'] for row in self.get_all_user_uuids()}
        
        weekly_usage_map = {uuid_id: 0.0 for uuid_id in all_uuids.keys()}
        daily_usage_map = {i: {} for i in range(7)}

        with self._conn() as c:
            all_snapshots_query = "SELECT uuid_id, hiddify_usage_gb, marzban_usage_gb, taken_at FROM usage_snapshots WHERE taken_at >= ? ORDER BY uuid_id, taken_at ASC;"
            all_week_snapshots = c.execute(all_snapshots_query, (week_start_utc,)).fetchall()

            snapshots_by_user = {}
            for snap in all_week_snapshots:
                snapshots_by_user.setdefault(snap['uuid_id'], []).append(snap)
            
            for uuid_id, user_snaps in snapshots_by_user.items():
                last_snap_before = c.execute("SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1", (uuid_id, week_start_utc)).fetchone()
                
                last_h = last_snap_before['hiddify_usage_gb'] if last_snap_before else 0.0
                last_m = last_snap_before['marzban_usage_gb'] if last_snap_before else 0.0

                for snap in user_snaps:
                    h_diff = max(0, (snap['hiddify_usage_gb'] or 0.0) - last_h)
                    m_diff = max(0, (snap['marzban_usage_gb'] or 0.0) - last_m)
                    total_diff = h_diff + m_diff
                    
                    weekly_usage_map[uuid_id] += total_diff
                    
                    snap_date_local = snap['taken_at'].astimezone(tehran_tz)
                    day_of_week_jalali = (jdatetime.datetime.fromgregorian(datetime=snap_date_local).weekday() + 1) % 7
                    daily_usage_map[day_of_week_jalali].setdefault(uuid_id, 0.0)
                    daily_usage_map[day_of_week_jalali][uuid_id] += total_diff

                    last_h, last_m = snap['hiddify_usage_gb'] or 0.0, snap['marzban_usage_gb'] or 0.0

        sorted_weekly = sorted(weekly_usage_map.items(), key=lambda item: item[1], reverse=True)
        for uuid_id, total_usage in sorted_weekly[:10]:
            if total_usage > 0.01:
                report['top_10_overall'].append({'name': all_uuids.get(uuid_id, 'ناشناس'), 'total_usage': total_usage})

        for day_index, daily_data in daily_usage_map.items():
            if not daily_data: continue
            top_user_id = max(daily_data, key=daily_data.get)
            top_usage = daily_data[top_user_id]
            if top_usage > 0.01:
                report['top_daily'][day_index] = {'name': all_uuids.get(top_user_id, 'ناشناس'), 'usage': top_usage}
                
        return report

    def add_achievement_points(self, user_id: int, points: int):
            """امتیاز به حساب یک کاربر اضافه می‌کند."""
            with self._conn() as c:
                c.execute("UPDATE users SET achievement_points = achievement_points + ? WHERE user_id = ?", (points, user_id))

    def spend_achievement_points(self, user_id: int, points: int) -> bool:
        """امتیاز را از حساب کاربر کم می‌کند و موفقیت عملیات را برمی‌گرداند."""
        with self._conn() as c:
            current_points = c.execute("SELECT achievement_points FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if current_points and current_points['achievement_points'] >= points:
                c.execute("UPDATE users SET achievement_points = achievement_points - ? WHERE user_id = ?", (points, user_id))
                return True
            return False

    def log_shop_purchase(self, user_id: int, item_key: str, cost: int):
        """یک خرید از فروشگاه را در دیتابیس ثبت می‌کند."""
        with self._conn() as c:
            c.execute("INSERT INTO achievement_shop_log (user_id, item_key, cost) VALUES (?, ?, ?)", (user_id, item_key, cost))

    def get_achievement_leaderboard(self, limit: int = 10) -> list[dict]:
        """لیستی از کاربران برتر بر اساس امتیاز دستاوردها را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT user_id, first_name, achievement_points FROM users WHERE achievement_points > 0 ORDER BY achievement_points DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_referred_users(self, referrer_user_id: int) -> list[dict]:
            """لیست کاربرانی که توسط یک کاربر خاص معرفی شده‌اند را برمی‌گرداند."""
            with self._conn() as c:
                rows = c.execute(
                    "SELECT user_id, first_name, referral_reward_applied FROM users WHERE referred_by_user_id = ?",
                    (referrer_user_id,)
                ).fetchall()
                return [dict(r) for r in rows]

    def delete_all_daily_snapshots(self) -> int:
        """تمام اسنپ‌شات‌های مصرف امروز (به وقت UTC) را برای همه کاربران حذف می‌کند."""
        today_start_utc = datetime.now(pytz.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        with self._conn() as c:
            cursor = c.execute("DELETE FROM usage_snapshots WHERE taken_at >= ?", (today_start_utc,))
            deleted_count = cursor.rowcount
            logger.info(f"ADMIN ACTION: Deleted {deleted_count} daily snapshots for all users.")
            return deleted_count

db = DatabaseManager()