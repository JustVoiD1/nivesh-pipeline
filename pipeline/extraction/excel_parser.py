"""Excel parser — extracts portfolio holding data using pandas.

Handles AMC-specific quirks: disclaimer rows, merged cells, multi-sheet
workbooks, and Indian number formatting.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from observability.logger import get_logger

logger = get_logger(__name__, component="extraction", parser="excel")

# Standard column headers for matching
HEADER_VARIANTS = {
    "isin": ["isin", "isin code", "isin no", "isin number"],
    "instrument_name": ["name of the instrument", "instrument", "security", "stock name", "name of instrument", "scrip name", "security name", "name"],
    "instrument_type": ["type", "instrument type", "asset type", "security type"],
    "quantity": ["quantity", "qty", "no. of shares", "units", "nos.", "no of shares"],
    "market_value": ["market value", "market/fair value", "value", "market value (rs. in lakhs)", "market value in lakhs", "total"],
    "pct_to_net_assets": ["% to net assets", "% of net assets", "% to nav", "% of nav", "% to total", "percentage to net assets"],
    "rating": ["rating", "credit rating"],
    "industry": ["industry", "sector"],
}


def _normalize_col(col: str) -> str:
    """Normalize a column name for matching."""
    return re.sub(r"[^a-z0-9\s%.]", "", str(col).lower()).strip()


def _match_column(col_name: str) -> Optional[str]:
    """Map a column name to a standardized field name."""
    normalized = _normalize_col(col_name)
    if "unnamed" in normalized:
        return None
    for field, variants in HEADER_VARIANTS.items():
        for variant in variants:
            if normalized == variant or (variant in normalized and (variant != "name" or normalized == "name")):
                return field
    return None


def _compute_header_hash(columns: list[str]) -> str:
    """Compute a hash of column headers for drift detection."""
    normalized = "|".join(sorted(_normalize_col(c) for c in columns))
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _find_header_row(df: pd.DataFrame, max_scan: int = 15) -> Optional[int]:
    """Find the row that contains column headers.
    
    Scans the first N rows looking for recognized column names.
    AMC Excel files often have header/disclaimer rows before the actual data.
    """
    for idx in range(min(max_scan, len(df))):
        row = df.iloc[idx]
        matches = 0
        for cell in row:
            if pd.notna(cell) and _match_column(str(cell)):
                matches += 1
        if matches >= 2:
            return idx
    return None


def extract_from_excel(
    file_path: str,
    amc_key: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Extract portfolio holding data from an Excel file.
    
    Handles:
    - Multi-sheet workbooks (each sheet may be a different scheme)
    - Smart header detection (scans first N rows)
    - Disclaimer/metadata rows at top and bottom
    - Indian number formatting (commas in numbers)
    - Merged cells and empty rows
    
    Args:
        file_path: Path to the Excel file
        amc_key: AMC key for per-AMC customization
        
    Returns:
        List of extraction results per sheet, each containing:
        - 'rows': standardized row dictionaries
        - 'headers': original column names
        - 'header_hash': for drift detection
        - 'sheet_name': source sheet
        - 'metadata': extraction context
    """
    results = []
    path = Path(file_path)
    
    # Determine engine based on extension
    engine = "openpyxl" if path.suffix.lower() == ".xlsx" else "xlrd"
    
    try:
        try:
            xl = pd.ExcelFile(file_path, engine=engine)
        except Exception as e:
            fallback_engine = "xlrd" if engine == "openpyxl" else "openpyxl"
            logger.info(
                "excel_engine_failed_trying_fallback",
                engine=engine,
                fallback=fallback_engine,
                error=str(e),
            )
            xl = pd.ExcelFile(file_path, engine=fallback_engine)
            engine = fallback_engine
            
        sheet_names = xl.sheet_names
        
        logger.info(
            "excel_opened",
            path=file_path,
            sheets=len(sheet_names),
            sheet_names=sheet_names[:10],
        )
        
        for sheet_name in sheet_names:
            try:
                # Read the entire sheet as strings first to find headers
                df_raw = pd.read_excel(
                    file_path,
                    sheet_name=sheet_name,
                    header=None,
                    dtype=str,
                    engine=engine,
                )
                
                if df_raw.empty or len(df_raw) < 2:
                    continue
                
                # Find the header row
                header_row = _find_header_row(df_raw)
                if header_row is None:
                    logger.debug("no_header_found", sheet=sheet_name)
                    continue
                
                # Re-read with correct header
                df = pd.read_excel(
                    file_path,
                    sheet_name=sheet_name,
                    header=header_row,
                    dtype=str,
                    engine=engine,
                    na_values=["-", "—", "N/A", "NA", "--", ""],
                )
                
                if df.empty:
                    continue
                
                # Map columns to standard names
                original_columns = list(df.columns)
                column_mapping = {}
                for col in original_columns:
                    mapped = _match_column(str(col))
                    if mapped:
                        column_mapping[col] = mapped
                
                if len(column_mapping) < 2:
                    logger.debug(
                        "insufficient_column_matches",
                        sheet=sheet_name,
                        matched=len(column_mapping),
                    )
                    continue
                
                # Rename and filter columns
                df_mapped = df.rename(columns=column_mapping)
                standard_cols = list(column_mapping.values())
                df_mapped = df_mapped[[c for c in df_mapped.columns if c in standard_cols]]
                
                # Clean data
                parsed_rows = []
                for _, row in df_mapped.iterrows():
                    row_dict = {}
                    has_data = False
                    
                    for col in df_mapped.columns:
                        value = row[col]
                        
                        if isinstance(value, pd.Series):
                            value = value.dropna().iloc[0] if not value.dropna().empty else None
                            
                        if pd.isna(value):
                            continue
                        
                        value = str(value).strip()
                        if not value:
                            continue
                        
                        has_data = True
                        
                        # Convert numeric fields
                        if col in ("quantity", "market_value", "pct_to_net_assets"):
                            try:
                                cleaned = re.sub(r"[,\s]", "", value)
                                cleaned = cleaned.replace("(", "-").replace(")", "")
                                if cleaned and cleaned not in ("-", "—"):
                                    row_dict[col] = float(cleaned)
                            except (ValueError, TypeError):
                                row_dict[col] = value
                        elif col == "isin":
                            # Ensure ISIN stays as string
                            row_dict[col] = value.upper().strip()
                        else:
                            row_dict[col] = value
                    
                    if has_data and len(row_dict) >= 2:
                        parsed_rows.append(row_dict)
                
                if parsed_rows:
                    header_hash = _compute_header_hash(
                        [str(c) for c in original_columns]
                    )
                    
                    results.append({
                        "rows": parsed_rows,
                        "headers": [str(c) for c in original_columns],
                        "header_hash": header_hash,
                        "sheet_name": sheet_name,
                        "row_count": len(parsed_rows),
                        "column_mapping": {str(k): v for k, v in column_mapping.items()},
                        "metadata": {
                            "parser": "pandas",
                            "engine": engine,
                            "amc_key": amc_key,
                            "header_row_index": header_row,
                            "total_sheets": len(sheet_names),
                            "original_columns": [str(c) for c in original_columns],
                        },
                    })
                    
            except Exception as e:
                logger.warning(
                    "sheet_extraction_failed",
                    sheet=sheet_name,
                    error=str(e),
                )
                continue
        
        logger.info(
            "excel_extraction_completed",
            path=file_path,
            sheets_with_data=len(results),
            total_rows=sum(r["row_count"] for r in results),
        )
        
    except Exception as e:
        logger.error(
            "excel_extraction_failed",
            path=file_path,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise
    
    return results
