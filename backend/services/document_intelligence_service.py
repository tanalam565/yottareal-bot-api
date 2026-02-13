# backend/services/document_intelligence_service.py

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.core.credentials import AzureKeyCredential
import base64
import config
import logging

class DocumentIntelligenceService:
    """
    Service class for extracting text from documents using Azure Document Intelligence.

    This class provides methods to analyze documents and extract text content,
    including per-page text extraction using Azure's prebuilt-read model.
    """
    def __init__(self):
        """
        Initialize the Document Intelligence Service.

        Creates a DocumentIntelligenceClient using the Azure endpoint and key
        from configuration, with the 2024-11-30 API version.
        """
        self.logger = logging.getLogger(__name__)
        self.endpoint = config.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
        self.key = config.AZURE_DOCUMENT_INTELLIGENCE_KEY
        # Use 2024 API version
        self.client = DocumentIntelligenceClient(
            endpoint=self.endpoint,
            credential=AzureKeyCredential(self.key),
            api_version="2024-11-30"
        )
    
    async def extract_text(self, file_content: bytes, filename: str) -> dict:
        """
        Extract text from a document using Azure Document Intelligence.

        Analyzes the provided file content and extracts text, including per-page
        breakdown with page numbers. Uses the prebuilt-read model for OCR and text extraction.

        Args:
            file_content (bytes): The binary content of the document file.
            filename (str): The name of the file being processed.

        Returns:
            dict: A dictionary containing:
                - 'text': Full extracted text (str)
                - 'page_texts': List of dicts with 'page_number' and 'text' for each page
                - 'page_count': Number of pages (int)
                - 'filename': Original filename (str)
                - 'success': True if extraction succeeded, False otherwise (bool)
                - 'error': Error message if success is False (str, optional)
        """
        try:
            # Encode to base64
            base64_source = base64.b64encode(file_content).decode('utf-8')
            
            # Create analyze request
            analyze_request = AnalyzeDocumentRequest(
                base64_source=base64_source
            )
            
            # Call with 2024 API
            poller = self.client.begin_analyze_document(
                model_id="prebuilt-read",
                analyze_request=analyze_request
            )
            
            result = poller.result()
            
            # Extract text PAGE BY PAGE
            page_texts = []
            
            if hasattr(result, 'pages'):
                for page in result.pages:
                    page_num = page.page_number
                    
                    # Combine all lines on this page
                    page_content = ""
                    if hasattr(page, 'lines'):
                        page_content = " ".join([line.content for line in page.lines])
                    
                    page_texts.append({
                        "page_number": page_num,
                        "text": page_content
                    })
            
            # Also keep full text for backward compatibility
            full_text = result.content if hasattr(result, 'content') else ""
            page_count = len(page_texts)
            
            return {
                "text": full_text.strip(),  # Full text (for backward compat)
                "page_texts": page_texts,    # Per-page breakdown with page numbers
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