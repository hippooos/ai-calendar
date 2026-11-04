from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def create_sqlite_engine(url: str) -> Engine:
    return create_engine(
        url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool if url.endswith(":memory:") else None,
    )


def create_database_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        return create_sqlite_engine(url)
    return create_engine(url, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
