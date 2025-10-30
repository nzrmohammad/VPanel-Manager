# bot/db/support.py

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from .base import DatabaseManager

logger = logging.getLogger(__name__)

class SupportDB(DatabaseManager):
    """
    کلاسی برای مدیریت تمام عملیات مربوط به تیکت‌های پشتیبانی.
    """

    def create_support_ticket(self, user_id: int, initial_admin_message_id: int) -> int:
        """
        یک تیکت پشتیبانی جدید ایجاد می‌کند و شناسه آن را برمی‌گرداند.
        """
        with self._conn() as c:
            cursor = c.execute(
                "INSERT INTO support_tickets (user_id, initial_admin_message_id, status) VALUES (?, ?, ?)",
                (user_id, initial_admin_message_id, 'open')
            )
            return cursor.lastrowid

    def get_ticket_by_admin_message_id(self, admin_message_id: int) -> Optional[Dict[str, Any]]:
        """
        یک تیکت را بر اساس شناسه پیامی که برای ادمین ارسال شده، پیدا می‌کند.
        """
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM support_tickets WHERE initial_admin_message_id = ? AND status = 'open'",
                (admin_message_id,)
            ).fetchone()
            return dict(row) if row else None

    def close_ticket(self, ticket_id: int):
        """
        وضعیت یک تیکت را به 'closed' تغییر می‌دهد.
        """
        with self._conn() as c:
            c.execute("UPDATE support_tickets SET status = 'closed' WHERE id = ?", (ticket_id,))