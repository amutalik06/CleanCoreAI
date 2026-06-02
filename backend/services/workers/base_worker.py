"""
CleanCore AI — Base Worker
Abstract base implementing the 5-step worker contract:
  Step 1: Parse — Extract relevant code region
  Step 2: Understand — Classify the issue
  Step 3: Retrieve Context + Generate Fix — RAG injection → (optional) LLM call
  Step 4: Self-Validate — Verify the fix is syntactically sound
  Step 5: Return — Package result with confidence score
"""
import difflib
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from models import WorkerInput, WorkerOutput, FixTier

logger = logging.getLogger("cleancore.worker")


class BaseWorker(ABC):
    """Abstract base for all remediation workers."""

    worker_type: str = "base"

    async def execute(self, input_data: WorkerInput) -> WorkerOutput:
        """Execute the 5-step pipeline. This is the contract every worker follows."""

        # Step 1: Parse — extract the relevant code region
        code_region = self.step1_parse(input_data)

        # Step 2: Understand — classify the issue and determine fix strategy
        understanding = self.step2_understand(input_data, code_region)

        # Step 3: Retrieve Context + Generate Fix
        #   For Tier 1: deterministic rule application (zero tokens)
        #   For Tier 2: template + local model (minimal tokens)
        #   For Tier 3: RAG context → LLM call (optimized tokens)
        fix_result = await self.step3_generate_fix(input_data, code_region, understanding)

        # Step 4: Self-Validate — check fix is syntactically valid
        validation = self.step4_validate(input_data, fix_result)

        # Step 5: Return — package result
        return self.step5_return(input_data, fix_result, validation)

    def step1_parse(self, input_data: WorkerInput) -> Dict[str, Any]:
        """Extract relevant code region around the finding."""
        lines = input_data.source_code.split("\n")
        finding_line = input_data.finding.line
        # Extract context window: 10 lines before and after
        start = max(0, finding_line - 11)
        end = min(len(lines), finding_line + 10)
        return {
            "lines": lines,
            "start_line": start + 1,
            "end_line": end,
            "code_region": "\n".join(lines[start:end]),
            "finding_line": finding_line,
            "finding_line_content": lines[finding_line - 1] if finding_line <= len(lines) else ""
        }

    @abstractmethod
    def step2_understand(self, input_data: WorkerInput, code_region: Dict) -> Dict[str, Any]:
        """Classify the issue and determine fix strategy. Returns understanding dict."""
        pass

    @abstractmethod
    async def step3_generate_fix(self, input_data: WorkerInput, code_region: Dict, understanding: Dict) -> Dict[str, Any]:
        """Generate the fix. Tier 1 = rules, Tier 2 = templates, Tier 3 = LLM."""
        pass

    def step4_validate(self, input_data: WorkerInput, fix_result: Dict) -> Dict[str, Any]:
        """Basic validation: ensure fix doesn't break obvious syntax."""
        fixed_code = fix_result.get("fixed_code", "")
        original = input_data.source_code
        messages = []
        passed = True

        if not fixed_code or fixed_code.strip() == "":
            passed = False
            messages.append("Fix produced empty code")

        if fixed_code.strip() == original.strip():
            passed = False
            messages.append("Fix produced identical code — no changes made")

        # Check balanced keywords
        for kw_open, kw_close in [("IF", "ENDIF"), ("LOOP", "ENDLOOP"), ("DO", "ENDDO"),
                                   ("SELECT", "ENDSELECT"), ("FORM", "ENDFORM"), ("METHOD", "ENDMETHOD")]:
            opens = len([l for l in fixed_code.upper().split("\n") if l.strip().startswith(kw_open) and not l.strip().startswith(kw_close)])
            closes = len([l for l in fixed_code.upper().split("\n") if l.strip().startswith(kw_close)])
            # Only flag if we had balanced before and now don't
            orig_opens = len([l for l in original.upper().split("\n") if l.strip().startswith(kw_open) and not l.strip().startswith(kw_close)])
            orig_closes = len([l for l in original.upper().split("\n") if l.strip().startswith(kw_close)])
            if orig_opens == orig_closes and opens != closes:
                messages.append(f"Unbalanced {kw_open}/{kw_close} after fix")
                passed = False

        return {"passed": passed, "messages": messages}

    def step5_return(self, input_data: WorkerInput, fix_result: Dict, validation: Dict) -> WorkerOutput:
        """Package the final result."""
        original = input_data.source_code
        fixed = fix_result.get("fixed_code", original)

        # Generate unified diff
        diff = difflib.unified_diff(
            original.split("\n"),
            fixed.split("\n"),
            fromfile="original",
            tofile="fixed",
            lineterm=""
        )
        diff_patch = "\n".join(diff)

        confidence = fix_result.get("confidence", 0.5)
        if not validation["passed"]:
            confidence = min(confidence, 0.4)

        return WorkerOutput(
            finding_id=input_data.finding.id,
            worker_type=self.worker_type,
            original_code=original,
            fixed_code=fixed,
            diff_patch=diff_patch,
            rationale=fix_result.get("rationale", ""),
            sap_note_refs=fix_result.get("sap_notes", []),
            confidence=confidence,
            tier=fix_result.get("tier", FixTier.TIER1_RULE),
            tokens_used=fix_result.get("tokens_used", 0),
            line_range=(fix_result.get("start_line", 0), fix_result.get("end_line", 0)),
            validation_passed=validation["passed"],
            validation_messages=validation["messages"]
        )
