import sqlite3
from datetime import datetime
import pytz

# --- تنظیمات ---
DB_PATH = 'bot_data.db'
# --- پایان تنظیمات ---

def purge_and_reset_today():
    """
    تمام آمارهای غلط ثبت شده برای امروز را پاک کرده و یک نقطه شروع صحیح
    برای همه کاربران ایجاد می‌کند. این کار آمار گزارش‌های هفتگی را اصلاح می‌کند.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            
            tehran_tz = pytz.timezone("Asia/Tehran")
            now_in_tehran = datetime.now(tehran_tz)
            today_midnight_tehran = now_in_tehran.replace(hour=0, minute=0, second=0, microsecond=0)
            today_midnight_utc = today_midnight_tehran.astimezone(pytz.utc)

            # 1. حذف کامل تمام رکوردهای ثبت شده در امروز
            print(f"🗑️ Purging all usage snapshots recorded today (after {today_midnight_utc})...")
            cursor = c.execute("DELETE FROM usage_snapshots WHERE taken_at >= ?", (today_midnight_utc,))
            print(f"  - ✅ {cursor.rowcount} incorrect records from today have been deleted.")

            # 2. پیدا کردن تمام کاربران فعال برای ساختن نقطه شروع جدید
            print("\n rebuilding a clean baseline for today...")
            # از نام جدول صحیح 'user_uuids' استفاده شده است
            all_users = c.execute("SELECT id FROM user_uuids WHERE is_active = 1").fetchall()
            if not all_users:
                print("❌ No active users found.")
                return
            
            total_users = len(all_users)
            print(f"  - Found {total_users} active users.")
            
            processed_count = 0
            for user_row in all_users:
                user_id = user_row['id']
                
                # 3. پیدا کردن آخرین مصرف کل کاربر از دیروز (یا قبل‌تر)
                last_snapshot = c.execute(
                    "SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? ORDER BY taken_at DESC LIMIT 1",
                    (user_id,)
                ).fetchone()

                baseline_h_usage = 0.0
                baseline_m_usage = 0.0
                if last_snapshot:
                    baseline_h_usage = last_snapshot['hiddify_usage_gb'] or 0.0
                    baseline_m_usage = last_snapshot['marzban_usage_gb'] or 0.0

                # 4. ثبت نقطه شروع تمیز و جدید برای امروز بر اساس آمار دیروز
                c.execute(
                    "INSERT INTO usage_snapshots (uuid_id, hiddify_usage_gb, marzban_usage_gb, taken_at) VALUES (?, ?, ?, ?)",
                    (user_id, baseline_h_usage, baseline_m_usage, datetime.utcnow())
                )
                processed_count += 1

            conn.commit()
            print(f"  - ✅ New baseline created for all {processed_count} users.")
            print("\n\n✅✅✅ Operation successful! Today's historical stats have been corrected.")

    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")

if __name__ == "__main__":
    purge_and_reset_today()