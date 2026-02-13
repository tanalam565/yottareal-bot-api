# backend/services/embedding_service.py - Full Code with dimensions parameter

from openai import AzureOpenAI
from typing import List
import config
import logging

class EmbeddingService:
    """
    Service class for generating text embeddings using Azure OpenAI.

    This class provides methods to generate embeddings for text using Azure OpenAI's
    embedding models, with support for custom dimensions and batch processing.
    """
    def __init__(self):
        """
        Initialize the Embedding Service.

        Creates an AzureOpenAI client using the configured endpoint, API key, and version.
        Sets up the deployment, model, and dimensions for embedding generation.
        Logs initialization details.
        """
        self.logger = logging.getLogger(__name__)
        self.client = AzureOpenAI(
            api_version=config.AZURE_OPENAI_EMBEDDING_API_VERSION,
            azure_endpoint=config.AZURE_OPENAI_EMBEDDING_ENDPOINT,
            api_key=config.AZURE_OPENAI_EMBEDDING_KEY
        )
        self.deployment = config.AZURE_OPENAI_EMBEDDING_DEPLOYMENT
        self.model = config.AZURE_OPENAI_EMBEDDING_MODEL
        self.dimensions = config.EMBEDDING_DIMENSIONS
        
        self.logger.info("Embedding service initialized: Model=%s, Deployment=%s, Dimensions=%d", self.model, self.deployment, self.dimensions)
    
    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate an embedding vector for a single text string.

        Creates an embedding using the configured Azure OpenAI model and dimensions.
        Truncates text if it exceeds the maximum length. Returns a zero vector on error.

        Args:
            text (str): The text to generate an embedding for.

        Returns:
            List[float]: The embedding vector as a list of floats.
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
                self.logger.warning("Expected %d dimensions, got %d", self.dimensions, len(embedding))
            
            return embedding
            
        except Exception as e:
            self.logger.error("Error generating embedding: %s", e)
            # Return zero vector as fallback
            return [0.0] * self.dimensions
    
    def generate_embeddings_batch(self, texts: List[str], batch_size: int = 16) -> List[List[float]]:
        """
        Generate embeddings for multiple texts in batches.

        Processes the texts in batches to handle large volumes efficiently.
        Truncates individual texts if they exceed the maximum length.
        Returns zero vectors for all texts on error.

        Args:
            texts (List[str]): List of texts to generate embeddings for.
            batch_size (int, optional): Number of texts to process in each batch. Defaults to 16.

        Returns:
            List[List[float]]: List of embedding vectors, one for each input text.
        """
        all_embeddings = []
        
        try:
            # Process in batches
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                
                # Truncate texts if needed
                truncated_batch = [text[:32000] if len(text) > 32000 else text for text in batch]
                
                self.logger.info("Processing batch %d/%d", i//batch_size + 1, (len(texts)-1)//batch_size + 1)
                
                response = self.client.embeddings.create(
                    input=truncated_batch,
                    model=self.deployment,
                    dimensions=self.dimensions  # Specify output dimensions
                )
                
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)
            
            return all_embeddings
            
        except Exception as e:
            self.logger.error("Error generating batch embeddings: %s", e)
            # Return zero vectors as fallback
            return [[0.0] * self.dimensions for _ in texts]