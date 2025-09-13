import logging
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from cachetools import TTLCache, cached

from .bot_instance import bot
from .config import ADMIN_IDS, TUTORIAL_LINKS, ADMIN_SUPPORT_CONTACT
from . import combined_handler
from .database import db
from .user_formatters import fmt_inline_result, fmt_smart_list_inline_result, fmt_service_plans
from .admin_formatters import fmt_card_info_inline
from .utils import load_service_plans, escape_markdown
from .language import get_string

logger = logging.getLogger(__name__)

# کش برای جلوگیری از محاسبات تکراری در کوئری‌های پشت سر هم
inline_cache = TTLCache(maxsize=10, ttl=300) 

@cached(inline_cache)
def get_cached_smart_lists():
    """
    (Cached Function) نتایج لیست‌های هوشمند ادمین را محاسبه و برای ۵ دقیقه کش می‌کند.
    """
    logger.info("INLINE_CACHE: Recalculating smart lists for admin...")
    all_users = combined_handler.get_all_users_combined()
    expiring_soon = [u for u in all_users if u.get('expire') is not None and 0 <= u['expire'] <= 3]
    expiring_soon.sort(key=lambda u: u.get('expire', 99))
    top_consumers = sorted(all_users, key=lambda u: u.get('current_usage_GB', 0), reverse=True)
    return expiring_soon, top_consumers[:5]

def register_inline_handlers(b):
    """
    هندلر اصلی را برای کوئری‌های inline ثبت می‌کند.
    """
    global bot
    bot = b

    @bot.inline_handler(lambda query: True)
    def handle_inline_query(inline_query: types.InlineQuery):
        user_id = inline_query.from_user.id
        if user_id in ADMIN_IDS:
            handle_admin_inline_query(inline_query)
        else:
            handle_user_inline_query(inline_query)

def handle_user_inline_query(inline_query: types.InlineQuery):
    """
    (نسخه نهایی) پردازش کوئری‌های inline برای کاربران.
    اگر کوئری خالی باشد، تمام گزینه‌ها را به صورت یک لیست کامل و دسته‌بندی شده نمایش می‌دهد.
    """
    user_id = inline_query.from_user.id
    query = inline_query.query.strip().lower()
    results = []
    lang_code = db.get_user_language(user_id)
    user_uuids = db.uuids(user_id)

    try:
        if not query:
            if user_uuids:
                user_uuid = user_uuids[0]['uuid']
                
                # ۱. افزودن کارت وضعیت اکانت
                info = combined_handler.get_combined_user_info(user_uuid)
                if info:
                    formatted_text, parse_mode = fmt_inline_result(info)
                    results.append(types.InlineQueryResultArticle(
                        id="status_card",
                        title="📊 وضعیت سریع اکانت",
                        description="برای ارسال کارت وضعیت در چت کلیک کنید.",
                        input_message_content=types.InputTextMessageContent(message_text=formatted_text, parse_mode=parse_mode)
                    ))

                # ۲. افزودن لینک‌های اتصال به صورت مستقیم
                WEBAPP_BASE_URL = "https://panel.cloudvibe.ir" # آدرس وب‌اپ خود را وارد کنید
                normal_link = f"{WEBAPP_BASE_URL}/user/sub/{user_uuid}"
                b64_link = f"{WEBAPP_BASE_URL}/user/sub/b64/{user_uuid}"
                results.extend([
                    types.InlineQueryResultArticle(
                        id='send_normal_link', title="🔗 لینک Normal", description="برای ارسال لینک قابل کپی کلیک کنید.",
                        input_message_content=types.InputTextMessageContent(f"`{escape_markdown(normal_link)}`", parse_mode="MarkdownV2")
                    ),
                    types.InlineQueryResultArticle(
                        id='send_b64_link', title="🔗 لینک Base64 (iOS)", description="برای ارسال لینک قابل کپی کلیک کنید.",
                        input_message_content=types.InputTextMessageContent(f"`{escape_markdown(b64_link)}`", parse_mode="MarkdownV2")
                    )
                ])

                # ۳. افزودن لینک دعوت از دوستان
                bot_username = bot.get_me().username
                referral_code = db.get_or_create_referral_code(user_id)
                referral_link = f"https://t.me/{bot_username}?start={referral_code}"
                message_text_referral = (
                    f"🤝 *به جمع ما بپیوند\\!* 🤝\n\n"
                    f"از طریق لینک زیر در ربات عضو شو و پس از اولین خرید، هر دوی ما هدیه دریافت خواهیم کرد\\."
                )
                kb_referral = InlineKeyboardMarkup().add(
                    InlineKeyboardButton("🚀 شروع و دریافت هدیه", url=referral_link)
                )
                results.append(types.InlineQueryResultArticle(
                    id='send_referral_link',
                    title="🤝 دعوت از دوستان",
                    description="برای ارسال لینک معرفی خود در چت کلیک کنید.",
                    input_message_content=types.InputTextMessageContent(
                        message_text=message_text_referral, parse_mode="MarkdownV2"
                    ),
                    reply_markup=kb_referral
                ))

                # ۴. افزودن پلن‌های فروش با دسته‌بندی
                all_plans = load_service_plans()
                if all_plans:
                    combined_plans = [p for p in all_plans if p.get("type") == "combined"]
                    dedicated_plans = [p for p in all_plans if p.get("type") != "combined"]
                    support_link = f"https://t.me/{ADMIN_SUPPORT_CONTACT.replace('@', '')}"

                    # بخش پلن‌های ترکیبی
                    if combined_plans:
                        results.append(types.InlineQueryResultArticle(
                            id="header_combined", title="🚀 ----- سرویس‌های ترکیبی (پیشنهادی) -----",
                            input_message_content=types.InputTextMessageContent("لطفاً یک سرویس را برای مشاهده جزئیات انتخاب کنید.")
                        ))
                        for i, plan in enumerate(combined_plans):
                            results.append(types.InlineQueryResultArticle(
                                id=f"plan_combined_{i}", title=f"{plan.get('name', 'پلن ناشناس')}",
                                description=f"قیمت: {'{:,.0f}'.format(plan.get('price', 0))} تومان | مدت: {plan.get('duration', 'نامحدود')}",
                                input_message_content=types.InputTextMessageContent(fmt_service_plans([plan], 'combined', lang_code), parse_mode="MarkdownV2"),
                                reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🚀 خرید و مشاوره", url=support_link))
                            ))
                    
                    # بخش پلن‌های اختصاصی
                    if dedicated_plans:
                        results.append(types.InlineQueryResultArticle(
                            id="header_dedicated", title="🇩🇪🇫🇷🇹🇷 ----- پلن‌های اختصاصی -----",
                            input_message_content=types.InputTextMessageContent("لطفاً یک سرویس را برای مشاهده جزئیات انتخاب کنید.")
                        ))
                        for i, plan in enumerate(dedicated_plans):
                            results.append(types.InlineQueryResultArticle(
                                id=f"plan_dedicated_{i}", title=f"{plan.get('name', 'پلن ناشناس')}",
                                description=f"قیمت: {'{:,.0f}'.format(plan.get('price', 0))} تومان | مدت: {plan.get('duration', 'نامحدود')}",
                                input_message_content=types.InputTextMessageContent(fmt_service_plans([plan], plan.get('type'), lang_code), parse_mode="MarkdownV2"),
                                reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🚀 خرید و مشاوره", url=support_link))
                            ))
                
                # ۵. افزودن گزینه نهایی تماس با پشتیبانی
                results.append(types.InlineQueryResultArticle(
                    id="contact_support",
                    title="💬 خرید و مشاوره",
                    description="برای سوالات و خرید مستقیم با ادمین صحبت کنید.",
                    input_message_content=types.InputTextMessageContent(f"برای ارتباط با پشتیبانی و خرید سرویس روی دکمه زیر کلیک کنید."),
                    reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("💬 تماس با ادمین", url=support_link))
                ))
            else:
                results.append(types.InlineQueryResultArticle(
                    id='no_account', title="شما هنوز اکانتی ثبت نکرده‌اید!",
                    description="لطفاً ابتدا وارد ربات شده و اکانت خود را اضافه کنید.",
                    input_message_content=types.InputTextMessageContent("برای استفاده از امکانات ربات، لطفاً ابتدا وارد ربات شده و اکانت خود را ثبت کنید.")
                ))
            
            bot.answer_inline_query(inline_query.id, results[:50], cache_time=10)
            return

        bot.answer_inline_query(inline_query.id, results, cache_time=10)

    except Exception as e:
        logger.error(f"Error handling user inline query for user {user_id}: {e}", exc_info=True)


def handle_admin_inline_query(inline_query: types.InlineQuery):
    """
    پردازش کوئری‌های inline برای ادمین‌ها.
    """
    query = inline_query.query.strip().lower()
    results = []
    user_id = inline_query.from_user.id
    lang_code = db.get_user_language(user_id)

    try:
        if not query:
            # --- بخش ۱: لیست‌های هوشمند و ابزارهای ادمین (بدون تغییر) ---
            expiring_soon_users, top_consumers = get_cached_smart_lists()
            
            if expiring_soon_users:
                list_text, parse_mode = fmt_smart_list_inline_result(expiring_soon_users, "کاربران در آستانه انقضا (۳ روز)")
                results.append(types.InlineQueryResultArticle(
                    id='smart_list_expiring', title="⚠️ کاربران در آستانه انقضا", 
                    description=", ".join([u.get('name', 'N/A') for u in expiring_soon_users[:3]]), 
                    input_message_content=types.InputTextMessageContent(message_text=list_text, parse_mode=parse_mode)
                ))
            if top_consumers:
                list_text, parse_mode = fmt_smart_list_inline_result(top_consumers, "پرمصرف‌ترین کاربران")
                results.append(types.InlineQueryResultArticle(
                    id='smart_list_top_consumers', title="🏆 پرمصرف‌ترین کاربران", 
                    description=", ".join([u.get('name', 'N/A') for u in top_consumers[:3]]), 
                    input_message_content=types.InputTextMessageContent(message_text=list_text, parse_mode=parse_mode)
                ))

            text, parse_mode = fmt_card_info_inline()
            results.append(types.InlineQueryResultArticle(
                id='send_card_info', title="💳 ارسال اطلاعات کارت",
                input_message_content=types.InputTextMessageContent(text, parse_mode=parse_mode)
            ))
            
            results.append(types.InlineQueryResultArticle(
                id='menu_search', title="🔎 جستجوی کاربر", description="برای جستجو، شروع به تایپ نام یا UUID کاربر کنید...",
                input_message_content=types.InputTextMessageContent("برای جستجوی کاربر، نام یا UUID او را پس از آیدی ربات تایپ کنید.")
            ))

            # --- بخش ۲: افزودن گزینه‌های ارسال لیست پلن‌ها ---
            all_plans = load_service_plans()
            if all_plans:
                # پلن‌ها را بر اساس نوعشان دسته‌بندی می‌کنیم
                plans_by_type = {}
                for plan in all_plans:
                    plan_type = plan.get("type", "unknown")
                    if plan_type not in plans_by_type:
                        plans_by_type[plan_type] = []
                    plans_by_type[plan_type].append(plan)

                # یک دیکشنری برای تعریف عنوان و نوع هر دکمه
                type_map = {
                    "combined": ("🚀 ارسال پلن‌های ترکیبی", "combined"),
                    "germany": ("🇩🇪 ارسال پلن‌های آلمان", "germany"),
                    "france": ("🇫🇷 ارسال پلن‌های فرانسه", "france"),
                    "turkey": ("🇹🇷 ارسال پلن‌های ترکیه", "turkey"),
                    "usa": ("🇺🇸 ارسال پلن‌های آمریکا", "usa"),
                }

                for key, (title, plan_type) in type_map.items():
                    if plan_type in plans_by_type:
                        # متن کامل پلن‌های این دسته را با استفاده از فرمت‌کننده موجود می‌سازیم
                        category_text = fmt_service_plans(plans_by_type[plan_type], plan_type, lang_code)
                        
                        # یک آیتم نتیجه اینلاین برای این دسته ایجاد می‌کنیم
                        results.append(types.InlineQueryResultArticle(
                            id=f"send_plan_list_{key}",
                            title=title,
                            description=f"ارسال لیست پلن‌های {plan_type} در چت.",
                            input_message_content=types.InputTextMessageContent(
                                message_text=category_text,
                                parse_mode="MarkdownV2"
                            )
                        ))
            
            bot.answer_inline_query(inline_query.id, results[:50], cache_time=10)
            return
                
        found_users = combined_handler.search_user(query)
        for i, user in enumerate(found_users[:10]):
            formatted_text, parse_mode = fmt_inline_result(user)
            keyboard = InlineKeyboardMarkup(row_width=2)
            normal_switch_query, b64_switch_query = f"copy_link:normal:{user.get('uuid', '')}", f"copy_link:b64:{user.get('uuid', '')}"
            keyboard.add(
                InlineKeyboardButton(text="📋 Normal", switch_inline_query_current_chat=normal_switch_query),
                InlineKeyboardButton(text="📋 Base64", switch_inline_query_current_chat=b64_switch_query)
            )
            result = types.InlineQueryResultArticle(
                id=str(i), title=f"👤 {user.get('name', 'کاربر ناشناس')}", description=f"UUID: {user.get('uuid', 'N/A')}",
                reply_markup=keyboard,
                input_message_content=types.InputTextMessageContent(message_text=formatted_text, parse_mode=parse_mode)
            )
            results.append(result)
        
        bot.answer_inline_query(inline_query.id, results, cache_time=5)

    except Exception as e:
        logger.error(f"Error handling admin inline query: {e}", exc_info=True)