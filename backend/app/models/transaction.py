from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    transaction_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    # ISO datetime string for calendar data; simulation rows store a non-date marker
    # and use simulation_step instead. Source values remain in source_timestamp_value.
    timestamp: Mapped[str] = mapped_column(String(64), index=True)
    simulation_step: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_timestamp_value: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sender: Mapped[str] = mapped_column(String(100), index=True)
    receiver: Mapped[str] = mapped_column(String(100), index=True)
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(12), nullable=True, default="USD")
    currency_missing: Mapped[bool] = mapped_column(default=False)
    import_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(40), default="wire")
    description: Mapped[str] = mapped_column(Text, default="")
    rule_score: Mapped[float] = mapped_column(Float, default=0)
    graph_score: Mapped[float] = mapped_column(Float, default=0)
    temporal_score: Mapped[float] = mapped_column(Float, default=0)
    anomaly_score: Mapped[float] = mapped_column(Float, default=0)
    risk_score: Mapped[float] = mapped_column(Float, default=0)
    reasons: Mapped[str] = mapped_column(Text, default="")
    review_status: Mapped[str] = mapped_column(String(20), default="open")
    source_transaction_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    source_alert_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    label_source: Mapped[str] = mapped_column(String(20), default="none")
    source_dataset: Mapped[str] = mapped_column(String(120), default="local")
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_record: Mapped[str] = mapped_column(Text, default="{}")
    related_accounts: Mapped[str] = mapped_column(Text, default="[]")
    supporting_transaction_ids: Mapped[str] = mapped_column(Text, default="[]")
    contributing_signals: Mapped[str] = mapped_column(Text, default="[]")
    evaluation_eligible: Mapped[bool] = mapped_column(default=False)
    validation_eligible: Mapped[bool] = mapped_column(default=False)
    alert_threshold: Mapped[int] = mapped_column(Integer, default=40)
