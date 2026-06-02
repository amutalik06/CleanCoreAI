# test_zconv_timeout.py
# Runs a live test against SAP to pull package ZCONV using the increased timeout.

import sys
import os
import json
import asyncio

# Ensure backend dir is on path
backend_dir = r"C:\Users\AnilMutalik\OneDrive - Motiveminds Consulting Pvt Ltd\Desktop\CleanCore AI\backend"
sys.path.insert(0, backend_dir)

from services.sap_connector import sap_connector

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
        
    print("\nCalling sap_connector.get_objects_by_package('ZCONV')...")
    try:
        objects = await sap_connector.get_objects_by_package("ZCONV")
        print("Successful pull! Total objects returned:", len(objects))
        if objects:
            print("First 10 objects:")
            for o in objects[:10]:
                print(f"  - {o.name} ({o.type}) in package {o.package}")
    except Exception as e:
        print("[EXCEPTION IN CONNECTOR WRAPPER]:", type(e), e)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_live_search())
