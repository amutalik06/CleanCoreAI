"""
CleanCore AI — RAG Engine
Retrieval-Augmented Generation for SAP-specific context injection.
Loads SAP Notes, deprecated FM mappings, CDS view replacements, and Clean Core rules.
"""
import json
import os
import logging
from typing import Dict, Any, List, Optional
from config import settings

logger = logging.getLogger("cleancore.rag_engine")


class RAGEngine:
    """Loads and retrieves SAP-specific knowledge for LLM context injection."""

    def __init__(self):
        self.knowledge: Dict[str, Any] = {}
        self._load_knowledge_base()

    def _load_knowledge_base(self):
        """Load all JSON knowledge base files."""
        kb_dir = settings.KNOWLEDGE_BASE_DIR
        self.knowledge = {
            "deprecated_tables": self._load_or_default(kb_dir, "deprecated_tables.json", self._default_tables()),
            "deprecated_fms": self._load_or_default(kb_dir, "deprecated_fms.json", self._default_fms()),
            "cds_mappings": self._load_or_default(kb_dir, "cds_mappings.json", self._default_cds()),
            "sap_notes": self._load_or_default(kb_dir, "sap_notes.json", self._default_notes()),
            "clean_core_rules": self._load_or_default(kb_dir, "clean_core_rules.json", self._default_rules()),
            "bdc_skills": self._load_or_default(kb_dir, "bdc_conversion_skills.json", {}),
        }
        logger.info(f"Knowledge base loaded: {len(self.knowledge)} categories")

    def _load_or_default(self, kb_dir: str, filename: str, default: Any) -> Any:
        filepath = os.path.join(kb_dir, filename)
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return default

    def get_context_for_finding(self, category: str, table_name: str = "", fm_name: str = "", sap_note: str = "", tcode: str = "") -> Dict[str, Any]:
        """Retrieve relevant SAP context for a specific finding category."""
        context: Dict[str, Any] = {"category": category, "rules": [], "references": [], "examples": []}

        if category in ("obsolete_table", "cluster_table") and table_name:
            tbl_info = self.knowledge["deprecated_tables"].get(table_name.upper(), {})
            if tbl_info:
                context["rules"].append(f"Table {table_name} → replace with {tbl_info.get('replacement', 'N/A')}")
                context["references"].append(f"SAP Note {tbl_info.get('note', 'N/A')}")
                context["examples"] = tbl_info.get("examples", [])
            cds = self.knowledge["cds_mappings"].get(table_name.upper(), {})
            if cds:
                context["cds_view"] = cds

        elif category == "deprecated_api" and fm_name:
            fm_info = self.knowledge["deprecated_fms"].get(fm_name, {})
            if fm_info:
                context["rules"].append(f"FM {fm_name} → replace with {fm_info.get('replacement', 'N/A')}")
                context["references"].append(f"SAP Note {fm_info.get('note', 'N/A')}")
                context["examples"] = fm_info.get("examples", [])

        elif category == "clean_core_conversion":
            # Inject BDC→BAPI conversion context from the skills knowledge base
            bdc_kb = self.knowledge.get("bdc_skills", {})
            if bdc_kb:
                # Add clean core guidelines
                for guideline in bdc_kb.get("clean_core_guidelines", []):
                    context["rules"].append(guideline)
                # Add transaction-specific mapping if tcode is provided
                if tcode:
                    for mapping in bdc_kb.get("mappings", []):
                        if mapping.get("tcode", "").upper() == tcode.upper():
                            context["rules"].append(f"{tcode} → {mapping['bapi']} ({mapping['description']})")
                            context["references"].extend([f"SAP Note {n}" for n in mapping.get("sap_notes", [])])
                            break
                # Add BDC pattern info
                patterns = bdc_kb.get("bdc_patterns", {})
                if patterns:
                    context["examples"].append(f"BDC pattern: {patterns.get('call_transaction', {}).get('pattern', '')}")

        if sap_note:
            note_info = self.knowledge["sap_notes"].get(sap_note, {})
            if note_info:
                context["sap_note_detail"] = note_info

        # Add clean core rules for category
        for rule in self.knowledge["clean_core_rules"]:
            if rule.get("category") == category:
                context["rules"].append(rule.get("rule", ""))

        return context

    def build_llm_context(self, category: str, source_snippet: str, finding_message: str, **kwargs) -> str:
        """Build compressed context string for LLM prompt injection."""
        ctx = self.get_context_for_finding(category, **kwargs)
        parts = [
            f"## SAP Migration Context for: {category}",
            f"Finding: {finding_message}",
        ]
        if ctx["rules"]:
            parts.append("### Rules:\n" + "\n".join(f"- {r}" for r in ctx["rules"]))
        if ctx["references"]:
            parts.append("### References:\n" + "\n".join(f"- {r}" for r in ctx["references"]))
        if ctx.get("cds_view"):
            parts.append(f"### CDS Replacement:\n```\n{json.dumps(ctx['cds_view'], indent=2)}\n```")
        if ctx["examples"]:
            parts.append("### Examples:\n" + "\n".join(ctx["examples"][:2]))
        return "\n\n".join(parts)

    # ─── Default Knowledge Bases ─────────────────────────────────────

    def _default_tables(self) -> Dict:
        return {
            "VBUK": {"replacement": "I_SalesDocument", "note": "2220005", "type": "cds_view",
                     "examples": ["SELECT vbeln, gbstk FROM I_SalesDocument WHERE ..."]},
            "VBUP": {"replacement": "I_SalesDocumentItem", "note": "2220005", "type": "cds_view",
                     "examples": ["SELECT vbeln, posnr, lfsta FROM I_SalesDocumentItem WHERE ..."]},
            "KONV": {"replacement": "PRCD_ELEMENTS", "note": "2267308", "type": "table",
                     "examples": ["SELECT knumv, kposn, kschl FROM prcd_elements WHERE ..."]},
            "BSEG": {"replacement": "ACDOCA", "note": "2287314", "type": "table",
                     "examples": ["SELECT bukrs, belnr, gjahr FROM acdoca WHERE ..."]},
            "BSIS": {"replacement": "I_JournalEntry", "note": "2287314", "type": "cds_view"},
            "BSAS": {"replacement": "I_JournalEntry", "note": "2287314", "type": "cds_view"},
            "BSIK": {"replacement": "I_JournalEntry", "note": "2287314", "type": "cds_view"},
            "BSAK": {"replacement": "I_JournalEntry", "note": "2287314", "type": "cds_view"},
            "BSID": {"replacement": "I_JournalEntry", "note": "2287314", "type": "cds_view"},
            "BSAD": {"replacement": "I_JournalEntry", "note": "2287314", "type": "cds_view"},
            "COEP": {"replacement": "ACDOCA", "note": "2220005", "type": "table"},
            "COBK": {"replacement": "ACDOCA", "note": "2220005", "type": "table"},
            "GLPCA": {"replacement": "ACDOCA", "note": "2287314", "type": "table"},
            "MKPF": {"replacement": "I_MaterialDocumentHeader_2", "note": "2220005", "type": "cds_view"},
            "MSEG": {"replacement": "I_MaterialDocumentItem_2", "note": "2220005", "type": "cds_view"},
            "LIPS": {"replacement": "I_DeliveryDocumentItem", "note": "2220005", "type": "cds_view"},
            "LIKP": {"replacement": "I_DeliveryDocument", "note": "2220005", "type": "cds_view"},
            "EKBE": {"replacement": "I_PurchaseOrderHistoryAPI01", "note": "2220005", "type": "cds_view"},
        }

    def _default_fms(self) -> Dict:
        return {
            "CONVERSION_EXIT_MATN1_INPUT": {"replacement": "CL_ABAP_CONV_CODEPAGE", "note": "2253265"},
            "CONVERSION_EXIT_MATN1_OUTPUT": {"replacement": "CL_ABAP_CONV_CODEPAGE", "note": "2253265"},
            "REUSE_ALV_GRID_DISPLAY": {"replacement": "CL_SALV_TABLE or RAP+Fiori Elements", "note": ""},
            "REUSE_ALV_LIST_DISPLAY": {"replacement": "CL_SALV_TABLE or RAP+Fiori Elements", "note": ""},
            "POPUP_TO_CONFIRM_WITH_MESSAGE": {"replacement": "POPUP_TO_CONFIRM", "note": ""},
            "WS_DOWNLOAD": {"replacement": "CL_GUI_FRONTEND_SERVICES=>GUI_DOWNLOAD", "note": ""},
            "WS_UPLOAD": {"replacement": "CL_GUI_FRONTEND_SERVICES=>GUI_UPLOAD", "note": ""},
        }

    def _default_cds(self) -> Dict:
        return {
            "VBUK": {"cds_view": "I_SalesDocument", "key_fields": ["SalesDocument"], "status_fields": ["OverallSDProcessStatus", "OverallDeliveryStatus"]},
            "VBUP": {"cds_view": "I_SalesDocumentItem", "key_fields": ["SalesDocument", "SalesDocumentItem"], "status_fields": ["DeliveryStatus", "BillingStatus"]},
            "BSEG": {"cds_view": "I_JournalEntryItem", "key_fields": ["CompanyCode", "FiscalYear", "AccountingDocument", "LedgerGLLineItem"]},
        }

    def _default_notes(self) -> Dict:
        return {
            "2220005": {"title": "Simplification List for S/4HANA", "description": "Master list of all simplification items"},
            "2267308": {"title": "Condition tables KONV→PRCD_ELEMENTS", "description": "Pricing condition data migration"},
            "2287314": {"title": "FI/CO table changes (BSEG→ACDOCA)", "description": "Financial accounting table consolidation"},
            "2253265": {"title": "Material number length 40 chars", "description": "MATNR extended to 40 characters"},
            "2399707": {"title": "BP migration from customer/vendor", "description": "Business Partner migration guide"},
        }

    def _default_rules(self) -> List[Dict]:
        return [
            {"category": "obsolete_table", "rule": "Replace deprecated table with CDS view or new table per SAP Note"},
            {"category": "open_sql", "rule": "Add ORDER BY PRIMARY KEY for SELECT INTO TABLE on HANA"},
            {"category": "open_sql", "rule": "Replace SELECT * with explicit field list"},
            {"category": "matnr_length", "rule": "MATNR is 40 chars in S/4HANA. Check CHAR18 references and adjust"},
            {"category": "deprecated_api", "rule": "Replace deprecated FM with modern class/method equivalent"},
            {"category": "cluster_table", "rule": "Replace cluster/pool table access with new transparent table"},
            {"category": "deprecated_statement", "rule": "Replace obsolete ABAP keywords with modern equivalents"},
            {"category": "clean_core_conversion", "rule": "Replace BDC CALL TRANSACTION with equivalent BAPI or standard API call. BDC is NOT Clean Core compliant."},
            {"category": "clean_core_conversion", "rule": "Replace classic ALV (REUSE_ALV_GRID_DISPLAY) with CL_SALV_TABLE or RAP + Fiori Elements."},
            {"category": "clean_core_conversion", "rule": "After BAPI calls, always check RETURN table for errors and call BAPI_TRANSACTION_COMMIT or ROLLBACK."},
        ]


rag_engine = RAGEngine()
