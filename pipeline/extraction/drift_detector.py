"""Drift detection system — detects when page layouts or document structures change.

Implements the "fail loudly" philosophy: when drift is detected, the system
alerts and quarantines rather than silently loading garbage data.

Detection Types:
  1. Page Structure Drift — DOM fingerprint changed
  2. Table Header Drift — column names/order changed
  3. Column Count Drift — expected vs actual column count
  4. Schema Validation Drift — Pydantic validation failure rate spike
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import DriftDetectionORM, SourceConfigORM, StagingDataORM, DiscoveredDocumentORM
from models.schemas import DriftDetectionModel, DriftSeverity
from observability.logger import get_logger

logger = get_logger(__name__, component="drift_detection")


class DriftDetector:
    """Detects structural drift in AMC source pages and documents.
    
    Compares current extraction signatures against historical baselines
    to identify when layouts, schemas, or structures have changed.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def check_page_structure_drift(
        self,
        source_id: UUID,
        current_hash: str,
    ) -> Optional[DriftDetectionModel]:
        """Check if the page DOM structure has changed since last crawl.
        
        Args:
            source_id: Source configuration ID
            current_hash: Current page structure hash from discovery
            
        Returns:
            DriftDetectionModel if drift detected, None otherwise
        """
        result = await self.session.execute(
            select(SourceConfigORM).where(SourceConfigORM.id == source_id)
        )
        source = result.scalar_one_or_none()
        
        if not source:
            return None
        
        previous_hash = source.page_structure_hash
        
        if not previous_hash:
            # First run — establish baseline
            source.page_structure_hash = current_hash
            await self.session.flush()
            logger.info(
                "page_structure_baseline_set",
                source_id=str(source_id),
                hash=current_hash[:12],
            )
            return None
        
        if previous_hash == current_hash:
            return None
        
        # Drift detected!
        drift = DriftDetectionModel(
            source_id=source_id,
            detection_type="page_structure",
            severity=DriftSeverity.WARNING,
            previous_signature={"hash": previous_hash},
            current_signature={"hash": current_hash},
            similarity_score=0.0,  # Binary: changed or not
            description=(
                f"Page DOM structure has changed. "
                f"Previous hash: {previous_hash[:12]}, "
                f"Current hash: {current_hash[:12]}. "
                f"The website layout may have been redesigned."
            ),
        )
        
        # Persist the drift detection
        await self._record_drift(drift)
        
        # Update baseline
        source.page_structure_hash = current_hash
        await self.session.flush()
        
        logger.warning(
            "page_structure_drift_detected",
            source_id=str(source_id),
            previous_hash=previous_hash[:12],
            current_hash=current_hash[:12],
        )
        
        return drift

    async def check_table_header_drift(
        self,
        source_id: UUID,
        document_id: UUID,
        current_header_hash: str,
        current_headers: list[str],
    ) -> Optional[DriftDetectionModel]:
        """Check if table column headers have changed from the baseline.
        
        This is the most reliable drift indicator for document extraction.
        A header change almost always means the parser needs updating.
        
        Args:
            source_id: Source configuration ID
            document_id: Document being processed
            current_header_hash: Hash of current table headers
            current_headers: Current column header names
            
        Returns:
            DriftDetectionModel if drift detected, None otherwise
        """
        # Get the most recent staging record for this source
        result = await self.session.execute(
            select(StagingDataORM.header_hash, StagingDataORM.column_names)
            .join(
                SourceConfigORM,
                StagingDataORM.document_id.in_(
                    select(DiscoveredDocumentORM.id).where(
                        DiscoveredDocumentORM.source_id == source_id
                    )
                )
            )
            .where(StagingDataORM.header_hash.isnot(None))
            .order_by(StagingDataORM.created_at.desc())
            .limit(1)
        )
        
        # Simpler query fallback
        result = await self.session.execute(
            select(StagingDataORM.header_hash, StagingDataORM.column_names)
            .where(StagingDataORM.header_hash.isnot(None))
            .order_by(StagingDataORM.created_at.desc())
            .limit(5)
        )
        previous_records = result.all()
        
        if not previous_records:
            # First extraction — no baseline yet
            logger.info(
                "header_baseline_establishing",
                source_id=str(source_id),
                header_hash=current_header_hash[:12],
            )
            return None
        
        # Check against recent baselines
        for prev_hash, prev_columns in previous_records:
            if prev_hash == current_header_hash:
                # Match found — no drift
                return None
        
        # Header has changed — this is CRITICAL
        prev_hash, prev_columns = previous_records[0]
        
        drift = DriftDetectionModel(
            source_id=source_id,
            document_id=document_id,
            detection_type="table_header",
            severity=DriftSeverity.CRITICAL,
            previous_signature={
                "hash": prev_hash,
                "columns": prev_columns,
            },
            current_signature={
                "hash": current_header_hash,
                "columns": current_headers,
            },
            description=(
                f"Table column headers have changed! "
                f"Previous columns: {prev_columns}, "
                f"Current columns: {current_headers}. "
                f"Parser may need recalibration."
            ),
        )
        
        await self._record_drift(drift)
        
        logger.error(
            "table_header_drift_detected",
            source_id=str(source_id),
            document_id=str(document_id),
            severity="CRITICAL",
            previous_hash=prev_hash[:12] if prev_hash else "none",
            current_hash=current_header_hash[:12],
            previous_columns=prev_columns,
            current_columns=current_headers,
        )
        
        return drift

    async def check_column_count_drift(
        self,
        source_id: UUID,
        document_id: UUID,
        current_col_count: int,
        expected_col_count: Optional[int] = None,
    ) -> Optional[DriftDetectionModel]:
        """Check if the number of columns has changed.
        
        A simpler but faster check than full header comparison.
        """
        if expected_col_count is None:
            # Get historical average
            result = await self.session.execute(
                select(func.avg(func.array_length(StagingDataORM.column_names, 1)))
                .where(StagingDataORM.column_names.isnot(None))
                .limit(20)
            )
            avg_count = result.scalar()
            if avg_count is None:
                return None
            expected_col_count = round(avg_count)
        
        if current_col_count == expected_col_count:
            return None
        
        # Determine severity based on difference
        diff = abs(current_col_count - expected_col_count)
        severity = DriftSeverity.WARNING if diff <= 2 else DriftSeverity.CRITICAL
        
        drift = DriftDetectionModel(
            source_id=source_id,
            document_id=document_id,
            detection_type="column_count",
            severity=severity,
            previous_signature={"expected_columns": expected_col_count},
            current_signature={"actual_columns": current_col_count},
            similarity_score=1.0 - (diff / max(expected_col_count, 1)),
            description=(
                f"Column count changed from {expected_col_count} to {current_col_count} "
                f"(difference: {diff})"
            ),
        )
        
        await self._record_drift(drift)
        
        logger.warning(
            "column_count_drift_detected",
            source_id=str(source_id),
            expected=expected_col_count,
            actual=current_col_count,
            severity=severity.value,
        )
        
        return drift

    async def check_validation_drift(
        self,
        source_id: UUID,
        total_rows: int,
        failed_rows: int,
        failure_threshold: float = 0.10,
    ) -> Optional[DriftDetectionModel]:
        """Check if the validation failure rate exceeds the threshold.
        
        A spike in validation failures indicates the document structure
        has changed in a way that the parser can't handle correctly.
        
        Args:
            source_id: Source configuration ID
            total_rows: Total extracted rows
            failed_rows: Number of rows that failed validation
            failure_threshold: Maximum acceptable failure rate (default: 10%)
        """
        if total_rows == 0:
            return None
        
        failure_rate = failed_rows / total_rows
        
        if failure_rate <= failure_threshold:
            return None
        
        severity = (
            DriftSeverity.CRITICAL if failure_rate > 0.5
            else DriftSeverity.WARNING
        )
        
        drift = DriftDetectionModel(
            source_id=source_id,
            detection_type="schema_validation",
            severity=severity,
            previous_signature={"expected_failure_rate": failure_threshold},
            current_signature={
                "actual_failure_rate": round(failure_rate, 4),
                "total_rows": total_rows,
                "failed_rows": failed_rows,
            },
            similarity_score=1.0 - failure_rate,
            description=(
                f"Validation failure rate {failure_rate:.1%} exceeds threshold "
                f"{failure_threshold:.1%}. {failed_rows}/{total_rows} rows failed. "
                f"Document structure may have changed."
            ),
        )
        
        await self._record_drift(drift)
        
        logger.error(
            "validation_drift_detected",
            source_id=str(source_id),
            failure_rate=round(failure_rate, 4),
            total_rows=total_rows,
            failed_rows=failed_rows,
            severity=severity.value,
        )
        
        return drift

    async def _record_drift(self, drift: DriftDetectionModel) -> None:
        """Persist a drift detection event to the database."""
        record = DriftDetectionORM(
            id=drift.id,
            source_id=drift.source_id,
            document_id=drift.document_id,
            detection_type=drift.detection_type,
            severity=drift.severity.value,
            previous_signature=drift.previous_signature,
            current_signature=drift.current_signature,
            similarity_score=drift.similarity_score,
            description=drift.description,
            alert_sent=False,
            resolved=False,
        )
        self.session.add(record)
        await self.session.flush()

    async def get_unresolved_drifts(
        self,
        source_id: Optional[UUID] = None,
    ) -> list[DriftDetectionORM]:
        """Get all unresolved drift detections."""
        query = select(DriftDetectionORM).where(
            DriftDetectionORM.resolved == False
        )
        if source_id:
            query = query.where(DriftDetectionORM.source_id == source_id)
        
        query = query.order_by(DriftDetectionORM.detected_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())
