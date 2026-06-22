"""Database connection, session management, and SQLAlchemy ORM models.

Uses async SQLAlchemy with asyncpg for PostgreSQL connectivity.
ORM models mirror the SQL schema defined in scripts/init.sql.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import AsyncGenerator, Optional
from uuid import uuid4

from sqlalchemy import (
    JSON,
    ARRAY,
    Boolean,
    BigInteger,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship

from observability.logger import get_logger

logger = get_logger(__name__)


from dotenv import load_dotenv
from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent / ".env")

# =============================================================================
# Database Engine & Session
# =============================================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://nivesh:nivesh_secret_2026@localhost:5432/nivesh_pipeline"
)

# Convert postgresql:// to postgresql+asyncpg:// if needed
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI to get a database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize the database connection pool and verify connectivity."""
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("database_connected", url=DATABASE_URL.split("@")[-1])
    except Exception as e:
        logger.error("database_connection_failed", error=str(e))
        raise


# =============================================================================
# ORM Base
# =============================================================================

class Base(DeclarativeBase):
    pass


# =============================================================================
# ORM Models
# =============================================================================

class SourceConfigORM(Base):
    __tablename__ = "source_config"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_key = Column(String(50), unique=True, nullable=False)
    amc_name = Column(String(200), nullable=False)
    base_url = Column(Text, nullable=False)
    page_type = Column(String(20), nullable=False, default="JS_SPA")
    discovery_strategy = Column(String(30), nullable=False, default="link_extraction")
    selectors = Column(JSONB, default={})
    anti_bot_config = Column(JSONB, default={})
    file_types = Column(ARRAY(String), default=["xlsx", "pdf"])
    schedule_cron = Column(String(100))
    enabled = Column(Boolean, nullable=False, default=True)
    last_crawled_at = Column(DateTime(timezone=True))
    last_success_at = Column(DateTime(timezone=True))
    page_structure_hash = Column(String(64))
    metadata_ = Column("metadata", JSONB, default={})
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    # Relationships
    discovered_documents = relationship("DiscoveredDocumentORM", back_populates="source")
    drift_detections = relationship("DriftDetectionORM", back_populates="source")
    pipeline_runs = relationship("PipelineRunORM", back_populates="source")


class DiscoveredDocumentORM(Base):
    __tablename__ = "discovered_document"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("source_config.id"), nullable=False)
    url = Column(Text, nullable=False)
    filename = Column(String(500))
    file_type = Column(String(20))
    file_size_bytes = Column(BigInteger)
    file_hash_sha256 = Column(String(64))
    content_hash = Column(String(64))
    url_fingerprint = Column(String(64), nullable=False)
    local_path = Column(Text)
    is_novel = Column(Boolean, nullable=False, default=True)
    status = Column(String(20), nullable=False, default="DISCOVERED")
    download_attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text)
    page_context = Column(JSONB, default={})
    discovered_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    downloaded_at = Column(DateTime(timezone=True))
    pipeline_run_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        UniqueConstraint("url_fingerprint", "source_id", name="uq_url_fingerprint_source"),
    )

    # Relationships
    source = relationship("SourceConfigORM", back_populates="discovered_documents")
    classifications = relationship("ClassifiedDocumentORM", back_populates="document")
    staging_records = relationship("StagingDataORM", back_populates="document")


class ClassifiedDocumentORM(Base):
    __tablename__ = "classified_document"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("discovered_document.id"), nullable=False)
    amc_name = Column(String(200))
    scheme_name = Column(String(500))
    scheme_category = Column(String(100))
    period_month = Column(Integer)
    period_year = Column(Integer)
    period_label = Column(String(50))
    doc_type = Column(String(100))
    confidence_score = Column(Float, nullable=False, default=0.0)
    classification_signals = Column(JSONB, nullable=False, default={})
    filename_signal = Column(JSONB, default={})
    url_signal = Column(JSONB, default={})
    page_context_signal = Column(JSONB, default={})
    doc_header_signal = Column(JSONB, default={})
    is_quarantined = Column(Boolean, nullable=False, default=False)
    quarantine_reason = Column(String(30))
    quarantine_details = Column(Text)
    reviewed_by = Column(String(200))
    review_decision = Column(String(20))
    review_notes = Column(Text)
    reviewed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    # Relationships
    document = relationship("DiscoveredDocumentORM", back_populates="classifications")


class StagingDataORM(Base):
    __tablename__ = "staging_data"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("discovered_document.id"), nullable=False)
    classification_id = Column(UUID(as_uuid=True), ForeignKey("classified_document.id"))
    idempotency_key = Column(String(128), unique=True, nullable=False)
    raw_data = Column(JSONB, nullable=False)
    page_number = Column(Integer)
    table_index = Column(Integer)
    row_count = Column(Integer)
    column_names = Column(ARRAY(String))
    header_hash = Column(String(64))
    extraction_metadata = Column("extraction_metadata", JSONB, default={})
    content_hash = Column(String(64))
    extracted_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    # Relationships
    document = relationship("DiscoveredDocumentORM", back_populates="staging_records")
    validated_records = relationship("ValidatedDataORM", back_populates="staging")


class ValidatedDataORM(Base):
    __tablename__ = "validated_data"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    staging_id = Column(UUID(as_uuid=True), ForeignKey("staging_data.id"), nullable=False)
    document_id = Column(UUID(as_uuid=True), ForeignKey("discovered_document.id"), nullable=False)
    clean_data = Column(JSONB, nullable=False)
    validation_status = Column(String(20), nullable=False, default="PENDING")
    validation_errors = Column(JSONB, default=[])
    validation_warnings = Column(JSONB, default=[])
    drift_score = Column(Float, default=0.0)
    drift_details = Column(JSONB, default={})
    business_rules_passed = Column(Boolean, nullable=False, default=False)
    validated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    # Relationships
    staging = relationship("StagingDataORM", back_populates="validated_records")
    published_records = relationship("PublishedDataORM", back_populates="validated")


class PublishedDataORM(Base):
    __tablename__ = "published_data"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    validated_id = Column(UUID(as_uuid=True), ForeignKey("validated_data.id"), nullable=False)
    document_id = Column(UUID(as_uuid=True), ForeignKey("discovered_document.id"), nullable=False)
    idempotency_key = Column(String(128), unique=True, nullable=False)
    amc_name = Column(String(200), nullable=False)
    scheme_name = Column(String(500), nullable=False)
    scheme_category = Column(String(100))
    period_month = Column(Integer, nullable=False)
    period_year = Column(Integer, nullable=False)
    isin = Column(String(100))
    instrument_name = Column(Text)
    instrument_type = Column(String(100))
    quantity = Column(Float)
    market_value = Column(Float)
    pct_to_net_assets = Column(Float)
    rating = Column(String(50))
    industry = Column(String(200))
    version = Column(Integer, nullable=False, default=1)
    is_current = Column(Boolean, nullable=False, default=True)
    published_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    # Relationships
    validated = relationship("ValidatedDataORM", back_populates="published_records")


class DriftDetectionORM(Base):
    __tablename__ = "drift_detection"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("source_config.id"), nullable=False)
    document_id = Column(UUID(as_uuid=True), ForeignKey("discovered_document.id"))
    detection_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False, default="WARNING")
    previous_signature = Column(JSONB)
    current_signature = Column(JSONB)
    similarity_score = Column(Float)
    description = Column(Text)
    alert_sent = Column(Boolean, nullable=False, default=False)
    resolved = Column(Boolean, nullable=False, default=False)
    resolved_by = Column(String(200))
    resolved_at = Column(DateTime(timezone=True))
    resolution_notes = Column(Text)
    detected_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    # Relationships
    source = relationship("SourceConfigORM", back_populates="drift_detections")


class AuditLogORM(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    action = Column(String(20), nullable=False)
    before_state = Column(JSONB)
    after_state = Column(JSONB)
    actor = Column(String(200), nullable=False, default="system")
    pipeline_run_id = Column(UUID(as_uuid=True))
    metadata_ = Column("metadata", JSONB, default={})
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class PipelineRunORM(Base):
    __tablename__ = "pipeline_run"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("source_config.id"))
    status = Column(String(20), nullable=False, default="RUNNING")
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    completed_at = Column(DateTime(timezone=True))
    documents_discovered = Column(Integer, default=0)
    documents_novel = Column(Integer, default=0)
    documents_classified = Column(Integer, default=0)
    documents_quarantined = Column(Integer, default=0)
    documents_extracted = Column(Integer, default=0)
    documents_published = Column(Integer, default=0)
    errors = Column(JSONB, default=[])
    metadata_ = Column("metadata", JSONB, default={})
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    # Relationships
    source = relationship("SourceConfigORM", back_populates="pipeline_runs")
