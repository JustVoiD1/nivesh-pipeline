-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Create enum types
CREATE TYPE page_type AS ENUM ('STATIC', 'JS_SPA');
CREATE TYPE discovery_strategy AS ENUM ('link_extraction', 'api_intercept', 'network_intercept');
CREATE TYPE document_status AS ENUM ('DISCOVERED', 'DOWNLOADING', 'DOWNLOADED', 'CLASSIFYING', 'CLASSIFIED', 'EXTRACTING', 'EXTRACTED', 'STAGING', 'STAGED', 'VALIDATING', 'VALIDATED', 'PUBLISHED', 'QUARANTINED', 'REJECTED', 'FAILED');
CREATE TYPE quarantine_reason AS ENUM ('LOW_CONFIDENCE', 'DRIFT_DETECTED', 'VALIDATION_FAILED', 'MANUAL_REVIEW', 'CLASSIFICATION_CONFLICT', 'STALE_PERIOD', 'UNKNOWN_SCHEME');
CREATE TYPE review_decision AS ENUM ('ACCEPTED', 'REJECTED', 'RECLASSIFIED');
CREATE TYPE drift_severity AS ENUM ('INFO', 'WARNING', 'CRITICAL');
CREATE TYPE audit_action AS ENUM ('CREATE', 'UPDATE', 'DELETE', 'STATUS_CHANGE', 'REVIEW', 'PUBLISH', 'QUARANTINE');

-- ===== Table 1: source_config =====
CREATE TABLE source_config (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_key VARCHAR(50) UNIQUE NOT NULL, -- e.g., 'sbi_mf', 'hdfc_mf'
    amc_name VARCHAR(200) NOT NULL,
    base_url TEXT NOT NULL,
    page_type VARCHAR(20) NOT NULL DEFAULT 'JS_SPA',
    discovery_strategy VARCHAR(30) NOT NULL DEFAULT 'link_extraction',
    selectors JSONB DEFAULT '{}', -- CSS selectors for page elements
    anti_bot_config JSONB DEFAULT '{}', -- stealth settings
    file_types TEXT[] DEFAULT ARRAY['xlsx', 'pdf'],
    schedule_cron VARCHAR(100),
    enabled BOOLEAN NOT NULL DEFAULT true,
    last_crawled_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    page_structure_hash VARCHAR(64), -- for drift detection
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===== Table 2: discovered_document =====
CREATE TABLE discovered_document (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id UUID NOT NULL REFERENCES source_config(id),
    url TEXT NOT NULL,
    filename VARCHAR(500),
    file_type VARCHAR(20),
    file_size_bytes BIGINT,
    file_hash_sha256 VARCHAR(64),
    content_hash VARCHAR(64), -- hash of extracted text content
    url_fingerprint VARCHAR(64) NOT NULL, -- normalized URL hash for dedup
    local_path TEXT, -- path to downloaded file
    is_novel BOOLEAN NOT NULL DEFAULT true,
    status VARCHAR(20) NOT NULL DEFAULT 'DISCOVERED',
    download_attempts INT NOT NULL DEFAULT 0,
    last_error TEXT,
    page_context JSONB DEFAULT '{}', -- text around download link, dropdown values
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    downloaded_at TIMESTAMPTZ,
    pipeline_run_id UUID, -- links to a specific pipeline execution
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(url_fingerprint, source_id)
);

-- ===== Table 3: classified_document =====
CREATE TABLE classified_document (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES discovered_document(id),
    amc_name VARCHAR(200),
    scheme_name VARCHAR(500),
    scheme_category VARCHAR(100), -- equity, debt, hybrid, etc.
    period_month INT, -- 1-12
    period_year INT,
    period_label VARCHAR(50), -- e.g., "June 2026"
    doc_type VARCHAR(100), -- portfolio, factsheet, etc.
    confidence_score FLOAT NOT NULL DEFAULT 0.0,
    classification_signals JSONB NOT NULL DEFAULT '{}', -- full breakdown per channel
    filename_signal JSONB DEFAULT '{}',
    url_signal JSONB DEFAULT '{}',
    page_context_signal JSONB DEFAULT '{}',
    doc_header_signal JSONB DEFAULT '{}',
    is_quarantined BOOLEAN NOT NULL DEFAULT false,
    quarantine_reason VARCHAR(30),
    quarantine_details TEXT,
    reviewed_by VARCHAR(200),
    review_decision VARCHAR(20),
    review_notes TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===== Table 4: staging_data =====
CREATE TABLE staging_data (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES discovered_document(id),
    classification_id UUID REFERENCES classified_document(id),
    idempotency_key VARCHAR(128) UNIQUE NOT NULL,
    raw_data JSONB NOT NULL, -- extracted raw rows
    page_number INT,
    table_index INT,
    row_count INT,
    column_names TEXT[],
    header_hash VARCHAR(64), -- for drift detection
    extraction_metadata JSONB DEFAULT '{}', -- parser used, confidence, etc.
    content_hash VARCHAR(64), -- hash of raw_data for change detection
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===== Table 5: validated_data =====
CREATE TABLE validated_data (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    staging_id UUID NOT NULL REFERENCES staging_data(id),
    document_id UUID NOT NULL REFERENCES discovered_document(id),
    clean_data JSONB NOT NULL, -- normalized/cleaned data
    validation_status VARCHAR(20) NOT NULL DEFAULT 'PENDING', -- PASSED, FAILED, WARNING
    validation_errors JSONB DEFAULT '[]',
    validation_warnings JSONB DEFAULT '[]',
    drift_score FLOAT DEFAULT 0.0,
    drift_details JSONB DEFAULT '{}',
    business_rules_passed BOOLEAN NOT NULL DEFAULT false,
    validated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===== Table 6: published_data =====
CREATE TABLE published_data (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    validated_id UUID NOT NULL REFERENCES validated_data(id),
    document_id UUID NOT NULL REFERENCES discovered_document(id),
    idempotency_key VARCHAR(128) UNIQUE NOT NULL,
    amc_name VARCHAR(200) NOT NULL,
    scheme_name VARCHAR(500) NOT NULL,
    scheme_category VARCHAR(100),
    period_month INT NOT NULL,
    period_year INT NOT NULL,
    isin VARCHAR(100),
    instrument_name TEXT,
    instrument_type VARCHAR(100),
    quantity NUMERIC(20, 4),
    market_value NUMERIC(20, 4),
    pct_to_net_assets NUMERIC(8, 4),
    rating VARCHAR(50),
    industry VARCHAR(200),
    version INT NOT NULL DEFAULT 1,
    is_current BOOLEAN NOT NULL DEFAULT true, -- for versioning
    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===== Table 7: drift_detection =====
CREATE TABLE drift_detection (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id UUID NOT NULL REFERENCES source_config(id),
    document_id UUID REFERENCES discovered_document(id),
    detection_type VARCHAR(50) NOT NULL, -- page_structure, table_header, column_count, schema_validation, visual
    severity VARCHAR(20) NOT NULL DEFAULT 'WARNING',
    previous_signature JSONB, -- baseline signature
    current_signature JSONB, -- current signature
    similarity_score FLOAT,
    description TEXT,
    alert_sent BOOLEAN NOT NULL DEFAULT false,
    resolved BOOLEAN NOT NULL DEFAULT false,
    resolved_by VARCHAR(200),
    resolved_at TIMESTAMPTZ,
    resolution_notes TEXT,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===== Table 8: audit_log =====
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type VARCHAR(50) NOT NULL, -- source_config, discovered_document, etc.
    entity_id UUID NOT NULL,
    action VARCHAR(20) NOT NULL,
    before_state JSONB,
    after_state JSONB,
    actor VARCHAR(200) NOT NULL DEFAULT 'system',
    pipeline_run_id UUID,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===== Table 9: pipeline_run =====
CREATE TABLE pipeline_run (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id UUID REFERENCES source_config(id),
    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING', -- RUNNING, COMPLETED, FAILED, PARTIAL
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    documents_discovered INT DEFAULT 0,
    documents_novel INT DEFAULT 0,
    documents_classified INT DEFAULT 0,
    documents_quarantined INT DEFAULT 0,
    documents_extracted INT DEFAULT 0,
    documents_published INT DEFAULT 0,
    errors JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===== Indexes =====
CREATE INDEX idx_discovered_doc_source ON discovered_document(source_id);
CREATE INDEX idx_discovered_doc_status ON discovered_document(status);
CREATE INDEX idx_discovered_doc_url_fp ON discovered_document(url_fingerprint);
CREATE INDEX idx_discovered_doc_file_hash ON discovered_document(file_hash_sha256);
CREATE INDEX idx_classified_doc_document ON classified_document(document_id);
CREATE INDEX idx_classified_doc_quarantine ON classified_document(is_quarantined) WHERE is_quarantined = true;
CREATE INDEX idx_classified_doc_confidence ON classified_document(confidence_score);
CREATE INDEX idx_staging_data_document ON staging_data(document_id);
CREATE INDEX idx_staging_data_header_hash ON staging_data(header_hash);
CREATE INDEX idx_validated_data_staging ON validated_data(staging_id);
CREATE INDEX idx_published_data_amc_period ON published_data(amc_name, period_year, period_month);
CREATE INDEX idx_published_data_isin ON published_data(isin);
CREATE INDEX idx_published_data_current ON published_data(is_current) WHERE is_current = true;
CREATE INDEX idx_drift_detection_source ON drift_detection(source_id);
CREATE INDEX idx_drift_unresolved ON drift_detection(resolved) WHERE resolved = false;
CREATE INDEX idx_audit_log_entity ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_log_run ON audit_log(pipeline_run_id);
CREATE INDEX idx_pipeline_run_source ON pipeline_run(source_id);
CREATE INDEX idx_pipeline_run_status ON pipeline_run(status);

-- ===== Updated_at trigger =====
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_source_config_updated_at BEFORE UPDATE ON source_config FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_discovered_document_updated_at BEFORE UPDATE ON discovered_document FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_classified_document_updated_at BEFORE UPDATE ON classified_document FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_staging_data_updated_at BEFORE UPDATE ON staging_data FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_validated_data_updated_at BEFORE UPDATE ON validated_data FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
