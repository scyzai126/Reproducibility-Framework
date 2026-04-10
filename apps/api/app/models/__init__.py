"""SQLAlchemy ORM models for app-specific tables.

Add your models here as needed. Example:

from sqlalchemy import Column, Integer, String
from app.database import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_path = Column(String(512), nullable=False)
    generated_sql = Column(String(4096))
    status = Column(String(64), default="pending")
"""
