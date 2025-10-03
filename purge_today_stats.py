# File: manual_fix_today_stats.py
import sys
import os
import logging
from datetime import datetime
import pytz

# --- این بخش برای دسترسی به ماژول‌های ربات ضروری است ---
# اطمینان حاصل کنید که این اسکریپت در پوشه اصلی پروژه (کنار run_bot.py) قرار دارد
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
# ----------------------------------------------------

# --- ایمپورت‌های لازم از ماژول‌های ربات ---
from bot.database import db
from bot.combined_handler import get_all_users_combined
# -----------------------------------------

# --- تنظیمات اولیه لاگ برای مشاهده مراحل ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# -----------------------------------------

def fix_today_stats():
    """
    آمار مصرف امروز را با دریافت داده‌های زنده از پنل‌ها به طور کامل اصلاح می‌کند.
    """
    try:
        # 1. حذف تمام اسنپ‌شات‌های امروز
        deleted_count = db.delete_all_daily_snapshots()
        logging.info(f"Step 1: Successfully deleted {deleted_count} snapshots from today.")

        # 2. دریافت اطلاعات زنده و کامل کاربران از تمام پنل‌ها
        logging.info("Step 2: Fetching live user data from all panels...")
        all_users_info = get_all_users_combined()
        if not all_users_info:
            logging.error("Could not fetch any user data from panels. Aborting.")
            return

        user_info_map = {user['uuid']: user for user in all_users_info if user.get('uuid')}
        logging.info(f"  - Fetched data for {len(user_info_map)} users.")

        # 3. دریافت تمام کاربران فعال از دیتاباس ربات
        logging.info("Step 3: Fetching active users from bot database...")
        all_uuids_from_db = list(db.all_active_uuids())
        logging.info(f"  - Found {len(all_uuids_from_db)} active UUIDs in DB.")

        # 4. ثبت نقطه شروع جدید و صحیح برای امروز
        logging.info("Step 4: Creating new, correct baseline snapshots for today...")
        reset_count = 0
        for u_row in all_uuids_from_db:
            uuid_str = u_row['uuid']
            if uuid_str in user_info_map:
                info = user_info_map[uuid_str]
                breakdown = info.get('breakdown', {})

                # استخراج مصرف فعلی از داده‌های زنده پنل‌ها
                h_usage = sum(p.get('data', {}).get('current_usage_GB', 0.0) for p in breakdown.values() if p.get('type') == 'hiddify')
                m_usage = sum(p.get('data', {}).get('current_usage_GB', 0.0) for p in breakdown.values() if p.get('type') == 'marzban')
                
                # ثبت اسنپ‌شات جدید با داده‌های صحیح
                db.add_usage_snapshot(u_row['id'], h_usage, m_usage)
                reset_count += 1
        
        logging.info(f"  - Successfully created new baseline for {reset_count} active users.")
        print("\n\n✅✅✅ Operation successful! Today's usage stats have been fixed using live panel data.")

    except Exception as e:
        logging.error(f"An unexpected error occurred during the fix process: {e}", exc_info=True)
        print(f"\n❌ An error occurred: {e}")

if __name__ == "__main__":
    print("Starting the process to fix today's usage statistics...")
    fix_today_stats()