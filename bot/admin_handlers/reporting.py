import logging
from datetime import datetime, timedelta
import pytz
import jdatetime
from telebot import types
from .. import combined_handler
from ..database import db
from ..menu import menu
from ..admin_formatters import (
    fmt_users_list, fmt_panel_users_list, fmt_online_users_list,
    fmt_top_consumers, fmt_bot_users_list, fmt_birthdays_list,
    fmt_marzban_system_stats,
    fmt_payments_report_list, fmt_admin_quick_dashboard, fmt_hiddify_panel_info
)
from ..user_formatters import fmt_user_report, fmt_user_weekly_report
from ..utils import _safe_edit, escape_markdown
from ..hiddify_api_handler import HiddifyAPIHandler
from ..marzban_api_handler import MarzbanAPIHandler
from ..config import WELCOME_MESSAGE_DELAY_HOURS

logger = logging.getLogger(__name__)
bot = None

def initialize_reporting_handlers(b):
    global bot
    bot = b

def handle_reports_menu(call, params):
    _safe_edit(call.from_user.id, call.message.message_id, "📜 *گزارش گیری*", reply_markup=menu.admin_reports_menu())

def handle_panel_specific_reports_menu(call, params):
    panel_type = params[0]
    panel_name = "Hiddify" if panel_type == "hiddify" else "Marzban"
    _safe_edit(call.from_user.id, call.message.message_id, f"📜 *گزارش‌های پنل‌های نوع {panel_name}*", reply_markup=menu.admin_panel_specific_reports_menu(panel_type))

def handle_health_check(call, params):
    """وضعیت اولین پنل فعال Hiddify را بررسی و نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    _safe_edit(uid, msg_id, escape_markdown("⏳ در حال بررسی وضعیت پنل Hiddify..."))
    back_to_status_menu = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin:system_status_menu"))

    try:
        active_hiddify_panel = next((p for p in db.get_active_panels() if p['panel_type'] == 'hiddify'), None)
        
        if not active_hiddify_panel:
            _safe_edit(uid, msg_id, escape_markdown("❌ هیچ پنل Hiddify فعالی یافت نشد."), reply_markup=back_to_status_menu)
            return

        handler = HiddifyAPIHandler(active_hiddify_panel)
        info = handler.get_panel_info()
        
        if info:
            text = fmt_hiddify_panel_info(info)
        else:
            text = escape_markdown(f"❌ امکان دریافت اطلاعات از پنل «{active_hiddify_panel['name']}» وجود ندارد.")
            
        _safe_edit(uid, msg_id, text, reply_markup=back_to_status_menu)

    except Exception as e:
        logger.error(f"Error in handle_health_check: {e}", exc_info=True)
        _safe_edit(uid, msg_id, escape_markdown("خطایی در هنگام بررسی وضعیت رخ داد."), reply_markup=back_to_status_menu)

def handle_marzban_system_stats(call, params):
    """آمار سیستم اولین پنل فعال Marzban را نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    _safe_edit(uid, msg_id, escape_markdown("⏳ در حال دریافت آمار از پنل Marzban..."))

    back_to_status_menu = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin:system_status_menu"))

    try:
        active_marzban_panel = next((p for p in db.get_active_panels() if p['panel_type'] == 'marzban'), None)
        
        if not active_marzban_panel:
            _safe_edit(uid, msg_id, escape_markdown("❌ هیچ پنل Marzban فعالی یافت نشد."), reply_markup=back_to_status_menu)
            return

        handler = MarzbanAPIHandler(active_marzban_panel)
        info = handler.get_system_stats()
        
        if info:
            text = fmt_marzban_system_stats(info)
        else:
            text = escape_markdown(f"❌ امکان دریافت اطلاعات از پنل «{active_marzban_panel['name']}» وجود ندارد.")
            
        _safe_edit(uid, msg_id, text, reply_markup=back_to_status_menu)

    except Exception as e:
        logger.error(f"Error in handle_marzban_system_stats: {e}", exc_info=True)
        _safe_edit(uid, msg_id, escape_markdown("خطایی در هنگام دریافت آمار رخ داد."), reply_markup=back_to_status_menu)

def handle_paginated_list(call, params):
    list_type, page = params[0], int(params[-1])
    panel_type = params[1] if len(params) > 2 else None
    
    _safe_edit(call.from_user.id, call.message.message_id, escape_markdown("⏳ در حال دریافت و پردازش اطلاعات..."), reply_markup=None)

    all_users_combined = combined_handler.get_all_users_combined()
    
    users_to_process = []
    if panel_type:
        all_panels_map = {p['name']: p['panel_type'] for p in db.get_all_panels()}
        for user in all_users_combined:
            for panel_name in user.get('breakdown', {}).keys():
                if all_panels_map.get(panel_name) == panel_type:
                    users_to_process.append(user)
                    break 
    else:
        users_to_process = all_users_combined

    users = []
    now_utc = datetime.now(pytz.utc)

    if list_type == "panel_users": 
        users = users_to_process
    elif list_type == "online_users":
        deadline = now_utc - timedelta(minutes=3)
        online_users = [u for u in users_to_process if u.get('is_active') and u.get('last_online') and isinstance(u.get('last_online'), datetime) and u['last_online'].astimezone(pytz.utc) >= deadline]
        for user in online_users:
            if user.get('uuid'):
                user['daily_usage_GB'] = sum(db.get_usage_since_midnight_by_uuid(user['uuid']).values())
        users = online_users
    elif list_type == "active_users":
        deadline = now_utc - timedelta(days=1)
        users = [u for u in users_to_process if u.get('last_online') and isinstance(u.get('last_online'), datetime) and u['last_online'].astimezone(pytz.utc) >= deadline]
    elif list_type == "inactive_users":
        users = [u for u in users_to_process if u.get('last_online') and isinstance(u.get('last_online'), datetime) and 1 <= (now_utc - u['last_online'].astimezone(pytz.utc)).days < 7]
    elif list_type == "never_connected": 
        users = [u for u in users_to_process if not u.get('last_online')]
    elif list_type == "top_consumers":
        sorted_users = sorted(users_to_process, key=lambda u: u.get('current_usage_GB', 0), reverse=True)
        users = sorted_users[:100]
    elif list_type == "bot_users": 
        users = db.get_all_bot_users()
    elif list_type == "birthdays": 
        users = db.get_users_with_birthdays()
    elif list_type == "payments":
        users = db.get_all_payments_with_user_info()

    list_configs = {
        "panel_users": {"format": lambda u, pg, p_type: fmt_panel_users_list(u, "Hiddify" if p_type == "hiddify" else "Marzban", pg), "back": "panel_reports"},
        "online_users": {"format": fmt_online_users_list, "back": "panel_reports"},
        "active_users": {"format": lambda u, pg, p_type: fmt_users_list(u, 'active', pg), "back": "panel_reports"},
        "inactive_users": {"format": lambda u, pg, p_type: fmt_users_list(u, 'inactive', pg), "back": "panel_reports"},
        "never_connected": {"format": lambda u, pg, p_type: fmt_users_list(u, 'never_connected', pg), "back": "panel_reports"},
        "top_consumers": {"format": fmt_top_consumers, "back": "reports_menu"},
        "bot_users": {"format": fmt_bot_users_list, "back": "reports_menu"},
        "birthdays": {"format": fmt_birthdays_list, "back": "reports_menu"},
        "payments": {"format": fmt_payments_report_list, "back": "reports_menu"},
    }
    
    config = list_configs.get(list_type)
    if not config: return
    
    try: text = config["format"](users, page, panel_type)
    except TypeError: text = config["format"](users, page)
    
    base_cb = f"admin:list:{list_type}" + (f":{panel_type}" if panel_type else "")
    back_cb = ""
    if list_type == "panel_users":
        back_cb = f"admin:manage_panel:{panel_type}"
    elif config['back'] == "panel_reports":
        back_cb = f"admin:panel_reports:{panel_type}"
    else:
        back_cb = f"admin:{config['back']}"

    kb = menu.create_pagination_menu(base_cb, page, len(users), back_cb, call.from_user.language_code)
    _safe_edit(call.from_user.id, call.message.message_id, text, reply_markup=kb)

def handle_report_by_plan_selection(call, params):
    uid, msg_id = call.from_user.id, call.message.message_id
    prompt = "لطفاً پلنی که می‌خواهید کاربران آن را مشاهده کنید، انتخاب نمایید:"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_select_plan_for_report_menu())

def _find_users_matching_plan_specs(all_users, plan_specs_set, invert_match=False):
    filtered_users = []
    for user in all_users:

        user_vol_de = 0
        user_vol_fr = 0
        for panel_name, panel_data in user.get('breakdown', {}).items():
            if 'germany' in panel_name.lower():
                user_vol_de += panel_data.get('usage_limit_GB', 0)
            elif 'france' in panel_name.lower():
                user_vol_fr += panel_data.get('usage_limit_GB', 0)
        
        user_spec = (user_vol_de, user_vol_fr)
        is_match = user_spec in plan_specs_set
        
        if (invert_match and not is_match) or (not invert_match and is_match):
            filtered_users.append(user)
    return filtered_users

def handle_list_users_by_plan(call, params):
    bot.answer_callback_query(call.id, "گزارش بر اساس پلن در حال بازبینی برای سیستم جدید است.")

def handle_list_users_no_plan(call, params):
    bot.answer_callback_query(call.id, "گزارش بر اساس پلن در حال بازبینی برای سیستم جدید است.")

def handle_quick_dashboard(call, params):
    uid, msg_id = call.from_user.id, call.message.message_id
    _safe_edit(uid, msg_id, escape_markdown("⏳ در حال محاسبه آمار داشبورد..."))

    try:
        all_users_data = combined_handler.get_all_users_combined()
        
        stats = {
            "total_users": len(all_users_data), "active_users": 0, "online_users": 0,
            "expiring_soon_count": 0, "total_usage_today_gb": 0, "new_users_last_24h_count": 0
        }
        now_utc = datetime.now(pytz.utc)
        
        for user in all_users_data:
            if user.get('uuid'):
                daily_usage = db.get_usage_since_midnight_by_uuid(user['uuid'])
                stats['total_usage_today_gb'] += sum(daily_usage.values())
                
                db_user = db.get_user_uuid_record(user['uuid'])
                if db_user and db_user.get('created_at'):
                    created_at_dt = db_user['created_at']
                    if (now_utc - created_at_dt.astimezone(pytz.utc)).days < 1:
                        stats['new_users_last_24h_count'] += 1

            if user.get('is_active'):
                stats['active_users'] += 1
            
            last_online = user.get('last_online')
            if last_online and isinstance(last_online, datetime) and (now_utc - last_online.astimezone(pytz.utc)).total_seconds() < 180:
                stats['online_users'] += 1

            expire_days = user.get('expire')
            if expire_days is not None and 0 <= expire_days <= 7:
                stats['expiring_soon_count'] += 1
        
        stats['total_usage_today'] = f"{stats['total_usage_today_gb']:.2f} GB"
        
        text = fmt_admin_quick_dashboard(stats)
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔄 بروزرسانی", callback_data="admin:quick_dashboard"), types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin:panel"))
        _safe_edit(uid, msg_id, text, reply_markup=kb)

    except Exception as e:
        logger.error(f"Failed to generate quick dashboard: {e}", exc_info=True)
        _safe_edit(uid, msg_id, "❌ خطا در تولید داشبورد", reply_markup=menu.admin_panel())

def handle_test_report_command(message: types.Message):
    """Handles the /test_report <user_id> command for admins, checking user settings."""
    admin_id = message.from_user.id
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "فرمت دستور اشتباه است. لطفاً به این شکل استفاده کنید:\n`/test_report USER_ID`", parse_mode="MarkdownV2")
            return
        
        target_user_id = int(parts[1])
        
        # --- FIX: Check user settings and escape the warning message ---
        user_settings = db.get_user_settings(target_user_id)
        if not user_settings.get('daily_reports', True):
            warning_text = f"⚠️ کاربر `{target_user_id}` دریافت گزارش روزانه را غیرفعال کرده است. پیامی ارسال نشد."
            bot.send_message(admin_id, escape_markdown(warning_text), parse_mode="MarkdownV2")
            return
        # --- END OF FIX ---

        bot.send_message(admin_id, f"⏳ در حال ساخت و ارسال گزارش روزانه تستی برای کاربر `{target_user_id}`\\.\\.\\.", parse_mode="MarkdownV2")

        all_users_info_from_api = combined_handler.get_all_users_combined()
        user_info_map = {user['uuid']: user for user in all_users_info_from_api}
        
        user_uuids_from_db = db.uuids(target_user_id)
        if not user_uuids_from_db:
            bot.send_message(admin_id, f"❌ کاربری با شناسه `{target_user_id}` در دیتابیس ربات یافت نشد\\.", parse_mode="MarkdownV2")
            return
            
        user_infos_for_report = []
        for u_row in user_uuids_from_db:
            if u_row['uuid'] in user_info_map:
                user_data = user_info_map[u_row['uuid']]
                user_data['db_id'] = u_row['id']
                user_infos_for_report.append(user_data)

        if not user_infos_for_report:
            bot.send_message(admin_id, f"❌ اکانت فعالی برای کاربر `{target_user_id}` در پنل‌ها یافت نشد\\.", parse_mode="MarkdownV2")
            return
            
        tehran_tz = pytz.timezone("Asia/Tehran")
        now_gregorian = datetime.now(tehran_tz)
        now_shamsi = jdatetime.datetime.fromgregorian(datetime=now_gregorian)
        now_str = now_shamsi.strftime("%Y/%m/%d - %H:%M")
        separator = '\n' + '─' * 18 + '\n'

        header = f"🧪 *گزارش تستی* {escape_markdown('-')} {escape_markdown(now_str)}{separator}"
        lang_code = db.get_user_language(target_user_id)
        report_text = fmt_user_report(user_infos_for_report, lang_code)
        
        # Send to admin first
        bot.send_message(admin_id, header + report_text, parse_mode="MarkdownV2")
        # Then send to the target user
        sent_message = bot.send_message(target_user_id, header + report_text, parse_mode="MarkdownV2")
        
        # --- FIX: Log the sent message for auto-deletion ---
        if sent_message:
            db.add_sent_report(target_user_id, sent_message.message_id)
        # --- END OF FIX ---
        
        bot.send_message(admin_id, "✅ گزارش با موفقیت به ادمین و کاربر ارسال شد\\.", parse_mode="MarkdownV2")

    except ValueError:
        bot.reply_to(message, "❌ شناسه کاربر باید یک عدد باشد\\.", parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Error in handle_test_report_command for user_id {message.text.split()[1] if len(message.text.split()) > 1 else 'N/A'}: {e}", exc_info=True)
        bot.send_message(admin_id, f"❌ خطایی در هنگام ساخت گزارش رخ داد: `{escape_markdown(str(e))}`", parse_mode="MarkdownV2")

def handle_test_weekly_report_command(message: types.Message):
    """Handles the /test_weekly_report <user_id> command for admins, checking user settings."""
    admin_id = message.from_user.id
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "فرمت دستور اشتباه است. لطفاً به این شکل استفاده کنید:\n`/test_weekly_report USER_ID`", parse_mode="MarkdownV2")
            return
        
        target_user_id = int(parts[1])

        # --- FIX: Check user settings and escape the warning message ---
        user_settings = db.get_user_settings(target_user_id)
        if not user_settings.get('weekly_reports', True):
            warning_text = f"⚠️ کاربر `{target_user_id}` دریافت گزارش هفتگی را غیرفعال کرده است. پیامی ارسال نشد."
            bot.send_message(admin_id, escape_markdown(warning_text), parse_mode="MarkdownV2")
            return
        # --- END OF FIX ---
        
        bot.send_message(admin_id, f"⏳ در حال ساخت و ارسال گزارش هفتگی تستی برای کاربر `{target_user_id}`\\.\\.\\.", parse_mode="MarkdownV2")

        all_users_info_from_api = combined_handler.get_all_users_combined()
        user_info_map = {user['uuid']: user for user in all_users_info_from_api}
        
        user_uuids_from_db = db.uuids(target_user_id)
        if not user_uuids_from_db:
            bot.send_message(admin_id, f"❌ کاربری با شناسه `{target_user_id}` در دیتابیس ربات یافت نشد\\.", parse_mode="MarkdownV2")
            return
            
        user_infos_for_report = []
        for u_row in user_uuids_from_db:
            if u_row['uuid'] in user_info_map:
                user_infos_for_report.append(user_info_map[u_row['uuid']])

        if not user_infos_for_report:
            bot.send_message(admin_id, f"❌ اکانت فعالی برای کاربر `{target_user_id}` در پنل‌ها یافت نشد\\.", parse_mode="MarkdownV2")
            return
            
        tehran_tz = pytz.timezone("Asia/Tehran")
        now_gregorian = datetime.now(tehran_tz)
        now_shamsi = jdatetime.datetime.fromgregorian(datetime=now_gregorian)
        now_str = now_shamsi.strftime("%Y/%m/%d - %H:%M")
        separator = '\n' + '─' * 18 + '\n'

        header = f"📊 *گزارش هفتگی* {escape_markdown('-')} {escape_markdown(now_str)}{separator}"
        lang_code = db.get_user_language(target_user_id)
        report_text = fmt_user_weekly_report(user_infos_for_report, lang_code)
        
        bot.send_message(admin_id, header + report_text, parse_mode="MarkdownV2")
        sent_message = bot.send_message(target_user_id, header + report_text, parse_mode="MarkdownV2")

        # --- FIX: Log the sent message for auto-deletion ---
        if sent_message:
            db.add_sent_report(target_user_id, sent_message.message_id)
        # --- END OF FIX ---
        
        bot.send_message(admin_id, "✅ گزارش هفتگی تستی با موفقیت به ادمین و کاربر ارسال شد\\.", parse_mode="MarkdownV2")

    except ValueError:
        bot.reply_to(message, "❌ شناسه کاربر باید یک عدد باشد\\.", parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Error in handle_test_weekly_report_command for user_id {message.text.split()[1] if len(message.text.split()) > 1 else 'N/A'}: {e}", exc_info=True)
        bot.send_message(admin_id, f"❌ خطایی در هنگام ساخت گزارش رخ داد: `{escape_markdown(str(e))}`", parse_mode="MarkdownV2")

# nzrmohammad/vpanel-manager/VPanel-Manager-aa3b4f7623a793527cfa3d33f8968c1f80909dbb/bot/admin_handlers/reporting.py

def handle_test_welcome_message_command(message: types.Message):
    """Handles the /test_welcome <user_id> command for admins."""
    admin_id = message.from_user.id
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "فرمت دستور اشتباه است\\. لطفاً به این شکل استفاده کنید:\n`/test_welcome USER_ID`", parse_mode="MarkdownV2")
            return
        
        target_user_id = int(parts[1])

        user_uuids = db.uuids(target_user_id)
        if not user_uuids:
            bot.send_message(admin_id, f"❌ کاربری با شناسه تلگرام `{target_user_id}` یافت نشد یا هیچ اکانتی ثبت نکرده است\\.", parse_mode="MarkdownV2")
            return
        
        uuid_id_to_test = user_uuids[0]['id']

        db.set_first_connection_time(uuid_id_to_test, datetime.now(pytz.utc))
        db.reset_welcome_message_sent(uuid_id_to_test)
        
        status_message = f"⏳ در حال آماده‌سازی و ارسال پیام خوش‌آمدگویی تستی برای کاربر `{target_user_id}`\\.\\.\\."
        bot.send_message(admin_id, status_message, parse_mode="MarkdownV2")

        # --- ✅ FIX: Manually escape problematic characters but keep markdown styles ---
        final_message_for_user = (
            "🎉 *به جمع ما خوش آمدی\\!* 🎉\n\n"
            "از اینکه به ما اعتماد کردی خوشحالیم\\. امیدواریم از کیفیت سرویس لذت ببری\\.\n\n"
            "💬 در صورت داشتن هرگونه سوال یا نیاز به پشتیبانی، ما همیشه در کنار شما هستیم\\.\n\n"
            "با آرزوی بهترین‌ها ✨"
        )
        
        admin_header = escape_markdown(f"نمونه پیام خوشامدگویی برای کاربر {target_user_id}:")
        final_message_for_admin = f"*{admin_header}*\n\n{final_message_for_user}"

        try:
            bot.send_message(admin_id, final_message_for_admin, parse_mode="MarkdownV2")
            bot.send_message(target_user_id, final_message_for_user, parse_mode="MarkdownV2")
            db.mark_welcome_message_as_sent(uuid_id_to_test)
            bot.send_message(admin_id, f"✅ پیام خوش‌آمدگویی با موفقیت به کاربر `{target_user_id}` ارسال شد و وضعیت در دیتابیس ثبت گردید\\.", parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"Failed to send welcome message to user {target_user_id} during test: {e}", exc_info=True)
            # FIX: Also escape the error message being sent to the admin
            error_text = f"❌ خطا در ارسال پیام به کاربر: `{escape_markdown(str(e))}`"
            bot.send_message(admin_id, error_text, parse_mode="MarkdownV2")

    except ValueError:
        bot.reply_to(message, "❌ شناسه کاربر باید یک عدد باشد\\.", parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Error in handle_test_welcome_message_command for user_id {message.text.split()[1] if len(message.text.split()) > 1 else 'N/A'}: {e}", exc_info=True)
        bot.send_message(admin_id, f"❌ خطایی در هنگام اجرای تست رخ داد: `{escape_markdown(str(e))}`", parse_mode="MarkdownV2")