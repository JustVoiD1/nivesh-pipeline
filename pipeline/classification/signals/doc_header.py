"""Document header signal extractor — Channel 4 of 4.

Extracts classification signals from the document's internal content:
- PDF: Reads first 2 pages to find AMC name, scheme name, "as on" date
- Excel: Reads header rows and sheet names for scheme/period information

This is the most reliable signal channel (weight: 0.40) because it uses
the actual document content rather than external metadata.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from rapidfuzz import fuzz

from config.loader import load_scheme_master
from models.schemas import SignalResult
from observability.logger import get_logger

logger = get_logger(__name__, component="classification", channel="doc_header")

# "As on" date patterns found in Indian MF documents
AS_ON_PATTERNS = [
    r"as\s+on\s+(\d{1,2})\s*(?:st|nd|rd|th)?\s*(january|february|march|april|may|june|july|august|september|october|november|december)\s*,?\s*(20\d{2}|\d{2})\b",
    r"as\s+on\s*(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})\s*(?:st|nd|rd|th)?\s*,?\s*(20\d{2}|\d{2})\b",
    r"as\s+on\s+(\d{1,2})[/\-](\d{1,2})[/\-](20\d{2}|\d{2})\b",
    r"portfolio\s+as\s+(?:on|of)\s+(\d{1,2})\s*(?:st|nd|rd|th)?\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s*,?\s*(20\d{2}|\d{2})\b",
    r"portfolio\s+as\s+(?:on|of)\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(\d{1,2})\s*(?:st|nd|rd|th)?\s*,?\s*(20\d{2}|\d{2})\b",
    r"month\s+(?:of|ending)\s*(january|february|march|april|may|june|july|august|september|october|november|december)\s*,?\s*(20\d{2}|\d{2})\b",
    r"for\s+the\s+month\s+(?:of\s+)?(january|february|march|april|may|june|july|august|september|october|november|december)\s*,?\s*(20\d{2}|\d{2})\b",
]

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "oct": 10, "nov": 11, "dec": 12,
}

# AMC name patterns in document headers
AMC_HEADER_PATTERNS = {
    r"sbi\s+(?:mutual\s+fund|funds?\s+management|mf)": "SBI Mutual Fund",
    r"hdfc\s+(?:mutual\s+fund|asset\s+management|mf)": "HDFC Mutual Fund",
    r"icici\s+prudential\s+(?:mutual\s+fund|asset\s+management|mf)": "ICICI Prudential Mutual Fund",
    r"nippon\s+india\s+(?:mutual\s+fund|mf)": "Nippon India Mutual Fund",
    r"uti\s+(?:mutual\s+fund|mf|asset\s+management)": "UTI Mutual Fund",
    r"kotak\s+(?:mahindra\s+)?(?:mutual\s+fund|mf|asset)": "Kotak Mahindra Mutual Fund",
    r"axis\s+(?:mutual\s+fund|mf|asset)": "Axis Mutual Fund",
    r"aditya\s+birla\s+(?:sun\s+life\s+)?(?:mutual\s+fund|mf)": "Aditya Birla Sun Life Mutual Fund",
    r"dsp\s+(?:mutual\s+fund|mf|investment)": "DSP Mutual Fund",
    r"mirae\s+asset\s+(?:mutual\s+fund|mf)": "Mirae Asset Mutual Fund",
}


def _extract_text_from_pdf(file_path: str, max_pages: int = 2) -> str:
    """Extract text from the first N pages of a PDF.
    
    Uses pdfplumber for accurate text extraction with layout preservation.
    Falls back to PyMuPDF if pdfplumber fails.
    """
    text = ""
    
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages[:max_pages]):
                page_text = page.extract_text() or ""
                text += f"\n--- Page {i+1} ---\n{page_text}"
    except Exception as e:
        logger.warning("pdfplumber_failed_trying_pymupdf", error=str(e))
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            for i in range(min(max_pages, len(doc))):
                text += f"\n--- Page {i+1} ---\n{doc[i].get_text()}"
            doc.close()
        except Exception as e2:
            logger.error("pdf_text_extraction_failed", error=str(e2))
    
    return text


def _extract_headers_from_excel(file_path: str) -> tuple[str, list[str]]:
    """Extract header text and sheet names from an Excel file.
    
    Reads the first 10 rows of each sheet to capture header/metadata
    information that typically contains AMC name, scheme, period.
    
    Returns:
        Tuple of (concatenated_header_text, list_of_sheet_names)
    """
    text = ""
    sheet_names = []
    
    try:
        import pandas as pd
        
        # Determine engine based on extension
        suffix = Path(file_path).suffix.lower()
        engine = "openpyxl" if suffix == ".xlsx" else "xlrd"
        
        try:
            xl = pd.ExcelFile(file_path, engine=engine)
        except Exception:
            fallback_engine = "xlrd" if engine == "openpyxl" else "openpyxl"
            xl = pd.ExcelFile(file_path, engine=fallback_engine)
            engine = fallback_engine
            
        sheet_names = xl.sheet_names
        
        # Read first 10 rows of each sheet (or first sheet if many sheets)
        sheets_to_read = sheet_names[:5]  # Limit to first 5 sheets
        
        for sheet_name in sheets_to_read:
            try:
                df = pd.read_excel(
                    file_path,
                    sheet_name=sheet_name,
                    nrows=10,
                    header=None,
                    dtype=str,
                    engine=engine,
                )
                # Concatenate all cell values
                for _, row in df.iterrows():
                    row_text = " ".join(str(v) for v in row.values if pd.notna(v))
                    text += f" {row_text}"
                text += f"\n[Sheet: {sheet_name}]\n"
            except Exception:
                continue
                
    except Exception as e:
        logger.error("excel_header_extraction_failed", error=str(e))
    
    return text, sheet_names


def extract_doc_header_signals(
    file_path: Optional[str],
    file_type: Optional[str] = None,
    source_amc: Optional[str] = None,
) -> SignalResult:
    """Extract classification signals from the document's internal content.
    
    This is the most reliable signal channel because it reads the actual
    document content. Weight: 0.40 (highest of all 4 channels).
    
    For PDFs: Extracts text from first 2 pages
    For Excel: Reads header rows and sheet names
    
    Args:
        file_path: Path to the downloaded document
        file_type: File type (pdf, xlsx, xls, csv)
        source_amc: Known AMC from source config
        
    Returns:
        SignalResult with extracted signals and confidence score
    """
    result = SignalResult(channel="doc_header")
    
    if not file_path or not Path(file_path).exists():
        result.confidence = 0.0
        result.reasoning = "File not available for header extraction"
        return result
    
    # Determine file type
    if not file_type:
        file_type = Path(file_path).suffix.lower().lstrip(".")
    
    raw_signals = {"file_type": file_type}
    signals_found = 0
    
    # Extract text based on file type
    header_text = ""
    sheet_names = []
    
    if file_type == "pdf":
        header_text = _extract_text_from_pdf(file_path)
    elif file_type in ("xlsx", "xls"):
        header_text, sheet_names = _extract_headers_from_excel(file_path)
        raw_signals["sheet_names"] = sheet_names
        raw_signals["sheet_count"] = len(sheet_names)
    else:
        result.confidence = 0.0
        result.reasoning = f"Unsupported file type: {file_type}"
        return result
    
    if not header_text.strip():
        result.confidence = 0.1
        result.reasoning = "No text could be extracted from document headers"
        return result
    
    header_lower = header_text.lower()
    raw_signals["header_text_length"] = len(header_text)
    raw_signals["header_preview"] = header_text[:500]
    
    # --- Extract AMC Name ---
    for pattern, amc_name in AMC_HEADER_PATTERNS.items():
        if re.search(pattern, header_lower):
            result.amc_name = amc_name
            raw_signals["amc_header_match"] = pattern
            signals_found += 1
            break
    
    if not result.amc_name and source_amc:
        # Check if source AMC name appears in text
        if source_amc.lower().split()[0] in header_lower:
            result.amc_name = source_amc
            raw_signals["amc_source_confirmed"] = True
            signals_found += 1
    
    # --- Extract Period (As On Date) ---
    for pattern in AS_ON_PATTERNS:
        match = re.search(pattern, header_lower)
        if match:
            groups = match.groups()
            
            if len(groups) == 3:
                # Pattern with day, month_name/month_num, year
                try:
                    # Year is always the last group (index 2)
                    year_val = int(groups[2])
                    if year_val < 100:
                        year_val = 2000 + year_val
                    result.period_year = year_val
                    
                    # Detect which group is the month.
                    g0 = groups[0].lower()
                    g1 = groups[1].lower()
                    if g0.isalpha() or any(m in g0 for m in MONTH_MAP):
                        month_str = g0
                    elif g1.isalpha() or any(m in g1 for m in MONTH_MAP):
                        month_str = g1
                    else:
                        month_str = g1  # Default to dd/mm/yyyy structure (second group is month)
                        
                    if month_str.isdigit():
                        m_num = int(month_str)
                        if 1 <= m_num <= 12:
                            result.period_month = m_num
                    else:
                        for m_name, m_num in MONTH_MAP.items():
                            if month_str.startswith(m_name):
                                result.period_month = m_num
                                break
                                
                    raw_signals["period_as_on"] = match.group(0)
                    signals_found += 2  # Both month and year
                except (ValueError, IndexError):
                    pass
            elif len(groups) == 2:
                # Pattern with month_name, year only
                try:
                    month_str = groups[0].lower()
                    for m_name, m_num in MONTH_MAP.items():
                        if month_str.startswith(m_name):
                            result.period_month = m_num
                            break
                    year_val = int(groups[1])
                    if year_val < 100:
                        year_val = 2000 + year_val
                    result.period_year = year_val
                    raw_signals["period_text"] = match.group(0)
                    signals_found += 2
                except (ValueError, IndexError):
                    pass
            break
    
    # --- Extract Scheme Name (fuzzy match) ---
    scheme_master = load_scheme_master()
    best_score = 0
    best_name = None
    best_category = None
    
    for amc_key, amc_data in scheme_master.get("amcs", {}).items():
        for scheme in amc_data.get("schemes", []):
            candidates = [scheme["name"]] + scheme.get("aliases", [])
            for candidate in candidates:
                # Use partial ratio for substring matching in headers
                score = fuzz.partial_ratio(candidate.lower(), header_lower)
                if score > best_score and score > 75:
                    best_score = score
                    best_name = scheme["name"]
                    best_category = scheme.get("category")
    
    if best_name:
        result.scheme_name = best_name
        result.scheme_category = best_category
        raw_signals["scheme_fuzzy_match"] = {
            "name": best_name,
            "score": best_score,
        }
        signals_found += 1
    
    # --- Also check sheet names for scheme info (Excel) ---
    if sheet_names and not result.scheme_name:
        for sheet in sheet_names:
            for amc_key, amc_data in scheme_master.get("amcs", {}).items():
                for scheme in amc_data.get("schemes", []):
                    candidates = [scheme["name"]] + scheme.get("aliases", [])
                    for candidate in candidates:
                        score = fuzz.partial_ratio(candidate.lower(), sheet.lower())
                        if score > 80:
                            result.scheme_name = scheme["name"]
                            result.scheme_category = scheme.get("category")
                            raw_signals["scheme_from_sheet"] = {
                                "sheet": sheet,
                                "name": scheme["name"],
                                "score": score,
                            }
                            signals_found += 1
                            break
    
    # --- Document Type from content ---
    doc_type_patterns = {
        r"portfolio\s+(?:disclosure|statement)": "portfolio_disclosure",
        r"scheme\s+portfolio": "portfolio_disclosure",
        r"monthly\s+portfolio": "portfolio_disclosure",
        r"fact\s*sheet": "factsheet",
        r"half[\s-]?yearly": "half_yearly_report",
    }
    for pattern, doc_type in doc_type_patterns.items():
        if re.search(pattern, header_lower):
            result.doc_type = doc_type
            raw_signals["doc_type_header"] = pattern
            signals_found += 1
            break
    
    # --- Calculate confidence ---
    # Document headers are the most reliable source
    max_signals = 5
    base_confidence = min(1.0, (signals_found / max_signals) * 1.2)
    
    # Strong boost if we found an "as on" date (very reliable)
    if raw_signals.get("period_as_on") or raw_signals.get("period_text"):
        base_confidence = min(1.0, base_confidence + 0.2)
    
    # Strong boost if AMC was found in document header
    if raw_signals.get("amc_header_match"):
        base_confidence = min(1.0, base_confidence + 0.1)
    
    result.confidence = base_confidence
    result.raw_signals = raw_signals
    result.reasoning = (
        f"Extracted {signals_found} signals from document {'PDF' if file_type == 'pdf' else 'Excel'} headers. "
        f"Text length: {len(header_text)}, Sheets: {len(sheet_names)}"
    )
    
    logger.debug(
        "doc_header_signals_extracted",
        file_type=file_type,
        signals_found=signals_found,
        confidence=result.confidence,
        has_period=bool(result.period_month and result.period_year),
    )
    
    return result
