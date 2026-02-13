from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta
import urllib.parse
import config
import logging

class BlobService:
    """
    Service class for interacting with Azure Blob Storage.

    This class provides methods to generate secure download URLs for blobs stored
    in Azure Blob Storage using Shared Access Signatures (SAS).
    """
    def __init__(self):
        """
        Initialize the Blob Service.

        Creates a BlobServiceClient using the Azure Storage connection string
        and sets the container name from configuration. Parses the connection string
        to extract account name and key for SAS token generation.
        """
        self.logger = logging.getLogger(__name__)
        self.blob_service_client = BlobServiceClient.from_connection_string(
            config.AZURE_STORAGE_CONNECTION_STRING
        )
        self.container_name = config.AZURE_STORAGE_CONTAINER_NAME
        
        # Parse connection string for SAS generation
        conn_parts = dict(
            item.split('=', 1) 
            for item in config.AZURE_STORAGE_CONNECTION_STRING.split(';') 
            if '=' in item
        )
        self.account_name = conn_parts.get('AccountName')
        self.account_key = conn_parts.get('AccountKey')
    
    def generate_download_url(self, blob_name: str, expiry_hours: int = 1) -> str:
        """
        Generate a temporary download URL (SAS token) for a blob.

        Creates a Shared Access Signature (SAS) token for the specified blob,
        allowing temporary read access. The URL is set to force download as an attachment.

        Args:
            blob_name (str): The name of the blob in Azure Storage.
            expiry_hours (int, optional): Number of hours the SAS token should be valid. Defaults to 1.

        Returns:
            str: The full URL with SAS token for downloading the blob, or None if generation fails.
        """
        try:
            # URL decode the blob name first (Azure stores with + as space)
            blob_name = urllib.parse.unquote(blob_name)
            
            if not self.account_name or not self.account_key:
                self.logger.error("Account name or key not found in connection string")
                return None
            
            # Generate SAS token
            sas_token = generate_blob_sas(
                account_name=self.account_name,
                container_name=self.container_name,
                blob_name=blob_name,
                account_key=self.account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.utcnow() + timedelta(hours=expiry_hours),
                # To force download, uncomment the next line and comment the following line
                content_disposition='attachment'  
                # To view in new tab, use inline
                # content_disposition='inline'
            )
            
            # URL encode the blob name for the URL
            encoded_blob_name = urllib.parse.quote(blob_name, safe='')
            
            # Return full URL with SAS token
            return f"https://{self.account_name}.blob.core.windows.net/{self.container_name}/{encoded_blob_name}?{sas_token}"
            
        except Exception as e:
            self.logger.error("Error generating download URL for %s: %s", blob_name, e)
            return None