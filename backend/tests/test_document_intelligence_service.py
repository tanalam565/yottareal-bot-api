import logging

import config
from services.document_intelligence_service import DocumentIntelligenceService


async def test_extract_text_plain_text_success_with_paging(monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_PAGES", 5)

    service = DocumentIntelligenceService.__new__(DocumentIntelligenceService)
    service.logger = logging.getLogger("test-doc-intelligence")

    content = ("A" * 2000 + "B" * 100).encode("utf-8")
    result = await service.extract_text(content, "notes.txt")

    assert result["success"] is True
    assert result["page_count"] == 2
    assert len(result["page_texts"]) == 2


async def test_extract_text_plain_text_invalid_utf8_returns_error():
    service = DocumentIntelligenceService.__new__(DocumentIntelligenceService)
    service.logger = logging.getLogger("test-doc-intelligence")

    result = await service.extract_text(b"\xff\xfe\xfa", "notes.txt")

    assert result["success"] is False
    assert "UTF-8" in result["error"]
