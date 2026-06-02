# test_zconv.py
# Runs a live test against SAP to pull package ZCONV and logs the details.

import sys
import os
import json
import asyncio

# Ensure backend dir is on path
backend_dir = r"C:\Users\AnilMutalik\OneDrive - Motiveminds Consulting Pvt Ltd\Desktop\CleanCore AI\backend"
sys.path.insert(0, backend_dir)

from services.sap_connector import sap_connector
from services.adt_client import ADTRestClient, ADTError

async def test_live_search():
    # Load connection config
    config_path = os.path.join(backend_dir, "uploads", "sap_connection_config.json")
    if not os.path.exists(config_path):
        print(f"[ERROR] Config path does not exist: {config_path}")
        print("Please connect to SAP via the UI first.")
        return
        
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)
        
    print("Loaded connection config. Client:", config_data.get("client"), "User:", config_data.get("user"))
    
    # Initialize connector with config
    from models import SAPConnectionConfig
    config = SAPConnectionConfig(**config_data)
    
    # Connect
    print("Connecting to SAP...")
    status = await sap_connector.connect(config)
    print("Connection status:", status)
    
    if not status.connected:
        print("[ERROR] Failed to connect:", status.message)
        return
        
    print("\nAttempting to get objects for package 'ZCONV'...")
    try:
        # Call the direct ADT method so we can see the raw HTTP status / response if any
        client = sap_connector._adt_client
        if client:
            print("Direct ADT request testing...")
            params = {
                "operation": "quickSearch",
                "query": "*",
                "package": "ZCONV",
                "maxResults": "5000",
            }
            resp = await client._request(
                "GET",
                "/sap/bc/adt/repository/informationsystem/search",
                params=params,
            )
            print("HTTP Status Code:", resp.status_code)
            print("Headers:", dict(resp.headers))
            print("Response Body (first 1000 chars):")
            print(resp.text[:1000])
            
            # Now parse search results
            results = client._parse_search_results(resp.text)
            print(f"\nParsed {len(results)} objects.")
            if results:
                print("First 3 objects:", results[:3])
        else:
            print("ADT client is None. Connected via RFC?")
            
    except Exception as e:
        print("[EXCEPTION IN DIRECT TEST]:", type(e), e)
        import traceback
        traceback.print_exc()

    print("\nCalling sap_connector.get_objects_by_package('ZCONV')...")
    try:
        objects = await sap_connector.get_objects_by_package("ZCONV")
        print("Successful pull! Total objects returned:", len(objects))
        if objects:
            print("First 3 objects:", [o.model_dump() for o in objects[:3]])
    except Exception as e:
        print("[EXCEPTION IN CONNECTOR WRAPPER]:", type(e), e)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_live_search())
