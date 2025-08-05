import logging
from telebot import types, telebot
from .bot_instance import bot, admin_conversations # << تغییر اصلی
from .admin_handlers import user_management, reporting, broadcast, backup, group_actions 
from .admin_hiddify_handlers import _start_add_hiddify_user_convo, initialize_hiddify_handlers, handle_add_user_back_step
from .admin_marzban_handlers import _start_add_marzban_user_convo, initialize_marzban_handlers
from .marzban_api_handler import marzban_handler
from .menu import menu
from .utils import _safe_edit

logger = logging.getLogger(__name__)

def register_admin_handlers(bot):
    
    initialize_hiddify_handlers(bot, admin_conversations)
    initialize_marzban_handlers(bot, admin_conversations)
    group_actions.initialize_group_actions_handlers(bot, admin_conversations)
    user_management.initialize_user_management_handlers(bot, admin_conversations)
    reporting.initialize_reporting_handlers(bot)
    broadcast.initialize_broadcast_handlers(bot, admin_conversations)
    backup.initialize_backup_handlers(bot)

# ===================================================================
# Simple Menu Functions
# ===================================================================

def _handle_show_panel(call, params):
    """Shows the main admin panel menu."""
    _safe_edit(call.from_user.id, call.message.message_id, "👑 پنل مدیریت", reply_markup=menu.admin_panel())

def _handle_management_menu(call, params):
    """Shows the user management menu."""
    _safe_edit(call.from_user.id, call.message.message_id, "👥 مدیریت کاربران", reply_markup=menu.admin_management_menu())

def _handle_search_menu(call, params):
    """Shows the search sub-menu."""
    _safe_edit(call.from_user.id, call.message.message_id, "🔎 لطفاً نوع جستجو را انتخاب کنید:", reply_markup=menu.admin_search_menu())

def _handle_group_actions_menu(call, params):
    """Shows the group actions sub-menu."""
    _safe_edit(call.from_user.id, call.message.message_id, "⚙️ لطفاً نوع دستور گروهی را انتخاب کنید:", reply_markup=menu.admin_group_actions_menu())

def _handle_user_analysis_menu(call, params):
    """
    کاربر را به منوی انتخاب پلن برای گزارش‌گیری هدایت می‌کند.
    این تابع مانند یک پل عمل کرده و خطای قبلی را برطرف می‌کند.
    """
    # این تابع، شما را مستقیماً به همان منویی می‌برد که لیست پلن‌ها را برای
    # گزارش‌گیری نمایش می‌دهد و دقیقاً همان عملکردی را دارد که می‌خواهید.
    reporting.handle_report_by_plan_selection(call, params)

# تابع جدید: برای نمایش منوی وضعیت سیستم
def _handle_system_status_menu(call, params):
    _safe_edit(call.from_user.id, call.message.message_id, "📊 لطفاً پنل مورد نظر برای مشاهده وضعیت را انتخاب کنید:", reply_markup=menu.admin_system_status_menu())

def _handle_panel_management_menu(call, params):
    """Shows the management menu for a specific panel (Hiddify/Marzban)."""
    bot.clear_step_handler_by_chat_id(call.from_user.id)
    panel = params[0]
    panel_name = "آلمان 🇩🇪" if panel == "hiddify" else "فرانسه 🇫🇷"
    _safe_edit(call.from_user.id, call.message.message_id, f"مدیریت کاربران پنل *{panel_name}*", reply_markup=menu.admin_panel_management_menu(panel))

def _handle_server_selection(call, params):
    """Shows the server selection menu for reports or analytics."""
    base_callback = params[0]
    text_map = {"reports_menu": "لطفاً پنل را برای گزارش‌گیری انتخاب کنید:", "analytics_menu": "لطفاً پنل را برای تحلیل و آمار انتخاب کنید:"}
    _safe_edit(call.from_user.id, call.message.message_id, text_map.get(base_callback, "لطفا انتخاب کنید:"),
               reply_markup=menu.admin_server_selection_menu(f"admin:{base_callback}"))
    
def _handle_reload_maps(call, params):
    bot.answer_callback_query(call.id, "⏳ در حال رفرش کردن...")
    success = marzban_handler.reload_uuid_maps() #
    
    if success:
        response_text = "✅ *مپینگ با موفقیت به‌روز شد\\.*\n\nاطلاعات کاربران پنل مرزبان از فایل `uuid_to_marzban_user\\.json` مجدداً بارگذاری شد\\."
    else:
        response_text = "❌ *خطا در به‌روزرسانی مپینگ\\.*\n\nلطفاً از صحت فایل `uuid_to_marzban_user\\.json` مطمئن شوید و لاگ‌های ربات را بررسی کنید\\."
        
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به وضعیت سیستم", callback_data="admin:system_status_menu"))
    _safe_edit(call.from_user.id, call.message.message_id, response_text, reply_markup=kb)


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

    
    # User Actions
    "add_user": lambda c, p: (_start_add_hiddify_user_convo if p[0] == 'hiddify' else _start_add_marzban_user_convo)(c.from_user.id, c.message.message_id),
    # "add_user_plan": lambda c, p: _start_add_user_from_plan_convo(c, p),
    # "plan_select": lambda c, p: _handle_plan_selection(c, p),
    "sg": user_management.handle_global_search_convo,
    "us": user_management.handle_show_user_summary,
    "edt": user_management.handle_edit_user_menu,
    "log_payment": user_management.handle_log_payment,
    "phist": user_management.handle_payment_history,
    "ae": user_management.handle_ask_edit_value,
    "tgl": user_management.handle_toggle_status,
    "tglA": user_management.handle_toggle_status_action, # این تابع جدید، عمل را انجام می‌دهد
    "rb": user_management.handle_reset_birthday,
    "rusg_m": user_management.handle_reset_usage_menu,
    "rsa": user_management.handle_reset_usage_action,
    "del_cfm": user_management.handle_delete_user_confirm,
    "del_a": user_management.handle_delete_user_action,
    "note": user_management.handle_ask_for_note,
    "search_by_tid": user_management.handle_search_by_telegram_id_convo,
    "purge_user": user_management.handle_purge_user_convo,
    
    # Reporting & Analytics
    "health_check": reporting.handle_health_check,
    "marzban_stats": reporting.handle_marzban_system_stats,
    "list": reporting.handle_paginated_list,
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
    "reload_maps": _handle_reload_maps,
    "add_user_back": handle_add_user_back_step,
}


def handle_admin_callbacks(call: types.CallbackQuery):
    """The main callback router for all admin actions."""
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