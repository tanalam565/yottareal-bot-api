# backend/services/embedding_service.py - WITH CONNECTION POOLING

from openai import AzureOpenAI, RateLimitError, APIConnectionError
from typing import List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import config
from services.http_client_service import get_shared_http_client


class EmbeddingService:
    def __init__(self):
        # Use shared HTTP client for connection pooling
        self.client = AzureOpenAI(
            api_version=config.AZURE_OPENAI_EMBEDDING_API_VERSION,
            azure_endpoint=config.AZURE_OPENAI_EMBEDDING_ENDPOINT,
            api_key=config.AZURE_OPENAI_EMBEDDING_KEY,
            http_client=get_shared_http_client()  # ← SHARED POOL
        )
        self.deployment = config.AZURE_OPENAI_EMBEDDING_DEPLOYMENT
        self.model = config.AZURE_OPENAI_EMBEDDING_MODEL
        self.dimensions = config.EMBEDDING_DIMENSIONS

        print(f"✓ Embedding service initialized:")
        print(f"  Model: {self.model}")
        print(f"  Deployment: {self.deployment}")
        print(f"  Dimensions: {self.dimensions}")

    @retry(
        retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3)
    )
    def _generate_with_retry(self, text: str) -> List[float]:
        """Inner sync call with tenacity retry — raise to allow retries"""
        response = self.client.embeddings.create(
            input=text,
            model=self.deployment,
            dimensions=self.dimensions
        )
        return response.data[0].embedding

    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding vector for a single text string.
        Sync — callers in async contexts should use asyncio.to_thread().
        """
        try:
            if len(text) > 32000:
                text = text[:32000]

            embedding = self._generate_with_retry(text)

            if len(embedding) != self.dimensions:
                print(f"  ⚠️  Warning: Expected {self.dimensions} dimensions, got {len(embedding)}")

            return embedding

        except Exception as e:
            print(f"❌ Error generating embedding after retries: {e}")
            return [0.0] * self.dimensions

    def generate_embeddings_batch(self, texts: List[str], batch_size: int = 16) -> List[List[float]]:
        """
        Generate embeddings for multiple texts in batches.
        Sync — used in scripts only.
        """
        all_embeddings = []

        try:
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                truncated_batch = [text[:32000] if len(text) > 32000 else text for text in batch]

                print(f"  Processing batch {i//batch_size + 1}/{(len(texts)-1)//batch_size + 1}...")

                response = self.client.embeddings.create(
                    input=truncated_batch,
                    model=self.deployment,
                    dimensions=self.dimensions
                )

                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)

            return all_embeddings

        except Exception as e:
            print(f"❌ Error generating batch embeddings: {e}")
            return [[0.0] * self.dimensions for _ in texts]
