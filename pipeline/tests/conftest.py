"""
Shared pytest fixtures for the Nivesh AI AMC pipeline test suite.

Provides realistic sample objects, temporary file artifacts, and
pre-configured component instances used across all test modules.
"""

from __future__ import annotations

import io
import struct
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from models.schemas import DiscoveredDocumentModel, SignalResult, ClassifiedDocumentModel


# ---------------------------------------------------------------------------
# Document / domain fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_discovered_document() -> DiscoveredDocumentModel:
    """A realistic *DiscoveredDocument* representing an SBI factsheet PDF."""
    return DiscoveredDocumentModel(
        url="https://www.sbimf.com/docs/portfolio/SBI_Blue_Chip_Fund_Jun2026.pdf",
        filename="SBI_Blue_Chip_Fund_Jun2026.pdf",
        page_context={
            "amc_dropdown": "SBI Mutual Fund",
            "scheme_dropdown": "SBI Blue Chip Fund",
            "period_dropdown": "June 2026",
            "page_title": "Portfolio Disclosure - SBI Mutual Fund",
        },
        file_type="pdf",
        discovered_at="2026-06-20T12:00:00Z",
    )


@pytest.fixture
def sample_hdfc_document() -> DiscoveredDocumentModel:
    """A realistic *DiscoveredDocument* for an HDFC equity Excel file."""
    return DiscoveredDocumentModel(
        url="https://www.hdfcfund.com/downloads/HDFC_Equity_May2026.xlsx",
        filename="HDFC_Equity_May2026.xlsx",
        page_context={
            "amc_dropdown": "HDFC Mutual Fund",
            "scheme_dropdown": "HDFC Equity Fund",
            "period_dropdown": "May 2026",
            "page_title": "Monthly Portfolio - HDFC Mutual Fund",
        },
        file_type="xlsx",
        discovered_at="2026-06-18T09:30:00Z",
    )


# ---------------------------------------------------------------------------
# Temporary file fixtures (minimal valid artifacts)
# ---------------------------------------------------------------------------

def _minimal_pdf_bytes() -> bytes:
    """Return the smallest standards-conformant PDF (no external deps)."""
    # A hand-crafted single-page blank PDF – avoids needing reportlab.
    return (
        b"%PDF-1.0\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n190\n%%EOF"
    )


@pytest.fixture
def sample_pdf_path(tmp_path: Path) -> Path:
    """Write a minimal PDF to *tmp_path* and return its path."""
    pdf = tmp_path / "SBI_Blue_Chip_Fund_Jun2026.pdf"
    pdf.write_bytes(_minimal_pdf_bytes())
    return pdf


@pytest.fixture
def sample_excel_path(tmp_path: Path) -> Path:
    """Create a minimal .xlsx workbook with a single data row.

    Uses *openpyxl* if available; otherwise falls back to writing a tiny
    XLSX-shaped ZIP (the tests that consume this fixture only need a real
    file on disk, not necessarily a fully valid workbook).
    """
    xlsx = tmp_path / "HDFC_Equity_May2026.xlsx"
    try:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Holdings"
        ws.append(["ISIN", "Security", "Quantity", "Market Value", "% to NAV"])
        ws.append(["INE009A01021", "Infosys Ltd", 150000, 2340000000, 8.5])
        ws.append(["INE002A01018", "Reliance Industries", 120000, 3120000000, 11.3])
        wb.save(xlsx)
    except ImportError:
        # Fallback: write recognisable placeholder bytes so the fixture
        # still provides a file for hash / fingerprint tests.
        xlsx.write_bytes(b"PK\x03\x04" + b"\x00" * 100)
    return xlsx


# ---------------------------------------------------------------------------
# Domain reference data
# ---------------------------------------------------------------------------

@pytest.fixture
def scheme_master() -> list[dict[str, Any]]:
    """A small slice of the scheme-master reference table."""
    return [
        {
            "scheme_code": "SBI-BC",
            "scheme_name": "SBI Blue Chip Fund",
            "amc": "SBI Mutual Fund",
            "category": "Large Cap",
            "aliases": ["SBI Bluechip", "SBI Large Cap"],
        },
        {
            "scheme_code": "HDFC-EQ",
            "scheme_name": "HDFC Equity Fund",
            "amc": "HDFC Mutual Fund",
            "category": "Multi Cap",
            "aliases": ["HDFC Equity"],
        },
        {
            "scheme_code": "ICICI-VAL",
            "scheme_name": "ICICI Prudential Value Discovery Fund",
            "amc": "ICICI Prudential Mutual Fund",
            "category": "Value",
            "aliases": ["ICICI Value Discovery"],
        },
        {
            "scheme_code": "AXIS-BF",
            "scheme_name": "Axis Bluechip Fund",
            "amc": "Axis Mutual Fund",
            "category": "Large Cap",
            "aliases": ["Axis Bluechip", "Axis Large Cap"],
        },
        {
            "scheme_code": "MFS-EG",
            "scheme_name": "SBI Magnum Equity ESG Fund",
            "amc": "SBI Mutual Fund",
            "category": "Thematic-ESG",
            "aliases": ["MFS", "Magnum ESG"],
        },
    ]


# ---------------------------------------------------------------------------
# Database mocks
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db_session() -> AsyncMock:
    """A mock *AsyncSession* suitable for SQLAlchemy async unit tests.

    Provides stubs for the most common session methods so callers can
    assert on interactions without hitting a real database.
    """
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.merge = AsyncMock()

    # Allow ``async with session.begin():`` context-manager usage.
    begin_cm = AsyncMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin_cm)

    return session
