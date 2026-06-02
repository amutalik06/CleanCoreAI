import httpx
import json

async def main():
    url = "http://localhost:8000/api/v1/sap/packages/analyze-objects"
    payload = {
        "objects": [
            {
                "name": "Z_ATC_S4_READINESS_ECC_FIXTURE",
                "type": "PROG"
            }
        ]
    }
    
    print(f"Sending POST request to {url}...")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            print(f"Status Code: {resp.status_code}")
            try:
                print("Response JSON snippet:")
                data = resp.json()
                print(json.dumps(data, indent=2)[:1000])
            except Exception:
                print("Raw Response text:")
                print(resp.text[:1000])
    except Exception as e:
        print(f"Request failed with exception: {e}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
