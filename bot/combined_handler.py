# bot/combined_handler.py
from typing import Optional, Dict, Any, List
from .hiddify_api_handler import HiddifyAPIHandler
from .marzban_api_handler import MarzbanAPIHandler
from .database import db
from .utils import validate_uuid
from datetime import datetime, timedelta, timezone
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
    ✅ نسخه نهایی اصلاح شده با لاگ کامل
    کاربر را با منطق صحیح ویرایش می‌کند.
    اگر target_panel_type مشخص شده باشد، تغییرات فقط روی آن نوع پنل اعمال می‌شود.
    """
    logger.info(f"╔═══════════════════════════════════════════════════════════")
    logger.info(f"║ Starting user modification for identifier: {identifier}")
    logger.info(f"║ Inputs: add_gb={add_gb}, add_days={add_days}, set_gb={set_gb}, set_days={set_days}")
    logger.info(f"║ Target panel type: {target_panel_type or 'ALL'}")
    logger.info(f"╚═══════════════════════════════════════════════════════════")

    user_info = get_combined_user_info(identifier)
    if not user_info:
        logger.error(f"❌ User with identifier '{identifier}' not found. Aborting modification.")
        return False

    all_panels_map = {p['name']: p for p in db.get_active_panels()}
    any_success = False

    for panel_name, panel_details in user_info.get('breakdown', {}).items():
        panel_type = panel_details.get('type')

        if target_panel_type and panel_type != target_panel_type:
            logger.info(f"⏭️  Skipping panel '{panel_name}' (type: '{panel_type}') - doesn't match target '{target_panel_type}'")
            continue

        logger.info(f"🔄 Processing panel '{panel_name}' (type: '{panel_type}')")
        
        panel_config = all_panels_map.get(panel_name)
        if not panel_config:
            logger.warning(f"⚠️  Panel config not found for '{panel_name}'")
            continue

        handler = _get_handler_for_panel(panel_config)
        if not handler:
            logger.warning(f"⚠️  Could not create handler for '{panel_name}'")
            continue

        user_panel_data = panel_details.get('data', {})
        
        if panel_type == 'hiddify' and user_info.get('uuid'):
            logger.info(f"🇩🇪 Processing Hiddify panel '{panel_name}' for user {user_info['uuid']}")
            
            payload = {}
            is_setting_new_plan = set_days is not None or set_gb is not None

            if is_setting_new_plan:
                logger.info("📝 Setting NEW plan (using set_days/set_gb)")
                payload['start_date'] = datetime.now().strftime('%Y-%m-%d')
                if set_days is not None:
                    payload['package_days'] = set_days
                    logger.info(f"   ├─ package_days = {set_days} (NEW)")
                if set_gb is not None:
                    payload['usage_limit_GB'] = set_gb
                    logger.info(f"   └─ usage_limit_GB = {set_gb} GB (NEW)")
            else:
                # --- Day Calculation Logic ---
                if add_days > 0:
                    logger.info(f"📅 Adding {add_days} days to Hiddify plan")
                    current_package_days = user_panel_data.get('package_days', 0)
                    last_reset_date_str = user_panel_data.get('last_reset_time')
                    is_expired = True

                    logger.info(f"   Current package_days: {current_package_days}")
                    logger.info(f"   Last reset time: {last_reset_date_str}")

                    if last_reset_date_str and current_package_days > 0:
                        try:
                            last_reset_date = datetime.fromisoformat(last_reset_date_str.replace('Z', '+00:00'))
                            if last_reset_date.tzinfo is None:
                                last_reset_date = last_reset_date.replace(tzinfo=timezone.utc)
                            
                            expiry_date = last_reset_date + timedelta(days=current_package_days)
                            now_utc = datetime.now(timezone.utc)
                            
                            logger.info(f"   Expiry date: {expiry_date}")
                            logger.info(f"   Current time: {now_utc}")
                            
                            if expiry_date > now_utc:
                                is_expired = False
                                logger.info(f"   ✅ Plan is ACTIVE (expires in {(expiry_date - now_utc).days} days)")
                            else:
                                logger.info(f"   ❌ Plan is EXPIRED ({(now_utc - expiry_date).days} days ago)")
                        except (ValueError, TypeError) as e:
                            logger.warning(f"   ⚠️  Could not parse last_reset_time: {e}. Assuming plan is active to be safe.")
                            is_expired = False
                    else:
                        logger.info("   ⚠️  No last_reset_time or package_days=0, assuming expired")
                    
                    if is_expired:
                        logger.info(f"   🆕 Setting NEW plan: package_days={add_days}, start_date=TODAY")
                        payload['package_days'] = add_days
                        payload['start_date'] = datetime.now().strftime('%Y-%m-%d')
                    else:
                        new_package_days = current_package_days + add_days
                        logger.info(f"   ➕ EXTENDING plan: package_days={current_package_days} + {add_days} = {new_package_days}")
                        payload['package_days'] = new_package_days

                # --- GB Calculation Logic ---
                if add_gb > 0:
                    current_limit_gb = user_panel_data.get('usage_limit_GB', 0)
                    new_limit_gb = current_limit_gb + add_gb
                    logger.info(f"💾 Adding {add_gb} GB: {current_limit_gb} + {add_gb} = {new_limit_gb} GB")
                    payload['usage_limit_GB'] = new_limit_gb
            
            logger.info(f"📤 Final Hiddify payload: {payload}")

            if payload:
                if handler.modify_user(user_info['uuid'], payload):
                    any_success = True
                    logger.info(f"✅ Successfully modified user on Hiddify panel '{panel_name}'")
                else:
                    logger.error(f"❌ Failed to modify user on Hiddify panel '{panel_name}'")
            else:
                logger.info("⚠️  No changes to apply for Hiddify panel")

        elif panel_type == 'marzban' and user_panel_data.get('username'):
            marzban_username = user_panel_data['username']
            logger.info(f"🌍 Processing Marzban panel '{panel_name}' for user '{marzban_username}'")
            
            current_data = handler.get_user_by_username(marzban_username)
            if not current_data:
                logger.error(f"❌ Could not retrieve current data for Marzban user '{marzban_username}'. Skipping.")
                continue

            current_limit_bytes = current_data.get('data_limit', 0)
            current_limit_gb = current_limit_bytes / (1024**3) if current_limit_bytes else 0
            current_expire_ts = current_data.get('expire')
            
            logger.info(f"   Current data_limit: {current_limit_gb:.2f} GB ({current_limit_bytes} bytes)")
            logger.info(f"   Current expire timestamp: {current_expire_ts}")
            
            marzban_payload = {}
            
            if set_gb is not None:
                new_limit_bytes = int(set_gb * (1024**3))
                logger.info(f"📝 Setting NEW data_limit: {set_gb} GB ({new_limit_bytes} bytes)")
                marzban_payload['data_limit'] = new_limit_bytes
            elif add_gb > 0:
                add_bytes = int(add_gb * (1024**3))
                new_limit_bytes = current_limit_bytes + add_bytes
                new_limit_gb = new_limit_bytes / (1024**3)
                logger.info(f"💾 Adding {add_gb} GB: {current_limit_gb:.2f} + {add_gb} = {new_limit_gb:.2f} GB")
                marzban_payload['data_limit'] = new_limit_bytes
            
            if set_days is not None:
                new_expire_ts = int((datetime.now() + timedelta(days=set_days)).timestamp())
                logger.info(f"📝 Setting NEW expire: {set_days} days from now (timestamp: {new_expire_ts})")
                marzban_payload['expire'] = new_expire_ts
            elif add_days > 0:
                start_date = datetime.now()
                if current_expire_ts and current_expire_ts > start_date.timestamp():
                    start_date = datetime.fromtimestamp(current_expire_ts)
                    logger.info(f"📅 Plan is active, extending from current expiry: {start_date}")
                else:
                    logger.info(f"📅 Plan is expired/new, starting from now: {start_date}")
                
                new_expire_date = start_date + timedelta(days=add_days)
                new_expire_ts = int(new_expire_date.timestamp())
                logger.info(f"   Adding {add_days} days: new expiry = {new_expire_date} (timestamp: {new_expire_ts})")
                marzban_payload['expire'] = new_expire_ts

            logger.info(f"📤 Final Marzban payload: {marzban_payload}")
            
            if marzban_payload and handler.modify_user(marzban_username, data=marzban_payload):
                any_success = True
                logger.info(f"✅ Successfully modified user on Marzban panel '{panel_name}'")
            else:
                logger.error(f"❌ Failed to modify user on Marzban panel '{panel_name}'")
    
    if any_success and (add_days > 0 or set_days is not None):
        uuid_to_check = user_info.get('uuid')
        if uuid_to_check:
            uuid_record = db.get_user_uuid_record(uuid_to_check)
            if uuid_record:
                uuid_id = uuid_record['id']
                db.reset_renewal_reminder_sent(uuid_id)
                logger.info(f"🔔 Renewal reminder flag reset for user {user_info.get('name')}")
    
    logger.info(f"╔═══════════════════════════════════════════════════════════")
    logger.info(f"║ Finished user modification for identifier: {identifier}")
    logger.info(f"║ Overall success: {any_success}")
    logger.info(f"╚═══════════════════════════════════════════════════════════")
    
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