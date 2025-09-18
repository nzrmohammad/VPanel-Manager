import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import pytz
import jdatetime
import secrets
import threading

logger = logging.getLogger(__name__)
db_lock = threading.RLock()

class DatabaseManager:
    def __init__(self, path: str = "bot_data.db"):
        self.path = path
        self._user_cache = {}
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.row_factory = sqlite3.Row
        return conn

    # متد جدید برای پاک کردن کش کاربر
    def clear_user_cache(self, user_id: int):
        """کش اطلاعات یک کاربر خاص را پاک می‌کند."""
        if user_id in self._user_cache:
            del self._user_cache[user_id]
            logger.info(f"CACHE: Cleared cache for user_id {user_id}.")

    def _init_db(self) -> None:
        with self.write_conn() as c:
            try:
                cursor = c.execute("PRAGMA table_info(users);")
                columns = [row['name'] for row in cursor.fetchall()]

            except Exception as e:
                logger.error(f"An error occurred during database migration check: {e}")

            c.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    birthday DATE,
                    last_name TEXT,
                    daily_reports INTEGER DEFAULT 1,
                    expiry_warnings INTEGER DEFAULT 1,
                    data_warning_de INTEGER DEFAULT 1,
                    data_warning_fr INTEGER DEFAULT 1,
                    data_warning_tr INTEGER DEFAULT 1,
                    data_warning_us INTEGER DEFAULT 1,
                    show_info_config INTEGER DEFAULT 1,
                    admin_note TEXT,
                    lang_code TEXT,
                    weekly_reports INTEGER DEFAULT 1,
                    auto_delete_reports INTEGER DEFAULT 0,
                    referral_code TEXT UNIQUE,
                    referred_by_user_id INTEGER,
                    referral_reward_applied INTEGER DEFAULT 0,
                    achievement_points INTEGER DEFAULT 0,
                    achievement_alerts INTEGER DEFAULT 1,
                    promotional_alerts INTEGER DEFAULT 1,
                    wallet_balance REAL DEFAULT 0.0
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
                    has_access_us INTEGER DEFAULT 0,
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
                CREATE TABLE IF NOT EXISTS birthday_gift_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    gift_year INTEGER NOT NULL,
                    given_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, gift_year)
                );
                CREATE TABLE IF NOT EXISTS anniversary_gift_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    gift_year INTEGER NOT NULL,
                    given_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, gift_year)
                );
                CREATE TABLE IF NOT EXISTS wallet_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    type TEXT NOT NULL, -- 'deposit', 'purchase', 'refund'
                    description TEXT,
                    transaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS charge_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    message_id INTEGER NOT NULL,
                    request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_pending INTEGER DEFAULT 1,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                category TEXT DEFAULT 'info', -- مثلا: system, warning, gift, broadcast
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS weekly_champion_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    win_date DATE NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS achievement_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    badge_code TEXT NOT NULL,
                    status TEXT DEFAULT 'pending', -- pending, approved, rejected
                    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reviewed_by INTEGER,
                    reviewed_at TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS monthly_costs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    cost REAL NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(year, month, description)
                );
                CREATE INDEX IF NOT EXISTS idx_user_uuids_uuid ON user_uuids(uuid);
                CREATE INDEX IF NOT EXISTS idx_user_uuids_user_id ON user_uuids(user_id);
                CREATE INDEX IF NOT EXISTS idx_snapshots_taken_at ON usage_snapshots(taken_at);
                CREATE INDEX IF NOT EXISTS idx_snapshots_uuid_id_taken_at ON usage_snapshots(uuid_id, taken_at);
            """)
        logger.info("SQLite schema is fresh and ready.")

    def write_conn(self):
        class WriteConnection:
            def __init__(self, db_manager_instance):
                self.db_manager = db_manager_instance

            def __enter__(self):
                db_lock.acquire()
                self.conn = sqlite3.connect(self.db_manager.path, detect_types=sqlite3.PARSE_DECLTYPES)
                self.conn.execute("PRAGMA journal_mode=WAL")
                self.conn.execute("PRAGMA foreign_keys = ON;")
                self.conn.row_factory = sqlite3.Row
                return self.conn

            def __exit__(self, exc_type, exc_val, exc_tb):
                if self.conn:
                    if exc_type is None:
                        self.conn.commit()
                    self.conn.close()
                db_lock.release()
        return WriteConnection(self)

    def clear_user_cache(self, user_id: int):
        """کش اطلاعات یک کاربر خاص را پاک می‌کند."""
        if user_id in self._user_cache:
            del self._user_cache[user_id]
            logger.info(f"CACHE: Cleared cache for user_id {user_id}.")

    def add_usage_snapshot(self, uuid_id: int, hiddify_usage: float, marzban_usage: float) -> None:
        with self.write_conn() as c:
            c.execute(
                "INSERT INTO usage_snapshots (uuid_id, hiddify_usage_gb, marzban_usage_gb, taken_at) VALUES (?, ?, ?, ?)",
                (uuid_id, hiddify_usage, marzban_usage, datetime.now(pytz.utc))
            )

    def get_usage_since_midnight(self, uuid_id: int) -> Dict[str, float]:
        """
        (نسخه نهایی و کاملاً پایدار) مصرف روزانه را با مدیریت ریست شدن حجم محاسبه می‌کند.
        """
        tehran_tz = pytz.timezone("Asia/Tehran")
        now_in_tehran = datetime.now(tehran_tz)
        today_midnight_tehran = now_in_tehran.replace(hour=0, minute=0, second=0, microsecond=0)
        today_midnight_utc = today_midnight_tehran.astimezone(pytz.utc)

        with self._conn() as c:
            snapshots_today = c.execute(
                "SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ? ORDER BY taken_at ASC",
                (uuid_id, today_midnight_utc)
            ).fetchall()

            last_snap_before = c.execute(
                "SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1",
                (uuid_id, today_midnight_utc)
            ).fetchone()

            if last_snap_before:
                last_h = last_snap_before['hiddify_usage_gb'] or 0.0
                last_m = last_snap_before['marzban_usage_gb'] or 0.0
            elif snapshots_today:
                last_h = snapshots_today[0]['hiddify_usage_gb'] or 0.0
                last_m = snapshots_today[0]['marzban_usage_gb'] or 0.0
            else:
                return {'hiddify': 0.0, 'marzban': 0.0}

            total_h_usage = 0.0
            total_m_usage = 0.0
            
            for snap in snapshots_today:
                current_h = snap['hiddify_usage_gb'] or 0.0
                current_m = snap['marzban_usage_gb'] or 0.0
                
                h_diff = current_h if current_h < last_h else current_h - last_h
                m_diff = current_m if current_m < last_m else current_m - last_m
                
                total_h_usage += h_diff
                total_m_usage += m_diff
                
                last_h, last_m = current_h, current_m

            return {'hiddify': total_h_usage, 'marzban': total_m_usage}

    def get_weekly_usage_by_uuid(self, uuid_str: str) -> Dict[str, float]:
        """
        (نسخه نهایی و اصلاح شده) مصرف هفتگی را برای هر دو پنل به درستی محاسبه می‌کند.
        """
        uuid_id = self.get_uuid_id_by_uuid(uuid_str)
        if not uuid_id:
            return {'hiddify': 0.0, 'marzban': 0.0}

        tehran_tz = pytz.timezone("Asia/Tehran")
        today_jalali = jdatetime.datetime.now(tz=tehran_tz)
        days_since_saturday = (today_jalali.weekday() + 1) % 7
        week_start_utc = (datetime.now(tehran_tz) - timedelta(days=days_since_saturday)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.utc)

        with self._conn() as c:
            hiddify_start_row = c.execute("SELECT hiddify_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1", (uuid_id, week_start_utc)).fetchone()
            hiddify_end_row = c.execute("SELECT hiddify_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ? ORDER BY taken_at DESC LIMIT 1", (uuid_id, week_start_utc)).fetchone()

            total_h_usage = 0.0
            if hiddify_end_row and hiddify_end_row['hiddify_usage_gb'] is not None:
                start_h = hiddify_start_row['hiddify_usage_gb'] if hiddify_start_row and hiddify_start_row['hiddify_usage_gb'] is not None else 0
                end_h = hiddify_end_row['hiddify_usage_gb']
                if end_h >= start_h:
                    total_h_usage = end_h - start_h

            marzban_start_row = c.execute("SELECT marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1", (uuid_id, week_start_utc)).fetchone()
            marzban_end_row = c.execute("SELECT marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ? ORDER BY taken_at DESC LIMIT 1", (uuid_id, week_start_utc)).fetchone()

            total_m_usage = 0.0
            if marzban_end_row and marzban_end_row['marzban_usage_gb'] is not None:
                start_m = marzban_start_row['marzban_usage_gb'] if marzban_start_row and marzban_start_row['marzban_usage_gb'] is not None else 0
                end_m = marzban_end_row['marzban_usage_gb']
                if end_m >= start_m:
                    total_m_usage = end_m - start_m

            return {'hiddify': total_h_usage, 'marzban': total_m_usage}


    def get_panel_usage_in_intervals(self, uuid_id: int, panel_name: str) -> Dict[int, float]:
        if panel_name not in ['hiddify_usage_gb', 'marzban_usage_gb']:
            return {}

        now_utc = datetime.now(pytz.utc)
        intervals = {3: 0.0, 6: 0.0, 12: 0.0, 24: 0.0}

        with self.write_conn() as c:
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
        with self.write_conn() as c:
            c.execute(
                "INSERT INTO warning_log (uuid_id, warning_type, sent_at) VALUES (?, ?, ?) "
                "ON CONFLICT(uuid_id, warning_type) DO UPDATE SET sent_at=excluded.sent_at",
                (uuid_id, warning_type, datetime.now(pytz.utc))
            )

    def has_recent_warning(self, uuid_id: int, warning_type: str, hours: int = 24) -> bool:
        time_ago = datetime.now(pytz.utc) - timedelta(hours=hours)
        with self.write_conn() as c:
            row = c.execute(
                "SELECT 1 FROM warning_log WHERE uuid_id = ? AND warning_type = ? AND sent_at >= ?",
                (uuid_id, warning_type, time_ago)
            ).fetchone()
            return row is not None

    def get_user_ids_by_uuids(self, uuids: List[str]) -> List[int]:
        if not uuids: return []
        placeholders = ','.join('?' for _ in uuids)
        query = f"SELECT DISTINCT user_id FROM user_uuids WHERE uuid IN ({placeholders})"
        with self.write_conn() as c:
            rows = c.execute(query, uuids).fetchall()
            return [row['user_id'] for row in rows]

    def get_uuid_id_by_uuid(self, uuid_str: str) -> Optional[int]:
        with self.write_conn() as c:
            row = c.execute("SELECT id FROM user_uuids WHERE uuid = ?", (uuid_str,)).fetchone()
            return row['id'] if row else None

    def get_usage_since_midnight_by_uuid(self, uuid_str: str) -> Dict[str, float]:
        """Convenience function to get daily usage directly by UUID string."""
        uuid_id = self.get_uuid_id_by_uuid(uuid_str)
        if uuid_id:
            return self.get_usage_since_midnight(uuid_id)
        return {'hiddify': 0.0, 'marzban': 0.0}


    def add_or_update_scheduled_message(self, job_type: str, chat_id: int, message_id: int):
        with self.write_conn() as c:
            c.execute(
                "INSERT INTO scheduled_messages(job_type, chat_id, message_id) VALUES(?,?,?) "
                "ON CONFLICT(job_type, chat_id) DO UPDATE SET message_id=excluded.message_id, created_at=CURRENT_TIMESTAMP",
                (job_type, chat_id, message_id)
            )

    def get_scheduled_messages(self, job_type: str) -> List[Dict[str, Any]]:
        with self.write_conn() as c:
            rows = c.execute("SELECT * FROM scheduled_messages WHERE job_type=?", (job_type,)).fetchall()
            return [dict(r) for r in rows]

    def delete_scheduled_message(self, job_id: int):
        with self.write_conn() as c:
            c.execute("DELETE FROM scheduled_messages WHERE id=?", (job_id,))

    def user(self, user_id: int) -> Optional[Dict[str, Any]]:
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        with self.write_conn() as c:
            row = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            user_data = dict(row) if row else None
            if user_data:
                self._user_cache[user_id] = user_data
            return user_data

    def add_or_update_user(self, user_id: int, username: Optional[str], first: Optional[str], last: Optional[str]) -> bool:
        """
        Adds a user if they don't exist, or updates their info.
        Returns True if the user was newly created, False otherwise.
        """
        with self.write_conn() as c:
            existing_user = c.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone()
            logger.info(f"DB: Checking user {user_id}. Exists before this operation: {bool(existing_user)}")

            c.execute(
                "INSERT INTO users(user_id, username, first_name, last_name) VALUES(?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, last_name=excluded.last_name",
                (user_id, username, first, last),
            )
            self.clear_user_cache(user_id)
            return not existing_user

    def get_user_settings(self, user_id: int) -> Dict[str, bool]:
        with self.write_conn() as c:
            row = c.execute("SELECT daily_reports, weekly_reports, expiry_warnings, data_warning_de, data_warning_fr, data_warning_tr, data_warning_us, show_info_config, auto_delete_reports, achievement_alerts, promotional_alerts FROM users WHERE user_id=?", (user_id,)).fetchone()
            if row:
                row_dict = dict(row)
                return {
                    'daily_reports': bool(row_dict.get('daily_reports', True)),
                    'weekly_reports': bool(row_dict.get('weekly_reports', True)),
                    'expiry_warnings': bool(row_dict.get('expiry_warnings', True)),
                    'data_warning_de': bool(row_dict.get('data_warning_de', True)),
                    'data_warning_fr': bool(row_dict.get('data_warning_fr', True)),
                    'data_warning_tr': bool(row_dict.get('data_warning_tr', True)),
                    'data_warning_us': bool(row_dict.get('data_warning_us', True)),
                    'show_info_config': bool(row_dict.get('show_info_config', True)),
                    'auto_delete_reports': bool(row_dict.get('auto_delete_reports', False)),
                    'achievement_alerts': bool(row_dict.get('achievement_alerts', True)),
                    'promotional_alerts': bool(row_dict.get('promotional_alerts', True))
                }
            return {
                'daily_reports': True, 'weekly_reports': True, 'expiry_warnings': True,
                'data_warning_de': True, 'data_warning_fr': True, 'data_warning_tr': True,
                'data_warning_us': True, 'show_info_config': True, 'auto_delete_reports': False,
                'achievement_alerts': True, 'promotional_alerts': True
            }

    def update_user_setting(self, user_id: int, setting: str, value: bool) -> None:
        valid_settings = [
            'daily_reports', 'weekly_reports', 'expiry_warnings', 'show_info_config',
            'auto_delete_reports', 'achievement_alerts', 'promotional_alerts',
            'data_warning_de', 'data_warning_fr', 'data_warning_tr', 'data_warning_us'
        ]

        if setting in valid_settings:
            with self.write_conn() as c:
                c.execute(f"UPDATE users SET {setting}=? WHERE user_id=?", (int(value), user_id))
            self.clear_user_cache(user_id)
        else:
            logger.warning(f"Attempted to update an invalid setting '{setting}' for user {user_id}.")

    def add_uuid(self, user_id: int, uuid_str: str, name: str) -> any:
            uuid_str = uuid_str.lower()
            with self.write_conn() as c:
                existing_inactive_for_this_user = c.execute("SELECT * FROM user_uuids WHERE user_id = ? AND uuid = ? AND is_active = 0", (user_id, uuid_str)).fetchone()
                if existing_inactive_for_this_user:
                    c.execute("UPDATE user_uuids SET is_active = 1, name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (name, existing_inactive_for_this_user['id']))
                    return "db_msg_uuid_reactivated"

                existing_active = c.execute("SELECT * FROM user_uuids WHERE uuid = ? AND is_active = 1", (uuid_str,)).fetchone()
                if existing_active:
                    if existing_active['user_id'] == user_id:
                        return "db_err_uuid_already_active_self"
                    else:
                        return {
                            "status": "confirmation_required",
                            "owner_id": existing_active['user_id'],
                            "uuid_id": existing_active['id']
                        }

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
        with self.write_conn() as c:
            existing_inactive = c.execute("SELECT * FROM user_uuids WHERE user_id = ? AND uuid = ? AND is_active = 0", (user_id, uuid_str)).fetchone()

            if existing_inactive:
                c.execute("UPDATE user_uuids SET is_active = 1, name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (name, existing_inactive['id']))
            else:
                c.execute("INSERT INTO user_uuids (user_id, uuid, name, is_active) VALUES (?, ?, ?, 1)", (user_id, uuid_str, name))
            return True

    def uuids(self, user_id: int) -> List[Dict[str, Any]]:
        with self.write_conn() as c:
            rows = c.execute("SELECT * FROM user_uuids WHERE user_id=? AND is_active=1 ORDER BY created_at", (user_id,)).fetchall()
            return [dict(r) for r in rows]

    def uuid_by_id(self, user_id: int, uuid_id: int) -> Optional[Dict[str, Any]]:
        with self.write_conn() as c:
            row = c.execute("SELECT * FROM user_uuids WHERE user_id=? AND id=? AND is_active=1", (user_id, uuid_id)).fetchone()
            return dict(row) if row else None

    def deactivate_uuid(self, uuid_id: int) -> bool:
        with self.write_conn() as c:
            res = c.execute("UPDATE user_uuids SET is_active = 0 WHERE id = ?", (uuid_id,))
            return res.rowcount > 0

    def delete_user_by_uuid(self, uuid: str) -> None:
        with self.write_conn() as c:
            c.execute("DELETE FROM user_uuids WHERE uuid=?", (uuid,))

    def all_active_uuids(self):
        """Yields all active UUIDs along with their reminder status."""
        with self.write_conn() as c:
            cursor = c.execute("SELECT id, user_id, uuid, created_at, first_connection_time, welcome_message_sent, renewal_reminder_sent FROM user_uuids WHERE is_active=1")
            for row in cursor:
                yield dict(row)

    def get_all_user_ids(self):
        """تمام شناسه‌های کاربری را به صورت جریانی (generator) برمی‌گرداند."""
        with self.write_conn() as c:
            cursor = c.execute("SELECT user_id FROM users")
            for row in cursor:
                yield row['user_id']

    def get_all_bot_users(self):
        """تمام کاربران ربات را به صورت لیست برمی‌گرداند."""
        with self.write_conn() as c:
            cursor = c.execute("SELECT user_id, username, first_name, last_name FROM users ORDER BY user_id")
            return [dict(r) for r in cursor.fetchall()]

    def update_user_birthday(self, user_id: int, birthday_date: datetime.date):
        with self.write_conn() as c:
            c.execute("UPDATE users SET birthday = ? WHERE user_id = ?", (birthday_date, user_id))
        self.clear_user_cache(user_id) #  <-- پاک کردن کش

    def get_users_with_birthdays(self):
        """کاربران دارای تاریخ تولد را به صورت جریانی (generator) برمی‌گرداند."""
        with self.write_conn() as c:
            cursor = c.execute("""
                SELECT user_id, first_name, username, birthday FROM users
                WHERE birthday IS NOT NULL
                ORDER BY strftime('%m-%d', birthday)
            """)
            for row in cursor:
                yield dict(row)

    def get_user_id_by_uuid(self, uuid: str) -> Optional[int]:
        with self.write_conn() as c:
            row = c.execute("SELECT user_id FROM user_uuids WHERE uuid = ?", (uuid,)).fetchone()
            return row['user_id'] if row else None

    def reset_user_birthday(self, user_id: int) -> None:
        with self.write_conn() as c:
            c.execute("UPDATE users SET birthday = NULL WHERE user_id = ?", (user_id,))
        self.clear_user_cache(user_id)

    def delete_user_snapshots(self, uuid_id: int) -> int:
        with self.write_conn() as c:
            cursor = c.execute("DELETE FROM usage_snapshots WHERE uuid_id = ?", (uuid_id,))
            return cursor.rowcount

    def get_todays_birthdays(self) -> list:
        today = datetime.now(pytz.utc)
        today_month_day = f"{today.month:02d}-{today.day:02d}"
        with self.write_conn() as c:
            rows = c.execute(
                "SELECT user_id FROM users WHERE strftime('%m-%d', birthday) = ?",
                (today_month_day,)
            ).fetchall()
            return [row['user_id'] for row in rows]

    def vacuum_db(self) -> None:
        with self.write_conn() as c:
            c.execute("VACUUM")

    def get_bot_user_by_uuid(self, uuid: str) -> Optional[Dict[str, Any]]:
        query = """
            SELECT u.user_id, u.first_name, u.username
            FROM users u
            JOIN user_uuids uu ON u.user_id = uu.user_id
            WHERE uu.uuid = ?
        """
        with self.write_conn() as c:
            row = c.execute(query, (uuid,)).fetchone()
            return dict(row) if row else None

    def get_uuid_to_user_id_map(self) -> Dict[str, int]:
        with self.write_conn() as c:
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
        with self.write_conn() as c:
            rows = c.execute(query).fetchall()
            for row in rows:
                if row['uuid'] not in result_map:
                    result_map[row['uuid']] = dict(row)
        return result_map

    def delete_daily_snapshots(self, uuid_id: int) -> None:
        """Deletes all usage snapshots for a given uuid_id that were taken today (UTC)."""
        today_start_utc = datetime.now(pytz.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        with self.write_conn() as c:
            c.execute("DELETE FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ?", (uuid_id, today_start_utc))
            logger.info(f"Deleted daily snapshots for uuid_id {uuid_id}.")

    def set_first_connection_time(self, uuid_id: int, time: datetime):
        with self.write_conn() as c:
            c.execute("UPDATE user_uuids SET first_connection_time = ? WHERE id = ?", (time, uuid_id))

    def mark_welcome_message_as_sent(self, uuid_id: int):
        with self.write_conn() as c:
            c.execute("UPDATE user_uuids SET welcome_message_sent = 1 WHERE id = ?", (uuid_id,))

    def reset_welcome_message_sent(self, uuid_id: int):
        """
        Resets the welcome message sent flag for a specific UUID. Used for testing purposes.
        """
        with self.write_conn() as c:
            c.execute("UPDATE user_uuids SET welcome_message_sent = 0 WHERE id = ?", (uuid_id,))

    def add_payment_record(self, uuid_id: int) -> bool:
        """یک رکورد پرداخت برای کاربر با تاریخ فعلی ثبت می‌کند."""
        with self.write_conn() as c:
            c.execute("INSERT INTO payments (uuid_id, payment_date) VALUES (?, ?)",
                      (uuid_id, datetime.now(pytz.utc)))
            return True

    def set_renewal_reminder_sent(self, uuid_id: int):
        """Sets the renewal reminder flag to 1 (sent)."""
        with self.write_conn() as c:
            c.execute("UPDATE user_uuids SET renewal_reminder_sent = 1 WHERE id = ?", (uuid_id,))

    def reset_renewal_reminder_sent(self, uuid_id: int):
        """Resets the renewal reminder flag to 0 (not sent)."""
        with self.write_conn() as c:
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
            with self.write_conn() as c:
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
        with self.write_conn() as c:
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]

    def get_user_payment_history(self, uuid_id: int) -> List[Dict[str, Any]]:
            """تمام رکوردهای پرداخت برای یک کاربر خاص را برمی‌گرداند."""
            with self.write_conn() as c:
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
        with self.write_conn() as c:
            cursor = c.execute(query)
            for row in cursor:
                yield dict(row)

    def update_user_note(self, user_id: int, note: Optional[str]) -> None:
        """Updates or removes the admin note for a given user."""
        with self.write_conn() as c:
            c.execute("UPDATE users SET admin_note = ? WHERE user_id = ?", (note, user_id))
        self.clear_user_cache(user_id)

    def add_batch_templates(self, templates: list[str]) -> int:
        """
        لیستی از رشته‌های الگو را به صورت دسته‌ای به دیتابیس اضافه می‌کند.
        تمام ورودی‌ها، حتی تکراری، اضافه خواهند شد.
        تعداد ردیف‌های اضافه شده را برمی‌گرداند.
        """
        if not templates:
            return 0

        with self.write_conn() as c:
            cursor = c.cursor()
            cursor.executemany(
                "INSERT INTO config_templates (template_str) VALUES (?)",
                [(tpl,) for tpl in templates]
            )
            return cursor.rowcount

    def update_template(self, template_id: int, new_template_str: str):
        """محتوای یک قالب کانفیگ مشخص را در دیتابیس به‌روزرسانی می‌کند."""
        sql = "UPDATE config_templates SET template_str = ? WHERE id = ?"
        try:
            with self._conn() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (new_template_str, template_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Database error in update_template for id={template_id}: {e}")
            raise

    def get_all_config_templates(self) -> list[dict]:
        """تمام الگوهای کانفیگ تعریف شده توسط ادمین را برمی‌گرداند."""
        with self.write_conn() as c:
            rows = c.execute("SELECT * FROM config_templates ORDER BY id DESC").fetchall()
            return [dict(r) for r in rows]

    def get_active_config_templates(self) -> list[dict]:
        """فقط الگوهای کانفیگ فعال را برمی‌گرداند."""
        with self.write_conn() as c:
            rows = c.execute("SELECT * FROM config_templates WHERE is_active = 1").fetchall()
            return [dict(r) for r in rows]

    def toggle_template_status(self, template_id: int) -> None:
        """وضعیت فعال/غیرفعال یک الگو را تغییر می‌دهد."""
        with self.write_conn() as c:
            c.execute("UPDATE config_templates SET is_active = 1 - is_active WHERE id = ?", (template_id,))

    def delete_template(self, template_id: int) -> None:
        """یک الگو و تمام کانفیگ‌های تولید شده از آن را حذف می‌کند."""
        with self.write_conn() as c:
            c.execute("DELETE FROM config_templates WHERE id = ?", (template_id,))

    def get_user_config(self, user_uuid_id: int, template_id: int) -> dict | None:
        """کانفیگ تولید شده برای یک کاربر و یک الگوی خاص را بازیابی می‌کند."""
        with self.write_conn() as c:
            row = c.execute(
                "SELECT * FROM user_generated_configs WHERE user_uuid_id = ? AND template_id = ?",
                (user_uuid_id, template_id)
            ).fetchone()
            return dict(row) if row else None

    def add_user_config(self, user_uuid_id: int, template_id: int, generated_uuid: str) -> None:
        """یک رکورد جدید برای UUID تولید شده ثبت می‌کند."""
        with self.write_conn() as c:
            c.execute(
                "INSERT INTO user_generated_configs (user_uuid_id, template_id, generated_uuid) VALUES (?, ?, ?)",
                (user_uuid_id, template_id, generated_uuid)
            )

    def get_user_uuid_record(self, uuid_str: str) -> dict | None:
        """اطلاعات کامل یک رکورد UUID را بر اساس رشته آن برمی‌گرداند."""
        with self.write_conn() as c:
            row = c.execute("SELECT * FROM user_uuids WHERE uuid = ? AND is_active = 1", (uuid_str,)).fetchone()
            return dict(row) if row else None

    def get_all_user_uuids(self) -> List[Dict[str, Any]]:
        """
        تمام رکوردهای UUID را از دیتابیس برمی‌گرداند.
        این تابع برای پنل ادمین جهت نمایش همه کاربران استفاده می‌شود.
        """
        with self.write_conn() as c:
            query = """
                SELECT id, user_id, uuid, name, is_active, created_at, is_vip, 
                       has_access_de, has_access_fr, has_access_tr, has_access_us
                FROM user_uuids
                ORDER BY created_at DESC
            """
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]

    def check_connection(self) -> bool:
        """بررسی می‌کند که آیا اتصال به دیتابیس برقرار است یا نه."""
        try:
            with self.write_conn() as c:
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
        with self.write_conn() as c:
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
        این نسخه برای تک تک روزهای گذشته نیز محاسبات را به صورت دقیق انجام می‌دهد.
        """
        tehran_tz = pytz.timezone("Asia/Tehran")
        now_in_tehran = datetime.now(tehran_tz)
        summary = []

        with self.write_conn() as c:
            for i in range(days - 1, -1, -1):
                target_date = now_in_tehran.date() - timedelta(days=i)
                day_start_utc = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tehran_tz).astimezone(pytz.utc)
                day_end_utc = day_start_utc + timedelta(days=1)

                prev_day_snapshots_query = """
                    SELECT uuid_id, hiddify_usage_gb, marzban_usage_gb
                    FROM (
                        SELECT uuid_id, hiddify_usage_gb, marzban_usage_gb,
                            ROW_NUMBER() OVER(PARTITION BY uuid_id ORDER BY taken_at DESC) as rn
                        FROM usage_snapshots
                        WHERE taken_at < ?
                    )
                    WHERE rn = 1
                """
                prev_day_rows = c.execute(prev_day_snapshots_query, (day_start_utc,)).fetchall()
                baseline_usage = {row['uuid_id']: {'h_start': row['hiddify_usage_gb'], 'm_start': row['marzban_usage_gb']} for row in prev_day_rows}

                daily_snapshots_query = """
                    SELECT uuid_id, hiddify_usage_gb, marzban_usage_gb,
                        ROW_NUMBER() OVER(PARTITION BY uuid_id ORDER BY taken_at ASC) as rn_asc,
                        ROW_NUMBER() OVER(PARTITION BY uuid_id ORDER BY taken_at DESC) as rn_desc
                    FROM usage_snapshots
                    WHERE taken_at >= ? AND taken_at < ?
                """
                daily_rows = c.execute(daily_snapshots_query, (day_start_utc, day_end_utc)).fetchall()

                daily_usage_by_user = {}
                for row in daily_rows:
                    uuid_id = row['uuid_id']
                    if uuid_id not in daily_usage_by_user:
                        daily_usage_by_user[uuid_id] = {}

                    if row['rn_asc'] == 1:
                        daily_usage_by_user[uuid_id]['h_first'] = row['hiddify_usage_gb']
                        daily_usage_by_user[uuid_id]['m_first'] = row['marzban_usage_gb']

                    if row['rn_desc'] == 1:
                        daily_usage_by_user[uuid_id]['h_end'] = row['hiddify_usage_gb']
                        daily_usage_by_user[uuid_id]['m_end'] = row['marzban_usage_gb']

                day_total_gb = 0.0
                for uuid_id, daily_data in daily_usage_by_user.items():
                    baseline = baseline_usage.get(uuid_id)

                    h_start = baseline['h_start'] if baseline else daily_data.get('h_first', 0.0)
                    m_start = baseline['m_start'] if baseline else daily_data.get('m_first', 0.0)

                    h_end = daily_data.get('h_end', 0.0)
                    m_end = daily_data.get('m_end', 0.0)

                    h_diff = (h_end or 0.0) - (h_start or 0.0)
                    m_diff = (m_end or 0.0) - (m_start or 0.0)

                    day_total_gb += max(0, h_diff)
                    day_total_gb += max(0, m_diff)

                summary.append({
                    'date': target_date.strftime('%Y-%m-%d'),
                    'total_gb': round(day_total_gb, 2)
                })

        return summary

    def update_config_name(self, uuid_id: int, new_name: str) -> bool:
        """نام نمایشی یک کانفیگ (UUID) را در دیتابیس تغییر می‌دهد."""
        if not new_name or len(new_name) < 2:
            return False

        with self.write_conn() as c:
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
        with self.write_conn() as c:
            rows = c.execute(query, (date_limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_new_users_per_month_stats(self, months: int = 6) -> List[Dict[str, Any]]:
        """آمار کاربران جدید در هر ماه را برای نمودار باز می‌گرداند."""
        query = f"""
            SELECT
                strftime('%Y-%m', created_at) as month,
                COUNT(id) as count
            FROM user_uuids
            GROUP BY month
            ORDER BY month DESC
            LIMIT {months};
        """
        with self.write_conn() as c:
            rows = c.execute(query).fetchall()
            return [dict(r) for r in reversed(rows)]

    def get_revenue_by_month(self, months: int = 6) -> List[Dict[str, Any]]:
        """درآمد ماهانه را برای نمودار MRR محاسبه می‌کند."""
        query = f"""
            SELECT
                strftime('%Y-%m', payment_date) as month,
                COUNT(payment_id) as revenue_unit
            FROM payments
            GROUP BY month
            ORDER BY month DESC
            LIMIT {months};
        """
        with self.write_conn() as c:
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
        with self.write_conn() as c:
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
        with self.write_conn() as c:
            rows = c.execute(query, (date_limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_new_users_in_range(self, start_date: datetime, end_date: datetime) -> int:
        """تعداد کاربران جدید در یک بازه زمانی را برمی‌گرداند."""
        with self.write_conn() as c:
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
            with self.write_conn() as c:
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
        with self.write_conn() as c:
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
        with self.write_conn() as c:
            rows = c.execute(query, (date_limit,)).fetchall()
            return [dict(r) for r in rows]

    def toggle_user_vip(self, uuid: str) -> None:
        """وضعیت VIP یک کاربر را بر اساس UUID تغییر می‌دهد."""
        with self.write_conn() as c:
            c.execute("UPDATE user_uuids SET is_vip = 1 - is_vip WHERE uuid = ?", (uuid,))

    def toggle_template_special(self, template_id: int) -> None:
        """وضعیت "ویژه" بودن یک قالب کانفیگ را تغییر می‌دهد."""
        with self.write_conn() as c:
            c.execute("UPDATE config_templates SET is_special = 1 - is_special WHERE id = ?", (template_id,))

    def set_template_server_type(self, template_id: int, server_type: str) -> None:
        """نوع سرور یک قالب کانفیگ را تنظیم می‌کند."""
        if server_type not in ['de', 'fr', 'tr', 'us', 'none']:
            return
        with self.write_conn() as c:
            c.execute("UPDATE config_templates SET server_type = ? WHERE id = ?", (server_type, template_id))

    def reset_templates_table(self) -> None:
        """تمام رکوردها را از جدول config_templates حذف کرده و شمارنده ID را ریست می‌کند."""
        with self.write_conn() as c:
            c.execute("DELETE FROM config_templates;")
            c.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'config_templates';")
        logger.info("Config templates table has been reset.")

    def set_user_language(self, user_id: int, lang_code: str):
        """زبان انتخابی کاربر را در دیتابیس ذخیره می‌کند."""
        with self.write_conn() as c:
            try:
                cursor = c.execute("UPDATE users SET lang_code = ? WHERE user_id = ?", (lang_code, user_id))
                if cursor.rowcount > 0:
                    logger.info(f"DB WRITE: Successfully set lang_code='{lang_code}' for user_id={user_id}.")
                else:
                    logger.warning(f"DB WRITE: UPDATE for lang_code failed. No rows affected for user_id={user_id}.")
            except Exception as e:
                logger.error(f"DB WRITE: FAILED to set lang_code for user_id={user_id}. Error: {e}", exc_info=True)
        self.clear_user_cache(user_id)

    def get_user_language(self, user_id: int) -> str:
        """کد زبان کاربر را از دیتابیس می‌خواند."""
        with self._conn() as c:
            row = c.execute("SELECT lang_code FROM users WHERE user_id = ?", (user_id,)).fetchone()
            lang_code = row['lang_code'] if row and row['lang_code'] else 'fa'

            return lang_code

    def add_marzban_mapping(self, hiddify_uuid: str, marzban_username: str) -> bool:
        """یک ارتباط جدید بین UUID هیدیفای و یوزرنیم مرزبان اضافه یا جایگزین می‌کند."""
        with self.write_conn() as c:
            try:
                c.execute("INSERT OR REPLACE INTO marzban_mapping (hiddify_uuid, marzban_username) VALUES (?, ?)", (hiddify_uuid.lower(), marzban_username))
                return True
            except sqlite3.IntegrityError:
                logger.warning(f"Marzban username '{marzban_username}' might already be mapped.")
                return False

    def get_marzban_username_by_uuid(self, hiddify_uuid: str) -> Optional[str]:
        """یوزرنیم مرزبان را بر اساس UUID هیدیفای از دیتابیس دریافت می‌کند."""
        with self.write_conn() as c:
            row = c.execute("SELECT marzban_username FROM marzban_mapping WHERE hiddify_uuid = ?", (hiddify_uuid.lower(),)).fetchone()
            return row['marzban_username'] if row else None

    def get_uuid_by_marzban_username(self, marzban_username: str) -> Optional[str]:
        """UUID هیدیفای را بر اساس یوزرنیم مرزبان از دیتابیس دریافت می‌کند."""
        with self.write_conn() as c:
            row = c.execute("SELECT hiddify_uuid FROM marzban_mapping WHERE marzban_username = ?", (marzban_username,)).fetchone()
            return row['hiddify_uuid'] if row else None

    def get_all_marzban_mappings(self) -> List[Dict[str, str]]:
        """تمام ارتباط‌های مرزبان را برای نمایش در پنل وب برمی‌گرداند."""
        with self.write_conn() as c:
            rows = c.execute("SELECT hiddify_uuid, marzban_username FROM marzban_mapping ORDER BY marzban_username").fetchall()
            return [dict(r) for r in rows]

    def delete_marzban_mapping(self, hiddify_uuid: str) -> bool:
        """یک ارتباط را بر اساس UUID هیدیفای حذف می‌کند."""
        with self.write_conn() as c:
            res = c.execute("DELETE FROM marzban_mapping WHERE hiddify_uuid = ?", (hiddify_uuid.lower(),))
            return res.rowcount > 0

    def purge_user_by_telegram_id(self, user_id: int) -> bool:
        """
        یک کاربر را به طور کامل از جدول users بر اساس شناسه تلگرام حذف می‌کند.
        به دلیل وجود ON DELETE CASCADE، تمام رکوردهای مرتبط نیز حذف خواهند شد.
        """
        with self.write_conn() as c:
            cursor = c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            self.clear_user_cache(user_id)
            return cursor.rowcount > 0

    def get_user_daily_usage_history(self, uuid_id: int, days: int = 7) -> list:
        """تاریخچه مصرف روزانه یک کاربر را برای تعداد روز مشخص شده برمی‌گرداند."""
        tehran_tz = pytz.timezone("Asia/Tehran")
        history = []
        with self.write_conn() as c:
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
        with self.write_conn() as c:
            c.execute("INSERT INTO login_tokens (token, uuid) VALUES (?, ?)", (token, user_uuid))
        return token

    def validate_login_token(self, token: str) -> Optional[str]:
        """یک توکن را اعتبارسنجی کرده و در صورت اعتبار، UUID کاربر را برمی‌گرداند."""
        five_minutes_ago = datetime.now(pytz.utc) - timedelta(minutes=5)
        with self.write_conn() as c:
            c.execute("DELETE FROM login_tokens WHERE created_at < ?", (five_minutes_ago,))

            row = c.execute("SELECT uuid FROM login_tokens WHERE token = ?", (token,)).fetchone()
            if row:
                c.execute("DELETE FROM login_tokens WHERE token = ?", (token,))
                return row['uuid']
        return None

    def delete_old_snapshots(self, days_to_keep: int = 3) -> int:
        """Deletes usage snapshots older than a specified number of days."""
        time_limit = datetime.now(pytz.utc) - timedelta(days=days_to_keep)
        with self.write_conn() as c:
            cursor = c.execute("DELETE FROM usage_snapshots WHERE taken_at < ?", (time_limit,))
            logger.info(f"Cleaned up {cursor.rowcount} old usage snapshots (older than {days_to_keep} days).")
            return cursor.rowcount

    def add_panel(self, name: str, panel_type: str, api_url: str, token1: str, token2: Optional[str] = None) -> bool:
        """Adds a new panel to the database."""
        with self.write_conn() as c:
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
        with self.write_conn() as c:
            rows = c.execute("SELECT * FROM panels ORDER BY name ASC").fetchall()
            return [dict(r) for r in rows]

    def get_active_panels(self) -> List[Dict[str, Any]]:
        """Retrieves only the active panels from the database."""
        with self.write_conn() as c:
            rows = c.execute("SELECT * FROM panels WHERE is_active = 1 ORDER BY name ASC").fetchall()
            return [dict(r) for r in rows]

    def delete_panel(self, panel_id: int) -> bool:
        """Deletes a panel by its ID."""
        with self.write_conn() as c:
            cursor = c.execute("DELETE FROM panels WHERE id = ?", (panel_id,))
            return cursor.rowcount > 0

    def toggle_panel_status(self, panel_id: int) -> bool:
        """Toggles the active status of a panel."""
        with self.write_conn() as c:
            cursor = c.execute("UPDATE panels SET is_active = 1 - is_active WHERE id = ?", (panel_id,))
            return cursor.rowcount > 0

    def get_panel_by_id(self, panel_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a single panel's details by its ID."""
        with self.write_conn() as c:
            row = c.execute("SELECT * FROM panels WHERE id = ?", (panel_id,)).fetchone()
            return dict(row) if row else None

    def update_panel_name(self, panel_id: int, new_name: str) -> bool:
        """Updates the name of a specific panel."""
        with self.write_conn() as c:
            try:
                cursor = c.execute("UPDATE panels SET name = ? WHERE id = ?", (new_name, panel_id))
                return cursor.rowcount > 0
            except sqlite3.IntegrityError:
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
                uu.has_access_us,
                -- Check if a mapping exists for the user's UUID
                CASE WHEN mm.hiddify_uuid IS NOT NULL THEN 1 ELSE 0 END as is_on_marzban
            FROM users u
            JOIN user_uuids uu ON u.user_id = uu.user_id
            -- Use LEFT JOIN to include all users from user_uuids, even if they don't have a mapping
            LEFT JOIN marzban_mapping mm ON uu.uuid = mm.hiddify_uuid
            WHERE uu.is_active = 1
            ORDER BY u.user_id, uu.created_at;
        """
        with self.write_conn() as c:
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]

    def update_user_server_access(self, uuid_id: int, server: str, status: bool) -> bool:
        """Updates a user's access status for a specific server."""
        if server not in ['de', 'fr', 'tr', 'us']:
            return False

        column_name = f"has_access_{server}"

        with self.write_conn() as c:
            cursor = c.execute(
                f"UPDATE user_uuids SET {column_name} = ? WHERE id = ?",
                (int(status), uuid_id)
            )
            return cursor.rowcount > 0

    def get_panel_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single panel's details by its unique name."""
        with self.write_conn() as c:
            row = c.execute("SELECT * FROM panels WHERE name = ?", (name,)).fetchone()
            return dict(row) if row else None

    def toggle_template_random_pool(self, template_id: int) -> bool:
        """وضعیت عضویت یک قالب در استخر انتخاب تصادفی را تغییر می‌دهد."""
        with self.write_conn() as c:
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
        with self.write_conn() as c:
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
        with self.write_conn() as c:
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
        with self.write_conn() as c:
            rows = c.execute(query, (time_limit,)).fetchall()
            return [dict(r) for r in rows]

    def delete_sent_report_record(self, record_id: int):
        """یک رکورد را از جدول sent_reports پس از تلاش برای حذف، پاک می‌کند."""
        with self.write_conn() as c:
            c.execute("DELETE FROM sent_reports WHERE id = ?", (record_id,))

    def get_sent_warnings_since_midnight(self) -> list:
        """
        گزارشی از هشدارهایی که از نیمه‌شب امروز ارسال شده‌اند را برمی‌گرداند.
        (نسخه نهایی: UUID برای شناسایی دقیق کاربر اضافه شده است)
        """
        tehran_tz = pytz.timezone("Asia/Tehran")
        today_midnight_tehran = datetime.now(tehran_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        today_midnight_utc = today_midnight_tehran.astimezone(pytz.utc)

        query = """
            SELECT
                uu.name,
                uu.uuid,
                wl.warning_type
            FROM warning_log wl
            JOIN user_uuids uu ON wl.uuid_id = uu.id
            WHERE wl.sent_at >= ?
            ORDER BY uu.name;
        """
        with self.write_conn() as c:
            rows = c.execute(query, (today_midnight_utc,)).fetchall()
            return [dict(r) for r in rows]

    def record_user_agent(self, uuid_id: int, user_agent: str):
        """(نسخه نهایی) به صورت هوشمند دستگاه را ثبت یا به‌روزرسانی می‌کند."""
        from .utils import parse_user_agent

        new_parsed = parse_user_agent(user_agent)
        if not new_parsed or not new_parsed.get('client'):
            return

        existing_agents = self.get_user_agents_for_uuid(uuid_id)

        for agent in existing_agents:
            existing_parsed = parse_user_agent(agent['user_agent'])
            if existing_parsed and existing_parsed.get('client') == new_parsed.get('client') and existing_parsed.get('os') == new_parsed.get('os'):
                with self.write_conn() as c:
                    c.execute("""
                        UPDATE client_user_agents
                        SET user_agent = ?, last_seen = ?
                        WHERE uuid_id = ? AND user_agent = ?
                    """, (user_agent, datetime.now(pytz.utc), uuid_id, agent['user_agent']))
                return

        with self.write_conn() as c:
            c.execute("""
                INSERT INTO client_user_agents (uuid_id, user_agent, last_seen)
                VALUES (?, ?, ?)
                ON CONFLICT(uuid_id, user_agent) DO UPDATE SET
                last_seen = excluded.last_seen;
            """, (uuid_id, user_agent, datetime.now(pytz.utc)))

    def delete_all_user_agents(self) -> int:
        """تمام رکوردهای دستگاه‌های ثبت‌شده را از دیتابیس حذف می‌کند."""
        with self.write_conn() as c:
            cursor = c.execute("DELETE FROM client_user_agents;")
            try:
                c.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'client_user_agents';")
            except sqlite3.OperationalError:
                pass
            return cursor.rowcount

    def get_user_agents_for_uuid(self, uuid_id: int) -> List[Dict[str, Any]]:
        """Retrieves all recorded user agents for a specific user UUID, ordered by last seen."""
        with self.write_conn() as c:
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
        with self.write_conn() as c:
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]

    def count_user_agents(self, uuid_id: int) -> int:
            """Counts the number of recorded user agents for a specific user UUID."""
            with self.write_conn() as c:
                row = c.execute("SELECT COUNT(id) FROM client_user_agents WHERE uuid_id = ?", (uuid_id,)).fetchone()
            return row[0] if row else 0

    def delete_user_agents_by_uuid_id(self, uuid_id: int) -> int:
        """Deletes all user agent records for a given uuid_id."""
        with self.write_conn() as c:
            cursor = c.execute("DELETE FROM client_user_agents WHERE uuid_id = ?", (uuid_id,))
            return cursor.rowcount

    def log_traffic_transfer(self, sender_uuid_id: int, receiver_uuid_id: int, panel_type: str, amount_gb: float):
        """یک رکورد جدید برای انتقال ترافیک ثبت می‌کند."""
        with self.write_conn() as c:
            c.execute(
                "INSERT INTO traffic_transfers (sender_uuid_id, receiver_uuid_id, panel_type, amount_gb, transferred_at) VALUES (?, ?, ?, ?, ?)",
                (sender_uuid_id, receiver_uuid_id, panel_type, amount_gb, datetime.now(pytz.utc))
            )

    def has_transferred_in_last_30_days(self, sender_uuid_id: int) -> bool:
        """بررسی می‌کند آیا کاربر در ۳۰ روز گذشته انتقالی داشته است یا خیر."""
        thirty_days_ago = datetime.now(pytz.utc) - timedelta(days=30)
        with self.write_conn() as c:
            row = c.execute(
                "SELECT 1 FROM traffic_transfers WHERE sender_uuid_id = ? AND transferred_at >= ?",
                (sender_uuid_id, thirty_days_ago)
            ).fetchone()
            return row is not None

    def add_achievement(self, user_id: int, badge_code: str) -> bool:
        """یک دستاورد جدید برای کاربر ثبت می‌کند و در صورت موفقیت True برمی‌گرداند."""
        with self.write_conn() as c:
            try:
                c.execute(
                    "INSERT INTO user_achievements (user_id, badge_code) VALUES (?, ?)",
                    (user_id, badge_code)
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def get_user_achievements(self, user_id: int) -> List[str]:
        """لیست کدهای تمام نشان‌های یک کاربر را برمی‌گرداند."""
        with self.write_conn() as c:
            rows = c.execute("SELECT badge_code FROM user_achievements WHERE user_id = ?", (user_id,)).fetchall()
            return [row['badge_code'] for row in rows]

    def get_total_usage_in_last_n_days(self, uuid_id: int, days: int) -> float:
        """مجموع کل مصرف یک کاربر در N روز گذشته را محاسبه می‌کند."""
        time_limit = datetime.now(pytz.utc) - timedelta(days=days)
        with self.write_conn() as c:
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

        with self.write_conn() as c:
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
        
        results = {'hiddify': 0, 'marzban_fr': 0, 'marzban_tr': 0, 'marzban_us': 0}
        active_users = {'hiddify': set(), 'marzban_fr': set(), 'marzban_tr': set(), 'marzban_us': set()}

        with self.write_conn() as c:
            all_uuids = c.execute("SELECT id FROM user_uuids WHERE is_active = 1").fetchall()
            uuid_ids = [row['id'] for row in all_uuids]

            for uuid_id in uuid_ids:
                snapshots = c.execute(
                    """
                    SELECT s.hiddify_usage_gb, s.marzban_usage_gb, s.taken_at, uu.has_access_fr, uu.has_access_tr, uu.has_access_us
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
                    if latest_snap['has_access_us']:
                        active_users['marzban_us'].add(uuid_id)

        results['hiddify'] = len(active_users['hiddify'])
        results['marzban_fr'] = len(active_users['marzban_fr'])
        results['marzban_tr'] = len(active_users['marzban_tr'])
        results['marzban_us'] = len(active_users['marzban_us'])
        return results

    def get_or_create_referral_code(self, user_id: int) -> str:
        """کد معرف کاربر را برمی‌گرداند یا اگر وجود نداشته باشد، یکی برای او می‌سازد."""
        with self.write_conn() as c:
            row = c.execute("SELECT referral_code FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if row and row['referral_code']:
                return row['referral_code']
            else:
                while True:
                    new_code = "REF-" + secrets.token_urlsafe(4).upper().replace("_", "").replace("-", "")
                    if not c.execute("SELECT 1 FROM users WHERE referral_code = ?", (new_code,)).fetchone():
                        c.execute("UPDATE users SET referral_code = ? WHERE user_id = ?", (new_code, user_id))
                        self.clear_user_cache(user_id)
                        return new_code

    def set_referrer(self, user_id: int, referrer_code: str):
        """کاربر معرف را برای یک کاربر جدید ثبت می‌کند."""
        with self.write_conn() as c:
            referrer = c.execute("SELECT user_id FROM users WHERE referral_code = ?", (referrer_code,)).fetchone()
            if referrer:
                c.execute("UPDATE users SET referred_by_user_id = ? WHERE user_id = ?", (referrer['user_id'], user_id))
                logger.info(f"User {user_id} was referred by user {referrer['user_id']} (code: {referrer_code}).")
                self.clear_user_cache(user_id)

    def get_referrer_info(self, user_id: int) -> Optional[dict]:
        """اطلاعات کاربر معرف را (در صورت وجود) برمی‌گرداند."""
        with self.write_conn() as c:
            row = c.execute("""
                SELECT u.referred_by_user_id, u.referral_reward_applied, r.first_name as referrer_name
                FROM users u
                JOIN users r ON u.referred_by_user_id = r.user_id
                WHERE u.user_id = ?
            """, (user_id,)).fetchone()
            return dict(row) if row else None

    def mark_referral_reward_as_applied(self, user_id: int):
        """وضعیت پاداش معرفی را برای جلوگیری از اهدای مجدد، ثبت می‌کند."""
        with self.write_conn() as c:
            c.execute("UPDATE users SET referral_reward_applied = 1 WHERE user_id = ?", (user_id,))
        self.clear_user_cache(user_id)

    def get_last_transfer_timestamp(self, sender_uuid_id: int) -> Optional[datetime]:
        """آخرین زمان انتقال ترافیک توسط یک کاربر را برمی‌گرداند."""
        with self.write_conn() as c:
            row = c.execute(
                "SELECT transferred_at FROM traffic_transfers WHERE sender_uuid_id = ? ORDER BY transferred_at DESC LIMIT 1",
                (sender_uuid_id,)
            ).fetchone()
            return row['transferred_at'] if row else None

    def delete_transfer_history(self, sender_uuid_id: int) -> int:
        """تمام تاریخچه انتقال یک کاربر خاص را برای ریست کردن محدودیت حذف می‌کند."""
        with self.write_conn() as c:
            cursor = c.execute("DELETE FROM traffic_transfers WHERE sender_uuid_id = ?", (sender_uuid_id,))
            return cursor.rowcount

    def get_weekly_top_consumers_report(self) -> dict:
        """
        (نسخه نهایی و اصلاح شده) گزارشی از پرمصرف‌ترین کاربران هفته و هر روز هفته را با محاسبه دقیق مصرف بر اساس شناسه کاربری تلگرام (user_id) برمی‌گرداند تا از شمارش تکراری جلوگیری شود.
        """
        tehran_tz = pytz.timezone("Asia/Tehran")
        today_jalali = jdatetime.datetime.now(tz=tehran_tz)
        days_since_saturday = (today_jalali.weekday() + 1) % 7
        week_start_utc = (datetime.now(tehran_tz) - timedelta(days=days_since_saturday)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.utc)

        report = {'top_10_overall': [], 'top_daily': {}}

        weekly_usage_by_uuid = {}
        daily_usage_by_uuid = {i: {} for i in range(7)}

        with self.write_conn() as c:
            all_snapshots_query = "SELECT uuid_id, hiddify_usage_gb, marzban_usage_gb, taken_at FROM usage_snapshots WHERE taken_at >= ? ORDER BY uuid_id, taken_at ASC;"
            all_week_snapshots = c.execute(all_snapshots_query, (week_start_utc,)).fetchall()

            snapshots_by_user = {}
            for snap in all_week_snapshots:
                snapshots_by_user.setdefault(snap['uuid_id'], []).append(snap)

            for uuid_id, user_snaps in snapshots_by_user.items():
                last_snap_before = c.execute("SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1", (uuid_id, week_start_utc)).fetchone()

                last_h = last_snap_before['hiddify_usage_gb'] if last_snap_before and last_snap_before['hiddify_usage_gb'] is not None else 0.0
                last_m = last_snap_before['marzban_usage_gb'] if last_snap_before and last_snap_before['marzban_usage_gb'] is not None else 0.0

                for snap in user_snaps:
                    h_diff = max(0, (snap['hiddify_usage_gb'] or 0.0) - last_h)
                    m_diff = max(0, (snap['marzban_usage_gb'] or 0.0) - last_m)
                    total_diff = h_diff + m_diff

                    weekly_usage_by_uuid.setdefault(uuid_id, 0.0)
                    weekly_usage_by_uuid[uuid_id] += total_diff

                    snap_date_local = snap['taken_at'].astimezone(tehran_tz)
                    day_of_week_jalali = (jdatetime.datetime.fromgregorian(datetime=snap_date_local).weekday() + 1) % 7
                    daily_usage_by_uuid[day_of_week_jalali].setdefault(uuid_id, 0.0)
                    daily_usage_by_uuid[day_of_week_jalali][uuid_id] += total_diff

                    last_h, last_m = snap['hiddify_usage_gb'] or 0.0, snap['marzban_usage_gb'] or 0.0

        user_id_map = {row['id']: row['user_id'] for row in self.get_all_user_uuids()}
        user_info_map = {user['user_id']: user for user in self.get_all_bot_users()}

        weekly_usage_by_user_id = {}
        for uuid_id, total_usage in weekly_usage_by_uuid.items():
            user_id = user_id_map.get(uuid_id)
            if user_id:
                weekly_usage_by_user_id.setdefault(user_id, 0.0)
                weekly_usage_by_user_id[user_id] += total_usage

        sorted_weekly_by_user_id = sorted(weekly_usage_by_user_id.items(), key=lambda item: item[1], reverse=True)
        for user_id, total_usage in sorted_weekly_by_user_id[:10]:
            if total_usage > 0.01:
                user_info = user_info_map.get(user_id)
                user_name = user_info.get('first_name', 'کاربر ناشناس') if user_info else 'کاربر ناشناس'
                report['top_10_overall'].append({'name': user_name, 'total_usage': total_usage})

        for day_index, daily_data in daily_usage_by_uuid.items():
            if not daily_data: continue

            daily_usage_by_user_id = {}
            for uuid_id, usage in daily_data.items():
                user_id = user_id_map.get(uuid_id)
                if user_id:
                    daily_usage_by_user_id.setdefault(user_id, 0.0)
                    daily_usage_by_user_id[user_id] += usage

            if not daily_usage_by_user_id: continue

            top_user_id = max(daily_usage_by_user_id, key=daily_usage_by_user_id.get)
            top_usage = daily_usage_by_user_id[top_user_id]

            if top_usage > 0.01:
                top_user_info = user_info_map.get(top_user_id)
                top_user_name = top_user_info.get('first_name', 'کاربر ناشناس') if top_user_info else 'کاربر ناشناس'
                report['top_daily'][day_index] = {'name': top_user_name, 'usage': top_usage}

        return report

    def add_achievement_points(self, user_id: int, points: int):
            """امتیاز به حساب یک کاربر اضافه می‌کند."""
            with self.write_conn() as c:
                c.execute("UPDATE users SET achievement_points = achievement_points + ? WHERE user_id = ?", (points, user_id))
            self.clear_user_cache(user_id) #  <-- پاک کردن کش

    def spend_achievement_points(self, user_id: int, points: int) -> bool:
        """امتیاز را از حساب کاربر کم می‌کند و موفقیت عملیات را برمی‌گرداند."""
        with self.write_conn() as c:
            current_points = c.execute("SELECT achievement_points FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if current_points and current_points['achievement_points'] >= points:
                c.execute("UPDATE users SET achievement_points = achievement_points - ? WHERE user_id = ?", (points, user_id))
                self.clear_user_cache(user_id) #  <-- پاک کردن کش
                return True
            return False

    def log_shop_purchase(self, user_id: int, item_key: str, cost: int):
        """یک خرید از فروشگاه را در دیتابیس ثبت می‌کند."""
        with self.write_conn() as c:
            c.execute("INSERT INTO achievement_shop_log (user_id, item_key, cost) VALUES (?, ?, ?)", (user_id, item_key, cost))

    def get_achievement_leaderboard(self, limit: int = 10) -> list[dict]:
        """لیستی از کاربران برتر بر اساس امتیاز دستاوردها را برمی‌گرداند."""
        with self.write_conn() as c:
            rows = c.execute(
                "SELECT user_id, first_name, achievement_points FROM users WHERE achievement_points > 0 ORDER BY achievement_points DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_users_by_points(self) -> List[Dict[str, Any]]:
        """
        (نسخه نهایی) تمام کاربرانی که امتیاز دارند را به همراه لیست نشان‌هایشان
        به ترتیب امتیاز برمی‌گرداند.
        """
        with self.write_conn() as c:
            query = """
                SELECT
                    u.user_id,
                    u.first_name,
                    u.achievement_points,
                    GROUP_CONCAT(ua.badge_code) as badges
                FROM users u
                LEFT JOIN user_achievements ua ON u.user_id = ua.user_id
                WHERE u.achievement_points > 0
                GROUP BY u.user_id
                ORDER BY u.achievement_points DESC
            """
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]

    def get_referred_users(self, referrer_user_id: int) -> list[dict]:
            """لیست کاربرانی که توسط یک کاربر خاص معرفی شده‌اند را برمی‌گرداند."""
            with self.write_conn() as c:
                rows = c.execute(
                    "SELECT user_id, first_name, referral_reward_applied FROM users WHERE referred_by_user_id = ?",
                    (referrer_user_id,)
                ).fetchall()
                return [dict(r) for r in rows]

    def delete_all_daily_snapshots(self) -> int:
        """تمام اسنپ‌شات‌های مصرف امروز (به وقت UTC) را برای همه کاربران حذف می‌کند."""
        today_start_utc = datetime.now(pytz.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        with self.write_conn() as c:
            cursor = c.execute("DELETE FROM usage_snapshots WHERE taken_at >= ?", (today_start_utc,))
            deleted_count = cursor.rowcount
            logger.info(f"ADMIN ACTION: Deleted {deleted_count} daily snapshots for all users.")
            return deleted_count

    def get_daily_achievements(self) -> list[dict]:
            """کاربرانی که امروز دستاوردی کسب کرده‌اند را به همراه جزئیات برمی‌گرداند."""
            tehran_tz = pytz.timezone("Asia/Tehran")
            today_midnight_tehran = datetime.now(tehran_tz).replace(hour=0, minute=0, second=0, microsecond=0)
            today_midnight_utc = today_midnight_tehran.astimezone(pytz.utc)

            query = """
                SELECT
                    u.user_id,
                    u.first_name,
                    ua.badge_code
                FROM user_achievements ua
                JOIN users u ON ua.user_id = u.user_id
                WHERE ua.awarded_at >= ?
                ORDER BY u.user_id;
            """
            with self.write_conn() as c:
                rows = c.execute(query, (today_midnight_utc,)).fetchall()
                return [dict(r) for r in rows]

    def get_weekly_usage_by_time_of_day(self, uuid_id: int) -> dict:
            """مصرف هفتگی کاربر را به تفکیک بازه‌های زمانی روز محاسبه می‌کند."""
            tehran_tz = pytz.timezone("Asia/Tehran")
            today_jalali = jdatetime.datetime.now(tz=tehran_tz)
            days_since_saturday = (today_jalali.weekday() + 1) % 7
            week_start_utc = (datetime.now(tehran_tz) - timedelta(days=days_since_saturday)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.utc)

            with self.write_conn() as c:
                query = "SELECT hiddify_usage_gb, marzban_usage_gb, taken_at FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ? ORDER BY taken_at ASC"
                snapshots = c.execute(query, (uuid_id, week_start_utc)).fetchall()

                time_of_day_usage = {"morning": 0.0, "afternoon": 0.0, "evening": 0.0, "night": 0.0}

                prev_snap = c.execute("SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1", (uuid_id, week_start_utc)).fetchone()
                last_h = prev_snap['hiddify_usage_gb'] if prev_snap and prev_snap['hiddify_usage_gb'] else 0.0
                last_m = prev_snap['marzban_usage_gb'] if prev_snap and prev_snap['marzban_usage_gb'] else 0.0

                for snap in snapshots:
                    h_diff = max(0, (snap['hiddify_usage_gb'] or 0.0) - last_h)
                    m_diff = max(0, (snap['marzban_usage_gb'] or 0.0) - last_m)
                    diff = h_diff + m_diff

                    snap_time_tehran = snap['taken_at'].astimezone(tehran_tz)
                    hour = snap_time_tehran.hour

                    if 6 <= hour < 12:
                        time_of_day_usage["morning"] += diff
                    elif 12 <= hour < 18:
                        time_of_day_usage["afternoon"] += diff
                    elif 18 <= hour < 22:
                        time_of_day_usage["evening"] += diff
                    else: # 22:00 to 05:59
                        time_of_day_usage["night"] += diff

                    last_h, last_m = snap['hiddify_usage_gb'] or 0.0, snap['marzban_usage_gb'] or 0.0

                return time_of_day_usage

    def get_user_latest_plan_price(self, uuid_id: int) -> Optional[int]:
        """
        با مقایسه حجم فعلی کاربر با پلن‌های موجود، قیمت پلن فعلی او را تخمین می‌زند.
        """
        from .utils import load_json_file, parse_volume_string
        user_uuid_record = self.uuid_by_id(0, uuid_id)
        if not user_uuid_record:
            uuid_row = self._conn().execute("SELECT uuid FROM user_uuids WHERE id = ?", (uuid_id,)).fetchone()
            if not uuid_row: return None
            uuid_str = uuid_row['uuid']
        else:
            uuid_str = user_uuid_record.get('uuid')

        if not uuid_str: return None

        from bot.combined_handler import get_combined_user_info
        user_info = get_combined_user_info(uuid_str)
        if not user_info: return None

        current_limit_gb = user_info.get('usage_limit_GB', -1)
        all_plans = load_json_file('plans.json')

        for plan in all_plans:
            plan_total_volume = parse_volume_string(plan.get('total_volume') or '0')
            if plan_total_volume == int(current_limit_gb):
                return plan.get('price')
        return None
    
    def get_total_payments_in_range(self, start_date: datetime, end_date: datetime) -> int:
        """تعداد کل پرداخت‌ها در یک بازه زمانی مشخص را برمی‌گرداند."""
        with self.write_conn() as c:
            row = c.execute(
                "SELECT COUNT(payment_id) as count FROM payments WHERE payment_date >= ? AND payment_date < ?",
                (start_date, end_date)
            ).fetchone()
            return row['count'] if row else 0

    def get_all_users_by_points(self) -> List[Dict[str, Any]]:
        """
        (نسخه نهایی) تمام کاربرانی که امتیاز دارند را به همراه لیست نشان‌هایشان
        به ترتیب امتیاز برمی‌گرداند.
        """
        with self.write_conn() as c:
            query = """
                SELECT
                    u.user_id,
                    u.first_name,
                    u.achievement_points,
                    GROUP_CONCAT(ua.badge_code) as badges
                FROM users u
                LEFT JOIN user_achievements ua ON u.user_id = ua.user_id
                WHERE u.achievement_points > 0
                GROUP BY u.user_id
                ORDER BY u.achievement_points DESC
            """
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]

    def reset_all_achievement_points(self) -> int:
        """امتیاز تمام کاربران را به ۰ ریست می‌کند."""
        with self.write_conn() as c:
            cursor = c.execute("UPDATE users SET achievement_points = 0;")
            self._user_cache.clear()
            return cursor.rowcount

    def delete_all_achievements(self) -> int:
        """تمام رکوردهای دستاوردهای کسب شده را حذف می‌کند."""
        with self.write_conn() as c:
            cursor = c.execute("DELETE FROM user_achievements;")
            return cursor.rowcount

    def get_user_achievements_in_range(self, user_id: int, start_date: datetime) -> List[Dict[str, Any]]:
        """
        تمام دستاوردهای کسب شده توسط یک کاربر در یک بازه زمانی مشخص را برمی‌گرداند.
        """
        query = """
            SELECT
                ua.badge_code,
                ua.awarded_at
            FROM user_achievements ua
            WHERE ua.user_id = ? AND ua.awarded_at >= ?
            ORDER BY ua.awarded_at DESC;
        """
        with self.write_conn() as c:
            rows = c.execute(query, (user_id, start_date)).fetchall()
            return [dict(r) for r in rows]

    def update_wallet_balance(self, user_id: int, amount: float, trans_type: str, description: str) -> bool:
        """
        موجودی کیف پول کاربر را به‌روز کرده و یک تراکنش ثبت می‌کند.
        """
        with self.write_conn() as c:
            try:
                current_balance_row = c.execute("SELECT wallet_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
                if current_balance_row is None:
                    logger.error(f"Attempted to update wallet for non-existent user_id: {user_id}")
                    return False

                current_balance = current_balance_row['wallet_balance']

                if trans_type == 'purchase' and current_balance < abs(amount):
                    return False

                c.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE user_id = ?", (amount, user_id))

                c.execute(
                    "INSERT INTO wallet_transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                    (user_id, amount, trans_type, description)
                )
                self.clear_user_cache(user_id)
                return True
            except Exception as e:
                logger.error(f"Error updating wallet for user {user_id}: {e}", exc_info=True)
                return False

    def set_wallet_balance(self, user_id: int, new_balance: float, trans_type: str, description: str) -> bool:
        """
        موجودی کیف پول کاربر را به یک مقدار مشخص تغییر داده و تراکنش را ثبت می‌کند.
        """
        with self.write_conn() as c:
            try:
                current_balance_row = c.execute("SELECT wallet_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
                if current_balance_row is None:
                    logger.error(f"Attempted to set wallet for non-existent user_id: {user_id}")
                    return False

                amount_changed = new_balance - current_balance_row['wallet_balance']

                c.execute("UPDATE users SET wallet_balance = ? WHERE user_id = ?", (new_balance, user_id))
                c.execute(
                    "INSERT INTO wallet_transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                    (user_id, amount_changed, trans_type, description)
                )
                self.clear_user_cache(user_id)
                return True
            except Exception as e:
                logger.error(f"Error setting wallet balance for user {user_id}: {e}", exc_info=True)
                return False

    def get_wallet_history(self, user_id: int) -> list:
        """تاریخچه تراکنش‌های کیف پول یک کاربر را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT amount, type, description, transaction_date FROM wallet_transactions WHERE user_id = ? ORDER BY transaction_date DESC",
                (user_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def create_charge_request(self, user_id: int, amount: float, message_id: int) -> int:
        """یک درخواست شارژ جدید ثبت کرده و شناسه آن را برمی‌گرداند."""
        with self.write_conn() as c:
            cursor = c.execute(
                "INSERT INTO charge_requests (user_id, amount, message_id) VALUES (?, ?, ?)",
                (user_id, amount, message_id)
            )
            return cursor.lastrowid

    def get_pending_charge_request(self, user_id: int, message_id: int) -> Optional[Dict[str, Any]]:
        """یک درخواست شارژ در حال انتظار را بر اساس شناسه کاربر و پیام برمی‌گرداند."""
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM charge_requests WHERE user_id = ? AND message_id = ? AND is_pending = 1 ORDER BY request_date DESC LIMIT 1",
                (user_id, message_id)
            ).fetchone()
            return dict(row) if row else None

    def get_charge_request_by_id(self, request_id: int) -> Optional[Dict[str, Any]]:
        """یک درخواست شارژ را با شناسه یکتای آن بازیابی می‌کند."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM charge_requests WHERE id = ?", (request_id,)).fetchone()
            return dict(row) if row else None

    def update_charge_request_status(self, request_id: int, is_pending: bool):
        """وضعیت یک درخواست شارژ را به‌روزرسانی می‌کند."""
        with self.write_conn() as c:
            c.execute("UPDATE charge_requests SET is_pending = ? WHERE id = ?", (int(is_pending), request_id))

    def get_all_users_with_balance(self) -> List[Dict[str, Any]]:
        """تمام کاربرانی که موجودی کیف پول دارند را به ترتیب از بیشترین به کمترین برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT user_id, first_name, wallet_balance FROM users WHERE wallet_balance > 0 ORDER BY wallet_balance DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def update_auto_renew_setting(self, user_id: int, status: bool):
        """وضعیت تمدید خودکار را برای کاربر به‌روز می‌کند."""
        with self.write_conn() as c:
            c.execute("UPDATE users SET auto_renew = ? WHERE user_id = ?", (int(status), user_id))

    def log_wallet_transfer(self, sender_id: int, receiver_id: int, amount: float):
        """یک رکورد برای انتقال موجودی ثبت می‌کند."""
        with self.write_conn() as c:
            c.execute(
                "INSERT INTO wallet_transfers (sender_user_id, receiver_user_id, amount) VALUES (?, ?, ?)",
                (sender_id, receiver_id, amount)
            )

    def get_user_by_telegram_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """یک کاربر را بر اساس شناسه تلگرام او پیدا می‌کند."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def get_user_latest_plan_price(self, uuid_id: int) -> Optional[int]:
        """با مقایسه حجم فعلی کاربر با پلن‌های موجود، قیمت پلن فعلی او را تخمین می‌زند."""
        from .utils import load_json_file, parse_volume_string
        from .combined_handler import get_combined_user_info

        uuid_row = self._conn().execute("SELECT uuid FROM user_uuids WHERE id = ?", (uuid_id,)).fetchone()
        if not uuid_row: return None

        user_info = get_combined_user_info(uuid_row['uuid'])
        if not user_info: return None

        current_limit_gb = user_info.get('usage_limit_GB', -1)
        all_plans = load_json_file('plans.json')

        for plan in all_plans:
            plan_total_volume = 0
            if plan.get('type') == 'combined':
                plan_total_volume = parse_volume_string(plan.get('total_volume', '0'))
            else:
                volume_key = 'volume_de' if plan.get('type') == 'germany' else 'volume_fr' if plan.get('type') == 'france' else 'volume_tr'
                plan_total_volume = parse_volume_string(plan.get(volume_key, '0'))

            if plan_total_volume == int(current_limit_gb):
                return plan.get('price')
        return None

    def get_lottery_participant_details(self) -> list[dict]:
        """
        لیست کاربران واجد شرایط برای قرعه‌کشی را به همراه جزئیاتشان
        (نام و تعداد نشان خوش‌شانس) برمی‌گرداند.
        """
        query = """
            SELECT
                u.user_id,
                u.first_name,
                COUNT(ua.id) as lucky_badge_count
            FROM users u
            JOIN user_achievements ua ON u.user_id = ua.user_id
            WHERE ua.badge_code = 'lucky_one'
            GROUP BY u.user_id
            HAVING lucky_badge_count > 0
            ORDER BY lucky_badge_count DESC;
        """
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]

    def reset_all_wallet_balances(self) -> int:
        """موجودی کیف پول تمام کاربران را صفر می‌کند."""
        with self.write_conn() as c:
            c.execute("DELETE FROM wallet_transactions;")
            c.execute("DELETE FROM charge_requests;")
            cursor = c.execute("UPDATE users SET wallet_balance = 0;")
            self._user_cache.clear()
            return cursor.rowcount

    def get_previous_week_usage(self, uuid_id: int) -> float:
        """Calculates the total usage for a specific user for the previous week."""
        tehran_tz = pytz.timezone("Asia/Tehran")
        today_jalali = jdatetime.datetime.now(tz=tehran_tz)
        days_since_saturday = (today_jalali.weekday() + 1) % 7
        
        current_week_start_utc = (datetime.now(tehran_tz) - timedelta(days=days_since_saturday)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.utc)
        previous_week_start_utc = current_week_start_utc - timedelta(days=7)
        
        total_usage = 0.0
        
        with self.write_conn() as c:
            snapshots = c.execute("SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ? AND taken_at < ? ORDER BY taken_at ASC", (uuid_id, previous_week_start_utc, current_week_start_utc)).fetchall()
            
            last_snap_before = c.execute("SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1", (uuid_id, previous_week_start_utc)).fetchone()

            last_h = last_snap_before['hiddify_usage_gb'] if last_snap_before and last_snap_before['hiddify_usage_gb'] is not None else 0.0
            last_m = last_snap_before['marzban_usage_gb'] if last_snap_before and last_snap_before['marzban_usage_gb'] is not None else 0.0

            for snap in snapshots:
                h_diff = max(0, (snap['hiddify_usage_gb'] or 0.0) - last_h)
                m_diff = max(0, (snap['marzban_usage_gb'] or 0.0) - last_m)
                total_usage += h_diff + m_diff
                last_h, last_m = snap['hiddify_usage_gb'] or 0.0, snap['marzban_usage_gb'] or 0.0
                
        return total_usage

    def get_user_weekly_total_usage(self, user_id: int) -> float:
        """
        مجموع مصرف هفتگی یک کاربر را با جمع کردن مصرف تمام اکانت‌هایش محاسبه می‌کند.
        """
        total_usage = 0.0
        user_uuids = self.uuids(user_id)
        if not user_uuids:
            return 0.0

        tehran_tz = pytz.timezone("Asia/Tehran")
        today_jalali = jdatetime.datetime.now(tz=tehran_tz)
        days_since_saturday = (today_jalali.weekday() + 1) % 7
        week_start_utc = (datetime.now(tehran_tz) - timedelta(days=days_since_saturday)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.utc)

        with self.write_conn() as c:
            for uuid_record in user_uuids:
                uuid_id = uuid_record['id']
                
                last_snap_before = c.execute("SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1", (uuid_id, week_start_utc)).fetchone()
                
                snapshots_this_week = c.execute("SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ? ORDER BY taken_at ASC", (uuid_id, week_start_utc)).fetchall()

                last_h = last_snap_before['hiddify_usage_gb'] if last_snap_before and last_snap_before['hiddify_usage_gb'] is not None else 0.0
                last_m = last_snap_before['marzban_usage_gb'] if last_snap_before and last_snap_before['marzban_usage_gb'] is not None else 0.0

                for snap in snapshots_this_week:
                    h_diff = max(0, (snap['hiddify_usage_gb'] or 0.0) - last_h)
                    m_diff = max(0, (snap['marzban_usage_gb'] or 0.0) - last_m)
                    total_usage += h_diff + m_diff
                    last_h, last_m = snap['hiddify_usage_gb'] or 0.0, snap['marzban_usage_gb'] or 0.0
        
        return total_usage

    def get_all_users_weekly_usage(self) -> list[float]:
        """Calculates the total weekly usage for every active user and returns a list of usage values."""
        tehran_tz = pytz.timezone("Asia/Tehran")
        today_jalali = jdatetime.datetime.now(tz=tehran_tz)
        days_since_saturday = (today_jalali.weekday() + 1) % 7
        week_start_utc = (datetime.now(tehran_tz) - timedelta(days=days_since_saturday)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.utc)

        weekly_usage_by_uuid = {}

        with self.write_conn() as c:
            all_snapshots_query = "SELECT uuid_id, hiddify_usage_gb, marzban_usage_gb, taken_at FROM usage_snapshots WHERE taken_at >= ? ORDER BY uuid_id, taken_at ASC;"
            all_week_snapshots = c.execute(all_snapshots_query, (week_start_utc,)).fetchall()

            snapshots_by_user = {}
            for snap in all_week_snapshots:
                snapshots_by_user.setdefault(snap['uuid_id'], []).append(snap)

            for uuid_id, user_snaps in snapshots_by_user.items():
                last_snap_before = c.execute("SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1", (uuid_id, week_start_utc)).fetchone()

                last_h = last_snap_before['hiddify_usage_gb'] if last_snap_before and last_snap_before['hiddify_usage_gb'] is not None else 0.0
                last_m = last_snap_before['marzban_usage_gb'] if last_snap_before and last_snap_before['marzban_usage_gb'] is not None else 0.0

                for snap in user_snaps:
                    h_diff = max(0, (snap['hiddify_usage_gb'] or 0.0) - last_h)
                    m_diff = max(0, (snap['marzban_usage_gb'] or 0.0) - last_m)
                    total_diff = h_diff + m_diff

                    weekly_usage_by_uuid.setdefault(uuid_id, 0.0)
                    weekly_usage_by_uuid[uuid_id] += total_diff
                    
                    last_h, last_m = snap['hiddify_usage_gb'] or 0.0, snap['marzban_usage_gb'] or 0.0
        
        user_id_map = {row['id']: row['user_id'] for row in self.get_all_user_uuids()}
        weekly_usage_by_user_id = {}
        for uuid_id, total_usage in weekly_usage_by_uuid.items():
            user_id = user_id_map.get(uuid_id)
            if user_id:
                weekly_usage_by_user_id.setdefault(user_id, 0.0)
                weekly_usage_by_user_id[user_id] += total_usage
        
        return list(weekly_usage_by_user_id.values())

    def get_previous_day_total_usage(self, uuid_id: int) -> float:
        """مجموع مصرف کل یک کاربر در روز گذشته را به صورت دقیق محاسبه می‌کند."""
        tehran_tz = pytz.timezone("Asia/Tehran")
        yesterday_tehran = datetime.now(tehran_tz).date() - timedelta(days=1)

        day_start_utc = datetime(yesterday_tehran.year, yesterday_tehran.month, yesterday_tehran.day, tzinfo=tehran_tz).astimezone(pytz.utc)
        day_end_utc = day_start_utc + timedelta(days=1)

        with self._conn() as c:
            last_snap_before = c.execute("SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1", (uuid_id, day_start_utc)).fetchone()
            snapshots_yesterday = c.execute("SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ? AND taken_at < ? ORDER BY taken_at ASC", (uuid_id, day_start_utc, day_end_utc)).fetchall()

            last_h = last_snap_before['hiddify_usage_gb'] if last_snap_before and last_snap_before['hiddify_usage_gb'] is not None else 0.0
            last_m = last_snap_before['marzban_usage_gb'] if last_snap_before and last_snap_before['marzban_usage_gb'] is not None else 0.0

            total_usage = 0.0
            for snap in snapshots_yesterday:
                h_diff = max(0, (snap['hiddify_usage_gb'] or 0.0) - last_h)
                m_diff = max(0, (snap['marzban_usage_gb'] or 0.0) - last_m)
                total_usage += h_diff + m_diff

                last_h = snap['hiddify_usage_gb'] or 0.0
                last_m = snap['marzban_usage_gb'] or 0.0

            return total_usage

    def create_notification(self, user_id: int, title: str, message: str, category: str = 'info'):
        """یک اعلان جدید برای کاربر در دیتابیس ثبت می‌کند."""
        with self.write_conn() as c:
            c.execute(
                "INSERT INTO notifications (user_id, title, message, category) VALUES (?, ?, ?, ?)",
                (user_id, title, message, category)
            )
            logger.info(f"Created notification for user {user_id}, category: {category}")

    def get_notifications_for_user(self, user_id: int, include_read: bool = False) -> list:
        """لیست اعلان‌های یک کاربر را برمی‌گرداند."""
        query = "SELECT * FROM notifications WHERE user_id = ?"
        if not include_read:
            query += " AND is_read = 0"
        query += " ORDER BY created_at DESC"
        
        with self._conn() as c:
            rows = c.execute(query, (user_id,)).fetchall()
            return [dict(r) for r in rows]

    def mark_notification_as_read(self, notification_id: int, user_id: int) -> bool:
        """یک اعلان خاص را به عنوان خوانده شده علامت می‌زند."""
        with self.write_conn() as c:
            cursor = c.execute(
                "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
                (notification_id, user_id)
            )
            return cursor.rowcount > 0

    def mark_all_notifications_as_read(self, user_id: int) -> int:
        """تمام اعلان‌های خوانده نشده یک کاربر را خوانده شده می‌کند."""
        with self.write_conn() as c:
            cursor = c.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0", (user_id,))
            return cursor.rowcount

    def get_wallet_transactions(self, user_id: int, limit: int = 50) -> list:
        """لیست تراکنش‌های کیف پول یک کاربر را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT amount, type, description, transaction_date
                FROM wallet_transactions
                WHERE user_id = ?
                ORDER BY transaction_date DESC
                LIMIT ?
                """,
                (user_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_wallet_transactions_paginated(self, user_id: int, page: int = 1, per_page: int = 10) -> list:
        """لیست تراکنش‌های کیف پول یک کاربر را به صورت صفحه‌بندی شده برمی‌گرداند."""
        offset = (page - 1) * per_page
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT amount, type, description, transaction_date
                FROM wallet_transactions
                WHERE user_id = ?
                ORDER BY transaction_date DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, per_page, offset)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_wallet_transactions_count(self, user_id: int) -> int:
        """تعداد کل تراکنش‌های کیف پول یک کاربر را برمی‌گرداند."""
        with self._conn() as c:
            row = c.execute("SELECT COUNT(id) FROM wallet_transactions WHERE user_id = ?", (user_id,)).fetchone()
            return row[0] if row else 0

    def get_user_total_expenses(self, user_id: int) -> float:
        """مجموع کل هزینه‌های یک کاربر (خرید و انتقال) را محاسبه می‌کند."""
        with self._conn() as c:
            row = c.execute(
                "SELECT SUM(amount) FROM wallet_transactions WHERE user_id = ? AND type IN ('purchase', 'wallet_transfer_sender')",
                (user_id,)
            ).fetchone()
            return row[0] if row and row[0] else 0.0

    def get_user_purchase_stats(self, user_id: int) -> dict:
        """(نسخه نهایی) آمار خریدهای یک کاربر (تعداد کل خریدها و تعداد هدایا) را به درستی محاسبه می‌کند."""
        with self._conn() as c:
            total_purchases_row = c.execute(
                "SELECT COUNT(id) FROM wallet_transactions WHERE user_id = ? AND type IN ('purchase', 'gift_purchase')",
                (user_id,)
            ).fetchone()
            total_purchases = total_purchases_row[0] if total_purchases_row else 0

            gift_purchases_row = c.execute(
                "SELECT COUNT(id) FROM wallet_transactions WHERE user_id = ? AND type = 'gift_purchase'",
                (user_id,)
            ).fetchone()
            gift_purchases = gift_purchases_row[0] if gift_purchases_row else 0
            
            return {
                'total_purchases': total_purchases,
                'gift_purchases': gift_purchases
            }

    def count_vip_users(self) -> int:
        """تعداد کل کاربران VIP فعال را می‌شمارد."""
        with self.write_conn() as c:
            row = c.execute("SELECT COUNT(id) as count FROM user_uuids WHERE is_active = 1 AND is_vip = 1").fetchone()
            return row['count'] if row else 0

    def log_weekly_champion_win(self, user_id: int):
        """یک رکورد برای قهرمانی هفتگی کاربر ثبت می‌کند."""
        today = datetime.now(pytz.utc).date()
        with self.write_conn() as c:
            c.execute(
                "INSERT INTO weekly_champion_log (user_id, win_date) VALUES (?, ?)",
                (user_id, today)
            )

    def count_consecutive_weekly_wins(self, user_id: int) -> int:
        """تعداد قهرمانی‌های هفتگی متوالی یک کاربر را محاسبه می‌کند."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT win_date FROM weekly_champion_log WHERE user_id = ? ORDER BY win_date DESC",
                (user_id,)
            ).fetchall()

        if not rows:
            return 0

        consecutive_wins = 0
        last_win_date = None

        for row in rows:
            win_date = row['win_date']
            if isinstance(win_date, str):
                win_date = datetime.strptime(win_date, '%Y-%m-%d').date()

            if last_win_date is None:
                consecutive_wins = 1
            else:
                if (last_win_date - win_date).days in [6, 7, 8]:
                    consecutive_wins += 1
                else:
                    break
            
            last_win_date = win_date
            
        return consecutive_wins

    def add_achievement_request(self, user_id: int, badge_code: str) -> int:
        """یک درخواست نشان جدید ثبت کرده و شناسه آن را برمی‌گرداند."""
        with self.write_conn() as c:
            cursor = c.execute(
                "INSERT INTO achievement_requests (user_id, badge_code) VALUES (?, ?)",
                (user_id, badge_code)
            )
            return cursor.lastrowid

    def get_achievement_request(self, request_id: int) -> Optional[Dict[str, Any]]:
        """اطلاعات یک درخواست نشان را با شناسه آن بازیابی می‌کند."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM achievement_requests WHERE id = ?", (request_id,)).fetchone()
            return dict(row) if row else None

    def update_achievement_request_status(self, request_id: int, status: str, admin_id: int):
        """وضعیت یک درخواست نشان را به‌روزرسانی می‌کند."""
        with self.write_conn() as c:
            c.execute(
                "UPDATE achievement_requests SET status = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?",
                (status, admin_id, datetime.now(pytz.utc), request_id)
            )

    def add_monthly_cost(self, year: int, month: int, cost: float, description: str) -> bool:
        """Adds a new monthly cost entry."""
        with self.write_conn() as c:
            try:
                c.execute(
                    "INSERT INTO monthly_costs (year, month, cost, description) VALUES (?, ?, ?, ?)",
                    (year, month, cost, description)
                )
                return True
            except sqlite3.IntegrityError:
                logger.warning(f"Cost entry for {year}-{month} with description '{description}' already exists.")
                return False

    def get_all_monthly_costs(self) -> List[Dict[str, Any]]:
        """Retrieves all monthly cost entries."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM monthly_costs ORDER BY year DESC, month DESC").fetchall()
            return [dict(r) for r in rows]

    def get_costs_for_month(self, year: int, month: int) -> List[Dict[str, Any]]:
        """هزینه‌های ثبت شده برای یک ماه و سال مشخص را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT description, cost FROM monthly_costs WHERE year = ? AND month = ?",
                (year, month)
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_monthly_cost(self, cost_id: int) -> bool:
        """Deletes a monthly cost entry by its ID."""
        with self.write_conn() as c:
            cursor = c.execute("DELETE FROM monthly_costs WHERE id = ?", (cost_id,))
            return cursor.rowcount > 0

    def get_monthly_financials(self) -> Dict[str, Dict[str, float]]:
        """
        (نسخه نهایی و پایدار)
        درآمدها و هزینه‌ها را بر اساس ماه میلادی محاسبه می‌کند.
        """
        financials = {}
        
        # ۱. محاسبه درآمد ماهانه با کوئری مستقیم SQLite
        revenue_query = """
            SELECT
                strftime('%Y-%m', transaction_date) as month,
                SUM(amount) as total_revenue
            FROM wallet_transactions
            WHERE (type = 'deposit' OR type = 'addon_purchase' OR type = 'purchase' OR type = 'gift_purchase')
            GROUP BY month
        """
        with self._conn() as c:
            try:
                revenue_rows = c.execute(revenue_query).fetchall()
                for row in revenue_rows:
                    if row['month']:
                        financials[row['month']] = {'revenue': row['total_revenue'], 'cost': 0}
            except sqlite3.OperationalError as e:
                logger.error(f"Error fetching monthly revenue: {e}", exc_info=True)


        # ۲. خواندن هزینه‌های ماهانه
        cost_query = """
            SELECT
                printf('%d-%02d', year, month) as month,
                SUM(cost) as total_cost
            FROM monthly_costs
            GROUP BY month
        """
        with self._conn() as c:
            try:
                cost_rows = c.execute(cost_query).fetchall()
                for row in cost_rows:
                    if row['month']:
                        if row['month'] not in financials:
                            financials[row['month']] = {'revenue': 0, 'cost': 0}
                        financials[row['month']]['cost'] = row['total_cost']
            except sqlite3.OperationalError as e:
                logger.error(f"Error fetching monthly costs: {e}", exc_info=True)

        # ۳. محاسبه سود
        for month, data in financials.items():
            data['profit'] = data.get('revenue', 0) - data.get('cost', 0)
            
        return financials

    def get_transactions_for_month(self, year: int, month: int) -> List[Dict[str, Any]]:
        """تمام تراکنش‌های درآمدی یک ماه و سال مشخص را به همراه نام کاربر برمی‌گرداند."""
        start_date = datetime(year, month, 1)
        end_date = (start_date + timedelta(days=32)).replace(day=1)
        
        query = """
            SELECT
                wt.amount,
                wt.description,
                wt.transaction_date,
                u.user_id,
                u.first_name
            FROM wallet_transactions wt
            JOIN users u ON wt.user_id = u.user_id
            WHERE wt.transaction_date >= ? AND wt.transaction_date < ? AND wt.type IN ('deposit', 'purchase', 'gift_purchase', 'addon_purchase')
            ORDER BY wt.transaction_date DESC
        """
        with self._conn() as c:
            rows = c.execute(query, (start_date, end_date)).fetchall()
            return [dict(r) for r in rows]

    def get_user_access_rights(self, user_id: int) -> dict:
        """حقوق دسترسی کاربر به پنل‌های مختلف را برمی‌گرداند."""
        access_rights = {'has_access_de': False, 'has_access_fr': False, 'has_access_tr': False}
        user_uuids = self.uuids(user_id)
        if user_uuids:
            first_uuid_record = self.uuid_by_id(user_id, user_uuids[0]['id'])
            if first_uuid_record:
                access_rights['has_access_de'] = first_uuid_record.get('has_access_de', False)
                access_rights['has_access_fr'] = first_uuid_record.get('has_access_fr', False)
                access_rights['has_access_tr'] = first_uuid_record.get('has_access_tr', False)
                access_rights['has_access_us'] = first_uuid_record.get('has_access_us', False)

        return access_rights

db = DatabaseManager()