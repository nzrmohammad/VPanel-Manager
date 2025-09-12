from markupsafe import escape
from datetime import datetime, timedelta
import pytz
from bot.database import db
from bot.hiddify_api_handler import HiddifyAPIHandler  
from bot.marzban_api_handler import MarzbanAPIHandler 
from bot.combined_handler import get_all_users_combined, get_combined_user_info, search_user
from bot.utils import to_shamsi, format_relative_time, format_usage, days_until_next_birthday
import logging
from bot.config import DAILY_REPORT_TIME, USAGE_WARNING_CHECK_HOURS
from html import unescape
from html import escape as html_escape


logger = logging.getLogger(__name__)

try:
    active_panels = db.get_active_panels()
    
    hiddify_panel_config = next((p for p in active_panels if p['panel_type'] == 'hiddify'), None)
    marzban_panel_config = next((p for p in active_panels if p['panel_type'] == 'marzban'), None)

    hiddify_handler = HiddifyAPIHandler(hiddify_panel_config) if hiddify_panel_config else None
    marzban_handler = MarzbanAPIHandler(marzban_panel_config) if marzban_panel_config else None
    
    if hiddify_handler:
        logger.info(f"WebApp services initialized default Hiddify handler for panel: {hiddify_panel_config.get('name')}")
    if marzban_handler:
        logger.info(f"WebApp services initialized default Marzban handler for panel: {marzban_panel_config.get('name')}")

except Exception as e:
    logger.error(f"Could not initialize default handlers for webapp: {e}", exc_info=True)
    hiddify_handler = None
    marzban_handler = None

# ===================================================================
# == توابع کمکی برای داشبورد ==
# ===================================================================

def _check_system_health():
    """وضعیت سلامت سرویس‌های خارجی را با مدیریت خطا بررسی می‌کند."""
    health = {}
    
    handlers_to_check = [('database', db)]
    if hiddify_handler:
        handlers_to_check.append(('hiddify', hiddify_handler))
    if marzban_handler:
        handlers_to_check.append(('marzban', marzban_handler))

    for name, handler in handlers_to_check:
        try:
            result = handler.check_connection()
            health[name] = {'ok': result}
        except Exception as e:
            logger.error(f"An exception occurred while checking connection for '{name}': {e}", exc_info=True)
            health[name] = {'ok': False, 'error': html_escape(str(e))}
    return health

def _process_user_data(all_users_data):
    stats = {
        "total_users": len(all_users_data), "active_users": 0, "online_users": 0,
        "expiring_soon_count": 0, "new_users_last_24h_count": 0,
        "hiddify_only_active": 0, "marzban_only_active": 0, "both_panels_active": 0
    }
    expiring_soon_users, new_users_last_24h, online_users_hiddify, online_users_marzban = [], [], [], []
    db_users_map = {u['uuid']: u for u in db.get_all_user_uuids()}
    now_utc = datetime.now(pytz.utc)

    for user in all_users_data:
        user['name'] = html_escape(user.get('name', 'کاربر ناشناس'))
        
        user_breakdown = user.get('breakdown', {})
        is_on_hiddify = any(p.get('type') == 'hiddify' for p in user_breakdown.values())
        is_on_marzban = any(p.get('type') == 'marzban' for p in user_breakdown.values())

        if user.get('is_active'):
            stats['active_users'] += 1
            if is_on_hiddify and not is_on_marzban:
                stats['hiddify_only_active'] += 1
            elif is_on_marzban and not is_on_hiddify:
                stats['marzban_only_active'] += 1
            elif is_on_hiddify and is_on_marzban:
                stats['both_panels_active'] += 1

        last_online = user.get('last_online')
        if last_online and isinstance(last_online, datetime):
            last_online_aware = last_online if last_online.tzinfo else pytz.utc.localize(last_online)
            if (now_utc - last_online_aware).total_seconds() < 180:
                stats['online_users'] += 1
                
                # --- START OF FIX ---
                h_online = next((p['data'].get('last_online') for p in user_breakdown.values() if p.get('type') == 'hiddify'), None)
                m_online = next((p['data'].get('last_online') for p in user_breakdown.values() if p.get('type') == 'marzban'), None)
                
                if h_online and (not m_online or h_online >= m_online):
                    online_users_hiddify.append(user)
                elif m_online:
                    online_users_marzban.append(user)
                # --- END OF FIX ---

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
# == تابع اصلی سرویس داشبورد (نسخه نهایی و اصلاح شده) ==
# ===================================================================
def get_dashboard_data():
    """
    داده‌های کامل و پردازش‌شده را برای داشبورد ادمین جمع‌آوری می‌کند.
    این نسخه شامل اصلاحیه محاسبه دقیق مصرف روزانه است.
    """
    system_health = _check_system_health()
    
    empty_stats = {
        "total_users": 0, "active_users": 0, "expiring_soon_count": 0, 
        "online_users": 0, "total_usage_today": "0 GB", "new_users_last_24h_count": 0
    }

    try:
        # 🔥 تغییر اصلی اینجاست: ابتدا مصرف روزانه صحیح را برای همه کاربران یکجا می‌خوانیم
        all_daily_usages = db.get_all_daily_usage_since_midnight()
        all_users_data = get_all_users_combined()
        
        total_usage_today_gb = 0
        
        # سپس، مصرف محاسبه‌شده را به اطلاعات هر کاربر اضافه می‌کنیم
        for user in all_users_data:
            uuid = user.get('uuid')
            if not uuid:
                user['daily_usage_gb'] = 0
                continue
            
            user_daily_usage_dict = all_daily_usages.get(uuid, {'hiddify': 0.0, 'marzban': 0.0})
            user_daily_usage_gb = sum(user_daily_usage_dict.values())
            user['daily_usage_gb'] = user_daily_usage_gb
            total_usage_today_gb += user_daily_usage_gb

    except Exception as e:
        logger.error(f"Failed to get combined user data: {e}", exc_info=True)
        all_users_data = []
        total_usage_today_gb = 0

    try:
        # داده‌های روزهای گذشته را از دیتابیس می‌خوانیم
        daily_usage_summary = db.get_daily_usage_summary(days=7)
    except Exception as e:
        logger.error(f"Failed to get daily usage summary: {e}", exc_info=True)
        daily_usage_summary = []
    
    # اگر هیچ کاربری وجود نداشت، یک پاسخ خالی برمی‌گردانیم
    if not all_users_data:
        return {
           "stats": empty_stats, "new_users_last_24h": [], "expiring_soon_users": [], 
           "top_consumers_today": [], "online_users_hiddify": [], "online_users_marzban": [],
           "panel_distribution_data": {"labels": ["فقط آلمان 🇩🇪", "فقط فرانسه 🇫🇷", "هر دو پنل (مشترک)"], "series": [0, 0, 0]},
           "system_health": system_health, "usage_chart_data": {"labels": [], "data": []},
           "top_consumers_chart_data": {"labels": [], "data": []}
        }

    stats, expiring_soon_users, new_users_last_24h, online_users_hiddify, online_users_marzban = _process_user_data(all_users_data)
    
    # آمار کارت بالای صفحه را با عدد دقیق امروز پر می‌کنیم
    stats['total_usage_today_gb'] = total_usage_today_gb
    stats['total_usage_today'] = f"{stats['total_usage_today_gb']:.2f} GB"
    
    top_consumers_today = sorted(
        [u for u in all_users_data if u.get('daily_usage_gb', 0) > 0.01], 
        key=lambda u: u.get('daily_usage_gb', 0), 
        reverse=True
    )[:10]
    
    panel_distribution_data = {
        "labels": ["فقط آلمان 🇩🇪", "فقط فرانسه 🇫🇷", "هر دو پنل (مشترک)"],
        "series": [stats.get('hiddify_only_active', 0), stats.get('marzban_only_active', 0), stats.get('both_panels_active', 0)]
    }
    
    # ✅ --- منطق جدید برای یکپارچه‌سازی داده‌های نمودار ---
    if daily_usage_summary:
        # اگر داده‌ای برای امروز در summary وجود داشت، آن را با عدد دقیق جایگزین می‌کنیم
        today_str = datetime.now(pytz.timezone("Asia/Tehran")).strftime('%Y-%m-%d')
        found_today = False
        for item in daily_usage_summary:
            if item['date'] == today_str:
                item['total_gb'] = round(total_usage_today_gb, 2)
                found_today = True
                break
        # اگر داده‌ای برای امروز وجود نداشت، آن را اضافه می‌کنیم
        if not found_today:
             daily_usage_summary.append({'date': today_str, 'total_gb': round(total_usage_today_gb, 2)})
             
        usage_chart_data = { "labels": [to_shamsi(datetime.strptime(item['date'], '%Y-%m-%d'), include_time=False) for item in daily_usage_summary], "data": [item['total_gb'] for item in daily_usage_summary]}
    else: 
        usage_chart_data = {"labels": [], "data": []}
    # ✅ --- پایان منطق جدید ---
    
    top_consumers_chart_data = {
        "labels": [html_escape(user['name']) for user in top_consumers_today],
        "data": [round(user.get('daily_usage_gb', 0), 2) for user in top_consumers_today]
    }

    users_with_birthdays = db.get_users_with_birthdays()
    for user in users_with_birthdays:
        user['name'] = html_escape(user.get('first_name', 'کاربر'))
        user['days_to_birthday'] = days_until_next_birthday(user.get('birthday'))

    return {
        "stats": stats, "new_users_last_24h": new_users_last_24h, "expiring_soon_users": expiring_soon_users, 
        "top_consumers_today": top_consumers_today, "online_users_hiddify": online_users_hiddify, 
        "online_users_marzban": online_users_marzban, "panel_distribution_data": panel_distribution_data,
        "system_health": system_health, "usage_chart_data": usage_chart_data,
        "top_consumers_chart_data": top_consumers_chart_data,
        "users_with_birthdays": users_with_birthdays
    }
        
# ===================================================================
# == سرویس گزارش جامع (نسخه نهایی با اصلاح نام کاربر در پرداخت‌ها) ==
# ===================================================================
def generate_comprehensive_report_data():
    logger.info("Starting comprehensive report generation...")
    all_users_data = get_all_users_combined()
    now_utc = datetime.now(pytz.utc)
    
    summary = {
        "total_users": len(all_users_data), "active_users": 0, "total_de": 0, "total_fr_tr": 0,
        "active_de": 0, "active_fr_tr": 0, "online_users": 0, "usage_de_gb": 0, "usage_fr_tr_gb": 0
    }
    online_users, active_last_24h, inactive_1_to_7_days, never_connected, expiring_soon_users = set(), [], [], [], []

    for user in all_users_data:
        user['name'] = escape(user.get('name', ''))
        user['usage'] = {'total_usage_GB': user.get('current_usage_GB', 0), 'data_limit_GB': user.get('usage_limit_GB', 0)}
        uuid = user.get('uuid')
        
        panels = []
        db_record = db.get_user_uuid_record(uuid) if uuid else None

        if any(p.get('type') == 'hiddify' for p in user.get('breakdown', {}).values()):
            panels.append('🇩🇪')
            if user.get("is_active"):
                summary['active_de'] += 1
            summary['total_de'] += 1

        marzban_flags = []
        if db_record:
            if db_record.get('has_access_fr'):
                marzban_flags.append('🇫🇷')
            if db_record.get('has_access_tr'):
                marzban_flags.append('🇹🇷')
        
        if marzban_flags:
            panels.extend(marzban_flags)
            if user.get("is_active"):
                summary['active_fr_tr'] += 1
            summary['total_fr_tr'] += 1
        
        user['panel_display'] = ' '.join(panels) if panels else '?'

        user_daily_usage = db.get_usage_since_midnight_by_uuid(uuid) if uuid else {'hiddify': 0, 'marzban': 0}
        summary['usage_de_gb'] += user_daily_usage.get('hiddify', 0)
        summary['usage_fr_tr_gb'] += user_daily_usage.get('marzban', 0)

        if user.get("is_active"):
            summary['active_users'] += 1
            
        if user.get('expire') is not None and 0 <= user.get('expire') <= 7: 
            expiring_soon_users.append(user)
            
        last_online = user.get('last_online')
        if last_online:
            if last_online >= (now_utc - timedelta(minutes=3)): 
                online_users.add(uuid)
            if last_online >= (now_utc - timedelta(hours=24)):
                user['last_online_relative'] = format_relative_time(last_online)
                active_last_24h.append(user)
            elif (now_utc - timedelta(days=7)) <= last_online < (now_utc - timedelta(days=1)):
                user['last_online_relative'] = format_relative_time(last_online)
                inactive_1_to_7_days.append(user)
        else:
            never_connected.append(user)

    summary['online_users'] = len(online_users)
    summary['total_usage'] = f"{(summary['usage_de_gb'] + summary['usage_fr_tr_gb']):.2f} GB"
    
    top_consumers = sorted([u for u in all_users_data if u.get('usage', {}).get('data_limit_GB', 0) > 0], key=lambda u: u.get('usage', {}).get('total_usage_GB', 0), reverse=True)[:10]
    
    # --- ✅ START OF THE FIX ---
    # Convert generators to lists before passing them to the template
    users_with_payments = list(db.get_all_payments_with_user_info())
    bot_users = list(db.get_all_bot_users())
    users_with_birthdays = list(db.get_users_with_birthdays())
    # --- ✅ END OF THE FIX ---

    for p in users_with_payments:
        p['payment_date_shamsi'] = to_shamsi(p.get('payment_date'), include_time=True)
        payment_panels = []
        if p.get('has_access_de'): payment_panels.append('🇩🇪')
        if p.get('has_access_fr'): payment_panels.append('🇫🇷')
        if p.get('has_access_tr'): payment_panels.append('🇹🇷')
        p['panel_display'] = ' '.join(payment_panels) if payment_panels else '?'
        p['name'] = escape(p.get('config_name', ''))
        p['first_name'] = escape(p.get('first_name', ''))
        p['username'] = escape(p.get('username', ''))

    for b_user in users_with_birthdays:
        b_user['days_remaining'] = days_until_next_birthday(b_user.get('birthday'))
        b_user['birthday_shamsi'] = to_shamsi(b_user.get('birthday'))

    return {
        "summary": summary, "active_last_24h": sorted(active_last_24h, key=lambda u: u.get('last_online', now_utc), reverse=True),
        "inactive_1_to_7_days": sorted(inactive_1_to_7_days, key=lambda u: u.get('last_online', now_utc), reverse=True),
        "never_connected": sorted(never_connected, key=lambda u: u.get('name', '').lower()),
        "top_consumers": top_consumers, "expiring_soon_users": sorted(expiring_soon_users, key=lambda u: u.get('expire', float('inf'))),
        "bot_users": bot_users, 
        "users_with_payments": users_with_payments,
        "users_with_birthdays": sorted(users_with_birthdays, key=lambda u: u.get('days_remaining', 999)),
        "today_shamsi": to_shamsi(datetime.now(), include_time=False)
    }


def get_all_payments_for_admin():
    try:
        # FIX: Convert the generator to a list immediately upon fetching
        payments_data = list(db.get_all_payments_with_user_info())

        for payment in payments_data:
            payment['payment_date_shamsi'] = to_shamsi(payment.get('payment_date'), include_time=True)

            panels = []
            if payment.get('has_access_de'):
                panels.append('🇩🇪')
            if payment.get('has_access_fr'):
                panels.append('🇫🇷')
            if payment.get('has_access_tr'):
                panels.append('🇹🇷')
            payment['panel_display'] = ' '.join(panels) if panels else '?'

            payment['config_name'] = escape(payment.get('config_name'))
            payment['first_name'] = escape(payment.get('first_name'))
            payment['username'] = escape(payment.get('username'))

        return payments_data
    except Exception as e:
        logger.error(f"Failed to get all payments for admin: {e}", exc_info=True)
        return []

def get_paginated_users(args):
    """
    Fetches and prepares a paginated list of users for the admin panel,
    ensuring all data is sanitized for safe JSON rendering.
    """
    try:
        page = int(args.get('page', 1))
    except (ValueError, TypeError):
        page = 1
    
    per_page = 15
    search_query = args.get('search', '').strip()
    panel_filter = args.get('panel', 'all')
    main_filter = args.get('filter', 'all')

    if search_query:
        all_users = search_user(search_query)
    else:
        all_users = get_all_users_combined()

    # Data Enrichment and Sanitization Loop
    for user in all_users:
        # ✅ FIX: Securely escape all user-generated or formatted strings
        user['name'] = escape(user.get('name', 'کاربر ناشناس'))
        user['last_online_relative'] = escape(format_relative_time(user.get('last_online')))
        
        expire_days = user.get('expire')
        if expire_days is not None and expire_days >= 0:
            user['expire_shamsi'] = to_shamsi(datetime.now() + timedelta(days=expire_days))
        else:
            user['expire_shamsi'] = "نامحدود" if expire_days is None else "منقضی"
        user['expire_shamsi'] = escape(user['expire_shamsi'])

        uuid = user.get('uuid')
        if uuid:
            uuid_record = db.get_user_uuid_record(uuid)
            if uuid_record:
                uuid_id = uuid_record['id']
                user['total_daily_usage_gb'] = sum(db.get_usage_since_midnight(uuid_id).values())
                user['payment_count'] = len(db.get_user_payment_history(uuid_id))
                user['is_vip'] = uuid_record.get('is_vip', False)
            else:
                user.update({'total_daily_usage_gb': 0, 'payment_count': 0, 'is_vip': False})
        else:
            user.update({'total_daily_usage_gb': 0, 'payment_count': 0, 'is_vip': False})
        
        user['total_daily_usage_formatted'] = escape(format_usage(user.get('total_daily_usage_gb', 0)))
        
        breakdown = user.get('breakdown', {})
        user['on_hiddify'] = any(p.get('type') == 'hiddify' for p in breakdown.values())
        user['on_marzban'] = any(p.get('type') == 'marzban' for p in breakdown.values())

    # Filtering Logic
    if panel_filter != 'all':
        panel_type_to_check = 'hiddify' if panel_filter == 'de' else 'marzban'
        all_users = [u for u in all_users if u.get(f'on_{panel_type_to_check}')]

    now_utc = datetime.now(pytz.utc)
    if main_filter != 'all':
        if main_filter == 'active':
            all_users = [u for u in all_users if u.get('is_active')]
        elif main_filter == 'online':
            online_deadline = now_utc - timedelta(minutes=3)
            all_users = [u for u in all_users if u.get('last_online') and u['last_online'].astimezone(pytz.utc) > online_deadline]
        elif main_filter == 'expiring_soon':
            all_users = [u for u in all_users if u.get('expire') is not None and 0 <= u.get('expire') <= 7]

    all_users.sort(key=lambda u: u.get('name', '').lower())

    # Pagination Logic
    total = len(all_users)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_users = all_users[start:end]

    return {
        'users': paginated_users,
        'pagination': {
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page
        }
    }
# ===================================================================
# == سرویس مدیریت کاربران (نسخه اصلاح شده نهایی) ==
# ===================================================================
def create_user_in_panel(data: dict):
    panel = data.get('panel')
    if 'name' in data:
        data['name'] = escape(data['name'])
    if 'username' in data:
        data['username'] = escape(data['username'])
        
    logger.info(f"Attempting to create a new user in panel: '{panel}' with data: {data}")

    if panel == 'hiddify-tab':
        result = hiddify_handler.add_user(data)
    elif panel == 'marzban-tab':
        result = marzban_handler.add_user(data)
    else:
        logger.warning(f"Invalid panel specified for user creation: '{panel}'")
        raise ValueError('پنل نامعتبر است.')
        
    if not result or not (result.get('uuid') or result.get('username')):
        error_detail = escape(str(result)) if result else 'Unknown error from panel API'
        logger.error(f"Failed to create user in panel '{panel}'. API Response: {error_detail}")
        raise Exception(error_detail)

    logger.info(f"Successfully created user in '{panel}'. Result: {result}")
    return result

def update_user_in_panels(data: dict):
    uuid = data.get('uuid')
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

    if 'common_name' in data and uuid:
        uuid_record = db.get_user_uuid_record(uuid)
        if uuid_record:
            db.update_config_name(uuid_record['id'], data['common_name'])

    logger.info(f"Update process finished for user UUID: {uuid}")
    return True

def delete_user_from_panels(uuid: str):
    logger.info(f"Starting deletion process for user with UUID: {uuid}")
    user_info = get_combined_user_info(uuid)
    if not user_info: 
        logger.warning(f"Deletion failed. User with UUID '{uuid}' not found in any panel.")
        raise ValueError('کاربر یافت نشد.')
        
    for panel_details in user_info.get('breakdown', {}).values():
        panel_type = panel_details.get('type')
        panel_data = panel_details.get('data', {})

        if panel_type == 'hiddify' and panel_data.get('uuid'):
            logger.info(f"Deleting user '{panel_data['uuid']}' from a Hiddify panel.")
            hiddify_handler.delete_user(panel_data['uuid'])
        elif panel_type == 'marzban' and panel_data.get('username'):
            username = escape(panel_data.get('username'))
            logger.info(f"Deleting user '{username}' from a Marzban panel.")
            marzban_handler.delete_user(username)

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

    config_list = [
        unescape(line).strip() 
        for line in raw_text.splitlines() 
        if line.strip().startswith(VALID_PROTOCOLS)
    ]
    
    if not config_list:
        logger.warning("No valid configs found in the provided text.")
        raise ValueError('هیچ کانفیگ معتبری یافت نشد.')

    added_count = db.add_batch_templates(config_list)
    logger.info(f"Successfully added {added_count} new templates to the database.")
    return added_count

def toggle_template(template_id: int):
    logger.info(f"Toggling status for template ID: {template_id}")
    new_status = db.toggle_template_status(template_id) 
    return new_status

def update_template(template_id: int, template_str: str):
    logger.info(f"Attempting to update template ID: {template_id}")
    VALID_PROTOCOLS = ('vless://', 'vmess://', 'trojan://', 'ss://', 'ssr://')
    
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
    
    # --- START OF FIX for Analytics Page ---
    # مانند داشبورد، اینجا هم محاسبه مصرف روزانه را با فراخوانی تابع بهینه انجام می‌دهیم
    all_daily_usages = db.get_all_daily_usage_since_midnight()
    total_usage_today = sum(sum(usages.values()) for usages in all_daily_usages.values())
    # --- END OF FIX for Analytics Page ---
    
    new_users_stats = db.get_new_users_per_month_stats(months=6)
    new_users_chart = {
        "labels": [item['month'] for item in new_users_stats],
        "series": [{"name": "کاربران جدید", "data": [item['count'] for item in new_users_stats]}]
    }

    revenue_stats = db.get_revenue_by_month(months=6)
    revenue_chart = {
        "labels": [item['month'] for item in revenue_stats],
        "series": [{"name": "تعداد پرداخت", "data": [item['revenue_unit'] for item in revenue_stats]}]
    }
    
    daily_active_users_stats = db.get_daily_active_users_count(days=30)
    daily_active_users_chart = {
        "labels": [to_shamsi(datetime.strptime(item['date'], '%Y-%m-%d')) for item in daily_active_users_stats],
        "series": [{"name": "کاربران فعال", "data": [item['active_users'] for item in daily_active_users_stats]}]
    }

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
        "active_users_by_panel_chart": {"labels": active_users_labels, "series": active_users_series},
        "new_users_chart": new_users_chart,
        "revenue_chart": revenue_chart,
        "daily_active_users_chart": daily_active_users_chart
    }


def toggle_user_vip_status(uuid: str):
    logger.info(f"Toggling VIP status for user UUID: {uuid}")
    db.toggle_user_vip(uuid)
    return True

def toggle_template_special_status(template_id: int):
    logger.info(f"Toggling Special status for template ID: {template_id}")
    new_status = db.toggle_template_special(template_id) 
    return new_status

def get_marzban_mappings_service():
    return db.get_all_marzban_mappings()

def add_marzban_mapping_service(hiddify_uuid, marzban_username):
    if not hiddify_uuid or not marzban_username:
        return False, "UUID و یوزرنیم نمی‌توانند خالی باشند."
    
    success = db.add_marzban_mapping(hiddify_uuid, marzban_username)
    if success:
        return True, "مپ با موفقیت اضافه شد."
    else:
        return False, "خطا در افزودن مپ به دیتابیس."

def delete_marzban_mapping_service(hiddify_uuid):
    success = db.delete_marzban_mapping(hiddify_uuid)
    if success:
        return True, "مپ با موفقیت حذف شد."
    else:
        return False, "خطا در حذف مپ از دیتابیس."

def get_schedule_info_service():
    """
    (نسخه نهایی و کامل شده)
    لیست جامع و دقیقی از تمام فرآیندهای خودکار و زمان‌بندی شده ربات را برمی‌گرداند.
    """
    report_time_str = DAILY_REPORT_TIME.strftime('%H:%M')
    warning_interval_hours = USAGE_WARNING_CHECK_HOURS
    
    schedule_list = [
        {
            "icon": "ri-camera-lens-line",
            "title": "ثبت آمار مصرف (Snapshot)",
            "interval": "هر ساعت، در دقیقه ۰۱",
            "description": "مصرف لحظه‌ای کاربران از تمام پنل‌ها ذخیره می‌شود. این داده پایه و اساس تمام گزارش‌های روزانه، هفتگی و نمودارها است."
        },
        {
            "icon": "ri-alarm-warning-line",
            "title": "ارسال هشدارها به کاربران",
            "interval": f"هر {warning_interval_hours} ساعت",
            "description": "وضعیت کاربران برای ارسال هشدارهای اتمام حجم (کمتر از 15%) و نزدیک شدن به تاریخ انقضا (کمتر از ۳ روز) به صورت خودکار بررسی می‌شود."
        },
        {
            "icon": "ri-send-plane-2-line",
            "title": "ارسال گزارش روزانه",
            "interval": f"هر شب ساعت {report_time_str} (به جز جمعه‌ها)",
            "description": "گزارش مصرف روزانه برای کاربران فعال و گزارش جامع مدیریتی برای ادمین‌ها ارسال می‌گردد."
        },
        {
            "icon": "ri-calendar-event-line",
            "title": "ارسال گزارش هفتگی",
            "interval": "هر جمعه ساعت ۲۳:۵۵",
            "description": "گزارش کامل مصرف هفتگی به تفکیک هر روز برای کاربران و گزارش پرمصرف‌ترین‌های هفته برای ادمین‌ها ارسال می‌شود."
        },
        {
            "icon": "ri-cake-2-line",
            "title": "اعمال هدیه تولد و مناسبت‌ها",
            "interval": "هر روز ساعت ۰۰:۰۵ و ۰۰:۱۵ بامداد",
            "description": "کاربرانی که روز تولدشان است و همچنین مناسبت‌های تقویم شمسی (مانند یلدا) بررسی شده و هدایا به صورت خودکار اعمال می‌شوند."
        },
        {
            "icon": "ri-star-smile-line",
            "title": "اعمال هدیه سالگرد",
            "interval": "هر روز ساعت ۰۲:۰۰ بامداد (همراه با دستاوردها)",
            "description": "سالگرد عضویت یکساله کاربران بررسی شده و در صورت واجد شرایط بودن، هدیه ویژه سالگرد به آنها اهدا می‌شود."
        },
        {
            "icon": "ri-medal-line",
            "title": "بررسی دستاوردها (Achievements)",
            "interval": "هر روز ساعت ۰۲:۰۰ بامداد",
            "description": "شرایط کسب نشان‌های مختلف (مانند کهنه‌کار، حامی وفادار، سفیر و...) برای تمام کاربران بررسی و امتیاز مربوطه به آنها اضافه می‌شود."
        },
        {
            "icon": "ri-trophy-line",
            "title": "قرعه‌کشی ماهانه خوش‌شانسی",
            "interval": "اولین جمعه هر ماه شمسی",
            "description": "بین کاربرانی که شرایط لازم را داشته باشند، قرعه‌کشی انجام شده و به برنده امتیاز ویژه اهدا می‌شود."
        },
        {
            "icon": "ri-refresh-line",
            "title": "همگام‌سازی کاربران با پنل‌ها",
            "interval": "هر ۱۲ ساعت",
            "description": "لیست کاربران در دیتابیس ربات با لیست کاربران در پنل‌ها مقایسه شده و کاربرانی که از پنل حذف شده‌اند، در ربات نیز غیرفعال می‌شوند."
        },
        {
            "icon": "ri-delete-bin-line",
            "title": "پاکسازی گزارش‌های قدیمی",
            "interval": "هر ۸ ساعت",
            "description": "پیام‌های گزارش روزانه و هفتگی که برای کاربران ارسال شده و قدیمی‌تر از ۱۲ ساعت هستند (در صورت فعال بودن تنظیمات کاربر) به طور خودکار حذف می‌شوند."
        },
        {
            "icon": "ri-database-2-line",
            "title": "بهینه‌سازی دیتابیس",
            "interval": "هر روز ساعت ۰۴:۰۰ بامداد",
            "description": "اسنپ‌شات‌های مصرف قدیمی‌تر از ۷ روز حذف شده و در روز اول هر ماه، عملیات بهینه‌سازی (VACUUM) روی فایل دیتابیس انجام می‌شود."
        }
    ]
    
    return schedule_list

def get_logs_service(lines_count=500):
    log_files = { 'bot_log': 'bot.log', 'error_log': 'error.log' }
    logs_content = {}

    for key, filename in log_files.items():
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                last_lines = lines[-lines_count:]
                logs_content[key] = ''.join(html_escape(line) for line in last_lines)
        except FileNotFoundError:
            logs_content[key] = f"فایل '{filename}' یافت نشد."
        except Exception as e:
            logger.error(f"خطا در خواندن فایل لاگ {filename}: {e}")
            logs_content[key] = f"خطا در بارگذاری فایل '{filename}'."
            
    return logs_content

def clear_logs_service():
    log_files = ['bot.log', 'error.log']
    cleared_files, errors = [], []

    for filename in log_files:
        try:
            with open(filename, 'w') as f: pass
            cleared_files.append(filename)
            logger.info(f"Log file '{filename}' has been cleared by admin.")
        except FileNotFoundError:
            cleared_files.append(filename)
        except Exception as e:
            logger.error(f"Error clearing log file {filename}: {e}")
            errors.append(filename)
            
    if errors:
        return False, f"خطا در پاک کردن فایل‌های: {', '.join(errors)}"
    return True, "تمام فایل‌های لاگ با موفقیت پاک شدند."

def get_server_status():
    statuses = []
    try:
        if hiddify_handler.check_connection():
            statuses.append({'name': 'سرور آلمان 🇩🇪', 'status': 'آنلاین', 'class': 'online'})
        else:
            statuses.append({'name': 'سرور آلمان 🇩🇪', 'status': 'آفلاین', 'class': 'offline'})
    except Exception as e:
        logger.error(f"Error checking Hiddify connection for status page: {e}")
        statuses.append({'name': 'سرور آلمان 🇩🇪', 'status': 'آفلاین', 'class': 'offline'})

    try:
        if marzban_handler.check_connection():
            statuses.append({'name': 'سرور فرانسه 🇫🇷', 'status': 'آنلاین', 'class': 'online'})
        else:
            statuses.append({'name': 'سرور فرانسه 🇫🇷', 'status': 'آفلاین', 'class': 'offline'})
    except Exception as e:
        logger.error(f"Error checking Marzban connection for status page: {e}")
        statuses.append({'name': 'سرور فرانسه 🇫🇷', 'status': 'آفلاین', 'class': 'offline'})
        
    return statuses