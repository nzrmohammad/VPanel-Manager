import sqlite3
import sys
from datetime import datetime
import pytz

# --- تنظیمات ---
DB_PATH = 'bot_data.db'
# --- پایان تنظیمات ---

def manual_reset_user_usage(uuid_str: str):
    """
    مصرف امروز یک کاربر مشخص را بر اساس UUID او صفر می‌کند.
    این کار با حذف اسنپ‌شات‌های امروز و ایجاد یک نقطه شروع جدید انجام می‌شود.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            
            # 1. پیدا کردن ID داخلی کاربر از روی UUID
            print(f"🔍 Finding user with UUID: {uuid_str}...")
            # از نام جدول صحیح 'user_uuids' استفاده شده است
            user_row = c.execute("SELECT id FROM user_uuids WHERE uuid = ?", (uuid_str,)).fetchone()
            if not user_row:
                print(f"❌ ERROR: User with UUID '{uuid_str}' not found in 'user_uuids' table.")
                return
            
            user_id = user_row['id']
            print(f"✅ User found. Internal ID: {user_id}")

            # 2. پیدا کردن آخرین مصرف کل کاربر (برای ثبت به عنوان نقطه شروع)
            print("📊 Fetching current total usage...")
            last_snapshot = c.execute(
                "SELECT hiddify_usage_gb, marzban_usage_gb FROM usage_snapshots WHERE uuid_id = ? ORDER BY taken_at DESC LIMIT 1",
                (user_id,)
            ).fetchone()

            current_h_usage = 0.0
            current_m_usage = 0.0
            if last_snapshot:
                current_h_usage = last_snapshot['hiddify_usage_gb'] or 0.0
                current_m_usage = last_snapshot['marzban_usage_gb'] or 0.0
            
            print(f"  - Hiddify Total: {current_h_usage:.2f} GB")
            print(f"  - Marzban Total: {current_m_usage:.2f} GB")

            # 3. حذف تمام اسنپ‌شات‌های امروز برای این کاربر
            tehran_tz = pytz.timezone("Asia/Tehran")
            now_in_tehran = datetime.now(tehran_tz)
            today_midnight_tehran = now_in_tehran.replace(hour=0, minute=0, second=0, microsecond=0)
            today_midnight_utc = today_midnight_tehran.astimezone(pytz.utc)
            
            print(f"🗑️ Deleting today's snapshots (after {today_midnight_utc})...")
            cursor = c.execute("DELETE FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ?", (user_id, today_midnight_utc))
            print(f"  - {cursor.rowcount} records deleted.")

            # 4. ثبت یک اسنپ‌شات جدید به عنوان نقطه شروع امروز
            print("➕ Inserting new baseline snapshot for today...")
            c.execute(
                "INSERT INTO usage_snapshots (uuid_id, hiddify_usage_gb, marzban_usage_gb, taken_at) VALUES (?, ?, ?, ?)",
                (user_id, current_h_usage, current_m_usage, datetime.utcnow())
            )
            
            conn.commit()
            print("\n\n✅✅✅ Operation successful! Today's usage for this user has been reset to zero.")

    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python manual_reset_single_user.py <USER_UUID>")
        sys.exit(1)
    
    target_uuid = sys.argv[1]
    manual_reset_user_usage(target_uuid)