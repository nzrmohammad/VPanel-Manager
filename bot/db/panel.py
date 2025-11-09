# bot/db/panel.py

from typing import Any, Dict, List, Optional
import logging
import sqlite3

from .base import DatabaseManager
from ..config import ACCESS_TEMPLATES

logger = logging.getLogger(__name__)

class PanelDB(DatabaseManager):
    """
    کلاسی برای مدیریت پنل‌ها، مپینگ مرزبان و قالب‌های کانفیگ.
    """

    # --- توابع مربوط به مدیریت پنل‌ها (Panels) ---

    def add_panel(self, name: str, panel_type: str, api_url: str, token1: str, token2: Optional[str] = None) -> bool:
        """یک پنل جدید به دیتابیس اضافه می‌کند."""
        with self._conn() as c:
            try:
                c.execute(
                    "INSERT INTO panels (name, panel_type, api_url, api_token1, api_token2) VALUES (?, ?, ?, ?, ?)",
                    (name, panel_type, api_url, token1, token2)
                )
                return True
            except sqlite3.IntegrityError:
                logger.warning(f"Attempted to add a panel with a duplicate name: {name}")
                return False

    def get_all_panels(self) -> List[Dict[str, Any]]:
        """تمام پنل‌های ثبت شده را از دیتابیس برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM panels ORDER BY name ASC").fetchall()
            return [dict(r) for r in rows]

    def get_active_panels(self) -> List[Dict[str, Any]]:
        """فقط پنل‌های فعال را از دیتابیس برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM panels WHERE is_active = 1 ORDER BY name ASC").fetchall()
            return [dict(r) for r in rows]

    def delete_panel(self, panel_id: int) -> bool:
        """یک پنل را با شناسه آن حذف می‌کند."""
        with self._conn() as c:
            cursor = c.execute("DELETE FROM panels WHERE id = ?", (panel_id,))
            return cursor.rowcount > 0

    def toggle_panel_status(self, panel_id: int) -> bool:
        """وضعیت فعال/غیرفعال یک پنل را تغییر می‌دهد."""
        with self._conn() as c:
            cursor = c.execute("UPDATE panels SET is_active = 1 - is_active WHERE id = ?", (panel_id,))
            return cursor.rowcount > 0

    def get_panel_by_id(self, panel_id: int) -> Optional[Dict[str, Any]]:
        """جزئیات یک پنل را با شناسه آن بازیابی می‌کند."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM panels WHERE id = ?", (panel_id,)).fetchone()
            return dict(row) if row else None
            
    def get_panel_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """جزئیات یک پنل را با نام منحصر به فرد آن بازیابی می‌کند."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM panels WHERE name = ?", (name,)).fetchone()
            return dict(row) if row else None

    def update_panel_name(self, panel_id: int, new_name: str) -> bool:
        """نام یک پنل مشخص را به‌روزرسانی می‌کند."""
        with self._conn() as c:
            try:
                cursor = c.execute("UPDATE panels SET name = ? WHERE id = ?", (new_name, panel_id))
                return cursor.rowcount > 0
            except sqlite3.IntegrityError:
                logger.warning(f"Attempted to rename panel {panel_id} to an existing name: {new_name}")
                return False

    # --- توابع مربوط به مپینگ مرزبان (Marzban Mapping) ---

    def add_marzban_mapping(self, hiddify_uuid: str, marzban_username: str) -> bool:
        """یک ارتباط جدید بین UUID هیدیفای و یوزرنیم مرزبان اضافه می‌کند."""
        with self._conn() as c:
            try:
                c.execute("INSERT OR REPLACE INTO marzban_mapping (hiddify_uuid, marzban_username) VALUES (?, ?)", (hiddify_uuid.lower(), marzban_username))
                return True
            except sqlite3.IntegrityError:
                logger.warning(f"Marzban username '{marzban_username}' might already be mapped.")
                return False

    def get_marzban_username_by_uuid(self, hiddify_uuid: str) -> Optional[str]:
        """یوزرنیم مرزبان را با استفاده از UUID هیدیفای پیدا می‌کند."""
        with self._conn() as c:
            row = c.execute("SELECT marzban_username FROM marzban_mapping WHERE hiddify_uuid = ?", (hiddify_uuid.lower(),)).fetchone()
            return row['marzban_username'] if row else None

    def get_uuid_by_marzban_username(self, marzban_username: str) -> Optional[str]:
        """UUID هیدیفای را با استفاده از یوزرنیم مرزبان پیدا می‌کند."""
        with self._conn() as c:
            row = c.execute("SELECT hiddify_uuid FROM marzban_mapping WHERE marzban_username = ?", (marzban_username,)).fetchone()
            return row['hiddify_uuid'] if row else None

    def get_all_marzban_mappings(self) -> List[Dict[str, str]]:
        """تمام ارتباط‌های مرزبان را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute("SELECT hiddify_uuid, marzban_username FROM marzban_mapping ORDER BY marzban_username").fetchall()
            return [dict(r) for r in rows]

    def delete_marzban_mapping(self, hiddify_uuid: str) -> bool:
        """یک ارتباط را با استفاده از UUID هیدیفای حذف می‌کند."""
        with self._conn() as c:
            res = c.execute("DELETE FROM marzban_mapping WHERE hiddify_uuid = ?", (hiddify_uuid.lower(),))
            return res.rowcount > 0

    # --- توابع مربوط به قالب‌های کانفیگ (Config Templates) ---

    def add_batch_templates(self, templates: list[str]) -> int:
        """لیستی از رشته‌های کانفیگ را به صورت دسته‌ای اضافه می‌کند."""
        if not templates:
            return 0
        with self._conn() as c:
            cursor = c.cursor()
            cursor.executemany("INSERT INTO config_templates (template_str) VALUES (?)", [(tpl,) for tpl in templates])
            return cursor.rowcount

    def update_template(self, template_id: int, new_template_str: str) -> bool:
        """محتوای یک قالب کانفیگ را به‌روزرسانی می‌کند."""
        with self._conn() as c:
            cursor = c.execute("UPDATE config_templates SET template_str = ? WHERE id = ?", (new_template_str, template_id))
            return cursor.rowcount > 0

    def get_all_config_templates(self) -> list[dict]:
        """تمام قالب‌های کانفیگ را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM config_templates ORDER BY id ASC").fetchall()
            return [dict(r) for r in rows]

    def get_active_config_templates(self) -> list[dict]:
        """فقط قالب‌های کانفیگ فعال را برمی‌گرداند."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM config_templates WHERE is_active = 1 ORDER BY id ASC").fetchall()
            return [dict(r) for r in rows]

    def toggle_template_status(self, template_id: int):
        """وضعیت فعال/غیرفعال یک قالب را تغییر می‌دهد."""
        with self._conn() as c:
            c.execute("UPDATE config_templates SET is_active = 1 - is_active WHERE id = ?", (template_id,))

    def delete_template(self, template_id: int):
        """یک قالب کانفیگ را حذف می‌کند."""
        with self._conn() as c:
            c.execute("DELETE FROM config_templates WHERE id = ?", (template_id,))

    def toggle_template_special(self, template_id: int):
        """وضعیت "ویژه" بودن یک قالب را تغییر می‌دهد."""
        with self._conn() as c:
            c.execute("UPDATE config_templates SET is_special = 1 - is_special WHERE id = ?", (template_id,))
    
    def toggle_template_random_pool(self, template_id: int) -> bool:
        """وضعیت عضویت یک قالب در استخر تصادفی را تغییر می‌دهد."""
        with self._conn() as c:
            cursor = c.execute("UPDATE config_templates SET is_random_pool = 1 - is_random_pool WHERE id = ?", (template_id,))
            return cursor.rowcount > 0

    def set_template_server_type(self, template_id: int, server_type: str):
        """نوع سرور یک قالب را تنظیم می‌کند."""
        if server_type not in ['de', 'fr', 'tr', 'us', 'ro', 'supp', 'none']:
            return
        with self._conn() as c:
            c.execute("UPDATE config_templates SET server_type = ? WHERE id = ?", (server_type, template_id))

    def reset_templates_table(self):
        """تمام قالب‌ها را حذف و شمارنده ID را ریست می‌کند."""
        with self._conn() as c:
            c.execute("DELETE FROM config_templates;")
            c.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'config_templates';")
        logger.info("Config templates table has been reset.")

    # --- توابع مربوط به قالب‌های دسترسی ---

    def apply_access_template(self, uuid_id: int, plan_category: str) -> bool:
        """یک قالب دسترسی از پیش تعریف شده را برای یک UUID اعمال می‌کند."""
        template = ACCESS_TEMPLATES.get(plan_category, ACCESS_TEMPLATES.get('default', {}))
        if not template:
            logging.error(f"Access template '{plan_category}' not found, and no default template is set.")
            return False

        with self._conn() as c:
            c.execute("""
                UPDATE user_uuids SET
                    has_access_de = ?, has_access_fr = ?, has_access_tr = ?,
                    has_access_us = ?, has_access_ro = ?, has_access_supp = ?
                WHERE id = ?
            """, (
                int(template.get('has_access_de', False)),
                int(template.get('has_access_fr', False)),
                int(template.get('has_access_tr', False)),
                int(template.get('has_access_us', False)),
                int(template.get('has_access_ro', False)),
                int(template.get('has_access_supp', False)),
                uuid_id
            ))
        logging.info(f"Access template '{plan_category}' applied for uuid_id {uuid_id}.")
        return True
    
    def get_user_config(self, user_uuid_id: int, template_id: int) -> dict | None:
        """کانفیگ تولید شده برای یک کاربر و یک الگوی خاص را بازیابی می‌کند."""
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM user_generated_configs WHERE user_uuid_id = ? AND template_id = ?",
                (user_uuid_id, template_id)
            ).fetchone()
            return dict(row) if row else None

    def add_user_config(self, user_uuid_id: int, template_id: int, generated_uuid: str) -> None:
        """یک رکورد جدید برای UUID تولید شده ثبت می‌کند."""
        with self._conn() as c:
            c.execute(
                "INSERT INTO user_generated_configs (user_uuid_id, template_id, generated_uuid) VALUES (?, ?, ?)",
                (user_uuid_id, template_id, generated_uuid)
            )

    def get_templates_by_pool_status(self) -> tuple[list[dict], list[dict]]:
        """قالب‌ها را به دو دسته عضو و غیرعضو در استخر تصادفی تقسیم می‌کند."""
        all_templates = self.get_active_config_templates()
        random_pool = [tpl for tpl in all_templates if tpl.get('is_random_pool')]
        fixed_pool = [tpl for tpl in all_templates if not tpl.get('is_random_pool')]
        return random_pool, fixed_pool