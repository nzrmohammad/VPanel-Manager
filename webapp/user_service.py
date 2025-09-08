from markupsafe import escape
from datetime import datetime, timedelta
import pytz
from bot.database import db
from bot.combined_handler import get_combined_user_info
from bot.utils import to_shamsi, days_until_next_birthday, load_service_plans, parse_volume_string, get_loyalty_progress_message

import logging

logger = logging.getLogger(__name__)

class UserService:
    @staticmethod
    def get_user_usage_stats(uuid_id):
        tehran_tz = pytz.timezone("Asia/Tehran")
        labels, hiddify_data, marzban_data = [], [], []
        total_usage_7_days = 0
        
        with db._conn() as c:
            for i in range(6, -1, -1):
                target_date = datetime.now(tehran_tz) - timedelta(days=i)
                day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
                day_end = day_start + timedelta(days=1)
                day_start_utc, day_end_utc = day_start.astimezone(pytz.utc), day_end.astimezone(pytz.utc)
                
                query = "SELECT (MAX(hiddify_usage_gb) - MIN(hiddify_usage_gb)) as h, (MAX(marzban_usage_gb) - MIN(marzban_usage_gb)) as m FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ? AND taken_at < ?"
                row = c.execute(query, (uuid_id, day_start_utc, day_end_utc)).fetchone()
                
                h_usage = max(0, row['h'] or 0) if row else 0
                m_usage = max(0, row['m'] or 0) if row else 0
                
                labels.append(day_start.strftime('%m/%d'))
                hiddify_data.append(round(h_usage, 2))
                marzban_data.append(round(m_usage, 2))
                total_usage_7_days += h_usage + m_usage
        
        avg_daily_usage = total_usage_7_days / 7 if total_usage_7_days > 0 else 0
        chart_data = {"labels": labels, "hiddify_data": hiddify_data, "marzban_data": marzban_data}
        
        return chart_data, avg_daily_usage

    @staticmethod
    def recommend_plan(current_usage_gb):
        """
        این تابع اصلاح شده است تا بر اساس مصرف فعلی کاربر، پلن پیشنهاد دهد.
        """
        if current_usage_gb < 1:
            return None, 0

        all_plans = load_service_plans()
        best_plan = None
        smallest_diff = float('inf')

        for plan in all_plans:
            total_volume_gb = parse_volume_string(plan.get('total_volume') or plan.get('volume_de') or plan.get('volume_fr') or plan.get('volume_tr') or '0')
            if total_volume_gb > current_usage_gb:
                diff = total_volume_gb - current_usage_gb
                if diff < smallest_diff:
                    smallest_diff = diff
                    best_plan = plan
        
        # اگر هیچ پلنی حجمش بیشتر از مصرف فعلی نبود، بزرگترین پلن را پیشنهاد بده
        if not best_plan and all_plans:
            best_plan = max(all_plans, key=lambda p: parse_volume_string(p.get('total_volume') or p.get('volume_de') or p.get('volume_fr') or p.get('volume_tr') or '0'))

        return best_plan, current_usage_gb
    
    @staticmethod
    def get_birthday_info(user_basic):
        birthday = user_basic.get("birthday")
        days_until = days_until_next_birthday(birthday) if birthday else None
        message = None
        if days_until is not None:
            if days_until == 0: message = "🎉 تولدتان مبارک!"
            elif days_until <= 7: message = f"🎂 {days_until} روز تا تولد شما!"
        
        return {"days_until_birthday": days_until, "birthday_message": escape(message) if message else None, "has_birthday": birthday is not None}
    
    @staticmethod
    def get_general_status(is_active, expire_days, usage_percentage):
        if not is_active: return {"text": "غیرفعال", "class": "status-inactive"}
        if expire_days is not None and (expire_days < 7 or usage_percentage >= 90): return {"text": "رو به اتمام", "class": "status-warning"}
        return {"text": "فعال", "class": "status-active"}

    @staticmethod
    def get_online_status(last_online):
        online_status, online_class = "آفلاین", "offline"
        if last_online:
            now_utc = datetime.now(pytz.utc)
            if last_online.tzinfo is None: last_online = pytz.utc.localize(last_online)
            time_diff = (now_utc - last_online).total_seconds()
            if time_diff < 180: online_status, online_class = "آنلاین", "online"
            elif time_diff < 300: online_status, online_class = "اخیراً آنلاین", "recent"
        return online_status, online_class
        
    @staticmethod
    def get_user_breakdown_data(combined_info, usage_today):
        breakdown = combined_info.get('breakdown', {}).copy()
        
        for panel_name, panel_details in breakdown.items():
            panel_data = panel_details.get('data', {})
            panel_type = panel_details.get('type')

            panel_data['today_usage_GB'] = usage_today.get(panel_type, 0)

            usage = panel_data.get('current_usage_GB', 0)
            limit = panel_data.get('usage_limit_GB', 0)
            panel_data['usage_percentage'] = (usage / limit * 100) if limit > 0 else 0
            
            expire_val = panel_data.get('expire')
            panel_data['expire_shamsi'] = to_shamsi(datetime.now() + timedelta(days=expire_val)) if expire_val is not None else "نامشخص"

            last_online_dt = panel_data.get('last_online')
            panel_data['online_status'], _ = UserService.get_online_status(last_online_dt)
            panel_data['last_online_shamsi'] = to_shamsi(last_online_dt, include_time=True) if last_online_dt else "هرگز"
            
            breakdown[panel_name]['data'] = panel_data
            
        return breakdown

    @staticmethod
    def get_processed_user_data(uuid):
        try:
            uuid_record = db.get_user_uuid_record(uuid)
            if not uuid_record: return None
            
            uuid_id = uuid_record['id']
            user_basic = db.user(uuid_record.get('user_id')) or {}
            user_id = user_basic.get('user_id')
            combined_info = get_combined_user_info(uuid) or {}
            
            payment_history = db.get_user_payment_history(uuid_id)
            last_payment_shamsi, payment_count = "ثبت نشده", 0
            if payment_history:
                payment_count = len(payment_history)
                last_payment_date = payment_history[0].get('payment_date')
                if last_payment_date:
                    last_payment_shamsi = to_shamsi(last_payment_date, include_time=True)

            current_usage = combined_info.get('usage', {}).get('total_usage_GB', 0)
            usage_limit = combined_info.get('usage', {}).get('data_limit_GB', 0)
            usage_percentage = (current_usage / usage_limit * 100) if usage_limit > 0 else 0
            usage_today = db.get_usage_since_midnight_by_uuid(uuid)
            chart_data, avg_daily_usage = UserService.get_user_usage_stats(uuid_id)

            remaining_gb = usage_limit - current_usage
            days_to_depletion = (remaining_gb / avg_daily_usage) if avg_daily_usage > 0 and remaining_gb > 0 else 0

            is_active = uuid_record.get("is_active", 0) == 1
            expire_days = combined_info.get('expire')
            general_status = UserService.get_general_status(is_active, expire_days, usage_percentage)
            online_status, online_class = UserService.get_online_status(combined_info.get('last_online'))
            created_at_shamsi = to_shamsi(uuid_record.get('created_at'))
            expire_shamsi = to_shamsi(datetime.now() + timedelta(days=expire_days)) if expire_days is not None else "نامحدود"
            
            recommended_plan, actual_usage = UserService.recommend_plan(current_usage)
            
            loyalty_data = get_loyalty_progress_message(user_id) if user_id else None
            loyalty_message = None
            if loyalty_data:
                loyalty_message = (
                    f"💎 شما تاکنون {loyalty_data['payment_count']} بار سرویس خود را تمدید کرده‌اید.<br>"
                    f"فقط <b>{loyalty_data['renewals_left']} تمدید دیگر</b> "
                    f"تا دریافت هدیه بعدی ({loyalty_data['gb_reward']} گیگابایت حجم + {loyalty_data['days_reward']} روز اعتبار) باقی مانده است!"
                )

            achievements = db.get_user_achievements(user_id) if user_id else []

            return {
                "is_active": is_active,
                "username": escape(uuid_record.get("name", "کاربر")),
                "general_status": general_status,
                "expire_shamsi": escape(expire_shamsi),
                "expire": expire_days if expire_days is not None and expire_days >= 0 else 0,
                "last_payment_shamsi": escape(last_payment_shamsi),
                "payment_count": payment_count,
                "avg_daily_usage_GB": avg_daily_usage,
                "days_to_depletion": days_to_depletion,
                "online_status": escape(online_status),
                "online_class": escape(online_class),
                "created_at_shamsi": escape(created_at_shamsi),
                "current_usage_GB": current_usage,
                "usage_limit_GB": usage_limit,
                "usage_percentage": round(usage_percentage, 1),
                "usage_chart_data": chart_data,
                "breakdown": UserService.get_user_breakdown_data(combined_info, usage_today),
                **UserService.get_birthday_info(user_basic),
                "payment_history": payment_history,
                "recommended_plan": recommended_plan,
                "actual_last_30_days_usage": actual_usage,
                "loyalty_progress_message": loyalty_message, # This is now a formatted string
                "achievements": achievements,
                "has_access_de": uuid_record.get('has_access_de', False),
                "has_access_fr": uuid_record.get('has_access_fr', False),
                "has_access_tr": uuid_record.get('has_access_tr', False),
            }
        except Exception as e:
            logger.error(f"خطا در دریافت داده‌های کاربر {uuid}: {e}", exc_info=True)
            return None

    @staticmethod
    def update_user_profile(uuid, form_data):
        try:
            uuid_record = db.get_user_uuid_record(uuid)
            if not uuid_record:
                return False, "کاربر یافت نشد."

            uuid_id = uuid_record['id']
            user_id = uuid_record['user_id']
            user_basic = db.user(user_id)

            new_name = form_data.get('config_name')
            if new_name:
                db.update_config_name(uuid_id, escape(new_name))

            if not user_basic.get('birthday'):
                birthday_str = form_data.get('birthday')
                if birthday_str:
                    try:
                        birthday_date = datetime.strptime(birthday_str, '%Y-%m-%d').date()
                        db.update_user_birthday(user_id, birthday_date)
                    except ValueError:
                        logger.warning(f"فرمت تاریخ تولد نامعتبر: {birthday_str}")
            
            # --- START OF FIX ---
            settings_keys = {
                'daily_reports': 'daily_reports',
                'weekly_reports': 'weekly_reports',
                'expiry_warnings': 'expiry_warnings',
                'data_warning_de': 'data_warning_de',
                'data_warning_fr': 'data_warning_fr',
                'data_warning_tr': 'data_warning_tr',
                'achievement_alerts': 'achievement_alerts',
                'promotional_alerts': 'promotional_alerts'
            }
            for form_key, db_key in settings_keys.items():
                # اگر کلید در فرم بود یعنی روشن است، در غیر این صورت خاموش است
                value = form_key in form_data
                db.update_user_setting(user_id, db_key, value)
            # --- END OF FIX ---

            return True, "تغییرات با موفقیت ذخیره شد."
        except Exception as e:
            logger.error(f"خطا در به‌روزرسانی پروفایل کاربر {uuid}: {e}", exc_info=True)
            return False, escape(f"خطایی در هنگام ذخیره تغییرات رخ داد: {e}")

user_service = UserService()