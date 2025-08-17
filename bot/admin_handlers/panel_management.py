import logging
from telebot import types
from ..database import db
from ..menu import menu
from ..utils import _safe_edit, escape_markdown

logger = logging.getLogger(__name__)
bot, admin_conversations = None, None

def initialize_panel_management_handlers(b, conv_dict):
    """مقادیر bot و admin_conversations را از فایل اصلی دریافت می‌کند."""
    global bot, admin_conversations
    bot = b
    admin_conversations = conv_dict

def _delete_user_message(msg: types.Message):
    """پیام کاربر را برای تمیز ماندن چت حذف می‌کند."""
    try:
        bot.delete_message(msg.chat.id, msg.message_id)
    except Exception:
        pass

def handle_panel_management_menu(call, params):
    """منوی اصلی مدیریت پنل‌ها را نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    panels = db.get_all_panels()
    prompt = "⚙️ *مدیریت پنل‌ها*\n\nدر این بخش می‌توانید سرورهای Hiddify و Marzban متصل به ربات را مدیریت کنید."
    
    kb = types.InlineKeyboardMarkup(row_width=1)
    for p in panels:
        status_emoji = "✅" if p['is_active'] else "❌"
        btn_text = f"{status_emoji} {p['name']} ({p['panel_type']})"
        # دکمه جزئیات بعداً تکمیل می‌شود
        kb.add(types.InlineKeyboardButton(btn_text, callback_data=f"admin:panel_details:{p['id']}"))
    
    kb.add(types.InlineKeyboardButton("➕ افزودن پنل جدید", callback_data="admin:panel_add_start"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin:panel"))
    
    _safe_edit(uid, msg_id, escape_markdown(prompt), reply_markup=kb)

# --- Start of Add Panel Conversation ---

def handle_start_add_panel(call, params):
    """مرحله اول: شروع مکالمه و پرسیدن نوع پنل."""
    uid, msg_id = call.from_user.id, call.message.message_id
    admin_conversations[uid] = {'step': 'type', 'msg_id': msg_id, 'data': {}}
    
    prompt = "1️⃣ لطفاً نوع پنلی که می‌خواهید اضافه کنید را انتخاب کنید:"
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("Hiddify", callback_data="admin:panel_set_type:hiddify"),
        types.InlineKeyboardButton("Marzban", callback_data="admin:panel_set_type:marzban")
    )
    kb.add(types.InlineKeyboardButton("🔙 لغو", callback_data="admin:panel_manage"))
    _safe_edit(uid, msg_id, prompt, reply_markup=kb)

def handle_set_panel_type(call, params):
    """مرحله دوم: ذخیره نوع پنل و پرسیدن نام."""
    uid, msg_id = call.from_user.id, call.message.message_id
    panel_type = params[0]
    
    if uid not in admin_conversations: return
    admin_conversations[uid]['data']['panel_type'] = panel_type
    admin_conversations[uid]['step'] = 'name'
    
    prompt = "2️⃣ یک نام منحصر به فرد برای این پنل انتخاب کنید (مثال: سرور آلمان، پنل اصلی):"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_cancel_action("admin:panel_manage"))
    bot.register_next_step_handler_by_chat_id(uid, get_panel_name)

def get_panel_name(message: types.Message):
    """مرحله سوم: دریافت نام و پرسیدن آدرس URL."""
    uid, name = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return

    admin_conversations[uid]['data']['name'] = name
    admin_conversations[uid]['step'] = 'url'
    msg_id = admin_conversations[uid]['msg_id']
    
    prompt = f"3️⃣ لطفاً آدرس کامل پنل را وارد کنید:\n\n*مثال برای Hiddify:*\n`https://mypanel.domain.com`\n\n*مثال برای Marzban:*\n`https://mypanel.domain.com:8000`"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_cancel_action("admin:panel_manage"))
    bot.register_next_step_handler_by_chat_id(uid, get_panel_url)

def get_panel_url(message: types.Message):
    """مرحله چهارم: دریافت URL و پرسیدن توکن اول."""
    uid, url = message.from_user.id, message.text.strip().rstrip('/')
    _delete_user_message(message)
    if uid not in admin_conversations: return

    admin_conversations[uid]['data']['api_url'] = url
    admin_conversations[uid]['step'] = 'token1'
    msg_id = admin_conversations[uid]['msg_id']
    panel_type = admin_conversations[uid]['data']['panel_type']

    prompt = "4️⃣ "
    if panel_type == 'hiddify':
        prompt += "لطفاً `Admin UUID` پنل هیدیفای را وارد کنید:"
    else: # Marzban
        prompt += "لطفاً `Username` ادمین پنل مرزبان را وارد کنید:"
        
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_cancel_action("admin:panel_manage"))
    bot.register_next_step_handler_by_chat_id(uid, get_panel_token1)

def get_panel_token1(message: types.Message):
    """مرحله پنجم: دریافت توکن اول و در صورت نیاز، پرسیدن توکن دوم."""
    uid, token1 = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return

    admin_conversations[uid]['data']['api_token1'] = token1
    msg_id = admin_conversations[uid]['msg_id']
    panel_type = admin_conversations[uid]['data']['panel_type']

    if panel_type == 'hiddify':
        admin_conversations[uid]['step'] = 'token2_hiddify'
        prompt = "5️⃣ (اختیاری) لطفاً `Admin Proxy Path` را وارد کنید. اگر ندارید، کلمه `ندارم` را ارسال کنید:"
        _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_cancel_action("admin:panel_manage"))
        bot.register_next_step_handler_by_chat_id(uid, get_panel_token2)
    else: # Marzban
        admin_conversations[uid]['step'] = 'token2_marzban'
        prompt = "5️⃣ لطفاً `Password` ادمین پنل مرزبان را وارد کنید:"
        _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_cancel_action("admin:panel_manage"))
        bot.register_next_step_handler_by_chat_id(uid, get_panel_token2)

def get_panel_token2(message: types.Message):
    """مرحله ششم (آخر): دریافت توکن دوم و ذخیره پنل در دیتابیس."""
    uid, token2 = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return

    panel_data = admin_conversations[uid]['data']
    msg_id = admin_conversations[uid]['msg_id']

    if panel_data['panel_type'] == 'hiddify' and token2.lower() in ['ندارم', 'none', 'no']:
        panel_data['api_token2'] = None
    else:
        panel_data['api_token2'] = token2
    
    # ذخیره در دیتابیس
    success = db.add_panel(
        name=panel_data['name'],
        panel_type=panel_data['panel_type'],
        api_url=panel_data['api_url'],
        token1=panel_data['api_token1'],
        token2=panel_data['api_token2']
    )
    
    admin_conversations.pop(uid, None) # پایان مکالمه
    
    if success:
        bot.answer_callback_query(message.id if hasattr(message, 'id') else admin_conversations[uid]['msg_id'], "✅ پنل با موفقیت اضافه شد.")
        # فراخوانی منوی اصلی مدیریت پنل‌ها برای نمایش لیست آپدیت شده
        # چون message آبجکت call نیست، یک call ساختگی میسازیم
        fake_call = types.CallbackQuery(id=0, from_user=message.from_user, data="", chat_instance="", json_string="", message=message)
        fake_call.message.message_id = msg_id
        handle_panel_management_menu(fake_call, [])
    else:
        _safe_edit(uid, msg_id, "❌ خطا: پنلی با این نام از قبل وجود دارد. لطفاً نام دیگری انتخاب کنید.", reply_markup=menu.admin_cancel_action("admin:panel_manage"))

def handle_panel_details(call, params):
    """نمایش جزئیات پنل و گزینه‌های مدیریت."""
    uid, msg_id = call.from_user.id, call.message.message_id
    panel_id = int(params[0])
    
    panels = {p['id']: p for p in db.get_all_panels()}
    panel = panels.get(panel_id)
    
    if not panel:
        bot.answer_callback_query(call.id, "❌ پنل یافت نشد.", show_alert=True)
        return

    status = "فعال ✅" if panel['is_active'] else "غیرفعال ❌"
    details = [
        f"⚙️ *جزئیات پنل: {escape_markdown(panel['name'])}*",
        f"`──────────────────`",
        f"🔸 *نوع:* {escape_markdown(panel['panel_type'])}",
        f"🔹 *وضعیت:* {status}",
        f"🔗 *آدرس:* `{escape_markdown(panel['api_url'])}`"
    ]
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    toggle_text = "غیرفعال کردن" if panel['is_active'] else "فعال کردن"
    kb.add(
        types.InlineKeyboardButton(f"🗑 حذف پنل", callback_data=f"admin:panel_delete_confirm:{panel_id}"),
        types.InlineKeyboardButton(f"🔄 {toggle_text}", callback_data=f"admin:panel_toggle:{panel_id}")
    )
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="admin:panel_manage"))
    
    _safe_edit(uid, msg_id, "\n".join(details), reply_markup=kb)

def handle_panel_delete_confirm(call, params):
    """نمایش پیام تایید برای حذف پنل."""
    panel_id = int(params[0])
    prompt = "⚠️ *آیا از حذف این پنل اطمینان دارید؟* این عمل غیرقابل بازگشت است."
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("❌ بله، حذف کن", callback_data=f"admin:panel_delete_execute:{panel_id}"),
        types.InlineKeyboardButton("✅ انصراف", callback_data=f"admin:panel_details:{panel_id}")
    )
    _safe_edit(call.from_user.id, call.message.message_id, prompt, reply_markup=kb)

def handle_panel_delete_execute(call, params):
    """حذف نهایی پنل."""
    panel_id = int(params[0])
    if db.delete_panel(panel_id):
        bot.answer_callback_query(call.id, "✅ پنل با موفقیت حذف شد.")
        handle_panel_management_menu(call, [])
    else:
        bot.answer_callback_query(call.id, "❌ خطا در حذف پنل.", show_alert=True)
        
def handle_panel_toggle_status(call, params):
    """تغییر وضعیت فعال/غیرفعال پنل."""
    panel_id = int(params[0])
    if db.toggle_panel_status(panel_id):
        bot.answer_callback_query(call.id, "✅ وضعیت پنل تغییر کرد.")
        # Refresh the details view
        handle_panel_details(call, params)
    else:
        bot.answer_callback_query(call.id, "❌ خطا در تغییر وضعیت پنل.", show_alert=True)