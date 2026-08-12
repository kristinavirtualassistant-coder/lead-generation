import json
import re
from datetime import datetime
import gspread
import requests
from bs4 import BeautifulSoup
from schemas import PropertyRecord

SPREADSHEET_ID = "1uG8jbHF3R1PpbgPJWsQC8_0f93jlLTQcJX6_Zh2JJ5E"
SERVICE_ACCOUNT_FILE = "service_account.json"

class SheetClient:
    def __init__(self, service_account_file: str, sheet_id: str):
        self.gc = gspread.service_account(filename=service_account_file)
        self.sheet = self.gc.open_by_key(sheet_id).sheet1
        self._ensure_headers()

    def _ensure_headers(self):
        headers = [
            "Target Property URL", "APN / Parcel ID", "Property Address",
            "Primary Owner", "Mailing Address", "Total Assessed Value ($)",
            "Annual Tax Amount ($)", "Tax Year", "Delinquent Status", "Geocoding & Payload Data"
        ]
        existing = self.sheet.row_values(1)
        if not existing:
            self.sheet.append_row(headers)

    def append_record(self, record: PropertyRecord):
        row = [
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
        self.sheet.append_row(row)


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

    # Flexible CSS locators across common property sites and portals
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


def main():
    sheet_client = SheetClient(SERVICE_ACCOUNT_FILE, SPREADSHEET_ID)

    while True:
        target_url = input("\nEnter Target URL to Scrape (or type 'exit' / 'q' to quit): ").strip()
        
        if target_url.lower() in ["exit", "q", "quit"]:
            print("Exiting interactive scraper.")
            break

        if not target_url.startswith("http"):
            print("Invalid URL format. Please include http:// or https://")
            continue

        try:
            record = scrape_url(target_url)
            sheet_client.append_record(record)
            print(f"[SUCCESS] Appended Record to Google Sheet:")
            print(f" - Address/Title: {record.full_address}")
            print(f" - APN: {record.apn or 'N/A'}")
            print(f" - Assessed Value: ${record.total_assessed_value}")
        except Exception as e:
            print(f"[ERROR] Failed to scrape {target_url}: {e}")


if __name__ == "__main__":
    main()
