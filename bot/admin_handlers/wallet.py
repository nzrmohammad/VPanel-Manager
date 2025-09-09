# bot/admin_handlers/wallet.py
import logging
from telebot import types
from ..database import db
from ..utils import escape_markdown

logger = logging.getLogger(__name__)
bot, admin_conversations = None, None

def initialize_wallet_handlers(b, conv_dict):
    """مقادیر bot و admin_conversations را از فایل اصلی دریافت می‌کند."""
    global bot, admin_conversations
    bot = b
    admin_conversations = conv_dict

def handle_charge_request_callback(call: types.CallbackQuery, params: list):
    """پاسخ ادمین به درخواست شارژ را مدیریت می‌کند."""
    admin_id = call.from_user.id
    original_caption = call.message.caption or ""
    
    # ✅ FIX: Determine action from call.data and parse params safely
    action_parts = call.data.split(':')
    decision = action_parts[1]  # 'charge_confirm' or 'charge_reject'
    user_id = int(action_parts[2])

    try:
        if decision == 'charge_confirm':
            amount = float(action_parts[3])
            if db.update_wallet_balance(user_id, amount, 'deposit', f"شارژ توسط ادمین {admin_id}"):
                try:
                    bot.send_message(user_id, f"✅ حساب شما به مبلغ {amount:,.0f} تومان با موفقیت شارژ شد.")
                    bot.edit_message_caption(caption=f"{original_caption}\n\n✅ تایید شد توسط شما.", chat_id=admin_id, message_id=call.message.message_id)
                    bot.answer_callback_query(call.id, f"✅ شارژ حساب کاربر {user_id} تایید شد.", show_alert=True)
                except Exception as e:
                    logger.error(f"Failed to send confirmation message to user {user_id}: {e}")
                    bot.edit_message_caption(caption=f"{original_caption}\n\n⚠️ شارژ ثبت شد، اما ارسال پیام به کاربر ناموفق بود.", chat_id=admin_id, message_id=call.message.message_id)
                    bot.answer_callback_query(call.id, f"⚠️ شارژ ثبت شد، اما ارسال پیام به کاربر ناموفق بود.", show_alert=True)
            else:
                bot.edit_message_caption(caption=f"{original_caption}\n\n❌ خطا در ثبت شارژ در دیتابیس.", chat_id=admin_id, message_id=call.message.message_id)
                bot.answer_callback_query(call.id, f"❌ خطا در شارژ حساب کاربر {user_id}.", show_alert=True)
                
        elif decision == 'charge_reject':
            try:
                bot.send_message(user_id, "❌ درخواست شارژ حساب شما توسط ادمین رد شد. لطفاً با پشتیبانی تماس بگیرید.")
                bot.edit_message_caption(caption=f"{original_caption}\n\n❌ توسط شما رد شد.", chat_id=admin_id, message_id=call.message.message_id)
                bot.answer_callback_query(call.id, f"❌ درخواست شارژ کاربر {user_id} رد شد.", show_alert=True)
            except Exception as e:
                logger.error(f"Failed to send rejection message to user {user_id}: {e}")
                bot.edit_message_caption(caption=f"{original_caption}\n\n⚠️ درخواست رد شد، اما ارسال پیام به کاربر ناموفق بود.", chat_id=admin_id, message_id=call.message.message_id)
                bot.answer_callback_query(call.id, "پیام رد درخواست به کاربر ارسال نشد.", show_alert=True)
    except Exception as e:
        logger.error(f"Could not edit admin charge confirmation message: {e}")
        bot.answer_callback_query(call.id, "عملیات انجام شد اما پیام اصلی قابل ویرایش نبود.", show_alert=False)