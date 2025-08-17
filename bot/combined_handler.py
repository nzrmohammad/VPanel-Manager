# bot/combined_handler.py
from typing import Optional, Dict, Any, List
from .hiddify_api_handler import HiddifyAPIHandler
from .marzban_api_handler import MarzbanAPIHandler
from .database import db
from .utils import validate_uuid
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
            uuid = user.get('uuid')
            identifier = uuid or f"marzban_{user.get('name')}"
            
            if identifier not in all_users_map:
                all_users_map[identifier] = {
                    'uuid': uuid,
                    'is_active': False, 'expire': None,
                    'current_usage_GB': 0, 'usage_limit_GB': 0,
                    'breakdown': {},
                    'panels': set()
                }

            all_users_map[identifier]['breakdown'][panel_name] = {
                "data": user,
                "type": panel_config['panel_type']
            }
            all_users_map[identifier]['panels'].add(panel_name)
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
    
    user_data_map = {}

    for panel_config in all_panels:
        handler = _get_handler_for_panel(panel_config)
        if not handler: continue

        user_info = None
        # منطق پیدا کردن کاربر بر اساس نوع پنل
        if panel_config['panel_type'] == 'hiddify' and is_uuid:
            user_info = handler.user_info(identifier)
        elif panel_config['panel_type'] == 'marzban':
            marzban_username = db.get_marzban_username_by_uuid(identifier) if is_uuid else identifier
            if marzban_username:
                user_info = handler.get_user_by_username(marzban_username)

        if user_info:
            user_data_map[panel_config['name']] = {
                "data": user_info,
                "type": panel_config['panel_type']
            }

    if not user_data_map:
        return None

    # --- START OF FIX ---
    # ترکیب اطلاعات پیدا شده با منطق اصلاح شده
    final_info = {
        'breakdown': user_data_map,
        'is_active': any(p['data'].get('is_active') for p in user_data_map.values()),
        'current_usage_GB': sum(p['data'].get('current_usage_GB', 0) for p in user_data_map.values()),
        'usage_limit_GB': sum(p['data'].get('usage_limit_GB', 0) for p in user_data_map.values()),
        # انتخاب کمترین (زودترین) تاریخ انقضا به عنوان تاریخ انقضای نهایی
        'expire': min([p['data'].get('expire') for p in user_data_map.values() if p['data'].get('expire') is not None] or [None]),
        'uuid': identifier if is_uuid else next((p['data'].get('uuid') for p in user_data_map.values() if p['data'].get('uuid')), None),
        'name': identifier if not is_uuid else next((p['data'].get('name') for p in user_data_map.values() if p['data'].get('name')), "کاربر ناشناس")
    }
    # --- END OF FIX ---
    
    limit = final_info['usage_limit_GB']
    usage = final_info['current_usage_GB']
    final_info['remaining_GB'] = max(0, limit - usage)
    final_info['usage_percentage'] = (usage / limit * 100) if limit > 0 else 0
    
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

def modify_user_on_all_panels(identifier: str, add_gb: float = 0, add_days: int = 0, target_panel_name: Optional[str] = None) -> bool:
    """یک کاربر را در پنل(های) مشخص شده یا در همه‌ی پنل‌ها ویرایش می‌کند."""
    user_info = get_combined_user_info(identifier)
    if not user_info: return False

    all_panels_map = {p['name']: p for p in db.get_all_panels()}
    any_success = False

    panels_to_modify = [target_panel_name] if target_panel_name else user_info['breakdown'].keys()

    for panel_name in panels_to_modify:
        if panel_name not in user_info['breakdown']: continue
        
        panel_config = all_panels_map.get(panel_name)
        if not panel_config: continue
        
        handler = _get_handler_for_panel(panel_config)
        if not handler: continue

        user_panel_details = user_info['breakdown'][panel_name]
        user_panel_data = user_panel_details.get('data', {})
        
        if panel_config['panel_type'] == 'hiddify' and user_panel_data.get('uuid'):
            payload = {}
            if add_gb: payload['usage_limit_GB'] = user_panel_data.get('usage_limit_GB', 0) + add_gb
            if add_days: 
                current_expire = user_panel_data.get('expire')
                # If expire is None or negative, base the addition on today
                base_days = max(0, current_expire) if current_expire is not None else 0
                payload['package_days'] = base_days + add_days
            if handler.modify_user(user_panel_data['uuid'], payload):
                any_success = True
        
        elif panel_config['panel_type'] == 'marzban' and user_panel_data.get('username'):
            if handler.modify_user(user_panel_data['username'], add_usage_gb=add_gb, add_days=add_days):
                any_success = True
                
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
    
    if all_success and user_info.get('uuid'):
        db.delete_user_by_uuid(user_info['uuid'])
        
    return all_success