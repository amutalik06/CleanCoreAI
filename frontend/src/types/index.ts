/**
 * CleanCore AI — TypeScript Types
 */

export interface SAPConnection {
  ashost?: string;
  sysnr: string;
  client: string;
  user: string;
  passwd: string;
  lang: string;
  saprouter?: string;
  use_adt_fallback?: boolean;
  adt_url?: string;
  adt_verify_ssl?: boolean;
}

export interface SAPConnectionStatus {
  connected: boolean;
  system_id?: string;
  system_name?: string;
  release?: string;
  host?: string;
  message: string;
}

export interface ATCFinding {
  id: string;
  object_name: string;
  object_type?: string;
  package_name?: string;
  check_id: string;
  check_title: string;
  message: string;
  line: number;
  column: number;
  priority: 'P1' | 'P2' | 'P3';
  category: string;
  sap_note?: string;
  quick_fix_available: boolean;
}

export interface CodeFix {
  id: string;
  finding_id: string;
  object_name: string;
  worker_type: string;
  category: string;
  priority: 'P1' | 'P2' | 'P3';
  original_code: string;
  fixed_code: string;
  diff_html: string;
  rationale: string;
  sap_note_refs: string[];
  confidence: number;
  tier: 'tier1_rule' | 'tier2_template' | 'tier3_llm';
  tokens_used: number;
  status: 'generated' | 'pending_review' | 'approved' | 'rejected' | 'modified' | 'applied' | 'failed';
  requires_human_review: boolean;
  approved_by?: string;
  approved_at?: string;
  created_at: string;
}

export interface AuditEntry {
  timestamp: string;
  action: string;
  detail: string;
}

export interface AnalysisSession {
  id: string;
  source: 'sap_rfc' | 'file_upload';
  object_name: string;
  status: 'pending' | 'connecting' | 'extracting' | 'parsing' | 'analyzing' | 'generating_fixes' | 'validating' | 'merging' | 'complete' | 'failed';
  progress: number;
  current_step: string;
  source_code: string;
  findings: ATCFinding[];
  fixes: CodeFix[];
  total_findings: number;
  fixes_generated: number;
  fixes_approved: number;
  fixes_rejected: number;
  human_review_count: number;
  tokens_used: number;
  started_at?: string;
  completed_at?: string;
  audit_log: AuditEntry[];
}

export interface SAPATCResult {
  id: string;
  title: string;
  timestamp: string;
  object_set?: string;
  findings_count?: number;
}

export interface SAPPackageObject {
  name: string;
  type: string;
  package: string;
}

export type ActiveView = 'home' | 'connection' | 'upload' | 'analysis' | 'fixes' | 'audit' | 'sap_atc' | 'sap_packages';
