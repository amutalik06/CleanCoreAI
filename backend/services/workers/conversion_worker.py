"""
CleanCore AI — Conversion Worker (Skills-First Architecture)
Handles complex SAP to Clean Core conversions:
  - BDC → BAPI/API  (Skills Engine: Tier 2 template → LLM fallback: Tier 3)
  - ALV → RAP       (LLM: Tier 3)
  - Module Pool → Fiori (LLM: Tier 3)

Skills are the MANDATORY first step. The LLM is only called when the
skills engine cannot handle the specific pattern. This dramatically
reduces token usage for common BDC→BAPI conversions (0 tokens for 25+ tcodes).
"""
import re
import logging
from typing import Dict, Any, Optional
from models import WorkerInput, FixTier
from services.workers.base_worker import BaseWorker
from services.skills.bdc_skills import bdc_skills
from services.rag_engine import rag_engine
from services.llm_client import llm_client

logger = logging.getLogger("cleancore.workers.conversion")


class CleanCoreConversionWorker(BaseWorker):
    """
    Skills-first conversion worker.

    Pipeline for BDC findings:
      1. Parse — extract code region around the finding
      2. Understand — detect tcode, check if skills engine can handle it
      3. Generate Fix:
         a. Tier 2 (Skills): If tcode is in mapping → deterministic BAPI template (0 tokens)
         b. Tier 3 (LLM): If tcode unknown → RAG context + LLM on code region only
      4. Validate — check balanced keywords, non-empty diff
      5. Return — package result with confidence + tier badge
    """
    worker_type = "clean_core_conversion"

    def step2_understand(self, input_data: WorkerInput, code_region: Dict) -> Dict[str, Any]:
        """Classify the conversion and determine if skills can handle it."""
        check_id = input_data.finding.check_id
        conversion_type = "Complex Legacy Conversion"
        tcode = None
        skill_available = False

        if check_id == "bdc_usage":
            conversion_type = "BDC (Batch Data Communication) to BAPI/API"

            # Extract transaction code from the finding line
            tcode = bdc_skills.extract_tcode_from_source(
                input_data.source_code,
                input_data.finding.line
            )

            if tcode and bdc_skills.can_handle(tcode):
                skill_available = True
                mapping = bdc_skills.get_mapping(tcode)
                logger.info(
                    f"BDC Skills Engine: tcode '{tcode}' → {mapping['bapi']} "
                    f"(Tier 2, 0 tokens)"
                )
            else:
                logger.info(
                    f"BDC Skills Engine: tcode '{tcode or '?'}' not in mapping — "
                    f"will use Tier 3 LLM with RAG context"
                )

        elif check_id == "alv_usage":
            conversion_type = "Classic ALV to RAP (Restful ABAP Programming)"
        elif check_id == "module_pool":
            conversion_type = "Module Pool to SAP Fiori Elements"

        return {
            "conversion_type": conversion_type,
            "check_id": check_id,
            "tcode": tcode,
            "skill_available": skill_available,
            "is_rule_fixable": skill_available,
            "tier": FixTier.TIER2_TEMPLATE if skill_available else FixTier.TIER3_LLM,
        }

    async def step3_generate_fix(
        self,
        input_data: WorkerInput,
        code_region: Dict,
        understanding: Dict
    ) -> Dict[str, Any]:
        """
        Generate the fix using skills first, LLM as fallback.

        Skills-first means:
          1. Check if the BDC Skills Engine can handle this tcode
          2. If yes → generate BAPI wrapper template (Tier 2, 0 tokens)
          3. If no → inject RAG context and call LLM on CODE REGION ONLY (Tier 3, optimized tokens)
        """
        tcode = understanding.get("tcode")
        skill_available = understanding.get("skill_available", False)

        # ── Tier 2: Skills-based conversion (MANDATORY first check) ──
        if skill_available and tcode:
            return self._generate_skill_fix(input_data, code_region, tcode)

        # ── Tier 3: LLM with RAG context (fallback for unknown patterns) ──
        return await self._generate_llm_fix(input_data, code_region, understanding)

    def _generate_skill_fix(
        self,
        input_data: WorkerInput,
        code_region: Dict,
        tcode: str
    ) -> Dict[str, Any]:
        """Generate fix using the BDC Skills Engine (Tier 2 — zero tokens)."""
        original_line = code_region.get("finding_line_content", "")

        result = bdc_skills.generate_bapi_replacement(
            tcode=tcode,
            original_line=original_line,
            code_region=code_region.get("code_region", ""),
            source_code=input_data.source_code,
            finding_line=input_data.finding.line,
        )

        if result.get("handled"):
            logger.info(
                f"Skills Engine converted BDC '{tcode}' → BAPI "
                f"(confidence={result['confidence']}, tokens=0)"
            )
            return {
                "fixed_code": result["fixed_code"],
                "changes": result.get("changes", []),
                "rationale": result["rationale"],
                "sap_notes": result.get("sap_notes", ["2220005"]),
                "confidence": result.get("confidence", 0.85),
                "tier": FixTier.TIER2_TEMPLATE,
                "tokens_used": 0,
                "start_line": code_region["start_line"],
                "end_line": code_region["end_line"],
            }

        # Skills engine couldn't handle — should not happen if skill_available was True
        logger.warning(f"Skills Engine reported can_handle=True for '{tcode}' but generate failed")
        return self._generate_guidance_fallback(input_data, code_region, tcode)

    async def _generate_llm_fix(
        self,
        input_data: WorkerInput,
        code_region: Dict,
        understanding: Dict
    ) -> Dict[str, Any]:
        """Generate fix using LLM with RAG context injection (Tier 3)."""
        conversion_type = understanding.get("conversion_type", "Complex Legacy Conversion")
        tcode = understanding.get("tcode", "")
        check_id = understanding.get("check_id", "")

        # Build RAG context for the LLM
        rag_context = rag_engine.build_llm_context(
            "clean_core_conversion",
            code_region["code_region"],
            input_data.finding.message,
            tcode=tcode,
        )

        # Build conversion-specific prompt
        prompt_context = f"""
## Architectural Conversion Task
Type: {conversion_type}
{f"Transaction Code: {tcode}" if tcode else ""}

## SAP Context (Skills Knowledge Base)
{rag_context}

## Supported BAPI Mappings for Reference
{self._get_nearby_mappings(tcode)}

## INSTRUCTIONS
You must refactor this legacy SAP code to adhere strictly to S/4HANA Clean Core Guidelines.
- If BDC → Identify the mapped fields, remove CALL TRANSACTION / SUBMIT,
  and provide the equivalent BAPI or standard API call wrapper.
  Include BAPI_TRANSACTION_COMMIT and error handling via RETURN table.
- If ALV → Provide a conceptual stub or the required ABAP class for
  an OData exposure (RAP behavior definition / projection).
- If Module Pool → Extract the core logic into an API endpoint / Class Method
  ready to be consumed by Fiori.

Ensure you preserve any critical business logic.
"""

        try:
            # Send ONLY the code region to the LLM to optimize tokens
            llm_result = await llm_client.generate_fix(
                code_region["code_region"],
                input_data.finding.message,
                prompt_context,
                "clean_core_conversion",
                max_tokens=4096,
            )

            # Merge the fixed region back into the original source code
            fixed_region_code = llm_result.get("fixed_code", code_region["code_region"])

            # Clean any markdown code block wrappers
            fixed_region_code = fixed_region_code.strip()
            if fixed_region_code.startswith("```"):
                r_lines = fixed_region_code.splitlines()
                if r_lines[0].startswith("```"):
                    r_lines = r_lines[1:]
                if r_lines and r_lines[-1].startswith("```"):
                    r_lines = r_lines[:-1]
                fixed_region_code = "\n".join(r_lines).strip()

            # Merge back into full source
            original_lines = input_data.source_code.split("\n")
            fixed_region_lines = fixed_region_code.split("\n")
            start_idx = code_region["start_line"] - 1
            end_idx = code_region["end_line"]
            fixed_lines = original_lines[:start_idx] + fixed_region_lines + original_lines[end_idx:]
            fixed_code = "\n".join(fixed_lines)

            logger.info(
                f"LLM converted {conversion_type} "
                f"(confidence={llm_result.get('confidence', 0.70)}, "
                f"tokens={llm_result.get('tokens_used', 0)})"
            )

            return {
                "fixed_code": fixed_code,
                "changes": llm_result.get("changes", []),
                "rationale": llm_result.get("rationale",
                    f"LLM-generated architectural refactoring: {conversion_type}"),
                "sap_notes": llm_result.get("sap_notes", ["Clean Core Guidelines", "2220005"]),
                "confidence": llm_result.get("confidence", 0.70),
                "tier": FixTier.TIER3_LLM,
                "tokens_used": llm_result.get("tokens_used", 0),
                "start_line": code_region["start_line"],
                "end_line": code_region["end_line"],
            }

        except Exception as e:
            logger.error(f"LLM fix generation failed for {conversion_type}: {e}")
            # Instead of returning unchanged code, generate guidance
            return self._generate_guidance_fallback(input_data, code_region, tcode)

    def _generate_guidance_fallback(
        self,
        input_data: WorkerInput,
        code_region: Dict,
        tcode: Optional[str]
    ) -> Dict[str, Any]:
        """
        When both skills and LLM fail, generate actionable guidance
        instead of returning unchanged code.
        """
        finding_line = input_data.finding.line
        lines = input_data.source_code.split("\n")
        fixed_lines = list(lines)

        # Find and comment the BDC line, adding guidance
        target_idx = finding_line - 1
        if 0 <= target_idx < len(fixed_lines):
            original_stmt = fixed_lines[target_idx]
            guidance_lines = [
                f'* ── CleanCore AI: Manual BDC Conversion Required ──',
                f'* Original: {original_stmt.strip()}',
                f'*',
            ]

            if tcode:
                # Try to find a similar tcode for guidance
                similar = self._find_similar_tcodes(tcode)
                if similar:
                    guidance_lines.append(f'* Suggested BAPI: Review {similar} for a similar pattern.')
                guidance_lines.append(f'* Transaction {tcode} needs manual BAPI mapping.')
                guidance_lines.append(f'* Steps:')
                guidance_lines.append(f'*   1. Identify the BAPI equivalent for tcode {tcode} (check SE37)')
                guidance_lines.append(f'*   2. Map BDC screen fields to BAPI parameters')
                guidance_lines.append(f'*   3. Add BAPI_TRANSACTION_COMMIT and error handling')
            else:
                guidance_lines.append(f'* BDC processing code needs conversion to BAPI/API calls.')

            guidance_lines.append(f'* Refer to SAP Note 2220005 (Simplification List)')
            guidance_lines.append(f'*')

            fixed_lines[target_idx] = '\n'.join(guidance_lines) + '\n' + original_stmt

        return {
            "fixed_code": "\n".join(fixed_lines),
            "changes": [{"line": finding_line, "original": lines[target_idx].strip() if target_idx < len(lines) else "", "fixed": "Added conversion guidance comments", "reason": "BDC conversion guidance"}],
            "rationale": f"LLM unavailable and no skills mapping for tcode '{tcode or '?'}'. "
                         f"Added inline guidance comments for manual conversion. "
                         f"Refer to SAP Note 2220005.",
            "sap_notes": ["2220005"],
            "confidence": 0.30,
            "tier": FixTier.TIER2_TEMPLATE,
            "tokens_used": 0,
            "start_line": code_region["start_line"],
            "end_line": code_region["end_line"],
        }

    def _get_nearby_mappings(self, tcode: Optional[str]) -> str:
        """Get similar BAPI mappings for context when LLM is needed."""
        if not tcode:
            return "No specific transaction code detected."

        # Get a few related mappings from the skills engine
        all_tcodes = bdc_skills.get_supported_tcodes()
        summaries = []
        for tc in all_tcodes[:10]:  # Limit to reduce prompt size
            summary = bdc_skills.get_mapping_summary(tc)
            if summary:
                summaries.append(f"- {summary}")

        if summaries:
            return "Known BAPI mappings (for reference):\n" + "\n".join(summaries)
        return "No nearby BAPI mappings available."

    def _find_similar_tcodes(self, tcode: str) -> Optional[str]:
        """Find a similar supported tcode for guidance."""
        # Check if a variant of the tcode is supported (e.g., ME21N → ME22N)
        prefix = tcode[:2]
        for tc in bdc_skills.get_supported_tcodes():
            if tc.startswith(prefix) and tc != tcode:
                mapping = bdc_skills.get_mapping(tc)
                if mapping:
                    return f"{tc} → {mapping['bapi']}"
        return None
