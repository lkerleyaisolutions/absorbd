r"""
Test agentic retrieval THROUGH the Foundry IQ knowledge base (not raw index search).

This exercises the same path the agents will use via the MCP tool
`knowledge_base_retrieve`: the knowledge base uses gpt-4.1-mini to plan the query,
retrieves from absorb-iq-index, and returns a grounded answer + references.

Uses the search admin key (no `az login`).

Run:  venv\Scripts\python.exe scripts\test_knowledge_base.py
"""

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.knowledgebases import KnowledgeBaseRetrievalClient
from azure.search.documents.knowledgebases.models import (
    KnowledgeBaseRetrievalRequest,
    KnowledgeRetrievalSemanticIntent,
    SearchIndexKnowledgeSourceParams,
)

from _common import (
    SEARCH_ENDPOINT,
    SEARCH_KEY,
    KNOWLEDGE_BASE_NAME,
    KNOWLEDGE_SOURCE_NAME,
)

QUERY = (
    "A patient with ulcerative colitis on long-term prednisone has fat malabsorption. "
    "What does this mean for their vitamin D, and what should be considered?"
)


def main() -> None:
    client = KnowledgeBaseRetrievalClient(
        endpoint=SEARCH_ENDPOINT,
        credential=AzureKeyCredential(SEARCH_KEY),
        knowledge_base_name=KNOWLEDGE_BASE_NAME,
    )

    request = KnowledgeBaseRetrievalRequest(
        intents=[KnowledgeRetrievalSemanticIntent(search=QUERY)],
        include_activity=True,
        knowledge_source_params=[
            SearchIndexKnowledgeSourceParams(
                knowledge_source_name=KNOWLEDGE_SOURCE_NAME,
                include_references=True,
                include_reference_source_data=True,
            )
        ],
    )

    print(f"Query: {QUERY}\n" + "=" * 70)
    resp = client.retrieve(request)

    # Grounded synthesized answer
    print("\nGROUNDED RESPONSE:")
    for msg in resp.response or []:
        for c in getattr(msg, "content", []) or []:
            print(getattr(c, "text", c))

    # Citations
    refs = resp.references or []
    print(f"\nREFERENCES ({len(refs)}):")
    for i, ref in enumerate(refs[:6], 1):
        data = getattr(ref, "source_data", None) or {}
        title = data.get("title") if isinstance(data, dict) else None
        url = data.get("source_url") if isinstance(data, dict) else None
        print(f"  [{i}] {title or getattr(ref,'doc_key','?')}")
        if url:
            print(f"      {url}")

    print("\n" + "=" * 70)
    print("KNOWLEDGE BASE RETRIEVAL:", "PASSED" if (resp.response or refs) else "NO RESULT")


if __name__ == "__main__":
    main()
