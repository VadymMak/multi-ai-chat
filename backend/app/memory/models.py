from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    ForeignKey,
    DateTime,
    Boolean
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ✅ Role table
class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255), nullable=True)

    # Relationships
    memories = relationship("MemoryEntry", back_populates="role", cascade="all, delete")
    role_projects = relationship("RoleProjectLink", back_populates="role", cascade="all, delete")
    prompt_templates = relationship("PromptTemplate", back_populates="role", cascade="all, delete")


# ✅ Project table
class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    project_structure = Column(Text, nullable=True)

    # Relationships
    memories = relationship("MemoryEntry", back_populates="project", cascade="all, delete")
    role_projects = relationship("RoleProjectLink", back_populates="project", cascade="all, delete")


# ✅ Link table for Role ↔ Project (many-to-many)
class RoleProjectLink(Base):
    __tablename__ = "role_project_link"

    id = Column(Integer, primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    # Relationships
    role = relationship("Role", back_populates="role_projects")
    project = relationship("Project", back_populates="role_projects")


# ✅ Memory entries (summarized or raw memory by session)
class MemoryEntry(Base):
    __tablename__ = "memory_entries"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    chat_session_id = Column(String(255), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    tokens = Column(Integer, nullable=True)
    summary = Column(Text, nullable=True)
    raw_text = Column(Text, nullable=True)

    # Relationships
    role = relationship("Role", back_populates="memories")
    project = relationship("Project", back_populates="memories")


# ✅ Prompt templates tied to a role
class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id = Column(Integer, primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    is_default = Column(Boolean, default=False)

    # Relationships
    role = relationship("Role", back_populates="prompt_templates")


# ✅ Audit log entries with model version
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    project_id = Column(String(255), nullable=False)
    role_id = Column(Integer, nullable=False)
    chat_session_id = Column(String(255), nullable=True)
    provider = Column(String(50), nullable=False)
    action = Column(String(50), nullable=False)  # e.g. "ask", "summary", "boost_review"
    query = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    model_version = Column(String(50), nullable=True)  # ✅ NEW: Model version info
