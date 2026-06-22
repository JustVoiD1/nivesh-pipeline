import pytest
from uuid import uuid4
from classification.classifier import DocumentClassifier
from models.schemas import DocumentStatus

def test_document_classification():
    classifier = DocumentClassifier()
    doc_id = uuid4()
    
    # Classify a sample SBI factsheet URL
    classified = classifier.classify(
        document_id=doc_id,
        url="https://sbimf.com/downloads/SBI_Bluechip_Fund_May_2026.pdf",
        filename="SBI_Bluechip_Fund_May_2026.pdf",
        file_type="pdf",
        source_amc="SBI Mutual Fund"
    )
    
    # Expect confidence scoring to extract details
    assert classified.document_id == doc_id
    assert classified.amc_name == "SBI Mutual Fund"
    assert "SBI Blue Chip Fund" in classified.scheme_name or classified.scheme_name is not None
    assert classified.period_month == 5
    assert classified.period_year == 2026
