"""Classification package.

Exposes the DocumentClassifier and confidence scoring utility functions.
"""
from classification.classifier import DocumentClassifier
from classification.confidence import compute_confidence

__all__ = ["DocumentClassifier", "compute_confidence"]
