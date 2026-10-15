from enum import Enum
from typing import Optional, List, TYPE_CHECKING
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.base import TimestampMixin, utc_now

if TYPE_CHECKING:
    from app.models.account import Account


class ProxyProtocol(str, Enum):
    SOCKS5 = "SOCKS5"
    HTTP = "HTTP"
    MTPROTO = "MTPROTO"


class Proxy(Base, TimestampMixin):
    __tablename__ = "proxies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    protocol: Mapped[str] = mapped_column(String(20), default=ProxyProtocol.SOCKS5.value, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    secret: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # MTProto secret
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    ping_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(100), default="MANUAL", nullable=False)
    fail_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    accounts: Mapped[List["Account"]] = relationship("Account", back_populates="proxy")

    def __repr__(self) -> str:
        return f"<Proxy id={self.id} {self.protocol}://{self.host}:{self.port} active={self.is_active}>"

    def to_kurigram_dict(self) -> dict:
        """Export proxy dictionary compatible with Kurigram Client."""
        proto = self.protocol.upper()
        if proto in ("MTPROTO", "MTPROXY"):
            return {
                "scheme": "mtproxy",
                "hostname": self.host,
                "port": self.port,
                "secret": self.secret or "",
            }

        p_dict = {
            "scheme": proto.lower(),
            "hostname": self.host,
            "port": self.port,
        }
        if self.username:
            p_dict["username"] = self.username
        if self.password:
            p_dict["password"] = self.password
        return p_dict


class ProxySourceChannel(Base, TimestampMixin):
    __tablename__ = "proxy_source_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<ProxySourceChannel id={self.id} channel={self.channel_username} enabled={self.is_enabled}>"
