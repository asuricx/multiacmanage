import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse
from sqlalchemy import select, func, update, delete
from sqlalchemy.orm import selectinload

from app.core.database import get_session
from app.models.account import Account, AccountStatus
from app.models.referral import ReferralJoinJob, ReferralJobStatus, JoinLog, JoinLogStatus


class ReferralService:
    """
    Manages Referral Bot Join jobs, duplicate prevention, and execution logs.
    """

    @classmethod
    def parse_bot_and_param(cls, input_text: str) -> Tuple[str, Optional[str]]:
        """
        Parses bot username and start parameter from plain text or Telegram URL.
        Examples:
        - 'https://t.me/DogesBot?start=r_123456' -> ('DogesBot', 'r_123456')
        - 't.me/tapswap_bot?startapp=ref_abc' -> ('tapswap_bot', 'ref_abc')
        - '@major_bot' -> ('major_bot', None)
        - 'major_bot ref_999' -> ('major_bot', 'ref_999')
        """
        text = input_text.strip()

        # Handle Telegram URLs (https://t.me/... or tg://resolve?...)
        if "t.me/" in text or "telegram.me/" in text:
            parsed = urlparse(text if "://" in text else f"https://{text}")
            path_parts = parsed.path.strip("/").split("/")
            bot_user = path_parts[0] if path_parts else ""
            query = parse_qs(parsed.query)
            start_param = query.get("start", [None])[0] or query.get("startapp", [None])[0]
            clean_bot = bot_user.lstrip("@").strip()
            return clean_bot, start_param

        # Handle two space-separated words: e.g. "@bot_name param123"
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            return parts[0].lstrip("@").strip(), parts[1].strip()

        # Single username
        return text.lstrip("@").strip(), None

    @classmethod
    def calculate_delays_from_duration(
        cls,
        accounts_count: int,
        duration_minutes: int,
    ) -> Tuple[int, int]:
        """
        Calculates random delay_min and delay_max so that `accounts_count`
        accounts complete their joins distributed organically across `duration_minutes`.
        Example: 100 accounts in 60 minutes (3600 seconds)
        Average interval = 3600 / 100 = 36 seconds.
        Range = (18s, 54s) -> expected total = 3600s = 1 hour!
        """
        if accounts_count <= 1:
            return 10, 30

        total_seconds = max(60, duration_minutes * 60)
        avg_interval = total_seconds / accounts_count

        delay_min = max(5, int(avg_interval * 0.5))
        delay_max = max(delay_min + 5, int(avg_interval * 1.5))
        return delay_min, delay_max

    @classmethod
    def parse_timing_input(cls, raw_text: str, accounts_count: int = 1) -> Optional[Tuple[int, int, Optional[int]]]:
        """
        Parses user input into (delay_min, delay_max, target_duration_minutes).
        Formats supported:
        - Range: '20-80', '30 - 90', '20 تا 80', '20 to 80'
        - Duration: '1h', '2h', '1.5h', '30m', '90m', '1 ساعت', '30 دقیقه'
        - Single number: '45'
        Also supports Persian/Arabic digits (e.g. '۱ ساعت', '۲۰-۸۰').
        """
        text = raw_text.strip().lower()
        # Normalize Persian & Arabic numerals to English digits
        persian_arabic_digits = {
            "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
            "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
            "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
            "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
        }
        for k, v in persian_arabic_digits.items():
            text = text.replace(k, v)

        # 1. Range format: '20-90', '20 - 90', '20 تا 90', '20 to 90'
        range_match = re.search(r"^(\d+)\s*(?:-|–|_|to|تا|\s)\s*(\d+)$", text)
        if range_match:
            d_min = int(range_match.group(1))
            d_max = int(range_match.group(2))
            return max(5, min(d_min, d_max)), max(5, max(d_min, d_max)), None

        # 2. Duration with units (hours or minutes)
        h_match = re.search(r"^([\d.]+)\s*(?:h|hour|hours|ساعت)$", text)
        if h_match:
            hours = float(h_match.group(1))
            minutes = max(1, int(hours * 60))
            d_min, d_max = cls.calculate_delays_from_duration(accounts_count, minutes)
            return d_min, d_max, minutes

        m_match = re.search(r"^(\d+)\s*(?:m|min|mins|دقیقه)$", text)
        if m_match:
            minutes = max(1, int(m_match.group(1)))
            d_min, d_max = cls.calculate_delays_from_duration(accounts_count, minutes)
            return d_min, d_max, minutes

        # 3. Simple number of seconds
        if text.isdigit():
            sec = int(text)
            d_min = max(5, int(sec * 0.8))
            d_max = max(d_min + 2, int(sec * 1.2))
            return d_min, d_max, None

        return None

    @classmethod
    async def create_job(
        cls,
        bot_username: str,
        start_param: Optional[str] = None,
        delay_min: int = 30,
        delay_max: int = 90,
        target_duration_minutes: Optional[int] = None,
    ) -> ReferralJoinJob:
        """Creates a new ReferralJoinJob in DB with randomized delay ranges."""
        clean_bot = bot_username.lstrip("@").strip()
        delay_min = max(5, delay_min)
        delay_max = max(delay_min, delay_max)
        avg_delay = (delay_min + delay_max) // 2

        async with get_session() as db:
            job = ReferralJoinJob(
                bot_username=clean_bot,
                start_param=start_param.strip() if start_param else None,
                delay_seconds=avg_delay,
                delay_min=delay_min,
                delay_max=delay_max,
                target_duration_minutes=target_duration_minutes,
                status=ReferralJobStatus.RUNNING.value,
            )
            db.add(job)
            await db.flush()
            await db.refresh(job)
            return job

    @classmethod
    async def get_paginated_jobs(cls, page: int = 1, page_size: int = 6) -> Tuple[List[ReferralJoinJob], int, int]:
        """Returns paginated list of referral jobs with total count and pages."""
        async with get_session() as db:
            count_stmt = select(func.count(ReferralJoinJob.id))
            total = (await db.execute(count_stmt)).scalar() or 0

            offset = (page - 1) * page_size
            stmt = (
                select(ReferralJoinJob)
                .options(selectinload(ReferralJoinJob.logs))
                .order_by(ReferralJoinJob.id.desc())
                .offset(offset)
                .limit(page_size)
            )
            jobs = (await db.execute(stmt)).scalars().all()
            total_pages = (total + page_size - 1) // page_size if total > 0 else 1
            return list(jobs), total, total_pages

    @classmethod
    async def get_job_by_id(cls, job_id: int) -> Optional[ReferralJoinJob]:
        """Retrieves a single referral job by ID with logs eager-loaded."""
        async with get_session() as db:
            stmt = (
                select(ReferralJoinJob)
                .options(selectinload(ReferralJoinJob.logs))
                .where(ReferralJoinJob.id == job_id)
            )
            return (await db.execute(stmt)).scalar_one_or_none()

    @classmethod
    async def update_job_status(cls, job_id: int, new_status: str) -> bool:
        """Updates the lifecycle status of a referral job."""
        async with get_session() as db:
            stmt = select(ReferralJoinJob).where(ReferralJoinJob.id == job_id)
            job = (await db.execute(stmt)).scalar_one_or_none()
            if job:
                job.status = new_status
                return True
            return False

    @classmethod
    async def delete_job(cls, job_id: int) -> bool:
        """Deletes a referral job and its associated logs."""
        async with get_session() as db:
            stmt = select(ReferralJoinJob).where(ReferralJoinJob.id == job_id)
            job = (await db.execute(stmt)).scalar_one_or_none()
            if job:
                await db.delete(job)
                return True
            return False

    @classmethod
    async def get_eligible_accounts_for_job(cls, job_id: int, bot_username: str) -> List[Account]:
        """
        Finds all active accounts that have NOT yet successfully started this target bot.
        Guarantees that an account will never execute duplicate referral starts on the same bot.
        """
        clean_bot = bot_username.lstrip("@").strip()

        async with get_session() as db:
            # Subquery: account IDs that have already successfully joined this bot (in this or previous jobs)
            already_joined_stmt = (
                select(JoinLog.account_id)
                .join(ReferralJoinJob, JoinLog.job_id == ReferralJoinJob.id)
                .where(
                    ReferralJoinJob.bot_username == clean_bot,
                    JoinLog.status == JoinLogStatus.SUCCESS.value,
                )
            )
            used_account_ids = (await db.execute(already_joined_stmt)).scalars().all()

            # Select active accounts excluding already used ones
            stmt = (
                select(Account)
                .options(selectinload(Account.proxy))
                .where(
                    Account.status == AccountStatus.ACTIVE.value,
                    Account.id.notin_(used_account_ids) if used_account_ids else True,
                )
                .order_by(Account.id.asc())
            )
            eligible_accounts = (await db.execute(stmt)).scalars().all()
            return list(eligible_accounts)

    @classmethod
    async def record_join_log(
        cls,
        job_id: int,
        account_id: int,
        status: str,
        error: Optional[str] = None,
    ) -> JoinLog:
        """Records an execution attempt for an account on a referral job."""
        async with get_session() as db:
            log_entry = JoinLog(
                job_id=job_id,
                account_id=account_id,
                status=status,
                error=error[:500] if error else None,
                executed_at=datetime.now(timezone.utc),
            )
            db.add(log_entry)
            await db.flush()
            await db.refresh(log_entry)
            return log_entry

    @classmethod
    async def get_job_stats(cls, job_id: int) -> Dict[str, int]:
        """Calculates success, failure, and remaining stats for a job."""
        job = await cls.get_job_by_id(job_id)
        if not job:
            return {"total": 0, "success": 0, "failed": 0, "remaining": 0}

        async with get_session() as db:
            # Counts from logs
            success_stmt = (
                select(func.count(JoinLog.id))
                .where(JoinLog.job_id == job_id, JoinLog.status == JoinLogStatus.SUCCESS.value)
            )
            success_count = (await db.execute(success_stmt)).scalar() or 0

            failed_stmt = (
                select(func.count(JoinLog.id))
                .where(JoinLog.job_id == job_id, JoinLog.status == JoinLogStatus.FAILED.value)
            )
            failed_count = (await db.execute(failed_stmt)).scalar() or 0

            # Eligible remaining
            eligible = await cls.get_eligible_accounts_for_job(job_id, job.bot_username)
            remaining_count = len(eligible)

            return {
                "total": success_count + failed_count + remaining_count,
                "success": success_count,
                "failed": failed_count,
                "remaining": remaining_count,
            }

    @classmethod
    async def get_job_paginated_logs(
        cls, job_id: int, page: int = 1, page_size: int = 8
    ) -> Tuple[List[JoinLog], int, int]:
        """Retrieves paginated logs for a specific referral job."""
        async with get_session() as db:
            count_stmt = select(func.count(JoinLog.id)).where(JoinLog.job_id == job_id)
            total = (await db.execute(count_stmt)).scalar() or 0

            offset = (page - 1) * page_size
            stmt = (
                select(JoinLog)
                .where(JoinLog.job_id == job_id)
                .order_by(JoinLog.id.desc())
                .offset(offset)
                .limit(page_size)
            )
            logs = (await db.execute(stmt)).scalars().all()
            total_pages = (total + page_size - 1) // page_size if total > 0 else 1
            return list(logs), total, total_pages

    @classmethod
    async def get_referral_summary(cls) -> Dict[str, int]:
        """Dashboard overview summary of referral jobs."""
        async with get_session() as db:
            total_jobs_stmt = select(func.count(ReferralJoinJob.id))
            total_jobs = (await db.execute(total_jobs_stmt)).scalar() or 0

            running_jobs_stmt = (
                select(func.count(ReferralJoinJob.id))
                .where(ReferralJoinJob.status == ReferralJobStatus.RUNNING.value)
            )
            running_jobs = (await db.execute(running_jobs_stmt)).scalar() or 0

            total_joins_stmt = (
                select(func.count(JoinLog.id))
                .where(JoinLog.status == JoinLogStatus.SUCCESS.value)
            )
            total_joins = (await db.execute(total_joins_stmt)).scalar() or 0

            return {
                "total_jobs": total_jobs,
                "running_jobs": running_jobs,
                "total_joins": total_joins,
            }
