"""
A2A Server for Montana SNAP Benefits Agent

Uses ADK's built-in A2A server (same pattern as working uw-voice-agents deployment).
The ADK handles all A2A protocol details via the a2a-sdk library.
"""

from google.adk.cli.fast_api import get_fast_api_app

app = get_fast_api_app(
    agents_dir="/app",
    web=False,
    a2a=True,
    session_service_uri="memory://",
    allow_origins=["*"],
)
