FROM python:3.11-slim

WORKDIR /app

# Install ADK with A2A support + SNAP agent dependencies
RUN pip install --no-cache-dir \
    "google-adk[a2a]" \
    a2a-sdk \
    uvicorn \
    google-cloud-bigquery \
    google-cloud-storage \
    google-cloud-documentai \
    google-cloud-discoveryengine \
    requests

# Copy the SNAP agent tools/setup module
COPY dphhs_snap_agent.py /app/dphhs_snap_agent.py

# Copy the agent package (discovered by ADK)
COPY snap_benefits_agent/ /app/snap_benefits_agent/

# Copy the A2A server entrypoint
COPY main.py /app/main.py

# Environment
ENV GOOGLE_CLOUD_PROJECT=mt-nick-demo
ENV GOOGLE_CLOUD_LOCATION=us-central1
# GOOGLE_API_KEY should be set at runtime, not baked into the image
# ENV GOOGLE_API_KEY=your-api-key-here

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
