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


def fmt_admin_user_summary(info: dict, db_user: Optional[dict] = None) -> str:
    # ——— اول تعریف یک تابع پرانتز escape شده ———
    def esc(text):
        # فقط برای مقادیر داینامیک!
        return escape_markdown(str(text))

    # اگر info تهی بود پیام خطا بده
    if not info:
        return "❌ خطا در دریافت اطلاعات کاربر."

    report_parts = []
    name = esc(info.get("name", "کاربر ناشناس"))
    report_parts.append(f"👤 *نام:* {name}")

    # یادداشت ادمین
    if db_user and db_user.get('admin_note'):
        note = esc(db_user['admin_note'])
        report_parts.append(f"🗒️ *یادداشت:* {note}")

    report_parts.append("")  # فاصله

    h_info = info.get('breakdown', {}).get('hiddify')
    m_info = info.get('breakdown', {}).get('marzban')

    def panel_block(panel_info, country, flag):
        status = "فعال 🟢" if panel_info.get('is_active') else "غیرفعال 🔴"
        panel_header = f"*{country}* {flag}  \\(وضعیت : {status}\\)"
        limit = esc(f"{panel_info.get('usage_limit_GB', 0):g}".replace('.', ','))
        usage = esc(f"{panel_info.get('current_usage_GB', 0):g}".replace('.', ','))
        remaining = esc(f"{panel_info.get('usage_limit_GB', 0) - panel_info.get('current_usage_GB', 0):g}".replace('.', ','))
        last_online = esc(to_shamsi(panel_info.get('last_online'), include_time=True))

        return [
            panel_header,
            f"🗂️ *حجم کل :* {limit} GB",
            f"🔥 *مصرف شده :* {usage} GB",
            f"📥 *باقی‌مانده :* {remaining} GB",
            f"⏰ *آخرین اتصال :* {last_online}",
            ""
        ]

    if h_info:
        report_parts += panel_block(h_info, "آلمان", "🇩🇪")
    if m_info:
        report_parts += panel_block(m_info, "فرانسه", "🇫🇷")

    # انقضا
    expire_days = info.get("expire")
    if expire_days is not None:
        expire_label = esc(f"{int(expire_days)} روز" if int(expire_days) >= 0 else "منقضی شده")
        report_parts.append(f"📅 *انقضا :* {expire_label}")

    # UUID
    if info.get('uuid'):
        uuid = esc(info['uuid'])
        report_parts.append(f"🔑 *شناسه یکتا :* `{uuid}`")

    return "\n".join(report_parts).strip()



def fmt_users_list(users: list, list_type: str, page: int) -> str:
    title_map = {
        'active': "✅ Active Users \\(last 24h\\)",
        'inactive': "⏳ Inactive Users \\(1\\-7 days\\)",
        'never_connected': "🚫 Never Connected Users"
    }
    title = title_map.get(list_type, "Users List")

    if not users:
        return f"*{title}*\n\nNo users found in this category."

    header_text = f"*{title}*"
    if len(users) > settings.get('PAGE_SIZE', 15):
        total_pages = (len(users) + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        pagination_text = f"\\(Page {page + 1} of {total_pages} \\| Total: {len(users)}\\)"
        header_text += f"\n{pagination_text}"

    lines = [header_text]

    start_index = page * settings.get('PAGE_SIZE', 15)
    paginated_users = users[start_index : start_index + settings.get('PAGE_SIZE', 15)]
    separator = " \\| "

    for user in paginated_users:
        name = escape_markdown(user.get('name', 'N/A'))
        line = f"• *{name}*"

        if list_type == 'active':
            last_online_str = to_shamsi(user.get('last_online')).split(' ')[0]
            usage_p = user.get('usage_percentage', 0)
            usage_p_str = f"{usage_p:.0f}"
            line += f"{separator}{escape_markdown(last_online_str)}{separator}{usage_p_str}%"

        elif list_type == 'inactive':
            last_online_str = format_relative_time(user.get('last_online'))
            status = "expired" if user.get('expire', 0) < 0 else "active"
            line += f"{separator}{escape_markdown(last_online_str)}{separator}{status}"

        elif list_type == 'never_connected':
            limit_gb = user.get('usage_limit_GB', 0)
            limit_gb_str = f"{limit_gb:g}"
            
            expire_days = user.get("expire")
            expire_text = "unlimited"
            if expire_days is not None:
                expire_text = f"{expire_days} days" if expire_days >= 0 else "expired"
            
            line += f"{separator}{limit_gb_str} GB{separator}{escape_markdown(expire_text)}"

        lines.append(line)

    return "\n".join(lines)


def fmt_online_users_list(users: list, page: int) -> str:
    # <<<< اصلاح ۱: پرانتزها در عنوان به صورت دستی escape شدند >>>>
    title = "⚡️ کاربران آنلاین \\(۳ دقیقه اخیر\\)"

    if not users:
        return f"*{title}*\n\nهیچ کاربری در این لحظه آنلاین نیست."

    header_text = f"*{title}*"
    if len(users) > settings.get('PAGE_SIZE', 15):
        total_pages = (len(users) + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        # <<<< اصلاح ۱: پرانتز و خط جداکننده در شماره صفحه هم escape شدند >>>>
        pagination_text = f"\\(صفحه {page + 1} از {total_pages} \\| کل: {len(users)}\\)"
        header_text += f"\n{pagination_text}"

    paginated_users = users[page * settings.get('PAGE_SIZE', 15) : (page + 1) * settings.get('PAGE_SIZE', 15)]
    user_lines = []
    # <<<< اصلاح ۲: کاراکتر | به درستی escape شد >>>>
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
    if total_users > settings.get('PAGE_SIZE', 15):
        total_pages = (total_users + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        pagination_text = f"(صفحه {page + 1} از {total_pages} | کل: {total_users})"
        header_text += f"\n{escape_markdown(pagination_text)}"

    lines = [header_text]
    start_index = page * settings.get('PAGE_SIZE', 15)
    paginated_users = bot_users[start_index : start_index + settings.get('PAGE_SIZE', 15)]

    for user in paginated_users:
        first_name = user.get('first_name') or 'ناشناس'
        username = user.get('username')
        user_id = user.get('user_id') or user.get('id')

        if username:  # اگر یوزرنیم داشت
            # یوزرنیم باید escape نشه، فقط اسم escape بشه
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
    disabled_users = escape_markdown(str(info.get('users_disabled', 0)))
    expired_users = escape_markdown(str(info.get('users_expired', 0)))

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
    if len(users) > settings.get('PAGE_SIZE', 15):
        total_pages = (len(users) + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        pagination_text = f"\\(صفحه {page + 1} از {total_pages} \\| کل: {len(users)}\\)"
        header_text += f"\n{pagination_text}"

    user_lines = [header_text]
    paginated_users = users[page * settings.get('PAGE_SIZE', 15) : (page + 1) * settings.get('PAGE_SIZE', 15)]
    separator = " \\| "

    for user in paginated_users:
        name = escape_markdown(user.get('name', 'کاربر ناشناس'))

        h_info = user.get('breakdown', {}).get('hiddify')
        m_info = user.get('breakdown', {}).get('marzban')
        
        panel_usage_parts = []
        
        # <<<<<<<<<<<<<<<< تغییر اصلی اینجاست >>>>>>>>>>>>>>>>
        if h_info:
            # روندن کردن به ۲ رقم اعشار و حذف .00 برای اعداد صحیح
            h_usage_gb = f"{h_info.get('current_usage_GB', 0.0):.2f}".replace('.00', '')
            h_limit_gb = f"{h_info.get('usage_limit_GB', 0.0):.2f}".replace('.00', '')
            panel_usage_parts.append(f"🇩🇪 `{h_usage_gb}/{h_limit_gb} GB`")

        if m_info:
            m_usage_gb = f"{m_info.get('current_usage_GB', 0.0):.2f}".replace('.00', '')
            m_limit_gb = f"{m_info.get('usage_limit_GB', 0.0):.2f}".replace('.00', '')
            panel_usage_parts.append(f"🇫🇷 `{m_usage_gb}/{m_limit_gb} GB`")
        # <<<<<<<<<<<<<<<< پایان تغییر اصلی >>>>>>>>>>>>>>>>

        usage_str = separator.join(panel_usage_parts)
        line = f"`•` *{name}*{separator}{usage_str}"
        user_lines.append(line)

    return "\n".join(user_lines)

def fmt_user_payment_history(payments: list, user_name: str, page: int) -> str:
    title = f"سابقه پرداخت‌های کاربر: {escape_markdown(user_name)}"

    if not payments:
        return f"*{escape_markdown(title)}*\n\nهیچ پرداخت ثبت‌شده‌ای برای این کاربر یافت نشد."

    header_text = f"*{title}*"
    if len(payments) > settings.get('PAGE_SIZE', 15):
        total_pages = (len(payments) + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        pagination_text = f"(صفحه {page + 1} از {total_pages} | کل: {len(payments)})"
        header_text += f"\n{pagination_text}"

    lines = [header_text]
    paginated_payments = payments[page * settings.get('PAGE_SIZE', 15) : (page + 1) * settings.get('PAGE_SIZE', 15)]

    for i, payment in enumerate(paginated_payments, start=page * settings.get('PAGE_SIZE', 15) + 1):
        shamsi_datetime = to_shamsi(payment.get('payment_date'), include_time=True)
        lines.append(f"`{i}.` 💳 تاریخ ثبت: `{shamsi_datetime}`")

    return "\n".join(lines)

# توابع زیر بدون تغییر باقی می‌مانند چون از قبل فارسی و صحیح بودند

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
    list_bullet = "- "
    
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

def fmt_top_consumers(users: list, page: int) -> str:
    title = "پرمصرف‌ترین کاربران"
    if not users:
        return f"🏆 *{escape_markdown(title)}*\n\nهیچ کاربری برای نمایش وجود ندارد."

    header_text = f"🏆 *{escape_markdown(title)}*"
    if len(users) > settings.get('PAGE_SIZE', 15):
        total_pages = (len(users) + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        pagination_text = f"(صفحه {page + 1} از {total_pages} | کل: {len(users)})"
        header_text += f"\n{pagination_text}"

    lines = [header_text]
    paginated_users = users[page * settings.get('PAGE_SIZE', 15) : (page + 1) * settings.get('PAGE_SIZE', 15)]
    separator = escape_markdown(" | ")

    for i, user in enumerate(paginated_users, start=page * settings.get('PAGE_SIZE', 15) + 1):
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

    if len(users) > settings.get('PAGE_SIZE', 15):
        total_pages = (len(users) + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        pagination_text = f"(صفحه {page + 1} از {total_pages} | کل : {len(users)})"
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

        lines.append(f"🎂 *{name}*{separator}`{shamsi_str}`{separator}مانده: {escape_markdown(days_str)}")

    return "\n".join(lines)


def fmt_panel_users_list(users: list, panel_name: str, page: int) -> str:
    title = f"کاربران پنل {panel_name}"
    if not users:
        return f"*{escape_markdown(title)}*\n\nهیچ کاربری در این پنل یافت نشد."

    header_text = f"*{title}*"
    if len(users) > settings.get('PAGE_SIZE', 15):
        total_pages = (len(users) + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        pagination_text = f"(صفحه {page + 1} از {total_pages} | کل: {len(users)})"
        header_text += f"\n{pagination_text}"

    user_lines = []
    paginated_users = users[page * settings.get('PAGE_SIZE', 15) : (page + 1) * settings.get('PAGE_SIZE', 15)]
    separator = escape_markdown(" | ")

    for user in paginated_users:
        name = escape_markdown(user.get('name', 'کاربر ناشناس'))
        expire_days = user.get("expire")
        expire_text = "نامحدود"
        if expire_days is not None:
            expire_text = f"{expire_days} روز" if expire_days >= 0 else "منقضی"

        line = f"`•` *{name}*{separator}{EMOJIS['calendar']} اعتبار: {escape_markdown(expire_text)}"
        user_lines.append(line)

    body_text = "\n".join(user_lines)
    return f"{header_text}\n\n{body_text}"


def fmt_payments_report_list(payments: list, page: int) -> str:
    title = "گزارش آخرین پرداخت کاربران"

    if not payments:
        return f"*{escape_markdown(title)}*\n\nهیچ پرداخت ثبت‌شده‌ای یافت نشد."

    header_text = f"*{title}*"
    if len(payments) > settings.get('PAGE_SIZE', 15):
        total_pages = (len(payments) + settings.get('PAGE_SIZE', 15) - 1) // settings.get('PAGE_SIZE', 15)
        pagination_text = f"(صفحه {page + 1} از {total_pages} | کل: {len(payments)})"
        header_text += f"\n{pagination_text}"

    lines = [header_text]
    paginated_payments = payments[page * settings.get('PAGE_SIZE', 15) : (page + 1) * settings.get('PAGE_SIZE', 15)]

    for i, payment in enumerate(paginated_payments, start=page * settings.get('PAGE_SIZE', 15) + 1):
        name = escape_markdown(payment.get('name', 'کاربر ناشناس'))
        shamsi_date = to_shamsi(payment.get('payment_date')).split(' ')[0]

        line = f"`{i}.` *{name}* `|` 💳 آخرین پرداخت: `{shamsi_date}`"
        lines.append(line)

    return "\n".join(lines)