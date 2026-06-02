"""
CleanCore AI — LLM Client
Token-optimized LLM integration. Supports OpenAI, Azure OpenAI, and Ollama.
LLM is ONLY called after RAG context injection (Phase 5, Step 3).
Returns structured JSON, never free text.
"""
import json
import logging
from typing import Dict, Any, Optional
from config import settings

logger = logging.getLogger("cleancore.llm_client")


SYSTEM_PROMPT = """You are CleanCore AI, an expert SAP ABAP code migration assistant.
You help migrate SAP ECC custom ABAP code to S/4HANA Clean Core compliance.

RULES:
1. Return ONLY valid JSON — no markdown, no explanation outside JSON.
2. Provide the complete fixed ABAP code, not just the changed lines.
3. Include rationale for every change.
4. Reference SAP Notes when applicable.
5. Rate your confidence 0.0-1.0.
6. Preserve all comments and non-affected code exactly.

OUTPUT FORMAT:
{
  "fixed_code": "... complete fixed ABAP code ...",
  "changes": [{"line": N, "original": "...", "fixed": "...", "reason": "..."}],
  "rationale": "Overall explanation of changes",
  "sap_notes": ["2220005", ...],
  "confidence": 0.95,
  "warnings": ["any caveats"]
}"""


class LLMClient:
    """Token-optimized LLM client for ABAP code transformation."""

    def __init__(self):
        self.total_tokens_used = 0
        self._client = None
        self._provider = settings.LLM_PROVIDER

    async def generate_fix(
        self,
        source_code: str,
        finding_message: str,
        rag_context: str,
        category: str,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """Generate a code fix using LLM with RAG context injection.
        
        This is the LLM moment — Step 3 of the 5-step worker pipeline.
        Called ONLY after RAG has injected SAP-specific context.
        """
        # Build compressed prompt — minimize tokens
        user_prompt = self._build_prompt(source_code, finding_message, rag_context, category)

        try:
            if self._provider == "openai":
                return await self._call_openai(user_prompt, max_tokens)
            elif self._provider == "azure":
                return await self._call_azure(user_prompt, max_tokens)
            elif self._provider == "ollama":
                return await self._call_ollama(user_prompt, max_tokens)
            elif self._provider == "gemini":
                return await self._call_gemini(user_prompt, max_tokens)
            else:
                return self._fallback_response(source_code, finding_message)
        except Exception as e:
            logger.error(f"LLM call failed: {str(e)}")
            return self._fallback_response(source_code, finding_message)

    def _build_prompt(self, source_code: str, finding: str, rag_context: str, category: str) -> str:
        """Build token-optimized prompt. Only send relevant code context."""
        # Compress: send max 200 lines of relevant code
        lines = source_code.split("\n")
        if len(lines) > 200:
            source_code = "\n".join(lines[:200]) + "\n... (truncated)"

        return f"""Fix the following ABAP code issue for S/4HANA migration.

## Finding
Category: {category}
Issue: {finding}

## SAP Context (from RAG)
{rag_context}

## Source Code
```abap
{source_code}
```

Return ONLY the JSON response as specified in system instructions."""

    async def _call_openai(self, prompt: str, max_tokens: int) -> Dict[str, Any]:
        """Call OpenAI API."""
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=settings.LLM_TEMPERATURE,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            tokens = response.usage.total_tokens if response.usage else 0
            self.total_tokens_used += tokens
            result = json.loads(content)
            result["tokens_used"] = tokens
            return result
        except Exception as e:
            logger.error(f"OpenAI call failed: {e}")
            raise

    async def _call_azure(self, prompt: str, max_tokens: int) -> Dict[str, Any]:
        """Call Azure OpenAI API."""
        try:
            from openai import AsyncAzureOpenAI
            client = AsyncAzureOpenAI(
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_key=settings.AZURE_OPENAI_KEY,
                api_version="2024-06-01"
            )
            response = await client.chat.completions.create(
                model=settings.AZURE_OPENAI_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=settings.LLM_TEMPERATURE,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            tokens = response.usage.total_tokens if response.usage else 0
            self.total_tokens_used += tokens
            result = json.loads(content)
            result["tokens_used"] = tokens
            return result
        except Exception as e:
            logger.error(f"Azure OpenAI call failed: {e}")
            raise

    async def _call_ollama(self, prompt: str, max_tokens: int) -> Dict[str, Any]:
        """Call local Ollama instance."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model": settings.OLLAMA_MODEL,
                        "prompt": f"{SYSTEM_PROMPT}\n\n{prompt}",
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": settings.LLM_TEMPERATURE, "num_predict": max_tokens}
                    }
                )
                data = resp.json()
                content = data.get("response", "{}")
                result = json.loads(content)
                result["tokens_used"] = data.get("eval_count", 0)
                self.total_tokens_used += result["tokens_used"]
                return result
        except Exception as e:
            logger.error(f"Ollama call failed: {e}")
            raise

    async def _call_gemini(self, prompt: str, max_tokens: int) -> Dict[str, Any]:
        """Call Google Gemini API via HTTP REST."""
        import httpx
        try:
            api_key = settings.GEMINI_API_KEY
            model = settings.GEMINI_MODEL or "gemini-1.5-pro"
            if not api_key:
                raise ValueError("GEMINI_API_KEY is not set in configuration")

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            
            payload = {
                "contents": [
                  {
                    "parts": [{"text": prompt}]
                  }
                ],
                "systemInstruction": {
                  "parts": [{"text": SYSTEM_PROMPT}]
                },
                "generationConfig": {
                  "temperature": settings.LLM_TEMPERATURE,
                  "maxOutputTokens": max_tokens,
                  "responseMimeType": "application/json",
                  "responseSchema": {
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
                }
            }

            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, json=payload)
                
                if resp.status_code != 200:
                    logger.error(f"Gemini API returned status {resp.status_code}: {resp.text}")
                    raise RuntimeError(f"Gemini API returned HTTP {resp.status_code}")

                data = resp.json()
                
                # Extract response text
                candidates = data.get("candidates", [])
                if not candidates:
                    raise ValueError("No candidates returned from Gemini API")
                    
                content_obj = candidates[0].get("content", {})
                parts = content_obj.get("parts", [])
                if not parts:
                    raise ValueError("No parts returned in candidate content")
                    
                text_content = parts[0].get("text", "{}").strip()
                
                # Sanitize response text: strip markdown block markers if present
                if text_content.startswith("```"):
                    lines = text_content.splitlines()
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    text_content = "\n".join(lines).strip()
                
                # Load response JSON with fallback sanitization
                try:
                    result = json.loads(text_content)
                except json.JSONDecodeError as je:
                    logger.warning("Gemini returned invalid JSON. Attempting secondary sanitization: %s", je)
                    try:
                        # Attempt to replace raw backslashes and control characters that break JSON
                        cleaned_content = text_content.replace('\t', '  ')
                        result = json.loads(cleaned_content)
                    except Exception:
                        raise je
                
                usage = data.get("usageMetadata", {})
                tokens = usage.get("totalTokenCount", 0)
                self.total_tokens_used += tokens
                result["tokens_used"] = tokens
                
                return result
        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")
            raise

    def _fallback_response(self, source_code: str, finding: str) -> Dict[str, Any]:
        """Fallback when LLM is unavailable — return source unchanged with flag."""
        return {
            "fixed_code": source_code,
            "changes": [],
            "rationale": f"LLM unavailable. Manual review required for: {finding}",
            "sap_notes": [],
            "confidence": 0.0,
            "warnings": ["LLM was unavailable. This fix requires manual review."],
            "tokens_used": 0
        }


llm_client = LLMClient()
