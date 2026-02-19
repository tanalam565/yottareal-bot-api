from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexerClient
from azure.search.documents.models import VectorizedQuery
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ServiceRequestError, HttpResponseError
from services.blob_service import BlobService
from typing import List, Dict
import urllib.parse
import asyncio
import config
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from services.embedding_service import EmbeddingService


class AzureSearchService:
    def __init__(self):
        self.endpoint = config.AZURE_SEARCH_ENDPOINT
        self.key = config.AZURE_SEARCH_KEY
        self.index_name = config.AZURE_SEARCH_INDEX_NAME
        self.indexer_name = "azureblob-indexer-yotta"

        self.credential = AzureKeyCredential(self.key)

        self.search_client = SearchClient(
            endpoint=self.endpoint,
            index_name=self.index_name,
            credential=self.credential
        )

        self.indexer_client = SearchIndexerClient(
            endpoint=self.endpoint,
            credential=self.credential
        )

        self.embedding_service = EmbeddingService()
        self.blob_service = BlobService()

        print(f"✓ Connected to index: {self.index_name} (Hybrid Search enabled)")
        print(f"✓ Max chunks per document: {config.MAX_CHUNKS_PER_DOCUMENT}")

    def _extract_filename(self, result_dict: dict) -> str:
        """Extract filename from search result - handle parent docs and chunks"""
        title = result_dict.get("title")
        if title and title.strip():
            return title

        filepath = result_dict.get("filepath")
        if filepath and filepath.strip():
            return filepath.split("/")[-1] if "/" in filepath else filepath

        parent_id = result_dict.get("parent_id")
        if parent_id and parent_id.strip():
            try:
                parsed = urllib.parse.urlparse(parent_id)
                path = parsed.path
                if '/' in path:
                    filename = path.split('/')[-1]
                    filename = urllib.parse.unquote(filename)
                    if filename:
                        return filename
            except:
                pass

        return "Unknown Document"

    # ── Sync helpers (run via asyncio.to_thread) ─────────────────────────────────

    @retry(
        retry=retry_if_exception_type((ServiceRequestError, HttpResponseError)),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3)
    )
    def _execute_search_sync(self, query: str, vector_query, top: int) -> list:
        """Execute hybrid search synchronously and return consumed list of dicts"""
        results = self.search_client.search(
            search_text=query,
            vector_queries=[vector_query],
            top=top * 5,
            include_total_count=True
        )
        return [dict(r) for r in results]

    @retry(
        retry=retry_if_exception_type((ServiceRequestError, HttpResponseError)),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3)
    )
    def _execute_keyword_search_sync(self, query: str, top: int) -> list:
        """Execute keyword-only search synchronously"""
        results = self.search_client.search(
            search_text=query,
            top=top * 3,
            include_total_count=True
        )
        return [dict(r) for r in results]

    def _get_indexer_status_sync(self):
        return self.indexer_client.get_indexer_status(self.indexer_name)

    def _run_indexer_sync(self):
        self.indexer_client.run_indexer(self.indexer_name)

    # ── Async public methods ──────────────────────────────────────────────────────

    async def search(self, query: str, top: int = config.MAX_SEARCH_RESULTS) -> List[Dict]:
        """
        Perform hybrid search (keyword + vector) on indexed documents
        with per-document chunk limiting to avoid one document dominating results
        """
        try:
            print(f"\n{'='*70}")
            print(f"🔍 Hybrid search for: '{query}'")
            print(f"📊 Target results: {top}")
            print(f"📄 Max chunks per document: {config.MAX_CHUNKS_PER_DOCUMENT}")
            print(f"{'='*70}")

            # Generate query embedding off the event loop
            query_embedding = await asyncio.to_thread(
                self.embedding_service.generate_embedding, query
            )

            vector_query = VectorizedQuery(
                vector=query_embedding,
                k_nearest_neighbors=top * 8,
                fields="content_vector"
            )

            # Execute search off the event loop
            raw_results = await asyncio.to_thread(
                self._execute_search_sync, query, vector_query, top
            )

            # Group chunks by parent_id and limit per document
            parent_chunks = {}
            processed_results = []

            print(f"\n📥 Processing search results with per-document limiting...")

            for result_dict in raw_results:
                parent_id = result_dict.get("parent_id")
                if not parent_id:
                    parent_id = result_dict.get("chunk_id", f"standalone_{len(parent_chunks)}")

                if parent_id not in parent_chunks:
                    parent_chunks[parent_id] = {
                        'count': 0,
                        'chunks': [],
                        'filename': self._extract_filename(result_dict)
                    }

                if parent_chunks[parent_id]['count'] >= config.MAX_CHUNKS_PER_DOCUMENT:
                    continue

                content = result_dict.get("content", "")
                if isinstance(content, list):
                    content = " ".join(str(item) for item in content)

                if not content:
                    continue

                filename = parent_chunks[parent_id]['filename']

                blob_name = result_dict.get("metadata_storage_name", "")
                download_url = None
                if blob_name:
                    try:
                        download_url = self.blob_service.generate_download_url(blob_name)
                    except Exception as e:
                        print(f"   ⚠️  Error generating download URL for {blob_name}: {e}")

                chunk_data = {
                    "content": str(content)[:5000],
                    "filename": filename,
                    "source_type": "company",
                    "download_url": download_url,
                    "parent_id": parent_id,
                    "chunk_number": result_dict.get("chunk_number"),
                    "page_number": result_dict.get("page_number", 1)
                }

                parent_chunks[parent_id]['chunks'].append(chunk_data)
                parent_chunks[parent_id]['count'] += 1
                processed_results.append(chunk_data)

                if len(processed_results) >= top:
                    break

            print(f"\n📊 Retrieval Statistics:")
            print(f"   ✓ Total unique documents: {len(parent_chunks)}")
            print(f"   ✓ Total chunks retrieved: {len(processed_results)}")

            print(f"\n📄 Chunks per document:")
            for parent_id, data in parent_chunks.items():
                filename = data['filename']
                count = data['count']
                status = "⚠️ LIMITED" if count >= config.MAX_CHUNKS_PER_DOCUMENT else "✓"
                print(f"   {status} {filename}: {count} chunks")

            print(f"{'='*70}\n")

            return processed_results[:top]

        except Exception as e:
            print(f"❌ Hybrid search error: {e}")
            import traceback
            traceback.print_exc()
            return await self._fallback_keyword_search(query, top)

    async def _fallback_keyword_search(self, query: str, top: int) -> List[Dict]:
        """Fallback to keyword-only search if hybrid search fails"""
        try:
            print(f"\n⚠️  Falling back to keyword-only search")

            raw_results = await asyncio.to_thread(
                self._execute_keyword_search_sync, query, top
            )

            parent_chunks = {}
            search_results = []

            for result_dict in raw_results:
                parent_id = result_dict.get("parent_id")
                if not parent_id:
                    parent_id = result_dict.get("chunk_id", f"standalone_{len(parent_chunks)}")

                if parent_id not in parent_chunks:
                    parent_chunks[parent_id] = 0

                if parent_chunks[parent_id] >= config.MAX_CHUNKS_PER_DOCUMENT:
                    continue

                content = result_dict.get("content", "")
                if isinstance(content, list):
                    content = " ".join(str(item) for item in content)

                filename = self._extract_filename(result_dict)

                if filename == "Unknown Document":
                    continue

                blob_name = result_dict.get("metadata_storage_name", "")
                download_url = None
                if blob_name:
                    download_url = self.blob_service.generate_download_url(blob_name)

                if content:
                    search_results.append({
                        "content": str(content)[:5000],
                        "filename": filename,
                        "source_type": "company",
                        "download_url": download_url,
                        "page_number": result_dict.get("page_number", 1)
                    })
                    parent_chunks[parent_id] += 1

                if len(search_results) >= top:
                    break

            print(f"✓ Keyword search returned {len(search_results)} results from {len(parent_chunks)} documents")
            return search_results

        except Exception as e:
            print(f"❌ Fallback search error: {e}")
            return []

    async def get_indexer_status(self):
        """Get status of the Azure Search indexer"""
        try:
            status = await asyncio.to_thread(self._get_indexer_status_sync)
            return {
                "name": status.name,
                "status": status.status,
                "last_result": {
                    "status": status.last_result.status if status.last_result else None,
                    "error_message": status.last_result.error_message if status.last_result else None
                }
            }
        except Exception as e:
            print(f"Error getting indexer status: {e}")
            return {"error": str(e)}

    async def run_indexer(self):
        """Manually trigger the indexer to process new documents"""
        try:
            await asyncio.to_thread(self._run_indexer_sync)
            print(f"✓ Indexer '{self.indexer_name}' triggered successfully")
            return True
        except Exception as e:
            print(f"❌ Error running indexer: {e}")
            return False