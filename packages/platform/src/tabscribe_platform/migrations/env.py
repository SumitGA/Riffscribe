"""Alembic entry point. Uses the connection passed in by tests, else DATABASE_URL."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, create_engine

from tabscribe_platform.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _migrate(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=Base.metadata, compare_server_default=True
    )
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if isinstance(connection, Connection):
    _migrate(connection)
else:
    # Only DATABASE_URL is needed to migrate, so this doesn't load the full Settings.
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        _migrate(conn)
    engine.dispose()
