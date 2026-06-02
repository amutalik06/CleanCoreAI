"""
CleanCore AI — BDC Skills Engine
Deterministic, template-based BDC → BAPI/API conversion.
Skills are the MANDATORY first step — LLM is only called when no skill matches.

Supports:
  - Transaction-to-BAPI mapping (25+ common SAP transactions)
  - Template-based ABAP code generation for BAPI wrappers
  - BDC pattern detection (CALL TRANSACTION, PERFORM bdc_*, BDCDATA)
  - SAP Note references for each conversion
"""
import re
import json
import os
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("cleancore.skills.bdc")


# ═══════════════════════════════════════════════════════════════════════
# BDC → BAPI MAPPING TABLE
# Each entry maps a SAP transaction code to its BAPI/API replacement.
# ═══════════════════════════════════════════════════════════════════════

TCODE_TO_BAPI: Dict[str, Dict[str, Any]] = {
    # ── Business Partner / Customer / Vendor ────────────────────────
    "XD01": {
        "bapi": "BAPI_BUPA_CREATE_FROM_DATA",
        "description": "Create Customer (Business Partner)",
        "domain": "Business Partner",
        "sap_notes": ["2220005", "1622868"],
        "params": {
            "exporting": ["businesspartnerextern", "partnercategory", "partnergroup"],
            "tables": ["centraldata", "centraldataperson", "centraldataorganization",
                       "addressdata", "return"],
        },
        "commit": True,
    },
    "XD02": {
        "bapi": "BAPI_BUPA_CHANGE",
        "description": "Change Customer (Business Partner)",
        "domain": "Business Partner",
        "sap_notes": ["2220005", "1622868"],
        "params": {
            "exporting": ["businesspartner"],
            "tables": ["centraldata", "centraldataorganization", "addressdata", "return"],
        },
        "commit": True,
    },
    "FD01": {
        "bapi": "BAPI_BUPA_CREATE_FROM_DATA",
        "description": "Create Customer FI (Business Partner)",
        "domain": "Business Partner",
        "sap_notes": ["2220005", "1622868"],
        "params": {
            "exporting": ["businesspartnerextern", "partnercategory"],
            "tables": ["centraldata", "addressdata", "return"],
        },
        "commit": True,
    },
    "FK01": {
        "bapi": "BAPI_BUPA_CREATE_FROM_DATA",
        "description": "Create Vendor (Business Partner)",
        "domain": "Business Partner",
        "sap_notes": ["2220005", "1622868"],
        "params": {
            "exporting": ["businesspartnerextern", "partnercategory"],
            "tables": ["centraldata", "addressdata", "return"],
        },
        "commit": True,
    },

    # ── Materials Management ────────────────────────────────────────
    "MM01": {
        "bapi": "BAPI_MATERIAL_SAVEDATA",
        "description": "Create Material Master",
        "domain": "Materials Management",
        "sap_notes": ["2220005"],
        "params": {
            "exporting": ["headdata", "clientdata", "clientdatax",
                          "plantdata", "plantdatax"],
            "importing": ["return"],
        },
        "commit": True,
    },
    "MM02": {
        "bapi": "BAPI_MATERIAL_SAVEDATA",
        "description": "Change Material Master",
        "domain": "Materials Management",
        "sap_notes": ["2220005"],
        "params": {
            "exporting": ["headdata", "clientdata", "clientdatax"],
            "importing": ["return"],
        },
        "commit": True,
    },

    # ── Purchasing ──────────────────────────────────────────────────
    "ME21N": {
        "bapi": "BAPI_PO_CREATE1",
        "description": "Create Purchase Order",
        "domain": "Purchasing",
        "sap_notes": ["2220005"],
        "params": {
            "exporting": ["poheader", "poheaderx"],
            "tables": ["poitem", "poitemx", "poschedule", "poschedulex", "return"],
        },
        "commit": True,
    },
    "ME22N": {
        "bapi": "BAPI_PO_CHANGE",
        "description": "Change Purchase Order",
        "domain": "Purchasing",
        "sap_notes": ["2220005"],
        "params": {
            "exporting": ["purchaseorder", "poheader", "poheaderx"],
            "tables": ["poitem", "poitemx", "return"],
        },
        "commit": True,
    },
    "ME51N": {
        "bapi": "BAPI_PR_CREATE",
        "description": "Create Purchase Requisition",
        "domain": "Purchasing",
        "sap_notes": ["2220005"],
        "params": {
            "exporting": ["prheader", "prheaderx"],
            "tables": ["pritem", "pritemx", "return"],
        },
        "commit": True,
    },

    # ── Sales & Distribution ────────────────────────────────────────
    "VA01": {
        "bapi": "BAPI_SALESORDER_CREATEFROMDAT2",
        "description": "Create Sales Order",
        "domain": "Sales & Distribution",
        "sap_notes": ["2220005"],
        "params": {
            "exporting": ["order_header_in", "order_header_inx"],
            "importing": ["salesdocument"],
            "tables": ["order_items_in", "order_items_inx",
                       "order_partners", "order_schedules_in", "return"],
        },
        "commit": True,
    },
    "VA02": {
        "bapi": "BAPI_SALESORDER_CHANGE",
        "description": "Change Sales Order",
        "domain": "Sales & Distribution",
        "sap_notes": ["2220005"],
        "params": {
            "exporting": ["salesdocument", "order_header_in", "order_header_inx"],
            "tables": ["order_item_in", "order_item_inx", "return"],
        },
        "commit": True,
    },

    # ── Inventory / Goods Movement ──────────────────────────────────
    "MB01": {
        "bapi": "BAPI_GOODSMVT_CREATE",
        "description": "Goods Receipt for Purchase Order",
        "domain": "Inventory Management",
        "sap_notes": ["2220005"],
        "params": {
            "exporting": ["goodsmvt_header", "goodsmvt_code"],
            "importing": ["materialdocument", "matdocumentyear"],
            "tables": ["goodsmvt_item", "return"],
        },
        "commit": True,
        "extra_notes": "goodsmvt_code = '01' for GR",
    },
    "MB1A": {
        "bapi": "BAPI_GOODSMVT_CREATE",
        "description": "Goods Issue",
        "domain": "Inventory Management",
        "sap_notes": ["2220005"],
        "params": {
            "exporting": ["goodsmvt_header", "goodsmvt_code"],
            "importing": ["materialdocument", "matdocumentyear"],
            "tables": ["goodsmvt_item", "return"],
        },
        "commit": True,
        "extra_notes": "goodsmvt_code = '03' for GI",
    },
    "MB1B": {
        "bapi": "BAPI_GOODSMVT_CREATE",
        "description": "Transfer Posting",
        "domain": "Inventory Management",
        "sap_notes": ["2220005"],
        "params": {
            "exporting": ["goodsmvt_header", "goodsmvt_code"],
            "importing": ["materialdocument", "matdocumentyear"],
            "tables": ["goodsmvt_item", "return"],
        },
        "commit": True,
        "extra_notes": "goodsmvt_code = '04' for Transfer",
    },
    "MB1C": {
        "bapi": "BAPI_GOODSMVT_CREATE",
        "description": "Other Goods Receipt",
        "domain": "Inventory Management",
        "sap_notes": ["2220005"],
        "params": {
            "exporting": ["goodsmvt_header", "goodsmvt_code"],
            "importing": ["materialdocument", "matdocumentyear"],
            "tables": ["goodsmvt_item", "return"],
        },
        "commit": True,
        "extra_notes": "goodsmvt_code = '01' for GR (other)",
    },
    "MIGO": {
        "bapi": "BAPI_GOODSMVT_CREATE",
        "description": "Goods Movement (General)",
        "domain": "Inventory Management",
        "sap_notes": ["2220005"],
        "params": {
            "exporting": ["goodsmvt_header", "goodsmvt_code"],
            "importing": ["materialdocument", "matdocumentyear"],
            "tables": ["goodsmvt_item", "return"],
        },
        "commit": True,
    },

    # ── Finance ─────────────────────────────────────────────────────
    "FB01": {
        "bapi": "BAPI_ACC_DOCUMENT_POST",
        "description": "Post FI Document",
        "domain": "Finance",
        "sap_notes": ["2220005", "2287314"],
        "params": {
            "exporting": ["documentheader"],
            "tables": ["accountgl", "accountpayable", "accountreceivable",
                       "currencyamount", "return"],
        },
        "commit": True,
    },
    "FB60": {
        "bapi": "BAPI_ACC_DOCUMENT_POST",
        "description": "Enter Vendor Invoice",
        "domain": "Finance",
        "sap_notes": ["2220005", "2287314"],
        "params": {
            "exporting": ["documentheader"],
            "tables": ["accountgl", "accountpayable", "currencyamount", "return"],
        },
        "commit": True,
    },
    "FB70": {
        "bapi": "BAPI_ACC_DOCUMENT_POST",
        "description": "Enter Customer Invoice",
        "domain": "Finance",
        "sap_notes": ["2220005", "2287314"],
        "params": {
            "exporting": ["documentheader"],
            "tables": ["accountgl", "accountreceivable", "currencyamount", "return"],
        },
        "commit": True,
    },

    # ── Delivery ────────────────────────────────────────────────────
    "VL01N": {
        "bapi": "BAPI_OUTB_DELIVERY_CREATE_SLS",
        "description": "Create Outbound Delivery",
        "domain": "Logistics Execution",
        "sap_notes": ["2220005"],
        "params": {
            "exporting": ["ship_point", "due_date"],
            "importing": ["delivery"],
            "tables": ["sales_order_items", "return"],
        },
        "commit": True,
    },

    # ── Billing ─────────────────────────────────────────────────────
    "VF01": {
        "bapi": "BAPI_BILLINGDOC_CREATEMULTIPLE",
        "description": "Create Billing Document",
        "domain": "Billing",
        "sap_notes": ["2220005"],
        "params": {
            "tables": ["billingdatain", "return"],
        },
        "commit": True,
    },
}


# Movement type codes for goods movement transactions
GOODS_MOVEMENT_CODES = {
    "MB01": "01",   # Goods Receipt
    "MB1A": "03",   # Goods Issue
    "MB1B": "04",   # Transfer Posting
    "MB1C": "01",   # Other GR
    "MIGO": "01",   # General (default GR)
}


class BDCSkillsEngine:
    """
    Deterministic BDC → BAPI conversion using skills (templates + mappings).

    This is the mandatory first step in the conversion pipeline.
    If a transaction code is found in the mapping table, a complete
    BAPI wrapper is generated WITHOUT calling the LLM (0 tokens).
    """

    def __init__(self):
        self._mappings = dict(TCODE_TO_BAPI)
        self._load_external_mappings()

    def _load_external_mappings(self):
        """Load additional mappings from knowledge_base if available."""
        kb_path = os.path.join(os.path.dirname(__file__), "..", "..", "knowledge_base", "bdc_conversion_skills.json")
        if os.path.exists(kb_path):
            try:
                with open(kb_path, "r", encoding="utf-8") as f:
                    external = json.load(f)
                    for entry in external.get("mappings", []):
                        tcode = entry.get("tcode", "").upper()
                        if tcode and tcode not in self._mappings:
                            self._mappings[tcode] = entry
                    logger.info(f"Loaded {len(external.get('mappings', []))} external BDC skill mappings")
            except Exception as e:
                logger.warning(f"Failed to load external BDC mappings: {e}")

    def can_handle(self, tcode: str) -> bool:
        """Check if the skills engine can handle this transaction code."""
        return tcode.upper() in self._mappings

    def get_mapping(self, tcode: str) -> Optional[Dict[str, Any]]:
        """Get the BAPI mapping for a transaction code."""
        return self._mappings.get(tcode.upper())

    def extract_tcode_from_source(self, source_code: str, finding_line: int) -> Optional[str]:
        """Extract the transaction code from CALL TRANSACTION at a given line."""
        lines = source_code.split("\n")
        if finding_line < 1 or finding_line > len(lines):
            return None

        # Check the finding line and nearby lines (±3)
        start = max(0, finding_line - 4)
        end = min(len(lines), finding_line + 3)

        for i in range(start, end):
            line = lines[i].strip()
            match = re.search(r"CALL\s+TRANSACTION\s+'(\w+)'", line, re.IGNORECASE)
            if match:
                return match.group(1).upper()

        return None

    def extract_all_tcodes_in_region(self, source_code: str, start_line: int, end_line: int) -> List[str]:
        """Extract all transaction codes in a code region."""
        lines = source_code.split("\n")
        tcodes = []
        for i in range(max(0, start_line - 1), min(len(lines), end_line)):
            match = re.search(r"CALL\s+TRANSACTION\s+'(\w+)'", lines[i], re.IGNORECASE)
            if match:
                tcodes.append(match.group(1).upper())
        return tcodes

    def generate_bapi_replacement(
        self,
        tcode: str,
        original_line: str,
        code_region: str,
        source_code: str,
        finding_line: int
    ) -> Dict[str, Any]:
        """
        Generate a complete BAPI wrapper replacement for a BDC CALL TRANSACTION.

        Returns dict with: fixed_code, rationale, sap_notes, confidence, changes
        """
        mapping = self._mappings.get(tcode.upper())
        if not mapping:
            return {"handled": False}

        bapi_name = mapping["bapi"]
        description = mapping["description"]
        domain = mapping.get("domain", "")
        sap_notes = mapping.get("sap_notes", [])
        params = mapping.get("params", {})
        needs_commit = mapping.get("commit", True)
        extra_notes = mapping.get("extra_notes", "")

        # Build the BAPI replacement code
        bapi_code = self._build_bapi_code(tcode, bapi_name, params, needs_commit, description, extra_notes)

        # Replace the CALL TRANSACTION line(s) in the source code
        fixed_code = self._apply_fix_to_source(source_code, finding_line, original_line, bapi_code, tcode)

        rationale = (
            f"Skills-based conversion: Replaced BDC CALL TRANSACTION '{tcode}' "
            f"({description}) with {bapi_name}. "
            f"Domain: {domain}. "
            f"This is a Clean Core compliant replacement that eliminates "
            f"screen-based automation in favor of a direct API call."
        )
        if extra_notes:
            rationale += f" Note: {extra_notes}"

        return {
            "handled": True,
            "fixed_code": fixed_code,
            "rationale": rationale,
            "sap_notes": sap_notes,
            "confidence": 0.85,
            "changes": [{
                "line": finding_line,
                "original": original_line.strip(),
                "fixed": f"CALL FUNCTION '{bapi_name}' ... (see full code)",
                "reason": f"BDC '{tcode}' → {bapi_name} ({description})"
            }],
        }

    def _build_bapi_code(
        self,
        tcode: str,
        bapi_name: str,
        params: Dict[str, Any],
        needs_commit: bool,
        description: str,
        extra_notes: str
    ) -> str:
        """Build complete BAPI wrapper ABAP code."""
        lines = []
        lines.append(f'* ── Clean Core Conversion: {tcode} → {bapi_name} ──')
        lines.append(f'* {description}')
        lines.append(f'* Converted from BDC CALL TRANSACTION by CleanCore AI Skills Engine')
        if extra_notes:
            lines.append(f'* Note: {extra_notes}')
        lines.append('')

        # Data declarations
        lines.append('    DATA lt_return TYPE TABLE OF bapiret2.')
        lines.append('    DATA ls_return TYPE bapiret2.')

        exporting = params.get("exporting", [])
        importing = params.get("importing", [])
        tables = params.get("tables", [])

        # Declare structures for exporting params (exclude return)
        for param in exporting:
            struct_type = self._infer_structure_type(bapi_name, param)
            lines.append(f'    DATA ls_{param} TYPE {struct_type}.')

        # Declare structures for importing params
        for param in importing:
            if param != "return":
                struct_type = self._infer_structure_type(bapi_name, param)
                lines.append(f'    DATA lv_{param} TYPE {struct_type}.')

        # Declare tables (exclude return)
        for param in tables:
            if param != "return":
                struct_type = self._infer_structure_type(bapi_name, param)
                lines.append(f'    DATA lt_{param} TYPE TABLE OF {struct_type}.')

        lines.append('')
        lines.append(f'    \"TODO: Populate the BAPI parameters with the values')
        lines.append(f'    \"      that were previously mapped via BDC screen fields.')
        lines.append(f'    \"      Review the original BDC field mappings above for reference.')
        lines.append('')

        # Special handling for goods movement codes
        gm_code = GOODS_MOVEMENT_CODES.get(tcode)
        if gm_code and "goodsmvt_code" in exporting:
            lines.append(f"    ls_goodsmvt_code-gm_code = '{gm_code}'.  \"Movement type for {tcode}")
            lines.append('')

        # Build CALL FUNCTION
        lines.append(f"    CALL FUNCTION '{bapi_name}'")

        # EXPORTING
        if exporting:
            lines.append('      EXPORTING')
            for i, param in enumerate(exporting):
                comma = '' if i == len(exporting) - 1 and not importing and not tables else ''
                lines.append(f'        {param} = ls_{param}')

        # IMPORTING
        if importing:
            lines.append('      IMPORTING')
            for param in importing:
                if param != "return":
                    lines.append(f'        {param} = lv_{param}')

        # TABLES
        non_return_tables = [t for t in tables if t != "return"]
        if non_return_tables or "return" in tables:
            lines.append('      TABLES')
            for param in non_return_tables:
                lines.append(f'        {param} = lt_{param}')
            if "return" in tables:
                lines.append(f'        return = lt_return')

        lines.append('      .')  # End CALL FUNCTION

        # Error handling
        lines.append('')
        lines.append('    \"── Check BAPI return messages ──')
        lines.append('    LOOP AT lt_return INTO ls_return WHERE type CA \'EA\'.')
        lines.append(f'      WRITE: / \'Error in {bapi_name}:\', ls_return-message.')
        lines.append('    ENDLOOP.')
        lines.append('')

        # Commit
        if needs_commit:
            lines.append('    IF NOT line_exists( lt_return[ type = \'E\' ] ).')
            lines.append("      CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'")
            lines.append('        EXPORTING')
            lines.append("          wait = abap_true.")
            lines.append('    ELSE.')
            lines.append("      CALL FUNCTION 'BAPI_TRANSACTION_ROLLBACK'.")
            lines.append('    ENDIF.')

        return '\n'.join(lines)

    def _infer_structure_type(self, bapi_name: str, param_name: str) -> str:
        """Infer the ABAP structure type for a BAPI parameter."""
        # Known type mappings for common BAPIs
        known_types = {
            # Goods Movement
            ("BAPI_GOODSMVT_CREATE", "goodsmvt_header"): "BAPI2017_GM_HEAD_01",
            ("BAPI_GOODSMVT_CREATE", "goodsmvt_code"): "BAPI2017_GM_CODE",
            ("BAPI_GOODSMVT_CREATE", "goodsmvt_item"): "BAPI2017_GM_ITEM_CREATE",
            ("BAPI_GOODSMVT_CREATE", "materialdocument"): "BAPI2017_GM_HEAD_RET-MAT_DOC",
            ("BAPI_GOODSMVT_CREATE", "matdocumentyear"): "BAPI2017_GM_HEAD_RET-DOC_YEAR",
            # Sales Order
            ("BAPI_SALESORDER_CREATEFROMDAT2", "order_header_in"): "BAPISDHD1",
            ("BAPI_SALESORDER_CREATEFROMDAT2", "order_header_inx"): "BAPISDHD1X",
            ("BAPI_SALESORDER_CREATEFROMDAT2", "order_items_in"): "BAPISDITM",
            ("BAPI_SALESORDER_CREATEFROMDAT2", "order_items_inx"): "BAPISDITMX",
            ("BAPI_SALESORDER_CREATEFROMDAT2", "order_partners"): "BAPIPARNR",
            ("BAPI_SALESORDER_CREATEFROMDAT2", "order_schedules_in"): "BAPISCHDL",
            ("BAPI_SALESORDER_CREATEFROMDAT2", "salesdocument"): "BAPI_VBELN-VBELN",
            # Sales Order Change
            ("BAPI_SALESORDER_CHANGE", "salesdocument"): "BAPI_VBELN-VBELN",
            ("BAPI_SALESORDER_CHANGE", "order_header_in"): "BAPISDH1",
            ("BAPI_SALESORDER_CHANGE", "order_header_inx"): "BAPISDH1X",
            ("BAPI_SALESORDER_CHANGE", "order_item_in"): "BAPISDITM",
            ("BAPI_SALESORDER_CHANGE", "order_item_inx"): "BAPISDITMX",
            # Purchase Order
            ("BAPI_PO_CREATE1", "poheader"): "BAPIMEPOHEADER",
            ("BAPI_PO_CREATE1", "poheaderx"): "BAPIMEPOHEADERX",
            ("BAPI_PO_CREATE1", "poitem"): "BAPIMEPOITEM",
            ("BAPI_PO_CREATE1", "poitemx"): "BAPIMEPOITEMX",
            ("BAPI_PO_CREATE1", "poschedule"): "BAPIMEPOSCHEDULE",
            ("BAPI_PO_CREATE1", "poschedulex"): "BAPIMEPOSCHEDULX",
            # PO Change
            ("BAPI_PO_CHANGE", "purchaseorder"): "BAPIMEPOHEADER-PO_NUMBER",
            ("BAPI_PO_CHANGE", "poheader"): "BAPIMEPOHEADER",
            ("BAPI_PO_CHANGE", "poheaderx"): "BAPIMEPOHEADERX",
            ("BAPI_PO_CHANGE", "poitem"): "BAPIMEPOITEM",
            ("BAPI_PO_CHANGE", "poitemx"): "BAPIMEPOITEMX",
            # PR Create
            ("BAPI_PR_CREATE", "prheader"): "BAPIMEREQHEADER",
            ("BAPI_PR_CREATE", "prheaderx"): "BAPIMEREQHEADERX",
            ("BAPI_PR_CREATE", "pritem"): "BAPIMEREQITEM",
            ("BAPI_PR_CREATE", "pritemx"): "BAPIMEREQITEMX",
            # Material
            ("BAPI_MATERIAL_SAVEDATA", "headdata"): "BAPIMATHEAD",
            ("BAPI_MATERIAL_SAVEDATA", "clientdata"): "BAPI_MARA",
            ("BAPI_MATERIAL_SAVEDATA", "clientdatax"): "BAPI_MARAX",
            ("BAPI_MATERIAL_SAVEDATA", "plantdata"): "BAPI_MARC",
            ("BAPI_MATERIAL_SAVEDATA", "plantdatax"): "BAPI_MARCX",
            ("BAPI_MATERIAL_SAVEDATA", "return"): "BAPIRET2",
            # BP
            ("BAPI_BUPA_CREATE_FROM_DATA", "businesspartnerextern"): "BU_PARTNER",
            ("BAPI_BUPA_CREATE_FROM_DATA", "partnercategory"): "BU_TYPE",
            ("BAPI_BUPA_CREATE_FROM_DATA", "partnergroup"): "BU_GROUP",
            ("BAPI_BUPA_CREATE_FROM_DATA", "centraldata"): "BAPIBUS1006_CENTRAL",
            ("BAPI_BUPA_CREATE_FROM_DATA", "centraldataperson"): "BAPIBUS1006_CENTRAL_PERSON",
            ("BAPI_BUPA_CREATE_FROM_DATA", "centraldataorganization"): "BAPIBUS1006_CENTRAL_ORGAN",
            ("BAPI_BUPA_CREATE_FROM_DATA", "addressdata"): "BAPIBUS1006_ADDRESS",
            # BP Change
            ("BAPI_BUPA_CHANGE", "businesspartner"): "BU_PARTNER",
            ("BAPI_BUPA_CHANGE", "centraldata"): "BAPIBUS1006_CENTRAL",
            ("BAPI_BUPA_CHANGE", "centraldataorganization"): "BAPIBUS1006_CENTRAL_ORGAN",
            ("BAPI_BUPA_CHANGE", "addressdata"): "BAPIBUS1006_ADDRESS",
            # FI Document
            ("BAPI_ACC_DOCUMENT_POST", "documentheader"): "BAPIACHE09",
            ("BAPI_ACC_DOCUMENT_POST", "accountgl"): "BAPIACGL09",
            ("BAPI_ACC_DOCUMENT_POST", "accountpayable"): "BAPIACAP09",
            ("BAPI_ACC_DOCUMENT_POST", "accountreceivable"): "BAPIACAR09",
            ("BAPI_ACC_DOCUMENT_POST", "currencyamount"): "BAPIACCR09",
            # Delivery
            ("BAPI_OUTB_DELIVERY_CREATE_SLS", "ship_point"): "BAPIDLVCREATEHEADER-SHIP_POINT",
            ("BAPI_OUTB_DELIVERY_CREATE_SLS", "due_date"): "BAPIDLVCREATEHEADER-DUE_DATE",
            ("BAPI_OUTB_DELIVERY_CREATE_SLS", "delivery"): "BAPISHPDELIVNUMB-DELIV_NUMB",
            ("BAPI_OUTB_DELIVERY_CREATE_SLS", "sales_order_items"): "BAPIDLVCREATEITEM",
            # Billing
            ("BAPI_BILLINGDOC_CREATEMULTIPLE", "billingdatain"): "BAPIVBRK",
        }

        key = (bapi_name, param_name)
        if key in known_types:
            return known_types[key]

        # Fallback: generic type inference from param name
        param_upper = param_name.upper()
        if "return" in param_name.lower():
            return "BAPIRET2"
        if "header" in param_name.lower():
            return f"BAPI_{bapi_name.replace('BAPI_', '').split('_')[0]}_HEADER"

        # Ultimate fallback
        return f"\"TODO: Look up type for {param_name} in SE37 → {bapi_name}"

    def _apply_fix_to_source(
        self,
        source_code: str,
        finding_line: int,
        original_line: str,
        bapi_code: str,
        tcode: str
    ) -> str:
        """Replace the CALL TRANSACTION line with BAPI code in the full source."""
        lines = source_code.split("\n")

        # Find the exact line with CALL TRANSACTION for this tcode
        target_idx = None
        for i in range(max(0, finding_line - 3), min(len(lines), finding_line + 2)):
            if re.search(rf"CALL\s+TRANSACTION\s+'{tcode}'", lines[i], re.IGNORECASE):
                target_idx = i
                break

        if target_idx is None:
            # Fallback: search by finding_line
            target_idx = finding_line - 1

        if target_idx < 0 or target_idx >= len(lines):
            return source_code

        # Check if the CALL TRANSACTION spans multiple lines (ends with '.')
        end_idx = target_idx
        if not lines[target_idx].rstrip().rstrip('\r').endswith('.'):
            for j in range(target_idx + 1, min(len(lines), target_idx + 5)):
                end_idx = j
                if lines[j].rstrip().rstrip('\r').endswith('.'):
                    break

        # Comment out the original BDC line(s) and insert BAPI code
        commented_lines = []
        for i in range(target_idx, end_idx + 1):
            commented_lines.append(f'*   {lines[i]}  \"Replaced by Clean Core BAPI conversion')

        bapi_lines = bapi_code.split("\n")
        replacement = commented_lines + [''] + bapi_lines

        fixed_lines = lines[:target_idx] + replacement + lines[end_idx + 1:]
        return "\n".join(fixed_lines)

    def get_supported_tcodes(self) -> List[str]:
        """Return list of all supported transaction codes."""
        return sorted(self._mappings.keys())

    def get_mapping_summary(self, tcode: str) -> Optional[str]:
        """Get a human-readable summary of the mapping for a tcode."""
        mapping = self._mappings.get(tcode.upper())
        if not mapping:
            return None
        return f"{tcode} → {mapping['bapi']} ({mapping['description']})"


# Singleton instance
bdc_skills = BDCSkillsEngine()
