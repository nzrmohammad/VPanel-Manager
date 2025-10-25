# bot/db/achievement.py

import pytz
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import sqlite3

from .base import DatabaseManager

logger = logging.getLogger(__name__)

class AchievementDB(DatabaseManager):
    """
    کلاسی برای مدیریت دستاوردها، امتیازات، سیستم معرفی و قرعه‌کشی.
    """

    def add_achievement(self, user_id: int, badge_code: str) -> bool:
        """یک دستاورد جدید برای کاربر ثبت می‌کند و در صورت موفقیت (عدم تکرار) True برمی‌گرداند."""
        with self._conn() as c:
            try:
                c.execute(
                    "INSERT INTO user_achievements (user_id, badge_code) VALUES (?, ?)",
                    (user_id, badge_code)
                )
                return True
            except sqlite3.IntegrityError:  # Handles UNIQUE constraint violation
                logger.info(f"User {user_id} already has achievement {badge_code}.")
                return False

    def get_user_achievements(self, user_id: int) -> List[str]:
        """لیست کدهای تمام نشان‌های یک کاربر را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute("SELECT badge_code FROM user_achievements WHERE user_id = ?", (user_id,)).fetchall()
            return [row['badge_code'] for row in rows]

    def add_achievement_points(self, user_id: int, points: int):
        """امتیاز به حساب دستاوردهای یک کاربر اضافه می‌کند."""
        with self._conn() as c:
            c.execute("UPDATE users SET achievement_points = achievement_points + ? WHERE user_id = ?", (points, user_id))
        self.clear_user_cache(user_id)

    def spend_achievement_points(self, user_id: int, points: int) -> bool:
        """امتیاز را از حساب کاربر کم می‌کند و موفقیت عملیات را برمی‌گرداند."""
        with self._conn() as c:
            current_points_row = c.execute("SELECT achievement_points FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if current_points_row and current_points_row['achievement_points'] >= points:
                c.execute("UPDATE users SET achievement_points = achievement_points - ? WHERE user_id = ?", (points, user_id))
                self.clear_user_cache(user_id)
                return True
            return False

    def log_shop_purchase(self, user_id: int, item_key: str, cost: int):
        """یک خرید از فروشگاه دستاوردها را در دیتابیس ثبت می‌کند."""
        with self._conn() as c:
            c.execute("INSERT INTO achievement_shop_log (user_id, item_key, cost) VALUES (?, ?, ?)", (user_id, item_key, cost))

    def get_achievement_leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        """لیستی از کاربران برتر بر اساس امتیاز دستاوردها را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT user_id, first_name, achievement_points FROM users WHERE achievement_points > 0 ORDER BY achievement_points DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_users_by_points(self) -> List[Dict[str, Any]]:
        """تمام کاربرانی که امتیاز دارند را به همراه لیست نشان‌هایشان به ترتیب امتیاز برمی‌گرداند."""
        with self._conn() as c:
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
        """امتیاز تمام کاربران را به صفر ریست کرده و تعداد کاربران آپدیت شده را برمی‌گرداند."""
        with self._conn() as c:
            cursor = c.execute("UPDATE users SET achievement_points = 0;")
            self._user_cache.clear()
            return cursor.rowcount

    def delete_all_achievements(self) -> int:
        """تمام رکوردهای دستاوردهای کسب شده را حذف کرده و تعداد ردیف‌های حذف شده را برمی‌گرداند."""
        with self._conn() as c:
            cursor = c.execute("DELETE FROM user_achievements;")
            return cursor.rowcount

    def get_user_achievements_in_range(self, user_id: int, start_date: datetime) -> List[Dict[str, Any]]:
        """تمام دستاوردهای کسب شده توسط یک کاربر در یک بازه زمانی مشخص را برمی‌گرداند."""
        query = "SELECT badge_code, awarded_at FROM user_achievements WHERE user_id = ? AND awarded_at >= ? ORDER BY awarded_at DESC"
        with self._conn() as c:
            rows = c.execute(query, (user_id, start_date)).fetchall()
            return [dict(r) for r in rows]
            
    def get_daily_achievements(self) -> List[Dict[str, Any]]:
        """کاربرانی که امروز دستاوردی کسب کرده‌اند را به همراه جزئیات برمی‌گرداند."""
        tehran_tz = pytz.timezone("Asia/Tehran")
        today_midnight_tehran = datetime.now(tehran_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        today_midnight_utc = today_midnight_tehran.astimezone(pytz.utc)

        query = """
            SELECT u.user_id, u.first_name, ua.badge_code
            FROM user_achievements ua
            JOIN users u ON ua.user_id = u.user_id
            WHERE ua.awarded_at >= ?
            ORDER BY u.user_id;
        """
        with self._conn() as c:
            rows = c.execute(query, (today_midnight_utc,)).fetchall()
            return [dict(r) for r in rows]


    # --- توابع مربوط به قهرمانی هفتگی و قرعه‌کشی ---

    def log_weekly_champion_win(self, user_id: int):
        """یک رکورد برای قهرمانی هفتگی کاربر ثبت می‌کند."""
        today = datetime.now(pytz.utc).date()
        with self._conn() as c:
            c.execute("INSERT INTO weekly_champion_log (user_id, win_date) VALUES (?, ?)", (user_id, today))

    def count_consecutive_weekly_wins(self, user_id: int) -> int:
        """تعداد قهرمانی‌های هفتگی متوالی یک کاربر را محاسبه می‌کند."""
        with self._conn() as c:
            rows = c.execute("SELECT win_date FROM weekly_champion_log WHERE user_id = ? ORDER BY win_date DESC", (user_id,)).fetchall()
        
        if not rows: return 0

        consecutive_wins = 0
        last_win_date = None
        for row in rows:
            win_date = row['win_date']
            if isinstance(win_date, str):
                win_date = datetime.strptime(win_date, '%Y-%m-%d').date()

            if last_win_date is None:
                consecutive_wins = 1
            elif (last_win_date - win_date).days in [6, 7, 8]:
                consecutive_wins += 1
            else:
                break
            last_win_date = win_date
        return consecutive_wins
    
    def get_lottery_participants(self) -> List[int]:
        """لیست شناسه‌های کاربری واجد شرایط برای قرعه‌کشی را برمی‌گرداند."""
        thirty_days_ago = datetime.now(pytz.utc) - timedelta(days=30)
        query = """
            SELECT DISTINCT u.user_id
            FROM users u
            JOIN user_uuids uu ON u.user_id = uu.user_id
            JOIN usage_snapshots us ON uu.id = us.uuid_id
            WHERE us.taken_at >= ?
        """
        with self._conn() as c:
            rows = c.execute(query, (thirty_days_ago,)).fetchall()
            return [row['user_id'] for row in rows]
    
    def get_lottery_participant_details(self) -> List[Dict[str, Any]]:
        """لیست کاربران واجد شرایط برای قرعه‌کشی را به همراه نام و تعداد نشان خوش‌شانس برمی‌گرداند."""
        query = """
            SELECT u.user_id, u.first_name, COUNT(ua.id) as lucky_badge_count
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

    def clear_lottery_tickets(self):
        """تمام بلیط‌های قرعه‌کشی را پاک می‌کند (در صورت وجود جدول مربوطه)."""
        # Placeholder logic. If you have a separate table for tickets, implement deletion here.
        pass

    # --- توابع مربوط به درخواست نشان ---
    
    def add_achievement_request(self, user_id: int, badge_code: str) -> int:
        """یک درخواست نشان جدید ثبت کرده و شناسه آن را برمی‌گرداند."""
        with self._conn() as c:
            cursor = c.execute("INSERT INTO achievement_requests (user_id, badge_code) VALUES (?, ?)", (user_id, badge_code))
            return cursor.lastrowid

    def get_achievement_request(self, request_id: int) -> Optional[Dict[str, Any]]:
        """اطلاعات یک درخواست نشان را با شناسه آن بازیابی می‌کند."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM achievement_requests WHERE id = ?", (request_id,)).fetchone()
            return dict(row) if row else None

    def update_achievement_request_status(self, request_id: int, status: str, admin_id: int):
        """وضعیت یک درخواست نشان را به‌روزرسانی می‌کند."""
        with self._conn() as c:
            c.execute(
                "UPDATE achievement_requests SET status = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?",
                (status, admin_id, datetime.now(pytz.utc), request_id)
            )

    def check_if_gift_given(self, user_id: int, gift_type: str, year: int) -> bool:
        """بررسی می‌کند که آیا هدیه‌ای در سال جاری به کاربر داده شده است یا خیر."""
        table_map = {
            'birthday': 'birthday_gift_log',
            'anniversary_1': 'anniversary_gift_log',
            # ... سایر انواع هدیه
        }
        table_name = table_map.get(gift_type)
        if not table_name: return False
        
        with self._conn() as c:
            row = c.execute(
                f"SELECT 1 FROM {table_name} WHERE user_id = ? AND gift_year = ?",
                (user_id, year)
            ).fetchone()
            return row is not None

    def log_gift_given(self, user_id: int, gift_type: str, year: int):
        """ثبت می‌کند که هدیه‌ای در سال جاری به کاربر داده شده است."""
        table_map = {
            'birthday': 'birthday_gift_log',
            'anniversary_1': 'anniversary_gift_log',
            # ... سایر انواع هدیه
        }
        table_name = table_map.get(gift_type)
        if not table_name: return

        with self._conn() as c:
            c.execute(
                f"INSERT OR IGNORE INTO {table_name} (user_id, gift_year) VALUES (?, ?)",
                (user_id, year)
            )