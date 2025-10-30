# bot/db/feedback.py

from datetime import datetime
from typing import Any, Dict, List, Optional
import logging

from .base import DatabaseManager

logger = logging.getLogger(__name__)

class FeedbackDB(DatabaseManager):
    """
    کلاسی برای مدیریت تمام عملیات مربوط به بازخورد کاربران.
    """

    def add_feedback_rating(self, user_id: int, rating: int) -> int:
        """
        امتیاز اولیه کاربر را ثبت می‌کند و شناسه رکورد را برمی‌گرداند.
        """
        with self._conn() as c:
            cursor = c.execute(
                "INSERT INTO user_feedback (user_id, rating) VALUES (?, ?)",
                (user_id, rating)
            )
            return cursor.lastrowid

    def update_feedback_comment(self, feedback_id: int, comment: str):
        """
        نظر متنی کاربر را به رکورد بازخورد اضافه می‌کند.
        """
        with self._conn() as c:
            c.execute(
                "UPDATE user_feedback SET comment = ? WHERE id = ?",
                (comment, feedback_id)
            )

    def get_paginated_feedback(self, page: int, page_size: int = 10) -> List[Dict[str, Any]]:
        """
        بازخوردها را برای پنل ادمین به صورت صفحه‌بندی شده واکشی می‌کند.
        """
        offset = page * page_size
        query = """
            SELECT f.id, f.rating, f.comment, f.created_at, u.user_id, u.first_name
            FROM user_feedback f
            LEFT JOIN users u ON f.user_id = u.user_id
            ORDER BY f.created_at DESC
            LIMIT ? OFFSET ?
        """
        with self._conn() as c:
            rows = c.execute(query, (page_size, offset)).fetchall()
            return [dict(r) for r in rows]

    def get_feedback_count(self) -> int:
        """
        تعداد کل بازخوردهای ثبت شده را برمی‌گرداند.
        """
        with self._conn() as c:
            row = c.execute("SELECT COUNT(id) as count FROM user_feedback").fetchone()
            return row['count'] if row else 0