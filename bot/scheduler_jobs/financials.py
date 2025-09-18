import logging
from datetime import datetime, timedelta
from bot.database import db

logger = logging.getLogger(__name__)

def renew_monthly_costs_job():
    """
    هزینه‌های ماه قبل را برای ماه جاری به صورت خودکار تمدید می‌کند.
    این تابع در روز اول هر ماه میلادی اجرا می‌شود.
    """
    try:
        today = datetime.now()
        # محاسبه ماه و سال قبل
        first_day_of_current_month = today.replace(day=1)
        last_day_of_previous_month = first_day_of_current_month - timedelta(days=1)
        prev_month = last_day_of_previous_month.month
        prev_year = last_day_of_previous_month.year

        logger.info(f"Running monthly cost renewal job for {today.year}-{today.month}. Checking costs from {prev_year}-{prev_month}.")

        # گرفتن هزینه‌هایی که در ماه قبل ثبت شده‌اند
        costs_from_last_month = db.get_costs_for_month(prev_year, prev_month)

        if not costs_from_last_month:
            logger.info("No costs found from the previous month to renew.")
            return

        added_count = 0
        for cost_item in costs_from_last_month:
            # افزودن هزینه برای ماه جاری
            success = db.add_monthly_cost(today.year, today.month, cost_item['cost'], cost_item['description'])
            if success:
                added_count += 1
                logger.info(f"Renewed cost '{cost_item['description']}' for the current month.")

        logger.info(f"Monthly cost renewal job finished. Renewed {added_count} cost entries.")

    except Exception as e:
        logger.error(f"Error in renew_monthly_costs_job: {e}", exc_info=True)