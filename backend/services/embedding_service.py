# backend/services/embedding_service.py - Full Code with dimensions parameter

from openai import AzureOpenAI
from typing import List
import config

class EmbeddingService:
    def __init__(self):
        self.client = AzureOpenAI(
            api_version=config.AZURE_OPENAI_EMBEDDING_API_VERSION,
            azure_endpoint=config.AZURE_OPENAI_EMBEDDING_ENDPOINT,
            api_key=config.AZURE_OPENAI_EMBEDDING_KEY
        )
        self.deployment = config.AZURE_OPENAI_EMBEDDING_DEPLOYMENT
        self.model = config.AZURE_OPENAI_EMBEDDING_MODEL
        self.dimensions = config.EMBEDDING_DIMENSIONS
        
        print(f"✓ Embedding service initialized:")
        print(f"  Model: {self.model}")
        print(f"  Deployment: {self.deployment}")
        print(f"  Dimensions: {self.dimensions}")
    
    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding vector for a single text string
        
        Args:
            text: Text to generate embedding for
            
        Returns:
            List of floats representing the embedding vector
        """
        try:
            # Truncate text if too long (max 8191 tokens)
            if len(text) > 32000:
                text = text[:32000]
            
            # Use dimensions parameter to get 1536-dim embeddings from text-embedding-3-large
            response = self.client.embeddings.create(
                input=text,
                model=self.deployment,
                dimensions=self.dimensions  # Specify output dimensions
            )
            
            embedding = response.data[0].embedding
            
            # Verify dimensions
            if len(embedding) != self.dimensions:
                print(f"  ⚠️  Warning: Expected {self.dimensions} dimensions, got {len(embedding)}")
            
            return embedding
            
        except Exception as e:
            print(f"❌ Error generating embedding: {e}")
            # Return zero vector as fallback
            return [0.0] * self.dimensions
    
    def generate_embeddings_batch(self, texts: List[str], batch_size: int = 16) -> List[List[float]]:
        """
        Generate embeddings for multiple texts in batches
        
        Args:
            texts: List of texts to generate embedings for
            batch_size: Number of texts to process in each batch
            
        Returns:
            List of embedding vectors
        """
        all_embeddings = []
        
        try:
            # Process in batches
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                
                # Truncate texts if needed
                truncated_batch = [text[:32000] if len(text) > 32000 else text for text in batch]
                
                print(f"  Processing batch {i//batch_size + 1}/{(len(texts)-1)//batch_size + 1}...")
                
                response = self.client.embeddings.create(
                    input=truncated_batch,
                    model=self.deployment,
                    dimensions=self.dimensions  # Specify output dimensions
                )
                
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)
            
            return all_embeddings
            
        except Exception as e:
            print(f"❌ Error generating batch embeddings: {e}")
            # Return zero vectors as fallback
            return [[0.0] * self.dimensions for _ in texts]