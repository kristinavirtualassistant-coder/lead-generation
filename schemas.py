from pydantic import BaseModel
from typing import Optional, Dict, Any

class PropertyRecord(BaseModel):
    source_url: str
    scraped_at: str
    apn: Optional[str] = None
    parcel_number: Optional[str] = None
    full_address: str
    street_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    county: Optional[str] = None
    use_code: Optional[str] = None
    owner_name_primary: Optional[str] = None
    owner_name_secondary: Optional[str] = None
    mailing_address: Optional[str] = None
    assessed_land_value: Optional[float] = 0.0
    assessed_improvement_value: Optional[float] = 0.0
    total_assessed_value: Optional[float] = 0.0
    tax_amount_annual: Optional[float] = 0.0
    tax_year: Optional[int] = None
    delinquent_status: Optional[bool] = False
    enrichment_payload: Dict[str, Any] = {}
