from telebot import types
from .config import EMOJIS, PAGE_SIZE, CARD_PAYMENT_INFO, ONLINE_PAYMENT_LINK
from .language import get_string
from typing import Optional
import urllib

class Menu:
    # =============================================================================
    # User Panel Menus
    # =============================================================================
    def main(self, is_admin: bool, lang_code: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        
        btn_manage_account = types.InlineKeyboardButton(f"{EMOJIS['key']} {get_string('manage_account', lang_code)}", callback_data="manage")
        btn_quick_stats = types.InlineKeyboardButton(f"{EMOJIS['lightning']} {get_string('quick_stats', lang_code)}", callback_data="quick_stats")
        btn_services = types.InlineKeyboardButton(f"🛒 {get_string('view_plans', lang_code)}", callback_data="view_plans")
        btn_wallet = types.InlineKeyboardButton(f"💳 {get_string('wallet', lang_code)}", callback_data="wallet:main")
        btn_support = types.InlineKeyboardButton(f"💬 {get_string('support', lang_code)}", callback_data="support:new")
        btn_doctor = types.InlineKeyboardButton(f"🩺 {get_string('btn_connection_doctor', lang_code)}", callback_data="connection_doctor")
        btn_tutorials = types.InlineKeyboardButton(f"📚 {get_string('btn_tutorials', lang_code)}", callback_data="tutorials")
        btn_user_account = types.InlineKeyboardButton(f"👤 {get_string('user_account_page_title', lang_code)}", callback_data="user_account")
        btn_referral = types.InlineKeyboardButton(f"👥 {get_string('btn_referrals', lang_code)}", callback_data="referral:info")
        btn_achievements = types.InlineKeyboardButton(f"🏆 {get_string('btn_achievements', lang_code)}", callback_data="achievements")
        btn_settings = types.InlineKeyboardButton(f"⚙️ {get_string('settings', lang_code)}", callback_data="settings")
        btn_birthday = types.InlineKeyboardButton(f"🎁 {get_string('birthday_gift', lang_code)}", callback_data="birthday_gift")
        btn_checkin = types.InlineKeyboardButton("📅 اعلام حضور (سکه رایگان)", callback_data="daily_checkin")
        btn_web_login = types.InlineKeyboardButton(f"🌐 {get_string('btn_web_login', lang_code)}", callback_data="web_login")

        kb.add(btn_manage_account, btn_quick_stats)
        kb.add(btn_services, btn_wallet)
        kb.add(btn_doctor, btn_tutorials)
        kb.add(btn_user_account, btn_referral)
        kb.add(btn_achievements, btn_settings)
        kb.add(btn_birthday,btn_support)
        kb.add(btn_checkin,btn_web_login)

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


    def plan_categories_menu(self, lang_code: str) -> types.InlineKeyboardMarkup:
        """
        (نسخه نهایی) منوی انتخاب دسته‌بندی سرویس‌ها را با دکمه "خرید افزودنی" ایجاد می‌کند.
        """
        kb = types.InlineKeyboardMarkup(row_width=2)
        btn_germany = types.InlineKeyboardButton(f"🇩🇪 {get_string('btn_cat_de', lang_code)}", callback_data="show_plans:germany")
        btn_france = types.InlineKeyboardButton(f"🇫🇷 {get_string('btn_cat_fr', lang_code)}", callback_data="show_plans:france")
        btn_turkey = types.InlineKeyboardButton(f"🇹🇷 {get_string('btn_cat_tr', lang_code)}", callback_data="show_plans:turkey")
        btn_usa = types.InlineKeyboardButton(f"🇺🇸 آمریکا", callback_data="show_plans:usa")
        btn_romania = types.InlineKeyboardButton(f"🇷🇴 رومانی", callback_data="show_plans:romania")
        btn_combined = types.InlineKeyboardButton(f"🚀 {get_string('btn_cat_combined', lang_code)}", callback_data="show_plans:combined")
        
        btn_addons = types.InlineKeyboardButton("➕ حجم یا زمان", callback_data="show_addons")
        btn_payment_methods = types.InlineKeyboardButton(get_string('btn_payment_methods', lang_code), callback_data="show_payment_options")
        
        btn_achievement_shop = types.InlineKeyboardButton("🛍️ فروشگاه دستاوردها", callback_data="shop:main")
        btn_back = types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back")

        # چیدمان جدید دکمه‌ها
        kb.add(btn_usa, btn_france)
        kb.add(btn_turkey, btn_romania)
        kb.add(btn_combined, btn_germany)
        kb.add(btn_addons, btn_achievement_shop)
        kb.add(btn_payment_methods)
        kb.add(btn_back)
        return kb


    def achievement_shop_menu(self, user_points: int, access: dict) -> types.InlineKeyboardMarkup:
        """منوی فروشگاه را با دسته‌بندی‌های منظم (حجم، روز و قرعه‌کشی) نمایش می‌دهد."""
        from .config import ACHIEVEMENT_SHOP_ITEMS
        kb = types.InlineKeyboardMarkup(row_width=2)
        
        has_de_access = access.get('has_access_de', False)
        has_fr_access = access.get('has_access_fr', False)
        has_tr_access = access.get('has_access_tr', False)
        has_us_access = access.get('has_access_us', False)
        has_ro_access = access.get('has_access_ro', False)

        day_items = {k: v for k, v in ACHIEVEMENT_SHOP_ITEMS.items() if v.get('days', 0) > 0}
        lottery_items = {k: v for k, v in ACHIEVEMENT_SHOP_ITEMS.items() if 'lottery' in k}
        data_items = {k: v for k, v in ACHIEVEMENT_SHOP_ITEMS.items() if k not in day_items and k not in lottery_items}
        # ----------------------------------------

        def create_button(item_key, item_data):
            target = item_data.get('target')
            show_item = False
            if (target == 'all' or
                (target == 'de' and has_de_access) or
                (target == 'fr' and has_fr_access) or
                (target == 'tr' and has_tr_access) or
                (target == 'us' and has_us_access) or
                (target == 'ro' and has_ro_access)):
                show_item = True

            if show_item:
                is_affordable = user_points >= item_data['cost']
                emoji = "✅" if is_affordable else "❌"
                button_text = f"{emoji} {item_data['name']} ({item_data['cost']})"
                callback_data = f"shop:confirm:{item_key}" if is_affordable else "shop:insufficient_points"
                return types.InlineKeyboardButton(button_text, callback_data=callback_data)
            return None

        # --- نمایش دکمه‌ها بر اساس دسته‌بندی ---
        
        # 1. حجم
        data_buttons = [create_button(k, v) for k, v in data_items.items() if create_button(k, v)]
        if data_buttons:
            kb.add(types.InlineKeyboardButton("📦 افزایش حجم (گیگابایت)", callback_data="noop"))
            kb.add(*data_buttons)

        # 2. روز (زمان)
        day_buttons = [create_button(k, v) for k, v in day_items.items() if create_button(k, v)]
        if day_buttons:
            kb.add(types.InlineKeyboardButton("⏳ تمدید سرویس (روز)", callback_data="noop"))
            kb.add(*day_buttons)
            
        # 3. قرعه‌کشی و سرگرمی (یکپارچه شده)
        lottery_buttons = [create_button(k, v) for k, v in lottery_items.items() if create_button(k, v)]
        
        # اضافه کردن دستی دکمه گردونه شانس به لیست دکمه‌های این بخش
        spin_button = types.InlineKeyboardButton("🎰 گردونه شانس", callback_data="lucky_spin_menu")
        lottery_buttons.append(spin_button)

        if lottery_buttons:
            kb.add(types.InlineKeyboardButton("🎉 سرگرمی و شانس", callback_data="noop"))
            kb.add(*lottery_buttons)

        # -----------------------------------------
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
        kb = types.InlineKeyboardMarkup(row_width=2)
        
        buttons = []
        if os_type == 'android':
            buttons.extend([
                types.InlineKeyboardButton(get_string('app_v2rayng', lang_code), callback_data="tutorial_app:android:v2rayng"),
                types.InlineKeyboardButton(get_string('app_hiddify', lang_code), callback_data="tutorial_app:android:hiddify"),
                types.InlineKeyboardButton(get_string('app_happ', lang_code), callback_data="tutorial_app:android:happ")
            ])
        elif os_type == 'windows':
            buttons.extend([
                types.InlineKeyboardButton(get_string('app_v2rayn', lang_code), callback_data="tutorial_app:windows:v2rayn"),
                types.InlineKeyboardButton(get_string('app_hiddify', lang_code), callback_data="tutorial_app:windows:hiddify"),
                types.InlineKeyboardButton(get_string('app_happ', lang_code), callback_data="tutorial_app:windows:happ")
            ])
        elif os_type == 'ios':
            buttons.extend([
                types.InlineKeyboardButton(get_string('app_shadowrocket', lang_code), callback_data="tutorial_app:ios:shadowrocket"),
                types.InlineKeyboardButton(get_string('app_streisand', lang_code), callback_data="tutorial_app:ios:streisand"),
                types.InlineKeyboardButton(get_string('app_hiddify', lang_code), callback_data="tutorial_app:ios:hiddify"),
                types.InlineKeyboardButton(get_string('app_happ', lang_code), callback_data="tutorial_app:ios:happ")
            ])

        kb.add(*buttons)
        kb.add(types.InlineKeyboardButton(f"🔙 {get_string('btn_back_to_os', lang_code)}", callback_data="tutorials"))
        return kb

    def plan_category_menu(self, lang_code: str, user_balance: float, plans: list) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        
        # نمایش موجودی کیف پول در بالای منو
        balance_str = "{:,.0f}".format(user_balance)
        kb.add(types.InlineKeyboardButton(f" موجودی: {balance_str} تومان ", callback_data="wallet:main"))
        
        # دکمه‌های خرید با کیف پول
        for plan in plans:
            price = plan.get('price', 0)
            is_affordable = user_balance >= price
            emoji = "✅" if is_affordable else "❌"
            price_str = "{:,.0f}".format(price)
            button_text = f"{emoji} {plan.get('name')} ({price_str} تومان)"
            callback_data = f"wallet:buy_confirm:{plan.get('name')}" if is_affordable else "wallet:insufficient"
            kb.add(types.InlineKeyboardButton(button_text, callback_data=callback_data))

        kb.add(types.InlineKeyboardButton(f"➕ {get_string('charge_wallet', lang_code)}", callback_data="wallet:charge"))
        kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
        return kb


    def wallet_main_menu(self, balance: float, lang_code: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        balance_str = "{:,.0f}".format(balance)

        kb.add(types.InlineKeyboardButton(f"موجودی شما: {balance_str} تومان", callback_data="noop"))

        kb.add(
            types.InlineKeyboardButton(f"📜 {get_string('transaction_history', lang_code)}", callback_data="wallet:history"),
            types.InlineKeyboardButton(f"➕ {get_string('charge_wallet', lang_code)}", callback_data="wallet:charge")
            
        )
        kb.add(
            types.InlineKeyboardButton("💸 انتقال موجودی", callback_data="wallet:transfer_start"),
            types.InlineKeyboardButton("⚙️ تمدید خودکار", callback_data="wallet:settings")
        )
        kb.add(types.InlineKeyboardButton("🎁 خرید برای دیگران", callback_data="wallet:gift_start"))
        kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back"))
        return kb


    def wallet_settings_menu(self, auto_renew_status: bool, lang_code: str) -> types.InlineKeyboardMarkup:
        """منوی تنظیمات تمدید خودکار را ایجاد می‌کند."""
        kb = types.InlineKeyboardMarkup(row_width=1)
        status_text = "✅ فعال" if auto_renew_status else "❌ غیرفعال"

        kb.add(types.InlineKeyboardButton(f"تمدید خودکار: {status_text}", callback_data="wallet:toggle_auto_renew"))
        kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="wallet:main"))
        return kb

    def settings(self, settings_dict: dict, lang_code: str, access: dict) -> types.InlineKeyboardMarkup:
        """
        منوی تنظیمات را با دسته‌بندی‌های مشخص و ظاهری تمیز نمایش می‌دهد.
        """
        kb = types.InlineKeyboardMarkup()
        
        def get_status_emoji(key):
            return '✅' if settings_dict.get(key, True) else '❌'

        # --- بخش گزارش‌ها ---
        kb.add(types.InlineKeyboardButton(f"🗓️ {get_string('reports_category', lang_code)}", callback_data="noop"))
        kb.row(
            types.InlineKeyboardButton(
                f"📊 {get_string('daily_report', lang_code)} {get_status_emoji('daily_reports')}",
                callback_data="toggle_daily_reports"
            ),
            types.InlineKeyboardButton(
                f"📅 {get_string('weekly_report', lang_code)} {get_status_emoji('weekly_reports')}",
                callback_data="toggle_weekly_reports"
            )
        )

        # --- بخش هشدار حجم ---
        kb.add(types.InlineKeyboardButton(f"🪫 {get_string('alerts_category', lang_code)}", callback_data="noop"))
        
        data_warning_buttons = []
        if access.get('has_access_de'):
            data_warning_buttons.append(
                types.InlineKeyboardButton(f"🇩🇪 {get_status_emoji('data_warning_de')}", callback_data="toggle_data_warning_de")
            )
        if access.get('has_access_fr'):
            data_warning_buttons.append(
                types.InlineKeyboardButton(f"🇫🇷 {get_status_emoji('data_warning_fr')}", callback_data="toggle_data_warning_fr")
            )
        if access.get('has_access_tr'):
            data_warning_buttons.append(
                types.InlineKeyboardButton(f"🇹🇷 {get_status_emoji('data_warning_tr')} ", callback_data="toggle_data_warning_tr")
            )

        if access.get('has_access_us'): # Add this block
            data_warning_buttons.append(
                types.InlineKeyboardButton(f"🇺🇸 {get_status_emoji('data_warning_us')} ", callback_data="toggle_data_warning_us")
            )

        if access.get('has_access_ro'): # Add this block
            data_warning_buttons.append(
                types.InlineKeyboardButton(f"🇷🇴 {get_status_emoji('data_warning_ro')} ", callback_data="toggle_data_warning_ro")
            )

        if data_warning_buttons:
            kb.row(*data_warning_buttons)

        # --- بخش اعلان‌های عمومی ---
        kb.add(types.InlineKeyboardButton(f"📢 {get_string('general_notifications_category', lang_code)}", callback_data="noop"))
        kb.row(
            types.InlineKeyboardButton(
                f"🏆 {get_string('achievement_alerts', lang_code)} {get_status_emoji('achievement_alerts')}",
                callback_data="toggle_achievement_alerts"
            ),
            types.InlineKeyboardButton(
                f"🎁 {get_string('promotional_alerts', lang_code)} {get_status_emoji('promotional_alerts')}",
                callback_data="toggle_promotional_alerts"
            )
        )

        # --- بخش سایر هشدارها ---
        kb.add(
            types.InlineKeyboardButton(
                f"⏰ {get_string('expiry_warning', lang_code)} {get_status_emoji('expiry_warnings')}",
                callback_data="toggle_expiry_warnings"
            ),
            types.InlineKeyboardButton(
                f"ℹ️ {get_string('info_config', lang_code)} {get_status_emoji('show_info_config')}",
                callback_data="toggle_show_info_config"
            )
        )

        # --- دکمه‌های کنترلی نهایی ---
        kb.add(
            types.InlineKeyboardButton(f"🌐 {get_string('change_language', lang_code)}", callback_data="change_language"),
            types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="back")
        )
        
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
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("🔄 به‌روزرسانی دستی آمار مصرف (Snapshot)", callback_data="admin:force_snapshot"),
               types.InlineKeyboardButton("🔄 ریست مصرف امروز همه کاربران", callback_data="admin:reset_all_daily_usage_confirm"))
        kb.add(types.InlineKeyboardButton("🏆 ریست امتیازات و دستاوردها", callback_data="admin:reset_all_points_confirm"),
               types.InlineKeyboardButton("🗑️ حذف تمام دستگاه‌های ثبت‌شده", callback_data="admin:delete_all_devices_confirm"))
        kb.add(types.InlineKeyboardButton("💸 ریست موجودی تمام کاربران", callback_data="admin:reset_all_balances_confirm"))
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
        """(نسخه خلاصه‌ شده) منوی مدیریت کاربر با گزینه‌های گروه‌بندی شده."""
        kb = types.InlineKeyboardMarkup(row_width=2)
        
        context_suffix = ""
        if back_callback and back_callback.endswith("search_menu"):
            context_suffix = ":s"

        panel_short = 'h' if panel == 'hiddify' else 'm'

        # ردیف اول
        kb.add(
            types.InlineKeyboardButton("⚙️ تغییر وضعیت", callback_data=f"admin:us_tgl:{identifier}{context_suffix}"),
            types.InlineKeyboardButton("📝 یادداشت ادمین", callback_data=f"admin:us_note:{identifier}{context_suffix}:{panel_short}")
        )
        # ردیف دوم
        kb.add(
            types.InlineKeyboardButton("💳 ثبت پرداخت", callback_data=f"admin:us_lpay:{identifier}{context_suffix}"),
            types.InlineKeyboardButton("📜 سابقه پرداخت", callback_data=f"admin:us_phist:{identifier}:0{context_suffix}")
        )
        # ردیف سوم
        kb.add(
            types.InlineKeyboardButton("💰 شارژ کیف پول", callback_data=f"admin:us_mchg:{identifier}{context_suffix}:{panel_short}"),
            types.InlineKeyboardButton("💸 برداشت وجه", callback_data=f"admin:us_wdrw:{identifier}{context_suffix}")
        )
        # ردیف چهارم
        kb.add(
            types.InlineKeyboardButton("🔧 ویرایش کاربر", callback_data=f"admin:us_edt:{identifier}{context_suffix}"),
            types.InlineKeyboardButton("📱 حذف دستگاه‌ها", callback_data=f"admin:us_ddev:{identifier}{context_suffix}")
        )
        # ردیف پنجم: دکمه‌های جدید برای منوهای خلاصه‌ شده
        kb.add(
            types.InlineKeyboardButton("♻️ تنظیمات ریست", callback_data=f"admin:us_reset_menu:{identifier}:{panel_short}{context_suffix}"),
            types.InlineKeyboardButton("⚠️ ارسال هشدار", callback_data=f"admin:us_warn_menu:{identifier}:{panel_short}{context_suffix}")
        )
        
        # ردیف ششم
        btn_renew_subscription = types.InlineKeyboardButton("🔄 تمدید اشتراک", callback_data=f"admin:renew_sub_menu:{identifier}{context_suffix}")
        btn_delete_user = types.InlineKeyboardButton("🗑 حذف کامل", callback_data=f"admin:us_delc:{identifier}{context_suffix}")
        kb.add(btn_renew_subscription, btn_delete_user)

        kb.add(types.InlineKeyboardButton("🥺 پیام دلتنگی", callback_data=f"admin:us_winback:{identifier}:{panel_short}{context_suffix}")) 
        # دکمه بازگشت
        final_back_callback = back_callback or f"admin:manage_panel:{panel}"
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=final_back_callback))
        
        return kb

    def admin_renew_subscription_menu(self, identifier: str, context_suffix: str) -> types.InlineKeyboardMarkup:
        """منوی گزینه‌های تمدید اشتراک را برای ادمین ایجاد می‌کند."""
        kb = types.InlineKeyboardMarkup(row_width=1)
        panel_short = 'h' # Fallback
        
        kb.add(
            types.InlineKeyboardButton("🔄 اعمال پلن جدید", callback_data=f"admin:renew_select_plan:{identifier}{context_suffix}")
        )
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به کاربر", callback_data=f"admin:us:{panel_short}:{identifier}{context_suffix}"))
        return kb

    def admin_select_plan_for_renew_menu(self, identifier: str, context_suffix: str) -> types.InlineKeyboardMarkup:
        """منوی انتخاب پلن برای تمدید اشتراک کاربر را نمایش می‌دهد."""
        from .utils import load_service_plans
        kb = types.InlineKeyboardMarkup(row_width=1)
        panel_short = 'h' # Fallback
        
        plans = load_service_plans()
        for i, plan in enumerate(plans):
            plan_name = plan.get('name', f'Plan {i+1}')
            callback_data = f"admin:renew_apply_plan:{i}:{identifier}{context_suffix}"
            kb.add(types.InlineKeyboardButton(plan_name, callback_data=callback_data))
        
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به گزینه‌های تمدید", callback_data=f"admin:renew_sub_menu:{identifier}{context_suffix}"))
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
        kb.add(
            types.InlineKeyboardButton("💰 موجودی کاربران", callback_data="admin:list:balances:0"), 
            types.InlineKeyboardButton("🎂 تولد کاربران", callback_data="admin:list:birthdays:0"))
        kb.add(types.InlineKeyboardButton("🏆 رتبه‌بندی امتیازها", callback_data="admin:list:leaderboard:0"),
                types.InlineKeyboardButton("📊 گزارش بر اساس پلن", callback_data="admin:user_analysis_menu"))
        kb.add(types.InlineKeyboardButton("📱 دستگاه‌های متصل", callback_data="admin:list_devices:0"),
               types.InlineKeyboardButton("💸 گزارش مالی", callback_data="admin:financial_report"))
        kb.add(types.InlineKeyboardButton("📊 بازخورد کاربران", callback_data="admin:list:feedback:0"))
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
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📄 کاربران آلمان (Hiddify)", callback_data="admin:backup:hiddify"),
            types.InlineKeyboardButton("📄 کاربران فرانسه (Marzban)", callback_data="admin:backup:marzban")
        )
        kb.add(types.InlineKeyboardButton("🗄️ دیتابیس ربات", callback_data="admin:backup:bot_db"))
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin:panel"))
        return kb
    
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

    def post_charge_menu(self, lang_code: str = 'fa') -> types.InlineKeyboardMarkup:
        """یک کیبورد برای نمایش بعد از شارژ موفق کیف پول ایجاد می‌کند."""
        kb = types.InlineKeyboardMarkup(row_width=2)
        btn_view_plans = types.InlineKeyboardButton("🛒 مشاهده سرویس‌ها", callback_data="view_plans")
        btn_back_to_wallet = types.InlineKeyboardButton("🔙 بازگشت به کیف پول", callback_data="wallet:main")
        kb.add(btn_view_plans, btn_back_to_wallet)
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
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("🔎 نام کاربر", callback_data="admin:sg"),
            types.InlineKeyboardButton("🆔 آیدی تلگرام", callback_data="admin:search_by_tid")
        )
        kb.add(types.InlineKeyboardButton("🔥 پاکسازی کامل کاربر با آیدی", callback_data="admin:purge_user"))
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
    
    def admin_award_badge_menu(self, identifier: str, context_suffix: str) -> types.InlineKeyboardMarkup:
        """منوی اهدای دستی نشان‌ها توسط ادمین."""
        kb = types.InlineKeyboardMarkup(row_width=2)
        panel_short = 'h' # Fallback panel
        # A list of admin-awardable badges (short_code, name)
        awardable_badges = [
            ('s_coach', "🏊‍♀️ مربی شنا"), ('b_coach', "🏋️‍♂️ مربی بدن‌سازی"),
            ('a_coach', "🧘‍♀️ مربی Aerial"), ('sc_champ', "🏊‍♂️ قهرمان شنا"),
            ('mp', "📣 یار رسانه‌ای"), ('sc', "🛠️ همیار پشتیبانی")
        ]
        buttons = [
            types.InlineKeyboardButton(name, callback_data=f"admin:awd_b:{short_code}:{identifier}{context_suffix}")
            for short_code, name in awardable_badges
        ]
        for i in range(0, len(buttons), 2):
            if i + 1 < len(buttons):
                kb.add(buttons[i], buttons[i+1])
            else:
                kb.add(buttons[i])

        kb.add(types.InlineKeyboardButton("🔙 بازگشت به کاربر", callback_data=f"admin:us:{panel_short}:{identifier}{context_suffix}"))
        return kb

    def request_badge_menu(self) -> types.InlineKeyboardMarkup:
        """منوی درخواست نشان‌های ورزشی را ایجاد می‌کند."""
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("💪 بدن‌سازی", callback_data="achievements:req:bodybuilder"),
            types.InlineKeyboardButton("🏊‍♂️ شنا", callback_data="achievements:req:water_athlete")
        )
        kb.add(
            types.InlineKeyboardButton("🤸‍♀️ اریال ", callback_data="achievements:req:aerialist")
        )
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به دستاوردها", callback_data="achievements"))
        return kb
    
    def back_or_cancel(self, back_callback: str, cancel_callback: str) -> types.InlineKeyboardMarkup:
        """یک کیبورد با دکمه‌های بازگشت به مرحله قبل و لغو کامل عملیات می‌سازد."""
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("🔙 بازگشت به مرحله قبل", callback_data=back_callback),
            types.InlineKeyboardButton("✖️ لغو عملیات", callback_data=cancel_callback)
        )
        return kb

    def select_account_for_purchase_menu(self, user_uuids: list, plan_name: str, lang_code: str) -> types.InlineKeyboardMarkup:
        """منوی انتخاب اکانت برای خرید را ایجاد می‌کند."""
        kb = types.InlineKeyboardMarkup(row_width=1)
        for u in user_uuids:
            button_text = f"👤 {u.get('name', get_string('unknown_user', lang_code))}"
            callback_data = f"wallet:buy_for_account:{u['id']}:{plan_name}"
            kb.add(types.InlineKeyboardButton(button_text, callback_data=callback_data))
        
        kb.add(types.InlineKeyboardButton(f"🔙 {get_string('back', lang_code)}", callback_data="view_plans"))
        return kb
    
    def feedback_rating_menu(self) -> types.InlineKeyboardMarkup:
        """منوی نظرسنجی رضایت (۱ تا ۵ ستاره) را ایجاد می‌کند."""
        kb = types.InlineKeyboardMarkup(row_width=1)
        buttons = [
            types.InlineKeyboardButton("⭐️", callback_data="feedback:rating:1"),
            types.InlineKeyboardButton("⭐️⭐️", callback_data="feedback:rating:2"),
            types.InlineKeyboardButton("⭐️⭐️⭐️", callback_data="feedback:rating:3"),
            types.InlineKeyboardButton("⭐️⭐️⭐️⭐️", callback_data="feedback:rating:4"),
            types.InlineKeyboardButton("⭐️⭐️⭐️⭐️⭐️", callback_data="feedback:rating:5"),
        ]
        kb.add(*buttons)
        kb.add(types.InlineKeyboardButton("✖️ علاقه‌ای ندارم", callback_data="feedback:cancel"))
        return kb

menu = Menu()