"""PDF parser — extracts tabular portfolio data using pdfplumber.

Uses anchor-based extraction to find known column headers like "ISIN",
"Market Value", "% to Net Assets" and extracts rows relative to those anchors.
Per-AMC parser profiles handle layout variations.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Optional

from observability.logger import get_logger

logger = get_logger(__name__, component="extraction", parser="pdf")

# Standard column headers found in Indian MF portfolio disclosures
STANDARD_HEADERS = {
    "isin": ["isin", "isin code", "isin no"],
    "instrument_name": ["name of the instrument", "instrument", "security", "stock name", "name of instrument", "scrip name", "security name"],
    "instrument_type": ["type", "instrument type", "asset type", "security type"],
    "quantity": ["quantity", "qty", "no. of shares", "units", "face value", "nos."],
    "market_value": ["market value", "market/fair value", "value", "market value (rs. in lakhs)", "market value (in lakhs)", "total (rs.)"],
    "pct_to_net_assets": ["% to net assets", "% of net assets", "% to nav", "% of nav", "% to total", "percentage to net assets", "% of total"],
    "rating": ["rating", "credit rating", "rating / industry"],
    "industry": ["industry", "industry / rating", "sector"],
}


def _normalize_header(header: str) -> str:
    """Normalize a table header for matching."""
    return re.sub(r"[^a-z0-9\s%.]", "", header.lower()).strip()


def _match_header(header: str) -> Optional[str]:
    """Match a header string to a standard column name."""
    normalized = _normalize_header(header)
    for field_name, variants in STANDARD_HEADERS.items():
        for variant in variants:
            if normalized == variant or variant in normalized:
                return field_name
    return None


def _compute_header_hash(headers: list[str]) -> str:
    """Compute a hash of the column headers for drift detection."""
    normalized = "|".join(sorted(_normalize_header(h) for h in headers if h))
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def extract_from_pdf(
    file_path: str,
    amc_key: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Extract portfolio holding data from a PDF file.
    
    Uses pdfplumber for table extraction with anchor-based column mapping.
    
    Args:
        file_path: Path to the PDF file
        amc_key: AMC key for per-AMC parsing customization
        
    Returns:
        List of dictionaries with extraction results including:
        - 'rows': list of row dictionaries with standardized column names
        - 'headers': original column headers
        - 'header_hash': hash of normalized headers for drift detection
        - 'page_number': which page the table was found on
        - 'table_index': index of the table on that page
        - 'metadata': extraction metadata
    """
    results = []
    
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber_not_installed")
        raise ImportError("pdfplumber is required for PDF extraction. Install with: pip install pdfplumber")
    
    try:
        with pdfplumber.open(file_path) as pdf:
            logger.info(
                "pdf_opened",
                path=file_path,
                page_count=len(pdf.pages),
            )
            
            for page_num, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables()
                
                if not tables:
                    continue
                
                for table_idx, table in enumerate(tables):
                    if not table or len(table) < 2:
                        continue
                    
                    # Find the header row (first row with recognized column names)
                    header_row_idx = None
                    column_mapping = {}
                    
                    for row_idx, row in enumerate(table[:5]):  # Check first 5 rows
                        if not row:
                            continue
                        
                        mapped = {}
                        for col_idx, cell in enumerate(row):
                            if cell:
                                field = _match_header(str(cell))
                                if field:
                                    mapped[col_idx] = field
                        
                        # Accept if we found at least 2 recognized columns
                        if len(mapped) >= 2:
                            header_row_idx = row_idx
                            column_mapping = mapped
                            break
                    
                    if header_row_idx is None:
                        continue
                    
                    # Extract data rows
                    headers = table[header_row_idx]
                    header_hash = _compute_header_hash([str(h) for h in headers if h])
                    data_rows = table[header_row_idx + 1:]
                    
                    parsed_rows = []
                    for row in data_rows:
                        if not row or all(cell is None or str(cell).strip() == "" for cell in row):
                            continue
                        
                        row_dict = {}
                        for col_idx, field_name in column_mapping.items():
                            if col_idx < len(row):
                                value = row[col_idx]
                                if value is not None:
                                    value = str(value).strip()
                                    # Try to convert numeric fields
                                    if field_name in ("quantity", "market_value", "pct_to_net_assets"):
                                        try:
                                            # Handle Indian number formatting (commas)
                                            cleaned = re.sub(r"[,\s]", "", value)
                                            cleaned = cleaned.replace("(", "-").replace(")", "")
                                            if cleaned and cleaned not in ("-", "—", "N/A", "NA", ""):
                                                row_dict[field_name] = float(cleaned)
                                        except (ValueError, TypeError):
                                            row_dict[field_name] = value
                                    else:
                                        row_dict[field_name] = value
                        
                        # Only include rows with at least some data
                        if len(row_dict) >= 2:
                            parsed_rows.append(row_dict)
                    
                    if parsed_rows:

                        total_pct = sum(row.get("pct_to_net_assets", 0.0) for row in parsed_rows if isinstance(row.get("pct_to_net_assets"), float))
    
                        # Validation Threshold: Should be close to 100% (allowing 80% to 102% for cash/derivatives)
                        if total_pct > 0.0 and not (80.0 <= total_pct <= 102.0):
                            logger.warning(
                                "DATA_QUALITY_VIOLATION",
                                calculated_total_pct=total_pct,
                                path=file_path,
                                message="Portfolio percentage totals do not balance mathematically."
                            )
                        results.append({
                            "rows": parsed_rows,
                            "headers": [str(h) for h in headers if h],
                            "header_hash": header_hash,
                            "page_number": page_num,
                            "table_index": table_idx,
                            "column_mapping": {str(k): v for k, v in column_mapping.items()},
                            "row_count": len(parsed_rows),
                            "metadata": {
                                "parser": "pdfplumber",
                                "amc_key": amc_key,
                                "total_pages": len(pdf.pages),
                            },
                        })
            
            logger.info(
                "pdf_extraction_completed",
                path=file_path,
                tables_found=len(results),
                total_rows=sum(r["row_count"] for r in results),
            )
    
    except Exception as e:
        logger.error(
            "pdf_extraction_failed",
            path=file_path,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise
    
    return results
