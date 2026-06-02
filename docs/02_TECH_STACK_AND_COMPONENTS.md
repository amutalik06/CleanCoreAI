# CleanCore AI — Technical Stack & Component Deep-Dive

---

## 1. Recommended Technical Stack

### 1.1 Primary Stack (Node.js — Recommended)

| Layer | Technology | Rationale |
|---|---|---|
| **Frontend** | React 18 + SAP UI5 Web Components + Vite | SAP Fiori Horizon look; enterprise-grade; reusable |
| **API Server** | NestJS (TypeScript) | Modular, scalable, decorator-based; great for enterprise |
| **Job Queue** | BullMQ + Redis | Reliable background jobs for code extraction/analysis |
| **Database** | PostgreSQL 16 + Prisma ORM | JSONB for flexible code storage; strong ecosystem |
| **Cache** | Redis 7 | Semantic cache for LLM responses + job queue |
| **Object Storage** | MinIO (S3-compatible) | Store code snapshots, diffs, audit exports |
| **SAP Connectivity** | `node-rfc` + SAP NW RFC SDK | Direct RFC calls to ECC/S4; proven library |
| **Real-time** | Socket.io | Live progress bars, phase status updates |
| **Auth** | Keycloak or SAP IAS | SSO, RBAC for developer/approver/admin roles |
| **Containerization** | Docker + Docker Compose / K8s Helm | Easy customer deployment |
| **CI/CD** | GitHub Actions / Jenkins | Automated testing + container builds |

### 1.2 Alternative Stack (Python — For AI-Heavy Scenarios)

| Layer | Technology |
|---|---|
| **API** | FastAPI + Uvicorn |
| **Job Queue** | Celery + Redis |
| **SAP Connectivity** | `pyrfc` |
| **AI/ML** | LangChain + Ollama + HuggingFace Transformers |
| **Database** | PostgreSQL + SQLAlchemy |

> [!TIP]
> **Recommendation:** Use **Node.js (NestJS)** as the primary stack. It provides superior real-time capabilities (WebSocket), native `node-rfc` integration, and TypeScript safety. Use Python only as a microservice sidecar for heavy AI/ML processing if needed.

---

## 2. AI & Token Optimization Strategy

### 2.1 Three-Tier Processing Model

```
┌─────────────────────────────────────────────────────────────┐
│                 AI Processing Pipeline                       │
│                                                              │
│  ┌─────────────────┐  80% of fixes     Zero tokens          │
│  │  TIER 1: Rules  │  ──────────────►  (Free)               │
│  │  Deterministic   │  Table mappings, SELECT fixes,         │
│  │  Rule Engine     │  MATNR length, syntax patterns         │
│  └────────┬────────┘                                         │
│           │ Complex cases only (20%)                         │
│  ┌────────▼────────┐  15% of fixes     Low tokens            │
│  │  TIER 2: Local  │  ──────────────►  (Self-hosted)         │
│  │  AST + Templates│  Pattern detection, template gen,       │
│  │  + Local LLM    │  RAP boilerplate, BDC→BAPI mapping     │
│  └────────┬────────┘                                         │
│           │ Truly complex (5%)                               │
│  ┌────────▼────────┐  5% of fixes      Optimized tokens     │
│  │  TIER 3: Cloud  │  ──────────────►  (Paid API)            │
│  │  LLM API        │  Complex refactoring, business logic    │
│  │  (GPT-4/Claude) │  understanding, natural language docs   │
│  └─────────────────┘                                         │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Token Optimization Techniques

| Technique | Implementation | Token Savings |
|---|---|---|
| **Semantic Cache** | Redis + vector embeddings; cache similar code fix patterns | 40-60% reduction |
| **Prompt Compression** | Send only relevant code sections, not entire programs | 50-70% reduction |
| **Batch Processing** | Group similar fixes (e.g., all MATNR fixes) into one prompt | 30-40% reduction |
| **Template Prefilling** | Pre-fill known patterns; LLM only fills gaps | 60% reduction |
| **Model Routing** | Route simple→cheap model, complex→powerful model | 50% cost reduction |
| **Few-Shot Caching** | Cache ABAP-specific examples; reuse across projects | 20-30% reduction |
| **Incremental Context** | Summarize prior context; don't resend full history | 40% reduction |

### 2.3 Pre-Built Rule Catalog (Tier 1 — Zero Tokens)

```json
{
  "rules": [
    {
      "id": "R001",
      "category": "obsolete_table",
      "pattern": "SELECT * FROM VBUK",
      "replacement": "SELECT * FROM I_SalesDocumentItem",
      "note": "SAP Note 2220005"
    },
    {
      "id": "R002",
      "category": "matnr_length",
      "pattern": "DATA: lv_matnr TYPE MATNR.",
      "fix": "Ensure 40-char compatibility",
      "note": "SAP Note 2253265"
    },
    {
      "id": "R003",
      "category": "cluster_table",
      "pattern": "SELECT FROM KONV",
      "replacement": "SELECT FROM PRCD_ELEMENTS",
      "note": "SAP Note 2267308"
    },
    {
      "id": "R004",
      "category": "select_fix",
      "pattern": "SELECT ... INTO TABLE ... FROM ... (no ORDER BY)",
      "fix": "Add explicit ORDER BY PRIMARY KEY",
      "note": "S/4HANA Simplification"
    }
  ]
}
```

> [!IMPORTANT]
> **Cost Estimate:** With the 3-tier model, a typical 5,000 custom object migration project would consume approximately **$200-500 in LLM API costs** vs. $5,000+ without optimization. The rule engine handles 80% of fixes at zero token cost.

---

## 3. SAP Connectivity Deep-Dive

### 3.1 RFC Connection Architecture

```typescript
// cleancore-rfc/src/sap-connector.ts
interface SAPConnection {
  ashost: string;      // Application server host
  sysnr: string;       // System number
  client: string;      // SAP client (e.g., "100")
  user: string;        // RFC user
  passwd: string;      // Password (encrypted at rest)
  lang: string;        // Login language
  saprouter?: string;  // SAP Router string (if needed)
}

// Key RFC calls used by CleanCore AI:
const RFC_CATALOG = {
  // Code Extraction
  'RPY_PROGRAM_READ':       'Read program source code',
  'RPY_FUNCTIONMODULE_READ':'Read function module source',
  'SEO_CLASS_READ_ALL':     'Read class definitions',
  'RFC_READ_TABLE':         'Read TADIR, TRDIR, D010TAB',
  
  // ATC Integration  
  'ATC_RUN_CHECK':          'Trigger ATC check run',
  'ATC_GET_RESULTS':        'Retrieve ATC findings',
  
  // Usage Analysis
  'SCMON_GET_DATA':         'Custom: Get usage statistics',
  
  // Transport Management
  'TR_COPY':                'Create transport copy',
  'TR_RELEASE':             'Release transport request',
  
  // System Info
  'RFC_SYSTEM_INFO':        'Get system details',
  'TH_SERVER_LIST':         'Get app server list'
};
```

### 3.2 Required ABAP Components (Install on ECC)

A lightweight Z-package must be deployed on the source ECC system:

```
Z_CLEANCORE_CONNECTOR (Transport Package)
├── ZCL_CC_CODE_EXTRACTOR     — Extract custom code objects
├── ZCL_CC_ATC_BRIDGE         — Bridge for ATC remote checks
├── ZCL_CC_USAGE_COLLECTOR    — Collect SCMON/ST03N usage data
├── ZCL_CC_TRANSPORT_MANAGER  — Create/manage transports
├── ZFM_CC_GET_CUSTOM_OBJECTS — RFC-enabled FM: list Z*/Y* objects
├── ZFM_CC_READ_SOURCE        — RFC-enabled FM: read source code
├── ZFM_CC_GET_DEPENDENCIES   — RFC-enabled FM: get object deps
└── ZFM_CC_APPLY_FIX          — RFC-enabled FM: apply code fix
```

> [!WARNING]
> `ZFM_CC_APPLY_FIX` must ONLY execute after receiving developer approval token from the CleanCore AI approval engine. The FM validates the approval token before writing any code changes.

---

## 4. Approval Workflow Design

### 4.1 Developer Confirmation Flow

```
┌──────────┐    ┌───────────┐    ┌──────────────┐    ┌─────────┐
│ AI/Rule  │───►│ Fix Queue │───►│ Developer    │───►│ Apply   │
│ generates│    │ (Pending) │    │ Review UI    │    │ to SAP  │
│ fix      │    │           │    │              │    │         │
└──────────┘    └───────────┘    │ • Code diff  │    └────┬────┘
                                 │ • Rationale  │         │
                                 │ • Impact     │         ▼
                                 │ • SAP Note   │    ┌─────────┐
                                 │              │    │ Audit   │
                                 │ [Approve]    │    │ Log     │
                                 │ [Reject]     │    └─────────┘
                                 │ [Modify]     │
                                 └──────────────┘
```

### 4.2 Approval States

| State | Description | Next States |
|---|---|---|
| `GENERATED` | Fix created by AI/Rule engine | → PENDING_REVIEW |
| `PENDING_REVIEW` | In developer's queue | → APPROVED, REJECTED, MODIFIED |
| `APPROVED` | Developer confirmed | → APPLYING, FAILED |
| `REJECTED` | Developer declined fix | → REGENERATE, CLOSED |
| `MODIFIED` | Developer edited the fix | → APPROVED |
| `APPLYING` | Being deployed to SAP | → APPLIED, FAILED |
| `APPLIED` | Successfully deployed | → VALIDATED, ROLLBACK |
| `VALIDATED` | Passed post-apply checks | (Terminal) |
| `ROLLBACK` | Reverted to original | → PENDING_REVIEW |

---

## 5. Database Schema (Core Tables)

```sql
-- Projects
CREATE TABLE projects (
  id UUID PRIMARY KEY,
  name VARCHAR(200),
  source_system JSONB,      -- ECC connection details
  target_system JSONB,      -- S/4HANA connection details  
  status VARCHAR(50),
  current_phase INTEGER,
  created_by VARCHAR(100),
  created_at TIMESTAMPTZ
);

-- Custom Objects Inventory
CREATE TABLE custom_objects (
  id UUID PRIMARY KEY,
  project_id UUID REFERENCES projects(id),
  object_type VARCHAR(20),  -- PROG, FUGR, CLAS, TABL, etc.
  object_name VARCHAR(120),
  package VARCHAR(30),
  source_code TEXT,
  source_hash VARCHAR(64),
  usage_count INTEGER,
  last_used_date DATE,
  priority VARCHAR(5),      -- P1, P2, P3
  status VARCHAR(50)
);

-- ATC Findings
CREATE TABLE atc_findings (
  id UUID PRIMARY KEY,
  object_id UUID REFERENCES custom_objects(id),
  check_id VARCHAR(100),
  message_text TEXT,
  priority VARCHAR(5),
  sap_note VARCHAR(20),
  simplification_item VARCHAR(100),
  finding_type VARCHAR(50)  -- SYNTAX, OBSOLETE_TABLE, etc.
);

-- Fixes (with approval tracking)
CREATE TABLE fixes (
  id UUID PRIMARY KEY,
  finding_id UUID REFERENCES atc_findings(id),
  object_id UUID REFERENCES custom_objects(id),
  fix_type VARCHAR(50),     -- RULE_BASED, AI_GENERATED, MANUAL
  original_code TEXT,
  fixed_code TEXT,
  diff_patch TEXT,
  rationale TEXT,
  sap_note_ref VARCHAR(20),
  tier VARCHAR(10),         -- TIER1, TIER2, TIER3
  tokens_used INTEGER DEFAULT 0,
  status VARCHAR(30),
  approved_by VARCHAR(100),
  approved_at TIMESTAMPTZ,
  applied_at TIMESTAMPTZ
);

-- Audit Trail (append-only)
CREATE TABLE audit_log (
  id BIGSERIAL PRIMARY KEY,
  project_id UUID,
  object_id UUID,
  fix_id UUID,
  phase INTEGER,
  action VARCHAR(100),
  actor VARCHAR(100),
  detail JSONB,
  before_snapshot TEXT,
  after_snapshot TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Clean Core Conversions
CREATE TABLE conversions (
  id UUID PRIMARY KEY,
  object_id UUID REFERENCES custom_objects(id),
  conversion_type VARCHAR(50),  -- BDC_TO_BAPI, ALV_TO_RAP, MODPOOL_TO_FIORI
  source_pattern JSONB,
  target_artifacts JSONB,       -- Generated RAP/CDS/UI5 artifact references
  status VARCHAR(30),
  approved_by VARCHAR(100)
);
```

---

## 6. Progress Tracking & Status Dashboard

### 6.1 Real-Time Progress Model

```typescript
interface PhaseProgress {
  phaseId: number;           // 1-6
  phaseName: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'blocked';
  progress: number;          // 0-100
  totalObjects: number;
  processedObjects: number;
  findings: {
    p1: number;
    p2: number;
    p3: number;
  };
  startedAt?: Date;
  completedAt?: Date;
  estimatedRemaining?: string;
}

interface ProjectDashboard {
  projectId: string;
  overallProgress: number;
  phases: PhaseProgress[];
  metrics: {
    totalCustomObjects: number;
    objectsAnalyzed: number;
    fixesGenerated: number;
    fixesApproved: number;
    fixesApplied: number;
    cleanCoreIndex: number;   // 0-100 score
    tokensUsed: number;
    estimatedCostSaved: number;
  };
}
```

### 6.2 WebSocket Events for Live Updates

```typescript
// Server → Client events
socket.emit('phase:progress', { phaseId: 2, progress: 45, current: 'Analyzing ZMM_REPORT_01' });
socket.emit('fix:generated', { objectName: 'ZSD_ORDER_PROC', fixType: 'RULE_BASED', priority: 'P1' });
socket.emit('fix:pending_approval', { fixId: 'uuid', diff: '...' });
socket.emit('audit:new_entry', { action: 'FIX_APPLIED', object: 'ZFI_GL_POST' });
```
