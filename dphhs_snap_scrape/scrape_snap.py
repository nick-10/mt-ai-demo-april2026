#!/usr/bin/env python3
"""
Montana DPHHS SNAP Benefits Scraper
Scrapes SNAP-related content from dphhs.mt.gov and saves as JSON/JSONL
for Vertex AI Search ingestion.
"""

import json
import os
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# ── Configuration ──────────────────────────────────────────────────────────────
BASE_URL = "https://dphhs.mt.gov"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

SNAP_PAGES = [
    {
        "id": "snap_main",
        "url": f"{BASE_URL}/HCSD/SNAP",
        "title": "SNAP - Supplemental Nutrition Assistance Program",
    },
    {
        "id": "snap_overpayment",
        "url": f"{BASE_URL}/HCSD/SNAPorTANFoverpayment",
        "title": "SNAP or TANF Overpayment",
    },
    {
        "id": "snap_manual_index",
        "url": f"{BASE_URL}/HCSD/snapmanual",
        "title": "SNAP Policy Manual",
    },
    {
        "id": "snap_tefap",
        "url": f"{BASE_URL}/HCSD/TheEmergencyFoodAssistanceProgram",
        "title": "The Emergency Food Assistance Program (TEFAP)",
    },
    {
        "id": "snap_hcsd_overview",
        "url": f"{BASE_URL}/HCSD/",
        "title": "Human and Community Services Division - Overview",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; MT-DPHHS-Demo-Scraper/1.0; "
        "educational/demo purposes)"
    )
}


# ── Helpers ────────────────────────────────────────────────────────────────────
def fetch_page(url: str) -> str:
    """Fetch HTML content from a URL."""
    print(f"  Fetching: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_main_content(html: str) -> str:
    """Extract the main body content, stripping nav/header/footer/scripts."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove elements that are not content
    for tag in soup.find_all(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()

    # Try to find the main content area
    main = (
        soup.find("main")
        or soup.find("div", {"id": "main"})
        or soup.find("div", {"class": re.compile(r"content|main", re.I)})
        or soup.find("div", {"id": re.compile(r"content|main", re.I)})
    )

    target = main if main else soup.body if soup.body else soup

    # Get text and clean it up
    text = target.get_text(separator="\n")
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip leading/trailing whitespace per line
    text = "\n".join(line.strip() for line in text.splitlines())
    # Remove excessive blank lines again after strip
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return text


def extract_links(html: str, pattern: str = "") -> list[dict]:
    """Extract links from HTML, optionally filtering by a regex pattern."""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if pattern and not re.search(pattern, href, re.I):
            continue
        # Resolve relative URLs
        if href.startswith("/") or href.startswith(".."):
            href = requests.compat.urljoin(BASE_URL, href)
        link_text = a.get_text(strip=True)
        links.append({"text": link_text, "url": href})
    return links


def scrape_page(page_config: dict) -> dict:
    """Scrape a single page and return a structured document."""
    html = fetch_page(page_config["url"])
    content = extract_main_content(html)

    doc = {
        "id": page_config["id"],
        "structData": {
            "title": page_config["title"],
            "url": page_config["url"],
            "source": "Montana Department of Public Health and Human Services",
            "category": "SNAP Benefits",
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        },
        "content": {
            "mimeType": "text/plain",
            "uri": page_config["url"],
        },
        "text_content": content,
    }

    # For the manual page, also extract PDF links
    if page_config["id"] == "snap_manual_index":
        pdf_links = extract_links(html, r"\.pdf$")
        doc["structData"]["pdf_manual_links"] = pdf_links
        doc["structData"]["pdf_count"] = len(pdf_links)

    return doc


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    all_docs = []
    
    print("=" * 60)
    print("Montana DPHHS - SNAP Benefits Scraper")
    print("=" * 60)

    for page in SNAP_PAGES:
        print(f"\n📄 Scraping: {page['title']}")
        try:
            doc = scrape_page(page)
            all_docs.append(doc)

            # Save individual JSON
            filepath = os.path.join(OUTPUT_DIR, f"{page['id']}.json")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=2, ensure_ascii=False)
            print(f"  ✅ Saved: {filepath}")
            print(f"  📏 Content length: {len(doc['text_content'])} chars")

        except Exception as e:
            print(f"  ❌ Error scraping {page['url']}: {e}")

        # Be polite - small delay between requests
        time.sleep(1)

    # Save combined JSONL (one JSON object per line)
    jsonl_path = os.path.join(OUTPUT_DIR, "all_snap_documents.jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for doc in all_docs:
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")
    print(f"\n📦 Combined JSONL saved: {jsonl_path}")
    print(f"   Total documents: {len(all_docs)}")

    # Summary
    print("\n" + "=" * 60)
    print("SCRAPING COMPLETE")
    print("=" * 60)
    print(f"Pages scraped: {len(all_docs)}/{len(SNAP_PAGES)}")
    total_chars = sum(len(d["text_content"]) for d in all_docs)
    print(f"Total content: {total_chars:,} characters")
    print(f"Output directory: {OUTPUT_DIR}")
    
    return all_docs


if __name__ == "__main__":
    main()
