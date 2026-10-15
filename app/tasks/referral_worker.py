import asyncio
import logging
import random
from typing import Dict, Optional
from pyrogram.errors import FloodWait, RPCError
from pyrogram.raw import functions

from app.core.database import get_session
from app.models.account import Account
from app.models.referral import ReferralJoinJob, ReferralJobStatus, JoinLogStatus
from app.services.client_manager import ClientManager
from app.services.referral_service import ReferralService

logger = logging.getLogger("ReferralWorker")


class ReferralWorker:
    """
    Background worker that executes referral joins sequentially with safe,
    human-like random delays across unused active userbot accounts.
    """

    _active_tasks: Dict[int, asyncio.Task] = {}

    @classmethod
    def start_job_task(cls, job_id: int) -> None:
        """Starts a background execution task for the specified job."""
        if job_id in cls._active_tasks and not cls._active_tasks[job_id].done():
            logger.info(f"Referral Job #{job_id} is already running.")
            return

        task = asyncio.create_task(cls._execute_job(job_id))
        cls._active_tasks[job_id] = task

    @classmethod
    def stop_job_task(cls, job_id: int) -> None:
        """Cancels a running background task if active."""
        task = cls._active_tasks.pop(job_id, None)
        if task and not task.done():
            task.cancel()

    @classmethod
    async def resume_active_jobs(cls) -> None:
        """Resumes any jobs marked as RUNNING upon application startup."""
        async with get_session() as db:
            from sqlalchemy import select
            stmt = select(ReferralJoinJob).where(
                ReferralJoinJob.status.in_([ReferralJobStatus.RUNNING.value, ReferralJobStatus.PENDING.value])
            )
            jobs = list((await db.execute(stmt)).scalars().all())

        for job in jobs:
            logger.info(f"Resuming active Referral Job #{job.id} for @{job.bot_username}...")
            cls.start_job_task(job.id)

    @classmethod
    async def _execute_job(cls, job_id: int) -> None:
        """Main loop that executes referral starts one by one across accounts."""
        try:
            job = await ReferralService.get_job_by_id(job_id)
            if not job or job.status != ReferralJobStatus.RUNNING.value:
                return

            logger.info(f"Started executing Referral Job #{job.id} for @{job.bot_username} (param: '{job.start_param}').")

            while True:
                # Re-verify job status
                job = await ReferralService.get_job_by_id(job_id)
                if not job or job.status != ReferralJobStatus.RUNNING.value:
                    if job and job.status == ReferralJobStatus.PAUSED.value:
                        # Wait while paused
                        await asyncio.sleep(5)
                        continue
                    break

                # Get next unused eligible accounts
                eligible_accounts = await ReferralService.get_eligible_accounts_for_job(job_id, job.bot_username)
                if not eligible_accounts:
                    logger.info(f"Referral Job #{job_id} has processed all available accounts. Marking as COMPLETED.")
                    await ReferralService.update_job_status(job_id, ReferralJobStatus.COMPLETED.value)
                    break

                # Pick the first eligible account
                account = eligible_accounts[0]
                await cls._execute_single_join(job, account)

                # Check if more accounts remain
                remaining = len(eligible_accounts) - 1
                if remaining > 0:
                    d_min = getattr(job, "delay_min", None) or max(5, int(job.delay_seconds * 0.85))
                    d_max = getattr(job, "delay_max", None) or max(d_min + 5, int(job.delay_seconds * 1.15))
                    random_delay = random.uniform(d_min, d_max)
                    logger.info(
                        f"Job #{job_id}: Waiting {random_delay:.1f}s (random range [{d_min}s - {d_max}s]) "
                        f"before next account join ({remaining} remaining)..."
                    )
                    await asyncio.sleep(random_delay)

        except asyncio.CancelledError:
            logger.info(f"Referral Job #{job_id} task was cancelled.")
        except Exception as e:
            logger.error(f"Unexpected error in Referral Job #{job_id}: {e}", exc_info=True)
        finally:
            cls._active_tasks.pop(job_id, None)

    @classmethod
    async def _execute_single_join(cls, job: ReferralJoinJob, account: Account) -> None:
        """Executes start command on the target bot using the given userbot account."""
        bot_user = job.bot_username.lstrip("@").strip()
        client = ClientManager.create_client(
            name=f"ref_worker_{account.id}",
            session_string=account.session_string,
            proxy=account.proxy,
        )

        try:
            await client.connect()
            peer = await client.resolve_peer(bot_user)

            # 1. First attempt: Official MTProto StartBot RPC
            try:
                await client.invoke(
                    functions.messages.StartBot(
                        bot=peer,
                        peer=peer,
                        random_id=client.rnd_id(),
                        start_param=job.start_param or "",
                    )
                )
                logger.info(f"Account #{account.id} successfully executed StartBot on @{bot_user} (param: '{job.start_param}').")
                await ReferralService.record_join_log(
                    job_id=job.id,
                    account_id=account.id,
                    status=JoinLogStatus.SUCCESS.value,
                )
                return
            except Exception as rpc_err:
                logger.warning(f"StartBot RPC failed for account #{account.id} on @{bot_user}: {rpc_err}. Falling back to /start text message...")

            # 2. Fallback attempt: Send /start message directly
            text_cmd = f"/start {job.start_param}".strip() if job.start_param else "/start"
            await client.send_message(chat_id=bot_user, text=text_cmd)
            logger.info(f"Account #{account.id} successfully sent '{text_cmd}' to @{bot_user}.")
            await ReferralService.record_join_log(
                job_id=job.id,
                account_id=account.id,
                status=JoinLogStatus.SUCCESS.value,
            )

        except FloodWait as e:
            err_msg = f"FloodWait: {e.value} seconds"
            logger.warning(f"Account #{account.id} encountered FloodWait on @{bot_user}: {err_msg}")
            await ReferralService.record_join_log(
                job_id=job.id,
                account_id=account.id,
                status=JoinLogStatus.FAILED.value,
                error=err_msg,
            )
        except RPCError as e:
            err_msg = f"RPCError: {e.MESSAGE or str(e)}"
            logger.warning(f"Account #{account.id} failed to join @{bot_user}: {err_msg}")
            await ReferralService.record_join_log(
                job_id=job.id,
                account_id=account.id,
                status=JoinLogStatus.FAILED.value,
                error=err_msg,
            )
        except Exception as e:
            err_msg = f"Error: {str(e)[:200]}"
            logger.error(f"Account #{account.id} join unexpected error on @{bot_user}: {err_msg}")
            await ReferralService.record_join_log(
                job_id=job.id,
                account_id=account.id,
                status=JoinLogStatus.FAILED.value,
                error=err_msg,
            )
        finally:
            if client.is_connected:
                try:
                    await client.disconnect()
                except Exception:
                    pass
