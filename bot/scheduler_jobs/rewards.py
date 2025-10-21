# bot/scheduler_jobs/rewards.py

import logging
import random
import time
from datetime import datetime, timedelta
import pytz
import jdatetime
from telebot import types

from bot import combined_handler
from bot.database import db
from bot.utils import escape_markdown, load_json_file, load_service_plans, parse_volume_string, days_until_next_birthday
from bot.config import (
    ADMIN_IDS, BIRTHDAY_GIFT_GB, BIRTHDAY_GIFT_DAYS,
    ACHIEVEMENTS, ENABLE_LUCKY_LOTTERY, LUCKY_LOTTERY_BADGE_REQUIREMENT,
    AMBASSADOR_BADGE_THRESHOLD, LOYALTY_REWARDS
)
from bot.language import get_string
from .warnings import send_warning_message
from ..admin_formatters import fmt_achievement_leaderboard, fmt_lottery_participants_list

logger = logging.getLogger(__name__)

# 1. تابع کمکی هوشمند برای اعمال هر نوع پاداش
def _apply_reward_intelligently(user_telegram_id: int, user_uuid: str, add_gb: float, add_days: int):
    """
    پاداش (حجم و روز) را به صورت هوشمند بین پنل‌های کاربر تقسیم و اعمال می‌کند.
    """
    try:
        # گرفتن دسترسی‌های کاربر برای تقسیم هوشمند پاداش
        user_uuid_records = db.uuids(user_telegram_id)
        user_access = next((r for r in user_uuid_records if r['uuid'] == user_uuid), None)
        if not user_access:
            logger.warning(f"Could not find access record for user {user_telegram_id} with uuid {user_uuid}")
            return False

        has_hiddify = user_access.get('has_access_de', False)
        has_marzban = user_access.get('has_access_fr', False) or user_access.get('has_access_tr', False) or user_access.get('has_access_us', False)

        if has_hiddify and has_marzban:
            # اگر به هر دو دسترسی داشت، حجم نصف می‌شود ولی روز به هر دو اضافه می‌شود
            half_gb = add_gb / 2
            combined_handler.modify_user_on_all_panels(user_uuid, add_gb=half_gb, target_panel_type='hiddify')
            combined_handler.modify_user_on_all_panels(user_uuid, add_gb=half_gb, target_panel_type='marzban')
            if add_days > 0:
                combined_handler.modify_user_on_all_panels(user_uuid, add_days=add_days)
        else:
            # اگر فقط به یکی دسترسی داشت، تمام پاداش به همان یک پنل اضافه می‌شود
            if add_gb > 0 or add_days > 0:
                combined_handler.modify_user_on_all_panels(user_uuid, add_gb=add_gb, add_days=add_days)
        
        return True
    except Exception as e:
        logger.error(f"Error in _apply_reward_intelligently for user {user_telegram_id}: {e}", exc_info=True)
        return False

def send_weekly_admin_digest(bot) -> None:
    """
    (تابع جدید)
    گزارش هفتگی مدیریتی شامل رویدادها، تولدها و کاربران VIP جدید را برای ادمین‌ها ارسال می‌کند.
    """
    try:
        tehran_tz = pytz.timezone("Asia/Tehran")
        now_jalali = jdatetime.datetime.now(tehran_tz)
        
        # بخش ۱: رویدادهای هفته آینده
        events = load_json_file('events.json')
        upcoming_events_lines = []
        for i in range(7):
            check_date = now_jalali + timedelta(days=i)
            check_date_str = check_date.strftime('%m-%d')
            for event in events:
                if event.get('date') == check_date_str:
                    event_name = escape_markdown(event.get('name', ''))
                    day_name = escape_markdown(check_date.strftime('%A'))
                    upcoming_events_lines.append(f"• *{day_name}* \\({escape_markdown(check_date.strftime('%Y/%m/%d'))}\\): *{event_name}*")
        
        # بخش ۲: تولدهای هفته آینده
        upcoming_birthdays_lines = []
        users_with_birthdays = db.get_users_with_birthdays()
        for user in users_with_birthdays:
            days_left = days_until_next_birthday(user['birthday'])
            if 0 <= days_left < 7:
                birthday_date = now_jalali + timedelta(days=days_left)
                day_name = escape_markdown(birthday_date.strftime('%A'))
                user_name = escape_markdown(user.get('first_name', 'کاربر'))
                upcoming_birthdays_lines.append(f"• *{day_name}*: تولد *{user_name}* \\(ID: `{user['user_id']}`\\)")
        
        # بخش ۳: کاربران VIP جدید در هفته گذشته
        new_vips_lines = []
        # این تابع به یک منطق در دیتابیس برای پیدا کردن کاربران VIP جدید نیاز دارد.
        # در اینجا فرض می‌کنیم تابعی به نام get_new_vips_last_7_days وجود دارد.
        new_vips = db.get_new_vips_last_7_days() # نیازمند پیاده‌سازی در database.py
        for vip in new_vips:
            user_name = escape_markdown(vip.get('first_name', 'کاربر'))
            new_vips_lines.append(f"• *{user_name}* \\(ID: `{vip['user_id']}`\\)")

        # ساخت پیام نهایی
        report_parts = [f"📊 *گزارش مدیریتی هفتگی ربات* \\- {escape_markdown(now_jalali.strftime('%Y/%m/%d'))}"]

        if upcoming_events_lines:
            report_parts.extend(["`──────────────────`", "🗓️ *رویدادهای پیش رو:*", *upcoming_events_lines])
        
        if upcoming_birthdays_lines:
            report_parts.extend(["`──────────────────`", "🎂 *تولدهای این هفته:*", *upcoming_birthdays_lines])

        if new_vips_lines:
            report_parts.extend(["`──────────────────`", "👑 *کاربران VIP جدید (هفته گذشته):*", *new_vips_lines])
        
        if len(report_parts) > 1:
            final_message = "\n".join(report_parts)
            for admin_id in ADMIN_IDS:
                bot.send_message(admin_id, final_message, parse_mode="MarkdownV2")
        else:
            logger.info("Weekly admin digest: No significant events to report.")

    except Exception as e:
        logger.error(f"Error in weekly admin digest: {e}", exc_info=True)


def notify_admin_of_upcoming_event(bot) -> None:
    """
    (نسخه نهایی و اصلاح شده)
    مناسبت‌های فردا را بررسی کرده و به همراه تعداد کاربران فعال به ادمین‌ها اطلاع‌رسانی می‌کند.
    """
    try:
        events = load_json_file('events.json')
        tomorrow_jalali = jdatetime.datetime.now(pytz.timezone("Asia/Tehran")) + timedelta(days=1)
        tomorrow_str = tomorrow_jalali.strftime('%m-%d')

        for event in events:
            if event.get('date') == tomorrow_str:
                logger.info(f"Upcoming event found for tomorrow: {event['name']}")
                
                # ✅ **کد جدید برای شمارش کاربران فعال**
                active_users_count = db.count_all_active_users()

                event_name = escape_markdown(event.get('name', 'نامشخص'))
                event_date = escape_markdown(tomorrow_jalali.strftime('%Y/%m/%d'))
                gift_gb = event.get('gift', {}).get('gb', 0)
                gift_days = event.get('gift', {}).get('days', 0)
                user_message = escape_markdown(event.get('message', ''))

                gift_details = []
                if gift_gb > 0: gift_details.append(f"`{gift_gb} GB` حجم")
                if gift_days > 0: gift_details.append(f"`{gift_days}` روز")
                gift_str = " و ".join(gift_details) if gift_details else "بدون هدیه"

                admin_message = (
                    f"🔔 *یادآوری رویداد آینده*\n\n"
                    f"فردا، *{event_date}*، مناسبت «*{event_name}*» است\\.\n\n"
                    f"🤖 *عملیات خودکار ربات:*\n"
                    f"ربات به صورت خودکار به *{active_users_count} کاربر فعال* هدیه خواهد داد\\.\n\n" # ✅ **آمار دقیق اضافه شد**
                    f"🎁 *جزئیات هدیه:*\n{gift_str}\n\n"
                    f"📝 *متن پیام به کاربران:*\n_{user_message}_\n\n"
                    f"💡 *پیشنهاد:*\nمی‌توانید برای این مناسبت یک پست تبریک در کانال خود منتشر کنید\\."
                )
                
                for admin_id in ADMIN_IDS:
                    bot.send_message(admin_id, admin_message, parse_mode="MarkdownV2")
                
                break 
    except Exception as e:
        logger.error(f"Error notifying admin of upcoming events: {e}", exc_info=True)

def notify_user_achievement(bot, user_id: int, badge_code: str):
    """(نسخه نهایی) کاربر را از دستاورد جدید با فرمت خوانا مطلع می‌کند."""
    badge = ACHIEVEMENTS.get(badge_code)
    if not badge: return

    points = badge.get("points", 0)
    if points > 0:
        db.add_achievement_points(user_id, points)

    user_settings = db.get_user_settings(user_id)
    if not user_settings.get('achievement_alerts', True):
        return
    
    message = (
        f"{badge['icon']} *شما یک نشان جدید دریافت کردید\\!* {badge['icon']}\n\n"
        f"تبریک\\! شما موفق به کسب نشان «*{escape_markdown(badge['name'])}*» شدید و *{points} امتیاز* دریافت کردید\\.\n\n"
        f"{escape_markdown(badge['description'])}\n\n"
        f"این نشان و امتیاز آن به پروفایل شما اضافه شد\\."
    )
    send_warning_message(bot, user_id, message)


def birthday_gifts_job(bot) -> None:
    """هدایای تولد را به صورت هوشمند اعمال کرده و ۱۵ روز قبل از تولد نیز به کاربر یادآوری می‌کند."""
    all_users_with_birthdays = list(db.get_users_with_birthdays())
    if not all_users_with_birthdays: return
        
    current_year = jdatetime.datetime.now(pytz.timezone("Asia/Tehran")).year

    for user in all_users_with_birthdays:
        user_id = user['user_id']
        days_left = days_until_next_birthday(user['birthday'])
        
        if days_left == 0:
            already_given = db.check_if_gift_given(user_id, 'birthday', current_year)
            if already_given: continue

            user_uuids = db.uuids(user_id)
            if user_uuids:
                first_uuid = user_uuids[0]['uuid']
                
                # استفاده از تابع هوشمند برای اهدای هدیه تولد
                if _apply_reward_intelligently(user_id, first_uuid, BIRTHDAY_GIFT_GB, BIRTHDAY_GIFT_DAYS):
                    user_settings = db.get_user_settings(user_id)
                    if user_settings.get('promotional_alerts', True):
                        gift_message = (f"🎉 *تولدت مبارک\\!* 🎉\n\n"
                                        f"امیدواریم سالی پر از شادی و موفقیت پیش رو داشته باشی\\.\n"
                                        f"ما به همین مناسبت، هدیه‌ای برای شما فعال کردیم:\n\n"
                                        f"🎁 `{BIRTHDAY_GIFT_GB} GB` حجم اضافی\n"
                                        f"📅 `{BIRTHDAY_GIFT_DAYS}` روز اعتبار اضافی\n\n"
                                        f"این هدیه به صورت خودکار به اکانت شما اضافه شد\\!\\.")
                        if send_warning_message(bot, user_id, gift_message):
                            db.log_gift_given(user_id, 'birthday', current_year)
        
        elif days_left == 15:
            if not db.has_recent_warning(user_id, 'pre_birthday_reminder', hours=360 * 24):
                 user_settings = db.get_user_settings(user_id)
                 if user_settings.get('promotional_alerts', True):
                    user_name = user.get('first_name', 'کاربر عزیز')
                    pre_birthday_message = get_string("pre_birthday_message", db.get_user_language(user_id)).format(name=escape_markdown(user_name))
                    if send_warning_message(bot, user_id, pre_birthday_message):
                        db.log_warning(user_id, 'pre_birthday_reminder')


def check_achievements_and_anniversary(bot) -> None:
    """
    (نسخه نهایی) شرایط دریافت دستاوردها و هدیه سالگرد را بررسی کرده و پاداش را به صورت هوشمند اعمال می‌کند.
    """
    all_user_ids = list(db.get_all_user_ids())
    logger.info(f"SCHEDULER: Checking achievements and anniversaries for {len(all_user_ids)} users.")
    
    for user_id in all_user_ids:
        try:
            user_uuids = db.uuids(user_id)
            if not user_uuids:
                continue

            first_uuid_record = user_uuids[0]
            uuid_id = first_uuid_record['id']
            first_uuid_creation_date = first_uuid_record['created_at']
            if first_uuid_creation_date.tzinfo is None:
                first_uuid_creation_date = pytz.utc.localize(first_uuid_creation_date)
            
            days_since_creation = (datetime.now(pytz.utc) - first_uuid_creation_date).days
            payment_count = len(db.get_user_payment_history(uuid_id))
            referred_users = db.get_referred_users(user_id)
            referral_count = sum(1 for u in referred_users if u.get('referral_reward_applied'))
            
            # --- بررسی دستاوردها ---
            if days_since_creation >= 365 and db.add_achievement(user_id, 'veteran'):
                notify_user_achievement(bot, user_id, 'veteran')
            
            if payment_count >= 5 and db.add_achievement(user_id, 'loyal_supporter'):
                notify_user_achievement(bot, user_id, 'loyal_supporter')

            if referral_count >= AMBASSADOR_BADGE_THRESHOLD and db.add_achievement(user_id, 'ambassador'):
                notify_user_achievement(bot, user_id, 'ambassador')
            
            user_info = combined_handler.get_combined_user_info(first_uuid_record['uuid'])
            if user_info and user_info.get('total_usage_GB', 0) >= 1000 and db.add_achievement(user_id, 'data_whale'):
                notify_user_achievement(bot, user_id, 'data_whale')

            # --- بررسی هدیه سالگرد ---
            current_year = datetime.now(pytz.utc).year
            if days_since_creation > 0 and days_since_creation % 365 == 0:
                anniversary_year = days_since_creation // 365
                gift_name = f'anniversary_{anniversary_year}'
                
                already_given = db.check_if_gift_given(user_id, gift_name, current_year)
                if not already_given:
                    anniversary_gift_gb, anniversary_gift_days = 20, 10
                    
                    if _apply_reward_intelligently(user_id, first_uuid_record['uuid'], anniversary_gift_gb, anniversary_gift_days):
                        lang_code = db.get_user_language(user_id)
                        title = get_string("anniversary_gift_title", lang_code)
                        body = get_string("anniversary_gift_body", lang_code).format(
                            year=anniversary_year,
                            gift_gb=anniversary_gift_gb,
                            gift_days=anniversary_gift_days
                        )
                        message = f"*{escape_markdown(title)}*\n\n{escape_markdown(body)}"
                        send_warning_message(bot, user_id, message)
                        db.log_gift_given(user_id, gift_name, current_year)
                        
        except Exception as e:
            logger.error(f"Error checking achievements/anniversary for user_id {user_id}: {e}", exc_info=True)
        
        time.sleep(0.1)
    
    logger.info("Finished checking achievements and anniversaries.")


def check_for_special_occasions(bot):
    """هر روز اجرا شده و تاریخ شمسی را با مناسبت‌ها چک می‌کند."""
    try:
        events = load_json_file('events.json')
        today_jalali = jdatetime.datetime.now(pytz.timezone("Asia/Tehran"))
        today_str = today_jalali.strftime('%m-%d')
        for event in events:
            if event.get('date') == today_str:
                logger.info(f"Today is {event['name']}. Preparing to send gifts.")
                _distribute_special_occasion_gifts(bot, event)
    except Exception as e:
        logger.error(f"Error checking for special occasions: {e}", exc_info=True)

def _distribute_special_occasion_gifts(bot, event_details: dict):
    """(نسخه نهایی) هدیه رویدادها را به صورت هوشمند بین پنل‌های کاربران فعال تقسیم و اعمال می‌کند."""
    all_active_uuids_records = list(db.all_active_uuids())
    if not all_active_uuids_records:
        logger.info(f"No active users to send {event_details['name']} gift to.")
        return

    gift_gb = event_details.get('gift', {}).get('gb', 0)
    gift_days = event_details.get('gift', {}).get('days', 0)
    message_template = event_details.get('message', "شما یک هدیه دریافت کردید!")

    if gift_gb == 0 and gift_days == 0:
        logger.warning(f"Gift for {event_details['name']} has no value. Skipping.")
        return

    successful_gifts = 0
    for user_row in all_active_uuids_records:
        try:
            user_uuid = user_row['uuid']
            user_id = user_row['user_id']
            
            # استفاده از تابع هوشمند برای اهدای هدیه رویدادها
            if _apply_reward_intelligently(user_id, user_uuid, gift_gb, gift_days):
                user_settings = db.get_user_settings(user_id)
                if user_settings.get('promotional_alerts', True):
                    send_warning_message(bot, user_id, escape_markdown(message_template))
                successful_gifts += 1
                time.sleep(0.2)
        except Exception as e:
            logger.error(f"Failed to give {event_details['name']} gift to user {user_row['user_id']}: {e}")
    
    logger.info(f"Successfully sent {event_details['name']} gift to {successful_gifts} users.")


def run_lucky_lottery(bot) -> None:
    """قرعه‌کشی ماهانه خوش‌شانسی را در اولین جمعه ماه شمسی اجرا می‌کند."""
    tehran_tz = pytz.timezone("Asia/Tehran")
    today_jalali = jdatetime.datetime.now(tehran_tz)
    
    if today_jalali.weekday() != 6 or today_jalali.day > 7:
        return

    if not ENABLE_LUCKY_LOTTERY:
        return

    logger.info("SCHEDULER: Running monthly lucky lottery.")
    participants = db.get_lottery_participant_details()
    
    if not participants:
        logger.info("LUCKY LOTTERY: No eligible participants this month.")
        for admin_id in ADMIN_IDS:
            bot.send_message(admin_id, "ℹ️ قرعه‌کشی ماهانه خوش‌شانسی به دلیل عدم وجود شرکت‌کننده واجد شرایط، این ماه انجام نشد\\.", parse_mode="MarkdownV2")
        return

    weighted_participants = []
    for p in participants:
        for _ in range(p.get('lucky_badge_count', 1)):
            weighted_participants.append(p)

    winner = random.choice(weighted_participants)
    
    winner_id = winner['user_id']
    winner_name = escape_markdown(winner['first_name'])
    
    badge = ACHIEVEMENTS.get("lucky_one")
    if badge and badge.get("points"):
        points_reward = badge.get("points") * 10 
        db.add_achievement_points(winner_id, points_reward)

        winner_message = (
            f"🎉 *شما برنده قرعه‌کشی ماهانه خوش‌شانسی شدید\\!* 🎉\n\n"
            f"تبریک\\! به همین مناسبت، *{points_reward} امتیاز* به حساب شما اضافه شد\\.\n\n"
            f"می‌توانید از این امتیاز در «فروشگاه دستاوردها» استفاده کنید\\."
        )
        send_warning_message(bot, winner_id, winner_message)

        admin_message = (
            f"🏆 *نتیجه قرعه‌کشی ماهانه خوش‌شانسی*\n\n"
            f"برنده این ماه: *{winner_name}* \\(`{winner_id}`\\)\n"
            f"جایزه: *{points_reward} امتیاز* با موفقیت به ایشان اهدا شد\\."
        )
        for admin_id in ADMIN_IDS:
            bot.send_message(admin_id, admin_message, parse_mode="MarkdownV2")


def send_lucky_badge_summary(bot) -> None:
    """گزارش تعداد نشان خوش‌شانس را برای کاربران و لیست شرکت‌کنندگان را برای ادمین ارسال می‌کند."""
    if not ENABLE_LUCKY_LOTTERY:
        return

    logger.info("SCHEDULER: Sending weekly lucky badge summary.")
    participants = db.get_lottery_participant_details()

    for user in participants:
        user_id = user['user_id']
        badge_count = user['lucky_badge_count']
        message = (
            f"🍀 *گزارش هفتگی خوش‌شانسی شما*\n\n"
            f"شما در این ماه *{badge_count}* بار نشان خوش‌شانس دریافت کرده‌اید و در قرعه‌کشی شرکت داده خواهید شد\.\n\n"
            f"*قرعه‌کشی ماهانه چیست؟*\n"
            f"در اولین جمعه هر ماه، بین تمام کاربرانی که شرایط لازم را داشته باشند، قرعه‌کشی شده و به برنده امتیاز ویژه اهدا می‌شود\.\n\n"
            f"با آرزوی موفقیت\!"
        )
        send_warning_message(bot, user_id, message)

    admin_report_text = fmt_lottery_participants_list(participants)
    for admin_id in ADMIN_IDS:
        bot.send_message(admin_id, admin_report_text, parse_mode="MarkdownV2")


def send_weekend_vip_message(bot) -> None:
    """پیام قدردانی آخر هفته را برای کاربران VIP ارسال می‌کند."""
    logger.info("SCHEDULER: Sending weekend thank you message to VIP users.")
    
    all_uuids = db.get_all_user_uuids()
    vip_users = [u for u in all_uuids if u.get('is_vip')]
    if not vip_users:
        logger.info("No VIP users found to send weekend message.")
        return
    vip_user_ids = {db.get_user_id_by_uuid(u['uuid']) for u in vip_users if db.get_user_id_by_uuid(u['uuid'])}

    message_templates = [
        "سلام {name} عزیز ✨\n\nامیدوارم شروع آخر هفته خوبی داشته باشی و فرصتی برای استراحت پیدا کنی.\n\nاین یک پیام قدردانی مخصوص کاربران ویژه ماست. چه بخوای فیلم ببینی، چه آنلاین بازی کنی، می‌خوام خیالت راحت باشه که اتصال پایدارت برای من در اولویته.\n\nاگه حس کردی سرعت یا کیفیت اتصال مثل همیشه نیست، بدون تردید روی دکمه زیر بزن تا شخصاً برات پیگیری کنم.\n\nمراقب خودت باش و از تعطیلاتت لذت ببر.",
        "سلام {name}، آخر هفته‌ات بخیر! ☀️\n\nفقط خواستم بگم حواسم به کیفیت سرویس هست تا تو این آخر هفته با خیال راحت به کارهات برسی.\n\nاگه موقع استریم یا هر استفاده دیگه‌ای حس کردی چیزی مثل همیشه نیست، من اینجام تا سریع حلش کنم. هدف من اینه که تو بهترین تجربه رو داشته باشی.\n\nآخر هفته خوبی داشته باشی و حسابی استراحت کن!",
        "{name} عزیز، آخر هفته خوبی پیش رو داشته باشی! ☕️\n\nهدف ما اینه که تو بتونی بدون هیچ دغدغه‌ای از دنیای آنلاین لذت ببری.\n\nاگه احساس کردی سرویس اون‌طور که باید باشه نیست و مانع تفریح یا کارت شده، حتماً بهم خبر بده. اتصال بی‌نقص حق شماست.\n\nامیدوارم آخر هفته پر از آرامشی داشته باشی. مراقب خودت هم باش.",

        "سلام {name} عزیز! آخر هفته فرصت خوبیه برای استراحت و تفریح. می‌خواستم مطمئن بشم که سرویس شما بدون هیچ وقفه‌ای، بهترین همراهتون برای لذت بردن از این تعطیلاته. هر مشکلی بود، من شخصا در خدمتم.",
        "سلام {name}، آخر هفته‌ات پر از آرامش! ☀️ خواستم یادآوری کنم که به عنوان کاربر ویژه، همیشه می‌تونی از امتیازهایی که جمع کردی برای دریافت حجم یا روز اضافه از فروشگاه استفاده کنی و تجربه‌ات رو خاص‌تر کنی. یه سر بهش بزن!",
        "{name} جان، از اینکه همراه ویژه ما هستی بی‌نهایت خوشحالیم. آخر هفته خوبی داشته باشی! 😊 نظر شما برای ما اولویت داره، پس اگه پیشنهاد یا انتقادی داشti، باعث افتخاره که بشنویم و اعمال کنیم."
    ]
    
    button_texts = [
        "💬 پشتیبانی ویژه VIP", "💬 اگه مشکلی بود، به من بگو",
        "📞 خط ارتباطی سریع", "ارتباط مستقیم با مدیریت", "پشتیبانی اختصاصی شما"
    ]

    my_telegram_username = "Mohammadnzrr"

    for user_id in vip_user_ids:
        try:
            user_info = db.user(user_id)
            if user_info:
                user_name = user_info.get('first_name', 'کاربر ویژه')
                
                chosen_template = random.choice(message_templates)
                chosen_button_text = random.choice(button_texts)
                
                escaped_template = escape_markdown(chosen_template)
                final_template = escaped_template.replace('\\{name\\}', '{name}')
                
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton(chosen_button_text, url=f"https://t.me/{my_telegram_username}"))
                
                send_warning_message(
                    bot, user_id, final_template,
                    reply_markup=kb, name=user_name
                )
                time.sleep(0.5)
        except Exception as e:
            logger.error(f"Failed to send VIP message to user {user_id}: {e}")


def send_weekend_normal_user_message(bot) -> None:
    """پیام قدردانی آخر هفته را برای کاربران عادی (غیر VIP) ارسال می‌کند."""
    logger.info("SCHEDULER: Sending weekend thank you message to normal users.")
    
    all_uuids = db.get_all_user_uuids()
    normal_users_uuids = [u for u in all_uuids if not u.get('is_vip')]
    
    if not normal_users_uuids:
        logger.info("No normal users found to send weekend message.")
        return

    normal_user_ids = {db.get_user_id_by_uuid(u['uuid']) for u in normal_users_uuids if db.get_user_id_by_uuid(u['uuid'])}

    message_templates = [
        "سلام {name} عزیز!\n\nامیدوارم آخر هفته خوبی داشته باشی. خواستم از همراهی و اعتماد شما به سرویس ما تشکر کنم. حضور شما برای ما بسیار ارزشمنده.\n\nما همیشه در تلاشیم تا بهترین و پایدارترین اتصال رو برای شما فراهم کنیم. یادت باشه که با تمدید به موقع سرویس و دعوت از دوستانت، می‌تونی امتیاز جمع کنی و به جمع کاربران ویژه ما بپیوندی.\n\nاگه هر سوالی داشتی، من برای کمک آماده‌ام.",
        "سلام {name} عزیز، آخر هفته‌ات بخیر! ☀️\n\nاز اینکه بخشی از جامعه کاربران ما هستی، خوشحالیم. امیدواریم از سرویس‌مون راضی باشی.\n\nخواستم یادآوری کنم که همیشه می‌تونی از بخش «🏆 دستاوردها» در ربات، راه‌های کسب امتیاز رو ببینی و از «🛍️ فروشگاه» برای خودت حجم یا روز اضافه هدیه بگیری.\n\nاگه پیشنهادی برای بهتر شدن سرویس داشتی، خوشحال میشم بشنوم. آخر هفته خوبی داشته باشی!",
        "سلام {name} عزیز! آخر هفته فرصت خوبیه برای استراحت و تفریح. امیدواریم سرویس ما همراه خوبی برات باشه و اگه مشکلی بود، ما در کنارت هستیم.",
        "سلام {name}، آخر هفته‌ات پر از آرامش! ☀️ می‌دونستی با امتیازهایی که جمع کردی می‌تونی از فروشگاه ربات، حجم یا روز اضافه بگیری؟ یه سر بهش بزن!",
        "{name} جان، از اینکه همراه ما هستی خوشحالیم. آخر هفته خوبی داشته باشی! 😊 اگه پیشنهاد یا انتقادی داشتی، خوشحال می‌شیم بشنویم."
    ]
    
    button_texts = ["💬 راهنمایی و پشتیبانی", "💬 ارسال پیشنهاد یا سوال"]
    my_telegram_username = "Nzrmohammad"

    for user_id in normal_user_ids:
        try:
            user_info = db.user(user_id)
            if user_info:
                user_name = user_info.get('first_name', 'کاربر گرامی')
                
                chosen_template = random.choice(message_templates)
                chosen_button_text = random.choice(button_texts)
                
                escaped_template = escape_markdown(chosen_template)
                final_template = escaped_template.replace('\\{name\\}', '{name}')
                
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton(chosen_button_text, url=f"https://t.me/{my_telegram_username}"))
                
                send_warning_message(bot, user_id, final_template, reply_markup=kb, name=user_name)
                time.sleep(0.5)
        except Exception as e:
            logger.error(f"Failed to send normal user message to user {user_id}: {e}")


def check_auto_renewals_and_warnings(bot) -> None:
    """
    (نسخه کامل و نهایی)
    هر روز اجرا شده و وضعیت تمدید خودکار و هشدارهای کمبود موجودی را بررسی می‌کند.
    """
    logger.info("SCHEDULER: Starting auto-renewal and low balance check job.")
    users_with_auto_renew = [u for u in db.get_all_user_ids() if (ud := db.user(u)) and ud.get('auto_renew')]

    for user_id in users_with_auto_renew:
        try:
            user_uuids = db.uuids(user_id)
            if not user_uuids: continue

            uuid_record = user_uuids[0]
            user_info = combined_handler.get_combined_user_info(uuid_record['uuid'])

            if not user_info or user_info.get('expire') is None: continue

            expire_days = user_info['expire']
            user_balance = (db.user(user_id) or {}).get('wallet_balance', 0.0)
            plan_price = db.get_user_latest_plan_price(uuid_record['id'])

            if expire_days == 1 and plan_price and user_balance >= plan_price:
                plan_info = next((p for p in load_service_plans() if p.get('price') == plan_price), None)
                if not plan_info:
                    logger.warning(f"Auto-renewal failed for user {user_id}: Could not find a plan with price {plan_price}.")
                    continue

                add_days = parse_volume_string(plan_info.get('duration', '0'))
                if add_days > 0:
                    combined_handler.modify_user_on_all_panels(uuid_record['uuid'], add_days=add_days)

                plan_type = plan_info.get('type')
                if plan_type == 'combined':
                    add_gb_de = parse_volume_string(plan_info.get('volume_de', '0'))
                    add_gb_fr_tr = parse_volume_string(plan_info.get('volume_fr', '0'))
                    combined_handler.modify_user_on_all_panels(uuid_record['uuid'], add_gb=add_gb_de, target_panel_type='hiddify')
                    combined_handler.modify_user_on_all_panels(uuid_record['uuid'], add_gb=add_gb_fr_tr, target_panel_type='marzban')
                else:
                    target_panel = 'hiddify' if plan_type == 'germany' else 'marzban'
                    volume_key = 'volume_de' if plan_type == 'germany' else 'volume_fr' if plan_type == 'france' else 'volume_tr'
                    add_gb = parse_volume_string(plan_info.get(volume_key, '0'))
                    combined_handler.modify_user_on_all_panels(uuid_record['uuid'], add_gb=add_gb, target_panel_type=target_panel)
                
                db.update_wallet_balance(user_id, -plan_price, 'auto_renewal', f"تمدید خودکار سرویس: {plan_info.get('name')}")
                bot.send_message(user_id, f"✅ سرویس شما با موفقیت به صورت خودکار تمدید شد. مبلغ {plan_price:,.0f} تومان از حساب شما کسر گردید.", parse_mode="MarkdownV2")
                logger.info(f"Auto-renewal successful for user {user_id} with plan '{plan_info.get('name')}'.")

            elif 1 < expire_days <= 3 and plan_price and user_balance < plan_price:
                if not db.has_recent_warning(uuid_record['id'], 'low_balance_for_renewal', hours=72):
                    needed_amount = plan_price - user_balance
                    msg = (
                        f"⚠️ *هشدار کمبود موجودی برای تمدید خودکار*\n\n"
                        f"اعتبار سرویس شما رو به اتمام است اما موجودی کیف پول شما برای تمدید خودکار کافی نیست\\.\n\n"
                        f"برای تمدید، نیاز به شارژ حساب به مبلغ حداقل *{needed_amount:,.0f} تومان* دارید\\."
                    )
                    if send_warning_message(bot, user_id, msg):
                        db.log_warning(uuid_record['id'], 'low_balance_for_renewal')

        except Exception as e:
            logger.error(f"Error during auto-renewal check for user {user_id}: {e}", exc_info=True)


def run_monthly_lottery(bot) -> None:
    """
    (نسخه کامل و نهایی)
    قرعه‌کشی ماهانه را اجرا کرده، به برنده جایزه می‌دهد و به همه اطلاع‌رسانی می‌کند.
    """
    today_jalali = jdatetime.datetime.now(pytz.timezone("Asia/Tehran"))
    if today_jalali.weekday() != 6 or today_jalali.day > 7:
        return

    logger.info("SCHEDULER: Running monthly lottery.")
    participants = db.get_lottery_participants()

    if not participants:
        logger.info("LOTTERY: No participants this month.")
        for admin_id in ADMIN_IDS:
            bot.send_message(admin_id, "ℹ️ قرعه‌کشی ماهانه به دلیل عدم وجود شرکت‌کننده، این ماه انجام نشد.", parse_mode="MarkdownV2")
        return

    winner_id = random.choice(participants)
    winner_info = db.get_user_by_telegram_id(winner_id)
    winner_name = escape_markdown(winner_info.get('first_name', f"کاربر {winner_id}"))

    prize_plan = next((p for p in load_service_plans() if p['name'] == 'Gold 🥇'), None)
    if prize_plan:
        winner_uuids = db.uuids(winner_id)
        if winner_uuids:
            winner_main_uuid = winner_uuids[0]['uuid']
            
            add_days = parse_volume_string(prize_plan.get('duration', '0'))
            if add_days > 0:
                combined_handler.modify_user_on_all_panels(winner_main_uuid, add_days=add_days)

            add_gb_de = parse_volume_string(prize_plan.get('volume_de', '0'))
            add_gb_fr_tr = parse_volume_string(prize_plan.get('volume_fr', '0'))
            combined_handler.modify_user_on_all_panels(winner_main_uuid, add_gb=add_gb_de, target_panel_type='hiddify')
            combined_handler.modify_user_on_all_panels(winner_main_uuid, add_gb=add_gb_fr_tr, target_panel_type='marzban')
            
            winner_message = f"🎉 *{escape_markdown('شما برنده قرعه‌کشی ماهانه شدید!')}* 🎉\n\n{escape_markdown(f'تبریک! جایزه شما (سرویس {prize_plan["name"]}) به صورت خودکار به اکانتتان اضافه شد.')}"
            send_warning_message(bot, winner_id, winner_message)

            admin_message = f"🏆 *{escape_markdown('نتیجه قرعه‌کشی ماهانه')}*\n\n{escape_markdown('برنده این ماه:')} *{winner_name}* (`{winner_id}`)\n{escape_markdown('جایزه با موفقیت به ایشان اهدا شد.')}"
            for admin_id in ADMIN_IDS:
                bot.send_message(admin_id, admin_message, parse_mode="MarkdownV2")

            db.clear_lottery_tickets()
            logger.info(f"Monthly lottery finished. Winner: {winner_id}")


def send_achievement_leaderboard(bot) -> None:
    """گزارش هفتگی رتبه‌بندی کاربران بر اساس امتیاز دستاوردها را برای ادمین‌ها ارسال می‌کند."""
    logger.info("SCHEDULER: Sending weekly achievement leaderboard.")
    try:
        leaderboard_data = db.get_achievement_leaderboard()
        report_text = fmt_achievement_leaderboard(leaderboard_data)
        
        for admin_id in ADMIN_IDS:
            bot.send_message(admin_id, report_text, parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Failed to generate or send achievement leaderboard: {e}", exc_info=True)

def award_daily_lucky_badge(bot):
    """
    هر روز به صورت تصادفی به ۳ کاربر فعال نشان "خوش‌شانس" را اهدا می‌کند.
    """
    logger.info("SCHEDULER: Running daily lucky badge awards.")
    try:
        # Get all active user IDs that have been active in the last 7 days
        seven_days_ago = datetime.now(pytz.utc) - timedelta(days=7)
        query = """
            SELECT DISTINCT u.user_id
            FROM users u
            JOIN user_uuids uu ON u.user_id = uu.user_id
            JOIN usage_snapshots us ON uu.id = us.uuid_id
            WHERE us.taken_at >= ?
        """
        with db._conn() as c:
            active_users_last_week = [row['user_id'] for row in c.execute(query, (seven_days_ago,)).fetchall()]

        if len(active_users_last_week) < 3:
            logger.warning("LUCKY BADGE: Not enough active users to award daily lucky badge.")
            return

        winners = random.sample(active_users_last_week, 3)
        awarded_count = 0
        for user_id in winners:
            if db.add_achievement(user_id, 'lucky_one'):
                notify_user_achievement(bot, user_id, 'lucky_one')
                awarded_count += 1
        
        logger.info(f"LUCKY BADGE: Awarded 'lucky_one' badge to {awarded_count} users.")

    except Exception as e:
        logger.error(f"Error in award_daily_lucky_badge job: {e}", exc_info=True)