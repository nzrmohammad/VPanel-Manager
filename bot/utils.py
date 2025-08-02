import re
import json
import logging
import os
from datetime import datetime, date, timedelta
from typing import Union, Optional
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
        logger.error(f"Error in to_shamsi conversion: value={dt}, error={e}")
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
        kwargs.setdefault('parse_mode', 'MarkdownV2')
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
    
    escaped_percent_str = escape_markdown(f"{percent:.1f}%")
    
    return f"`{filled_bar}{empty_bar} {escaped_percent_str}`"

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
    from bot import combined_handler
    import urllib.parse

    info = combined_handler.get_combined_user_info(user_uuid)
    if not info:
        return None

    parts = []

    hiddify_info = info.get('breakdown', {}).get('hiddify')
    if hiddify_info:
        usage = hiddify_info.get('current_usage_GB', 0)
        limit = hiddify_info.get('usage_limit_GB', 0)
        limit_str = f"{limit:.1f}" if limit > 0 else '∞'
        parts.append(f"🇩🇪 {usage:.2f} / {limit_str} GB ")

    marzban_info = info.get('breakdown', {}).get('marzban')
    if marzban_info:
        usage = marzban_info.get('current_usage_GB', 0)
        limit = marzban_info.get('usage_limit_GB', 0)
        
        limit_str = f"{limit:.1f}" if limit > 0 else '∞'
        parts.append(f" 🇫🇷 {usage:.2f} / {limit_str} GB ")
    
    days_left = info.get('expire')
    if parts and days_left is not None:
        days_left_str = str(days_left) if days_left >= 0 else 'پایان'
        parts.append(f"  📅 {days_left_str}  ")

    if not parts:
        return None 
        
    final_name_parts = " | ".join(parts)
    config_name = f" {final_name_parts} "
    
    encoded_name = urllib.parse.quote(config_name)
    return f"vless://00000000-0000-0000-0000-000000000000@1.1.1.1:443?type=ws&path=/&security=tls#{encoded_name}"

def generate_user_subscription_configs(user_main_uuid: str) -> list[str]:
    from . import combined_handler
    import urllib.parse

    user_info = combined_handler.get_combined_user_info(user_main_uuid)
    user_record = db.get_user_uuid_record(user_main_uuid)

    if not user_info or not user_record:
        logger.warning(f"Could not generate subscription for UUID {user_main_uuid}. User info or DB record not found.")
        return []

    has_access_de = user_info.get('on_hiddify', False)
    has_access_fr = user_info.get('on_marzban', False)
    user_name = user_record.get('name', 'کاربر')
    is_user_vip = user_record.get('is_vip', False)

    all_active_templates = db.get_active_config_templates()
    final_configs = []

    info_config = create_info_config(user_main_uuid)
    if info_config:
        final_configs.append(info_config)

    for template in all_active_templates:
        config_str = template['template_str']
        is_template_special = template.get('is_special', False)
        server_type = template.get('server_type', 'none')

        if server_type == 'fr' and not has_access_fr:
            continue
        if server_type == 'de' and not has_access_de:
            continue

        if is_template_special:
            if is_user_vip:
                final_configs.append(config_str)
        else:
            final_configs.append(config_str)

    processed_configs = []
    for config_str in final_configs:
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