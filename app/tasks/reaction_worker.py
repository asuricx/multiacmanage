import asyncio
import logging
import random
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from pyrogram.errors import FloodWait, RPCError

from app.core.database import get_session
from app.models.account import Account, AccountStatus
from app.models.reaction import ReactionJob, ReactionJobStatus
from app.services.client_manager import ClientManager
from app.services.reaction_service import ReactionService

logger = logging.getLogger("ReactionWorker")


class ReactionWorker:
    """
    Executes reactions with human-like randomized delays and emoji percentage distributions.
    """

    @classmethod
    async def process_message_reactions(
        cls,
        job_id: int,
        target_channel: str,
        message_id: int,
    ) -> None:
        """
        Distributes reactions across active userbot accounts with randomized delays.
        """
        job = await ReactionService.get_job_by_id(job_id)
        if not job or job.status != ReactionJobStatus.RUNNING.value:
            return

        if await ReactionService.has_reacted_to_message(job_id, message_id):
            logger.info(f"Job #{job_id}: Message #{message_id} in {target_channel} already reacted. Skipping.")
            return

        # Fetch active accounts
        async with get_session() as db:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            stmt = (
                select(Account)
                .options(selectinload(Account.proxy))
                .where(Account.status == AccountStatus.ACTIVE.value)
            )
            accounts = list((await db.execute(stmt)).scalars().all())

        if not accounts:
            logger.warning(f"No active accounts available to react for Job #{job_id}.")
            return

        assignments = ReactionService.calculate_emoji_assignments(accounts, job.emoji_distribution)
        logger.info(
            f"Scheduling {len(assignments)} reactions for post #{message_id} in {target_channel} (Job #{job_id})."
        )

        for account, emoji in assignments:
            # Random delay within specified window (human-like behavior)
            delay = random.uniform(job.delay_min, job.delay_max)
            asyncio.create_task(
                cls._dispatch_delayed_reaction(
                    account=account,
                    target_channel=target_channel,
                    message_id=message_id,
                    emoji=emoji,
                    delay_seconds=delay,
                    job_id=job_id,
                )
            )

    @classmethod
    async def _dispatch_delayed_reaction(
        cls,
        account: Account,
        target_channel: str,
        message_id: int,
        emoji: str,
        delay_seconds: float,
        job_id: int,
    ) -> None:
        """Waits for delay and sends reaction through account's Kurigram client."""
        await asyncio.sleep(delay_seconds)

        # Re-check job status after delay
        job = await ReactionService.get_job_by_id(job_id)
        if not job or job.status != ReactionJobStatus.RUNNING.value:
            return

        client = ClientManager.create_client(
            name=f"reaction_acc_{account.id}",
            session_string=account.session_string,
            proxy=account.proxy,
        )

        try:
            await client.connect()
            await client.send_reaction(
                chat_id=target_channel,
                message_id=message_id,
                emoji=emoji,
            )
            logger.info(f"Account #{account.id} reacted {emoji} to {target_channel}#{message_id}")
            await ReactionService.record_reaction_stat(job_id, message_id, reaction_increment=1)

        except FloodWait as e:
            logger.warning(f"Account #{account.id} FloodWait: {e.value}s on reaction.")
        except RPCError as e:
            logger.warning(f"Account #{account.id} failed to react: {e.MESSAGE or str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error reacting with account #{account.id}: {e}")
        finally:
            if client.is_connected:
                try:
                    await client.disconnect()
                except Exception:
                    pass


class ReactionWatcher:
    """
    Single Watcher that monitors public channels for active reaction jobs.
    Runs periodically without requiring userbots to join public channels.
    """

    _running = False

    @classmethod
    async def start_watcher_loop(cls, poll_interval_seconds: int = 45):
        """Monitors all active running jobs."""
        if cls._running:
            return
        cls._running = True
        logger.info("Starting Single Watcher for Reaction Jobs...")

        while cls._running:
            try:
                active_jobs = await ReactionService.get_active_running_jobs()
                if active_jobs:
                    await cls._check_channels_posts(active_jobs)
            except Exception as e:
                logger.error(f"Error in ReactionWatcher loop: {e}")

            await asyncio.sleep(poll_interval_seconds)

    @classmethod
    def stop(cls):
        cls._running = False

    @classmethod
    async def _check_channels_posts(cls, jobs: List[ReactionJob]):
        """Checks latest posts in each target channel."""
        # Get one healthy active account to serve as the watcher client
        async with get_session() as db:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            stmt = (
                select(Account)
                .options(selectinload(Account.proxy))
                .where(Account.status == AccountStatus.ACTIVE.value)
                .limit(1)
            )
            watcher_acc = (await db.execute(stmt)).scalar_one_or_none()

        if not watcher_acc:
            return

        client = ClientManager.create_client(
            name="single_channel_watcher",
            session_string=watcher_acc.session_string,
            proxy=watcher_acc.proxy,
        )

        try:
            await client.connect()
            now = datetime.now(timezone.utc)

            for job in jobs:
                if job.status != ReactionJobStatus.RUNNING.value:
                    continue

                channel = job.target_channel
                logger.info(f"Checking posts for Reaction Job #{job.id} on channel {channel}...")

                try:
                    found_messages = []
                    async for message in client.get_chat_history(channel, limit=10):
                        if not message or not message.id:
                            continue
                        if getattr(message, "service", False):
                            continue
                        found_messages.append(message)

                    if not found_messages:
                        logger.info(f"No messages retrieved from {channel}.")
                        continue

                    for idx, message in enumerate(found_messages):
                        msg_dt = message.date
                        now_ts = now.timestamp()
                        age_days = 0.0
                        if msg_dt:
                            if msg_dt.tzinfo is None:
                                msg_dt = msg_dt.replace(tzinfo=timezone.utc)
                            age_days = max(0.0, (now - msg_dt).total_seconds() / 86400.0)

                        if job.days_range == 0:
                            # Days=0: Always react to latest message (idx 0), and any newer post
                            is_newest = (idx == 0)
                            is_recent = False
                            if job.created_at and msg_dt:
                                job_cr = job.created_at if job.created_at.tzinfo else job.created_at.replace(tzinfo=timezone.utc)
                                is_recent = (msg_dt >= job_cr)
                            if not (is_newest or is_recent):
                                continue
                        else:
                            if age_days > job.days_range:
                                continue

                        # Check if already reacted
                        already_done = await ReactionService.has_reacted_to_message(job.id, message.id)
                        if not already_done:
                            logger.info(f"Job #{job.id}: Dispatched reactions for post #{message.id} in {channel}")
                            await ReactionWorker.process_message_reactions(
                                job_id=job.id,
                                target_channel=channel,
                                message_id=message.id,
                            )

                except Exception as e:
                    logger.warning(f"Error watching channel {channel}: {e}")

        except Exception as e:
            logger.error(f"Watcher client connection error: {e}")
        finally:
            if client.is_connected:
                try:
                    await client.disconnect()
                except Exception:
                    pass
