"""URL signal extractor — Channel 2 of 4.

Extracts classification signals from URL path segments, query parameters,
and the source configuration mapping.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse, parse_qs

from models.schemas import SignalResult
from observability.logger import get_logger

logger = get_logger(__name__, component="classification", channel="url")

# URL path segment → AMC mapping
URL_AMC_PATTERNS = {
    r"sbimf\.com": "SBI Mutual Fund",
    r"sbi.*mf": "SBI Mutual Fund",
    r"hdfcfund\.com": "HDFC Mutual Fund",
    r"hdfc.*fund": "HDFC Mutual Fund",
    r"icicipruamc\.com": "ICICI Prudential Mutual Fund",
    r"icici.*pru": "ICICI Prudential Mutual Fund",
    r"nipponindiaim\.com": "Nippon India Mutual Fund",
    r"utimf\.com": "UTI Mutual Fund",
    r"kotakmf\.com": "Kotak Mahindra Mutual Fund",
    r"axismf\.com": "Axis Mutual Fund",
    r"adityabirlacapital\.com": "Aditya Birla Sun Life Mutual Fund",
    r"dspim\.com": "DSP Mutual Fund",
    r"miraeassetmf": "Mirae Asset Mutual Fund",
}

# URL path segments that indicate document type
PATH_DOC_TYPE_INDICATORS = {
    "portfolio": "portfolio_disclosure",
    "portfolios": "portfolio_disclosure",
    "factsheet": "factsheet",
    "fact-sheet": "factsheet",
    "disclosure": "portfolio_disclosure",
    "statutory-disclosure": "portfolio_disclosure",
    "statutory-disclosures": "portfolio_disclosure",
    "monthly-portfolio": "portfolio_disclosure",
    "monthly-portfolio-disclosures": "portfolio_disclosure",
    "downloads": "portfolio_disclosure",
    "annual-report": "annual_report",
}

# Month names in URL paths
URL_MONTH_PATTERNS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "oct": 10, "nov": 11, "dec": 12,
}


def extract_url_signals(
    url: str,
    source_amc: Optional[str] = None,
) -> SignalResult:
    """Extract classification signals from a document URL.
    
    Analyzes URL components:
    - Domain → AMC identification
    - Path segments → document type, period hints
    - Query parameters → scheme, period, category filters
    
    Args:
        url: Full URL of the document
        source_amc: Known AMC name from source config (high confidence)
        
    Returns:
        SignalResult with extracted signals and confidence score
    """
    result = SignalResult(channel="url")
    
    if not url:
        result.confidence = 0.0
        result.reasoning = "No URL available"
        return result
    
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()
    path_segments = [s for s in path.split("/") if s]
    query_params = parse_qs(parsed.query)
    
    raw_signals = {
        "domain": domain,
        "path_segments": path_segments,
        "query_params": {k: v[0] if len(v) == 1 else v for k, v in query_params.items()},
    }
    signals_found = 0
    
    # --- Extract AMC from domain ---
    for pattern, amc_name in URL_AMC_PATTERNS.items():
        if re.search(pattern, domain):
            result.amc_name = amc_name
            raw_signals["amc_domain_match"] = pattern
            signals_found += 1
            break
    
    # Use source AMC as strong fallback
    if not result.amc_name and source_amc:
        result.amc_name = source_amc
        raw_signals["amc_source"] = "source_config"
        signals_found += 1
    
    # --- Extract Document Type from path ---
    for segment in path_segments:
        if segment in PATH_DOC_TYPE_INDICATORS:
            result.doc_type = PATH_DOC_TYPE_INDICATORS[segment]
            raw_signals["doc_type_segment"] = segment
            signals_found += 1
            break
    
    # --- Extract Period from path segments ---
    for segment in path_segments:
        # Check for month names
        seg_lower = segment.lower().replace("-", "").replace("_", "")
        for month_str, month_num in URL_MONTH_PATTERNS.items():
            if month_str in seg_lower:
                result.period_month = month_num
                raw_signals["month_segment"] = segment
                signals_found += 1
                break
        
        # Check for year
        year_match = re.search(r"\b(20[0-9]{2})\b", segment)
        if year_match:
            result.period_year = int(year_match.group(1))
            raw_signals["year_segment"] = segment
            signals_found += 1
        else:
            # Fallback to 2-digit year check
            month_year_match = re.search(
                r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:[_\-\s]+)?([2-3][0-9])\b",
                segment
            )
            if month_year_match:
                result.period_year = 2000 + int(month_year_match.group(1))
                raw_signals["year_segment"] = segment
                signals_found += 1
            else:
                exact_2d_match = re.match(r"^([2-3][0-9])$", segment)
                if exact_2d_match:
                    result.period_year = 2000 + int(exact_2d_match.group(1))
                    raw_signals["year_segment"] = segment
                    signals_found += 1
    
    # --- Extract from query parameters ---
    # Many AMC sites use query params for filtering
    for key, values in query_params.items():
        key_lower = key.lower()
        value = values[0] if values else ""
        value_lower = value.lower()
        
        if key_lower in ("month", "mon", "m"):
            for month_str, month_num in URL_MONTH_PATTERNS.items():
                if month_str in value_lower:
                    result.period_month = month_num
                    raw_signals["month_param"] = value
                    signals_found += 1
                    break
            # Try numeric month
            try:
                m = int(value)
                if 1 <= m <= 12:
                    result.period_month = m
                    signals_found += 1
            except ValueError:
                pass
        
        elif key_lower in ("year", "yr", "y"):
            try:
                y = int(value)
                if 20 <= y <= 30:
                    y = 2000 + y
                if 2020 <= y <= 2030:
                    result.period_year = y
                    raw_signals["year_param"] = value
                    signals_found += 1
            except ValueError:
                pass
        
        elif key_lower in ("scheme", "fund", "schemename"):
            result.scheme_name = value
            raw_signals["scheme_param"] = value
            signals_found += 1
        
        elif key_lower in ("category", "cat", "type"):
            result.scheme_category = value_lower
            raw_signals["category_param"] = value
            signals_found += 1
    
    # --- Calculate confidence ---
    # URL signals are generally reliable for AMC (from domain)
    # but less reliable for specific scheme/period
    max_signals = 4  # AMC, doc_type, month, year
    base_confidence = min(1.0, (signals_found / max_signals) * 1.1)
    
    # Domain-based AMC identification is very reliable
    if result.amc_name and raw_signals.get("amc_domain_match"):
        base_confidence = max(base_confidence, 0.5)
    
    result.confidence = base_confidence
    result.raw_signals = raw_signals
    result.reasoning = (
        f"Extracted {signals_found} signals from URL. "
        f"Domain: {domain}, Path segments: {len(path_segments)}"
    )
    
    logger.debug(
        "url_signals_extracted",
        url=url[:100],
        signals_found=signals_found,
        confidence=result.confidence,
    )
    
    return result
