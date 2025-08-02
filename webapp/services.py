from markupsafe import escape
from datetime import datetime, timedelta
import pytz
from bot.database import db
from bot.hiddify_api_handler import hiddify_handler
from bot.marzban_api_handler import marzban_handler
from bot.combined_handler import get_all_users_combined, get_combined_user_info
from bot.utils import to_shamsi, format_relative_time, format_usage, days_until_next_birthday
import logging
from bot.settings_manager import settings

logger = logging.getLogger(__name__)

# ===================================================================
# == توابع کمکی برای داشبورد ==
# ===================================================================

def _check_system_health():
    """وضعیت سلامت سرویس‌های خارجی را با مدیریت خطا بررسی می‌کند."""
    health = {}
    for name, handler in [('hiddify', hiddify_handler), ('marzban', marzban_handler), ('database', db)]:
        try:
            result = handler.check_connection()
            if isinstance(result, bool):
                health[name] = {'ok': result}
            else:
                # ✅ امن‌سازی پیام خطا
                if 'error' in result:
                    result['error'] = escape(result['error'])
                health[name] = result
        except Exception as e:
            logger.error(f"An exception occurred while checking connection for '{name}': {e}", exc_info=True)
            # ✅ امن‌سازی پیام خطا
            health[name] = {'ok': False, 'error': escape(str(e))}
    return health


def _process_user_data(all_users_data):
    stats = {
        "total_users": len(all_users_data), "active_users": 0, "online_users": 0,
        "expiring_soon_count": 0, "total_usage_today_gb": 0, "new_users_last_24h_count": 0,
        "hiddify_only_active": 0, "marzban_only_active": 0, "both_panels_active": 0
    }
    expiring_soon_users, new_users_last_24h, online_users_hiddify, online_users_marzban = [], [], [], []
    db_users_map = {u['uuid']: u for u in db.get_all_user_uuids()}
    now_utc = datetime.now(pytz.utc)

    for user in all_users_data:
        # ✅ امن‌سازی نام کاربر در ابتدای پردازش
        user['name'] = escape(user.get('name', 'کاربر ناشناس'))
        
        daily_usage = db.get_usage_since_midnight_by_uuid(user.get('uuid', ''))
        user['daily_usage_gb'] = sum(daily_usage.values())
        stats['total_usage_today_gb'] += user['daily_usage_gb']

        is_on_hiddify = 'hiddify' in user.get('breakdown', {})
        is_on_marzban = 'marzban' in user.get('breakdown', {})

        if user.get('is_active'):
            stats['active_users'] += 1
            if is_on_hiddify and not is_on_marzban:
                stats['hiddify_only_active'] += 1
            elif is_on_marzban and not is_on_hiddify:
                stats['marzban_only_active'] += 1
            elif is_on_hiddify and is_on_marzban:
                stats['both_panels_active'] += 1

        is_online_in_any_panel = False
        for panel_name, online_list in [('hiddify', online_users_hiddify), ('marzban', online_users_marzban)]:
            panel_info = user.get('breakdown', {}).get(panel_name, {})
            if panel_info:
                last_online = panel_info.get('last_online')
                if last_online and isinstance(last_online, datetime):
                    last_online_aware = last_online if last_online.tzinfo else pytz.utc.localize(last_online)
                    if (now_utc - last_online_aware).total_seconds() < 180:
                        if not any(u['uuid'] == user['uuid'] for u in online_list):
                            online_list.append(user)
                        is_online_in_any_panel = True

        if is_online_in_any_panel:
            stats['online_users'] += 1

        expire_days = user.get('expire')
        if expire_days is not None and 0 <= expire_days <= 7:
            stats['expiring_soon_count'] += 1
            expiring_soon_users.append(user)

        db_user = db_users_map.get(user.get('uuid'))
        if db_user and db_user.get('created_at'):
            created_at_dt = db_user['created_at']
            if created_at_dt.tzinfo is None: created_at_dt = pytz.utc.localize(created_at_dt)
            user['created_at'] = created_at_dt
            
            if (now_utc - created_at_dt) <= timedelta(hours=24):
                stats['new_users_last_24h_count'] += 1
                new_users_last_24h.append(user)

    return stats, expiring_soon_users, new_users_last_24h, online_users_hiddify, online_users_marzban

# ===================================================================
# == تابع اصلی سرویس داشبورد ==
# ===================================================================

def get_dashboard_data():
    system_health = _check_system_health()
    
    empty_stats = {
        "total_users": 0, "active_users": 0, "expiring_soon_count": 0, 
        "online_users": 0, "total_usage_today": "0 GB", "new_users_last_24h_count": 0
    }

    try:
        all_users_data = get_all_users_combined()
    except Exception as e:
        logger.error(f"Failed to get combined user data: {e}", exc_info=True)
        all_users_data = []

    try:
        daily_usage_summary = db.get_daily_usage_summary(days=7)
    except Exception as e:
        logger.error(f"Failed to get daily usage summary: {e}", exc_info=True)
        daily_usage_summary = []

    if not all_users_data:
        # ... (بخش مدیریت خطا در صورت خالی بودن لیست کاربران)
        # این بخش نیازی به امن‌سازی ندارد چون داده‌ای از کاربر نمایش نمی‌دهد
        return {
           "stats": empty_stats, "new_users_last_24h": [], "expiring_soon_users": [], 
           "top_consumers_today": [], "online_users_hiddify": [], "online_users_marzban": [],
           "panel_distribution_data": {"labels": ["فقط آلمان 🇩🇪", "فقط فرانسه 🇫🇷", "هر دو پنل (مشترک)"], "series": [0, 0, 0]},
           "system_health": system_health, "usage_chart_data": {"labels": [], "data": []},
           "top_consumers_chart_data": {"labels": [], "data": []}
        }

    stats, expiring_soon_users, new_users_last_24h, online_users_hiddify, online_users_marzban = _process_user_data(all_users_data)
    stats['total_usage_today'] = f"{stats['total_usage_today_gb']:.2f} GB"
    
    top_consumers_today = sorted(
        [u for u in all_users_data if u.get('daily_usage_gb', 0) > 0], 
        key=lambda u: u.get('daily_usage_gb', 0), 
        reverse=True
    )[:5]
    
    panel_distribution_data = {
        "labels": ["فقط آلمان 🇩🇪", "فقط فرانسه 🇫🇷", "هر دو پنل (مشترک)"],
        "series": [stats.get('hiddify_only_active', 0), stats.get('marzban_only_active', 0), stats.get('both_panels_active', 0)]
    }
    
    if daily_usage_summary:
        usage_chart_data = {
            "labels": [to_shamsi(datetime.strptime(item['date'], '%Y-%m-%d'), include_time=False) for item in daily_usage_summary],
            "data": [item['total_gb'] for item in daily_usage_summary]
        }
    else: 
        usage_chart_data = {"labels": [], "data": []}
    
    top_consumers_chart_data = {
        # ✅ نام کاربران اینجا هم امن‌سازی می‌شود
        "labels": [escape(user['name']) for user in top_consumers_today],
        "data": [round(user.get('daily_usage_gb', 0), 2) for user in top_consumers_today]
    }

    return {
        "stats": stats, "new_users_last_24h": new_users_last_24h, "expiring_soon_users": expiring_soon_users, 
        "top_consumers_today": top_consumers_today, "online_users_hiddify": online_users_hiddify, 
        "online_users_marzban": online_users_marzban, "panel_distribution_data": panel_distribution_data,
        "system_health": system_health, "usage_chart_data": usage_chart_data,
        "top_consumers_chart_data": top_consumers_chart_data
    }

# ===================================================================
# == سرویس گزارش جامع ==
# ===================================================================
def generate_comprehensive_report_data():
    logger.info("Starting comprehensive report generation...")
    all_users_data = get_all_users_combined()
    daily_usage_map = db.get_all_daily_usage_since_midnight()
    user_panel_info_map = { u.get('uuid'): {'on_hiddify': u.get('on_hiddify', False), 'on_marzban': u.get('on_marzban', False)} for u in all_users_data if u.get('uuid') }
    now_utc = datetime.now(pytz.utc)
    summary = { "total_users": len(all_users_data), "active_users": 0, "total_de": 0, "total_fr": 0, "active_de": 0, "active_fr": 0, "online_users": 0, "usage_de_gb": 0, "usage_fr_gb": 0 }
    online_users, active_last_24h, inactive_1_to_7_days, never_connected, expiring_soon_users = set(), [], [], [], []
    
    for user in all_users_data:
        # ✅ امن‌سازی نام کاربر
        user['name'] = escape(user.get('name', ''))
        
        uuid = user.get('uuid')
        panels = []
        if user.get('on_hiddify'): panels.append('🇩🇪'); summary['total_de'] += 1
        if user.get('on_marzban'): panels.append('🇫🇷'); summary['total_fr'] += 1
        user['panel_display'] = ' '.join(panels) if panels else '?'
        user_daily_usage = daily_usage_map.get(uuid, {'hiddify': 0, 'marzban': 0})
        summary['usage_de_gb'] += user_daily_usage['hiddify']; summary['usage_fr_gb'] += user_daily_usage['marzban']
        if user.get("is_active"):
            summary['active_users'] += 1
            if user.get('on_hiddify'): summary['active_de'] += 1
            if user.get('on_marzban'): summary['active_fr'] += 1
        if user.get('expire') is not None and 0 <= user.get('expire') <= 7: expiring_soon_users.append(user)
        last_online = user.get('last_online')
        if last_online:
            if last_online >= (now_utc - timedelta(minutes=3)): online_users.add(uuid)
            if last_online >= (now_utc - timedelta(hours=24)): user['last_online_relative'] = format_relative_time(last_online); active_last_24h.append(user)
            elif (now_utc - timedelta(days=7)) <= last_online < (now_utc - timedelta(days=1)): user['last_online_relative'] = format_relative_time(last_online); inactive_1_to_7_days.append(user)
        else: never_connected.append(user)

    summary['online_users'] = len(online_users); summary['total_usage'] = f"{(summary['usage_de_gb'] + summary['usage_fr_gb']):.2f} GB"
    top_consumers = sorted([u for u in all_users_data if u.get('usage', {}).get('data_limit_GB', 0) > 0], key=lambda u: u.get('usage', {}).get('total_usage_GB', 0), reverse=True)[:10]
    
    users_with_payments = db.get_payment_history()
    uuid_by_configname = {u.get('name'): u.get('uuid') for u in all_users_data}
    bot_user_map = db.get_uuid_to_bot_user_map() 

    for p in users_with_payments:
        p['payment_date_shamsi'] = to_shamsi(p.get('payment_date'), include_time=True)
        uuid = uuid_by_configname.get(p.get('name'))
        panels = []
        
        # ✅ امن‌سازی نام کانفیگ
        p['name'] = escape(p.get('name'))
        
        if uuid:
            panel_info = user_panel_info_map.get(uuid, {})
            user_details = bot_user_map.get(uuid, {}) 
            
            # ✅ امن‌سازی اطلاعات کاربر تلگرام
            p['user_id'] = escape(user_details.get('user_id'))
            p['first_name'] = escape(user_details.get('first_name', 'کاربر'))
            
            if panel_info.get('on_hiddify'): panels.append('🇩🇪')
            if panel_info.get('on_marzban'): panels.append('🇫🇷')
        
        p['panel_display'] = ' '.join(panels) if panels else '?'

    users_with_birthdays = db.get_users_with_birthdays()
    uuid_by_userid = {u['user_id']: u['uuid'] for u in db.get_all_user_uuids()}
    for b in users_with_birthdays:
        # ✅ امن‌سازی نام و نام خانوادگی
        b['first_name'] = escape(b.get('first_name'))
        b['last_name'] = escape(b.get('last_name'))
        
        uuid = uuid_by_userid.get(b['user_id']); panel_info = user_panel_info_map.get(uuid, {}); panels = []
        if panel_info.get('on_hiddify'): panels.append('🇩🇪')
        if panel_info.get('on_marzban'): panels.append('🇫🇷')
        b['panel_display'] = ' '.join(panels) if panels else '?'
        if b.get('birthday'): 
            try:
                b['birthday_shamsi'] = to_shamsi(b['birthday'])
                b['days_remaining'] = days_until_next_birthday(b['birthday'])
            except Exception as e:
                logger.error(f"Failed to process birthday for user {b.get('user_id')}: {e}")
                b['birthday_shamsi'] = 'خطا'
                b['days_remaining'] = -1
    
    return { 
        "summary": summary, "active_last_24h": sorted(active_last_24h, key=lambda u: u.get('last_online'), reverse=True), 
        "inactive_1_to_7_days": sorted(inactive_1_to_7_days, key=lambda u: u.get('last_online'), reverse=True), 
        "never_connected": sorted(never_connected, key=lambda u: u.get('name', '').lower()), 
        "top_consumers": top_consumers, "expiring_soon_users": sorted(expiring_soon_users, key=lambda u: u.get('expire', float('inf'))),
        "bot_users": db.get_all_bot_users(), "users_with_payments": users_with_payments, 
        "users_with_birthdays": sorted(users_with_birthdays, key=lambda u: u.get('days_remaining', 999)), 
        "today_shamsi": to_shamsi(datetime.now(), include_time=False) 
    }

def get_all_payments_for_admin():
    try:
        payments_data = db.get_all_payments_with_user_info()
        for payment in payments_data:
            payment['payment_date_shamsi'] = to_shamsi(payment.get('payment_date'), include_time=True)
            # ✅ امن‌سازی تمام فیلدهای متنی
            payment['config_name'] = escape(payment.get('config_name'))
            payment['first_name'] = escape(payment.get('first_name'))
            payment['username'] = escape(payment.get('username'))
        return payments_data
    except Exception as e:
        logger.error(f"Failed to get all payments for admin: {e}", exc_info=True)
        return []

# ===================================================================
# == سرویس مدیریت کاربران ==
# ===================================================================

def get_paginated_users(args: dict):
    # ۱. دریافت پارامترها (بدون تغییر)
    page = args.get('page', 1, type=int)
    per_page = args.get('per_page', 15, type=int)
    search_query = args.get('search', '', type=str).lower()
    panel_filter = args.get('panel', 'all', type=str)
    main_filter = args.get('filter', 'all', type=str)

    logger.info(f"Fetching users. Page: {page}, Query: '{search_query}', Panel: '{panel_filter}', Filter: '{main_filter}'")
    
    # ۲. دریافت داده‌های اولیه (بدون تغییر)
    all_users_data = get_all_users_combined()
    payment_counts = db.get_payment_counts()

    db_user_details_list = db.get_all_user_uuids()
    db_user_details_map = {
        u['uuid']: {
            'is_vip': bool(u.get('is_vip')),
            'has_access_de': bool(u.get('has_access_de')),
            'has_access_fr': bool(u.get('has_access_fr'))
        } for u in db_user_details_list if u.get('uuid')
    }

    # ۳. غنی‌سازی و امن‌سازی داده‌های کاربران
    for user in all_users_data:
        # ✅ امن‌سازی نام کاربر در همان ابتدا
        user['name'] = escape(user.get('name', ''))

        user['payment_count'] = payment_counts.get(user.get('name'), 0)
        
        user_uuid = user.get('uuid')
        if user_uuid:
            details = db_user_details_map.get(user_uuid, {'is_vip': False, 'has_access_de': True, 'has_access_fr': True})
            user.update(details)

            daily_usage = db.get_usage_since_midnight_by_uuid(user_uuid)
            if user.get('on_hiddify'):
                h_info = user.setdefault('breakdown', {}).setdefault('hiddify', {})
                h_info['daily_usage_formatted'] = format_usage(daily_usage.get('hiddify', 0))
                h_info['last_online_shamsi'] = to_shamsi(h_info.get('last_online'), include_time=True)

            if user.get('on_marzban'):
                m_info = user.setdefault('breakdown', {}).setdefault('marzban', {})
                m_info['daily_usage_formatted'] = format_usage(daily_usage.get('marzban', 0))
                m_info['last_online_shamsi'] = to_shamsi(m_info.get('last_online'), include_time=True)
        else:
            user.update({'is_vip': False, 'has_access_de': False, 'has_access_fr': False})

        if user.get('expire') is not None and user.get('expire') >= 0:
            user['expire_shamsi'] = to_shamsi(datetime.now() + timedelta(days=user.get('expire')))
        
        user['last_online_relative'] = format_relative_time(user.get('last_online'))

    # ۴. اعمال فیلترها (بدون تغییر)
    filtered_users = all_users_data

    if panel_filter == 'de':
        filtered_users = [u for u in filtered_users if u.get('on_hiddify')]
    elif panel_filter == 'fr':
        filtered_users = [u for u in filtered_users if u.get('on_marzban')]
    
    if main_filter == 'active':
        filtered_users = [u for u in filtered_users if u.get('is_active')]
    elif main_filter == 'online':
        now_utc = datetime.now(pytz.utc)
        online_deadline = now_utc - timedelta(minutes=3)
        filtered_users = [u for u in filtered_users if u.get('last_online') and u['last_online'].astimezone(pytz.utc) > online_deadline]
    elif main_filter == 'expiring_soon':
        filtered_users = [u for u in filtered_users if u.get('expire') is not None and 0 <= u['expire'] <= 7]
    
    if search_query:
        # ✅ اینجا هم نام کاربر قبلاً escape شده و جستجو روی آن انجام می‌شود که مشکلی ندارد
        filtered_users = [u for u in filtered_users if search_query in (u.get('name') or '').lower() or search_query in (u.get('uuid') or '').lower()]

    # ۵. مرتب‌سازی و صفحه‌بندی (بدون تغییر)
    filtered_users.sort(key=lambda u: (u.get('name') or '').lower())
    total_items = len(filtered_users)
    paginated_users = filtered_users[(page - 1) * per_page : page * per_page]
    
    return {
        "users": paginated_users,
        "pagination": {
            "page": page, "per_page": per_page,
            "total_items": total_items, "total_pages": (total_items + per_page - 1) // per_page
        }
    }

def create_user_in_panel(data: dict):
    panel = data.get('panel')
    # ✅ امن‌سازی ورودی کاربر قبل از ارسال به API
    if 'name' in data:
        data['name'] = escape(data['name'])
    if 'username' in data:
        data['username'] = escape(data['username'])
        
    logger.info(f"Attempting to create a new user in panel: '{panel}' with data: {data}")

    if panel == 'hiddify': result = hiddify_handler.add_user(data)
    elif panel == 'marzban': result = marzban_handler.add_user(data)
    else:
        logger.warning(f"Invalid panel specified for user creation: '{panel}'")
        raise ValueError('پنل نامعتبر است.')
        
    if not result or not (result.get('uuid') or result.get('username')):
        # ✅ امن‌سازی پیام خطای دریافتی از API
        error_detail = escape(result.get('detail', 'Unknown error from panel API'))
        logger.error(f"Failed to create user in panel '{panel}'. API Response: {error_detail}")
        raise Exception(error_detail)

    logger.info(f"Successfully created user in '{panel}'. Result: {result}")
    return result

def update_user_in_panels(data: dict):
    uuid = data.get('uuid')
    # ✅ امن‌سازی ورودی کاربر قبل از ارسال به API
    if 'common_name' in data:
        data['common_name'] = escape(data['common_name'])

    logger.info(f"Attempting to update user with UUID: {uuid}. Update data: {data}")

    if not uuid:
        logger.error("Update failed: UUID was not provided in the request data.")
        raise ValueError('UUID کاربر برای ویرایش مشخص نشده است.')
        
    if 'h_usage_limit_GB' in data or 'h_package_days' in data:
        h_payload = { 'usage_limit_GB': data.get('h_usage_limit_GB'), 'package_days': data.get('h_package_days') }
        if data.get('common_name'): h_payload['name'] = data.get('common_name')
        logger.info(f"Updating Hiddify user '{uuid}' with payload: {h_payload}")
        hiddify_handler.modify_user(uuid, h_payload)
        
    if 'm_usage_limit_GB' in data or 'm_expire_days' in data:
        m_payload = { 'data_limit': int(float(data['m_usage_limit_GB']) * 1024**3) if data.get('m_usage_limit_GB') else None, 'expire': int(timedelta(days=int(data['m_expire_days'])).total_seconds()) if data.get('m_expire_days') else None }
        marzban_username = get_combined_user_info(uuid).get('breakdown',{}).get('marzban',{}).get('username')
        if marzban_username: marzban_handler.modify_user(marzban_username, data=m_payload)
        else:
            logger.warning(f"Could not update Marzban user for UUID {uuid} because Marzban username was not found.")

    elif 'common_name' in data and 'h_usage_limit_GB' not in data:
         hiddify_handler.modify_user(uuid, {'name': data.get('common_name')})

    logger.info(f"Update process finished for user UUID: {uuid}")
    return True

def delete_user_from_panels(uuid: str):
    logger.info(f"Starting deletion process for user with UUID: {uuid}")
    user_info = get_combined_user_info(uuid)
    if not user_info: 
        logger.warning(f"Deletion failed. User with UUID '{uuid}' not found in any panel.")
        raise ValueError('کاربر یافت نشد.')
        
    if user_info.get('on_hiddify'):
        logger.info(f"Deleting user '{uuid}' from Hiddify panel.")
        hiddify_handler.delete_user(uuid)
        
    if user_info.get('on_marzban'):
        # ✅ نام کاربری که از API خوانده شده، قبل از استفاده باید امن بشه
        # هرچند در اینجا فقط برای لاگ و ارسال به تابع دیگه استفاده میشه و خطری نداره، ولی عادت خوبیه
        username = escape(user_info.get('breakdown', {}).get('marzban', {}).get('username'))
        if username: marzban_handler.delete_user(username)

    logger.info(f"Deleting user record for UUID '{uuid}' from the local database.")
    db.delete_user_by_uuid(uuid)
    logger.info(f"Deletion process for UUID '{uuid}' completed successfully.")
    return True
# ===================================================================
# == سرویس مدیریت قالب‌ها (نسخه امن‌شده) ==
# ===================================================================
def add_templates_from_text(raw_text: str):
    VALID_PROTOCOLS = ('vless://', 'vmess://', 'trojan://', 'ss://', 'ssr://')
    if not raw_text:
        logger.warning("add_templates_from_text called with empty input text.")
        raise ValueError('کادر ورود کانفیگ‌ها نمی‌تواند خالی باشد.')

    # ✅ امن‌سازی: هر خط از ورودی کاربر قبل از پردازش escape می‌شود.
    config_list = [escape(line.strip()) for line in raw_text.splitlines() if line.strip().startswith(VALID_PROTOCOLS)]
    
    if not config_list:
        logger.warning("No valid configs found in the provided text.")
        raise ValueError('هیچ کانفیگ معتبری یافت نشد.')

    added_count = db.add_batch_templates(config_list)
    logger.info(f"Successfully added {added_count} new templates to the database.")
    return added_count

def toggle_template(template_id: int):
    logger.info(f"Toggling status for template ID: {template_id}")
    db.toggle_template_status(template_id)
    return True

def update_template(template_id: int, template_str: str):
    logger.info(f"Attempting to update template ID: {template_id}")
    VALID_PROTOCOLS = ('vless://', 'vmess://', 'trojan://', 'ss://', 'ssr://')
    
    # ✅ امن‌سازی: رشته کانفیگ ورودی قبل از هر کاری escape می‌شود.
    safe_template_str = escape(template_str.strip())
    
    if not safe_template_str or not safe_template_str.startswith(VALID_PROTOCOLS):
        logger.warning(f"Update failed for template {template_id}: Invalid config string provided.")
        raise ValueError('رشته کانفیگ ارائه شده معتبر نیست.')
    
    db.update_template(template_id, safe_template_str)
    return True

def delete_template(template_id: int):
    logger.info(f"Deleting template ID: {template_id}")
    db.delete_template(template_id)
    return True

def get_analytics_data():
    all_users = get_all_users_combined()
    active_users_count = len([u for u in all_users if u.get('is_active')])
    now_utc = datetime.now(pytz.utc)
    online_deadline = now_utc - timedelta(minutes=3)
    online_users_count = len([u for u in all_users if u.get('last_online') and u['last_online'].astimezone(pytz.utc) > online_deadline])
    start_of_today_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    new_users_today_count = db.get_new_users_in_range(start_of_today_utc, now_utc)
    daily_usage_map = db.get_all_daily_usage_since_midnight()
    total_usage_today = sum(sum(usage.values()) for usage in daily_usage_map.values())

    kpis = {
        "active_users": active_users_count, "online_users": online_users_count,
        "new_users_today": new_users_today_count, "total_usage_today_gb": f"{total_usage_today:.2f} GB"
    }
    
    exp_buckets = {"<7": 0, "7-30": 0, "30-60": 0, ">60": 0}
    plan_buckets = {"0-50": 0, "50-100": 0, "100-150": 0, "150-200": 0, ">200": 0, "نامحدود": 0}
    for user in all_users:
        expire = user.get('expire'); limit = user.get('usage', {}).get('data_limit_GB', 0)
        if expire is not None:
            if expire < 7: exp_buckets["<7"] += 1
            elif 7 <= expire < 30: exp_buckets["7-30"] += 1
            elif 30 <= expire < 60: exp_buckets["30-60"] += 1
            else: exp_buckets[">60"] += 1
        if limit == 0: plan_buckets["نامحدود"] += 1
        elif limit <= 50: plan_buckets["0-50"] += 1
        elif limit <= 100: plan_buckets["50-100"] += 1
        elif limit <= 150: plan_buckets["100-150"] += 1
        elif limit <= 200: plan_buckets["150-200"] += 1
        else: plan_buckets[">200"] += 1

    expiration_labels = ["کمتر از ۷ روز", "۷ تا ۳۰ روز", "۳۰ تا ۶۰ روز", "بیش از ۶۰ روز"]
    expiration_series = [{"name": "تعداد کاربران", "data": list(exp_buckets.values())}]
    plan_labels = ["۰-۵۰ گیگ", "۵۰-۱۰۰ گیگ", "۱۰۰-۱۵۰ گیگ", "۱۵۰-۲۰۰ گیگ", "بیش از ۲۰۰ گیگ", "نامحدود"]
    plan_series = list(plan_buckets.values())
    top_consumers_data = db.get_top_consumers_by_usage(days=30, limit=10)
    
    # ✅ امن‌سازی نام کاربران برای لیبل نمودار
    top_consumers_labels = [escape(d.get('name', '')) for d in top_consumers_data]
    top_consumers_series_data = [round((d.get('h_usage', 0) or 0) + (d.get('m_usage', 0) or 0), 2) for d in top_consumers_data]
    
    daily_usage_per_panel = db.get_daily_usage_per_panel(days=30)
    usage_comparison_labels = [to_shamsi(datetime.strptime(d['date'], '%Y-%m-%d')) for d in daily_usage_per_panel]
    usage_comparison_series = [{"name": "آلمان 🇩🇪", "data": [d['total_h_gb'] for d in daily_usage_per_panel]}, {"name": "فرانسه 🇫🇷", "data": [d['total_m_gb'] for d in daily_usage_per_panel]}]

    active_users_by_panel = db.get_daily_active_users_by_panel(days=30)
    active_users_labels = [to_shamsi(datetime.strptime(d['date'], '%Y-%m-%d')) for d in active_users_by_panel]
    active_users_series = [{"name": "آلمان 🇩🇪", "data": [d['hiddify_users'] for d in active_users_by_panel]}, {"name": "فرانسه 🇫🇷", "data": [d['marzban_users'] for d in active_users_by_panel]}]

    return {
        "kpis": kpis,
        "expiration_chart": {"labels": expiration_labels, "series": expiration_series},
        "plan_distribution_chart": {"labels": plan_labels, "series": plan_series},
        "top_consumers_chart": {"labels": top_consumers_labels, "series": [{"name": "مصرف (GB)", "data": top_consumers_series_data}]},
        "usage_comparison_chart": {"labels": usage_comparison_labels, "series": usage_comparison_series},
        "active_users_by_panel_chart": {"labels": active_users_labels, "series": active_users_series}
    }


def get_all_settings() -> dict:
    logger.info("Fetching all settings directly from disk for the admin settings page.")
    try:
        all_settings = settings.get_all_from_disk()
        # ✅ امن‌سازی مقادیر متنی تنظیمات
        for key, value in all_settings.items():
            if isinstance(value, str):
                all_settings[key] = escape(value)
        logger.info(f"Successfully fetched and sanitized settings from disk: {all_settings}")
        return all_settings
    except Exception as e:
        logger.error(f"An error occurred while fetching settings from disk for UI: {e}", exc_info=True)
        return settings.settings

def save_all_settings(data: dict):
    logger.info(f"Attempting to save new settings via centralized manager: {data}")
    # ✅ امن‌سازی داده‌های ورودی قبل از ذخیره
    safe_data = {}
    for key, value in data.items():
        if isinstance(value, str):
            safe_data[key] = escape(value)
        else:
            safe_data[key] = value # برای مقادیر عددی یا boolean نیازی به escape نیست
            
    success = settings.save_settings(safe_data)
    if not success:
        raise Exception("A server-side error occurred while writing to the settings file.")
    return True

def toggle_user_vip_status(uuid: str):
    logger.info(f"Toggling VIP status for user UUID: {uuid}")
    db.toggle_user_vip(uuid)
    return True

def toggle_template_special_status(template_id: int):
    logger.info(f"Toggling Special status for template ID: {template_id}")
    db.toggle_template_special(template_id)
    return True
