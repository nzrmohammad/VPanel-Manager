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
    panel_management,
    wallet as wallet_admin_handler
)

from .admin_hiddify_handlers import (_start_add_hiddify_user_convo, initialize_hiddify_handlers, handle_add_user_back_step)
from .admin_marzban_handlers import (_start_add_marzban_user_convo, initialize_marzban_handlers)
from .menu import menu
from .utils import _safe_edit, escape_markdown
from .database import db
scheduler = None


logger = logging.getLogger(__name__)

def register_admin_handlers(bot, scheduler_instance):
    global scheduler
    scheduler = scheduler_instance
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
    wallet_admin_handler.initialize_wallet_handlers(bot, admin_conversations)

    # ===================================================================
    # Test Commands (Corrected and Completed)
    # ===================================================================

    @bot.message_handler(commands=['test_nightly'], func=lambda message: message.from_user.id in ADMIN_IDS)
    def run_test_nightly_report(message: types.Message):
        admin_id = message.from_user.id
        try:
            parts = message.text.split()
            target_user_id = int(parts[1]) if len(parts) > 1 else admin_id
            bot.send_message(admin_id, f"⏳ در حال اجرای تست گزارش شبانه برای کاربر `{target_user_id}`...", parse_mode="Markdown")
            scheduler._nightly_report(target_user_id=target_user_id)
            bot.send_message(admin_id, f"✅ تست گزارش شبانه برای کاربر `{target_user_id}` با موفقیت انجام و ارسال شد.")
        except Exception as e:
            bot.send_message(admin_id, f"❌ خطا در اجرای تست: {escape_markdown(str(e))}", parse_mode="MarkdownV2")

    @bot.message_handler(commands=['test_weekly'], func=lambda message: message.from_user.id in ADMIN_IDS)
    def run_test_weekly_report(message: types.Message):
        """
        (نسخه نهایی و اصلاح شده)
        این تابع هم گزارش هفتگی کاربر و هم گزارش هفتگی ادمین را برای تست اجرا می‌کند.
        """
        admin_id = message.from_user.id
        try:
            parts = message.text.split()
            target_user_id = int(parts[1]) if len(parts) > 1 else admin_id
            
            # بخش اول: تست گزارش هفتگی کاربر
            bot.send_message(admin_id, f"⏳ در حال اجرای تست گزارش هفتگی برای کاربر `{target_user_id}`...", parse_mode="Markdown")
            scheduler._weekly_report(target_user_id=target_user_id)
            bot.send_message(admin_id, f"✅ تست گزارش هفتگی برای کاربر `{target_user_id}` با موفقیت انجام و ارسال شد.")
            
            # بخش دوم: تست گزارش هفتگی ادمین
            bot.send_message(admin_id, "⏳ در حال اجرای تست گزارش هفتگی ادمین (پرمصرف‌ترین‌ها)...", parse_mode="Markdown")
            scheduler._send_weekly_admin_summary()
            bot.send_message(admin_id, "✅ تست گزارش هفتگی ادمین با موفقیت انجام و ارسال شد.")

        except Exception as e:
            bot.send_message(admin_id, f"❌ خطا در اجرای تست: {escape_markdown(str(e))}", parse_mode="MarkdownV2")


    @bot.message_handler(commands=['test_warnings'], func=lambda message: message.from_user.id in ADMIN_IDS)
    def run_test_warnings_check(message: types.Message):
        admin_id = message.from_user.id
        try:
            parts = message.text.split()
            target_user_id = int(parts[1]) if len(parts) > 1 else admin_id
            bot.send_message(admin_id, f"⏳ در حال اجرای تست بررسی هشدارها برای کاربر `{target_user_id}`...", parse_mode="Markdown")
            scheduler._check_for_warnings(target_user_id=target_user_id)
            bot.send_message(admin_id, "✅ تست بررسی هشدارها با موفقیت انجام شد. اگر کاربر شرایط لازم را داشته باشد، پیام دریافت خواهد کرد.")
        except Exception as e:
            bot.send_message(admin_id, f"❌ خطا در اجرای تست: {escape_markdown(str(e))}", parse_mode="MarkdownV2")

    @bot.message_handler(commands=['test'], func=lambda message: message.from_user.id in ADMIN_IDS)
    def run_all_scheduler_tests(message: types.Message):
        admin_id = message.from_user.id
        test_report = ["*⚙️ تست کامل سیستم زمان‌بندی ربات*"]
        msg = bot.send_message(admin_id, "⏳ لطفاً صبر کنید، در حال اجرای تمام تست‌ها...", parse_mode="Markdown")

        def run_single_test(title, function, *args, **kwargs):
            try:
                # اطمینان از اینکه scheduler مقداردهی شده است
                if not scheduler:
                    raise Exception("Scheduler has not been initialized.")
                function(*args, **kwargs)
                test_report.append(f"✅ {title}: موفق")
            except Exception as e:
                test_report.append(f"❌ {title}: ناموفق\n   `خطا: {str(e)}`")
                logger.error(f"Error during '/test' for '{title}': {e}", exc_info=True)

        run_single_test("گزارش شبانه", scheduler._nightly_report, target_user_id=admin_id)
        run_single_test("گزارش هفتگی", scheduler._weekly_report, target_user_id=admin_id)
        run_single_test("بررسی هشدارها", scheduler._check_for_warnings, target_user_id=admin_id)
        run_single_test("بررسی دستاوردها و سالگرد", scheduler._check_achievements_and_anniversary)
        run_single_test("بررسی هدیه تولد", scheduler._birthday_gifts_job)
        
        bot.edit_message_text("\n".join(test_report), chat_id=admin_id, message_id=msg.message_id, parse_mode="Markdown")

    @bot.message_handler(commands=['test_event'], func=lambda message: message.from_user.id in ADMIN_IDS)
    def run_test_event_notification(message: types.Message):
        admin_id = message.from_user.id
        try:
            bot.send_message(admin_id, "⏳ در حال اجرای تست اطلاع‌رسانی رویداد فردا...")
            scheduler._test_upcoming_event_notification()
            bot.send_message(admin_id, "✅ تست با موفقیت انجام شد. اگر رویدادی برای فردا ثبت شده باشد، پیام آن ارسال شد.")
        except Exception as e:
            bot.send_message(admin_id, f"❌ خطا در اجرای تست: {escape_markdown(str(e))}", parse_mode="MarkdownV2")

    @bot.message_handler(commands=['test_digest'], func=lambda message: message.from_user.id in ADMIN_IDS)
    def run_test_weekly_digest(message: types.Message):
        admin_id = message.from_user.id
        try:
            bot.send_message(admin_id, "⏳ در حال اجرای تست گزارش مدیریتی هفتگی...")
            scheduler._test_weekly_digest()
            bot.send_message(admin_id, "✅ تست با موفقیت انجام و گزارش هفتگی برای شما ارسال شد.")
        except Exception as e:
            bot.send_message(admin_id, f"❌ خطا در اجرای تست: {escape_markdown(str(e))}", parse_mode="MarkdownV2")

    @bot.message_handler(commands=['addpoints'], func=lambda message: message.from_user.id in ADMIN_IDS)
    def add_points_command(message: types.Message):
        """
        امتیاز دستاورد را به یک کاربر اضافه می‌کند.
        نحوه استفاده: /addpoints [USER_ID] [AMOUNT]
        اگر USER_ID وارد نشود، به خود ادمین امتیاز اضافه می‌شود.
        """
        admin_id = message.from_user.id
        try:
            parts = message.text.split()
            if len(parts) < 2:
                bot.reply_to(message, "فرمت دستور اشتباه است. لطفاً به این شکل استفاده کنید:\n`/addpoints AMOUNT`\nیا\n`/addpoints USER_ID AMOUNT`", parse_mode="MarkdownV2")
                return

            if len(parts) == 2:
                # حالت افزودن امتیاز به خود ادمین
                target_user_id = admin_id
                amount = int(parts[1])
            else: # len(parts) == 3
                # حالت افزودن امتیاز به کاربر دیگر
                target_user_id = int(parts[1])
                amount = int(parts[2])

            # فراخوانی تابع دیتابیس برای افزودن امتیاز
            db.add_achievement_points(target_user_id, amount)
            
            # --- START OF FIX: Escape the period for MarkdownV2 ---
            success_message = f"✅ *{amount}* امتیاز با موفقیت به کاربر `{target_user_id}` اضافه شد\\."
            bot.send_message(admin_id, success_message, parse_mode="MarkdownV2")
            # --- END OF FIX ---

        except (ValueError, IndexError):
            bot.reply_to(message, "❌ مقادیر وارد شده نامعتبر هستند. لطفاً از اعداد صحیح استفاده کنید.", parse_mode="MarkdownV2")
        except Exception as e:
            bot.send_message(admin_id, f"❌ خطایی در هنگام افزودن امتیاز رخ داد: `{escape_markdown(str(e))}`", parse_mode="MarkdownV2")
            logger.error(f"Error in addpoints command: {e}", exc_info=True)


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
    "scheduled_tasks": reporting.handle_show_scheduled_tasks,
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
    "plan_show_category": plan_management.handle_show_plans_by_category,
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
    "us_edt": user_management.handle_edit_user_menu,
    "us_lpay": user_management.handle_log_payment,
    "us_phist": user_management.handle_payment_history,
    "ae": user_management.handle_ask_edit_value,
    "us_tgl": user_management.handle_toggle_status,
    "tglA": user_management.handle_toggle_status_action,
    "us_rb": user_management.handle_reset_birthday,
    "us_rusg": user_management.handle_reset_usage_menu,
    "rsa": user_management.handle_reset_usage_action,
    "us_delc": user_management.handle_delete_user_confirm,
    "del_a": user_management.handle_delete_user_action,
    "us_note": user_management.handle_ask_for_note,
    "search_by_tid": user_management.handle_search_by_telegram_id_convo,
    "purge_user": user_management.handle_purge_user_convo,
    "us_ddev": user_management.handle_delete_devices_confirm,
    "del_devs_exec": user_management.handle_delete_devices_action,
    "us_rtr": user_management.handle_reset_transfer_cooldown,
    "us_mchg": wallet_admin_handler.handle_manual_charge_request,
    "awd_b_menu": user_management.handle_award_badge_menu,
    "awd_b": user_management.handle_award_badge,
    "ach_req_approve": user_management.handle_achievement_request_callback,
    "ach_req_reject": user_management.handle_achievement_request_callback,
    "reset_phist": user_management.handle_reset_payment_history_confirm,
    "do_reset_phist": user_management.handle_reset_payment_history_action,
    
    # Reporting & Analytics
    "health_check": reporting.handle_health_check,
    "marzban_stats": reporting.handle_marzban_system_stats,
    "list": reporting.handle_paginated_list,
    "financial_report": reporting.handle_financial_report,
    "financial_details": reporting.handle_financial_details,
    "confirm_delete_trans": reporting.handle_confirm_delete_transaction,
    "do_delete_trans": reporting.handle_do_delete_transaction,  
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
    "system_tools_menu": user_management.handle_system_tools_menu,
    "reset_all_daily_usage_confirm": user_management.handle_reset_all_daily_usage_confirm,
    "reset_all_daily_usage_exec": user_management.handle_reset_all_daily_usage_action,
    "force_snapshot": user_management.handle_force_snapshot,
    "reset_all_points_confirm": user_management.handle_reset_all_points_confirm,
    "reset_all_points_exec": user_management.handle_reset_all_points_execute,
    "delete_all_devices_confirm": user_management.handle_delete_all_devices_confirm,
    "delete_all_devices_exec": user_management.handle_delete_all_devices_execute,
    "charge_confirm": wallet_admin_handler.handle_charge_request_callback,
    "charge_reject": wallet_admin_handler.handle_charge_request_callback,
    "manual_charge": wallet_admin_handler.handle_manual_charge_request,
    "manual_charge_exec": wallet_admin_handler.handle_manual_charge_execution,
    "manual_charge_cancel": wallet_admin_handler.handle_manual_charge_cancel,
    "us_wdrw": wallet_admin_handler.handle_manual_withdraw_request,
    "manual_withdraw_exec": wallet_admin_handler.handle_manual_withdraw_execution,
    "manual_withdraw_cancel": wallet_admin_handler.handle_manual_withdraw_cancel,
    "reset_all_balances_confirm": user_management.handle_reset_all_balances_confirm,
    "reset_all_balances_exec": user_management.handle_reset_all_balances_execute,

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