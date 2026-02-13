# backend/scripts/list_documents.py
"""
Script for listing and reconciling documents in Azure Cognitive Search and Blob Storage.

This script provides utilities to:
- List all unique documents in the search index
- List files in blob storage
- List source files referenced in the search index
- Reconcile differences between blob storage and search index
"""

import asyncio
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient
import urllib.parse
import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


async def list_all_documents():
    """
    List all unique documents in the search index.

    Queries the Azure Cognitive Search index to retrieve all documents,
    extracts unique document names from titles or parent IDs, and logs them.
    """
    logger = logging.getLogger(__name__)
    search_client = SearchClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        index_name=config.AZURE_SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(config.AZURE_SEARCH_KEY)
    )
    
    results = search_client.search(search_text="*", top=1000, select=["title", "parent_id"])
    
    # Collect unique document names
    documents = set()
    
    for result in results:
        r = dict(result)
        title = r.get("title")
        
        if title:
            documents.add(title)
        else:
            # Extract from parent_id if no title
            parent_id = r.get("parent_id")
            if parent_id:
                try:
                    import urllib.parse
                    parsed = urllib.parse.urlparse(parent_id)
                    filename = parsed.path.split('/')[-1]
                    filename = urllib.parse.unquote(filename)
                    if filename:
                        documents.add(filename)
                except:
                    pass
    
    logger.info("Found %d unique documents", len(documents))
    for i, doc in enumerate(sorted(documents), 1):
        logger.info("%d. %s", i, doc)


def list_blob_files():
    """
    List all files in the blob storage container.

    Retrieves all blob names from the configured Azure Blob Storage container,
    excluding directory markers, and returns them as a set of filenames.

    Returns:
        set: Set of filenames in the blob storage container.
    """
    blob_service = BlobServiceClient.from_connection_string(
        config.AZURE_STORAGE_CONNECTION_STRING
    )
    container = blob_service.get_container_client(config.AZURE_STORAGE_CONTAINER_NAME)

    files = set()
    for blob in container.list_blobs():
        if blob.name.endswith("/"):
            continue
        files.add(blob.name.split("/")[-1])
    return files


def list_index_files():
    """
    List all source files referenced in the search index.

    Queries the Azure Cognitive Search index to retrieve all document URLs,
    extracts filenames from the URLs, and returns them as a set.

    Returns:
        set: Set of filenames referenced in the search index.
    """
    client = SearchClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        index_name=config.AZURE_SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(config.AZURE_SEARCH_KEY),
    )

    results = client.search(search_text="*", top=1000, select=["url"])
    files = set()

    for r in results:
        d = dict(r)
        url = d.get("url")
        if not url:
            continue
        parsed = urllib.parse.urlparse(url)
        name = urllib.parse.unquote(parsed.path.split("/")[-1])
        if name:
            files.add(name)
    return files


def reconcile_blob_vs_index():
    """
    Reconcile blob storage files with search index files.

    Compares the files in Azure Blob Storage with those referenced in the
    Azure Cognitive Search index, logging any discrepancies:
    - Files present in blob storage but missing from index
    - Files present in index but missing from blob storage
    """
    logger = logging.getLogger(__name__)
    blob_files = list_blob_files()
    index_files = list_index_files()

    missing = sorted(blob_files - index_files)
    extra = sorted(index_files - blob_files)

    logger.info("Blob files: %d, Index source files: %d", len(blob_files), len(index_files))
    logger.info("Missing from INDEX (present in blob, not indexed): %d", len(missing))
    for i, f in enumerate(missing, 1):
        logger.info("%d. %s", i, f)

    if extra:
        logger.warning("Present in INDEX but not in blob: %d", len(extra))
        for i, f in enumerate(extra, 1):
            logger.warning("%d. %s", i, f)


if __name__ == "__main__":
    # Run the reconcile function by default
    reconcile_blob_vs_index()
