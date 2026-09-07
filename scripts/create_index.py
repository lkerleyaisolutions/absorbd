r"""
Create (or update) the Absorbd Azure AI Search index.

The index holds chunked clinical-nutrition documents with embeddings, plus an
integrated Azure OpenAI vectorizer so that query text is auto-embedded at search
time. This is the foundation the Foundry IQ knowledge base sits on top of.

Idempotent: safe to re-run. Uses the search admin key (no `az login`).

Run:  venv\Scripts\python.exe scripts\create_index.py
"""

from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
    AzureOpenAIVectorizer,
    AzureOpenAIVectorizerParameters,
    SemanticConfiguration,
    SemanticSearch,
    SemanticPrioritizedFields,
    SemanticField,
)

from _common import (
    INDEX_NAME,
    AOAI_RESOURCE_URL,
    AOAI_API_KEY,
    EMBEDDING_DEPLOYMENT,
    EMBEDDING_DIMENSIONS,
    search_index_client,
)

VECTORIZER_NAME = "absorb-iq-vectorizer"
HNSW_CONFIG_NAME = "absorb-iq-hnsw"
VECTOR_PROFILE_NAME = "absorb-iq-vector-profile"
SEMANTIC_CONFIG_NAME = "absorb-iq-semantic"


def build_index() -> SearchIndex:
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SearchableField(name="title", type=SearchFieldDataType.String),
        # Citation + filtering metadata
        SimpleField(name="source", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="source_url", type=SearchFieldDataType.String),
        SimpleField(name="doc_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="nutrient", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="evidence_level", type=SearchFieldDataType.String, filterable=True),
        # Per-patient document isolation (None = general clinical literature)
        SimpleField(name="patient_id", type=SearchFieldDataType.String, filterable=True),
        # Embedding
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBEDDING_DIMENSIONS,
            vector_search_profile_name=VECTOR_PROFILE_NAME,
        ),
    ]

    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name=HNSW_CONFIG_NAME)],
        profiles=[
            VectorSearchProfile(
                name=VECTOR_PROFILE_NAME,
                algorithm_configuration_name=HNSW_CONFIG_NAME,
                vectorizer_name=VECTORIZER_NAME,
            )
        ],
        vectorizers=[
            AzureOpenAIVectorizer(
                vectorizer_name=VECTORIZER_NAME,
                parameters=AzureOpenAIVectorizerParameters(
                    resource_url=AOAI_RESOURCE_URL,
                    deployment_name=EMBEDDING_DEPLOYMENT,
                    model_name="text-embedding-3-small",
                    api_key=AOAI_API_KEY,
                ),
            )
        ],
    )

    semantic_search = SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name=SEMANTIC_CONFIG_NAME,
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"),
                    content_fields=[SemanticField(field_name="content")],
                ),
            )
        ]
    )

    return SearchIndex(
        name=INDEX_NAME,
        fields=fields,
        vector_search=vector_search,
        semantic_search=semantic_search,
    )


def main() -> None:
    client = search_index_client()
    index = build_index()
    result = client.create_or_update_index(index)
    print(f"Index '{result.name}' created/updated.")
    print(f"  Fields        : {len(result.fields)}")
    print(f"  Vector dims   : {EMBEDDING_DIMENSIONS} ({EMBEDDING_DEPLOYMENT})")
    print(f"  Vectorizer    : {VECTORIZER_NAME} -> {AOAI_RESOURCE_URL}")
    print(f"  Semantic cfg  : {SEMANTIC_CONFIG_NAME}")
    # Confirm it round-trips
    fetched = client.get_index(INDEX_NAME)
    print(f"\nVerified: index '{fetched.name}' exists with {len(fetched.fields)} fields.")


if __name__ == "__main__":
    main()
