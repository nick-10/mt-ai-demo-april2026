#!/usr/bin/env python3
"""
Montana DPHHS SNAP Benefits Agent — Google Agent Development Kit (ADK) Demo

This single file:
  1. Downloads a SNAP Policy Manual PDF to GCS and extracts text with Document AI.
  2. Creates a BigQuery dataset/table for SNAP benefit applications.
  3. Launches an interactive ADK agent powered by gemini-3-flash-preview
     with four tools: Vertex AI Search, policy lookup, submit application,
     and list applications.

Prerequisites:
  pip install google-adk google-cloud-bigquery google-cloud-storage \
              google-cloud-documentai google-cloud-discoveryengine
  gcloud auth application-default login

  Run prepare_and_import.py FIRST to set up Vertex AI Search data store.
"""

import asyncio
import os
import uuid
import requests as http_requests
from datetime import datetime, timezone

# ── Google Cloud clients ─────────────────────────────────────────────────────
from google.cloud import storage as gcs
from google.cloud import bigquery
from google.cloud import documentai_v1 as documentai
from google.cloud import discoveryengine_v1 as discoveryengine
from google.api_core.client_options import ClientOptions
from google.api_core.exceptions import AlreadyExists

# ── ADK imports ──────────────────────────────────────────────────────────────
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════
PROJECT_ID = "mt-nick-demo"
LOCATION = "us"                          # Document AI location
VERTEX_LOCATION = "us-central1"          # Vertex AI / model location
MODEL_ID = "gemini-3-flash-preview"

# ── Document AI / GCS ────────────────────────────────────────────────────────
GCS_BUCKET_NAME = f"{PROJECT_ID}-snap-policy"
GCS_BLOB_NAME = "snap-standards.pdf"
PDF_URL = "https://dphhs.mt.gov/assets/hcsd/snapmanual/SNAP001.pdf"
LOCAL_PDF_PATH = "snap_standards.pdf"
LOCAL_TEXT_PATH = "snap_policy_extracted.txt"

# ── BigQuery ─────────────────────────────────────────────────────────────────
BQ_DATASET = "dphhs_snap"
BQ_TABLE = "applications"
BQ_FULL_TABLE = f"{PROJECT_ID}.{BQ_DATASET}.{BQ_TABLE}"

# ── Vertex AI Search ────────────────────────────────────────────────────────
SEARCH_DATA_STORE_ID = "snap-benefits-datastore"
SEARCH_LOCATION = "global"
SEARCH_APP_ID = "snap-benefits-app"
SERVING_CONFIG = (
    f"projects/{PROJECT_ID}/locations/{SEARCH_LOCATION}"
    f"/collections/default_collection/engines/{SEARCH_APP_ID}"
    f"/servingConfigs/default_serving_config"
)

# ── ADK API Key ──────────────────────────────────────────────────────────────
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID

# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 1 — INFRASTRUCTURE SETUP
# ═══════════════════════════════════════════════════════════════════════════════

def download_pdf() -> bytes:
    """Download the SNAP Policy Manual PDF (Table of Standards)."""
    print("⬇️  Downloading SNAP Policy Manual PDF …")
    resp = http_requests.get(PDF_URL, timeout=60)
    resp.raise_for_status()
    pdf_bytes = resp.content
    with open(LOCAL_PDF_PATH, "wb") as f:
        f.write(pdf_bytes)
    print(f"   Saved local copy → {LOCAL_PDF_PATH} ({len(pdf_bytes):,} bytes)")
    return pdf_bytes


def upload_to_gcs(pdf_bytes: bytes) -> str:
    """Upload the PDF to GCS. Returns gs:// URI."""
    client = gcs.Client(project=PROJECT_ID)
    try:
        bucket = client.create_bucket(GCS_BUCKET_NAME, location="US")
        print(f"🪣  Created GCS bucket: gs://{GCS_BUCKET_NAME}")
    except Exception:
        bucket = client.bucket(GCS_BUCKET_NAME)
        print(f"🪣  Using existing GCS bucket: gs://{GCS_BUCKET_NAME}")

    blob = bucket.blob(GCS_BLOB_NAME)
    blob.upload_from_string(pdf_bytes, content_type="application/pdf")
    gcs_uri = f"gs://{GCS_BUCKET_NAME}/{GCS_BLOB_NAME}"
    print(f"   Uploaded → {gcs_uri}")
    return gcs_uri


def extract_text_with_docai(gcs_uri: str) -> str:
    """Use Document AI OCR to extract text from the SNAP policy PDF."""
    print("📄  Extracting text with Document AI …")

    client = documentai.DocumentProcessorServiceClient(
        client_options={"api_endpoint": f"{LOCATION}-documentai.googleapis.com"}
    )
    parent = client.common_location_path(PROJECT_ID, LOCATION)

    # Create an OCR processor (or reuse existing)
    processor_display_name = "snap-policy-ocr"
    try:
        processor = client.create_processor(
            parent=parent,
            processor=documentai.Processor(
                display_name=processor_display_name,
                type_="OCR_PROCESSOR",
            ),
        )
        print(f"   Created processor: {processor.name}")
    except AlreadyExists:
        processors = client.list_processors(parent=parent)
        processor = None
        for p in processors:
            if p.display_name == processor_display_name:
                processor = p
                break
        if processor is None:
            raise RuntimeError("Could not find existing OCR processor")
        print(f"   Using existing processor: {processor.name}")

    # Process the PDF
    with open(LOCAL_PDF_PATH, "rb") as f:
        pdf_content = f.read()

    result = client.process_document(
        request=documentai.ProcessRequest(
            name=processor.name,
            raw_document=documentai.RawDocument(
                content=pdf_content,
                mime_type="application/pdf",
            ),
        )
    )
    text = result.document.text

    # Save locally
    with open(LOCAL_TEXT_PATH, "w") as f:
        f.write(text)
    print(f"   Saved extracted text → {LOCAL_TEXT_PATH} ({len(text):,} chars)")
    return text


def setup_bigquery():
    """Create the BigQuery dataset and applications table."""
    print("🗄️  Setting up BigQuery …")
    client = bigquery.Client(project=PROJECT_ID)

    # Create dataset
    dataset_ref = bigquery.DatasetReference(PROJECT_ID, BQ_DATASET)
    dataset = bigquery.Dataset(dataset_ref)
    dataset.location = "US"
    try:
        client.create_dataset(dataset)
        print(f"   Created dataset: {BQ_DATASET}")
    except Exception:
        print(f"   Dataset already exists: {BQ_DATASET}")

    # Create applications table
    schema = [
        bigquery.SchemaField("application_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("applicant_name", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("household_size", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("monthly_income", "FLOAT", mode="REQUIRED"),
        bigquery.SchemaField("county", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("contact_phone", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
    ]
    table = bigquery.Table(f"{PROJECT_ID}.{BQ_DATASET}.{BQ_TABLE}", schema=schema)
    try:
        client.create_table(table)
        print(f"   Created table: {BQ_FULL_TABLE}")
    except Exception:
        print(f"   Table already exists: {BQ_FULL_TABLE}")


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 2 — AGENT TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

# Will be populated after Document AI extraction
POLICY_TEXT: str = ""


def search_snap_info(query: str) -> dict:
    """Search the Montana SNAP benefits knowledge base using Vertex AI Search.

    Use this tool to answer general questions about SNAP benefits, eligibility,
    income limits, how to apply, EBT cards, employment training, and more.

    Args:
        query: The user's question about SNAP benefits.
    """
    _client_options = ClientOptions(quota_project_id=PROJECT_ID)
    client = discoveryengine.SearchServiceClient(client_options=_client_options)

    request = discoveryengine.SearchRequest(
        serving_config=SERVING_CONFIG,
        query=query,
        page_size=5,
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
                max_extractive_answer_count=3,
            ),
        ),
    )

    response = client.search(request)

    # Build a clean result
    results = []
    for result in response.results:
        doc = result.document
        doc_data = {
            "title": doc.derived_struct_data.get("title", ""),
            "snippets": [],
        }
        # Extract snippets
        for snippet in doc.derived_struct_data.get("snippets", []):
            doc_data["snippets"].append(snippet.get("snippet", ""))
        # Extract extractive answers
        for answer in doc.derived_struct_data.get("extractive_answers", []):
            doc_data["snippets"].append(answer.get("content", ""))
        results.append(doc_data)

    # Get the AI summary if available
    summary = ""
    if response.summary and response.summary.summary_text:
        summary = response.summary.summary_text

    return {
        "summary": summary,
        "results": results,
        "total_results": response.total_size,
    }


def get_policy_details() -> dict:
    """Return the SNAP Policy Manual text extracted from the official PDF
    using Document AI. This contains the Table of Standards including
    Gross Monthly Income (GMI), Net Monthly Income (NMI), and Thrifty
    Food Plan benefit amounts by household size.

    Call this tool when the user asks about specific income standards,
    benefit amounts, or detailed policy numbers."""
    return {"policy_text": POLICY_TEXT}


def submit_application(
    applicant_name: str,
    household_size: int,
    monthly_income: float,
    county: str,
    contact_phone: str = "",
) -> dict:
    """Submit a new SNAP benefits application to BigQuery.

    Args:
        applicant_name: Full name of the applicant.
        household_size: Number of people in the household.
        monthly_income: Total monthly gross income of the household.
        county: Montana county where the applicant resides.
        contact_phone: Phone number for the applicant (optional).
    """
    client = bigquery.Client(project=PROJECT_ID)
    application_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    rows = [
        {
            "application_id": application_id,
            "applicant_name": applicant_name,
            "household_size": household_size,
            "monthly_income": monthly_income,
            "county": county,
            "contact_phone": contact_phone,
            "status": "submitted",
            "created_at": now,
        }
    ]
    errors = client.insert_rows_json(BQ_FULL_TABLE, rows)
    if errors:
        return {"status": "error", "errors": str(errors)}
    return {
        "status": "success",
        "application_id": application_id,
        "applicant_name": applicant_name,
        "household_size": household_size,
        "monthly_income": monthly_income,
        "county": county,
        "created_at": now,
        "application_status": "submitted",
    }


def get_all_applications() -> dict:
    """Retrieve all SNAP benefit applications from BigQuery.
    Call this tool when the user wants to see submitted applications."""
    client = bigquery.Client(project=PROJECT_ID)
    query = f"""
        SELECT application_id, applicant_name, household_size,
               monthly_income, county, contact_phone, status, created_at
        FROM `{BQ_FULL_TABLE}`
        ORDER BY created_at DESC
    """
    results = client.query(query).result()
    applications = [
        {
            "application_id": row.application_id,
            "applicant_name": row.applicant_name,
            "household_size": row.household_size,
            "monthly_income": row.monthly_income,
            "county": row.county,
            "contact_phone": row.contact_phone,
            "status": row.status,
            "created_at": row.created_at.isoformat(),
        }
        for row in results
    ]
    return {"applications": applications, "total_count": len(applications)}


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 3 — AGENT + INTERACTIVE LOOP
# ═══════════════════════════════════════════════════════════════════════════════

SYSTEM_INSTRUCTION = """You are a helpful and knowledgeable Montana DPHHS SNAP Benefits Assistant.

You help Montana residents understand SNAP (Supplemental Nutrition Assistance Program)
benefits and assist them with applications.

You have access to four tools:

1. **search_snap_info** — Search the SNAP benefits knowledge base (powered by Vertex AI Search)
   for information about eligibility, income limits, how to apply, EBT cards, employment
   training, TEFAP food assistance, and more. Use this for general SNAP questions.

2. **get_policy_details** — Get the official SNAP Policy Manual text (extracted via Document AI)
   containing the Table of Standards with exact income limits and benefit amounts by
   household size. Use this for specific numbers and policy details.

3. **submit_application** — Submit a new SNAP benefits application. Collect the applicant's
   name, household size, monthly income, county, and optionally phone number before submitting.

4. **get_all_applications** — List all submitted SNAP benefit applications.

Guidelines:
• Always use search_snap_info first when answering general SNAP questions.
• Use get_policy_details when the user needs exact income thresholds or benefit amounts.
• When submitting an application, confirm all details with the user before calling submit_application.
• Be empathetic and helpful — people applying for benefits may be in difficult situations.
• Always mention that the official way to apply is at apply.mt.gov or by calling 1-888-706-1535.
"""


def create_agent() -> Agent:
    """Build the ADK Agent with the four SNAP tools."""
    return Agent(
        name="snap_benefits_agent",
        model=MODEL_ID,
        description="A Montana DPHHS SNAP Benefits assistant that can search benefits info, "
                    "look up policy details, and manage benefit applications.",
        instruction=SYSTEM_INSTRUCTION,
        tools=[search_snap_info, get_policy_details, submit_application, get_all_applications],
    )


async def run_interactive():
    """Run the agent in an interactive terminal loop."""
    agent = create_agent()
    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name="snap_benefits_app",
        session_service=session_service,
    )

    user_id = "terminal_user"
    session_id = str(uuid.uuid4())

    await session_service.create_session(
        app_name="snap_benefits_app",
        user_id=user_id,
        session_id=session_id,
    )

    print("\n" + "=" * 60)
    print("🏔️  MONTANA SNAP BENEFITS AGENT  (powered by Google ADK)")
    print(f"   Model: {MODEL_ID}")
    print("   Type 'quit' or 'exit' to leave.")
    print("=" * 60)
    print("\nExample questions you can ask:")
    print("  • Am I eligible for SNAP benefits?")
    print("  • What are the income limits for a family of 4?")
    print("  • How do I apply for SNAP in Montana?")
    print("  • Can I use my EBT card at farmers markets?")
    print("  • I'd like to submit an application for benefits.")
    print("  • Show me all submitted applications.")
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋  Goodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("👋  Goodbye!")
            break

        user_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_input)],
        )

        final_text = ""
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=user_message,
        ):
            if event.content and event.content.parts:
                if event.author == "snap_benefits_agent":
                    for part in event.content.parts:
                        if part.text:
                            final_text += part.text

        if final_text:
            print(f"\n🏔️  Agent: {final_text}\n")
        else:
            print("\n🏔️  Agent: (no response)\n")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    global POLICY_TEXT

    print("=" * 60)
    print("  MONTANA DPHHS SNAP BENEFITS AGENT — SETUP")
    print("=" * 60)

    # Step 1: Download SNAP Policy Manual PDF
    pdf_bytes = download_pdf()

    # Step 2: Upload to GCS
    gcs_uri = upload_to_gcs(pdf_bytes)

    # Step 3: Extract text with Document AI
    POLICY_TEXT = extract_text_with_docai(gcs_uri)

    # Step 4: Setup BigQuery for applications
    setup_bigquery()

    print("\n✅  Setup complete!\n")

    # Step 5: Launch interactive agent
    asyncio.run(run_interactive())


if __name__ == "__main__":
    main()
