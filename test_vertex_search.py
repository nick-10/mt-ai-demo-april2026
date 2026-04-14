#!/usr/bin/env python3
"""
Vertex AI Search — 10 Example SNAP Benefit Queries

Demonstrates how to query the SNAP benefits knowledge base using
the Discovery Engine Search API. Each query shows the code pattern
and the search results.
"""

from google.api_core.client_options import ClientOptions
from google.cloud import discoveryengine_v1 as discoveryengine

# ── Configuration ──────────────────────────────────────────────────────────────
PROJECT_ID = "mt-nick-demo"
SEARCH_APP_ID = "snap-benefits-app"
SERVING_CONFIG = (
    f"projects/{PROJECT_ID}/locations/global"
    f"/collections/default_collection/engines/{SEARCH_APP_ID}"
    f"/servingConfigs/default_serving_config"
)

# ── Create the search client ──────────────────────────────────────────────────
client_options = ClientOptions(quota_project_id=PROJECT_ID)
client = discoveryengine.SearchServiceClient(client_options=client_options)


def search_snap(query: str, page_size: int = 3) -> dict:
    """Search the SNAP benefits data store with Vertex AI Search.

    Args:
        query: Natural language question about SNAP benefits.
        page_size: Number of results to return (default 3).

    Returns:
        dict with summary, results list, and total count.
    """
    request = discoveryengine.SearchRequest(
        serving_config=SERVING_CONFIG,
        query=query,
        page_size=page_size,
        query_expansion_spec=discoveryengine.SearchRequest.QueryExpansionSpec(
            condition=discoveryengine.SearchRequest.QueryExpansionSpec.Condition.AUTO,
        ),
        content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
            snippet_spec=discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
                return_snippet=True,
            ),
            summary_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec(
                summary_result_count=3,
                include_citations=True,
            ),
            extractive_content_spec=discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                max_extractive_answer_count=1,
            ),
        ),
    )

    response = client.search(request)

    # Parse results into a clean dict
    results = []
    for result in response.results:
        doc = result.document
        doc_data = {"title": doc.derived_struct_data.get("title", "")}
        snippets = doc.derived_struct_data.get("snippets", [])
        if snippets:
            doc_data["snippet"] = snippets[0].get("snippet", "")
        answers = doc.derived_struct_data.get("extractive_answers", [])
        if answers:
            doc_data["answer"] = answers[0].get("content", "")
        results.append(doc_data)

    summary = ""
    if response.summary and response.summary.summary_text:
        summary = response.summary.summary_text

    return {"summary": summary, "results": results, "total": response.total_size}


# ══════════════════════════════════════════════════════════════════════════════
#  10 EXAMPLE QUERIES
# ══════════════════════════════════════════════════════════════════════════════

queries = [
    "Am I eligible for SNAP benefits?",
    "What are the income limits for a household of 4?",
    "How do I apply for SNAP in Montana?",
    "What is expedited services for SNAP?",
    "Can I use my EBT card at farmers markets?",
    "What is the SNAP Employment and Training program?",
    "What are the resource limits for SNAP?",
    "What is TEFAP and how does it work?",
    "How do I report SNAP fraud?",
    "What deductions are allowed for SNAP?",
]

if __name__ == "__main__":
    for i, query in enumerate(queries, 1):
        print(f"{'═' * 70}")
        print(f"  Query {i}: \"{query}\"")
        print(f"{'─' * 70}")
        print(f"  Code:  search_snap(\"{query}\")")
        print(f"{'─' * 70}")

        result = search_snap(query)

        print(f"  Total results: {result['total']}")
        if result["summary"]:
            print(f"  AI Summary: {result['summary'][:300]}")
        print()

        for j, doc in enumerate(result["results"], 1):
            print(f"  [{j}] {doc['title']}")
            if "snippet" in doc:
                # Strip HTML bold tags for clean display
                snippet = doc["snippet"].replace("<b>", "").replace("</b>", "")
                snippet = snippet.replace("&nbsp;...", "…").replace("&amp;", "&")
                print(f"      Snippet: {snippet[:200]}")
            if "answer" in doc:
                answer = doc["answer"].replace("<b>", "").replace("</b>", "")
                answer = answer.replace("&#39;", "'").replace("&amp;", "&")
                print(f"      Answer:  {answer[:200]}")
            print()
        print()
