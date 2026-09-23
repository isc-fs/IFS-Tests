from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from ifs_tests.db.models import Base
from ifs_tests.settings import get_settings

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)

# The URL comes from the app settings (IFS_DATABASE_URL), or from -x url=... for one-off runs.
url = context.get_x_argument(as_dictionary=True).get("url") or get_settings().database_url


def run() -> None:
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=Base.metadata, literal_binds=True, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    with create_engine(url).connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run()
