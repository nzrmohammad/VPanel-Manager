import logging
from datetime import datetime, timedelta
import pytz
from telebot import types
from .. import combined_handler
from ..hiddify_api_handler import hiddify_handler
from ..marzban_api_handler import marzban_handler
from ..database import db
from ..menu import menu
from ..admin_formatters import (
    fmt_users_list, fmt_panel_users_list, fmt_online_users_list,
    fmt_top_consumers, fmt_bot_users_list, fmt_birthdays_list,
    fmt_hiddify_panel_info, fmt_marzban_system_stats, fmt_users_by_plan_list,
    fmt_payments_report_list
)
from ..utils import _safe_edit, load_service_plans, parse_volume_string, escape_markdown

logger = logging.getLogger(__name__)
bot = None

def initialize_reporting_handlers(b):
    global bot
    bot = b

def handle_reports_menu(call, params):
    """Displays the main reporting menu."""
    _safe_edit(call.from_user.id, call.message.message_id, "📜 *گزارش گیری*", reply_markup=menu.admin_reports_menu())

def handle_panel_specific_reports_menu(call, params):
    """Displays the reports menu for a specific panel."""
    panel = params[0]
    panel_name = "آلمان 🇩🇪" if panel == "hiddify" else "فرانسه 🇫🇷"
    _safe_edit(call.from_user.id, call.message.message_id, f"📜 *گزارش‌های پنل {panel_name}*", reply_markup=menu.admin_panel_specific_reports_menu(panel))

def handle_health_check(call, params):
    bot.answer_callback_query(call.id, "در حال دریافت اطلاعات پنل...")
    info = hiddify_handler.get_panel_info()
    text = fmt_hiddify_panel_info(info) if info else escape_markdown("❌ اطلاعاتی دریافت نشد.")
    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin:system_status_menu"))
    _safe_edit(call.from_user.id, call.message.message_id, text, reply_markup=kb)

def handle_marzban_system_stats(call, params):
    bot.answer_callback_query(call.id, "در حال دریافت آمار سیستم مرزبان...")
    stats = marzban_handler.get_system_stats()
    text = fmt_marzban_system_stats(stats) if stats else escape_markdown("❌ اطلاعاتی دریافت نشد.")
    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin:system_status_menu"))
    _safe_edit(call.from_user.id, call.message.message_id, text, reply_markup=kb)

def handle_paginated_list(call, params):
    list_type, panel, page = params[0], params[1] if len(params) > 2 else None, int(params[-1])
    
    if panel:
        _safe_edit(call.from_user.id, call.message.message_id, "⏳ در حال دریافت اطلاعات از پنل، لطفاً صبر کنید...", reply_markup=None, parse_mode=None)

    users, all_panel_users = [], []
    if panel == 'hiddify': all_panel_users = hiddify_handler.get_all_users()
    elif panel == 'marzban': all_panel_users = marzban_handler.get_all_users()
    
    if list_type == "panel_users": 
        users = all_panel_users
    elif list_type == "online_users":
        deadline = datetime.now(pytz.utc) - timedelta(minutes=3)
        online_users = [u for u in all_panel_users if u.get('is_active') and isinstance(u.get('last_online'), datetime) and u['last_online'].astimezone(pytz.utc) >= deadline]
        for user in online_users:
            if user.get('uuid'):
                user['daily_usage_GB'] = sum(db.get_usage_since_midnight_by_uuid(user['uuid']).values())
            else:
                user['daily_usage_GB'] = 0
        users = online_users
    elif list_type == "active_users":
        deadline = datetime.now(pytz.utc) - timedelta(days=1)
        users = [u for u in all_panel_users if u.get('last_online') and u['last_online'].astimezone(pytz.utc) >= deadline]
    elif list_type == "inactive_users":
        now_utc = datetime.now(pytz.utc)
        users = [u for u in all_panel_users if u.get('last_online') and 1 <= (now_utc - u['last_online'].astimezone(pytz.utc)).days < 7]
    elif list_type == "never_connected": 
        users = [u for u in all_panel_users if not u.get('last_online')]
    elif list_type == "top_consumers":
        sorted_users = sorted(all_panel_users, key=lambda u: u.get('current_usage_GB', 0), reverse=True)
        users = sorted_users[:100]
    elif list_type == "bot_users": 
        users = db.get_all_bot_users()
    elif list_type == "birthdays": 
        users = db.get_users_with_birthdays()
    elif list_type == "payments":
        users = db.get_payment_history()

    list_configs = {
        "panel_users": {"format": lambda u, pg, p: fmt_panel_users_list(u, "آلمان 🇩🇪" if p == "hiddify" else "فرانسه 🇫🇷", pg), "back": "manage_panel"},
        "online_users": {"format": fmt_online_users_list, "back": "panel_reports"},
        "active_users": {"format": lambda u, pg, p: fmt_users_list(u, 'active', pg), "back": "panel_reports"},
        "inactive_users": {"format": lambda u, pg, p: fmt_users_list(u, 'inactive', pg), "back": "panel_reports"},
        "never_connected": {"format": lambda u, pg, p: fmt_users_list(u, 'never_connected', pg), "back": "panel_reports"},
        "top_consumers": {"format": fmt_top_consumers, "back": "analytics_menu"},
        "bot_users": {"format": fmt_bot_users_list, "back": "reports_menu"},
        "birthdays": {"format": fmt_birthdays_list, "back": "reports_menu"},
        "payments": {"format": fmt_payments_report_list, "back": "reports_menu"},
    }
    
    config = list_configs.get(list_type)
    if not config: return
    try: text = config["format"](users, page, panel)
    except TypeError: text = config["format"](users, page)
    
    base_cb = f"admin:list:{list_type}" + (f":{panel}" if panel else "")
    
    back_cb = f"admin:{config['back']}"
    if config['back'] in ['panel_reports', 'analytics_menu', 'manage_panel']:
         back_cb += f":{panel}"

    lang_code = call.from_user.language_code
    kb = menu.create_pagination_menu(base_cb, page, len(users), back_cb, lang_code)
    _safe_edit(call.from_user.id, call.message.message_id, text, reply_markup=kb)

def handle_report_by_plan_selection(call, params):
    uid, msg_id = call.from_user.id, call.message.message_id
    prompt = "لطفاً پلنی که می‌خواهید کاربران آن را مشاهده کنید، انتخاب نمایید:"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_select_plan_for_report_menu())

def _find_users_matching_plan_specs(all_users, plan_specs_set, invert_match=False):
    filtered_users = []
    for user in all_users:
        h_info = user.get('breakdown', {}).get('hiddify', {})
        m_info = user.get('breakdown', {}).get('marzban', {})
        
        user_vol_de = h_info.get('usage_limit_GB', -1.0)
        user_vol_fr = m_info.get('usage_limit_GB', -1.0)
        user_spec = (user_vol_de, user_vol_fr)

        is_match = user_spec in plan_specs_set
        
        if (invert_match and not is_match) or (not invert_match and is_match):
            filtered_users.append(user)
            
    return filtered_users

def handle_list_users_by_plan(call, params):
    plan_index, page = int(params[0]), int(params[1])
    uid, msg_id = call.from_user.id, call.message.message_id

    _safe_edit(uid, msg_id, "⏳ در حال دریافت اطلاعات و مقایسه با پلن، لطفاً صبر کنید...")

    all_plans = load_service_plans()
    if plan_index >= len(all_plans):
        _safe_edit(uid, msg_id, escape_markdown("❌ پلن انتخاب شده نامعتبر است."), reply_markup=menu.admin_panel())
        return
        
    selected_plan = all_plans[plan_index]
    plan_type = selected_plan.get('type', 'combined')

    # <<<<<<<<<<<<<<<< منطق جدید برای تشخیص پلن >>>>
    plan_vol_de = float(parse_volume_string(selected_plan.get('volume_de', '0'))) if plan_type in ['germany', 'combined'] else -1.0
    plan_vol_fr = float(parse_volume_string(selected_plan.get('volume_fr', '0'))) if plan_type in ['france', 'combined'] else -1.0
    
    plan_spec_to_match = {(plan_vol_de, plan_vol_fr)}
    all_users = combined_handler.get_all_users_combined()
    
    # تابع _find_users_matching_plan_specs بدون تغییر باقی می‌ماند
    filtered_users = _find_users_matching_plan_specs(all_users, plan_spec_to_match, invert_match=False)

    plan_name_raw = selected_plan.get('name', '')
    text = fmt_users_by_plan_list(filtered_users, plan_name_raw, page)

    base_cb = f"admin:list_by_plan:{plan_index}"
    back_cb = "admin:report_by_plan_select"
    lang_code = call.from_user.language_code
    kb = menu.create_pagination_menu(base_cb, page, len(filtered_users), back_cb, lang_code)
    _safe_edit(uid, msg_id, text, reply_markup=kb)


def handle_list_users_no_plan(call, params):
    page = int(params[0])
    uid, msg_id = call.from_user.id, call.message.message_id

    _safe_edit(uid, msg_id, "⏳ در حال دریافت اطلاعات و مقایسه با پلن‌ها، لطفاً صبر کنید...")

    all_plans = load_service_plans()
    all_users = combined_handler.get_all_users_combined()
    
    plan_specs = set()
    for plan in all_plans:
        plan_type = plan.get('type', 'combined')
        # <<<<<<<<<<<<<<<< منطق جدید برای تشخیص پلن >>>>
        vol_de = float(parse_volume_string(plan.get('volume_de', '0'))) if plan_type in ['germany', 'combined'] else -1.0
        vol_fr = float(parse_volume_string(plan.get('volume_fr', '0'))) if plan_type in ['france', 'combined'] else -1.0
        plan_specs.add((vol_de, vol_fr))

    # تابع _find_users_matching_plan_specs بدون تغییر باقی می‌ماند
    users_without_plan = _find_users_matching_plan_specs(all_users, plan_specs, invert_match=True)

    text = fmt_users_by_plan_list(users_without_plan, "بدون پلن مشخص", page)

    base_cb = "admin:list_no_plan"
    back_cb = "admin:report_by_plan_select"
    lang_code = call.from_user.language_code
    kb = menu.create_pagination_menu(base_cb, page, len(users_without_plan), back_cb, lang_code)
    _safe_edit(uid, msg_id, text, reply_markup=kb)