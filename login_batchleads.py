import re
import requests

# Updated BatchLeads login endpoint
BATCHLEADS_LOGIN_URL = "https://app.batchleads.io/api/v1/user/login"
EMAIL = "kristina@cmc-realty.com"
PASSWORD = "Dominate2026!"

def login_and_save_token():
    print("=== Authenticating with BatchLeads ===")
    payload = {
        "email": EMAIL,
        "password": PASSWORD
    }
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.post(BATCHLEADS_LOGIN_URL, json=payload, headers=headers, timeout=15)
        print(f"Server Response Code: {response.status_code}")
        
        if response.status_code in [200, 201]:
            data = response.json()
            
            # Extract token across possible keys
            token = (
                data.get("token") or 
                data.get("access_token") or 
                data.get("data", {}).get("token") or 
                data.get("result", {}).get("token")
            )
            
            if token:
                print("\n[SUCCESS] Active Bearer Token Retrieved!")
                
                with open("batchleads_scraper.py", "r") as f:
                    content = f.read()
                
                updated_content = re.sub(
                    r'BATCHLEADS_API_TOKEN = ".*?"',
                    f'BATCHLEADS_API_TOKEN = "{token}"',
                    content
                )
                
                with open("batchleads_scraper.py", "w") as f:
                    f.write(updated_content)
                    
                print("Updated batchleads_scraper.py with active session token!")
            else:
                print("Response received, but token key missing from payload:", data)
        else:
            print(f"Login failed [{response.status_code}]: {response.text}")
    except Exception as e:
        print(f"Connection error: {e}")

if __name__ == "__main__":
    login_and_save_token()
