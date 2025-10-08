# bot/combined_handler.py
from typing import Optional, Dict, Any, List
from .hiddify_api_handler import HiddifyAPIHandler
from .marzban_api_handler import MarzbanAPIHandler
from .database import db
from .utils import validate_uuid
from datetime import datetime, timedelta
import logging

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
    """
    (نسخه نهایی با استفاده از start_date بر اساس مستندات API)
    کاربر را ویرایش می‌کند.
    """
    logger.info(f"--- Starting user modification for identifier: {identifier} ---")
    logger.info(f"Inputs: add_gb={add_gb}, add_days={add_days}, set_gb={set_gb}, set_days={set_days}")

    user_info = get_combined_user_info(identifier)
    if not user_info:
        logger.error(f"User with identifier '{identifier}' not found. Aborting modification.")
        return False

    all_panels_map = {p['name']: p for p in db.get_active_panels()}
    any_success = False

    for panel_name, panel_details in user_info.get('breakdown', {}).items():
        panel_type = panel_details.get('type')
        
        if target_panel_type and panel_type != target_panel_type:
            continue

        panel_config = all_panels_map.get(panel_name)
        if not panel_config: continue
        
        handler = _get_handler_for_panel(panel_config)
        if not handler: continue

        user_panel_data = panel_details.get('data', {})
        
        if panel_type == 'hiddify' and user_info.get('uuid'):
            logger.info(f"Processing Hiddify panel '{panel_name}' for user {user_info['uuid']}")
            
            current_limit_gb = user_panel_data.get('usage_limit_GB', 0)
            payload = {}
            is_new_plan = False

            # --- بخش حجم ---
            if set_gb is not None:
                payload['usage_limit_GB'] = set_gb
                is_new_plan = True
            elif add_gb > 0:
                # افزودن حجم نیازی به ریست ندارد و به تنهایی ارسال می‌شود
                payload['usage_limit_GB'] = current_limit_gb + add_gb

            # --- بخش روز ---
            if set_days is not None:
                payload['package_days'] = set_days
                is_new_plan = True
            elif add_days > 0:
                payload['package_days'] = add_days
                is_new_plan = True

            # --- منطق نهایی بر اساس مستندات ---
            if is_new_plan:
                # برای تعریف پلن جدید، تاریخ شروع را برابر امروز قرار می‌دهیم
                payload['start_date'] = datetime.now().strftime('%Y-%m-%d')
                
                # اگر حجم در درخواست نبود، از حجم فعلی کاربر استفاده می‌کنیم
                if 'usage_limit_GB' not in payload:
                    payload['usage_limit_GB'] = current_limit_gb
            
            logger.info(f"Constructed Hiddify payload: {payload}")

            if payload:
                if handler.modify_user(user_info['uuid'], payload):
                    any_success = True
                    logger.info(f"Successfully modified user on Hiddify panel '{panel_name}'.")
                else:
                    logger.error(f"Failed to modify user on Hiddify panel '{panel_name}'. Check previous logs for details.")
            else:
                logger.info("No changes to apply for Hiddify panel.")

        # ... (بخش مرزبان بدون تغییر) ...
        elif panel_type == 'marzban' and user_panel_data.get('username'):
            marzban_username = user_panel_data['username']
            current_limit_bytes = user_panel_data.get('data_limit', 0)
            current_expire_ts = user_panel_data.get('expire')
            marzban_payload = {}
            
            if set_gb is not None:
                marzban_payload['data_limit'] = int(set_gb * (1024**3))
            elif add_gb > 0:
                 marzban_payload['data_limit'] = current_limit_bytes + int(add_gb * (1024**3))
            
            if set_days is not None:
                new_expire_ts = int((datetime.now() + timedelta(days=set_days)).timestamp())
                marzban_payload['expire'] = new_expire_ts
            elif add_days > 0:
                 start_date = datetime.now()
                 if current_expire_ts and current_expire_ts > start_date.timestamp():
                     start_date = datetime.fromtimestamp(current_expire_ts)
                 new_expire_date = start_date + timedelta(days=add_days)
                 marzban_payload['expire'] = int(new_expire_date.timestamp())

            if marzban_payload and handler.modify_user(marzban_username, data=marzban_payload):
                any_success = True

    if any_success and (add_days > 0 or set_days is not None):
        uuid_to_check = user_info.get('uuid')
        if uuid_to_check:
            uuid_id = db.get_uuid_id_by_uuid(uuid_to_check)
            if uuid_id:
                db.reset_renewal_reminder_sent(uuid_id)
                logger.info(f"Renewal reminder flag reset for user {user_info.get('name')} due to manual day/plan change.")
            
    logger.info(f"--- Finished user modification for identifier: {identifier}. Overall success: {any_success} ---")
    return any_success

def delete_user_from_all_panels(identifier: str) -> bool:
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