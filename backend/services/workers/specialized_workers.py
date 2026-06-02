"""
CleanCore AI — Specialized Workers
Each worker handles a specific finding category following the 5-step contract.
"""
import re
import logging
from typing import Dict, Any
from models import WorkerInput, FixTier, FindingCategory
from services.workers.base_worker import BaseWorker
from services.rag_engine import rag_engine
from services.llm_client import llm_client
from services.workers.conversion_worker import CleanCoreConversionWorker

logger = logging.getLogger("cleancore.workers")

# ─── Table Replacement Maps ────────────────────────────────────────

TABLE_REPLACEMENTS = {
    "VBUK": "I_SalesDocument", "VBUP": "I_SalesDocumentItem",
    "BSIS": "I_JournalEntry", "BSAS": "I_JournalEntry",
    "BSIK": "I_JournalEntry", "BSAK": "I_JournalEntry",
    "BSID": "I_JournalEntry", "BSAD": "I_JournalEntry",
    "KONV": "PRCD_ELEMENTS", "BSEG": "ACDOCA",
    "COEP": "ACDOCA", "COBK": "ACDOCA",
    "GLPCA": "ACDOCA", "MKPF": "I_MaterialDocumentHeader_2",
    "MSEG": "I_MaterialDocumentItem_2",
    "LIPS": "I_DeliveryDocumentItem", "LIKP": "I_DeliveryDocument",
    "EKBE": "I_PurchaseOrderHistoryAPI01",
}

TABLE_NOTES = {
    "VBUK": "2220005", "VBUP": "2220005", "KONV": "2267308",
    "BSEG": "2287314", "BSIS": "2287314", "COEP": "2220005",
    "MKPF": "2220005", "MSEG": "2220005", "LIPS": "2220005",
    "LIKP": "2220005", "EKBE": "2220005", "GLPCA": "2287314",
}


# ═══════════════════════════════════════════════════════════════════
# OpenSQL Worker — Handles SELECT *, missing ORDER BY
# ═══════════════════════════════════════════════════════════════════

class OpenSQLWorker(BaseWorker):
    worker_type = "open_sql"

    def step2_understand(self, input_data: WorkerInput, code_region: Dict) -> Dict[str, Any]:
        stmt = code_region.get("finding_line_content", "")
        issues = []
        if re.search(r'SELECT\s+\*', stmt, re.IGNORECASE):
            issues.append("select_star")
        if "ORDER BY" not in stmt.upper() and "INTO TABLE" in stmt.upper():
            issues.append("missing_order_by")
        return {"issues": issues, "is_rule_fixable": True, "tier": FixTier.TIER1_RULE}

    async def step3_generate_fix(self, input_data: WorkerInput, code_region: Dict, understanding: Dict) -> Dict[str, Any]:
        lines = input_data.source_code.split("\n")
        fixed_lines = list(lines)
        changes = []

        for i, line in enumerate(lines):
            original_line = line
            modified = False

            # Fix SELECT *: This is a Tier 1 rule-based fix
            if re.search(r'SELECT\s+\*\s+FROM\s+(\w+)', line, re.IGNORECASE):
                # For rule-based, we add a comment indicating the developer should specify fields
                table_match = re.search(r'FROM\s+(\w+)', line, re.IGNORECASE)
                table_name = table_match.group(1) if table_match else "table"
                fixed_lines[i] = re.sub(
                    r'SELECT\s+\*',
                    f'SELECT * "TODO: Replace * with explicit fields from {table_name}',
                    line, flags=re.IGNORECASE
                )
                modified = True

            # Fix missing ORDER BY
            if (re.search(r'INTO\s+TABLE', line, re.IGNORECASE) and
                    not re.search(r'ORDER\s+BY', line, re.IGNORECASE) and
                    line.rstrip().endswith(".")):
                fixed_lines[i] = line.rstrip().rstrip(".") + "\n    ORDER BY PRIMARY KEY."
                modified = True

            if modified:
                changes.append({"line": i + 1, "original": original_line, "fixed": fixed_lines[i], "reason": "OpenSQL S/4HANA compliance"})

        return {
            "fixed_code": "\n".join(fixed_lines),
            "changes": changes,
            "rationale": "Applied OpenSQL fixes: ORDER BY for deterministic results on HANA, flagged SELECT * for field list review",
            "sap_notes": ["2220005"],
            "confidence": 0.92,
            "tier": FixTier.TIER1_RULE,
            "tokens_used": 0,
            "start_line": code_region["start_line"],
            "end_line": code_region["end_line"]
        }


# ═══════════════════════════════════════════════════════════════════
# Table Replacement Worker — Obsolete/Cluster tables → CDS Views
# ═══════════════════════════════════════════════════════════════════

class TableReplacementWorker(BaseWorker):
    worker_type = "table_replacement"

    def step2_understand(self, input_data: WorkerInput, code_region: Dict) -> Dict[str, Any]:
        tables_found = []
        # Find which tables from the replacement map are referenced in the finding region
        for table in TABLE_REPLACEMENTS:
            if (re.search(rf'\b{table}\b', code_region.get("finding_line_content", ""), re.IGNORECASE) or
                    re.search(rf'\b{table}\b', code_region.get("code_region", ""), re.IGNORECASE)):
                tables_found.append(table)
        
        if not tables_found:
            # Fallback to check entire source code
            for table in TABLE_REPLACEMENTS:
                if re.search(rf'\b{table}\b', input_data.source_code, re.IGNORECASE):
                    tables_found.append(table)

        # Table replacement is non-deterministic (requires query structural refactoring), so we use LLM (Tier 3)
        return {
            "tables": tables_found,
            "is_rule_fixable": False,
            "tier": FixTier.TIER3_LLM
        }

    async def step3_generate_fix(self, input_data: WorkerInput, code_region: Dict, understanding: Dict) -> Dict[str, Any]:
        tables = understanding.get("tables", [])
        if not tables:
            return {"fixed_code": input_data.source_code, "changes": [], "rationale": "No deprecated tables found", "sap_notes": [], "confidence": 1.0, "tier": FixTier.TIER1_RULE, "tokens_used": 0}

        if understanding.get("tier") == FixTier.TIER3_LLM:
            # Complex table — use LLM with RAG context on the specific code region
            rag_context = rag_engine.build_llm_context(
                "obsolete_table", code_region["code_region"],
                input_data.finding.message, table_name=tables[0]
            )
            # Pass only the code region to the LLM to optimize tokens and prevent truncation
            llm_result = await llm_client.generate_fix(
                code_region["code_region"], input_data.finding.message,
                rag_context, "obsolete_table"
            )
            
            # Merge the fixed region back into the original source code
            original_lines = input_data.source_code.split("\n")
            fixed_region_code = llm_result.get("fixed_code", code_region["code_region"])
            
            # Clean any markdown code block wrappers from the LLM code region if present
            fixed_region_code = fixed_region_code.strip()
            if fixed_region_code.startswith("```"):
                r_lines = fixed_region_code.splitlines()
                if r_lines[0].startswith("```"):
                    r_lines = r_lines[1:]
                if r_lines and r_lines[-1].startswith("```"):
                    r_lines = r_lines[:-1]
                fixed_region_code = "\n".join(r_lines).strip()
                
            fixed_region_lines = fixed_region_code.split("\n")
            
            start_idx = code_region["start_line"] - 1
            end_idx = code_region["end_line"]
            
            fixed_lines = original_lines[:start_idx] + fixed_region_lines + original_lines[end_idx:]
            fixed_code = "\n".join(fixed_lines)
            
            return {
                "fixed_code": fixed_code,
                "changes": llm_result.get("changes", []),
                "rationale": llm_result.get("rationale", "LLM-generated table replacement"),
                "sap_notes": llm_result.get("sap_notes", [TABLE_NOTES.get(tables[0], "")]),
                "confidence": llm_result.get("confidence", 0.75),
                "tier": FixTier.TIER3_LLM,
                "tokens_used": llm_result.get("tokens_used", 0),
                "start_line": code_region["start_line"],
                "end_line": code_region["end_line"]
            }

        # Tier 1: Simple regex replacement
        fixed_code = input_data.source_code
        changes = []
        sap_notes = []
        for table in tables:
            replacement = TABLE_REPLACEMENTS[table]
            note = TABLE_NOTES.get(table, "")
            if note: sap_notes.append(note)
            pattern = re.compile(rf'\bFROM\s+{table}\b', re.IGNORECASE)
            if pattern.search(fixed_code):
                fixed_code = pattern.sub(f'FROM {replacement}', fixed_code)
                changes.append({"table": table, "replacement": replacement, "reason": f"Deprecated in S/4HANA (Note {note})"})

        return {
            "fixed_code": fixed_code,
            "changes": changes,
            "rationale": f"Replaced deprecated tables: {', '.join(f'{t}→{TABLE_REPLACEMENTS[t]}' for t in tables)}",
            "sap_notes": list(set(sap_notes)),
            "confidence": 0.90,
            "tier": FixTier.TIER1_RULE,
            "tokens_used": 0,
            "start_line": code_region["start_line"],
            "end_line": code_region["end_line"]
        }


# ═══════════════════════════════════════════════════════════════════
# Deprecated API Worker — Obsolete FMs → Modern replacements
# ═══════════════════════════════════════════════════════════════════

class DeprecatedAPIWorker(BaseWorker):
    worker_type = "deprecated_api"

    FM_REPLACEMENTS = {
        "POPUP_TO_CONFIRM_WITH_MESSAGE": "POPUP_TO_CONFIRM",
        "WS_DOWNLOAD": "CL_GUI_FRONTEND_SERVICES=>GUI_DOWNLOAD",
        "WS_UPLOAD": "CL_GUI_FRONTEND_SERVICES=>GUI_UPLOAD",
        "REUSE_ALV_GRID_DISPLAY": "CL_SALV_TABLE",
        "REUSE_ALV_LIST_DISPLAY": "CL_SALV_TABLE",
    }

    def step2_understand(self, input_data: WorkerInput, code_region: Dict) -> Dict[str, Any]:
        fms_found = []
        for fm in self.FM_REPLACEMENTS:
            if fm.upper() in input_data.source_code.upper():
                fms_found.append(fm)
        needs_llm = len(fms_found) == 0  # Unknown FM — needs LLM
        return {"fms": fms_found, "is_rule_fixable": not needs_llm, "tier": FixTier.TIER3_LLM if needs_llm else FixTier.TIER2_TEMPLATE}

    async def step3_generate_fix(self, input_data: WorkerInput, code_region: Dict, understanding: Dict) -> Dict[str, Any]:
        if understanding.get("tier") == FixTier.TIER3_LLM:
            rag_context = rag_engine.build_llm_context(
                "deprecated_api", code_region["code_region"],
                input_data.finding.message, fm_name=input_data.finding.check_id
            )
            llm_result = await llm_client.generate_fix(
                input_data.source_code, input_data.finding.message,
                rag_context, "deprecated_api"
            )
            return {**llm_result, "tier": FixTier.TIER3_LLM,
                    "start_line": code_region["start_line"], "end_line": code_region["end_line"]}

        # Tier 2: Template-based replacement
        fixed_code = input_data.source_code
        changes = []
        for fm in understanding.get("fms", []):
            replacement = self.FM_REPLACEMENTS[fm]
            # Add TODO comment for developer to review
            fixed_code = fixed_code.replace(
                f"'{fm}'",
                f"'{fm}' \"TODO: Replace with {replacement}"
            )
            changes.append({"fm": fm, "replacement": replacement})

        return {
            "fixed_code": fixed_code,
            "changes": changes,
            "rationale": f"Flagged deprecated FMs for replacement: {', '.join(understanding.get('fms', []))}",
            "sap_notes": [],
            "confidence": 0.85,
            "tier": FixTier.TIER2_TEMPLATE,
            "tokens_used": 0,
            "start_line": code_region["start_line"],
            "end_line": code_region["end_line"]
        }


# ═══════════════════════════════════════════════════════════════════
# MATNR Length Worker — 18→40 char material number
# ═══════════════════════════════════════════════════════════════════

class MATNRLengthWorker(BaseWorker):
    worker_type = "matnr_length"

    def step2_understand(self, input_data: WorkerInput, code_region: Dict) -> Dict[str, Any]:
        # Check for hardcoded CHAR18 references to MATNR
        has_hardcoded = bool(re.search(r'TYPE\s+C\s+LENGTH\s+18', input_data.source_code, re.IGNORECASE))
        return {"has_hardcoded": has_hardcoded, "tier": FixTier.TIER1_RULE}

    async def step3_generate_fix(self, input_data: WorkerInput, code_region: Dict, understanding: Dict) -> Dict[str, Any]:
        fixed_code = input_data.source_code
        changes = []

        # Fix hardcoded CHAR(18) for material numbers
        fixed_code = re.sub(
            r'(DATA[:\s]+\s*\w*matnr\w*\s+TYPE\s+)C\s+LENGTH\s+18',
            r'\1MATNR',
            fixed_code, flags=re.IGNORECASE
        )
        if fixed_code != input_data.source_code:
            changes.append({"reason": "Replaced hardcoded CHAR(18) with TYPE MATNR for 40-char compatibility"})

        return {
            "fixed_code": fixed_code,
            "changes": changes,
            "rationale": "MATNR extended to 40 characters in S/4HANA. Replaced hardcoded lengths with MATNR data element.",
            "sap_notes": ["2253265"],
            "confidence": 0.95,
            "tier": FixTier.TIER1_RULE,
            "tokens_used": 0,
            "start_line": code_region["start_line"],
            "end_line": code_region["end_line"]
        }


# ═══════════════════════════════════════════════════════════════════
# Deprecated Statement Worker — Obsolete ABAP syntax
# ═══════════════════════════════════════════════════════════════════

class DeprecatedStatementWorker(BaseWorker):
    worker_type = "deprecated_statement"

    STMT_RULES = [
        (r'\bMOVE\s+(\S+)\s+TO\s+(\S+)\s*\.', r'\2 = \1.', "MOVE...TO → assignment operator"),
        (r'\bCOMPUTE\s+(\S+)\s*=\s*(.+?)\.', r'\1 = \2.', "COMPUTE → direct assignment"),
        (r'\bADD\s+(\S+)\s+TO\s+(\S+)\s*\.', r'\2 = \2 + \1.', "ADD...TO → + operator"),
        (r'\bSUBTRACT\s+(\S+)\s+FROM\s+(\S+)\s*\.', r'\2 = \2 - \1.', "SUBTRACT → - operator"),
        (r'\bMULTIPLY\s+(\S+)\s+BY\s+(\S+)\s*\.', r'\1 = \1 * \2.', "MULTIPLY → * operator"),
        (r'\bDIVIDE\s+(\S+)\s+BY\s+(\S+)\s*\.', r'\1 = \1 / \2.', "DIVIDE → / operator"),
    ]

    def step2_understand(self, input_data: WorkerInput, code_region: Dict) -> Dict[str, Any]:
        return {"is_rule_fixable": True, "tier": FixTier.TIER1_RULE}

    async def step3_generate_fix(self, input_data: WorkerInput, code_region: Dict, understanding: Dict) -> Dict[str, Any]:
        fixed_code = input_data.source_code
        changes = []

        for pattern, replacement, reason in self.STMT_RULES:
            new_code = re.sub(pattern, replacement, fixed_code, flags=re.IGNORECASE)
            if new_code != fixed_code:
                changes.append({"reason": reason})
                fixed_code = new_code

        return {
            "fixed_code": fixed_code,
            "changes": changes,
            "rationale": "Replaced obsolete ABAP statements with modern equivalents",
            "sap_notes": [],
            "confidence": 0.95,
            "tier": FixTier.TIER1_RULE,
            "tokens_used": 0,
            "start_line": code_region["start_line"],
            "end_line": code_region["end_line"]
        }


# ═══════════════════════════════════════════════════════════════════
# Validation Worker — Post-fix validation
# ═══════════════════════════════════════════════════════════════════

class ValidationWorker:
    """Validates fixed code against original for correctness."""

    def validate(self, original: str, fixed: str) -> Dict[str, Any]:
        issues = []
        orig_lines = original.split("\n")
        fixed_lines = fixed.split("\n")

        # Check for unbalanced structures
        for kw_open, kw_close in [("IF", "ENDIF"), ("LOOP", "ENDLOOP"),
                                   ("DO", "ENDDO"), ("FORM", "ENDFORM"),
                                   ("METHOD", "ENDMETHOD"), ("CLASS", "ENDCLASS")]:
            o_count = sum(1 for l in fixed_lines if l.strip().upper().startswith(kw_open + " ") or l.strip().upper() == kw_open + ".")
            c_count = sum(1 for l in fixed_lines if l.strip().upper().startswith(kw_close))
            if o_count != c_count:
                issues.append(f"Unbalanced {kw_open}/{kw_close}: {o_count} opens vs {c_count} closes")

        # Check no data was lost (line count shouldn't drop dramatically)
        if len(fixed_lines) < len(orig_lines) * 0.5:
            issues.append(f"Significant code reduction: {len(orig_lines)}→{len(fixed_lines)} lines")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "original_lines": len(orig_lines),
            "fixed_lines": len(fixed_lines)
        }


# ─── Worker Registry ───────────────────────────────────────────────

WORKER_REGISTRY: Dict[str, BaseWorker] = {
    FindingCategory.OPEN_SQL: OpenSQLWorker(),
    FindingCategory.MISSING_ORDER_BY: OpenSQLWorker(),
    FindingCategory.SELECT_STAR: OpenSQLWorker(),
    FindingCategory.OBSOLETE_TABLE: TableReplacementWorker(),
    FindingCategory.CLUSTER_TABLE: TableReplacementWorker(),
    FindingCategory.DEPRECATED_API: DeprecatedAPIWorker(),
    FindingCategory.MATNR_LENGTH: MATNRLengthWorker(),
    FindingCategory.DEPRECATED_STATEMENT: DeprecatedStatementWorker(),
    FindingCategory.DATA_TYPE: MATNRLengthWorker(),
    FindingCategory.CLEAN_CORE_CONVERSION: CleanCoreConversionWorker(),
}

validation_worker = ValidationWorker()
