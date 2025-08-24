from flask import Blueprint, render_template, abort, request, Response, url_for, flash, redirect, session, jsonify
from bot.utils import load_json_file, generate_user_subscription_configs, to_shamsi
from bot.database import db
from .user_service import user_service
import base64
import urllib.parse
import logging
from datetime import datetime, timedelta
from bot.config import ADMIN_SUPPORT_CONTACT
import os
import json

logger = logging.getLogger(__name__)
user_bp = Blueprint('user', __name__, url_prefix='/user')

@user_bp.context_processor
def inject_uuid_for_user_pages():
    uuid = request.view_args.get('uuid')
    if uuid:
        return dict(uuid=uuid)
    return {}

@user_bp.route('/<string:uuid>')
def user_dashboard(uuid):
    user_data = user_service.get_processed_user_data(uuid)
    if not user_data:
        abort(404, "کاربر یافت نشد")
    return render_template('user_dashboard.html', user=user_data)

@user_bp.route('/<string:uuid>/payments')
def payment_history_page(uuid):
    user_data = user_service.get_processed_user_data(uuid)
    if not user_data:
        abort(404, "کاربر یافت نشد")

    payment_history_list = user_data.get("payment_history", [])
    
    for payment in payment_history_list:
        payment['shamsi_date'] = to_shamsi(payment['payment_date'], include_time=True)
    
    return render_template('user_payment_history.html', user=user_data)


@user_bp.route('/sub/<string:uuid>')
def serve_normal_subscription(uuid):
    from bot import combined_handler
    user_record = db.get_user_uuid_record(uuid)
    if not user_record or not user_record.get('user_id'):
        abort(404, "کاربر یا شناسه کاربری یافت نشد")
        
    user_id = user_record['user_id']
    configs = generate_user_subscription_configs(uuid, user_id)
    if not configs:
        abort(404, "کانفیگ یافت نشد")
    
    subscription_content = "\n".join(configs)
    
    response = Response(subscription_content, mimetype='text/plain; charset=utf-8')
    
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

@user_bp.route('/sub/b64/<string:uuid>')
def serve_base64_subscription(uuid):
    from bot import combined_handler
    user_record = db.get_user_uuid_record(uuid)
    if not user_record or not user_record.get('user_id'):
        abort(404, "کاربر یا شناسه کاربری یافت نشد")

    user_id = user_record['user_id']
    configs = generate_user_subscription_configs(uuid, user_id)
    if not configs:
        abort(404, "کانفیگ یافت نشد")
        
    subscription_content = "\n".join(configs)
    encoded_content = base64.b64encode(subscription_content.encode('utf-8')).decode('utf-8')

    response = Response(encoded_content, mimetype='text/plain; charset=utf-8')
    
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

@user_bp.route('/<string:uuid>/links')
def subscription_links_page(uuid):
    user_record = db.get_user_uuid_record(uuid)
    if not user_record or not user_record.get('user_id'):
        abort(404, "کاربر یا شناسه کاربری یافت نشد")
    
    user_id = user_record['user_id']
    raw_configs = generate_user_subscription_configs(uuid, user_id)
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
            elif any(c in name_lower for c in ['(tr)', '[tr]', 'tr ']): detected_code = 'tr'

            
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
    
    chart_data = {
        "series": [],
        "categories": ["در ۲۴ ساعت گذشته", "در ۱۲ ساعت گذشته", "در ۶ ساعت گذشته", "در ۳ ساعت گذشته"],
        "pie_series": [],
        "pie_labels": []
    }
    try:
        uuid_id = db.get_uuid_id_by_uuid(uuid)
        if uuid_id and user_data.get('breakdown'):
            for panel_name, panel_details in user_data['breakdown'].items():
                panel_type = panel_details.get('type')
                usage_column = f"{panel_type}_usage_gb"
                
                # داده‌های نمودار میله‌ای مصرف روزانه
                usage_intervals = db.get_panel_usage_in_intervals(uuid_id, usage_column)
                panel_data = [float(usage_intervals.get(h, 0)) for h in [24, 12, 6, 3]]
                chart_data["series"].append({"name": panel_name, "data": panel_data})

                # داده‌های نمودارهای دایره‌ای
                panel_usage = panel_details.get('data', {}).get('current_usage_GB', 0)
                chart_data["pie_series"].append(panel_usage)
                chart_data["pie_labels"].append(panel_name)

    except Exception as e:
        logger.error(f"خطا در دریافت داده‌های نمودار برای {uuid}: {e}", exc_info=True)
    
    return render_template('usage_chart_page.html', user=user_data, usage_data=chart_data)

@user_bp.route('/<string:uuid>/buy')
def buy_service_page(uuid):
    all_plans = load_json_file('plans.json')
    support_link = f"https://t.me/{ADMIN_SUPPORT_CONTACT.replace('@', '')}"
    
    combined_plans, dedicated_plans = [], []
    if isinstance(all_plans, list):
        for plan in all_plans:
            if plan.get('type') == 'combined':
                combined_plans.append(plan)
            else:
                dedicated_plans.append(plan)
    
    # دریافت اطلاعات کامل کاربر فعلی
    current_user_data = user_service.get_processed_user_data(uuid)
    if not current_user_data:
        abort(404, "کاربر یافت نشد")

    recommended_plan = current_user_data.get('recommended_plan')
    actual_usage = current_user_data.get('actual_last_30_days_usage')
    
    return render_template('buy_service_page.html', 
                           user=current_user_data, # ارسال اطلاعات کامل کاربر
                           combined_plans=combined_plans, 
                           dedicated_plans=dedicated_plans, 
                           support_link=support_link,
                           recommended_plan=recommended_plan,
                           actual_last_30_days_usage=actual_usage)

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

    user_data = user_service.get_processed_user_data(uuid)
    if not user_data:
        abort(404, "کاربر یافت نشد")
    
    uuid_record = db.get_user_uuid_record(uuid)
    if not uuid_record or not uuid_record.get('user_id'):
        abort(404, "رکورد کاربر یافت نشد")

    user_id = uuid_record['user_id']
    user_settings = db.get_user_settings(user_id)
    user_basic = db.user(user_id) or {}
    
    return render_template('user_profile.html', user=user_data, settings=user_settings, user_basic=user_basic)

@user_bp.route('/<string:uuid>/serverless.json')
def serve_serverless_config(uuid):
    """
    این روت، فایل قالب کانفیگ سرورلس را خوانده، UUID کاربر را در آن جایگزین کرده
    و به عنوان یک فایل JSON قابل دانلود به کاربر ارائه می‌دهد.
    """
    user_record = db.get_user_uuid_record(uuid)
    # اگر کاربر فعال نباشد یا وجود نداشته باشد، دسترسی داده نمی‌شود
    if not user_record or not user_record.get('is_active'):
        abort(404, "کاربر یافت نشد یا غیرفعال است")

    try:
        # خواندن فایل قالب
        template_path = os.path.join(os.path.dirname(__file__), '..', 'bot', 'serverless_config.json')
        with open(template_path, 'r', encoding='utf-8') as f:
            config_template_str = f.read()

        # جایگذاری UUID و نام کاربر
        user_name = user_record.get('name', 'Serverless')
        user_config_str = config_template_str.replace("{new_uuid}", uuid)
        
        # تبدیل رشته به آبجکت JSON برای تغییر نام
        config_data = json.loads(user_config_str)
        
        # تغییر نام (remark) در کانفیگ
        # این بخش ممکن است بسته به ساختار دقیق فایل شما نیاز به تغییر داشته باشد
        if 'outbounds' in config_data and len(config_data['outbounds']) > 0:
             # فرض می‌کنیم اولین outbound همان کانفیگ اصلی است
            config_data['outbounds'][0]['remark'] = user_name

        final_config_str = json.dumps(config_data, indent=2)

        return Response(
            final_config_str,
            mimetype='application/json',
            headers={'Content-Disposition': f'attachment;filename={user_name}.json'}
        )

    except FileNotFoundError:
        logger.error("serverless_config.json template not found.")
        abort(500, "قالب کانفیگ سرورلس یافت نشد.")
    except Exception as e:
        logger.error(f"Error serving serverless config for {uuid}: {e}", exc_info=True)
        abort(500, "خطا در ساخت کانفیگ.")