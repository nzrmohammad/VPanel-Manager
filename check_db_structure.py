import sqlite3
import os

# مسیر فایل دیتابیس (مطابق با فایل‌های پروژه شما)
DB_PATH = "bot_data.db"

def inspect_database_structure():
    # بررسی وجود فایل دیتابیس
    if not os.path.exists(DB_PATH):
        print(f"❌ خطا: فایل دیتابیس در مسیر '{DB_PATH}' پیدا نشد.")
        return

    print(f"🔍 در حال اسکن ساختار دیتابیس: {DB_PATH}")
    print("=" * 60)

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # 1. دریافت لیست تمام جداول موجود در دیتابیس
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()

        if not tables:
            print("⚠️ هیچ جدولی در این دیتابیس یافت نشد.")
            return

        print(f"✅ تعداد {len(tables)} جدول پیدا شد.\n")

        # 2. پیمایش روی هر جدول و دریافت اطلاعات ستون‌ها
        for table in tables:
            table_name = table[0]
            # جداول داخلی sqlite را نادیده می‌گیریم
            if table_name.startswith('sqlite_'):
                continue
                
            print(f"📋 جدول: {table_name}")
            print("-" * 60)
            
            # هدر برای نمایش مرتب
            # CID: شناسه ستون | Type: نوع داده | PK: کلید اصلی
            print(f"{'Name':<25} | {'Type':<15} | {'NotNull':<8} | {'PK':<5} | {'Default'}")
            print("-" * 60)

            # دریافت اطلاعات ستون‌ها با دستور PRAGMA
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()

            for col in columns:
                # col[1]: نام ستون
                # col[2]: نوع داده (INTEGER, TEXT, ...)
                # col[3]: آیا نال بودن مجاز است؟ (1=نه، 0=بله)
                # col[4]: مقدار پیش‌فرض
                # col[5]: آیا کلید اصلی است؟ (1=بله)
                
                col_name = col[1]
                col_type = col[2]
                is_not_null = "Yes" if col[3] else "No"
                is_pk = "Yes" if col[5] else " "
                default_val = col[4] if col[4] is not None else "None"

                print(f"{col_name:<25} | {col_type:<15} | {is_not_null:<8} | {is_pk:<5} | {default_val}")
            
            print("\n" + "=" * 60 + "\n")

    except sqlite3.Error as e:
        print(f"❌ خطای SQL رخ داد: {e}")
    finally:
        if conn:
            conn.close()
            print("🔒 اتصال دیتابیس بسته شد.")

if __name__ == "__main__":
    inspect_database_structure()