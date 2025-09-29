import pytz
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from .config import EMOJIS, PAGE_SIZE, ACHIEVEMENTS
from .database import db
from .utils import (
    format_daily_usage, escape_markdown,
    format_relative_time , to_shamsi, days_until_next_birthday, create_progress_bar, parse_user_agent
)

logger = logging.getLogger(__name__)


def fmt_admin_user_summary(info: dict, db_user: Optional[dict] = None) -> str:
    """
    اصلاح نهایی: پرانتزهای موجود در متن escape شده‌اند تا خطای parse entities تلگرام برطرف شود.
    """
    if not info:
        return escape_markdown("❌ خطا در دریافت اطلاعات کاربر.")

    def esc(text):
        return escape_markdown(str(text))

    # --- بخش هدر ---
    name = esc(info.get("name", "کاربر ناشناس"))
    is_active_overall = info.get('is_active', False)
    status_text_overall = "✅ فعال" if is_active_overall else "❌ غیرفعال"

    # شمارش تعداد پرداخت‌ها
    payment_count = 0
    uuid_str = info.get('uuid')
    if uuid_str:
        uuid_id = db.get_uuid_id_by_uuid(uuid_str)
        if uuid_id:
            payment_count = len(db.get_user_payment_history(uuid_id))

    # تعیین آیکون وفاداری
    loyalty_icon = ""
    if payment_count >= 10:
        loyalty_icon = "💎"
    elif payment_count >= 6:
        loyalty_icon = "🥇"
    elif payment_count >= 3:
        loyalty_icon = "⭐"

    # خط ۱ (اصلاح شده): کاراکترهای ( و ) با \\ escape شده‌اند
    header = f"👤 نام : {name} {loyalty_icon} \\({status_text_overall} \\| {payment_count} پرداخت\\)"


    report_lines = [header]
    separator = "`──────────────────`"

    # --- بخش تفکیک پنل‌ها ---
    breakdown = info.get('breakdown', {})

    if not db_user and info.get('uuid'):
        user_telegram_id = db.get_user_id_by_uuid(info['uuid'])
        if user_telegram_id:
            db_user = db.user(user_telegram_id)

    user_uuid_record = db.get_user_uuid_record(info.get('uuid', '')) if info.get('uuid') else None

    def create_panel_block(panel_display_name: str, panel_data: dict, panel_type: str):
        is_panel_active = panel_data.get('is_active', False)
        status_text_panel = "✅" if is_panel_active else "❌"

        limit_gb = panel_data.get('usage_limit_GB', 0)
        usage_gb = panel_data.get('current_usage_GB', 0)
        remaining_gb = max(0, limit_gb - usage_gb)

        daily_usage_gb = 0
        if info.get('uuid'):
            daily_usage_dict = db.get_usage_since_midnight_by_uuid(info['uuid'])
            daily_usage_gb = daily_usage_dict.get(panel_type, 0.0)

        display_name_with_flags = panel_display_name
        if panel_type == 'marzban' and user_uuid_record:
            flags = []
            if user_uuid_record.get('has_access_fr'):
                flags.append("🇫🇷")
            if user_uuid_record.get('has_access_tr'):
                flags.append("🇹🇷")
            if user_uuid_record.get('has_access_us'):
                flags.append("🇺🇸")
            if flags:
                display_name_with_flags = "".join(flags)

        return [
            separator,
            f"سرور {display_name_with_flags} \\({status_text_panel}\\)",
            f"🗂 حجم کل : `{limit_gb:.0f} GB`",
            f"🔥 حجم مصرف شده : `{usage_gb:.2f} GB`",
            f"📥 حجم باقیمانده : `{remaining_gb:.2f} GB`",
            f"{EMOJIS['lightning']} مصرف امروز : `{format_daily_usage(daily_usage_gb)}`",
            f"⏰ آخرین اتصال : `{esc(to_shamsi(panel_data.get('last_online'), include_time=True))}`"
        ]

    panel_order = ['hiddify', 'marzban']
    panel_display_map = {'hiddify': '🇩🇪', 'marzban': '🇫🇷🇹🇷'}

    for p_type in panel_order:
        panel_info = next((p for p in breakdown.values() if p.get('type') == p_type), None)
        if panel_info and panel_info.get('data'):
            report_lines.extend(create_panel_block(
                panel_display_name=panel_display_map[p_type],
                panel_data=panel_info['data'],
                panel_type=p_type
            ))

    uuid_str = info.get('uuid')
    if uuid_str:
        uuid_id = db.get_uuid_id_by_uuid(uuid_str)
        if uuid_id:
            user_agents = db.get_user_agents_for_uuid(uuid_id)
            if user_agents:
                report_lines.append(separator)
                report_lines.append("📱 *دستگاه‌های متصل:*")
                for agent in user_agents[:5]:
                    parsed = parse_user_agent(agent['user_agent'])
                    if parsed:
                        os_name_lower = (parsed.get('os') or '').lower()
                        icon = "❓"
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

                        client_name = esc(parsed.get('client', 'Unknown'))
                        details = []
                        if parsed.get('version'):
                            details.append(f"v{esc(parsed['version'])}")
                        if parsed.get('os'):
                            details.append(esc(parsed['os']))

                        details_str = f" \\({', '.join(details)}\\)" if details else ""
                        last_seen_str = esc(to_shamsi(agent['last_seen'], include_time=True))

                        report_lines.append(f"` `└─ {icon} *{client_name}*{details_str} \\(_{last_seen_str}_\\)")


    # --- بخش فوتر ---
    expire_days = info.get("expire")
    expire_label = f"{int(expire_days)} روز" if expire_days is not None and expire_days >= 0 else "منقضی شده"

    report_lines.extend([
        separator,
        f"📅 انقضا : {expire_label}",
        f"🔑 شناسه یکتا : `{esc(info.get('uuid', 'N/A'))}`"
    ])

    if db_user and db_user.get('admin_note'):
        report_lines.extend([
            separator,
            f"📝 *یادداشت ادمین:*",
            f"{esc(db_user['admin_note'])}"
        ])

    return "\n".join(report_lines)

def fmt_weekly_admin_summary(report_data: dict) -> str:
    """گزارش هفتگی پرمصرف‌ترین‌ها را برای ادمین فرمت‌بندی می‌کند."""
    
    lines = ["🏆 *گزارش هفتگی پرمصرف‌ترین کاربران*"]
    lines.append("`──────────────────`")
    lines.append("🥇 *۱۰ کاربر برتر این هفته:*")

    if not report_data.get('top_10_overall'):
        lines.append("هیچ مصرفی در این هفته ثبت نشده است.")
    else:
        for i, user in enumerate(report_data['top_10_overall']):
            usage_str = format_daily_usage(user['total_usage'])
            lines.append(f"`{i+1}.` *{escape_markdown(user['name'])}*: {escape_markdown(usage_str)}")

    lines.append("\n`──────────────────`")
    lines.append("🔥 *قهرمان هر روز هفته:*")

    day_names = ["🗓️ شنبه", "🗒️ یکشنبه", "🗓️ دوشنبه", "🗒️ سه‌شنبه", "🗓️ چهارشنبه", "🗒️ پنجشنبه", "🎉 جمعه"]

    if not report_data.get('top_daily'):
        lines.append("هنوز داده‌ای برای نمایش قهرمان روزانه وجود ندارد.")
    else:
        for i, day_name in enumerate(day_names):
            top_user = report_data['top_daily'].get(i)
            if top_user:
                usage_str = format_daily_usage(top_user['usage'])
                lines.append(f"*{escape_markdown(day_name)}:* {escape_markdown(top_user['name'])} \\({escape_markdown(usage_str)}\\)")
            else:
                lines.append(f"*{escape_markdown(day_name)}:* {escape_markdown('مصرفی ثبت نشده')}")
    
    return "\n".join(lines)

def fmt_achievement_leaderboard(leaderboard_data: list) -> str:
    """گزارش رتبه‌بندی کاربران بر اساس امتیاز را برای ادمین فرمت‌بندی می‌کند."""
    lines = ["🎖️ *رتبه‌بندی هفتگی کاربران بر اساس امتیاز*"]
    lines.append("`──────────────────`")
    
    if not leaderboard_data:
        lines.append("_هنوز هیچ کاربری امتیازی کسب نکرده است._")
        return "\n".join(lines)
        
    for i, user in enumerate(leaderboard_data):
        name = escape_markdown(user.get('first_name', 'کاربر ناشناس'))
        points = user.get('achievement_points', 0)
        
        emoji = ""
        if i == 0: emoji = "🥇"
        elif i == 1: emoji = "🥈"
        elif i == 2: emoji = "🥉"
        else: emoji = f"`{i+1}.`"
        
        lines.append(f"{emoji} *{name}*: {points} امتیاز")
        
    return "\n".join(lines)

def fmt_leaderboard_list(users: list, page: int) -> str:
    """(نسخه نهایی) لیست کامل کاربران، امتیازات و نشان‌هایشان را برای ادمین فرمت‌بندی می‌کند."""
    title = "🏆 رتبه‌بندی امتیازهای کاربران"
    if not users:
        return f"*{escape_markdown(title)}*\n\n{escape_markdown('هیچ کاربری امتیازی کسب نکرده است.')}"

    total_users = len(users)
    total_pages = (total_users + PAGE_SIZE - 1) // PAGE_SIZE
    is_last_page = (page + 1) == total_pages

    header_text = f"*{escape_markdown(title)}*"
    if total_users > PAGE_SIZE:
        pagination_text = f"\\(صفحه {page + 1} از {total_pages} \\| کل: {total_users}\\)"
        header_text += f"\n{pagination_text}"

    lines = [header_text]
    start_index = page * PAGE_SIZE
    paginated_users = users[start_index : start_index + PAGE_SIZE]

    for i, user in enumerate(paginated_users, start=start_index + 1):
        name = escape_markdown(user.get('first_name', 'کاربر ناشناس'))
        points = user.get('achievement_points', 0)
        
        badges_str = user.get('badges', '')
        badge_icons = ""
        if badges_str:
            badge_codes = badges_str.split(',')
            badge_icons = " ".join([ACHIEVEMENTS.get(code, {}).get('icon', '') for code in badge_codes])
        
        lines.append(f"`{i}.` *{name}* {badge_icons} : *{points}* امتیاز")
    
    if is_last_page:
        lines.append("\n`──────────────────`")
        lines.append("*راهنمای نشان‌ها:*")
        for code, details in ACHIEVEMENTS.items():
            points = details.get('points', 0)
            lines.append(f"{details.get('icon', '❓')} \\= {escape_markdown(details.get('name', code))} \\(*{points} امتیاز*\\)")
        
        lines.append("\nامتیاز نشان‌های 🏆 \\(قهرمان هفته\\) و 🍀 \\(خوش‌شانس\\) در هر بار کسب کردن، به کاربر تعلق می‌گیرد\\. سایر نشان‌ها فقط یک‌بار امتیاز دارند\\.")

    return "\n".join(lines)

def fmt_lottery_participants_list(participants: list) -> str:
    """لیست شرکت‌کنندگان در قرعه‌کشی را برای ادمین فرمت‌بندی می‌کند."""
    lines = ["🍀 *لیست هفتگی واجدین شرایط قرعه‌کشی ماهانه*"]
    lines.append("`──────────────────`")

    if not participants:
        lines.append("_در این هفته هیچ کاربری واجد شرایط نشده است._")
        return "\n".join(lines)

    for i, user in enumerate(participants):
        name = escape_markdown(user.get('first_name', 'کاربر ناشناس'))
        badge_count = user.get('lucky_badge_count', 0)
        user_id = user.get('user_id', 'N/A')
        lines.append(f"`{i+1}.` *{name}* \\(`{user_id}`\\) \\- {badge_count} نشان")
        
    return "\n".join(lines)

def fmt_users_list(users: list, list_type: str, page: int) -> str:
    title_map = {
        'active': "✅ کاربران فعال (۲۴ ساعت اخیر)",
        'inactive': "⏳ کاربران غیرفعال (۱ تا ۷ روز)",
        'never_connected': "🚫 کاربران هرگز متصل نشده"
    }
    title = escape_markdown(title_map.get(list_type, "لیست کاربران"))

    if not users:
        return f"*{title}*\n\n{escape_markdown('هیچ کاربری در این دسته یافت نشد.')}"

    header_text = f"*{title}*"
    if len(users) > PAGE_SIZE:
        total_pages = (len(users) + PAGE_SIZE - 1) // PAGE_SIZE
        pagination_text = f"\\(صفحه {page + 1} از {total_pages} \\| کل: {len(users)}\\)"
        header_text += f"\n{pagination_text}"

    lines = [header_text]

    start_index = page * PAGE_SIZE
    paginated_users = users[start_index : start_index + PAGE_SIZE]
    separator = " \\| "

    for user in paginated_users:
        name = escape_markdown(user.get('name', 'N/A'))
        line = f"`•` *{name}*"

        if list_type == 'active':
            last_online_str = to_shamsi(user.get('last_online')).split(' ')[0]
            usage_p = user.get('usage_percentage', 0)
            usage_p_str = f"{usage_p:.0f}"
            line += f"{separator}{escape_markdown(last_online_str)}{separator}{usage_p_str}%"

        elif list_type == 'inactive':
            last_online_str = format_relative_time(user.get('last_online'))
            status = "منقضی" if user.get('expire', 0) < 0 else "فعال"
            line += f"{separator}{escape_markdown(last_online_str)}{separator}{status}"

        elif list_type == 'never_connected':
            limit_gb = user.get('usage_limit_GB', 0)
            limit_gb_str = f"{limit_gb:g}"
            
            expire_days = user.get("expire")
            expire_text = "نامحدود"
            if expire_days is not None:
                expire_text = f"{expire_days} روز" if expire_days >= 0 else "منقضی"
            
            line += f"{separator}{limit_gb_str} GB{separator}{escape_markdown(expire_text)}"

        lines.append(line)

    return "\n".join(lines)


def fmt_online_users_list(users: list, page: int) -> str:
    title = "⚡️ کاربران آنلاین \\(۳ دقیقه اخیر\\)"

    if not users:
        return f"*{title}*\n\nهیچ کاربری در این لحظه آنلاین نیست\\."

    header_text = f"*{title}*"
    if len(users) > PAGE_SIZE:
        total_pages = (len(users) + PAGE_SIZE - 1) // PAGE_SIZE
        pagination_text = f"\\(صفحه {page + 1} از {total_pages} \\| کل: {len(users)}\\)"
        header_text += f"\n{pagination_text}"

    paginated_users = users[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    user_lines = []
    separator = " \\| "

    uuid_to_bot_user = db.get_uuid_to_bot_user_map()

    for user in paginated_users:
        panel_name_raw = user.get('name', 'کاربر ناشناس')
        bot_user_info = uuid_to_bot_user.get(user.get('uuid'))

        clean_name_for_link = escape_markdown(panel_name_raw.replace('[', '').replace(']', ''))

        if bot_user_info and bot_user_info.get('user_id'):
            user_id = bot_user_info['user_id']
            name_str = f"[{clean_name_for_link}](tg://user?id={user_id})"
        else:
            name_str = escape_markdown(panel_name_raw)

        daily_usage_output = escape_markdown(format_daily_usage(user.get('daily_usage_GB', 0)))
        expire_days = user.get("expire")

        expire_text = "unlimited"
        if expire_days is not None:
            expire_text = f"{expire_days} days" if expire_days >= 0 else "expired"

        line = f"• {name_str}{separator}`{daily_usage_output}`{separator}`{escape_markdown(expire_text)}`"
        user_lines.append(line)

    body_text = "\n".join(user_lines)
    return f"{header_text}\n\n{body_text}"



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

def fmt_bot_users_list(bot_users: list, page: int) -> str:
    title = "کاربران ربات"
    if not bot_users:
        return f"🤖 *{escape_markdown(title)}*\n\nهیچ کاربری در ربات ثبت‌نام نکرده است."

    header_text = f"🤖 *{escape_markdown(title)}*"
    total_users = len(bot_users)
    if total_users > PAGE_SIZE:
        total_pages = (total_users + PAGE_SIZE - 1) // PAGE_SIZE
        pagination_text = f"\\(صفحه {page + 1} از {total_pages} \\| کل: {total_users}\\)"
        header_text += f"\n{pagination_text}"

    lines = [header_text]
    start_index = page * PAGE_SIZE
    paginated_users = bot_users[start_index : start_index + PAGE_SIZE]

    for user in paginated_users:
        first_name = user.get('first_name') or 'ناشناس'
        username = user.get('username')
        user_id = user.get('user_id') or user.get('id')

        if username:
            link_name = f"[{escape_markdown(first_name)}](https://t.me/{username})"
        elif user_id:
            try:
                user_id_int = int(user_id)
                link_name = f"[{escape_markdown(first_name)}](tg://user?id={user_id_int})"
            except (ValueError, TypeError):
                link_name = escape_markdown(first_name)
        else:
            link_name = escape_markdown(first_name)
        lines.append(f"`•` {link_name} \\| ID : `{user_id or 'N/A'}`")

    return "\n".join(lines)

def fmt_marzban_system_stats(info: dict) -> str:
    if not info:
        return escape_markdown("اطلاعاتی از سیستم دریافت نشد.")

    to_gb = lambda b: b / (1024**3)
    
    version = escape_markdown(info.get('version', 'N/A'))
    mem_total_gb = f"{to_gb(info.get('mem_total', 0)):.2f}".replace('.', ',')
    mem_used_gb = f"{to_gb(info.get('mem_used', 0)):.2f}".replace('.', ',')
    mem_percent = (info.get('mem_used', 0) / info.get('mem_total', 1) * 100)
    mem_percent_str = f"{mem_percent:.1f}".replace('.', ',')
    cpu_cores = escape_markdown(str(info.get('cpu_cores', 'N/A')))
    cpu_usage = f"{info.get('cpu_usage', 0.0):.1f}".replace('.', ',')

    total_users = escape_markdown(str(info.get('total_user', 0)))
    online_users = escape_markdown(str(info.get('online_users', 0)))
    active_users = escape_markdown(str(info.get('users_active', 0)))
    disabled_users = escape_markdown(str(info.get('disabled_users_count', 0)))
    expired_users = escape_markdown(str(info.get('expired_users_count', 0)))

    total_dl_gb = f"{to_gb(info.get('incoming_bandwidth', 0)):.2f}".replace('.', ',')
    total_ul_gb = f"{to_gb(info.get('outgoing_bandwidth', 0)):.2f}".replace('.', ',')
    speed_dl_mbps = f"{info.get('incoming_bandwidth_speed', 0) / (1024 * 1024):.2f}".replace('.', ',')
    speed_ul_mbps = f"{info.get('outgoing_bandwidth_speed', 0) / (1024 * 1024):.2f}".replace('.', ',')

    report = (
        f"*📊 وضعیت سیستم پنل مرزبان \\(فرانسه 🇫🇷\\)*\n"
        f"`──────────────────`\n"
        f"⚙️ نسخه: `{version}`\n"
        f"🖥️ هسته CPU: `{cpu_cores}` `|` مصرف: `{cpu_usage}\\%`\n"
        f"💾 مصرف RAM: `{mem_used_gb} / {mem_total_gb} GB` `({mem_percent_str}\\%)`\n"
        f"`──────────────────`\n"
        f"👥 کاربران کل: `{total_users}` {escape_markdown('|')} 🟢 فعال: `{active_users}` {escape_markdown('|')} 🔴 آنلاین: `{online_users}`\n"
        f"⚪️ غیرفعال: `{disabled_users}` {escape_markdown('|')} 🗓 منقضی شده: `{expired_users}`\n"
        f"`──────────────────`\n"
        f"*📈 ترافیک کل:*\n"
        f"  `↓` دانلود: `{total_dl_gb} GB`\n"
        f"  `↑` آپلود: `{total_ul_gb} GB`\n"
        f"*🚀 سرعت لحظه‌ای:*\n"
        f"  `↓` دانلود: `{speed_dl_mbps} MB/s`\n"
        f"  `↑` آپلود: `{speed_ul_mbps} MB/s`"
    )

    return report


def fmt_users_by_plan_list(users: list, plan_name: str, page: int) -> str:
    title = f"گزارش کاربران پلن: {escape_markdown(plan_name)}"

    if not users:
        return f"*{title}*\n\nهیچ کاربری با مشخصات این پلن یافت نشد\\."

    header_text = f"*{title}*"
    if len(users) > PAGE_SIZE:
        total_pages = (len(users) + PAGE_SIZE - 1) // PAGE_SIZE
        pagination_text = f"\\(صفحه {page + 1} از {total_pages} \\| کل: {len(users)}\\)"
        header_text += f"\n{pagination_text}"

    user_lines = [header_text]
    paginated_users = users[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    separator = " \\| "

    for user in paginated_users:
        name = escape_markdown(user.get('name', 'کاربر ناشناس'))

        h_info = user.get('breakdown', {}).get('hiddify', {}).get('data', {})
        m_info = user.get('breakdown', {}).get('marzban', {}).get('data', {})
        
        panel_usage_parts = []
        
        if h_info:
            h_usage_gb = f"{h_info.get('current_usage_GB', 0.0):.2f}".replace('.00', '')
            h_limit_gb = f"{h_info.get('usage_limit_GB', 0.0):.2f}".replace('.00', '')
            panel_usage_parts.append(f"🇩🇪 `{h_usage_gb}/{h_limit_gb} GB`")

        if m_info:
            m_usage_gb = f"{m_info.get('current_usage_GB', 0.0):.2f}".replace('.00', '')
            m_limit_gb = f"{m_info.get('usage_limit_GB', 0.0):.2f}".replace('.00', '')
            panel_usage_parts.append(f"🇫🇷 `{m_usage_gb}/{m_limit_gb} GB`")

        usage_str = separator.join(panel_usage_parts)
        line = f"`•` *{name}*{separator}{usage_str}"
        user_lines.append(line)

    return "\n".join(user_lines)


def fmt_user_payment_history(payments: list, user_name: str, page: int) -> str:
    title_raw = f"سابقه پرداخت‌های کاربر: {user_name}"
    title = f"*{escape_markdown(title_raw)}*"

    if not payments:
        no_payments_text = "هیچ پرداخت ثبت‌شده‌ای برای این کاربر یافت نشد."
        return f"{title}\n\n{escape_markdown(no_payments_text)}"

    header_text = title
    if len(payments) > PAGE_SIZE:
        total_pages = (len(payments) + PAGE_SIZE - 1) // PAGE_SIZE
        pagination_text = f"(صفحه {page + 1} از {total_pages} | کل: {len(payments)})"
        header_text += f"\n{escape_markdown(pagination_text)}"

    lines = [header_text]
    paginated_payments = payments[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    for i, payment in enumerate(paginated_payments, start=page * PAGE_SIZE + 1):
        name = escape_markdown(payment.get('config_name', user_name))
        shamsi_datetime = to_shamsi(payment.get('payment_date'), include_time=True)
        lines.append(f"`{i}.` *{name}*\n` `💳 `تاریخ ثبت:` `{shamsi_datetime}`")

    return "\n".join(lines)

def fmt_admin_report(all_users_from_api: list, db_manager) -> str:
    """
    (نسخه نهایی با چیدمان سفارشی و لاگ‌های جامع برای عیب‌یابی)
    گزارش جامع ادمین را تولید کرده و مراحل کلیدی را برای عیب‌یابی لاگ می‌کند.
    """
    try:
        if not all_users_from_api:
            logger.warning("fmt_admin_report: `all_users_from_api` list is empty. Report generation stopped.")
            return "هیچ کاربری در پنل یافت نشد"

        logger.info(f"fmt_admin_report: Starting comprehensive report generation for {len(all_users_from_api)} users from API.")

        # --- بخش ۱: محاسبات اولیه ---
        active_users, total_daily_hiddify, total_daily_marzban = 0, 0.0, 0.0
        expiring_soon_users, new_users_today, expired_recently_users = [], [], []

        now_utc = datetime.now(pytz.utc)
        start_of_today_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

        db_users_map = {u['uuid']: u for u in db_manager.get_all_user_uuids()}
        top_consumer_today = {"name": "N/A", "usage": 0.0}
        active_today_users = []

        logger.debug(f"fmt_admin_report: Starting to process {len(all_users_from_api)} users.")

        for user_info in all_users_from_api:
            if user_info.get("is_active"):
                active_users += 1

            daily_usage_sum = 0
            if user_info.get('uuid'):
                daily_usage_dict = db_manager.get_usage_since_midnight_by_uuid(user_info['uuid'])
                h_usage = daily_usage_dict.get('hiddify', 0.0)
                m_usage = daily_usage_dict.get('marzban', 0.0)
                total_daily_hiddify += h_usage
                total_daily_marzban += m_usage
                user_info['daily_usage_dict'] = daily_usage_dict
                daily_usage_sum = h_usage + m_usage

            if daily_usage_sum > 0:
                active_today_users.append(user_info)
                if daily_usage_sum > top_consumer_today["usage"]:
                    top_consumer_today = {"name": user_info.get('name', 'N/A'), "usage": daily_usage_sum}
                    logger.debug(f"fmt_admin_report: New top consumer found: {top_consumer_today['name']} with usage {top_consumer_today['usage']:.2f} GB.")


            expire_days = user_info.get('expire')
            if expire_days is not None:
                if 0 <= expire_days <= 3: expiring_soon_users.append(user_info)
                elif -2 <= expire_days < 0: expired_recently_users.append(user_info)

            created_at_info = db_users_map.get(user_info.get('uuid'))
            if created_at_info and created_at_info.get('created_at'):
                created_at = created_at_info['created_at']
                if isinstance(created_at, datetime) and (now_utc - created_at.astimezone(pytz.utc)).days < 1:
                    new_users_today.append(user_info)

        total_daily_all = total_daily_hiddify + total_daily_marzban
        payments_today_count = db_manager.get_total_payments_in_range(start_of_today_utc, now_utc)

        logger.info(f"fmt_admin_report: Calculation complete. Total daily usage: {total_daily_all:.2f} GB. Top consumer: {top_consumer_today['name']} ({top_consumer_today['usage']:.2f} GB).")
        logger.info(f"fmt_admin_report: Found {len(expiring_soon_users)} expiring users, {len(new_users_today)} new users, {len(expired_recently_users)} recently expired users.")


        # --- بخش ۲: ساخت متن گزارش (هدر) ---
        report_lines = [
            f"*{escape_markdown('⚙️ خلاصه وضعیت کل پنل')}*",
            f"👤 تعداد کل اکانت‌ها : *{len(all_users_from_api)}*",
            f"✅ اکانت‌های فعال : *{active_users}*",
            f"➕ کاربران جدید امروز : *{len(new_users_today)}*",
            f"💳 پرداخت‌های امروز : *{payments_today_count}*",
            f"⚡️ *مصرف کل امروز :* {escape_markdown(format_daily_usage(total_daily_all))}",
            f" 🇩🇪 : `{escape_markdown(format_daily_usage(total_daily_hiddify))}`",
            f" 🇫🇷🇹🇷🇺🇸 : `{escape_markdown(format_daily_usage(total_daily_marzban))}`"
        ]

        if top_consumer_today["usage"] > 0.01:
            report_lines.append(f"🔥 *قهرمان امروز : * {escape_markdown(top_consumer_today['name'])} \\({escape_markdown(format_daily_usage(top_consumer_today['usage']))}\\)")
        else:
            logger.info(f"fmt_admin_report: Top consumer of the day was NOT displayed because their usage ({top_consumer_today['usage']:.4f} GB) was not greater than 0.01.")

        # 1. کاربران فعال امروز
        if active_today_users:
            report_lines.extend(["`──────────────────`", f"*{escape_markdown('✅ کاربران فعال امروز و مصرفشان')}*"])
            active_today_users.sort(key=lambda u: u.get('name', ''))
            for user in active_today_users:
                user_name = escape_markdown(user.get('name', 'کاربر ناشناس'))
                user_db_record = db_users_map.get(user.get('uuid'))
                is_vip = user_db_record.get('is_vip', False) if user_db_record else False
                user_emoji = "👑" if is_vip else "👤"

                daily_dict = user.get('daily_usage_dict', {})
                usage_parts = []
                h_usage = daily_dict.get('hiddify', 0.0)
                if h_usage > 0.001: usage_parts.append(f"🇩🇪 {escape_markdown(format_daily_usage(h_usage))}")
                m_usage = daily_dict.get('marzban', 0.0)
                if m_usage > 0.001 and user_db_record:
                    flags = [f for f, has in [("🇫🇷", 'has_access_fr'), ("🇹🇷", 'has_access_tr'), ("🇺🇸", 'has_access_us')] if user_db_record.get(has)]
                    if flags: usage_parts.append(f"{''.join(flags)} {escape_markdown(format_daily_usage(m_usage))}")

                usage_str = escape_markdown(" | ").join(usage_parts)
                if usage_str:
                    report_lines.append(f"{user_emoji} {user_name} : {usage_str}")

        # 2. کاربران در آستانه انقضا
        if expiring_soon_users:
            report_lines.extend(["`──────────────────`", f"*{escape_markdown('⚠️ کاربرانی که تا ۳ روز آینده منقضی می شوند')}*"])
            expiring_soon_users.sort(key=lambda u: u.get('expire', 99))
            for user in expiring_soon_users:
                name = escape_markdown(user['name'])
                days = user['expire']
                user_db_record = db_users_map.get(user.get('uuid'))
                is_vip = user_db_record.get('is_vip', False) if user_db_record else False
                user_emoji = "👑" if is_vip else "👤"
                report_lines.append(f"{user_emoji} {name} : {days} روز")

        # 3. کاربران منقضی شده
        if expired_recently_users:
            report_lines.extend(["`──────────────────`", f"*{escape_markdown('❌ کاربران منقضی (۴۸ ساعت اخیر)')}*"])
            expired_recently_users.sort(key=lambda u: u.get('name', ''))
            for user in expired_recently_users:
                name = escape_markdown(user['name'])
                user_db_record = db_users_map.get(user.get('uuid'))
                is_vip = user_db_record.get('is_vip', False) if user_db_record else False
                user_emoji = "👑" if is_vip else "👤"
                report_lines.append(f"{user_emoji} {name}")

        # 4. هشدارهای ارسال شده
        sent_warnings_raw = db_manager.get_sent_warnings_since_midnight()
        if sent_warnings_raw:
            report_lines.extend(["`──────────────────`", f"*{escape_markdown('🔔 هشدارهای ارسال شده امروز')}*"])

            warnings_by_type = {}
            for w in sent_warnings_raw:
                warnings_by_type.setdefault(w.get('warning_type', 'unknown'), []).append(w)

            warning_map = {
                "low_data_hiddify": "کمبود حجم 🇩🇪", "volume_depleted_hiddify": "اتمام حجم 🇩🇪",
                "low_data_marzban": "کمبود حجم 🇫🇷🇹🇷🇺🇸", "volume_depleted_marzban": "اتمام حجم 🇫🇷🇹🇷🇺🇸",
                "expiry_hiddify": "در آستانه انقضا 🇩🇪", "expiry_marzban": "در آستانه انقضا 🇫🇷🇹🇷🇺🇸",
                "expired": "منقضی شده", "inactive_user_reminder": "یادآوری عدم فعالیت",
                "unusual_daily_usage_admin_alert": "مصرف غیرعادی (به ادمین)",
                "too_many_devices_admin_alert": "تعداد دستگاه بالا (به ادمین)"
            }

            for warning_type, warnings in warnings_by_type.items():
                type_fa = warning_map.get(warning_type, warning_type)
                report_lines.append(f"*{escape_markdown(f'   - دسته: {type_fa}')}*")
                for warning in warnings:
                    user_name = escape_markdown(warning.get('name', 'کاربر ناشناس'))
                    user_uuid = warning.get('uuid')
                    db_rec_for_vip = db_users_map.get(user_uuid) if user_uuid else None
                    is_vip = db_rec_for_vip.get('is_vip', False) if db_rec_for_vip else False
                    user_emoji = "👑" if is_vip else "👤"
                    report_lines.append(f"     {user_emoji} {user_name}")
        
        logger.info(f"fmt_admin_report: Successfully generated report with {len(report_lines)} lines.")
        return "\n".join(report_lines)

    except Exception as e:
        logger.error(f"FATAL ERROR in fmt_admin_report: {e}", exc_info=True)
        return escape_markdown(f"❌ خطای بحرانی در هنگام ساخت گزارش جامع: {e}")

def fmt_top_consumers(users: list, page: int) -> str:
    title = "پرمصرف‌ترین کاربران"
    if not users:
        return f"🏆 *{escape_markdown(title)}*\n\nهیچ کاربری برای نمایش وجود ندارد."

    header_text = f"🏆 *{escape_markdown(title)}*"
    if len(users) > PAGE_SIZE:
        total_pages = (len(users) + PAGE_SIZE - 1) // PAGE_SIZE
        pagination_text = f"(صفحه {page + 1} از {total_pages} | کل: {len(users)})"
        header_text += f"\n{pagination_text}"

    lines = [header_text]
    paginated_users = users[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    separator = escape_markdown(" | ")

    for i, user in enumerate(paginated_users, start=page * PAGE_SIZE + 1):
        name = escape_markdown(user.get('name', 'کاربر ناشناس'))
        usage = f"{user.get('current_usage_GB', 0):.2f}".replace('.', ',')
        limit = f"{user.get('usage_limit_GB', 0):.2f}".replace('.', ',')
        usage_str = f"`{usage} GB / {limit} GB`"
        line = f"`{i}.` *{name}*{separator}{EMOJIS['chart']} {usage_str}"
        lines.append(line)

    return "\n".join(lines)


def fmt_birthdays_list(users: list, page: int) -> str:
    title = "لیست تولد کاربران"
    if not users:
        return f"🎂 *{escape_markdown(title)}*\n\n{escape_markdown('هیچ کاربری تاریخ تولد خود را ثبت نکرده است.')}"
    
    title_text = f"{title} (مرتب شده بر اساس ماه)"
    header_text = f"🎂 *{escape_markdown(title_text)}*"
    total_users = len(users)
    if total_users > PAGE_SIZE:
        total_pages = (total_users + PAGE_SIZE - 1) // PAGE_SIZE
        pagination_text = f"\\(صفحه {page + 1} از {total_pages} \\| کل: {total_users}\\)"
        header_text += f"\n{pagination_text}"

    lines = [header_text]
    start_index = page * PAGE_SIZE
    paginated_users = users[start_index : start_index + PAGE_SIZE]
    separator = escape_markdown(" | ")

    for user in paginated_users:
        name = escape_markdown(user.get('first_name', 'کاربر ناشناس'))
        birthday_obj = user.get('birthday')

        shamsi_str = to_shamsi(birthday_obj)

        remaining_days = days_until_next_birthday(birthday_obj)
        days_str = f"{remaining_days} روز" if remaining_days is not None else "نامشخص"

        lines.append(f"🎂 *{name}*{separator}`{shamsi_str}`{separator}{escape_markdown(days_str)}")

    return "\n".join(lines)


def fmt_panel_users_list(users: list, panel_name: str, page: int) -> str:
    title = f"کاربران پنل {panel_name}"
    if not users:
        return f"*{escape_markdown(title)}*\n\nهیچ کاربری در این پنل یافت نشد\\."

    header_text = f"*{escape_markdown(title)}*"
    if len(users) > PAGE_SIZE:
        total_pages = (len(users) + PAGE_SIZE - 1) // PAGE_SIZE
        pagination_text = f"\\(صفحه {page + 1} از {total_pages} \\| کل: {len(users)}\\)"
        header_text += f"\n{pagination_text}"

    user_lines = []
    paginated_users = users[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    separator = escape_markdown(" | ")

    for user in paginated_users:
        name = escape_markdown(user.get('name', 'کاربر ناشناس'))
        expire_days = user.get("expire")
        expire_text = "نامحدود"
        if expire_days is not None:
            expire_text = f"{expire_days} day" if expire_days >= 0 else "منقضی"

        line = f"`•` *{name}*{separator}{EMOJIS['calendar']} {escape_markdown(expire_text)}"
        user_lines.append(line)

    body_text = "\n".join(user_lines)
    return f"{header_text}\n\n{body_text}"


def fmt_payments_report_list(payments: list, page: int) -> str:
    title = "گزارش تمام پرداخت‌های ثبت‌شده"

    if not payments:
        return f"*{escape_markdown(title)}*\n\nهیچ پرداخت ثبت‌شده‌ای یافت نشد."

    header_text = f"*{escape_markdown(title)}*"
    if len(payments) > PAGE_SIZE:
        total_pages = (len(payments) + PAGE_SIZE - 1) // PAGE_SIZE
        pagination_text = f"\\(صفحه {page + 1} از {total_pages} \\| کل: {len(payments)}\\)"
        header_text += f"\n{pagination_text}"

    lines = [header_text]
    paginated_payments = payments[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    for i, payment in enumerate(paginated_payments, start=page * PAGE_SIZE + 1):
        name = escape_markdown(payment.get('config_name', 'کاربر ناشناس'))
        shamsi_datetime = to_shamsi(payment.get('payment_date'), include_time=True)
        
        line = f"`{i}.` *{name} *\\(💳 {shamsi_datetime}\\)"
        lines.append(line)

    return "\n".join(lines)

def fmt_admin_quick_dashboard(stats: dict) -> str:
    """داده‌های داشبورد را به یک پیام متنی خوانا برای تلگرام تبدیل می‌کند."""
    
    total_users = stats.get('total_users', 0)
    active_users = stats.get('active_users', 0)
    online_users = stats.get('online_users', 0)
    expiring_soon = stats.get('expiring_soon_count', 0)
    new_users = stats.get('new_users_last_24h_count', 0)
    total_usage = escape_markdown(stats.get('total_usage_today', '0 GB'))

    lines = [
        f"👑 *داشبورد سریع ربات*",
        "`──────────────────`",
        f"👥 *کل کاربران :* {total_users}",
        f"✅ *کاربران فعال :* {active_users}",
        f"📡 *کاربران آنلاین  \\(۳ دقیقه\\):* {online_users}",
        f"⚠️ *در آستانه انقضا \\(۷ روز\\) :* {expiring_soon}",
        f"➕ *کاربران جدید \\(۲۴ ساعت\\) :* {new_users}",
        f"⚡️ *مجموع مصرف امروز :* {total_usage}"
    ]
    
    return "\n".join(lines)

def fmt_card_info_inline() -> tuple[str, str]:
    """Formats the card payment info for an inline result."""
    from .config import CARD_PAYMENT_INFO
    from .utils import escape_markdown

    if not (CARD_PAYMENT_INFO and CARD_PAYMENT_INFO.get("card_number")):
        return (escape_markdown("اطلاعات کارت در فایل کانفیگ تعریف نشده است."), "MarkdownV2")

    title = "اطلاعات کارت به کارت"
    holder_label = "نام صاحب حساب"
    number_label = "شماره کارت"
    
    holder_name = escape_markdown(CARD_PAYMENT_INFO.get("card_holder", ""))
    card_number = escape_markdown(CARD_PAYMENT_INFO.get("card_number", ""))
    bank_name = escape_markdown(CARD_PAYMENT_INFO.get("bank_name", ""))

    # --- ✨ تغییر اصلی: escape کردن پرانتزها ---
    text = (
        f"*{escape_markdown(title)}*\n\n"
        f"*{escape_markdown(holder_label)} : *{holder_name}\n"
        f"*{escape_markdown(number_label)} \\({bank_name}\\):*\n`{card_number}`"
    )
    return text, "MarkdownV2"

def fmt_connected_devices_list(devices: list, page: int) -> str:
    """
    Formats the list of all connected devices for the admin report with pagination.
    Devices are grouped by user, and an icon specific to the OS is displayed.
    """
    title = "📱 *لیست کامل دستگاه‌های متصل*"

    if not devices:
        return f"{title}\n\nهیچ دستگاهی برای نمایش یافت نشد\\."

    # --- 1. Group devices by user ---
    users_devices = {}
    for device in devices:
        parsed = parse_user_agent(device['user_agent'])
        if not parsed:
            continue
            
        user_key = device.get('user_id') or device.get('config_name', 'کاربر ناشناس')
        if user_key not in users_devices:
            users_devices[user_key] = {
                'name': device.get('config_name') or device.get('first_name', 'کاربر ناشناس'),
                'devices': []
            }
        
        parsed['last_seen'] = device['last_seen']
        users_devices[user_key]['devices'].append(parsed)
    
    for user in users_devices.values():
        user['devices'].sort(key=lambda x: x['last_seen'], reverse=True)

    user_list = list(users_devices.values())

    # --- 2. Pagination Header ---
    header_text = title
    total_items = len(user_list)
    ADMIN_DEVICE_LIST_PAGE_SIZE = 20
    if total_items > ADMIN_DEVICE_LIST_PAGE_SIZE:
        total_pages = (total_items + ADMIN_DEVICE_LIST_PAGE_SIZE - 1) // ADMIN_DEVICE_LIST_PAGE_SIZE
        pagination_text = f"\\(صفحه {page + 1} از {total_pages} \\| کل: {total_items}\\)"
        header_text += f"\n{pagination_text}"

    # --- 3. Build the final report string ---
    lines = [header_text, "`──────────────────`"]
    paginated_users = user_list[page * ADMIN_DEVICE_LIST_PAGE_SIZE : (page + 1) * ADMIN_DEVICE_LIST_PAGE_SIZE]

    for user in paginated_users:
        user_name = escape_markdown(user['name'])
        lines.append(f"👤 *{user_name}*")
        
        if not user['devices']:
             lines.append("` `└─ ▫️ دستگاهی یافت نشد")
        else:
            for device in user['devices'][:6]: 
                # --- START: New Emoji Logic ---
                os_name_lower = (device.get('os') or '').lower()
                icon = "❓" # Default icon
                if 'ios' in os_name_lower or 'macos' in os_name_lower:
                    icon = "📱"
                elif 'android' in os_name_lower:
                    icon = "🤖"
                elif 'windows' in os_name_lower:
                    icon = "🖥️"
                elif 'linux' in os_name_lower:
                    icon = "🐧"
                elif 'browser' in (device.get('client') or '').lower():
                    icon = "🌐"
                # --- END: New Emoji Logic ---

                client_name = escape_markdown(device.get('client', 'Unknown'))
                details = []
                if device.get('version'):
                    details.append(f"v{escape_markdown(device['version'])}")
                if device.get('os'):
                    details.append(escape_markdown(device['os']))
                
                details_str = f" \\({', '.join(details)}\\)" if details else ""
                last_seen_str = escape_markdown(to_shamsi(device['last_seen'], include_time=True))

                lines.append(f"` `└─ {icon} *{client_name}*{details_str} \\(_{last_seen_str}_\\)")
        lines.append("")

    return "\n".join(lines)

def fmt_scheduled_tasks(tasks: list) -> str:
    """(نسخه نهایی) لیست تسک‌های زمان‌بندی شده را به یک پیام خوانا برای ادمین تبدیل می‌کند."""
    
    if not tasks:
        return "هیچ تسک زمان‌بندی شده‌ای برای نمایش وجود ندارد."

    lines = ["⏰ *لیست فرآیندهای خودکار ربات*", "`──────────────────`"]
    
    icon_map = {
        'camera-lens': '📸',
        'alarm-warning': '⚠️',
        'send-plane-2': '✈️',
        'cake-2': '🎂',
        'database-2': '🗂️',
        'calendar-event': '🗓️', # گزارش هفتگی
        'medal': '🎖️',         # دستاوردها
        'trophy': '🏆',         # قرعه‌کشی
        'refresh': '🔄',         # همگام‌سازی
        'delete-bin': '🗑️'         # پاکسازی
    }

    for task in tasks:
        icon_key_parts = task.get('icon', '').replace('ri-', '').split('-')
        icon_key = '-'.join(icon_key_parts[:2]) if len(icon_key_parts) > 1 else icon_key_parts[0]
        
        icon = icon_map.get(icon_key, '⚙️') 
        
        title = escape_markdown(task.get('title', 'تسک ناشناس'))
        interval = escape_markdown(task.get('interval', 'نامشخص'))
        description = escape_markdown(task.get('description', 'بدون توضیحات.'))
        
        lines.append(f"{icon} *{title}*")
        lines.append(f"  زمان‌بندی : {interval}")
        lines.append(f"  توضیحات : {description}")
        lines.append("") # ایجاد یک خط خالی برای جداسازی بهتر

    return "\n".join(lines)


def fmt_daily_achievements_report(daily_achievements: list) -> str:
    """
    گزارش روزانه دستاوردهای کسب شده توسط کاربران را برای ادمین فرمت‌بندی می‌کند.
    (نسخه اصلاح شده با escape کردن پرانتزها)
    """
    if not daily_achievements:
        return "🎖️ *گزارش دستاوردهای امروز*\n\nامروز هیچ کاربری دستاورد جدیدی کسب نکرده است."

    lines = ["🎖️ *گزارش دستاوردهای امروز*"]
    lines.append("`──────────────────`")
    
    users_achievements = {}
    for achievement in daily_achievements:
        user_id = achievement['user_id']
        if user_id not in users_achievements:
            users_achievements[user_id] = {
                'first_name': escape_markdown(achievement.get('first_name', 'کاربر ناشناس')),
                'badges': []
            }
        users_achievements[user_id]['badges'].append(achievement['badge_code'])

    for user_id, data in users_achievements.items():
        lines.append(f"👤 *{data['first_name']}* \\(`{user_id}`\\):")
        
        total_points_today = 0
        for badge_code in data['badges']:
            badge_info = ACHIEVEMENTS.get(badge_code, {})
            points = badge_info.get('points', 0)
            total_points_today += points
            badge_name = escape_markdown(badge_info.get('name', badge_code))
            lines.append(f"  `•` {badge_info.get('icon', '🎖️')} {badge_name} \\(\\+{points} امتیاز\\)")
                    
        lines.append(f"  💰 *مجموع امتیاز امروز: {total_points_today}*")
        lines.append("") 

    return "\n".join(lines)

def fmt_user_balances_list(users: list, page: int) -> str:
    """لیست موجودی کیف پول کاربران را برای ادمین فرمت‌بندی می‌کند."""
    title = "موجودی کیف پول کاربران"
    if not users:
        return f"💰 *{escape_markdown(title)}*\n\n{escape_markdown('هیچ کاربری کیف پول خود را شارژ نکرده است.')}"

    total_users = len(users)
    total_balance = sum(u.get('wallet_balance', 0) for u in users)
    header_text = f"💰 *{escape_markdown(title)}* \\| *مجموع کل: {total_balance:,.0f} تومان*"

    if total_users > PAGE_SIZE:
        total_pages = (total_users + PAGE_SIZE - 1) // PAGE_SIZE
        pagination_text = f"\\(صفحه {page + 1} از {total_pages} \\| کل: {total_users}\\)"
        header_text += f"\n{pagination_text}"

    lines = [header_text]
    start_index = page * PAGE_SIZE
    paginated_users = users[start_index : start_index + PAGE_SIZE]

    for i, user in enumerate(paginated_users, start=start_index + 1):
        name = escape_markdown(user.get('first_name', 'کاربر ناشناس'))
        balance = user.get('wallet_balance', 0)
        lines.append(f"`{i}.` *{name}* \\(`{user['user_id']}`\\): `{balance:,.0f}` تومان")
    
    return "\n".join(lines)

def fmt_admin_purchase_notification(user_info: dict, plan: dict, new_balance: float, info_before: dict, info_after: dict, payment_count: int, is_vip: bool, user_access: dict) -> str:
    """
    (نسخه نهایی) پیام اطلاع‌رسانی خرید را با نمایش وضعیت قبل و بعد از خرید، فرمت‌بندی می‌کند.
    """
    user_name = escape_markdown(user_info.first_name)
    user_id = user_info.id
    plan_name = escape_markdown(plan.get('name', 'ناشناس'))
    price = plan.get('price', 0)
    
    lines = [
        "🛒 *خرید جدید از کیف پول*",
        "`──────────────────`",
        f"👤 *کاربر:* {user_name} \\(`{user_id}`\\)",
        f"🛍️ *پلن:* {plan_name}",
        f"💰 *هزینه:* `{price:,.0f}` تومان",
        f"💳 *موجودی:* `{new_balance:,.0f}` تومان",
        f"📈 *تمدید شماره:* {payment_count}",
        "`──────────────────`",
    ]
    
    marzban_flags = []
    if user_access.get('has_access_fr'): marzban_flags.append("🇫🇷")
    if user_access.get('has_access_tr'): marzban_flags.append("🇹🇷")
    if user_access.get('has_access_us'): marzban_flags.append("🇺🇸")
    dynamic_marzban_flags = "".join(marzban_flags) if marzban_flags else ""

    def sort_key(panel_item_tuple):
        panel_details = panel_item_tuple[1]
        return panel_details.get('type') != 'hiddify'

    lines.append(f"📊 *وضعیت قبل از خرید*")
    sorted_before = sorted(info_before.get('breakdown', {}).items(), key=sort_key)
    for panel_name, panel_details in sorted_before:
        panel_type = panel_details.get('type')
        if (panel_type == 'hiddify' and user_access.get('has_access_de')) or \
           (panel_type == 'marzban' and dynamic_marzban_flags):
            p_data = panel_details.get('data', {})
            limit = p_data.get('usage_limit_GB', 0)
            expire_raw = p_data.get('expire')
            expire = expire_raw if expire_raw is not None and expire_raw >= 0 else 0
            flag = "🇩🇪" if panel_type == 'hiddify' else dynamic_marzban_flags
            lines.append(f" {flag} : *{int(limit)} GB* \\| *{int(expire)} روز*")

    lines.append(f"\n📊 *وضعیت پس از خرید*")

    sorted_after = sorted(info_after.get('breakdown', {}).items(), key=sort_key)
    for panel_name, panel_details in sorted_after:
        panel_type = panel_details.get('type')
        if (panel_type == 'hiddify' and user_access.get('has_access_de')) or \
           (panel_type == 'marzban' and dynamic_marzban_flags):
            p_data = panel_details.get('data', {})
            limit = p_data.get('usage_limit_GB', 0)
            expire_raw = p_data.get('expire')
            expire = expire_raw if expire_raw is not None and expire_raw >= 0 else 0
            flag = "🇩🇪" if panel_type == 'hiddify' else dynamic_marzban_flags
            lines.append(f" {flag} : *{int(limit)} GB* \\| *{int(expire)} روز*")

    return "\n".join(lines)

def fmt_financial_report(financial_data: dict) -> str:
    """گزارش مالی ماهانه را برای نمایش در تلگرام با فرمت بهبود یافته و دقیق فرمت‌بندی می‌کند."""
    lines = ["📊 *گزارش مالی ماهانه*"]
    
    summary = financial_data.get('summary', {})
    total_revenue = summary.get('total_revenue', 0)
    total_cost = summary.get('total_cost', 0)
    total_profit = summary.get('total_profit', 0)
    
    profit_emoji = "✅" if total_profit >= 0 else "🔻"

    def format_negative_number(num):
        if num < 0:
            return escape_markdown(f"{abs(num):,.0f}-")
        return escape_markdown(f"{num:,.0f}")

    lines.extend([
        "`──────────────────`",
        f"💰 *درآمد کل :* {total_revenue:,.0f} تومان",
        f"💳 *هزینه کل :* {total_cost:,.0f} تومان",
        f"{profit_emoji} *سود / زیان کل :* {format_negative_number(total_profit)} تومان"
    ])
    
    financials = financial_data.get('financials', [])
    if financials:
        lines.append("`──────────────────`")
        lines.append("*عملکرد ۶ ماه اخیر:*")
        for item in financials[:6]:
            month_str = item['month']
            profit = item.get('profit', 0)
            profit_str = format_negative_number(profit) # استفاده از تابع جدید
            month_shamsi = to_shamsi(datetime.strptime(month_str, '%Y-%m'), month_only=True)
            
            lines.append(f"🗓️ *{escape_markdown(month_shamsi)}:* {profit_str} تومان")
            
    return "\n".join(lines)

def fmt_monthly_transactions_report(transactions: list, year: int, month: int, page: int) -> str:
    """لیست تراکنش‌های یک ماه را با فرمت فشرده، آیکون‌محور و به همراه راهنمای آیکون‌ها برای ادمین فرمت‌بندی می‌کند."""
    shamsi_date_str = to_shamsi(datetime(year, month, 1), month_only=True)
    title = f"💳 *جزئیات تراکنش‌های {escape_markdown(shamsi_date_str)}*"

    if not transactions:
        return f"{title}\n\nهیچ تراکنشی در این ماه ثبت نشده است."

    header_text = f"{title}"
    total_items = len(transactions)
    total_pages = (total_items + PAGE_SIZE - 1) // PAGE_SIZE
    is_last_page = (page + 1) == total_pages

    if total_items > PAGE_SIZE:
        pagination_text = f"\\(صفحه {page + 1} از {total_pages} \\| کل: {total_items}\\)"
        header_text += f"\n{pagination_text}"

    lines = [header_text, "`──────────────────`"]
    paginated_transactions = transactions[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    for trans in paginated_transactions:
        name = escape_markdown(trans.get('first_name', 'کاربر'))
        user_id = trans.get('user_id', 'N/A')
        amount = trans.get('amount', 0)
        desc_raw = trans.get('description', '')
        date_str = escape_markdown(to_shamsi(trans.get('transaction_date'), include_time=False))
        
        icon = "❔"
        if 'خرید پلن:' in desc_raw:
            icon = "🛒"
        elif 'شارژ دستی توسط مدیریت' in desc_raw:
            icon = "🛠️"
        elif 'شارژ توسط مدیریت' in desc_raw:
            icon = "✅"
        elif 'خرید هدیه برای کاربر' in desc_raw:
            icon = "🎁"
        
        sign = "\\+" if amount > 0 else ""
        amount_str = escape_markdown(f"{amount:,.0f}")
        final_amount_str = f"{sign}{amount_str}" if amount > 0 else amount_str
        
        lines.append(f"{icon} *{name}* \\(`{user_id}`\\): *{final_amount_str}* \\({date_str}\\)")

    if is_last_page:
        lines.append("`──────────────────`")
        lines.append("*راهنمای آیکون‌ها*")
        lines.append("🛒 خرید پلن   ✅ تایید رسید")
        lines.append("🎁 خرید هدیه   🛠️ شارژ دستی")

    return "\n".join(lines)