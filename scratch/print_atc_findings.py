import sys
import os
import asyncio

backend_dir = r"c:\Users\AnilMutalik\OneDrive - Motiveminds Consulting Pvt Ltd\Desktop\CleanCore AI\backend"
sys.path.insert(0, backend_dir)

from services.sap_connector import sap_connector

async def main():
    print("Fetching active ATC runs to find worklist/result ID...")
    try:
        await sap_connector._ensure_connected()
        if not sap_connector._adt_client:
            print("Not connected via ADT.")
            return
            
        results = await sap_connector.get_atc_results()
        print(f"Found {len(results)} ATC results:")
        for r in results:
            print(f"  ID: {r.id} | Title: {r.title} | Object Set: {r.object_set} | Findings Count: {r.findings_count}")
            
        # If there are results, let's fetch findings for the first one
        if results:
            first_id = results[0].id
            print(f"\nFetching findings for result ID: {first_id}...")
            findings = await sap_connector.get_atc_worklist_findings(first_id)
            print(f"Found {len(findings)} findings:")
            for idx, f in enumerate(findings):
                print(f"  Finding {idx+1}: {f.object_name} ({f.object_type}) | Check: {f.check_title} | Msg: {f.message}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
