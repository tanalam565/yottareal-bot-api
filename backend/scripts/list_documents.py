# # backend/scripts/list_documents.py

# import asyncio
# from azure.search.documents import SearchClient
# from azure.core.credentials import AzureKeyCredential
# import sys
# import os

# sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# import config

# async def list_all_documents():
#     search_client = SearchClient(
#         endpoint=config.AZURE_SEARCH_ENDPOINT,
#         index_name=config.AZURE_SEARCH_INDEX_NAME,
#         credential=AzureKeyCredential(config.AZURE_SEARCH_KEY)
#     )
    
#     results = search_client.search(search_text="*", top=1000, select=["title", "parent_id"])
    
#     # Collect unique document names
#     documents = set()
    
#     for result in results:
#         r = dict(result)
#         title = r.get("title")
        
#         if title:
#             documents.add(title)
#         else:
#             # Extract from parent_id if no title
#             parent_id = r.get("parent_id")
#             if parent_id:
#                 try:
#                     import urllib.parse
#                     parsed = urllib.parse.urlparse(parent_id)
#                     filename = parsed.path.split('/')[-1]
#                     filename = urllib.parse.unquote(filename)
#                     if filename:
#                         documents.add(filename)
#                 except:
#                     pass
    
#     print(f"\n📚 Found {len(documents)} unique documents:\n")
#     for i, doc in enumerate(sorted(documents), 1):
#         print(f"{i}. {doc}")


# if __name__ == "__main__":
#     asyncio.run(list_all_documents())

# backend/scripts/reconcile_blob_vs_index.py

from azure.storage.blob import BlobServiceClient
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
import urllib.parse
import os, sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


def list_blob_files():
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


def main():
    blob_files = list_blob_files()
    index_files = list_index_files()

    missing = sorted(blob_files - index_files)
    extra = sorted(index_files - blob_files)

    print(f"\n📦 Blob files: {len(blob_files)}")
    print(f"🧾 Index source files: {len(index_files)}")

    print(f"\n❌ Missing from INDEX (present in blob, not indexed): {len(missing)}")
    for i, f in enumerate(missing, 1):
        print(f"{i}. {f}")

    if extra:
        print(f"\n⚠️ Present in INDEX but not in blob: {len(extra)}")
        for i, f in enumerate(extra, 1):
            print(f"{i}. {f}")

if __name__ == "__main__":
    main()
