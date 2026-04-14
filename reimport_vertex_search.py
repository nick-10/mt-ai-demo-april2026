#!/usr/bin/env python3
"""
Vertex AI Search — Clean Reimport for Montana SNAP Benefits

This script:
1. Purges all existing documents from the data store
2. Converts all scraped content + policy PDF text to plain .txt files
3. Uploads text files to GCS
4. Runs importDocuments from GCS (the most reliable import method)
5. Verifies the import succeeded

Usage:
    python3 reimport_vertex_search.py
"""

import json
import os
import time

from google.api_core.client_options import ClientOptions
from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import discoveryengine_v1 as discoveryengine
from google.cloud import storage

# ── Configuration ──────────────────────────────────────────────────────────────
PROJECT_ID = "mt-nick-demo"
LOCATION = "global"
DATA_STORE_ID = "snap-benefits-datastore"
SEARCH_APP_ID = "snap-benefits-app"
GCS_BUCKET = "mt-nick-demo-snap-data"
GCS_TEXT_PREFIX = "text_documents"  # folder in GCS for clean text files

CLIENT_OPTIONS = ClientOptions(quota_project_id=PROJECT_ID)

PARENT = (
    f"projects/{PROJECT_ID}/locations/{LOCATION}"
    f"/collections/default_collection"
)
BRANCH_PATH = f"{PARENT}/dataStores/{DATA_STORE_ID}/branches/default_branch"

JSONL_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "dphhs_snap_scrape", "data", "all_snap_documents.jsonl",
)
POLICY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "snap_policy_extracted.txt",
)
LOCAL_TEXT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "dphhs_snap_scrape", "data", "text_for_import",
)


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 1 — Purge existing documents
# ═══════════════════════════════════════════════════════════════════════════════

def purge_documents():
    """Delete all existing documents from the data store."""
    print("\n🗑️  STEP 1: Purging existing documents …")
    client = discoveryengine.DocumentServiceClient(client_options=CLIENT_OPTIONS)

    count = 0
    for doc in client.list_documents(parent=BRANCH_PATH):
        try:
            client.delete_document(name=doc.name)
            count += 1
            print(f"   Deleted: {doc.id}")
        except NotFound:
            print(f"   Already gone: {doc.id}")

    if count == 0:
        print("   No documents to delete.")
    else:
        print(f"   ✅ Purged {count} documents")


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 2 — Convert all content to clean text files
# ═══════════════════════════════════════════════════════════════════════════════

def convert_to_text_files():
    """Convert scraped JSONL data and policy text into clean .txt files."""
    print("\n📄  STEP 2: Converting content to plain text files …")

    os.makedirs(LOCAL_TEXT_DIR, exist_ok=True)

    files_created = []

    # --- Process scraped web pages from JSONL ---
    with open(JSONL_FILE, "r", encoding="utf-8") as f:
        for line in f:
            doc_data = json.loads(line)
            doc_id = doc_data["id"]
            title = doc_data["structData"].get("title", doc_id)
            url = doc_data["structData"].get("url", "")
            source = doc_data["structData"].get("source", "")
            text_content = doc_data["text_content"]

            # Build a clean text document with metadata header
            clean_text = f"""Title: {title}
Source: {source}
URL: {url}
Category: Montana SNAP Benefits

---

{text_content}
"""
            filename = f"{doc_id}.txt"
            filepath = os.path.join(LOCAL_TEXT_DIR, filename)
            with open(filepath, "w", encoding="utf-8") as out:
                out.write(clean_text)
            files_created.append(filename)
            print(f"   Created: {filename} ({len(clean_text):,} chars)")

    # --- Process the extracted SNAP policy PDF text ---
    if os.path.exists(POLICY_FILE):
        with open(POLICY_FILE, "r", encoding="utf-8") as f:
            policy_text = f.read()

        clean_policy = f"""Title: SNAP Policy Manual - Gross and Net Income Standards / Thrifty Food Plan (SNAP 001)
Source: Montana Department of Public Health and Human Services
URL: https://dphhs.mt.gov/HCSD/snapmanual
Category: Montana SNAP Benefits - Policy Manual

---

{policy_text}
"""
        filename = "snap_policy_001_income_standards.txt"
        filepath = os.path.join(LOCAL_TEXT_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as out:
            out.write(clean_policy)
        files_created.append(filename)
        print(f"   Created: {filename} ({len(clean_policy):,} chars)")

    # --- Also upload the PDF itself if available ---
    pdf_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snap_standards.pdf")
    if os.path.exists(pdf_file):
        files_created.append("snap_standards.pdf")
        print(f"   Found PDF: snap_standards.pdf (will upload directly)")

    print(f"\n   ✅ Created {len(files_created)} files for import")
    return files_created


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 3 — Upload text files to GCS
# ═══════════════════════════════════════════════════════════════════════════════

def upload_to_gcs(files_created):
    """Upload all text files to GCS bucket under a clean prefix."""
    print(f"\n☁️   STEP 3: Uploading to gs://{GCS_BUCKET}/{GCS_TEXT_PREFIX}/ …")

    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(GCS_BUCKET)

    # Clear existing files in the prefix
    existing = list(bucket.list_blobs(prefix=f"{GCS_TEXT_PREFIX}/"))
    if existing:
        print(f"   Cleaning {len(existing)} existing files in prefix …")
        for blob in existing:
            blob.delete()

    uploaded = []
    for filename in files_created:
        if filename == "snap_standards.pdf":
            local_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "snap_standards.pdf"
            )
        else:
            local_path = os.path.join(LOCAL_TEXT_DIR, filename)

        gcs_path = f"{GCS_TEXT_PREFIX}/{filename}"
        blob = bucket.blob(gcs_path)
        blob.upload_from_filename(local_path)
        uploaded.append(f"gs://{GCS_BUCKET}/{gcs_path}")
        print(f"   Uploaded: {gcs_path}")

    print(f"\n   ✅ Uploaded {len(uploaded)} files to GCS")
    return uploaded


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 4 — Import documents from GCS using importDocuments API
# ═══════════════════════════════════════════════════════════════════════════════

def import_documents_from_gcs(gcs_uris):
    """Import documents into Vertex AI Search from GCS using importDocuments."""
    print(f"\n📥  STEP 4: Importing documents from GCS into Vertex AI Search …")

    client = discoveryengine.DocumentServiceClient(client_options=CLIENT_OPTIONS)

    # Use GCS source pointing to all uploaded files
    gcs_source = discoveryengine.GcsSource(
        input_uris=[f"gs://{GCS_BUCKET}/{GCS_TEXT_PREFIX}/*"],
        data_schema="content",
    )

    request = discoveryengine.ImportDocumentsRequest(
        parent=BRANCH_PATH,
        gcs_source=gcs_source,
        reconciliation_mode=discoveryengine.ImportDocumentsRequest.ReconciliationMode.FULL,
    )

    print(f"   GCS source: gs://{GCS_BUCKET}/{GCS_TEXT_PREFIX}/*")
    print(f"   Data schema: content (unstructured)")
    print(f"   Reconciliation: FULL (replace all)")
    print(f"   Starting import operation …")

    operation = client.import_documents(request=request)

    # Poll for completion
    print("   Waiting for import to complete …", end="", flush=True)
    start_time = time.time()
    while not operation.done():
        time.sleep(5)
        elapsed = int(time.time() - start_time)
        print(f"\r   Waiting for import to complete … ({elapsed}s)", end="", flush=True)

    elapsed = int(time.time() - start_time)
    print(f"\r   Import completed in {elapsed}s                    ")

    # Check result
    result = operation.result()
    print(f"\n   Import Result:")
    if hasattr(result, 'error_samples') and result.error_samples:
        print(f"   ⚠️  Error samples ({len(result.error_samples)}):")
        for err in result.error_samples:
            print(f"      - {err.message}")
    else:
        print(f"   ✅ No errors!")

    if hasattr(result, 'error_config') and result.error_config:
        print(f"   Error config: {result.error_config}")

    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 5 — Verify imported documents
# ═══════════════════════════════════════════════════════════════════════════════

def verify_documents():
    """List all documents in the data store to verify import."""
    print(f"\n🔍  STEP 5: Verifying imported documents …")
    client = discoveryengine.DocumentServiceClient(client_options=CLIENT_OPTIONS)

    count = 0
    for doc in client.list_documents(parent=BRANCH_PATH):
        count += 1
        content_info = ""
        if doc.content:
            if doc.content.uri:
                content_info = f"URI={doc.content.uri}"
            elif doc.content.raw_bytes:
                content_info = f"raw_bytes={len(doc.content.raw_bytes)} bytes"
            content_info += f", mime={doc.content.mime_type}"
        print(f"   {count}. {doc.id} [{content_info}]")

    print(f"\n   ✅ Total documents in data store: {count}")
    return count


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 65)
    print("  VERTEX AI SEARCH — CLEAN REIMPORT (TEXT-BASED)")
    print("=" * 65)
    print(f"  Project:     {PROJECT_ID}")
    print(f"  Data Store:  {DATA_STORE_ID}")
    print(f"  Engine:      {SEARCH_APP_ID}")
    print(f"  GCS Bucket:  {GCS_BUCKET}/{GCS_TEXT_PREFIX}/")
    print("=" * 65)

    # Step 1: Purge existing documents
    purge_documents()

    # Step 2: Convert to text files
    files_created = convert_to_text_files()

    # Step 3: Upload to GCS
    gcs_uris = upload_to_gcs(files_created)

    # Step 4: Import from GCS
    import_result = import_documents_from_gcs(gcs_uris)

    # Step 5: Verify
    doc_count = verify_documents()

    print("\n" + "=" * 65)
    if doc_count > 0:
        print("  ✅ REIMPORT COMPLETE!")
    else:
        print("  ⚠️  REIMPORT FINISHED BUT NO DOCUMENTS FOUND")
        print("      Documents may take a moment to appear.")
    print("=" * 65)
    print(f"\n  Data Store:  {DATA_STORE_ID}")
    print(f"  Engine:      {SEARCH_APP_ID}")
    print(f"  Documents:   {doc_count}")
    print(f"\n  The search index will update automatically.")
    print(f"  You can test with: python3 test_vertex_search.py")


if __name__ == "__main__":
    main()
