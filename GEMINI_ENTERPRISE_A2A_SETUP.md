# Setting Up A2A with Gemini Enterprise

## Your Agent Details
- **Service URL:** `https://snap-benefits-agent-290945876474.us-central1.run.app`
- **Agent Card:** `https://snap-benefits-agent-290945876474.us-central1.run.app/.well-known/agent.json`
- **Project:** `mt-nick-demo`
- **Region:** `us-central1`

---

## Step 1: Verify Your Agent is Running

```bash
# Check health
curl -s -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://snap-benefits-agent-290945876474.us-central1.run.app/health

# Check Agent Card is discoverable
curl -s -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://snap-benefits-agent-290945876474.us-central1.run.app/.well-known/agent.json | jq .
```

---

## Step 2: Register the Agent in Google Admin Console

1. Go to **[admin.google.com](https://admin.google.com)**
2. Sign in with your admin account (`admin@nicknelson.altostrat.com`)
3. Navigate to: **Apps → Google Workspace → Gemini**
4. Click on **"Gemini Apps"** or **"Extensions & Integrations"**
5. Look for **"Third-party extensions"** or **"Agent connections"**
6. Click **"Add agent"** or **"Connect external agent"**
7. Enter:
   - **Agent URL:** `https://snap-benefits-agent-290945876474.us-central1.run.app`
   - **Name:** Montana SNAP Benefits Agent
   - **Description:** Helps Montana residents understand SNAP benefits, check eligibility, and submit applications
8. For **Authentication**, select **Google Cloud IAM** or **Service Account**
   - The agent requires an authenticated identity token
   - Gemini Enterprise will automatically pass the user's identity

---

## Step 3: Alternative — Register via Agentspace (Vertex AI Agent Builder)

If using Vertex AI Agentspace instead of Gemini for Workspace:

1. Go to **[console.cloud.google.com](https://console.cloud.google.com)**
2. Select project **`mt-nick-demo`**
3. Navigate to: **Vertex AI → Agent Builder → Agentspace**
4. Click **"Create Agent"** or **"Add External Agent"**
5. Select **"A2A Agent"** as the type
6. Enter:
   - **Agent endpoint URL:** `https://snap-benefits-agent-290945876474.us-central1.run.app`
   - Agentspace will auto-discover capabilities from `/.well-known/agent.json`
7. Configure access control (which users/groups can interact with the agent)
8. Click **Deploy**

---

## Step 4: Grant Gemini Service Account Access to Cloud Run

Gemini Enterprise needs permission to invoke your Cloud Run service. The Gemini service agent in your project needs the `roles/run.invoker` role:

```bash
# Find the Gemini service agent email (format varies)
# Option A: Gemini for Workspace service account
gcloud run services add-iam-policy-binding snap-benefits-agent \
  --region=us-central1 \
  --project=mt-nick-demo \
  --member="serviceAccount:service-290945876474@gcp-sa-aiplatform.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# Option B: If using Agentspace, the service account may be different
# Check the Agentspace configuration for the exact service account email
```

If you need to allow specific users to invoke directly (for testing):

```bash
# Allow a specific user
gcloud run services add-iam-policy-binding snap-benefits-agent \
  --region=us-central1 \
  --project=mt-nick-demo \
  --member="user:admin@nicknelson.altostrat.com" \
  --role="roles/run.invoker"

# Allow all authenticated users in your org
gcloud run services add-iam-policy-binding snap-benefits-agent \
  --region=us-central1 \
  --project=mt-nick-demo \
  --member="domain:nicknelson.altostrat.com" \
  --role="roles/run.invoker"
```

---

## Step 5: Test from Gemini Enterprise

Once registered:

1. Open **[gemini.google.com](https://gemini.google.com)** (or Gemini in Google Workspace)
2. Sign in with your enterprise account
3. The SNAP Benefits Agent should appear as an available agent/extension
4. Start a conversation:
   - *"Am I eligible for SNAP benefits in Montana? I earn $1,500/month."*
   - *"What are the income limits for a family of 4?"*
   - *"I'd like to submit an application"*
   - *"Show me all submitted applications"*

Gemini Enterprise handles the A2A protocol behind the scenes — it sends `tasks/send` JSON-RPC calls to your Cloud Run service and displays the agent's responses inline.

---

## Step 6: Monitor & Debug

### View Cloud Run Logs
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=snap-benefits-agent" \
  --project mt-nick-demo \
  --limit 20 \
  --format="table(timestamp,textPayload)"
```

### Test A2A Manually (simulate what Gemini Enterprise does)
```bash
export TOKEN=$(gcloud auth print-identity-token)
export BASE=https://snap-benefits-agent-290945876474.us-central1.run.app

# Discover agent capabilities
curl -s -H "Authorization: Bearer $TOKEN" $BASE/.well-known/agent.json | jq .

# Send a message
curl -s -X POST $BASE/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tasks/send",
    "params": {
      "id": "test-001",
      "message": {
        "role": "user",
        "parts": [{"type": "text", "text": "What is SNAP?"}]
      }
    }
  }' | jq .result.status.message.parts[0].text
```

---

## Architecture Summary

```
┌─────────────────────────┐
│   Gemini Enterprise     │
│   (Business User UI)    │
└──────────┬──────────────┘
           │ A2A JSON-RPC
           │ tasks/send
           ▼
┌─────────────────────────┐
│   Cloud Run Service     │
│   server.py (FastAPI)   │
│   ┌───────────────────┐ │
│   │  ADK Agent        │ │
│   │  gemini-3-flash   │ │
│   │  ┌─────────────┐  │ │
│   │  │ 4 Tools:    │  │ │
│   │  │ • search    │──┼─┼──→ Vertex AI Search
│   │  │ • policy    │──┼─┼──→ Document AI (OCR'd text)
│   │  │ • submit    │──┼─┼──→ BigQuery INSERT
│   │  │ • list      │──┼─┼──→ BigQuery SELECT
│   │  └─────────────┘  │ │
│   └───────────────────┘ │
└─────────────────────────┘
```

---

## Demo Script

1. **Vibe Coding** — Show building `server.py` with AI
2. **Vertex AI Search** — Run `prepare_and_import.py`, show data store + search engine
3. **Document AI** — Show PDF → OCR extraction during agent startup
4. **ADK Agent** — Show `dphhs_snap_agent.py` with 4 tools + system instruction
5. **Cloud Run** — `gcloud run deploy` and hit the health endpoint
6. **A2A + Gemini Enterprise** — Open Gemini, talk to the SNAP agent naturally
