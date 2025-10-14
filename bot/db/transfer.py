# bot/db/transfer.py

from datetime import datetime, timedelta
from typing import Optional
import logging
import pytz

from .base import DatabaseManager

logger = logging.getLogger(__name__)

class TransferDB(DatabaseManager):
    """
    کلاسی برای مدیریت تمام عملیات مربوط به انتقال ترافیک بین کاربران.
    """

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
        with self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM traffic_transfers WHERE sender_uuid_id = ? AND transferred_at >= ?",
                (sender_uuid_id, thirty_days_ago)
            ).fetchone()
            return row is not None

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
        with self.write_conn() as c:
            cursor = c.execute("DELETE FROM traffic_transfers WHERE sender_uuid_id = ?", (sender_uuid_id,))
            return cursor.rowcount