# bot/db/usage.py

import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import logging
import pytz
import jdatetime

from .base import DatabaseManager

logger = logging.getLogger(__name__)


class UsageDB(DatabaseManager):
    """
    کلاسی برای مدیریت تمام عملیات مربوط به آمار مصرف (usage) کاربران و سیستم.
    """

    def add_usage_snapshot(self, uuid_id: int, hiddify_usage: float, marzban_usage: float) -> None:
        """یک اسنپ‌شات جدید از مصرف کاربر ثبت می‌کند."""
        with self._conn() as c:
            c.execute(
                "INSERT INTO usage_snapshots (uuid_id, hiddify_usage_gb, marzban_usage_gb, taken_at) VALUES (?, ?, ?, ?)",
                (uuid_id, hiddify_usage, marzban_usage, datetime.now(pytz.utc))
            )

    def get_usage_since_midnight(self, uuid_id: int) -> Dict[str, float]:
        """
        (نسخه اصلاح شده نهایی)
        مصرف روزانه کاربر را از نیمه‌شب به وقت تهران به صورت دقیق محاسبه می‌کند.
        این نسخه جدید، حالت‌های مختلف (مانند نبودن baseline) را مدیریت می‌کند.
        """
        try:
            tehran_tz = pytz.timezone("Asia/Tehran")
            now_in_tehran = datetime.now(tehran_tz)
            today_midnight_tehran = now_in_tehran.replace(hour=0, minute=0, second=0, microsecond=0)
            today_midnight_utc = today_midnight_tehran.astimezone(pytz.utc)

            with self._conn() as c:
                # آخرین اسنپ‌شات از قبل از امروز (به عنوان baseline اصلی)
                baseline_snap = c.execute(
                    "SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1",
                    (uuid_id, today_midnight_utc)
                ).fetchone()

                # اولین اسنپ‌شات امروز (به عنوان baseline جایگزین)
                first_today_snap = c.execute(
                    "SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ? ORDER BY taken_at ASC LIMIT 1",
                    (uuid_id, today_midnight_utc)
                ).fetchone()

                # آخرین اسنپ‌شات کلی (برای محاسبه مصرف نهایی)
                last_snap = c.execute(
                    "SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? ORDER BY taken_at DESC LIMIT 1",
                    (uuid_id,)
                ).fetchone()

                if not last_snap:
                    return {'hiddify': 0.0, 'marzban': 0.0}

                h_end = last_snap['hiddify_usage_gb'] or 0.0
                m_end = last_snap['marzban_usage_gb'] or 0.0
                h_start, m_start = 0.0, 0.0

                if baseline_snap:
                    # بهترین حالت: baseline از روز قبل وجود دارد
                    h_start = baseline_snap['hiddify_usage_gb'] or 0.0
                    m_start = baseline_snap['marzban_usage_gb'] or 0.0
                elif first_today_snap:
                    # حالت دوم: baseline از امروز صبح استفاده می‌شود
                    h_start = first_today_snap['hiddify_usage_gb'] or 0.0
                    m_start = first_today_snap['marzban_usage_gb'] or 0.0
                else:
                    # اگر هیچ اسنپ‌شاتی امروز یا قبل از آن وجود نداشته باشد، مصرف صفر است
                     return {'hiddify': 0.0, 'marzban': 0.0}


                # مدیریت حالت ریست شدن حجم (وقتی مصرف پایانی کمتر از مصرف اولیه است)
                h_usage = h_end - h_start if h_end >= h_start else h_end
                m_usage = m_end - m_start if m_end >= m_start else m_end

                return {'hiddify': max(0, h_usage), 'marzban': max(0, m_usage)}
        except Exception as e:
            logger.error(f"DB Error: Calculating daily usage for uuid_id {uuid_id}: {e}", exc_info=True)
            return {'hiddify': 0.0, 'marzban': 0.0}

    def get_usage_since_midnight_by_uuid(self, uuid_str: str) -> Dict[str, float]:
        uuid_id = self.get_uuid_id_by_uuid(uuid_str)
        if uuid_id:
            return self.get_usage_since_midnight(uuid_id)
        return {'hiddify': 0.0, 'marzban': 0.0}

    def get_user_daily_usage_history_by_panel(self, uuid_id: int, days: int = 7) -> list:
        """
        (نسخه اصلاح‌شده نهایی)
        محاسبه مصرف روزانه واقعی کاربر به تفکیک پنل‌ها با مدیریت هوشمند ریست API.
        """
        logger.info(f"Generating daily usage history for UUID {uuid_id} (last {days} days)...")
        tehran_tz = pytz.timezone("Asia/Tehran")
        now_in_tehran = datetime.now(tehran_tz)
        history = []

        with self._conn() as c:
            for i in range(days - 1, -1, -1):
                target_date = (now_in_tehran - timedelta(days=i)).date()
                day_start_utc = datetime(
                    target_date.year, target_date.month, target_date.day,
                    tzinfo=tehran_tz
                ).astimezone(pytz.utc)
                day_end_utc = day_start_utc + timedelta(days=1)

                try:
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
                    h_end = end_snap['hiddify_usage_gb'] if end_snap and end_snap['hiddify_usage_gb'] is not None else 0.0
                    m_end = end_snap['marzban_usage_gb'] if end_snap and end_snap['marzban_usage_gb'] is not None else 0.0

                    daily_h_usage = h_end - h_start if h_end >= h_start else h_end
                    daily_m_usage = m_end - m_start if m_end >= m_start else m_end

                    history.append({
                        "date": target_date,
                        "hiddify_usage": round(max(0.0, daily_h_usage), 2),
                        "marzban_usage": round(max(0.0, daily_m_usage), 2),
                        "total_usage": round(max(0.0, daily_h_usage) + max(0.0, daily_m_usage), 2)
                    })
                except Exception as e:
                    logger.error(f"Failed to calculate daily usage for {target_date}: {e}")
                    history.append({"date": target_date, "hiddify_usage": 0.0, "marzban_usage": 0.0, "total_usage": 0.0})
        return history

    def delete_all_daily_snapshots(self) -> int:
        """تمام اسنپ‌شات‌های مصرف امروز (به وقت UTC) را برای همه کاربران حذف می‌کند."""
        today_start_utc = datetime.now(pytz.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        with self._conn() as c:
            cursor = c.execute("DELETE FROM usage_snapshots WHERE taken_at >= ?", (today_start_utc,))
            deleted_count = cursor.rowcount
            logger.info(f"ADMIN ACTION: Deleted {deleted_count} daily snapshots for all users.")
            return deleted_count

    def delete_old_snapshots(self, days_to_keep: int = 3) -> int:
        """Deletes usage snapshots older than a specified number of days."""
        time_limit = datetime.now(pytz.utc) - timedelta(days=days_to_keep)
        with self._conn() as c:
            cursor = c.execute("DELETE FROM usage_snapshots WHERE taken_at < ?", (time_limit,))
            logger.info(f"Cleaned up {cursor.rowcount} old usage snapshots (older than {days_to_keep} days).")
            return cursor.rowcount

    def get_week_start_utc(self) -> datetime:
        """شروع هفته شمسی (شنبه) را به وقت UTC برمی‌گرداند."""
        tehran_tz = pytz.timezone("Asia/Tehran")
        now_jalali = jdatetime.datetime.now(tz=tehran_tz)
        days_since_saturday = (now_jalali.weekday() + 1) % 7
        week_start_gregorian = (datetime.now(tehran_tz) - timedelta(days=days_since_saturday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return week_start_gregorian.astimezone(pytz.utc)

    def get_weekly_usage_by_uuid(self, uuid_str: str) -> Dict[str, float]:
        """مصرف هفتگی یک UUID خاص را محاسبه می‌کند."""
        uuid_id = self.get_uuid_id_by_uuid(uuid_str)
        if not uuid_id:
            return {'hiddify': 0.0, 'marzban': 0.0}

        week_start_utc = self.get_week_start_utc()

        with self._conn() as c:
            start_h_row = c.execute("SELECT hiddify_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1", (uuid_id, week_start_utc)).fetchone()
            end_h_row = c.execute("SELECT hiddify_usage_gb FROM usage_snapshots WHERE uuid_id = ? ORDER BY taken_at DESC LIMIT 1", (uuid_id,)).fetchone()
            start_h = start_h_row['hiddify_usage_gb'] if start_h_row else 0.0
            end_h = end_h_row['hiddify_usage_gb'] if end_h_row else 0.0
            h_usage = end_h - start_h if end_h >= start_h else end_h

            start_m_row = c.execute("SELECT marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at < ? ORDER BY taken_at DESC LIMIT 1", (uuid_id, week_start_utc)).fetchone()
            end_m_row = c.execute("SELECT marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? ORDER BY taken_at DESC LIMIT 1", (uuid_id,)).fetchone()
            start_m = start_m_row['marzban_usage_gb'] if start_m_row else 0.0
            end_m = end_m_row['marzban_usage_gb'] if end_m_row else 0.0
            m_usage = end_m - start_m if end_m >= start_m else end_m

            return {'hiddify': max(0, h_usage), 'marzban': max(0, m_usage)}

    def get_panel_usage_in_intervals(self, uuid_id: int, panel_name: str) -> Dict[int, float]:
        """مصرف یک پنل خاص را در بازه‌های زمانی مختلف (۳، ۶، ۱۲، ۲۴ ساعت) محاسبه می‌کند."""
        if panel_name not in ['hiddify_usage_gb', 'marzban_usage_gb']:
            return {}

        now_utc = datetime.now(pytz.utc)
        intervals = {3: 0.0, 6: 0.0, 12: 0.0, 24: 0.0}

        with self._conn() as c:
            for hours in intervals.keys():
                time_ago = now_utc - timedelta(hours=hours)
                query = f"SELECT (MAX({panel_name}) - MIN({panel_name})) as usage FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ?"
                row = c.execute(query, (uuid_id, time_ago)).fetchone()
                if row and row['usage'] is not None:
                    intervals[hours] = max(0, row['usage'])
        return intervals

    def get_all_daily_usage_since_midnight(self) -> Dict[str, Dict[str, float]]:
        usage_map = {}
        all_uuids = self.get_all_user_uuids()
        for u in all_uuids:
            if u.get('is_active'):
                usage_map[u['uuid']] = self.get_usage_since_midnight(u['id'])
        return usage_map

    def get_daily_usage_summary(self) -> List[Dict[str, Any]]:
        """خلاصه مصرف روزانه کل سیستم برای ۷ روز گذشته را برمی‌گرداند."""
        today = datetime.now(pytz.timezone('Asia/Tehran')).date()
        summary = []
        for i in range(7):
            date_to_check = today - timedelta(days=i)
            start_of_day_utc = datetime(date_to_check.year, date_to_check.month, date_to_check.day, tzinfo=pytz.timezone('Asia/Tehran')).astimezone(pytz.utc)
            end_of_day_utc = start_of_day_utc + timedelta(days=1)
            
            with self._conn() as c:
                row = c.execute(
                    """
                    SELECT SUM(daily_h_usage), SUM(daily_m_usage) FROM (
                        SELECT
                            MAX(CASE WHEN taken_at < ? THEN hiddify_usage_gb ELSE 0 END) as h_start,
                            MAX(CASE WHEN taken_at < ? THEN hiddify_usage_gb ELSE NULL END) as h_end,
                            MAX(CASE WHEN taken_at < ? THEN marzban_usage_gb ELSE 0 END) as m_start,
                            MAX(CASE WHEN taken_at < ? THEN marzban_usage_gb ELSE NULL END) as m_end,
                            (MAX(hiddify_usage_gb) - MIN(hiddify_usage_gb)) as daily_h_usage,
                            (MAX(marzban_usage_gb) - MIN(marzban_usage_gb)) as daily_m_usage
                        FROM usage_snapshots
                        WHERE uuid_id IN (SELECT id FROM user_uuids WHERE is_active = 1)
                        AND taken_at >= ? AND taken_at < ?
                        GROUP BY uuid_id
                    )
                    """, (end_of_day_utc, end_of_day_utc, end_of_day_utc, end_of_day_utc, start_of_day_utc, end_of_day_utc)
                ).fetchone()
                total_usage = (row[0] or 0) + (row[1] or 0)
                summary.append({"date": date_to_check.strftime('%Y-%m-%d'), "total_usage": total_usage})
        return summary
    
    def get_new_users_per_month_stats(self) -> Dict[str, int]:
        """آمار کاربران جدید در هر ماه را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT strftime('%Y-%m', created_at) as month, COUNT(id) as count
                FROM users
                GROUP BY month
                ORDER BY month DESC
                LIMIT 12
            """).fetchall()
            return {row['month']: row['count'] for row in rows}

    def get_daily_active_users_count(self) -> int:
        """تعداد کاربران فعالی که در ۲۴ ساعت گذشته مصرف داشته‌اند را برمی‌گرداند."""
        yesterday = datetime.now(pytz.utc) - timedelta(days=1)
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(DISTINCT uuid_id) FROM usage_snapshots WHERE taken_at >= ?",
                (yesterday,)
            ).fetchone()
            return row[0] if row else 0

    def get_top_consumers_by_usage(self, limit: int = 10) -> List[Dict[str, Any]]:
        """لیست ۱۰ کاربر پرمصرف در ۳۰ روز گذشته را برمی‌گرداند."""
        thirty_days_ago = datetime.now(pytz.utc) - timedelta(days=30)
        with self._conn() as c:
            rows = c.execute("""
                SELECT u.telegram_id, u.name,
                       SUM(s.h_usage + s.m_usage) as total_usage
                FROM (
                    SELECT uuid_id,
                           MAX(hiddify_usage_gb) - MIN(hiddify_usage_gb) as h_usage,
                           MAX(marzban_usage_gb) - MIN(marzban_usage_gb) as m_usage
                    FROM usage_snapshots
                    WHERE taken_at >= ?
                    GROUP BY uuid_id
                ) s
                JOIN user_uuids uu ON s.uuid_id = uu.id
                JOIN users u ON uu.user_id = u.id
                GROUP BY u.id
                ORDER BY total_usage DESC
                LIMIT ?
            """, (thirty_days_ago, limit)).fetchall()
            return [dict(row) for row in rows]

    def get_new_users_in_range(self, start_date: datetime, end_date: datetime) -> int:
        """تعداد کاربران جدید در یک بازه زمانی مشخص را برمی‌گرداند."""
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(id) FROM users WHERE created_at >= ? AND created_at <= ?",
                (start_date, end_date)
            ).fetchone()
            return row[0] if row else 0

    def get_daily_usage_per_panel(self, days: int = 30) -> list[dict[str, Any]]:
        """
        (نسخه کاملاً اصلاح شده) مصرف روزانه را به تفکیک هر پنل محاسبه می‌کند
        """
        tehran_tz = pytz.timezone("Asia/Tehran")
        end_date = datetime.now(tehran_tz)
        
        # لیست تمام کاربران فعال
        all_uuids = self.get_all_active_uuids_with_user_id()
        uuid_ids = [u['id'] for u in all_uuids]

        # دیکشنری برای نگهداری مصرف روزانه
        daily_summary = {}

        with self._conn() as c:
            for i in range(days):
                target_date = (end_date - timedelta(days=i)).date()
                date_str = target_date.strftime('%Y-%m-%d')
                
                day_start_utc = datetime(
                    target_date.year, target_date.month, target_date.day,
                    tzinfo=tehran_tz
                ).astimezone(pytz.utc)
                day_end_utc = day_start_utc + timedelta(days=1)

                day_total_h_gb = 0.0
                day_total_m_gb = 0.0

                # برای هر کاربر
                for uuid_id in uuid_ids:
                    # 🔧 FIX: دریافت آخرین اسنپ‌شات قبل از این روز (baseline)
                    baseline_snap = c.execute(
                        """SELECT hiddify_usage_gb, marzban_usage_gb 
                        FROM usage_snapshots 
                        WHERE uuid_id = ? AND taken_at < ? 
                        ORDER BY taken_at DESC LIMIT 1""",
                        (uuid_id, day_start_utc)
                    ).fetchone()

                    # اولین اسنپ‌شات روز
                    first_snap = c.execute(
                        """SELECT hiddify_usage_gb, marzban_usage_gb 
                        FROM usage_snapshots 
                        WHERE uuid_id = ? AND taken_at >= ? AND taken_at < ? 
                        ORDER BY taken_at ASC LIMIT 1""",
                        (uuid_id, day_start_utc, day_end_utc)
                    ).fetchone()

                    # آخرین اسنپ‌شات روز
                    last_snap = c.execute(
                        """SELECT hiddify_usage_gb, marzban_usage_gb 
                        FROM usage_snapshots 
                        WHERE uuid_id = ? AND taken_at >= ? AND taken_at < ? 
                        ORDER BY taken_at DESC LIMIT 1""",
                        (uuid_id, day_start_utc, day_end_utc)
                    ).fetchone()

                    if not first_snap or not last_snap:
                        continue

                    # 🔧 FIX: اگر baseline داریم، از آن استفاده کن، وگرنه از صفر
                    if baseline_snap:
                        h_start = baseline_snap['hiddify_usage_gb'] or 0.0
                        m_start = baseline_snap['marzban_usage_gb'] or 0.0
                    else:
                        h_start = 0.0
                        m_start = 0.0

                    h_end = last_snap['hiddify_usage_gb'] or 0.0
                    m_end = last_snap['marzban_usage_gb'] or 0.0
                    
                    # محاسبه تفاضل با چک ریست شدن
                    h_diff = h_end - h_start
                    m_diff = m_end - m_start

                    # اگر منفی شد (ریست شده)، فقط مقدار نهایی را حساب کن
                    if h_diff < 0:
                        h_diff = h_end
                    if m_diff < 0:
                        m_diff = m_end

                    day_total_h_gb += max(0, h_diff)
                    day_total_m_gb += max(0, m_diff)

                daily_summary[date_str] = {
                    'total_h_gb': round(day_total_h_gb, 2),
                    'total_m_gb': round(day_total_m_gb, 2)
                }

        # مرتب‌سازی نهایی
        result = []
        for i in range(days):
            target_date = (end_date - timedelta(days=i)).date()
            date_str = target_date.strftime('%Y-%m-%d')
            data = daily_summary.get(date_str, {'total_h_gb': 0, 'total_m_gb': 0})
            result.append({
                'date': date_str,
                'total_h_gb': data['total_h_gb'],
                'total_m_gb': data['total_m_gb']
            })

        return result[::-1]  # معکوس کردن برای ترتیب زمانی صحیح

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

    def get_user_daily_usage_history(self, uuid_id: int, days: int = 7) -> List[Dict[str, Any]]:
        """تاریخچه مصرف روزانه یک کاربر را برمی‌گرداند."""
        return self.get_user_daily_usage_history_by_panel(uuid_id, days)

    def get_total_usage_in_last_n_days(self, days: int) -> float:
        """مجموع کل مصرف در N روز گذشته را برمی‌گرداند."""
        n_days_ago = datetime.now(pytz.utc) - timedelta(days=days)
        with self._conn() as c:
            row = c.execute(
                """
                SELECT SUM(s.h_usage + s.m_usage)
                FROM (
                    SELECT MAX(hiddify_usage_gb) - MIN(hiddify_usage_gb) as h_usage,
                           MAX(marzban_usage_gb) - MIN(marzban_usage_gb) as m_usage
                    FROM usage_snapshots
                    WHERE taken_at >= ?
                    GROUP BY uuid_id
                ) s
                """, (n_days_ago,)
            ).fetchone()
            return row[0] if row and row[0] is not None else 0.0

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
        
    def count_recently_active_users(self, all_users_data: list, minutes: int = 15) -> dict:
        """
        (نسخه نهایی و اصلاح شده) تعداد کاربران آنلاینی که در N دقیقه گذشته فعالیت داشته‌اند را
        بر اساس داده‌های مستقیم از پنل‌ها محاسبه می‌کند.
        """
        results = {'hiddify': 0, 'marzban_fr': 0, 'marzban_tr': 0, 'marzban_us': 0}
        time_limit = datetime.now(pytz.utc) - timedelta(minutes=minutes)

        for user in all_users_data:
            last_online = user.get('last_online')
            if not (user.get('is_active') and last_online and isinstance(last_online, datetime)):
                continue

            # Ensure last_online is timezone-aware for correct comparison
            last_online_aware = last_online if last_online.tzinfo else pytz.utc.localize(last_online)

            if last_online_aware >= time_limit:
                # Check which panel this user was active on based on the breakdown
                breakdown = user.get('breakdown', {})
                
                h_online = next((p['data'].get('last_online') for p in breakdown.values() if p.get('type') == 'hiddify'), None)
                m_online = next((p['data'].get('last_online') for p in breakdown.values() if p.get('type') == 'marzban'), None)
                
                # Determine the most recent panel activity
                if h_online and (not m_online or h_online >= m_online):
                    results['hiddify'] += 1
                elif m_online:
                    # To be more precise, you need to know which marzban server they connected to.
                    # This requires more specific data from the panel not currently available.
                    # As a fallback, we increment all accessible marzban servers.
                    user_record = self.get_user_uuid_record(user.get('uuid', ''))
                    if user_record:
                        if user_record.get('has_access_fr'):
                            results['marzban_fr'] += 1
                        if user_record.get('has_access_tr'):
                            results['marzban_tr'] += 1
                        if user_record.get('has_access_us'):
                            results['marzban_us'] += 1
                        if user_record.get('has_access_ro'):
                            results['marzban_us'] += 1    
        return results


    def get_weekly_top_consumers_report(self) -> List[Dict[str, Any]]:
        """گزارش هفتگی پرمصرف‌ترین کاربران را برمی‌گرداند."""
        week_start_utc = self.get_week_start_utc()
        with self._conn() as c:
            rows = c.execute("""
                SELECT u.name, SUM(s.h_usage + s.m_usage) as total_usage
                FROM (
                    SELECT uuid_id,
                           MAX(hiddify_usage_gb) - MIN(hiddify_usage_gb) as h_usage,
                           MAX(marzban_usage_gb) - MIN(marzban_usage_gb) as m_usage
                    FROM usage_snapshots
                    WHERE taken_at >= ?
                    GROUP BY uuid_id
                ) s
                JOIN user_uuids uu ON s.uuid_id = uu.id
                JOIN users u ON uu.user_id = u.id
                GROUP BY u.id
                ORDER BY total_usage DESC
                LIMIT 10
            """, (week_start_utc,)).fetchall()
            return [dict(row) for row in rows]

    def get_previous_week_usage(self, uuid_id: int) -> float:
        """Calculates the total usage for a specific user for the previous week."""
        tehran_tz = pytz.timezone("Asia/Tehran")
        today_jalali = jdatetime.datetime.now(tz=tehran_tz)
        days_since_saturday = today_jalali.weekday()
        
        current_week_start_utc = (datetime.now(tehran_tz) - timedelta(days=days_since_saturday)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.utc)
        previous_week_start_utc = current_week_start_utc - timedelta(days=7)
        
        total_usage = 0.0
        
        with self._conn() as c:
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

        with self._conn() as c:
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

        with self._conn() as c:
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

    def get_previous_day_total_usage(self) -> float:
        """مجموع مصرف کل در روز گذشته را برمی‌گرداند."""
        yesterday_summary = self.get_daily_usage_summary(days=2)
        return yesterday_summary[1]['total_usage'] if len(yesterday_summary) > 1 else 0.0

    def count_all_active_users(self) -> int:
        """تعداد کل کاربران فعال را شمارش می‌کند."""
        with self._conn() as c:
            row = c.execute("SELECT COUNT(id) FROM user_uuids WHERE is_active = 1").fetchone()
            return row[0] if row else 0