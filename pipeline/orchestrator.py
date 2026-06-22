"""Pipeline Orchestrator.

Chains all pipeline stages together:
Discover -> Novelty -> Classify -> Extract -> Drift Check -> Load
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from classification.classifier import DocumentClassifier
from discovery.browser import DiscoveryEngine
from extraction.drift_detector import DriftDetector
from extraction.excel_parser import extract_from_excel
from extraction.pdf_parser import extract_from_pdf
from loading.warehouse import WarehouseLoader
from models.database import PipelineRunORM
from models.schemas import DocumentStatus
from novelty.ledger import NoveltyLedger, compute_idempotency_key, compute_content_hash, compute_data_hash
from observability.logger import get_logger

logger = get_logger(__name__, component="orchestrator")


class PipelineOrchestrator:
    """Orchestrates the end-to-end AMC data pipeline."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.novelty = NoveltyLedger(session)
        self.classifier = DocumentClassifier()
        self.drift = DriftDetector(session)
        self.warehouse = WarehouseLoader(session)

    async def run_pipeline(self, source_config: dict, run_id: UUID, force_refresh: bool = False) -> PipelineRunORM:
        """Run the full pipeline for a given source."""
        source_key = source_config["source_key"]
        source_id = source_config.get("id")
        
        logger.info("pipeline_run_started", source_key=source_key, run_id=str(run_id))
        
        # 1. Update Run Status
        run_record = await self.session.get(PipelineRunORM, run_id)
        if not run_record:
            run_record = PipelineRunORM(id=run_id, source_id=source_id, status="RUNNING")
            self.session.add(run_record)
        
        try:
            # 2. Discover Documents
            async with DiscoveryEngine() as browser:
                documents = await browser.discover(source_config, str(run_id))
            
            run_record.documents_discovered = len(documents)
            
            # Process each discovered document
            for doc in documents:
                # 3. Novelty Check (Level 0: URL)
                doc.source_id = source_id
                is_novel, existing = await self.novelty.check_url_novelty(doc.url, source_id)
                if not force_refresh and not is_novel and existing and existing.status in ("PUBLISHED", "VALIDATED", "QUARANTINED", "REJECTED"):
                    continue
                
                # Record initial discovery
                doc_record = await self.novelty.record_document(doc, source_id)
                run_record.documents_novel += 1
                
                # 4. Download file
                try:
                    doc_record.status = DocumentStatus.DOWNLOADING.value
                    await self.session.flush()
                    
                    async with DiscoveryEngine() as browser_dl:
                        local_path, size = await browser_dl.download_file(doc.url, source_config)
                    
                    doc_record.local_path = local_path
                    doc_record.file_size_bytes = size
                    
                    from novelty.ledger import compute_file_hash
                    doc_record.file_hash_sha256 = compute_file_hash(local_path)
                    
                    # Level 1 Novelty (File Hash) - Exclude current record to prevent autoflush self-match
                    is_novel_file, _ = await self.novelty.check_file_novelty(doc_record.file_hash_sha256, source_id, exclude_doc_id=doc_record.id)
                    if not force_refresh and not is_novel_file:
                        doc_record.status = DocumentStatus.PUBLISHED.value # Skip as it's duplicate
                        await self.session.commit()
                        continue
                    
                    doc_record.status = DocumentStatus.DOWNLOADED.value
                    await self.session.flush()
                except Exception as e:
                    logger.error("download_failed", error=str(e), url=doc.url)
                    doc_record.status = DocumentStatus.FAILED.value
                    doc_record.last_error = str(e)
                    await self.session.flush()
                    continue

                # 5. Classify Document
                doc_record.status = DocumentStatus.CLASSIFYING.value
                await self.session.flush()
                
                classified = self.classifier.classify(
                    document_id=doc_record.id,
                    url=doc_record.url,
                    filename=doc_record.filename,
                    file_path=doc_record.local_path,
                    file_type=doc_record.file_type,
                    page_context=doc_record.page_context,
                    source_amc=source_config.get("amc_name")
                )
                
                # Save classification to DB
                from models.database import ClassifiedDocumentORM
                classified_orm = ClassifiedDocumentORM(
                    document_id=doc_record.id,
                    amc_name=classified.amc_name,
                    scheme_name=classified.scheme_name,
                    scheme_category=classified.scheme_category,
                    period_month=classified.period_month,
                    period_year=classified.period_year,
                    period_label=classified.period_label,
                    doc_type=classified.doc_type,
                    confidence_score=classified.confidence_score,
                    classification_signals=classified.confidence_breakdown.model_dump(),
                    is_quarantined=classified.is_quarantined,
                    quarantine_reason=classified.quarantine_reason.value if classified.quarantine_reason else None,
                    quarantine_details=classified.quarantine_details
                )
                self.session.add(classified_orm)
                
                doc_record.status = DocumentStatus.CLASSIFIED.value
                if classified.is_quarantined:
                    doc_record.status = DocumentStatus.QUARANTINED.value
                    run_record.documents_quarantined += 1
                else:
                    run_record.documents_classified += 1
                    
                await self.session.flush()
                
                # If quarantined, we stop processing this document until manual review
                if classified.is_quarantined:
                    await self.session.commit()
                    continue
                
                # 6. Extract Data
                doc_record.status = DocumentStatus.EXTRACTING.value
                await self.session.flush()
                
                extraction_results = []
                try:
                    import asyncio
                    if doc_record.file_type == "pdf":
                        extraction_results = await asyncio.to_thread(extract_from_pdf, doc_record.local_path, source_key)
                    elif doc_record.file_type == "xlsx" or doc_record.file_type == "xls":
                        extraction_results = await asyncio.to_thread(extract_from_excel, doc_record.local_path, source_key)
                    else:
                        raise ValueError(f"Unsupported file type: {doc_record.file_type}")
                    
                    doc_record.status = DocumentStatus.EXTRACTED.value
                    run_record.documents_extracted += 1
                    await self.session.flush()
                except Exception as e:
                    logger.error("extraction_failed", error=str(e), file_path=doc_record.local_path)
                    doc_record.status = DocumentStatus.FAILED.value
                    doc_record.last_error = f"Extraction error: {str(e)}"
                    await self.session.commit()
                    continue
                
                # 7. Drift Detection & Loading
                for result in extraction_results:
                    raw_data = result.get("rows", [])
                    if not raw_data:
                        continue
                        
                    headers = result.get("headers", [])
                    header_hash = result.get("header_hash", "")
                    
                    # Drift Check
                    await self.drift.check_table_header_drift(
                        source_id=source_id,
                        document_id=doc_record.id,
                        current_header_hash=header_hash,
                        current_headers=headers
                    )
                    
                    # Load to Staging
                    content_hash = compute_data_hash(raw_data)
                    idemp_key = compute_idempotency_key(
                        source_key,
                        classified.period_year or 0,
                        classified.period_month or 0,
                        classified.scheme_name or "unknown",
                        content_hash
                    )
                    
                    staging = await self.warehouse.load_staging(
                        document_id=doc_record.id,
                        classification_id=classified_orm.id,
                        raw_data=raw_data,
                        column_names=headers,
                        header_hash=header_hash,
                        content_hash=content_hash,
                        idempotency_key=idemp_key
                    )
                    doc_record.status = DocumentStatus.STAGED.value
                    await self.session.flush()
                    
                    # Validate
                    validated = await self.warehouse.validate_and_clean(staging)
                    doc_record.status = DocumentStatus.VALIDATED.value
                    await self.session.flush()
                    
                    # Publish
                    published = await self.warehouse.publish(
                        validated=validated,
                        amc_name=classified.amc_name or "Unknown AMC",
                        scheme_name=classified.scheme_name or "Unknown Scheme",
                        period_year=classified.period_year or 0,
                        period_month=classified.period_month or 0,
                        scheme_category=classified.scheme_category
                    )
                    
                    if published:
                        doc_record.status = DocumentStatus.PUBLISHED.value
                        run_record.documents_published += 1
                        await self.session.flush()
                
                await self.session.commit()

            # End Run
            run_record.status = "COMPLETED"
            import datetime
            run_record.completed_at = datetime.datetime.utcnow()
            await self.session.commit()
            
            logger.info("pipeline_run_completed", run_id=str(run_id))
            return run_record

        except Exception as e:
            logger.error("pipeline_run_failed", error=str(e), run_id=str(run_id))
            run_record.status = "FAILED"
            run_record.errors = [{"message": str(e)}]
            import datetime
            run_record.completed_at = datetime.datetime.utcnow()
            await self.session.commit()
            raise
