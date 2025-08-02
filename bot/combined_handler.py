from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from .hiddify_api_handler import hiddify_handler
from .marzban_api_handler import marzban_handler
from .database import db
from .utils import validate_uuid
import logging
import pytz

logger = logging.getLogger(__name__)

def _process_single_user_data(h_info: Optional[Dict], m_info: Optional[Dict]) -> Optional[Dict[str, Any]]:
    """
    یک تابع داخلی برای پردازش و ترکیب اطلاعات یک کاربر از هر دو پنل.
    این تابع قلب منطق ترکیب داده است.
    """
    if not h_info and not m_info:
        return None

    base_info = (h_info or m_info).copy()
    h_info = h_info or {}
    m_info = m_info or {}

    base_info['breakdown'] = {'hiddify': h_info, 'marzban': m_info}
    
    # اصلاح 1: اضافه کردن فیلد panels برای نمایش در جدول
    panels = []
    if h_info:
        panels.append("آلمان (Hiddify)")
    if m_info:
        panels.append("فرانسه (Marzban)")
    base_info['panels'] = " + ".join(panels) if panels else "نامشخص"
    
    h_limit = h_info.get('usage_limit_GB', 0)
    m_limit = m_info.get('usage_limit_GB', 0)
    total_limit = h_limit + m_limit
    
    h_usage = h_info.get('current_usage_GB', 0)
    m_usage = m_info.get('current_usage_GB', 0)
    total_usage = h_usage + m_usage
    
    base_info['usage'] = {
        'total_usage_GB': total_usage,
        'data_limit_GB': total_limit,
        'remaining_GB': max(0, total_limit - total_usage),
        'percentage': (total_usage / total_limit * 100) if total_limit > 0 else 0
    }

    base_info['is_active'] = h_info.get('is_active', False) or m_info.get('is_active', False)
    if base_info['is_active']:
        base_info['status'] = 'active'
    elif (h_info.get('expire', -1) < 0) or (m_info.get('expire', -1) < 0):
        base_info['status'] = 'expired'
    else:
        base_info['status'] = 'disabled'

    # اصلاح 2: بهبود منطق last_online و is_online
    latest_online = None
    h_online = h_info.get('last_online')
    m_online = m_info.get('last_online')

    # مدیریت string datetime ها
    if h_online:
        if isinstance(h_online, str):
            try:
                h_online = datetime.fromisoformat(h_online.replace('Z', '+00:00'))
            except:
                h_online = None
        if h_online and h_online.tzinfo is None:
            h_online = pytz.utc.localize(h_online)

    if m_online:
        if isinstance(m_online, str):
            try:
                m_online = datetime.fromisoformat(m_online.replace('Z', '+00:00'))
            except:
                m_online = None
        if m_online and m_online.tzinfo is None:
            m_online = pytz.utc.localize(m_online)

    # انتخاب آخرین زمان اتصال
    if h_online and m_online:
        latest_online = max(h_online, m_online)
    elif h_online:
        latest_online = h_online
    elif m_online:
        latest_online = m_online

    base_info['last_online'] = latest_online
    
    # محاسبه وضعیت آنلاین
    base_info['is_online'] = False
    if latest_online:
        try:
            time_diff_seconds = (datetime.now(pytz.utc) - latest_online).total_seconds()
            if 0 <= time_diff_seconds < 180:
                base_info['is_online'] = True
        except:
            base_info['is_online'] = False

    base_info['name'] = h_info.get('name') or m_info.get('name', 'ناشناس')
    base_info['username'] = base_info['name']
    base_info['uuid'] = h_info.get('uuid') or m_info.get('uuid')
    
    # اصلاح 3: بهبود منطق expire
    h_expire = h_info.get('expire', -1)
    m_expire = m_info.get('expire', -1)

    if h_expire == -1 and m_expire == -1:
        base_info['expire'] = -1  # نامحدود
    elif h_expire == -1:
        base_info['expire'] = m_expire
    elif m_expire == -1:
        base_info['expire'] = h_expire
    else:
        base_info['expire'] = max(h_expire, m_expire)
    
    # اصلاح 4: درست کردن indentation
    base_info['on_hiddify'] = bool(h_info)
    base_info['on_marzban'] = bool(m_info)

    return base_info


def get_combined_user_info(identifier: str) -> Optional[Dict[str, Any]]:
    """
    دریافت اطلاعات ترکیبی یک کاربر از هر دو پنل بر اساس UUID یا نام کاربری
    """
    try:
        is_uuid = validate_uuid(identifier)
        h_info, m_info = None, None
        
        if is_uuid:
            # جستجو بر اساس UUID
            try:
                h_info = hiddify_handler.user_info(identifier)
            except Exception as e:
                logger.warning(f"Error fetching Hiddify user {identifier}: {e}")
                
            try:
                m_info = marzban_handler.get_user_info(identifier)
            except Exception as e:
                logger.warning(f"Error fetching Marzban user by UUID {identifier}: {e}")
        else:
            # جستجو بر اساس نام کاربری
            try:
                m_info = marzban_handler.get_user_by_username(identifier)
                if m_info and m_info.get('uuid'):
                    try:
                        h_info = hiddify_handler.user_info(m_info['uuid'])
                    except Exception as e:
                        logger.warning(f"Error fetching Hiddify user by UUID {m_info['uuid']}: {e}")
            except Exception as e:
                logger.warning(f"Error fetching Marzban user by username {identifier}: {e}")
        
        # پردازش و ترکیب داده‌ها
        return _process_single_user_data(h_info, m_info)
        
    except Exception as e:
        logger.error(f"Critical error in get_combined_user_info for {identifier}: {e}")
        return None

def modify_user_on_all_panels(identifier: str, add_gb: float = 0, add_days: int = 0, target_panel: str = 'both') -> bool:
    """
    Modifies a user on Hiddify, Marzban, or both, handling relative additions.
    This is a new, crucial function to fix editing bugs.
    """
    info = get_combined_user_info(identifier)
    if not info:
        logger.error(f"Cannot modify non-existent user: {identifier}")
        return False

    h_success, m_success = True, True  # Assume success if not targeted

    # --- Hiddify Modification ---
    if target_panel in ['hiddify', 'both'] and 'hiddify' in info.get('breakdown', {}):
        h_info = info['breakdown']['hiddify']
        h_payload = {}
        
        if add_gb != 0:
            current_limit = h_info.get('usage_limit_GB', 0)
            h_payload['usage_limit_GB'] = current_limit + add_gb
        
        if add_days != 0:
            # Hiddify needs an absolute number of days, so we calculate it.
            current_expire = h_info.get('expire', 0)
            # If expired, start from today. Otherwise, add to remaining days.
            base_days = current_expire if current_expire is not None and current_expire > 0 else 0
            h_payload['package_days'] = base_days + add_days

        if h_payload:
            h_success = hiddify_handler.modify_user(h_info['uuid'], h_payload)
        else:
            h_success = True # Nothing to do

    # --- Marzban Modification ---
    if target_panel in ['marzban', 'both'] and 'marzban' in info.get('breakdown', {}):
        m_info = info['breakdown']['marzban']
        # Marzban handler already supports relative additions directly
        m_success = marzban_handler.modify_user(
            username=m_info['name'],
            add_usage_gb=add_gb,
            add_days=add_days
        )

    return h_success and m_success

def delete_user_from_all_panels(identifier: str) -> bool:
    info = get_combined_user_info(identifier)
    if not info: return False
    h_success, m_success = True, True
    h_uuid = info.get('uuid')
    m_username = info.get('name') if 'marzban' in info.get('breakdown', {}) else None
    if h_uuid and 'hiddify' in info.get('breakdown', {}):
        h_success = hiddify_handler.delete_user(h_uuid)
    if m_username and 'marzban' in info.get('breakdown', {}):
        m_success = marzban_handler.delete_user(m_username)
    if h_success and m_success and h_uuid:
        db_id = db.get_uuid_id_by_uuid(h_uuid)
        if db_id:
            db.deactivate_uuid(db_id)
            db.delete_user_snapshots(db_id)
    return h_success and m_success

def get_all_users_combined() -> List[Dict[str, Any]]:
    logger.info("COMBINED_HANDLER: Starting to fetch users from all panels.")
    all_users_map = {}
    
    # دریافت کاربران از هیدیفای
    logger.info("COMBINED_HANDLER: Fetching from Hiddify...")
    h_users = hiddify_handler.get_all_users() or []
    logger.info(f"COMBINED_HANDLER: Fetched {len(h_users)} users from Hiddify.")
    
    for user in h_users:
        uuid = user.get('uuid')
        if uuid:
            all_users_map[uuid] = _process_single_user_data(user, None)

    # دریافت کاربران از مرزبان
    logger.info("COMBINED_HANDLER: Fetching from Marzban...")
    m_users = marzban_handler.get_all_users() or []
    logger.info(f"COMBINED_HANDLER: Fetched {len(m_users)} users from Marzban.")
    
    for user in m_users:
        uuid = user.get('uuid')
        if uuid:
            if uuid in all_users_map:
                # کاربر در هر دو پنل وجود دارد
                h_data = all_users_map[uuid]['breakdown']['hiddify']
                all_users_map[uuid] = _process_single_user_data(h_data, user)
            else:
                # کاربر فقط در مرزبان وجود دارد
                all_users_map[uuid] = _process_single_user_data(None, user)
        else:
            # کاربر UUID ندارد - استفاده از نام کاربری
            username = user.get('name')
            if username:
                all_users_map[f"marzban_{username}"] = _process_single_user_data(None, user)
    
    # فیلتر کردن None values
    result = [user for user in all_users_map.values() if user is not None]
    logger.info(f"COMBINED_HANDLER: Total processed users: {len(result)}")
    return result


def search_user(query: str) -> List[Dict[str, Any]]:
    query_lower = query.lower()
    results, found_identifiers = [], set()

    all_users = get_all_users_combined()
    for user in all_users:
        identifier = user.get('uuid') or user.get('name')
        if identifier in found_identifiers: continue
        
        match = query_lower in user.get('name', '').lower() or \
                (user.get('uuid') and query_lower in user.get('uuid'))
        
        if match:
            panel = 'hiddify' if 'hiddify' in user.get('breakdown', {}) else 'marzban'
            results.append({**user, 'panel': panel})
            found_identifiers.add(identifier)
    return results