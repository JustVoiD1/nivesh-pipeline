import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
from models.database import StagingDataORM, ValidatedDataORM, PublishedDataORM
from loading.warehouse import WarehouseLoader

@pytest.mark.asyncio
async def test_warehouse_loading_stages(mock_db_session):
    # Instantiate the loader with a mock session
    loader = WarehouseLoader(mock_db_session)
    
    document_id = uuid4()
    classification_id = uuid4()
    
    raw_data = [
        {"isin": "INE009A01021", "instrument_name": "Infosys Ltd", "quantity": "1000", "market_value": "1500000", "pct_to_net_assets": "5.5"},
        {"isin": "INE040A01034", "instrument_name": "HDFC Bank Ltd", "quantity": "2000", "market_value": "3000000", "pct_to_net_assets": "10.0"}
    ]
    
    # 1. Test staging layer load
    # Mocking executing select statement returning no existing staged data
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = mock_execute_result
    
    staging = await loader.load_staging(
        document_id=document_id,
        classification_id=classification_id,
        raw_data=raw_data,
        column_names=["isin", "instrument_name", "quantity", "market_value", "pct_to_net_assets"],
        header_hash="header123",
        content_hash="content456",
        idempotency_key="idemp789"
    )
    
    assert staging.document_id == document_id
    assert staging.idempotency_key == "idemp789"
    assert staging.row_count == 2
    mock_db_session.add.assert_called_once_with(staging)
    
    # Reset mock session calls
    mock_db_session.add.reset_mock()
    
    # 2. Test validation and cleaning layer
    validated = await loader.validate_and_clean(staging)
    assert validated.document_id == document_id
    assert validated.validation_status == "PASSED"
    assert validated.business_rules_passed is True
    assert len(validated.clean_data) == 2
    mock_db_session.add.assert_called_once_with(validated)
    
    # Reset mock session calls
    mock_db_session.add.reset_mock()
    
    # 3. Test publishing layer
    # Staging select executed in loop when publishing to check existing, mock to return None
    mock_db_session.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    
    published = await loader.publish(
        validated=validated,
        amc_name="SBI Mutual Fund",
        scheme_name="SBI Blue Chip Fund",
        period_year=2026,
        period_month=5
    )
    
    assert len(published) == 2
    assert published[0].amc_name == "SBI Mutual Fund"
    assert published[0].scheme_name == "SBI Blue Chip Fund"
    assert published[0].quantity == 1000.0
    assert published[0].market_value == 1500000.0
    assert published[0].pct_to_net_assets == 5.5
    assert published[1].pct_to_net_assets == 10.0
