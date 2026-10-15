import asyncio
from typing import Optional, Tuple
from pyrogram import Client
from pyrogram.errors import (
    AuthKeyUnregistered,
    UserDeactivated,
    UserDeactivatedBan,
    SessionPasswordNeeded,
    FloodWait,
    RPCError,
)

from app.core.config import settings
from app.core.exceptions import (
    AccountAuthError,
    AccountBannedError,
    AccountFloodWaitError,
    PlatformError,
)
from app.models.proxy import Proxy


class ClientManager:
    """
    Manager for creating, executing, and cleaning up Kurigram MTProto client instances.
    """

    @classmethod
    def create_client(
        cls,
        name: str,
        session_string: Optional[str] = None,
        proxy: Optional[Proxy] = None,
    ) -> Client:
        """Instantiates an in-memory Kurigram Client."""
        proxy_dict = None
        if proxy and proxy.is_active:
            try:
                p_cand = proxy.to_kurigram_dict()
                if p_cand.get("scheme") == "mtproxy" and not p_cand.get("secret"):
                    proxy_dict = None
                else:
                    proxy_dict = p_cand
            except Exception:
                proxy_dict = None

        return Client(
            name=name,
            api_id=settings.API_ID,
            api_hash=settings.API_HASH,
            session_string=session_string,
            in_memory=True,
            proxy=proxy_dict,
        )

    @classmethod
    async def verify_session(
        cls,
        session_string: str,
        proxy: Optional[Proxy] = None,
        timeout: int = 15,
    ) -> Tuple[bool, dict, Optional[str]]:
        """
        Connects using the session string, invokes get_me(), and retrieves user profile details.
        Returns: (is_healthy, user_dict, error_message)
        """
        client = cls.create_client(
            name="session_verifier",
            session_string=session_string,
            proxy=proxy,
        )

        try:
            # Connect with timeout
            await asyncio.wait_for(client.connect(), timeout=timeout)
            me = await asyncio.wait_for(client.get_me(), timeout=timeout)

            # Export latest modern Kurigram session string if needed
            latest_session_str = await client.export_session_string()

            user_data = {
                "user_id": me.id,
                "first_name": me.first_name,
                "username": me.username,
                "phone": me.phone_number,
                "session_string": latest_session_str or session_string,
            }
            return True, user_data, None

        except UserDeactivated:
            return False, {}, "حساب کاربری غیرفعال (Deactivated) شده است."
        except UserDeactivatedBan:
            return False, {}, "حساب کاربری از سمت تلگرام مسدود و بن (Banned) شده است."
        except AuthKeyUnregistered:
            return False, {}, "سشن منقضی شده یا از دستگاه‌های دیگر ابطال (Terminated) شده است."
        except FloodWait as e:
            return False, {}, f"محدودیت زمانی تلگرام (FloodWait): باید {e.value} ثانیه صبر کنید."
        except asyncio.TimeoutError:
            return False, {}, "تایم‌اوت در اتصال به سرورهای تلگرام (احتمال قطعی یا فیلترینگ پروکسی)."
        except RPCError as e:
            return False, {}, f"خطای تلگرام: {e.MESSAGE or str(e)}"
        except Exception as e:
            return False, {}, f"خطای ناشناخته در بررسی سشن: {str(e)[:80]}"
        finally:
            if client.is_connected:
                try:
                    await client.disconnect()
                except Exception:
                    pass
