"""Multi-layer novelty checking — the "seen" ledger.

Implements a 4-level deduplication strategy:
  Level 0: URL fingerprint — "Have we seen this exact URL before?"
  Level 1: File hash (SHA-256) — "Is this the exact same file bytes?"
  Level 2: Content hash — "Is the extracted text identical?"
  Level 3: Data hash — "Is the structured data identical?"

Ensures idempotency: re-running the pipeline on the same source
will never produce duplicate records.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from discovery.browser import url_fingerprint
from models.database import DiscoveredDocumentORM
from models.schemas import DiscoveredDocumentModel
from observability.logger import get_logger

logger = get_logger(__name__, component="novelty")


def compute_file_hash(file_path: str) -> str:
    """Compute SHA-256 hash of a file's bytes.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Hex-encoded SHA-256 hash
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def compute_content_hash(text_content: str) -> str:
    """Compute hash of normalized text content.
    
    Normalizes whitespace and case to detect content equivalence
    even when formatting differs.
    
    Args:
        text_content: Extracted text from document
        
    Returns:
        Hex-encoded SHA-256 hash
    """
    # Normalize: lowercase, strip extra whitespace, remove common noise
    normalized = " ".join(text_content.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_data_hash(structured_data: list[dict]) -> str:
    """Compute hash of structured/extracted data.
    
    Serializes data deterministically (sorted keys) to produce
    a consistent hash regardless of extraction order.
    
    Args:
        structured_data: List of row dictionaries from extraction
        
    Returns:
        Hex-encoded SHA-256 hash
    """
    # Sort by keys for deterministic serialization
    serialized = json.dumps(structured_data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_idempotency_key(
    source_key: str,
    period_year: int,
    period_month: int,
    scheme_name: str,
    content_hash: str,
) -> str:
    """Generate an idempotency key for staging/publishing.
    
    This key ensures that the same data for the same source, period,
    and scheme is never duplicated, even across multiple pipeline runs.
    
    Args:
        source_key: Source identifier (e.g., 'sbi_mf')
        period_year: Year of the reporting period
        period_month: Month of the reporting period
        scheme_name: Scheme name
        content_hash: Hash of the actual data content
        
    Returns:
        SHA-256 idempotency key
    """
    components = f"{source_key}|{period_year}|{period_month}|{scheme_name}|{content_hash}"
    return hashlib.sha256(components.encode("utf-8")).hexdigest()


class NoveltyLedger:
    """Manages the 'seen' ledger for document deduplication.
    
    Checks multiple layers of novelty to determine whether a discovered
    document needs to be processed or has already been handled.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def check_url_novelty(
        self,
        url: str,
        source_id: UUID,
    ) -> tuple[bool, Optional[DiscoveredDocumentORM]]:
        """Level 0: Check if this URL has been seen before.
        
        Args:
            url: Document URL
            source_id: Source configuration ID
            
        Returns:
            Tuple of (is_novel, existing_record_or_none)
        """
        fp = url_fingerprint(url)
        
        result = await self.session.execute(
            select(DiscoveredDocumentORM).where(
                DiscoveredDocumentORM.url_fingerprint == fp,
                DiscoveredDocumentORM.source_id == source_id,
            )
        )
        existing = result.scalar_one_or_none()
        
        is_novel = existing is None
        logger.debug(
            "url_novelty_check",
            url=url[:100],
            fingerprint=fp[:12],
            is_novel=is_novel,
        )
        
        return is_novel, existing

    async def check_file_novelty(
        self,
        file_hash: str,
        source_id: UUID,
        exclude_doc_id: Optional[UUID] = None,
    ) -> tuple[bool, Optional[DiscoveredDocumentORM]]:
        """Level 1: Check if this exact file (by SHA-256) has been seen before.
        
        Args:
            file_hash: SHA-256 hash of the file bytes
            source_id: Source configuration ID
            exclude_doc_id: Optional document ID to exclude from query (the current record)
            
        Returns:
            Tuple of (is_novel, existing_record_or_none)
        """
        query = select(DiscoveredDocumentORM).where(
            DiscoveredDocumentORM.file_hash_sha256 == file_hash,
            DiscoveredDocumentORM.source_id == source_id,
        )
        if exclude_doc_id:
            query = query.where(DiscoveredDocumentORM.id != exclude_doc_id)
            
        result = await self.session.execute(query)
        existing = result.scalars().first()
        
        is_novel = existing is None
        logger.debug(
            "file_novelty_check",
            file_hash=file_hash[:12],
            is_novel=is_novel,
        )
        
        return is_novel, existing

    async def check_content_novelty(
        self,
        content_hash: str,
        source_id: UUID,
        exclude_doc_id: Optional[UUID] = None,
    ) -> tuple[bool, Optional[DiscoveredDocumentORM]]:
        """Level 2: Check if this content (extracted text) has been seen before.
        
        Args:
            content_hash: Hash of normalized text content
            source_id: Source configuration ID
            exclude_doc_id: Optional document ID to exclude from query (the current record)
            
        Returns:
            Tuple of (is_novel, existing_record_or_none)
        """
        query = select(DiscoveredDocumentORM).where(
            DiscoveredDocumentORM.content_hash == content_hash,
            DiscoveredDocumentORM.source_id == source_id,
        )
        if exclude_doc_id:
            query = query.where(DiscoveredDocumentORM.id != exclude_doc_id)
            
        result = await self.session.execute(query)
        existing = result.scalars().first()
        
        is_novel = existing is None
        logger.debug(
            "content_novelty_check",
            content_hash=content_hash[:12],
            is_novel=is_novel,
        )
        
        return is_novel, existing

    async def check_full_novelty(
        self,
        document: DiscoveredDocumentModel,
        source_id: UUID,
        force_refresh: bool = False,
    ) -> tuple[bool, str]:
        """Run the full multi-layer novelty check.
        
        Checks URL → File Hash → Content Hash in sequence,
        short-circuiting as soon as a match is found.
        
        Args:
            document: Discovered document to check
            source_id: Source configuration ID
            force_refresh: If True, skip novelty checks (for backfill)
            
        Returns:
            Tuple of (is_novel, reason_string)
        """
        if force_refresh:
            logger.info("novelty_bypassed_force_refresh", url=document.url[:100])
            return True, "force_refresh"

        # Level 0: URL fingerprint
        url_novel, existing = await self.check_url_novelty(document.url, source_id)
        if not url_novel:
            # URL seen before — but was it successfully processed?
            if existing and existing.status in ("PUBLISHED", "VALIDATED"):
                logger.info(
                    "document_already_processed",
                    url=document.url[:100],
                    status=existing.status,
                )
                return False, f"url_seen:status={existing.status}"
            elif existing and existing.status in ("FAILED", "QUARANTINED"):
                # Re-try failed/quarantined documents
                logger.info(
                    "document_retry",
                    url=document.url[:100],
                    previous_status=existing.status,
                )
                return True, f"retry:previous_status={existing.status}"

        # Level 1: File hash (only if file is already downloaded)
        if document.file_hash_sha256:
            file_novel, _ = await self.check_file_novelty(
                document.file_hash_sha256, source_id
            )
            if not file_novel:
                logger.info(
                    "duplicate_file_content",
                    file_hash=document.file_hash_sha256[:12],
                )
                return False, "file_hash_duplicate"

        # Level 2: Content hash (only if content has been extracted)
        if document.content_hash:
            content_novel, _ = await self.check_content_novelty(
                document.content_hash, source_id
            )
            if not content_novel:
                logger.info(
                    "duplicate_text_content",
                    content_hash=document.content_hash[:12],
                )
                return False, "content_hash_duplicate"

        return True, "novel"

    async def record_document(
        self,
        document: DiscoveredDocumentModel,
        source_id: UUID,
    ) -> DiscoveredDocumentORM:
        """Record a discovered document in the ledger.
        
        Uses upsert semantics: if the URL fingerprint already exists for
        this source, update the record instead of creating a duplicate.
        
        Args:
            document: Document to record
            source_id: Source configuration ID
            
        Returns:
            The created or updated ORM record
        """
        fp = url_fingerprint(document.url)
        
        # Check for existing record
        result = await self.session.execute(
            select(DiscoveredDocumentORM).where(
                DiscoveredDocumentORM.url_fingerprint == fp,
                DiscoveredDocumentORM.source_id == source_id,
            )
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            # Update existing record
            existing.status = document.status.value
            existing.page_context = document.page_context
            existing.download_attempts = existing.download_attempts + 1
            if document.file_hash_sha256:
                existing.file_hash_sha256 = document.file_hash_sha256
            if document.content_hash:
                existing.content_hash = document.content_hash
            if document.local_path:
                existing.local_path = document.local_path
            if document.file_size_bytes:
                existing.file_size_bytes = document.file_size_bytes
            
            await self.session.flush()
            logger.info("document_record_updated", url=document.url[:100], id=str(existing.id))
            return existing
        
        # Create new record
        record = DiscoveredDocumentORM(
            source_id=source_id,
            url=document.url,
            filename=document.filename,
            file_type=document.file_type,
            file_size_bytes=document.file_size_bytes,
            file_hash_sha256=document.file_hash_sha256,
            content_hash=document.content_hash,
            url_fingerprint=fp,
            local_path=document.local_path,
            is_novel=document.is_novel,
            status=document.status.value,
            page_context=document.page_context,
            pipeline_run_id=document.pipeline_run_id,
        )
        self.session.add(record)
        await self.session.flush()
        
        logger.info("document_recorded", url=document.url[:100], id=str(record.id))
        return record
