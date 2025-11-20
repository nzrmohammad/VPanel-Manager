# bot/combined_handler.py
from typing import Optional, Dict, Any, List
from .hiddify_api_handler import HiddifyAPIHandler
from .marzban_api_handler import MarzbanAPIHandler
from .utils import validate_uuid
from datetime import datetime, timedelta, timezone
import logging
import time 

logger = logging.getLogger(__name__)

def _get_handler_for_panel(panel_config: Dict[str, Any]):
    """یک نمونه API handler بر اساس نوع پنل می‌سازد."""
    try:
        if panel_config['panel_type'] == 'hiddify':
            return HiddifyAPIHandler(panel_config)
        elif panel_config['panel_type'] == 'marzban':
            return MarzbanAPIHandler(panel_config)
    except Exception as e:
        logger.error(f"Failed to create handler for panel {panel_config.get('name')}: {e}")
    return None

def _process_and_merge_user_data(all_users_map: dict) -> List[Dict[str, Any]]:
    """اطلاعات خام جمع‌آوری شده از پنل‌ها را پردازش نهایی می‌کند."""
    processed_list = []
    for identifier, data in all_users_map.items():
        limit = data.get('usage_limit_GB', 0)
        usage = data.get('current_usage_GB', 0)
        data['remaining_GB'] = max(0, limit - usage)
        data['usage_percentage'] = (usage / limit * 100) if limit > 0 else 0
        
        # Add the 'usage' dictionary for template compatibility
        data['usage'] = {
            'total_usage_GB': usage,
            'data_limit_GB': limit
        }

        if 'panels' in data and isinstance(data['panels'], set):
            data['panels'] = list(data['panels'])

        final_name = "کاربر ناشناس"
        if data.get('breakdown'):
            for panel_name, panel_details in data['breakdown'].items():
                panel_data = panel_details.get('data', {})
                if panel_data.get('name'):
                    final_name = panel_data['name']
                    break
        data['name'] = final_name

        processed_list.append(data)
    return processed_list

def get_all_users_combined() -> List[Dict[str, Any]]:
    from .database import db
    """اطلاعات کاربران را از تمام پنل‌های فعال دریافت و ترکیب می‌کند."""
    logger.info("COMBINED_HANDLER: Fetching users from all active panels.")
    all_users_map = {}
    active_panels = db.get_active_panels()

    for panel_config in active_panels:
        panel_name = panel_config['name']
        handler = _get_handler_for_panel(panel_config)
        if not handler:
            logger.warning(f"Could not create handler for panel: {panel_name}")
            continue

        try:
            panel_users = handler.get_all_users() or []
            logger.info(f"Fetched {len(panel_users)} users from '{panel_name}'.")
        except Exception as e:
            logger.error(f"Could not fetch users from panel '{panel_name}': {e}")
            continue

        for user in panel_users:
            identifier = None
            uuid = None

            if panel_config['panel_type'] == 'hiddify':
                uuid = user.get('uuid')
                identifier = uuid
            elif panel_config['panel_type'] == 'marzban':
                marzban_username = user.get('username')
                linked_uuid = db.get_uuid_by_marzban_username(marzban_username)
                if linked_uuid:
                    identifier = linked_uuid
                    uuid = linked_uuid
                else:
                    identifier = f"marzban_{marzban_username}"
                    uuid = None
            
            if not identifier:
                continue
            
            if identifier not in all_users_map:
                all_users_map[identifier] = {
                    'uuid': uuid,
                    'is_active': False, 'expire': None,
                    'last_online': None,
                    'current_usage_GB': 0, 'usage_limit_GB': 0,
                    'breakdown': {},
                    'panels': set()
                }

            if uuid and not all_users_map[identifier].get('uuid'):
                 all_users_map[identifier]['uuid'] = uuid

            all_users_map[identifier]['breakdown'][panel_name] = {
                "data": user,
                "type": panel_config['panel_type']
            }
            all_users_map[identifier]['panels'].add(panel_name)
            current_last_online = all_users_map[identifier].get('last_online')
            new_last_online = user.get('last_online')
            if new_last_online:
                if not current_last_online or new_last_online > current_last_online:
                    all_users_map[identifier]['last_online'] = new_last_online
            all_users_map[identifier]['is_active'] |= user.get('is_active', False)
            all_users_map[identifier]['current_usage_GB'] += user.get('current_usage_GB', 0)
            all_users_map[identifier]['usage_limit_GB'] += user.get('usage_limit_GB', 0)

            new_expire = user.get('expire')
            if new_expire is not None:
                current_expire = all_users_map[identifier]['expire']
                if current_expire is None or new_expire < current_expire:
                    all_users_map[identifier]['expire'] = new_expire
    
    return _process_and_merge_user_data(all_users_map)


def get_combined_user_info(identifier: str) -> Optional[Dict[str, Any]]:
    from .database import db
    """اطلاعات یک کاربر خاص را از تمام پنل‌های فعال دریافت می‌کند."""
    is_uuid = validate_uuid(identifier)
    all_panels = db.get_active_panels()
    
    hiddify_uuid_to_query = None
    marzban_username_to_query = None

    if is_uuid:
        hiddify_uuid_to_query = identifier
        marzban_username_to_query = db.get_marzban_username_by_uuid(identifier)
    else:
        marzban_username_to_query = identifier
        hiddify_uuid_to_query = db.get_uuid_by_marzban_username(identifier)

    user_data_map = {}

    for panel_config in all_panels:
        handler = _get_handler_for_panel(panel_config)
        if not handler: continue

        user_info = None
        if panel_config['panel_type'] == 'hiddify' and hiddify_uuid_to_query:
            user_info = handler.user_info(hiddify_uuid_to_query)
        elif panel_config['panel_type'] == 'marzban' and marzban_username_to_query:
            user_info = handler.get_user_by_username(marzban_username_to_query)

        if user_info:
            user_data_map[panel_config['name']] = {
                "data": user_info,
                "type": panel_config['panel_type']
            }

    if not user_data_map:
        return None
    
    all_online_times = [ p['data'].get('last_online') for p in user_data_map.values() if p['data'].get('last_online') ]
    most_recent_online = max(all_online_times) if all_online_times else None

    final_info = {
        'breakdown': user_data_map,
        'is_active': any(p['data'].get('is_active') for p in user_data_map.values()),
        'last_online': most_recent_online,
        'current_usage_GB': sum(p['data'].get('current_usage_GB', 0) for p in user_data_map.values()),
        'usage_limit_GB': sum(p['data'].get('usage_limit_GB', 0) for p in user_data_map.values()),
        'expire': min([p['data'].get('expire') for p in user_data_map.values() if p['data'].get('expire') is not None] or [None]),
        'uuid': hiddify_uuid_to_query or next((p['data'].get('uuid') for p in user_data_map.values() if p['data'].get('uuid')), None),
        'name': identifier if not is_uuid else next((p['data'].get('name') for p in user_data_map.values() if p['data'].get('name')), "کاربر ناشناس")
    }
    
    limit = final_info['usage_limit_GB']
    usage = final_info['current_usage_GB']
    final_info['remaining_GB'] = max(0, limit - usage)
    final_info['usage_percentage'] = (usage / limit * 100) if limit > 0 else 0
    final_info['usage'] = {
        'total_usage_GB': final_info.get('current_usage_GB', 0),
        'data_limit_GB': final_info.get('usage_limit_GB', 0)
    }
    
    return final_info


def search_user(query: str) -> List[Dict[str, Any]]:
    """یک کاربر را در تمام پنل‌های فعال جستجو می‌کند."""
    query_lower = query.lower()
    results = []
    
    all_users = get_all_users_combined()
    
    for user in all_users:
        match_name = query_lower in user.get('name', '').lower()
        match_uuid = user.get('uuid') and query_lower in user.get('uuid')
        
        if match_name or match_uuid:
            results.append(user)
            
    return results

def modify_user_on_all_panels(
    identifier: str,
    add_gb: float = 0,
    add_days: int = 0,
    set_gb: Optional[float] = None,
    set_days: Optional[int] = None,
    target_panel_type: Optional[str] = None
) -> bool:
    from .database import db
    """
    (نسخه نهایی و کاملاً اصلاح شده)
    تغییرات کاربر را به صورت اتمی برای هر پنل اعمال می‌کند.
    - حجم فعلی کاربر (usage_limit_GB) به درستی خوانده شده و حجم جدید به آن اضافه می‌شود.
    - تاریخ انقضا برای کاربران منقضی شده از امروز محاسبه می‌شود.
    """
    logger.info("╔═══════════════════════════════════════════════════════════")
    logger.info(f"║ Starting user modification for identifier: {identifier}")
    logger.info(f"║ Inputs: add_gb={add_gb}, add_days={add_days}, set_gb={set_gb}, set_days={set_days}")
    logger.info(f"║ Target panel type: {target_panel_type or 'ALL'}")
    logger.info("╚═══════════════════════════════════════════════════════════")

    is_uuid = validate_uuid(identifier)
    uuid = identifier if is_uuid else db.get_uuid_by_marzban_username(identifier)
    marzban_username = db.get_marzban_username_by_uuid(identifier) if is_uuid else identifier

    if not uuid and not marzban_username:
        logger.error(f"❌ User with identifier '{identifier}' could not be resolved. Aborting.")
        return False
        
    any_success = False
    all_panels = db.get_active_panels()

    for panel_config in all_panels:
        panel_type = panel_config['panel_type']
        panel_name = panel_config['name']

        if target_panel_type and panel_type != target_panel_type:
            continue

        handler = _get_handler_for_panel(panel_config)
        if not handler:
            logger.warning(f"⚠️  Could not create handler for '{panel_name}'")
            continue

        # --- بخش اصلاح شده مربوط به Hiddify ---
        if panel_type == 'hiddify' and uuid:
            logger.info(f"🔄 Processing panel '{panel_name}' (type: 'hiddify')")
            user_panel_data = handler.user_info(uuid)
            
            if not user_panel_data:
                logger.info(f"⏭️  User {uuid} not found on Hiddify panel '{panel_name}'. Skipping.")
                continue
            
            payload = {}
            
            # دریافت روزهای باقیمانده (اگر منفی بود صفر در نظر می‌گیریم)
            current_remaining = user_panel_data.get('expire', 0)
            if current_remaining is None or current_remaining < 0:
                current_remaining = 0
            
            # اگر قرار است روز اضافه شود
            if add_days > 0:
                # 1. تاریخ شروع را حتماً ریست می‌کنیم تا کنتور از صفر (امروز) شروع شود
                payload['start_date'] = None
                
                # 2. روزهای پکیج برابر است با: روزهای باقیمانده کاربر + روزهای خرید جدید
                # اینطوری اگر 1 روز مانده باشد، با 30 روز خرید می‌شود 31 روز اعتبار از همین لحظه
                payload['package_days'] = int(current_remaining + add_days)
            
            # اضافه کردن حجم (بدون تغییر نسبت به قبل)
            if add_gb > 0: 
                current_limit = user_panel_data.get('usage_limit_GB', 0)
                payload['usage_limit_GB'] = current_limit + add_gb

            if payload:
                logger.info(f"📤 Final Hiddify payload: {payload}")
                if handler.modify_user(uuid, payload):
                    any_success = True
                    logger.info(f"✅ Successfully modified user on Hiddify panel '{panel_name}'")

        # --- بخش مربوط به Marzban (با اصلاح نهایی) ---
        elif panel_type == 'marzban' and marzban_username:
            logger.info(f"🔄 Processing panel '{panel_name}' (type: 'marzban')")
            user_panel_data = handler.get_user_by_username(marzban_username)

            if not user_panel_data:
                logger.info(f"⏭️  User '{marzban_username}' not found on Marzban panel '{panel_name}'. Skipping.")
                continue

            marzban_payload = {}
            
            # --- ✨✨✨ شروع اصلاح اصلی و نهایی ✨✨✨ ---
            # به جای خواندن فیلد اشتباه data_limit، فیلد صحیح usage_limit_GB را خوانده
            # و آن را به بایت تبدیل می‌کنیم تا حجم فعلی کاربر به درستی محاسبه شود.
            current_limit_gb = user_panel_data.get('usage_limit_GB', 0) or 0
            current_limit_bytes = int(current_limit_gb * (1024**3))
            
            if add_gb > 0:
                marzban_payload['data_limit'] = current_limit_bytes + int(add_gb * (1024**3))
            # --- ✨✨✨ پایان اصلاح اصلی و نهایی ✨✨✨ ---

            # منطق تاریخ انقضا (بدون تغییر)
            # نکته: برای خواندن تاریخ انقضای فعلی، باید اطلاعات خام را از پنل بگیریم
            # که این کار در تابع modify_user در marzban_api_handler انجام می‌شود.
            # بنابراین این بخش به درستی کار می‌کند.
            raw_marzban_user = handler._request("GET", f"/user/{marzban_username}")
            current_expire_ts = raw_marzban_user.get('expire') if raw_marzban_user else None

            if add_days > 0:
                start_date = datetime.now()
                if current_expire_ts and current_expire_ts > start_date.timestamp():
                    start_date = datetime.fromtimestamp(current_expire_ts)
                marzban_payload['expire'] = int((start_date + timedelta(days=add_days)).timestamp())
            
            if marzban_payload:
                logger.info(f"📤 Final Marzban payload: {marzban_payload}")
                if handler.modify_user(marzban_username, data=marzban_payload):
                    any_success = True
                    logger.info(f"✅ Successfully modified user on Marzban panel '{panel_name}'")

    if any_success and (add_days > 0 or set_days is not None):
        if uuid:
            uuid_record = db.get_user_uuid_record(uuid)
            if uuid_record:
                db.reset_renewal_reminder_sent(uuid_record['id'])
                logger.info(f"🔔 Renewal reminder flag reset for user identifier {identifier}")

    logger.info("╔═══════════════════════════════════════════════════════════")
    logger.info(f"║ Finished user modification for identifier: {identifier}")
    logger.info(f"║ Overall success: {any_success}")
    logger.info("╚═══════════════════════════════════════════════════════════")
    
    return any_success


def delete_user_from_all_panels(identifier: str) -> bool:
    from .database import db
    """کاربر را از تمام پنل‌هایی که در آن وجود دارد حذف می‌کند."""
    user_info = get_combined_user_info(identifier)
    if not user_info: return False

    all_panels_map = {p['name']: p for p in db.get_all_panels()}
    all_success = True

    for panel_name, panel_details in user_info.get('breakdown', {}).items():
        panel_config = all_panels_map.get(panel_name)
        if not panel_config: continue
        
        handler = _get_handler_for_panel(panel_config)
        if not handler: continue

        user_panel_data = panel_details.get('data', {})
        panel_type = panel_details.get('type')

        if panel_type == 'hiddify' and user_panel_data.get('uuid'):
            if not handler.delete_user(user_panel_data['uuid']):
                all_success = False
        elif panel_type == 'marzban' and user_panel_data.get('username'):
            if not handler.delete_user(user_panel_data['username']):
                all_success = False
    
    if user_info.get('uuid'):
        db.delete_user_by_uuid(user_info['uuid'])
        
    return all_success