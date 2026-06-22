import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from models.schemas import DiscoveredDocumentModel, DocumentStatus
from novelty.ledger import NoveltyLedger
from models.database import DiscoveredDocumentORM

@pytest.mark.asyncio
async def test_url_novelty(mock_db_session):
    # Set up mock response for novelty check
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = mock_execute_result

    ledger = NoveltyLedger(mock_db_session)
    source_id = uuid4()
    url = "https://sbimf.com/doc.pdf"
    
    is_novel, existing = await ledger.check_url_novelty(url, source_id)
    assert is_novel is True
    assert existing is None
