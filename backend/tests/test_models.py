from app.db import models  # noqa: F401
from app.db.base import Base


def test_core_business_tables_are_registered() -> None:
    assert {
        "users",
        "chat_sessions",
        "messages",
        "documents",
        "ingestion_jobs",
    }.issubset(Base.metadata.tables)


def test_message_metadata_uses_a_non_reserved_python_attribute() -> None:
    message_table = Base.metadata.tables["messages"]

    assert "metadata" in message_table.columns
