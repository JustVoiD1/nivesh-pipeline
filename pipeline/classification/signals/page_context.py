"""Page context signal extractor — Channel 3 of 4.

Extracts classification signals from the context surrounding a download
link on the source page: dropdown selections, nearby text, data attributes,
and DOM metadata captured during discovery.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from rapidfuzz import fuzz

from config.loader import load_scheme_master
from models.schemas import SignalResult
from observability.logger import get_logger

logger = get_logger(__name__, component="classification", channel="page_context")

# Month name patterns for text extraction
MONTH_TEXT_PATTERNS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "oct": 10, "nov": 11, "dec": 12,
}

# Document type indicators in page text
TEXT_DOC_TYPE_PATTERNS = {
    r"monthly\s+portfolio": "portfolio_disclosure",
    r"portfolio\s+disclosure": "portfolio_disclosure",
    r"scheme\s+portfolio": "portfolio_disclosure",
    r"factsheet": "factsheet",
    r"fact\s+sheet": "factsheet",
    r"half[\s-]?yearly": "half_yearly_report",
    r"fortnightly": "fortnightly_disclosure",
    r"annual\s+report": "annual_report",
}

# Category indicators in surrounding text
TEXT_CATEGORY_PATTERNS = {
    r"\bequity\b": "equity",
    r"\bdebt\b": "debt",
    r"\bhybrid\b": "hybrid",
    r"\bliquid\b": "debt",
    r"\bbalanced\b": "hybrid",
    r"\bflexi[\s-]?cap\b": "equity",
    r"\blarge[\s-]?cap\b": "equity",
    r"\bmid[\s-]?cap\b": "equity",
    r"\bsmall[\s-]?cap\b": "equity",
    r"\bgilt\b": "debt",
    r"\belss\b": "equity",
}


def _extract_period_from_text(text: str) -> tuple[Optional[int], Optional[int]]:
    """Extract month and year from free-form text.
    
    Handles patterns like:
    - "June 2026" or "June-26" or "June 26"
    - "Portfolio as on 31st May 2026"
    - "For the month of April, 2026"
    - "2026-06" (ISO format)
    
    Returns:
        Tuple of (month, year) or (None, None)
    """
    text_lower = text.lower()
    month = None
    year = None
    
    # Pattern 1: "Month Year" (e.g., "June 2026" or "June-26")
    for month_name, month_num in MONTH_TEXT_PATTERNS.items():
        pattern = rf"\b{month_name}\b\s*(?:[_\-\s]+)?\b(20[0-9]{{2}}|[2-3][0-9])\b"
        match = re.search(pattern, text_lower)
        if match:
            month = month_num
            year_val = int(match.group(1))
            if year_val < 100:
                year_val = 2000 + year_val
            return month, year_val
    
    # Pattern 2: "Year Month" or contextual
    year_match = re.search(r"\b(20[0-9]{2})\b", text)
    if year_match:
        year = int(year_match.group(1))
    else:
        # Fallback to 2-digit year check in text
        for token in re.split(r"[_\-\s.,/]+", text_lower):
            if token.isdigit() and len(token) == 2:
                val = int(token)
                if 20 <= val <= 30:
                    year = 2000 + val
                    break
    
    for month_name, month_num in MONTH_TEXT_PATTERNS.items():
        if re.search(rf"\b{month_name}\b", text_lower):
            month = month_num
            break
    
    return month, year


def extract_page_context_signals(
    page_context: dict[str, Any],
    source_amc: Optional[str] = None,
) -> SignalResult:
    """Extract classification signals from page context captured during discovery.
    
    Analyzes:
    - Link text and title attributes
    - Parent/grandparent element text (surrounding context)
    - Active dropdown/select values
    - Data-* attributes
    
    Args:
        page_context: Context dictionary captured by the discovery engine
        source_amc: Known AMC from source config
        
    Returns:
        SignalResult with extracted signals and confidence score
    """
    result = SignalResult(channel="page_context")
    
    if not page_context:
        result.confidence = 0.0
        result.reasoning = "No page context available"
        return result
    
    raw_signals = {}
    signals_found = 0
    
    # Collect all text from page context
    link_text = page_context.get("link_text", "")
    parent_text = page_context.get("parent_text", "")
    grandparent_text = page_context.get("grandparent_text", "")
    title = page_context.get("title", "")
    aria_label = page_context.get("aria_label", "")
    data_attrs = page_context.get("data_attrs", {})
    dropdowns = page_context.get("active_dropdowns", {})
    
    all_text = f"{link_text} {parent_text} {title} {aria_label}"
    all_text_lower = all_text.lower()
    
    # --- AMC from source config (high confidence when from page context) ---
    if source_amc:
        result.amc_name = source_amc
        raw_signals["amc_source"] = "source_config"
        signals_found += 1
    
    # --- Extract Period from dropdowns (very reliable) ---
    for dropdown_name, dropdown_value in dropdowns.items():
        name_lower = dropdown_name.lower()
        value_lower = dropdown_value.lower()
        
        if any(k in name_lower for k in ("month", "period", "mon")):
            month, year = _extract_period_from_text(dropdown_value)
            if month:
                result.period_month = month
                raw_signals["month_dropdown"] = {
                    "name": dropdown_name,
                    "value": dropdown_value,
                }
                signals_found += 1
            if year:
                result.period_year = year
                raw_signals["year_dropdown_from_month"] = year
                signals_found += 1
        
        elif any(k in name_lower for k in ("year", "yr")):
            try:
                y = int(dropdown_value.strip())
                if 20 <= y <= 30:
                    y = 2000 + y
                if 2020 <= y <= 2030:
                    result.period_year = y
                    raw_signals["year_dropdown"] = {
                        "name": dropdown_name,
                        "value": dropdown_value,
                    }
                    signals_found += 1
            except ValueError:
                pass
        
        elif any(k in name_lower for k in ("scheme", "fund", "category")):
            result.scheme_name = dropdown_value
            raw_signals["scheme_dropdown"] = {
                "name": dropdown_name,
                "value": dropdown_value,
            }
            signals_found += 1
    
    # --- Extract Period from surrounding text ---
    if not result.period_month or not result.period_year:
        month, year = _extract_period_from_text(all_text)
        if month and not result.period_month:
            result.period_month = month
            raw_signals["month_from_text"] = month
            signals_found += 1
        if year and not result.period_year:
            result.period_year = year
            raw_signals["year_from_text"] = year
            signals_found += 1
    
    # --- Extract Document Type ---
    for pattern, doc_type in TEXT_DOC_TYPE_PATTERNS.items():
        if re.search(pattern, all_text_lower):
            result.doc_type = doc_type
            raw_signals["doc_type_text_match"] = pattern
            signals_found += 1
            break
    
    # --- Extract Scheme Category ---
    for pattern, category in TEXT_CATEGORY_PATTERNS.items():
        if re.search(pattern, all_text_lower):
            result.scheme_category = category
            raw_signals["category_text_match"] = pattern
            signals_found += 1
            break
    
    # --- Extract from data-* attributes ---
    for attr_name, attr_value in data_attrs.items():
        attr_lower = attr_name.lower()
        if "scheme" in attr_lower or "fund" in attr_lower:
            result.scheme_name = result.scheme_name or attr_value
            raw_signals["scheme_data_attr"] = {attr_name: attr_value}
            signals_found += 1
        elif "month" in attr_lower or "period" in attr_lower:
            month, year = _extract_period_from_text(attr_value)
            if month and not result.period_month:
                result.period_month = month
                signals_found += 1
            if year and not result.period_year:
                result.period_year = year
                signals_found += 1
    
    # --- Fuzzy match scheme from text ---
    if not result.scheme_name and all_text:
        scheme_master = load_scheme_master()
        best_score = 0
        best_name = None
        
        for amc_key, amc_data in scheme_master.get("amcs", {}).items():
            for scheme in amc_data.get("schemes", []):
                candidates = [scheme["name"]] + scheme.get("aliases", [])
                for candidate in candidates:
                    score = fuzz.partial_ratio(candidate.lower(), all_text_lower)
                    if score > best_score and score > 70:
                        best_score = score
                        best_name = scheme["name"]
                        result.scheme_category = scheme.get("category")
        
        if best_name:
            result.scheme_name = best_name
            raw_signals["scheme_fuzzy_from_text"] = {
                "name": best_name,
                "score": best_score,
            }
            signals_found += 1
    
    # --- Calculate confidence ---
    max_signals = 5
    base_confidence = min(1.0, (signals_found / max_signals) * 1.1)
    
    # Dropdown values are very reliable
    if raw_signals.get("month_dropdown") or raw_signals.get("scheme_dropdown"):
        base_confidence = min(1.0, base_confidence + 0.15)
    
    result.confidence = base_confidence
    result.raw_signals = raw_signals
    result.reasoning = (
        f"Extracted {signals_found} signals from page context. "
        f"Dropdowns: {len(dropdowns)}, Text length: {len(all_text)}"
    )
    
    logger.debug(
        "page_context_signals_extracted",
        signals_found=signals_found,
        confidence=result.confidence,
        has_dropdowns=bool(dropdowns),
    )
    
    return result
