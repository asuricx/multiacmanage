from enum import Enum
from typing import Optional, TYPE_CHECKING
from datetime import datetime
from sqlalchemy import String, Integer, BigInteger, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.proxy import Proxy


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BANNED = "BANNED"
    FLOOD_WAIT = "FLOOD_WAIT"
    INVALID = "INVALID"


class Account(Base, TimestampMixin):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), index=True, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, index=True, nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    session_string: Mapped[str] = mapped_column(Text, nullable=False)
    session_format: Mapped[str] = mapped_column(String(50), default="KURIGRAM", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=AccountStatus.ACTIVE.value, nullable=False, index=True)
    proxy_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("proxies.id", ondelete="SET NULL"), nullable=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    proxy: Mapped[Optional["Proxy"]] = relationship("Proxy", back_populates="accounts")

    def __repr__(self) -> str:
        return f"<Account id={self.id} user_id={self.user_id} phone={self.phone} status={self.status}>"

    @property
    def status_emoji(self) -> str:
        mapping = {
            AccountStatus.ACTIVE.value: "🟢",
            AccountStatus.BANNED.value: "🔴",
            AccountStatus.FLOOD_WAIT.value: "🟡",
            AccountStatus.INVALID.value: "⚪",
        }
        return mapping.get(self.status, "❓")

    @property
    def display_name(self) -> str:
        if self.first_name:
            return self.first_name
        if self.username:
            return f"@{self.username}"
        if self.phone:
            return self.phone
        return f"User {self.user_id or self.id}"
