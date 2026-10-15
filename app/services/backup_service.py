import asyncio
import gzip
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

from pyrogram import Client
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.database import get_session

logger = logging.getLogger("BackupService")


class BackupService:
    """Service for creating database dumps and delivering backups to Telegram admins."""

    _bot_client: Optional[Client] = None

    @classmethod
    def set_bot_client(cls, client: Client):
        """Stores the bot client instance for background delivery."""
        cls._bot_client = client

    @classmethod
    def get_bot_client(cls) -> Optional[Client]:
        """Returns the registered bot client instance."""
        return cls._bot_client

    @classmethod
    async def create_database_dump(cls) -> Tuple[str, int]:
        """
        Dumps PostgreSQL (or SQLite in tests) database, compresses it with gzip (.sql.gz),
        performs retention cleanup, and returns (file_path, file_size_in_bytes).
        """
        backup_dir = Path(settings.BACKUP_DIR)
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_userbot_{timestamp_str}.sql.gz"
        backup_filepath = str(backup_dir / backup_filename)

        url = make_url(settings.DATABASE_URL)

        if url.drivername.startswith("postgresql"):
            host = url.host or "localhost"
            port = url.port or 5432
            user = url.username or "userbot"
            password = url.password or ""
            database = url.database or "userbot_db"

            env = os.environ.copy()
            if password:
                env["PGPASSWORD"] = password

            cmd = [
                "pg_dump",
                "-h", str(host),
                "-p", str(port),
                "-U", str(user),
                "-d", str(database),
                "--no-owner",
                "--no-privileges",
            ]

            logger.info(f"Running pg_dump for database '{database}' on {host}:{port}...")
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                stdout, stderr = await proc.communicate()

                if proc.returncode != 0:
                    err_msg = stderr.decode(errors="replace").strip()
                    logger.error(f"pg_dump failed with return code {proc.returncode}: {err_msg}")
                    raise RuntimeError(f"pg_dump failed: {err_msg}")

                # Compress and write output
                with gzip.open(backup_filepath, "wb") as f_out:
                    f_out.write(stdout)

            except FileNotFoundError:
                logger.warning("pg_dump binary not found on system. Using fallback SQL exporter...")
                await cls._fallback_export_to_sql_gz(backup_filepath)

        elif url.drivername.startswith("sqlite"):
            # Handle SQLite (e.g. testing)
            await cls._fallback_export_to_sql_gz(backup_filepath)
        else:
            await cls._fallback_export_to_sql_gz(backup_filepath)

        file_size = os.path.getsize(backup_filepath)
        logger.info(f"Database backup generated successfully: {backup_filepath} ({file_size} bytes)")

        # Perform retention cleanup
        cls._cleanup_old_backups(backup_dir, max_days=settings.BACKUP_RETENTION_DAYS)

        return backup_filepath, file_size

    @classmethod
    async def _fallback_export_to_sql_gz(cls, destination_path: str):
        """Fallback exporter using SQLAlchemy session when pg_dump is unavailable."""
        logger.info("Executing fallback database schema & data export...")
        lines = [
            f"-- Userbot Platform Fallback Backup",
            f"-- Generated At: {datetime.now(timezone.utc).isoformat()}Z\n",
        ]
        try:
            async with get_session() as db:
                for table in ["accounts", "proxies", "proxy_source_channels", "reaction_jobs", "reaction_stats", "referral_join_jobs", "join_logs"]:
                    try:
                        res = await db.execute(text(f"SELECT * FROM {table}"))
                        rows = res.fetchall()
                        lines.append(f"-- Table: {table} ({len(rows)} rows)")
                        for row in rows:
                            lines.append(f"-- {dict(row._mapping)}")
                        lines.append("\n")
                    except Exception:
                        pass
        except Exception as e:
            lines.append(f"-- Fallback note: {e}")

        content_bytes = "\n".join(lines).encode("utf-8")
        with gzip.open(destination_path, "wb") as f_out:
            f_out.write(content_bytes)

    @classmethod
    def _cleanup_old_backups(cls, backup_dir: Path, max_days: int = 7):
        """Removes local backups older than max_days to prevent disk exhaustion."""
        try:
            now = time.time()
            cutoff = now - (max_days * 86400)
            for item in backup_dir.glob("backup_userbot_*.sql.gz"):
                if item.is_file() and item.stat().st_mtime < cutoff:
                    logger.info(f"Removing expired backup file: {item.name}")
                    item.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Error during backup cleanup: {e}")

    @classmethod
    async def send_backup_to_recipients(
        cls,
        client: Optional[Client] = None,
        recipient_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        Creates backup and delivers it to specified recipients (or all configured admins).
        """
        bot_client = client or cls.get_bot_client()
        if not bot_client:
            logger.error("Cannot send database backup: Bot Client is not initialized.")
            return {"success": False, "error": "Bot Client not initialized"}

        recipients: List[int] = []
        if recipient_ids:
            recipients = [int(r) for r in recipient_ids]
        elif settings.BACKUP_CHAT_ID:
            recipients = [settings.BACKUP_CHAT_ID]
        elif settings.ADMIN_IDS:
            recipients = [int(r) for r in settings.ADMIN_IDS]

        if not recipients:
            logger.warning("No recipients configured for database backup delivery.")
            return {"success": False, "error": "No recipients configured"}

        # 1. Create dump
        filepath, filesize = await cls.create_database_dump()
        filename = os.path.basename(filepath)

        size_kb = filesize / 1024
        if size_kb >= 1024:
            size_str = f"`{size_kb / 1024:.2f} MB`"
        else:
            size_str = f"`{size_kb:.2f} KB`"

        now_utc = datetime.now(timezone.utc)
        caption = (
            "📦 **پشتیبان‌گیری خودکار دیتابیس (PostgreSQL Backup)**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 تاریخ: `{now_utc.strftime('%Y-%m-%d')}`\n"
            f"⏱ ساعت: `{now_utc.strftime('%H:%M:%S')} UTC`\n"
            f"💾 حجم فایل فشرده: {size_str}\n"
            f"📂 نام فایل: `{filename}`\n\n"
            "🔒 _این فایل شامل بک‌آپ کامل تمام جداول (اکانت‌ها، پروکسی‌ها، جاب‌ها و لاگ‌ها) به صورت فشرده است._"
        )

        sent_count = 0
        try:
            for chat_id in recipients:
                try:
                    await bot_client.send_document(
                        chat_id=chat_id,
                        document=filepath,
                        caption=caption,
                        file_name=filename,
                    )
                    sent_count += 1
                    logger.info(f"Database backup successfully sent to chat_id: {chat_id}")
                except Exception as e:
                    logger.error(f"Failed to send database backup to chat_id {chat_id}: {e}")
        finally:
            # Delete local backup file immediately after delivery so it doesn't remain on the server
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                    logger.info(f"Local backup file deleted from server: {filepath}")
            except Exception as e:
                logger.warning(f"Failed to delete local backup file {filepath}: {e}")

        return {
            "success": sent_count > 0,
            "filepath": filepath,
            "filename": filename,
            "filesize": filesize,
            "sent_count": sent_count,
            "total_recipients": len(recipients),
        }
