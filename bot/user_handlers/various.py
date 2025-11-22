import logging
from telebot import types
import jdatetime
from datetime import datetime, timedelta
import pytz
import copy
import random
import time

# --- Local Imports ---
from ..database import db
from ..menu import menu
from ..utils import escape_markdown, _safe_edit
from ..language import get_string
from ..user_formatters import fmt_registered_birthday_info, fmt_referral_page, fmt_purchase_summary
from ..admin_formatters import fmt_admin_purchase_notification
from ..config import ADMIN_IDS, ADMIN_SUPPORT_CONTACT, TUTORIAL_LINKS, ACHIEVEMENTS, ACHIEVEMENT_SHOP_ITEMS
from .. import combined_handler
from ..hiddify_api_handler import HiddifyAPIHandler
from ..marzban_api_handler import MarzbanAPIHandler
from .wallet import _notify_user
from bot.scheduler_jobs.rewards import _apply_reward_intelligently


logger = logging.getLogger(__name__)
bot, admin_conversations = None, None


def initialize_handlers(b, conv_dict):
    """مقادیر bot و admin_conversations را از فایل اصلی دریافت می‌کند."""
    global bot, admin_conversations
    bot = b
    admin_conversations = conv_dict

# =============================================================================
# 1. Initial Menus & Guides
# =============================================================================

def show_initial_menu(uid: int, msg_id: int = None):
    """منوی خوشامدگویی اولیه را برای کاربران جدید نمایش می‌دهد."""
    lang_code = db.get_user_language(uid)
    welcome_text = (
        "<b>Welcome!</b> 👋\n\n"
        "Please choose one of the options below to get started:"
    )
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(f"💳 {get_string('btn_have_service', lang_code)}", callback_data="add"),
        types.InlineKeyboardButton(f"🚀 {get_string('btn_request_service', lang_code)}", callback_data="request_service")
    )
    kb.add(types.InlineKeyboardButton(get_string('btn_features_guide', lang_code), callback_data="show_features_guide"))

    if msg_id:
        _safe_edit(uid, msg_id, welcome_text, reply_markup=kb, parse_mode="HTML")
    else:
        bot.send_message(uid, welcome_text, reply_markup=kb, parse_mode="HTML")


def show_features_guide(call: types.CallbackQuery):
    """یک پیام راهنمای کلی درباره امکانات ربات نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)

    guide_title = get_string("features_guide_title", lang_code)
    guide_body = get_string("features_guide_body", lang_code)

    escaped_body = escape_markdown(guide_body).replace('\\*\\*', '*')
    guide_text = f"*{escape_markdown(guide_title)}*\n\n{escaped_body}"

    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back_to_start_menu"))
    _safe_edit(uid, msg_id, guide_text, reply_markup=kb, parse_mode="MarkdownV2")

# =============================================================================
# 2. Support, Tutorials & Service Requests
# =============================================================================

def handle_support_request(call: types.CallbackQuery):
    """(نسخه جدید) از کاربر می‌خواهد تا پیام پشتیبانی خود را ارسال کند."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)
    
    prompt = (
        f"*{escape_markdown('📝 ارسال تیکت پشتیبانی')}*\n\n"
        f"{escape_markdown('لطفاً سوال یا مشکل خود را به صورت کامل در قالب یک پیام بنویسید و ارسال کنید.')}\n\n"
        f"{escape_markdown('⚠️ توجه: پیام شما مستقیماً برای ادمین ارسال خواهد شد.')}"
    )
    
    kb = menu.user_cancel_action(back_callback="back", lang_code=lang_code)
    _safe_edit(uid, msg_id, prompt, reply_markup=kb)
    
    # ثبت گام بعدی برای دریافت پیام کاربر
    bot.register_next_step_handler(call.message, get_support_ticket_message, original_msg_id=msg_id)

def get_support_ticket_message(message: types.Message, original_msg_id: int):
    """
    (نسخه نهایی با دکمه پاسخ)
    پیام کاربر را دریافت، برای ادمین‌ها فوروارد و تیکت را در DB ثبت می‌کند.
    """
    uid = message.from_user.id
    lang_code = db.get_user_language(uid)

    _safe_edit(uid, original_msg_id, escape_markdown("⏳ در حال ارسال پیام شما به پشتیبانی..."), reply_markup=None)

    try:
        user_info = message.from_user
        user_db_data = db.user(uid)
        wallet_balance = user_db_data.get('wallet_balance', 0.0) if user_db_data else 0.0
        
        caption_lines = [
            f"💬 *تیکت پشتیبانی جدید*",
            f"`──────────────────`",
            f"👤 *کاربر:* {escape_markdown(user_info.first_name)}",
            f"🆔 *آیدی:* `{uid}`"
        ]
        if user_info.username:
            caption_lines.append(f"🔗 *یوزرنیم:* @{escape_markdown(user_info.username)}")
        
        caption_lines.append(f"💳 *موجودی کیف پول:* {wallet_balance:,.0f} تومان")
        caption_lines.append(f"`──────────────────`")
        
        admin_caption = "\n".join(caption_lines)
        
        # دیکشنری برای نگهداری {admin_id: message_id}
        admin_message_ids = {} 
        
        for admin_id in ADMIN_IDS:
            try:
                forwarded_msg = bot.forward_message(admin_id, uid, message.message_id)
                admin_msg = bot.send_message(admin_id, admin_caption, parse_mode="MarkdownV2", 
                                             reply_to_message_id=forwarded_msg.message_id)
                
                # (اصلاح شده) شناسه پیام هر ادمین را ذخیره می‌کنیم
                admin_message_ids[admin_id] = admin_msg.message_id
            
            except Exception as e:
                logger.error(f"Failed to forward support ticket to admin {admin_id}: {e}")

        if admin_message_ids:
            # (اصلاح شده) از اولین شناسه پیام برای ثبت در DB استفاده می‌کنیم
            first_admin_msg_id = list(admin_message_ids.values())[0]
            ticket_id = db.create_support_ticket(uid, first_admin_msg_id)
            
            final_admin_caption = f"🎫 *تیکت شماره:* `{ticket_id}`\n" + admin_caption

            # --- (جدید) ساخت دکمه پاسخ ---
            # ما به ticket_id برای بستن تیکت و uid برای ارسال پاسخ نیاز داریم
            kb_admin = types.InlineKeyboardMarkup()
            kb_admin.add(types.InlineKeyboardButton(
                "✍️ پاسخ به این تیکت", 
                callback_data=f"admin:support_reply:{ticket_id}:{uid}"
            ))
            # --------------------------------

            # (اصلاح شده) پیام همه ادمین‌ها را ویرایش می‌کنیم تا شامل دکمه و شماره تیکت باشد
            for admin_id, msg_id in admin_message_ids.items():
                try:
                    bot.edit_message_text(final_admin_caption, admin_id, msg_id, 
                                          parse_mode="MarkdownV2", 
                                          reply_markup=kb_admin) # <--- دکمه اضافه شد
                except Exception:
                    pass 

        success_prompt = escape_markdown("✅ پیام شما با موفقیت برای پشتیبانی ارسال شد. لطفاً منتظر پاسخ بمانید.")
        kb_back = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back")
        )
        _safe_edit(uid, original_msg_id, success_prompt, reply_markup=kb_back)

    except Exception as e:
        logger.error(f"Error in get_support_ticket_message: {e}", exc_info=True)
        _safe_edit(uid, original_msg_id, escape_markdown("❌ خطایی در ارسال پیام رخ داد. لطفاً دوباره تلاش کنید."))

def show_tutorial_main_menu(call: types.CallbackQuery):
    """منوی اصلی انتخاب سیستم‌عامل برای آموزش را نمایش می‌دهد."""
    lang_code = db.get_user_language(call.from_user.id)
    prompt = get_string("prompt_select_os", lang_code)
    _safe_edit(call.from_user.id, call.message.message_id, prompt, reply_markup=menu.tutorial_main_menu(lang_code))


def show_tutorial_os_menu(call: types.CallbackQuery):
    """منوی انتخاب نرم‌افزار برای یک سیستم‌عامل خاص را نمایش می‌دهد."""
    os_type = call.data.split(":")[1]
    lang_code = db.get_user_language(call.from_user.id)
    prompt = get_string("prompt_select_app", lang_code)
    _safe_edit(call.from_user.id, call.message.message_id, prompt, reply_markup=menu.tutorial_os_menu(os_type, lang_code))


def send_tutorial_link(call: types.CallbackQuery):
    """لینک آموزش مربوط به نرم‌افزار انتخاب شده را ارسال می‌کند."""
    _, os_type, app_name = call.data.split(":")
    lang_code = db.get_user_language(call.from_user.id)
    try:
        link = TUTORIAL_LINKS[os_type][app_name]
        app_display_name = f"{os_type.capitalize()} - {app_name.capitalize().replace('_', ' ')}"
        
        header = get_string("tutorial_ready_header", lang_code).format(app_display_name=app_display_name)
        body = get_string("tutorial_ready_body", lang_code)
        text = f"<b>{header}</b>\n\n{body}"
               
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(get_string("btn_view_tutorial", lang_code), url=link))
        kb.add(types.InlineKeyboardButton(get_string("btn_back_to_apps", lang_code), callback_data=f"tutorial_os:{os_type}"))
        
        _safe_edit(call.from_user.id, call.message.message_id, text, reply_markup=kb, parse_mode="HTML")
    except KeyError:
        bot.answer_callback_query(call.id, "خطا: لینک آموزشی برای این مورد یافت نشد.", show_alert=True)


def handle_request_service(call: types.CallbackQuery):
    """درخواست سرویس جدید را به ادمین‌ها اطلاع می‌دهد."""
    user_info = call.from_user
    uid, msg_id = user_info.id, call.message.message_id
    lang_code = db.get_user_language(uid)

    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back_to_start_menu"))
    _safe_edit(uid, msg_id, escape_markdown("✅ درخواست شما برای مدیران ارسال شد. لطفاً منتظر بمانید تا با شما تماس بگیرند."), reply_markup=kb)

    user_name = escape_markdown(user_info.first_name)
    admin_message = [f"👤 *درخواست سرویس جدید*\n\n*کاربر:* {user_name} \\(`{uid}`\\)"]
    if user_info.username:
        admin_message.append(f"*یوزرنیم:* @{escape_markdown(user_info.username)}")

    referrer_info = db.get_referrer_info(uid)
    if referrer_info:
        referrer_name = escape_markdown(referrer_info['referrer_name'])
        admin_message.append(f"*معرف:* {referrer_name} \\(`{referrer_info['referred_by_user_id']}`\\)")

    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, "\n".join(admin_message), parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"Failed to send new service request to admin {admin_id}: {e}")

# =============================================================================
# 3. Birthday, Achievements, and Referrals
# =============================================================================

def handle_birthday_gift_request(call: types.CallbackQuery):
    """منطق مربوط به هدیه تولد را مدیریت می‌کند."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)
    user_data = db.user(uid)
    
    if user_data and user_data.get('birthday'):
        text = fmt_registered_birthday_info(user_data, lang_code=lang_code)
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
        _safe_edit(uid, msg_id, text, reply_markup=kb, parse_mode="MarkdownV2")
    else:
        raw_text = get_string("prompt_birthday", lang_code)
        prompt = escape_markdown(raw_text).replace("YYYY/MM/DD", "`YYYY/MM/DD`")
        _safe_edit(uid, msg_id, prompt, reply_markup=menu.user_cancel_action(back_callback="back", lang_code=lang_code), parse_mode="MarkdownV2")
        bot.register_next_step_handler_by_chat_id(uid, get_birthday_step, original_msg_id=msg_id)


def get_birthday_step(message: types.Message, original_msg_id: int):
    """تاریخ تولد وارد شده توسط کاربر را پردازش می‌کند."""
    uid, birthday_str = message.from_user.id, message.text.strip()
    lang_code = db.get_user_language(uid)

    try:
        bot.delete_message(chat_id=uid, message_id=message.message_id)
    except Exception as e:
        logger.warning(f"Could not delete user message {message.message_id} for user {uid}: {e}")

    try:
        gregorian_date = jdatetime.datetime.strptime(birthday_str, '%Y/%m/%d').togregorian().date()
        db.update_user_birthday(uid, gregorian_date)
        
        success_text = escape_markdown(get_string("birthday_success", lang_code))
        back_button_text = get_string('back_to_main_menu', lang_code)
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔙 {back_button_text}", callback_data="back"))
        _safe_edit(uid, original_msg_id, success_text, reply_markup=kb, parse_mode="MarkdownV2")
    except ValueError:
        prompt = escape_markdown(get_string("birthday_invalid_format", lang_code)).replace("YYYY/MM/DD", "`YYYY/MM/DD`")
        _safe_edit(uid, original_msg_id, prompt, parse_mode="MarkdownV2")
        bot.register_next_step_handler_by_chat_id(uid, get_birthday_step, original_msg_id=original_msg_id)

def show_achievements_page(call: types.CallbackQuery):
    """صفحه دستاوردها و نشان‌های کاربر را با دسته‌بندی کامل و دکمه راهنما نمایش می‌دهد."""
    uid, msg_id, lang_code = call.from_user.id, call.message.message_id, call.from_user.language_code
    user_achievements = db.get_user_achievements(uid)
    
    # محاسبه امتیاز کل و سطح کاربر
    total_points = sum(ACHIEVEMENTS.get(ach, {}).get('points', 0) for ach in user_achievements)
    level_name = "تازه‌کار"
    if total_points >= 1000:
        level_name = "اسطوره"
    elif total_points >= 500:
        level_name = "افسانه"
    elif total_points >= 250:
        level_name = "حرفه‌ای"
    elif total_points >= 100:
        level_name = "باتجربه"

    # --- بخش دسته‌بندی هوشمند (با نام جدید) ---
    achievements_by_cat = {}
    category_map = {
        # ورزشی
        "bodybuilder": "🏅 نشان‌های ورزشی", "water_athlete": "🏅 نشان‌های ورزشی",
        "aerialist": "🏅 نشان‌های ورزشی", "swimming_champion": "🏅 نشان‌های ورزشی",
        "swimming_coach": "🏅 نشان‌های ورزشی", "bodybuilding_coach": "🏅 نشان‌های ورزشی",
        "aerial_coach": "🏅 نشان‌های ورزشی",
        # اجتماعی
        "media_partner": "👥 نشان‌های اجتماعی", "support_contributor": "👥 نشان‌های اجتماعی",
        "ambassador": "👥 نشان‌های اجتماعی",
        # وفاداری
        "veteran": "💖 نشان‌های وفاداری", "loyal_supporter": "💖 نشان‌های وفاداری",
        # عملکرد
        "pro_consumer": "🚀 نشان‌های عملکرد", "weekly_champion": "🚀 نشان‌های عملکرد",
        "serial_champion": "🚀 نشان‌های عملکرد", "night_owl": "🚀 نشان‌های عملکرد",
        "early_bird": "🚀 نشان‌های عملکرد",
        # ویژه
        "legend": "🌟 دستاوردهای ویژه", "vip_friend": "🌟 دستاوردهای ویژه",
        "collector": "🌟 دستاوردهای ویژه", "lucky_one": "🌟 دستاوردهای ویژه"
    }
    
    for ach_code in user_achievements:
        category = category_map.get(ach_code, " متفرقه ن متفرقه")
        if category not in achievements_by_cat:
            achievements_by_cat[category] = []
        achievements_by_cat[category].append(ach_code)
    
    kb = types.InlineKeyboardMarkup(row_width=2)

    final_text = f"🏅 *{escape_markdown('دستاوردها (Achievements)')}*\n\n"
    final_text += f"🏆 سطح شما: *{level_name}*\n"
    final_text += f"⭐ امتیاز کل: *{total_points}*\n"
    final_text += "───────────────\n\n"

    if achievements_by_cat:
        sorted_categories = sorted(achievements_by_cat.keys())
        for category in sorted_categories:
            final_text += f"*{escape_markdown(category)}*:\n"
            for ach_code in achievements_by_cat[category]:
                ach_info = ACHIEVEMENTS.get(ach_code, {})
                final_text += f"{ach_info.get('icon', '')} {escape_markdown(ach_info.get('name', ''))}\n"
            final_text += "\n"
    else:
        no_achievements_text = "شما هنوز هیچ دستاوردی کسب نکرده‌اید. با فعالیت بیشتر و دعوت از دوستانتان می‌توانید نشان‌های ارزشمندی به دست آورید!"
        final_text += escape_markdown(no_achievements_text)

    kb.add(
        types.InlineKeyboardButton("🏅 درخواست نشان ورزشی", callback_data="achievements:request_badge"),
        types.InlineKeyboardButton("ℹ️ راهنما", callback_data="achievements:info")
    )
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="back"))
    
    _safe_edit(uid, msg_id, final_text, reply_markup=kb, parse_mode="MarkdownV2")


def handle_achievements_info(call: types.CallbackQuery):
    """صفحه راهنمای کامل نحوه کسب تمام دستاوردها را نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    
    # --- ✨ شروع بخش دسته‌بندی هوشمند ---
    achievements_by_cat = {}
    category_map = {
        # ورزشی
        "bodybuilder": "🏅 نشان‌های ورزشی", "water_athlete": "🏅 نشان‌های ورزشی",
        "aerialist": "🏅 نشان‌های ورزشی", "swimming_champion": "🏅 نشان‌های ورزشی",
        "swimming_coach": "🏅 نشان‌های ورزشی", "bodybuilding_coach": "🏅 نشان‌های ورزشی",
        "aerial_coach": "🏅 نشان‌های ورزشی",
        # اجتماعی
        "media_partner": "👥 نشان‌های اجتماعی", "support_contributor": "👥 نشان‌های اجتماعی",
        "ambassador": "👥 نشان‌های اجتماعی",
        # وفاداری
        "veteran": "💖 نشان‌های وفاداری", "loyal_supporter": "💖 نشان‌های وفاداری",
        # عملکرد
        "pro_consumer": "🚀 نشان‌های عملکرد", "weekly_champion": "🚀 نشان‌های عملکرد",
        "serial_champion": "🚀 نشان‌های عملکرد", "night_owl": "🚀 نشان‌های عملکرد",
        "early_bird": "🚀 نشان‌های عملکرد",
        # ویژه
        "legend": "🌟 دستاوردهای ویژه", "vip_friend": "🌟 دستاوردهای ویژه",
        "collector": "🌟 دستاوردهای ویژه", "lucky_one": "🌟 دستاوردهای ویژه"
    }
    
    all_achievements = ACHIEVEMENTS.keys()
    for ach_code in all_achievements:
        category = category_map.get(ach_code, " متفرقه ن متفرقه")
        if category not in achievements_by_cat:
            achievements_by_cat[category] = []
        achievements_by_cat[category].append(ach_code)
    # --- پایان بخش دسته‌بندی ---

    info_text = f"*{escape_markdown('راهنمای کسب دستاوردها')}*\n\n"
    info_text += "در این بخش می‌توانید با نحوه کسب هر نشان به طور کامل آشنا شوید:\n\n"
    info_text += "───────────────\n"

    sorted_categories = sorted(achievements_by_cat.keys())
    for category in sorted_categories:
        info_text += f"*{escape_markdown(category)}*:\n"
        for ach_code in sorted(achievements_by_cat[category], key=lambda x: ACHIEVEMENTS[x]['points'], reverse=True):
            ach_info = ACHIEVEMENTS.get(ach_code, {})
            info_text += f"{ach_info.get('icon', '')} *{escape_markdown(ach_info.get('name', ''))}*:\n"
            info_text += f"{escape_markdown(ach_info.get('description', ''))}\n\n"
        info_text += "───────────────\n"

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به دستاوردها", callback_data="achievements"))
    
    _safe_edit(uid, msg_id, info_text, reply_markup=kb, parse_mode="MarkdownV2")

def handle_request_badge_menu(call: types.CallbackQuery):
    """منوی درخواست نشان ورزشی را نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    prompt = escape_markdown("انتخاب کنید برای کدام رشته ورزشی می‌خواهید درخواست نشان دهید.\n\nپس از ارسال، درخواست شما توسط ادمین بررسی خواهد شد.")
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.request_badge_menu())

def handle_badge_request_action(call: types.CallbackQuery, badge_code: str):
    """درخواست نشان کاربر را ثبت کرده، پیام را ویرایش می‌کند و به ادمین اطلاع می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    user_achievements = db.get_user_achievements(uid)

    if badge_code in user_achievements:
        bot.answer_callback_query(call.id, "شما قبلاً این نشان را دریافت کرده‌اید.", show_alert=True)
        return

    request_id = db.add_achievement_request(uid, badge_code)
    
    # ✨ اصلاح اصلی: escape کردن کاراکترهای ویژه در پیام تاییدیه
    confirmation_text = escape_markdown("✅ درخواست شما با موفقیت ثبت شد و برای ادمین ارسال گردید.\n\nنتیجه بررسی به شما اطلاع داده خواهد شد.")
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به دستاوردها", callback_data="achievements"))
    _safe_edit(uid, msg_id, confirmation_text, reply_markup=kb, parse_mode="MarkdownV2")

    # اطلاع‌رسانی به ادمین
    user_info = call.from_user
    user_name = escape_markdown(user_info.first_name)
    badge_name = escape_markdown(ACHIEVEMENTS.get(badge_code, {}).get('name', badge_code))
    
    admin_message = (
        f"🏅 *درخواست نشان جدید*\n\n"
        f"کاربر *{user_name}* \\(`{uid}`\\) درخواست دریافت نشان «*{badge_name}*» را دارد\\."
    )
    
    admin_kb = types.InlineKeyboardMarkup(row_width=2)
    admin_kb.add(
        types.InlineKeyboardButton("✅ تایید", callback_data=f"admin:ach_req_approve:{request_id}"),
        types.InlineKeyboardButton("❌ رد", callback_data=f"admin:ach_req_reject:{request_id}")
    )
    for admin_id in ADMIN_IDS:
        bot.send_message(admin_id, admin_message, parse_mode="MarkdownV2", reply_markup=admin_kb)

def handle_referral_callbacks(call: types.CallbackQuery):
    """اطلاعات مربوط به سیستم دعوت از دوستان را نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)
    bot_username = bot.get_me().username
    
    text = fmt_referral_page(uid, bot_username, lang_code)
    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
    _safe_edit(uid, msg_id, text, reply_markup=kb)

# =============================================================================
# 4. Shop, Connection Doctor & "Coming Soon"
# =============================================================================
def handle_shop_callbacks(call: types.CallbackQuery):
    """
    (نسخه نهایی و کامل)
    تمام callback های مربوط به فروشگاه دستاوردها را با منطق پیش‌نمایش و تایید نهایی مدیریت می‌کند.
    """
    uid, msg_id, data = call.from_user.id, call.message.message_id, call.data
    lang_code = db.get_user_language(uid)

    try:
        # --- 1. نمایش منوی اصلی فروشگاه ---
        if data == "shop:main":
            user = db.user(uid)
            user_points = user.get('achievement_points', 0) if user else 0
            access_rights = db.get_user_access_rights(uid)
            prompt = (
                f"🛍️ *{escape_markdown('فروشگاه دستاوردها')}*\n\n"
                f"{escape_markdown('با امتیازهای خود می‌توانید جوایز زیر را خریداری کنید.')}\n\n"
                f"💰 *{escape_markdown('موجودی امتیاز شما:')} {user_points}*"
            )
            _safe_edit(uid, msg_id, prompt, reply_markup=menu.achievement_shop_menu(user_points, access_rights))

        # --- 2. نمایش صفحه تاییدیه (پیش‌نمایش خرید) ---
        elif data.startswith("shop:confirm:"):
            item_key = data.split(":")[2]
            item = ACHIEVEMENT_SHOP_ITEMS.get(item_key)
            if not item: 
                bot.answer_callback_query(call.id, "آیتم یافت نشد.", show_alert=True)
                return

            user_uuids = db.uuids(uid)
            if not user_uuids:
                bot.answer_callback_query(call.id, "خطا: شما هیچ اکانت فعالی برای اعمال خرید ندارید.", show_alert=True)
                return

            # --- شروع منطق پیش‌نمایش (مشابه خرید با کیف پول) ---
            user_main_uuid_record = user_uuids[0]
            user_main_uuid = user_main_uuid_record['uuid']
            info_before = combined_handler.get_combined_user_info(user_main_uuid)
            info_after = copy.deepcopy(info_before) # کپی عمیق برای شبیه‌سازی

            add_gb = item.get("gb", 0)
            add_days = item.get("days", 0)
            target = item.get("target")

            target_panel_type = None
            if target == 'de': target_panel_type = 'hiddify'
            elif target in ['fr', 'tr', 'us', 'ro']: target_panel_type = 'marzban'
            
            # اعمال تغییرات شبیه‌سازی شده روی info_after
            for panel_details in info_after.get('breakdown', {}).values():
                panel_data = panel_details.get('data', {})
                if target == 'all' or panel_details.get('type') == target_panel_type:
                    if add_gb > 0:
                        panel_data['usage_limit_GB'] += add_gb
                    if add_days > 0:
                        current_panel_expire = panel_data.get('expire', 0)
                        panel_data['expire'] = add_days if current_panel_expire is None or current_panel_expire < 0 else current_panel_expire + add_days

            # --- ساخت پیام تاییدیه ---
            lines = [f"*{escape_markdown('🔍 پیش‌نمایش خرید با امتیاز')}*"]
            lines.append(f"`──────────────────`")
            lines.append(f"🎁 *{escape_markdown('آیتم انتخابی:')}* {escape_markdown(item['name'])}")
            lines.append(f"💰 *{escape_markdown('هزینه:')}* {item['cost']} امتیاز")
            lines.append(f"`──────────────────`")
            
            lines.append(f"*{escape_markdown(get_string('purchase_summary_before_status', lang_code))}*")
            # نمایش وضعیت قبل
            for panel_details in sorted(info_before.get('breakdown', {}).values(), key=lambda p: p.get('type') != 'hiddify'):
                p_data = panel_details.get('data', {})
                limit = p_data.get('usage_limit_GB', 0)
                expire_raw = p_data.get('expire')
                expire = expire_raw if expire_raw is not None and expire_raw >= 0 else 0
                
                flag = "🏳️"
                if panel_details.get('type') == 'hiddify': 
                    flag = "🇩🇪"
                elif panel_details.get('type') == 'marzban':
                     marzban_flags = []
                     if user_main_uuid_record.get('has_access_fr'): marzban_flags.append("🇫🇷")
                     if user_main_uuid_record.get('has_access_tr'): marzban_flags.append("🇹🇷")
                     if user_main_uuid_record.get('has_access_us'): marzban_flags.append("🇺🇸")
                     if user_main_uuid_record.get('has_access_ro'): marzban_flags.append("🇷🇴")
                     flag = "".join(marzban_flags)
                
                if flag != "🏳️" and (user_main_uuid_record.get(f"has_access_{panel_details.get('type')[:2]}", True)):
                    lines.append(f" {flag} : *{int(limit)} GB* \\| *{int(expire)} روز*")

            lines.append(f"\n*{escape_markdown('وضعیت پس از خرید')}*")
            # نمایش وضعیت بعد
            for panel_details in sorted(info_after.get('breakdown', {}).values(), key=lambda p: p.get('type') != 'hiddify'):
                p_data = panel_details.get('data', {})
                limit = p_data.get('usage_limit_GB', 0)
                expire_raw = p_data.get('expire')
                expire = expire_raw if expire_raw is not None and expire_raw >= 0 else 0
                
                flag = "🏳️"
                if panel_details.get('type') == 'hiddify': 
                    flag = "🇩🇪"
                elif panel_details.get('type') == 'marzban':
                     marzban_flags = []
                     if user_main_uuid_record.get('has_access_fr'): marzban_flags.append("🇫🇷")
                     if user_main_uuid_record.get('has_access_tr'): marzban_flags.append("🇹🇷")
                     if user_main_uuid_record.get('has_access_us'): marzban_flags.append("🇺🇸")
                     if user_main_uuid_record.get('has_access_ro'): marzban_flags.append("🇷🇴")
                     flag = "".join(marzban_flags)

                if flag != "🏳️" and (user_main_uuid_record.get(f"has_access_{panel_details.get('type')[:2]}", True)):
                    lines.append(f" {flag} : *{int(limit)} GB* \\| *{int(expire)} روز*")

            lines.extend([
                f"`──────────────────`",
                f"❓ *{escape_markdown('تایید نهایی')}*",
                escape_markdown(f"آیا از کسر {item['cost']} امتیاز و اعمال این آیتم اطمینان دارید؟")
            ])
            
            confirm_text = "\n".join(lines)
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.add(
                types.InlineKeyboardButton("✅ بله، خرید", callback_data=f"shop:execute:{item_key}"),
                types.InlineKeyboardButton("❌ انصراف", callback_data="shop:main")
            )
            _safe_edit(uid, msg_id, confirm_text, reply_markup=kb)

        # --- 3. اجرای نهایی خرید ---
        elif data.startswith("shop:execute:"):
            item_key = data.split(":")[2]
            item = ACHIEVEMENT_SHOP_ITEMS.get(item_key)
            if not item: return

            _safe_edit(uid, msg_id, escape_markdown("⏳ در حال پردازش خرید... لطفاً صبر کنید."), reply_markup=None)

            if db.spend_achievement_points(uid, item['cost']):
                user_uuids = db.uuids(uid)
                purchase_successful = False

                if item_key == "buy_lottery_ticket":
                    if db.add_achievement(uid, 'lucky_one'):
                        purchase_successful = True
                        from scheduler_jobs.rewards import notify_user_achievement
                        notify_user_achievement(bot, uid, 'lucky_one')
                
                elif user_uuids:
                    user_main_uuid_record = user_uuids[0]
                    user_main_uuid = user_main_uuid_record['uuid']
                    info_before = combined_handler.get_combined_user_info(user_main_uuid)
                    
                    target = item.get("target")
                    add_gb = item.get("gb", 0)
                    add_days = item.get("days", 0)

                    target_panel_type = None
                    if target == 'de':
                        target_panel_type = 'hiddify'
                    elif target in ['fr', 'tr', 'us', 'ro']:
                        target_panel_type = 'marzban'

                    purchase_successful = combined_handler.modify_user_on_all_panels(
                        user_main_uuid, add_gb=add_gb, add_days=add_days, target_panel_type=target_panel_type
                    )

                if purchase_successful:
                    info_after = combined_handler.get_combined_user_info(user_main_uuid)
                    db.log_shop_purchase(uid, item_key, item['cost'])
                    bot.answer_callback_query(call.id, "✅ خرید شما با موفقیت انجام شد.", show_alert=True)

                    # --- اطلاع‌رسانی به ادمین ---
                    try:
                        mock_plan_for_formatter = { "name": f"امتیاز: {item['name']}", "price": item['cost'] }
                        user_db_info_after = db.user(uid)
                        new_points = user_db_info_after.get('achievement_points', 0) if user_db_info_after else 0
                        
                        admin_notification_text = fmt_admin_purchase_notification(
                            user_info=call.from_user,
                            plan=mock_plan_for_formatter,
                            new_balance=new_points,
                            info_before=info_before,
                            info_after=info_after,
                            payment_count=0, # امتیازی است
                            is_vip=user_main_uuid_record.get('is_vip', False),
                            user_access=user_main_uuid_record
                        ).replace("خرید جدید از کیف پول", "خرید جدید از فروشگاه امتیاز") \
                         .replace("تومان", "امتیاز") \
                         .replace("تمدید شماره:", "خرید آیتم:")

                        panel_short = 'h' if any(p.get('type') == 'hiddify' for p in info_after.get('breakdown', {}).values()) else 'm'
                        kb_admin = types.InlineKeyboardMarkup().add(
                            types.InlineKeyboardButton("👤 مدیریت کاربر", callback_data=f"admin:us:{panel_short}:{user_main_uuid}:search")
                        )
                        for admin_id in ADMIN_IDS:
                            _notify_user(admin_id, admin_notification_text)
                            
                    except Exception as e:
                        logger.error(f"Failed to send shop purchase notification to admins for user {uid}: {e}")
                    # --- پایان اطلاع‌رسانی به ادمین ---

                    # --- پیام موفقیت به کاربر ---
                    user = db.user(uid)
                    user_points = user.get('achievement_points', 0) if user else 0
                    access_rights = db.get_user_access_rights(uid)
                    
                    summary_text = fmt_purchase_summary(info_before, info_after, {"name": item['name']}, lang_code, user_access=user_main_uuid_record)
                    
                    purchased_item_name = escape_markdown(item['name'])
                    success_message = (
                        f"✅ *خرید با موفقیت انجام شد*\\!\n\n"
                        f"آیتم «*{purchased_item_name}*» برای شما فعال شد\\.\n\n"
                        f"{summary_text}\n\n"
                        f"💰 *موجودی امتیاز فعلی:* {user_points}"
                    )
                    _safe_edit(uid, msg_id, success_message, reply_markup=menu.achievement_shop_menu(user_points, access_rights))
                else:
                    db.add_achievement_points(uid, item['cost']) # بازگرداندن امتیاز در صورت خطا
                    bot.answer_callback_query(call.id, "❌ خطایی در اعمال تغییرات رخ داد. امتیاز شما بازگردانده شد.", show_alert=True)
            else:
                bot.answer_callback_query(call.id, "❌ امتیاز شما کافی نیست.", show_alert=True)

        # --- 4. مدیریت کلیک روی دکمه آیتم غیرقابل خرید ---
        elif data == "shop:insufficient_points":
            bot.answer_callback_query(call.id, "❌ امتیاز شما برای خرید این آیتم کافی نیست.", show_alert=False)

    except Exception as e:
        logger.error(f"Error in handle_shop_callbacks: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "خطای داخلی رخ داد. لطفاً دوباره تلاش کنید.", show_alert=True)
        # بازگرداندن کاربر به منوی اصلی فروشگاه در صورت بروز خطا
        user = db.user(uid)
        user_points = user.get('achievement_points', 0) if user else 0
        access_rights = db.get_user_access_rights(uid)
        prompt = (
            f"🛍️ *{escape_markdown('فروشگاه دستاوردها')}*\n\n"
            f"{escape_markdown('با امتیازهای خود می‌توانید جوایز زیر را خریداری کنید.')}\n\n"
            f"💰 *{escape_markdown('موجودی امتیاز شما:')} {user_points}*"
        )
        _safe_edit(uid, msg_id, prompt, reply_markup=menu.achievement_shop_menu(user_points, access_rights))


def handle_connection_doctor(call: types.CallbackQuery):
    """
    (نسخه نهایی و بازنویسی شده)
    وضعیت سرویس کاربر و سرورها را به همراه تحلیل هوشمند بار ترافیکی نمایش می‌دهد.
    """
    uid, msg_id = call.from_user.id, call.message.id
    lang_code = db.get_user_language(uid)

    _safe_edit(uid, msg_id, escape_markdown(get_string("doctor_checking_status", lang_code)), reply_markup=None)
    
    report_lines = [f"*{escape_markdown(get_string('doctor_report_title', lang_code))}*", "`──────────────────`"]
    
    # --- بخش ۱: بررسی وضعیت کلی اکانت کاربر ---
    user_uuids = db.uuids(uid)
    if not user_uuids:
        from ..user_router import go_back_to_main
        go_back_to_main(call=call)
        return
        
    user_info = combined_handler.get_combined_user_info(user_uuids[0]['uuid'])
    is_user_ok = user_info and user_info.get('is_active') and (user_info.get('expire') is None or user_info.get('expire') >= 0)
    status_text = f"*{escape_markdown(get_string('fmt_status_active' if is_user_ok else 'fmt_status_inactive', lang_code))}*"
    report_lines.append(f"✅ {escape_markdown(get_string('doctor_account_status_label', lang_code))} {status_text}")

    # --- بخش ۲: بررسی وضعیت آنلاین بودن سرورها ---
    active_panels = db.get_active_panels()
    all_servers_ok = True
    for panel in active_panels:
        panel_name_raw = panel.get('name', '...')
        server_status_label = escape_markdown(get_string('doctor_server_status_label', lang_code).format(panel_name=panel_name_raw))
        
        handler_class = HiddifyAPIHandler if panel['panel_type'] == 'hiddify' else MarzbanAPIHandler
        handler = handler_class(panel)
        is_online = handler.check_connection()
        if not is_online:
            all_servers_ok = False
        status_text_server = f"*{escape_markdown(get_string('server_status_online' if is_online else 'server_status_offline', lang_code))}*"
        report_lines.append(f"{'✅' if is_online else '🚨'} {server_status_label} {status_text_server}")

    # --- بخش ۳: تحلیل هوشمند بار سرور (ایده جدید) ---
    try:
        all_users_data = combined_handler.get_all_users_combined()
        total_active_users = sum(1 for u in all_users_data if u.get('is_active'))
        activity_stats = db.count_recently_active_users(all_users_data, minutes=15)
        
        analysis_title = escape_markdown("📈 تحلیل هوشمند بار سرور (۱۵ دقیقه اخیر):")
        
        def get_load_indicator(online_count, total_count):
            if total_count == 0: return "⚪️", "بدون اطلاعات"
            load_ratio = online_count / total_count
            if load_ratio < 0.1: return "🟢", "خلوت"
            if load_ratio < 0.3: return "🟡", "عادی"
            if load_ratio < 0.6: return "🟠", "شلوغ"
            return "🔴", "بسیار شلوغ"

        report_lines.extend([
            "`──────────────────`",
            f"*{analysis_title}*"
        ])
        
        # نمایش شاخص بار برای هر سرور
        access_rights = db.get_user_access_rights(uid)
        if access_rights.get('has_access_de'):
            icon, text = get_load_indicator(activity_stats.get('hiddify', 0), total_active_users)
            report_lines.append(f"  {icon} سرور آلمان 🇩🇪: *{escape_markdown(text)}*")
        if access_rights.get('has_access_fr'):
            icon, text = get_load_indicator(activity_stats.get('marzban_fr', 0), total_active_users)
            report_lines.append(f"  {icon} سرور فرانسه 🇫🇷: *{escape_markdown(text)}*")
        if access_rights.get('has_access_tr'):
            icon, text = get_load_indicator(activity_stats.get('marzban_tr', 0), total_active_users)
            report_lines.append(f"  {icon} سرور ترکیه 🇹🇷: *{escape_markdown(text)}*")
        if access_rights.get('has_access_us'):
            icon, text = get_load_indicator(activity_stats.get('marzban_us', 0), total_active_users)
            report_lines.append(f"  {icon} سرور آمریکا 🇺🇸: *{escape_markdown(text)}*")
            
    except Exception as e:
        logger.error(f"Error getting activity stats for doctor: {e}")

    # --- بخش ۴: پیشنهاد نهایی (ایده جدید) ---
    report_lines.append("`──────────────────`")
    suggestion_title = f"💡 *{escape_markdown(get_string('doctor_suggestion_title', lang_code))}*"
    suggestion_body = ""
    kb = types.InlineKeyboardMarkup()
    
    if not is_user_ok and user_info.get('expire') is not None and user_info.get('expire') < 0:
        suggestion_body = escape_markdown("اکانت شما منقضی شده است. برای اتصال مجدد، لطفاً سرویس خود را تمدید کنید.")
        kb.add(types.InlineKeyboardButton("🚀 تمدید سرویس", callback_data="view_plans"))
    elif not is_user_ok:
        suggestion_body = escape_markdown("اکانت شما غیرفعال است. لطفاً برای بررسی وضعیت با پشتیبانی تماس بگیرید.")
        kb.add(types.InlineKeyboardButton("💬 تماس با پشتیبانی", callback_data="support"))
    elif not all_servers_ok:
        suggestion_body = escape_markdown("به نظر می‌رسد در یک یا چند سرور اختلال وجود دارد. لطفاً کمی صبر کنید و مجدداً تلاش کنید. تیم فنی در حال بررسی است.")
    else:
        suggestion_body = escape_markdown(get_string('doctor_suggestion_body', lang_code))

    report_lines.append(f"{suggestion_title}\n{suggestion_body}")
    
    kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
    _safe_edit(uid, msg_id, "\n".join(report_lines), reply_markup=kb)


def handle_coming_soon(call: types.CallbackQuery):
    """یک آلرت "به زودی" نمایش می‌دهد."""
    lang_code = db.get_user_language(call.from_user.id)
    alert_text = get_string('msg_coming_soon_alert', lang_code)
    bot.answer_callback_query(call.id, text=alert_text, show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data == "daily_checkin")
def daily_checkin_handler(call):
    user_id = call.from_user.id
    
    # فراخوانی متدی که در مرحله ۱ ساختیم
    result = db.claim_daily_checkin(user_id)
    
    if result['status'] == 'already_claimed':
        # اگر امروز قبلاً گرفته باشد، فقط یک هشدار (Alert) نمایش می‌دهیم
        text = (
            f"✋ امروز سهمیه‌تو گرفتی!\n\n"
            f"🔥 رکورد فعلی: {result['streak']} روز متوالی\n"
            f"⏰ فردا دوباره سر بزن."
        )
        bot.answer_callback_query(call.id, text, show_alert=True)
        
    elif result['status'] == 'success':
        # اگر موفق بود، پیام تبریک می‌فرستیم
        points = result['points']
        streak = result['streak']
        
        msg = (
            f"✅ *حضور امروزت ثبت شد!*\n\n"
            f"💰 پاداش دریافتی: *{points} سکه*\n"
            f"🔥 رکورد متوالی: *{streak} روز*\n\n"
            f"💡 _هر روز سر بزن تا رکوردت خراب نشه!_"
        )
        
        # نمایش پیام موفقیت کوچک بالای صفحه
        bot.answer_callback_query(call.id, f"🎉 {points} سکه دریافت شد!", show_alert=False)
        
        # ارسال پیام کامل
        bot.send_message(user_id, msg, parse_mode="Markdown")

# --- تنظیمات گردونه ---
SPIN_COST = 50  # هزینه هر بار چرخش
REWARDS_CONFIG = [
    {"name": "پوچ 😢",           "weight": 40, "type": "none"},
    {"name": "۲۰ سکه بازگشت 🪙", "weight": 30, "type": "points", "value": 20},
    {"name": "۵۰۰ مگابایت حجم 🎁", "weight": 20, "type": "volume", "value": 0.5},
    {"name": "۱ گیگابایت حجم 🔥",  "weight": 10, "type": "volume", "value": 1.0},
]

@bot.callback_query_handler(func=lambda call: call.data == "lucky_spin_menu")
def lucky_spin_menu_handler(call):
    """منوی اولیه گردونه برای نمایش قوانین و دکمه شروع"""
    user_id = call.from_user.id
    user_data = db.user(user_id)
    current_points = user_data.get('achievement_points', 0)
    
    msg = (
        f"🎰 **گردونه شانس**\n\n"
        f"💰 موجودی شما: *{current_points} سکه*\n"
        f"💎 هزینه هر چرخش: *{SPIN_COST} سکه*\n\n"
        f"🎁 **جوایز احتمالی:**\n"
        f"▫️ حجم اضافه (تا ۱ گیگ)\n"
        f"▫️ سکه رایگان\n"
        f"▫️ و شاید هم پوچ!\n\n"
        f"آیا شانست رو امتحان می‌کنی؟"
    )
    
    kb = types.InlineKeyboardMarkup()
    if current_points >= SPIN_COST:
        kb.add(types.InlineKeyboardButton("🎲 بچرخون! (50- سکه)", callback_data="do_spin"))
    else:
        kb.add(types.InlineKeyboardButton("❌ موجودی کافی نیست", callback_data="noop"))
    
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="shop:main"))
    
    bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data == "do_spin")
def do_spin_handler(call):
    """اجرای عملیات چرخش"""
    user_id = call.from_user.id
    
    # ۱. تلاش برای کسر امتیاز
    # متد spend_achievement_points را قبلا در AchievementDB داشتید (فایل achievement.py)
    if not db.spend_achievement_points(user_id, SPIN_COST):
        bot.answer_callback_query(call.id, "موجودی شما کافی نیست!", show_alert=True)
        return

    # ۲. نمایش انیمیشن (اختیاری: صرفا با ویرایش متن حس چرخش می‌دهیم)
    try:
        bot.edit_message_text("🎰 در حال چرخش... 🎲", call.message.chat.id, call.message.message_id)
        time.sleep(1.5) # وقفه کوتاه برای هیجان
    except:
        pass

    # ۳. انتخاب جایزه بر اساس شانس (Weight)
    reward = random.choices(REWARDS_CONFIG, weights=[r['weight'] for r in REWARDS_CONFIG], k=1)[0]
    
    # ۴. اعمال جایزه
    result_msg = ""
    if reward['type'] == "none":
        result_msg = f"😢 اوه! {reward['name']}\nشانس بعدی شاید بهتر باشه."
        
    elif reward['type'] == "points":
        db.add_achievement_points(user_id, reward['value'])
        result_msg = f"🎉 تبریک! برنده شدی:\n**{reward['name']}**"
        
    elif reward['type'] == "volume":
        # پیدا کردن UUID کاربر برای واریز حجم
        user_uuids = db.uuids(user_id)
        if user_uuids:
            # استفاده از تابع هوشمند rewards.py برای واریز حجم
            first_uuid = user_uuids[0]['uuid']
            success = _apply_reward_intelligently(user_id, first_uuid, add_gb=reward['value'], add_days=0)
            if success:
                result_msg = f"🔥 عالیه! برنده شدی:\n**{reward['name']}**\n(به سرویس شما اضافه شد)"
            else:
                # اگر به هر دلیلی نشد حجم بدیم، سکه رو پس میدیم
                db.add_achievement_points(user_id, SPIN_COST)
                result_msg = "❌ خطا در واریز حجم. سکه‌های شما برگشت داده شد."
        else:
            # کاربر سرویس فعال ندارد، سکه رو پس میدیم
            db.add_achievement_points(user_id, SPIN_COST)
            result_msg = "❌ شما سرویس فعالی برای دریافت حجم ندارید. سکه‌ها برگشت داده شد."

    # ۵. نمایش نتیجه نهایی
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎲 دوباره بچرخون", callback_data="lucky_spin_menu"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به فروشگاه", callback_data="shop:main"))
    
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, result_msg, reply_markup=kb, parse_mode="Markdown")