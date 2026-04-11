from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

import os

_connect_args = {}
_unix_socket = os.getenv("MYSQL_SOCKET", "/tmp/mysql.sock")
if os.path.exists(_unix_socket):
    _connect_args["unix_socket"] = _unix_socket

engine = create_async_engine(
    settings.MYSQL_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,
    connect_args=_connect_args,
)

async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
