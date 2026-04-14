#!/usr/bin/env python3
"""
A2A-Compatible Server for the Montana SNAP Benefits Agent

Deploys the SNAP Benefits ADK agent as a Cloud Run service with:
  - A2A (Agent-to-Agent) protocol support for Gemini Enterprise
  - Agent Card discovery at /.well-known/agent.json
  - JSON-RPC 2.0 endpoint for tasks/send and tasks/get
  - Health check at /health

Usage:
  python server.py                                    # Local dev (port 8080)
  gcloud run deploy snap-benefits-agent --source .    # Cloud Run
"""

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

# Import agent setup and tools from the main agent file
import dphhs_snap_agent as snap
from google.genai import types

# ═══════════════════════════════════════════════════════════════════════════════
#  STATE
# ═══════════════════════════════════════════════════════════════════════════════

# Task storage: task_id → full task data (history, last response, etc.)
tasks_store: dict[str, dict] = {}

# Map A2A task_id → ADK session_id for multi-turn context
task_sessions: dict[str, str] = {}

# ADK runner + session service (created at startup)
runner = None
session_service = None
setup_complete = False


# ═══════════════════════════════════════════════════════════════════════════════
#  STARTUP — Phase 1 Infrastructure Setup (runs in background)
# ═══════════════════════════════════════════════════════════════════════════════

async def setup_agent():
    """Run Phase 1 infrastructure setup in the background."""
    global runner, session_service, setup_complete

    print("=" * 60)
    print("  SNAP BENEFITS AGENT — BACKGROUND SETUP")
    print("=" * 60)

    # Phase 1: Download PDF → GCS → Document AI OCR → BigQuery
    # Run blocking I/O in a thread pool so we don't block the event loop
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_phase1)

    # Phase 2+3: Create the ADK agent and runner
    agent = snap.create_agent()
    session_service = snap.InMemorySessionService()
    runner = snap.Runner(
        agent=agent,
        app_name="snap_benefits_app",
        session_service=session_service,
    )

    setup_complete = True
    print("\n✅  Setup complete! Agent is live.\n")


def _run_phase1():
    """Phase 1 blocking I/O (runs in thread pool)."""
    pdf_bytes = snap.download_pdf()
    gcs_uri = snap.upload_to_gcs(pdf_bytes)
    snap.POLICY_TEXT = snap.extract_text_with_docai(gcs_uri)
    snap.setup_bigquery()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start server immediately, run setup in background."""
    print("🚀  Server starting — setup will run in background …")
    asyncio.create_task(setup_agent())
    yield
    print("👋  Server shutting down.")


app = FastAPI(title="Montana SNAP Benefits Agent", lifespan=lifespan)


# ═══════════════════════════════════════════════════════════════════════════════
#  AGENT CARD — A2A Discovery
# ═══════════════════════════════════════════════════════════════════════════════

AGENT_CARD = {
    "name": "Montana SNAP Benefits Agent",
    "description": (
        "Helps Montana residents understand SNAP (Supplemental Nutrition "
        "Assistance Program) benefits, check eligibility, look up income "
        "limits and policy details, and submit benefit applications."
    ),
    "url": os.environ.get("SERVICE_URL", "http://localhost:8080"),
    "version": "1.0.0",
    "protocolVersion": "0.2.1",
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "provider": {
        "organization": "Montana DPHHS",
        "url": "https://dphhs.mt.gov",
    },
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
    },
    "skills": [
        {
            "id": "snap-search",
            "name": "SNAP Benefits Search",
            "description": (
                "Search the SNAP benefits knowledge base for eligibility, "
                "income limits, how to apply, EBT cards, and more."
            ),
            "tags": ["search", "snap", "eligibility"],
            "examples": [
                "Am I eligible for SNAP benefits?",
                "How do I apply for SNAP in Montana?",
            ],
        },
        {
            "id": "policy-lookup",
            "name": "Policy Details Lookup",
            "description": (
                "Get official SNAP policy manual text with exact income "
                "thresholds and benefit amounts by household size."
            ),
            "tags": ["policy", "income-limits", "benefits"],
            "examples": [
                "What are the income limits for a family of 4?",
                "How much SNAP benefit would I get?",
            ],
        },
        {
            "id": "submit-application",
            "name": "Submit SNAP Application",
            "description": (
                "Submit a new SNAP benefits application with applicant "
                "details to BigQuery."
            ),
            "tags": ["application", "submit", "apply"],
            "examples": [
                "I want to submit a SNAP application",
                "Help me apply for benefits",
            ],
        },
        {
            "id": "list-applications",
            "name": "List Applications",
            "description": "Retrieve all submitted SNAP benefit applications.",
            "tags": ["applications", "list", "status"],
            "examples": [
                "Show me all submitted applications",
                "List all SNAP applications",
            ],
        },
    ],
}


@app.get("/.well-known/agent.json")
async def agent_card():
    """Serve the A2A Agent Card for discovery by Gemini Enterprise."""
    return JSONResponse(content=AGENT_CARD)


# ═══════════════════════════════════════════════════════════════════════════════
#  HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    """Health check endpoint for Cloud Run."""
    return {"status": "healthy", "agent": "snap_benefits_agent"}


# ═══════════════════════════════════════════════════════════════════════════════
#  CORE — Run the ADK Agent
# ═══════════════════════════════════════════════════════════════════════════════

async def run_agent(task_id: str, user_text: str) -> str:
    """Send a message to the ADK agent and return the response text.

    Uses task_id → session_id mapping to maintain multi-turn context.
    """
    # Get or create an ADK session for this A2A task
    if task_id not in task_sessions:
        session_id = str(uuid.uuid4())
        task_sessions[task_id] = session_id
        await session_service.create_session(
            app_name="snap_benefits_app",
            user_id="a2a_user",
            session_id=session_id,
        )

    session_id = task_sessions[task_id]

    # Build the user message for ADK
    user_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=user_text)],
    )

    # Run the agent and collect the response
    response_text = ""
    async for event in runner.run_async(
        user_id="a2a_user",
        session_id=session_id,
        new_message=user_message,
    ):
        if event.content and event.content.parts:
            if event.author == "snap_benefits_agent":
                for part in event.content.parts:
                    if part.text:
                        response_text += part.text

    return response_text or "(no response)"


# ═══════════════════════════════════════════════════════════════════════════════
#  A2A JSON-RPC 2.0 ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════════

def build_a2a_task(task_id: str, context_id: str, state: str, agent_text: str, history: list) -> dict:
    """Build an A2A Task response object (v0.2.1 format with all required fields)."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "kind": "task",
        "id": task_id,
        "contextId": context_id,
        "status": {
            "state": state,
            "timestamp": now,
            "message": {
                "kind": "message",
                "role": "agent",
                "messageId": str(uuid.uuid4()),
                "parts": [{"kind": "text", "text": agent_text}],
            },
        },
        "artifacts": [
            {
                "artifactId": str(uuid.uuid4()),
                "parts": [{"kind": "text", "text": agent_text}],
            }
        ],
        "history": history,
        "metadata": {},
    }


@app.post("/")
async def a2a_endpoint(request: Request):
    """Handle A2A JSON-RPC 2.0 requests (tasks/send, tasks/get, message/send)."""
    body = await request.json()

    # Log the incoming request for debugging
    import json as _json
    print(f"📨  A2A Request: method={body.get('method')} id={body.get('id')}")
    print(f"    params keys: {list(body.get('params', {}).keys())}")
    print(f"    full body: {_json.dumps(body)[:500]}")

    jsonrpc = body.get("jsonrpc", "2.0")
    req_id = body.get("id", 1)
    method = body.get("method", "")
    params = body.get("params", {})

    # Wait for setup to complete before processing requests
    if not setup_complete:
        return JSONResponse(content={
            "jsonrpc": jsonrpc,
            "id": req_id,
            "error": {"code": -32000, "message": "Agent is still starting up. Please try again in a moment."},
        })

    # ── message/send (A2A v0.2.1) or tasks/send (legacy) ─────────────────
    if method in ("message/send", "tasks/send"):
        message = params.get("message", {})

        # For message/send: use the JSON-RPC id as task_id
        # For tasks/send:   use params.id
        task_id = params.get("id", str(req_id))

        # Extract text — handle both "kind" (v0.2.1) and "type" (legacy)
        user_text = ""
        for part in message.get("parts", []):
            part_kind = part.get("kind", part.get("type", ""))
            if part_kind == "text":
                user_text += part.get("text", "")

        if not user_text:
            return JSONResponse(content={
                "jsonrpc": jsonrpc,
                "id": req_id,
                "error": {"code": -32602, "message": "No text content in message"},
            })

        # Initialize task history if this is a new task
        if task_id not in tasks_store:
            tasks_store[task_id] = {"history": []}

        # Add user message to A2A history
        tasks_store[task_id]["history"].append({
            "role": "user",
            "parts": [{"kind": "text", "text": user_text}],
        })

        # Run the ADK agent (multi-turn context via session_id)
        agent_response = await run_agent(task_id, user_text)

        # Add agent response to A2A history
        tasks_store[task_id]["history"].append({
            "role": "agent",
            "parts": [{"kind": "text", "text": agent_response}],
        })

        # Build the task result (use session_id as contextId for multi-turn)
        context_id = task_sessions.get(task_id, task_id)
        task = build_a2a_task(
            task_id=task_id,
            context_id=context_id,
            state="completed",
            agent_text=agent_response,
            history=tasks_store[task_id]["history"],
        )
        tasks_store[task_id]["task"] = task

        print(f"📤  A2A Response: task_id={task_id} state=completed text_len={len(agent_response)}")

        return JSONResponse(content={
            "jsonrpc": jsonrpc,
            "id": req_id,
            "result": task,
        })

    # ── tasks/get ─────────────────────────────────────────────────────────
    elif method == "tasks/get":
        task_id = params.get("id", "")
        if task_id not in tasks_store:
            return JSONResponse(content={
                "jsonrpc": jsonrpc,
                "id": req_id,
                "error": {"code": -32001, "message": f"Task not found: {task_id}"},
            })

        return JSONResponse(content={
            "jsonrpc": jsonrpc,
            "id": req_id,
            "result": tasks_store[task_id].get("task", {}),
        })

    # ── Unknown method ────────────────────────────────────────────────────
    else:
        return JSONResponse(content={
            "jsonrpc": jsonrpc,
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        })


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"🚀  Starting SNAP Benefits Agent server on port {port} …")
    uvicorn.run(app, host="0.0.0.0", port=port)
