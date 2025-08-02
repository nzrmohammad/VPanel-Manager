import pytz
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from .config import EMOJIS
from .settings_manager import settings
from .database import db
from .utils import (
    format_daily_usage, escape_markdown,
    format_relative_time, validate_uuid, create_progress_bar, to_shamsi, days_until_next_birthday
)


def fmt_users_list(users: list, list_type: str, page: int) -> str:
    title_map = {
        'active': "✅ کاربران فعال (۲۴ ساعت اخیر)",
        'inactive': "⏳ کاربران غیرفعال (۱ تا ۷ روز)",
        'never_connected': "🚫 کاربرانی که هرگز متصل نشده‌اند"
    }
    title = title_map.get(list_type, "لیست کاربران")

    if not users:
        return f"*{escape_markdown(title)}*\n\nهیچ کاربری در این دسته یافت نشد."

    header_text = f"*{escape_markdown(title)}*"
    if len(users) > settings.get('PAGE_SIZE', 15):
        total_pages = (len(users) + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        pagination_text = f"(صفحه {page + 1} از {total_pages} | کل: {len(users)})"
        header_text += f"\n{escape_markdown(pagination_text)}"

    lines = [header_text]

    start_index = page * settings.get('PAGE_SIZE', 15)
    paginated_users = users[start_index : start_index + settings.get('PAGE_SIZE', 15)]

    for user in paginated_users:
        name = escape_markdown(user.get('name', 'کاربر ناشناس'))
        line = f"`•` *{name}*"
        separator = escape_markdown(" | ")

        if list_type == 'active':
            last_online_str = to_shamsi(user.get('last_online')).split(' ')[-1]
            usage_p = user.get('usage_percentage', 0)
            line += f"{separator}Last Seen: `{escape_markdown(last_online_str)}`{separator}Usage: `{usage_p:.1f}\\%`"

        elif list_type == 'inactive':
            last_online_str = format_relative_time(user.get('last_online'))
            status = "Expired" if user.get('expire', 0) < 0 else "Active"
            line += f"{separator}Last Seen: `{escape_markdown(last_online_str)}`{separator}Status: `{status}`"

        elif list_type == 'never_connected':
            created_at_str = format_relative_time(user.get('created_at'))
            limit_gb = user.get('usage_limit_GB', 0)
            line += f"{separator}Registered: `{escape_markdown(created_at_str)}`{separator}Limit: `{limit_gb} GB`"

        lines.append(line)

    return "\n".join(lines)

def fmt_online_users_list(users: list, page: int) -> str:
    title = "⚡️ کاربران آنلاین (۳ دقیقه اخیر)" 

    if not users:
        return f"*{escape_markdown(title)}*\n\nهیچ کاربری در این لحظه آنلاین نیست\\."

    header_text = f"*{escape_markdown(title)}*"
    if len(users) > settings.get('PAGE_SIZE', 15):
        total_pages = (len(users) + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        pagination_text = f"\\(صفحه {page + 1} از {total_pages} \\| کل: {len(users)}\\)"
        header_text += f"\n{pagination_text}"

    paginated_users = users[page * settings.get('PAGE_SIZE', 15) : (page + 1) * settings.get('PAGE_SIZE', 15)]
    user_lines = []
    separator = escape_markdown(" | ")

    uuid_to_bot_user = db.get_uuid_to_bot_user_map()

    for user in paginated_users:
        panel_name_raw = user.get('name', 'کاربر ناشناس')
        bot_user_info = uuid_to_bot_user.get(user.get('uuid'))

        clean_name = panel_name_raw.replace('[', '').replace(']', '')
        name_str = escape_markdown(clean_name)
        if bot_user_info and bot_user_info.get('user_id'):
            user_id = bot_user_info['user_id']
            name_str = f"[{clean_name}](tg://user?id={user_id})"

        daily_usage_output = escape_markdown(format_daily_usage(user.get('daily_usage_GB', 0)))
        expire_days = user.get("expire")
        expire_text = "Unlimited"
        if expire_days is not None:
            expire_text = f"{expire_days} Days" if expire_days >= 0 else "Expired"
        expire_output = escape_markdown(expire_text)

        line = f"{name_str}{separator}`{daily_usage_output}`{separator}`{expire_output}`"
        user_lines.append(line)

    body_text = "\n".join(user_lines)
    return f"{header_text}\n\n{body_text}"

# file: admin_formatters.py

def fmt_admin_report(all_users_from_api: list, db_manager) -> str:
    if not all_users_from_api:
        return "هیچ کاربری در پنل یافت نشد"

    # --- Data Calculation ---
    active_users = 0
    active_hiddify_users, active_marzban_users = 0, 0
    total_daily_hiddify, total_daily_marzban = 0.0, 0.0
    online_users, expiring_soon_users, new_users_today, expired_recently_users = [], [], [], []
    hiddify_user_count, marzban_user_count = 0, 0

    now_utc = datetime.now(pytz.utc)
    online_deadline = now_utc - timedelta(minutes=3)

    db_users_map = {u['uuid']: u.get('created_at') for u in db_manager.all_active_uuids()}

    for user_info in all_users_from_api:
        breakdown = user_info.get('breakdown', {})
        is_on_hiddify = 'hiddify' in breakdown and breakdown['hiddify']
        is_on_marzban = 'marzban' in breakdown and breakdown['marzban']
        if is_on_hiddify:
            hiddify_user_count += 1
        if is_on_marzban:
            marzban_user_count += 1

        if user_info.get("is_active"):
            active_users += 1
            if is_on_hiddify: active_hiddify_users += 1
            if is_on_marzban: active_marzban_users += 1

        if user_info.get('uuid'):
            daily_usage_dict = db_manager.get_usage_since_midnight_by_uuid(user_info['uuid'])
            total_daily_hiddify += daily_usage_dict.get('hiddify', 0.0)
            total_daily_marzban += daily_usage_dict.get('marzban', 0.0)
        else:
            daily_usage_dict = {}

        if user_info.get('is_active') and user_info.get('last_online') and isinstance(user_info.get('last_online'), datetime) and user_info['last_online'].astimezone(pytz.utc) >= online_deadline:
            user_info['daily_usage_dict'] = daily_usage_dict
            online_users.append(user_info)

        expire_days = user_info.get('expire')
        if expire_days is not None:
            if 0 <= expire_days <= 3:
                expiring_soon_users.append(user_info)
            elif -2 <= expire_days < 0:
                expired_recently_users.append(user_info)


        created_at = db_users_map.get(user_info.get('uuid'))
        if created_at and isinstance(created_at, datetime) and (now_utc - created_at.astimezone(pytz.utc)).days < 1:
            new_users_today.append(user_info)

    total_daily_all = total_daily_hiddify + total_daily_marzban
    list_bullet = escape_markdown("- ")
    
    # --- Report Formatting ---
    report_lines = [
        f"{EMOJIS['gear']} *{escape_markdown('خلاصه وضعیت کل پنل')}*",
        f"{list_bullet}{EMOJIS['user']} تعداد کل اکانت‌ها : *{len(all_users_from_api)}*",
        f"{list_bullet} 🇩🇪 : *{hiddify_user_count}* {escape_markdown('|')} 🇫🇷 : *{marzban_user_count}*",
        f"{list_bullet}{EMOJIS['success']} اکانت‌های فعال : *{active_users}*",
        f"{list_bullet} 🇩🇪 : *{active_hiddify_users}* {escape_markdown('|')} 🇫🇷 : *{active_marzban_users}*",
        f"{list_bullet}{EMOJIS['wifi']} کاربران آنلاین : *{len(online_users)}*",
        f"{list_bullet}{EMOJIS['lightning']} *مصرف کل امروز :* `{escape_markdown(format_daily_usage(total_daily_all))}`",
        f"{list_bullet} 🇩🇪 : `{escape_markdown(format_daily_usage(total_daily_hiddify))}`",
        f"{list_bullet} 🇫🇷 : `{escape_markdown(format_daily_usage(total_daily_marzban))}`"
    ]

    if online_users:
        report_lines.append("\n" + "─" * 15 + f"\n*{EMOJIS['wifi']} {escape_markdown('کاربران آنلاین و مصرف امروزشان')}*")
        online_users.sort(key=lambda u: u.get('name', ''))
        for user in online_users:
            user_name = escape_markdown(user.get('name', 'کاربر ناشناس'))
            daily_dict = user.get('daily_usage_dict', {})
            
            usage_parts = []
            breakdown = user.get('breakdown', {})
            if 'hiddify' in breakdown and breakdown['hiddify']:
                h_daily_str = escape_markdown(format_daily_usage(daily_dict.get('hiddify', 0.0)))
                usage_parts.append(f"🇩🇪 `{h_daily_str}`")
            if 'marzban' in breakdown and breakdown['marzban']:
                m_daily_str = escape_markdown(format_daily_usage(daily_dict.get('marzban', 0.0)))
                usage_parts.append(f"🇫🇷 `{m_daily_str}`")
            
            usage_str = escape_markdown(" | ").join(usage_parts)
            report_lines.append(f"`•` *{user_name} :* {usage_str}")

    if expiring_soon_users:
        report_lines.append("\n" + "─" * 15 + f"\n*{EMOJIS['warning']} {escape_markdown('کاربرانی که تا ۳ روز آینده منقضی می شوند')}*")
        expiring_soon_users.sort(key=lambda u: u.get('expire', 99))
        for user in expiring_soon_users:
            name = escape_markdown(user['name'])
            days = user['expire']
            report_lines.append(f"`•` *{name} :* {days} روز")

    if expired_recently_users:
        report_lines.append("\n" + "─" * 15 + f"\n*{EMOJIS['error']} {escape_markdown('کاربران منقضی (۴۸ ساعت اخیر)')}*")
        expired_recently_users.sort(key=lambda u: u.get('name', ''))
        for user in expired_recently_users:
            name = escape_markdown(user['name'])
            report_lines.append(f"`•` *{name}*")

    if new_users_today:
        report_lines.append("\n" + "─" * 15 + f"\n*{EMOJIS['star']} {escape_markdown('کاربران جدید (۲۴ ساعت اخیر):')}*")
        for user in new_users_today:
            name = escape_markdown(user['name'])
            report_lines.append(f"`•` *{name}*")

    return "\n".join(report_lines)

def fmt_hiddify_panel_info(info: dict) -> str:
    if not info:
        return escape_markdown("اطلاعاتی از پنل دریافت نشد.")

    title = escape_markdown(info.get('title', 'N/A'))
    description = escape_markdown(info.get('description', 'N/A'))
    version = escape_markdown(info.get('version', 'N/A'))

    return (f"{EMOJIS['gear']} *اطلاعات پنل Hiddify*\n\n"
            f"**عنوان:** {title}\n"
            f"**توضیحات:** {description}\n"
            f"**نسخه:** {version}\n")

def fmt_top_consumers(users: list, page: int) -> str:
    title = "پرمصرف‌ترین کاربران"
    if not users:
        return f"🏆 *{escape_markdown(title)}*\n\nهیچ کاربری برای نمایش وجود ندارد."

    header_text = f"🏆 *{escape_markdown(title)}*"
    if len(users) > settings.get('PAGE_SIZE', 15):
        total_pages = (len(users) + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        pagination_text = f"(صفحه {page + 1} از {total_pages} | کل: {len(users)})"
        header_text += f"\n{escape_markdown(pagination_text)}"

    lines = [header_text]
    paginated_users = users[page * settings.get('PAGE_SIZE', 15) : (page + 1) * settings.get('PAGE_SIZE', 15)]
    separator = escape_markdown(" | ")

    for i, user in enumerate(paginated_users, start=page * settings.get('PAGE_SIZE', 15) + 1):
        name = escape_markdown(user.get('name', 'کاربر ناشناس'))
        usage = user.get('current_usage_GB', 0)
        limit = user.get('usage_limit_GB', 0)
        usage_str = f"`{usage:.2f} GB / {limit:.2f} GB`"
        line = f"`{i}.` *{name}*{separator}{EMOJIS['chart']} {usage_str}"
        lines.append(line)

    return "\n".join(lines)

def fmt_bot_users_list(bot_users: list, page: int) -> str:
    title = "کاربران ربات"
    if not bot_users:
        return f"🤖 *{escape_markdown(title)}*\n\nهیچ کاربری در ربات ثبت‌نام نکرده است."

    header_text = f"🤖 *{escape_markdown(title)}*"
    total_users = len(bot_users)
    if total_users > settings.get('PAGE_SIZE', 15):
        total_pages = (total_users + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        pagination_text = f"(صفحه {page + 1} از {total_pages} | کل: {total_users})"
        header_text += f"\n{escape_markdown(pagination_text)}"

    lines = [header_text]
    start_index = page * settings.get('PAGE_SIZE', 15)
    paginated_users = bot_users[start_index : start_index + settings.get('PAGE_SIZE', 15)]

    for user in paginated_users:
        user_id = user.get('user_id')
        first_name = escape_markdown(user.get('first_name') or 'ناشناس')
        username = escape_markdown(f"(@{user.get('username')})" if user.get('username') else '')
        lines.append(f"`•` {first_name} {username} `| ID:` `{user_id}`")

    return "\n".join(lines)

def fmt_birthdays_list(users: list, page: int) -> str:
    title = "لیست تولد کاربران"
    if not users:
        return f"🎂 *{escape_markdown(title)}*\n\nهیچ کاربری تاریخ تولد خود را ثبت نکرده است."

    title_text = f"{title} (مرتب شده بر اساس ماه)"
    header_text = f"🎂 *{escape_markdown(title_text)}*"

    if len(users) > settings.get('PAGE_SIZE', 15):
        total_pages = (len(users) + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        pagination_text = escape_markdown(f"(صفحه {page + 1} از {total_pages} | کل: {len(users)})")
        header_text += f"\n{pagination_text}"

    lines = [header_text]
    start_index = page * settings.get('PAGE_SIZE', 15)
    paginated_users = users[start_index : start_index + settings.get('PAGE_SIZE', 15)]
    separator = escape_markdown(" | ")

    for user in paginated_users:
        name = escape_markdown(user.get('first_name', 'کاربر ناشناس'))
        birthday_obj = user.get('birthday')

        shamsi_str = to_shamsi(birthday_obj)

        remaining_days = days_until_next_birthday(birthday_obj)
        days_str = f"{remaining_days} روز" if remaining_days is not None else "نامشخص"

        lines.append(f"🎂 *{name}*{separator}`{shamsi_str}`{separator}{escape_markdown(days_str)}")

    return "\n".join(lines)

def fmt_marzban_system_stats(info: dict) -> str:
    if not info:
        return escape_markdown("اطلاعاتی از سیستم دریافت نشد.")

    to_gb = lambda b: b / (1024**3)
    
    # تغيير: تمام متغیرها قبل از استفاده escape شدند
    version = escape_markdown(info.get('version', 'N/A'))
    mem_total_gb = escape_markdown(f"{to_gb(info.get('mem_total', 0)):.2f}")
    mem_used_gb = escape_markdown(f"{to_gb(info.get('mem_used', 0)):.2f}")
    mem_percent = (info.get('mem_used', 0) / info.get('mem_total', 1) * 100)
    mem_percent_str = escape_markdown(f"{mem_percent:.1f}")
    cpu_cores = escape_markdown(info.get('cpu_cores', 'N/A'))
    cpu_usage = escape_markdown(f"{info.get('cpu_usage', 0.0):.1f}")

    total_users = escape_markdown(info.get('total_user', 0))
    online_users = escape_markdown(info.get('online_users', 0))
    active_users = escape_markdown(info.get('users_active', 0))
    disabled_users = escape_markdown(info.get('users_disabled', 0))
    expired_users = escape_markdown(info.get('users_expired', 0))

    total_dl_gb = escape_markdown(f"{to_gb(info.get('incoming_bandwidth', 0)):.2f}")
    total_ul_gb = escape_markdown(f"{to_gb(info.get('outgoing_bandwidth', 0)):.2f}")
    speed_dl_mbps = escape_markdown(f"{info.get('incoming_bandwidth_speed', 0) / (1024 * 1024):.2f}")
    speed_ul_mbps = escape_markdown(f"{info.get('outgoing_bandwidth_speed', 0) / (1024 * 1024):.2f}")

    report = (
        f"*📊 وضعیت سیستم پنل مرزبان \\(فرانسه 🇫🇷\\)*\n"
        f"`────────────────────────────`\n"
        f"⚙️ نسخه: `{version}`\n"
        f"🖥️ هسته CPU: `{cpu_cores}` `|` مصرف: `{cpu_usage}\\%`\n"
        f"💾 مصرف RAM: `{mem_used_gb} / {mem_total_gb} GB` `({mem_percent_str}\\%)`\n"
        f"`────────────────────────────`\n"
        f"👥 کاربران کل: `{total_users}` {escape_markdown('|')} 🟢 فعال: `{active_users}` {escape_markdown('|')} 🔴 آنلاین: `{online_users}`\n"
        f"⚪️ غیرفعال: `{disabled_users}` {escape_markdown('|')} 🗓 منقضی شده: `{expired_users}`\n"
        f"`────────────────────────────`\n"
        f"*📈 ترافیک کل:*\n"
        f"  `↓` دانلود: `{total_dl_gb} GB`\n"
        f"  `↑` آپلود: `{total_ul_gb} GB`\n"
        f"*🚀 سرعت لحظه‌ای:*\n"
        f"  `↓` دانلود: `{speed_dl_mbps} MB/s`\n"
        f"  `↑` آپلود: `{speed_ul_mbps} MB/s`"
    )

    return report

def fmt_panel_users_list(users: list, panel_name: str, page: int) -> str:
    title = f"کاربران پنل {panel_name}"
    if not users:
        return f"*{escape_markdown(title)}*\n\nهیچ کاربری در این پنل یافت نشد."

    header_text = f"*{escape_markdown(title)}*"
    if len(users) > settings.get('PAGE_SIZE', 15):
        total_pages = (len(users) + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        pagination_text = f"(صفحه {page + 1} از {total_pages} | کل: {len(users)})"
        header_text += f"\n{escape_markdown(pagination_text)}"

    user_lines = []
    paginated_users = users[page * settings.get('PAGE_SIZE', 15) : (page + 1) * settings.get('PAGE_SIZE', 15)]
    separator = escape_markdown(" | ")

    for user in paginated_users:
        name = escape_markdown(user.get('name', 'کاربر ناشناس'))
        expire_days = user.get("expire")
        expire_text = "نامحدود"
        if expire_days is not None:
            expire_text = f"{expire_days} روز" if expire_days >= 0 else "منقضی"

        line = f"`•` *{name}*{separator}{EMOJIS['calendar']} {escape_markdown(expire_text)}"
        user_lines.append(line)

    body_text = "\n".join(user_lines)
    return f"{header_text}\n\n{body_text}"

def fmt_admin_user_summary(info: dict, db_user: Optional[dict] = None) -> str:
    if not info:
        return "❌ خطا در دریافت اطلاعات کاربر\\."

    name = escape_markdown(info.get("name", "کاربر ناشناس"))
    status_emoji = "🟢" if info.get("is_active") else "🔴"
    status_text = "فعال" if info.get("is_active") else "غیرفعال"
    # مشکل اینجا بود: پرانتزها باید escape می‌شدند
    name_line = f"👤 نام : {name} \\({status_emoji} {status_text}\\)"

    total_limit_gb = info.get('usage_limit_GB', 0)
    total_usage_gb = info.get('current_usage_GB', 0)

    h_info = info.get('breakdown', {}).get('hiddify')
    m_info = info.get('breakdown', {}).get('marzban')
    is_on_both_panels = h_info and m_info

    report_parts = [name_line, ""]

    if is_on_both_panels:
        total_remaining_gb = total_limit_gb - total_usage_gb
        daily_usage_total = info.get('daily_usage_GB', 0)

        report_parts.extend([
            f"🗂️ مجموع حجم : `{escape_markdown(f'{total_limit_gb:.2f}')} GB`",
            f"🔥 مجموع مصرف شده : `{escape_markdown(f'{total_usage_gb:.2f}')} GB`",
            f"📥 مجموع باقیمانده: `{escape_markdown(f'{total_remaining_gb:.2f}')} GB`",
            f"⚡️ مجموع مصرف امروز: `{escape_markdown(format_daily_usage(daily_usage_total))}`"
        ])

    if is_on_both_panels:
        report_parts.append("\n*جزئیات سرورها*")

    if h_info:
        h_daily_usage = h_info.get('daily_usage', 0.0)
        h_last_online_str = escape_markdown(to_shamsi(h_info.get('last_online')))

        report_parts.extend([
            "\nآلمان 🇩🇪",
            f"🗂️ حجم : `{escape_markdown(f'{h_info.get('usage_limit_GB', 0):.2f}')} GB`",
            f"🔥 مصرف شده : `{escape_markdown(f'{h_info.get('current_usage_GB', 0):.2f}')} GB`",
            f"⚡️ مصرف امروز : `{escape_markdown(format_daily_usage(h_daily_usage))}`",
            f"⏰ آخرین اتصال : `{h_last_online_str}`"
        ])

    if m_info:
        m_daily_usage = m_info.get('daily_usage', 0.0)
        m_last_online_str = escape_markdown(to_shamsi(m_info.get('last_online')))

        report_parts.extend([
            "\nفرانسه 🇫🇷",
            f"🗂️ حجم : `{escape_markdown(f'{m_info.get('usage_limit_GB', 0):.2f}')} GB`",
            f"🔥 مصرف شده : `{escape_markdown(f'{m_info.get('current_usage_GB', 0):.2f}')} GB`",
            f"⚡️ مصرف امروز : `{escape_markdown(format_daily_usage(m_daily_usage))}`",
            f"⏰ آخرین اتصال : `{m_last_online_str}`"
        ])

    report_parts.append("")

    expire_days = info.get("expire")
    expire_label = "نامحدود"
    if expire_days is not None:
        expire_label = f"{expire_days} روز" if expire_days >= 0 else "منقضی شده"
    report_parts.append(f"📅 انقضا: {escape_markdown(expire_label)}")

    if h_info:
        report_parts.append(f"🔑 شناسه یکتا: `{escape_markdown(info.get('uuid'))}`")
    elif m_info:
        report_parts.append(f"👤 یوزرنیم: `{escape_markdown(info.get('name'))}`")

    admin_note = db_user.get('admin_note') if db_user else None
    if admin_note:
        report_parts.append(f"📝 *یادداشت ادمین:* `{escape_markdown(admin_note)}`")

    usage_percentage = info.get('usage_percentage', 0)
    status_bar_line = create_progress_bar(usage_percentage)
    report_parts.append(f"\nوضعیت : {status_bar_line}")

    return "\n".join(report_parts)

def fmt_users_by_plan_list(users: list, plan_name: str, page: int) -> str:
    title = f"گزارش کاربران پلن: {escape_markdown(plan_name)}"

    if not users:
        return f"*{title}*\n\nهیچ کاربری با مشخصات این پلن یافت نشد."

    header_text = f"*{title}*"
    if len(users) > settings.get('PAGE_SIZE', 15):
        total_pages = (len(users) + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        pagination_text = f"(صفحه {page + 1} از {total_pages} | کل: {len(users)})"
        header_text += f"\n{escape_markdown(pagination_text)}"

    user_lines = [header_text]
    paginated_users = users[page * settings.get('PAGE_SIZE', 15) : (page + 1) * settings.get('PAGE_SIZE', 15)]

    for user in paginated_users:
        name = escape_markdown(user.get('name', 'کاربر ناشناس'))

        h_info = user.get('breakdown', {}).get('hiddify', {})
        m_info = user.get('breakdown', {}).get('marzban', {})

        h_usage_gb = h_info.get('current_usage_GB', 0.0)
        h_limit_gb = h_info.get('usage_limit_GB', 0.0)
        h_usage_str = escape_markdown(f"{h_usage_gb:.2f}")
        h_limit_str = escape_markdown(f"{h_limit_gb:.2f}")

        m_usage_gb = m_info.get('current_usage_GB', 0.0)
        m_limit_gb = m_info.get('usage_limit_GB', 0.0)
        m_usage_str = escape_markdown(f"{m_usage_gb:.2f}")
        m_limit_str = escape_markdown(f"{m_limit_gb:.2f}")

        line = f"`•` *{name}* `|` `{h_usage_str}/{h_limit_str} GB`  🇩🇪  `|`  `{m_usage_str}/{m_limit_str} GB`  🇫🇷  "
        user_lines.append(line)

    return "\n".join(user_lines)

def fmt_payments_report_list(payments: list, page: int) -> str:
    """گزارش آخرین پرداخت کاربران را با تاریخ شمسی فرمت می‌کند."""
    title = "گزارش آخرین پرداخت کاربران"

    if not payments:
        return f"*{escape_markdown(title)}*\n\nهیچ پرداخت ثبت‌شده‌ای یافت نشد."

    header_text = f"*{escape_markdown(title)}*"
    if len(payments) > settings.get('PAGE_SIZE', 15):
        total_pages = (len(payments) + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        pagination_text = f"(صفحه {page + 1} از {total_pages} | کل: {len(payments)})"
        header_text += f"\n{escape_markdown(pagination_text)}"

    lines = [header_text]
    paginated_payments = payments[page * settings.get('PAGE_SIZE', 15) : (page + 1) * settings.get('PAGE_SIZE', 15)]

    for payment in paginated_payments:
        name = escape_markdown(payment.get('name', 'کاربر ناشناس'))
        shamsi_date = to_shamsi(payment.get('payment_date')).split(' ')[0]

        line = f"`•` *{name}* `|` 💳 آخرین پرداخت: `{shamsi_date}`"
        lines.append(line)

    return "\n".join(lines)

def fmt_user_payment_history(payments: list, user_name: str, page: int) -> str:
    """تاریخچه پرداخت‌های یک کاربر را با تاریخ شمسی فرمت می‌کند."""
    title = f"سابقه پرداخت‌های کاربر: {escape_markdown(user_name)}"

    if not payments:
        return f"*{escape_markdown(title)}*\n\nهیچ پرداخت ثبت‌شده‌ای برای این کاربر یافت نشد."

    header_text = f"*{escape_markdown(title)}*"
    if len(payments) > settings.get('PAGE_SIZE', 15):
        total_pages = (len(payments) + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        pagination_text = f"(صفحه {page + 1} از {total_pages} | کل: {len(payments)})"
        header_text += f"\n{escape_markdown(pagination_text)}"

    lines = [header_text]
    paginated_payments = payments[page * settings.get('PAGE_SIZE', 15) : (page + 1) * settings.get('PAGE_SIZE', 15)]

    for payment in paginated_payments:
        shamsi_datetime = to_shamsi(payment.get('payment_date'))
        line = f"`•` 💳 تاریخ ثبت: `{shamsi_datetime}`"
        lines.append(line)

    return "\n".join(lines)