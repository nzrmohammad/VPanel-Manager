# bot/admin_handlers/__init__.py

# وارد کردن همه ماژول‌های هندلر برای دسترسی آسان‌تر
from . import user_management
from . import reporting
from . import broadcast
from . import backup
from . import group_actions
from . import plan_management
from . import panel_management

# این خطوط به پایتون اجازه می‌دهند تا ماژول‌ها را با نامشان بشناسد
__all__ = [
    'user_management',
    'reporting',
    'broadcast',
    'backup',
    'group_actions',
    'plan_management',
    'panel_management'
]