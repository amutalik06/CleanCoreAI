"""
CleanCore AI — ABAP Parser
Parses ABAP source code into structured AST-like representation.
"""
import re
import logging
from typing import List, Dict, Any
from models import ABAPParseResult

logger = logging.getLogger("cleancore.abap_parser")

OBSOLETE_TABLES = {
    "VBUK": {"replacement": "I_SalesDocument", "note": "2220005"},
    "VBUP": {"replacement": "I_SalesDocumentItem", "note": "2220005"},
    "BSIS": {"replacement": "I_JournalEntry", "note": "2287314"},
    "BSAS": {"replacement": "I_JournalEntry", "note": "2287314"},
    "BSIK": {"replacement": "I_JournalEntry", "note": "2287314"},
    "BSAK": {"replacement": "I_JournalEntry", "note": "2287314"},
    "BSID": {"replacement": "I_JournalEntry", "note": "2287314"},
    "BSAD": {"replacement": "I_JournalEntry", "note": "2287314"},
    "KONV": {"replacement": "PRCD_ELEMENTS", "note": "2267308"},
    "BSEG": {"replacement": "ACDOCA", "note": "2287314"},
    "COEP": {"replacement": "ACDOCA", "note": "2220005"},
    "MKPF": {"replacement": "I_MaterialDocumentHeader_2", "note": "2220005"},
    "MSEG": {"replacement": "I_MaterialDocumentItem_2", "note": "2220005"},
    "GLPCA": {"replacement": "ACDOCA", "note": "2287314"},
    "LIPS": {"replacement": "I_DeliveryDocumentItem", "note": "2220005"},
    "LIKP": {"replacement": "I_DeliveryDocument", "note": "2220005"},
    "EKBE": {"replacement": "I_PurchaseOrderHistoryAPI01", "note": "2220005"},
}

DEPRECATED_STMTS = [
    (r"\bOCCURS\b", "OCCURS is obsolete. Use standard tables."),
    (r"\bHEADER LINE\b", "HEADER LINE is obsolete. Use separate work area."),
    (r"\bMOVE\b\s+\S+\s+TO\b", "MOVE...TO is obsolete. Use = operator."),
    (r"\bCOMPUTE\b", "COMPUTE is obsolete. Use direct assignment."),
    (r"\bMULTIPLY\b", "MULTIPLY is obsolete. Use * operator."),
    (r"\bDIVIDE\b", "DIVIDE is obsolete. Use / operator."),
    (r"\bADD\b\s+\S+\s+TO\b", "ADD...TO is obsolete. Use + operator."),
    (r"\bSUBTRACT\b", "SUBTRACT is obsolete. Use - operator."),
]


class ABAPParser:
    """Parses ABAP source code and extracts structural info for migration analysis."""

    def parse(self, source_code: str, object_name: str = "UNKNOWN") -> ABAPParseResult:
        result = ABAPParseResult(object_name=object_name)
        lines = source_code.split("\n")
        try:
            result.select_statements = self._extract_selects(source_code, lines)
            result.tables_used = self._extract_tables(source_code)
            result.function_modules_called = self._extract_fm_calls(source_code)
            result.classes_used = self._extract_class_usage(source_code)
            result.data_declarations = self._extract_data_decls(lines)
            result.bdc_calls = self._extract_bdc(lines)
            result.alv_calls = self._extract_alv(lines)
            result.statements = self._extract_deprecated(lines)
        except Exception as e:
            result.errors.append(f"Parse error: {str(e)}")
            logger.error(f"Parse failed for {object_name}: {e}")
        return result

    def _extract_selects(self, source: str, lines: List[str]) -> List[Dict[str, Any]]:
        selects = []
        pat = re.compile(r'(SELECT\s+.*?(?:ENDSELECT|\.)\s*)', re.IGNORECASE | re.DOTALL)
        for match in pat.finditer(source):
            stmt = match.group(1)
            line_num = source[:match.start()].count("\n") + 1
            info: Dict[str, Any] = {"line": line_num, "statement": stmt.strip()[:500], "issues": []}
            if re.search(r'SELECT\s+\*', stmt, re.IGNORECASE):
                info["issues"].append({"type": "select_star", "message": "Replace SELECT * with explicit fields", "priority": "P2"})
            if re.search(r'INTO\s+TABLE', stmt, re.IGNORECASE) and not re.search(r'ORDER\s+BY', stmt, re.IGNORECASE):
                info["issues"].append({"type": "missing_order_by", "message": "SELECT INTO TABLE without ORDER BY", "priority": "P1"})
            from_m = re.search(r'FROM\s+(\w+)', stmt, re.IGNORECASE)
            if from_m:
                tbl = from_m.group(1).upper()
                info["table"] = tbl
                if tbl in OBSOLETE_TABLES:
                    r = OBSOLETE_TABLES[tbl]
                    info["issues"].append({"type": "obsolete_table", "message": f"{tbl} deprecated → {r['replacement']}", "replacement": r["replacement"], "sap_note": r["note"], "priority": "P1"})
            if info["issues"]:
                selects.append(info)
        return selects

    def _extract_tables(self, source: str) -> List[str]:
        tables = set()
        for m in re.finditer(r'FROM\s+(\w+)', source, re.IGNORECASE): tables.add(m.group(1).upper())
        for m in re.finditer(r'JOIN\s+(\w+)', source, re.IGNORECASE): tables.add(m.group(1).upper())
        for m in re.finditer(r'(?:UPDATE|INSERT\s+INTO|DELETE\s+FROM|MODIFY)\s+(\w+)', source, re.IGNORECASE): tables.add(m.group(1).upper())
        return sorted(tables)

    def _extract_fm_calls(self, source: str) -> List[str]:
        return sorted({m.group(1) for m in re.finditer(r"CALL\s+FUNCTION\s+'([^']+)'", source, re.IGNORECASE)})

    def _extract_class_usage(self, source: str) -> List[str]:
        c = set()
        for m in re.finditer(r'(?:CREATE\s+OBJECT|TYPE\s+REF\s+TO)\s+(\w+)', source, re.IGNORECASE): c.add(m.group(1))
        for m in re.finditer(r'(\w+)=>(\w+)', source): c.add(m.group(1))
        return sorted(c)

    def _extract_data_decls(self, lines: List[str]) -> List[Dict[str, Any]]:
        decls = []
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if s.startswith("*") or s.startswith('"'): continue
            m = re.match(r'DATA[:\s]+\s*(\w+)\s+TYPE\s+(\w+)', s, re.IGNORECASE)
            if m:
                vtype = m.group(2).upper()
                if vtype == "MATNR":
                    decls.append({"line": i, "variable": m.group(1), "type": vtype, "issues": [{"type": "matnr_length", "message": "MATNR is 40 chars in S/4HANA", "sap_note": "2253265", "priority": "P1"}]})
        return decls

    def _extract_bdc(self, lines: List[str]) -> List[Dict[str, Any]]:
        calls = []
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if re.search(r'CALL\s+TRANSACTION\s+', s, re.IGNORECASE):
                tc = re.search(r"CALL\s+TRANSACTION\s+'?(\w+)'?", s, re.IGNORECASE)
                calls.append({"line": i, "type": "call_transaction", "tcode": tc.group(1) if tc else "?", "statement": s[:200]})
            elif re.search(r'BDC_INSERT|BDCDATA|BDC_FIELD', s, re.IGNORECASE):
                calls.append({"line": i, "type": "bdc_processing", "statement": s[:200]})
        return calls

    def _extract_alv(self, lines: List[str]) -> List[Dict[str, Any]]:
        calls = []
        pats = [(r"REUSE_ALV_GRID_DISPLAY", "classic_alv"), (r"REUSE_ALV_LIST_DISPLAY", "classic_alv_list"),
                (r"CL_SALV_TABLE", "salv"), (r"CL_GUI_ALV_GRID", "gui_alv"), (r"REUSE_ALV_FIELDCATALOG_MERGE", "fieldcat")]
        for i, line in enumerate(lines, 1):
            for p, t in pats:
                if re.search(p, line, re.IGNORECASE):
                    calls.append({"line": i, "type": t, "statement": line.strip()[:200]})
        return calls

    def _extract_deprecated(self, lines: List[str]) -> List[Dict[str, Any]]:
        stmts = []
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if s.startswith("*") or s.startswith('"'): continue
            for pat, msg in DEPRECATED_STMTS:
                if re.search(pat, s, re.IGNORECASE):
                    stmts.append({"line": i, "type": "deprecated_statement", "message": msg, "statement": s[:200]})
        return stmts


abap_parser = ABAPParser()
