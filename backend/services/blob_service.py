from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta
import urllib.parse
import config

class BlobService:
    def __init__(self):
        self.blob_service_client = BlobServiceClient.from_connection_string(
            config.AZURE_STORAGE_CONNECTION_STRING
        )
        self.container_name = config.AZURE_STORAGE_CONTAINER_NAME
    
    def generate_download_url(self, blob_name: str, expiry_hours: int = 1) -> str:
        """Generate a temporary download URL (SAS token) for a blob"""
        try:
            # URL decode the blob name first (Azure stores with + as space)
            blob_name = urllib.parse.unquote(blob_name)
            
            # Parse connection string
            conn_parts = dict(
                item.split('=', 1) 
                for item in config.AZURE_STORAGE_CONNECTION_STRING.split(';') 
                if '=' in item
            )
            account_name = conn_parts.get('AccountName')
            account_key = conn_parts.get('AccountKey')
            
            if not account_name or not account_key:
                return None
            
            # Generate SAS token
            sas_token = generate_blob_sas(
                account_name=account_name,
                container_name=self.container_name,
                blob_name=blob_name,
                account_key=account_key,
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
            return f"https://{account_name}.blob.core.windows.net/{self.container_name}/{encoded_blob_name}?{sas_token}"
            
        except Exception as e:
            print(f"❌ Error generating download URL for {blob_name}: {e}")
            return None