from flask import Blueprint, render_template, request, abort, jsonify, session, redirect, url_for, flash
from functools import wraps
import logging
from bot.config import ADMIN_SECRET_KEY
from bot.database import db
from bot.utils import set_template_server_type_service, reset_all_templates
from bot.config import ADMIN_SUPPORT_CONTACT,BIRTHDAY_GIFT_GB,BIRTHDAY_GIFT_DAYS,WARNING_USAGE_THRESHOLD,WARNING_DAYS_BEFORE_EXPIRY,DAILY_USAGE_ALERT_THRESHOLD_GB,NOTIFY_ADMIN_ON_USAGE
from datetime import datetime

logger = logging.getLogger(__name__)
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# --- تابع امنیتی ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

# --- روت‌های اصلی ---
@admin_bp.route('/dashboard')
@admin_required
def admin_dashboard():
    from .services import get_dashboard_data  # Import moved inside
    try:
        context = get_dashboard_data()
        return render_template('admin_dashboard.html', **context, is_admin=True)
    except Exception as e:
        logger.error(f"Error in admin_dashboard: {e}", exc_info=True)
        return "<h1>خطا در بارگذاری داشبورد</h1>", 500

@admin_bp.route('/reports/comprehensive')
@admin_required
def comprehensive_report_page():
    from .services import generate_comprehensive_report_data  # Import moved inside
    try:
        report_data = generate_comprehensive_report_data()
        return render_template('admin_comprehensive_report.html', report_data=report_data, is_admin=True)
    except Exception as e:
        logger.error(f"Failed to generate comprehensive report: {e}", exc_info=True)
        return render_template('admin_error.html', error_message="خطا در تولید گزارش جامع.", is_admin=True)
    
@admin_bp.route('/payments')
@admin_required
def payment_list_page():
    from .services import get_all_payments_for_admin  # Import moved inside
    try:
        all_payments = get_all_payments_for_admin()
        return render_template('admin_payment_list.html',
                               payments=all_payments,
                               is_admin=True
                               )
    except Exception as e:
        logger.error(f"Error in payment_list_page: {e}", exc_info=True)
        return "<h1>خطا در بارگذاری صفحه پرداخت‌ها</h1>", 500

@admin_bp.route('/analytics')
@admin_required
def analytics_page():
    from .services import get_analytics_data  # Import moved inside
    try:
        analytics_data = get_analytics_data()
        return render_template('admin_analytics.html',
                               analytics_data=analytics_data,
                               is_admin=True
                               )
    except Exception as e:
        logger.error(f"Error in analytics_page: {e}", exc_info=True)
        return "<h1>خطا در بارگذاری صفحه تحلیل</h1>", 500

@admin_bp.route('/financials')
@admin_required
def financial_report_page():
    from .services import get_financial_report_data
    try:
        data = get_financial_report_data()
        # ماه جاری را برای پیش‌فرض فیلد تاریخ به قالب ارسال می‌کنیم
        current_month_str = datetime.now().strftime('%Y-%m')
        return render_template('admin_financials.html', **data, is_admin=True, current_month_str=current_month_str)
    except Exception as e:
        logger.error(f"Error in financial_report_page: {e}", exc_info=True)
        flash("خطا در بارگذاری گزارش مالی.", "error")
        return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/financials/add_cost', methods=['POST'])
@admin_required
def add_cost_route():
    try:
        month_str = request.form.get('month') # e.g., "2024-09"
        cost = float(request.form.get('cost'))
        description = request.form.get('description')
        
        year, month = map(int, month_str.split('-'))
        
        if db.add_monthly_cost(year, month, cost, description):
            flash("هزینه با موفقیت ثبت شد.", "success")
        else:
            flash("خطا: هزینه‌ای با این مشخصات از قبل وجود دارد.", "error")
    except Exception as e:
        logger.error(f"Error adding cost: {e}", exc_info=True)
        flash("خطا در ثبت هزینه.", "error")
    return redirect(url_for('admin.financial_report_page'))

@admin_bp.route('/financials/delete_cost/<int:cost_id>', methods=['POST'])
@admin_required
def delete_cost_route(cost_id):
    if db.delete_monthly_cost(cost_id):
        flash("هزینه با موفقیت حذف شد.", "success")
    else:
        flash("خطا در حذف هزینه.", "error")
    return redirect(url_for('admin.financial_report_page'))

# --- بخش مدیریت کاربران ---
@admin_bp.route('/users')
@admin_required
def user_management_page():
    return render_template('admin_user_management.html', is_admin=True)

@admin_bp.route('/api/users')
@admin_required
def get_users_api_paginated():
    from .services import get_paginated_users  # Import moved inside
    try:
        data = get_paginated_users(request.args)
        return jsonify(data)
    except Exception as e:
        logger.error(f"API Error in get_paginated_users: {e}", exc_info=True)
        return jsonify({"error": "خطا در دریافت لیست کاربران."}), 500

@admin_bp.route('/api/users/create', methods=['POST'])
@admin_required
def create_user_api():
    from .services import create_user_in_panel  # Import moved inside
    try:
        create_user_in_panel(request.json)
        return jsonify({'success': True, 'message': 'کاربر با موفقیت ساخته شد.'})
    except Exception as e:
        logger.error(f"API Failed to create user: {e}", exc_info=True)
        error_message = "کاربری با این نام وجود دارد." if "UNIQUE" in str(e) or "already exists" in str(e) else str(e)
        return jsonify({'success': False, 'message': f'خطا: {error_message}'}), 500
    
@admin_bp.route('/api/users/update', methods=['POST'])
@admin_required
def update_user_api():
    from .services import update_user_in_panels  # Import moved inside
    try:
        update_user_in_panels(request.json)
        return jsonify({'success': True, 'message': 'کاربر با موفقیت به‌روزرسانی شد.'})
    except Exception as e:
        logger.error(f"API Failed to update user: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'خطا در به‌روزرسانی: {e}'}), 500

@admin_bp.route('/api/users/delete/<string:uuid>', methods=['DELETE'])
@admin_required
def delete_user_api(uuid):
    from .services import delete_user_from_panels  # Import moved inside
    try:
        delete_user_from_panels(uuid)
        return jsonify({'success': True, 'message': 'کاربر با موفقیت حذف شد.'})
    except Exception as e:
        logger.error(f"API Failed to delete user {uuid}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'خطا در حذف: {e}'}), 500

# --- بخش مدیریت قالب‌ها ---
@admin_bp.route('/templates')
@admin_required
def manage_templates_page():
    templates = db.get_all_config_templates()
    return render_template('admin_templates.html', templates=templates, is_admin=True)

@admin_bp.route('/api/templates', methods=['POST'])
@admin_required
def add_templates_api():
    from .services import add_templates_from_text  # Import moved inside
    try:
        added_count = add_templates_from_text(request.json.get('templates_str'))
        return jsonify({'success': True, 'message': f"{added_count} کانفیگ جدید اضافه شد."})
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        logger.error(f"API Failed to add batch templates: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'خطا در افزودن کانفیگ‌ها.'}), 500

@admin_bp.route('/api/templates/toggle_active/<int:template_id>', methods=['POST'])
@admin_required
def toggle_template_api(template_id):
    from .services import toggle_template  # Import moved inside
    try:
        is_now_active = toggle_template(template_id) 
        return jsonify({
            'success': True, 
            'message': 'وضعیت کانفیگ تغییر کرد.',
            'is_active': is_now_active
        })
    except Exception as e:
        logger.error(f"API Failed to toggle template {template_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'خطا در تغییر وضعیت.'}), 500

@admin_bp.route('/api/templates/update/<int:template_id>', methods=['POST'])
@admin_required
def update_template_api(template_id):
    from .services import update_template  # Import moved inside
    try:
        data = request.get_json()
        if not data or 'template_str' not in data:
            return jsonify({'success': False, 'message': 'اطلاعات ارسالی ناقص است.'}), 400
        
        update_template(template_id, data['template_str'])
        return jsonify({'success': True, 'message': 'کانفیگ با موفقیت به‌روزرسانی شد.'})
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        logger.error(f"API Failed to update template {template_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'خطا در به‌روزرسانی: {e}'}), 500

@admin_bp.route('/api/templates/<int:template_id>', methods=['DELETE'])
@admin_required
def delete_template_api(template_id):
    from .services import delete_template  # Import moved inside
    try:
        delete_template(template_id)
        return jsonify({'success': True, 'message': 'کانفیگ حذف شد.'})
    except Exception as e:
        logger.error(f"API Failed to delete template {template_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'خطا در حذف کانفیگ.'}), 500
    
@admin_bp.route('/settings')
@admin_required
def admin_settings_page():
    from .services import get_schedule_info_service  # Import moved inside
    try:
        schedule_information = get_schedule_info_service()
        current_settings = {
            "شناسه پشتیبانی ادمین": ADMIN_SUPPORT_CONTACT,
            "حجم هدیه تولد (GB)": BIRTHDAY_GIFT_GB,
            "مدت زمان هدیه تولد (روز)": BIRTHDAY_GIFT_DAYS,
            "آستانه هشدار مصرف (درصد)": WARNING_USAGE_THRESHOLD,
            "هشدار انقضا از چند روز قبل": WARNING_DAYS_BEFORE_EXPIRY,
            "آستانه هشدار مصرف غیرعادی روزانه (GB)": DAILY_USAGE_ALERT_THRESHOLD_GB,
            "اطلاع‌رسانی به ادمین در مورد مصرف بالا": NOTIFY_ADMIN_ON_USAGE
        }
        return render_template(
            'admin_settings.html',
            settings=current_settings,
            schedule_info=schedule_information,
            is_admin=True
        )
    except Exception as e:
        logger.error(f"خطا در بارگذاری صفحه تنظیمات: {e}", exc_info=True)
        flash("خطا در بارگذاری صفحه تنظیمات. لطفاً لاگ‌ها را بررسی کنید.", "error")
        return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/api/users/toggle_vip/<string:uuid>', methods=['POST'])
@admin_required
def toggle_user_vip_api(uuid):
    from .services import toggle_user_vip_status
    try:
        toggle_user_vip_status(uuid)
        return jsonify({'success': True, 'message': 'وضعیت VIP کاربر تغییر کرد.'})
    except Exception as e:
        logger.error(f"API Failed to toggle user VIP status {uuid}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'خطا در تغییر وضعیت VIP.'}), 500

@admin_bp.route('/api/templates/toggle_special/<int:template_id>', methods=['POST'])
@admin_required
def toggle_template_special_api(template_id):
    from .services import toggle_template_special_status
    try:
        toggle_template_special_status(template_id)
        return jsonify({'success': True, 'message': 'وضعیت "ویژه" کانفیگ تغییر کرد.'})
    except Exception as e:
        logger.error(f"API Failed to toggle template special status {template_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'خطا در تغییر وضعیت.'}), 500

@admin_bp.route('/api/templates/set_server_type/<int:template_id>', methods=['POST'])
@admin_required
def set_template_server_type_api(template_id):
    from bot.utils import set_template_server_type_service
    server_type = request.json.get('server_type')
    try:
        set_template_server_type_service(template_id, server_type)
        return jsonify({'success': True, 'message': 'نوع سرور کانفیگ به‌روز شد.'})
    except Exception as e:
        return jsonify({'success': False, 'message': 'خطا در به‌روزرسانی.'}), 500

@admin_bp.route('/api/templates/reset', methods=['POST'])
@admin_required
def reset_templates_api():
    from bot.utils import reset_all_templates
    try:
        reset_all_templates()
        return jsonify({'success': True, 'message': 'تمام کانفیگ‌ها با موفقیت حذف و شمارنده ریست شد.'})
    except Exception as e:
        logger.error(f"API Failed to reset templates: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'خطا در عملیات ریست.'}), 500
    
@admin_bp.route('/marzban-mapping')
@admin_required
def marzban_mapping_page():
    from .services import get_marzban_mappings_service
    mappings = get_marzban_mappings_service()
    return render_template('admin_marzban_mapping.html', mappings=mappings, is_admin=True)

@admin_bp.route('/marzban-mapping/add', methods=['POST'])
@admin_required
def add_marzban_mapping_route():
    from .services import add_marzban_mapping_service
    hiddify_uuid = request.form.get('hiddify_uuid')
    marzban_username = request.form.get('marzban_username')
    success, message = add_marzban_mapping_service(hiddify_uuid, marzban_username)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')
    return redirect(url_for('admin.marzban_mapping_page'))

@admin_bp.route('/marzban-mapping/delete', methods=['POST'])
@admin_required
def delete_marzban_mapping_route():
    from .services import delete_marzban_mapping_service
    hiddify_uuid = request.form.get('hiddify_uuid')
    success, message = delete_marzban_mapping_service(hiddify_uuid)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')
    return redirect(url_for('admin.marzban_mapping_page'))

@admin_bp.route('/logs')
@admin_required
def view_logs_page():
    return render_template('admin_logs.html', is_admin=True)

@admin_bp.route('/api/logs')
@admin_required
def get_logs_api():
    from .services import get_logs_service
    try:
        log_data = get_logs_service()
        return jsonify(log_data)
    except Exception as e:
        logger.error(f"Error fetching logs via API: {e}", exc_info=True)
        return jsonify({'bot_log': 'Error fetching logs.', 'error_log': 'Error fetching logs.'}), 500

@admin_bp.route('/api/logs/clear', methods=['POST'])
@admin_required
def clear_logs_api():
    from .services import clear_logs_service
    try:
        success, message = clear_logs_service()
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': message}), 500
    except Exception as e:
        logger.error(f"Error clearing logs via API: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'یک خطای ناشناخته در سرور رخ داد.'}), 500
    
@admin_bp.route('/user-access')
@admin_required
def user_access_page():
    # یک تابع جدید در database.py برای گرفتن همه کاربران با اطلاعات تلگرامشان بساز
    bot_users_with_uuids = db.get_all_bot_users_with_uuids()
    return render_template('admin_user_access.html', bot_users=bot_users_with_uuids, is_admin=True)

@admin_bp.route('/api/users/toggle_access', methods=['POST'])
@admin_required
def toggle_user_access_api():
    data = request.json
    uuid_id = data.get('uuid_id')
    server = data.get('server')
    status = data.get('status')

    if not all([uuid_id, server, isinstance(status, bool)]):
        return jsonify({'success': False, 'message': 'درخواست نامعتبر است.'}), 400

    # یک تابع جدید در database.py برای این کار بساز
    success = db.update_user_server_access(uuid_id, server, status)
    if success:
        return jsonify({'success': True, 'message': 'وضعیت دسترسی تغییر کرد.'})
    else:
        return jsonify({'success': False, 'message': 'خطا در به‌روزرسانی دیتابیس.'}), 500
    
@admin_bp.route('/api/templates/toggle_random/<int:template_id>', methods=['POST'])
@admin_required
def toggle_template_random_api(template_id):
    try:
        db.toggle_template_random_pool(template_id)
        return jsonify({'success': True, 'message': 'وضعیت عضویت در استخر تصادفی تغییر کرد.'})
    except Exception as e:
        logger.error(f"API Failed to toggle template random pool status {template_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'خطا در تغییر وضعیت.'}), 500
    
@admin_bp.route('/financials/details/<int:year>/<int:month>')
@admin_required
def financial_details_page(year, month):
    from .services import get_monthly_transaction_details
    try:
        transactions, shamsi_month_str = get_monthly_transaction_details(year, month)
        return render_template('admin_financial_details.html',
                               transactions=transactions,
                               shamsi_month=shamsi_month_str,
                               is_admin=True)
    except Exception as e:
        logger.error(f"Error loading financial details page for {year}-{month}: {e}", exc_info=True)
        flash("خطا در بارگذاری جزئیات تراکنش‌ها.", "error")
        return redirect(url_for('admin.financial_report_page'))