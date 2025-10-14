# bot/db/usage.py

import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Any
import logging
import pytz
import jdatetime

from .base import DatabaseManager

logger = logging.getLogger(__name__)


class UsageDB(DatabaseManager):
    """
    کلاسی برای مدیریت تمام عملیات مربوط به مصرف (usage) کاربران.
    """

    def add_usage_snapshot(self, uuid_id: int, hiddify_usage: float, marzban_usage: float) -> None:
        """یک اسنپ‌شات جدید از مصرف کاربر ثبت می‌کند."""
        with self.write_conn() as c:
            c.execute(
                "INSERT INTO usage_snapshots (uuid_id, hiddify_usage_gb, marzban_usage_gb, taken_at) VALUES (?, ?, ?, ?)",
                (uuid_id, hiddify_usage, marzban_usage, datetime.now(pytz.utc))
            )

    def get_usage_since_midnight(self, uuid_id: int) -> Dict[str, float]:
        """
        مصرف روزانه کاربر را از نیمه‌شب به وقت تهران محاسبه می‌کند.
        این تابع با مقایسه آخرین اسنپ‌شات کلی با آخرین اسنپ‌شاتِ قبل از امروز کار می‌کند.
        """
        try:
            tehran_tz = pytz.timezone("Asia/Tehran")
            now_in_tehran = datetime.now(tehran_tz)
            today_midnight_tehran = now_in_tehran.replace(hour=0, minute=0, second=0, microsecond=0)
            today_midnight_utc = today_midnight_tehran.astimezone(pytz.utc)

            with self._conn() as c:
                # نقطه شروع: آخرین اسنپ‌شات قبل از شروع امروز
                baseline_snap = c.execute(
                    "SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1",
                    (uuid_id, today_midnight_utc)
                ).fetchone()

                # نقطه پایان: آخرین اسنپ‌شات ثبت شده برای کاربر
                last_snap = c.execute(
                    "SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? ORDER BY taken_at DESC LIMIT 1",
                    (uuid_id,)
                ).fetchone()

                if not last_snap:
                    return {'hiddify': 0.0, 'marzban': 0.0}

                h_start = baseline_snap['hiddify_usage_gb'] if baseline_snap and baseline_snap['hiddify_usage_gb'] is not None else 0.0
                m_start = baseline_snap['marzban_usage_gb'] if baseline_snap and baseline_snap['marzban_usage_gb'] is not None else 0.0

                h_end = last_snap['hiddify_usage_gb'] or 0.0
                m_end = last_snap['marzban_usage_gb'] or 0.0

                # مدیریت حالت ریست شدن حجم
                h_usage = h_end - h_start if h_end >= h_start else h_end
                m_usage = m_end - m_start if m_end >= m_start else m_end

                return {'hiddify': max(0, h_usage), 'marzban': max(0, m_usage)}
        except Exception as e:
            logger.error(f"DB Error: Calculating daily usage for uuid_id {uuid_id}: {e}", exc_info=True)
            return {'hiddify': 0.0, 'marzban': 0.0}

    def get_usage_since_midnight_by_uuid(self, uuid_str: str) -> Dict[str, float]:
        """مصرف روزانه را مستقیماً با استفاده از رشته UUID دریافت می‌کند."""
        uuid_id = self.get_uuid_id_by_uuid(uuid_str)
        if uuid_id:
            return self.get_usage_since_midnight(uuid_id)
        return {'hiddify': 0.0, 'marzban': 0.0}

    def get_user_daily_usage_history_by_panel(self, uuid_id: int, days: int = 7) -> list:
        """تاریخچه مصرف روزانه کاربر به تفکیک پنل‌ها را برمی‌گرداند."""
        tehran_tz = pytz.timezone("Asia/Tehran")
        now_in_tehran = datetime.now(tehran_tz)
        history = []

        with self._conn() as c:
            for i in range(days - 1, -1, -1):
                target_date = (now_in_tehran - timedelta(days=i)).date()
                day_start_utc = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tehran_tz).astimezone(pytz.utc)
                day_end_utc = day_start_utc + timedelta(days=1)

                baseline_snap = c.execute(
                    "SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1",
                    (uuid_id, day_start_utc)
                ).fetchone()
                end_snap = c.execute(
                    "SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1",
                    (uuid_id, day_end_utc)
                ).fetchone()

                if not end_snap:
                    history.append({"date": target_date, "hiddify_usage": 0.0, "marzban_usage": 0.0, "total_usage": 0.0})
                    continue

                h_start = baseline_snap['hiddify_usage_gb'] if baseline_snap and baseline_snap['hiddify_usage_gb'] is not None else 0.0
                m_start = baseline_snap['marzban_usage_gb'] if baseline_snap and baseline_snap['marzban_usage_gb'] is not None else 0.0
                h_end = end_snap['hiddify_usage_gb'] or 0.0
                m_end = end_snap['marzban_usage_gb'] or 0.0

                daily_h_usage = h_end - h_start if h_end >= h_start else h_end
                daily_m_usage = m_end - m_start if m_end >= m_start else m_end

                daily_h_usage = max(0.0, daily_h_usage)
                daily_m_usage = max(0.0, daily_m_usage)

                history.append({
                    "date": target_date,
                    "hiddify_usage": round(daily_h_usage, 2),
                    "marzban_usage": round(daily_m_usage, 2),
                    "total_usage": round(daily_h_usage + daily_m_usage, 2)
                })
        return history

    def get_weekly_usage_by_time_of_day(self, uuid_id: int) -> dict:
        """مصرف هفتگی کاربر را به تفکیک بازه‌های زمانی روز محاسبه می‌کند."""
        tehran_tz = pytz.timezone("Asia/Tehran")
        today_jalali = jdatetime.datetime.now(tz=tehran_tz)
        days_since_saturday = (today_jalali.weekday() + 1) % 7 # شنبه = 0
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

    def delete_all_daily_snapshots(self) -> int:
        """تمام اسنپ‌شات‌های مصرف امروز را برای همه کاربران حذف می‌کند."""
        today_start_utc = datetime.now(pytz.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        with self.write_conn() as c:
            cursor = c.execute("DELETE FROM usage_snapshots WHERE taken_at >= ?", (today_start_utc,))
            return cursor.rowcount

    def delete_old_snapshots(self, days_to_keep: int = 7) -> int:
        """اسنپ‌شات‌های قدیمی‌تر از تعداد روز مشخص شده را حذف می‌کند."""
        time_limit = datetime.now(pytz.utc) - timedelta(days=days_to_keep)
        with self.write_conn() as c:
            cursor = c.execute("DELETE FROM usage_snapshots WHERE taken_at < ?", (time_limit,))
            return cursor.rowcount