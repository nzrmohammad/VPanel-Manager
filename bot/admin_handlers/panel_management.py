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
    
    prompt = f"⚙️ *{escape_markdown('مدیریت پنل‌ها')}*\n\n{escape_markdown('در این بخش می‌توانید سرورهای Hiddify و Marzban متصل به ربات را مدیریت کنید.')}"
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    
    buttons = []
    for p in panels:
        status_emoji = "✅" if p['is_active'] else "❌"
        panel_type_fa = "Hiddify" if p['panel_type'] == 'hiddify' else "Marzban"
        btn_text = f"{status_emoji} {p['name']} ({panel_type_fa})"
        buttons.append(types.InlineKeyboardButton(btn_text, callback_data=f"admin:panel_details:{p['id']}"))
    
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            kb.add(buttons[i], buttons[i+1])
        else:
            kb.add(buttons[i])
    
    kb.add(types.InlineKeyboardButton("➕ افزودن پنل جدید", callback_data="admin:panel_add_start"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin:panel"))
    
    _safe_edit(uid, msg_id, prompt, reply_markup=kb, parse_mode="MarkdownV2")

# --- Start of Add Panel Conversation ---

def handle_start_add_panel(call, params):
    """مرحله اول: شروع مکالمه و پرسیدن نوع پنل."""
    uid, msg_id = call.from_user.id, call.message.message_id
    admin_conversations[uid] = {'step': 'type', 'msg_id': msg_id, 'data': {}}
    
    prompt = escape_markdown("1️⃣ لطفاً نوع پنلی که می‌خواهید اضافه کنید را انتخاب کنید:")
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
    
    prompt = escape_markdown("2️⃣ یک نام منحصر به فرد برای این پنل انتخاب کنید (مثال: سرور آلمان):")
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
    
    prompt = escape_markdown(f"3️⃣ لطفاً آدرس کامل پنل را وارد کنید:\n\n*مثال برای Hiddify:*\n`https://mypanel.domain.com`\n\n*مثال برای Marzban:*\n`https://mypanel.domain.com:8000`")
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

    prompt_text = "4️⃣ "
    if panel_type == 'hiddify':
        prompt_text += "لطفاً `Admin UUID` پنل هیدیفای را وارد کنید:"
    else: # Marzban
        prompt_text += "لطفاً `Username` ادمین پنل مرزبان را وارد کنید:"
        
    _safe_edit(uid, msg_id, escape_markdown(prompt_text), reply_markup=menu.admin_cancel_action("admin:panel_manage"))
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
        prompt = escape_markdown("5️⃣ (اختیاری) لطفاً `Admin Proxy Path` را وارد کنید. اگر ندارید، کلمه `ندارم` را ارسال کنید:")
        _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_cancel_action("admin:panel_manage"))
        bot.register_next_step_handler_by_chat_id(uid, get_panel_token2)
    else: # Marzban
        admin_conversations[uid]['step'] = 'token2_marzban'
        prompt = escape_markdown("5️⃣ لطفاً `Password` ادمین پنل مرزبان را وارد کنید:")
        _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_cancel_action("admin:panel_manage"))
        bot.register_next_step_handler_by_chat_id(uid, get_panel_token2)

def get_panel_token2(message: types.Message):
    """مرحله ششم (آخر): دریافت توکن دوم و ذخیره پنل در دیتابیس."""
    uid, token2 = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return

    # اطلاعات مکالمه را در متغیرهای محلی ذخیره می‌کنیم
    convo_data = admin_conversations[uid]
    panel_data = convo_data['data']
    msg_id = convo_data['msg_id']

    if panel_data['panel_type'] == 'hiddify' and token2.lower() in ['ندارم', 'none', 'no']:
        panel_data['api_token2'] = None
    else:
        panel_data['api_token2'] = token2

    success = db.add_panel(
        name=panel_data['name'],
        panel_type=panel_data['panel_type'],
        api_url=panel_data['api_url'],
        token1=panel_data['api_token1'],
        token2=panel_data['api_token2']
    )

    if success:
        # ساخت یک پیام موفقیت‌آمیز خوانا
        success_message = escape_markdown("✅ پنل با موفقیت اضافه شد. برای مشاهده لیست جدید، به منوی مدیریت پنل‌ها بازگردید.")
        # ویرایش پیام قبلی با پیام موفقیت
        _safe_edit(uid, msg_id, success_message, reply_markup=menu.admin_cancel_action("admin:panel_manage"))
    else:
        error_message = escape_markdown("❌ خطا: پنلی با این نام از قبل وجود دارد. لطفاً نام دیگری انتخاب کنید.")
        _safe_edit(uid, msg_id, error_message, reply_markup=menu.admin_cancel_action("admin:panel_manage"))

    # مکالمه را در انتهای تابع پاک می‌کنیم
    admin_conversations.pop(uid, None)

def handle_panel_details(call, params):
    """نمایش جزئیات پنل و گزینه‌های مدیریت."""
    uid, msg_id = call.from_user.id, call.message.message_id
    panel_id = int(params[0])
    
    panel = db.get_panel_by_id(panel_id)
    
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
    
    # دکمه جدید مشاهده پنل
    kb.add(types.InlineKeyboardButton(f"🌐 مشاهده پنل", url=panel['api_url']))
    
    kb.add(
        types.InlineKeyboardButton(f"🗑 حذف", callback_data=f"admin:panel_delete_confirm:{panel_id}"),
        types.InlineKeyboardButton(f"🔄 {toggle_text}", callback_data=f"admin:panel_toggle:{panel_id}")
    )
    kb.add(types.InlineKeyboardButton(f"✏️ تغییر نام", callback_data=f"admin:panel_edit_start:{panel_id}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="admin:panel_manage"))
    
    _safe_edit(uid, msg_id, "\n".join(details), reply_markup=kb)

def handle_panel_delete_confirm(call, params):
    """نمایش پیام تایید برای حذف پنل."""
    panel_id = int(params[0])
    prompt = "⚠️ *آیا از حذف این پنل اطمینان دارید؟* این عمل غیرقابل بازگشت است\\."
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
        handle_panel_details(call, params)
    else:
        bot.answer_callback_query(call.id, "❌ خطا در تغییر وضعیت پنل.", show_alert=True)

def handle_panel_edit_start(call, params):
    """مرحله اول ویرایش: پرسیدن نام جدید."""
    uid, msg_id = call.from_user.id, call.message.message_id
    panel_id = int(params[0])
    
    panel = db.get_panel_by_id(panel_id)
    if not panel:
        bot.answer_callback_query(call.id, "❌ پنل یافت نشد.", show_alert=True)
        return

    admin_conversations[uid] = {'step': 'panel_rename', 'msg_id': msg_id, 'panel_id': panel_id}
    
    prompt = f"لطفاً نام جدید را برای پنل «{escape_markdown(panel['name'])}» وارد کنید:"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_cancel_action(f"admin:panel_details:{panel_id}"))
    bot.register_next_step_handler_by_chat_id(uid, get_new_panel_name)


def get_new_panel_name(message: types.Message):
    """مرحله دوم ویرایش: دریافت و ذخیره نام جدید."""
    uid, new_name = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return

    convo_data = admin_conversations.get(uid, {})
    panel_id = convo_data.get('panel_id')
    msg_id = convo_data.get('msg_id')

    admin_conversations.pop(uid, None)

    if not all([panel_id, msg_id]):
        logger.error(f"Incomplete conversation data for renaming panel for user {uid}")
        bot.send_message(uid, "❌ خطایی در جریان مکالمه رخ داد. لطفاً دوباره تلاش کنید.", reply_markup=menu.admin_cancel_action("admin:panel_manage"))
        return

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به جزئیات پنل", callback_data=f"admin:panel_details:{panel_id}"))

    if db.update_panel_name(panel_id, new_name):
        success_message = escape_markdown(f"✅ نام پنل با موفقیت به «{new_name}» تغییر کرد.")
        _safe_edit(uid, msg_id, success_message, reply_markup=kb)
    else:
        error_message = escape_markdown("❌ خطا در تغییر نام پنل. ممکن است نام تکراری باشد.")
        _safe_edit(uid, msg_id, error_message, reply_markup=kb)


def handle_panel_details(call, params):
    """نمایش جزئیات پنل و گزینه‌های مدیریت."""
    uid, msg_id = call.from_user.id, call.message.message_id
    panel_id = int(params[0])
    
    panel = db.get_panel_by_id(panel_id)
    
    if not panel:
        bot.answer_callback_query(call.id, "❌ پنل یافت نشد.", show_alert=True)
        return

    panel_view_url = panel['api_url']
    if panel['panel_type'] == 'hiddify' and panel.get('api_token2'):
        base_url = panel['api_url'].rstrip('/')
        proxy_path = panel['api_token2'].lstrip('/')
        panel_view_url = f"{base_url}/{proxy_path}/"

    status = "✅" if panel['is_active'] else "❌"
    details = [
        f"⚙️ *جزئیات پنل: {escape_markdown(panel['name'])}*",
        f"`──────────────────`",
        f"🔸 *نوع :* {escape_markdown(panel['panel_type'])}",
        f"🔹 *وضعیت :* {status}",
        f"🔗 *آدرس :* `{escape_markdown(panel['api_url'])}`"
    ]
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    toggle_text = "غیرفعال کردن" if panel['is_active'] else "فعال کردن"
    
    kb.add(types.InlineKeyboardButton(f"🌐 مشاهده پنل", url=panel_view_url))
    
    kb.add(
        types.InlineKeyboardButton(f"🗑 حذف", callback_data=f"admin:panel_delete_confirm:{panel_id}"),
        types.InlineKeyboardButton(f"🔄 {toggle_text}", callback_data=f"admin:panel_toggle:{panel_id}")
    )
    kb.add(types.InlineKeyboardButton(f"✏️ تغییر نام", callback_data=f"admin:panel_edit_start:{panel_id}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="admin:panel_manage"))
    
    _safe_edit(uid, msg_id, "\n".join(details), reply_markup=kb)