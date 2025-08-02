import logging
from .config import EMOJIS
from .settings_manager import settings
from .database import db
from . import combined_handler
from .language import get_string
from .utils import (
    create_progress_bar,
    format_daily_usage, escape_markdown,
    to_shamsi, days_until_next_birthday
)

logger = logging.getLogger(__name__)


def fmt_one(info: dict, daily_usage_dict: dict, lang_code: str) -> str:
    """Formats the detailed information for a single user account."""
    if not info:
        return escape_markdown(get_string("fmt_err_getting_info", lang_code))

    name = escape_markdown(info.get("name", get_string('unknown_user', lang_code)))
    status_emoji = "🟢" if info.get("is_active") else "🔴"
    status_text = get_string("fmt_status_active", lang_code) if info.get("is_active") else get_string("fmt_status_inactive", lang_code)

    expire_days = info.get("expire")
    expire_label = get_string("fmt_expire_unlimited", lang_code)
    if expire_days is not None:
        expire_label = get_string("fmt_expire_days", lang_code).format(days=expire_days)

    uuid = escape_markdown(info.get('uuid', ''))
    bar = create_progress_bar(info.get("usage_percentage", 0))
    header_content = get_string("fmt_user_info_header", lang_code).format(name=name, status_emoji=status_emoji, status_text=status_text)
    name_line = f"*{escape_markdown(header_content)}*"
    
    report = [name_line]

    h_info = info.get('breakdown', {}).get('hiddify', {})
    m_info = info.get('breakdown', {}).get('marzban', {})

    if h_info and m_info:
        total_limit_gb = f"{info.get('usage_limit_GB', 0):.2f} GB"
        total_usage_gb = f"{info.get('current_usage_GB', 0):.2f} GB"
        total_remaining_gb = f"{info.get('remaining_GB', 0):.2f} GB"
        total_daily_gb_str = format_daily_usage(sum(daily_usage_dict.values()))
        report.extend([
            "",
            f'*{get_string("fmt_total_volume", lang_code).format(volume=f"`{total_limit_gb}`")}*',
            f'*{get_string("fmt_total_usage", lang_code).format(usage=f"`{total_usage_gb}`")}*',
            f'*{get_string("fmt_total_remaining", lang_code).format(remaining=f"`{total_remaining_gb}`")}*',
            f'*{get_string("fmt_total_daily_usage", lang_code).format(usage=f"`{total_daily_gb_str}`")}*',
        ])

    if h_info or m_info:
        report.append(f"\n*{get_string('fmt_server_details_header', lang_code)}*")
    
    def format_panel_details(panel_info, daily_usage, server_name_key):
        limit_str = f"`{panel_info.get('usage_limit_GB', 0.0):.2f} GB`"
        usage_str = f"`{panel_info.get('current_usage_GB', 0.0):.2f} GB`"
        daily_str = f"`{format_daily_usage(daily_usage)}`"
        last_online = f"`{to_shamsi(panel_info.get('last_online'), include_time=True)}`"
        return [
            "",
            get_string(server_name_key, lang_code),
            get_string("fmt_server_volume", lang_code).format(volume=limit_str),
            get_string("fmt_server_usage", lang_code).format(usage=usage_str),
            get_string("fmt_server_daily_usage", lang_code).format(usage=daily_str),
            get_string("fmt_server_last_online", lang_code).format(time=last_online),
        ]

    if h_info:
        report.extend(format_panel_details(h_info, daily_usage_dict.get('hiddify', 0.0), 'server_de'))
    if m_info:
        report.extend(format_panel_details(m_info, daily_usage_dict.get('marzban', 0.0), 'server_fr'))

    report.extend([
        "",
        f'*{get_string("fmt_expiry_date", lang_code).format(date=escape_markdown(expire_label))}*',
        get_string("fmt_uuid", lang_code).format(uuid=f"`{uuid}`"),
        "",
        get_string("fmt_status_bar", lang_code).format(bar=bar)
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
    report_text = fmt_one(info, daily_usage_dict, lang_code)
    
    return report_text, menu_data


def fmt_user_report(user_infos: list, lang_code: str) -> str:
    if not user_infos:
        return ""

    accounts_reports = []
    total_daily_usage_all_accounts = 0.0

    for info in user_infos:
        name = escape_markdown(info.get("name", get_string("unknown_user", lang_code)))
        header = f'*{get_string("fmt_report_account_header", lang_code).format(name=name)}*'
        account_lines = [header]
        
        daily_usage_dict = db.get_usage_since_midnight(info['db_id'])
        total_daily_usage_all_accounts += sum(daily_usage_dict.values())
        
        h_info = info.get('breakdown', {}).get('hiddify', {})
        m_info = info.get('breakdown', {}).get('marzban', {})

        panel_info = h_info or m_info
        if panel_info:
            account_lines.append(get_string("fmt_report_total_volume", lang_code).format(volume=escape_markdown(f'{panel_info.get("usage_limit_GB", 0):.2f} GB')))
            account_lines.append(get_string("fmt_report_used_volume", lang_code).format(usage=escape_markdown(f'{panel_info.get("current_usage_GB", 0):.2f} GB')))
            account_lines.append(get_string("fmt_report_remaining_volume", lang_code).format(remaining=escape_markdown(f'{max(0, panel_info.get("usage_limit_GB", 0) - panel_info.get("current_usage_GB", 0)):.2f} GB')))
        
        account_lines.append(get_string("fmt_report_daily_usage_header", lang_code))
        if h_info:
            account_lines.append(f" 🇩🇪 : {escape_markdown(format_daily_usage(daily_usage_dict.get('hiddify', 0.0)))}")
        if m_info:
            account_lines.append(f" 🇫🇷 : {escape_markdown(format_daily_usage(daily_usage_dict.get('marzban', 0.0)))}")

        expire_days = info.get("expire")
        expire_str = f"`{get_string('fmt_expire_unlimited', lang_code)}`"
        if expire_days is not None:
            expire_word = get_string('expire_summary', lang_code).split(' ')[-1] # Gets "Days" or "روز"
            expire_str = f"{expire_days} {expire_word}" if expire_days >= 0 else get_string("fmt_status_expired", lang_code)
        
        account_lines.append(get_string("fmt_report_expiry", lang_code).format(expiry=escape_markdown(expire_str)))
        accounts_reports.append("\n".join(account_lines))
    
    final_report = "\n\n".join(accounts_reports)

    footer_key = "fmt_report_footer_total_multi" if len(user_infos) > 1 else "fmt_report_footer_total_single"
    usage_str = escape_markdown(format_daily_usage(total_daily_usage_all_accounts))
    footer_text = f'*{get_string(footer_key, lang_code).format(usage=usage_str)}*'
    
    final_report += f"\n\n {footer_text}"
    return final_report

def fmt_service_plans(plans_to_show: list, plan_type: str, lang_code: str) -> str:
    if not plans_to_show:
        return escape_markdown(get_string("fmt_plans_none_in_category", lang_code))
    
    type_map = { "combined": "fmt_plan_type_combined", "germany": "fmt_plan_type_germany", "france": "fmt_plan_type_france" }
    type_title = get_string(type_map.get(plan_type, "fmt_plan_type_general"), lang_code)
    
    title = f'*{escape_markdown(get_string("fmt_plans_title", lang_code).format(type_title=type_title))}*'
    lines = [title]
    
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
    title_str = get_string('fmt_panel_stats_title', lang_code).format(panel_name=panel_name)
    title = f"*{escape_markdown(title_str)}*"
    
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
    title_str = title_template.format(action=title_action, user_name=escape_markdown(user_name))
    
    header_text = f"*{escape_markdown(title_str)}*"

    if not payments:
        no_info_text = escape_markdown(get_string('fmt_payment_history_no_info', lang_code))
        return f"{header_text}\n\n{no_info_text}"

    page_size = settings.get('PAGE_SIZE', 15)
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