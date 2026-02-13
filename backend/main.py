import logging
from fastapi import FastAPI, HTTPException, Security, Depends, UploadFile, File, Form
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
import uvicorn
import uuid

from services.azure_search_service import AzureSearchService
from services.llm_service import LLMService
from services.document_intelligence_service import DocumentIntelligenceService
import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

"""
YottaReal Bot API - FastAPI Backend

This module provides the main FastAPI application for the YottaReal chatbot API.
It handles chat interactions, document uploads, session management, and integrates
with Azure Cognitive Search, Azure OpenAI, and Azure Document Intelligence services.

Key Features:
- Chat endpoint with hybrid search (vector + keyword) and LLM response generation
- Document upload with automatic text extraction using Azure Document Intelligence
- Session-based document management for temporary user uploads
- API key authentication
- Indexer status and manual trigger endpoints
- Health check endpoint

Endpoints:
- POST /api/chat: Process chat messages with document context
- POST /api/upload: Upload documents for session-based queries
- POST /api/cleanup-session: Clean up session documents
- GET /api/indexer/status: Get Azure Search indexer status
- POST /api/indexer/run: Manually trigger indexer
- GET /api/health: Health check (public)

Environment Variables:
- CHATBOT_API_KEY: Optional API key for authentication
- Various Azure service configurations (see config.py)

Dependencies:
- fastapi: Web framework
- uvicorn: ASGI server
- Azure Cognitive Search, OpenAI, Document Intelligence services
"""

app = FastAPI(title="Property Management Chatbot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOWED_ORIGINS.split(",") if config.CORS_ALLOWED_ORIGINS else [
        
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

search_service = AzureSearchService()
llm_service = LLMService()
doc_intelligence_service = DocumentIntelligenceService()

# In-memory storage for session documents (temporary user uploads)
session_documents: Dict[str, list] = {}

# API Key Authentication
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: str = Security(api_key_header)):
    """
    Verify API key for authentication.
    
    Checks the provided API key against the configured CHATBOT_API_KEY.
    If no API key is configured, authentication is bypassed.
    
    Args:
        api_key: The API key from the request header
        
    Returns:
        bool: True if authentication passes
        
    Raises:
        HTTPException: If API key is invalid or missing when required
    """
    if not config.CHATBOT_API_KEY:
        return True
    
    if api_key != config.CHATBOT_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return True

class ChatRequest(BaseModel):
    """Request model for chat endpoint"""
    message: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    """Response model for chat endpoint"""
    response: str
    sources: List[dict]
    session_id: str

class CleanupRequest(BaseModel):
    """Request model for session cleanup endpoint"""
    session_id: str

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, authenticated: bool = Depends(verify_api_key)):
    """
    Process chat messages with document context and generate AI responses.
    
    Performs hybrid search across uploaded session documents and indexed company documents,
    then generates responses using Azure OpenAI with citation tracking.
    
    Args:
        request: ChatRequest containing message and optional session_id
        authenticated: API key authentication dependency
        
    Returns:
        ChatResponse with AI response, sources, and session_id
        
    Raises:
        HTTPException: For authentication or processing errors
    """
    try:
        logger.info(f"Chat request - Session ID: {request.session_id}, Query: {request.message}")
        logger.debug(f"Active sessions: {list(session_documents.keys())}")
        
        # ===== STEP 1: GET ALL UPLOADED DOCUMENTS FOR THIS SESSION =====
        session_context = []
        if request.session_id and request.session_id in session_documents:
            for doc in session_documents[request.session_id]:
                # Check if document has page_texts (new format with page tracking)
                if 'page_texts' in doc and doc['page_texts']:
                    # Multi-page document - add each page separately
                    for page_info in doc['page_texts']:
                        session_context.append({
                            "content": page_info['text'],
                            "filename": doc["filename"],
                            "source_type": "uploaded",
                            "page_number": page_info['page_number']
                        })
                else:
                    # Old format or single string - add as single page
                    session_context.append({
                        "content": doc["content"],
                        "filename": doc["filename"],
                        "source_type": "uploaded",
                        "page_number": 1
                    })
            
            logger.info(f"Uploaded documents in session: {len(session_documents[request.session_id])} files")
            total_pages = len(session_context)
            logger.debug(f"Total pages across all uploads: {total_pages}")
            for i, doc in enumerate(session_documents[request.session_id], 1):
                page_count = len(doc.get('page_texts', [])) if 'page_texts' in doc else 1
                content_preview = doc['content'][:100].replace('\n', ' ') if 'content' in doc else doc.get('page_texts', [{}])[0].get('text', '')[:100].replace('\n', ' ')
                logger.debug(f"  {i}. {doc['filename']} ({page_count} pages)")
                logger.debug(f"     Content preview: {content_preview}...")
        else:
            logger.info("No uploaded documents in this session")
        
        # ===== STEP 2: CHECK IF CASUAL CHAT (IMPROVED) =====
        casual_patterns = [
            'hi', 'hello', 'hey', 'how are you', 'thanks', 
            'thank you', 'bye', 'goodbye', 'good morning', 'good evening',
            'sup', 'what\'s up', 'wassup', 'yo', 'howdy', 'good night'
        ]
        
        query_lower = request.message.lower().strip()
        is_casual = False
        
        # Method 1: Exact match
        if query_lower in casual_patterns:
            is_casual = True
        # Method 2: Short queries (1-2 words) containing casual words
        elif len(query_lower.split()) <= 2:
            if any(p in query_lower for p in casual_patterns):
                is_casual = True
        # Method 3: Fuzzy match for common variations (handles typos)
        elif any(pattern in query_lower for pattern in ['how are', 'how r u', 'how r you', 'hows it going', 'how do you do']):
            is_casual = True
        # Method 4: Very short queries (likely greetings)
        elif len(query_lower.split()) == 1 and len(query_lower) <= 6:
            is_casual = True
        
        logger.info(f"Query type: {'Casual chat' if is_casual else 'Document query'}")
        
        # ===== STEP 3: SEARCH COMPANY DOCUMENTS =====
        indexed_results = []
        if not is_casual:
            logger.info("Searching company documents...")
            indexed_results = await search_service.search(request.message)
            
            for doc in indexed_results:
                doc["source_type"] = "company"
            
            logger.info(f"Found {len(indexed_results)} company documents")
            for i, doc in enumerate(indexed_results, 1):
                logger.debug(f"  {i}. {doc['filename']}")
        else:
            logger.info("Skipping document search (casual chat)")
        
        # ===== STEP 4: BUILD CONTEXT FOR LLM =====
        all_context = []
        
        if is_casual:
            # Casual chat - no documents needed
            all_context = []
            logger.info("Context for LLM: Empty (casual chat)")
            
        elif session_context:
            # HAS UPLOADS: Send ALL upload pages + top 15 company docs
            all_context = session_context + indexed_results[:15]
            logger.info(f"Context for LLM: {len(all_context)} document pages")
            logger.debug(f"   - ALL {len(session_context)} uploaded pages")
            logger.debug(f"   - Top {len(indexed_results[:15])} company documents")
            
        else:
            # NO UPLOADS: Send top 15 company docs only
            all_context = indexed_results[:15]
            logger.info(f"Context for LLM: {len(all_context)} company documents")
        
        # ===== STEP 5: LOG WHAT'S BEING SENT =====
        logger.info(f"Sending to LLM ({len(all_context)} document pages)")
        for i, doc in enumerate(all_context, 1):
            doc_type = doc.get('source_type', 'unknown')
            page_num = doc.get('page_number', 1)
            logger.debug(f"  {i}. [{doc_type}] {doc['filename']} - Page {page_num}")
            logger.debug(f"      Content length: {len(doc.get('content', ''))} chars")
        
        if not all_context and not is_casual:
            logger.warning("No documents in context!")
        
        # ===== STEP 6: GENERATE RESPONSE =====
        response = await llm_service.generate_response(
            query=request.message,
            context=all_context,
            session_id=request.session_id,
            has_uploads=bool(session_context),
            is_comparison=False
        )
        
        # Deduplicate sources by filename - show each document once
        source_map = {}
        for source in response["sources"]:
            filename = source.get("filename", "Unknown")
            if filename not in source_map:
                source_map[filename] = source

        unique_sources = list(source_map.values())

        logger.info(f"Sources after deduplication: {len(unique_sources)}")
        for i, src in enumerate(unique_sources, 1):
            source_type = src.get('source_type', 'unknown')
            logger.debug(f"  {i}. [{source_type}] {src.get('filename', 'Unknown')}")

        return ChatResponse(
            response=response["answer"],
            sources=unique_sources,
            session_id=response["session_id"]
        )
                
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload")
async def upload_document(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    authenticated: bool = Depends(verify_api_key)
):
    """
    Upload a document and extract text for session-based queries.
    
    Supports PDF, images, Word documents, and text files. Uses Azure Document Intelligence
    to extract text content which is stored in memory for the session.
    
    Args:
        file: The uploaded file
        session_id: Optional session identifier (generated if not provided)
        authenticated: API key authentication dependency
        
    Returns:
        Dict with upload confirmation and metadata
        
    Raises:
        HTTPException: For invalid file types or processing errors
    """
    try:
        if not session_id:
            session_id = str(uuid.uuid4())
        
        logger.info(f"Upload request - Session ID: {session_id}, Filename: {file.filename}, Content-Type: {file.content_type}")
        
        # Validate file type
        allowed_types = [
            'application/pdf',
            'image/jpeg',
            'image/jpg', 
            'image/png',
            'image/tiff',
            'image/bmp',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'text/plain'
        ]
        
        if file.content_type not in allowed_types:
            logger.warning(f"Unsupported file type: {file.content_type}")
            raise HTTPException(
                status_code=400,
                detail=f"File type {file.content_type} not supported"
            )
        
        # Read file content
        file_content = await file.read()
        logger.info(f"File size: {len(file_content)} bytes")
        
        # Extract text using Document Intelligence
        logger.info(f"Extracting text from {file.filename}...")
        extraction_result = await doc_intelligence_service.extract_text(
            file_content,
            file.filename
        )
        
        if not extraction_result['success']:
            logger.error(f"Extraction failed: {extraction_result.get('error')}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to extract text: {extraction_result.get('error', 'Unknown error')}"
            )
        
        logger.info(f"Extracted {len(extraction_result['text'])} characters from {extraction_result['page_count']} pages")
        
        # Store in memory for this session
        if session_id not in session_documents:
            session_documents[session_id] = []
        
        session_documents[session_id].append({
            "filename": file.filename,
            "content": extraction_result['text'],  # Full text for backward compat
            "page_texts": extraction_result.get('page_texts', []),  # Per-page text with page numbers
            "page_count": extraction_result['page_count']
        })
        
        logger.info(f"Stored in session: {session_id}")
        logger.debug(f"Session now has {len(session_documents[session_id])} documents:")
        for i, doc in enumerate(session_documents[session_id], 1):
            page_count = len(doc.get('page_texts', [])) if 'page_texts' in doc else doc.get('page_count', 1)
            logger.debug(f"   {i}. {doc['filename']} ({page_count} pages, {len(doc.get('content', ''))} chars)")
        logger.info(f"Total active sessions: {len(session_documents)}")
        
        return {
            "message": "File uploaded and ready for queries!",
            "filename": file.filename,
            "session_id": session_id,
            "pages_extracted": extraction_result['page_count'],
            "text_length": len(extraction_result['text']),
            "immediate_access": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in upload_document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/cleanup-session")
async def cleanup_session(
    request: CleanupRequest,
    authenticated: bool = Depends(verify_api_key)
):
    """
    Clean up session documents from memory.
    
    Removes all uploaded documents associated with the given session ID
    to free up memory and ensure data privacy.
    
    Args:
        request: CleanupRequest containing session_id
        authenticated: API key authentication dependency
        
    Returns:
        Dict with cleanup confirmation and statistics
        
    Raises:
        HTTPException: For invalid requests or processing errors
    """
    try:
        session_id = request.session_id
        logger.info(f"Cleanup request - Session ID: {session_id}")
        
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")
        
        if session_id in session_documents:
            files_count = len(session_documents[session_id])
            del session_documents[session_id]
            logger.info(f"Deleted {files_count} documents from session")
            logger.info(f"Remaining active sessions: {len(session_documents)}")
            
            return {
                "message": "Session cleaned up successfully",
                "session_id": session_id,
                "files_deleted": files_count
            }
        
        logger.warning(f"Session not found: {session_id}")
        return {
            "message": "No session found",
            "session_id": session_id,
            "files_deleted": 0
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in cleanup_session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/indexer/status")
async def get_indexer_status(authenticated: bool = Depends(verify_api_key)):
    """
    Get status of Azure Search indexer.
    
    Returns current status, last run time, and any error information
    for the Azure Cognitive Search indexer.
    
    Args:
        authenticated: API key authentication dependency
        
    Returns:
        Dict with indexer status information
        
    Raises:
        HTTPException: For authentication or service errors
    """
    try:
        status = await search_service.get_indexer_status()
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/indexer/run")
async def run_indexer(authenticated: bool = Depends(verify_api_key)):
    """
    Manually trigger Azure Search indexer.
    
    Initiates a full re-indexing of documents in Azure Cognitive Search.
    This is useful for updating the search index after document changes.
    
    Args:
        authenticated: API key authentication dependency
        
    Returns:
        Dict with success confirmation
        
    Raises:
        HTTPException: For authentication or indexer trigger failures
    """
    try:
        success = await search_service.run_indexer()
        if success:
            return {"message": "Indexer triggered successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to trigger indexer")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
async def health_check():
    """
    Public health check endpoint.
    
    Returns a simple health status for load balancer and monitoring checks.
    No authentication required.
    
    Returns:
        Dict with health status
    """
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)