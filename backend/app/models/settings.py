from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, Numeric, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AppSettings(Base):
    __tablename__ = "app_settings"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    emails_per_hour: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    delay_between_emails_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")
    max_daily_emails: Mapped[int] = mapped_column(Integer, nullable=False, server_default="400")
    match_confidence_threshold: Mapped[Decimal] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        server_default="0.800",
    )
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    gmail_reconnect_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
