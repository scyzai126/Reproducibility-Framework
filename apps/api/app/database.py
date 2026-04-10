from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

engine = create_async_engine(
    settings.MYSQL_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,
)

async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
