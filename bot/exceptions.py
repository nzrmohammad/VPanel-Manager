class APIError(Exception):
    """کلاس پایه برای تمام خطاهای مربوط به API پنل‌ها."""
    def __init__(self, message="یک خطای نامشخص در API رخ داد."):
        self.message = message
        super().__init__(self.message)

class APIConnectionError(APIError):
    """برای زمانی که ارتباط با سرور پنل برقرار نمی‌شود."""
    def __init__(self, panel_name="پنل"):
        super().__init__(f"امکان برقراری ارتباط با {panel_name} وجود ندارد. لطفاً از روشن بودن سرور و درستی آدرس آن اطمینان حاصل کنید.")

class APIAuthenticationError(APIError):
    """برای زمانی که اطلاعات ورود (توکن، نام کاربری/رمز عبور) اشتباه است."""
    def __init__(self, panel_name="پنل"):
        super().__init__(f"اطلاعات ورود برای {panel_name} نامعتبر است. لطفاً توکن یا مشخصات ورود را بررسی کنید.")

class UserNotFoundError(APIError):
    """برای زمانی که کاربر مورد نظر در پنل یافت نمی‌شود."""
    def __init__(self, identifier="کاربر"):
        super().__init__(f"کاربری با شناسه '{identifier}' یافت نشد.")

class DuplicateUserError(APIError):
    """برای زمانی که تلاش برای ساخت یک کاربر تکراری وجود دارد."""
    def __init__(self, username):
        super().__init__(f"کاربری با نام کاربری '{username}' از قبل وجود دارد.")