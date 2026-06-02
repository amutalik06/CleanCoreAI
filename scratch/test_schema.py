import sys
import os
import asyncio
import httpx
import json

backend_dir = r"c:\Users\AnilMutalik\OneDrive - Motiveminds Consulting Pvt Ltd\Desktop\CleanCore AI\backend"
sys.path.insert(0, backend_dir)

from config import settings

async def test_schema():
    print("Testing Gemini structured schema response...")
    api_key = settings.GEMINI_API_KEY
    model = settings.GEMINI_MODEL or "gemini-3.5-flash"
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    # We define the structured output schema
    schema = {
        "type": "OBJECT",
        "properties": {
            "fixed_code": {"type": "STRING"},
            "changes": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "line": {"type": "INTEGER"},
                        "original": {"type": "STRING"},
                        "fixed": {"type": "STRING"},
                        "reason": {"type": "STRING"}
                    },
                    "required": ["line", "original", "fixed", "reason"]
                }
            },
            "rationale": {"type": "STRING"},
            "sap_notes": {
                "type": "ARRAY",
                "items": {"type": "STRING"}
            },
            "confidence": {"type": "NUMBER"},
            "warnings": {
                "type": "ARRAY",
                "items": {"type": "STRING"}
            }
        },
        "required": ["fixed_code", "changes", "rationale", "sap_notes", "confidence", "warnings"]
    }
    
    prompt = "Fix obsolete table VBUK in SELECT * FROM vbuk INTO TABLE lt_vbuk. Replace VBUK with I_SalesDocument."
    
    payload = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
            "responseSchema": schema
        }
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            print("Response text length:", len(text))
            try:
                parsed = json.loads(text)
                print("[SUCCESS] Parsed successfully:")
                print(json.dumps(parsed, indent=2)[:500])
            except Exception as e:
                print("[FAILED] JSON parsing failed:", e)
                print("Raw response text:")
                print(text)
        else:
            print("API error:", resp.text)

if __name__ == "__main__":
    asyncio.run(test_schema())
