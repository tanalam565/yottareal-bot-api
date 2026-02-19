# backend/scripts/generate_embeddings_from_blob_storage.py - WITH PAGE NUMBER TRACKING
"""
Script to generate embeddings for existing documents in blob storage.

This script processes PDF files from Azure Blob Storage, extracts text with page numbers
using Document Intelligence, chunks the text with overlap, generates embeddings, and
uploads the chunks to Azure Cognitive Search with proper page number tracking.
"""

import asyncio
from azure.storage.blob import BlobServiceClient
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
import sys
import os
import base64
import hashlib
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from services.embedding_service import EmbeddingService


# CHUNKING CONFIGURATION
CHUNK_SIZE = 1000  # characters per chunk
CHUNK_OVERLAP = 200  # overlap between chunks


def chunk_text_with_pages(page_texts: list, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list:
    """
    Split text into overlapping chunks while tracking page numbers.

    Concatenates text from all pages and splits it into chunks of specified size with overlap.
    Each chunk is assigned the page number from its middle character position.

    Args:
        page_texts (list): List of dicts with {"page_number": int, "text": str}.
        chunk_size (int, optional): Maximum characters per chunk. Defaults to CHUNK_SIZE.
        overlap (int, optional): Overlap between chunks in characters. Defaults to CHUNK_OVERLAP.

    Returns:
        list: List of dicts with {"text": str, "page_number": int, "chunk_number": int}.
    """
    chunks = []
    chunk_number = 0
    
    # Concatenate all page texts with page markers
    full_text = ""
    char_to_page = []  # Maps character index to page number
    
    for page_info in page_texts:
        page_num = page_info["page_number"]
        page_text = page_info["text"]
        
        # Track which characters belong to which page
        for _ in range(len(page_text)):
            char_to_page.append(page_num)
        
        full_text += page_text + " "  # Add space between pages
        char_to_page.append(page_num)  # For the space
    
    # Now chunk the full text and determine page for each chunk
    start = 0
    
    while start < len(full_text):
        end = start + chunk_size
        
        # If not the last chunk, try to break at sentence/word boundary
        if end < len(full_text):
            # Look for sentence end (. ! ?)
            for i in range(end, max(start + chunk_size - 200, start), -1):
                if i < len(full_text) and full_text[i] in '.!?\n':
                    end = i + 1
                    break
            else:
                # No sentence boundary, look for space
                for i in range(end, max(start + chunk_size - 100, start), -1):
                    if i < len(full_text) and full_text[i] == ' ':
                        end = i
                        break
        
        chunk_text = full_text[start:end].strip()
        
        if chunk_text:
            # Determine which page this chunk is primarily from
            # Use the middle of the chunk as the reference point
            chunk_middle = start + ((end - start) // 2)
            chunk_middle = min(chunk_middle, len(char_to_page) - 1)
            primary_page = char_to_page[chunk_middle]
            
            chunks.append({
                "text": chunk_text,
                "page_number": primary_page,
                "chunk_number": chunk_number
            })
            chunk_number += 1
        
        start = end - overlap if end < len(full_text) else end
    
    return chunks


def generate_chunk_id(parent_id: str, chunk_number: int) -> str:
    """
    Generate a unique chunk ID from parent ID and chunk number.

    Creates a base64-encoded unique identifier for each chunk.

    Args:
        parent_id (str): The parent document identifier.
        chunk_number (int): The chunk number within the document.

    Returns:
        str: A unique base64-encoded chunk ID.
    """
    combined = f"{parent_id}_chunk_{chunk_number}"
    return base64.b64encode(combined.encode()).decode()


async def extract_text_from_blob(blob_client, filename: str, doc_intelligence_client) -> dict:
    """
    Download a blob and extract text with page numbers using Document Intelligence.

    Downloads the blob content, processes it with Azure Document Intelligence
    to extract text page by page, and returns structured page data.

    Args:
        blob_client: Azure Blob client for the specific blob.
        filename (str): Name of the file being processed.
        doc_intelligence_client: Azure Document Intelligence client.

    Returns:
        dict: Dictionary containing 'page_texts', 'page_count', 'success', and optionally 'error'.
    """
    logger = logging.getLogger(__name__)
    try:
        logger.info("Downloading %s", filename)
        blob_data = blob_client.download_blob().readall()
        
        logger.info("Extracting text with page tracking (size: %d bytes)", len(blob_data))
        
        # Encode to base64
        base64_source = base64.b64encode(blob_data).decode('utf-8')
        
        # Create analyze request
        analyze_request = AnalyzeDocumentRequest(
            base64_source=base64_source
        )
        
        # Call Document Intelligence
        poller = doc_intelligence_client.begin_analyze_document(
            model_id="prebuilt-read",
            analyze_request=analyze_request
        )
        
        result = poller.result()
        
        # Extract text page by page
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
        
        page_count = len(page_texts)
        total_chars = sum(len(p["text"]) for p in page_texts)
        
        logger.info("Extracted %d characters from %d pages", total_chars, page_count)
        
        return {
            "page_texts": page_texts,
            "page_count": page_count,
            "success": True
        }
        
    except Exception as e:
        logger.exception("Extraction error for %s: %s", filename, e)
        return {
            "page_texts": [],
            "page_count": 0,
            "success": False,
            "error": str(e)
        }


async def generate_embeddings_from_blob_storage():
    """
    Generate embeddings by reading full documents from blob storage with page number tracking.

    Main function that orchestrates the entire process:
    - Clears existing search index
    - Lists PDF files in blob storage
    - Extracts text with page numbers from each PDF
    - Chunks the text with overlap and page tracking
    - Generates embeddings for each chunk
    - Uploads chunks to Azure Cognitive Search

    This creates searchable chunks with accurate page number references.
    """
    logger = logging.getLogger(__name__)
    
    logger.info("Starting Full Document Embedding Generation from Blob Storage with page number tracking")
    logger.info("Configuration: Chunk size=%d, Overlap=%d, Container=%s", CHUNK_SIZE, CHUNK_OVERLAP, config.AZURE_STORAGE_CONTAINER_NAME)

    # Initialize services
    embedding_service = EmbeddingService()
    
    search_client = SearchClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        index_name=config.AZURE_SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(config.AZURE_SEARCH_KEY)
    )
    
    blob_service = BlobServiceClient.from_connection_string(
        config.AZURE_STORAGE_CONNECTION_STRING
    )
    container_client = blob_service.get_container_client(
        config.AZURE_STORAGE_CONTAINER_NAME
    )
    
    doc_intelligence_client = DocumentIntelligenceClient(
        endpoint=config.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT,
        credential=AzureKeyCredential(config.AZURE_DOCUMENT_INTELLIGENCE_KEY),
        api_version="2024-11-30"
    )

    try:
        # Clear existing index
        logger.info("Clearing existing index")
        
        existing_results = search_client.search(
            search_text="*",
            select=["chunk_id"],
            top=10000
        )
        
        existing_ids = [dict(r)["chunk_id"] for r in existing_results]
        
        if existing_ids:
            logger.info("Found %d existing entries to delete", len(existing_ids))
            batch_size = 1000
            for i in range(0, len(existing_ids), batch_size):
                batch = existing_ids[i:i+batch_size]
                docs_to_delete = [{"chunk_id": doc_id} for doc_id in batch]
                search_client.delete_documents(documents=docs_to_delete)
                logger.info("Deleted %d/%d entries", min(i+batch_size, len(existing_ids)), len(existing_ids))
            logger.info("Index cleared")
        else:
            logger.info("Index is empty")

        # List all blobs in container
        logger.info("Listing files in blob storage")
        
        blobs = list(container_client.list_blobs())
        pdf_blobs = [b for b in blobs if b.name.lower().endswith('.pdf')]
        
        logger.info("Found %d PDF files", len(pdf_blobs))

        # Process each blob
        total_chunks_created = 0
        documents_processed = 0
        chunks_to_upload = []

        logger.info("Processing PDFs and creating chunks with page numbers...")

        for blob_info in pdf_blobs:
            blob_name = blob_info.name
            documents_processed += 1
            
            logger.info("Processing document %d/%d: %s", documents_processed, len(pdf_blobs), blob_name)
            
            # Get blob client
            blob_client = container_client.get_blob_client(blob_name)
            
            # Extract text page by page from blob
            extraction_result = await extract_text_from_blob(
                blob_client, 
                blob_name,
                doc_intelligence_client
            )
            
            if not extraction_result['success'] or not extraction_result['page_texts']:
                logger.warning("Skipping %s: No text extracted", blob_name)
                continue
            
            page_texts = extraction_result['page_texts']
            page_count = extraction_result['page_count']
            
            # Generate parent_id from blob name
            parent_id = f"blob://{config.AZURE_STORAGE_CONTAINER_NAME}/{blob_name}"
            
            # Split into chunks while tracking page numbers
            chunks = chunk_text_with_pages(page_texts)
            total_chunks_created += len(chunks)

            total_chars = sum(len(p["text"]) for p in page_texts)
            logger.info("Document stats: %d chars, %d pages, created %d chunks", total_chars, page_count, len(chunks))

            # Process each chunk
            for chunk_info in chunks:
                chunk_content = chunk_info["text"]
                chunk_num = chunk_info["chunk_number"]
                page_num = chunk_info["page_number"]
                
                # Generate embedding for this chunk
                embedding = embedding_service.generate_embedding(chunk_content)

                # Create chunk document
                chunk_id = generate_chunk_id(parent_id, chunk_num)
                
                chunk_doc = {
                    "chunk_id": chunk_id,
                    "parent_id": parent_id,
                    "chunk_number": chunk_num,
                    "page_number": page_num,  # ← ACTUAL PAGE NUMBER FROM PDF
                    "title": blob_name,
                    "content": chunk_content,
                    "merged_content": chunk_content,
                    "filepath": blob_name,
                    "url": f"https://{blob_service.account_name}.blob.core.windows.net/{config.AZURE_STORAGE_CONTAINER_NAME}/{blob_name}",
                    "metadata_storage_name": blob_name,
                    "metadata_storage_path": parent_id,
                    "metadata_storage_content_type": "application/pdf",
                    "content_vector": embedding
                }
                
                chunks_to_upload.append(chunk_doc)

                # Upload in batches of 50
                if len(chunks_to_upload) >= 50:
                    logger.info("Uploading batch of %d chunks", len(chunks_to_upload))
                    try:
                        search_client.upload_documents(documents=chunks_to_upload)
                        logger.info("Batch uploaded successfully")
                    except Exception as batch_error:
                        logger.error("Batch upload error: %s", batch_error)
                        # Try one by one
                        for single_doc in chunks_to_upload:
                            try:
                                search_client.upload_documents(documents=[single_doc])
                            except Exception as doc_error:
                                logger.error("Failed to upload chunk: %s", doc_error)
                    
                    chunks_to_upload = []

        # Upload remaining chunks
        if chunks_to_upload:
            logger.info("Uploading final batch of %d chunks", len(chunks_to_upload))
            try:
                search_client.upload_documents(documents=chunks_to_upload)
                logger.info("Final batch uploaded successfully")
            except Exception as batch_error:
                logger.error("Final batch upload error: %s", batch_error)

        # Summary
        logger.info("Embedding generation complete: %d documents processed, %d chunks created", documents_processed, total_chunks_created)
        logger.info("Configuration: Model=%s, Dimensions=%d, Chunk size=%d", config.AZURE_OPENAI_EMBEDDING_MODEL, config.EMBEDDING_DIMENSIONS, CHUNK_SIZE)

    except Exception as e:
        logger.exception("Error in embedding generation: %s", e)


if __name__ == "__main__":
    asyncio.run(generate_embeddings_from_blob_storage())