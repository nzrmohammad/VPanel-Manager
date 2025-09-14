import logging
from telebot import types
import io
import qrcode
import urllib.parse
from datetime import datetime, timedelta
import pytz
import jdatetime


# --- Local Imports ---
from ..database import db
from .. import combined_handler
from ..menu import menu
from ..utils import escape_markdown, _safe_edit, load_service_plans, load_json_file
from ..language import get_string
from ..user_formatters import (
    fmt_one, quick_stats, fmt_service_plans, fmt_panel_quick_stats,
    fmt_user_payment_history, fmt_user_usage_history, fmt_referral_page,
    fmt_user_account_page
)
from ..config import CARD_PAYMENT_INFO, ADMIN_SUPPORT_CONTACT, ONLINE_PAYMENT_LINK, TUTORIAL_LINKS
from ..hiddify_api_handler import HiddifyAPIHandler
from ..marzban_api_handler import MarzbanAPIHandler


logger = logging.getLogger(__name__)
bot = None


def initialize_handlers(b):
    """نمونه bot را از فایل اصلی دریافت می‌کند."""
    global bot
    bot = b

# =============================================================================
# 1. Main Account Menus and Information Display
# =============================================================================

def show_manage_menu(call: types.CallbackQuery = None, message: types.Message = None, override_text: str = None, target_user_id: int = None, target_msg_id: int = None):
    """لیست اکانت‌های فعال کاربر را به همراه دکمه افزودن اکانت جدید نمایش می‌دهد."""
    uid = target_user_id or (call.from_user.id if call else message.from_user.id)
    msg_id = target_msg_id or (call.message.message_id if call else (message.message_id if message else None))

    lang_code = db.get_user_language(uid)

    user_uuids = db.uuids(uid)
    user_accounts_details = []
    if user_uuids:
        for row in user_uuids:
            if (info := combined_handler.get_combined_user_info(row["uuid"])):
                info['id'] = row['id']
                user_accounts_details.append(info)

    text = f'*{escape_markdown(get_string("account_list_title", lang_code))}*'
    if override_text:
        text = escape_markdown(override_text)

    reply_markup = menu.accounts(user_accounts_details, lang_code)

    if msg_id:
        _safe_edit(uid, msg_id, text, reply_markup=reply_markup)
    elif message:
        bot.send_message(uid, text, reply_markup=reply_markup, parse_mode="MarkdownV2")


def show_account_details(call: types.CallbackQuery):
    """جزئیات کامل یک اکانت انتخاب شده را نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)
    uuid_id = int(call.data.split("_")[1])

    row = db.uuid_by_id(uid, uuid_id)
    if row and (info := combined_handler.get_combined_user_info(row["uuid"])):
        daily_usage_data = db.get_usage_since_midnight(uuid_id)
        text = fmt_one(info, daily_usage_data, lang_code=lang_code)
        _safe_edit(uid, msg_id, text, reply_markup=menu.account_menu(uuid_id, lang_code=lang_code))
    else:
        bot.answer_callback_query(call.id, get_string("err_acc_not_found", lang_code), show_alert=True)


def show_quick_stats(call: types.CallbackQuery):
    """آمار فوری اولین اکانت کاربر را نمایش می‌دهد."""
    uid = call.from_user.id
    lang_code = db.get_user_language(uid)
    text, menu_data = quick_stats(db.uuids(uid), page=0, lang_code=lang_code)
    reply_markup = menu.quick_stats_menu(menu_data['num_accounts'], menu_data['current_page'], lang_code=lang_code)
    _safe_edit(uid, call.message.message_id, text, reply_markup=reply_markup)


def show_quick_stats_page(call: types.CallbackQuery):
    """برای جابجایی بین اکانت‌ها در حالت آمار فوری استفاده می‌شود."""
    uid = call.from_user.id
    lang_code = db.get_user_language(uid)
    page = int(call.data.split("_")[3])
    text, menu_data = quick_stats(db.uuids(uid), page=page, lang_code=lang_code)
    reply_markup = menu.quick_stats_menu(menu_data['num_accounts'], menu_data['current_page'], lang_code=lang_code)
    _safe_edit(uid, call.message.message_id, text, reply_markup=reply_markup)


def show_user_account_page(call: types.CallbackQuery):
    """صفحه کامل حساب کاربری را نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)

    text = fmt_user_account_page(uid, lang_code)

    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
    _safe_edit(uid, msg_id, text, reply_markup=kb)


# =============================================================================
# 2. Subscription Links, QR Code & Web Login
# =============================================================================

def handle_get_links_request(call: types.CallbackQuery):
    """منوی انتخاب نوع لینک اشتراک (Normal یا Base64) را نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)
    uuid_id = int(call.data.split("_")[1])

    raw_text = get_string("prompt_get_links", lang_code)
    lines = [escape_markdown(line) for line in raw_text.split('\n')]
    text_to_send = "\n".join(lines).replace('Normal:', '*Normal:*').replace('Base64:', '*Base64:*')

    if call.message.photo:
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception: pass
        bot.send_message(uid, text_to_send, reply_markup=menu.get_links_menu(uuid_id, lang_code=lang_code), parse_mode="MarkdownV2")
    else:
        _safe_edit(chat_id=uid, msg_id=msg_id, text=text_to_send, reply_markup=menu.get_links_menu(uuid_id, lang_code=lang_code))


def send_subscription_link(call: types.CallbackQuery):
    """
    لینک اشتراک و QR Code را به همراه دکمه‌های deep link (با منطق درخواستی کاربر) ارسال می‌کند.
    """
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)
    parts = call.data.split("_")
    link_type, uuid_id = parts[1], int(parts[2])

    row = db.uuid_by_id(uid, uuid_id)
    if not row:
        bot.answer_callback_query(call.id, get_string("err_acc_not_found", lang_code), show_alert=True)
        return

    try:
        user_uuid = row['uuid']
        config_name = row.get('name', 'CloudVibe')
        WEBAPP_BASE_URL = "https://panel.cloudvibe.ir"

        normal_sub_link = f"{WEBAPP_BASE_URL.rstrip('/')}/user/sub/{user_uuid}#{urllib.parse.quote(config_name)}"
        b64_sub_link = f"{WEBAPP_BASE_URL.rstrip('/')}/user/sub/b64/{user_uuid}#{urllib.parse.quote(config_name)}"
        final_sub_link = b64_sub_link if link_type == 'b64' else normal_sub_link

        qr_img = qrcode.make(final_sub_link)
        stream = io.BytesIO()
        qr_img.save(stream, 'PNG')
        stream.seek(0)

        raw_template = get_string("msg_link_ready", lang_code)
        escaped_link = f"`{escape_markdown(final_sub_link)}`"
        message_text = (f'*{escape_markdown(raw_template.splitlines()[0].format(link_type=link_type.capitalize()))}*\n\n'
                        f'{escape_markdown(raw_template.splitlines()[2])}\n{escaped_link}')

        kb = types.InlineKeyboardMarkup(row_width=2)

        def create_redirect_button(app_name: str, deep_link: str):
            params = {'url': deep_link, 'app_name': app_name}
            query_string = urllib.parse.urlencode(params)
            redirect_page_url = f"{WEBAPP_BASE_URL}/app/redirect?{query_string}"
            return types.InlineKeyboardButton(f"📲 افزودن به {app_name}", url=redirect_page_url)

        hiddify_deep_link = f"hiddify://import/{normal_sub_link}"

        if link_type == 'b64':
            streisand_deep_link = f"streisand://import/{b64_sub_link}"
            v2box_deep_link = f"v2box://import/?url={urllib.parse.quote(b64_sub_link)}"

            kb.add(create_redirect_button("Streisand", streisand_deep_link),
                   create_redirect_button("V2Box", v2box_deep_link))
            kb.add(create_redirect_button("Hiddify", hiddify_deep_link))

        else:
            v2rayng_deep_link = f"v2rayng://install-sub/?url={urllib.parse.quote(normal_sub_link)}"
            happ_deep_link = f"happ://add/{normal_sub_link}"

            kb.add(create_redirect_button("V2rayNG", v2rayng_deep_link),
                   create_redirect_button("HAPP", happ_deep_link))
            kb.add(create_redirect_button("Hiddify", hiddify_deep_link))

        kb.add(types.InlineKeyboardButton(get_string("back", lang_code), callback_data=f"getlinks_{uuid_id}"))

        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception as e:
            logger.warning(f"Could not delete old message {call.message.message.id}: {e}")

        bot.send_photo(uid, photo=stream, caption=message_text, reply_markup=kb, parse_mode="MarkdownV2")

    except Exception as e:
        logger.error(f"Failed to generate/send subscription link for UUID {row.get('uuid')}: {e}", exc_info=True)
        bot.answer_callback_query(call.id, escape_markdown(get_string("err_link_generation", lang_code)), show_alert=True)
        _safe_edit(uid, msg_id, escape_markdown(get_string("err_try_again", lang_code)), reply_markup=menu.get_links_menu(uuid_id, lang_code=lang_code))


def handle_web_login_request(call: types.CallbackQuery):
    """یک لینک ورود یکبار مصرف به پنل وب برای کاربر ایجاد می‌کند."""
    uid, msg_id = call.from_user.id, call.message.message_id
    user_uuids = db.uuids(uid)
    if not user_uuids:
        bot.answer_callback_query(call.id, "ابتدا باید یک اکانت ثبت کنید.", show_alert=True)
        return

    user_uuid = user_uuids[0]['uuid']
    token = db.create_login_token(user_uuid)
    base_url = "https://panel.cloudvibe.ir" # این آدرس باید مطابق با تنظیمات شما باشد
    login_url = f"{base_url}/login/token/{token}"

    text = "✅ لینک ورود یکبار مصرف شما ایجاد شد.\n\nاین لینک به مدت ۵ دقیقه معتبر است و پس از یکبار استفاده منقضی می‌شود."
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("ورود به پنل کاربری", url=login_url))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="back"))

    _safe_edit(uid, msg_id, text, reply_markup=kb, parse_mode=None)


# =============================================================================
# 3. Usage and Payment History
# =============================================================================

def handle_payment_history(call: types.CallbackQuery):
    """سابقه پرداخت‌های یک اکانت را به صورت صفحه‌بندی شده نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)
    parts = call.data.split('_');
    uuid_id, page = int(parts[2]), int(parts[3])

    row = db.uuid_by_id(uid, uuid_id)
    if row:
        payment_history = db.get_user_payment_history(uuid_id)
        text = fmt_user_payment_history(payment_history, row.get('name', get_string('unknown_user', lang_code)), page, lang_code=lang_code)
        kb = menu.create_pagination_menu(f"payment_history_{uuid_id}", page, len(payment_history), f"acc_{uuid_id}", lang_code)
        _safe_edit(uid, msg_id, text, reply_markup=kb)
    else:
        bot.answer_callback_query(call.id, get_string("err_acc_not_found", lang_code), show_alert=True)


def handle_usage_history(call: types.CallbackQuery):
    """لیست مصرف ۷ روز گذشته را نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)
    uuid_id = int(call.data.split("_")[2])

    row = db.uuid_by_id(uid, uuid_id)
    if row:
        history = db.get_user_daily_usage_history(uuid_id)
        text = fmt_user_usage_history(history, row.get('name', 'اکانت'), lang_code)
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data=f"acc_{uuid_id}"))
        _safe_edit(uid, msg_id, text, reply_markup=kb)

# =============================================================================
# 4. Service Plans and Payment
# =============================================================================

def show_plan_categories(call: types.CallbackQuery):
    """منوی دسته‌بندی پلن‌های فروش را نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)
    prompt = get_string("prompt_select_plan_category", lang_code)
    reply_markup = menu.plan_categories_menu(lang_code=lang_code)

    _safe_edit(uid, msg_id, prompt, reply_markup=reply_markup, parse_mode=None)

def show_addons_page(call: types.CallbackQuery):
    """(نسخه نهایی) صفحه خرید بسته‌های افزودنی را بر اساس دسترسی کاربر نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)

    all_addons = load_json_file('addons.json')
    user_data = db.user(uid)
    user_balance = user_data.get('wallet_balance', 0.0) if user_data else 0.0
    access_rights = db.get_user_access_rights(uid)

    prompt = (f"*{escape_markdown('➕ خرید بسته‌های افزودنی')}*\n\n"
              f"{escape_markdown('در این بخش می‌توانید به سرویس فعلی خود حجم یا زمان اضافه کنید.')}\n\n"
              f"💰 *{escape_markdown('موجودی شما:')} {user_balance:,.0f} تومان*")

    kb = types.InlineKeyboardMarkup(row_width=1)

    def create_addon_buttons(addons):
        buttons = []
        for addon in addons:
            price = addon.get('price', 0)
            is_affordable = user_balance >= price
            emoji = "✅" if is_affordable else "❌"
            price_str = "{:,.0f}".format(price)
            button_text = f"{emoji} {addon.get('name')} ({price_str} تومان)"
            callback_data = f"addon_confirm:{addon.get('type')}:{addon.get('name')}" if is_affordable else "wallet:insufficient"
            buttons.append(types.InlineKeyboardButton(button_text, callback_data=callback_data))
        return buttons

    # نمایش بسته‌های حجم آلمان
    if access_rights.get('has_access_de'):
        data_addons_de = [a for a in all_addons if a.get("type") == "data_de"]
        if data_addons_de:
            kb.add(types.InlineKeyboardButton("حجم 🇩🇪", callback_data="noop"))
            for btn in create_addon_buttons(data_addons_de):
                kb.add(btn)

    # نمایش بسته‌های حجم فرانسه
    if access_rights.get('has_access_fr'):
        data_addons_fr = [a for a in all_addons if a.get("type") == "data_fr"]
        if data_addons_fr:
            kb.add(types.InlineKeyboardButton("حجم 🇫🇷", callback_data="noop"))
            for btn in create_addon_buttons(data_addons_fr):
                kb.add(btn)

    if access_rights.get('has_access_us'):
        data_addons_us = [a for a in all_addons if a.get("type") == "data_us"]
        if data_addons_us:
            kb.add(types.InlineKeyboardButton("حجم 🇺🇸", callback_data="noop"))
            for btn in create_addon_buttons(data_addons_us):
                kb.add(btn)

    # نمایش بسته‌های حجم ترکیه
    if access_rights.get('has_access_tr'):
        data_addons_tr = [a for a in all_addons if a.get("type") == "data_tr"]
        if data_addons_tr:
            kb.add(types.InlineKeyboardButton("حجم 🇹🇷", callback_data="noop"))
            for btn in create_addon_buttons(data_addons_tr):
                kb.add(btn)
    
    # نمایش بسته‌های زمانی (برای همه)
    time_addons = [a for a in all_addons if a.get("type") == "time"]
    if time_addons:
        kb.add(types.InlineKeyboardButton("زمان", callback_data="noop"))
        for btn in create_addon_buttons(time_addons):
            kb.add(btn)
    
    kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="view_plans"))
    _safe_edit(uid, msg_id, prompt, reply_markup=kb)

def confirm_addon_purchase(call: types.CallbackQuery):
    """از کاربر برای خرید بسته افزودنی تاییدیه می‌گیرد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    parts = call.data.split(':')
    addon_type, addon_name = parts[1], parts[2]

    all_addons = load_json_file('addons.json')
    addon_to_buy = next((a for a in all_addons if a.get("type") == addon_type and a.get("name") == addon_name), None)
    
    if not addon_to_buy:
        bot.answer_callback_query(call.id, "بسته مورد نظر یافت نشد.", show_alert=True)
        return

    price = addon_to_buy.get('price', 0)
    
    confirm_prompt = (
        f"❓ *{escape_markdown('تایید نهایی')}*\n\n"
        f"{escape_markdown(f'آیا از خرید بسته «{addon_name}» به مبلغ {price:,.0f} تومان اطمینان دارید؟')}"
    )
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ بله، خرید", callback_data=f"addon_execute:{addon_type}:{addon_name}"),
        types.InlineKeyboardButton("❌ انصراف", callback_data="show_addons")
    )
    _safe_edit(uid, msg_id, confirm_prompt, reply_markup=kb)

def execute_addon_purchase(call: types.CallbackQuery):
    """(نسخه نهایی) خرید بسته افزودنی را بر اساس نوع آن نهایی می‌کند."""
    uid, msg_id = call.from_user.id, call.message.message_id
    parts = call.data.split(':')
    addon_type, addon_name = parts[1], parts[2]

    all_addons = load_json_file('addons.json')
    addon = next((a for a in all_addons if a.get("type") == addon_type and a.get("name") == addon_name), None)

    if not addon:
        bot.answer_callback_query(call.id, "بسته یافت نشد.", show_alert=True)
        return

    price = addon.get('price', 0)
    
    if not db.update_wallet_balance(uid, -price, 'addon_purchase', f"خرید افزودنی: {addon_name}"):
        bot.answer_callback_query(call.id, "موجودی شما کافی نیست.", show_alert=True)
        return

    user_uuids = db.uuids(uid)
    if not user_uuids:
        db.update_wallet_balance(uid, price, 'refund', f"بازگشت وجه به دلیل نبود اکانت: {addon_name}")
        bot.answer_callback_query(call.id, "شما اکانت فعالی برای اعمال بسته ندارید. وجه به حساب شما بازگردانده شد.", show_alert=True)
        return
        
    user_main_uuid = user_uuids[0]['uuid']
    add_gb = addon.get('gb', 0)
    add_days = addon.get('days', 0)

    target_panel_type = None
    if addon_type == 'data_de':
        target_panel_type = 'hiddify'
    elif addon_type in ['data_fr', 'data_tr', 'data_us']:
        target_panel_type = 'marzban'

    success = combined_handler.modify_user_on_all_panels(
        identifier=user_main_uuid, 
        add_gb=add_gb, 
        add_days=add_days,
        target_panel_type=target_panel_type
    )

    if success:
        bot.answer_callback_query(call.id, f"✅ بسته «{addon_name}» با موفقیت اعمال شد.", show_alert=True)
        show_addons_page(call)
    else:
        db.update_wallet_balance(uid, price, 'refund', f"بازگشت وجه به دلیل خطا در اعمال: {addon_name}")
        bot.answer_callback_query(call.id, "خطایی در اعمال بسته رخ داد. وجه به حساب شما بازگردانده شد.", show_alert=True)

def show_filtered_plans(call: types.CallbackQuery):
    """
    پلن‌های یک دسته‌بندی خاص را به همراه دکمه‌های خرید نمایش می‌دهد.
    """
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)
    plan_type = call.data.split(":")[1]

    # دریافت موجودی کاربر و لیست پلن‌ها
    user_data = db.user(uid)
    user_balance = user_data.get('wallet_balance', 0.0) if user_data else 0.0
    all_plans = load_service_plans()
    plans_to_show = [p for p in all_plans if p.get("type") == plan_type]

    # ساخت متن پیام با استفاده از فرمت‌کننده
    text = fmt_service_plans(plans_to_show, plan_type, lang_code=lang_code)

    # ساخت دکمه‌های خرید
    kb = types.InlineKeyboardMarkup(row_width=1)
    for plan in plans_to_show:
        price = plan.get('price', 0)
        is_affordable = user_balance >= price
        emoji = "✅" if is_affordable else "❌"
        price_str = "{:,.0f}".format(price)
        button_text = f"{emoji} خرید {plan.get('name')} ({price_str} تومان)"

        # اگر موجودی کافی بود، به صفحه تایید خرید می‌رود، در غیر این صورت به کاربر اطلاع می‌دهد
        callback_data = f"wallet:buy_confirm:{plan.get('name')}" if is_affordable else "wallet:insufficient"
        kb.add(types.InlineKeyboardButton(button_text, callback_data=callback_data))

    kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="view_plans"))

    _safe_edit(uid, msg_id, text, reply_markup=kb)


def show_payment_options_menu(call: types.CallbackQuery):
    """منوی انتخاب روش پرداخت را نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)

    text = f"*{escape_markdown(get_string('prompt_select_payment_method', lang_code))}*"
    _safe_edit(uid, msg_id, text, reply_markup=menu.payment_options_menu(lang_code=lang_code), parse_mode="MarkdownV2")


def handle_show_card_details(call: types.CallbackQuery):
    """اطلاعات پرداخت کارت به کارت را نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    lang_code = db.get_user_language(uid)

    if not (CARD_PAYMENT_INFO and CARD_PAYMENT_INFO.get("card_number")):
        return

    title = get_string("payment_card_details_title", lang_code)
    holder = escape_markdown(CARD_PAYMENT_INFO.get("card_holder", ""))
    card_number = escape_markdown(CARD_PAYMENT_INFO.get("card_number", ""))
    instructions = escape_markdown(get_string("payment_card_instructions", lang_code))

    text = (
        f"*{escape_markdown(title)}*\n\n"
        f"*{escape_markdown(get_string('payment_card_holder', lang_code))}* `{holder}`\n\n"
        f"*{escape_markdown(get_string('payment_card_number', lang_code))}*\n`{card_number}`\n\n"
        f"{instructions}"
    )

    kb = types.InlineKeyboardMarkup(row_width=1)
    support_url = f"https://t.me/{ADMIN_SUPPORT_CONTACT.replace('@', '')}"
    kb.add(types.InlineKeyboardButton(f"💬 {get_string('btn_contact_support', lang_code)}", url=support_url))
    kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="show_payment_options"))

    _safe_edit(uid, msg_id, text, reply_markup=kb, parse_mode="MarkdownV2")

# =============================================================================
# 5. Connection Doctor & Periodic Usage
# =============================================================================

def handle_periodic_usage_menu(call: types.CallbackQuery):
    """منوی انتخاب سرور برای مشاهده مصرف بازه‌ای را نمایش می‌دهد."""
    uid, msg_id, lang_code = call.from_user.id, call.message.message_id, db.get_user_language(call.from_user.id)
    uuid_id = int(call.data.split("_")[2])
    
    #  <--  استفاده از تابع جدید
    access_rights = db.get_user_access_rights(uid)

    text = get_string("prompt_select_server_stats", lang_code)
    reply_markup = menu.server_selection_menu(
        uuid_id,
        show_germany=access_rights['has_access_de'],
        show_france=access_rights['has_access_fr'],
        show_turkey=access_rights['has_access_tr'],
        lang_code=lang_code
    )
    _safe_edit(uid, msg_id, text, reply_markup=reply_markup, parse_mode=None)


def show_panel_periodic_usage(call: types.CallbackQuery):
    """آمار مصرف بازه‌ای برای یک پنل خاص را نمایش می‌دهد."""
    uid, msg_id, lang_code = call.from_user.id, call.message.message_id, db.get_user_language(call.from_user.id)
    parts = call.data.split("_")
    panel_code, uuid_id = parts[1], int(parts[2])
    if db.uuid_by_id(uid, uuid_id):
        panel_db_name = f"{panel_code}_usage_gb"
        panel_display_name = get_string('server_de' if panel_code == "hiddify" else 'server_fr', lang_code)
        stats = db.get_panel_usage_in_intervals(uuid_id, panel_db_name)
        text = fmt_panel_quick_stats(panel_display_name, stats, lang_code=lang_code)
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data=f"win_select_{uuid_id}"))
        _safe_edit(uid, msg_id, text, reply_markup=kb)


def handle_connection_doctor(call: types.CallbackQuery):
    """
    (نسخه نهایی و اصلاح شده)
    وضعیت سرویس کاربر و سرورها را به همراه آمار دقیق کاربران آنلاین نمایش می‌دهد.
    """
    uid, msg_id, lang_code = call.from_user.id, call.message.message_id, db.get_user_language(call.from_user.id)
    _safe_edit(uid, msg_id, escape_markdown(get_string("doctor_checking_status", lang_code)), reply_markup=None)

    report = [f"*{escape_markdown(get_string('doctor_report_title', lang_code))}*", "`──────────────────`"]

    user_uuids = db.uuids(uid)
    if not user_uuids:
        from ..user_router import go_back_to_main
        go_back_to_main(call=call)
        return

    user_info = combined_handler.get_combined_user_info(user_uuids[0]['uuid'])
    account_status_label = escape_markdown(get_string('doctor_account_status_label', lang_code))
    is_ok = user_info and user_info.get('is_active') and (user_info.get('expire') is None or user_info.get('expire') >= 0)
    status_text = f"*{escape_markdown(get_string('fmt_status_active' if is_ok else 'fmt_status_inactive', lang_code))}*"
    report.append(f"✅ {account_status_label} {status_text}")

    active_panels = db.get_active_panels()
    for panel in active_panels:
        panel_name_raw = panel.get('name', '...')
        server_status_label = escape_markdown(get_string('doctor_server_status_label', lang_code).format(panel_name=panel_name_raw))

        handler_class = HiddifyAPIHandler if panel['panel_type'] == 'hiddify' else MarzbanAPIHandler
        handler = handler_class(panel)
        is_online = handler.check_connection()
        status_text = f"*{escape_markdown(get_string('server_status_online' if is_online else 'server_status_offline', lang_code))}*"
        report.append(f"{'✅' if is_online else '🚨'} {server_status_label} {status_text}")

    try:
        from ..database import db as db_instance
        activity_stats = db_instance.count_recently_active_users(minutes=15)
        analysis_title = escape_markdown(get_string('doctor_analysis_title', lang_code))
        line_template = get_string('doctor_online_users_line', lang_code)

        report.extend([
            "`──────────────────`",
            f"📈 *{analysis_title}*",
            escape_markdown(line_template.format(count=activity_stats.get('hiddify', 0), server_name="آلمان 🇩🇪")),
            escape_markdown(line_template.format(count=activity_stats.get('marzban_fr', 0), server_name="فرانسه 🇫🇷")),
            escape_markdown(line_template.format(count=activity_stats.get('marzban_tr', 0), server_name="ترکیه 🇹🇷"))
        ])
    except Exception as e:
        logger.error(f"Error getting activity stats for doctor: {e}")

    report.extend([
        "`──────────────────`",
        f"💡 *{escape_markdown(get_string('doctor_suggestion_title', lang_code))}*\n{escape_markdown(get_string('doctor_suggestion_body', lang_code))}"
    ])

    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
    _safe_edit(uid, msg_id, "\n".join(report), reply_markup=kb)