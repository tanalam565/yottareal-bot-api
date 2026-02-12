from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexerClient
from azure.search.documents.models import VectorizedQuery
from azure.core.credentials import AzureKeyCredential
from services.blob_service import BlobService
from typing import List, Dict
import urllib.parse
import config
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
        
        # Try title first
        title = result_dict.get("title")
        if title and title.strip():
            return title
        
        # Try filepath
        filepath = result_dict.get("filepath")
        if filepath and filepath.strip():
            return filepath.split("/")[-1] if "/" in filepath else filepath
        
        # Try parent_id
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
            
            # Generate query embedding
            query_embedding = self.embedding_service.generate_embedding(query)
            
            # Create vector query
            vector_query = VectorizedQuery(
                vector=query_embedding,
                k_nearest_neighbors=top * 8,  # Get more initial results for filtering
                fields="content_vector"
            )
            
            # Perform hybrid search - get more results than needed
            results = self.search_client.search(
                search_text=query,
                vector_queries=[vector_query],
                top=top * 5,  # Fetch 5x more results to account for per-doc limiting
                include_total_count=True
            )
            
            # Group chunks by parent_id and limit per document
            parent_chunks = {}  # {parent_id: [chunks]}
            processed_results = []
            
            print(f"\n📥 Processing search results with per-document limiting...")
            
            for result in results:
                result_dict = dict(result)
                
                # Get parent_id to group chunks
                parent_id = result_dict.get("parent_id")
                if not parent_id:
                    # No parent_id means it's a standalone document
                    parent_id = result_dict.get("chunk_id", f"standalone_{len(parent_chunks)}")
                
                # Initialize parent tracking
                if parent_id not in parent_chunks:
                    parent_chunks[parent_id] = {
                        'count': 0,
                        'chunks': [],
                        'filename': self._extract_filename(result_dict)
                    }
                
                # Check if we've hit the per-document limit
                if parent_chunks[parent_id]['count'] >= config.MAX_CHUNKS_PER_DOCUMENT:
                    continue  # Skip this chunk, already have enough from this document
                
                # Get content
                content = result_dict.get("content", "")
                if isinstance(content, list):
                    content = " ".join(str(item) for item in content)
                
                if not content:
                    continue
                
                filename = parent_chunks[parent_id]['filename']
                
                # Generate download URL from metadata_storage_name
                blob_name = result_dict.get("metadata_storage_name", "")
                download_url = None
                if blob_name:
                    try:
                        download_url = self.blob_service.generate_download_url(blob_name)
                    except Exception as e:
                        print(f"   ⚠️  Error generating download URL for {blob_name}: {e}")
                
                # Add to parent's chunks
                chunk_data = {
                    "content": str(content)[:5000],
                    "filename": filename,
                    "source_type": "company",
                    "download_url": download_url,
                    "parent_id": parent_id,
                    "chunk_number": result_dict.get("chunk_number"),
                    "page_number": result_dict.get("page_number", 1)  # ← ACTUAL PAGE NUMBER FROM PDF
                }
                
                parent_chunks[parent_id]['chunks'].append(chunk_data)
                parent_chunks[parent_id]['count'] += 1
                processed_results.append(chunk_data)
                
                # Stop if we have enough results overall
                if len(processed_results) >= top:
                    break
            
            # Log statistics
            print(f"\n📊 Retrieval Statistics:")
            print(f"   ✓ Total unique documents: {len(parent_chunks)}")
            print(f"   ✓ Total chunks retrieved: {len(processed_results)}")
            
            # Show per-document breakdown
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
            
            results = self.search_client.search(
                search_text=query,
                top=top * 3,
                include_total_count=True
            )
            
            # Apply same per-document limiting
            parent_chunks = {}
            search_results = []
            
            for result in results:
                result_dict = dict(result)
                
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
                        "page_number": result_dict.get("page_number", 1)  # ← ACTUAL PAGE NUMBER
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
            status = self.indexer_client.get_indexer_status(self.indexer_name)
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
            self.indexer_client.run_indexer(self.indexer_name)
            print(f"✓ Indexer '{self.indexer_name}' triggered successfully")
            return True
        except Exception as e:
            print(f"❌ Error running indexer: {e}")
            return False