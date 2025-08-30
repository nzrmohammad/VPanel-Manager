import logging
from telebot import types
from .config import ADMIN_IDS
from .bot_instance import bot, admin_conversations

from .admin_handlers import (
    user_management, 
    reporting, 
    broadcast, 
    backup, 
    group_actions, 
    plan_management, 
    panel_management
)

from .admin_hiddify_handlers import (_start_add_hiddify_user_convo, initialize_hiddify_handlers, handle_add_user_back_step)
from .admin_marzban_handlers import (_start_add_marzban_user_convo, initialize_marzban_handlers)
from .menu import menu
from .utils import _safe_edit, escape_markdown

logger = logging.getLogger(__name__)

def register_admin_handlers(bot, scheduler):
# -----------------------------------------------
    initialize_hiddify_handlers(bot, admin_conversations)
    initialize_marzban_handlers(bot, admin_conversations)
    group_actions.initialize_group_actions_handlers(bot, admin_conversations)
    user_management.initialize_user_management_handlers(bot, admin_conversations)
    reporting.initialize_reporting_handlers(bot)
    broadcast.initialize_broadcast_handlers(bot, admin_conversations)
    backup.initialize_backup_handlers(bot)
    plan_management.initialize_plan_management_handlers(bot, admin_conversations)
    panel_management.initialize_panel_management_handlers(bot, admin_conversations)

    @bot.message_handler(commands=['test_report'], func=lambda message: message.from_user.id in ADMIN_IDS)
    def test_report_command(message: types.Message):
        reporting.handle_test_report_command(message)

    @bot.message_handler(commands=['test_weekly_report'], func=lambda message: message.from_user.id in ADMIN_IDS)
    def test_weekly_report_command(message: types.Message):
        reporting.handle_test_weekly_report_command(message)

    @bot.message_handler(commands=['test_welcome'], func=lambda message: message.from_user.id in ADMIN_IDS)
    def test_welcome_message_command(message: types.Message):
        reporting.handle_test_welcome_message_command(message)
        
    # --- START: NEW TEST COMMANDS FOR SCHEDULER ---
    @bot.message_handler(commands=['test_nightly'], func=lambda message: message.from_user.id in ADMIN_IDS)
    def run_test_nightly_report(message: types.Message):
        admin_id = message.from_user.id
        bot.send_message(admin_id, "⏳ در حال اجرای تست گزارش شبانه (فقط برای شما)...")
        try:
            scheduler._nightly_report(target_user_id=admin_id)
            bot.send_message(admin_id, "✅ تست گزارش شبانه با موفقیت انجام شد.")
        except Exception as e:
            bot.send_message(admin_id, f"❌ خطا در اجرای تست گزارش شبانه: {escape_markdown(str(e))}", parse_mode="MarkdownV2")
            logger.error(f"Error in test_nightly command: {e}", exc_info=True)

    @bot.message_handler(commands=['test_weekly'], func=lambda message: message.from_user.id in ADMIN_IDS)
    def run_test_weekly_report(message: types.Message):
        admin_id = message.from_user.id
        bot.send_message(admin_id, "⏳ در حال اجرای تست گزارش هفتگی (فقط برای شما)...")
        try:
            scheduler._weekly_report(target_user_id=admin_id)
            bot.send_message(admin_id, "✅ تست گزارش هفتگی با موفقیت انجام شد.")
        except Exception as e:
            bot.send_message(admin_id, f"❌ خطا در اجرای تست گزارش هفتگی: {escape_markdown(str(e))}", parse_mode="MarkdownV2")
            logger.error(f"Error in test_weekly command: {e}", exc_info=True)

    @bot.message_handler(commands=['test_warnings'], func=lambda message: message.from_user.id in ADMIN_IDS)
    def run_test_warnings_check(message: types.Message):
        admin_id = message.from_user.id
        bot.send_message(admin_id, "⏳ در حال اجرای تست بررسی هشدارها (فقط برای شما)...")
        try:
            scheduler._check_for_warnings(target_user_id=admin_id)
            bot.send_message(admin_id, "✅ تست بررسی هشدارها با موفقیت انجام شد. اگر شرایط لازم را داشته باشید، پیام هشدار دریافت خواهید کرد.")
        except Exception as e:
            bot.send_message(admin_id, f"❌ خطا در اجرای تست بررسی هشدارها: {escape_markdown(str(e))}", parse_mode="MarkdownV2")
            logger.error(f"Error in test_warnings command: {e}", exc_info=True)
    # --- END: NEW TEST COMMANDS FOR SCHEDULER ---

# ===================================================================
# Simple Menu Functions
# ===================================================================

def _handle_show_panel(call, params):
    _safe_edit(call.from_user.id, call.message.message_id, "👑 پنل مدیریت", reply_markup=menu.admin_panel())

def _handle_management_menu(call, params):
    _safe_edit(call.from_user.id, call.message.message_id, "👥 مدیریت کاربران", reply_markup=menu.admin_management_menu())

def _handle_search_menu(call, params):
    _safe_edit(call.from_user.id, call.message.message_id, "🔎 لطفاً نوع جستجو را انتخاب کنید:", reply_markup=menu.admin_search_menu())

def _handle_group_actions_menu(call, params):
    _safe_edit(call.from_user.id, call.message.message_id, "⚙️ لطفاً نوع دستور گروهی را انتخاب کنید:", reply_markup=menu.admin_group_actions_menu())

def _handle_user_analysis_menu(call, params):
    reporting.handle_report_by_plan_selection(call, params)

def _handle_system_status_menu(call, params):
    _safe_edit(call.from_user.id, call.message.message_id, "📊 لطفاً پنل مورد نظر برای مشاهده وضعیت را انتخاب کنید:", reply_markup=menu.admin_system_status_menu())

def _handle_panel_management_menu(call, params):
    bot.clear_step_handler_by_chat_id(call.from_user.id)
    panel_type = params[0]
    panel_name = "Hiddify" if panel_type == "hiddify" else "Marzban"
    _safe_edit(call.from_user.id, call.message.message_id, f"مدیریت کاربران پنل‌های نوع *{panel_name}*", reply_markup=menu.admin_panel_management_menu(panel_type))

def _handle_server_selection(call, params):
    base_callback = params[0]
    text_map = {"reports_menu": "لطفاً نوع پنل را برای گزارش‌گیری انتخاب کنید:", "analytics_menu": "لطفاً نوع پنل را برای تحلیل و آمار انتخاب کنید:"}
    _safe_edit(call.from_user.id, call.message.message_id, text_map.get(base_callback, "لطفا انتخاب کنید:"),
               reply_markup=menu.admin_server_selection_menu(f"admin:{base_callback}"))

# ===================================================================
# Final Dispatcher Dictionary
# ===================================================================
ADMIN_CALLBACK_HANDLERS = {
    # Menus
    "panel": _handle_show_panel,
    "quick_dashboard": reporting.handle_quick_dashboard,
    "management_menu": _handle_management_menu,
    "manage_panel": _handle_panel_management_menu,
    "select_server": _handle_server_selection,
    "search_menu": _handle_search_menu,
    "group_actions_menu": _handle_group_actions_menu,
    "reports_menu": reporting.handle_reports_menu,
    "panel_reports": reporting.handle_panel_specific_reports_menu,
    "user_analysis_menu": _handle_user_analysis_menu,
    "system_status_menu": _handle_system_status_menu,
    "ep": user_management.handle_select_panel_for_edit,
    "plan_manage": plan_management.handle_plan_management_menu,
    "plan_details": plan_management.handle_plan_details_menu,
    "plan_delete_confirm": plan_management.handle_delete_plan_confirm,
    "plan_delete_execute": plan_management.handle_delete_plan_execute,
    "plan_edit_start": plan_management.handle_plan_edit_start,
    "plan_add_start": plan_management.handle_plan_add_start,
    "plan_add_type": plan_management.get_plan_add_type,
    
    # Panel Management
    "panel_manage": panel_management.handle_panel_management_menu,
    "panel_details": panel_management.handle_panel_details,
    "panel_add_start": panel_management.handle_start_add_panel,
    "panel_set_type": panel_management.handle_set_panel_type,
    "panel_toggle": panel_management.handle_panel_toggle_status,
    "panel_edit_start": panel_management.handle_panel_edit_start,
    "panel_delete_confirm": panel_management.handle_panel_delete_confirm,
    "panel_delete_execute": panel_management.handle_panel_delete_execute,
    
    # User Actions
    "add_user": lambda c, p: (_start_add_hiddify_user_convo if p[0] == 'hiddify' else _start_add_marzban_user_convo)(c.from_user.id, c.message.message_id),
    "sg": user_management.handle_global_search_convo,
    "us": user_management.handle_show_user_summary,
    "edt": user_management.handle_edit_user_menu,
    "log_payment": user_management.handle_log_payment,
    "phist": user_management.handle_payment_history,
    "ae": user_management.handle_ask_edit_value,
    "tgl": user_management.handle_toggle_status,
    "tglA": user_management.handle_toggle_status_action,
    "rb": user_management.handle_reset_birthday,
    "rusg_m": user_management.handle_reset_usage_menu,
    "rsa": user_management.handle_reset_usage_action,
    "del_cfm": user_management.handle_delete_user_confirm,
    "del_a": user_management.handle_delete_user_action,
    "note": user_management.handle_ask_for_note,
    "search_by_tid": user_management.handle_search_by_telegram_id_convo,
    "purge_user": user_management.handle_purge_user_convo,
    "del_devs": user_management.handle_delete_devices_action,
    
    # Reporting & Analytics
    "health_check": reporting.handle_health_check,
    "marzban_stats": reporting.handle_marzban_system_stats,
    "list": reporting.handle_paginated_list,
    "list_devices": reporting.handle_connected_devices_list,
    "report_by_plan_select": reporting.handle_report_by_plan_selection,
    "list_by_plan": reporting.handle_list_users_by_plan,
    "list_no_plan": reporting.handle_list_users_no_plan,
    
    # Group Actions
    "group_action_select_plan": group_actions.handle_select_plan_for_action,
    "ga_select_type": group_actions.handle_select_action_type,
    "ga_ask_value": group_actions.handle_ask_action_value,
    "adv_ga_select_filter": group_actions.handle_select_advanced_filter,
    "adv_ga_select_action": group_actions.handle_select_action_for_filter,
    
    # Other Admin Tools
    "broadcast": broadcast.start_broadcast_flow,
    "broadcast_target": broadcast.ask_for_broadcast_message,
    "backup_menu": backup.handle_backup_menu,
    "backup": backup.handle_backup_action,
    "add_user_back": handle_add_user_back_step,
}

def handle_admin_callbacks(call: types.CallbackQuery):
    if not call.data.startswith("admin:"):
        return

    parts = call.data.split(':')
    action = parts[1]
    params = parts[2:]
    
    handler = ADMIN_CALLBACK_HANDLERS.get(action)
    if handler:
        try:
            handler(call, params)
        except Exception as e:
            logger.error(f"Error handling admin callback '{call.data}': {e}", exc_info=True)
            bot.answer_callback_query(call.id, "❌ خطایی در پردازش درخواست رخ داد.", show_alert=True)
    else:
        logger.warning(f"No handler found for admin action: '{action}' in callback: {call.data}")