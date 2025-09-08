import logging
from telebot import types, telebot

# --- Local Imports ---
from .database import db
from .config import ADMIN_IDS
from .menu import menu
from .language import get_string
from .utils import get_loyalty_progress_message, escape_markdown, _safe_edit
from .user_handlers import account, info, settings, various

logger = logging.getLogger(__name__)
bot = None
admin_conversations = {}


def initialize_user_handlers(b_instance, conversations_dict):
    """تمام ماژول‌های فرزند را با نمونه bot و دیکشنری مکالمات مقداردهی اولیه می‌کند."""
    global bot, admin_conversations
    bot = b_instance
    admin_conversations = conversations_dict

    # مقداردهی اولیه تمام ماژول‌های فرزند
    account.initialize_handlers(b_instance, conversations_dict)
    info.initialize_handlers(b_instance)
    settings.initialize_handlers(b_instance)
    various.initialize_handlers(b_instance, conversations_dict)


def go_back_to_main(call: types.CallbackQuery = None, message: types.Message = None, original_msg_id: int = None):
    """منوی اصلی و شخصی‌سازی شده کاربر را نمایش می‌دهد."""
    # (کد این تابع صحیح است و بدون تغییر باقی می‌ماند)
    uid = call.from_user.id if call else message.from_user.id
    msg_id = original_msg_id or (call.message.message_id if call else None)
    lang_code = db.get_user_language(uid)
    user_db_info = db.user(uid)
    user_points = user_db_info.get('achievement_points', 0) if user_db_info else 0
    text_lines = [
        f"*{escape_markdown(get_string('main_menu_title', lang_code))}*",
        "`-----------------`",
        f"💰 {escape_markdown(get_string('fmt_your_points', lang_code))} *{user_points}*"
    ]
    loyalty_data = get_loyalty_progress_message(uid)
    if loyalty_data:
        line1 = get_string('loyalty_message_line1', lang_code).format(payment_count=loyalty_data['payment_count'])
        line2_template = get_string('loyalty_message_line2', lang_code)
        renewals_left = str(loyalty_data['renewals_left'])
        line2_formatted = line2_template.format(renewals_left=renewals_left, gb_reward=loyalty_data['gb_reward'], days_reward=loyalty_data['days_reward'])
        loyalty_message = escape_markdown(line2_formatted).replace(escape_markdown(renewals_left), f"*{escape_markdown(renewals_left)}*")
        text_lines.append(f"{escape_markdown(line1)}\n{loyalty_message}")
    text_lines.append("`──────────────────`")
    text_lines.append(f"💡 {escape_markdown(get_string('main_menu_tip', lang_code))}")
    text = "\n".join(text_lines)
    reply_markup = menu.main(uid in ADMIN_IDS, lang_code=lang_code)
    if msg_id:
        _safe_edit(uid, msg_id, text, reply_markup=reply_markup)
    else:
        bot.send_message(uid, text, reply_markup=reply_markup, parse_mode="MarkdownV2")


def handle_user_callbacks(call: types.CallbackQuery):
    """
    مسیریاب اصلی برای تمام callback های کاربران.
    این نسخه اصلاح شده و تمام توابع را از ماژول‌های صحیح فراخوانی می‌کند.
    """
    bot.clear_step_handler_by_chat_id(call.from_user.id)
    data = call.data

    # --- Account Management Callbacks ---
    if any(data.startswith(prefix) for prefix in ["add", "changename_", "del_", "share_confirm:", "cancel_share_req:", "transfer_"]):
        if data == "add": account.handle_add_uuid_request(call)
        elif data.startswith("changename_"): account.handle_change_name_request(call)
        elif data.startswith("del_"): account.handle_delete_account(call)
        elif data.startswith("share_confirm:"): account.handle_share_confirmation(call)
        elif data.startswith("cancel_share_req:"): account.handle_cancel_share_request(call)
        elif data.startswith("transfer_start_"): account.start_traffic_transfer(call)
        elif data.startswith("transfer_panel_"): account.ask_for_transfer_amount(call)
        elif data.startswith("transfer_confirm_"): account.confirm_and_execute_transfer(call)
        return

    # --- Information Display Callbacks ---
    if any(data.startswith(prefix) for prefix in ["manage", "acc_", "quick_stats", "qstats_acc_page_", "getlinks_", "getlink_", "payment_history_", "usage_history_", "view_plans", "show_plans:", "show_payment_options", "show_card_details", "web_login", "user_account", "win_select_", "win_hiddify_", "win_marzban_"]):
        if data == "manage": info.show_manage_menu(call)
        elif data.startswith("acc_"): info.show_account_details(call)
        elif data == "quick_stats": info.show_quick_stats(call)
        elif data.startswith("qstats_acc_page_"): info.show_quick_stats_page(call)
        elif data.startswith("getlinks_"): info.handle_get_links_request(call)
        elif data.startswith("getlink_"): info.send_subscription_link(call)
        elif data.startswith("payment_history_"): info.handle_payment_history(call)
        elif data.startswith("usage_history_"): info.handle_usage_history(call)
        elif data == "view_plans": info.show_plan_categories(call)
        elif data.startswith("show_plans:"): info.show_filtered_plans(call)
        elif data == "show_payment_options": info.show_payment_options_menu(call)
        elif data == "show_card_details": info.handle_show_card_details(call)
        elif data == "web_login": info.handle_web_login_request(call)
        elif data == "user_account": info.show_user_account_page(call)
        elif data.startswith("win_select_"): info.handle_periodic_usage_menu(call)
        elif data.startswith(("win_hiddify_", "win_marzban_")): info.show_panel_periodic_usage(call)
        return

    # --- Settings Callbacks ---
    if any(data.startswith(prefix) for prefix in ["settings", "toggle_", "change_language"]):
        if data == "settings": settings.show_settings(call)
        elif data.startswith("toggle_"): settings.handle_toggle_setting(call)
        elif data == "change_language": settings.handle_change_language_request(call)
        return
        
    # --- Various/Other Callbacks ---
    if any(data.startswith(prefix) for prefix in ["support", "tutorial", "birthday_gift", "coming_soon", "request_service", "connection_doctor", "achievements", "shop:", "referral:", "show_features_guide", "back_to_start_menu"]):
        if data == "support": various.handle_support_request(call)
        elif data.startswith("tutorial_os:"): various.show_tutorial_os_menu(call)
        elif data.startswith("tutorial_app:"): various.send_tutorial_link(call)
        elif data == "tutorials": various.show_tutorial_main_menu(call)
        elif data == "birthday_gift": various.handle_birthday_gift_request(call)
        elif data == "coming_soon": various.handle_coming_soon(call)
        elif data == "request_service": various.handle_request_service(call)
        elif data == "connection_doctor": various.handle_connection_doctor(call) # <-- اصلاح شد
        elif data == "achievements": various.show_achievements_page(call)
        elif data.startswith("shop:"): various.handle_shop_callbacks(call) # <-- اصلاح شد
        elif data.startswith("referral:"): various.handle_referral_callbacks(call)
        elif data == "show_features_guide": various.show_features_guide(call)
        elif data == "back_to_start_menu": various.show_initial_menu(call.from_user.id, call.message.message_id)
        return
    
    # --- Fallback to Main Menu ---
    if data == "back":
        go_back_to_main(call)


def register_user_handlers(b: telebot.TeleBot):
    """
    هندلرهای اصلی پیام‌ها (مانند /start) و callback انتخاب زبان را ثبت می‌کند.
    """
    global bot
    bot = b

    @bot.message_handler(commands=['start'])
    def cmd_start(message: types.Message):
        uid = message.from_user.id
        is_new_user = db.add_or_update_user(uid, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
        user_data = db.user(uid)
        if is_new_user or not user_data.get('lang_code'):
            bot.send_message(uid, "Welcome! / خوش آمدید!\nPlease select your language: / لطفاً زبان خود را انتخاب کنید:", 
                             reply_markup=settings.language_selection_menu())
            return
        parts = message.text.split()
        if len(parts) > 1 and not user_data.get('referred_by_user_id'):
            db.set_referrer(uid, parts[1])
        if db.uuids(uid):
            go_back_to_main(message=message)
        else:
            various.show_initial_menu(uid=uid)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('set_lang:'))
    def language_callback(call: types.CallbackQuery):
        """Callback مربوط به انتخاب زبان را به ماژول تنظیمات ارسال می‌کند."""
        settings.handle_language_selection(call)