import logging
from telebot import types
from ..database import db
from ..utils import escape_markdown, _safe_edit
from ..menu import menu
from .. import combined_handler
from ..admin_formatters import fmt_admin_user_summary

logger = logging.getLogger(__name__)
bot, admin_conversations = None, None

def initialize_wallet_handlers(b, conv_dict):
    """مقادیر bot و admin_conversations را از فایل اصلی دریافت می‌کند."""
    global bot, admin_conversations
    bot = b
    admin_conversations = conv_dict

def handle_charge_request_callback(call: types.CallbackQuery, params: list):
    """پاسخ ادمین به درخواست شارژ را مدیریت می‌کند و پیام کاربر را ویرایش می‌کند."""
    admin_id = call.from_user.id
    original_caption = call.message.caption or ""
    
    action_parts = call.data.split(':')
    decision = action_parts[1]
    request_id = int(action_parts[2])

    charge_request = db.get_charge_request_by_id(request_id)
    if not charge_request or not charge_request['is_pending']:
        bot.answer_callback_query(call.id, "این درخواست قبلاً پردازش شده است.", show_alert=True)
        bot.edit_message_caption(caption=f"{original_caption}\n\n⚠️ این درخواست قبلا پردازش شده است.", chat_id=admin_id, message_id=call.message.message_id)
        return

    user_id = charge_request['user_id']
    amount = charge_request['amount']
    user_message_id = charge_request['message_id']
    lang_code = db.get_user_language(user_id)

    try:
        if decision == 'charge_confirm':
            # در توضیحات تراکنش، از یک متن عمومی‌تر استفاده می‌کنیم
            if db.update_wallet_balance(user_id, amount, 'deposit', f"شارژ توسط مدیریت (درخواست #{request_id})"):
                db.update_charge_request_status(request_id, is_pending=False)
                
                # ✅ اصلاح اصلی: مبلغ را برای MarkdownV2 آماده‌سازی می‌کنیم
                amount_str = escape_markdown(f"{amount:,.0f}")
                success_text = f"✅ حساب شما به مبلغ *{amount_str} تومان* با موفقیت شارژ شد\\."
                
                # به جای دکمه لغو، دکمه بازگشت به منوی کیف پول را نمایش می‌دهیم
                _safe_edit(user_id, user_message_id, success_text, reply_markup=menu.user_cancel_action("wallet:main", lang_code))
                
                bot.edit_message_caption(caption=f"{original_caption}\n\n✅ تایید شد توسط شما.", chat_id=admin_id, message_id=call.message.message_id)
                bot.answer_callback_query(call.id, "شارژ حساب کاربر تایید شد.", show_alert=True)
            else:
                bot.edit_message_caption(caption=f"{original_caption}\n\n❌ خطا در ثبت شارژ در دیتابیس.", chat_id=admin_id, message_id=call.message.message_id)
                bot.answer_callback_query(call.id, f"❌ خطا در شارژ حساب کاربر {user_id}.", show_alert=True)
                
        elif decision == 'charge_reject':
            db.update_charge_request_status(request_id, is_pending=False)
            
            reject_text = "❌ درخواست شارژ حساب شما توسط ادمین رد شد. لطفاً با پشتیبانی تماس بگیرید."
            
            # ✅ اصلاح اصلی: به جای دکمه لغو، دکمه بازگشت به منوی کیف پول نمایش داده می‌شود
            _safe_edit(user_id, user_message_id, escape_markdown(reject_text), reply_markup=menu.user_cancel_action("wallet:main", lang_code))

            bot.edit_message_caption(caption=f"{original_caption}\n\n❌ توسط شما رد شد.", chat_id=admin_id, message_id=call.message.message_id)
            bot.answer_callback_query(call.id, "درخواست شارژ کاربر رد شد.", show_alert=True)
            
    except Exception as e:
        logger.error(f"Could not edit messages for charge request {request_id}: {e}")
        bot.answer_callback_query(call.id, "عملیات انجام شد اما پیام‌ها قابل ویرایش نبودند.", show_alert=False)

def handle_manual_charge_request(call: types.CallbackQuery, params: list):
    """شروع فرآیند شارژ دستی کیف پول توسط ادمین."""
    uid, msg_id = call.from_user.id, call.message.message_id
    identifier = params[0] # UUID یا username کاربر
    context = "search" if len(params) > 1 and params[1] == 'search' else None
    
    prompt = "لطفاً مبلغ مورد نظر برای شارژ دستی کیف پول کاربر را به تومان وارد کنید:"
    admin_conversations[uid] = {
        'action_type': 'manual_charge',
        'msg_id': msg_id,
        'identifier': identifier,
        'context': context
    }
    
    panel_short = params[2] if len(params) > 2 else 'h'
    back_cb = f"admin:us:{panel_short}:{identifier}"
    if context:
        back_cb += f":{context}"

    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_cancel_action(back_cb))
    bot.register_next_step_handler_by_chat_id(uid, _get_manual_charge_amount)

def _get_manual_charge_amount(message: types.Message):
    """مبلغ شارژ دستی را از ادمین دریافت و تاییدیه می‌گیرد."""
    admin_id, text = message.from_user.id, message.text.strip()
    bot.delete_message(admin_id, message.message_id)
    if admin_id not in admin_conversations: return
    
    convo = admin_conversations[admin_id]
    msg_id = convo['msg_id']
    
    try:
        amount = float(text)
        convo['amount'] = amount
        
        from .. import combined_handler
        user_info = combined_handler.get_combined_user_info(convo['identifier'])
        if not user_info or not user_info.get('uuid'):
            raise ValueError("کاربر یافت نشد یا UUID ندارد.")
            
        user_id = db.get_user_id_by_uuid(user_info['uuid'])
        if not user_id:
            raise ValueError("کاربر در دیتابیس ربات یافت نشد.")
            
        convo['target_user_id'] = user_id
        user_name = user_info.get('name', 'کاربر ناشناس')
        
        confirm_prompt = (f"آیا از شارژ کیف پول کاربر *{escape_markdown(user_name)}* \\(`{user_id}`\\) "
                          f"به مبلغ *{amount:,.0f} تومان* اطمینان دارید؟")
        
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("✅ بله، تایید", callback_data="admin:manual_charge_exec"),
            types.InlineKeyboardButton("❌ خیر، لغو", callback_data="admin:manual_charge_cancel")
        )
        _safe_edit(admin_id, msg_id, confirm_prompt, reply_markup=kb)

    except (ValueError, TypeError):
        _safe_edit(admin_id, msg_id, "❌ مقدار وارد شده نامعتبر است. لطفاً فقط عدد وارد کنید.", reply_markup=menu.admin_panel())
        admin_conversations.pop(admin_id, None)
    except Exception as e:
        _safe_edit(admin_id, msg_id, f"❌ خطایی رخ داد: {escape_markdown(str(e))}", reply_markup=menu.admin_panel())
        admin_conversations.pop(admin_id, None)

def handle_manual_charge_execution(call: types.CallbackQuery, params: list):
    """شارژ دستی را نهایی می‌کند."""
    admin_id = call.from_user.id
    if admin_id not in admin_conversations: return
    
    convo = admin_conversations.pop(admin_id, {})
    msg_id = convo.get('msg_id')
    target_user_id = convo.get('target_user_id')
    amount = convo.get('amount')
    identifier = convo.get('identifier')

    if not all([msg_id, target_user_id, amount, identifier]):
        _safe_edit(admin_id, msg_id, escape_markdown("❌ اطلاعات ناقص است. عملیات لغو شد."), reply_markup=menu.admin_panel())
        return
        
    if db.update_wallet_balance(target_user_id, amount, 'deposit', "شارژ دستی توسط مدیریت"):
        
        success_msg = f"✅ کیف پول کاربر با موفقیت به مبلغ *{amount:,.0f} تومان* شارژ شد\\."
        _safe_edit(admin_id, msg_id, success_msg, reply_markup=menu.admin_panel())
        
        try:
            user_notification = f"✅ حساب شما به مبلغ *{amount:,.0f} تومان* توسط مدیریت شارژ شد\\."
            bot.send_message(target_user_id, user_notification, parse_mode="MarkdownV2")
        except Exception as e:
            logger.warning(f"Could not send manual charge notification to user {target_user_id}: {e}")

    else:
        _safe_edit(admin_id, msg_id, escape_markdown("❌ خطا در به‌روزرسانی موجودی کاربر در دیتابیس."), reply_markup=menu.admin_panel())

def handle_manual_charge_cancel(call: types.CallbackQuery, params: list):
    """(نسخه اصلاح شده) عملیات شارژ دستی را لغو کرده و به صفحه کاربر بازمی‌گردد."""
    admin_id = call.from_user.id
    if admin_id not in admin_conversations: return
    
    convo = admin_conversations.pop(admin_id)
    msg_id = convo.get('msg_id')
    identifier = convo.get('identifier')
    context = convo.get('context')

    if not all([msg_id, identifier]):
        cancel_text = escape_markdown("❌ عملیات شارژ دستی لغو شد.")
        _safe_edit(admin_id, msg_id, cancel_text, reply_markup=menu.admin_panel())
        return

    info = combined_handler.get_combined_user_info(identifier)
    if info:
        db_user = None
        if info.get('uuid'):
            user_telegram_id = db.get_user_id_by_uuid(info['uuid'])
            if user_telegram_id:
                db_user = db.user(user_telegram_id)
        
        text = fmt_admin_user_summary(info, db_user) + "\n\n" + escape_markdown("❌ عملیات شارژ دستی لغو شد.")
        
        panel_type = 'hiddify' if any(p.get('type') == 'hiddify' for p in info.get('breakdown', {}).values()) else 'marzban'
        back_callback = "admin:search_menu" if context == "search" else "admin:management_menu"
        kb = menu.admin_user_interactive_management(identifier, info.get('is_active', False), panel_type, back_callback=back_callback)

        _safe_edit(admin_id, msg_id, text, reply_markup=kb)
    else:
        cancel_text = escape_markdown("❌ عملیات لغو شد و اطلاعات کاربر یافت نشد.")
        _safe_edit(admin_id, msg_id, cancel_text, reply_markup=menu.admin_search_menu())

def handle_manual_withdraw_request(call: types.CallbackQuery, params: list):
    """شروع فرآیند برداشت وجه / صفر کردن موجودی توسط ادمین."""
    uid, msg_id = call.from_user.id, call.message.message_id
    identifier = params[0]
    context = "search" if len(params) > 1 and params[1] == 's' else None
    
    from .. import combined_handler
    user_info = combined_handler.get_combined_user_info(identifier)
    if not user_info or not user_info.get('uuid'):
        bot.answer_callback_query(call.id, "کاربر یافت نشد.", show_alert=True)
        return

    user_id = db.get_user_id_by_uuid(user_info['uuid'])
    user_db = db.user(user_id)
    balance = user_db.get('wallet_balance', 0.0) if user_db else 0.0

    if balance == 0:
        bot.answer_callback_query(call.id, "موجودی این کاربر در حال حاضر صفر است.", show_alert=True)
        return

    admin_conversations[uid] = {
        'action_type': 'manual_withdraw',
        'msg_id': msg_id,
        'identifier': identifier,
        'context': context,
        'target_user_id': user_id,
        'current_balance': balance,
        'user_name': user_info.get('name', 'کاربر ناشناس')
    }
    
    prompt = (f"موجودی فعلی کاربر *{escape_markdown(user_info.get('name', ''))}* مبلغ *{balance:,.0f} تومان* است\\.\n\n"
              f"آیا از صفر کردن موجودی و ثبت تراکنش برداشت برای این کاربر اطمینان دارید؟")

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ بله، تایید برداشت", callback_data="admin:manual_withdraw_exec"),
        types.InlineKeyboardButton("❌ خیر، لغو", callback_data="admin:manual_withdraw_cancel")
    )
    _safe_edit(uid, msg_id, prompt, reply_markup=kb)

def handle_manual_withdraw_execution(call: types.CallbackQuery, params: list):
    """برداشت وجه را نهایی می‌کند."""
    admin_id = call.from_user.id
    if admin_id not in admin_conversations: return
    
    convo = admin_conversations.pop(admin_id, {})
    msg_id = convo.get('msg_id')
    target_user_id = convo.get('target_user_id')
    amount_withdrawn = convo.get('current_balance', 0.0)

    if not all([msg_id, target_user_id]):
        _safe_edit(admin_id, msg_id, "❌ اطلاعات ناقص است. عملیات لغو شد.", reply_markup=menu.admin_panel())
        return
        
    if db.set_wallet_balance(target_user_id, 0.0, 'withdraw', "برداشت توسط مدیریت"):
        success_msg_raw = f"✅ موجودی کاربر با موفقیت صفر شد. تراکنش برداشت به مبلغ {amount_withdrawn:,.0f} تومان ثبت گردید."
        success_msg = escape_markdown(success_msg_raw)
        _safe_edit(admin_id, msg_id, success_msg, reply_markup=menu.admin_panel())
        
        try:
            user_notification_raw = f"✅ مبلغ {amount_withdrawn:,.0f} تومان از کیف پول شما برداشت و موجودی شما صفر شد."
            bot.send_message(target_user_id, escape_markdown(user_notification_raw), parse_mode="MarkdownV2")
        except Exception as e:
            logger.warning(f"Could not send manual withdraw notification to user {target_user_id}: {e}")
    else:
        _safe_edit(admin_id, msg_id, "❌ خطا در صفر کردن موجودی کاربر در دیتابیس.", reply_markup=menu.admin_panel())


def handle_manual_withdraw_cancel(call: types.CallbackQuery, params: list):
    """عملیات برداشت وجه را لغو می‌کند و به صفحه کاربر بازمی‌گردد."""
    admin_id = call.from_user.id
    if admin_id not in admin_conversations: return
    
    convo = admin_conversations.pop(admin_id)
    msg_id = convo.get('msg_id')
    identifier = convo.get('identifier')
    
    from ..admin_handlers.user_management import handle_show_user_summary # Import in-function
    handle_show_user_summary(call, [None, identifier, convo.get('context')])