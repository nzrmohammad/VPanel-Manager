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
    """صفحه دستاوردها و نشان‌های کاربر را نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)
    
    user_badges = db.get_user_achievements(uid)
    unlocked_lines = [
        (f"{badge_data.get('icon', '🎖️')} *{escape_markdown(badge_data.get('name', code))}*\n"
         f"{escape_markdown(badge_data.get('description', '...'))}")
        for code in user_badges if (badge_data := ACHIEVEMENTS.get(code))
    ]

    title = f"*{escape_markdown(get_string('achievements_page_title', lang_code))}*"
    raw_intro = get_string("achievements_intro", lang_code)
    escaped_intro = escape_markdown(raw_intro).replace('\\*امتیاز\\*', '*امتیاز*')

    if not unlocked_lines:
        final_text = f"{title}\n\n{escaped_intro}"
    else:
        unlocked_section_title = get_string("achievements_unlocked_section", lang_code)
        unlocked_section = f"*{escape_markdown(unlocked_section_title)}*\n" + "\n\n".join(unlocked_lines)
        final_text = f"{title}\n\n{escaped_intro}\n\n{unlocked_section}"
    
    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
    _safe_edit(uid, msg_id, final_text, reply_markup=kb)


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

# در فایل bot/user_handlers/various.py

def handle_shop_callbacks(call: types.CallbackQuery):
    """تمام callback های مربوط به فروشگاه دستاوردها را با منطق جدید و هوشمند مدیریت می‌کند."""
    uid, msg_id, data = call.from_user.id, call.message.message_id, call.data
    from ..config import ACHIEVEMENT_SHOP_ITEMS
    
    if data == "shop:main":
        user = db.user(uid)
        user_points = user.get('achievement_points', 0) if user else 0
        
        user_uuids = db.uuids(uid)
        access_rights = {'has_access_de': False, 'has_access_fr': False, 'has_access_tr': False}
        if user_uuids:
            first_uuid_record = db.uuid_by_id(uid, user_uuids[0]['id'])
            if first_uuid_record:
                access_rights['has_access_de'] = first_uuid_record.get('has_access_de', False)
                access_rights['has_access_fr'] = first_uuid_record.get('has_access_fr', False)
                access_rights['has_access_tr'] = first_uuid_record.get('has_access_tr', False)

        prompt = (
            f"🛍️ *{escape_markdown('فروشگاه دستاوردها')}*\n\n"
            f"{escape_markdown('با امتیازهای خود می‌توانید جوایز زیر را خریداری کنید.')}\n\n"
            f"💰 *{escape_markdown('موجودی امتیاز شما:')} {user_points}*"
        )
        _safe_edit(uid, msg_id, prompt, reply_markup=menu.achievement_shop_menu(user_points, access_rights))

    elif data.startswith("shop:confirm:"):
        item_key = data.split(":")[2]
        item = ACHIEVEMENT_SHOP_ITEMS.get(item_key)
        if not item: return

        confirm_text = (
            f"❓ *{escape_markdown('تایید خرید از فروشگاه')}*\n\n"
            f"{escape_markdown(f'آیا از خرج کردن {item["cost"]} امتیاز برای خرید «{item["name"]}» اطمینان دارید؟')}"
        )
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("✅ بله، خرید", callback_data=f"shop:execute:{item_key}"),
            types.InlineKeyboardButton("❌ انصراف", callback_data="shop:main")
        )
        _safe_edit(uid, msg_id, confirm_text, reply_markup=kb)

    elif data.startswith("shop:execute:"):
        item_key = data.split(":")[2]
        item = ACHIEVEMENT_SHOP_ITEMS.get(item_key)
        
        if not item: return

        if db.spend_achievement_points(uid, item['cost']):
            bot.answer_callback_query(call.id) # پاسخ به کلیک کاربر برای تجربه کاربری بهتر
            
            user_uuids = db.uuids(uid)
            if user_uuids:
                user_main_uuid = user_uuids[0]['uuid']
                
                target = item.get("target")
                add_gb = item.get("gb", 0)
                add_days = item.get("days", 0)
                target_panel = 'hiddify' if target == 'de' else 'marzban' if target == 'fr_tr' else None
                
                purchase_successful = combined_handler.modify_user_on_all_panels(
                    user_main_uuid, add_gb=add_gb, add_days=add_days, target_panel_type=target_panel
                )

                if purchase_successful:
                    db.log_shop_purchase(uid, item_key, item['cost'])
                    
                    # --- تغییر اصلی برای نمایش پیام موفقیت در پایین منو ---
                    user = db.user(uid)
                    user_points = user.get('achievement_points', 0) if user else 0
                    access_rights = {'has_access_de': False, 'has_access_fr': False, 'has_access_tr': False}
                    first_uuid_record = db.uuid_by_id(uid, user_uuids[0]['id'])
                    if first_uuid_record:
                        access_rights['has_access_de'] = first_uuid_record.get('has_access_de', False)
                        access_rights['has_access_fr'] = first_uuid_record.get('has_access_fr', False)
                        access_rights['has_access_tr'] = first_uuid_record.get('has_access_tr', False)

                    prompt = (
                        f"🛍️ *{escape_markdown('فروشگاه دستاوردها')}*\n\n"
                        f"{escape_markdown('با امتیازهای خود می‌توانید جوایز زیر را خریداری کنید.')}\n\n"
                        f"💰 *{escape_markdown('موجودی امتیاز شما:')} {user_points}*"
                    )
                    
                    # ساخت فوتر موفقیت به روشی کاملاً امن
                    purchased_item_name = item['name']
                    success_footer = (
                        f"\n`──────────────────`\n"
                        f"✅ {escape_markdown(f'خرید «{purchased_item_name}» با موفقیت انجام شد.')}"
                    )
                    
                    final_message = prompt + success_footer
                    _safe_edit(uid, msg_id, final_message, reply_markup=menu.achievement_shop_menu(user_points, access_rights))
                    # ----------------------------------------------------
                else:
                    db.add_achievement_points(uid, item['cost']) # بازگرداندن امتیاز
                    bot.answer_callback_query(call.id, "❌ خطایی در اعمال تغییرات رخ داد. امتیاز شما بازگردانده شد.", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "❌ امتیاز شما کافی نیست.", show_alert=True)

    elif data == "shop:insufficient_points":
        bot.answer_callback_query(call.id, "❌ امتیاز شما برای خرید این آیتم کافی نیست.", show_alert=False)


def handle_connection_doctor(call: types.CallbackQuery):
    """وضعیت سرویس کاربر و سرورها را بررسی می‌کند."""
    uid, msg_id = call.from_user.id, call.message.message_id
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
            escape_markdown(line_template.format(count=activity_stats.get('marzban_tr', 0), server_name="ترکیه 🇹🇷"))
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