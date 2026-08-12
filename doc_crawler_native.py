import json
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse
import gspread
import requests
from bs4 import BeautifulSoup

SERVICE_ACCOUNT_FILE = "service_account.json"
HEADERS = [
    "Doc Category", "Page Title", "Sub-Section / Tab", 
    "Source URL", "Main Content / Endpoints", "API Parameters / Fields", "Raw Payload Data"
]

class SheetManager:
    def __init__(self, service_account_file: str):
        self.gc = gspread.service_account(filename=service_account_file)

    def create_doc_spreadsheet(self, title: str):
        spreadsheet = self.gc.create(title)
        sheet = spreadsheet.sheet1
        sheet.append_row(HEADERS)
        return spreadsheet, sheet


def extract_sidebar_and_crawl(start_url: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    print(f"\nFetching documentation root: {start_url}")
    response = requests.get(start_url, headers=headers, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    # Extract all navigation sidebar links
    sidebar_links = []
    nav_elements = soup.select("nav a, .sidebar a, [class*='sidebar'] a, [class*='nav'] a, aside a")

    for el in nav_elements:
        href = el.get("href")
        text = el.get_text(strip=True)
        if href and not href.startswith("javascript"):
            full_url = urljoin(start_url, href)
            sidebar_links.append({"title": text or "Doc Link", "url": full_url})

    # Fallback to internal links if no explicit sidebar structure detected
    if not sidebar_links:
        parsed_start = urlparse(start_url)
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full_url = urljoin(start_url, href)
            if parsed_start.netloc in full_url:
                sidebar_links.append({"title": a.get_text(strip=True) or "Doc Link", "url": full_url})

    # Deduplicate links preserving order
    unique_links = []
    seen_urls = set()
    for item in sidebar_links:
        if item["url"] not in seen_urls and item["url"].startswith("http"):
            seen_urls.add(item["url"])
            unique_links.append(item)

    print(f"Discovered {len(unique_links)} documentation pages in navigation tree.")

    doc_records = []

    for index, item in enumerate(unique_links, start=1):
        url = item["url"]
        print(f"[{index}/{len(unique_links)}] Scraping: {url}")
        try:
            res = requests.get(url, headers=headers, timeout=15)
            page_soup = BeautifulSoup(res.text, "html.parser")

            page_title = page_soup.title.string.strip() if page_soup.title else "ATTOM API Documentation"

            # Parse main content body
            content_elem = page_soup.select_one("main, article, .content, #content, body")
            content_text = content_elem.get_text(separator="\n", strip=True) if content_elem else ""

            # Extract parameter tables / field definitions
            param_rows = []
            tables = page_soup.select("table")
            for t in tables:
                for row in t.select("tr"):
                    cells = [c.get_text(strip=True) for c in row.select("th, td")]
                    if cells:
                        param_rows.append(" | ".join(cells))

            doc_records.append({
                "category": item["title"] or "Documentation",
                "title": page_title,
                "sub_section": "Main",
                "url": url,
                "content": content_text[:4000],
                "parameters": "\n".join(param_rows[:20]) if param_rows else "No parameter table detected",
                "timestamp": datetime.utcnow().isoformat()
            })

        except Exception as e:
            print(f"Failed to crawl {url}: {e}")

    return doc_records


def main():
    manager = SheetManager(SERVICE_ACCOUNT_FILE)

    while True:
        target_url = input("\nEnter Documentation Root URL to Crawl (or 'q' to exit): ").strip()
        if target_url.lower() in ["q", "quit", "exit"]:
            break

        if not target_url.startswith("http"):
            print("Please enter a valid URL starting with http:// or https://")
            continue

        records = extract_sidebar_and_crawl(target_url)

        if records:
            domain = urlparse(target_url).netloc.replace("www.", "")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            sheet_title = f"Doc Tree - {domain} ({timestamp})"

            spreadsheet, sheet = manager.create_doc_spreadsheet(sheet_title)

            rows_to_insert = []
            for r in records:
                rows_to_insert.append([
                    r["category"],
                    r["title"],
                    r["sub_section"],
                    r["url"],
                    r["content"],
                    r["parameters"],
                    json.dumps({"timestamp": r["timestamp"]})
                ])

            sheet.append_rows(rows_to_insert)

            print(f"\n[SUCCESS] Document Tree Crawl Complete!")
            print(f" - Created Sheet: {sheet_title}")
            print(f" - Sheet URL: {spreadsheet.url}")
            print(f" - Total Doc Pages Processed: {len(records)}")


if __name__ == "__main__":
    main()
