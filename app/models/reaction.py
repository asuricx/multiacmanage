from enum import Enum
from typing import Optional, List, Dict, Any
from sqlalchemy import String, Integer, BigInteger, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.base import TimestampMixin


class ReactionJobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"


class ReactionJob(Base, TimestampMixin):
    __tablename__ = "reaction_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_channel: Mapped[str] = mapped_column(String(255), nullable=False)
    days_range: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    delay_min: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    delay_max: Mapped[int] = mapped_column(Integer, default=180, nullable=False)
    emoji_distribution: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=ReactionJobStatus.PENDING.value, nullable=False)

    stats: Mapped[List["ReactionStat"]] = relationship("ReactionStat", back_populates="job", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<ReactionJob id={self.id} channel={self.target_channel} status={self.status}>"


class ReactionStat(Base, TimestampMixin):
    __tablename__ = "reaction_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("reaction_jobs.id", ondelete="CASCADE"), nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_reactions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    job: Mapped["ReactionJob"] = relationship("ReactionJob", back_populates="stats")

    def __repr__(self) -> str:
        return f"<ReactionStat id={self.id} job_id={self.job_id} msg_id={self.message_id} reactions={self.total_reactions}>"
