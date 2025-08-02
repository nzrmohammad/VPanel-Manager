import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import pytz
import requests
from requests.adapters import HTTPAdapter, Retry
from cachetools import cached
from .config import HIDDIFY_DOMAIN, ADMIN_PROXY_PATH, ADMIN_UUID, API_TIMEOUT, api_cache
from .utils import safe_float

logger = logging.getLogger(__name__)

class HiddifyAPIHandler:
    def __init__(self):
        self.base_url = f"{HIDDIFY_DOMAIN.rstrip('/')}/{ADMIN_PROXY_PATH.strip('/')}/api/v2/admin"
        self.api_key = ADMIN_UUID
        self.tehran_tz = pytz.timezone("Asia/Tehran")
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({"Hiddify-API-Key": self.api_key, "Accept": "application/json"})
        retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        session.mount('https://', adapter)
        return session

    def _request(self, method: str, endpoint: str, **kwargs) -> Optional[Any]:
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.request(method, url, timeout=API_TIMEOUT, **kwargs)
            if response.status_code == 401:
                logger.error(f"Hiddify API request failed: 401 Unauthorized. Check your ADMIN_UUID.")
                return None
            response.raise_for_status()
            return response.json() if response.status_code != 204 else True
        except requests.exceptions.RequestException as e:
            logger.error(f"Hiddify API request failed: {method} {url} - {e}")
            return None

    def _parse_api_datetime(self, date_str: Optional[str]) -> Optional[datetime]:
        if not date_str or date_str.startswith('0001-01-01'):
            return None
        try:
            if 'Z' in date_str or '+' in date_str[10:] or '-' in date_str[10:]:
                clean_str = date_str.replace('Z', '+00:00').split('.')[0]
                dt_obj = datetime.fromisoformat(clean_str)
            else:
                dt_obj = datetime.fromisoformat(date_str.split('.')[0])
                dt_obj = self.tehran_tz.localize(dt_obj)
            return dt_obj
        except (ValueError, TypeError):
            logger.warning(f"Could not parse Hiddify datetime string: {date_str}")
            return None

    def _calculate_remaining_days(self, start_date_str: Optional[str], package_days: Optional[int]) -> Optional[int]:
        if package_days in [None, 0]: return None
        try:
            start_date = datetime.fromisoformat(start_date_str.split('T')[0]).date()
            expiration_date = start_date + timedelta(days=package_days)
            return (expiration_date - datetime.now(self.tehran_tz).date()).days
        except (ValueError, TypeError, AttributeError):
            # Fallback to now if start_date is invalid
            start_date = datetime.now(self.tehran_tz).date()
            expiration_date = start_date + timedelta(days=package_days)
            return (expiration_date - start_date).days

    def _norm(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            if not isinstance(raw, dict): return None
            
            usage_limit = round(safe_float(raw.get("usage_limit_GB", 0)), 3)
            current_usage = round(safe_float(raw.get("current_usage_GB", 0)), 3)
            
            normalized_data = {
                "name": raw.get("name") or "کاربر ناشناس",
                "uuid": raw.get("uuid", "").lower(),
                "is_active": bool(raw.get("enable", False)),
                "last_online": self._parse_api_datetime(raw.get("last_online")),
                "usage_limit_GB": usage_limit,
                "current_usage_GB": current_usage,
                "remaining_GB": max(0, usage_limit - current_usage),
                "usage_percentage": (current_usage / usage_limit * 100) if usage_limit > 0 else 0,
                "expire": self._calculate_remaining_days(raw.get("start_date"), raw.get("package_days")),
                "mode": raw.get("mode", "no_reset")
            }
            return normalized_data

    @cached(api_cache)
    def get_all_users(self) -> List[Dict[str, Any]]:
        """فقط کاربران پنل Hiddify را برمیگرداند."""
        data = self._request("GET", "/user/")
        if not data: return []
        raw_users = data if isinstance(data, list) else data.get("results", []) or data.get("users", [])
        return [norm_user for u in raw_users if (norm_user := self._norm(u))]

    def user_info(self, uuid: str) -> Optional[Dict[str, Any]]:
        """فقط اطلاعات یک کاربر از پنل Hiddify را برمیگرداند."""
        data = self._request("GET", f"/user/{uuid}/")
        return self._norm(data) if data else None

    def add_user(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """یک کاربر جدید فقط در پنل Hiddify اضافه میکند."""
        payload = {
            "name": data.get("name"),
            "usage_limit_GB": data.get("usage_limit_GB", 0),
            "package_days": data.get("package_days", 0),
            "mode": data.get("mode", "no_reset")
        }
        new_user_raw = self._request("POST", "/user/", json=payload)
        return self.user_info(new_user_raw['uuid']) if new_user_raw and new_user_raw.get('uuid') else None

    def modify_user(self, uuid: str, data: dict) -> bool:
        """یک کاربر را فقط در پنل Hiddify ویرایش میکند."""
        return self._request("PATCH", f"/user/{uuid}/", json=data) is not None

    def delete_user(self, uuid: str) -> bool:
        """یک کاربر را فقط از پنل Hiddify حذف میکند."""
        return self._request("DELETE", f"/user/{uuid}/") is True

    def reset_user_usage(self, uuid: str) -> bool:
        """مصرف یک کاربر را فقط در پنل Hiddify صفر میکند."""
        return self.modify_user(uuid, data={"current_usage_GB": 0})

    def get_panel_info(self) -> Optional[Dict[str, Any]]:
        """اطلاعات پنل Hiddify را برمیگرداند."""
        panel_info_url = f"{HIDDIFY_DOMAIN.rstrip('/')}/{ADMIN_PROXY_PATH.strip('/')}/api/v2/panel/info/"
        try:
            response = self.session.get(panel_info_url, timeout=API_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Hiddify API request for panel info failed: {e}")
            return None

    def check_connection(self) -> bool:
        """برای بررسی صحت اتصال و کلید API، اطلاعات پنل را درخواست می‌کند."""
        logger.info("Checking Hiddify panel connection...")
        # از یک اندپوینت سبک برای تست اتصال استفاده می‌کنیم
        panel_info_url = f"{HIDDIFY_DOMAIN.rstrip('/')}/{ADMIN_PROXY_PATH.strip('/')}/api/v2/panel/info/"
        try:
            # از یک تایم‌اوت کوتاه برای این تست استفاده می‌کنیم
            response = self.session.get(panel_info_url, timeout=5)
            response.raise_for_status()
            logger.info("Hiddify connection check successful.")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Hiddify connection check FAILED: {e}")
            return False

hiddify_handler = HiddifyAPIHandler()