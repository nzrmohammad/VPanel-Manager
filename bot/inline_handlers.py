# مسیر فایل: bot/inline_handlers.py

import logging
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from .bot_instance import bot
from .config import ADMIN_IDS
from .combined_handler import get_all_users_combined, search_user
from .user_formatters import fmt_inline_result, fmt_smart_list_inline_result

logger = logging.getLogger(__name__)

def register_inline_handlers(b):
    global bot
    bot = b

    @bot.inline_handler(lambda query: query.from_user.id in ADMIN_IDS)
    def handle_admin_inline_query(inline_query: types.InlineQuery):
        query = inline_query.query.strip()

        try:
            if query.startswith("copy_link:"):
                parts = query.split(":", 2)
                link_type = parts[1]
                uuid = parts[2]
                WEBAPP_BASE_URL = "https://panel.cloudvibe.ir" # در صورت نیاز این آدرس را ویرایش کنید
                
                link_to_copy = ""
                if link_type == "normal":
                    link_to_copy = f"{WEBAPP_BASE_URL}/user/sub/{uuid}"
                elif link_type == "b64":
                    link_to_copy = f"{WEBAPP_BASE_URL}/user/sub/b64/{uuid}"
                
                # --- ✨ تغییر اصلی: قرار دادن لینک داخل بک‌تیک برای کپی شدن ---
                message_content = f"`{link_to_copy}`"
                
                result = types.InlineQueryResultArticle(
                    id=f'copy_{link_type}_{uuid}',
                    title=f"ارسال لینک {link_type.capitalize()} (قابل کپی)",
                    description="برای ارسال لینک در چت کلیک کنید.",
                    input_message_content=types.InputTextMessageContent(
                        message_text=message_content,
                        parse_mode="MarkdownV2" # استفاده از Markdown برای فعال شدن بک‌تیک
                    )
                )
                bot.answer_inline_query(inline_query.id, [result], cache_time=1)
                return

            results = []
            if not query:
                # منطق لیست‌های هوشمند (بدون تغییر باقی می‌ماند)
                all_users = get_all_users_combined()
                expiring_soon_users = [u for u in all_users if u.get('expire') is not None and 0 <= u['expire'] <= 3]
                expiring_soon_users.sort(key=lambda u: u.get('expire', 99))
                if expiring_soon_users:
                    list_text, parse_mode = fmt_smart_list_inline_result(expiring_soon_users, "کاربران در آستانه انقضا (۳ روز)")
                    description = ", ".join([u.get('name', 'N/A') for u in expiring_soon_users[:3]])
                    results.append(types.InlineQueryResultArticle(id='smart_list_expiring', title="⚠️ کاربران در آستانه انقضا", description=description, input_message_content=types.InputTextMessageContent(message_text=list_text, parse_mode=parse_mode)))
                
                top_consumers = sorted(all_users, key=lambda u: u.get('current_usage_GB', 0), reverse=True)
                if top_consumers:
                    list_text, parse_mode = fmt_smart_list_inline_result(top_consumers[:5], "پرمصرف‌ترین کاربران")
                    description = ", ".join([u.get('name', 'N/A') for u in top_consumers[:3]])
                    results.append(types.InlineQueryResultArticle(id='smart_list_top_consumers', title="🏆 پرمصرف‌ترین کاربران", description=description, input_message_content=types.InputTextMessageContent(message_text=list_text, parse_mode=parse_mode)))
            
            else:
                # منطق جستجوی عادی کاربر (بدون تغییر)
                found_users = search_user(query)
                for i, user in enumerate(found_users[:10]):
                    keyboard = InlineKeyboardMarkup(row_width=2)
                    normal_switch_query = f"copy_link:normal:{user.get('uuid', '')}"
                    b64_switch_query = f"copy_link:b64:{user.get('uuid', '')}"
                    
                    keyboard.add(
                        InlineKeyboardButton(text="📋 Normal", switch_inline_query_current_chat=normal_switch_query),
                        InlineKeyboardButton(text="📋 Base64", switch_inline_query_current_chat=b64_switch_query)
                    )
                    
                    formatted_text, parse_mode = fmt_inline_result(user)
                    result = types.InlineQueryResultArticle(
                        id=str(i),
                        title=f"👤 {user.get('name', 'کاربر ناشناس')}",
                        description=f"UUID: {user.get('uuid', 'N/A')}",
                        reply_markup=keyboard,
                        input_message_content=types.InputTextMessageContent(message_text=formatted_text, parse_mode=parse_mode)
                    )
                    results.append(result)
            
            bot.answer_inline_query(inline_query.id, results, cache_time=5)

        except Exception as e:
            logger.error(f"Error handling inline query: {e}", exc_info=True)