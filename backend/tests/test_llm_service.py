from services.llm_service import LLMService


def test_extract_citations_deduplicates_same_filename():
    service = LLMService.__new__(LLMService)

    response = "According to policy [2 → Page 4], and also [3 → Page 5]."
    doc_mapping = {
        2: {"filename": "Handbook.pdf", "type": "company", "download_url": None, "pages": {4}},
        3: {"filename": "Handbook.pdf", "type": "company", "download_url": None, "pages": {5}},
    }

    updated_text, sources = service._extract_citations_and_renumber(response, doc_mapping)

    assert "[1 → Page 4]" in updated_text
    assert "[1 → Page 5]" in updated_text
    assert len(sources) == 1
    assert "Handbook.pdf" in sources[0]["filename"]


def test_clean_response_removes_markdown_bold():
    service = LLMService.__new__(LLMService)
    assert service._clean_response("**Hello** world") == "Hello world"
