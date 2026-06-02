# CleanCore AI — Architecture Overview
## SAP ECC → S/4HANA Private Cloud Migration Automation Tool

> **Product Vision:** A SUM-inspired, AI-powered one-stop framework that automates custom code assessment, remediation, Clean Core conversion, and validation — with full audit trail and developer-confirmation gates.

---

## 1. Product Identity & Positioning

| Attribute | Detail |
|---|---|
| **Product Name** | CleanCore AI |
| **Tagline** | "AI-Powered Custom Code Migration — From ECC to Clean Core" |
| **Target Users** | SAP Basis, ABAP Developers, Solution Architects, Migration PMs |
| **Deployment** | On-premise appliance (Docker/K8s) within customer DMZ |
| **AI Strategy** | Hybrid — local rule engine + optional LLM for complex transforms |

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CleanCore AI Tool                            │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                   Presentation Layer                          │  │
│  │  SAP Fiori Horizon UI (SAPUI5 / React)                       │  │
│  │  • Dashboard  • Phase Navigator  • Code Diff Viewer          │  │
│  │  • Approval Queue  • Audit Log Viewer  • Progress Tracker    │  │
│  └──────────────────────────┬────────────────────────────────────┘  │
│                             │ REST / WebSocket                      │
│  ┌──────────────────────────▼────────────────────────────────────┐  │
│  │                   Orchestration Layer                         │  │
│  │  Phase Engine (SUM-inspired 6-phase workflow)                 │  │
│  │  • Phase 1: Connect & Extract                                │  │
│  │  • Phase 2: Analyze (ATC + Usage + Priority)                 │  │
│  │  • Phase 3: Auto-Fix (Rule Engine + AI)                      │  │
│  │  • Phase 4: Convert to Clean Core                            │  │
│  │  • Phase 5: Validate                                         │  │
│  │  • Phase 6: Deploy & Audit                                   │  │
│  └──────────────────────────┬────────────────────────────────────┘  │
│                             │                                       │
│  ┌──────────┬───────────┬───▼──────┬─────────────┬──────────────┐  │
│  │ SAP      │ Code      │ AI/LLM   │ Validation  │ Audit        │  │
│  │ Connect  │ Analysis  │ Engine   │ Engine      │ Engine       │  │
│  │ Module   │ Module    │          │             │              │  │
│  └────┬─────┴─────┬─────┴────┬─────┴──────┬──────┴──────────────┘  │
│       │           │          │            │                         │
└───────┼───────────┼──────────┼────────────┼─────────────────────────┘
        │           │          │            │
   ┌────▼────┐ ┌────▼───┐ ┌───▼───┐  ┌────▼────┐
   │SAP ECC  │ │SAP     │ │LLM    │  │S/4HANA  │
   │(Source) │ │S/4HANA │ │API    │  │Target   │
   │RFC/OData│ │(Check) │ │(Opt.) │  │System   │
   └─────────┘ └────────┘ └───────┘  └─────────┘
```

---

## 3. SUM-Inspired Phase Architecture

### Phase 1 — CONNECT & EXTRACT
| Item | Detail |
|---|---|
| **Purpose** | Establish RFC/OData connectivity to SAP ECC; extract custom code inventory |
| **SAP Interfaces** | RFC via `node-rfc`/`pyrfc`, OData V2/V4, ADT REST APIs |
| **Key Actions** | Validate credentials → Discover custom objects (Y*/Z*) → Extract source via `RPY_PROGRAM_READ` → Pull ATC results via remote check → Collect usage logs (SCMON) |
| **Output** | Complete custom code repository snapshot in local DB |

### Phase 2 — ANALYZE
| Item | Detail |
|---|---|
| **Purpose** | Deep analysis of all custom code for S/4HANA readiness |
| **Sub-steps** | ① ATC remote analysis against Simplification DB → ② Usage pattern analysis (SCMON data) → ③ Priority classification (P1/P2/P3) → ④ Dependency mapping |
| **AI Role** | Classify code complexity; suggest migration path per object |
| **Output** | Prioritized findings dashboard with effort estimates |

### Phase 3 — AUTO-FIX
| Item | Detail |
|---|---|
| **Purpose** | Apply rule-based and AI-assisted code fixes |
| **Rule Engine** | Deterministic fixes: obsolete table → CDS view mapping, SELECT fixes, MATNR length, cluster/pool table conversions |
| **AI Engine** | Complex transforms: refactor business logic, suggest BAPI replacements |
| **Developer Gate** | ⚠️ Every fix requires explicit developer confirmation before apply |
| **Output** | Fixed code with before/after diff + rationale |

### Phase 4 — CONVERT TO CLEAN CORE
| Item | Detail |
|---|---|
| **Purpose** | Transform legacy patterns to modern SAP architecture |
| **Conversions** | BDC → BAPI/API wrappers, ALV → RAP + Fiori Elements, Module Pool → RAP BO + Fiori |
| **AI Role** | Generate RAP artifacts (CDS, Behavior Def, Service Binding) from legacy code analysis |
| **Developer Gate** | ⚠️ Full code review + approval before each conversion |

### Phase 5 — VALIDATE
| Item | Detail |
|---|---|
| **Purpose** | Ensure correctness of all transformations |
| **Sub-steps** | ① Version comparison (original vs. fixed) → ② ATC re-run → ③ Syntax check → ④ Output validation → ⑤ Clean Core compliance scoring |

### Phase 6 — DEPLOY & AUDIT
| Item | Detail |
|---|---|
| **Purpose** | Deploy validated code and maintain complete audit trail |
| **Sub-steps** | ① Generate transport requests → ② Deploy to target → ③ Post-deployment ATC → ④ Generate audit report |
| **Audit Trail** | Every action logged: who, what, when, approval status, before/after code |

---

## 4. Deployment Architecture

```
Customer Network / DMZ
┌──────────────────────────────────────────────────┐
│  Docker Host / Kubernetes Cluster                │
│  ┌────────────────────────────────────────────┐  │
│  │  CleanCore AI Stack                        │  │
│  │  ┌──────────┐ ┌──────────┐ ┌───────────┐  │  │
│  │  │ Frontend │ │ Backend  │ │ Worker    │  │  │
│  │  │ (Nginx)  │ │ (NestJS/ │ │ (Bull/    │  │  │
│  │  │ React+   │ │  FastAPI)│ │  Celery)  │  │  │
│  │  │ SAPUI5   │ │          │ │           │  │  │
│  │  └────┬─────┘ └────┬─────┘ └─────┬─────┘  │  │
│  │       │             │             │         │  │
│  │  ┌────▼─────────────▼─────────────▼──────┐  │  │
│  │  │  PostgreSQL  │  Redis  │  MinIO (S3)  │  │  │
│  │  └──────────────┴─────────┴──────────────┘  │  │
│  └────────────────────────────────────────────┘  │
│          │           │           │                │
│     SAP ECC     SAP S/4HANA   SAP Cloud           │
│     (Source)    (Check/Target) Connector           │
└──────────────────────────────────────────────────┘
```

| Component | Technology | Container |
|---|---|---|
| Frontend | React + SAP UI5 Web Components | `cleancore-ui` |
| API Server | NestJS (Node.js) or FastAPI (Python) | `cleancore-api` |
| Worker | Bull (Node) or Celery (Python) | `cleancore-worker` |
| Database | PostgreSQL 16 | `postgres:16-alpine` |
| Cache/Queue | Redis 7 | `redis:7-alpine` |
| Object Store | MinIO | `minio:latest` |
| RFC Bridge | Node-RFC sidecar | `cleancore-rfc` |
