#!/usr/bin/env python3
"""
Vertex AI Search — SNAP Benefits Data Store Setup

This script creates a Vertex AI Search data store, imports the scraped
SNAP benefits data, and creates a search app. Run this ONCE before
launching the agent.

Prerequisites:
  pip install google-cloud-discoveryengine google-cloud-storage
  gcloud auth application-default login
"""

import json
import os

from google.api_core.exceptions import AlreadyExists
from google.cloud import discoveryengine_v1 as discoveryengine
from google.protobuf import struct_pb2

# ── Configuration ──────────────────────────────────────────────────────────────
PROJECT_ID = "mt-nick-demo"
LOCATION = "global"
DATA_STORE_ID = "snap-benefits-datastore"
SEARCH_APP_ID = "snap-benefits-app"

JSONL_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "all_snap_documents.jsonl"
)

BRANCH_PATH = (
    f"projects/{PROJECT_ID}/locations/{LOCATION}"
    f"/collections/default_collection/dataStores/{DATA_STORE_ID}"
    f"/branches/default_branch"
)


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 1 — Create Data Store
# ═══════════════════════════════════════════════════════════════════════════════

def create_data_store():
    """Create a Vertex AI Search data store for SNAP benefits content."""
    print("🗄️  Creating Vertex AI Search data store …")

    client = discoveryengine.DataStoreServiceClient()
    parent = f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection"

    data_store = discoveryengine.DataStore(
        display_name="Montana SNAP Benefits",
        industry_vertical=discoveryengine.IndustryVertical.GENERIC,
        content_config=discoveryengine.DataStore.ContentConfig.CONTENT_REQUIRED,
        solution_types=[discoveryengine.SolutionType.SOLUTION_TYPE_SEARCH],
    )

    try:
        operation = client.create_data_store(
            parent=parent,
            data_store=data_store,
            data_store_id=DATA_STORE_ID,
        )
        print("   Waiting for data store creation …")
        operation.result(timeout=120)
        print(f"   ✅ Created data store: {DATA_STORE_ID}")
    except AlreadyExists:
        print(f"   Data store already exists: {DATA_STORE_ID}")


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 2 — Create Documents directly via API
# ═══════════════════════════════════════════════════════════════════════════════

def create_documents():
    """Read scraped SNAP data and create documents directly in the data store."""
    print("📥  Creating documents in data store …")

    client = discoveryengine.DocumentServiceClient()

    with open(JSONL_FILE, "r", encoding="utf-8") as f:
        for line in f:
            doc_data = json.loads(line)
            doc_id = doc_data["id"]
            text_content = doc_data["text_content"]

            # Only keep simple fields in structData (no nested lists/dicts)
            clean_struct = {
                k: v for k, v in doc_data["structData"].items()
                if isinstance(v, (str, int, float, bool))
            }
            struct = struct_pb2.Struct()
            struct.update(clean_struct)

            # Build the document with inline text content
            doc = discoveryengine.Document(
                id=doc_id,
                struct_data=struct,
                content=discoveryengine.Document.Content(
                    mime_type="text/plain",
                    raw_bytes=text_content.encode("utf-8"),
                ),
            )

            try:
                client.create_document(
                    parent=BRANCH_PATH,
                    document=doc,
                    document_id=doc_id,
                )
                print(f"   ✅ Created: {doc_id} ({len(text_content):,} chars)")
            except AlreadyExists:
                doc.name = f"{BRANCH_PATH}/documents/{doc_id}"
                client.update_document(document=doc)
                print(f"   ✅ Updated: {doc_id} ({len(text_content):,} chars)")

    # Verify
    docs = client.list_documents(parent=BRANCH_PATH)
    count = sum(1 for _ in docs)
    print(f"   Total documents in store: {count}")


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 3 — Create Search App (Engine)
# ═══════════════════════════════════════════════════════════════════════════════

def create_search_app():
    """Create a Vertex AI Search app linked to the data store."""
    print("🔍  Creating search app …")

    client = discoveryengine.EngineServiceClient()
    parent = f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection"

    engine = discoveryengine.Engine(
        display_name="SNAP Benefits Search",
        solution_type=discoveryengine.SolutionType.SOLUTION_TYPE_SEARCH,
        search_engine_config=discoveryengine.Engine.SearchEngineConfig(
            search_tier=discoveryengine.SearchTier.SEARCH_TIER_ENTERPRISE,
            search_add_ons=[discoveryengine.SearchAddOn.SEARCH_ADD_ON_LLM],
        ),
        data_store_ids=[DATA_STORE_ID],
    )

    try:
        operation = client.create_engine(
            parent=parent,
            engine=engine,
            engine_id=SEARCH_APP_ID,
        )
        print("   Waiting for search app creation …")
        operation.result(timeout=120)
        print(f"   ✅ Created search app: {SEARCH_APP_ID}")
    except AlreadyExists:
        print(f"   Search app already exists: {SEARCH_APP_ID}")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  VERTEX AI SEARCH — SNAP BENEFITS SETUP")
    print("=" * 60)

    # Step 1: Create data store
    create_data_store()

    # Step 2: Create documents directly
    create_documents()

    # Step 3: Create search app
    create_search_app()

    print("\n" + "=" * 60)
    print("  ✅ SETUP COMPLETE!")
    print("=" * 60)
    print(f"\n  Data Store ID:  {DATA_STORE_ID}")
    print(f"  Search App ID:  {SEARCH_APP_ID}")
    print(f"  Project:        {PROJECT_ID}")
    print(f"\n  You can now run dphhs_snap_agent.py!")


if __name__ == "__main__":
    main()
