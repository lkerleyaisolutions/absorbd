"""Shared config + clients for Absorbd build scripts.

Auth: uses the Azure AI Search ADMIN KEY (from .env) for all index/knowledge-base
operations, so these scripts run WITHOUT `az login`. Entra auth is only needed later
for the agent runtime's Foundry IQ MCP connection.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# --- Search ---
SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
SEARCH_KEY = os.environ["AZURE_SEARCH_KEY"]
INDEX_NAME = "absorb-iq-index"
KNOWLEDGE_BASE_NAME = os.environ.get("KNOWLEDGE_BASE_NAME", "absorb-iq-kb")
KNOWLEDGE_SOURCE_NAME = "absorb-iq-index-source"

# --- Azure OpenAI (for the integrated vectorizer + query planning) ---
# The vectorizer wants the bare resource URL, WITHOUT the "/openai/v1" suffix.
AOAI_ENDPOINT_V1 = os.environ["AZURE_OPENAI_ENDPOINT"]            # .../openai/v1
AOAI_RESOURCE_URL = AOAI_ENDPOINT_V1.split("/openai/")[0]        # bare resource url
AOAI_API_KEY = os.environ["AZURE_AI_PROJECT_API_KEY"]
EMBEDDING_DEPLOYMENT = os.environ["EMBEDDING_DEPLOYMENT"]         # text-embedding-3-small
MODEL_DEPLOYMENT = os.environ["MODEL_DEPLOYMENT"]                 # gpt-4.1-mini

EMBEDDING_DIMENSIONS = 1536  # text-embedding-3-small


def search_index_client():
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexClient

    return SearchIndexClient(
        endpoint=SEARCH_ENDPOINT,
        credential=AzureKeyCredential(SEARCH_KEY),
    )


def search_client():
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient

    return SearchClient(
        endpoint=SEARCH_ENDPOINT,
        index_name=INDEX_NAME,
        credential=AzureKeyCredential(SEARCH_KEY),
    )
