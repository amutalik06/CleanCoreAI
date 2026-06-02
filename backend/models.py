"""
CleanCore AI — Pydantic Models
All data contracts for the Code Remediation Engine.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime
import uuid


# ─── Enums ───────────────────────────────────────────────────────────

class AnalysisStatus(str, Enum):
    PENDING = "pending"
    CONNECTING = "connecting"
    EXTRACTING = "extracting"
    PARSING = "parsing"
    ANALYZING = "analyzing"
    GENERATING_FIXES = "generating_fixes"
    VALIDATING = "validating"
    MERGING = "merging"
    COMPLETE = "complete"
    FAILED = "failed"


class FindingPriority(str, Enum):
    P1 = "P1"  # Syntax-breaking — must fix
    P2 = "P2"  # Functional impact — should fix
    P3 = "P3"  # Clean Core compliance — nice to fix


class FindingCategory(str, Enum):
    OPEN_SQL = "open_sql"
    DEPRECATED_API = "deprecated_api"
    OBSOLETE_TABLE = "obsolete_table"
    MATNR_LENGTH = "matnr_length"
    CLUSTER_TABLE = "cluster_table"
    MISSING_ORDER_BY = "missing_order_by"
    SELECT_STAR = "select_star"
    DEPRECATED_STATEMENT = "deprecated_statement"
    KEY_USER_EXIT = "key_user_exit"
    DATA_TYPE = "data_type"
    CLEAN_CORE_CONVERSION = "clean_core_conversion"
    GENERIC = "generic"


class FixStatus(str, Enum):
    GENERATED = "generated"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"
    APPLIED = "applied"
    FAILED = "failed"


class FixTier(str, Enum):
    TIER1_RULE = "tier1_rule"       # Deterministic rule — zero tokens
    TIER2_TEMPLATE = "tier2_template"  # Template + local — minimal tokens
    TIER3_LLM = "tier3_llm"        # Cloud LLM — optimized tokens


class InputSource(str, Enum):
    SAP_RFC = "sap_rfc"
    FILE_UPLOAD = "file_upload"


# ─── SAP Connection ─────────────────────────────────────────────────

class SAPConnectionConfig(BaseModel):
    # RFC fields — optional when using ADT-only mode
    ashost: Optional[str] = Field(default="", description="Application server host (RFC only)")
    sysnr: str = Field(default="00", description="System number")
    client: str = Field(default="100", description="SAP client")
    user: str = Field(..., description="SAP user")
    passwd: str = Field(..., description="Password")
    lang: str = Field(default="EN", description="Login language")
    saprouter: Optional[str] = Field(default=None, description="SAP Router string")

    # ADT REST API (primary connection mode for private/cloud S/4HANA)
    use_adt_fallback: bool = Field(default=False, description="Show RFC fallback fields in UI (legacy flag)")
    adt_url: Optional[str] = Field(default=None, description="ADT base URL (e.g., https://my-s4hana.com:44300)")
    adt_verify_ssl: bool = Field(default=False, description="Verify SSL certificate for ADT connection")


class SAPConnectionStatus(BaseModel):
    connected: bool
    system_id: Optional[str] = None
    system_name: Optional[str] = None
    release: Optional[str] = None
    host: Optional[str] = None
    message: str = ""


# ─── ABAP Code Objects ──────────────────────────────────────────────

class ABAPObject(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    type: str  # PROG, FUGR, CLAS, INTF, TABL, etc.
    package: Optional[str] = None
    source_code: str
    line_count: int = 0
    source: InputSource = InputSource.FILE_UPLOAD


class ABAPParseResult(BaseModel):
    object_name: str
    statements: List[Dict[str, Any]] = []
    tokens: List[Dict[str, Any]] = []
    tables_used: List[str] = []
    function_modules_called: List[str] = []
    classes_used: List[str] = []
    select_statements: List[Dict[str, Any]] = []
    data_declarations: List[Dict[str, Any]] = []
    bdc_calls: List[Dict[str, Any]] = []
    alv_calls: List[Dict[str, Any]] = []
    errors: List[str] = []


# ─── ATC Findings ───────────────────────────────────────────────────

class ATCFinding(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    object_name: str
    object_type: Optional[str] = "PROG"
    package_name: Optional[str] = ""
    check_id: str
    check_title: str
    message: str
    line: int
    column: int = 0
    priority: FindingPriority
    category: FindingCategory
    sap_note: Optional[str] = None
    quick_fix_available: bool = False
    raw_data: Optional[Dict[str, Any]] = None


# ─── Worker Contract ────────────────────────────────────────────────

class WorkerInput(BaseModel):
    finding: ATCFinding
    source_code: str
    parse_result: ABAPParseResult
    rag_context: Optional[Dict[str, Any]] = None


class WorkerOutput(BaseModel):
    finding_id: str
    worker_type: str
    original_code: str
    fixed_code: str
    diff_patch: str
    rationale: str
    sap_note_refs: List[str] = []
    confidence: float = Field(ge=0.0, le=1.0)
    tier: FixTier
    tokens_used: int = 0
    line_range: tuple = (0, 0)
    validation_passed: bool = False
    validation_messages: List[str] = []


# ─── Fix / Patch ────────────────────────────────────────────────────

class CodeFix(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    finding_id: str
    object_name: str
    worker_type: str
    category: FindingCategory
    priority: FindingPriority
    original_code: str
    fixed_code: str
    diff_html: str = ""
    rationale: str
    sap_note_refs: List[str] = []
    confidence: float
    tier: FixTier
    tokens_used: int = 0
    status: FixStatus = FixStatus.PENDING_REVIEW
    requires_human_review: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FixApprovalRequest(BaseModel):
    action: str  # approve | reject | modify
    modified_code: Optional[str] = None
    comment: Optional[str] = None
    approved_by: str = "developer"


# ─── Analysis Session ───────────────────────────────────────────────

class AnalysisSession(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: InputSource
    object_name: str
    status: AnalysisStatus = AnalysisStatus.PENDING
    progress: float = 0.0
    current_step: str = ""
    source_code: str = ""
    parse_result: Optional[ABAPParseResult] = None
    findings: List[ATCFinding] = []
    fixes: List[CodeFix] = []
    total_findings: int = 0
    fixes_generated: int = 0
    fixes_approved: int = 0
    fixes_rejected: int = 0
    human_review_count: int = 0
    tokens_used: int = 0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    audit_log: List[Dict[str, Any]] = []

# ─── SAP ATC & Package Explorer Models ────────────────────────────────

class SAPATCResult(BaseModel):
    id: str
    title: str
    timestamp: datetime
    object_set: Optional[str] = None
    findings_count: Optional[int] = 0


class SAPPackageObject(BaseModel):
    name: str
    type: str
    package: str
    uri: Optional[str] = None
    adt_type: Optional[str] = None
    description: Optional[str] = None
    source_supported: bool = True


class AnalyzePackageObjectsRequest(BaseModel):
    objects: List[Dict[str, str]]


# ─── API Response Models ────────────────────────────────────────────

class ProgressUpdate(BaseModel):
    session_id: str
    status: AnalysisStatus
    progress: float
    current_step: str
    message: str = ""
    findings_count: int = 0
    fixes_count: int = 0


class AnalysisResult(BaseModel):
    session: AnalysisSession
    summary: Dict[str, Any] = {}


class FileUploadRequest(BaseModel):
    filename: str
    content: str
    object_type: str = "PROG"
