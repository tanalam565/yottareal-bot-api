from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    SearchFieldDataType,
    SearchIndexer,
    SearchIndexerDataContainer,
    SearchIndexerDataSourceConnection,
    SearchIndexerSkillset,
    InputFieldMappingEntry,
    OutputFieldMappingEntry,
    OcrSkill,
    MergeSkill,
    SplitSkill,
    TextSplitMode,
    FieldMapping,
)
from azure.core.credentials import AzureKeyCredential
from typing import List, Dict
import config

class AzureSearchService:
    def __init__(self):
        self.endpoint = config.AZURE_SEARCH_ENDPOINT
        self.key = config.AZURE_SEARCH_KEY
        self.index_name = config.AZURE_SEARCH_INDEX_NAME
        self.datasource_name = config.AZURE_SEARCH_DATASOURCE_NAME
        self.indexer_name = config.AZURE_SEARCH_INDEXER_NAME
        self.skillset_name = "property-ocr-skillset"
        
        self.credential = AzureKeyCredential(self.key)
        self.search_client = SearchClient(
            endpoint=self.endpoint,
            index_name=self.index_name,
            credential=self.credential
        )
        self.index_client = SearchIndexClient(
            endpoint=self.endpoint,
            credential=self.credential
        )
        
        self._setup_blob_indexer()
    
    def _setup_blob_indexer(self):
        """Setup index, data source, skillset, and indexer for blob storage with OCR"""
        try:
            # Create or update index
            self._create_index()
            
            # Create or update data source
            self._create_datasource()
            
            # Create or update skillset with OCR
            self._create_skillset()
            
            # Create or update indexer
            self._create_indexer()
            
            print("Blob indexer with OCR skillset setup complete")
        except Exception as e:
            print(f"Error setting up blob indexer: {e}")
    
    def _create_index(self):
        """Create search index with fields for OCR content"""
        try:
            fields = [
                SimpleField(
                    name="metadata_storage_path",
                    type=SearchFieldDataType.String,
                    key=True,
                    filterable=True
                ),
                SearchableField(
                    name="content",
                    type=SearchFieldDataType.String,
                    analyzer_name="en.microsoft"
                ),
                SearchableField(
                    name="merged_content",
                    type=SearchFieldDataType.String,
                    analyzer_name="en.microsoft"
                ),
                SearchableField(
                    name="text",
                    type=SearchFieldDataType.Collection(SearchFieldDataType.String),
                    analyzer_name="en.microsoft"
                ),
                SearchableField(
                    name="layoutText",
                    type=SearchFieldDataType.Collection(SearchFieldDataType.String),
                    analyzer_name="en.microsoft"
                ),
                SearchableField(
                    name="metadata_storage_name",
                    type=SearchFieldDataType.String,
                    filterable=True,
                    sortable=True
                ),
                SimpleField(
                    name="metadata_storage_size",
                    type=SearchFieldDataType.Int64,
                    filterable=True,
                    sortable=True
                ),
                SimpleField(
                    name="metadata_storage_last_modified",
                    type=SearchFieldDataType.DateTimeOffset,
                    filterable=True,
                    sortable=True
                ),
            ]
            
            index = SearchIndex(name=self.index_name, fields=fields)
            self.index_client.create_or_update_index(index)
            print(f"Index '{self.index_name}' created/updated with OCR fields")
        except Exception as e:
            print(f"Error creating index: {e}")
    
    def _create_datasource(self):
        """Create blob storage data source"""
        try:
            container = SearchIndexerDataContainer(
                name=config.AZURE_STORAGE_CONTAINER_NAME
            )
            
            data_source = SearchIndexerDataSourceConnection(
                name=self.datasource_name,
                type="azureblob",
                connection_string=config.AZURE_STORAGE_CONNECTION_STRING,
                container=container
            )
            
            self.index_client.create_or_update_data_source_connection(data_source)
            print(f"Data source '{self.datasource_name}' created/updated")
        except Exception as e:
            print(f"Error creating data source: {e}")
    
    def _create_skillset(self):
        """Create skillset with OCR for processing images and scanned PDFs"""
        try:
            # OCR Skill - Extracts text from images
            ocr_skill = OcrSkill(
                name="ocr-skill",
                description="Extract text from images using OCR",
                context="/document/normalized_images/*",
                inputs=[
                    InputFieldMappingEntry(name="image", source="/document/normalized_images/*")
                ],
                outputs=[
                    OutputFieldMappingEntry(name="text", target_name="text")
                ],
                default_language_code="en"
            )
            
            # Merge Skill - Combines OCR text with document text
            merge_skill = MergeSkill(
                name="merge-skill",
                description="Merge extracted text with document content",
                context="/document",
                inputs=[
                    InputFieldMappingEntry(name="text", source="/document/content"),
                    InputFieldMappingEntry(name="itemsToInsert", source="/document/normalized_images/*/text")
                ],
                outputs=[
                    OutputFieldMappingEntry(name="mergedText", target_name="merged_content")
                ]
            )
            
            # Split Skill - Chunks large documents
            split_skill = SplitSkill(
                name="split-skill",
                description="Split documents into chunks",
                context="/document",
                text_split_mode=TextSplitMode.PAGES,
                maximum_page_length=4000,
                page_overlap_length=500,
                inputs=[
                    InputFieldMappingEntry(name="text", source="/document/merged_content")
                ],
                outputs=[
                    OutputFieldMappingEntry(name="textItems", target_name="pages")
                ]
            )
            
            skillset = SearchIndexerSkillset(
                name=self.skillset_name,
                description="Skillset for OCR and document processing",
                skills=[ocr_skill, merge_skill, split_skill]
            )
            
            self.index_client.create_or_update_skillset(skillset)
            print(f"Skillset '{self.skillset_name}' created/updated with OCR")
        except Exception as e:
            print(f"Error creating skillset: {e}")
    
    def _create_indexer(self):
        """Create indexer to automatically index blob storage with OCR skillset"""
        try:
            indexer = SearchIndexer(
                name=self.indexer_name,
                data_source_name=self.datasource_name,
                target_index_name=self.index_name,
                skillset_name=self.skillset_name,
                parameters={
                    "configuration": {
                        "dataToExtract": "contentAndMetadata",
                        "imageAction": "generateNormalizedImages"  # Enable image processing
                    }
                },
                field_mappings=[
                    FieldMapping(
                        source_field_name="metadata_storage_path",
                        target_field_name="metadata_storage_path"
                    )
                ],
                output_field_mappings=[
                    FieldMapping(
                        source_field_name="/document/merged_content",
                        target_field_name="merged_content"
                    ),
                    FieldMapping(
                        source_field_name="/document/normalized_images/*/text",
                        target_field_name="text"
                    )
                ]
            )
            
            self.index_client.create_or_update_indexer(indexer)
            print(f"Indexer '{self.indexer_name}' created/updated with OCR skillset")
        except Exception as e:
            print(f"Error creating indexer: {e}")
    
    async def run_indexer(self):
        """Manually trigger indexer to process new files"""
        try:
            self.index_client.run_indexer(self.indexer_name)
            print(f"Indexer '{self.indexer_name}' started")
            return True
        except Exception as e:
            print(f"Error running indexer: {e}")
            return False
    
    async def get_indexer_status(self):
        """Get indexer execution status"""
        try:
            status = self.index_client.get_indexer_status(self.indexer_name)
            return {
                "status": status.status,
                "last_result": status.last_result.status if status.last_result else None,
                "execution_history": [
                    {
                        "status": exec.status,
                        "error_message": exec.error_message,
                        "start_time": exec.start_time,
                        "end_time": exec.end_time
                    }
                    for exec in (status.execution_history[:5] if status.execution_history else [])
                ]
            }
        except Exception as e:
            print(f"Error getting indexer status: {e}")
            return None
    
    async def search(self, query: str, top: int = config.MAX_SEARCH_RESULTS) -> List[Dict]:
        """Search indexed documents including OCR content"""
        try:
            results = self.search_client.search(
                search_text=query,
                top=top,
                select=["merged_content", "content", "metadata_storage_name", "metadata_storage_path"]
            )
            
            return [
                {
                    "content": result.get("merged_content") or result.get("content", ""),
                    "filename": result.get("metadata_storage_name", ""),
                    "path": result.get("metadata_storage_path", ""),
                    "score": result.get("@search.score", 0)
                }
                for result in results
            ]
        except Exception as e:
            print(f"Search error: {e}")
            return []
    
    async def delete_all_documents(self):
        """Delete all documents from index"""
        try:
            results = self.search_client.search(search_text="*", select=["metadata_storage_path"])
            docs_to_delete = [{"metadata_storage_path": result["metadata_storage_path"]} for result in results]
            
            if docs_to_delete:
                self.search_client.delete_documents(documents=docs_to_delete)
            return True
        except Exception as e:
            print(f"Delete error: {e}")
            return False