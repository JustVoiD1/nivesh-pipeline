"""Document classifier — orchestrates all 4 signal channels and confidence scoring.

This is the main entry point for document classification. It:
1. Runs all 4 signal extractors (filename, URL, page context, doc header)
2. Feeds signals into the confidence scoring engine
3. Makes quarantine/accept/reject decisions
4. Returns a fully classified document model
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from classification.confidence import compute_confidence
from classification.signals.doc_header import extract_doc_header_signals
from classification.signals.filename import extract_filename_signals
from classification.signals.page_context import extract_page_context_signals
from classification.signals.url import extract_url_signals
from models.schemas import (
    ClassifiedDocumentModel,
    ConfidenceBreakdown,
    QuarantineReason,
)
from observability.logger import get_logger

logger = get_logger(__name__, component="classification")


class DocumentClassifier:
    """Orchestrates multi-channel document classification.
    
    Combines signals from 4 independent channels to determine:
    - Which AMC this document belongs to
    - Which scheme it's for
    - What period it covers
    - What type of document it is (portfolio, factsheet, etc.)
    - How confident we are in this classification
    """

    def classify(
        self,
        document_id: UUID,
        url: str,
        filename: Optional[str] = None,
        file_path: Optional[str] = None,
        file_type: Optional[str] = None,
        page_context: Optional[dict[str, Any]] = None,
        source_amc: Optional[str] = None,
    ) -> ClassifiedDocumentModel:
        """Classify a document using all available signal channels.
        
        Args:
            document_id: UUID of the discovered document
            url: Document URL
            filename: Original filename
            file_path: Path to downloaded file (for header extraction)
            file_type: File type (pdf, xlsx, etc.)
            page_context: Context captured during discovery
            source_amc: Known AMC from source configuration
            
        Returns:
            ClassifiedDocumentModel with confidence score and signals
        """
        logger.info(
            "classification_started",
            document_id=str(document_id),
            filename=filename,
            url=url[:100],
        )

        # --- Channel 1: Filename signals (weight: 0.20) ---
        filename_signal = extract_filename_signals(
            filename=filename,
            source_amc=source_amc,
        )

        # --- Channel 2: URL signals (weight: 0.15) ---
        url_signal = extract_url_signals(
            url=url,
            source_amc=source_amc,
        )

        # --- Channel 3: Page context signals (weight: 0.25) ---
        page_context_signal = extract_page_context_signals(
            page_context=page_context or {},
            source_amc=source_amc,
        )

        # --- Channel 4: Document header signals (weight: 0.40) ---
        doc_header_signal = extract_doc_header_signals(
            file_path=file_path,
            file_type=file_type,
            source_amc=source_amc,
        )

        # --- Compute confidence score ---
        breakdown = compute_confidence(
            filename_signal=filename_signal,
            url_signal=url_signal,
            page_context_signal=page_context_signal,
            doc_header_signal=doc_header_signal,
            source_amc=source_amc,
        )

        # --- Build classified document ---
        classified = ClassifiedDocumentModel(
            document_id=document_id,
            amc_name=breakdown.final_amc_name,
            scheme_name=breakdown.final_scheme_name,
            scheme_category=breakdown.final_scheme_category,
            period_month=breakdown.final_period_month,
            period_year=breakdown.final_period_year,
            doc_type=breakdown.final_doc_type,
            confidence_score=breakdown.final_confidence,
            confidence_breakdown=breakdown,
        )

        # Generate period label
        if classified.period_month and classified.period_year:
            month_names = [
                "", "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December",
            ]
            classified.period_label = (
                f"{month_names[classified.period_month]} {classified.period_year}"
            )

        # --- Apply quarantine logic ---
        if breakdown.decision in ("QUARANTINE", "REJECT"):
            classified.is_quarantined = True
            
            # Determine primary quarantine reason
            if breakdown.decision == "REJECT":
                classified.quarantine_reason = QuarantineReason.LOW_CONFIDENCE
            elif any("contradict" in r.lower() for r in breakdown.quarantine_reasons):
                classified.quarantine_reason = QuarantineReason.CLASSIFICATION_CONFLICT
            elif any("stale" in r.lower() or "old" in r.lower() for r in breakdown.quarantine_reasons):
                classified.quarantine_reason = QuarantineReason.STALE_PERIOD
            elif any("scheme" in r.lower() for r in breakdown.quarantine_reasons):
                classified.quarantine_reason = QuarantineReason.UNKNOWN_SCHEME
            else:
                classified.quarantine_reason = QuarantineReason.LOW_CONFIDENCE
            
            classified.quarantine_details = "; ".join(breakdown.quarantine_reasons)

        logger.info(
            "classification_completed",
            document_id=str(document_id),
            confidence=round(breakdown.final_confidence, 4),
            decision=breakdown.decision,
            amc=classified.amc_name,
            scheme=classified.scheme_name,
            period=classified.period_label,
            quarantined=classified.is_quarantined,
        )

        return classified
