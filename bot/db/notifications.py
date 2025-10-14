# bot/db/notifications.py

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import pytz

from .base import DatabaseManager

logger = logging.getLogger(__name__)


class NotificationsDB(DatabaseManager):
    """
    کلاسی برای مدیریت تمام عملیات مربوط به اعلان‌ها، هشدارها و لاگ‌ها.
    """

    # --- توابع مربوط به هشدارها (Warnings) ---

    def log_warning(self, uuid_id: int, warning_type: str) -> None:
        """
        یک هشدار ارسال شده برای کاربر را ثبت یا به‌روزرسانی می‌کند.
        این کار از ارسال هشدارهای تکراری جلوگیری می‌کند.
        """
        with self._conn() as c:
            c.execute(
                "INSERT INTO warning_log (uuid_id, warning_type, sent_at) VALUES (?, ?, ?) "
                "ON CONFLICT(uuid_id, warning_type) DO UPDATE SET sent_at=excluded.sent_at",
                (uuid_id, warning_type, datetime.now(pytz.utc))
            )

    def has_recent_warning(self, uuid_id: int, warning_type: str, hours: int = 24) -> bool:
        """
        بررسی می‌کند که آیا در چند ساعت گذشته هشدار مشخصی برای کاربر ارسال شده است یا خیر.
        """
        time_ago = datetime.now(pytz.utc) - timedelta(hours=hours)
        with self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM warning_log WHERE uuid_id = ? AND warning_type = ? AND sent_at >= ?",
                (uuid_id, warning_type, time_ago)
            ).fetchone()
            return row is not None

    def get_sent_warnings_since_midnight(self) -> List[Dict[str, Any]]:
        """
        گزارشی از تمام هشدارهایی که از نیمه‌شب امروز (به وقت تهران) ارسال شده‌اند را برمی‌گرداند.
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
        with self._conn() as c:
            rows = c.execute(query, (today_midnight_utc,)).fetchall()
            return [dict(r) for r in rows]

    # --- توابع مربوط به گزارش‌های ارسال شده (Sent Reports) ---

    def add_sent_report(self, user_id: int, message_id: int) -> None:
        """یک رکورد برای پیام گزارش ارسال شده (برای حذف خودکار در آینده) ثبت می‌کند."""
        with self._conn() as c:
            c.execute(
                "INSERT INTO sent_reports (user_id, message_id) VALUES (?, ?)",
                (user_id, message_id)
            )

    def get_old_reports_to_delete(self, hours: int = 12) -> List[Dict[str, Any]]:
        """پیام‌های گزارشی که قدیمی‌تر از زمان مشخص شده هستند را برای حذف برمی‌گرداند."""
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

    def delete_sent_report_record(self, record_id: int) -> None:
        """یک رکورد را از جدول sent_reports پس از حذف پیام، پاک می‌کند."""
        with self._conn() as c:
            c.execute("DELETE FROM sent_reports WHERE id = ?", (record_id,))
            
    # --- توابع مربوط به اعلان‌های عمومی (Notifications) ---

    def create_notification(self, user_id: int, title: str, message: str, category: str = 'info') -> None:
        """یک اعلان جدید برای نمایش در پنل وب کاربر در دیتابیس ثبت می‌کند."""
        with self._conn() as c:
            c.execute(
                "INSERT INTO notifications (user_id, title, message, category) VALUES (?, ?, ?, ?)",
                (user_id, title, message, category)
            )
            logger.info(f"Created notification for user {user_id}, category: {category}")

    def get_notifications_for_user(self, user_id: int, include_read: bool = False) -> List[Dict[str, Any]]:
        """لیست اعلان‌های یک کاربر را برمی‌گرداند. به طور پیش‌فرض فقط خوانده‌نشده‌ها را نشان می‌دهد."""
        query = "SELECT * FROM notifications WHERE user_id = ?"
        params = [user_id]
        
        if not include_read:
            query += " AND is_read = 0"
        
        query += " ORDER BY created_at DESC"
        
        with self._conn() as c:
            rows = c.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def mark_notification_as_read(self, notification_id: int, user_id: int) -> bool:
        """یک اعلان خاص را به عنوان خوانده شده علامت می‌زند."""
        with self._conn() as c:
            cursor = c.execute(
                "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
                (notification_id, user_id)
            )
            return cursor.rowcount > 0

    def mark_all_notifications_as_read(self, user_id: int) -> int:
        """تمام اعلان‌های خوانده نشده یک کاربر را خوانده شده می‌کند و تعداد آنها را برمی‌گرداند."""
        with self._conn() as c:
            cursor = c.execute(
                "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0",
                (user_id,)
            )
            return cursor.rowcount