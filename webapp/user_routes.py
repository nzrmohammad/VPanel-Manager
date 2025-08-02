from flask import Blueprint, render_template, abort, request, Response, url_for, flash, redirect, session, jsonify
from bot.utils import load_json_file, generate_user_subscription_configs, to_shamsi
from bot.settings_manager import settings
from bot.database import db
from .user_service import user_service
import base64
import urllib.parse
import logging
from bot.settings_manager import settings
from datetime import datetime, timedelta


logger = logging.getLogger(__name__)
user_bp = Blueprint('user', __name__, url_prefix='/user')

@user_bp.context_processor
def inject_uuid_for_user_pages():
    uuid = request.view_args.get('uuid')
    if uuid:
        return dict(uuid=uuid)
    return {}

# # <<<<<<<<<<<<<<<< شروع بخش امنیتی >>>>>>>>>>>>>>>>
# @user_bp.before_request
# def require_login():
#     # اگر کاربر وارد نشده بود، او را به صفحه ورود هدایت کن
#     if 'uuid' not in session:
#         return redirect(url_for('auth.login'))
    
#     # برای امنیت بیشتر، چک می‌کنیم UUID در URL با UUID ذخیره شده در سشن یکی باشد
#     # این کار جلوی دسترسی یک کاربر به داشبورد کاربر دیگر را می‌گیرد
#     if request.view_args and 'uuid' in request.view_args:
#         if request.view_args['uuid'] != session.get('uuid'):
#             # اگر یکی نبود، او را از سیستم خارج کرده و به صفحه ورود می‌فرستیم
#             session.pop('uuid', None)
#             flash("برای دسترسی به این صفحه، لطفاً با UUID خودتان وارد شوید.", "error")
#             return redirect(url_for('auth.login'))
# # <<<<<<<<<<<<<<<< پایان بخش امنیتی >>>>>>>>>>>>>>>>

@user_bp.route('/<string:uuid>')
def user_dashboard(uuid):
    user_data = user_service.get_processed_user_data(uuid)
    if not user_data:
        abort(404, "کاربر یافت نشد")
    return render_template('user_dashboard.html', user=user_data)

# <<<<<<<<<<<<<<<< روت جدید برای صفحه پرداخت‌ها >>>>>>>>>>>>>>>>
@user_bp.route('/<string:uuid>/payments')
def payment_history_page(uuid):
    user_data = user_service.get_processed_user_data(uuid)
    if not user_data:
        abort(404, "کاربر یافت نشد")
    
    # تبدیل تاریخ‌های میلادی به شمسی برای نمایش
    for payment in user_data.get("payment_history", []):
        payment['shamsi_date'] = to_shamsi(payment['payment_date'], include_time=True)
        
    return render_template('user_payment_history.html', user=user_data)
# <<<<<<<<<<<<<<<< پایان بخش جدید >>>>>>>>>>>>>>>>

@user_bp.route('/sub/<string:uuid>')
def serve_normal_subscription(uuid):
    from bot import combined_handler
    configs = generate_user_subscription_configs(uuid)
    if not configs:
        abort(404, "کانفیگ یافت نشد")
    
    subscription_content = "\n".join(configs)
    
    # ✅ START: افزودن هدرها
    response = Response(subscription_content, mimetype='text/plain; charset=utf-8')
    
    user_record = db.get_user_uuid_record(uuid)
    user_info = combined_handler.get_combined_user_info(uuid)

    if user_record and user_info:
        # هدر برای نام پروفایل
        profile_title = user_record.get('name', 'CloudVibe')
        # این روش انکودینگ برای پشتیبانی از کاراکترهای فارسی در هدر ضروری است
        response.headers['Profile-Title'] = profile_title.encode('utf-8').decode('latin-1')
        
        # هدر برای به‌روزرسانی خودکار (هر ۲۴ ساعت)
        response.headers['Profile-Update-Interval'] = '24'
        
        # هدر برای نمایش اطلاعات مصرف و انقضا در کلاینت
        usage = user_info.get('usage', {})
        total_usage_bytes = int(usage.get('total_usage_GB', 0) * (1024**3))
        data_limit_bytes = int(usage.get('data_limit_GB', 0) * (1024**3))
        expire_days = user_info.get('expire')
        expire_timestamp = 0
        if expire_days is not None:
            expire_timestamp = int((datetime.now() + timedelta(days=expire_days)).timestamp())

        userinfo_header = f"upload={total_usage_bytes}; download=0; total={data_limit_bytes}; expire={expire_timestamp}"
        response.headers['Subscription-Userinfo'] = userinfo_header

    return response
    # ✅ END: پایان تغییرات

@user_bp.route('/sub/b64/<string:uuid>')
def serve_base64_subscription(uuid):
    from bot import combined_handler
    configs = generate_user_subscription_configs(uuid)
    if not configs:
        abort(404, "کانفیگ یافت نشد")
        
    subscription_content = "\n".join(configs)
    encoded_content = base64.b64encode(subscription_content.encode('utf-8')).decode('utf-8')

    # ✅ START: افزودن هدرها (مشابه تابع قبلی)
    response = Response(encoded_content, mimetype='text/plain; charset=utf-8')
    
    user_record = db.get_user_uuid_record(uuid)
    user_info = combined_handler.get_combined_user_info(uuid)

    if user_record and user_info:
        profile_title = user_record.get('name', 'CloudVibe')
        response.headers['Profile-Title'] = profile_title.encode('utf-8').decode('latin-1')
        response.headers['Profile-Update-Interval'] = '24'
        
        usage = user_info.get('usage', {})
        total_usage_bytes = int(usage.get('total_usage_GB', 0) * (1024**3))
        data_limit_bytes = int(usage.get('data_limit_GB', 0) * (1024**3))
        expire_days = user_info.get('expire')
        expire_timestamp = 0
        if expire_days is not None:
            expire_timestamp = int((datetime.now() + timedelta(days=expire_days)).timestamp())

        userinfo_header = f"upload={total_usage_bytes}; download=0; total={data_limit_bytes}; expire={expire_timestamp}"
        response.headers['Subscription-Userinfo'] = userinfo_header
        
    return response
    # ✅ END: پایان تغییرات
@user_bp.route('/<string:uuid>/links')
def subscription_links_page(uuid):
    raw_configs = generate_user_subscription_configs(uuid)
    individual_configs = []
    
    if raw_configs:
        for config_str in raw_configs:
            try:
                name_part = config_str.split('#', 1)[1]
                config_name = urllib.parse.unquote(name_part, encoding='utf-8')
            except IndexError:
                config_name = "کانفیگ بدون نام"
            
            detected_code = None
            name_lower = config_name.lower()
            if any(c in name_lower for c in ['(de)', '[de]', 'de ']): detected_code = 'de'
            elif any(c in name_lower for c in ['(fr)', '[fr]', 'fr ']): detected_code = 'fr'
            
            individual_configs.append({"name": config_name, "url": config_str, "country_code": detected_code})

    subscription_links = [
        {"type": "همه کانفیگ‌ها (Normal)", "url": url_for('user.serve_normal_subscription', uuid=uuid, _external=True, _scheme='https')},
        {"type": "همه کانفیگ‌ها (Base64)", "url": url_for('user.serve_base64_subscription', uuid=uuid, _external=True, _scheme='https')}
    ]
    
    user_data = {"username": "کاربر"}
    return render_template('subscription_links_page.html', user=user_data, subscription_links=subscription_links, individual_configs=individual_configs)

@user_bp.route('/<string:uuid>/usage')
def usage_chart_page(uuid):
    user_data = user_service.get_processed_user_data(uuid)
    if not user_data:
        abort(404, "کاربر یافت نشد")
    
    chart_data = {"series": [], "categories": []}
    try:
        uuid_id = db.get_uuid_id_by_uuid(uuid)
        if uuid_id:
            h_usage = db.get_panel_usage_in_intervals(uuid_id, 'hiddify_usage_gb')
            m_usage = db.get_panel_usage_in_intervals(uuid_id, 'marzban_usage_gb')
            h_data = [float(h_usage.get(h, 0)) for h in [24, 12, 6, 3]]
            m_data = [float(m_usage.get(h, 0)) for h in [24, 12, 6, 3]]
            chart_data = {
                "series": [{"name": "Hiddify (GB)", "data": h_data}, {"name": "Marzban (GB)", "data": m_data}],
                "categories": ["در ۲۴ ساعت گذشته", "در ۱۲ ساعت گذشته", "در ۶ ساعت گذشته", "در ۳ ساعت گذشته"]
            }
    except Exception as e:
        logger.error(f"خطا در دریافت داده‌های نمودار: {e}")
    
    return render_template('usage_chart_page.html', user=user_data, usage_data=chart_data)

@user_bp.route('/<string:uuid>/buy')
def buy_service_page(uuid):
    all_plans = load_json_file('plans.json')
    support_link = f"https://t.me/{settings.get('admin_support_contact', "Nzrmohammad").replace('@', '')}"
    
    combined_plans, dedicated_plans = [], []
    if isinstance(all_plans, list):
        for plan in all_plans:
            if plan.get('type') == 'combined': combined_plans.append(plan)
            else: dedicated_plans.append(plan)
    
    user_data = {"username": "کاربر"}
    return render_template('buy_service_page.html', user=user_data, combined_plans=combined_plans, dedicated_plans=dedicated_plans, support_link=support_link)

@user_bp.route('/<string:uuid>/tutorials')
def tutorials_page(uuid):
    user_data = user_service.get_processed_user_data(uuid)
    if not user_data:
        abort(404, "کاربر یافت نشد")
    
    return render_template('tutorials_page.html', user=user_data)

@user_bp.route('/<string:uuid>/profile', methods=['GET', 'POST'])
def user_profile_page(uuid):
    if request.method == 'POST':
        success, message = user_service.update_user_profile(uuid, request.form)
        if success:
            flash(message, 'success')
        else:
            flash(message, 'error')
        return redirect(url_for('user.user_profile_page', uuid=uuid))

    # برای متد GET
    user_data = user_service.get_processed_user_data(uuid)
    if not user_data:
        abort(404, "کاربر یافت نشد")
    
    uuid_record = db.get_user_uuid_record(uuid)
    user_settings = db.get_user_settings(uuid_record['user_id']) if uuid_record else {}
    
    # <<<<<<<<<<<<<<<< شروع بخش اصلاح شده >>>>>>>>>>>>>>>>
    # اطلاعات پایه کاربر (شامل تاریخ تولد) را نیز دریافت کرده و به صفحه ارسال می‌کنیم
    user_basic = db.user(uuid_record.get('user_id')) if uuid_record else {}
    
    return render_template('user_profile.html', user=user_data, settings=user_settings, user_basic=user_basic)
    # <<<<<<<<<<<<<<<< پایان بخش اصلاح شده >>>>>>>>>>>>>>>>