"""`python -m tabscribe_platform.migrate`: apply database migrations (needs DATABASE_URL).

The container images have no alembic.ini (it isn't part of the installed package), so the
config is built here; the migration scripts ship inside the package.
"""

import logging

from alembic import command
from alembic.config import Config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    config = Config()
    config.set_main_option("script_location", "tabscribe_platform:migrations")
    command.upgrade(config, "head")


if __name__ == "__main__":
    main()
