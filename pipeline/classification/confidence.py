"""Confidence scoring engine — the core of identity resolution.

Implements a 4-channel weighted scoring system that combines signals from
filename, URL, page context, and document headers to produce a final
confidence score for document classification.

Channel Weights:
  doc_headers:   0.40 (most reliable — from document content itself)
  page_context:  0.25 (dropdown values, surrounding text)
  filename:      0.20 (regex patterns, fuzzy matching)
  url_signals:   0.15 (URL path/domain analysis)

Scoring Modifiers:
  Agreement bonus:     +0.10 if ≥3 channels agree on a field
  Disagreement penalty: -0.15 if channels actively contradict

Decision Thresholds:
  ≥0.85: AUTO_ACCEPT — high confidence, all signals align
  0.70-0.85: ACCEPT_WITH_FLAG — minor uncertainty
  0.50-0.70: QUARANTINE — requires manual review
  <0.50: REJECT — too uncertain, log and alert
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from models.schemas import (
    ConfidenceBreakdown,
    QuarantineReason,
    SignalResult,
)
from observability.logger import get_logger

logger = get_logger(__name__, component="classification", channel="confidence")

# Channel weights (must sum to 1.0)
WEIGHTS = {
    "doc_header": 0.40,
    "page_context": 0.25,
    "filename": 0.20,
    "url": 0.15,
}

# Scoring modifiers
AGREEMENT_BONUS = 0.10       # Applied when ≥3 channels agree
DISAGREEMENT_PENALTY = 0.15  # Applied when channels contradict

# Decision thresholds (configurable via environment)
THRESHOLD_AUTO_ACCEPT = float(os.getenv("CONFIDENCE_THRESHOLD_AUTO", "0.85"))
THRESHOLD_ACCEPT_FLAG = float(os.getenv("CONFIDENCE_THRESHOLD_ACCEPT", "0.70"))
THRESHOLD_QUARANTINE = float(os.getenv("CONFIDENCE_THRESHOLD_QUARANTINE", "0.50"))

# Staleness check: flag documents with period >6 months old
STALE_MONTHS = 6


def _values_agree(values: list[Optional[str]], min_agree: int = 3) -> bool:
    """Check if at least min_agree non-None values match (case-insensitive)."""
    non_none = [v.lower().strip() for v in values if v]
    if len(non_none) < min_agree:
        return False
    # Check if the majority agrees
    from collections import Counter
    counts = Counter(non_none)
    most_common_count = counts.most_common(1)[0][1] if counts else 0
    return most_common_count >= min_agree


def _values_contradict(values: list[Optional[str]]) -> bool:
    """Check if non-None values actively contradict each other."""
    non_none = [v.lower().strip() for v in values if v]
    unique = set(non_none)
    # Contradiction: 2+ distinct non-empty values
    return len(unique) > 1 and len(non_none) >= 2


def _select_best_value(
    signals: list[tuple[Optional[str], float, str]],
) -> Optional[str]:
    """Select the best value from multiple channels, weighted by confidence.
    
    Args:
        signals: List of (value, weight * confidence, channel_name) tuples
        
    Returns:
        The highest-weighted non-None value
    """
    scored = [
        (value, score, channel)
        for value, score, channel in signals
        if value is not None
    ]
    if not scored:
        return None
    
    # Sort by weighted score descending
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0]


def compute_confidence(
    filename_signal: SignalResult,
    url_signal: SignalResult,
    page_context_signal: SignalResult,
    doc_header_signal: SignalResult,
    source_amc: Optional[str] = None,
) -> ConfidenceBreakdown:
    """Compute the final confidence score from all 4 signal channels.
    
    This is the core scoring algorithm:
    1. Calculate weighted average of channel confidences
    2. Apply agreement bonus if ≥3 channels agree on key fields
    3. Apply disagreement penalty if channels contradict
    4. Determine decision (AUTO_ACCEPT / ACCEPT_WITH_FLAG / QUARANTINE / REJECT)
    5. Check additional quarantine triggers
    
    Args:
        filename_signal: Results from filename analysis
        url_signal: Results from URL analysis
        page_context_signal: Results from page context analysis
        doc_header_signal: Results from document header analysis
        source_amc: Known AMC from source configuration
        
    Returns:
        Complete ConfidenceBreakdown with scoring details and decision
    """
    breakdown = ConfidenceBreakdown(
        filename_signal=filename_signal,
        url_signal=url_signal,
        page_context_signal=page_context_signal,
        doc_header_signal=doc_header_signal,
    )
    
    channels = {
        "doc_header": doc_header_signal,
        "page_context": page_context_signal,
        "filename": filename_signal,
        "url": url_signal,
    }
    
    # === Step 1: Weighted average of channel confidences ===
    weighted_sum = sum(
        WEIGHTS[name] * signal.confidence
        for name, signal in channels.items()
    )
    breakdown.weighted_score = weighted_sum
    
    # === Step 2: Resolve identity fields ===
    # For each field, select the best value across channels
    
    # AMC Name resolution
    amc_values = [
        (s.amc_name, WEIGHTS[name] * s.confidence, name)
        for name, s in channels.items()
    ]
    breakdown.final_amc_name = _select_best_value(amc_values) or source_amc
    
    # Scheme Name resolution
    scheme_values = [
        (s.scheme_name, WEIGHTS[name] * s.confidence, name)
        for name, s in channels.items()
    ]
    breakdown.final_scheme_name = _select_best_value(scheme_values)
    
    # Period Month resolution
    month_values = [
        (str(s.period_month) if s.period_month else None, WEIGHTS[name] * s.confidence, name)
        for name, s in channels.items()
    ]
    best_month = _select_best_value(month_values)
    breakdown.final_period_month = int(best_month) if best_month else None
    
    # Period Year resolution
    year_values = [
        (str(s.period_year) if s.period_year else None, WEIGHTS[name] * s.confidence, name)
        for name, s in channels.items()
    ]
    best_year = _select_best_value(year_values)
    breakdown.final_period_year = int(best_year) if best_year else None
    
    # Scheme Category resolution
    cat_values = [
        (s.scheme_category, WEIGHTS[name] * s.confidence, name)
        for name, s in channels.items()
    ]
    breakdown.final_scheme_category = _select_best_value(cat_values)
    
    # Doc Type resolution
    doctype_values = [
        (s.doc_type, WEIGHTS[name] * s.confidence, name)
        for name, s in channels.items()
    ]
    breakdown.final_doc_type = _select_best_value(doctype_values)
    
    # === Step 3: Agreement bonus ===
    agreement_bonus = 0.0
    
    # Check AMC agreement
    amc_list = [s.amc_name for _, s in channels.items()]
    if _values_agree(amc_list, min_agree=3):
        agreement_bonus += AGREEMENT_BONUS / 2
    elif len([a for a in amc_list if a]) == 2 and len(set([a.lower() for a in amc_list if a])) == 1:
        agreement_bonus += AGREEMENT_BONUS / 4
    
    # Check period agreement
    period_strs = [
        f"{s.period_month}-{s.period_year}" if s.period_month and s.period_year else None
        for _, s in channels.items()
    ]
    period_non_none = [p for p in period_strs if p]
    if len(period_non_none) >= 3 and len(set(period_non_none)) == 1:
        agreement_bonus += AGREEMENT_BONUS / 2
    elif len(period_non_none) == 2 and len(set(period_non_none)) == 1:
        agreement_bonus += AGREEMENT_BONUS / 4
    
    breakdown.agreement_bonus = agreement_bonus
    
    # === Step 4: Disagreement penalty ===
    disagreement_penalty = 0.0
    quarantine_reasons = []
    
    # Check AMC contradiction (different AMCs from different channels)
    if _values_contradict(amc_list):
        disagreement_penalty += DISAGREEMENT_PENALTY
        quarantine_reasons.append("AMC signals contradict across channels")
    
    # Check AMC mismatch with source config
    if (source_amc and breakdown.final_amc_name and
            source_amc.lower() != breakdown.final_amc_name.lower()):
        disagreement_penalty += DISAGREEMENT_PENALTY / 2
        quarantine_reasons.append(
            f"AMC mismatch: source={source_amc}, resolved={breakdown.final_amc_name}"
        )
    
    # Check period contradiction
    month_list = [str(s.period_month) for _, s in channels.items() if s.period_month]
    if _values_contradict(month_list):
        disagreement_penalty += DISAGREEMENT_PENALTY / 2
        quarantine_reasons.append("Period month contradicts across channels")
    
    breakdown.disagreement_penalty = disagreement_penalty
    
    # === Step 5: Final score ===
    final = weighted_sum + agreement_bonus - disagreement_penalty
    final = max(0.0, min(1.0, final))  # Clamp to [0, 1]
    breakdown.final_confidence = final
    
    # === Step 6: Decision logic ===
    if final >= THRESHOLD_AUTO_ACCEPT:
        breakdown.decision = "AUTO_ACCEPT"
    elif final >= THRESHOLD_ACCEPT_FLAG:
        breakdown.decision = "ACCEPT_WITH_FLAG"
    elif final >= THRESHOLD_QUARANTINE:
        breakdown.decision = "QUARANTINE"
        quarantine_reasons.append(f"Confidence {final:.2f} below accept threshold {THRESHOLD_ACCEPT_FLAG}")
    else:
        breakdown.decision = "REJECT"
        quarantine_reasons.append(f"Confidence {final:.2f} below quarantine threshold {THRESHOLD_QUARANTINE}")
    
    # === Step 7: Additional quarantine triggers ===
    
    # Missing essential fields
    if not breakdown.final_amc_name:
        breakdown.decision = "QUARANTINE"
        quarantine_reasons.append("AMC name could not be determined")
    
    if not breakdown.final_period_month or not breakdown.final_period_year:
        if breakdown.decision == "AUTO_ACCEPT":
            breakdown.decision = "ACCEPT_WITH_FLAG"
        quarantine_reasons.append("Period (month/year) could not be fully determined")
    
    # Staleness check
    if breakdown.final_period_month and breakdown.final_period_year:
        try:
            doc_date = datetime(breakdown.final_period_year, breakdown.final_period_month, 1)
            months_old = (datetime.utcnow() - doc_date).days / 30
            if months_old > STALE_MONTHS:
                if breakdown.decision in ("AUTO_ACCEPT", "ACCEPT_WITH_FLAG"):
                    breakdown.decision = "QUARANTINE"
                quarantine_reasons.append(
                    f"Document period is {months_old:.0f} months old (threshold: {STALE_MONTHS})"
                )
        except (ValueError, OverflowError):
            pass
    
    breakdown.quarantine_reasons = quarantine_reasons
    
    logger.info(
        "confidence_computed",
        final_confidence=round(final, 4),
        weighted_score=round(weighted_sum, 4),
        agreement_bonus=round(agreement_bonus, 4),
        disagreement_penalty=round(disagreement_penalty, 4),
        decision=breakdown.decision,
        amc=breakdown.final_amc_name,
        period=f"{breakdown.final_period_month}/{breakdown.final_period_year}",
        quarantine_reasons=len(quarantine_reasons),
    )
    
    return breakdown
