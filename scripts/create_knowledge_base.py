r"""
Create (or update) the Foundry IQ knowledge base on top of absorb-iq-index.

Two objects:
  1. KnowledgeSource  -> points at the search index (what to retrieve from)
  2. KnowledgeBase    -> references the source + a gpt-4.1-mini "query planning"
                         model (how to reason about the query before retrieving)

The KnowledgeBase is what the agents query via the Foundry IQ MCP tool
`knowledge_base_retrieve`. This is the grounding layer behind every agent query.

Idempotent; uses the search admin key (no `az login`).

Run:  venv\Scripts\python.exe scripts\create_knowledge_base.py
"""

from azure.search.documents.indexes.models import (
    SearchIndexKnowledgeSource,
    SearchIndexKnowledgeSourceParameters,
    SearchIndexFieldReference,
    KnowledgeBase,
    KnowledgeSourceReference,
    KnowledgeBaseAzureOpenAIModel,
    AzureOpenAIVectorizerParameters,
)

# Fields returned with each retrieved reference. Without this, retrieval only
# returns id/content/title — and citations (source_url) would be lost.
SOURCE_DATA_FIELDS = ["title", "content", "source", "source_url", "doc_type", "nutrient", "evidence_level"]

from _common import (
    INDEX_NAME,
    KNOWLEDGE_SOURCE_NAME,
    KNOWLEDGE_BASE_NAME,
    AOAI_RESOURCE_URL,
    AOAI_API_KEY,
    MODEL_DEPLOYMENT,
    search_index_client,
)

SEMANTIC_CONFIG_NAME = "absorb-iq-semantic"


def build_knowledge_source() -> SearchIndexKnowledgeSource:
    return SearchIndexKnowledgeSource(
        name=KNOWLEDGE_SOURCE_NAME,
        description="Absorbd clinical-nutrition evidence (NIH ODS, ECCO, ACG) in absorb-iq-index.",
        search_index_parameters=SearchIndexKnowledgeSourceParameters(
            search_index_name=INDEX_NAME,
            semantic_configuration_name=SEMANTIC_CONFIG_NAME,
            source_data_fields=[SearchIndexFieldReference(name=f) for f in SOURCE_DATA_FIELDS],
        ),
    )


def build_knowledge_base() -> KnowledgeBase:
    return KnowledgeBase(
        name=KNOWLEDGE_BASE_NAME,
        description="Absorbd Foundry IQ knowledge base for grounded, cited IBD nutrition guidance.",
        knowledge_sources=[KnowledgeSourceReference(name=KNOWLEDGE_SOURCE_NAME)],
        models=[
            KnowledgeBaseAzureOpenAIModel(
                azure_open_ai_parameters=AzureOpenAIVectorizerParameters(
                    resource_url=AOAI_RESOURCE_URL,
                    deployment_name=MODEL_DEPLOYMENT,   # gpt-4.1-mini
                    model_name="gpt-4.1-mini",
                    api_key=AOAI_API_KEY,
                )
            )
        ],
    )


def main() -> None:
    client = search_index_client()

    ks = client.create_or_update_knowledge_source(knowledge_source=build_knowledge_source())
    print(f"KnowledgeSource '{ks.name}' -> index '{INDEX_NAME}' (created/updated).")

    kb = client.create_or_update_knowledge_base(knowledge_base=build_knowledge_base())
    print(f"KnowledgeBase   '{kb.name}' (created/updated).")
    print(f"  sources : {[s.name for s in kb.knowledge_sources]}")
    print(f"  model   : {MODEL_DEPLOYMENT} (query planning)")

    # Round-trip verify
    fetched = client.get_knowledge_base(KNOWLEDGE_BASE_NAME)
    print(f"\nVerified: knowledge base '{fetched.name}' exists.")
    print(f"MCP endpoint: {{AZURE_SEARCH_ENDPOINT}}/knowledgebases/{KNOWLEDGE_BASE_NAME}/mcp?api-version=2026-05-01-preview")


if __name__ == "__main__":
    main()
