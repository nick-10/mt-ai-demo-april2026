"""
Montana SNAP Benefits Agent — ADK Agent Module

This module is auto-discovered by ADK's get_fast_api_app(a2a=True).
It runs Phase 1 infrastructure setup at import time, then exposes
`root_agent` for the A2A server to use.
"""

import sys
import os

# Ensure the parent directory is importable so we can use dphhs_snap_agent
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dphhs_snap_agent as snap

# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 1 — Infrastructure Setup (runs once at import/startup)
# ═══════════════════════════════════════════════════════════════════════════════

print("=" * 60)
print("  SNAP BENEFITS AGENT — PHASE 1 SETUP")
print("=" * 60)

try:
    pdf_bytes = snap.download_pdf()
    gcs_uri = snap.upload_to_gcs(pdf_bytes)
    snap.POLICY_TEXT = snap.extract_text_with_docai(gcs_uri)
    snap.setup_bigquery()
    print("\n✅  Phase 1 setup complete!\n")
except Exception as e:
    print(f"\n⚠️  Phase 1 setup error (agent will still start): {e}\n")

# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 2+3 — Agent Definition (discovered by ADK)
# ═══════════════════════════════════════════════════════════════════════════════

root_agent = snap.create_agent()
