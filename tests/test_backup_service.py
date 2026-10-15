import asyncio
import gzip
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.core.config import settings
from app.services.backup_service import BackupService


@pytest.mark.asyncio
async def test_create_database_dump_and_gzip():
    """Verify that BackupService creates a valid .sql.gz file."""
    # Test backup dump creation
    filepath, filesize = await BackupService.create_database_dump()
    assert os.path.exists(filepath)
    assert filesize > 0
    assert filepath.endswith(".sql.gz")

    # Verify gzip contents
    with gzip.open(filepath, "rt", encoding="utf-8") as f:
        content = f.read()
        assert len(content) > 0
        assert "Backup" in content or "CREATE" in content or "PostgreSQL" in content

    print("test_create_database_dump_and_gzip: PASSED")


def test_backup_retention_cleanup(tmp_path):
    """Verify that backups older than retention cutoff are cleaned up."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    # Create an old backup (10 days old)
    old_file = backup_dir / "backup_userbot_20260101_000000.sql.gz"
    old_file.write_bytes(b"old")
    past_time = time.time() - (10 * 86400)
    os.utime(str(old_file), (past_time, past_time))

    # Create a fresh backup (today)
    new_file = backup_dir / "backup_userbot_20261013_120000.sql.gz"
    new_file.write_bytes(b"new")

    # Run cleanup with 7 days max
    BackupService._cleanup_old_backups(backup_dir, max_days=7)

    assert not old_file.exists()
    assert new_file.exists()
    print("test_backup_retention_cleanup: PASSED")


@pytest.mark.asyncio
async def test_send_backup_to_recipients():
    """Verify delivering backup document via mock client."""
    mock_client = MagicMock()
    mock_client.send_document = AsyncMock()

    res = await BackupService.send_backup_to_recipients(
        client=mock_client,
        recipient_ids=[123456789, 987654321],
    )

    assert res["success"] is True
    assert res["sent_count"] == 2
    assert mock_client.send_document.call_count == 2

    # Check argument passed to send_document
    call_args = mock_client.send_document.call_args_list[0]
    kwargs = call_args.kwargs
    assert kwargs["chat_id"] == 123456789
    assert kwargs["document"].endswith(".sql.gz")
    assert "پشتیبان‌گیری" in kwargs["caption"]

    # Verify that the backup file is deleted immediately from the server
    assert not os.path.exists(res["filepath"])

    print("test_send_backup_to_recipients: PASSED")
