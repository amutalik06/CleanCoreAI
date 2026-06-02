"""
CleanCore AI — Orchestrator
Maps findings to specialized workers, groups overlapping findings,
builds parallel execution plan, merges patches, applies confidence gate.
"""
import asyncio
import difflib
import logging
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from models import (
    ABAPObject, ABAPParseResult, ATCFinding, CodeFix, AnalysisSession,
    AnalysisStatus, FindingPriority, FindingCategory, FixStatus, FixTier, WorkerInput, InputSource
)
from services.abap_parser import abap_parser
from services.workers.specialized_workers import WORKER_REGISTRY, validation_worker
from services.rag_engine import rag_engine
from config import settings

logger = logging.getLogger("cleancore.orchestrator")


class Orchestrator:
    """Central orchestrator that manages the full remediation pipeline."""

    def __init__(self):
        self.sessions: Dict[str, AnalysisSession] = {}

    async def run_full_pipeline(
        self,
        source_code: str,
        object_name: str,
        input_source: InputSource = InputSource.FILE_UPLOAD,
        external_findings: Optional[List[ATCFinding]] = None,
        progress_callback=None
    ) -> AnalysisSession:
        """Execute the complete 8-phase pipeline."""

        session = AnalysisSession(
            source=input_source,
            object_name=object_name,
            source_code=source_code
        )
        self.sessions[session.id] = session

        try:
            # ── Phase 1-2: Ingestion ─────────────────────────────────
            await self._update_progress(session, AnalysisStatus.PARSING, 10, "Phase 1-2: Parsing ABAP source code...", progress_callback)
            session.parse_result = abap_parser.parse(source_code, object_name)
            self._log_audit(session, "PARSE_COMPLETE", f"Parsed {object_name}: {len(session.parse_result.select_statements)} SELECTs, {len(session.parse_result.tables_used)} tables")

            # ── Phase 3-4: Analysis + Finding Generation ─────────────
            await self._update_progress(session, AnalysisStatus.ANALYZING, 25, "Phase 3-4: Analyzing findings and mapping workers...", progress_callback)

            if external_findings:
                session.findings = external_findings
            else:
                session.findings = self._generate_findings_from_parse(session.parse_result, object_name)

            session.total_findings = len(session.findings)
            self._log_audit(session, "ANALYSIS_COMPLETE", f"Found {session.total_findings} findings: P1={sum(1 for f in session.findings if f.priority == FindingPriority.P1)}, P2={sum(1 for f in session.findings if f.priority == FindingPriority.P2)}, P3={sum(1 for f in session.findings if f.priority == FindingPriority.P3)}")

            if not session.findings:
                await self._update_progress(session, AnalysisStatus.COMPLETE, 100, "No findings detected — code is S/4HANA compliant!", progress_callback)
                session.completed_at = datetime.utcnow()
                return session

            # ── Group overlapping findings ────────────────────────────
            grouped_findings = self._group_findings(session.findings)
            self._log_audit(session, "FINDINGS_GROUPED", f"Grouped into {len(grouped_findings)} non-overlapping batches")

            # ── Phase 5-6: Worker Execution (The LLM Moment) ─────────
            await self._update_progress(session, AnalysisStatus.GENERATING_FIXES, 40, "Phase 5-6: Generating fixes via worker pipeline...", progress_callback)

            all_fixes = []
            total_groups = len(grouped_findings)
            for idx, group in enumerate(grouped_findings):
                progress = 40 + (idx / max(total_groups, 1)) * 35
                await self._update_progress(session, AnalysisStatus.GENERATING_FIXES, progress, f"Processing group {idx + 1}/{total_groups}...", progress_callback)

                group_fixes = await self._execute_worker_group(group, source_code, session.parse_result)
                all_fixes.extend(group_fixes)

            session.fixes = all_fixes
            session.fixes_generated = len(all_fixes)
            session.tokens_used = sum(f.tokens_used for f in all_fixes)

            # ── Phase 7-8: Merge + Confidence Gate + Validation ──────
            await self._update_progress(session, AnalysisStatus.VALIDATING, 80, "Phase 7-8: Validating and applying confidence gate...", progress_callback)

            # Apply confidence threshold
            for fix in session.fixes:
                if fix.confidence < settings.CONFIDENCE_THRESHOLD:
                    fix.requires_human_review = True
                    fix.status = FixStatus.PENDING_REVIEW
                    session.human_review_count += 1
                    self._log_audit(session, "HUMAN_REVIEW_REQUIRED", f"Fix {fix.id[:8]} confidence={fix.confidence:.2f} < threshold={settings.CONFIDENCE_THRESHOLD}")
                else:
                    fix.status = FixStatus.PENDING_REVIEW

            # Run validation worker on all fixes
            for fix in session.fixes:
                val_result = validation_worker.validate(fix.original_code, fix.fixed_code)
                if not val_result["valid"]:
                    fix.requires_human_review = True
                    fix.confidence = min(fix.confidence, 0.5)
                    self._log_audit(session, "VALIDATION_ISSUE", f"Fix {fix.id[:8]}: {', '.join(val_result['issues'])}")

            # Generate HTML diffs
            for fix in session.fixes:
                fix.diff_html = self._generate_html_diff(fix.original_code, fix.fixed_code)

            await self._update_progress(session, AnalysisStatus.COMPLETE, 100, "Pipeline complete! Review fixes in the approval queue.", progress_callback)
            session.completed_at = datetime.utcnow()
            self._log_audit(session, "PIPELINE_COMPLETE", f"Generated {session.fixes_generated} fixes, {session.human_review_count} require human review, {session.tokens_used} tokens used")

        except Exception as e:
            logger.error(f"Pipeline failed: {str(e)}")
            session.status = AnalysisStatus.FAILED
            session.current_step = f"Error: {str(e)}"
            self._log_audit(session, "PIPELINE_FAILED", str(e))

        return session

    def _generate_findings_from_parse(self, parse: ABAPParseResult, object_name: str) -> List[ATCFinding]:
        """Generate ATCFinding objects from parse results (for file upload mode)."""
        findings = []

        for sel in parse.select_statements:
            for issue in sel.get("issues", []):
                cat_map = {
                    "select_star": FindingCategory.SELECT_STAR,
                    "missing_order_by": FindingCategory.MISSING_ORDER_BY,
                    "obsolete_table": FindingCategory.OBSOLETE_TABLE,
                }
                findings.append(ATCFinding(
                    object_name=object_name,
                    check_id=issue["type"],
                    check_title=issue["type"].replace("_", " ").title(),
                    message=issue["message"],
                    line=sel["line"],
                    priority=FindingPriority(issue.get("priority", "P2")),
                    category=cat_map.get(issue["type"], FindingCategory.GENERIC),
                    sap_note=issue.get("sap_note")
                ))

        for decl in parse.data_declarations:
            for issue in decl.get("issues", []):
                findings.append(ATCFinding(
                    object_name=object_name,
                    check_id="matnr_length",
                    check_title="Material Number Length",
                    message=issue["message"],
                    line=decl["line"],
                    priority=FindingPriority.P1,
                    category=FindingCategory.MATNR_LENGTH,
                    sap_note=issue.get("sap_note", "2253265")
                ))

        for stmt in parse.statements:
            findings.append(ATCFinding(
                object_name=object_name,
                check_id="deprecated_statement",
                check_title="Deprecated Statement",
                message=stmt["message"],
                line=stmt["line"],
                priority=FindingPriority.P3,
                category=FindingCategory.DEPRECATED_STATEMENT
            ))

        for bdc in parse.bdc_calls:
            findings.append(ATCFinding(
                object_name=object_name,
                check_id="bdc_usage",
                check_title="BDC Usage Detected",
                message=f"BDC {bdc['type']} at line {bdc['line']} — consider replacing with BAPI/API",
                line=bdc["line"],
                priority=FindingPriority.P2,
                category=FindingCategory.CLEAN_CORE_CONVERSION
            ))

        for alv in parse.alv_calls:
            findings.append(ATCFinding(
                object_name=object_name,
                check_id="alv_usage",
                check_title="Classic ALV Usage",
                message=f"Classic ALV ({alv['type']}) — consider RAP + Fiori Elements",
                line=alv["line"],
                priority=FindingPriority.P3,
                category=FindingCategory.CLEAN_CORE_CONVERSION
            ))

        return findings

    def _group_findings(self, findings: List[ATCFinding]) -> List[List[ATCFinding]]:
        """Group overlapping findings to prevent patch conflicts."""
        sorted_findings = sorted(findings, key=lambda f: f.line)
        groups: List[List[ATCFinding]] = []
        current_group: List[ATCFinding] = []
        last_line = -999

        for finding in sorted_findings:
            if finding.line - last_line <= 5 and current_group:
                current_group.append(finding)
            else:
                if current_group:
                    groups.append(current_group)
                current_group = [finding]
            last_line = finding.line

        if current_group:
            groups.append(current_group)
        return groups

    async def _execute_worker_group(self, findings: List[ATCFinding], source_code: str, parse_result: ABAPParseResult) -> List[CodeFix]:
        """Execute workers for a group of findings (potentially parallel)."""
        fixes = []
        tasks = []

        for finding in findings:
            worker = WORKER_REGISTRY.get(finding.category)
            if not worker:
                logger.warning(f"No worker for category: {finding.category}")
                continue

            worker_input = WorkerInput(
                finding=finding,
                source_code=source_code,
                parse_result=parse_result
            )
            tasks.append(self._run_worker(worker, worker_input, finding))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, CodeFix):
                    fixes.append(result)
                elif isinstance(result, Exception):
                    logger.error(f"Worker failed: {str(result)}")

        return fixes

    async def _run_worker(self, worker, worker_input: WorkerInput, finding: ATCFinding) -> CodeFix:
        """Run a single worker and convert output to CodeFix."""
        output = await worker.execute(worker_input)
        return CodeFix(
            finding_id=finding.id,
            object_name=finding.object_name,
            worker_type=output.worker_type,
            category=finding.category,
            priority=finding.priority,
            original_code=output.original_code,
            fixed_code=output.fixed_code,
            rationale=output.rationale,
            sap_note_refs=output.sap_note_refs,
            confidence=output.confidence,
            tier=output.tier,
            tokens_used=output.tokens_used
        )

    def _generate_html_diff(self, original: str, fixed: str) -> str:
        """Generate HTML diff for side-by-side comparison."""
        differ = difflib.HtmlDiff(tabsize=2, wrapcolumn=80)
        return differ.make_table(
            original.split("\n"), fixed.split("\n"),
            fromdesc="Original", todesc="Fixed",
            context=True, numlines=3
        )

    async def _update_progress(self, session: AnalysisSession, status: AnalysisStatus, progress: float, message: str, callback=None):
        session.status = status
        session.progress = progress
        session.current_step = message
        if callback:
            await callback(session)

    def _log_audit(self, session: AnalysisSession, action: str, detail: str):
        session.audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "detail": detail
        })

    def get_session(self, session_id: str) -> Optional[AnalysisSession]:
        return self.sessions.get(session_id)

    def approve_fix(self, session_id: str, fix_id: str, action: str, modified_code: str = None, comment: str = None, approved_by: str = "developer") -> Optional[CodeFix]:
        session = self.sessions.get(session_id)
        if not session:
            return None
        for fix in session.fixes:
            if fix.id == fix_id:
                if action == "approve":
                    fix.status = FixStatus.APPROVED
                    fix.approved_by = approved_by
                    fix.approved_at = datetime.utcnow()
                    session.fixes_approved += 1
                elif action == "reject":
                    fix.status = FixStatus.REJECTED
                    session.fixes_rejected += 1
                elif action == "modify":
                    fix.fixed_code = modified_code or fix.fixed_code
                    fix.status = FixStatus.MODIFIED
                    fix.diff_html = self._generate_html_diff(fix.original_code, fix.fixed_code)
                self._log_audit(session, f"FIX_{action.upper()}", f"Fix {fix_id[:8]} {action}d by {approved_by}" + (f" — {comment}" if comment else ""))
                return fix
        return None


orchestrator = Orchestrator()
