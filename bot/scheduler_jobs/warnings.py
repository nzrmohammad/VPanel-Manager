import logging
from datetime import datetime, timedelta
import pytz
from telebot import types, apihelper

from bot import combined_handler
from bot.database import db
from bot.utils import escape_markdown, format_daily_usage
from bot.config import (
    ADMIN_IDS, EMOJIS, WELCOME_MESSAGE_DELAY_HOURS,
    WARNING_DAYS_BEFORE_EXPIRY, WARNING_USAGE_THRESHOLD,
    DAILY_USAGE_ALERT_THRESHOLD_GB
)

logger = logging.getLogger(__name__)

def send_warning_message(bot, user_id: int, message_template: str, reply_markup: types.InlineKeyboardMarkup = None, **kwargs):
    """
    یک پیام هشدار را با فرمت صحیح MarkdownV2 برای کاربر ارسال می‌کند.
    """
    try:
        kwargs_escaped = {k: escape_markdown(str(v)) for k, v in kwargs.items()}
        final_message = message_template.format(**kwargs_escaped)

        bot.send_message(user_id, final_message, parse_mode="MarkdownV2", reply_markup=reply_markup)
        return True
    except apihelper.ApiTelegramException as e:
        if "bot was blocked by the user" in e.description or "user is deactivated" in e.description:
            logger.warning(f"SCHEDULER: User {user_id} has blocked the bot or is deactivated. Deactivating all their UUIDs.")
            user_uuids = db.uuids(user_id)
            for u in user_uuids:
                db.deactivate_uuid(u['id'])
        else:
            if "can't parse entities" in e.description:
                 logger.error(f"Failed to send warning to user {user_id} due to PARSE ERROR. Original message template: '{message_template}'. Final message attempt: '{final_message}'. Error: {e}")
            else:
                 logger.error(f"Failed to send warning message to user {user_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred while sending a warning message to user {user_id}: {e}", exc_info=True)
        return False

def check_for_warnings(bot, target_user_id: int = None) -> None:
    """
    (نسخه نهایی و اصلاح شده)
    به صورت دوره‌ای تمام کاربران را برای شرایط مختلف (شامل منقضی شدن) بررسی کرده و اعلان ارسال می‌کند.
    """
    logger.info("SCHEDULER (Warnings): Starting warnings check job.")
    try:
        active_uuids_list = [row for row in db.all_active_uuids() if not target_user_id or row['user_id'] == target_user_id]
        
        if not active_uuids_list:
            logger.info("SCHEDULER (Warnings): No active users to check.")
            return

        all_users_info_map = {u['uuid']: u for u in combined_handler.get_all_users_combined() if u.get('uuid')}
        
        if not all_users_info_map:
            logger.warning("SCHEDULER (Warnings): Could not fetch any user data from panels. Aborting check.")
            return

        now_utc = datetime.now(pytz.utc)

        for u_row in active_uuids_list:
            try:
                uuid_str = u_row['uuid']
                uuid_id_in_db = u_row['id']
                user_id_in_telegram = u_row['user_id']
                
                info = all_users_info_map.get(uuid_str)
                if not info:
                    logger.warning(f"SCHEDULER (Warnings): User with UUID {uuid_str} found in bot DB but not in panels. Skipping.")
                    continue

                user_settings = db.get_user_settings(user_id_in_telegram)
                uuid_record = db.uuid_by_id(user_id_in_telegram, uuid_id_in_db)
                user_name = info.get('name', 'کاربر ناشناس')
                
                # 1. ارسال پیام خوش‌آمدگویی
                if u_row.get('first_connection_time') and not u_row.get('welcome_message_sent', 0):
                    first_conn_time = pytz.utc.localize(u_row['first_connection_time']) if u_row['first_connection_time'].tzinfo is None else u_row['first_connection_time']
                    if datetime.now(pytz.utc) - first_conn_time >= timedelta(hours=WELCOME_MESSAGE_DELAY_HOURS):
                        welcome_text = (
                            "🎉 *به جمع ما خوش آمدی\\!* 🎉\n\n"
                            "از اینکه به ما اعتماد کردی خوشحالیم\\. امیدواریم از کیفیت سرویس لذت ببری\\.\n\n"
                            "💬 در صورت داشتن هرگونه سوال یا نیاز به پشتیبانی، ما همیشه در کنار شما هستیم\\.\n\n"
                            "با آرزوی بهترین‌ها ✨"
                        )
                        # ✨ ساخت و افزودن دکمه‌های راهنما
                        kb = types.InlineKeyboardMarkup(row_width=2)
                        kb.add(
                            types.InlineKeyboardButton("🛍️ مشاهده سرویس‌ها", callback_data="view_plans"),
                            types.InlineKeyboardButton("💡 راهنمای اتصال", callback_data="get_guideme")
                        )
                        if send_warning_message(bot, user_id_in_telegram, welcome_text, reply_markup=kb):
                            db.mark_welcome_message_as_sent(uuid_id_in_db)
                            db.create_notification(user_id_in_telegram, "خوش آمدید!", "از اینکه به ما اعتماد کردید خوشحالیم. امیدواریم از کیفیت سرویس لذت ببرید.", "info")


                # 2. ارسال یادآوری تمدید
                expire_days = info.get('expire')
                if expire_days == 1 and not u_row.get('renewal_reminder_sent', 0):
                    renewal_text = (
                        f"⏳ *یادآوری تمدید سرویس*\n\n"
                        f"کاربر گرامی، تنها *۱ روز* از اعتبار اکانت *{escape_markdown(user_name)}* شما باقی مانده است\\.\n\n"
                        f"برای جلوگیری از قطع شدن سرویس، لطفاً نسبت به تمدید آن اقدام نمایید\\."
                    )
                    kb = types.InlineKeyboardMarkup(row_width=2)
                    kb.add(
                        types.InlineKeyboardButton("🚀 تمدید سرویس", callback_data="view_plans"),
                        types.InlineKeyboardButton("💳 کیف پول", callback_data="wallet:main")
                    )
                    
                    if bot.send_message(user_id_in_telegram, renewal_text, parse_mode="MarkdownV2", reply_markup=kb):
                        db.set_renewal_reminder_sent(uuid_id_in_db)
                        db.create_notification(user_id_in_telegram, "یادآوری تمدید", f"تنها ۱ روز از اعتبار اکانت «{user_name}» شما باقی مانده است.", "warning")

                # 3. ارسال هشدارهای انقضای اکانت (به تفکیک پنل)
                if user_settings.get('expiry_warnings'):
                    breakdown = info.get('breakdown', {})
                    for panel_name, panel_details in breakdown.items():
                        panel_data = panel_details.get('data', {})
                        panel_type = panel_details.get('type')
                        expire_days = panel_data.get('expire')

                        if expire_days is not None and 1 <= expire_days <= WARNING_DAYS_BEFORE_EXPIRY:
                            # یک شناسه هشدار منحصر به فرد برای هر پنل ایجاد می‌کنیم
                            warning_type_key = f'expiry_{panel_type}'
                            if not db.has_recent_warning(uuid_id_in_db, warning_type_key):
                                server_name = "🇩🇪" if panel_type == 'hiddify' else "🇫🇷🇹🇷🇺🇸🇷🇴🇫🇮🇮🇷"
                                msg_template = (f"{EMOJIS['warning']} *هشدار انقضای اکانت*\n\n"
                                                f"سرویس شما در پنل *{server_name}* تا *{{expire_days}}* روز دیگر منقضی می‌شود\\.")
                                # ✨ ساخت و افزودن دکمه‌ها
                                kb = types.InlineKeyboardMarkup(row_width=2)
                                kb.add(
                                    types.InlineKeyboardButton("🚀 تمدید سرویس", callback_data="view_plans"),
                                    types.InlineKeyboardButton("💳 کیف پول", callback_data="wallet:main")
                                )
                                if send_warning_message(bot, user_id_in_telegram, msg_template, expire_days=str(expire_days), reply_markup=kb):
                                    db.log_warning(uuid_id_in_db, warning_type_key)
                                    db.create_notification(
                                        user_id_in_telegram, 
                                        "هشدار انقضای اکانت", 
                                        f"اکانت شما در سرور {server_name} تا {expire_days} روز دیگر منقضی می‌شود.", 
                                        "warning"
                                    )
                
                # 3.5. ارسال هشدار برای اکانت‌های منقضی شده
                if user_settings.get('expiry_warnings') and expire_days is not None and expire_days <= 0:
                    # برای جلوگیری از ارسال پیام تکراری، هر ۴۸ ساعت یکبار چک می‌کنیم
                    if not db.has_recent_warning(uuid_id_in_db, 'expired', hours=48):
                        msg_template = (f"❗️ *اکانت شما منقضی شده است*\n\n"
                                        f"اعتبار اکانت *{{user_name}}* شما به پایان رسیده است\\.\n\n"
                                        f"برای استفاده مجدد، لطفاً نسبت به تمدید آن اقدام نمایید\\.")
                        # ✨ ساخت دکمه‌های جدید
                        kb = types.InlineKeyboardMarkup(row_width=2)
                        kb.add(
                            types.InlineKeyboardButton("🚀 تمدید سرویس", callback_data="view_plans"),
                            types.InlineKeyboardButton("💳 کیف پول", callback_data="wallet:main")
                        )
                        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🚀 تمدید سرویس", callback_data="view_plans"))
                        if send_warning_message(bot, user_id_in_telegram, msg_template, user_name=user_name, reply_markup=kb):
                            db.log_warning(uuid_id_in_db, 'expired')
                            db.create_notification(user_id_in_telegram, "اکانت منقضی شده", f"اعتبار اکانت «{user_name}» شما به پایان رسیده است.", "warning")


                # --- (جدید) سناریوی ۲: هشدار ادمین برای "کاربر مردد" ---
                # اگر سرویس کاربر همین امروز یا دیروز منقضی شده (0 یا -1 روز)
                # و هنوز تمدید نکرده است، به ادمین اطلاع بده
                if (expire_days is not None and -1 <= expire_days <= 0):
                    # 48 ساعت فرصت می‌دهیم تا کاربر خودش تمدید کند، بعد هشدار می‌دهیم
                    if not db.has_recent_warning(uuid_id_in_db, 'churn_alert_expired', hours=48):
                        # (اختیاری ولی مهم) چک می‌کنیم که در ۲۴ ساعت گذشته تراکنش موفقی نداشته باشد
                        if not db.check_recent_successful_payment(uuid_id_in_db, hours=24):
                            alert_message = (
                                f"⚠️ *هشدار ریزش مشتری \\(مردد\\)*\n\n"
                                f"سرویس کاربر *{escape_markdown(user_name)}* \\(`{escape_markdown(str(user_id_in_telegram))}`\\) *دیروز/امروز* منقضی شده و هنوز تمدید نکرده است\\.\n\n"
                                f"این بهترین زمان برای ارسال یک پیشنهاد تخفیف و بازگرداندن اوست\\."
                            )
                            kb_admin = types.InlineKeyboardMarkup(row_width=2)
                            kb_admin.add(
                                types.InlineKeyboardButton("👤 مشاهده کاربر", callback_data=f"admin:us:h:{uuid_str}"), # 'h' به عنوان پیش‌فرض
                                types.InlineKeyboardButton("🎁 ارسال پیشنهاد تمدید", callback_data=f"admin:churn_send_offer:{user_id_in_telegram}")
                            )
                            for admin_id in ADMIN_IDS:
                                send_warning_message(bot, admin_id, alert_message, reply_markup=kb_admin)
                            
                            db.log_warning(uuid_id_in_db, 'churn_alert_expired')
                # --- پایان کد جدید ---
                
                # 4. ارسال هشدارهای اتمام حجم
                breakdown = info.get('breakdown', {})
                
                if user_settings.get('data_warning_de'):
                    hiddify_info = next((p.get('data', {}) for p in breakdown.values() if p.get('type') == 'hiddify'), None)
                    if hiddify_info:
                        limit, usage = hiddify_info.get('usage_limit_GB', 0.0), hiddify_info.get('current_usage_GB', 0.0)
                        if limit > 0:
                            usage_percent = (usage / limit) * 100
                            if WARNING_USAGE_THRESHOLD <= usage_percent < 100 and not db.has_recent_warning(uuid_id_in_db, 'low_data_hiddify'):
                                msg = (f"❗️ *هشدار اتمام حجم*\n\nکاربر گرامی، بیش از *{int(WARNING_USAGE_THRESHOLD)}%* از حجم سرویس شما در سرور *آلمان 🇩🇪* مصرف شده است\\.")
                                # ✨ ساخت دکمه‌ها
                                kb = types.InlineKeyboardMarkup(row_width=2)
                                kb.add(
                                    types.InlineKeyboardButton("🚀 تمدید سرویس", callback_data="view_plans"),
                                    types.InlineKeyboardButton("💳 کیف پول", callback_data="wallet:main")
                                )
                                if send_warning_message(bot, user_id_in_telegram, msg, reply_markup=kb):
                                    db.log_warning(uuid_id_in_db, 'low_data_hiddify')
                                    db.create_notification(user_id_in_telegram, "هشدار اتمام حجم", f"بیش از {int(WARNING_USAGE_THRESHOLD)}% از حجم سرویس شما در سرور آلمان 🇩🇪 مصرف شده است.", "warning")
                            if usage >= limit and not hiddify_info.get('is_active') and not db.has_recent_warning(uuid_id_in_db, 'volume_depleted_hiddify'):
                                
                                # --- (جدید) افزودن ۱ گیگ حجم اضطراری ---
                                try:
                                    combined_handler.modify_user_on_all_panels(uuid_str, add_gb=1, target_panel_type='hiddify')
                                    logger.info(f"Added 1GB grace data to user {uuid_str} (Hiddify)")
                                except Exception as e:
                                    logger.error(f"Failed to add grace data to {uuid_str} (Hiddify): {e}")
                                # --- پایان بخش جدید ---

                                msg = (f"🔴 *اتمام حجم*\n\n"
                                       f"حجم سرویس شما در سرور *آلمان 🇩🇪* به پایان رسیده بود\\.\n\n"
                                       f"🎁 *1 گیگابایت* حجم اضطراری برای شما فعال شد تا بتوانید به راحتی سرویس خود را تمدید کنید\\.")
                                
                                # ✨ ساخت دکمه‌ها
                                kb = types.InlineKeyboardMarkup(row_width=2)
                                kb.add(
                                    types.InlineKeyboardButton("🚀 تمدید سرویس", callback_data="view_plans"),
                                    types.InlineKeyboardButton("💳 کیف پول", callback_data="wallet:main")
                                )
                                if send_warning_message(bot, user_id_in_telegram, msg, reply_markup=kb):
                                    db.log_warning(uuid_id_in_db, 'volume_depleted_hiddify')
                                    db.create_notification(user_id_in_telegram, "اتمام حجم", "حجم سرویس شما در سرور آلمان 🇩🇪 به پایان رسیده است.", "warning")
                                    
                marzban_info = next((p.get('data', {}) for p in breakdown.values() if p.get('type') == 'marzban'), None)
                if marzban_info and uuid_record:
                    should_warn_fr = user_settings.get('data_warning_fr') and uuid_record.get('has_access_fr')
                    should_warn_tr = user_settings.get('data_warning_tr') and uuid_record.get('has_access_tr')
                    should_warn_us = user_settings.get('data_warning_us') and uuid_record.get('has_access_us')
                    should_warn_ro = user_settings.get('data_warning_ro') and uuid_record.get('has_access_ro')
                    should_warn_ir = user_settings.get('data_warning_ir') and uuid_record.get('has_access_ir')
                    should_warn_fi = user_settings.get('data_warning_supp') and uuid_record.get('has_access_supp')
                    
                    if should_warn_fr or should_warn_tr or should_warn_us:
                        limit, usage = marzban_info.get('usage_limit_GB', 0.0), marzban_info.get('current_usage_GB', 0.0)
                        if limit > 0:
                            usage_percent = (usage / limit) * 100
                            server_names = []
                            if should_warn_fr: server_names.append("فرانسه 🇫🇷")
                            if should_warn_tr: server_names.append("ترکیه 🇹🇷")
                            if should_warn_us: server_names.append("آمریکا 🇺🇸")
                            if should_warn_ro: server_names.append("رومانی 🇷🇴")
                            if should_warn_ir: server_names.append("ایران 🇮🇷")
                            if should_warn_fi: server_names.append("فنلاند 🇫🇮")
                            server_display_name = " / ".join(server_names)

                            if WARNING_USAGE_THRESHOLD <= usage_percent < 100 and not db.has_recent_warning(uuid_id_in_db, 'low_data_marzban'):
                                msg = (f"❗️ *هشدار اتمام حجم*\n\nکاربر گرامی، بیش از *{int(WARNING_USAGE_THRESHOLD)}%* از حجم سرویس شما در سرور *{server_display_name}* مصرف شده است\\.")
                                # ✨ ساخت دکمه‌ها
                                kb = types.InlineKeyboardMarkup(row_width=2)
                                kb.add(
                                    types.InlineKeyboardButton("🚀 تمدید سرویس", callback_data="view_plans"),
                                    types.InlineKeyboardButton("💳 کیف پول", callback_data="wallet:main")
                                )
                                if send_warning_message(bot, user_id_in_telegram, msg, reply_markup=kb):
                                    db.log_warning(uuid_id_in_db, 'low_data_marzban')
                                    db.create_notification(user_id_in_telegram, "هشدار اتمام حجم", f"بیش از {int(WARNING_USAGE_THRESHOLD)}% از حجم سرویس شما در سرور {server_display_name} مصرف شده است.", "warning")
                                    
                            if usage >= limit and not marzban_info.get('is_active') and not db.has_recent_warning(uuid_id_in_db, 'volume_depleted_marzban'):

                                # --- (جدید) افزودن ۱ گیگ حجم اضطراری ---
                                try:
                                    combined_handler.modify_user_on_all_panels(uuid_str, add_gb=1, target_panel_type='marzban')
                                    logger.info(f"Added 1GB grace data to user {uuid_str} (Marzban)")
                                except Exception as e:
                                    logger.error(f"Failed to add grace data to {uuid_str} (Marzban): {e}")
                                # --- پایان بخش جدید ---

                                msg = (f"🔴 *اتمام حجم*\n\n"
                                       f"حجم سرویس شما در سرور *{server_display_name}* به پایان رسیده بود\\.\n\n"
                                       f"🎁 *1 گیگابایت* حجم اضطراری برای شما فعال شد تا بتوانید به راحتی سرویس خود را تمدید کنید\\.")
                                
                                # ✨ ساخت دکمه‌ها
                                kb = types.InlineKeyboardMarkup(row_width=2)
                                kb.add(
                                    types.InlineKeyboardButton("🚀 تمدید سرویس", callback_data="view_plans"),
                                    types.InlineKeyboardButton("💳 کیف پول", callback_data="wallet:main")
                                )
                                if send_warning_message(bot, user_id_in_telegram, msg, reply_markup=kb):
                                    db.log_warning(uuid_id_in_db, 'volume_depleted_marzban')
                                    db.create_notification(user_id_in_telegram, "اتمام حجم", f"حجم سرویس شما در سرور {server_display_name} به پایان رسیده است.", "warning")

                # 5. ارسال پیام به کاربران غیرفعال
                last_online = info.get('last_online')
                if last_online and isinstance(last_online, datetime):
                    days_inactive = (now_utc.replace(tzinfo=None) - last_online.replace(tzinfo=None)).days
                    if 4 <= days_inactive <= 7 and not db.has_recent_warning(uuid_id_in_db, 'inactive_user_reminder', hours=168):
                        msg = ("حس میکنم نیاز به راهنمایی داری\\!\n\n"
                            "چند روز از آخرین اتصالت میگذره، به نظر میاد نتونستی به اکانت وصل بشی\\. "
                            "اگه روش اتصال رو نمیدونی و یا اشتراک برات کار نکرد، با پشتیبانی در ارتباط باش تا برات حلش کنیم\\.")
                        if send_warning_message(bot, user_id_in_telegram, msg):
                            db.log_warning(uuid_id_in_db, 'inactive_user_reminder')
                            db.create_notification(
                                user_id_in_telegram,
                                "یادآوری عدم فعالیت",
                                "چند روز از آخرین اتصال شما می‌گذرد. در صورت وجود مشکل در اتصال، لطفاً با پشتیبانی تماس بگیرید.",
                                "warning"
                            )
                # --- (جدید) سناریوی ۱: هشدار ادمین برای "ناراضی خاموش" ---
                # اگر کاربر اعتبار دارد (بیش از 3 روز) و حجم دارد (بیش از 1 گیگ)
                # اما بیش از 4 روز است که وصل نشده، به ادمین هشدار بده
                if (expire_days is not None and expire_days > 3 and
                    info.get('remaining_GB', 0.0) > 1 and
                    last_online and isinstance(last_online, datetime)):
                    
                    days_inactive = (now_utc.replace(tzinfo=None) - last_online.replace(tzinfo=None)).days
                    
                    if days_inactive >= 4 and not db.has_recent_warning(uuid_id_in_db, 'churn_alert_inactive', hours=72):
                        remaining_gb_str = f"{info.get('remaining_GB', 0.0):.1f}"
                        alert_message = (
                            f"⚠️ *هشدار ریزش مشتری \\(ناراضی خاموش\\)*\n\n"
                            f"کاربر *{escape_markdown(user_name)}* \\(`{escape_markdown(str(user_id_in_telegram))}`\\) با وجود داشتن اعتبار، *{escape_markdown(str(days_inactive))} روز* است که متصل نشده است\\.\n\n"
                            f"اعتبار: *{escape_markdown(str(expire_days))} روز* \\| حجم باقی‌مانده: *{escape_markdown(remaining_gb_str)} GB*\n\n"
                            f"این کاربر احتمالاً به مشکل خورده و نیاز به پیگیری دارد\\."
                        )
                        kb_admin = types.InlineKeyboardMarkup(row_width=2)
                        kb_admin.add(
                            types.InlineKeyboardButton("👤 مشاهده کاربر", callback_data=f"admin:us:h:{uuid_str}"), # 'h' به عنوان پیش‌فرض پنل
                            types.InlineKeyboardButton("💬 ارسال پیام پیگیری", callback_data=f"admin:churn_contact_user:{user_id_in_telegram}")
                        )
                        for admin_id in ADMIN_IDS:
                            send_warning_message(bot, admin_id, alert_message, reply_markup=kb_admin)
                        
                        db.log_warning(uuid_id_in_db, 'churn_alert_inactive')
                # --- پایان کد جدید ---

                # 6. ارسال هشدار مصرف غیرعادی روزانه به ادمین‌ها
                if DAILY_USAGE_ALERT_THRESHOLD_GB > 0:
                    total_daily_usage = sum(db.get_usage_since_midnight_by_uuid(uuid_str).values())
                    if total_daily_usage >= DAILY_USAGE_ALERT_THRESHOLD_GB and not db.has_recent_warning(uuid_id_in_db, 'unusual_daily_usage_admin_alert', hours=24):
                        alert_message = (f"⚠️ *مصرف غیرعادی روزانه*\n\nکاربر *{escape_markdown(user_name)}* \\(`{escape_markdown(uuid_str)}`\\) "
                                        f"امروز بیش از *{escape_markdown(str(DAILY_USAGE_ALERT_THRESHOLD_GB))} GB* مصرف داشته است\\.\n\n"
                                        f"\\- مجموع مصرف امروز: *{escape_markdown(format_daily_usage(total_daily_usage))}*")
                        for admin_id in ADMIN_IDS:
                            if send_warning_message(bot, admin_id, alert_message):
                                db.create_notification(
                                    admin_id,
                                    "مصرف غیرعادی روزانه",
                                    f"کاربر «{user_name}» امروز بیش از {DAILY_USAGE_ALERT_THRESHOLD_GB} GB مصرف داشته است (مصرف کل: {format_daily_usage(total_daily_usage)}).",
                                    "broadcast"
                                )
                        db.log_warning(uuid_id_in_db, 'unusual_daily_usage_admin_alert')

                # 7. ارسال هشدار تعداد زیاد دستگاه‌ها به ادمین‌ها
                device_count = db.count_user_agents(uuid_id_in_db)
                if device_count > 5 and not db.has_recent_warning(uuid_id_in_db, 'too_many_devices_admin_alert', hours=24):
                    alert_message = (f"⚠️ *تعداد دستگاه بالا*\n\n"
                                    f"کاربر *{escape_markdown(user_name)}* \\(`{escape_markdown(uuid_str)}`\\) "
                                    f"بیش از *۵* دستگاه \\({device_count} دستگاه\\) متصل کرده است\\. احتمال به اشتراک گذاری لینک وجود دارد\\.")
                    for admin_id in ADMIN_IDS:
                        if send_warning_message(bot, admin_id, alert_message):
                            db.create_notification(
                                admin_id,
                                "تعداد دستگاه بالا",
                                f"کاربر «{user_name}» بیش از ۵ دستگاه ({device_count} دستگاه) متصل کرده است. احتمال به اشتراک گذاری لینک وجود دارد.",
                                "broadcast"
                            )
                    db.log_warning(uuid_id_in_db, 'too_many_devices_admin_alert')

            except Exception as e:
                logger.error(f"SCHEDULER (Warnings): Error processing UUID_ID {u_row.get('id', 'N/A')}: {e}", exc_info=True)
    
    except Exception as e:
        logger.error(f"SCHEDULER (Warnings): A critical error occurred during check: {e}", exc_info=True)
    
    logger.info("SCHEDULER (Warnings): Finished warnings check job.")