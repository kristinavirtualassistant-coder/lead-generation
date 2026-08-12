import json
import re
from datetime import datetime
from urllib.parse import urlparse
import gspread
import requests
from bs4 import BeautifulSoup
from schemas import PropertyRecord

SERVICE_ACCOUNT_FILE = "service_account.json"
HEADERS = [
    "Target Property URL", "APN / Parcel ID", "Property Address",
    "Primary Owner", "Mailing Address", "Total Assessed Value ($)",
    "Annual Tax Amount ($)", "Tax Year", "Delinquent Status", "Geocoding & Payload Data"
]


class SheetManager:
    def __init__(self, service_account_file: str):
        self.gc = gspread.service_account(filename=service_account_file)

    def create_new_spreadsheet(self, title: str):
        """Creates a new Google Spreadsheet and initializes headers in Row 1."""
        spreadsheet = self.gc.create(title)
        
        # Share with user if needed or keep default service account ownership
        sheet = spreadsheet.sheet1
        sheet.append_row(HEADERS)
        
        return spreadsheet, sheet


def parse_currency(text: str) -> float:
    if not text:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", text)
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def scrape_url(url: str) -> PropertyRecord:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    print(f"\nFetching content from: {url}")
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    # Dynamic target locators
    apn_elem = soup.select_one(".apn-value, #parcel-id, [data-apn], td:has-text('APN') + td, td:has-text('Parcel') + td, .parcel-number")
    apn = apn_elem.get_text(strip=True) if apn_elem else None

    addr_elem = soup.select_one("h1.address, .property-address, #prop-addr, .situs-address, title, h1")
    address = addr_elem.get_text(strip=True) if addr_elem else "Address / Page Title Not Found"

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
        "tech_stack_requirements": {
            "geocoding_api": "Google Maps Geocoding API / Census Geocoder",
            "db_extension": "PostGIS (Geometry Point, EPSG:4326)"
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


def generate_sheet_title(url: str, record: PropertyRecord) -> str:
    """Generates a clean spreadsheet name using property address or domain timestamp."""
    domain = urlparse(url).netloc.replace("www.", "")
    clean_addr = re.sub(r"[^\w\s-]", "", record.full_address).strip()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if clean_addr and clean_addr != "Address  Page Title Not Found":
        return f"Lead - {clean_addr[:30]} ({timestamp})"
    return f"Lead - {domain} ({timestamp})"


def main():
    manager = SheetManager(SERVICE_ACCOUNT_FILE)

    while True:
        target_url = input("\nEnter Target URL to Scrape (or type 'exit' / 'q' to quit): ").strip()
        
        if target_url.lower() in ["exit", "q", "quit"]:
            print("Exiting interactive scraper.")
            break

        if not target_url.startswith("http"):
            print("Invalid URL format. Please include http:// or https://")
            continue

        try:
            # 1. Scrape the URL
            record = scrape_url(target_url)
            
            # 2. Create a dedicated Spreadsheet for this URL
            sheet_title = generate_sheet_title(target_url, record)
            spreadsheet, sheet = manager.create_new_spreadsheet(sheet_title)
            
            # 3. Append record into Row 2 (under headers)
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

            print(f"\n[SUCCESS] Created New Spreadsheet: '{sheet_title}'")
            print(f" - Sheet URL: {spreadsheet.url}")
            print(f" - Address/Title: {record.full_address}")
            print(f" - APN: {record.apn or 'N/A'}")

        except Exception as e:
            print(f"[ERROR] Failed to process {target_url}: {e}")


if __name__ == "__main__":
    main()
