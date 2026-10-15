import asyncio
import re
from typing import Dict, Optional, Tuple
from pyrogram import Client
from pyrogram.errors import (
    FloodWait,
    PasswordHashInvalid,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    PhoneNumberBanned,
    PhoneNumberInvalid,
    SessionPasswordNeeded,
)

from app.core.config import settings
from app.core.database import get_session
from app.models.account import Account, AccountStatus
from app.utils.fsm import FSMManager


class LoginSession:
    def __init__(self, client: Client, phone: str, phone_code_hash: str):
        self.client = client
        self.phone = phone
        self.phone_code_hash = phone_code_hash
        self.created_at = asyncio.get_event_loop().time()


class LoginWizard:
    """
    Manages stateful interactive Telegram login via phone number, code, and 2FA password.
    """

    _active_sessions: Dict[int, LoginSession] = {}

    @classmethod
    async def cancel_login(cls, admin_id: int) -> None:
        """Terminates any active login session for the admin."""
        session = cls._active_sessions.pop(admin_id, None)
        if session and session.client and session.client.is_connected:
            try:
                await session.client.disconnect()
            except Exception:
                pass
        await FSMManager.clear_state(admin_id)

    @classmethod
    async def start_login(cls, admin_id: int, phone: str) -> Tuple[bool, str]:
        """
        Validates phone, establishes client, and sends authentication code.
        """
        # Cancel any previous session
        await cls.cancel_login(admin_id)

        clean_phone = re.sub(r"[^\d+]", "", phone)
        if not clean_phone.startswith("+"):
            clean_phone = "+" + clean_phone

        client = Client(
            name=f"wizard_{admin_id}",
            api_id=settings.API_ID,
            api_hash=settings.API_HASH,
            in_memory=True,
        )

        try:
            await client.connect()
            sent_code = await client.send_code(clean_phone)
            cls._active_sessions[admin_id] = LoginSession(
                client=client,
                phone=clean_phone,
                phone_code_hash=sent_code.phone_code_hash,
            )

            await FSMManager.set_state(
                admin_id,
                state="WAITING_LOGIN_CODE",
                data={"phone": clean_phone},
            )

            return True, (
                f"✅ کد تأیید تلگرام با موفقیت برای شماره `{clean_phone}` ارسال شد.\n\n"
                f"لطفاً کد دریافتی را ارسال کنید (برای جلوگیری از تداخل تلگرام، می‌توانید با فاصله ارسال کنید، مثلاً: `1 2 3 4 5`):"
            )

        except PhoneNumberInvalid:
            await client.disconnect()
            return False, "❌ شماره تلفن ارسال شده نامعتبر است."
        except PhoneNumberBanned:
            await client.disconnect()
            return False, "❌ این شماره تلفن از سمت تلگرام مسدود و بن (Banned) شده است."
        except FloodWait as e:
            await client.disconnect()
            return False, f"⏳ این شماره با محدودیت زمانی تلگرام مواجه است. لطفاً {e.value} ثانیه دیگر مجدداً تلاش کنید."
        except Exception as e:
            if client.is_connected:
                await client.disconnect()
            return False, f"❌ خطا در ارسال کد: {e}"

    @classmethod
    async def submit_code(cls, admin_id: int, code: str) -> Tuple[str, str, Optional[dict]]:
        """
        Submits login code. Handles 2FA, invalid code, or complete success.
        Returns: (status, message, result_dict)
        Status values: 'SUCCESS', '2FA_REQUIRED', 'INVALID_CODE', 'ERROR'
        """
        session = cls._active_sessions.get(admin_id)
        if not session or not session.client:
            return "ERROR", "❌ نشست ورود منقضی شده یا یافت نشد. لطفاً از ابتدا تلاش کنید.", None

        clean_code = re.sub(r"\D", "", code)
        if not clean_code:
            return "INVALID_CODE", "❌ کد وارد شده خالی یا نامعتبر است. لطفاً فقط ارقام را ارسال کنید.", None

        client = session.client
        try:
            await client.sign_in(
                phone_number=session.phone,
                phone_code_hash=session.phone_code_hash,
                phone_code=clean_code,
            )
            return await cls._finalize_login(admin_id, client, session.phone)

        except SessionPasswordNeeded:
            await FSMManager.set_state(
                admin_id,
                state="WAITING_2FA_PASSWORD",
                data={"phone": session.phone},
            )
            return (
                "2FA_REQUIRED",
                "🔐 این اکانت دارای تایید هویت دو مرحله‌ای (2FA) است.\n\nلطفاً رمز عبور دو مرحله‌ای اکانت را ارسال کنید:",
                None,
            )

        except PhoneCodeInvalid:
            return "INVALID_CODE", "❌ کد وارد شده اشتباه است. لطفاً کد را مجدداً بررسی و ارسال فرمایید.", None
        except PhoneCodeExpired:
            await cls.cancel_login(admin_id)
            return "ERROR", "❌ کد ورود منقضی شده است. لطفاً فرآیند را از ابتدا آغاز کنید.", None
        except FloodWait as e:
            await cls.cancel_login(admin_id)
            return "ERROR", f"⏳ محدودیت زمانی تلگرام: لطفاً {e.value} ثانیه صبر کنید.", None
        except Exception as e:
            await cls.cancel_login(admin_id)
            return "ERROR", f"❌ خطا در هنگام ورود: {e}", None

    @classmethod
    async def submit_password(cls, admin_id: int, password: str) -> Tuple[str, str, Optional[dict]]:
        """
        Submits 2FA password and finalizes login.
        """
        session = cls._active_sessions.get(admin_id)
        if not session or not session.client:
            return "ERROR", "❌ نشست ورود منقضی شده است. لطفاً از ابتدا شروع کنید.", None

        client = session.client
        try:
            await client.check_password(password.strip())
            return await cls._finalize_login(admin_id, client, session.phone)
        except PasswordHashInvalid:
            return "INVALID_CODE", "❌ رمز عبور دو مرحله‌ای اشتباه است. لطفاً مجدداً امتحان کنید:", None
        except FloodWait as e:
            await cls.cancel_login(admin_id)
            return "ERROR", f"⏳ محدودیت زمانی تلگرام: {e.value} ثانیه صبر کنید.", None
        except Exception as e:
            await cls.cancel_login(admin_id)
            return "ERROR", f"❌ خطا در اعتبارسنجی رمز دو مرحله‌ای: {e}", None

    @classmethod
    async def _finalize_login(cls, admin_id: int, client: Client, phone: str) -> Tuple[str, str, dict]:
        """Exports session string, retrieves user profile, saves in DB."""
        try:
            me = await client.get_me()
            session_string = await client.export_session_string()

            # Save / update in database
            async with get_session() as db:
                from sqlalchemy import select
                stmt = select(Account).where(Account.user_id == me.id)
                res = await db.execute(stmt)
                existing = res.scalar_one_or_none()

                if existing:
                    existing.phone = phone
                    existing.first_name = me.first_name
                    existing.username = me.username
                    existing.session_string = session_string
                    existing.session_format = "PHONE_LOGIN"
                    existing.status = AccountStatus.ACTIVE.value
                    existing.error_message = None
                    account_id = existing.id
                else:
                    new_acc = Account(
                        phone=phone,
                        user_id=me.id,
                        first_name=me.first_name,
                        username=me.username,
                        session_string=session_string,
                        session_format="PHONE_LOGIN",
                        status=AccountStatus.ACTIVE.value,
                    )
                    db.add(new_acc)
                    await db.flush()
                    account_id = new_acc.id

            await cls.cancel_login(admin_id)

            data = {
                "account_id": account_id,
                "user_id": me.id,
                "first_name": me.first_name,
                "username": me.username,
                "phone": phone,
            }
            msg = (
                f"🎉 اکانت با موفقیت وارد شد و در سیستم ذخیره گردید!\n\n"
                f"👤 نام: {me.first_name or '-'}\n"
                f"🆔 شناسه: `{me.id}`\n"
                f"📞 شماره: `{phone}`\n"
                f"🔗 یوزرنیم: @{me.username or '-'}\n"
                f"🟢 وضعیت: فعال (ACTIVE)"
            )
            return "SUCCESS", msg, data

        except Exception as e:
            await cls.cancel_login(admin_id)
            return "ERROR", f"❌ خطا در ذخیره‌سازی نهایی اکانت: {e}", None
