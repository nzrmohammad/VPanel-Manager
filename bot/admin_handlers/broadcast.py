import logging
import time
from telebot import types
import pytz
from datetime import datetime, timedelta
import re

from ..database import db
from ..hiddify_api_handler import hiddify_handler
from ..marzban_api_handler import marzban_handler
from ..menu import menu
from ..utils import _safe_edit, escape_markdown 
from telebot.apihelper import ApiTelegramException

logger = logging.getLogger(__name__)
bot, admin_conversations = None, None

def initialize_broadcast_handlers(b, conv_dict):
    global bot, admin_conversations
    bot = b
    admin_conversations = conv_dict

def start_broadcast_flow(call, params):
    """
    محاسبه تعداد کاربران هر گروه و نمایش منو با تعداد آن‌ها.
    """
    uid = call.from_user.id
    msg_id = call.message.message_id
    
    # --- اصلاح ۱: Escape کردن سه نقطه انتهای پیام ---
    _safe_edit(uid, msg_id, "⏳ در حال محاسبه تعداد کاربران هر گروه\\.\\.\\.", reply_markup=None)

    try:
        # دریافت همه کاربران از پنل‌ها و دیتابیس
        h_users = hiddify_handler.get_all_users() or []
        m_users = marzban_handler.get_all_users() or []
        all_panel_users = h_users + [u for u in m_users if u.get('uuid')]
        
        uuid_to_user_id_map = db.get_uuid_to_user_id_map()
        all_bot_user_ids = set(db.get_all_user_ids())

        # فیلتر کردن کاربران بر اساس دسته‌بندی
        counts = {}
        now_utc = datetime.now(pytz.utc)
        
        online_uuids = {u['uuid'] for u in all_panel_users if u.get('is_active') and u.get('last_online') and u['last_online'].astimezone(pytz.utc) >= now_utc - timedelta(minutes=3)}
        counts['online'] = len({uuid_to_user_id_map.get(uuid) for uuid in online_uuids if uuid_to_user_id_map.get(uuid)})

        active_1_uuids = {u['uuid'] for u in all_panel_users if u.get('last_online') and u['last_online'].astimezone(pytz.utc) >= now_utc - timedelta(days=1)}
        counts['active_1'] = len({uuid_to_user_id_map.get(uuid) for uuid in active_1_uuids if uuid_to_user_id_map.get(uuid)})

        inactive_7_uuids = {u['uuid'] for u in all_panel_users if u.get('last_online') and 1 <= (now_utc - u['last_online'].astimezone(pytz.utc)).days < 7}
        counts['inactive_7'] = len({uuid_to_user_id_map.get(uuid) for uuid in inactive_7_uuids if uuid_to_user_id_map.get(uuid)})
        
        inactive_0_uuids = {u['uuid'] for u in all_panel_users if not u.get('last_online')}
        counts['inactive_0'] = len({uuid_to_user_id_map.get(uuid) for uuid in inactive_0_uuids if uuid_to_user_id_map.get(uuid)})

        counts['all'] = len(all_bot_user_ids)

        # ساخت منوی داینامیک
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton(f"📣 همه کاربران ربات ({counts['all']})", callback_data="admin:broadcast_target:all"),
            types.InlineKeyboardButton(f"🟢 آنلاین در ۳ دقیقه اخیر ({counts['online']})", callback_data="admin:broadcast_target:online"),
            types.InlineKeyboardButton(f"✅ فعال در ۲۴ ساعت اخیر ({counts['active_1']})", callback_data="admin:broadcast_target:active_1"),
            types.InlineKeyboardButton(f"⚠️ غیرفعال در ۷ روز گذشته ({counts['inactive_7']})", callback_data="admin:broadcast_target:inactive_7"),
            types.InlineKeyboardButton(f"🚫 هرگز متصل نشده ({counts['inactive_0']})", callback_data="admin:broadcast_target:inactive_0"),
            types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin:panel")
        )
        
        prompt = "لطفاً جامعه هدف برای ارسال پیام همگانی را انتخاب کنید:"
        _safe_edit(uid, msg_id, prompt, reply_markup=kb)

    except Exception as e:
        logger.error(f"Failed to calculate broadcast target counts: {e}", exc_info=True)
        _safe_edit(uid, msg_id, "❌ خطا در محاسبه تعداد کاربران\\.", reply_markup=menu.admin_panel())


def ask_for_broadcast_message(call, params):
    target_group = params[0]
    uid, msg_id = call.from_user.id, call.message.message_id
    
    admin_conversations[uid] = {
        'broadcast_target': target_group,
        'msg_id': msg_id
    }
    
    target_names = {
        'all': 'همه کاربران ربات',
        'online': 'آنلاین در ۳ دقیقه اخیر',
        'active_1': 'فعال در ۲۴ ساعت اخیر',
        'inactive_7': 'غیرفعال در ۷ روز گذشته',
        'inactive_0': 'هرگز متصل نشده'
    }
    target_name_fa = target_names.get(target_group, target_group)
    
    prompt = f"پیام شما برای گروه «<b>{target_name_fa}</b>» ارسال خواهد شد.\n\nلطفاً پیام خود را بنویسید:"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_cancel_action("admin:broadcast"), parse_mode="HTML")
    bot.register_next_step_handler_by_chat_id(uid, _send_broadcast)


def _send_broadcast(message: types.Message):
    admin_id = message.from_user.id
    if admin_id not in admin_conversations: return

    convo_data = admin_conversations.pop(admin_id)
    target_group = convo_data.get('broadcast_target')
    original_msg_id = convo_data.get('msg_id')
    
    back_to_broadcast_menu = types.InlineKeyboardMarkup()
    back_to_broadcast_menu.add(types.InlineKeyboardButton("🔙 بازگشت به پیام همگانی", callback_data="admin:broadcast"))

    uuids_to_fetch, target_user_ids = [], []
    
    if target_group != 'all':
        h_users = hiddify_handler.get_all_users() or []
        m_users = marzban_handler.get_all_users() or []
        all_users = h_users + [u for u in m_users if u.get('uuid')]
        
        filtered_users = []
        now_utc = datetime.now(pytz.utc)
        if target_group == 'online':
            deadline = now_utc - timedelta(minutes=3)
            filtered_users = [u for u in all_users if u.get('is_active') and u.get('last_online') and u['last_online'].astimezone(pytz.utc) >= deadline]
        elif target_group == 'active_1':
            deadline = now_utc - timedelta(days=1)
            filtered_users = [u for u in all_users if u.get('last_online') and u['last_online'].astimezone(pytz.utc) >= deadline]
        elif target_group == 'inactive_7':
            filtered_users = [u for u in all_users if u.get('last_online') and 1 <= (now_utc - u['last_online'].astimezone(pytz.utc)).days < 7]
        elif target_group == 'inactive_0':
            filtered_users = [u for u in all_users if not u.get('last_online')]
        
        uuids_to_fetch = [u['uuid'] for u in filtered_users]

    if target_group == 'all':
        target_user_ids = db.get_all_user_ids()
    else:
        target_user_ids = db.get_user_ids_by_uuids(uuids_to_fetch)

    if not target_user_ids:
        safe_text = "هیچ کاربری در گروه هدف یافت نشد\\."
        if original_msg_id:
            _safe_edit(admin_id, original_msg_id, safe_text, reply_markup=back_to_broadcast_menu)
        try:
            bot.delete_message(chat_id=admin_id, message_id=message.message_id)
        except Exception: pass
        return

    unique_targets = set(target_user_ids) - {admin_id}
    
    if not unique_targets:
        safe_text = "هیچ کاربری در گروه هدف یافت نشد (یا فقط شما در این گروه بودید)\\."
        if original_msg_id:
            _safe_edit(admin_id, original_msg_id, safe_text, reply_markup=back_to_broadcast_menu)
        try:
            bot.delete_message(chat_id=admin_id, message_id=message.message_id)
        except Exception: pass
        return
    
    if original_msg_id:
        _safe_edit(admin_id, original_msg_id, f"⏳ شروع ارسال پیام برای {len(unique_targets)} کاربر\\.\\.\\.", parse_mode="MarkdownV2", reply_markup=None)

    success_count, fail_count = 0, 0
    for user_id in unique_targets:
        try:
            bot.copy_message(chat_id=user_id, from_chat_id=admin_id, message_id=message.message_id)
            success_count += 1
            time.sleep(0.1) 
        except ApiTelegramException as e:
            if 'flood control' in e.description.lower():
                try:
                    retry_after = int(re.search(r'retry after (\d+)', e.description).group(1))
                    logger.warning(f"Flood control triggered. Sleeping for {retry_after} seconds.")
                    time.sleep(retry_after)
                    bot.copy_message(chat_id=user_id, from_chat_id=admin_id, message_id=message.message_id)
                    success_count += 1
                except Exception as retry_e:
                    logger.error(f"Failed to send broadcast to {user_id} after flood wait: {retry_e}")
                    fail_count += 1
            else:
                logger.warning(f"Failed to send broadcast to user {user_id}: {e}")
                fail_count += 1
        except Exception as e:
            logger.error(f"An unexpected error occurred sending to {user_id}: {e}")
            fail_count += 1
            
    try:
        bot.delete_message(chat_id=admin_id, message_id=message.message_id)
    except Exception as e:
        logger.warning(f"Could not delete broadcast source message for admin {admin_id}: {e}")

    # --- اصلاح ۲: Escape کردن نقطه در گزارش نهایی ---
    final_report_text = (
        f"✅ *ارسال همگانی به پایان رسید\\.*\n\n"
        f"🔹 *موفقیت‌آمیز :* {success_count}\n"
        f"🔸 *ناموفق :* {fail_count}"
    )
    if original_msg_id:
        _safe_edit(admin_id, original_msg_id, final_report_text, reply_markup=back_to_broadcast_menu)
    else:
        bot.send_message(admin_id, final_report_text, parse_mode='MarkdownV2', reply_markup=back_to_broadcast_menu)