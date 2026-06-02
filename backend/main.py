"""
CleanCore AI — FastAPI Main Application
"""
import os
import sys
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import Optional, List
from datetime import datetime

# Ensure backend dir is on path
sys.path.insert(0, os.path.dirname(__file__))

from config import settings
from models import (
    SAPConnectionConfig, SAPConnectionStatus, FileUploadRequest,
    AnalysisSession, AnalysisStatus, CodeFix, FixApprovalRequest,
    ProgressUpdate, InputSource, SAPATCResult, SAPPackageObject,
    AnalyzePackageObjectsRequest
)
from services.sap_connector import sap_connector
from services.orchestrator import orchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("cleancore.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(settings.KNOWLEDGE_BASE_DIR, exist_ok=True)
    logger.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} starting...")
    yield
    await sap_connector.disconnect(clear_cache=False)
    logger.info("Shutdown complete.")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-Powered SAP ECC → S/4HANA Code Remediation Engine",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── WebSocket Connections ───────────────────────────────────────────
ws_connections: dict[str, WebSocket] = {}


# ═══════════════════════════════════════════════════════════════════
# SAP CONNECTION ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/v1/sap/rfc-status")
async def sap_rfc_status():
    """Report local SAP RFC runtime readiness."""
    return await sap_connector.runtime_status()


@app.post("/api/v1/sap/connect", response_model=SAPConnectionStatus)
async def connect_to_sap(config: SAPConnectionConfig):
    """Connect to SAP ECC/S4HANA system via RFC."""
    return await sap_connector.connect(config)


@app.post("/api/v1/sap/disconnect")
async def disconnect_from_sap():
    """Disconnect from SAP system."""
    await sap_connector.disconnect()
    return {"status": "disconnected"}


@app.get("/api/v1/sap/adt-status")
async def sap_adt_status():
    """Report ADT REST API connectivity details."""
    status = await sap_connector.runtime_status()
    return {
        "connection_mode": status.get("connection_mode", ""),
        "adt_connected": status.get("adt_connected", False),
        "pyrfc_available": status.get("pyrfc_available", False),
        "message": status.get("message", ""),
    }


@app.get("/api/v1/sap/objects")
async def list_custom_objects(namespace: str = "Z"):
    """List custom ABAP objects from connected SAP system."""
    try:
        objects = await sap_connector.get_custom_objects(namespace)
        return {"objects": objects, "count": len(objects)}
    except ConnectionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/sap/read-program")
async def read_sap_program(program_name: str = Form(...)):
    """Read ABAP program source from SAP via RFC."""
    try:
        obj = await sap_connector.read_program_source(program_name)
        if not obj:
            raise HTTPException(status_code=404, detail=f"Program {program_name} not found")
        return {"object": obj.model_dump()}
    except ConnectionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/sap/atc-results", response_model=List[SAPATCResult])
async def get_sap_atc_results():
    """Retrieve historical/central ATC check run results from SAP."""
    try:
        return await sap_connector.get_atc_results()
    except ConnectionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/sap/atc-results/{result_id}/findings")
async def get_sap_atc_findings(result_id: str):
    """Retrieve findings for a specific central ATC run from SAP."""
    try:
        findings = await sap_connector.get_atc_worklist_findings(result_id)
        return {"findings": [f.model_dump() for f in findings], "count": len(findings)}
    except ConnectionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/sap/atc/run-on-package")
async def run_atc_on_package(data: dict):
    """Trigger a fresh ATC check run on an SAP package."""
    package_name = data.get("package_name", "")
    if not package_name.strip():
        raise HTTPException(status_code=400, detail="package_name is required")
    try:
        result = await sap_connector.run_atc_on_package(package_name)
        return result
    except ConnectionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("ATC run on package failed")
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/api/v1/sap/packages/{package_name}/objects", response_model=List[SAPPackageObject])
async def get_sap_package_objects(package_name: str):
    """Retrieve all repository objects in an SAP package (read-only list)."""
    try:
        return await sap_connector.get_objects_by_package(package_name)
    except ConnectionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/sap/packages/analyze-objects")
async def analyze_sap_package_objects(request: AnalyzePackageObjectsRequest):
    """
    Start the remediation pipeline for a batch of SAP package objects.
    Pulls code via ADT/RFC (read-only) and triggers analysis.
    """
    try:
        sessions = []
        for obj in request.objects:
            obj_name = obj.get("name")
            obj_type = obj.get("type", "PROG")
            if not obj_name:
                continue
            
            abap_obj = await sap_connector.read_object_source(obj_name, obj_type)
            if not abap_obj or not abap_obj.source_code.strip():
                logger.warning(f"Could not read source code for object {obj_name} ({obj_type})")
                continue
                
            session = await orchestrator.run_full_pipeline(
                source_code=abap_obj.source_code,
                object_name=obj_name,
                input_source=InputSource.SAP_RFC
            )
            sessions.append(_serialize_session(session))
            
        return {"sessions": sessions, "count": len(sessions)}
    except ConnectionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Batch analysis failed")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════
# FILE UPLOAD ENDPOINT
# ═══════════════════════════════════════════════════════════════════

@app.post("/api/v1/upload")
async def upload_abap_file(file: UploadFile = File(...)):
    """Upload an ABAP source file (.txt/.abap) for analysis."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    content = await file.read()
    source_code = content.decode("utf-8", errors="replace")
    object_name = os.path.splitext(file.filename)[0].upper()

    return {
        "object_name": object_name,
        "source_code": source_code,
        "line_count": len(source_code.split("\n")),
        "filename": file.filename
    }


@app.post("/api/v1/upload/text")
async def upload_abap_text(request: FileUploadRequest):
    """Upload ABAP source code as text string."""
    return {
        "object_name": os.path.splitext(request.filename)[0].upper(),
        "source_code": request.content,
        "line_count": len(request.content.split("\n")),
        "filename": request.filename
    }


# ═══════════════════════════════════════════════════════════════════
# ANALYSIS PIPELINE ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@app.post("/api/v1/analyze")
async def start_analysis(
    source_code: str = Form(...),
    object_name: str = Form(...),
    source: str = Form(default="file_upload")
):
    """Start the full remediation pipeline on ABAP source code."""
    input_source = InputSource.SAP_RFC if source == "sap_rfc" else InputSource.FILE_UPLOAD

    session = await orchestrator.run_full_pipeline(
        source_code=source_code,
        object_name=object_name,
        input_source=input_source
    )

    return {"session": _serialize_session(session)}


@app.post("/api/v1/analyze/json")
async def start_analysis_json(data: dict):
    """Start analysis via JSON body (for React frontend)."""
    source_code = data.get("source_code", "")
    object_name = data.get("object_name", "UNKNOWN")
    source = data.get("source", "file_upload")

    if not source_code.strip():
        raise HTTPException(status_code=400, detail="source_code is required")

    input_source = InputSource.SAP_RFC if source == "sap_rfc" else InputSource.FILE_UPLOAD

    session = await orchestrator.run_full_pipeline(
        source_code=source_code,
        object_name=object_name,
        input_source=input_source
    )

    return {"session": _serialize_session(session)}


@app.get("/api/v1/sessions/{session_id}")
async def get_session(session_id: str):
    """Get analysis session details."""
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session": _serialize_session(session)}


@app.get("/api/v1/sessions")
async def list_sessions():
    """List all analysis sessions."""
    sessions = [_serialize_session(s) for s in orchestrator.sessions.values()]
    return {"sessions": sessions}


# ═══════════════════════════════════════════════════════════════════
# FIX APPROVAL ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@app.post("/api/v1/sessions/{session_id}/fixes/{fix_id}/action")
async def approve_fix(session_id: str, fix_id: str, request: FixApprovalRequest):
    """Approve, reject, or modify a fix."""
    fix = orchestrator.approve_fix(
        session_id, fix_id,
        action=request.action,
        modified_code=request.modified_code,
        comment=request.comment,
        approved_by=request.approved_by
    )
    if not fix:
        raise HTTPException(status_code=404, detail="Session or fix not found")
    return {"fix": fix.model_dump()}


@app.post("/api/v1/sessions/{session_id}/bulk-approve")
async def bulk_approve(session_id: str, data: dict):
    """Bulk approve fixes matching criteria."""
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    min_confidence = data.get("min_confidence", 0.9)
    approved_by = data.get("approved_by", "developer")
    approved = []

    for fix in session.fixes:
        if fix.confidence >= min_confidence and fix.status.value == "pending_review":
            orchestrator.approve_fix(session_id, fix.id, "approve", approved_by=approved_by)
            approved.append(fix.id)

    return {"approved_count": len(approved), "approved_ids": approved}


# ═══════════════════════════════════════════════════════════════════
# AUDIT TRAIL ENDPOINT
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/v1/sessions/{session_id}/audit")
async def get_audit_log(session_id: str):
    """Get the audit trail for a session."""
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"audit_log": session.audit_log, "count": len(session.audit_log)}


# ═══════════════════════════════════════════════════════════════════
# WEBSOCKET FOR LIVE PROGRESS
# ═══════════════════════════════════════════════════════════════════

@app.websocket("/ws/progress/{session_id}")
async def websocket_progress(websocket: WebSocket, session_id: str):
    """WebSocket for real-time progress updates."""
    await websocket.accept()
    ws_connections[session_id] = websocket
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_connections.pop(session_id, None)


# ═══════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/v1/health")
async def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "llm_provider": settings.LLM_PROVIDER,
        "timestamp": datetime.utcnow().isoformat()
    }


# ─── Helpers ─────────────────────────────────────────────────────────

def _serialize_session(session: AnalysisSession) -> dict:
    """Serialize session for JSON response."""
    data = session.model_dump()
    data["started_at"] = session.started_at.isoformat() if session.started_at else None
    data["completed_at"] = session.completed_at.isoformat() if session.completed_at else None
    # Convert fix dates
    for fix in data.get("fixes", []):
        if fix.get("created_at"):
            fix["created_at"] = fix["created_at"].isoformat() if isinstance(fix["created_at"], datetime) else str(fix["created_at"])
        if fix.get("approved_at"):
            fix["approved_at"] = fix["approved_at"].isoformat() if isinstance(fix["approved_at"], datetime) else str(fix["approved_at"])
    return data


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
