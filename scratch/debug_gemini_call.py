import sys
import os
import asyncio
import httpx
import json

backend_dir = r"c:\Users\AnilMutalik\OneDrive - Motiveminds Consulting Pvt Ltd\Desktop\CleanCore AI\backend"
sys.path.insert(0, backend_dir)

from config import settings
from services.llm_client import SYSTEM_PROMPT

async def test_debug():
    print("Debugging raw Gemini API response for VBUK...")
    
    # Load program source code
    with open(os.path.join(backend_dir, "fixture_source.abap"), "r", encoding="utf-8") as f:
        source_code = f.read()
        
    api_key = settings.GEMINI_API_KEY
    model = settings.GEMINI_MODEL or "gemini-3.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    # Recreate the prompt that would be sent to Gemini
    finding_message = "DB Operation SELECT found (VBUK, see Note(s):0002198647)"
    rag_context = "Prerequisites: VBUK is deprecated. Replace VBUK with I_SalesDocument."
    category = "obsolete_table"
    
    # Compress prompt
    lines = source_code.split("\n")
    if len(lines) > 200:
        source_code = "\n".join(lines[:200]) + "\n... (truncated)"
        
    prompt = f"""Fix the following ABAP code issue for S/4HANA migration.

## Finding
Category: {category}
Issue: {finding_message}

## SAP Context (from RAG)
{rag_context}

## Source Code
```abap
{source_code}
```

Return ONLY the JSON response as specified in system instructions."""

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
    
    payload = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ],
        "systemInstruction": {
            "parts": [{"text": SYSTEM_PROMPT}]
        },
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
            "responseSchema": schema
        }
    }
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json=payload)
        print(f"HTTP Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("candidates", [])
            text = candidates[0]["content"]["parts"][0]["text"]
            print("Raw text returned:")
            print("--------------------------------------------------")
            print(repr(text))
            print("--------------------------------------------------")
            try:
                json.loads(text)
                print("[SUCCESS] JSON is valid!")
            except Exception as e:
                print(f"[FAILED] JSON parsing failed: {e}")
        else:
            print("Error:", resp.text)

if __name__ == "__main__":
    asyncio.run(test_debug())
