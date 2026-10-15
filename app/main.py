import asyncio
import logging
import sys
from pyrogram import Client

from app.core.config import settings
from app.core.redis import close_redis
from app.handlers.accounts import register_account_handlers
from app.handlers.proxies import register_proxy_handlers
from app.handlers.reactions import register_reaction_handlers
from app.handlers.referral import register_referral_handlers
from app.handlers.start import register_start_handlers
from app.tasks.reaction_worker import ReactionWatcher
from app.tasks.referral_worker import ReferralWorker
from app.tasks.scheduler import setup_scheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s : %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("UserbotPlatform")


async def main():
    logger.info("Starting Telegram Userbot Automation Platform...")

    if not settings.BOT_TOKEN:
        logger.error("BOT_TOKEN is not configured! Please provide BOT_TOKEN in .env.")
        sys.exit(1)

    if not settings.API_ID or not settings.API_HASH:
        logger.error("API_ID and API_HASH are required in .env! Please configure them.")
        sys.exit(1)

    # Initialize Admin Bot Client
    app = Client(
        name="admin_bot",
        api_id=settings.API_ID,
        api_hash=settings.API_HASH,
        bot_token=settings.BOT_TOKEN,
        in_memory=True,
    )

    # Register handlers
    register_start_handlers(app)
    register_account_handlers(app)
    register_proxy_handlers(app)
    register_reaction_handlers(app)
    register_referral_handlers(app)

    # Start background scheduler
    setup_scheduler(app)

    # Start Single Watcher for Reaction Jobs
    watcher_task = asyncio.create_task(ReactionWatcher.start_watcher_loop())

    # Resume active referral jobs
    await ReferralWorker.resume_active_jobs()

    logger.info("Connecting bot to Telegram...")
    await app.start()
    bot_me = await app.get_me()
    logger.info(f"Bot successfully started: @{bot_me.username} (ID: {bot_me.id})")

    try:
        # Keep running
        from pyrogram.methods.utilities.idle import idle
        await idle()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown signal received.")
    finally:
        logger.info("Stopping Bot and closing resources...")
        ReactionWatcher.stop()
        watcher_task.cancel()
        if app.is_connected:
            await app.stop()
        await close_redis()
        logger.info("Platform stopped gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
