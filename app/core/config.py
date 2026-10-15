from typing import List, Union, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Telegram API Credentials
    API_ID: int = 0
    API_HASH: str = ""

    # Bot Father Token
    BOT_TOKEN: str = ""

    # Admin User IDs
    ADMIN_IDS: Union[str, List[int]] = []

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://userbot:userbot_secret_password@localhost:5432/userbot_db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Proxy settings
    AUTO_ROTATE_PROXY: bool = True
    PROXY_HEALTH_CHECK_TIMEOUT: int = 5

    # Database Backup settings
    BACKUP_INTERVAL_HOURS: int = 24
    BACKUP_DIR: str = "backups"
    BACKUP_RETENTION_DAYS: int = 7
    BACKUP_CHAT_ID: Optional[int] = None

    @field_validator("ADMIN_IDS", mode="before")
    def parse_admin_ids(cls, v: Union[str, List[int], int]) -> List[int]:
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            if not v.strip():
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip().isdigit()]
        if isinstance(v, list):
            return [int(x) for x in v]
        return []

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
