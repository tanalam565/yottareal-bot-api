# backend/main.py - WITH REDIS SESSIONS, RATE LIMITING, FILE VALIDATION

from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, HTTPException, Security, Depends, UploadFile, File, Form, Request
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
import uvicorn
import uuid
import json

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from services.azure_search_service import AzureSearchService
from services.llm_service import LLMService
from services.document_intelligence_service import DocumentIntelligenceService
from services.redis_service import get_redis_client, close_redis
import config

"""
YottaReal Bot API - FastAPI Backend.

Provides chat, upload, session cleanup, indexer controls, and health endpoints.
The application integrates Azure Cognitive Search, Azure OpenAI, Azure Document
Intelligence, and Redis-backed session/history state.
"""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Reduce noisy third-party logs while keeping app/service logs readable.
for noisy_logger in [
    "httpx",
    "httpcore",
    "azure",
    "azure.core.pipeline.policies.http_logging_policy",
    "urllib3",
    "openai",
    "gunicorn.access",
    "uvicorn.access",
]:
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

# ── File validation via magic bytes (not trusting content-type header) ──────────
ALLOWED_SIGNATURES = [
    b'%PDF',              # PDF
    b'\xff\xd8\xff',      # JPEG
    b'\x89PNG\r\n\x1a\n', # PNG
    b'II*\x00',           # TIFF little-endian
    b'MM\x00*',           # TIFF big-endian
    b'BM',                # BMP
    b'PK\x03\x04',        # DOCX (ZIP-based)
]

ALLOWED_CONTENT_TYPES = [
    'application/pdf',
    'image/jpeg',
    'image/jpg',
    'image/png',
    'image/tiff',
    'image/bmp',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'text/plain'
]


def validate_file_content(content: bytes, content_type: str) -> bool:
    """Validate file using magic bytes, not just the content-type header"""
    for sig in ALLOWED_SIGNATURES:
        if content[:len(sig)] == sig:
            return True
    # Plain text has no reliable magic bytes — attempt UTF-8 decode
    if content_type == 'text/plain':
        try:
            content[:1024].decode('utf-8')
            return True
        except UnicodeDecodeError:
            return False
    return False


# ── Lifespan: close Redis pool on shutdown ───────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_redis()


# ── Rate limiter ─────────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Property Management Chatbot API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


search_service = AzureSearchService()
llm_service = LLMService()
doc_intelligence_service = DocumentIntelligenceService()

# ── API Key Authentication ────────────────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)):
    """
    Verify API key for authentication.

    Args:
        api_key: API key provided in `X-API-Key` header.

    Returns:
        bool: True if authentication succeeds.

    Raises:
        HTTPException: If key is missing/invalid when auth is enabled.
    """
    if not config.CHATBOT_API_KEY:
        return True
    if api_key != config.CHATBOT_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return True


class ChatRequest(BaseModel):
    """Request model for chat endpoint."""
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    """Response model for chat endpoint."""
    response: str
    sources: List[dict]
    session_id: str


class CleanupRequest(BaseModel):
    """Request model for session cleanup endpoint."""
    session_id: str


@app.post("/api/chat", response_model=ChatResponse)
@limiter.limit(config.RATE_LIMIT_CHAT)
async def chat(request: Request, body: ChatRequest, authenticated: bool = Depends(verify_api_key)):
    """
    Process chat messages with session uploads and indexed document retrieval.

    Args:
        request: FastAPI request (used by limiter middleware).
        body: Chat request payload.
        authenticated: Authentication dependency guard.

    Returns:
        ChatResponse: AI response with source citations and session id.
    """
    try:
        logger.info(f"Chat request - Session ID: {body.session_id}, Query: {body.message}")

        # ===== STEP 1: GET ALL UPLOADED DOCUMENTS FOR THIS SESSION (REDIS) =====
        session_context = []
        redis_client = await get_redis_client()

        if body.session_id:
            session_key = f"session:{body.session_id}"
            session_data = await redis_client.get(session_key)
            session_docs = json.loads(session_data) if session_data else []

            # Refresh TTL on access
            if session_data:
                await redis_client.expire(session_key, config.SESSION_TTL_SECONDS)

            for doc in session_docs:
                if 'page_texts' in doc and doc['page_texts']:
                    for page_info in doc['page_texts']:
                        session_context.append({
                            "content": page_info['text'],
                            "filename": doc["filename"],
                            "source_type": "uploaded",
                            "page_number": page_info['page_number']
                        })
                else:
                    session_context.append({
                        "content": doc["content"],
                        "filename": doc["filename"],
                        "source_type": "uploaded",
                        "page_number": 1
                    })

            logger.info(f"Uploaded documents in session: {len(session_docs)} files")
            logger.debug(f"Total pages across all uploads: {len(session_context)}")
            for i, doc in enumerate(session_docs, 1):
                page_count = len(doc.get('page_texts', [])) if 'page_texts' in doc else 1
                content_preview = doc['content'][:100].replace('\n', ' ') if 'content' in doc else doc.get('page_texts', [{}])[0].get('text', '')[:100].replace('\n', ' ')
                logger.debug(f"{i}. {doc['filename']} ({page_count} pages)")
                logger.debug(f"Content preview: {content_preview}...")
        else:
            logger.info("No uploaded documents in this session")

        # ===== STEP 2: CHECK IF CASUAL CHAT =====
        casual_patterns = [
            'hi', 'hello', 'hey', 'how are you', 'thanks',
            'thank you', 'bye', 'goodbye', 'good morning', 'good evening',
            'sup', 'what\'s up', 'wassup', 'yo', 'howdy', 'good night'
        ]

        query_lower = body.message.lower().strip()
        is_casual = False

        if query_lower in casual_patterns:
            is_casual = True
        elif len(query_lower.split()) <= 2:
            if any(p in query_lower for p in casual_patterns):
                is_casual = True
        elif any(pattern in query_lower for pattern in ['how are', 'how r u', 'how r you', 'hows it going', 'how do you do']):
            is_casual = True
        elif len(query_lower.split()) == 1 and len(query_lower) <= 6:
            is_casual = True

        logger.info(f"Query type: {'Casual chat' if is_casual else 'Document query'}")

        # ===== STEP 3: SEARCH COMPANY DOCUMENTS =====
        indexed_results = []
        if not is_casual:
            logger.info("Searching company documents")
            indexed_results = await search_service.search(body.message)
            for doc in indexed_results:
                doc["source_type"] = "company"
            logger.info(f"Found {len(indexed_results)} company documents")
            for i, doc in enumerate(indexed_results, 1):
                logger.debug(f"{i}. {doc['filename']}")
        else:
            logger.info("Skipping document search (casual chat)")

        # ===== STEP 4: BUILD CONTEXT FOR LLM =====
        all_context = []

        if is_casual:
            all_context = []
            logger.info("Context for LLM: Empty (casual chat)")
        elif session_context:
            all_context = session_context + indexed_results[:15]
            logger.info(f"Context for LLM: {len(all_context)} document pages")
            logger.debug(f"ALL {len(session_context)} uploaded pages")
            logger.debug(f"Top {len(indexed_results[:15])} company documents")
        else:
            all_context = indexed_results[:15]
            logger.info(f"Context for LLM: {len(all_context)} company documents")

        # ===== STEP 5: LOG WHAT'S BEING SENT =====
        logger.info(f"Sending to LLM ({len(all_context)} document pages)")
        for i, doc in enumerate(all_context, 1):
            doc_type = doc.get('source_type', 'unknown')
            page_num = doc.get('page_number', 1)
            icon = "📤" if doc_type == "uploaded" else "📁"
            logger.debug(f"{i}. {icon} [{doc_type}] {doc['filename']} - Page {page_num}")
            logger.debug(f"Content length: {len(doc.get('content', ''))} chars")

        if not all_context and not is_casual:
            logger.warning("No documents in context for non-casual query")

        # ===== STEP 6: GENERATE RESPONSE =====
        response = await llm_service.generate_response(
            query=body.message,
            context=all_context,
            session_id=body.session_id,
            has_uploads=bool(session_context),
            is_comparison=False
        )

        # Deduplicate sources by filename
        source_map = {}
        for source in response["sources"]:
            filename = source.get("filename", "Unknown")
            if filename not in source_map:
                source_map[filename] = source

        unique_sources = list(source_map.values())

        logger.info(f"Sources after deduplication: {len(unique_sources)}")
        for i, src in enumerate(unique_sources, 1):
            source_type = src.get('source_type', 'unknown')
            icon = "📤" if source_type == "uploaded" else "📁"
            logger.debug(f"{i}. {icon} {src.get('filename', 'Unknown')}")

        return ChatResponse(
            response=response["answer"],
            sources=unique_sources,
            session_id=response["session_id"]
        )

    except Exception as e:
        logger.exception(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/upload")
@limiter.limit(config.RATE_LIMIT_UPLOAD)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    authenticated: bool = Depends(verify_api_key)
):
    """
    Upload a document, extract text, and store results in Redis session state.

    Applies content-type, signature, page, size, and per-session upload limits.
    """
    try:
        if not session_id:
            session_id = str(uuid.uuid4())

        logger.info(f"Upload request - Session ID: {session_id}, Filename: {file.filename}, Content-Type: {file.content_type}")

        # Check upload count for this session
        redis_client = await get_redis_client()
        session_key = f"session:{session_id}"
        session_data = await redis_client.get(session_key)
        current_docs = json.loads(session_data) if session_data else []

        if len(current_docs) >= config.MAX_UPLOADS_PER_SESSION:
            logger.warning(f"Upload limit reached: {len(current_docs)}/{config.MAX_UPLOADS_PER_SESSION}")
            raise HTTPException(
                status_code=400,
                detail=f"Upload limit reached. Maximum {config.MAX_UPLOADS_PER_SESSION} files per session."
            )

        # Validate content-type header
        if file.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"File type {file.content_type} not supported"
            )

        # Read file content
        file_content = await file.read()
        logger.info(f"File size: {len(file_content)} bytes")

        # Validate file size
        if len(file_content) > config.MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"File exceeds {config.MAX_FILE_SIZE_MB}MB limit"
            )

        # Validate file content via magic bytes
        if not validate_file_content(file_content, file.content_type):
            raise HTTPException(
                status_code=400,
                detail="File content does not match its declared type"
            )

        # Extract text using Document Intelligence
        logger.info(f"Extracting text from {file.filename}")
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

        # Add to session documents
        current_docs.append({
            "filename": file.filename,
            "content": extraction_result['text'],
            "page_texts": extraction_result.get('page_texts', []),
            "page_count": extraction_result['page_count']
        })

        # Store in Redis with TTL
        await redis_client.setex(
            session_key,
            config.SESSION_TTL_SECONDS,
            json.dumps(current_docs)
        )

        logger.info(f"Stored in Redis session: {session_id}")
        logger.info(f"Session now has {len(current_docs)}/{config.MAX_UPLOADS_PER_SESSION} documents")
        for i, doc in enumerate(current_docs, 1):
            page_count = len(doc.get('page_texts', [])) if 'page_texts' in doc else doc.get('page_count', 1)
            logger.debug(f"{i}. {doc['filename']} ({page_count} pages, {len(doc.get('content', ''))} chars)")

        return {
            "message": "File uploaded and ready for queries!",
            "filename": file.filename,
            "session_id": session_id,
            "pages_extracted": extraction_result['page_count'],
            "text_length": len(extraction_result['text']),
            "immediate_access": True,
            "uploads_remaining": config.MAX_UPLOADS_PER_SESSION - len(current_docs)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in upload_document: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/cleanup-session")
async def cleanup_session(
    request_body: CleanupRequest,
    authenticated: bool = Depends(verify_api_key)
):
    """
    Delete all uploaded documents for a session from Redis.

    Args:
        request_body: Cleanup request with `session_id`.
        authenticated: Authentication dependency guard.
    """
    try:
        session_id = request_body.session_id
        logger.info(f"Cleanup request - Session ID: {session_id}")

        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")

        redis_client = await get_redis_client()
        session_key = f"session:{session_id}"
        session_data = await redis_client.get(session_key)

        if session_data:
            session_docs = json.loads(session_data)
            files_count = len(session_docs)
            await redis_client.delete(session_key)
            logger.info(f"Deleted {files_count} documents from Redis session")
            return {
                "message": "Session cleaned up successfully",
                "session_id": session_id,
                "files_deleted": files_count
            }

        logger.warning("Session not found")
        return {
            "message": "No session found",
            "session_id": session_id,
            "files_deleted": 0
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in cleanup_session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/indexer/status")
async def get_indexer_status(authenticated: bool = Depends(verify_api_key)):
    """Get status of Azure Search indexer"""
    try:
        status = await search_service.get_indexer_status()
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/indexer/run")
async def run_indexer(authenticated: bool = Depends(verify_api_key)):
    """Manually trigger Azure Search indexer"""
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
    """Health check — verifies Redis is reachable"""
    health = {"status": "healthy", "redis": "healthy"}

    try:
        redis_client = await get_redis_client()
        await redis_client.ping()
    except Exception as e:
        health["status"] = "degraded"
        health["redis"] = f"unhealthy: {str(e)}"

    return health


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)