import logging
import jdatetime
import pytz
from datetime import datetime, timedelta
from .config import EMOJIS, PAGE_SIZE, ACHIEVEMENTS 
from .database import db
from . import combined_handler
from .language import get_string
from .utils import (
    create_progress_bar,
    format_daily_usage, escape_markdown,
    to_shamsi, days_until_next_birthday,
    parse_user_agent
)

logger = logging.getLogger(__name__)

def fmt_one(info: dict, daily_usage_dict: dict, lang_code: str) -> str:
    """Formats the detailed information for a single user account to the new desired format."""
    if not info:
        return escape_markdown(get_string("fmt_err_getting_info", lang_code))

    user_record = db.get_user_uuid_record(info.get("uuid", ""))
    has_access_de = user_record.get('has_access_de', False) if user_record else False
    has_access_fr = user_record.get('has_access_fr', False) if user_record else False
    has_access_tr = user_record.get('has_access_tr', False) if user_record else False

    raw_name = info.get("name", get_string('unknown_user', lang_code))
    is_active_overall = info.get("is_active", False)
    status_emoji = get_string("fmt_status_active", lang_code) if is_active_overall else get_string("fmt_status_inactive", lang_code)
    header_raw = f"{get_string('fmt_user_name_header', lang_code)} : {raw_name} ({EMOJIS['success'] if is_active_overall else EMOJIS['error']} {status_emoji})"
    header_line = f"*{escape_markdown(header_raw)}*"

    report = [header_line]
    separator = "`──────────────────`"
    report.append(separator)
    
    breakdown = info.get('breakdown', {})
    
    def format_panel_details(panel_data, daily_usage, panel_type):
        flags = ""
        if panel_type == 'hiddify' and has_access_de:
            flags = "🇩🇪"
        elif panel_type == 'marzban':
            if has_access_fr: flags += "🇫🇷"
            if has_access_tr: flags += "🇹🇷"
        
        if not flags:
            return []

        limit = panel_data.get("usage_limit_GB", 0.0)
        usage = panel_data.get("current_usage_GB", 0.0)
        remaining = max(0, limit - usage)
        
        return [
            f"*سرور {flags}*",
            f"{EMOJIS['database']} {escape_markdown('حجم کل :')} {escape_markdown(f'{limit:.0f} GB')}",
            f"{EMOJIS['fire']} {escape_markdown('حجم مصرف شده :')} {escape_markdown(f'{usage:.0f} GB')}",
            f"{EMOJIS['download']} {escape_markdown('حجم باقیمانده :')} {escape_markdown(f'{remaining:.0f} GB')}",
            f"{EMOJIS['lightning']} {escape_markdown('مصرف امروز :')} {escape_markdown(format_daily_usage(daily_usage))}",
            f"{EMOJIS['time']} {escape_markdown('آخرین اتصال :')} {escape_markdown(to_shamsi(panel_data.get('last_online'), include_time=True))}",
            separator
        ]

    for panel_name, panel_details in breakdown.items():
        panel_data = panel_details.get('data', {})
        panel_type = panel_details.get('type')
        daily_usage = daily_usage_dict.get(panel_type, 0.0) if panel_type else 0.0
        report.extend(format_panel_details(panel_data, daily_usage, panel_type))

    uuid_str = info.get('uuid')
    if uuid_str:
        uuid_id = db.get_uuid_id_by_uuid(uuid_str)
        if uuid_id:
            user_agents = db.get_user_agents_for_uuid(uuid_id)
            if user_agents:
                report.append("📱 *دستگاه‌های شما*")
                for agent in user_agents[:6]: 
                    parsed = parse_user_agent(agent['user_agent'])
                    if parsed:
                        os_name_lower = (parsed.get('os') or '').lower()
                        icon = "❓" # Default icon
                        if 'ios' in os_name_lower or 'macos' in os_name_lower:
                            icon = "📱"
                        elif 'android' in os_name_lower:
                            icon = "🤖"
                        elif 'windows' in os_name_lower:
                            icon = "🖥️"
                        elif 'linux' in os_name_lower:
                            icon = "🐧"
                        elif 'browser' in (parsed.get('client') or '').lower():
                            icon = "🌐"

                        client_name = escape_markdown(parsed.get('client', 'Unknown'))
                        details = []
                        if parsed.get('version'):
                            details.append(f"v{escape_markdown(parsed['version'])}")
                        if parsed.get('os'):
                            details.append(escape_markdown(parsed['os']))
                        
                        details_str = f" \\({', '.join(details)}\\)" if details else ""
                        last_seen_str = escape_markdown(to_shamsi(agent['last_seen'], include_time=True))

                        report.append(f"` `└─ {icon} *{client_name}*{details_str} \\(_{last_seen_str}_\\)")

                report.append(separator)

    expire_days = info.get("expire")
    expire_label = get_string("fmt_expire_unlimited", lang_code)
    if expire_days is not None:
        expire_label = get_string("fmt_status_expired", lang_code) if expire_days < 0 else get_string("fmt_expire_days", lang_code).format(days=expire_days)

    report.extend([
        f'*{get_string("fmt_expiry_date_new", lang_code)} :* {escape_markdown(expire_label)}',
        f'*{get_string("fmt_uuid_new", lang_code)} :* `{escape_markdown(info.get("uuid", ""))}`',
        "",
        f'*{get_string("fmt_status_bar_new", lang_code)} :* {create_progress_bar(info.get("usage_percentage", 0))}'
    ])
    
    return "\n".join(report)

def quick_stats(uuid_rows: list, page: int, lang_code: str) -> tuple[str, dict]:
    num_uuids = len(uuid_rows)
    menu_data = {"num_accounts": num_uuids, "current_page": 0}
    if not num_uuids: 
        return escape_markdown(get_string("fmt_no_account_registered", lang_code)), menu_data

    current_page = max(0, min(page, num_uuids - 1))
    menu_data["current_page"] = current_page
    
    target_row = uuid_rows[current_page]
    info = combined_handler.get_combined_user_info(target_row['uuid'])
    
    if not info:
        err_msg = get_string("fmt_err_getting_info_for_page", lang_code).format(page=current_page + 1)
        return escape_markdown(err_msg), menu_data

    daily_usage_dict = db.get_usage_since_midnight(target_row['id'])
    report_text = fmt_one(info, daily_usage_dict, lang_code=lang_code)
    
    return report_text, menu_data

def fmt_user_report(user_infos: list, lang_code: str) -> str:
    if not user_infos:
        return ""

    accounts_reports = []
    total_daily_usage_all_accounts = 0.0

    for info in user_infos:
        user_record = db.get_user_uuid_record(info.get("uuid", ""))
        has_access_de = user_record.get('has_access_de', False) if user_record else False
        has_access_fr = user_record.get('has_access_fr', False) if user_record else False
        has_access_tr = user_record.get('has_access_tr', False) if user_record else False

        name = info.get("name", get_string('unknown_user', lang_code))
        header = get_string("fmt_report_account_header", lang_code).format(name=name)
        account_lines = [f'*{escape_markdown(header)}*']
        
        daily_usage_dict = {}
        if 'db_id' in info:
            daily_usage_dict = db.get_usage_since_midnight(info['db_id'])
            total_daily_usage_all_accounts += sum(daily_usage_dict.values())

        volume_str = f"{info.get('usage_limit_GB', 0):.2f} GB"
        volume_line = get_string("fmt_report_total_volume", lang_code).format(volume=volume_str)
        account_lines.append(escape_markdown(volume_line))
        
        usage_str = f"{info.get('current_usage_GB', 0):.2f} GB"
        usage_line = get_string("fmt_report_used_volume", lang_code).format(usage=usage_str)
        account_lines.append(escape_markdown(usage_line))
        
        remaining_str = f"{max(0, info.get('usage_limit_GB', 0) - info.get('current_usage_GB', 0)):.2f} GB"
        remaining_line = get_string("fmt_report_remaining_volume", lang_code).format(remaining=remaining_str)
        account_lines.append(escape_markdown(remaining_line))
        
        account_lines.append(escape_markdown(get_string("fmt_report_daily_usage_header", lang_code)))
        
        breakdown = info.get('breakdown', {})
        for panel_name, panel_details in breakdown.items():
            panel_type = panel_details.get('type')
            if panel_type:
                panel_daily_usage = daily_usage_dict.get(panel_type, 0.0)
                
                flags = ""
                if panel_type == "hiddify" and has_access_de:
                    flags = "🇩🇪"
                elif panel_type == "marzban":
                    if has_access_fr: flags += "🇫🇷"
                    if has_access_tr: flags += "🇹🇷"
                
                if flags:
                    account_lines.append(f" {flags} : {escape_markdown(format_daily_usage(panel_daily_usage))}")

        expire_days = info.get("expire")
        expire_str = f"`{escape_markdown(get_string('fmt_expire_unlimited', lang_code))}`"
        if expire_days is not None:
            expire_word = "روز"
            expire_str = f"{expire_days} {escape_markdown(expire_word)}" if expire_days >= 0 else escape_markdown(get_string("fmt_status_expired", lang_code))
        
        expiry_line = get_string("fmt_report_expiry", lang_code).format(expiry=expire_str)
        account_lines.append(escape_markdown(expiry_line))

        accounts_reports.append("\n".join(account_lines))
    
    final_report = "\n\n".join(accounts_reports)

    usage_footer_str = format_daily_usage(total_daily_usage_all_accounts)
    footer_key = "fmt_report_footer_total_multi" if len(user_infos) > 1 else "fmt_report_footer_total_single"
    
    raw_footer_template = get_string(footer_key, lang_code)
    formatted_footer = raw_footer_template.format(usage=usage_footer_str)
    footer_text = f'*{escape_markdown(formatted_footer)}*'
    
    final_report += f"\n\n {footer_text}"
    return final_report

# در فایل bot/user_formatters.py

def fmt_user_weekly_report(user_infos: list, lang_code: str) -> str:
    """
    گزارش هفتگی کاملی را شامل تفکیک مصرف روزانه، تحلیل هوشمند و دستاوردهای هفته برای کاربر فرمت‌بندی می‌کند.
    """
    if not user_infos:
        return ""

    accounts_reports = []
    separator = '`──────────────────`'
    day_names = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]
    
    tehran_tz = pytz.timezone("Asia/Tehran")
    today_jalali = jdatetime.datetime.now(tz=tehran_tz)
    days_since_saturday = (today_jalali.weekday() + 1) % 7
    week_start_utc = (datetime.now(tehran_tz) - timedelta(days=days_since_saturday)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.utc)

    for info in user_infos:
        uuid = info.get("uuid")
        if not uuid: continue
            
        uuid_id = db.get_uuid_id_by_uuid(uuid)
        user_record = db.get_user_uuid_record(uuid)
        if not uuid_id or not user_record: continue
        
        user_id = user_record.get('user_id')

        has_access_de = user_record.get('has_access_de', False)
        has_access_fr = user_record.get('has_access_fr', False)
        has_access_tr = user_record.get('has_access_tr', False)
        name = info.get("name", get_string('unknown_user', lang_code))
        header = get_string("fmt_report_account_header", lang_code).format(name=name)
        
        daily_history = db.get_user_daily_usage_history_by_panel(uuid_id, days=7)
        current_week_usage = sum(item['total_usage'] for item in daily_history)

        account_lines = [f'*{escape_markdown(header)}*']
        
        has_usage_data = False
        for item in reversed(daily_history):
            if item['total_usage'] > 0.001:
                has_usage_data = True
                date_shamsi = to_shamsi(item['date'])
                usage_formatted = format_daily_usage(item['total_usage'])
                account_lines.append(f"\n در `{date_shamsi}` : *{escape_markdown(usage_formatted)}*")
                daily_breakdown_parts = []
                if has_access_de and item['hiddify_usage'] > 0.001:
                    daily_breakdown_parts.append(f"🇩🇪 {escape_markdown(format_daily_usage(item['hiddify_usage']))}")
                marzban_flags = []
                if has_access_fr: marzban_flags.append("🇫🇷")
                if has_access_tr: marzban_flags.append("🇹🇷")
                if marzban_flags and item['marzban_usage'] > 0.001:
                    daily_breakdown_parts.append(f"{''.join(marzban_flags)} {escape_markdown(format_daily_usage(item['marzban_usage']))}")
                if daily_breakdown_parts:
                    account_lines.append(f" \\({', '.join(daily_breakdown_parts)}\\)")
        
        if not has_usage_data:
            account_lines.append(f"\n_{escape_markdown('در این هفته مصرفی برای این اکانت ثبت نشده است.')}_")

        usage_footer_str = format_daily_usage(current_week_usage)
        footer_template = get_string("weekly_usage_header", lang_code)
        final_footer_line = f"{footer_template} {usage_footer_str}"
        account_lines.append(f'\n\n⚡️ *{escape_markdown(final_footer_line)}*')

        if user_id:
            weekly_achievements = db.get_user_achievements_in_range(user_id, week_start_utc)
            if weekly_achievements:
                account_lines.append(separator)
                account_lines.append(f"🏆 *{escape_markdown('دستاوردها و جوایز این هفته')}*")
                for ach in weekly_achievements:
                    badge_code = ach['badge_code']
                    badge_data = ACHIEVEMENTS.get(badge_code, {})
                    badge_name = escape_markdown(badge_data.get('name', badge_code))
                    badge_icon = badge_data.get('icon', '🎖️')
                    points = badge_data.get('points', 0)
                    account_lines.append(f"{badge_icon} {badge_name} \\(*\\+{points} امتیاز*\\)")
        
        # --- بخش تحلیل هوشمند ---
        if current_week_usage > 0.1: # حداقل مصرف برای نمایش تحلیل
            busiest_day_info = max(daily_history, key=lambda x: x['total_usage'])
            busiest_day_name = day_names[jdatetime.datetime.fromgregorian(date=busiest_day_info['date']).weekday()]

            total_hiddify = sum(d['hiddify_usage'] for d in daily_history)
            total_marzban = sum(d['marzban_usage'] for d in daily_history)
            most_used_server = "آلمان 🇩🇪" if total_hiddify >= total_marzban else "فرانسه/ترکیه 🇫🇷🇹🇷"
            
            time_of_day_stats = db.get_weekly_usage_by_time_of_day(uuid_id)
            busiest_period_key = max(time_of_day_stats, key=time_of_day_stats.get)
            
            period_map = {
                "morning": "صبح ☀️", "afternoon": "بعد از ظهر 🏙️",
                "evening": "عصر 🌆", "night": "شب 🦉"
            }
            busiest_period_name = period_map.get(busiest_period_key, "ساعات مختلف")

            summary_text = (
                f"\n\nسلام {escape_markdown(name.split('(')[0].strip())}\\!\n"
                f"این هفته *{escape_markdown(format_daily_usage(current_week_usage))}* مصرف داشتی\\. "
                f"پرمصرف‌ترین روزت *{escape_markdown(busiest_day_name)}* بود و بیشتر از سرور *{escape_markdown(most_used_server)}* استفاده کردی\\. "
                f"به نظر میاد بیشتر در *{escape_markdown(busiest_period_name)}* فعال هستی\\!"
            )
            account_lines.append(summary_text)

        accounts_reports.append("\n".join(account_lines))

    final_report = f"\n{separator}\n".join(accounts_reports)
    return final_report


def fmt_service_plans(plans_to_show: list, plan_type: str, lang_code: str) -> str:
    if not plans_to_show:
        return escape_markdown(get_string("fmt_plans_none_in_category", lang_code))
    
    type_map = { 
        "combined": "fmt_plan_type_combined", 
        "germany": "fmt_plan_type_germany", 
        "france": "fmt_plan_type_france",
        "turkey": "fmt_plan_type_turkey"
    }
    type_title = get_string(type_map.get(plan_type, "fmt_plan_type_general"), lang_code)
    
    raw_title_template = get_string("fmt_plans_title", lang_code)
    formatted_title = raw_title_template.format(type_title=type_title)
    title = f'*{escape_markdown(formatted_title)}*'
    
    lines = [title]

    if plan_type == "combined":
        lines.append(escape_markdown(get_string('plan_guide_combined', lang_code)))
    elif plan_type in ["germany", "france", "turkey"]:
        lines.append(escape_markdown(get_string('plan_guide_dedicated', lang_code)))

    separator = "`────────────────────`"
    
    for plan in plans_to_show:
        lines.append(separator)
        lines.append(f"*{escape_markdown(plan.get('name'))}*")
        
        details = []
        if plan.get('total_volume'):
            details.append(f'*{get_string("fmt_plan_label_total_volume", lang_code)}:* {escape_markdown(plan["total_volume"])}')
        
        if plan_type == 'germany' and plan.get('volume_de'):
            details.append(f'*{get_string("fmt_plan_label_volume", lang_code)}:* {escape_markdown(plan["volume_de"])}')
        elif plan_type == 'france' and plan.get('volume_fr'):
            details.append(f'*{get_string("fmt_plan_label_volume", lang_code)}:* {escape_markdown(plan["volume_fr"])}')
        elif plan_type == 'turkey' and plan.get('volume_tr'):
            details.append(f'*{get_string("fmt_plan_label_volume", lang_code)}:* {escape_markdown(plan["volume_tr"])}')
        elif plan_type == 'combined':
            if plan.get('volume_de'):
                details.append(f'*{get_string("fmt_plan_label_germany", lang_code)}:* {escape_markdown(plan["volume_de"])}')
            if plan.get('volume_fr'):
                details.append(f'*{get_string("fmt_plan_label_france", lang_code)}:* {escape_markdown(plan["volume_fr"])}')

        details.append(f'*{get_string("fmt_plan_label_duration", lang_code)}:* {escape_markdown(plan["duration"])}')
        
        price_formatted = get_string("fmt_currency_unit", lang_code).format(price=plan.get('price', 0))
        details.append(f'*{get_string("fmt_plan_label_price", lang_code)}:* {escape_markdown(price_formatted)}')
        
        lines.extend(details)

    lines.append(separator)
    if plan_type == "combined":
        lines.append(escape_markdown(get_string("fmt_plans_note_combined", lang_code)))
    
    lines.append(f'\n{escape_markdown(get_string("fmt_plans_footer_contact_admin", lang_code))}')
    
    return "\n".join(lines)


def fmt_panel_quick_stats(panel_name: str, stats: dict, lang_code: str) -> str:
    raw_title_template = get_string('fmt_panel_stats_title', lang_code)
    formatted_title = raw_title_template.format(panel_name=panel_name)
    title = f"*{escape_markdown(formatted_title)}*"

    
    lines = [title, ""]
    if not stats:
        lines.append(escape_markdown(get_string("fmt_panel_stats_no_info", lang_code)))
        return "\n".join(lines)
        
    for hours, usage_gb in stats.items():
        usage_str = escape_markdown(format_daily_usage(usage_gb))
        line_template = get_string("fmt_panel_stats_hours_ago", lang_code)
        lines.append(line_template.format(hours=f"`{hours}`", usage=usage_str))

    lines.append(f"\n{escape_markdown(get_string('fmt_panel_stats_note', lang_code))}")
        
    return "\n".join(lines)


def fmt_user_payment_history(payments: list, user_name: str, page: int, lang_code: str) -> str:
    total_payments = len(payments)
    title_action = get_string("fmt_payment_history_title_single" if total_payments == 1 else "fmt_payment_history_title_multi", lang_code)
    title_template = get_string("fmt_payment_history_header", lang_code)
    title_str_raw = title_template.format(action=title_action, user_name=user_name)
    header_text = f"*{escape_markdown(title_str_raw)}*"

    if not payments:
        no_info_text = escape_markdown(get_string('fmt_payment_history_no_info', lang_code))
        return f"{header_text}\n\n{no_info_text}"

    page_size = PAGE_SIZE
    if total_payments > page_size:
        total_pages = (total_payments + page_size - 1) // page_size
        pagination_text = get_string("fmt_payment_page_of", lang_code).format(current_page=page + 1, total_pages=total_pages)
        header_text += f"\n_{escape_markdown(pagination_text)}_"

    lines = [header_text]
    paginated_payments = payments[page * page_size : (page + 1) * page_size]

    for i, payment in enumerate(paginated_payments):
        label_key = "fmt_payment_label_purchase" if i == total_payments - 1 else "fmt_payment_label_renewal"
        label = get_string(label_key, lang_code)
        datetime_str = f"`{to_shamsi(payment.get('payment_date'))}`"
        lines.append(get_string("fmt_payment_item", lang_code).format(label=label, datetime=datetime_str))

    return "\n".join(lines)


def fmt_registered_birthday_info(user_data: dict, lang_code: str) -> str:
    if not user_data or not user_data.get('birthday'):
        return escape_markdown(get_string("fmt_err_getting_birthday_info", lang_code))

    birthday_obj = user_data['birthday']
    shamsi_date_str = f"`{escape_markdown(to_shamsi(birthday_obj))}`"
    remaining_days = days_until_next_birthday(birthday_obj)

    header = f'*{escape_markdown(get_string("fmt_birthday_header", lang_code))}*'
    separator = "`────────────────────`"
    
    lines = [header, separator]
    lines.append(f'*{get_string("fmt_birthday_registered_date", lang_code)}:* {shamsi_date_str}')

    if remaining_days is not None:
        if remaining_days == 0:
            lines.append(f'*{escape_markdown(get_string("fmt_birthday_countdown_today", lang_code))}* 🎉')
            lines.append(f"_{escape_markdown(get_string('fmt_birthday_gift_added', lang_code))}_")
        else:
            days_str = str(remaining_days)
            raw_template = get_string("fmt_birthday_countdown_days", lang_code)
            full_text = raw_template.format(days=days_str)
            final_text = escape_markdown(full_text).replace(days_str, f'*{days_str}*')
            lines.append(final_text)
    
    lines.append(separator)
    lines.append(f'⚠️ {escape_markdown(get_string("fmt_birthday_note", lang_code))}')

    return "\n".join(lines)

def fmt_user_usage_history(history: list, user_name: str, lang_code: str) -> str:
    """تاریخچه مصرف کاربر را به صورت یک لیست متنی خوانا قالب‌بندی می‌کند."""
    title = f'*{escape_markdown(get_string("usage_history_title", lang_code).format(name=user_name))}*'
    
    if not any(item['total_usage'] > 0 for item in history):
        return f'{title}\n\n{escape_markdown(get_string("usage_history_no_data", lang_code))}'

    lines = [title]
    for item in history:
        date_shamsi = to_shamsi(item['date'])
        usage_formatted = format_daily_usage(item['total_usage'])
        lines.append(f"`{date_shamsi}`: *{escape_markdown(usage_formatted)}*")
        
    return "\n".join(lines)

def fmt_inline_result(info: dict) -> tuple[str, str]:
    """Formats user info for an inline query result with detailed breakdown and spacing."""
    if not info:
        return ("❌ اطلاعات کاربر یافت نشد.", None)

    from .utils import escape_markdown, create_progress_bar, format_daily_usage, parse_user_agent
    from .database import db

    # --- 1. آماده‌سازی داده‌های اولیه ---
    name = escape_markdown(info.get("name", "کاربر ناشناس"))
    status = "✅" if info.get("is_active") else "❌"
    user_uuid = info.get("uuid", "")
    uuid_escaped = escape_markdown(user_uuid)

    # --- 2. آمار کلی ---
    total_limit_gb = info.get("usage_limit_GB", 0)
    total_usage_gb = info.get("current_usage_GB", 0)
    total_remaining_gb = max(0, total_limit_gb - total_usage_gb)
    usage_percentage = info.get("usage_percentage", 0)
    expire_days = info.get("expire")
    expire_text = "نامحدود" if expire_days is None else (f"{expire_days} روز" if expire_days >= 0 else "منقضی شده")
    expire_text = escape_markdown(expire_text)

    # --- 3. مصرف روزانه (کلی و تفکیک شده) ---
    daily_usage_dict = {'hiddify': 0.0, 'marzban': 0.0}
    if user_uuid:
        daily_usage_dict = db.get_usage_since_midnight_by_uuid(user_uuid)
    total_daily_usage_gb = sum(daily_usage_dict.values())
    total_daily_usage_str = escape_markdown(format_daily_usage(total_daily_usage_gb))

    # --- 4. استخراج اطلاعات زنده پنل‌ها ---
    breakdown = info.get('breakdown', {})
    hiddify_info = next((p['data'] for p in breakdown.values() if p.get('type') == 'hiddify'), None)
    marzban_info = next((p['data'] for p in breakdown.values() if p.get('type') == 'marzban'), None)

    # --- 5. ساخت متن سرورها و VIP بر اساس اطلاعات زنده و دیتابیس ---
    access_text = ""
    vip_text = ""
    has_access_fr, has_access_tr = False, False
    if user_uuid:
        user_record = db.get_user_uuid_record(user_uuid)
        if user_record:
            if user_record.get('is_vip'):
                vip_text = " کاربر ویژه : ✅"
            has_access_fr = user_record.get('has_access_fr', False)
            has_access_tr = user_record.get('has_access_tr', False)
    
    access_flags = []
    if hiddify_info: 
        access_flags.append("🇩🇪")
    if marzban_info:
        if has_access_fr: access_flags.append("🇫🇷")
        if has_access_tr: access_flags.append("🇹🇷")
    
    if access_flags:
        access_text = f" سرورها : {''.join(access_flags)}"

    # --- 6. ساخت پیام نهایی ---
    lines = [
        f"📊 *آمار کاربر : {name}*",
        f"`──────────────────`",
        f" وضعیت : *{status}*",
    ]

    if vip_text: lines.append(vip_text)
    if access_text: lines.append(access_text)
    
    lines.append(f"📅 انقضا : *{expire_text}*")
    lines.append("")

    # --- 7. منطق تفکیک اطلاعات بر اساس سرور ---
    marzban_flags = []
    if has_access_fr: marzban_flags.append("🇫🇷")
    if has_access_tr: marzban_flags.append("🇹🇷")
    marzban_flag_str = "".join(marzban_flags)

    # A. حجم کل
    lines.append(f"📦 حجم کل : *{escape_markdown(f'{total_limit_gb:.2f}')} GB*")
    if hiddify_info:
        limit = hiddify_info.get('usage_limit_GB', 0)
        lines.append(f"  🇩🇪 {escape_markdown(f'{limit:.2f} GB')}")
    if marzban_info and marzban_flag_str:
        limit = marzban_info.get('usage_limit_GB', 0)
        lines.append(f"  {marzban_flag_str} {escape_markdown(f'{limit:.2f} GB')}")

    # B. مجموع مصرف شده
    lines.append(f"🔥 مجموع مصرف شده: *{escape_markdown(f'{total_usage_gb:.2f}')} GB*")
    if hiddify_info:
        usage = hiddify_info.get('current_usage_GB', 0)
        lines.append(f"  🇩🇪 {escape_markdown(f'{usage:.2f} GB')}")
    if marzban_info and marzban_flag_str:
        usage = marzban_info.get('current_usage_GB', 0)
        lines.append(f"  {marzban_flag_str} {escape_markdown(f'{usage:.2f} GB')}")

    # C. مجموع باقیمانده
    lines.append(f"📥 مجموع باقیمانده: *{escape_markdown(f'{total_remaining_gb:.2f}')} GB*")
    if hiddify_info:
        remaining = hiddify_info.get('remaining_GB', 0)
        lines.append(f"  🇩🇪 {escape_markdown(f'{remaining:.2f} GB')}")
    if marzban_info and marzban_flag_str:
        remaining = marzban_info.get('remaining_GB', 0)
        lines.append(f"  {marzban_flag_str} {escape_markdown(f'{remaining:.2f} GB')}")

    # D. مصرف امروز
    lines.append(f"⚡️ مصرف امروز : *{total_daily_usage_str}*")
    if (hiddify_info and daily_usage_dict.get('hiddify', 0) > 0.001) or \
       (marzban_info and daily_usage_dict.get('marzban', 0) > 0.001 and marzban_flag_str):
        if hiddify_info and daily_usage_dict.get('hiddify', 0) > 0.001:
            daily = daily_usage_dict['hiddify']
            lines.append(f"  🇩🇪 {escape_markdown(format_daily_usage(daily))}")
        if marzban_info and daily_usage_dict.get('marzban', 0) > 0.001 and marzban_flag_str:
            daily = daily_usage_dict['marzban']
            lines.append(f"  {marzban_flag_str} {escape_markdown(format_daily_usage(daily))}")
    
        uuid_id = db.get_uuid_id_by_uuid(user_uuid)
        if uuid_id:
            user_agents = db.get_user_agents_for_uuid(uuid_id)
            if user_agents:
                lines.append("📱 *دستگاه‌های متصل:*")
                for agent in user_agents[:]: # Show max 6 devices
                    parsed = parse_user_agent(agent['user_agent'])
                    if parsed:
                        client_name = escape_markdown(parsed.get('client', 'Unknown'))
                        details = []
                        if parsed.get('version'):
                            details.append(f"v{escape_markdown(parsed['version'])}")
                        if parsed.get('os'):
                            details.append(escape_markdown(parsed['os']))
                        details_str = f" \\({', '.join(details)}\\)" if details else ""
                        lines.append(f"` `└─ *{client_name}*{details_str}")
                lines.append("")


    # --- 8. بخش پایانی ---
    lines.append(create_progress_bar(usage_percentage))
    lines.append(f"`{uuid_escaped}`")

    final_text = "\n".join(lines)
    return final_text, "MarkdownV2"

def fmt_smart_list_inline_result(users: list, title: str) -> tuple[str, str]:
    """Formats a smart list of users for an inline query result."""
    from .utils import escape_markdown
    
    title_escaped = escape_markdown(title)
    lines = [f"📊 *{title_escaped}*"]

    if not users:
        lines.append("\n_موردی یافت نشد._")
        return "\n".join(lines), "MarkdownV2"

    for user in users:
        name = escape_markdown(user.get('name', 'کاربر ناشناس'))
        expire_days = user.get('expire')
        usage_gb = user.get('current_usage_GB', 0)
        
        details = []
        if expire_days is not None:
            expire_str = f"{expire_days} day" if expire_days >= 0 else "expired"
            details.append(f"📅 {expire_str}")
            
        details.append(f"📥 {usage_gb:.2f} GB")

        lines.append(f"`•` *{name}* \\({escape_markdown(' | '.join(details))}\\)")
    
    return "\n".join(lines), "MarkdownV2"

def fmt_referral_page(user_id: int, bot_username: str, lang_code: str) -> str:
    from .config import REFERRAL_REWARD_GB, REFERRAL_REWARD_DAYS
    
    referral_code = db.get_or_create_referral_code(user_id)
    referral_link = f"https://t.me/{bot_username}?start={referral_code}"
    
    referred_users = db.get_referred_users(user_id)
    successful_referrals = [u for u in referred_users if u['referral_reward_applied']]
    pending_referrals = [u for u in referred_users if not u['referral_reward_applied']]

    unit_person = get_string('unit_person', lang_code)
    successful_count_str = f"*{len(successful_referrals)} {escape_markdown(unit_person)}*"
    pending_count_str = f"*{len(pending_referrals)} {escape_markdown(unit_person)}*"

    lines = [
        f"*{escape_markdown(get_string('referral_page_title', lang_code))}*",
        "`──────────────────`",
        escape_markdown(get_string('referral_intro', lang_code).format(gb=REFERRAL_REWARD_GB, days=REFERRAL_REWARD_DAYS)),
        "\n",
        f"🔗 *{escape_markdown(get_string('referral_link_title', lang_code))}*",
        f"`{escape_markdown(referral_link)}`",
        "\n",
        f"🏆 *{escape_markdown(get_string('referral_status_title', lang_code))}*",
        f" {get_string('referral_successful_count', lang_code)} {successful_count_str}",
        f" {get_string('referral_pending_count', lang_code)} {pending_count_str}"
    ]

    if successful_referrals:
        lines.append(f"\n✅ *{escape_markdown(get_string('referral_successful_list_title', lang_code))}*")
        for user in successful_referrals:
            lines.append(f" `•` {escape_markdown(user['first_name'])}")
            
    if pending_referrals:
        lines.append(f"\n⏳ *{escape_markdown(get_string('referral_pending_list_title', lang_code))}*")
        for user in pending_referrals:
            lines.append(f" `•` {escape_markdown(user['first_name'])}")

    return "\n".join(lines)

def fmt_user_account_page(user_id: int, lang_code: str) -> str:
    """اطلاعات شخصی‌سازی شده حساب کاربری را برای نمایش در ربات فرمت‌بندی می‌کند."""
    user_info = db.user(user_id)
    user_uuids = db.uuids(user_id)

    if not user_info or not user_uuids:
        return get_string("err_acc_not_found", lang_code)

    first_uuid_record = user_uuids[0]

    # دریافت اطلاعات
    referrals_count = len(db.get_referred_users(user_id))
    payments_count = len(db.get_user_payment_history(first_uuid_record['id']))
    user_group = get_string("group_vip", lang_code) if first_uuid_record.get('is_vip') else get_string("group_normal", lang_code)
    registration_date = to_shamsi(first_uuid_record.get('created_at'), include_time=False)

    # ساخت متن نهایی
    lines = [
        f"*{escape_markdown(get_string('user_account_page_title', lang_code))}*",
        "`──────────────────`",
        f"*{escape_markdown(get_string('personal_info_title', lang_code))}*",
        f"`•` {escape_markdown(get_string('label_name', lang_code))}: *{escape_markdown(user_info.get('first_name', ''))}*",
        f"`•` {escape_markdown(get_string('label_user_id', lang_code))}: `{user_id}`",
        f"`•` {escape_markdown(get_string('label_referral_code', lang_code))}: `{escape_markdown(user_info.get('referral_code', 'N/A'))}`",
        f"`•` {escape_markdown(get_string('label_registration_date', lang_code))}: *{escape_markdown(registration_date)}*",
        f"`•` {escape_markdown(get_string('label_user_group', lang_code))}: *{escape_markdown(user_group)}*",
        "",
        f"*{escape_markdown(get_string('account_stats_title', lang_code))}*",
        f"`•` {escape_markdown(get_string('label_services_purchased', lang_code))}: *{len(user_uuids)} {escape_markdown(get_string('unit_count', lang_code))}*",
        f"`•` {escape_markdown(get_string('label_paid_invoices', lang_code))}: *{payments_count} {escape_markdown(get_string('unit_count', lang_code))}*",
        f"`•` {escape_markdown(get_string('label_referrals', lang_code))}: *{referrals_count} {escape_markdown(get_string('unit_person', lang_code))}*",
    ]
    
    return "\n".join(lines)


def fmt_purchase_summary(info_before: dict, info_after: dict, plan_to_buy: dict, lang_code: str) -> str:
    """یک خلاصه متنی مدرن برای نمایش وضعیت سرویس قبل و بعد از خرید ایجاد می‌کند."""

    limit_before = info_before.get('usage_limit_GB', 0)
    expire_before = info_before.get('expire', 0) if info_before.get('expire') is not None else '∞'
    limit_after = info_after.get('usage_limit_GB', 0)
    expire_after = info_after.get('expire', 0) if info_after.get('expire') is not None else '∞'

    from .utils import parse_volume_string
    days_added = parse_volume_string(plan_to_buy.get('duration', '0'))
    
    gb_added = 0
    plan_type = plan_to_buy.get('type')
    if plan_type == 'combined':
        gb_added = parse_volume_string(plan_to_buy.get('total_volume', '0'))
    else:
        volume_key = 'volume_de' if plan_type == 'germany' else 'volume_fr' if plan_type == 'france' else 'volume_tr'
        gb_added = parse_volume_string(plan_to_buy.get(volume_key, '0'))

    
    header_text = escape_markdown("سرویس شما با موفقیت شارژ شد.\n")
    details_header = escape_markdown("\nجزئیات تغییرات:")
    separator = "`──────────────────`"
    
    gb_added_text = escape_markdown(f"+{gb_added:g} GB")
    volume_line = f"📊 {limit_before:g} GB ➡️ {limit_after:g} GB \\({gb_added_text}\\)"
    
    days_added_text = escape_markdown(f"+{days_added} day")
    days_line = f"📅 {expire_before} ➡️ {expire_after} \\({days_added_text}\\)"

    lines = [header_text, details_header, separator, volume_line, days_line]
    return "\n".join(lines)