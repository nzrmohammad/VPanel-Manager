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
    به صورت دوره‌ای تمام کاربران را برای شرایط مختلف بررسی کرده و اعلان ارسال می‌کند.
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
                        if send_warning_message(bot, user_id_in_telegram, welcome_text):
                            db.mark_welcome_message_as_sent(uuid_id_in_db)

                # 2. ارسال یادآوری تمدید
                expire_days = info.get('expire')
                if expire_days == 1 and not u_row.get('renewal_reminder_sent', 0):
                    renewal_text = (
                        f"⏳ *یادآوری تمدید سرویس*\n\n"
                        f"کاربر گرامی، تنها *۱ روز* از اعتبار اکانت *{escape_markdown(user_name)}* شما باقی مانده است\\.\n\n"
                        f"برای جلوگیری از قطع شدن سرویس، لطفاً نسبت به تمدید آن اقدام نمایید\\."
                    )
                    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🚀 مشاهده و تمدید سرویس‌ها", callback_data="view_plans"))
                    if bot.send_message(user_id_in_telegram, renewal_text, parse_mode="MarkdownV2", reply_markup=kb):
                        db.set_renewal_reminder_sent(uuid_id_in_db)

                # 3. ارسال هشدار انقضای اکانت
                if user_settings.get('expiry_warnings') and expire_days is not None and 1 < expire_days <= WARNING_DAYS_BEFORE_EXPIRY:
                    if not db.has_recent_warning(uuid_id_in_db, 'expiry'):
                        msg_template = (f"{EMOJIS['warning']} *هشدار انقضای اکانت*\n\nاکانت *{{user_name}}* شما تا *{{expire_days}}* روز دیگر منقضی می‌شود\\.")
                        if send_warning_message(bot, user_id_in_telegram, msg_template, user_name=user_name, expire_days=str(expire_days)):
                            db.log_warning(uuid_id_in_db, 'expiry')
                
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
                                if send_warning_message(bot, user_id_in_telegram, msg):
                                    db.log_warning(uuid_id_in_db, 'low_data_hiddify')
                            if usage >= limit and not hiddify_info.get('is_active') and not db.has_recent_warning(uuid_id_in_db, 'volume_depleted_hiddify'):
                                msg = (f"🔴 *اتمام حجم*\n\nحجم سرویس شما در سرور *آلمان 🇩🇪* به پایان رسیده و این سرور برای شما غیرفعال شده است\\.")
                                if send_warning_message(bot, user_id_in_telegram, msg):
                                    db.log_warning(uuid_id_in_db, 'volume_depleted_hiddify')
                                    
                marzban_info = next((p.get('data', {}) for p in breakdown.values() if p.get('type') == 'marzban'), None)
                if marzban_info and uuid_record:
                    should_warn_fr = user_settings.get('data_warning_fr') and uuid_record.get('has_access_fr')
                    should_warn_tr = user_settings.get('data_warning_tr') and uuid_record.get('has_access_tr')
                    should_warn_us = user_settings.get('data_warning_us') and uuid_record.get('has_access_us')
                    
                    if should_warn_fr or should_warn_tr or should_warn_us:
                        limit, usage = marzban_info.get('usage_limit_GB', 0.0), marzban_info.get('current_usage_GB', 0.0)
                        if limit > 0:
                            usage_percent = (usage / limit) * 100
                            server_names = []
                            if should_warn_fr: server_names.append("فرانسه 🇫🇷")
                            if should_warn_tr: server_names.append("ترکیه 🇹🇷")
                            if should_warn_us: server_names.append("آمریکا 🇺🇸")
                            server_display_name = " / ".join(server_names)

                            if WARNING_USAGE_THRESHOLD <= usage_percent < 100 and not db.has_recent_warning(uuid_id_in_db, 'low_data_marzban'):
                                msg = (f"❗️ *هشدار اتمام حجم*\n\nکاربر گرامی، بیش از *{int(WARNING_USAGE_THRESHOLD)}%* از حجم سرویس شما در سرور *{server_display_name}* مصرف شده است\\.")
                                if send_warning_message(bot, user_id_in_telegram, msg):
                                    db.log_warning(uuid_id_in_db, 'low_data_marzban')
                                    
                            if usage >= limit and not marzban_info.get('is_active') and not db.has_recent_warning(uuid_id_in_db, 'volume_depleted_marzban'):
                                msg = (f"🔴 *اتمام حجم*\n\nحجم سرویس شما در سرور *{server_display_name}* به پایان رسیده و این سرور برای شما غیرفعال شده است\\.")
                                if send_warning_message(bot, user_id_in_telegram, msg):
                                    db.log_warning(uuid_id_in_db, 'volume_depleted_marzban')

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

                # 6. ارسال هشدار مصرف غیرعادی روزانه به ادمین‌ها
                if DAILY_USAGE_ALERT_THRESHOLD_GB > 0:
                    total_daily_usage = sum(db.get_usage_since_midnight_by_uuid(uuid_str).values())
                    if total_daily_usage >= DAILY_USAGE_ALERT_THRESHOLD_GB and not db.has_recent_warning(uuid_id_in_db, 'unusual_daily_usage', hours=24):
                        alert_message = (f"⚠️ *مصرف غیرعادی روزانه*\n\nکاربر *{escape_markdown(user_name)}* \\(`{escape_markdown(uuid_str)}`\\) "
                                        f"امروز بیش از *{escape_markdown(str(DAILY_USAGE_ALERT_THRESHOLD_GB))} GB* مصرف داشته است\\.\n\n"
                                        f"\\- مجموع مصرف امروز: *{escape_markdown(format_daily_usage(total_daily_usage))}*")
                        for admin_id in ADMIN_IDS:
                            send_warning_message(bot, admin_id, alert_message) # Use the safe function
                        db.log_warning(uuid_id_in_db, 'unusual_daily_usage')

                # 7. ارسال هشدار تعداد زیاد دستگاه‌ها به ادمین‌ها
                device_count = db.count_user_agents(uuid_id_in_db)
                if device_count > 5 and not db.has_recent_warning(uuid_id_in_db, 'too_many_devices', hours=168):
                    alert_message = (f"⚠️ *تعداد دستگاه بالا*\n\n"
                                    f"کاربر *{escape_markdown(user_name)}* \\(`{escape_markdown(uuid_str)}`\\) "
                                    f"بیش از *۵* دستگاه \\({device_count} دستگاه\\) متصل کرده است\\. احتمال به اشتراک گذاری لینک وجود دارد\\.")
                    for admin_id in ADMIN_IDS:
                        send_warning_message(bot, admin_id, alert_message) # Use the safe function
                    db.log_warning(uuid_id_in_db, 'too_many_devices')

            except Exception as e:
                logger.error(f"SCHEDULER (Warnings): Error processing UUID_ID {u_row.get('id', 'N/A')}: {e}", exc_info=True)
    
    except Exception as e:
        logger.error(f"SCHEDULER (Warnings): A critical error occurred during check: {e}", exc_info=True)
    
    logger.info("SCHEDULER (Warnings): Finished warnings check job.")