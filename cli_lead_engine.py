import json
import re
import sys
from datetime import datetime
from urllib.parse import urljoin, urlparse
import gspread
import requests
from bs4 import BeautifulSoup
from schemas import PropertyRecord

SERVICE_ACCOUNT_FILE = "service_account.json"

# Target Google Drive Folder ID
TARGET_DRIVE_FOLDER_ID = "17h-HBVutvBNwZi9Ui__hYmCtgns-my6V"

# Headers for Property Lead Sheets
PROPERTY_HEADERS = [
    "Target Property URL", "APN / Parcel ID", "Property Address",
    "Primary Owner", "Mailing Address", "Total Assessed Value ($)",
    "Annual Tax Amount ($)", "Tax Year", "Delinquent Status", "Geocoding & Payload Data"
]

# Headers for Documentation Tree Sheets
DOC_HEADERS = [
    "Doc Category", "Page Title", "Sub-Section / Tab", 
    "Source URL", "Main Content / Endpoints", "API Parameters / Fields", "Raw Payload Data"
]


class SheetManager:
    def __init__(self, service_account_file: str, folder_id: str = None):
        self.gc = gspread.service_account(filename=service_account_file)
        self.folder_id = folder_id

    def create_spreadsheet(self, title: str, headers: list):
        """Creates 1 dedicated spreadsheet per target URL inside your Google Drive folder."""
        if self.folder_id:
            spreadsheet = self.gc.create(title, folder_id=self.folder_id)
        else:
            spreadsheet = self.gc.create(title)

        sheet = spreadsheet.sheet1
        sheet.append_row(headers)
        return spreadsheet, sheet


def parse_currency(text: str) -> float:
    if not text:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", text)
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


# =====================================================================
# ENGINE 1: Property Lead Scraper
# =====================================================================
def scrape_property_url(url: str) -> PropertyRecord:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    print(f"\nFetching property record from: {url}")
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    apn_elem = soup.select_one(".apn-value, #parcel-id, [data-apn], td:has-text('APN') + td, td:has-text('Parcel') + td, .parcel-number")
    apn = apn_elem.get_text(strip=True) if apn_elem else None

    addr_elem = soup.select_one("h1.address, .property-address, #prop-addr, .situs-address, title, h1")
    address = addr_elem.get_text(strip=True) if addr_elem else "Address / Title Not Found"

    owner_elem = soup.select_one(".owner-name, #owner-info, td:has-text('Owner') + td, .owner")
    owner_primary = owner_elem.get_text(strip=True) if owner_elem else None

    mailing_elem = soup.select_one(".mailing-address, td:has-text('Mailing') + td, .mailing")
    mailing_address = mailing_elem.get_text(strip=True) if mailing_elem else None

    tax_elem = soup.select_one(".tax-total, #tax-amount, td:has-text('Total Tax') + td, .tax-amount")
    tax_amount = parse_currency(tax_elem.get_text()) if tax_elem else 0.0

    assessed_elem = soup.select_one(".assessed-value, td:has-text('Assessed') + td, .assessed")
    assessed_val = parse_currency(assessed_elem.get_text()) if assessed_elem else 0.0

    enrichment_payload = {
        "geocoding_query": address.strip(),
        "meta_description": soup.find("meta", {"name": "description"})["content"] if soup.find("meta", {"name": "description"}) else None,
        "tech_stack": {
            "geocoding_api": "Google Maps / Census Geocoder",
            "db_extension": "PostGIS (EPSG:4326)"
        },
        "raw_attributes": {
            "status_code": response.status_code,
            "scraped_timestamp": datetime.utcnow().isoformat()
        }
    }

    return PropertyRecord(
        source_url=url,
        scraped_at=datetime.utcnow().isoformat(),
        apn=apn,
        parcel_number=apn,
        full_address=address,
        owner_name_primary=owner_primary,
        mailing_address=mailing_address,
        total_assessed_value=assessed_val,
        tax_amount_annual=tax_amount,
        tax_year=datetime.now().year,
        enrichment_payload=enrichment_payload
    )


def run_property_scraper_loop(manager: SheetManager):
    print("\n--- MODE: Property Lead Extraction ---")
    while True:
        url = input("\nEnter Property URL to Scrape (or 'back' to change mode): ").strip()
        if url.lower() in ["back", "b"]:
            break
        if not url.startswith("http"):
            print("Invalid URL format. Please include http:// or https://")
            continue

        try:
            record = scrape_property_url(url)
            domain = urlparse(url).netloc.replace("www.", "")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            sheet_title = f"Property Lead - {domain} ({timestamp})"

            spreadsheet, sheet = manager.create_spreadsheet(sheet_title, PROPERTY_HEADERS)

            row_data = [
                record.source_url,
                record.apn or record.parcel_number or "N/A",
                record.full_address,
                record.owner_name_primary or "N/A",
                record.mailing_address or "N/A",
                record.total_assessed_value,
                record.tax_amount_annual,
                record.tax_year or "N/A",
                record.delinquent_status,
                json.dumps(record.enrichment_payload)
            ]
            sheet.append_row(row_data)

            print(f"[SUCCESS] Created Dedicated Property Sheet in Target Folder: '{sheet_title}'")
            print(f" - Sheet URL: {spreadsheet.url}")
            print(f" - Address/Title: {record.full_address}")
        except Exception as e:
            print(f"[ERROR] Failed to process property URL {url}: {e}")


# =====================================================================
# ENGINE 2: Documentation Tree Crawler
# =====================================================================
def extract_doc_tree_and_crawl(start_url: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    print(f"\nFetching documentation root: {start_url}")
    response = requests.get(start_url, headers=headers, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    sidebar_links = []
    nav_elements = soup.select("nav a, .sidebar a, [class*='sidebar'] a, [class*='nav'] a, aside a")

    for el in nav_elements:
        href = el.get("href")
        text = el.get_text(strip=True)
        if href and not href.startswith("javascript"):
            sidebar_links.append({"title": text or "Doc Link", "url": urljoin(start_url, href)})

    if not sidebar_links:
        parsed_start = urlparse(start_url)
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full_url = urljoin(start_url, href)
            if parsed_start.netloc in full_url:
                sidebar_links.append({"title": a.get_text(strip=True) or "Doc Link", "url": full_url})

    sidebar_links.insert(0, {"title": "Root Overview", "url": start_url})

    unique_links = []
    seen_urls = set()
    for item in sidebar_links:
        if item["url"] not in seen_urls and item["url"].startswith("http"):
            seen_urls.add(item["url"])
            unique_links.append(item)

    print(f"Discovered {len(unique_links)} documentation sub-pages in tree.")
    doc_records = []

    for index, item in enumerate(unique_links, start=1):
        url = item["url"]
        print(f"[{index}/{len(unique_links)}] Scraping doc page: {url}")
        try:
            res = requests.get(url, headers=headers, timeout=15)
            page_soup = BeautifulSoup(res.text, "html.parser")
            page_title = page_soup.title.string.strip() if page_soup.title else "Documentation Page"

            content_elem = page_soup.select_one("main, article, .content, #content, body")
            content_text = content_elem.get_text(separator="\n", strip=True) if content_elem else ""

            param_rows = []
            for t in page_soup.select("table"):
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


def run_doc_crawler_loop(manager: SheetManager):
    print("\n--- MODE: Documentation Tree Crawler ---")
    while True:
        url = input("\nEnter Documentation Root URL to Crawl (or 'back' to change mode): ").strip()
        if url.lower() in ["back", "b"]:
            break
        if not url.startswith("http"):
            print("Invalid URL format. Please include http:// or https://")
            continue

        try:
            records = extract_doc_tree_and_crawl(url)
            if records:
                domain = urlparse(url).netloc.replace("www.", "")
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                sheet_title = f"Doc Suite - {domain} ({timestamp})"

                spreadsheet, sheet = manager.create_spreadsheet(sheet_title, DOC_HEADERS)

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

                print(f"[SUCCESS] Created Dedicated Doc Suite Sheet in Target Folder: '{sheet_title}'")
                print(f" - Sheet URL: {spreadsheet.url}")
                print(f" - Total Pages Extracted: {len(records)}")
        except Exception as e:
            print(f"[ERROR] Failed to process doc URL {url}: {e}")


# =====================================================================
# CLI MENU ROUTER
# =====================================================================
def main():
    manager = SheetManager(SERVICE_ACCOUNT_FILE, folder_id=TARGET_DRIVE_FOLDER_ID)

    while True:
        print("\n=======================================================")
        print("          UNIFIED LEAD GENERATION CLI ENGINE          ")
        print("=======================================================")
        print(f" Target Folder ID: {manager.folder_id}")
        print("-------------------------------------------------------")
        print(" [1] Property Lead Scraper (1 URL -> 1 Dedicated Sheet)")
        print(" [2] Documentation Tree Crawler (Full Tree -> 1 Dedicated Sheet)")
        print(" [q] Quit CLI Engine")
        
        choice = input("\nSelect execution mode [1, 2, or q]: ").strip().lower()

        if choice == "1":
            run_property_scraper_loop(manager)
        elif choice == "2":
            run_doc_crawler_loop(manager)
        elif choice in ["q", "quit", "exit"]:
            print("Shutting down CLI Engine. Goodbye!")
            sys.exit(0)
        else:
            print("Invalid selection. Please choose 1, 2, or q.")


if __name__ == "__main__":
    main()
