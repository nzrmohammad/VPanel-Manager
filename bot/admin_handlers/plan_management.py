import logging
from telebot import types
from ..menu import menu
from ..utils import _safe_edit, escape_markdown, load_service_plans, save_service_plans, parse_volume_string

logger = logging.getLogger(__name__)
bot, admin_conversations = None, None


def initialize_plan_management_handlers(b, conv_dict):
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


def handle_plan_management_menu(call, params):
    """منوی اصلی مدیریت پلن‌ها را با دسته‌بندی نمایش می‌دهد."""
    uid, msg_id = call.from_user.id, call.message.message_id
    prompt = f"🗂️ *{escape_markdown('مدیریت پلن‌های فروش')}*\n\n{escape_markdown('لطفاً دسته‌بندی مورد نظر را برای مشاهده یا ویرایش پلن‌ها انتخاب کنید.')}"
    kb = types.InlineKeyboardMarkup(row_width=2)
    
    kb.add(
        types.InlineKeyboardButton("🇺🇸 پلن‌های آمریکا", callback_data="admin:plan_show_category:usa"),
        types.InlineKeyboardButton("🇩🇪 پلن‌های آلمان", callback_data="admin:plan_show_category:germany")
    )
    kb.add(
        types.InlineKeyboardButton("🇫🇷 پلن‌های فرانسه", callback_data="admin:plan_show_category:france"),
        types.InlineKeyboardButton("🇹🇷 پلن‌های ترکیه", callback_data="admin:plan_show_category:turkey")
    )
    kb.add(
        types.InlineKeyboardButton("🚀 پلن‌های ترکیبی", callback_data="admin:plan_show_category:combined"),
        types.InlineKeyboardButton("➕ افزودن پلن جدید", callback_data="admin:plan_add_start")
    )
    
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin:panel"))
    
    _safe_edit(uid, msg_id, prompt, reply_markup=kb, parse_mode="MarkdownV2")

def handle_show_plans_by_category(call, params):
    """لیست پلن‌های یک دسته‌بندی خاص را برای مدیریت نمایش می‌دهد."""
    plan_type = params[0]
    uid, msg_id = call.from_user.id, call.message.message_id
    all_plans = load_service_plans()
    
    type_map = {
        "combined": "ترکیبی",
        "germany": "آلمان",
        "france": "فرانسه",
        "turkey": "ترکیه",
        "usa": "آمریکا"
    }
    category_name = type_map.get(plan_type, plan_type.capitalize())
    
    prompt = f"🗂️ *{escape_markdown(f'لیست پلن‌های دسته: {category_name}')}*"
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    
    buttons = []
    for i, plan in enumerate(all_plans):
        if plan.get('type') == plan_type:
            plan_name = plan.get('name', f'پلن بدون نام {i+1}')
            buttons.append(types.InlineKeyboardButton(f"🔸 {plan_name}", callback_data=f"admin:plan_details:{i}"))
            
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            kb.add(buttons[i], buttons[i+1])
        else:
            kb.add(buttons[i])
            
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به دسته‌بندی‌ها", callback_data="admin:plan_manage"))
    
    _safe_edit(uid, msg_id, prompt, reply_markup=kb, parse_mode="MarkdownV2")

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
    
    details = [f"🔸 *{escape_markdown('نام پلن:')}* {escape_markdown(plan.get('name', ''))}"]

    if plan_type == 'combined':
        details.extend([
            f"🔹 *{escape_markdown('نوع:')}* ترکیبی",
            f"📦 *{escape_markdown('حجم کل:')}* {escape_markdown(plan.get('total_volume', '0'))}",
            f"🇩🇪 *{escape_markdown('حجم آلمان:')}* {escape_markdown(plan.get('volume_de', '0'))}",
            f"🇫🇷 *{escape_markdown('حجم فرانسه:')}* {escape_markdown(plan.get('volume_fr', '0'))}"
        ])
    else: 
        volume = ""
        if plan_type == 'germany' and plan.get('volume_de'):
            volume = f"{escape_markdown(plan.get('volume_de'))} 🇩🇪"
        elif plan_type == 'france' and plan.get('volume_fr'):
            volume = f"{escape_markdown(plan.get('volume_fr'))} 🇫🇷"
        elif plan_type == 'turkey' and plan.get('volume_tr'):
            volume = f"{escape_markdown(plan.get('volume_tr'))} 🇹🇷"
        elif plan_type == 'usa' and plan.get('volume_us'):
            volume = f"{escape_markdown(plan.get('volume_us'))} 🇺🇸"
        
        details.extend([
            f"🔹 *{escape_markdown('نوع:')}* اختصاصی",
            f"📦 *{escape_markdown('حجم:')}* {volume}"
        ])
    
    details.extend([
        f"📅 *{escape_markdown('مدت زمان:')}* {escape_markdown(plan.get('duration', '0'))}",
        f"💰 *{escape_markdown('قیمت (تومان):')}* `{escape_markdown(str(plan.get('price', 0)))}`"
    ])
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🗑 حذف پلن", callback_data=f"admin:plan_delete_confirm:{plan_index}"),
        types.InlineKeyboardButton("✏️ ویرایش پلن", callback_data=f"admin:plan_edit_start:{plan_index}")
    )
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست پلن‌ها", callback_data=f"admin:plan_show_category:{plan_type}"))
    
    _safe_edit(uid, msg_id, "\n".join(details), reply_markup=kb, parse_mode="MarkdownV2")

def handle_delete_plan_confirm(call, params):
    """از ادمین برای حذف یک پلن تاییدیه می‌گیرد."""
    plan_index = int(params[0])
    uid, msg_id = call.from_user.id, call.message.message_id
    plans = load_service_plans()
    plan_name = plans[plan_index].get('name', 'این پلن')

    prompt = f"⚠️ *آیا از حذف «{escape_markdown(plan_name)}» اطمینان دارید؟*\n\nاین عمل غیرقابل بازگشت است\\."
    
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

# --- New Edit Plan Conversation Flow ---

def handle_plan_edit_start(call, params):
    """مرحله اول ویرایش: شروع مکالمه و پرسیدن نام جدید."""
    plan_index = int(params[0])
    uid, msg_id = call.from_user.id, call.message.message_id
    
    admin_conversations[uid] = {
        'step': 'plan_edit_name',
        'msg_id': msg_id,
        'plan_index': plan_index,
        'new_plan_data': load_service_plans()[plan_index].copy()
    }
    
    prompt = "1️⃣ لطفاً *نام جدید* را برای پلن وارد کنید:"
    _safe_edit(uid, msg_id, escape_markdown(prompt), reply_markup=menu.admin_cancel_action(f"admin:plan_details:{plan_index}"))
    bot.register_next_step_handler_by_chat_id(uid, get_plan_new_name)

def get_plan_new_name(message: types.Message):
    """نام جدید را دریافت کرده و به مرحله بعد می‌رود."""
    uid, new_name = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return
    
    convo = admin_conversations[uid]
    convo['new_plan_data']['name'] = new_name
    convo['step'] = 'plan_edit_total_volume'

    prompt = f"2️⃣ لطفاً *حجم کل* جدید را وارد کنید (مثال: `۵۰ گیگابایت`):"
    _safe_edit(uid, convo['msg_id'], escape_markdown(prompt), reply_markup=menu.admin_cancel_action(f"admin:plan_details:{convo['plan_index']}"))
    bot.register_next_step_handler_by_chat_id(uid, get_plan_new_total_volume)
    
def get_plan_new_total_volume(message: types.Message):
    """حجم کل جدید را دریافت کرده و به مرحله بعد می‌رود."""
    uid, new_volume = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return
    
    convo = admin_conversations[uid]
    convo['new_plan_data']['total_volume'] = new_volume
    convo['step'] = 'plan_edit_duration'

    prompt = f"3️⃣ لطفاً *مدت زمان* جدید را وارد کنید (مثال: `۳۰ روز`):"
    _safe_edit(uid, convo['msg_id'], escape_markdown(prompt), reply_markup=menu.admin_cancel_action(f"admin:plan_details:{convo['plan_index']}"))
    bot.register_next_step_handler_by_chat_id(uid, get_plan_new_duration)

def get_plan_new_duration(message: types.Message):
    """مدت زمان جدید را دریافت کرده و به مرحله بعد می‌رود."""
    uid, new_duration = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return
    
    convo = admin_conversations[uid]
    convo['new_plan_data']['duration'] = new_duration
    convo['step'] = 'plan_edit_price'

    prompt = f"4️⃣ لطفاً *قیمت جدید* را به تومان وارد کنید (فقط عدد):"
    _safe_edit(uid, convo['msg_id'], escape_markdown(prompt), reply_markup=menu.admin_cancel_action(f"admin:plan_details:{convo['plan_index']}"))
    bot.register_next_step_handler_by_chat_id(uid, get_plan_new_price_and_save)

def get_plan_new_price_and_save(message: types.Message):
    """قیمت جدید را دریافت کرده، پلن را ذخیره و نتیجه را اعلام می‌کند."""
    uid, new_price_str = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return

    convo = admin_conversations.pop(uid)
    msg_id = convo['msg_id']
    plan_index = convo['plan_index']
    
    try:
        new_price = int(new_price_str)
        convo['new_plan_data']['price'] = new_price

        all_plans = load_service_plans()
        all_plans[plan_index] = convo['new_plan_data']
        
        if save_service_plans(all_plans):
            success_msg = "✅ پلن با موفقیت ویرایش و ذخیره شد."
            _safe_edit(uid, msg_id, escape_markdown(success_msg), reply_markup=menu.admin_cancel_action(f"admin:plan_manage"))
        else:
            raise IOError("Failed to save plans file.")

    except (ValueError, TypeError):
        error_msg = "❌ قیمت وارد شده نامعتبر است. عملیات ویرایش لغو شد."
        _safe_edit(uid, msg_id, escape_markdown(error_msg), reply_markup=menu.admin_cancel_action(f"admin:plan_details:{plan_index}"))
    except Exception as e:
        logger.error(f"Error saving edited plan: {e}", exc_info=True)
        error_msg = "❌ خطایی در هنگام ذخیره پلن رخ داد. عملیات لغو شد."
        _safe_edit(uid, msg_id, escape_markdown(error_msg), reply_markup=menu.admin_cancel_action(f"admin:plan_details:{plan_index}"))

# --- Add Plan Conversation Flow ---
def handle_plan_add_start(call, params):
    """مرحله اول افزودن: شروع مکالمه و پرسیدن نوع پلن."""
    uid, msg_id = call.from_user.id, call.message.message_id
    
    admin_conversations[uid] = {
        'step': 'plan_add_type',
        'msg_id': msg_id,
        'new_plan_data': {}
    }
    
    prompt = "1️⃣ لطفاً *نوع پلن* جدید را انتخاب کنید:"
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("پلن ترکیبی", callback_data="admin:plan_add_type:combined"),
        types.InlineKeyboardButton("پلن آلمان", callback_data="admin:plan_add_type:germany"),
        types.InlineKeyboardButton("پلن فرانسه", callback_data="admin:plan_add_type:france"),
        types.InlineKeyboardButton("پلن ترکیه", callback_data="admin:plan_add_type:turkey")
    )
    kb.add(types.InlineKeyboardButton("🔙 لغو", callback_data="admin:plan_manage"))
    
    _safe_edit(uid, msg_id, prompt, reply_markup=kb)

def get_plan_add_type(call, params):
    """دریافت نوع پلن و پرسیدن نام آن."""
    uid, msg_id = call.from_user.id, call.message.message_id
    plan_type = params[0]
    
    if uid not in admin_conversations: return
    
    admin_conversations[uid]['new_plan_data']['type'] = plan_type
    admin_conversations[uid]['step'] = 'plan_add_name'
    
    prompt = f"2️⃣ لطفاً *نام* پلن جدید را وارد کنید:"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_cancel_action("admin:plan_manage"))
    bot.register_next_step_handler_by_chat_id(uid, get_plan_add_name)

def get_plan_add_name(message: types.Message):
    """دریافت نام پلن و پرسیدن جزئیات حجم."""
    uid, new_name = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return
    
    convo = admin_conversations[uid]
    plan_type = convo['new_plan_data']['type']
    convo['new_plan_data']['name'] = new_name
    convo['step'] = 'plan_add_volume_details'

    if plan_type == 'combined':
        prompt = f"3️⃣ لطفاً *حجم هر سرور* را وارد کنید (مثال: `۲۰ گیگابایت ۱۰ گیگابایت`):"
        _safe_edit(uid, convo['msg_id'], prompt, reply_markup=menu.admin_cancel_action("admin:plan_manage"))
        bot.register_next_step_handler_by_chat_id(uid, get_plan_add_combined_volumes)
    else:
        prompt = f"3️⃣ لطفاً *حجم کل* را وارد کنید (مثال: `۵۰ گیگابایت`):"
        _safe_edit(uid, convo['msg_id'], prompt, reply_markup=menu.admin_cancel_action("admin:plan_manage"))
        bot.register_next_step_handler_by_chat_id(uid, get_plan_add_simple_volume)

def get_plan_add_combined_volumes(message: types.Message):
    """دریافت حجم‌های پلن ترکیبی."""
    uid, volumes_text = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return

    convo = admin_conversations[uid]
    
    parts = volumes_text.split()
    if len(parts) < 2:
        error_msg = "❌ لطفاً حجم آلمان و فرانسه را با فاصله وارد کنید (مثال: `۲۰ گیگابایت ۱۰ گیگابایت`). عملیات لغو شد."
        _safe_edit(uid, convo['msg_id'], error_msg, reply_markup=menu.admin_cancel_action("admin:plan_manage"))
        return

    convo['new_plan_data']['volume_de'] = parts[0]
    convo['new_plan_data']['volume_fr'] = parts[1]
    
    total_volume_de = parse_volume_string(parts[0])
    total_volume_fr = parse_volume_string(parts[1])
    convo['new_plan_data']['total_volume'] = f"{total_volume_de + total_volume_fr} گیگابایت"
    
    convo['step'] = 'plan_add_duration'
    prompt = f"4️⃣ لطفاً *مدت زمان* را وارد کنید (مثال: `۳۰ روز`):"
    _safe_edit(uid, convo['msg_id'], prompt, reply_markup=menu.admin_cancel_action("admin:plan_manage"))
    bot.register_next_step_handler_by_chat_id(uid, get_plan_add_duration)


def get_plan_add_simple_volume(message: types.Message):
    """دریافت حجم پلن ساده."""
    uid, volume_text = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return

    convo = admin_conversations[uid]
    plan_type = convo['new_plan_data']['type']
    
    volume_key = 'volume_de' if plan_type == 'germany' else 'volume_fr'
    convo['new_plan_data'][volume_key] = volume_text
    convo['new_plan_data']['total_volume'] = volume_text
    
    convo['step'] = 'plan_add_duration'
    prompt = f"4️⃣ لطفاً *مدت زمان* را وارد کنید (مثال: `۳۰ روز`):"
    _safe_edit(uid, convo['msg_id'], prompt, reply_markup=menu.admin_cancel_action("admin:plan_manage"))
    bot.register_next_step_handler_by_chat_id(uid, get_plan_add_duration)


def get_plan_add_duration(message: types.Message):
    """دریافت مدت زمان و پرسیدن قیمت."""
    uid, duration_text = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return

    convo = admin_conversations[uid]
    convo['new_plan_data']['duration'] = duration_text
    convo['step'] = 'plan_add_price'
    
    prompt = f"5️⃣ لطفاً *قیمت* را به تومان وارد کنید (فقط عدد):"
    _safe_edit(uid, convo['msg_id'], prompt, reply_markup=menu.admin_cancel_action("admin:plan_manage"))
    bot.register_next_step_handler_by_chat_id(uid, get_plan_add_price_and_save)


def get_plan_add_price_and_save(message: types.Message):
    """دریافت قیمت، ذخیره پلن جدید و اعلام نتیجه."""
    uid, new_price_str = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return
    
    convo = admin_conversations.pop(uid)
    msg_id = convo['msg_id']
    
    try:
        new_price = int(new_price_str)
        convo['new_plan_data']['price'] = new_price
        
        all_plans = load_service_plans()
        all_plans.append(convo['new_plan_data'])
        
        if save_service_plans(all_plans):
            success_msg = "✅ پلن جدید با موفقیت اضافه شد."
            kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت به مدیریت پلن‌ها", callback_data="admin:plan_manage"))
            _safe_edit(uid, msg_id, success_msg, reply_markup=kb)
        else:
            raise IOError("Failed to save plans file.")
    except (ValueError, TypeError):
        error_msg = "❌ قیمت وارد شده نامعتبر است. عملیات افزودن پلن لغو شد."
        _safe_edit(uid, msg_id, error_msg, reply_markup=menu.admin_cancel_action("admin:plan_manage"))
    except Exception as e:
        logger.error(f"Error adding new plan: {e}", exc_info=True)
        error_msg = "❌ خطایی در هنگام ذخیره پلن رخ داد. عملیات لغو شد."
        _safe_edit(uid, msg_id, error_msg, reply_markup=menu.admin_cancel_action("admin:plan_manage"))

# --- Edit Plan Conversation Flow ---
def handle_plan_edit_start(call, params):
    """مرحله اول ویرایش: شروع مکالمه و پرسیدن نام جدید."""
    plan_index = int(params[0])
    uid, msg_id = call.from_user.id, call.message.message_id
    
    admin_conversations[uid] = {
        'step': 'plan_edit_name',
        'msg_id': msg_id,
        'plan_index': plan_index,
        'new_plan_data': load_service_plans()[plan_index].copy()
    }
    
    prompt = "1️⃣ لطفاً *نام جدید* را برای پلن وارد کنید:"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_cancel_action(f"admin:plan_details:{plan_index}"))
    bot.register_next_step_handler_by_chat_id(uid, get_plan_new_name)

def get_plan_new_name(message: types.Message):
    """نام جدید را دریافت کرده و به مرحله بعد می‌رود."""
    uid, new_name = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return
    
    convo = admin_conversations[uid]
    convo['new_plan_data']['name'] = new_name
    convo['step'] = 'plan_edit_total_volume'

    prompt = f"2️⃣ لطفاً *حجم کل* جدید را وارد کنید (مثال: `۵۰ گیگابایت`):"
    _safe_edit(uid, convo['msg_id'], prompt, reply_markup=menu.admin_cancel_action(f"admin:plan_details:{convo['plan_index']}"))
    bot.register_next_step_handler_by_chat_id(uid, get_plan_new_total_volume)
    
def get_plan_new_total_volume(message: types.Message):
    """حجم کل جدید را دریافت کرده و به مرحله بعد می‌رود."""
    uid, new_volume = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return
    
    convo = admin_conversations[uid]
    convo['new_plan_data']['total_volume'] = new_volume
    convo['step'] = 'plan_edit_duration'

    prompt = f"3️⃣ لطفاً *مدت زمان* جدید را وارد کنید (مثال: `۳۰ روز`):"
    _safe_edit(uid, convo['msg_id'], prompt, reply_markup=menu.admin_cancel_action(f"admin:plan_details:{convo['plan_index']}"))
    bot.register_next_step_handler_by_chat_id(uid, get_plan_new_duration)

def get_plan_new_duration(message: types.Message):
    """مدت زمان جدید را دریافت کرده و به مرحله بعد می‌رود."""
    uid, new_duration = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return
    
    convo = admin_conversations[uid]
    convo['new_plan_data']['duration'] = new_duration
    convo['step'] = 'plan_edit_price'

    prompt = f"4️⃣ لطفاً *قیمت جدید* را به تومان وارد کنید (فقط عدد):"
    _safe_edit(uid, convo['msg_id'], prompt, reply_markup=menu.admin_cancel_action(f"admin:plan_details:{convo['plan_index']}"))
    bot.register_next_step_handler_by_chat_id(uid, get_plan_new_price_and_save)

def get_plan_new_price_and_save(message: types.Message):
    """قیمت جدید را دریافت کرده، پلن را ذخیره و نتیجه را اعلام می‌کند."""
    uid, new_price_str = message.from_user.id, message.text.strip()
    _delete_user_message(message)
    if uid not in admin_conversations: return

    convo = admin_conversations.pop(uid)
    msg_id = convo['msg_id']
    plan_index = convo['plan_index']
    
    try:
        new_price = int(new_price_str)
        convo['new_plan_data']['price'] = new_price

        all_plans = load_service_plans()
        all_plans[plan_index] = convo['new_plan_data']
        
        if save_service_plans(all_plans):
            success_msg = "✅ پلن با موفقیت ویرایش و ذخیره شد."
            kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت به مدیریت پلن‌ها", callback_data="admin:plan_manage"))
            _safe_edit(uid, msg_id, success_msg, reply_markup=kb)
        else:
            raise IOError("Failed to save plans file.")

    except (ValueError, TypeError):
        error_msg = "❌ قیمت وارد شده نامعتبر است. عملیات ویرایش لغو شد."
        _safe_edit(uid, msg_id, error_msg, reply_markup=menu.admin_cancel_action(f"admin:plan_details:{plan_index}"))
    except Exception as e:
        logger.error(f"Error saving edited plan: {e}", exc_info=True)
        error_msg = "❌ خطایی در هنگام ذخیره پلن رخ داد. عملیات لغو شد."
        _safe_edit(uid, msg_id, error_msg, reply_markup=menu.admin_cancel_action(f"admin:plan_details:{plan_index}"))