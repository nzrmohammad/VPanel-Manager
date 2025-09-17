import logging
from telebot import types
import jdatetime
from datetime import datetime, timedelta
import pytz

# --- Local Imports ---
from ..database import db
from ..menu import menu
from ..utils import escape_markdown, _safe_edit
from ..language import get_string
from ..user_formatters import fmt_registered_birthday_info, fmt_referral_page
from ..config import ADMIN_IDS, ADMIN_SUPPORT_CONTACT, TUTORIAL_LINKS, ACHIEVEMENTS
from .. import combined_handler
from ..hiddify_api_handler import HiddifyAPIHandler
from ..marzban_api_handler import MarzbanAPIHandler


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
    """پیام راهنمای تماس با پشتیبانی را نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)
    admin_contact = escape_markdown(ADMIN_SUPPORT_CONTACT)
    
    title = f'*{escape_markdown(get_string("support_guidance_title", lang_code))}*'
    body_template = get_string('support_guidance_body', lang_code)
    body = escape_markdown(body_template).replace(escape_markdown('{admin_contact}'), f'*{admin_contact}*')
    
    text = f"{title}\n\n{body}"
    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
    _safe_edit(uid, msg_id, text, reply_markup=kb, parse_mode="MarkdownV2")


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
    """تمام callback های مربوط به فروشگاه دستاوردها را با منطق جدید و هوشمند مدیریت می‌کند."""
    uid, msg_id, data = call.from_user.id, call.message.message_id, call.data

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

    elif data.startswith("shop:buy:"):
        from ..config import ACHIEVEMENT_SHOP_ITEMS
        item_key = data.split(":")[2]
        item = ACHIEVEMENT_SHOP_ITEMS.get(item_key)

        if not item: return

        if db.spend_achievement_points(uid, item['cost']):
            user_uuids = db.uuids(uid)
            if user_uuids:
                user_main_uuid = user_uuids[0]['uuid']
                purchase_successful = False

                target = item.get("target")
                add_gb = item.get("gb", 0)
                add_days = item.get("days", 0)

                target_panel = None
                if target == 'de':
                    target_panel = 'hiddify'
                elif target == 'fr_tr':
                    target_panel = 'marzban'

                purchase_successful = combined_handler.modify_user_on_all_panels(
                    user_main_uuid, add_gb=add_gb, add_days=add_days, target_panel_type=target_panel
                )

                if purchase_successful:
                    db.log_shop_purchase(uid, item_key, item['cost'])
                    bot.answer_callback_query(call.id, "✅ خرید شما با موفقیت انجام شد.", show_alert=True)

                    user = db.user(uid)
                    user_points = user.get('achievement_points', 0) if user else 0
                    
                    access_rights = db.get_user_access_rights(uid)

                    purchased_item_name = escape_markdown(item['name'])
                    success_message = (
                        f"✅ *خرید با موفقیت انجام شد*\\!\n\n"
                        f"شما آیتم «*{purchased_item_name}*» را خریداری کردید و تغییرات روی سرویس شما اعمال شد\\.\n\n"
                        f"💰 *موجودی امتیاز فعلی:* {user_points}"
                    )
                    _safe_edit(uid, msg_id, success_message, reply_markup=menu.achievement_shop_menu(user_points, access_rights))
                else:
                    db.add_achievement_points(uid, item['cost'])
                    bot.answer_callback_query(call.id, "❌ خطایی در اعمال تغییرات رخ داد. امتیاز شما بازگردانده شد.", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "❌ امتیاز شما کافی نیست.", show_alert=True)

    elif data == "shop:insufficient_points":
        bot.answer_callback_query(call.id, "❌ امتیاز شما برای خرید این آیتم کافی نیست.", show_alert=False)


def handle_connection_doctor(call: types.CallbackQuery):
    """وضعیت سرویس کاربر و سرورها را بررسی می‌کند."""
    uid, msg_id = call.from_user.id, call.message.id
    lang_code = db.get_user_language(uid)

    _safe_edit(uid, msg_id, escape_markdown(get_string("doctor_checking_status", lang_code)), reply_markup=None)
    
    report_lines = [f"*{escape_markdown(get_string('doctor_report_title', lang_code))}*", "`──────────────────`"]
    
    user_uuids = db.uuids(uid)
    if not user_uuids:
        from ..user_router import go_back_to_main
        go_back_to_main(call=call)
        return
        
    user_info = combined_handler.get_combined_user_info(user_uuids[0]['uuid'])
    account_status_label = escape_markdown(get_string('doctor_account_status_label', lang_code))
    is_ok = user_info and user_info.get('is_active') and (user_info.get('expire') is None or user_info.get('expire') >= 0)
    status_text = f"*{escape_markdown(get_string('fmt_status_active' if is_ok else 'fmt_status_inactive', lang_code))}*"
    report_lines.append(f"✅ {account_status_label} {status_text}")

    active_panels = db.get_active_panels()
    for panel in active_panels:
        panel_name_raw = panel.get('name', '...')
        server_status_label = escape_markdown(get_string('doctor_server_status_label', lang_code).format(panel_name=panel_name_raw))
        
        handler_class = HiddifyAPIHandler if panel['panel_type'] == 'hiddify' else MarzbanAPIHandler
        handler = handler_class(panel)
        is_online = handler.check_connection()
        status_text = f"*{escape_markdown(get_string('server_status_online' if is_online else 'server_status_offline', lang_code))}*"
        report_lines.append(f"{'✅' if is_online else '🚨'} {server_status_label} {status_text}")

    try:
        from ..database import db as db_instance
        activity_stats = db_instance.count_recently_active_users(minutes=15)
        analysis_title = escape_markdown(get_string('doctor_analysis_title', lang_code))
        line_template = get_string('doctor_online_users_line', lang_code)
        
        report_lines.extend([
            "`──────────────────`",
            f"📈 *{analysis_title}*",
            escape_markdown(line_template.format(count=activity_stats.get('hiddify', 0), server_name="آلمان 🇩🇪")),
            escape_markdown(line_template.format(count=activity_stats.get('marzban_fr', 0), server_name="فرانسه 🇫🇷")),
            escape_markdown(line_template.format(count=activity_stats.get('marzban_tr', 0), server_name="ترکیه 🇹🇷")),
            escape_markdown(line_template.format(count=activity_stats.get('marzban_us', 0), server_name="آمریکا 🇺🇸"))
        ])
    except Exception as e:
        logger.error(f"Error getting activity stats for doctor: {e}")

    report_lines.extend([
        "`──────────────────`",
        f"💡 *{escape_markdown(get_string('doctor_suggestion_title', lang_code))}*\n{escape_markdown(get_string('doctor_suggestion_body', lang_code))}"
    ])
    
    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
    _safe_edit(uid, msg_id, "\n".join(report_lines), reply_markup=kb)


def handle_coming_soon(call: types.CallbackQuery):
    """یک آلرت "به زودی" نمایش می‌دهد."""
    lang_code = db.get_user_language(call.from_user.id)
    alert_text = get_string('msg_coming_soon_alert', lang_code)
    bot.answer_callback_query(call.id, text=alert_text, show_alert=True)