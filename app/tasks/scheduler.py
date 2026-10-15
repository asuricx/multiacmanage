import logging
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client

from app.core.config import settings
from app.services.proxy_service import ProxyService
from app.services.account_service import AccountService
from app.services.backup_service import BackupService

logger = logging.getLogger("Scheduler")

scheduler = AsyncIOScheduler()


async def scheduled_proxy_health_check():
    """Runs periodic health check on all proxies in pool, cleans dead ones and refreshes assignments."""
    logger.info("Executing scheduled proxy health check...")
    try:
        active, dead = await ProxyService.test_all_proxies()
        if dead > 0:
            deleted = await ProxyService.cleanup_dead_proxies()
            await ProxyService.auto_assign_proxies()
            logger.info(f"Proxy check: {active} active, {deleted} dead proxies removed and accounts reassigned.")
        else:
            logger.info(f"Proxy check completed: {active} active, 0 dead.")
    except Exception as e:
        logger.error(f"Error in scheduled proxy check: {e}")


async def scheduled_proxy_sync_pipeline():
    """
    Every 12 hours (twice daily):
    Scrapes fresh proxies (messages + inline buttons), health-checks pool,
    removes dead proxies, and connects healthy proxies to accounts (falls back to main IP if none).
    """
    logger.info("Executing 12-hour scheduled proxy sync pipeline...")
    try:
        res = await ProxyService.sync_proxies_pipeline()
        logger.info(
            f"12-hour Proxy Sync completed: Found={res['found']}, NewAdded={res['added']}, "
            f"Active={res['active']}, RemovedDead={res['deleted_dead']}, "
            f"Assigned={res['assigned']}, DirectIP={res['direct_ip']}"
        )
    except Exception as e:
        logger.error(f"Error in scheduled 12-hour proxy sync pipeline: {e}")


async def scheduled_accounts_health_check():
    """Runs periodic health check on all registered userbot accounts."""
    logger.info("Executing scheduled accounts health check...")
    try:
        res = await AccountService.test_all_accounts()
        logger.info(f"Accounts check completed: {res}")
    except Exception as e:
        logger.error(f"Error in scheduled accounts check: {e}")


async def scheduled_database_backup():
    """Runs scheduled 24-hour backup of PostgreSQL database and sends it to Telegram admins."""
    logger.info("Executing 24-hour scheduled database backup...")
    try:
        res = await BackupService.send_backup_to_recipients()
        logger.info(f"Scheduled database backup finished: {res}")
    except Exception as e:
        logger.error(f"Error in scheduled database backup: {e}")


def setup_scheduler(bot_client: Optional[Client] = None):
    """Registers periodic jobs and starts the AsyncIOScheduler."""
    if bot_client:
        BackupService.set_bot_client(bot_client)

    # Complete proxy scraping, cleanup, and rotation every 12 hours (twice daily)
    scheduler.add_job(scheduled_proxy_sync_pipeline, "interval", hours=12, id="proxy_sync_pipeline")
    # Quick health check every 30 minutes
    scheduler.add_job(scheduled_proxy_health_check, "interval", minutes=30, id="proxy_health_check")
    # Accounts health check every 12 hours
    scheduler.add_job(scheduled_accounts_health_check, "interval", hours=12, id="accounts_health_check")
    # Database backup every 24 hours
    scheduler.add_job(
        scheduled_database_backup,
        "interval",
        hours=settings.BACKUP_INTERVAL_HOURS,
        id="database_daily_backup",
    )
    scheduler.start()
    logger.info("Background AsyncIOScheduler started successfully with 24-hour database backup job.")

