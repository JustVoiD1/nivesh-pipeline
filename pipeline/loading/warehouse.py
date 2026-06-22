"""Data warehouse loading layer.

Manages the transition of extracted data through the warehouse stages:
Staging (raw) -> Validated (cleaned) -> Published (ready for consumption).
Implements idempotency to ensure re-runs don't duplicate data.
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import PublishedDataORM, StagingDataORM, ValidatedDataORM
from models.schemas import ValidatedDataModel, PublishedHoldingModel
from observability.logger import get_logger

logger = get_logger(__name__, component="loading")


class WarehouseLoader:
    """Loads extracted document data into the warehouse."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def load_staging(
        self,
        document_id: UUID,
        classification_id: Optional[UUID],
        raw_data: list[dict[str, Any]],
        column_names: list[str],
        header_hash: str,
        content_hash: str,
        idempotency_key: str,
    ) -> StagingDataORM:
        """Load raw extracted data into the staging layer."""
        
        # Check if already staged for this idempotency key
        result = await self.session.execute(
            select(StagingDataORM).where(StagingDataORM.idempotency_key == idempotency_key)
        )
        existing = result.scalar_one_or_none()
        if existing:
            logger.info("staging_data_exists", idempotency_key=idempotency_key)
            return existing

        staging = StagingDataORM(
            document_id=document_id,
            classification_id=classification_id,
            idempotency_key=idempotency_key,
            raw_data=raw_data,
            row_count=len(raw_data),
            column_names=column_names,
            header_hash=header_hash,
            content_hash=content_hash,
        )
        self.session.add(staging)
        await self.session.flush()
        
        logger.info(
            "data_staged", 
            staging_id=str(staging.id), 
            rows=len(raw_data)
        )
        return staging

    async def validate_and_clean(
        self,
        staging: StagingDataORM,
        drift_score: float = 0.0,
        drift_details: dict[str, Any] = None,
    ) -> ValidatedDataORM:
        """Apply business rules to staging data and move to validated layer."""
        
        clean_data = []
        errors = []
        warnings = []
        
        # Simple validation: ensure we have basic required fields in each row
        # (Assuming the extraction logic mapped these to standard keys like 'isin', 'instrument_name', etc.)
        for idx, row in enumerate(staging.raw_data):
            clean_row = {k: v for k, v in row.items() if v is not None}
            
            if "instrument_name" not in clean_row and "isin" not in clean_row:
                warnings.append({"row": idx, "message": "Missing both ISIN and Instrument Name"})
            
            clean_data.append(clean_row)

        validation_status = "PASSED" if not errors else "FAILED"
        business_rules_passed = validation_status == "PASSED"

        validated = ValidatedDataORM(
            staging_id=staging.id,
            document_id=staging.document_id,
            clean_data=clean_data,
            validation_status=validation_status,
            validation_errors=errors,
            validation_warnings=warnings,
            drift_score=drift_score,
            drift_details=drift_details or {},
            business_rules_passed=business_rules_passed,
        )
        self.session.add(validated)
        await self.session.flush()

        logger.info(
            "data_validated",
            validated_id=str(validated.id),
            status=validation_status,
            errors=len(errors),
            warnings=len(warnings),
        )
        return validated

    def _generate_holding_idempotency_key(
        self,
        amc_name: str,
        scheme_name: str,
        period_year: int,
        period_month: int,
        holding_row: dict[str, Any],
        row_index: int,
    ) -> str:
        """Generate a unique key for a single published holding row."""
        # Use ISIN if available, else instrument name, else fallback to row index
        instrument_id = holding_row.get("isin") or holding_row.get("instrument_name") or f"row_{row_index}"
        components = f"{amc_name}|{scheme_name}|{period_year}|{period_month}|{instrument_id}"
        return hashlib.sha256(components.encode("utf-8")).hexdigest()

    async def publish(
        self,
        validated: ValidatedDataORM,
        amc_name: str,
        scheme_name: str,
        period_year: int,
        period_month: int,
        scheme_category: Optional[str] = None,
    ) -> list[PublishedDataORM]:
        """Publish validated data to the final consumption tables."""
        
        if not validated.business_rules_passed:
            logger.warning("skipping_publish_validation_failed", validated_id=str(validated.id))
            return []

        published_records = []
        for idx, row in enumerate(validated.clean_data):
            # Parse numeric fields safely
            def _parse_float(val: Any) -> Optional[float]:
                try:
                    if val is None:
                        return None
                    return float(str(val).replace(",", "").strip())
                except (ValueError, TypeError):
                    return None

            holding_key = self._generate_holding_idempotency_key(
                amc_name, scheme_name, period_year, period_month, row, idx
            )
            
            # Check if this holding already exists
            result = await self.session.execute(
                select(PublishedDataORM).where(PublishedDataORM.idempotency_key == holding_key)
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                # Upsert / Versioning logic could go here
                # For now, we update in-place or just skip if it's identical
                existing.quantity = _parse_float(row.get("quantity"))
                existing.market_value = _parse_float(row.get("market_value"))
                existing.pct_to_net_assets = _parse_float(row.get("pct_to_net_assets"))
                existing.rating = row.get("rating")
                existing.version += 1
                published_records.append(existing)
            else:
                record = PublishedDataORM(
                    validated_id=validated.id,
                    document_id=validated.document_id,
                    idempotency_key=holding_key,
                    amc_name=amc_name,
                    scheme_name=scheme_name,
                    scheme_category=scheme_category,
                    period_month=period_month,
                    period_year=period_year,
                    isin=row.get("isin"),
                    instrument_name=row.get("instrument_name"),
                    instrument_type=row.get("instrument_type"),
                    quantity=_parse_float(row.get("quantity")),
                    market_value=_parse_float(row.get("market_value")),
                    pct_to_net_assets=_parse_float(row.get("pct_to_net_assets")),
                    rating=row.get("rating"),
                    industry=row.get("industry"),
                )
                self.session.add(record)
                published_records.append(record)

        await self.session.flush()
        
        logger.info(
            "data_published",
            validated_id=str(validated.id),
            published_count=len(published_records)
        )
        return published_records
