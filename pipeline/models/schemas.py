"""Pydantic models for the AMC data pipeline.

Defines all request/response schemas, domain models, and validation logic
used throughout the pipeline stages.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Enums (matching PostgreSQL enum types)
# =============================================================================

class PageType(str, enum.Enum):
    STATIC = "STATIC"
    JS_SPA = "JS_SPA"


class DiscoveryStrategy(str, enum.Enum):
    LINK_EXTRACTION = "link_extraction"
    API_INTERCEPT = "api_intercept"
    NETWORK_INTERCEPT = "network_intercept"


class DocumentStatus(str, enum.Enum):
    DISCOVERED = "DISCOVERED"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    CLASSIFYING = "CLASSIFYING"
    CLASSIFIED = "CLASSIFIED"
    EXTRACTING = "EXTRACTING"
    EXTRACTED = "EXTRACTED"
    STAGING = "STAGING"
    STAGED = "STAGED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    PUBLISHED = "PUBLISHED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class QuarantineReason(str, enum.Enum):
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    DRIFT_DETECTED = "DRIFT_DETECTED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    CLASSIFICATION_CONFLICT = "CLASSIFICATION_CONFLICT"
    STALE_PERIOD = "STALE_PERIOD"
    UNKNOWN_SCHEME = "UNKNOWN_SCHEME"


class ReviewDecision(str, enum.Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    RECLASSIFIED = "RECLASSIFIED"


class DriftSeverity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AuditAction(str, enum.Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    STATUS_CHANGE = "STATUS_CHANGE"
    REVIEW = "REVIEW"
    PUBLISH = "PUBLISH"
    QUARANTINE = "QUARANTINE"


# =============================================================================
# Signal Models (for confidence scoring)
# =============================================================================

class SignalResult(BaseModel):
    """Result from a single classification signal channel."""
    channel: str = Field(..., description="Signal channel name")
    amc_name: Optional[str] = None
    scheme_name: Optional[str] = None
    period_month: Optional[int] = None
    period_year: Optional[int] = None
    scheme_category: Optional[str] = None
    doc_type: Optional[str] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Channel confidence 0-1")
    raw_signals: dict[str, Any] = Field(default_factory=dict, description="Raw extracted data")
    reasoning: str = Field("", description="Why this confidence was assigned")


class ConfidenceBreakdown(BaseModel):
    """Full breakdown of confidence scoring across all channels."""
    filename_signal: SignalResult = Field(default_factory=lambda: SignalResult(channel="filename"))
    url_signal: SignalResult = Field(default_factory=lambda: SignalResult(channel="url"))
    page_context_signal: SignalResult = Field(default_factory=lambda: SignalResult(channel="page_context"))
    doc_header_signal: SignalResult = Field(default_factory=lambda: SignalResult(channel="doc_header"))
    
    # Aggregated results
    final_amc_name: Optional[str] = None
    final_scheme_name: Optional[str] = None
    final_period_month: Optional[int] = None
    final_period_year: Optional[int] = None
    final_scheme_category: Optional[str] = None
    final_doc_type: Optional[str] = None
    
    # Scoring
    weighted_score: float = 0.0
    agreement_bonus: float = 0.0
    disagreement_penalty: float = 0.0
    final_confidence: float = 0.0
    
    # Decision
    decision: str = "QUARANTINE"  # AUTO_ACCEPT, ACCEPT_WITH_FLAG, QUARANTINE, REJECT
    quarantine_reasons: list[str] = Field(default_factory=list)


# =============================================================================
# Domain Models
# =============================================================================

class SourceConfigModel(BaseModel):
    """Source configuration for an AMC."""
    id: Optional[UUID] = None
    source_key: str
    amc_name: str
    base_url: str
    page_type: PageType = PageType.JS_SPA
    discovery_strategy: DiscoveryStrategy = DiscoveryStrategy.LINK_EXTRACTION
    selectors: dict[str, Any] = Field(default_factory=dict)
    anti_bot_config: dict[str, Any] = Field(default_factory=dict)
    file_types: list[str] = Field(default_factory=lambda: ["xlsx", "pdf"])
    schedule_cron: Optional[str] = None
    enabled: bool = True
    last_crawled_at: Optional[datetime] = None
    page_structure_hash: Optional[str] = None


class DiscoveredDocumentModel(BaseModel):
    """A document discovered during the crawl phase."""
    id: UUID = Field(default_factory=uuid4)
    source_id: Optional[UUID] = None
    source_key: str = ""
    url: str
    filename: Optional[str] = None
    file_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    file_hash_sha256: Optional[str] = None
    content_hash: Optional[str] = None
    url_fingerprint: str = ""
    local_path: Optional[str] = None
    is_novel: bool = True
    status: DocumentStatus = DocumentStatus.DISCOVERED
    page_context: dict[str, Any] = Field(default_factory=dict)
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    pipeline_run_id: Optional[UUID] = None


class ClassifiedDocumentModel(BaseModel):
    """A classified document with identity resolution results."""
    id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    amc_name: Optional[str] = None
    scheme_name: Optional[str] = None
    scheme_category: Optional[str] = None
    period_month: Optional[int] = None
    period_year: Optional[int] = None
    period_label: Optional[str] = None
    doc_type: Optional[str] = None
    confidence_score: float = 0.0
    confidence_breakdown: ConfidenceBreakdown = Field(default_factory=ConfidenceBreakdown)
    is_quarantined: bool = False
    quarantine_reason: Optional[QuarantineReason] = None
    quarantine_details: Optional[str] = None
    reviewed_by: Optional[str] = None
    review_decision: Optional[ReviewDecision] = None
    review_notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None

    @field_validator("period_month")
    @classmethod
    def validate_month(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 1 or v > 12):
            raise ValueError("period_month must be between 1 and 12")
        return v


class StagingDataModel(BaseModel):
    """Raw extracted data in the staging layer."""
    id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    classification_id: Optional[UUID] = None
    idempotency_key: str
    raw_data: list[dict[str, Any]]
    page_number: Optional[int] = None
    table_index: Optional[int] = None
    row_count: int = 0
    column_names: list[str] = Field(default_factory=list)
    header_hash: Optional[str] = None
    extraction_metadata: dict[str, Any] = Field(default_factory=dict)
    content_hash: Optional[str] = None


class ValidatedDataModel(BaseModel):
    """Validated data ready for publishing."""
    id: UUID = Field(default_factory=uuid4)
    staging_id: UUID
    document_id: UUID
    clean_data: list[dict[str, Any]]
    validation_status: str = "PENDING"
    validation_errors: list[dict[str, Any]] = Field(default_factory=list)
    validation_warnings: list[dict[str, Any]] = Field(default_factory=list)
    drift_score: float = 0.0
    drift_details: dict[str, Any] = Field(default_factory=dict)
    business_rules_passed: bool = False


class PublishedHoldingModel(BaseModel):
    """A single published holding record in the warehouse."""
    id: UUID = Field(default_factory=uuid4)
    validated_id: UUID
    document_id: UUID
    idempotency_key: str
    amc_name: str
    scheme_name: str
    scheme_category: Optional[str] = None
    period_month: int
    period_year: int
    isin: Optional[str] = None
    instrument_name: Optional[str] = None
    instrument_type: Optional[str] = None
    quantity: Optional[float] = None
    market_value: Optional[float] = None
    pct_to_net_assets: Optional[float] = None
    rating: Optional[str] = None
    industry: Optional[str] = None
    version: int = 1
    is_current: bool = True

    @field_validator("isin")
    @classmethod
    def validate_isin(cls, v: Optional[str]) -> Optional[str]:
        """Validate ISIN format: 2-letter country + 9 alphanum + 1 check digit."""
        if v is not None and v.strip():
            v = v.strip().upper()
            if len(v) != 12:
                return v  # Don't reject, but flag during validation
        return v


class DriftDetectionModel(BaseModel):
    """A drift detection event."""
    id: UUID = Field(default_factory=uuid4)
    source_id: UUID
    document_id: Optional[UUID] = None
    detection_type: str
    severity: DriftSeverity = DriftSeverity.WARNING
    previous_signature: Optional[dict[str, Any]] = None
    current_signature: Optional[dict[str, Any]] = None
    similarity_score: Optional[float] = None
    description: Optional[str] = None
    alert_sent: bool = False
    resolved: bool = False


class PipelineRunModel(BaseModel):
    """Tracks a single pipeline execution run."""
    id: UUID = Field(default_factory=uuid4)
    source_id: Optional[UUID] = None
    source_key: str = ""
    status: str = "RUNNING"
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    documents_discovered: int = 0
    documents_novel: int = 0
    documents_classified: int = 0
    documents_quarantined: int = 0
    documents_extracted: int = 0
    documents_published: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)


# =============================================================================
# API Request/Response Models
# =============================================================================

class PipelineRunRequest(BaseModel):
    force_refresh: bool = True
    dry_run: bool = False


class ReviewRequest(BaseModel):
    decision: ReviewDecision
    reviewer: str = "admin"
    notes: Optional[str] = None
    corrected_amc_name: Optional[str] = None
    corrected_scheme_name: Optional[str] = None
    corrected_period_month: Optional[int] = None
    corrected_period_year: Optional[int] = None


class SourceCreateRequest(BaseModel):
    source_key: str
    amc_name: str
    base_url: str
    page_type: PageType = PageType.JS_SPA
    file_types: list[str] = Field(default_factory=lambda: ["xlsx", "pdf"])
    schedule_cron: Optional[str] = None
    enabled: bool = True


class StatsResponse(BaseModel):
    total_sources: int = 0
    enabled_sources: int = 0
    total_documents: int = 0
    total_quarantined: int = 0
    total_published: int = 0
    recent_runs: int = 0
    active_drift_alerts: int = 0


class HealthResponse(BaseModel):
    status: str = "healthy"
    database: str = "connected"
    version: str = "1.0.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
