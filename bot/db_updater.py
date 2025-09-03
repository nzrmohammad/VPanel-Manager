# File: /opt/custom_bot/bot/db_updater.py (نسخه نهایی)
import sqlite3
import os
import secrets

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'bot_data.db')

def add_column_if_not_exists(cursor, table, column, definition):
    try:
        cursor.execute(f"SELECT {column} FROM {table} LIMIT 1;")
        print(f"✅ ستون '{column}' از قبل در جدول '{table}' وجود دارد.")
        return False # ستون از قبل وجود داشت
    except sqlite3.OperationalError:
        print(f"⚠️ ستون '{column}' یافت نشد. در حال اضافه کردن...")
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition};")
            print(f"✅ ستون '{column}' با موفقیت به جدول '{table}' اضافه شد.")
            return True # ستون جدید اضافه شد
        except Exception as e:
            print(f"❌ خطا در اضافه کردن ستون '{column}': {e}")
            return False

def run_update():
    if not os.path.exists(DB_PATH):
        print(f"❌ خطا: فایل دیتابیس در مسیر '{DB_PATH}' یافت نشد.")
        return

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        print("✅ با موفقیت به دیتابیس متصل شد.")

        # مرحله ۱: ستون‌ها را بدون محدودیت UNIQUE اضافه می‌کنیم
        referral_code_added = add_column_if_not_exists(cursor, "users", "referral_code", "TEXT")
        add_column_if_not_exists(cursor, "users", "referred_by_user_id", "INTEGER")
        add_column_if_not_exists(cursor, "users", "referral_reward_applied", "INTEGER DEFAULT 0")

        # مرحله ۲: اگر ستون referral_code به تازگی اضافه شده، آن را با مقادیر منحصر به فرد پر می‌کنیم
        if referral_code_added:
            print("\n⚠️ در حال ساخت کدهای معرف اولیه برای کاربران موجود...")
            cursor.execute("SELECT user_id FROM users WHERE referral_code IS NULL")
            users_to_update = cursor.fetchall()

            for row in users_to_update:
                user_id = row[0]
                while True:
                    new_code = "REF-" + secrets.token_urlsafe(4).upper().replace("_", "").replace("-", "")
                    # بررسی می‌کنیم که کد تولید شده تکراری نباشد
                    cursor.execute("SELECT 1 FROM users WHERE referral_code = ?", (new_code,))
                    if cursor.fetchone() is None:
                        cursor.execute("UPDATE users SET referral_code = ? WHERE user_id = ?", (new_code, user_id))
                        break
            print(f"✅ کدهای معرف اولیه برای {len(users_to_update)} کاربر ساخته شد.")

        # مرحله ۳: یک ایندکس UNIQUE روی ستون referral_code ایجاد می‌کنیم
        try:
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_referral_code ON users (referral_code);")
            print("✅ ایندکس UNIQUE برای ستون 'referral_code' با موفقیت ایجاد یا تایید شد.")
        except Exception as e:
            print(f"❌ خطا در ایجاد ایندکس UNIQUE: {e}")

        conn.commit()
        print("\n✅ عملیات آپدیت دیتابیس با موفقیت به پایان رسید.")

    except Exception as e:
        print(f"\n❌ یک خطای کلی در حین عملیات رخ داد: {e}")
    finally:
        if conn:
            conn.close()
            print("✅ اتصال از دیتابیس قطع شد.")

if __name__ == "__main__":
    run_update()