from flask import Blueprint, render_template, request, abort, jsonify, session, redirect, url_for, flash
from functools import wraps
import logging
from bot.config import ADMIN_SECRET_KEY
from bot.database import db
from bot.settings_manager import settings
from bot.utils import set_template_server_type_service, reset_all_templates
from .services import (
    get_dashboard_data,
    generate_comprehensive_report_data,
    get_paginated_users,
    create_user_in_panel,
    delete_user_from_panels,
    add_templates_from_text,
    update_user_in_panels,
    toggle_template,
    update_template,
    delete_template,
    get_all_payments_for_admin,
    get_analytics_data,
    get_all_settings,
    save_all_settings,
    get_marzban_mappings_service, 
    add_marzban_mapping_service,
    delete_marzban_mapping_service,
    get_schedule_info_service
)

logger = logging.getLogger(__name__)
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# --- تابع امنیتی ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            # ری‌دایرکت به صفحه لاگین ادمین (اختیاری: پیام خطا بده)
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

# --- روت‌های اصلی ---
@admin_bp.route('/dashboard')
@admin_required
def admin_dashboard():
    try:
        context = get_dashboard_data()
        return render_template('admin_dashboard.html', **context, is_admin=True)
    except Exception as e:
        logger.error(f"Error in admin_dashboard: {e}", exc_info=True)
        return "<h1>خطا در بارگذاری داشبورد</h1>", 500

@admin_bp.route('/reports/comprehensive')
@admin_required
def comprehensive_report_page():
    try:
        report_data = generate_comprehensive_report_data()
        return render_template('admin_comprehensive_report.html', report_data=report_data, is_admin=True)
    except Exception as e:
        logger.error(f"Failed to generate comprehensive report: {e}", exc_info=True)
        return render_template('admin_error.html', error_message="خطا در تولید گزارش جامع.", is_admin=True)
    
@admin_bp.route('/payments')
@admin_required
def payment_list_page():
    """صفحه جدید برای نمایش لیست تمام پرداخت‌ها به ادمین."""
    try:
        # دریافت تمام پرداخت‌ها از سرویس
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
    """صفحه جدید برای نمایش نمودارهای تحلیل و گزارش‌های پیشرفته."""
    try:
        analytics_data = get_analytics_data()
        return render_template('admin_analytics.html',
                               analytics_data=analytics_data,
                               is_admin=True
                               )
    except Exception as e:
        logger.error(f"Error in analytics_page: {e}", exc_info=True)
        return "<h1>خطا در بارگذاری صفحه تحلیل</h1>", 500

# --- بخش مدیریت کاربران ---
@admin_bp.route('/users')
@admin_required
def user_management_page():
    return render_template('admin_user_management.html', is_admin=True)

@admin_bp.route('/api/users')
@admin_required
def get_users_api_paginated():
    try:
        data = get_paginated_users(request.args)
        return jsonify(data)
    except Exception as e:
        logger.error(f"API Error in get_paginated_users: {e}", exc_info=True)
        return jsonify({"error": "خطا در دریافت لیست کاربران."}), 500

@admin_bp.route('/api/users/create', methods=['POST'])
@admin_required
def create_user_api():
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
    try:
        update_user_in_panels(request.json)
        return jsonify({'success': True, 'message': 'کاربر با موفقیت به‌روزرسانی شد.'})
    except Exception as e:
        logger.error(f"API Failed to update user: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'خطا در به‌روزرسانی: {e}'}), 500

@admin_bp.route('/api/users/delete/<string:uuid>', methods=['DELETE'])
@admin_required
def delete_user_api(uuid):
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
    try:
        added_count = add_templates_from_text(request.json.get('templates_str'))
        return jsonify({'success': True, 'message': f"{added_count} کانفیگ جدید اضافه شد."})
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        logger.error(f"API Failed to add batch templates: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'خطا در افزودن کانفیگ‌ها.'}), 500

@admin_bp.route('/api/templates/toggle/<int:template_id>', methods=['POST'])
@admin_required
def toggle_template_api(template_id):
    try:
        toggle_template(template_id)
        return jsonify({'success': True, 'message': 'وضعیت کانفیگ تغییر کرد.'})
    except Exception as e:
        logger.error(f"API Failed to toggle template {template_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'خطا در تغییر وضعیت.'}), 500

# ✅ روت جدید برای ویرایش
@admin_bp.route('/api/templates/update/<int:template_id>', methods=['POST'])
@admin_required
def update_template_api(template_id):
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
    try:
        delete_template(template_id)
        return jsonify({'success': True, 'message': 'کانفیگ حذف شد.'})
    except Exception as e:
        logger.error(f"API Failed to delete template {template_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'خطا در حذف کانفیگ.'}), 500
    
# ✅ **بخش جدید: روت‌های مدیریت تنظیمات**
@admin_bp.route('/settings')
@admin_required
def admin_settings_page():
    """صفحه تنظیمات پیشرفته را نمایش می‌دهد."""
    try:
        current_settings = get_all_settings()
        # کد جدید: دریافت اطلاعات زمان‌بندی
        schedule_info = get_schedule_info_service()
        return render_template('admin_settings.html', settings=current_settings, schedule_info=schedule_info, is_admin=True)
    except Exception as e:
        logger.error(f"Error loading settings page: {e}", exc_info=True)
        return "<h1>خطا در بارگذاری صفحه تنظیمات</h1>", 500

@admin_bp.route('/api/settings/save', methods=['POST'])
@admin_required
def save_settings_api():
    """تنظیمات جدید را از طریق API ذخیره می‌کند."""
    try:
        new_settings = request.json
        save_all_settings(new_settings)
        return jsonify({'success': True, 'message': 'تنظیمات با موفقیت ذخیره شد. برای اعمال برخی تغییرات، ممکن است نیاز به ری‌استارت ربات باشد.'})
    except Exception as e:
        logger.error(f"API Error saving settings: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'خطا در ذخیره‌سازی: {str(e)}'}), 500
    
@admin_bp.route('/api/users/toggle_vip/<string:uuid>', methods=['POST'])
@admin_required
def toggle_user_vip_api(uuid):
    """API برای تغییر وضعیت VIP کاربر."""
    from .services import toggle_user_vip_status  # ایمپورت محلی
    try:
        toggle_user_vip_status(uuid)
        return jsonify({'success': True, 'message': 'وضعیت VIP کاربر تغییر کرد.'})
    except Exception as e:
        logger.error(f"API Failed to toggle user VIP status {uuid}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'خطا در تغییر وضعیت VIP.'}), 500

@admin_bp.route('/api/templates/toggle_special/<int:template_id>', methods=['POST'])
@admin_required
def toggle_template_special_api(template_id):
    """API برای تغییر وضعیت "ویژه" بودن کانفیگ."""
    from .services import toggle_template_special_status # ایمپورت محلی
    try:
        toggle_template_special_status(template_id)
        return jsonify({'success': True, 'message': 'وضعیت "ویژه" کانفیگ تغییر کرد.'})
    except Exception as e:
        logger.error(f"API Failed to toggle template special status {template_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'خطا در تغییر وضعیت.'}), 500

@admin_bp.route('/api/templates/set_server_type/<int:template_id>', methods=['POST']) # ✅ این خط باید اضافه شود
@admin_required
def set_template_server_type_api(template_id):
    server_type = request.json.get('server_type')
    try:
        set_template_server_type_service(template_id, server_type)
        return jsonify({'success': True, 'message': 'نوع سرور کانفیگ به‌روز شد.'})
    except Exception as e:
        return jsonify({'success': False, 'message': 'خطا در به‌روزرسانی.'}), 500
    
# این کد را به انتهای فایل admin_routes.py اضافه کنید

@admin_bp.route('/api/templates/reset', methods=['POST'])
@admin_required
def reset_templates_api():
    """API برای ریست کردن تمام کانفیگ‌ها."""
    try:
        reset_all_templates()
        return jsonify({'success': True, 'message': 'تمام کانفیGها با موفقیت حذف و شمارنده ریست شد.'})
    except Exception as e:
        logger.error(f"API Failed to reset templates: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'خطا در عملیات ریست.'}), 500
    
@admin_bp.route('/marzban-mapping')
@admin_required
def marzban_mapping_page():
    mappings = get_marzban_mappings_service()
    return render_template('admin_marzban_mapping.html', mappings=mappings, is_admin=True)

@admin_bp.route('/marzban-mapping/add', methods=['POST'])
@admin_required
def add_marzban_mapping_route():
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
    hiddify_uuid = request.form.get('hiddify_uuid')
    success, message = delete_marzban_mapping_service(hiddify_uuid)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')
    return redirect(url_for('admin.marzban_mapping_page'))