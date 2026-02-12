# backend/scripts/generate_embeddings_from_blob_storage.py - WITH PAGE NUMBER TRACKING

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

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from services.embedding_service import EmbeddingService


# CHUNKING CONFIGURATION
CHUNK_SIZE = 1000  # characters per chunk
CHUNK_OVERLAP = 200  # overlap between chunks


def chunk_text_with_pages(page_texts: list, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list:
    """
    Split text into overlapping chunks while tracking page numbers
    
    Args:
        page_texts: List of dicts with {"page_number": int, "text": str}
        chunk_size: Maximum characters per chunk
        overlap: Overlap between chunks
    
    Returns:
        List of dicts with {"text": str, "page_number": int, "chunk_number": int}
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
    """Generate unique chunk ID"""
    combined = f"{parent_id}_chunk_{chunk_number}"
    return base64.b64encode(combined.encode()).decode()


async def extract_text_from_blob(blob_client, filename: str, doc_intelligence_client) -> dict:
    """Download blob and extract text with page numbers using Document Intelligence"""
    try:
        print(f"   📥 Downloading {filename}...")
        blob_data = blob_client.download_blob().readall()
        
        print(f"   📄 Extracting text with page tracking (size: {len(blob_data)} bytes)...")
        
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
        
        print(f"   ✅ Extracted {total_chars} characters from {page_count} pages")
        
        return {
            "page_texts": page_texts,
            "page_count": page_count,
            "success": True
        }
        
    except Exception as e:
        print(f"   ❌ Extraction error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "page_texts": [],
            "page_count": 0,
            "success": False,
            "error": str(e)
        }


async def generate_embeddings_from_blob_storage():
    """
    Generate embeddings by reading full documents from blob storage
    with actual page number tracking
    """

    print("=" * 70)
    print("🚀 Starting Full Document Embedding Generation from Blob Storage")
    print("   WITH PAGE NUMBER TRACKING")
    print("=" * 70)
    print(f"📏 Chunk size: {CHUNK_SIZE} characters")
    print(f"🔗 Chunk overlap: {CHUNK_OVERLAP} characters")
    print(f"📦 Reading from: {config.AZURE_STORAGE_CONTAINER_NAME}")

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
        print(f"\n🗑️  Clearing existing index...")
        
        existing_results = search_client.search(
            search_text="*",
            select=["chunk_id"],
            top=10000
        )
        
        existing_ids = [dict(r)["chunk_id"] for r in existing_results]
        
        if existing_ids:
            print(f"   Found {len(existing_ids)} existing entries to delete...")
            batch_size = 1000
            for i in range(0, len(existing_ids), batch_size):
                batch = existing_ids[i:i+batch_size]
                docs_to_delete = [{"chunk_id": doc_id} for doc_id in batch]
                search_client.delete_documents(documents=docs_to_delete)
                print(f"   Deleted {min(i+batch_size, len(existing_ids))}/{len(existing_ids)}")
            print(f"   ✅ Index cleared")
        else:
            print(f"   Index is empty")

        # List all blobs in container
        print(f"\n📥 Listing files in blob storage...")
        
        blobs = list(container_client.list_blobs())
        pdf_blobs = [b for b in blobs if b.name.lower().endswith('.pdf')]
        
        print(f"✓ Found {len(pdf_blobs)} PDF files")

        # Process each blob
        total_chunks_created = 0
        documents_processed = 0
        chunks_to_upload = []

        print(f"\n⚙️  Processing PDFs and creating chunks with page numbers...")
        print("-" * 70)

        for blob_info in pdf_blobs:
            blob_name = blob_info.name
            documents_processed += 1
            
            print(f"\n  [{documents_processed}/{len(pdf_blobs)}] Processing: {blob_name}")
            
            # Get blob client
            blob_client = container_client.get_blob_client(blob_name)
            
            # Extract text page by page from blob
            extraction_result = await extract_text_from_blob(
                blob_client, 
                blob_name,
                doc_intelligence_client
            )
            
            if not extraction_result['success'] or not extraction_result['page_texts']:
                print(f"   ⚠️  Skipping: No text extracted")
                continue
            
            page_texts = extraction_result['page_texts']
            page_count = extraction_result['page_count']
            
            # Generate parent_id from blob name
            parent_id = f"blob://{config.AZURE_STORAGE_CONTAINER_NAME}/{blob_name}"
            
            # Split into chunks while tracking page numbers
            chunks = chunk_text_with_pages(page_texts)
            total_chunks_created += len(chunks)

            total_chars = sum(len(p["text"]) for p in page_texts)
            print(f"   📄 Document: {total_chars} chars, {page_count} pages")
            print(f"   ✂️  Created {len(chunks)} chunks with page numbers")

            # Show sample chunk-to-page mapping
            if chunks:
                sample_size = min(3, len(chunks))
                print(f"   📍 Sample chunk → page mapping:")
                for i in range(sample_size):
                    print(f"      Chunk {chunks[i]['chunk_number']} → Page {chunks[i]['page_number']}")

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
                    print(f"      📤 Uploading batch of {len(chunks_to_upload)} chunks...")
                    try:
                        search_client.upload_documents(documents=chunks_to_upload)
                        print(f"      ✅ Batch uploaded")
                    except Exception as batch_error:
                        print(f"      ❌ Batch error: {batch_error}")
                        # Try one by one
                        for single_doc in chunks_to_upload:
                            try:
                                search_client.upload_documents(documents=[single_doc])
                            except Exception as doc_error:
                                print(f"        ❌ Failed chunk: {doc_error}")
                    
                    chunks_to_upload = []

        # Upload remaining chunks
        if chunks_to_upload:
            print(f"\n  📤 Uploading final batch of {len(chunks_to_upload)} chunks...")
            try:
                search_client.upload_documents(documents=chunks_to_upload)
                print(f"  ✅ Final batch uploaded")
            except Exception as batch_error:
                print(f"  ❌ Final batch error: {batch_error}")

        # Summary
        print("\n" + "=" * 70)
        print("✅ FULL DOCUMENT EMBEDDING GENERATION COMPLETE!")
        print("   WITH PAGE NUMBER TRACKING")
        print("=" * 70)
        print(f"📊 Summary:")
        print(f"   ✓ PDF files processed: {documents_processed}")
        print(f"   ✓ Total chunks created: {total_chunks_created}")
        print(f"   ✓ Average chunks per document: {total_chunks_created/documents_processed:.1f}")
        print(f"   ✓ Each chunk has actual page number from PDF")
        print(f"\n🎉 Your index now has {total_chunks_created} searchable chunks with page numbers!")
        print(f"   Each chunk is ~{CHUNK_SIZE} characters")
        print(f"   Model: {config.AZURE_OPENAI_EMBEDDING_MODEL}")
        print(f"   Dimensions: {config.EMBEDDING_DIMENSIONS}")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(generate_embeddings_from_blob_storage())