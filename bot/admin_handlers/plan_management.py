import logging
from telebot import types
from ..menu import menu
from ..utils import _safe_edit, escape_markdown, load_service_plans, save_service_plans

logger = logging.getLogger(__name__)
bot, admin_conversations = None, None

def initialize_plan_management_handlers(b, conv_dict):
    """مقادیر bot و admin_conversations را از فایل اصلی دریافت می‌کند."""
    global bot, admin_conversations
    bot = b
    admin_conversations = conv_dict

def handle_plan_management_menu(call, params):
    """منوی اصلی مدیریت پلن‌ها را نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    plans = load_service_plans()
    
    prompt = "🗂️ *مدیریت پلن‌های فروش*\n\nدر این بخش می‌توانید پلن‌های فروش سرویس را مشاهده، ویرایش، حذف یا اضافه کنید."
    
    kb = types.InlineKeyboardMarkup(row_width=1)
    for i, plan in enumerate(plans):
        plan_name = plan.get('name', f'پلن بدون نام {i+1}')
        kb.add(types.InlineKeyboardButton(f"🔸 {plan_name}", callback_data=f"admin:plan_details:{i}"))
    
    kb.add(types.InlineKeyboardButton("➕ افزودن پلن جدید", callback_data="admin:plan_add_start"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin:panel"))
    
    _safe_edit(uid, msg_id, escape_markdown(prompt), reply_markup=kb)

# مسیر فایل: bot/admin_handlers/plan_management.py

# مسیر فایل: bot/admin_handlers/plan_management.py

def handle_plan_details_menu(call, params):
    """جزئیات یک پلن خاص را به همراه دکمه‌های ویرایش و حذف نمایش می‌دهد."""
    plan_index = int(params[0])
    uid, msg_id = call.from_user.id, call.message.message_id
    plans = load_service_plans()
    
    if not (0 <= plan_index < len(plans)):
        bot.answer_callback_query(call.id, "❌ پلن مورد نظر یافت نشد.", show_alert=True)
        return

    plan = plans[plan_index]
    plan_type = plan.get('type')
    
    details = [f"🔸 *نام پلن:* {escape_markdown(plan.get('name', ''))}"]

    # --- شروع بخش منطق جدید ---
    if plan_type == 'combined':
        details.extend([
            f"🔹 *نوع:* ترکیبی",
            f"📦 *حجم کل:* {escape_markdown(plan.get('total_volume', '0'))}",
            f"🇩🇪 *حجم آلمان:* {escape_markdown(plan.get('volume_de', '0'))}",
            f"🇫🇷 *حجم فرانسه:* {escape_markdown(plan.get('volume_fr', '0'))}"
        ])
    else: # برای پلن‌های 'germany' و 'france'
        volume = ""
        if plan_type == 'germany' and plan.get('volume_de'):
            volume = f"{escape_markdown(plan.get('volume_de'))} 🇩🇪"
        elif plan_type == 'france' and plan.get('volume_fr'):
            volume = f"{escape_markdown(plan.get('volume_fr'))} 🇫🇷"
        
        details.extend([
            f"🔹 *نوع:* ساده",
            f"📦 *حجم کل:* {volume}"
        ])
    
    details.extend([
        f"📅 *مدت زمان:* {escape_markdown(plan.get('duration', '0'))}",
        f"💰 *قیمت \\(تومان\\):* `{escape_markdown(str(plan.get('price', 0)))}`"
    ])
    # --- پایان بخش منطق جدید ---
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🗑 حذف پلن", callback_data=f"admin:plan_delete_confirm:{plan_index}"),
        types.InlineKeyboardButton("✏️ ویرایش پلن", callback_data=f"admin:plan_edit_start:{plan_index}")
    )
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست پلن‌ها", callback_data="admin:plan_manage"))
    
    _safe_edit(uid, msg_id, "\n".join(details), reply_markup=kb)

def handle_delete_plan_confirm(call, params):
    """از ادمین برای حذف یک پلن تاییدیه می‌گیرد."""
    plan_index = int(params[0])
    uid, msg_id = call.from_user.id, call.message.message_id
    plans = load_service_plans()
    plan_name = plans[plan_index].get('name', 'این پلن')

    prompt = f"⚠️ *آیا از حذف «{escape_markdown(plan_name)}» اطمینان دارید؟*\n\nاین عمل غیرقابل بازگشت است."
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("❌ بله، حذف کن", callback_data=f"admin:plan_delete_execute:{plan_index}"),
        types.InlineKeyboardButton("✅ انصراف", callback_data=f"admin:plan_details:{plan_index}")
    )
    _safe_edit(uid, msg_id, prompt, reply_markup=kb)

def handle_delete_plan_execute(call, params):
    """پلن انتخاب شده را حذف کرده و نتیجه را اعلام می‌کند."""
    plan_index = int(params[0])
    uid = call.from_user.id
    
    plans = load_service_plans()
    if 0 <= plan_index < len(plans):
        del plans[plan_index]
        if save_service_plans(plans):
            bot.answer_callback_query(call.id, "✅ پلن با موفقیت حذف شد.")
            handle_plan_management_menu(call, [])
        else:
            bot.answer_callback_query(call.id, "❌ خطا در ذخیره فایل پلن‌ها.", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "❌ پلن یافت نشد.", show_alert=True)