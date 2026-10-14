import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.db.checkpointer import setup_checkpointer_schema


def run_business_migrations() -> None:
    """Upgrade all Alembic-managed business tables to the latest revision."""
    project_root = Path(__file__).resolve().parents[3]
    alembic_config = Config(project_root / "alembic.ini")
    command.upgrade(alembic_config, "head")


def main() -> None:
    """Run business migrations, then initialize LangGraph checkpoint tables."""
    # Alembic owns its event loop internally; run it before starting checkpoint setup.
    run_business_migrations()
    asyncio.run(setup_checkpointer_schema())


if __name__ == "__main__":
    main()
