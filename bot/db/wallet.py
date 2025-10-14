# bot/db/wallet.py

from datetime import datetime
from typing import Any, Dict, List, Optional
import logging

from .base import DatabaseManager

logger = logging.getLogger(__name__)

class WalletDB(DatabaseManager):
    """
    کلاسی برای مدیریت تمام عملیات مربوط به کیف پول و تراکنش‌ها.
    """

    def update_wallet_balance(self, user_id: int, amount: float, trans_type: str, description: str) -> bool:
        """
        موجودی کیف پول کاربر را به‌روز کرده و یک تراکنش ثبت می‌کند.
        در صورت موفقیت True و در غیر این صورت False برمی‌گرداند.
        """
        with self._conn() as c:
            try:
                # ابتدا موجودی فعلی را برای بررسی واکشی می‌کنیم
                current_balance_row = c.execute("SELECT wallet_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
                if current_balance_row is None:
                    logger.error(f"Attempted to update wallet for non-existent user_id: {user_id}")
                    return False

                current_balance = current_balance_row['wallet_balance']

                # اگر نوع تراکنش خرید است و موجودی کافی نیست، عملیات را متوقف کن
                if trans_type in ['purchase', 'gift_purchase', 'addon_purchase', 'transfer_out'] and current_balance < abs(amount):
                    logger.warning(f"Insufficient balance for user {user_id} to perform '{trans_type}'. Needed: {abs(amount)}, Has: {current_balance}")
                    return False

                # موجودی کاربر را به‌روزرسانی کن
                c.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE user_id = ?", (amount, user_id))

                # یک رکورد جدید در تاریخچه تراکنش‌ها ثبت کن
                c.execute(
                    "INSERT INTO wallet_transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                    (user_id, amount, trans_type, description)
                )
                self.clear_user_cache(user_id)
                logger.info(f"Wallet updated for user {user_id}. Amount: {amount}, Type: {trans_type}.")
                return True
            except Exception as e:
                logger.error(f"Error updating wallet for user {user_id}: {e}", exc_info=True)
                # در صورت بروز خطا، تراکنش به صورت خودکار rollback می‌شود
                return False

    def set_wallet_balance(self, user_id: int, new_balance: float, trans_type: str, description: str) -> bool:
        """
        موجودی کیف پول کاربر را به یک مقدار مشخص تغییر داده و تراکنش را ثبت می‌کند.
        """
        with self._conn() as c:
            try:
                current_balance_row = c.execute("SELECT wallet_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
                if current_balance_row is None:
                    logger.error(f"Attempted to set wallet for non-existent user_id: {user_id}")
                    return False

                amount_changed = new_balance - current_balance_row['wallet_balance']

                c.execute("UPDATE users SET wallet_balance = ? WHERE user_id = ?", (new_balance, user_id))
                c.execute(
                    "INSERT INTO wallet_transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                    (user_id, amount_changed, trans_type, description)
                )
                self.clear_user_cache(user_id)
                return True
            except Exception as e:
                logger.error(f"Error setting wallet balance for user {user_id}: {e}", exc_info=True)
                return False

    def get_wallet_history(self, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """تاریخچه تراکنش‌های کیف پول یک کاربر را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, amount, type, description, transaction_date FROM wallet_transactions WHERE user_id = ? ORDER BY transaction_date DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def create_charge_request(self, user_id: int, amount: float, message_id: int) -> int:
        """یک درخواست شارژ جدید ثبت کرده و شناسه آن را برمی‌گرداند."""
        with self._conn() as c:
            cursor = c.execute(
                "INSERT INTO charge_requests (user_id, amount, message_id) VALUES (?, ?, ?)",
                (user_id, amount, message_id)
            )
            return cursor.lastrowid

    def get_pending_charge_request(self, user_id: int, message_id: int) -> Optional[Dict[str, Any]]:
        """یک درخواست شارژ در حال انتظار را بر اساس شناسه کاربر و پیام برمی‌گرداند."""
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM charge_requests WHERE user_id = ? AND message_id = ? AND is_pending = 1 ORDER BY request_date DESC LIMIT 1",
                (user_id, message_id)
            ).fetchone()
            return dict(row) if row else None

    def get_charge_request_by_id(self, request_id: int) -> Optional[Dict[str, Any]]:
        """یک درخواست شارژ را با شناسه یکتای آن بازیابی می‌کند."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM charge_requests WHERE id = ?", (request_id,)).fetchone()
            return dict(row) if row else None

    def update_charge_request_status(self, request_id: int, is_pending: bool):
        """وضعیت یک درخواست شارژ را به‌روزرسانی می‌کند."""
        with self._conn() as c:
            c.execute("UPDATE charge_requests SET is_pending = ? WHERE id = ?", (int(is_pending), request_id))

    def get_all_users_with_balance(self) -> List[Dict[str, Any]]:
        """تمام کاربرانی که موجودی کیف پول دارند را به ترتیب از بیشترین به کمترین برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT user_id, first_name, wallet_balance FROM users WHERE wallet_balance > 0 ORDER BY wallet_balance DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def reset_all_wallet_balances(self) -> int:
        """موجودی کیف پول تمام کاربران را صفر کرده و تمام تاریخچه تراکنش‌ها را پاک می‌کند."""
        with self._conn() as c:
            c.execute("DELETE FROM wallet_transactions;")
            c.execute("DELETE FROM charge_requests;")
            cursor = c.execute("UPDATE users SET wallet_balance = 0;")
            self._user_cache.clear()
            return cursor.rowcount
            
    def get_wallet_transactions_paginated(self, user_id: int, page: int = 1, per_page: int = 10) -> List[Dict[str, Any]]:
        """لیست تراکنش‌های کیف پول یک کاربر را به صورت صفحه‌بندی شده برمی‌گرداند."""
        offset = (page - 1) * per_page
        with self._conn() as c:
            rows = c.execute(
                "SELECT amount, type, description, transaction_date FROM wallet_transactions WHERE user_id = ? ORDER BY transaction_date DESC LIMIT ? OFFSET ?",
                (user_id, per_page, offset)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_wallet_transactions_count(self, user_id: int) -> int:
        """تعداد کل تراکنش‌های کیف پول یک کاربر را برمی‌گرداند."""
        with self._conn() as c:
            row = c.execute("SELECT COUNT(id) FROM wallet_transactions WHERE user_id = ?", (user_id,)).fetchone()
            return row[0] if row else 0

    def get_user_total_expenses(self, user_id: int) -> float:
        """مجموع کل هزینه‌های یک کاربر (خرید و انتقال) را محاسبه می‌کند."""
        with self._conn() as c:
            # انواع تراکنش‌هایی که هزینه محسوب می‌شوند
            expense_types = ('purchase', 'addon_purchase', 'gift_purchase', 'transfer_out')
            placeholders = ','.join('?' for _ in expense_types)
            query = f"SELECT SUM(amount) FROM wallet_transactions WHERE user_id = ? AND type IN ({placeholders})"
            
            # مقادیر amount برای هزینه منفی هستند، پس abs می‌گیریم
            row = c.execute(query, (user_id, *expense_types)).fetchone()
            return abs(row[0]) if row and row[0] is not None else 0.0

    def get_user_purchase_stats(self, user_id: int) -> dict:
        """آمار خریدهای یک کاربر (تعداد کل خریدها و تعداد هدایا) را محاسبه می‌کند."""
        with self._conn() as c:
            total_purchases_row = c.execute(
                "SELECT COUNT(id) FROM wallet_transactions WHERE user_id = ? AND type IN ('purchase', 'addon_purchase', 'gift_purchase')",
                (user_id,)
            ).fetchone()
            total_purchases = total_purchases_row[0] if total_purchases_row else 0

            gift_purchases_row = c.execute(
                "SELECT COUNT(id) FROM wallet_transactions WHERE user_id = ? AND type = 'gift_purchase'",
                (user_id,)
            ).fetchone()
            gift_purchases = gift_purchases_row[0] if gift_purchases_row else 0
            
            return {
                'total_purchases': total_purchases,
                'gift_purchases': gift_purchases
            }