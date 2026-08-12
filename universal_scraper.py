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

    def read_target_rows(self) -> list:
        """Reads all rows from Row 2 down to process target URLs."""
        return self.sheet.get_all_values()[1:]

    def update_record_at_row(self, row_idx: int, record: PropertyRecord):
        """Updates Columns B through J for the specific row index."""
        row_data = [
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
        cell_range = f"B{row_idx}:J{row_idx}"
        self.sheet.update(range_name=cell_range, values=[row_data])


def parse_currency(text: str) -> float:
    if not text:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", text)
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def scrape_url(url: str) -> PropertyRecord:
    """Fetches any target URL and extracts property/page data using flexible CSS selectors."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    # Flexible CSS locators across common property sites and county portals
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

    # Build payload for downstream PostGIS ingestion & geocoding
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
    rows = sheet_client.read_target_rows()

    if not rows:
        print("No rows found in sheet. Please add URLs to Column A starting at Row 2.")
        return

    print(f"Loaded {len(rows)} rows from Google Sheet.")

    for i, row in enumerate(rows, start=2):
        if not row or not row[0].startswith("http"):
            continue

        url = row[0].strip()

        # Skip rows that have already been extracted
        if len(row) > 1 and row[1] and row[1] != "NaN" and row[1] != "":
            print(f"Row {i} already processed ({url[:40]}...). Skipping.")
            continue

        try:
            print(f"Scraping Row {i}: {url}")
            record = scrape_url(url)
            sheet_client.update_record_at_row(i, record)
            print(f"Row {i} Successfully Updated: {record.full_address[:50]}")
        except Exception as e:
            print(f"Failed to scrape Row {i} ({url}): {e}")


if __name__ == "__main__":
    main()
