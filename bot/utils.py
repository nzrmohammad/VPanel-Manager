import re
import json
import logging
import os
from datetime import datetime, date, timedelta
from typing import Union, Optional, Dict
import pytz
import jdatetime
from .config import PROGRESS_COLORS
from .database import db
import urllib.parse


logger = logging.getLogger(__name__)
bot = None

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")

def initialize_utils(b_instance):
    global bot
    bot = b_instance

def to_shamsi(dt: Optional[Union[datetime, date, str]], include_time: bool = False, month_only: bool = False) -> str:
    """
    تابع جامع برای تبدیل تاریخ میلادی (datetime, date یا str) به شمسی با مدیریت صحیح تایم‌زون.
    month_only=True: فقط نام ماه و سال را برمی‌گرداند (مثال: تیر ۱۴۰۳).
    """
    if not dt:
        return "نامشخص"
        
    try:
        gregorian_dt = None
        # بخش ۱: تبدیل ورودی‌های مختلف به یک آبجکت datetime استاندارد
        if isinstance(dt, datetime):
            gregorian_dt = dt
        elif isinstance(dt, date):
            gregorian_dt = datetime(dt.year, dt.month, dt.day)
        elif isinstance(dt, str):
            try:
                # تلاش برای پارس کردن با فرمت کامل (شامل تایم‌زون)
                gregorian_dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
            except ValueError:
                # تلاش برای پارس کردن فرمت‌های بدون تایم‌زون
                if '.' in dt:
                    dt = dt.split('.')[0] # حذف میکروثانیه‌ها
                gregorian_dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')

        if not gregorian_dt:
            return "نامشخص"

        # بخش ۲: مدیریت تایم‌زون
        # اگر تاریخ ورودی فاقد اطلاعات تایم‌زون بود، آن را UTC در نظر می‌گیریم
        if gregorian_dt.tzinfo is None:
            gregorian_dt = pytz.utc.localize(gregorian_dt)
        
        # تاریخ را به وقت تهران تبدیل می‌کنیم
        tehran_tz = pytz.timezone("Asia/Tehran")
        local_dt = gregorian_dt.astimezone(tehran_tz)
        
        # بخش ۳: تبدیل به شمسی و فرمت‌بندی خروجی
        dt_shamsi = jdatetime.datetime.fromgregorian(datetime=local_dt)
        
        # <<<<<<<<<<<<<<<< تغییر اصلی اینجاست >>>>>>>>>>>>>>>>
        # اگر فقط ماه و سال مورد نیاز باشد، آن را برمی‌گرداند
        if month_only:
            # استفاده از متد خود کتابخانه jdatetime برای دریافت نام ماه
            return f"{dt_shamsi.j_month_name()} {dt_shamsi.year}"
        
        if include_time:
            return dt_shamsi.strftime("%Y/%m/%d %H:%M:%S")
        
        return dt_shamsi.strftime("%Y/%m/%d")

    except Exception as e:
        logger.error(f"Error in to_shamsi conversion: value={dt}, error={e}", exc_info=True)
        return "خطا"



def format_relative_time(dt: Optional[datetime]) -> str:
    """یک شیء datetime را به زمان نسبی خوانا تبدیل می‌کند."""
    if not dt or not isinstance(dt, datetime): return "هرگز"
    now = datetime.now(pytz.utc); dt_utc = dt if dt.tzinfo else pytz.utc.localize(dt)
    delta = now - dt_utc; seconds = delta.total_seconds()
    if seconds < 60: return "همین الان"
    if seconds < 3600: return f"{int(seconds / 60)} دقیقه پیش"
    if seconds < 86400: return f"{int(seconds / 3600)} ساعت پیش"
    if seconds < 172800: return "دیروز"
    return f"{delta.days} روز پیش"

def days_until_next_birthday(birth_date: Optional[date]) -> Optional[int]:
    """تعداد روزهای باقی‌مانده تا تولد بعدی کاربر را محاسبه می‌کند."""
    if not birth_date: return None
    try:
        today = datetime.now().date()
        next_birthday = birth_date.replace(year=today.year)
        if next_birthday < today: next_birthday = next_birthday.replace(year=today.year + 1)
        return (next_birthday - today).days
    except (ValueError, TypeError): return None

def format_usage(usage_gb: float) -> str:
    """مصرف را به صورت خوانا (MB یا GB) فرمت‌بندی می‌کند."""
    if usage_gb is None: return "0 MB"
    if usage_gb < 1: return f"{usage_gb * 1024:.0f} MB"
    return f"{usage_gb:.2f} GB"

def load_json_file(file_name: str) -> dict | list:
    """فایل جیسون را از مسیر مشخص شده بارگذاری می‌کند."""
    try:
        script_dir = os.path.dirname(__file__)
        file_path = os.path.join(script_dir, file_name) # مسیردهی اصلاح شد
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"File not found: {file_name}")
        return {}
    except Exception as e:
        logger.error(f"Failed to load or parse {file_name}: {e}")
        return {}

# ==============================================================================
# تابع اصلاح شده و هوشمند
# ==============================================================================
def load_service_plans():
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)
        json_path = os.path.join(script_dir, 'plans.json')
        
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"CRITICAL ERROR: 'plans.json' could not be found at the expected path: {json_path}")
        return []
    except Exception as e:
        logger.error(f"CRITICAL ERROR: Failed to load or parse 'plans.json'. Error: {e}")
        return []
# ==============================================================================

def validate_uuid(uuid_str: str) -> bool:
    return bool(_UUID_RE.match(uuid_str.strip())) if uuid_str else False

def _safe_edit(chat_id: int, msg_id: int, text: str, **kwargs):
    if not bot: return
    try:
        # این خط، حالت پیش‌فرض را روی 'Markdown' تنظیم می‌کند
        # اگر در فراخوانی تابع، حالت دیگری مشخص نشود، از این استفاده می‌شود
        kwargs.setdefault('parse_mode', 'MarkdownV2') # <<< این خط مهم است

        bot.edit_message_text(text=text, chat_id=chat_id, message_id=msg_id, **kwargs)
    except Exception as e:
        logger.error(f"Safe edit failed: {e}. Text was: \n---\n{text}\n---")

def safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def escape_markdown(text: Union[str, int, float]) -> str:
    text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def create_progress_bar(percent: float, length: int = 15) -> str:
    percent = max(0, min(100, percent))
    filled_count = int(percent / 100 * length)

    filled_bar = '█' * filled_count
    empty_bar = '░' * (length - filled_count)
    percent_str = f"{percent:.1f}%" 

    return f"`{filled_bar}{empty_bar} {percent_str}`"

def load_custom_links():
    try:
        with open('custom_sub_links.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception: return {}

def parse_volume_string(volume_str: str) -> int:
    if not isinstance(volume_str, str):
        return 0
    numbers = re.findall(r'\d+', volume_str)
    if numbers:
        return int(numbers[0])
    return 0

def parse_user_agent(user_agent: str) -> Optional[Dict[str, Optional[str]]]:
    """
    Parses a user-agent string to identify the client app, OS, and version with professional accuracy,
    including detailed OS version mapping and browser identification.
    """
    if not user_agent or "TelegramBot" in user_agent:
        return None

    logger.info(f"Processing User-Agent: {user_agent}")

    # --- Tier 1: Specific VPN Client Signatures ---
    v2box_ios_match = re.search(r"^(V2Box)\s+([\d.]+);(IOS)\s+([\d.]+)", user_agent, re.IGNORECASE)
    if v2box_ios_match:
        return {
            "client": v2box_ios_match.group(1),
            "version": v2box_ios_match.group(2),
            "os": f"{v2box_ios_match.group(3).upper()} {v2box_ios_match.group(4)}"
        }

    if "CFNetwork" in user_agent and "Darwin" in user_agent:
        client_name, client_version = "Unknown Apple Client", None
        client_patterns = {
            "Shadowrocket": r"Shadowrocket/([\d.]+)", "Stash": r"Stash/([\d.]+)",
            "Quantumult X": r"Quantumult%20X/([\d.]+)", "Loon": r"Loon/([\d.]+)",
            "V2Box": r"V2Box/([\d.]+)", "Streisand": r"Streisand/([\d.]+)"
        }
        for name, pattern in client_patterns.items():
            match = re.search(pattern, user_agent)
            if match:
                client_name, client_version = name, match.group(1)
                break

        os_name = "macOS" if "Mac" in user_agent else "iOS"
        os_version = None
        darwin_match = re.search(r"Darwin/([\d.]+)", user_agent)
        if darwin_match:
            darwin_version = int(darwin_match.group(1).split('.')[0])
            darwin_to_os = { 24: "18", 23: "17", 22: "16", 21: "15", 20: "14", 19: "13" }
            os_version = darwin_to_os.get(darwin_version)

        device_model_match = re.search(r'\((iPhone|iPad|Mac)[^;]*;', user_agent)
        if device_model_match:
            os_name = device_model_match.group(1).replace("iPhone", "iOS").replace("iPad", "iPadOS")

        final_os_str = f"{os_name} {os_version}" if os_version else os_name
        return {"client": client_name, "os": final_os_str, "version": client_version}

    # --- START: FIX for HiddifyNext on Linux ---
    client_patterns = {
        'NekoBox': (r"NekoBox/([\d.]+)", lambda m: (m.group(1), 'Android')),
        'Throne': (r'Throne/([\d.]+)\s+\((\w+);\s*(\w+)\)', lambda m: (m.group(1), f"{m.group(2).capitalize()} {m.group(3)}")),
        'Hiddify': (r'HiddifyNextX?/([\d.]+)\s+\((\w+)\)', lambda m: (m.group(1), m.group(2).capitalize())),
        'v2rayNG': (r"v2rayNG/([\d.]+)", lambda m: (m.group(1), 'Android')),
        'v2rayN': (r"v2rayN/([\d.]+)", lambda m: (m.group(1), 'Windows')),
        'NekoRay': (r"nekoray/([\d.]+)", lambda m: (m.group(1), 'Linux')),
        'Happ': (r'Happ/([\d.]+)', lambda m: (m.group(1), None)),
    }
    for client_name, (pattern, extractor) in client_patterns.items():
        match = re.search(pattern, user_agent, re.IGNORECASE)
        if match:
            client_version, os_name = extractor(match)
            if not os_name:
                if 'android' in user_agent.lower(): os_name = 'Android'
                elif 'windows' in user_agent.lower(): os_name = 'Windows'
                elif 'linux' in user_agent.lower(): os_name = 'Linux'
            
            # Correct the client name if it was matched with the optional 'X'
            final_client_name = 'HiddifyNextX' if client_name == 'HiddifyNext' and 'HiddifyNextX' in match.group(0) else client_name
            return {"client": final_client_name, "os": os_name, "version": client_version}
    # --- END: FIX for HiddifyNext on Linux ---

    # --- Tier 2: Common Web Browsers ---
    browser_patterns = {
        'Chrome': r"Chrome/([\d.]+)",
        'Firefox': r"Firefox/([\d.]+)",
        'Safari': r"Version/([\d.]+).*Safari/",
        'Opera': r"OPR/([\d.]+)",
        'Mozilla': r"Mozilla/([\d.]+)" # Generic fallback
    }
    for browser_name, version_pattern in browser_patterns.items():
        version_match = re.search(version_pattern, user_agent)
        if version_match:
            if browser_name == 'Safari' and 'Chrome' in user_agent: continue
            if browser_name == 'Mozilla' and ('Chrome' in user_agent or 'Safari' in user_agent or 'Firefox' in user_agent): continue

            version = version_match.group(1)
            os_str = "Unknown OS"
            
            if "Windows" in user_agent:
                if "Windows NT 10.0" in user_agent:
                    os_str = "Windows 10/11"
                else:
                    os_str = "Windows"
            elif "Android" in user_agent:
                android_match = re.search(r"Android ([\d.]+)", user_agent)
                os_str = android_match.group(0) if android_match else "Android"
            elif "Macintosh" in user_agent:
                mac_match = re.search(r"Mac OS X ([\d_]+)", user_agent)
                os_str = f"macOS {mac_match.group(1).replace('_', '.')}" if mac_match else "macOS"
            elif "Linux" in user_agent: os_str = "Linux"

            logger.info(f"Identified standard browser: {browser_name} on {os_str}")
            return {"client": browser_name, "os": os_str, "version": version}

    # --- Tier 3: Generic Fallback ---
    logger.warning(f"Unmatched User-Agent (using generic fallback): {user_agent}")
    generic_client = user_agent.split('/')[0].split(' ')[0]
    return {"client": generic_client, "os": "Unknown", "version": None}


def format_daily_usage(gb: float) -> str:
    if gb < 0: return "0 MB"
    if gb < 1: return f"{gb * 1024:.0f} MB"
    return f"{gb:.2f} GB"

def days_until_next_birthday(birthday: Optional[date]) -> Optional[int]:
    if not birthday:
        return None
    
    today = date.today()
    if isinstance(birthday, datetime):
        birthday = birthday.date()
        
    next_birthday = birthday.replace(year=today.year)
    
    if next_birthday < today:
        next_birthday = next_birthday.replace(year=today.year + 1)
        
    return (next_birthday - today).days

def get_processed_user_data(uuid: str) -> Optional[dict]:
    from .combined_handler import get_combined_user_info
    info = get_combined_user_info(uuid)
    if not info:
        return None

    processed_info = info.copy()
    breakdown = info.get('breakdown', {})
    
    processed_info['on_hiddify'] = 'hiddify' in breakdown and bool(breakdown.get('hiddify'))
    processed_info['on_marzban'] = 'marzban' in breakdown and bool(breakdown.get('marzban'))
    processed_info['last_online_relative'] = format_relative_time(info.get('last_online'))
    
    # پردازش جزئیات هر پنل با استفاده از تابع to_shamsi
    if processed_info['on_hiddify']:
        h_info = breakdown['hiddify']
        h_info['last_online_shamsi'] = to_shamsi(h_info.get('last_online'), include_time=True)
        daily_usage_h = db.get_usage_since_midnight_by_uuid(uuid).get('hiddify', 0.0)
        h_info['daily_usage_formatted'] = format_usage(daily_usage_h)

    if processed_info['on_marzban']:
        m_info = breakdown['marzban']
        m_info['last_online_shamsi'] = to_shamsi(m_info.get('last_online'), include_time=True)
        daily_usage_m = db.get_usage_since_midnight_by_uuid(uuid).get('marzban', 0.0)
        m_info['daily_usage_formatted'] = format_usage(daily_usage_m)

    # تبدیل روزهای انقضا به تاریخ شمسی
    expire_days = info.get('expire')
    if expire_days is not None and expire_days >= 0:
        expire_date = datetime.now() + timedelta(days=expire_days)
        processed_info['expire_shamsi'] = to_shamsi(expire_date)
    else:
        processed_info['expire_shamsi'] = "نامحدود" if expire_days is None else "منقضی"


    user_record = db.get_user_uuid_record(uuid)
    if user_record:
        processed_info['created_at'] = user_record.get('created_at')

    return processed_info

def create_info_config(user_uuid: str) -> Optional[str]:
    from . import combined_handler
    import urllib.parse

    info = combined_handler.get_combined_user_info(user_uuid)
    if not info:
        return None

    user_record = db.get_user_uuid_record(user_uuid)
    if not user_record:
        return None

    has_access_de = user_record.get('has_access_de', False)
    has_access_fr = user_record.get('has_access_fr', False)
    has_access_tr = user_record.get('has_access_tr', False)

    parts = []
    breakdown = info.get('breakdown', {})
    
    hiddify_info = next((p['data'] for p in breakdown.values() if p.get('type') == 'hiddify'), None)
    marzban_info = next((p['data'] for p in breakdown.values() if p.get('type') == 'marzban'), None)

    if has_access_de and hiddify_info:
        usage = hiddify_info.get('current_usage_GB', 0)
        limit = hiddify_info.get('usage_limit_GB', 0)
        limit_str = f"{limit:.0f}" if limit > 0 else '∞'
        parts.append(f"🇩🇪 {usage:.0f}/{limit_str}GB")

    if (has_access_fr or has_access_tr) and marzban_info:
        flags = []
        if has_access_fr:
            flags.append("🇫🇷")
        if has_access_tr:
            flags.append("🇹🇷")
        
        flag_str = "".join(flags)
        usage = marzban_info.get('current_usage_GB', 0)
        limit = marzban_info.get('usage_limit_GB', 0)
        limit_str = f"{limit:.0f}" if limit > 0 else '∞'
        parts.append(f"{flag_str} {usage:.0f}/{limit_str}GB")

    days_left = info.get('expire')
    if days_left is not None:
        days_left_str = str(days_left) if days_left >= 0 else 'پایان'
        parts.append(f"📅{days_left_str}")

    if not parts:
        return None 
        
    final_name_parts = " | ".join(parts)
    encoded_name = urllib.parse.quote(final_name_parts)
    return f"vless://00000000-0000-0000-0000-000000000000@1.1.1.1:443?type=ws&path=/&security=tls#{encoded_name}"

def generate_user_subscription_configs(user_main_uuid: str, user_id: int) -> list[str]:
    from . import combined_handler
    import urllib.parse
    import random
    from .config import RANDOM_SERVERS_COUNT

    user_info = combined_handler.get_combined_user_info(user_main_uuid)
    user_record = db.get_user_uuid_record(user_main_uuid)
    if not user_info or not user_record:
        logger.warning(f"Could not generate subscription for UUID {user_main_uuid}. User info or DB record not found.")
        return []

    user_settings = db.get_user_settings(user_id)
    show_info_conf = user_settings.get('show_info_config', True)
    
    final_configs_to_process = []

    if show_info_conf:
        info_config = create_info_config(user_main_uuid)
        if info_config:
            final_configs_to_process.append(info_config)

    has_access_de = user_record.get('has_access_de', False)
    has_access_fr = user_record.get('has_access_fr', False)
    has_access_tr = user_record.get('has_access_tr', False)
    is_user_vip = user_record.get('is_vip', False)
    user_name = user_record.get('name', 'کاربر')

    # --- ✨ شروع منطق کاملاً جدید برای حفظ ترتیب ---
    # ۱. دریافت تمام کانفیگ‌های فعال با حفظ ترتیب اصلی (بر اساس ID)
    all_active_templates = db.get_active_config_templates()

    # ۲. فیلتر کردن کانفیگ‌ها بر اساس دسترسی کاربر
    eligible_templates = []
    for tpl in all_active_templates:
        is_special = tpl.get('is_special', False)
        server_type = tpl.get('server_type', 'none')
        
        if (is_special and not is_user_vip) or \
           (server_type == 'de' and not has_access_de) or \
           (server_type == 'fr' and not has_access_fr) or \
           (server_type == 'tr' and not has_access_tr):
            continue
        eligible_templates.append(tpl)

    # ۳. جدا کردن کانفیگ‌های ثابت از کانفیگ‌های داخل استخر تصادفی
    fixed_templates = [tpl for tpl in eligible_templates if not tpl.get('is_random_pool')]
    random_pool_templates = [tpl for tpl in eligible_templates if tpl.get('is_random_pool')]

    # ۴. انتخاب تصادفی از استخر (در صورت نیاز)
    chosen_random_templates = []
    if RANDOM_SERVERS_COUNT and RANDOM_SERVERS_COUNT > 0 and len(random_pool_templates) > RANDOM_SERVERS_COUNT:
        chosen_random_templates = random.sample(random_pool_templates, RANDOM_SERVERS_COUNT)
    else:
        chosen_random_templates = random_pool_templates # اگر تعداد کمتر بود، همه را انتخاب کن

    # ۵. ترکیب کانفیگ‌های ثابت و کانفیگ‌های انتخاب شده از استخر
    final_template_objects = fixed_templates + chosen_random_templates
    
    # ۶. مرتب‌سازی لیست نهایی بر اساس ID اصلی برای حفظ ترتیب اولیه
    final_template_objects.sort(key=lambda x: x['id'], reverse=False)
    
    # ۷. استخراج رشته کانفیگ‌ها از آبجکت‌های مرتب شده
    final_configs_to_process.extend([tpl['template_str'] for tpl in final_template_objects])
    # --- ✨ پایان منطق جدید ---

    processed_configs = []
    for config_str in final_configs_to_process:
        # جایگزینی متغیرها در تمام کانفیگ‌ها
        if "{new_uuid}" in config_str or "{name}" in config_str:
            config_str = config_str.replace("{new_uuid}", user_main_uuid)
            config_str = config_str.replace("{name}", urllib.parse.quote(user_name))
        processed_configs.append(config_str)

    return processed_configs

def set_template_server_type_service(template_id: int, server_type: str):
    db.set_template_server_type(template_id, server_type)
    return True

def reset_all_templates():
    """سرویس برای ریست کردن جدول قالب‌های کانفیگ."""
    logger.info("Executing service to reset all config templates.")
    db.reset_templates_table()
    return True

def save_service_plans(plans: list) -> bool:
    """لیست پلن‌ها را در فایل plans.json ذخیره می‌کند."""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        json_path = os.path.join(script_dir, 'plans.json')
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(plans, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logger.error(f"CRITICAL ERROR: Failed to save 'plans.json'. Error: {e}")
        return False