import logging
from telebot import types
from datetime import datetime, timedelta
from ..menu import menu
from ..utils import _safe_edit, load_service_plans, parse_volume_string, escape_markdown
from .. import combined_handler
import pytz

logger = logging.getLogger(__name__)
bot, admin_conversations = None, None

def initialize_group_actions_handlers(b, conv_dict):
    global bot, admin_conversations
    bot = b
    admin_conversations = conv_dict

def handle_select_plan_for_action(call, params):
    """
    محاسبه تعداد کاربران هر پلن و نمایش منوی داینامیک.
    """
    uid, msg_id = call.from_user.id, call.message.message_id
    _safe_edit(uid, msg_id, "⏳ در حال محاسبه تعداد کاربران هر پلن\\.\\.\\.", reply_markup=None)

    try:
        all_plans = load_service_plans()
        all_users = combined_handler.get_all_users_combined()
        
        plan_counts = {i: 0 for i in range(len(all_plans))}

        for user in all_users:
            h_info = user.get('breakdown', {}).get('hiddify', {})
            m_info = user.get('breakdown', {}).get('marzban', {})
            
            # --- تغییر اصلی اینجاست: مقدار پیش‌فرض به 0.0 تغییر کرد ---
            user_vol_de = h_info.get('usage_limit_GB', 0.0)
            user_vol_fr = m_info.get('usage_limit_GB', 0.0)

            for i, plan in enumerate(all_plans):
                plan_vol_de = float(parse_volume_string(plan.get('volume_de', '0')))
                plan_vol_fr = float(parse_volume_string(plan.get('volume_fr', '0')))
                
                if user_vol_de == plan_vol_de and user_vol_fr == plan_vol_fr:
                    plan_counts[i] += 1
                    break 

        # ساخت منوی داینامیک با تعداد کاربران
        kb = types.InlineKeyboardMarkup(row_width=1)
        for i, plan in enumerate(all_plans):
            plan_name = escape_markdown(plan.get('name', f'پلن {i+1}'))
            count = plan_counts.get(i, 0)
            button_text = f"{plan_name} ({count} کاربر)"
            kb.add(types.InlineKeyboardButton(button_text, callback_data=f"admin:ga_select_type:{i}"))
        
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin:panel"))

        prompt = "لطفاً پلنی که می‌خواهید دستور روی کاربران آن اجرا شود را انتخاب کنید:"
        _safe_edit(uid, msg_id, prompt, reply_markup=kb)

    except Exception as e:
        logger.error(f"Failed to calculate plan user counts: {e}", exc_info=True)
        _safe_edit(uid, msg_id, "❌ خطا در محاسبه تعداد کاربران\\.", reply_markup=menu.admin_panel())

def handle_ask_action_value(call, params):
    action_type, context_type, context_value = params[0], params[1], params[2]
    uid, msg_id = call.from_user.id, call.message.message_id

    convo_data = admin_conversations.get(uid, {})
    if convo_data.get('action_type') == 'advanced_group_action' and convo_data.get('filter_type') == context_value:
        target_users = convo_data.get('target_users', [])
        plan_or_filter_name = f"فیلتر «{context_value.replace('_', ' ')}»"
    
    elif context_type == 'plan':
        plan_index = int(context_value)
        all_plans = load_service_plans()
        selected_plan = all_plans[plan_index]

        plan_vol_de = float(parse_volume_string(selected_plan.get('volume_de', '0')))
        plan_vol_fr = float(parse_volume_string(selected_plan.get('volume_fr', '0')))
        all_users = combined_handler.get_all_users_combined()
        
        target_users = []
        for user in all_users:
            h_info = user.get('breakdown', {}).get('hiddify', {})
            m_info = user.get('breakdown', {}).get('marzban', {})
            user_vol_de = h_info.get('usage_limit_GB', -1.0)
            user_vol_fr = m_info.get('usage_limit_GB', -1.0)
            if user_vol_de == plan_vol_de and user_vol_fr == plan_vol_fr:
                target_users.append(user)
        plan_or_filter_name = f"پلن «{escape_markdown(selected_plan.get('name', ''))}»"

    else:
        _safe_edit(uid, msg_id, "❌ خطای داخلی: اطلاعات زمینه یافت نشد\\.", reply_markup=menu.admin_group_actions_menu())
        return

    if not target_users:
        prompt = f"❌ هیچ کاربری منطبق با {plan_or_filter_name} یافت نشد\\."
        # --- اصلاح: بازگشت به منوی دستورات گروهی ---
        _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_group_actions_menu())
        return

    admin_conversations[uid] = {
        'action_type': action_type,
        'msg_id': msg_id,
        'target_users': target_users
    }

    user_count = len(target_users)
    prompt_map = {"add_gb": "حجم (GB)", "add_days": "تعداد روز"}
    value_type_str = escape_markdown(prompt_map.get(action_type, "مقدار"))

    prompt = (f"شما *{plan_or_filter_name}* را انتخاب کردید (شامل *{user_count}* کاربر)\\.\n\n"
              f"حالا لطفاً مقدار *{value_type_str}* که می‌خواهید به این کاربران اضافه شود را وارد کنید:")
    
    back_cb = "admin:group_action_select_plan" if context_type == 'plan' else "admin:adv_ga_select_filter"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.cancel_action(back_cb))
    bot.register_next_step_handler_by_chat_id(uid, _apply_group_action)

def _apply_group_action(message: types.Message):
    uid, text = message.from_user.id, message.text.strip()
    if uid not in admin_conversations: return
    
    convo_data = admin_conversations.pop(uid, {})
    msg_id = convo_data.get('msg_id')
    action_type = convo_data.get('action_type')
    target_users = convo_data.get('target_users', [])

    if not all([msg_id, action_type, target_users]):
        _safe_edit(uid, msg_id, "❌ خطای داخلی: اطلاعات عملیات ناقص است\\.", reply_markup=menu.admin_group_actions_menu())
        return

    try:
        value = float(text)
    except ValueError:
        _safe_edit(uid, msg_id, "❌ مقدار وارد شده نامعتبر است\\. لطفاً یک عدد وارد کنید\\.", reply_markup=menu.admin_group_actions_menu())
        return

    _safe_edit(uid, msg_id, f"⏳ در حال اجرای دستور روی *{len(target_users)}* کاربر\\.\\.\\.")

    add_gb = value if action_type == 'add_gb' else 0
    add_days = int(value) if action_type == 'add_days' else 0

    success_count, fail_count = 0, 0
    for user in target_users:
        identifier = user.get('uuid') or user.get('username')
        if combined_handler.modify_user_on_all_panels(identifier, add_gb=add_gb, add_days=add_days):
            success_count += 1
        else:
            fail_count += 1

    final_text = (f"✅ عملیات گروهی با موفقیت انجام شد\\.\n\n"
                  f"🔹 به *{success_count}* کاربر اعمال شد\\.\n"
                  f"🔸 عملیات برای *{fail_count}* کاربر ناموفق بود\\.")
    # --- اصلاح: بازگشت به منوی دستورات گروهی ---
    _safe_edit(uid, msg_id, final_text, reply_markup=menu.admin_group_actions_menu())

def handle_select_action_type(call, params):
    plan_index = int(params[0])
    uid, msg_id = call.from_user.id, call.message.message_id
    
    all_plans = load_service_plans()
    selected_plan = all_plans[plan_index]
    plan_name_escaped = escape_markdown(selected_plan.get('name', ''))

    prompt = f"شما پلن *{plan_name_escaped}* را انتخاب کردید\\.\n\nلطفاً نوع دستور مورد نظر را انتخاب کنید:"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_select_action_type_menu(plan_index, 'plan'))


def handle_select_advanced_filter(call, params):
    uid, msg_id = call.from_user.id, call.message.message_id
    prompt = "لطفاً یک فیلتر برای انتخاب گروهی کاربران انتخاب کنید:"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_advanced_group_action_filter_menu())


def handle_select_action_for_filter(call, params):
    filter_type = params[0]
    uid, msg_id = call.from_user.id, call.message.message_id

    _safe_edit(uid, msg_id, "⏳ در حال فیلتر کردن کاربران، لطفاً صبر کنید\\.\\.\\.")

    all_users = combined_handler.get_all_users_combined()
    target_users = []

    if filter_type == 'expiring_soon':
        for user in all_users:
            expire_days = user.get('expire')
            if expire_days is not None and 0 <= expire_days < 3:
                target_users.append(user)
    
    elif filter_type == 'inactive_30_days':
        thirty_days_ago = datetime.now(pytz.utc) - timedelta(days=30)
        for user in all_users:
            last_online = user.get('last_online')
            if not last_online or (isinstance(last_online, datetime) and last_online < thirty_days_ago):
                target_users.append(user)
    
    if not target_users:
        prompt = "❌ هیچ کاربری با این فیلتر یافت نشد\\."
        _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_advanced_group_action_filter_menu())
        return

    admin_conversations[uid] = {
        'action_type': 'advanced_group_action',
        'filter_type': filter_type,
        'target_users': target_users,
        'msg_id': msg_id,
    }

    user_count = len(target_users)
    filter_display_name = escape_markdown(filter_type.replace('_', ' '))
    prompt = (f"✅ *{user_count}* کاربر با فیلتر «{filter_display_name}» یافت شد\\.\n\n"
              f"حالا لطفاً دستوری که می‌خواهید روی این کاربران اجرا شود را انتخاب کنید:")
    
    kb = menu.admin_select_action_type_menu(filter_type, 'filter')
    _safe_edit(uid, msg_id, prompt, reply_markup=kb)