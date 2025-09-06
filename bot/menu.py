from telebot import types
from .config import EMOJIS, PAGE_SIZE, CARD_PAYMENT_INFO, ONLINE_PAYMENT_LINK
from .language import get_string
from typing import Optional

class Menu:
    # =============================================================================
    # User Panel Menus
    # =============================================================================
    def main(self, is_admin: bool, lang_code: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        
        btn_manage_account = types.InlineKeyboardButton(f"{EMOJIS['key']} {get_string('manage_account', lang_code)}", callback_data="manage")
        btn_quick_stats = types.InlineKeyboardButton(f"{EMOJIS['lightning']} {get_string('quick_stats', lang_code)}", callback_data="quick_stats")
        btn_services = types.InlineKeyboardButton(f"🛒 {get_string('view_plans', lang_code)}", callback_data="view_plans")
        btn_support = types.InlineKeyboardButton(f"💬 {get_string('support', lang_code)}", callback_data="support")
        btn_doctor = types.InlineKeyboardButton(f"🩺 پزشک اتصال", callback_data="connection_doctor")
        btn_tutorials = types.InlineKeyboardButton(f"📚 {get_string('btn_tutorials', lang_code)}", callback_data="tutorials")
        btn_user_account = types.InlineKeyboardButton(f"👤 {get_string('user_account_page_title', lang_code)}", callback_data="user_account")
        btn_referral = types.InlineKeyboardButton("👥 دعوت از دوستان", callback_data="referral:info")
        btn_achievements = types.InlineKeyboardButton(f"🏆 دستاوردها", callback_data="achievements")
        btn_settings = types.InlineKeyboardButton(f"⚙️ {get_string('settings', lang_code)}", callback_data="settings")
        btn_birthday = types.InlineKeyboardButton(f"🎁 {get_string('birthday_gift', lang_code)}", callback_data="birthday_gift")
        btn_web_login = types.InlineKeyboardButton(f"🌐 {get_string('btn_web_login', lang_code)}", callback_data="web_login")

        kb.add(btn_manage_account, btn_quick_stats) # ردیف ۱: اصلی‌ترین‌ها
        kb.add(btn_services, btn_support)           # ردیف ۲: خرید و پشتیبانی
        kb.add(btn_doctor, btn_tutorials)           # ردیف ۳: ابزارها
        kb.add(btn_user_account, btn_referral)      # ردیف ۴: پروفایل و دعوت
        kb.add(btn_achievements, btn_settings)      # ردیف ۵: جوایز و تنظیمات
        kb.add(btn_birthday, btn_web_login)         # ردیف ۶: سایر

        if is_admin:
            kb.add(types.InlineKeyboardButton(f"{EMOJIS['crown']} پنل مدیریت", callback_data="admin:panel"))
        return kb

    def accounts(self, rows, lang_code: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        for r in rows:
            name = r.get('name', get_string('unknown_user', lang_code))
            usage_percentage = r.get('usage_percentage', 0)
            expire_days = r.get('expire')

            usage_str = f"{usage_percentage:.0f}%"
            
            summary = usage_str
            if expire_days is not None:
                expire_str = f"{expire_days} days"
                summary += f" - {expire_str}"

            button_text = f"📊 {name} ({summary})"
            kb.add(types.InlineKeyboardButton(button_text, callback_data=f"acc_{r['id']}"))

        kb.add(types.InlineKeyboardButton(f"➕ {get_string('btn_add_account', lang_code)}", callback_data="add"))
        kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
        return kb
    
    def account_menu(self, uuid_id: int, lang_code: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton(f"⏱ {get_string('btn_periodic_usage', lang_code)}", callback_data=f"win_select_{uuid_id}"),
            types.InlineKeyboardButton(f"{EMOJIS['globe']} {get_string('btn_get_links', lang_code)}", callback_data=f"getlinks_{uuid_id}")
        )
        kb.add(
            types.InlineKeyboardButton(f"✏️ {get_string('btn_change_name', lang_code)}", callback_data=f"changename_{uuid_id}"),
            types.InlineKeyboardButton(f"💳 {get_string('btn_payment_history', lang_code)}", callback_data=f"payment_history_{uuid_id}_0")
        )
        kb.add(
            types.InlineKeyboardButton(f"🗑 {get_string('btn_delete', lang_code)}", callback_data=f"del_{uuid_id}"),
            types.InlineKeyboardButton(f"📈 {get_string('btn_usage_history', lang_code)}", callback_data=f"usage_history_{uuid_id}")
        )
        from .config import ENABLE_TRAFFIC_TRANSFER
        if ENABLE_TRAFFIC_TRANSFER:
            kb.add(types.InlineKeyboardButton(f"💸 انتقال ترافیک", callback_data=f"transfer_start_{uuid_id}"))
        kb.add(types.InlineKeyboardButton(f"🔙 {get_string('btn_back_to_list', lang_code)}", callback_data="manage"))
        return kb

    def quick_stats_menu(self, num_accounts: int, current_page: int, lang_code: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        nav_buttons = []
        if num_accounts > 1:
            if current_page > 0:
                nav_buttons.append(types.InlineKeyboardButton(f"⬅️ {get_string('btn_prev_account', lang_code)}", callback_data=f"qstats_acc_page_{current_page - 1}"))
            if current_page < num_accounts - 1:
                nav_buttons.append(types.InlineKeyboardButton(f"{get_string('btn_next_account', lang_code)} ➡️", callback_data=f"qstats_acc_page_{current_page + 1}"))

        if nav_buttons:
            kb.row(*nav_buttons)

        kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back_to_main_menu', lang_code)}", callback_data="back"))
        return kb

    def server_selection_menu(self, uuid_id: int, show_germany: bool, show_france: bool, show_turkey: bool, lang_code: str) -> types.InlineKeyboardMarkup:
        """
        منوی انتخاب سرور را با دکمه ترکیبی برای فرانسه و ترکیه ایجاد می‌کند.
        """
        kb = types.InlineKeyboardMarkup(row_width=2)
        buttons = []
        
        if show_germany:
            buttons.append(types.InlineKeyboardButton(f"{get_string('server_de', lang_code)} 🇩🇪", callback_data=f"win_hiddify_{uuid_id}"))
        
        # منطق دکمه ترکیبی
        if show_france or show_turkey:
            flags = ""
            if show_france: flags += "🇫🇷"
            if show_turkey: flags += "🇹🇷"
            # چون هر دو از یک پنل (Marzban) هستند، callback یکی است
            buttons.append(types.InlineKeyboardButton(f"فرانسه/ترکیه {flags}", callback_data=f"win_marzban_{uuid_id}"))
        
        if buttons:
            kb.add(*buttons)

        btn_back = types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data=f"acc_{uuid_id}")
        kb.add(btn_back)
        return kb


    def plan_category_menu(self, lang_code: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        btn_germany = types.InlineKeyboardButton(f"🇩🇪 {get_string('btn_cat_de', lang_code)}", callback_data="show_plans:germany")
        btn_france = types.InlineKeyboardButton(f"🇫🇷 {get_string('btn_cat_fr', lang_code)}", callback_data="show_plans:france")
        btn_turkey = types.InlineKeyboardButton(f"🇹🇷 {get_string('btn_cat_tr', lang_code)}", callback_data="show_plans:turkey")
        btn_combined = types.InlineKeyboardButton(f"🚀 {get_string('btn_cat_combined', lang_code)}", callback_data="show_plans:combined")
        btn_payment_methods = types.InlineKeyboardButton(get_string('btn_payment_methods', lang_code), callback_data="show_payment_options")
        btn_achievement_shop = types.InlineKeyboardButton("🛍️ فروشگاه دستاوردها", callback_data="shop:main")

        btn_back = types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back")
        kb.add(btn_turkey, btn_france)
        kb.add(btn_combined, btn_germany)
        kb.add(btn_achievement_shop, btn_payment_methods)
        kb.add(btn_back)
        return kb

    def achievement_shop_menu(self, user_points: int) -> types.InlineKeyboardMarkup:
            """منوی فروشگاه دستاوردها را با آیتم‌های قابل خرید نمایش می‌دهد."""
            from .config import ACHIEVEMENT_SHOP_ITEMS
            kb = types.InlineKeyboardMarkup(row_width=1)
            
            for item_key, item_data in ACHIEVEMENT_SHOP_ITEMS.items():
                is_affordable = user_points >= item_data['cost']
                emoji = "✅" if is_affordable else "❌"
                button_text = f"{emoji} {item_data['name']} ({item_data['cost']} امتیاز)"
                
                callback_data = f"shop:buy:{item_key}" if is_affordable else "shop:insufficient_points"
                kb.add(types.InlineKeyboardButton(button_text, callback_data=callback_data))

            kb.add(types.InlineKeyboardButton("🔙 بازگشت به سرویس‌ها", callback_data="view_plans"))
            return kb

    def payment_options_menu(self, lang_code: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        
        # دکمه پرداخت آنلاین (فقط اگر لینکی تعریف شده باشد)
        if ONLINE_PAYMENT_LINK:
            btn_online = types.InlineKeyboardButton("💳 پرداخت آنلاین (درگاه)", url=ONLINE_PAYMENT_LINK)
            kb.add(btn_online)
        
        # دکمه کارت به کارت (فقط اگر اطلاعات کارت تعریف شده باشد)
        if CARD_PAYMENT_INFO and CARD_PAYMENT_INFO.get("card_number"):
            bank_name = CARD_PAYMENT_INFO.get("bank_name", "کارت به کارت")
            btn_card = types.InlineKeyboardButton(f"📄 {bank_name}", callback_data="show_card_details")
            kb.add(btn_card)

        # دکمه‌های پرداخت کریپتو (بدون تغییر)
        btn_crypto = types.InlineKeyboardButton(get_string('btn_crypto_payment', lang_code), callback_data="coming_soon")
        kb.add(btn_crypto)
        
        btn_back = types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="view_plans")
        kb.add(btn_back)
        return kb

    def tutorial_main_menu(self, lang_code: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton(get_string('os_android', lang_code), callback_data="tutorial_os:android"),
            types.InlineKeyboardButton(get_string('os_windows', lang_code), callback_data="tutorial_os:windows"),
            types.InlineKeyboardButton(get_string('os_ios', lang_code), callback_data="tutorial_os:ios")
        )
        kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
        return kb

    def tutorial_os_menu(self, os_type: str, lang_code: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        
        if os_type == 'android':
            kb.add(types.InlineKeyboardButton(get_string('app_v2rayng', lang_code), callback_data="tutorial_app:android:v2rayng"))
            kb.add(types.InlineKeyboardButton(get_string('app_hiddify', lang_code), callback_data="tutorial_app:android:hiddify"))
            kb.add(types.InlineKeyboardButton(get_string('app_happ', lang_code), callback_data="tutorial_app:android:happ"))

        elif os_type == 'windows':
            kb.add(types.InlineKeyboardButton(get_string('app_v2rayn', lang_code), callback_data="tutorial_app:windows:v2rayn"))
            kb.add(types.InlineKeyboardButton(get_string('app_hiddify', lang_code), callback_data="tutorial_app:windows:hiddify"))
            
        elif os_type == 'ios':
            kb.add(types.InlineKeyboardButton(get_string('app_shadowrocket', lang_code), callback_data="tutorial_app:ios:shadowrocket"))
            kb.add(types.InlineKeyboardButton(get_string('app_streisand', lang_code), callback_data="tutorial_app:ios:streisand"))
            kb.add(types.InlineKeyboardButton(get_string('app_hiddify', lang_code), callback_data="tutorial_app:ios:hiddify"))
            kb.add(types.InlineKeyboardButton(get_string('app_happ', lang_code), callback_data="tutorial_app:ios:happ"))

        kb.add(types.InlineKeyboardButton(f"🔙 {get_string('btn_back_to_os', lang_code)}", callback_data="tutorials"))
        return kb

    def settings(self, settings_dict: dict, lang_code: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        
        daily_text = f"📊 {get_string('daily_report', lang_code)} {'✅' if settings_dict.get('daily_reports', True) else '❌'}"
        weekly_text = f"📅 {get_string('weekly_report', lang_code)} {'✅' if settings_dict.get('weekly_reports', True) else '❌'}"
        kb.add(
            types.InlineKeyboardButton(daily_text, callback_data="toggle_daily_reports"),
            types.InlineKeyboardButton(weekly_text, callback_data="toggle_weekly_reports")
        )

        expiry_text = f"⏰ {get_string('expiry_warning', lang_code)} {'✅' if settings_dict.get('expiry_warnings', True) else '❌'}"
        auto_delete_text = f"🗑️ {get_string('auto_delete_reports', lang_code)} {'✅' if settings_dict.get('auto_delete_reports', True) else '❌'}"
        kb.add(
            types.InlineKeyboardButton(expiry_text, callback_data="toggle_expiry_warnings"),
            types.InlineKeyboardButton(auto_delete_text, callback_data="toggle_auto_delete_reports")
        )
        
        hiddify_text = f"🪫 {get_string('data_warning_de', lang_code)} {'✅' if settings_dict.get('data_warning_hiddify', True) else '❌'}"
        marzban_text = f"🪫 {get_string('data_warning_fr_tr', lang_code)} {'✅' if settings_dict.get('data_warning_marzban', True) else '❌'}"
        kb.add(types.InlineKeyboardButton(hiddify_text, callback_data="toggle_data_warning_hiddify"),
            types.InlineKeyboardButton(marzban_text, callback_data="toggle_data_warning_marzban"))

        info_config_text = f"ℹ️ {get_string('info_config', lang_code)} {'✅' if settings_dict.get('show_info_config', True) else '❌'}"
        kb.add(types.InlineKeyboardButton(info_config_text, callback_data="toggle_show_info_config"))

        kb.add(types.InlineKeyboardButton(f"🌐 {get_string('change_language', lang_code)}", callback_data="change_language"))
        kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
        return kb

    # =============================================================================
    # Admin Panel Menus
    # =============================================================================
    def admin_panel(self):
        kb = types.InlineKeyboardMarkup(row_width=2)
        btn_dashboard = types.InlineKeyboardButton("📊 داشبورد سریع", callback_data="admin:quick_dashboard")
        btn1 = types.InlineKeyboardButton("👥 مدیریت کاربران", callback_data="admin:management_menu")
        btn2 = types.InlineKeyboardButton("🔎 جستجوی کاربر", callback_data="admin:search_menu")
        btn3 = types.InlineKeyboardButton("⚙️ دستورات گروهی", callback_data="admin:group_actions_menu")
        btn4 = types.InlineKeyboardButton("📊 گزارش‌ها و آمار", callback_data="admin:reports_menu")
        btn5 = types.InlineKeyboardButton("📣 پیام همگانی", callback_data="admin:broadcast")
        btn6 = types.InlineKeyboardButton("💾 پشتیبان‌گیری", callback_data="admin:backup_menu")
        btn7 = types.InlineKeyboardButton("⏰ کارهای زمان‌بندی شده", callback_data="admin:scheduled_tasks")
        btn8 = types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back")
        btn9 = types.InlineKeyboardButton("🗂️ مدیریت پلن‌ها", callback_data="admin:plan_manage")
        btn10 = types.InlineKeyboardButton("⚙️ مدیریت پنل‌ها", callback_data="admin:panel_manage")
        btn11 = types.InlineKeyboardButton("🛠️ ابزارهای سیستمی", callback_data="admin:system_tools_menu")

        kb.add(btn_dashboard)
        kb.add(btn2, btn1)
        kb.add(btn4, btn3)
        kb.add(btn6, btn5)
        kb.add(btn7, btn9)
        kb.add(btn10, btn11)
        kb.add(btn8)
        return kb

    def admin_system_tools_menu(self):
        """منوی جدید برای دستورات حساس و سیستمی."""
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("🔄 به‌روزرسانی دستی آمار مصرف (Snapshot)", callback_data="admin:force_snapshot"))
        kb.add(types.InlineKeyboardButton("🔄 ریست مصرف امروز همه کاربران", callback_data="admin:reset_all_daily_usage_confirm"))
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin:panel"))
        return kb

    def admin_server_selection_menu(self, base_callback: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("آلمان 🇩🇪", callback_data=f"{base_callback}:hiddify"),
            types.InlineKeyboardButton("فرانسه 🇫🇷", callback_data=f"{base_callback}:marzban")
        )
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin:panel"))
        return kb

    ### 2. User Management ###
    def admin_management_menu(self) -> types.InlineKeyboardMarkup:
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.add(
                types.InlineKeyboardButton("آلمان 🇩🇪", callback_data="admin:manage_panel:hiddify"),
                types.InlineKeyboardButton("فرانسه 🇫🇷", callback_data="admin:manage_panel:marzban")
            )
            kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin:panel"))
            return kb

    def admin_panel_management_menu(self, panel: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("➕ افزودن کاربر جدید", callback_data=f"admin:add_user:{panel}"),
            types.InlineKeyboardButton("📋 لیست کاربران پنل", callback_data=f"admin:list:panel_users:{panel}:0")
        )
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به انتخاب پنل", callback_data="admin:management_menu"))
        return kb

    def admin_user_interactive_management(self, identifier: str, is_active: bool, panel: str, back_callback: str | None = None) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        
        context_suffix = ""
        if back_callback and back_callback.endswith("search_menu"):
            context_suffix = ":search"

        status_text = "⚙️ تغییر وضعیت"
        
        kb.add(
            types.InlineKeyboardButton(status_text, callback_data=f"admin:tgl:{identifier}{context_suffix}"),
            types.InlineKeyboardButton("📝 یادداشت ادمین", callback_data=f"admin:note:{identifier}{context_suffix}")
        )
        kb.add(
            types.InlineKeyboardButton("💳 ثبت پرداخت", callback_data=f"admin:log_payment:{identifier}{context_suffix}"),
            types.InlineKeyboardButton("📜 سابقه پرداخت", callback_data=f"admin:phist:{identifier}:0{context_suffix}")
        )
        kb.add(
            types.InlineKeyboardButton("🔄 ریست مصرف", callback_data=f"admin:rusg_m:{identifier}{context_suffix}"),
            types.InlineKeyboardButton("🗑 حذف کامل", callback_data=f"admin:del_cfm:{identifier}{context_suffix}")
        )
        kb.add(
            types.InlineKeyboardButton("🔧 ویرایش کاربر", callback_data=f"admin:edt:{identifier}{context_suffix}"),
            types.InlineKeyboardButton("🔄 ریست تاریخ تولد", callback_data=f"admin:rb:{identifier}{context_suffix}")
        )
        kb.add(
            types.InlineKeyboardButton("📱 حذف دستگاه‌ها", callback_data=f"admin:del_devs:{identifier}{context_suffix}"),
            types.InlineKeyboardButton("💸 ریست محدودیت انتقال", callback_data=f"admin:reset_transfer:{identifier}{context_suffix}")
        )

        final_back_callback = back_callback or f"admin:manage_panel:{panel}"
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=final_back_callback))
        return kb

    def admin_edit_user_menu(self, identifier: str, panel: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("➕ افزودن حجم", callback_data=f"admin:ae:add_gb:{panel}:{identifier}"),
            types.InlineKeyboardButton("➕ افزودن روز", callback_data=f"admin:ae:add_days:{panel}:{identifier}")
        )
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"admin:us:{panel}:{identifier}"))
        return kb
    
    def admin_reset_usage_selection_menu(self, identifier: str, base_callback: str, context: Optional[str] = None) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        
        context_suffix = f":{context}" if context else ""
        panel_short = 'h' 
        
        btn_h = types.InlineKeyboardButton("آلمان 🇩🇪", callback_data=f"admin:{base_callback}:hiddify:{identifier}{context_suffix}")
        btn_m = types.InlineKeyboardButton("فرانسه 🇫🇷", callback_data=f"admin:{base_callback}:marzban:{identifier}{context_suffix}")
        btn_both = types.InlineKeyboardButton("هر دو پنل", callback_data=f"admin:{base_callback}:both:{identifier}{context_suffix}")
        btn_back = types.InlineKeyboardButton("🔙 لغو و بازگشت", callback_data=f"admin:us:{panel_short}:{identifier}{context_suffix}")
        
        kb.add(btn_h, btn_m)
        kb.add(btn_both)
        kb.add(btn_back)
        return kb

    def admin_reports_menu(self) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("🇩🇪", callback_data="admin:panel_reports:hiddify"),
            types.InlineKeyboardButton("🇫🇷", callback_data="admin:panel_reports:marzban")
        )
        kb.add(
            types.InlineKeyboardButton("💳 پرداخت‌ها", callback_data="admin:list:payments:0"),
            types.InlineKeyboardButton("🤖 لیست کاربران ربات", callback_data="admin:list:bot_users:0"))
        kb.add(types.InlineKeyboardButton("📱 دستگاه‌های متصل", callback_data="admin:list_devices:0"),
               types.InlineKeyboardButton("🎂 تولد کاربران", callback_data="admin:list:birthdays:0"))
        kb.add(types.InlineKeyboardButton("📊 گزارش بر اساس پلن", callback_data="admin:user_analysis_menu"))
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin:panel"))
        return kb

    def admin_panel_specific_reports_menu(self, panel: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("✅ فعال (۲۴ ساعت اخیر)", callback_data=f"admin:list:active_users:{panel}:0"),
            types.InlineKeyboardButton("📡 کاربران آنلاین", callback_data=f"admin:list:online_users:{panel}:0")
        )
        kb.add(
            types.InlineKeyboardButton("🚫 هرگز متصل نشده", callback_data=f"admin:list:never_connected:{panel}:0"),
            types.InlineKeyboardButton("⏳ غیرفعال (۱ تا ۷ روز)", callback_data=f"admin:list:inactive_users:{panel}:0")
        )
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به گزارش‌گیری", callback_data="admin:reports_menu"))
        return kb

    def admin_analytics_menu(self, panel: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("🏆 پرمصرف‌ترین کاربران", callback_data=f"admin:list:top_consumers:{panel}:0"))
        if panel == 'hiddify':
            kb.add(types.InlineKeyboardButton("🌡️ وضعیت سلامت پنل", callback_data="admin:health_check"))
        elif panel == 'marzban':
            kb.add(types.InlineKeyboardButton("🖥️ وضعیت سیستم", callback_data="admin:marzban_stats"))

        kb.add(types.InlineKeyboardButton("🔙 بازگشت به انتخاب پنل", callback_data="admin:select_server:analytics_menu"),
               types.InlineKeyboardButton("↩️ بازگشت به پنل مدیریت", callback_data="admin:panel"))
        return kb

    def admin_select_plan_for_report_menu(self) -> types.InlineKeyboardMarkup:
        from .utils import load_service_plans
        kb = types.InlineKeyboardMarkup(row_width=1)
        
        plans = load_service_plans()
        for i, plan in enumerate(plans):
            callback = f"admin:list_by_plan:{i}:0"
            kb.add(types.InlineKeyboardButton(plan.get('name', f'Plan {i+1}'), callback_data=callback)) 
        kb.add(types.InlineKeyboardButton("📝 کاربران بدون پلن", callback_data="admin:list_no_plan:0"))
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin:reports_menu"))
        return kb
        
    ### 4. Group Actions & Other Tools ###
    def admin_select_plan_for_action_menu(self) -> types.InlineKeyboardMarkup:
            from .utils import load_service_plans
            kb = types.InlineKeyboardMarkup(row_width=1)
            
            plans = load_service_plans()
            for i, plan in enumerate(plans):
                callback = f"admin:ga_select_type:{i}"
                kb.add(types.InlineKeyboardButton(plan.get('name', f'Plan {i+1}'), callback_data=callback))
                
            kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin:group_actions_menu"))
            return kb

    def admin_select_action_type_menu(self, context_value: any, context_type: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("➕ افزودن حجم", callback_data=f"admin:ga_ask_value:add_gb:{context_type}:{context_value}"),
            types.InlineKeyboardButton("➕ افزودن روز", callback_data=f"admin:ga_ask_value:add_days:{context_type}:{context_value}")
        )
        
        back_cb = "admin:group_action_select_plan" if context_type == 'plan' else "admin:adv_ga_select_filter"
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb))
        return kb

    def broadcast_target_menu(self) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📡 آنلاین", callback_data="admin:broadcast_target:online"),
            types.InlineKeyboardButton("✅ فعال اخیر", callback_data="admin:broadcast_target:active_1")
        )
        kb.add(
            types.InlineKeyboardButton("⏳ غیرفعال اخیر", callback_data="admin:broadcast_target:inactive_7"),
            types.InlineKeyboardButton("🚫 هرگز متصل نشده", callback_data="admin:broadcast_target:inactive_0")
        )
        kb.add(types.InlineKeyboardButton("👥 همه کاربران ربات", callback_data="admin:broadcast_target:all"))
        kb.add(types.InlineKeyboardButton("🔙 لغو و بازگشت", callback_data="admin:panel"))
        return kb

    def admin_backup_selection_menu(self) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            # FIX: گزینه جدید برای پشتیبان‌گیری از کاربران پنل آلمان اضافه شد
            types.InlineKeyboardButton("📄 کاربران آلمان (Hiddify)", callback_data="admin:backup:hiddify"),
            types.InlineKeyboardButton("📄 کاربران فرانسه (Marzban)", callback_data="admin:backup:marzban"),
            types.InlineKeyboardButton("🗄️ دیتابیس ربات", callback_data="admin:backup:bot_db")
        )
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin:panel"))
        return kb
    # =============================================================================
    # Utility & Helper Menus
    # =============================================================================
    def create_pagination_menu(self, base_callback: str, current_page: int, total_items: int, back_callback: str, lang_code: Optional[str] = None, context: Optional[str] = None) -> types.InlineKeyboardMarkup:
        effective_lang_code = lang_code or 'fa'
        kb = types.InlineKeyboardMarkup(row_width=2)
        
        back_text = f"🔙 {get_string('back', effective_lang_code)}"
        prev_text = f"⬅️ {get_string('btn_prev_page', effective_lang_code)}"
        next_text = f"{get_string('btn_next_page', effective_lang_code)} ➡️"

        if total_items <= PAGE_SIZE:
            kb.add(types.InlineKeyboardButton(back_text, callback_data=back_callback))
            return kb

        # FIX: پسوند زمینه برای افزودن به دکمه‌های صفحه‌بندی ساخته می‌شود
        context_suffix = f":{context}" if context else ""

        nav_buttons = []
        if current_page > 0:
            # پسوند زمینه به callback اضافه می‌شود
            nav_buttons.append(types.InlineKeyboardButton(prev_text, callback_data=f"{base_callback}:{current_page - 1}{context_suffix}"))
        if (current_page + 1) * PAGE_SIZE < total_items:
            # پسوند زمینه به callback اضافه می‌شود
            nav_buttons.append(types.InlineKeyboardButton(next_text, callback_data=f"{base_callback}:{current_page + 1}{context_suffix}"))

        if nav_buttons:
            kb.row(*nav_buttons)

        kb.add(types.InlineKeyboardButton(back_text, callback_data=back_callback))
        return kb

    def user_cancel_action(self, back_callback: str, lang_code: str = 'fa') -> types.InlineKeyboardMarkup:
        """یک کیبورد با دکمه لغو عملیات برای بخش کاربری می‌سازد."""
        kb = types.InlineKeyboardMarkup()
        cancel_text = get_string('btn_cancel_action', lang_code)
        kb.add(types.InlineKeyboardButton(f"✖️ {cancel_text}", callback_data=back_callback))
        return kb

    def admin_cancel_action(self, back_callback="admin:panel") -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✖️ لغو عملیات", callback_data=back_callback))
        return kb
        
    def confirm_delete(self, identifier: str, panel: str) -> types.InlineKeyboardMarkup:
        panel_short = 'h' if panel == 'hiddify' else 'm'
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("❌ بله، حذف کن", callback_data=f"admin:del_a:confirm:{panel_short}:{identifier}"),
            types.InlineKeyboardButton("✅ نه، لغو کن", callback_data=f"admin:del_a:cancel:{panel_short}:{identifier}")
        )
        return kb
    
    def admin_advanced_group_action_filter_menu(self) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("⏳ کاربران در آستانه انقضا (کمتر از ۳ روز)", callback_data="admin:adv_ga_select_action:expiring_soon"))
        kb.add(types.InlineKeyboardButton("🚫 کاربران غیرفعال (بیش از ۳۰ روز)", callback_data="admin:adv_ga_select_action:inactive_30_days"))
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به مدیریت", callback_data="admin:management_menu"))
        return kb

    def admin_search_menu(self) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("🔎 جست و جوی جامع کاربر", callback_data="admin:sg"),
            types.InlineKeyboardButton("🆔 جست و جو با آیدی تلگرام", callback_data="admin:search_by_tid"),
            types.InlineKeyboardButton("🔥 پاکسازی کامل کاربر با آیدی", callback_data="admin:purge_user")
        )
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin:panel"))
        return kb

    def admin_group_actions_menu(self) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("⚙️ دستور گروهی (بر اساس پلن)", callback_data="admin:group_action_select_plan"),
            types.InlineKeyboardButton("🔥 دستور گروهی (پیشرفته)", callback_data="admin:adv_ga_select_filter")
        )
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin:management_menu"))
        return kb
    
    def get_links_menu(self, uuid_id: int, lang_code: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton(f"📋 {get_string('btn_link_normal', lang_code)}", callback_data=f"getlink_normal_{uuid_id}"),
            types.InlineKeyboardButton(f"📝 {get_string('btn_link_b64', lang_code)}", callback_data=f"getlink_b64_{uuid_id}")
        )
        kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data=f"acc_{uuid_id}"))
        return kb

    def admin_system_status_menu(self) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("آلمان 🇩🇪", callback_data="admin:health_check"),
            types.InlineKeyboardButton("فرانسه 🇫🇷", callback_data="admin:marzban_stats")
        )
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin:panel"))
        return kb
    
    def back_or_cancel(self, back_callback: str, cancel_callback: str) -> types.InlineKeyboardMarkup:
        """یک کیبورد با دکمه‌های بازگشت به مرحله قبل و لغو کامل عملیات می‌سازد."""
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("🔙 بازگشت به مرحله قبل", callback_data=back_callback),
            types.InlineKeyboardButton("✖️ لغو عملیات", callback_data=cancel_callback)
        )
        return kb

menu = Menu()