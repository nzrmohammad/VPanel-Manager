# یک فایل جدید به نام bot/bot_api_routes.py بسازید

from flask import Blueprint, jsonify
from .bot_instance import bot  # فرض بر اینکه نمونه bot در اینجا قابل دسترسی است

# این یک Blueprint جدید است که می‌توانید به اپلیکیشن Flask خود اضافه کنید
bot_api_bp = Blueprint('bot_api', __name__, url_prefix='/api/bot')

@bot_api_bp.route('/reschedule', methods=['POST'])
def reschedule_bot_jobs():
    try:
        if bot and hasattr(bot, 'scheduler') and hasattr(bot.scheduler, 'reschedule_jobs'):
            bot.scheduler.reschedule_jobs()
            return jsonify({"success": True, "message": "Scheduler reloaded successfully."}), 200
        return jsonify({"success": False, "message": "Scheduler not found or bot not ready."}), 500
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500