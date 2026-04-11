import asyncio
import os

os.environ["MYSQL_URL"] = "mysql+aiomysql://immport_user:Edic-123@127.0.0.1:3306/immport_dr62"

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

engine = create_async_engine(os.environ["MYSQL_URL"])
Session = sessionmaker(engine, class_=AsyncSession)

async def test():
    async with Session() as s:
        r = await s.execute(text("SELECT DISTINCT `condition` FROM subject_data_view WHERE study_accession='SDY1669' LIMIT 1"))
        print("DB works:", r.fetchone())

asyncio.run(test())
