import logging
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from .bot_instance import bot
from .config import ADMIN_IDS, TUTORIAL_LINKS, ADMIN_SUPPORT_CONTACT
from . import combined_handler
from .database import db
from .user_formatters import fmt_inline_result, fmt_smart_list_inline_result, fmt_service_plans
from .admin_formatters import fmt_card_info_inline
from .utils import load_service_plans, escape_markdown
from .language import get_string

logger = logging.getLogger(__name__)

def register_inline_handlers(b):
    """
    هندلر اصلی را برای کوئری‌های inline ثبت می‌کند.
    """
    global bot
    bot = b

    @bot.inline_handler(lambda query: True) # به تمام کاربران (ادمین و عادی) پاسخ می‌دهد
    def handle_inline_query(inline_query: types.InlineQuery):
        user_id = inline_query.from_user.id
        
        # بر اساس ادمین بودن یا نبودن کاربر، هندلر مناسب فراخوانی می‌شود
        if user_id in ADMIN_IDS:
            handle_admin_inline_query(inline_query)
        else:
            handle_user_inline_query(inline_query)


def handle_user_inline_query(inline_query: types.InlineQuery):
    """
    پردازش کوئری‌های inline برای کاربران عادی.
    """
    user_id = inline_query.from_user.id
    query = inline_query.query.strip().lower()
    results = []
    lang_code = db.get_user_language(user_id)
    user_uuids = db.uuids(user_id)

    try:
        # 1. نمایش وضعیت سریع اکانت (وقتی کاربر چیزی تایپ نکرده)
        if not query and user_uuids:
            for i, u_row in enumerate(user_uuids[:5]): # نمایش حداکثر ۵ اکانت
                info = combined_handler.get_combined_user_info(u_row['uuid'])
                if info:
                    formatted_text, parse_mode = fmt_inline_result(info)
                    result = types.InlineQueryResultArticle(
                        id=f"status_{i}",
                        title=f"📊 وضعیت اکانت: {info.get('name', 'ناشناس')}",
                        description="برای ارسال کارت وضعیت در چت کلیک کنید.",
                        input_message_content=types.InputTextMessageContent(
                            message_text=formatted_text,
                            parse_mode=parse_mode
                        )
                    )
                    results.append(result)
        
        # 2. دریافت سریع لینک‌های اشتراک
        elif query in ["link", "links", "لینک"] and user_uuids:
            user_uuid = user_uuids[0]['uuid']
            WEBAPP_BASE_URL = "https://panel.cloudvibe.ir"
            
            normal_link = f"{WEBAPP_BASE_URL}/user/sub/{user_uuid}"
            b64_link = f"{WEBAPP_BASE_URL}/user/sub/b64/{user_uuid}"

            results.append(types.InlineQueryResultArticle(
                id='send_normal_link',
                title="🔗 ارسال لینک Normal",
                description="برای ارسال لینک قابل کپی در چت کلیک کنید.",
                input_message_content=types.InputTextMessageContent(f"`{escape_markdown(normal_link)}`", parse_mode="MarkdownV2")
            ))
            results.append(types.InlineQueryResultArticle(
                id='send_b64_link',
                title="🔗 ارسال لینک Base64",
                description="برای ارسال لینک قابل کپی در چت کلیک کنید.",
                input_message_content=types.InputTextMessageContent(f"`{escape_markdown(b64_link)}`", parse_mode="MarkdownV2")
            ))

        # 3. ارسال آموزش و راهنما
        elif query in ["help", "راهنما", "آموزش"]:
            for os_key, os_name in [('android', 'اندروید'), ('windows', 'ویندوز'), ('ios', 'iOS')]:
                tutorial_links = TUTORIAL_LINKS.get(os_key, {})
                if tutorial_links:
                    message_lines = [f"📚 *راهنمای اتصال در {escape_markdown(os_name)}*"]
                    for app_key, link in tutorial_links.items():
                        app_name_raw = get_string(f"app_{app_key}", lang_code)
                        app_name = app_name_raw.replace('(پیشنهادی)', '').replace('(پولی)', '').strip()
                        message_lines.append(f" `•` [{escape_markdown(app_name)}]({link})")
                    
                    results.append(types.InlineQueryResultArticle(
                        id=f'help_{os_key}',
                        title=f"📚 راهنمای اتصال در {os_name}",
                        description=f"برای ارسال لینک‌های آموزشی {os_name} کلیک کنید.",
                        input_message_content=types.InputTextMessageContent(
                            message_text="\n".join(message_lines),
                            parse_mode="MarkdownV2",
                            disable_web_page_preview=True
                        )
                    ))

        # 4. نمایش و انتخاب سرویس‌ها برای خرید
        elif query in ["buy", "خرید", "سرویس", "تمدید", "plans"]:
            all_plans = load_service_plans()
            if all_plans:
                for i, plan in enumerate(all_plans[:20]): # نمایش حداکثر ۲۰ پلن
                    plan_name = plan.get('name', 'پلن ناشناس')
                    price_formatted = "{:,.0f}".format(plan.get('price', 0))
                    duration = plan.get('duration', 'نامحدود')
                    
                    # ساخت متن پیام اصلی که پس از کلیک ارسال می‌شود
                    message_text = fmt_service_plans([plan], plan.get('type', ''), lang_code)
                    
                    # ساخت دکمه خرید
                    support_link = f"https://t.me/{ADMIN_SUPPORT_CONTACT.replace('@', '')}"
                    kb = InlineKeyboardMarkup()
                    kb.add(InlineKeyboardButton(f"🚀 خرید و مشاوره", url=support_link))

                    results.append(types.InlineQueryResultArticle(
                        id=f"plan_{i}",
                        title=f"🛒 {plan_name}",
                        description=f"قیمت: {price_formatted} تومان | مدت: {duration}",
                        input_message_content=types.InputTextMessageContent(
                            message_text=message_text,
                            parse_mode="MarkdownV2"
                        ),
                        reply_markup=kb
                    ))

        # اگر کاربر اکانتی نداشت، یک پیام راهنما نمایش داده می‌شود
        if not user_uuids and not query:
             results.append(types.InlineQueryResultArticle(
                id='no_account',
                title="شما هنوز اکانتی ثبت نکرده‌اید!",
                description="لطفاً ابتدا وارد ربات شده و اکانت خود را اضافه کنید.",
                input_message_content=types.InputTextMessageContent("برای استفاده از امکانات ربات، لطفاً ابتدا وارد ربات شده و اکانت خود را ثبت کنید.")
            ))

        bot.answer_inline_query(inline_query.id, results, cache_time=10)

    except Exception as e:
        logger.error(f"Error handling user inline query for user {user_id}: {e}", exc_info=True)


def handle_admin_inline_query(inline_query: types.InlineQuery):
    """
    پردازش کوئری‌های inline برای ادمین‌ها.
    """
    query = inline_query.query.strip().lower()
    lang_code = db.get_user_language(inline_query.from_user.id)
    results = []

    try:
        # کپی کردن لینک برای ارسال به کاربر
        if query.startswith("copy_link:"):
            parts = query.split(":", 2)
            link_type, uuid = parts[1], parts[2]
            WEBAPP_BASE_URL = "https://panel.cloudvibe.ir"
            
            link_to_copy = f"{WEBAPP_BASE_URL}/user/sub/{uuid}" if link_type == "normal" else f"{WEBAPP_BASE_URL}/user/sub/b64/{uuid}"
            
            result = types.InlineQueryResultArticle(
                id=f'copy_{link_type}_{uuid}',
                title=f"ارسال لینک {link_type.capitalize()} (قابل کپی)",
                input_message_content=types.InputTextMessageContent(f"`{escape_markdown(link_to_copy)}`", parse_mode="MarkdownV2")
            )
            bot.answer_inline_query(inline_query.id, [result], cache_time=1)
            return

        # دستورات کلیدی ادمین
        if query in ["کارت", "card"]:
            text, parse_mode = fmt_card_info_inline()
            results.append(types.InlineQueryResultArticle(
                id='send_card_info',
                title="💳 ارسال اطلاعات کارت",
                input_message_content=types.InputTextMessageContent(text, parse_mode=parse_mode)
            ))

        elif query in ["سرویس", "سرویسها", "services", "plans", "خرید", "buy", "تمدید"]:
            all_plans = load_service_plans()
            if all_plans:
                for i, plan in enumerate(all_plans[:20]):
                    plan_name = plan.get('name', 'پلن ناشناس')
                    price_formatted = "{:,.0f}".format(plan.get('price', 0))
                    duration = plan.get('duration', 'نامحدود')
                    message_text = fmt_service_plans([plan], plan.get('type', ''), lang_code)
                    support_link = f"https://t.me/{ADMIN_SUPPORT_CONTACT.replace('@', '')}"
                    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🚀 خرید و مشاوره", url=support_link))
                    results.append(types.InlineQueryResultArticle(
                        id=f"admin_plan_{i}",
                        title=f"🛒 {plan_name}",
                        description=f"قیمت: {price_formatted} تومان | مدت: {duration}",
                        input_message_content=types.InputTextMessageContent(message_text, parse_mode="MarkdownV2"),
                        reply_markup=kb
                    ))
        
        # اگر کوئری خالی باشد، لیست‌های هوشمند ادمین نمایش داده می‌شود
        elif not query:
            all_users = combined_handler.get_all_users_combined()
            expiring_soon_users = [u for u in all_users if u.get('expire') is not None and 0 <= u['expire'] <= 3]
            expiring_soon_users.sort(key=lambda u: u.get('expire', 99))
            if expiring_soon_users:
                list_text, parse_mode = fmt_smart_list_inline_result(expiring_soon_users, "کاربران در آستانه انقضا (۳ روز)")
                description = ", ".join([u.get('name', 'N/A') for u in expiring_soon_users[:3]])
                results.append(types.InlineQueryResultArticle(
                    id='smart_list_expiring', 
                    title="⚠️ کاربران در آستانه انقضا", 
                    description=description, 
                    input_message_content=types.InputTextMessageContent(message_text=list_text, parse_mode=parse_mode)
                ))

                top_consumers = sorted(all_users, key=lambda u: u.get('current_usage_GB', 0), reverse=True)
                if top_consumers:
                    list_text, parse_mode = fmt_smart_list_inline_result(top_consumers[:5], "پرمصرف‌ترین کاربران")
                    description = ", ".join([u.get('name', 'N/A') for u in top_consumers[:3]])
                    results.append(types.InlineQueryResultArticle(
                        id='smart_list_top_consumers',
                        title="🏆 پرمصرف‌ترین کاربران",
                        description=description,
                        input_message_content=types.InputTextMessageContent(message_text=list_text, parse_mode=parse_mode)))
        else:
            found_users = combined_handler.search_user(query)
            for i, user in enumerate(found_users[:10]):
                formatted_text, parse_mode = fmt_inline_result(user)
                
                keyboard = InlineKeyboardMarkup(row_width=2)
                normal_switch_query = f"copy_link:normal:{user.get('uuid', '')}"
                b64_switch_query = f"copy_link:b64:{user.get('uuid', '')}"
                
                keyboard.add(
                    InlineKeyboardButton(text="📋 Normal", switch_inline_query_current_chat=normal_switch_query),
                    InlineKeyboardButton(text="📋 Base64", switch_inline_query_current_chat=b64_switch_query)
                )
                
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
        logger.error(f"Error handling admin inline query: {e}", exc_info=True)