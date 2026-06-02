import sys
import os
import asyncio

backend_dir = r"c:\Users\AnilMutalik\OneDrive - Motiveminds Consulting Pvt Ltd\Desktop\CleanCore AI\backend"
sys.path.insert(0, backend_dir)

from services.sap_connector import sap_connector

async def main():
    print("Reading Z_ATC_S4_READINESS_ECC_FIXTURE source code via read_program_source...")
    try:
        await sap_connector._ensure_connected()
        if not sap_connector._adt_client:
            print("Not connected via ADT.")
            return
            
        source = await sap_connector._adt_client.read_program_source("z_atc_s4_readiness_ecc_fixture")
        print(f"Source loaded ({len(source)} chars). Entire source code:")
        print("--------------------------------------------------")
        print(source)
        print("--------------------------------------------------")
        with open("fixture_source.abap", "w", encoding="utf-8") as f:
            f.write(source)
        print("Saved to fixture_source.abap")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
