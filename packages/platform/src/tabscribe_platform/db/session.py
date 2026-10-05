from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: str) -> Engine:
    # pre_ping drops connections Postgres closed (restarts, idle timeouts) instead of failing.
    return create_engine(database_url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False: objects stay readable after commit (e.g. when building a response).
    return sessionmaker(engine, expire_on_commit=False)
