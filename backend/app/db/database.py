import os
from pathlib import Path
from dotenv import load_dotenv

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./aml_detection.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_sqlite_columns():
    """Additive schema upgrade that preserves the existing SQLite rows."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    additions = {
        "source_transaction_id": "VARCHAR(150)", "source_label": "VARCHAR(100)",
        "label_source": "VARCHAR(20) NOT NULL DEFAULT 'none'", "source_dataset": "VARCHAR(120) NOT NULL DEFAULT 'local'",
        "source_row": "INTEGER", "source_record": "TEXT NOT NULL DEFAULT '{}'",
        "related_accounts": "TEXT NOT NULL DEFAULT '[]'", "supporting_transaction_ids": "TEXT NOT NULL DEFAULT '[]'",
        "contributing_signals": "TEXT NOT NULL DEFAULT '[]'", "evaluation_eligible": "BOOLEAN NOT NULL DEFAULT 0",
        "validation_eligible": "BOOLEAN NOT NULL DEFAULT 0",
        "alert_threshold": "INTEGER NOT NULL DEFAULT 40",
        "currency_missing": "BOOLEAN NOT NULL DEFAULT 0", "import_id": "VARCHAR(36)",
        "simulation_step": "INTEGER", "source_timestamp_value": "VARCHAR(100)",
        "source_alert_id": "VARCHAR(100)",
    }
    if "transactions" not in inspect(engine).get_table_names():
        return
    existing = {column["name"] for column in inspect(engine).get_columns("transactions")}
    with engine.begin() as connection:
        for name, declaration in additions.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE transactions ADD COLUMN {name} {declaration}"))
                if name == "currency_missing":
                    connection.execute(text("UPDATE transactions SET currency_missing=1 WHERE source_dataset != 'local'"))
