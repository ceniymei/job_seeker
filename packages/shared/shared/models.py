from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from shared.database import Base
from shared.config import config

# Dynamically choose JSON column type to ensure bidirectional compatibility between SQLite and PostgreSQL
JSON_TYPE = JSONB if config.database_dsn.startswith("postgresql") else JSON

class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    homepage_url = Column(String(500), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    crawl_config = Column(JSON_TYPE, nullable=True)

    # Relationship with jobs
    jobs = relationship("Job", back_populates="company", cascade="all, delete-orphan")

class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(250), nullable=False, index=True)
    department = Column(Text, nullable=True)
    location = Column(String(250), nullable=False, index=True)
    salary = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)

    job_url = Column(String(1000), unique=True, nullable=False, index=True)
    status = Column(String(50), default="active")
    detail_status = Column(String(50), default="pending", nullable=False)

    # Store other structured metadata extracted by ScrapegraphAI (for future scalability)
    # Maps to JSONB under PostgreSQL, falls back to JSON under SQLite
    raw_metadata = Column(JSON_TYPE, nullable=True)
    location_standard = Column(JSON_TYPE, nullable=True)
    salary_standard = Column(JSON_TYPE, nullable=True)
    embedding = Column(JSON_TYPE, nullable=True)
    embedding_model = Column(String(250), nullable=True)

    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="jobs")

class CrawlLog(Base):
    __tablename__ = "crawl_logs"

    id = Column(Integer, primary_key=True, index=True)
    target_url = Column(String(1000), nullable=False, index=True)
    html_hash = Column(String(64), nullable=True, index=True)
    status = Column(String(50), nullable=False)
    error_message = Column(Text, nullable=True)
    crawled_at = Column(DateTime, default=datetime.utcnow)
