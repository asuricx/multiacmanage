import math
import random
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from sqlalchemy import select, func, delete
from sqlalchemy.orm import selectinload

from app.core.database import get_session
from app.models.account import Account, AccountStatus
from app.core.database import get_session
from app.models.account import Account, AccountStatus
from app.models.reaction import ReactionJob, ReactionJobStatus, ReactionStat
from app.services.client_manager import ClientManager
from pyrogram.raw import functions, types


class ReactionService:
    """
    Manages Smart Reaction jobs, emoji distributions, and statistics.
    """

    DEFAULT_EMOJIS = ["👍", "❤️", "🔥", "🥰", "👏", "🎉", "🤩", "🙏", "👌", "💯", "🤔", "😍"]

    @classmethod
    async def get_channel_available_reactions(cls, target_channel: str) -> List[str]:
        """
        Inspects the public channel and retrieves allowed reaction emojis.
        If channel allows all reactions, returns default top reaction emojis.
        """
        clean_channel = target_channel.strip()
        if "t.me/" in clean_channel:
            clean_channel = clean_channel.split("t.me/")[-1].split("/")[0]
        if not clean_channel.startswith("@") and not clean_channel.startswith("-100"):
            clean_channel = "@" + clean_channel

        # Retrieve one active account to query channel metadata
        async with get_session() as db:
            stmt = select(Account).options(selectinload(Account.proxy)).where(Account.status == AccountStatus.ACTIVE.value).limit(1)
            acc = (await db.execute(stmt)).scalar_one_or_none()

        if not acc:
            return cls.DEFAULT_EMOJIS

        client = ClientManager.create_client(
            name="reaction_inspector",
            session_string=acc.session_string,
            proxy=acc.proxy,
        )

        try:
            await client.connect()
            peer = await client.resolve_peer(clean_channel)
            full_chat_res = await client.invoke(functions.channels.GetFullChannel(channel=peer))
            avail = full_chat_res.full_chat.available_reactions

            if isinstance(avail, types.ChatReactionsSome) and avail.reactions:
                allowed = []
                for r in avail.reactions:
                    if hasattr(r, "emoticon") and r.emoticon:
                        allowed.append(r.emoticon)
                if allowed:
                    return allowed

            # If all reactions allowed or None
            return cls.DEFAULT_EMOJIS

        except Exception:
            return cls.DEFAULT_EMOJIS
        finally:
            if client.is_connected:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    @classmethod
    async def create_job(
        cls,
        target_channel: str,
        emoji_distribution: Dict[str, int],
        delay_min: int = 30,
        delay_max: int = 180,
        days_range: int = 3,
    ) -> ReactionJob:
        """Creates and stores a new ReactionJob in DB."""
        clean_channel = target_channel.strip()
        if "t.me/" in clean_channel:
            clean_channel = clean_channel.split("t.me/")[-1].split("/")[0]
        if not clean_channel.startswith("@") and not clean_channel.startswith("-100"):
            clean_channel = "@" + clean_channel

        async with get_session() as db:
            job = ReactionJob(
                target_channel=clean_channel,
                emoji_distribution=emoji_distribution,
                delay_min=delay_min,
                delay_max=delay_max,
                days_range=days_range,
                status=ReactionJobStatus.RUNNING.value,
            )
            db.add(job)
            await db.flush()
            await db.refresh(job)
            return job

    @classmethod
    async def get_paginated_jobs(cls, page: int = 1, page_size: int = 6) -> Tuple[List[ReactionJob], int, int]:
        async with get_session() as db:
            count_stmt = select(func.count(ReactionJob.id))
            total = (await db.execute(count_stmt)).scalar() or 0

            offset = (page - 1) * page_size
            stmt = (
                select(ReactionJob)
                .options(selectinload(ReactionJob.stats))
                .order_by(ReactionJob.id.desc())
                .offset(offset)
                .limit(page_size)
            )
            jobs = (await db.execute(stmt)).scalars().all()
            total_pages = (total + page_size - 1) // page_size if total > 0 else 1
            return list(jobs), total, total_pages

    @classmethod
    async def get_job_by_id(cls, job_id: int) -> Optional[ReactionJob]:
        async with get_session() as db:
            stmt = select(ReactionJob).options(selectinload(ReactionJob.stats)).where(ReactionJob.id == job_id)
            return (await db.execute(stmt)).scalar_one_or_none()

    @classmethod
    async def get_active_running_jobs(cls) -> List[ReactionJob]:
        async with get_session() as db:
            stmt = select(ReactionJob).where(ReactionJob.status == ReactionJobStatus.RUNNING.value)
            return list((await db.execute(stmt)).scalars().all())

    @classmethod
    async def update_job_status(cls, job_id: int, new_status: str) -> bool:
        async with get_session() as db:
            stmt = select(ReactionJob).where(ReactionJob.id == job_id)
            job = (await db.execute(stmt)).scalar_one_or_none()
            if job:
                job.status = new_status
                return True
            return False

    @classmethod
    async def delete_job(cls, job_id: int) -> bool:
        async with get_session() as db:
            stmt = select(ReactionJob).where(ReactionJob.id == job_id)
            job = (await db.execute(stmt)).scalar_one_or_none()
            if job:
                await db.delete(job)
                return True
            return False

    @classmethod
    async def record_reaction_stat(cls, job_id: int, message_id: int, reaction_increment: int = 1) -> None:
        async with get_session() as db:
            stmt = select(ReactionStat).where(
                ReactionStat.job_id == job_id,
                ReactionStat.message_id == message_id,
            )
            stat = (await db.execute(stmt)).scalar_one_or_none()
            if stat:
                stat.total_reactions += reaction_increment
            else:
                new_stat = ReactionStat(
                    job_id=job_id,
                    message_id=message_id,
                    total_reactions=reaction_increment,
                )
                db.add(new_stat)

    @classmethod
    async def has_reacted_to_message(cls, job_id: int, message_id: int) -> bool:
        async with get_session() as db:
            stmt = select(ReactionStat).where(
                ReactionStat.job_id == job_id,
                ReactionStat.message_id == message_id,
            )
            stat = (await db.execute(stmt)).scalar_one_or_none()
            return stat is not None and stat.total_reactions > 0

    @classmethod
    def calculate_emoji_assignments(
        cls,
        accounts: List[Account],
        emoji_distribution: Dict[str, int],
    ) -> List[Tuple[Account, str]]:
        """
        Maps each available account to an emoji according to percentage distribution.
        Handles both large account fleets and single/small account setups with
        true weighted random sampling so accounts don't repeatedly pick the same emoji.
        """
        if not accounts or not emoji_distribution:
            return []

        total_accounts = len(accounts)
        emojis = list(emoji_distribution.keys())
        weights = [max(1, int(emoji_distribution[em])) for em in emojis]
        total_weight = sum(weights) or 100

        # Exact quota allocation for fleets
        emoji_pool: List[str] = []
        for em, w in zip(emojis, weights):
            count = int(math.floor(total_accounts * (w / total_weight)))
            emoji_pool.extend([em] * count)

        # For remaining slots (e.g. 1 account or rounding remainder),
        # sample randomly according to the percentage weights
        remainder = total_accounts - len(emoji_pool)
        if remainder > 0:
            extra = random.choices(emojis, weights=weights, k=remainder)
            emoji_pool.extend(extra)
        elif remainder < 0:
            emoji_pool = emoji_pool[:total_accounts]

        # Shuffle for organic non-predictable distribution
        shuffled_accounts = list(accounts)
        random.shuffle(shuffled_accounts)
        random.shuffle(emoji_pool)

        return list(zip(shuffled_accounts, emoji_pool))

