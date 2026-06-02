import httpx
import json
import asyncio

async def test_all_atc_fixes():
    print("=== End-to-End Analysis Pipeline Test ===")
    
    # 1. Fetch ATC results
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            print("Fetching ATC results...")
            resp = await client.get("http://localhost:8000/api/v1/sap/atc-results")
            if resp.status_code != 200:
                print(f"Failed to fetch ATC results: {resp.text}")
                return
            results = resp.json()
            if not results:
                print("No ATC results found.")
                return
                
            result_id = results[0]["id"]
            print(f"Using ATC Result ID: {result_id}")
            
            # 2. Fetch findings
            print("Fetching ATC findings...")
            resp = await client.get(f"http://localhost:8000/api/v1/sap/atc-results/{result_id}/findings")
            if resp.status_code != 200:
                print(f"Failed to fetch ATC findings: {resp.text}")
                return
            findings_data = resp.json()
            findings = findings_data.get("findings", [])
            print(f"Found {len(findings)} findings.")
            
            # Group by unique objects to test analysis on each unique object
            unique_objects = {}
            for f in findings:
                obj_name = f["object_name"]
                obj_type = f.get("object_type", "PROG")
                unique_objects[obj_name] = obj_type
                
            print(f"Unique objects to analyze: {unique_objects}")
            
            # 3. Analyze each unique object
            for obj_name, obj_type in unique_objects.items():
                print(f"\n--- Analyzing Object: {obj_name} ({obj_type}) ---")
                payload = {
                    "objects": [
                        {
                            "name": obj_name,
                            "type": obj_type
                        }
                    ]
                }
                
                resp = await client.post("http://localhost:8000/api/v1/sap/packages/analyze-objects", json=payload)
                print(f"Status Code: {resp.status_code}")
                if resp.status_code == 200:
                    data = resp.json()
                    sessions = data.get("sessions", [])
                    if sessions:
                        session = sessions[0]
                        print(f"Session Status: {session['status']}")
                        print(f"Fixes Generated: {session['fixes_generated']}")
                        for idx, fix in enumerate(session['fixes']):
                            print(f"  Fix {idx+1}: Line {fix['original_code'][:40].strip()}... -> {fix['fixed_code'][:40].strip()}... (Confidence: {fix['confidence']})")
                    else:
                        print("Analysis completed but did not produce a session.")
                else:
                    print(f"Analysis failed: {resp.text}")
                    
        except Exception as e:
            print(f"Test failed with exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_all_atc_fixes())
