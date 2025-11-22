# bot/db/user.py

import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
import logging
import secrets
import pytz
import time

from .base import DatabaseManager

logger = logging.getLogger(__name__)

class UserDB(DatabaseManager):
    """
    کلاسی برای مدیریت تمام عملیات مربوط به کاربران و UUID های آن‌ها در دیتابیس.
    """

    def user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        اطلاعات کامل یک کاربر را با استفاده از کش واکشی می‌کند.
        """
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        with self._conn() as c:  #
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
        with self._conn() as c:
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
        """تنظیمات مختلف کاربر را برمی‌گرداند."""
        with self._conn() as c:
            row = c.execute("SELECT daily_reports, weekly_reports, expiry_warnings, data_warning_de, data_warning_fr, data_warning_tr, data_warning_us, show_info_config, auto_delete_reports, achievement_alerts, promotional_alerts FROM users WHERE user_id=?", (user_id,)).fetchone()
            if row:
                row_dict = dict(row)
                return {k: bool(v) for k, v in row_dict.items()}
            # مقادیر پیش‌فرض در صورت عدم وجود کاربر
            return {
                'daily_reports': True, 'weekly_reports': True, 'expiry_warnings': True,
                'data_warning_de': True, 'data_warning_fr': True, 'data_warning_tr': True,
                'data_warning_us': True, 'show_info_config': True,
                'auto_delete_reports': False, 'achievement_alerts': True, 'promotional_alerts': True
            }

    def update_user_setting(self, user_id: int, setting: str, value: bool) -> None:
        """یک تنظیم خاص کاربر را به‌روزرسانی می‌کند."""
        valid_settings = [
            'daily_reports', 'weekly_reports', 'expiry_warnings', 'show_info_config',
            'auto_delete_reports', 'achievement_alerts', 'promotional_alerts',
            'data_warning_de', 'data_warning_fr', 'data_warning_tr', 'data_warning_us'
        ]
        if setting in valid_settings:
            with self._conn() as c:
                c.execute(f"UPDATE users SET {setting}=? WHERE user_id=?", (int(value), user_id))
            self.clear_user_cache(user_id)

    def update_user_birthday(self, user_id: int, birthday_date: datetime.date):
        """تاریخ تولد کاربر را به‌روزرسانی می‌کند."""
        with self._conn() as c:
            c.execute("UPDATE users SET birthday = ? WHERE user_id = ?", (birthday_date, user_id))
        self.clear_user_cache(user_id)

    def get_users_with_birthdays(self):
        """تمام کاربرانی که تاریخ تولد ثبت کرده‌اند را برمی‌گرداند."""
        with self._conn() as c:
            cursor = c.execute("SELECT user_id, first_name, username, birthday FROM users WHERE birthday IS NOT NULL ORDER BY strftime('%m-%d', birthday)")
            for row in cursor:
                yield dict(row)

    def reset_user_birthday(self, user_id: int) -> None:
        """تاریخ تولد کاربر را حذف (ریست) می‌کند."""
        with self._conn() as c:
            c.execute("UPDATE users SET birthday = NULL WHERE user_id = ?", (user_id,))
        self.clear_user_cache(user_id)

    def set_user_language(self, user_id: int, lang_code: str):
        """زبان انتخابی کاربر را ذخیره می‌کند."""
        with self._conn() as c:
            c.execute("UPDATE users SET lang_code = ? WHERE user_id = ?", (lang_code, user_id))
        self.clear_user_cache(user_id)

    def get_user_language(self, user_id: int) -> str:
        """زبان کاربر را از دیتابیس می‌خواند."""
        with self._conn() as c:
            row = c.execute("SELECT lang_code FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return row['lang_code'] if row and row['lang_code'] else 'fa'

    def update_user_note(self, user_id: int, note: Optional[str]) -> None:
        """یادداشت ادمین برای یک کاربر را به‌روزرسانی می‌کند."""
        with self._conn() as c:
            c.execute("UPDATE users SET admin_note = ? WHERE user_id = ?", (note, user_id))
        self.clear_user_cache(user_id)

    def get_all_bot_users(self) -> List[Dict[str, Any]]:
        """لیست تمام کاربران ربات را برمی‌گرداند."""
        with self._conn() as c:
            cursor = c.execute("SELECT user_id, username, first_name, last_name FROM users ORDER BY user_id")
            return [dict(r) for r in cursor.fetchall()]

    def get_user_by_telegram_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """یک کاربر را بر اساس شناسه تلگرام او پیدا می‌کند."""
        return self.user(user_id)

    def get_all_user_ids(self):
        """تمام شناسه‌های کاربری تلگرام را برمی‌گرداند."""
        with self._conn() as c:
            cursor = c.execute("SELECT user_id FROM users")
            for row in cursor:
                yield row['user_id']

    def purge_user_by_telegram_id(self, user_id: int) -> bool:
        """یک کاربر را به طور کامل از جدول users و تمام جداول وابسته حذف می‌کند."""
        with self._conn() as c:
            cursor = c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            self.clear_user_cache(user_id)
            return cursor.rowcount > 0

    # --- توابع مربوط به UUID ---

    def add_uuid(self, user_id: int, uuid_str: str, name: str) -> any:
        """یک UUID جدید برای کاربر اضافه می‌کند یا در صورت وجود، وضعیت‌های مختلف را مدیریت می‌کند."""
        uuid_str = uuid_str.lower()
        with self._conn() as c:
            # بررسی اینکه آیا همین کاربر قبلا این UUID را داشته و غیرفعال کرده
            existing_inactive = c.execute("SELECT * FROM user_uuids WHERE user_id = ? AND uuid = ? AND is_active = 0", (user_id, uuid_str)).fetchone()
            if existing_inactive:
                c.execute("UPDATE user_uuids SET is_active = 1, name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (name, existing_inactive['id']))
                return "db_msg_uuid_reactivated"

            # بررسی اینکه آیا این UUID برای کاربر دیگری فعال است
            existing_active = c.execute("SELECT * FROM user_uuids WHERE uuid = ? AND is_active = 1", (uuid_str,)).fetchone()
            if existing_active:
                if existing_active['user_id'] == user_id:
                    return "db_err_uuid_already_active_self"
                else: # متعلق به کاربر دیگری است
                    return {
                        "status": "confirmation_required",
                        "owner_id": existing_active['user_id'],
                        "uuid_id": existing_active['id']
                    }

            # افزودن UUID جدید
            c.execute("INSERT INTO user_uuids (user_id, uuid, name) VALUES (?, ?, ?)", (user_id, uuid_str, name))
            return "db_msg_uuid_added"

    def add_shared_uuid(self, user_id: int, uuid_str: str, name: str) -> bool:
        """یک اکانت اشتراکی را بدون بررسی مالکیت، برای کاربر ثبت می‌کند."""
        uuid_str = uuid_str.lower()
        with self._conn() as c:
            # اگر قبلا داشته و غیرفعال کرده، دوباره فعالش کن
            existing_inactive = c.execute("SELECT * FROM user_uuids WHERE user_id = ? AND uuid = ? AND is_active = 0", (user_id, uuid_str)).fetchone()
            if existing_inactive:
                c.execute("UPDATE user_uuids SET is_active = 1, name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (name, existing_inactive['id']))
            else:
                c.execute("INSERT INTO user_uuids (user_id, uuid, name, is_active) VALUES (?, ?, ?, 1)", (user_id, uuid_str, name))
            return True

    def uuids(self, user_id: int) -> List[Dict[str, Any]]:
        """تمام UUID های فعال یک کاربر را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM user_uuids WHERE user_id=? AND is_active=1 ORDER BY created_at", (user_id,)).fetchall()
            return [dict(r) for r in rows]

    def uuid_by_id(self, user_id: int, uuid_id: int) -> Optional[Dict[str, Any]]:
        """یک UUID خاص را با شناسه داخلی آن برمی‌گرداند."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM user_uuids WHERE user_id=? AND id=? AND is_active=1", (user_id, uuid_id)).fetchone()
            return dict(row) if row else None

    def get_uuid_id_by_uuid(self, uuid_str: str) -> Optional[int]:
        """Finds the internal ID of a UUID record."""
        with self._conn() as c:
            row = c.execute("SELECT id FROM user_uuids WHERE uuid = ?", (uuid_str,)).fetchone()
            return row['id'] if row else None

    def deactivate_uuid(self, uuid_id: int) -> bool:
        """یک UUID را غیرفعال می‌کند."""
        with self._conn() as c:
            res = c.execute("UPDATE user_uuids SET is_active = 0 WHERE id = ?", (uuid_id,))
            return res.rowcount > 0

    def delete_user_by_uuid(self, uuid: str) -> None:
        """یک رکورد UUID را از دیتابیس حذف می‌کند."""
        with self._conn() as c:
            c.execute("DELETE FROM user_uuids WHERE uuid=?", (uuid,))

    def all_active_uuids(self):
        """تمام UUID های فعال را به همراه اطلاعاتشان برمی‌گرداند."""
        with self._conn() as c:
            cursor = c.execute("SELECT id, user_id, uuid, created_at, first_connection_time, welcome_message_sent, renewal_reminder_sent FROM user_uuids WHERE is_active=1")
            for row in cursor:
                yield dict(row)

    def get_user_id_by_uuid(self, uuid: str) -> Optional[int]:
        """شناسه تلگرام کاربر را با استفاده از UUID پیدا می‌کند."""
        with self._conn() as c:
            row = c.execute("SELECT user_id FROM user_uuids WHERE uuid = ?", (uuid,)).fetchone()
            return row['user_id'] if row else None

    def get_bot_user_by_uuid(self, uuid: str) -> Optional[Dict[str, Any]]:
        """اطلاعات پایه کاربر (نام، یوزرنیم) را با استفاده از UUID پیدا می‌کند."""
        query = "SELECT u.user_id, u.first_name, u.username FROM users u JOIN user_uuids uu ON u.user_id = uu.user_id WHERE uu.uuid = ?"
        with self._conn() as c:
            row = c.execute(query, (uuid,)).fetchone()
            return dict(row) if row else None
            
    def get_uuid_to_user_id_map(self) -> Dict[str, int]:
        """یک دیکشنری از UUID به شناسه تلگرام برای تمام کاربران فعال می‌سازد."""
        with self._conn() as c:
            rows = c.execute("SELECT uuid, user_id FROM user_uuids WHERE is_active=1").fetchall()
            return {row['uuid']: row['user_id'] for row in rows}
    
    def get_uuid_to_bot_user_map(self) -> Dict[str, Dict[str, Any]]:
        """یک دیکشنری از UUID به اطلاعات پایه کاربر (نام، یوزرنیم) می‌سازد."""
        query = "SELECT uu.uuid, u.user_id, u.first_name, u.username FROM user_uuids uu LEFT JOIN users u ON uu.user_id = u.user_id WHERE uu.is_active = 1"
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            return {row['uuid']: dict(row) for row in rows}

    def set_first_connection_time(self, uuid_id: int, time: datetime):
        """زمان اولین اتصال یک UUID را ثبت می‌کند."""
        with self._conn() as c:
            c.execute("UPDATE user_uuids SET first_connection_time = ? WHERE id = ?", (time, uuid_id))

    def mark_welcome_message_as_sent(self, uuid_id: int):
        """وضعیت ارسال پیام خوشامدگویی را برای یک UUID ثبت می‌کند."""
        with self._conn() as c:
            c.execute("UPDATE user_uuids SET welcome_message_sent = 1 WHERE id = ?", (uuid_id,))
            
    def reset_welcome_message_sent(self, uuid_id: int):
        """وضعیت ارسال پیام خوشامدگویی را برای تست ریست می‌کند."""
        with self._conn() as c:
            c.execute("UPDATE user_uuids SET welcome_message_sent = 0 WHERE id = ?", (uuid_id,))

    def set_renewal_reminder_sent(self, uuid_id: int):
        """وضعیت ارسال یادآوری تمدید را برای یک UUID ثبت می‌کند."""
        with self._conn() as c:
            c.execute("UPDATE user_uuids SET renewal_reminder_sent = 1 WHERE id = ?", (uuid_id,))
            
    def reset_renewal_reminder_sent(self, uuid_id: int):
        """وضعیت ارسال یادآوری تمدید را برای تست ریست می‌کند."""
        with self._conn() as c:
            c.execute("UPDATE user_uuids SET renewal_reminder_sent = 0 WHERE id = ?", (uuid_id,))
            
    def get_user_uuid_record(self, uuid_str: str) -> dict | None:
        """اطلاعات کامل یک رکورد UUID را بر اساس رشته آن برمی‌گرداند."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM user_uuids WHERE uuid = ? AND is_active = 1", (uuid_str,)).fetchone()
            return dict(row) if row else None
            
    def get_all_user_uuids(self) -> List[Dict[str, Any]]:
        """تمام رکوردهای UUID را برای پنل ادمین برمی‌گرداند."""
        with self._conn() as c:
            query = "SELECT id, user_id, uuid, name, is_active, created_at, is_vip, has_access_de, has_access_fr, has_access_tr, has_access_us, has_access_ro, has_access_supp FROM user_uuids ORDER BY created_at DESC"
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]

    def update_config_name(self, uuid_id: int, new_name: str) -> bool:
        """نام نمایشی یک کانفیگ (UUID) را تغییر می‌دهد."""
        if not new_name or len(new_name) < 2:
            return False
        with self._conn() as c:
            cursor = c.execute("UPDATE user_uuids SET name = ? WHERE id = ?", (new_name, uuid_id))
            return cursor.rowcount > 0

    def toggle_user_vip(self, uuid: str) -> None:
        """وضعیت VIP یک کاربر را تغییر می‌دهد."""
        with self._conn() as c:
            c.execute("UPDATE user_uuids SET is_vip = 1 - is_vip WHERE uuid = ?", (uuid,))
            
    def get_all_bot_users_with_uuids(self) -> List[Dict[str, Any]]:
        """اطلاعات کاربران ربات به همراه UUID ها و دسترسی‌هایشان را برمی‌گرداند."""
        query = """
            SELECT
                u.user_id, u.first_name, u.username,
                uu.id as uuid_id, uu.name as config_name, uu.uuid, uu.is_vip,
                uu.has_access_de, uu.has_access_fr, uu.has_access_tr, uu.has_access_us, uu.has_access_ro, uu.has_access_supp,
                CASE WHEN mm.hiddify_uuid IS NOT NULL THEN 1 ELSE 0 END as is_on_marzban
            FROM users u
            JOIN user_uuids uu ON u.user_id = uu.user_id
            LEFT JOIN marzban_mapping mm ON uu.uuid = mm.hiddify_uuid
            WHERE uu.is_active = 1
            ORDER BY u.user_id, uu.created_at;
        """
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]

    def update_user_server_access(self, uuid_id: int, server: str, status: bool) -> bool:
        """دسترسی کاربر به یک سرور خاص را به‌روزرسانی می‌کند."""
        if server not in ['de', 'fr', 'tr', 'us', 'ro', 'supp']:
            return False
        column_name = f"has_access_{server}"
        with self._conn() as c:
            cursor = c.execute(f"UPDATE user_uuids SET {column_name} = ? WHERE id = ?", (int(status), uuid_id))
            return cursor.rowcount > 0
            
    def get_user_access_rights(self, user_id: int) -> dict:
        """حقوق دسترسی کاربر به پنل‌های مختلف را برمی‌گرداند."""
        access_rights = {'has_access_de': False, 'has_access_fr': False, 'has_access_tr': False, 'has_access_us': False, 'has_access_ro': False, 'has_access_supp': False}
        user_uuids = self.uuids(user_id)
        if user_uuids:
            # دسترسی بر اساس اولین اکانت ثبت شده تعیین می‌شود
            first_uuid_record = self.uuid_by_id(user_id, user_uuids[0]['id'])
            if first_uuid_record:
                access_rights['has_access_de'] = first_uuid_record.get('has_access_de', False)
                access_rights['has_access_fr'] = first_uuid_record.get('has_access_fr', False)
                access_rights['has_access_tr'] = first_uuid_record.get('has_access_tr', False)
                access_rights['has_access_us'] = first_uuid_record.get('has_access_us', False)
                access_rights['has_access_ro'] = first_uuid_record.get('has_access_ro', False)
                access_rights['has_access_supp'] = first_uuid_record.get('has_access_supp', False)
        return access_rights

    # --- توابع مربوط به دستگاه‌های کاربر (User Agents) ---

    def record_user_agent(self, uuid_id: int, user_agent: str):
        """دستگاه کاربر را به صورت هوشمند ثبت یا به‌روزرسانی می‌کند."""
        from ..utils import parse_user_agent # Local import to avoid circular dependency
        new_parsed = parse_user_agent(user_agent)
        if not new_parsed or not new_parsed.get('client'):
            return

        existing_agents = self.get_user_agents_for_uuid(uuid_id)
        for agent in existing_agents:
            existing_parsed = parse_user_agent(agent['user_agent'])
            if existing_parsed and existing_parsed.get('client') == new_parsed.get('client') and existing_parsed.get('os') == new_parsed.get('os'):
                # اگر دستگاهی با همین کلاینت و سیستم‌عامل وجود داشت، فقط آن را آپدیت کن
                with self._conn() as c:
                    c.execute("UPDATE client_user_agents SET user_agent = ?, last_seen = ? WHERE uuid_id = ? AND user_agent = ?", (user_agent, datetime.now(pytz.utc), uuid_id, agent['user_agent']))
                return
        # اگر دستگاه جدید بود، آن را اضافه کن
        with self._conn() as c:
            c.execute("INSERT INTO client_user_agents (uuid_id, user_agent, last_seen) VALUES (?, ?, ?) ON CONFLICT(uuid_id, user_agent) DO UPDATE SET last_seen = excluded.last_seen;", (uuid_id, user_agent, datetime.now(pytz.utc)))

    def delete_all_user_agents(self) -> int:
        """تمام دستگاه‌های ثبت‌شده را حذف می‌کند."""
        with self._conn() as c:
            cursor = c.execute("DELETE FROM client_user_agents;")
            try:
                c.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'client_user_agents';")
            except sqlite3.OperationalError:
                pass
            return cursor.rowcount

    def get_user_agents_for_uuid(self, uuid_id: int) -> List[Dict[str, Any]]:
        """تمام دستگاه‌های ثبت‌شده برای یک UUID خاص را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute("SELECT user_agent, last_seen FROM client_user_agents WHERE uuid_id = ? ORDER BY last_seen DESC", (uuid_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_all_user_agents(self) -> List[Dict[str, Any]]:
        """تمام دستگاه‌های ثبت‌شده به همراه اطلاعات کاربر را برمی‌گرداند."""
        query = "SELECT ca.user_agent, ca.last_seen, uu.name as config_name, u.first_name, u.user_id FROM client_user_agents ca JOIN user_uuids uu ON ca.uuid_id = uu.id LEFT JOIN users u ON uu.user_id = u.user_id ORDER BY ca.last_seen DESC;"
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]

    def count_user_agents(self, uuid_id: int) -> int:
        """تعداد دستگاه‌های ثبت‌شده برای یک UUID را می‌شمارد."""
        with self._conn() as c:
            row = c.execute("SELECT COUNT(id) FROM client_user_agents WHERE uuid_id = ?", (uuid_id,)).fetchone()
        return row[0] if row else 0

    def delete_user_agents_by_uuid_id(self, uuid_id: int) -> int:
        """تمام دستگاه‌های یک UUID خاص را حذف می‌کند."""
        with self._conn() as c:
            cursor = c.execute("DELETE FROM client_user_agents WHERE uuid_id = ?", (uuid_id,))
            return cursor.rowcount
            
    # --- توابع مربوط به سیستم معرفی (Referral) ---

    def get_or_create_referral_code(self, user_id: int) -> str:
        """کد معرف کاربر را برمی‌گرداند یا در صورت عدم وجود، یکی می‌سازد."""
        with self._conn() as c:
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
        with self._conn() as c:
            referrer = c.execute("SELECT user_id FROM users WHERE referral_code = ?", (referrer_code,)).fetchone()
            if referrer:
                c.execute("UPDATE users SET referred_by_user_id = ? WHERE user_id = ?", (referrer['user_id'], user_id))
                self.clear_user_cache(user_id)

    def get_referrer_info(self, user_id: int) -> Optional[dict]:
        """اطلاعات کاربر معرف را برمی‌گرداند."""
        with self._conn() as c:
            row = c.execute("SELECT u.referred_by_user_id, u.referral_reward_applied, r.first_name as referrer_name FROM users u JOIN users r ON u.referred_by_user_id = r.user_id WHERE u.user_id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def mark_referral_reward_as_applied(self, user_id: int):
        """وضعیت پاداش معرفی را ثبت می‌کند."""
        with self._conn() as c:
            c.execute("UPDATE users SET referral_reward_applied = 1 WHERE user_id = ?", (user_id,))
        self.clear_user_cache(user_id)
        
    def get_referred_users(self, referrer_user_id: int) -> list[dict]:
        """لیست کاربرانی که توسط یک کاربر خاص معرفی شده‌اند را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute("SELECT user_id, first_name, referral_reward_applied FROM users WHERE referred_by_user_id = ?", (referrer_user_id,)).fetchall()
            return [dict(r) for r in rows]
        

    def get_user_ids_by_uuids(self, uuids: List[str]) -> List[int]:
        if not uuids: return []
        placeholders = ','.join('?' for _ in uuids)
        query = f"SELECT DISTINCT user_id FROM user_uuids WHERE uuid IN ({placeholders})"
        with self._conn() as c:
            rows = c.execute(query, uuids).fetchall()
            return [row['user_id'] for row in rows]

    def purge_user_by_telegram_id(self, user_id: int) -> bool:
        """یک کاربر را به طور کامل از جدول users و تمام جداول وابسته حذف می‌کند."""
        with self._conn() as c:
            cursor = c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            self.clear_user_cache(user_id)
            return cursor.rowcount > 0

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
            c.execute("DELETE FROM login_tokens WHERE created_at < ?", (five_minutes_ago,))
            row = c.execute("SELECT uuid FROM login_tokens WHERE token = ?", (token,)).fetchone()
            if row:
                c.execute("DELETE FROM login_tokens WHERE token = ?", (token,))
                return row['uuid']
        return None

    def update_auto_renew_setting(self, user_id: int, status: bool):
        """وضعیت تمدید خودکار را برای کاربر به‌روز می‌کند."""
        with self._conn() as c:
            c.execute("UPDATE users SET auto_renew = ? WHERE user_id = ?", (int(status), user_id))
        self.clear_user_cache(user_id)

    def get_all_active_uuids_with_user_id(self) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT id, user_id FROM user_uuids WHERE is_active=1").fetchall()
            return [dict(r) for r in rows]

    def get_all_user_uuids_and_panel_data(self) -> List[Dict[str, Any]]:
        query = """
            WITH LastSnapshots AS (
                SELECT uuid_id, MAX(taken_at) as last_taken_at
                FROM usage_snapshots GROUP BY uuid_id
            )
            SELECT
                uu.uuid, uu.user_id, uu.name,
                COALESCE(s.hiddify_usage_gb, 0) as used_traffic_hiddify,
                COALESCE(s.marzban_usage_gb, 0) as used_traffic_marzban,
                s.taken_at as last_online_jalali
            FROM user_uuids uu
            LEFT JOIN LastSnapshots ls ON uu.id = ls.uuid_id
            LEFT JOIN usage_snapshots s ON ls.uuid_id = s.uuid_id AND ls.last_taken_at = s.taken_at
            WHERE uu.is_active = 1;
        """
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]

    def add_or_update_user_from_panel(self, uuid: str, name: str, telegram_id: Optional[int], expire_days_hiddify: Optional[int], expire_days_marzban: Optional[int], last_online_jalali: Optional[datetime], used_traffic_hiddify: float, used_traffic_marzban: float):
        with self._conn() as c:
            uuid_row = c.execute("SELECT id FROM user_uuids WHERE uuid = ?", (uuid,)).fetchone()
            if not uuid_row:
                logger.info(f"SYNCER: Skipping update for UUID {uuid} as it's not in bot DB.")
                return

            uuid_id = uuid_row['id']
            c.execute("UPDATE user_uuids SET name = ? WHERE id = ?", (name, uuid_id))
            
            # Note: Snapshot logic is removed as it's now in the sync job itself.
            if telegram_id:
                self.add_or_update_user(telegram_id, None, name, None)
            logger.debug(f"SYNCER: Updated data for UUID {uuid}.")

    def get_todays_birthdays(self) -> list:
        today = datetime.now(pytz.utc)
        today_month_day = f"{today.month:02d}-{today.day:02d}"
        with self._conn() as c:
            rows = c.execute("SELECT user_id FROM users WHERE strftime('%m-%d', birthday) = ?", (today_month_day,)).fetchall()
            return [row['user_id'] for row in rows]

    def count_vip_users(self) -> int:
        with self._conn() as c:
            row = c.execute("SELECT COUNT(id) as count FROM user_uuids WHERE is_active = 1 AND is_vip = 1").fetchone()
            return row['count'] if row else 0

    def get_new_vips_last_7_days(self) -> list[dict]:
        seven_days_ago = datetime.now(pytz.utc) - timedelta(days=7)
        query = """
            SELECT u.user_id, u.first_name
            FROM users u JOIN user_uuids uu ON u.user_id = uu.user_id
            WHERE uu.is_vip = 1 AND uu.updated_at >= ?
        """
        with self._conn() as c:
            rows = c.execute(query, (seven_days_ago,)).fetchall()
            return [dict(r) for r in rows]
        
    def claim_daily_checkin(self, user_id: int) -> dict:
        """ثبت اعلام حضور روزانه با امتیاز کم (سرگرمی)"""
        today = datetime.now(pytz.timezone("Asia/Tehran")).date()
        
        with self._conn() as c:
            # دریافت اطلاعات فعلی کاربر
            row = c.execute("SELECT last_checkin, streak_count FROM users WHERE user_id = ?", (user_id,)).fetchone()
            
            # تبدیل تاریخ دیتابیس به آبجکت پایتون
            last_checkin = None
            if row and row['last_checkin']:
                try:
                    last_checkin = datetime.strptime(row['last_checkin'], "%Y-%m-%d").date()
                except ValueError:
                    last_checkin = None
            
            streak = row['streak_count'] if row and row['streak_count'] else 0
            
            # ۱. اگر امروز قبلاً گرفته باشد
            if last_checkin == today:
                return {"status": "already_claimed", "streak": streak}
            
            # ۲. محاسبه استریک (روزهای متوالی)
            # اگر آخرین بار "دیروز" بوده، استریک یکی اضافه میشه
            if last_checkin == today - timedelta(days=1):
                new_streak = streak + 1
            else:
                # اگر فاصله افتاده، استریک ریست میشه به ۱
                new_streak = 1
            
            # ۳. محاسبه امتیاز (خیلی کم، صرفاً جهت فان)
            # فرمول: همیشه ۱ امتیاز، ولی اگر ۷ روز پشت سر هم بیاد ۱ امتیاز تشویقی میگیره
            points = 1
            if new_streak % 7 == 0:
                points += 5  # جایزه هفتگی کوچک
            
            # ۴. ذخیره در دیتابیس
            # آپدیت تاریخ و استریک
            c.execute("UPDATE users SET last_checkin = ?, streak_count = ? WHERE user_id = ?", (today, new_streak, user_id))
            
            # اضافه کردن امتیاز به کیف امتیازات کاربر
            # فرض بر این است که ستون achievement_points دارید (چون سیستم دستاورد دارید)
            c.execute("UPDATE users SET achievement_points = COALESCE(achievement_points, 0) + ? WHERE user_id = ?", (points, user_id))
            
            return {"status": "success", "streak": new_streak, "points": points}