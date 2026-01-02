------------------------------------------------------Backend .env--------------------------------------------

# Azure Blob Storage
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=your-storage-account;AccountKey=your-key;EndpointSuffix=core.windows.net
AZURE_STORAGE_CONTAINER_NAME=property-documents

# Azure AI Search
AZURE_SEARCH_ENDPOINT=https://yottaaisearch.search.windows.net
AZURE_SEARCH_KEY=your-search-key
AZURE_SEARCH_INDEX_NAME=property-docs
AZURE_SEARCH_DATASOURCE_NAME=property-blob-datasource
AZURE_SEARCH_INDEXER_NAME=property-blob-indexer

# Azure OpenAI
AZURE_OPENAI_API_KEY=your-openai-api-key
AZURE_OPENAI_ENDPOINT=https://your-openai-endpoint.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=yotta-gpt-4o
AZURE_OPENAI_API_VERSION=2024-02-15-preview

# API Authentication
CHATBOT_API_KEY=your-secret-api-key-here

----------------------------------------------------Frontend .env-----------------------------------------------------

# Backend API Configuration
REACT_APP_API_URL=http://localhost:8000/api

# API Authentication (must match backend CHATBOT_API_KEY)
REACT_APP_CHATBOT_API_KEY=your-secret-api-key-here

                                   ==============Production Frontend .env==============
# Backend API Configuration
REACT_APP_API_URL=https://your-production-server.com/api

# API Authentication
REACT_APP_CHATBOT_API_KEY=your-secret-api-key-here

*************************************************RUN FRONTEND***************************************************
cd frontend
npm install
npm start