# backend/app/memory/models.py
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255), nullable=True)

    memories = relationship("MemoryEntry", back_populates="role")

class MemoryEntry(Base):
    __tablename__ = "memory_entries"

    id = Column(Integer, primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id"))
    timestamp = Column(DateTime, default=datetime.utcnow)
    tokens = Column(Integer)
    summary = Column(Text)
    raw_text = Column(Text)

    role = relationship("Role", back_populates="memories")
