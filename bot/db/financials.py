# bot/db/financials.py

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from .base import DatabaseManager

logger = logging.getLogger(__name__)


class FinancialsDB(DatabaseManager):
    """
    کلاسی برای مدیریت تمام عملیات مربوط به امور مالی، پرداخت‌ها،
    هزینه‌ها و گزارش‌های مالی کل سیستم.
    """

    # --- توابع مربوط به پرداخت‌ها (Payments) ---

    def add_payment_record(self, uuid_id: int) -> bool:
        """یک رکورد پرداخت جدید برای یک UUID مشخص ثبت می‌کند."""
        with self.write_conn() as c:
            c.execute("INSERT INTO payments (uuid_id, payment_date) VALUES (?, ?)",
                      (uuid_id, datetime.now(self.pytz.utc)))
            return True

    def get_payment_counts(self) -> Dict[str, int]:
        """تعداد کل پرداخت‌ها را به ازای هر نام کانفیگ برمی‌گرداند."""
        query = """
            SELECT uu.name, COUNT(p.payment_id) as payment_count
            FROM user_uuids uu
            LEFT JOIN payments p ON uu.id = p.uuid_id
            WHERE uu.is_active = 1
            GROUP BY uu.name
        """
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            return {row['name']: row['payment_count'] for row in rows if row['name']}

    def get_payment_history(self) -> List[Dict[str, Any]]:
        """لیست آخرین پرداخت ثبت‌شده برای تمام کاربران فعال را برمی‌گرداند."""
        query = """
            SELECT uu.name, p.payment_date
            FROM payments p
            JOIN user_uuids uu ON p.uuid_id = uu.id
            WHERE p.payment_date = (SELECT MAX(sub_p.payment_date) FROM payments sub_p WHERE sub_p.uuid_id = p.uuid_id)
            AND uu.is_active = 1
            ORDER BY p.payment_date DESC;
        """
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]

    def get_user_payment_history(self, uuid_id: int) -> List[Dict[str, Any]]:
        """تمام رکوردهای پرداخت برای یک UUID خاص را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute("SELECT payment_date FROM payments WHERE uuid_id = ? ORDER BY payment_date DESC", (uuid_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_all_payments_with_user_info(self) -> List[Dict[str, Any]]:
        """تمام پرداخت‌ها را به همراه اطلاعات کاربر (تلگرام و کانفیگ) برمی‌گرداند."""
        query = """
            SELECT p.payment_id, p.payment_date, uu.name AS config_name, uu.uuid,
                   u.user_id, u.first_name, u.username
            FROM payments p
            JOIN user_uuids uu ON p.uuid_id = uu.id
            LEFT JOIN users u ON uu.user_id = u.user_id
            ORDER BY p.payment_date DESC;
        """
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]

    def get_daily_payment_stats(self, days: int = 30) -> List[Dict[str, Any]]:
        """آمار تعداد پرداخت‌های روزانه را برای نمودار برمی‌گرداند."""
        date_limit = datetime.now(self.pytz.utc) - timedelta(days=days)
        query = """
            SELECT DATE(payment_date) as date, COUNT(payment_id) as count
            FROM payments
            WHERE payment_date >= ?
            GROUP BY date ORDER BY date ASC;
        """
        with self._conn() as c:
            rows = c.execute(query, (date_limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_revenue_by_month(self, months: int = 6) -> List[Dict[str, Any]]:
        """درآمد ماهانه (تعداد پرداخت‌ها) را برای نمودار MRR محاسبه می‌کند."""
        query = f"""
            SELECT strftime('%Y-%m', payment_date) as month, COUNT(payment_id) as revenue_unit
            FROM payments
            GROUP BY month ORDER BY month DESC LIMIT {months};
        """
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            return [dict(r) for r in reversed(rows)]

    def get_user_latest_plan_price(self, uuid_id: int) -> Optional[int]:
        """قیمت آخرین پلن کاربر را با مقایسه حجم فعلی او با پلن‌ها تخمین می‌زند."""
        from ..utils import load_service_plans, parse_volume_string
        from ..combined_handler import get_combined_user_info
        
        uuid_row = self._conn().execute("SELECT uuid FROM user_uuids WHERE id = ?", (uuid_id,)).fetchone()
        if not uuid_row: return None

        user_info = get_combined_user_info(uuid_row['uuid'])
        if not user_info: return None

        current_limit_gb = user_info.get('usage_limit_GB', -1)
        all_plans = load_service_plans()

        for plan in all_plans:
            plan_total_volume = 0
            # منطق محاسبه حجم کل پلن بر اساس نوع آن
            # این بخش ممکن است نیاز به تطبیق با ساختار فایل plans.json شما داشته باشد
            # در اینجا یک پیاده‌سازی نمونه آورده شده است
            if plan.get('type') == 'combined':
                vol_de = parse_volume_string(plan.get('volume_de', '0'))
                vol_fr = parse_volume_string(plan.get('volume_fr', '0'))
                plan_total_volume = vol_de + vol_fr
            else:
                volume_keys = ['volume_de', 'volume_fr', 'volume_tr', 'volume_us', 'volume_ro']
                for key in volume_keys:
                    if key in plan:
                        plan_total_volume = parse_volume_string(plan.get(key, '0'))
                        break
            
            if plan_total_volume == int(current_limit_gb):
                return plan.get('price')
        return None

    def get_total_payments_in_range(self, start_date: datetime, end_date: datetime) -> int:
        """تعداد کل پرداخت‌ها در یک بازه زمانی مشخص را برمی‌گرداند."""
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(payment_id) as count FROM payments WHERE payment_date >= ? AND payment_date < ?",
                (start_date, end_date)
            ).fetchone()
            return row['count'] if row else 0

    def delete_user_payment_history(self, uuid_id: int) -> int:
        """تمام رکوردهای پرداخت یک UUID خاص را حذف کرده و تعداد ردیف‌های حذف شده را برمی‌گرداند."""
        with self._conn() as c:
            cursor = c.execute("DELETE FROM payments WHERE uuid_id = ?", (uuid_id,))
            return cursor.rowcount
            
    # --- توابع مربوط به هزینه‌ها (Costs) ---

    def add_monthly_cost(self, year: int, month: int, cost: float, description: str) -> bool:
        """یک هزینه ماهانه جدید ثبت می‌کند."""
        with self._conn() as c:
            try:
                c.execute(
                    "INSERT INTO monthly_costs (year, month, cost, description) VALUES (?, ?, ?, ?)",
                    (year, month, cost, description)
                )
                return True
            except self.IntegrityError:
                logger.warning(f"Cost entry for {year}-{month} with description '{description}' already exists.")
                return False

    def get_all_monthly_costs(self) -> List[Dict[str, Any]]:
        """تمام هزینه‌های ماهانه ثبت شده را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM monthly_costs ORDER BY year DESC, month DESC").fetchall()
            return [dict(r) for r in rows]

    def get_costs_for_month(self, year: int, month: int) -> List[Dict[str, Any]]:
        """هزینه‌های ثبت شده برای یک ماه و سال مشخص را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, description, cost FROM monthly_costs WHERE year = ? AND month = ?",
                (year, month)
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_monthly_cost(self, cost_id: int) -> bool:
        """یک هزینه ماهانه را با شناسه آن حذف می‌کند."""
        with self._conn() as c:
            cursor = c.execute("DELETE FROM monthly_costs WHERE id = ?", (cost_id,))
            return cursor.rowcount > 0

    # --- توابع مربوط به گزارش‌های مالی (Financial Reports) ---

    def get_monthly_financials(self) -> Dict[str, Any]:
        """خلاصه مالی ماهانه (درآمد، هزینه، سود) را محاسبه می‌کند."""
        with self._conn() as c:
            # محاسبه درآمد از تراکنش‌های کیف پول
            revenue_query = """
                SELECT strftime('%Y-%m', transaction_date) as month, SUM(amount) as total_revenue
                FROM wallet_transactions WHERE type IN ('purchase', 'addon_purchase', 'gift_purchase')
                GROUP BY month
            """
            revenues = {r['month']: abs(r['total_revenue']) for r in c.execute(revenue_query).fetchall()}

            # محاسبه هزینه‌ها
            costs_query = """
                SELECT (year || '-' || printf('%02d', month)) as month, SUM(cost) as total_cost
                FROM monthly_costs GROUP BY month
            """
            costs = {r['month']: r['total_cost'] for r in c.execute(costs_query).fetchall()}
            
            all_months = sorted(list(set(revenues.keys()) | set(costs.keys())), reverse=True)
            monthly_breakdown = []
            total_revenue, total_cost = 0, 0

            for month in all_months:
                revenue = revenues.get(month, 0)
                cost = costs.get(month, 0)
                monthly_breakdown.append({'month': month, 'revenue': revenue, 'cost': cost, 'profit': revenue - cost})
                total_revenue += revenue
                total_cost += cost
            
            all_cost_records = self.get_all_monthly_costs()

            return {
                'total_revenue': total_revenue, 'total_cost': total_cost,
                'total_profit': total_revenue - total_cost,
                'monthly_breakdown': monthly_breakdown, 'all_records': all_cost_records
            }

    def get_transactions_for_month(self, year: int, month: int) -> List[Dict[str, Any]]:
        """تمام تراکنش‌های درآمدی یک ماه و سال مشخص را به همراه نام کاربر برمی‌گرداند."""
        start_date = datetime(year, month, 1)
        end_date = (start_date + timedelta(days=32)).replace(day=1)
        
        query = """
            SELECT wt.id, wt.amount, wt.description, wt.transaction_date, u.user_id, u.first_name
            FROM wallet_transactions wt
            JOIN users u ON wt.user_id = u.user_id
            WHERE wt.transaction_date >= ? AND wt.transaction_date < ? AND wt.amount < 0
            ORDER BY wt.transaction_date DESC
        """
        with self._conn() as c:
            rows = c.execute(query, (start_date, end_date)).fetchall()
            return [dict(r) for r in rows]

    def delete_transaction(self, transaction_id: int) -> bool:
        """یک تراکنش خاص را از تاریخچه کیف پول حذف می‌کند."""
        with self._conn() as c:
            cursor = c.execute("DELETE FROM wallet_transactions WHERE id = ?", (transaction_id,))
            return cursor.rowcount > 0

    def get_all_transactions_for_report(self) -> list:
        """تمام تراکنش‌های مالی را برای گزارش‌گیری جامع برمی‌گرداند."""
        query = "SELECT amount, type, transaction_date FROM wallet_transactions ORDER BY transaction_date"
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            return [dict(r) for r in rows]