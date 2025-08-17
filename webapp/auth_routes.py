from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort
from bot.database import db
from bot.config import ADMIN_SECRET_KEY
from .services import get_server_status # Add this import at the top
import jdatetime # Add this import
import pytz
from datetime import datetime

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_type = request.form.get('login_type')
        session.clear()
        if login_type == 'user':
            uuid = request.form.get('uuid')
            if not uuid:
                flash("لطفاً UUID خود را وارد کنید.", "error")
                return redirect(url_for('auth.login'))
            user_record = db.get_user_uuid_record(uuid)
            if user_record:
                session['uuid'] = uuid
                return redirect(url_for('user.user_dashboard', uuid=uuid))
            else:
                flash("UUID وارد شده معتبر نیست.", "error")
                return redirect(url_for('auth.login'))
        elif login_type == 'admin':
            password = request.form.get('password')
            if password == ADMIN_SECRET_KEY:
                session['is_admin'] = True
                return redirect(url_for('admin.admin_dashboard'))
            else:
                flash("رمز عبور ادمین اشتباه است.", "error")
                return redirect(url_for('auth.login'))
        else:
            flash("نوع ورود نامعتبر است.", "error")
            return redirect(url_for('auth.login'))
    return render_template('login.html')


@auth_bp.route('/login/token/<string:token>')
def login_with_token(token):
    session.clear()
    user_uuid = db.validate_login_token(token)
    
    if user_uuid:
        session['uuid'] = user_uuid
        flash("شما با موفقیت وارد شدید.", "success")
        return redirect(url_for('user.user_dashboard', uuid=user_uuid))
    else:
        flash("لینک ورود نامعتبر یا منقضی شده است. لطفاً دوباره تلاش کنید.", "error")
        return redirect(url_for('auth.login'))

@auth_bp.route('/status')
def status_page():
    server_statuses = get_server_status()
    now_tehran = datetime.now(pytz.timezone("Asia/Tehran"))
    last_updated = jdatetime.datetime.fromgregorian(datetime=now_tehran).strftime("%Y/%m/%d - %H:%M:%S")

    return render_template('status_page.html', statuses=server_statuses, last_updated=last_updated)

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash("شما با موفقیت خارج شدید.", 'success')
    return redirect(url_for('auth.login'))

@auth_bp.route('/app/redirect')
def app_redirect():
    """
    یک صفحه وب واسط برای ریدایرکت کردن کاربر به لینک‌های هوشمند (deep links) اپلیکیشن‌ها.
    """
    redirect_url = request.args.get('url')
    app_name = request.args.get('app_name', 'اپلیکیشن') # دریافت نام اپلیکیشن

    if not redirect_url:
        abort(400, "URL parameter is missing.")
    
    allowed_protocols = ['v2rayng://', 'hiddify://', 'hap://', 'happ://', 'streisand://']
    if not any(redirect_url.startswith(p) for p in allowed_protocols):
        abort(400, "Unsupported URL protocol.")

    # ارسال نام اپلیکیشن به قالب
    return render_template('app_redirect.html', redirect_url=redirect_url, app_name=app_name)