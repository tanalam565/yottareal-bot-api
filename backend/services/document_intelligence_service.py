"""
Azure Document Intelligence extraction service.

Supports text extraction for PDFs/images/DOCX via Azure Document Intelligence and
direct UTF-8 parsing for plain text uploads.
"""

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.core.credentials import AzureKeyCredential
import base64
import asyncio
import logging
import config


class DocumentIntelligenceService:
    """Extract page-aware text content from uploaded documents."""

    def __init__(self):
        """Initialize Azure Document Intelligence client from configured endpoint/key."""
        self.endpoint = config.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
        self.key = config.AZURE_DOCUMENT_INTELLIGENCE_KEY
        self.client = DocumentIntelligenceClient(
            endpoint=self.endpoint,
            credential=AzureKeyCredential(self.key),
            api_version="2024-11-30"
        )
        self.logger = logging.getLogger(__name__)

    def _extract_sync(self, file_content: bytes, filename: str) -> dict:
        """
        Perform synchronous extraction via Azure Document Intelligence.

        Called through ``asyncio.to_thread`` by async code to avoid blocking
        the event loop during network I/O and polling.

        Returns:
            dict: Extraction result containing success flag, page text entries,
            and basic metadata.
        """
        try:
            base64_source = base64.b64encode(file_content).decode('utf-8')
            analyze_request = AnalyzeDocumentRequest(base64_source=base64_source)

            poller = self.client.begin_analyze_document(
                model_id="prebuilt-read",
                analyze_request=analyze_request
            )
            result = poller.result()

            # Extract text PAGE BY PAGE — limit to MAX_UPLOAD_PAGES
            page_texts = []

            if hasattr(result, 'pages'):
                for page in result.pages:
                    if page.page_number > config.MAX_UPLOAD_PAGES:
                        self.logger.warning("Stopping at page %s (MAX_UPLOAD_PAGES limit)", config.MAX_UPLOAD_PAGES)
                        break
                    page_num = page.page_number
                    page_content = ""
                    if hasattr(page, 'lines'):
                        page_content = " ".join([line.content for line in page.lines])
                    page_texts.append({
                        "page_number": page_num,
                        "text": page_content
                    })

            full_text = result.content if hasattr(result, 'content') else ""
            page_count = len(page_texts)

            return {
                "text": full_text.strip(),
                "page_texts": page_texts,
                "page_count": page_count,
                "filename": filename,
                "success": True
            }

        except Exception as e:
            self.logger.error("Error extracting text from %s: %s", filename, e)
            return {
                "text": "",
                "page_texts": [],
                "page_count": 0,
                "filename": filename,
                "success": False,
                "error": str(e)
            }

    async def extract_text(self, file_content: bytes, filename: str) -> dict:
        """
        Extract text content from uploaded file bytes.

        Handles `.txt` directly and routes binary office/image/PDF formats to
        Azure Document Intelligence.

        Returns:
            dict: Normalized extraction payload with `text`, `page_texts`,
            `page_count`, `success`, and optional `error`.
        """
        
        # Handle plain text files directly without Document Intelligence
        if filename.lower().endswith('.txt'):
            try:
                text = file_content.decode('utf-8')
                
                # Split into pages (every 2000 chars = 1 "page" for consistency)
                page_texts = []
                page_size = 2000
                page_num = 1
                
                for i in range(0, len(text), page_size):
                    page_content = text[i:i + page_size]
                    if page_num > config.MAX_UPLOAD_PAGES:
                        self.logger.warning("Stopping at page %s (MAX_UPLOAD_PAGES limit)", config.MAX_UPLOAD_PAGES)
                        break
                    page_texts.append({
                        "page_number": page_num,
                        "text": page_content
                    })
                    page_num += 1
                
                self.logger.info("Extracted %s characters from %s pages (plain text)", len(text), len(page_texts))
                
                return {
                    "text": text.strip(),
                    "page_texts": page_texts,
                    "page_count": len(page_texts),
                    "filename": filename,
                    "success": True
                }
            except UnicodeDecodeError as e:
                self.logger.error("Error decoding text file %s: %s", filename, e)
                return {
                    "text": "",
                    "page_texts": [],
                    "page_count": 0,
                    "filename": filename,
                    "success": False,
                    "error": "File is not valid UTF-8 text"
                }
        
        # Use Document Intelligence for PDFs, images, DOCX
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._extract_sync, file_content, filename),
                timeout=config.REQUEST_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            self.logger.error(
                "Document Intelligence timed out for %s after %ss",
                filename,
                config.REQUEST_TIMEOUT_SECONDS,
            )
            return {
                "text": "",
                "page_texts": [],
                "page_count": 0,
                "filename": filename,
                "success": False,
                "error": f"Request timed out after {config.REQUEST_TIMEOUT_SECONDS}s"
            }