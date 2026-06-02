/**
 * CleanCore AI — API Service Layer
 */
import type { SAPConnection, SAPConnectionStatus, AnalysisSession, SAPATCResult, SAPPackageObject, ATCFinding } from '../types';

const getApiBase = (): string => {
  const storedUrl = localStorage.getItem('CLEANCORE_API_URL');
  if (storedUrl) {
    return `${storedUrl}/api/v1`;
  }
  const envUrl = import.meta.env.VITE_API_URL;
  if (envUrl) {
    return `${envUrl}/api/v1`;
  }
  // Fallback to local API when deployed on external hosts (like Vercel)
  if (window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
    return 'http://localhost:8000/api/v1';
  }
  return '/api/v1';
};

const API_BASE = getApiBase();

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

export const api = {
  // Health
  health: () => request<{ status: string; version: string }>('/health'),

  // SAP Connection
  connectSAP: (config: SAPConnection) =>
    request<SAPConnectionStatus>('/sap/connect', { method: 'POST', body: JSON.stringify(config) }),

  disconnectSAP: () =>
    request<{ status: string }>('/sap/disconnect', { method: 'POST' }),

  getSAPStatus: () =>
    request<SAPConnectionStatus>('/sap/rfc-status'),

  listCustomObjects: (namespace = 'Z') =>
    request<{ objects: any[]; count: number }>(`/sap/objects?namespace=${namespace}`),

  // File Upload
  uploadFile: async (file: File): Promise<{ object_name: string; source_code: string; line_count: number }> => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API_BASE}/upload`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error('Upload failed');
    return res.json();
  },

  uploadText: (filename: string, content: string) =>
    request<{ object_name: string; source_code: string }>('/upload/text', {
      method: 'POST',
      body: JSON.stringify({ filename, content, object_type: 'PROG' }),
    }),

  // Analysis
  startAnalysis: (source_code: string, object_name: string, source = 'file_upload') =>
    request<{ session: AnalysisSession }>('/analyze/json', {
      method: 'POST',
      body: JSON.stringify({ source_code, object_name, source }),
    }),

  getSession: (sessionId: string) =>
    request<{ session: AnalysisSession }>(`/sessions/${sessionId}`),

  listSessions: () =>
    request<{ sessions: AnalysisSession[] }>('/sessions'),

  // Approval
  fixAction: (sessionId: string, fixId: string, action: string, modifiedCode?: string, comment?: string) =>
    request<{ fix: any }>(`/sessions/${sessionId}/fixes/${fixId}/action`, {
      method: 'POST',
      body: JSON.stringify({ action, modified_code: modifiedCode, comment, approved_by: 'developer' }),
    }),

  bulkApprove: (sessionId: string, minConfidence = 0.9) =>
    request<{ approved_count: number }>(`/sessions/${sessionId}/bulk-approve`, {
      method: 'POST',
      body: JSON.stringify({ min_confidence: minConfidence, approved_by: 'developer' }),
    }),

  // Audit
  getAuditLog: (sessionId: string) =>
    request<{ audit_log: any[]; count: number }>(`/sessions/${sessionId}/audit`),

  // SAP ATC and Package Explorer
  getSAPATCResults: () =>
    request<SAPATCResult[]>('/sap/atc-results'),

  getSAPATCFindings: (resultId: string) =>
    request<{ findings: ATCFinding[]; count: number }>(`/sap/atc-results/${resultId}/findings`),

  runATCOnPackage: (packageName: string) =>
    request<{ worklist_id: string; package: string }>('/sap/atc/run-on-package', {
      method: 'POST',
      body: JSON.stringify({ package_name: packageName }),
    }),

  getSAPPackageObjects: (packageName: string) =>
    request<SAPPackageObject[]>(`/sap/packages/${packageName}/objects`),

  analyzeSAPPackageObjects: (objects: Array<{ name: string; type: string }>) =>
    request<{ sessions: AnalysisSession[]; count: number }>('/sap/packages/analyze-objects', {
      method: 'POST',
      body: JSON.stringify({ objects }),
    }),
};
