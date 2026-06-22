"""Signal extraction package.

Exposes the specific signal extractors for document attributes.
"""
from classification.signals.doc_header import extract_doc_header_signals
from classification.signals.filename import extract_filename_signals
from classification.signals.page_context import extract_page_context_signals
from classification.signals.url import extract_url_signals

__all__ = [
    "extract_doc_header_signals",
    "extract_filename_signals",
    "extract_page_context_signals",
    "extract_url_signals",
]
