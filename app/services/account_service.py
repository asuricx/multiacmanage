import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from sqlalchemy import select, func, delete
from sqlalchemy.orm import selectinload

from app.core.database import get_session
from app.core.exceptions import SessionConversionError
from app.models.account import Account, AccountStatus
from app.models.proxy import Proxy
from app.services.client_manager import ClientManager
from app.services.proxy_service import ProxyService
from app.utils.session_converter import SessionConverter


class AccountService:
    """
    Core service for managing Telegram userbot accounts: conversion, health verification,
    batch imports, and cleanup.
    """

    @classmethod
    async def add_single_session_string(
        cls,
        raw_session_str: str,
        proxy_id: Optional[int] = None,
    ) -> Tuple[bool, str, Optional[dict]]:
        """
        Converts a single session string, tests its connection to Telegram, and persists it in DB.
        """
        try:
            converted_str, detected_format = SessionConverter.convert_string_to_kurigram(raw_session_str)
        except SessionConversionError as e:
            return False, f"خطای تبدیل فرمت سشن: {e}", None

        async with get_session() as db:
            proxy = None
            if proxy_id:
                p_stmt = select(Proxy).where(Proxy.id == proxy_id)
                proxy = (await db.execute(p_stmt)).scalar_one_or_none()

            # Live verification with Telegram servers
            is_healthy, user_dict, err_msg = await ClientManager.verify_session(
                session_string=converted_str,
                proxy=proxy,
            )

            status = AccountStatus.ACTIVE.value if is_healthy else AccountStatus.INVALID.value
            if err_msg and ("بن" in err_msg or "Banned" in err_msg or "مسدود" in err_msg):
                status = AccountStatus.BANNED.value
            elif err_msg and "FloodWait" in err_msg:
                status = AccountStatus.FLOOD_WAIT.value

            user_id = user_dict.get("user_id")

            # Check if account already exists
            existing = None
            if user_id:
                stmt = select(Account).where(Account.user_id == user_id)
                existing = (await db.execute(stmt)).scalar_one_or_none()

            if existing:
                existing.session_string = user_dict.get("session_string", converted_str)
                existing.session_format = detected_format
                existing.first_name = user_dict.get("first_name", existing.first_name)
                existing.username = user_dict.get("username", existing.username)
                existing.phone = user_dict.get("phone", existing.phone)
                existing.status = status
                existing.proxy_id = proxy_id or existing.proxy_id
                existing.last_checked_at = datetime.now(timezone.utc)
                existing.error_message = err_msg
                acc_id = existing.id
            else:
                new_acc = Account(
                    phone=user_dict.get("phone"),
                    user_id=user_id,
                    first_name=user_dict.get("first_name"),
                    username=user_dict.get("username"),
                    session_string=user_dict.get("session_string", converted_str),
                    session_format=detected_format,
                    status=status,
                    proxy_id=proxy_id,
                    last_checked_at=datetime.now(timezone.utc),
                    error_message=err_msg,
                )
                db.add(new_acc)
                await db.flush()
                acc_id = new_acc.id

            result_info = {
                "account_id": acc_id,
                "user_id": user_id,
                "first_name": user_dict.get("first_name"),
                "phone": user_dict.get("phone"),
                "username": user_dict.get("username"),
                "status": status,
                "detected_format": detected_format,
            }

            if is_healthy:
                return True, "اکانت با موفقیت اعتبارسنجی و ثبت گردید.", result_info
            return False, f"سشن ذخیره شد اما در تست ناموفق بود: {err_msg}", result_info

    @classmethod
    async def batch_add_from_text(
        cls,
        text: str,
        proxy_id: Optional[int] = None,
    ) -> Tuple[int, int, List[dict]]:
        """
        Parses all sessions in text, runs individual health checks, and returns detailed results.
        """
        candidates = SessionConverter.extract_multiple_sessions_from_text(text)
        if not candidates:
            return 0, 0, []

        success_count = 0
        fail_count = 0
        details = []

        for idx, candidate in enumerate(candidates, start=1):
            short_preview = candidate[:12] + "..." + candidate[-8:]
            ok, msg, res_data = await cls.add_single_session_string(candidate, proxy_id=proxy_id)
            if ok:
                success_count += 1
                details.append({
                    "index": idx,
                    "preview": short_preview,
                    "success": True,
                    "message": msg,
                    "info": res_data,
                })
            else:
                fail_count += 1
                details.append({
                    "index": idx,
                    "preview": short_preview,
                    "success": False,
                    "message": msg,
                    "info": res_data,
                })

        return success_count, fail_count, details

    @classmethod
    async def add_from_session_file(
        cls,
        file_bytes_or_path,
        proxy_id: Optional[int] = None,
    ) -> Tuple[bool, str, Optional[dict]]:
        """Converts SQLite .session file and stores account."""
        try:
            converted_str, detected_format = SessionConverter.convert_sqlite_file_to_kurigram(file_bytes_or_path)
        except SessionConversionError as e:
            return False, f"خطای استخراج فایل سشن: {e}", None

        return await cls.add_single_session_string(converted_str, proxy_id=proxy_id)

    @classmethod
    async def get_paginated_accounts(
        cls,
        page: int = 1,
        page_size: int = 8,
    ) -> Tuple[List[Account], int, int]:
        """Returns paginated account list, total accounts, and total pages."""
        async with get_session() as db:
            count_stmt = select(func.count(Account.id))
            total = (await db.execute(count_stmt)).scalar() or 0

            offset = (page - 1) * page_size
            stmt = select(Account).options(selectinload(Account.proxy)).order_by(Account.id.desc()).offset(offset).limit(page_size)
            accounts = (await db.execute(stmt)).scalars().all()

            total_pages = (total + page_size - 1) // page_size if total > 0 else 1
            return list(accounts), total, total_pages

    @classmethod
    async def get_account_by_id(cls, account_id: int) -> Optional[Account]:
        async with get_session() as db:
            stmt = select(Account).options(selectinload(Account.proxy)).where(Account.id == account_id)
            return (await db.execute(stmt)).scalar_one_or_none()

    @classmethod
    async def test_single_account(cls, account_id: int) -> Tuple[bool, str]:
        """
        Tests account health with assigned proxy (with auto-rotation fallback).
        """
        async with get_session() as db:
            stmt = select(Account).options(selectinload(Account.proxy)).where(Account.id == account_id)
            acc = (await db.execute(stmt)).scalar_one_or_none()
            if not acc:
                return False, "اکانت مورد نظر یافت نشد."

            proxy = acc.proxy
            is_healthy, user_dict, err_msg = await ClientManager.verify_session(
                session_string=acc.session_string,
                proxy=proxy,
            )

            # Auto-rotate if failure seems proxy-related
            if not is_healthy and err_msg and ("پروکسی" in err_msg or "Timeout" in err_msg):
                rotated = await ProxyService.rotate_proxy_for_account(acc.id)
                if rotated:
                    # Retry with new proxy
                    is_healthy, user_dict, err_msg = await ClientManager.verify_session(
                        session_string=acc.session_string,
                        proxy=rotated,
                    )

            if is_healthy:
                acc.status = AccountStatus.ACTIVE.value
                acc.error_message = None
                if user_dict.get("first_name"):
                    acc.first_name = user_dict["first_name"]
                if user_dict.get("username"):
                    acc.username = user_dict["username"]
                if user_dict.get("phone"):
                    acc.phone = user_dict["phone"]
            else:
                if err_msg and ("بن" in err_msg or "Banned" in err_msg):
                    acc.status = AccountStatus.BANNED.value
                elif err_msg and "FloodWait" in err_msg:
                    acc.status = AccountStatus.FLOOD_WAIT.value
                else:
                    acc.status = AccountStatus.INVALID.value
                acc.error_message = err_msg

            acc.last_checked_at = datetime.now(timezone.utc)
            return is_healthy, err_msg or "اکانت فعال و سالم است."

    @classmethod
    async def test_all_accounts(cls) -> Dict[str, int]:
        """Runs health checks on all registered accounts concurrently."""
        async with get_session() as db:
            stmt = select(Account.id)
            account_ids = (await db.execute(stmt)).scalars().all()

        results = {"total": len(account_ids), "active": 0, "banned": 0, "invalid": 0, "flood_wait": 0}

        async def _check(acc_id: int):
            ok, _ = await cls.test_single_account(acc_id)
            async with get_session() as check_db:
                a_stmt = select(Account.status).where(Account.id == acc_id)
                st = (await check_db.execute(a_stmt)).scalar()
                if st == AccountStatus.ACTIVE.value:
                    results["active"] += 1
                elif st == AccountStatus.BANNED.value:
                    results["banned"] += 1
                elif st == AccountStatus.FLOOD_WAIT.value:
                    results["flood_wait"] += 1
                else:
                    results["invalid"] += 1

        tasks = [_check(a_id) for a_id in account_ids]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        return results

    @classmethod
    async def cleanup_broken_accounts(cls) -> int:
        """Purges all accounts with BANNED or INVALID status."""
        async with get_session() as db:
            stmt = delete(Account).where(
                Account.status.in_([AccountStatus.BANNED.value, AccountStatus.INVALID.value])
            )
            res = await db.execute(stmt)
            return res.rowcount or 0

    @classmethod
    async def get_accounts_summary(cls) -> Dict[str, int]:
        """Returns statistics breakdown of accounts."""
        async with get_session() as db:
            stmt = select(
                func.count(Account.id).label("total"),
                func.count().filter(Account.status == AccountStatus.ACTIVE.value).label("active"),
                func.count().filter(Account.status == AccountStatus.BANNED.value).label("banned"),
                func.count().filter(Account.status == AccountStatus.FLOOD_WAIT.value).label("flood_wait"),
                func.count().filter(Account.status == AccountStatus.INVALID.value).label("invalid"),
            )
            row = (await db.execute(stmt)).one()
            return {
                "total": row.total or 0,
                "active": row.active or 0,
                "banned": row.banned or 0,
                "flood_wait": row.flood_wait or 0,
                "invalid": row.invalid or 0,
            }

    @classmethod
    async def delete_account(cls, account_id: int) -> bool:
        async with get_session() as db:
            stmt = select(Account).where(Account.id == account_id)
            acc = (await db.execute(stmt)).scalar_one_or_none()
            if acc:
                await db.delete(acc)
                return True
            return False
