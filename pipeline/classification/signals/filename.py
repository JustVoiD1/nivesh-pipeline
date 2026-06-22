"""Filename signal extractor — Channel 1 of 4.

Extracts AMC name, scheme name, period (month/year), and document type
from the document filename using regex patterns and fuzzy matching.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz

from config.loader import load_scheme_master
from models.schemas import SignalResult
from observability.logger import get_logger

logger = get_logger(__name__, component="classification", channel="filename")

# Pre-compiled regex patterns for common filename elements
MONTH_PATTERNS = {
    r"\b(jan(?:uary)?)\b": (1, "January"),
    r"\b(feb(?:ruary)?)\b": (2, "February"),
    r"\b(mar(?:ch)?)\b": (3, "March"),
    r"\b(apr(?:il)?)\b": (4, "April"),
    r"\b(may)\b": (5, "May"),
    r"\b(jun(?:e)?)\b": (6, "June"),
    r"\b(jul(?:y)?)\b": (7, "July"),
    r"\b(aug(?:ust)?)\b": (8, "August"),
    r"\b(sep(?:t(?:ember)?)?)\b": (9, "September"),
    r"\b(oct(?:ober)?)\b": (10, "October"),
    r"\b(nov(?:ember)?)\b": (11, "November"),
    r"\b(dec(?:ember)?)\b": (12, "December"),
}

YEAR_PATTERN = re.compile(r"\b(20[0-9]{2})\b")

# AMC name indicators in filenames
AMC_FILENAME_INDICATORS = {
    "sbi": "SBI Mutual Fund",
    "sbimf": "SBI Mutual Fund",
    "hdfc": "HDFC Mutual Fund",
    "hdfcfund": "HDFC Mutual Fund",
    "icici": "ICICI Prudential Mutual Fund",
    "icicipru": "ICICI Prudential Mutual Fund",
    "nippon": "Nippon India Mutual Fund",
    "uti": "UTI Mutual Fund",
    "kotak": "Kotak Mahindra Mutual Fund",
    "axis": "Axis Mutual Fund",
    "birla": "Aditya Birla Sun Life Mutual Fund",
    "absl": "Aditya Birla Sun Life Mutual Fund",
    "dsp": "DSP Mutual Fund",
    "mirae": "Mirae Asset Mutual Fund",
}

# Document type indicators
DOC_TYPE_INDICATORS = {
    "portfolio": "portfolio_disclosure",
    "factsheet": "factsheet",
    "disclosure": "portfolio_disclosure",
    "monthly": "portfolio_disclosure",
    "fortnightly": "fortnightly_disclosure",
    "halfyearly": "half_yearly_report",
    "half_yearly": "half_yearly_report",
    "annual": "annual_report",
}

# Scheme category indicators
CATEGORY_INDICATORS = {
    "equity": "equity",
    "debt": "debt",
    "hybrid": "hybrid",
    "liquid": "debt",
    "balanced": "hybrid",
    "flexi": "equity",
    "bluechip": "equity",
    "midcap": "equity",
    "smallcap": "equity",
    "largecap": "equity",
    "gilt": "debt",
    "bond": "debt",
    "elss": "equity",
    "arbitrage": "hybrid",
    "overnight": "debt",
    "index": "other",
    "etf": "other",
}


def extract_filename_signals(
    filename: Optional[str],
    source_amc: Optional[str] = None,
) -> SignalResult:
    """Extract classification signals from a document filename.
    
    Parses the filename to extract:
    - AMC name (from known indicators)
    - Scheme name / category (from keywords and fuzzy matching)
    - Period month and year (from date patterns)
    - Document type (portfolio, factsheet, etc.)
    
    Args:
        filename: The document filename (e.g., "MFS_jun.pdf", "HDFC_Equity_May2026.xlsx")
        source_amc: Known AMC from source config (used as fallback)
        
    Returns:
        SignalResult with extracted signals and confidence score
    """
    result = SignalResult(channel="filename")
    
    if not filename:
        result.confidence = 0.0
        result.reasoning = "No filename available"
        return result
    
    # Clean the filename
    name = Path(filename).stem  # Remove extension
    name_lower = name.lower()
    name_parts = re.split(r"[_\-\s.]+", name_lower)
    
    raw_signals = {"original_filename": filename, "parsed_parts": name_parts}
    signals_found = 0
    
    # --- Extract AMC Name ---
    for indicator, amc_name in AMC_FILENAME_INDICATORS.items():
        if indicator in name_lower:
            result.amc_name = amc_name
            raw_signals["amc_indicator"] = indicator
            signals_found += 1
            break
    
    if not result.amc_name and source_amc:
        result.amc_name = source_amc
        raw_signals["amc_source"] = "fallback_from_source_config"
    
    # --- Extract Period (Month) ---
    for pattern, (month_num, month_name) in MONTH_PATTERNS.items():
        if re.search(pattern, name_lower):
            result.period_month = month_num
            raw_signals["month_match"] = month_name
            signals_found += 1
            break
    
    # --- Extract Period (Year) ---
    year_match = YEAR_PATTERN.search(name)
    if year_match:
        year = int(year_match.group(1))
        if 2020 <= year <= 2030:  # Sanity check
            result.period_year = year
            raw_signals["year_match"] = year
            signals_found += 1
    else:
        # Fallback to 2-digit year (e.g., June-26 or May-23 or June23)
        # Check if adjacent to month name first
        month_year_match = re.search(
            r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:[_\-\s]+)?([2-3][0-9])\b",
            name_lower
        )
        if month_year_match:
            year = 2000 + int(month_year_match.group(1))
            result.period_year = year
            raw_signals["year_match"] = year
            signals_found += 1
        # Or if the last token of the filename stem is a 2-digit number (20-30)
        elif name_parts and name_parts[-1].isdigit() and len(name_parts[-1]) == 2:
            val = int(name_parts[-1])
            if 20 <= val <= 30:
                year = 2000 + val
                result.period_year = year
                raw_signals["year_match"] = year
                signals_found += 1
    
    # --- Extract Document Type ---
    for indicator, doc_type in DOC_TYPE_INDICATORS.items():
        if indicator in name_lower:
            result.doc_type = doc_type
            raw_signals["doc_type_indicator"] = indicator
            signals_found += 1
            break
    
    # --- Extract Scheme Category ---
    for indicator, category in CATEGORY_INDICATORS.items():
        if indicator in name_lower:
            result.scheme_category = category
            raw_signals["category_indicator"] = indicator
            signals_found += 1
            break
    
    # --- Fuzzy match scheme name against master list ---
    scheme_master = load_scheme_master()
    best_match_score = 0
    best_match_name = None
    
    for amc_key, amc_data in scheme_master.get("amcs", {}).items():
        for scheme in amc_data.get("schemes", []):
            # Check against scheme name and aliases
            candidates = [scheme["name"]] + scheme.get("aliases", [])
            for candidate in candidates:
                score = fuzz.token_sort_ratio(name_lower, candidate.lower())
                if score > best_match_score and score > 60:
                    best_match_score = score
                    best_match_name = scheme["name"]
                    result.scheme_category = scheme.get("category")
    
    if best_match_name and best_match_score > 60:
        result.scheme_name = best_match_name
        raw_signals["scheme_fuzzy_match"] = {
            "name": best_match_name,
            "score": best_match_score,
        }
        signals_found += 1
    
    # --- Calculate confidence ---
    # More signals extracted = higher confidence
    max_signals = 5  # AMC, month, year, doc_type, scheme
    result.confidence = min(1.0, (signals_found / max_signals) * 1.2)
    
    # Boost if we got the essential trio (AMC + month + year)
    if result.amc_name and result.period_month and result.period_year:
        result.confidence = min(1.0, result.confidence + 0.15)
    
    result.raw_signals = raw_signals
    result.reasoning = (
        f"Extracted {signals_found}/{max_signals} signals from filename '{filename}'. "
        f"Parts: {name_parts}"
    )
    
    logger.debug(
        "filename_signals_extracted",
        filename=filename,
        signals_found=signals_found,
        confidence=result.confidence,
    )
    
    return result
