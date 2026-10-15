from enum import Enum
from typing import Optional, List
from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.base import TimestampMixin, utc_now


class ReferralJobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"


class JoinLogStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ReferralJoinJob(Base, TimestampMixin):
    __tablename__ = "referral_join_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_username: Mapped[str] = mapped_column(String(255), nullable=False)
    start_param: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    delay_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    delay_min: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    delay_max: Mapped[int] = mapped_column(Integer, default=90, nullable=False)
    target_duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=ReferralJobStatus.PENDING.value, nullable=False)

    logs: Mapped[List["JoinLog"]] = relationship("JoinLog", back_populates="job", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<ReferralJoinJob id={self.id} bot={self.bot_username} status={self.status}>"


class JoinLog(Base):
    __tablename__ = "join_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("referral_join_jobs.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=JoinLogStatus.SUCCESS.value, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    job: Mapped["ReferralJoinJob"] = relationship("ReferralJoinJob", back_populates="logs")

    def __repr__(self) -> str:
        return f"<JoinLog id={self.id} job_id={self.job_id} account_id={self.account_id} status={self.status}>"
