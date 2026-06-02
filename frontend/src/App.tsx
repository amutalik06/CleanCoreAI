/**
 * CleanCore AI — Main Application
 * SAP ECC → S/4HANA Code Remediation Engine
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
  Activity,
  Cable,
  Check,
  ClipboardList,
  Eye,
  FileCode2,
  FolderOpen,
  Link2,
  Rocket,
  Search,
  Upload,
  Wrench,
  X,
  ChevronRight,
  ArrowUpDown,
  Filter,
  AlertTriangle,
  Play,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  BarChart3,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Info,
} from 'lucide-react';
import type { ActiveView, AnalysisSession, SAPConnectionStatus } from './types';
import { api } from './services/api';

/* ═══════════════════════════════════════════════════════════════════
   PHASE STEPPER
   ═══════════════════════════════════════════════════════════════════ */

const PHASES = [
  { id: 1, label: 'Connect', desc: 'SAP / File Upload', icon: Cable, theme: 'blue' },
  { id: 2, label: 'Parse', desc: 'ABAP AST Analysis', icon: FileCode2, theme: 'purple' },
  { id: 3, label: 'Analyze', desc: 'ATC Findings', icon: Search, theme: 'teal' },
  { id: 4, label: 'Orchestrate', desc: 'Map Workers', icon: Activity, theme: 'orange' },
  { id: 5, label: 'Generate', desc: 'RAG + LLM Fixes', icon: Rocket, theme: 'pink' },
  { id: 6, label: 'Validate', desc: 'Self-Check', icon: Check, theme: 'green' },
  { id: 7, label: 'Merge', desc: 'Patch Merge', icon: Link2, theme: 'indigo' },
  { id: 8, label: 'Review', desc: 'Developer Approval', icon: Eye, theme: 'cyan' },
];

const NAV_ITEMS: Array<{ id: ActiveView; icon: LucideIcon; label: string; color: string }> = [
  { id: 'home', icon: Activity, label: 'Dashboard', color: '#0070f2' },
  { id: 'connection', icon: Cable, label: 'SAP Connection', color: '#e76500' },
  { id: 'sap_atc', icon: Search, label: 'SAP ATC Hub', color: '#008299' },
  { id: 'sap_packages', icon: FolderOpen, label: 'Package Explorer', color: '#893baf' },
  { id: 'upload', icon: FileCode2, label: 'Upload / Analyze', color: '#008a8a' },
  { id: 'fixes', icon: Wrench, label: 'Fix Queue', color: '#c0399f' },
  { id: 'audit', icon: ClipboardList, label: 'Audit Trail', color: '#256f3a' },
];

function getActivePhase(status: string): number {
  const map: Record<string, number> = {
    pending: 0, connecting: 1, extracting: 1, parsing: 2,
    analyzing: 3, generating_fixes: 5, validating: 6, merging: 7, complete: 8, failed: 0,
  };
  return map[status] || 0;
}

function PhaseStepper({ activePhase }: { activePhase: number }) {
  return (
    <div className="phase-stepper-container">
      {PHASES.map((p, index) => {
        const Icon = p.icon;
        const statusClass = p.id < activePhase ? 'completed' : p.id === activePhase ? 'active' : 'pending';
        const isLastInRow = index === 3; // No arrow after phase 4 (end of row 1)
        const showArrow = index < PHASES.length - 1 && !isLastInRow;
        return (
          <div key={p.id} className="phase-card-wrapper">
            <div className={`phase-card theme-${p.theme} status-${statusClass}`}>
              <div className="phase-card-icon-wrapper">
                <Icon size={15} className="phase-card-icon" />
              </div>
              <div className="phase-card-content">
                <div className="phase-card-title">{p.label}</div>
                <div className="phase-card-desc">{p.desc}</div>
              </div>
            </div>
            {showArrow && <ChevronRight size={16} className="phase-arrow" />}
          </div>
        );
      })}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   DIFF VIEWER
   ═══════════════════════════════════════════════════════════════════ */

function computeDiff(original: string, fixed: string) {
  const origLines = (original || '').split('\n');
  const fixedLines = (fixed || '').split('\n');
  
  let i = 0;
  let j = 0;
  const result: Array<{
    origNum: number | null;
    origText: string;
    origClass: string;
    fixedNum: number | null;
    fixedText: string;
    fixedClass: string;
  }> = [];

  while (i < origLines.length || j < fixedLines.length) {
    if (i < origLines.length && j < fixedLines.length) {
      if (origLines[i] === fixedLines[j]) {
        result.push({
          origNum: i + 1,
          origText: origLines[i],
          origClass: '',
          fixedNum: j + 1,
          fixedText: fixedLines[j],
          fixedClass: ''
        });
        i++;
        j++;
      } else {
        // Look ahead to find matches and align deletion/insertion
        let lookAheadMatch = -1;
        for (let k = 1; k < 10; k++) {
          if (i + k < origLines.length && origLines[i + k] === fixedLines[j]) {
            lookAheadMatch = k;
            break;
          }
        }
        
        if (lookAheadMatch !== -1) {
          for (let k = 0; k < lookAheadMatch; k++) {
            result.push({
              origNum: i + 1,
              origText: origLines[i],
              origClass: 'removed',
              fixedNum: null,
              fixedText: '',
              fixedClass: 'empty'
            });
            i++;
          }
        } else {
          let lookAheadInsert = -1;
          for (let k = 1; k < 10; k++) {
            if (j + k < fixedLines.length && origLines[i] === fixedLines[j + k]) {
              lookAheadInsert = k;
              break;
            }
          }
          
          if (lookAheadInsert !== -1) {
            for (let k = 0; k < lookAheadInsert; k++) {
              result.push({
                origNum: null,
                origText: '',
                origClass: 'empty',
                fixedNum: j + 1,
                fixedText: fixedLines[j],
                fixedClass: 'added'
              });
              j++;
            }
          } else {
            result.push({
              origNum: i + 1,
              origText: origLines[i],
              origClass: 'removed',
              fixedNum: j + 1,
              fixedText: fixedLines[j],
              fixedClass: 'added'
            });
            i++;
            j++;
          }
        }
      }
    } else if (i < origLines.length) {
      result.push({
        origNum: i + 1,
        origText: origLines[i],
        origClass: 'removed',
        fixedNum: null,
        fixedText: '',
        fixedClass: 'empty'
      });
      i++;
    } else {
      result.push({
        origNum: null,
        origText: '',
        origClass: 'empty',
        fixedNum: j + 1,
        fixedText: fixedLines[j],
        fixedClass: 'added'
      });
      j++;
    }
  }

  return result;
}

function DiffViewer({ original, fixed }: { original: string; fixed: string }) {
  const diff = computeDiff(original, fixed);

  return (
    <div className="diff-viewer">
      <div className="diff-pane">
        <div className="diff-header">◀ Original</div>
        {diff.map((line, idx) => (
          <div key={idx} className={`diff-line ${line.origClass}`}>
            <span className="diff-line-num">{line.origNum !== null ? line.origNum : ' '}</span>
            <span className="diff-line-content">{line.origText || ' '}</span>
          </div>
        ))}
      </div>
      <div className="diff-pane">
        <div className="diff-header">Fixed ▶</div>
        {diff.map((line, idx) => (
          <div key={idx} className={`diff-line ${line.fixedClass}`}>
            <span className="diff-line-num">{line.fixedNum !== null ? line.fixedNum : ' '}</span>
            <span className="diff-line-content">{line.fixedText || ' '}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   MAIN APP
   ═══════════════════════════════════════════════════════════════════ */

export default function App() {
  const [view, setView] = useState<ActiveView>('home');
  const [session, setSession] = useState<AnalysisSession | null>(null);
  const [sapStatus, setSapStatus] = useState<SAPConnectionStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // SAP Connection Form
  const [sapForm, setSapForm] = useState({
    ashost: '',
    sysnr: '00',
    client: '100',
    user: '',
    passwd: '',
    lang: 'EN',
    saprouter: '',
    use_adt_fallback: false,   // controls whether RFC fields are shown
    adt_url: '',
    adt_verify_ssl: false,
  });

  // Upload state
  const [sourceCode, setSourceCode] = useState('');
  const [objectName, setObjectName] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  // SAP ATC Hub state
  const [atcResults, setAtcResults] = useState<any[]>([]);
  const [selectedAtcResult, setSelectedAtcResult] = useState<any | null>(null);
  const [atcFindings, setAtcFindings] = useState<any[]>([]);
  const [atcPriorityFilter, setAtcPriorityFilter] = useState<string[]>(['P1', 'P2', 'P3']);
  const [atcSortField, setAtcSortField] = useState<string>('priority');
  const [atcSortDir, setAtcSortDir] = useState<'asc' | 'desc'>('asc');
  const [atcRunPackage, setAtcRunPackage] = useState('');
  
  // Package explorer state
  const [packageName, setPackageName] = useState('ZCUSTOM');
  const [packageObjects, setPackageObjects] = useState<any[]>([]);
  const [selectedObjects, setSelectedObjects] = useState<Record<string, boolean>>({});

  const fetchATCResults = async () => {
    setLoading(true); setError('');
    try {
      const results = await api.getSAPATCResults();
      setAtcResults(results);
    } catch (e: any) {
      setError(e.message);
      if (e.message.toLowerCase().includes('not connected')) {
        setSapStatus(null);
      }
    }
    setLoading(false);
  };

  const selectATCResult = async (result: any) => {
    setSelectedAtcResult(result);
    setLoading(true); setError('');
    try {
      const res = await api.getSAPATCFindings(result.id);
      setAtcFindings(res.findings);
    } catch (e: any) {
      setError(e.message);
      if (e.message.toLowerCase().includes('not connected')) {
        setSapStatus(null);
      }
    }
    setLoading(false);
  };

  const handleAnalyzeATCFinding = async (finding: any) => {
    setLoading(true); setError(''); setView('analysis');
    try {
      const res = await api.analyzeSAPPackageObjects([{ name: finding.object_name, type: finding.object_type || 'PROG' }]);
      if (res.sessions && res.sessions.length > 0) {
        setSession(res.sessions[0]);
        setView('fixes');
      } else {
        throw new Error('Analysis did not produce a session');
      }
    } catch (e: any) {
      setError(e.message);
      setView('sap_atc');
      if (e.message.toLowerCase().includes('not connected')) {
        setSapStatus(null);
      }
    }
    setLoading(false);
  };

  const toggleAtcPriorityFilter = (p: string) => {
    setAtcPriorityFilter(prev =>
      prev.includes(p) ? prev.filter(x => x !== p) : [...prev, p]
    );
  };

  const handleAtcSort = (field: string) => {
    if (atcSortField === field) {
      setAtcSortDir(prev => prev === 'asc' ? 'desc' : 'asc');
    } else {
      setAtcSortField(field);
      setAtcSortDir('asc');
    }
  };

  const filteredAtcFindings = atcFindings
    .filter(f => atcPriorityFilter.includes(f.priority))
    .sort((a, b) => {
      const dir = atcSortDir === 'asc' ? 1 : -1;
      if (atcSortField === 'priority') {
        const pOrder: Record<string, number> = { P1: 1, P2: 2, P3: 3 };
        return (( pOrder[a.priority] || 9) - (pOrder[b.priority] || 9)) * dir;
      }
      if (atcSortField === 'check_title') {
        return (a.check_title || '').localeCompare(b.check_title || '') * dir;
      }
      if (atcSortField === 'object_name') {
        return (a.object_name || '').localeCompare(b.object_name || '') * dir;
      }
      if (atcSortField === 'message') {
        return (a.message || '').localeCompare(b.message || '') * dir;
      }
      return 0;
    });

  const atcPriorityCounts = {
    P1: atcFindings.filter(f => f.priority === 'P1').length,
    P2: atcFindings.filter(f => f.priority === 'P2').length,
    P3: atcFindings.filter(f => f.priority === 'P3').length,
  };

  const handleRunATCOnPackage = async () => {
    if (!atcRunPackage.trim()) return;
    setLoading(true); setError('');
    try {
      const result = await api.runATCOnPackage(atcRunPackage);
      // After the run, fetch the worklist findings
      const res = await api.getSAPATCFindings(result.worklist_id);
      setAtcFindings(res.findings);
      setSelectedAtcResult({ id: result.worklist_id, title: `ATC Run on ${result.package}`, timestamp: new Date().toISOString() });
      // Also refresh the results list
      await fetchATCResults();
    } catch (e: any) {
      setError(e.message);
    }
    setLoading(false);
  };

  const handleFetchPackageObjects = async () => {
    setLoading(true); setError('');
    try {
      const objects = await api.getSAPPackageObjects(packageName);
      setPackageObjects(objects);
      setSelectedObjects({});
    } catch (e: any) {
      setError(e.message);
      if (e.message.toLowerCase().includes('not connected')) {
        setSapStatus(null);
      }
    }
    setLoading(false);
  };

  const handleToggleObjectSelection = (name: string) => {
    setSelectedObjects(prev => ({ ...prev, [name]: !prev[name] }));
  };

  const handleToggleAllObjects = () => {
    const allSelected = packageObjects.every(obj => selectedObjects[obj.name]);
    const next: Record<string, boolean> = {};
    if (!allSelected) {
      packageObjects.forEach(obj => { next[obj.name] = true; });
    }
    setSelectedObjects(next);
  };

  const handleAnalyzeSelectedObjects = async () => {
    const toAnalyze = packageObjects
      .filter(obj => selectedObjects[obj.name])
      .map(obj => ({ name: obj.name, type: obj.type }));
    if (toAnalyze.length === 0) return;
    
    setLoading(true); setError(''); setView('analysis');
    try {
      const res = await api.analyzeSAPPackageObjects(toAnalyze);
      if (res.sessions && res.sessions.length > 0) {
        setSession(res.sessions[res.sessions.length - 1]);
        setView('fixes');
      } else {
        setError('No objects could be successfully analyzed.');
        setView('sap_packages');
      }
    } catch (e: any) { setError(e.message); setView('sap_packages'); }
    setLoading(false);
  };

  // Check connection status on mount
  useEffect(() => {
    const checkConnection = async () => {
      try {
        const status = await api.getSAPStatus();
        if (status && status.connected) {
          setSapStatus(status);
        }
      } catch (e) {
        console.warn('Failed to fetch SAP status on mount', e);
      }
    };
    checkConnection();
  }, []);

  useEffect(() => {
    if (view === 'sap_atc' && sapStatus?.connected) {
      fetchATCResults();
    }
  }, [view, sapStatus?.connected]);

  /* ─── SAP Connect ────────────────────────────────────────────── */
  const handleSAPConnect = async () => {
    setLoading(true); setError('');
    try {
      const status = await api.connectSAP(sapForm);
      setSapStatus(status);
      if (!status.connected) setError(status.message);
    } catch (e: any) { setError(e.message); }
    setLoading(false);
  };

  /* ─── File Upload ────────────────────────────────────────────── */
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true); setError('');
    try {
      const result = await api.uploadFile(file);
      setSourceCode(result.source_code);
      setObjectName(result.object_name);
    } catch (e: any) { setError(e.message); }
    setLoading(false);
  };

  const handleDragDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (!file) return;
    setLoading(true); setError('');
    try {
      const result = await api.uploadFile(file);
      setSourceCode(result.source_code);
      setObjectName(result.object_name);
    } catch (e: any) { setError(e.message); }
    setLoading(false);
  }, []);

  /* ─── Start Analysis ─────────────────────────────────────────── */
  const handleAnalyze = async () => {
    if (!sourceCode.trim()) { setError('No source code to analyze'); return; }
    setLoading(true); setError(''); setView('analysis');
    try {
      const result = await api.startAnalysis(sourceCode, objectName || 'UPLOADED_PROGRAM');
      setSession(result.session);
      if (result.session.fixes?.length > 0) setView('fixes');
    } catch (e: any) { setError(e.message); }
    setLoading(false);
  };

  /* ─── Fix Actions ────────────────────────────────────────────── */
  const handleFixAction = async (fixId: string, action: string) => {
    if (!session) return;
    try {
      await api.fixAction(session.id, fixId, action);
      const updated = await api.getSession(session.id);
      setSession(updated.session);
    } catch (e: any) { setError(e.message); }
  };

  const handleBulkApprove = async () => {
    if (!session) return;
    try {
      await api.bulkApprove(session.id, 0.9);
      const updated = await api.getSession(session.id);
      setSession(updated.session);
    } catch (e: any) { setError(e.message); }
  };

  /* ─── Render ─────────────────────────────────────────────────── */
  return (
    <div className="app-layout">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-logo">
            <h1>CleanCore AI</h1>
            <span className="badge">v1.0</span>
          </div>
          <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 8 }}>Code Remediation Engine</p>
        </div>
        <nav className="sidebar-nav">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.id} className={`nav-item nav-${item.id} ${view === item.id ? 'active' : ''}`} onClick={() => setView(item.id)}>
                <Icon className="nav-icon" size={18} aria-hidden="true" style={{ color: view === item.id ? '#fff' : item.color }} />
                <span>{item.label}</span>
                {item.id === 'fixes' && session && session.fixes.filter(f => f.status === 'pending_review').length > 0 && (
                  <span className="badge badge-pending" style={{ marginLeft: 'auto' }}>
                    {session.fixes.filter(f => f.status === 'pending_review').length}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
        {session && (
          <div style={{ padding: 'var(--space-md)', borderTop: '1px solid var(--border)', fontSize: '0.75rem' }}>
            <div style={{ color: 'var(--text-muted)', marginBottom: 4 }}>Session Active</div>
            <div style={{ color: 'var(--accent)', fontWeight: 600 }}>{session.object_name}</div>
            <div className="progress-bar-track" style={{ marginTop: 8 }}>
              <div className="progress-bar-fill" style={{ width: `${session.progress}%` }} />
            </div>
          </div>
        )}
      </aside>

      {/* Main Content */}
      <main className="main-content">
        <header className="app-topbar" aria-label="Application brand">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem', fontWeight: 500, color: 'var(--text-muted)' }}>
            <span>CleanCore AI</span>
            <ChevronRight size={14} style={{ color: '#94a3b8' }} />
            <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
              {view === 'home' && 'Dashboard'}
              {view === 'connection' && 'SAP Connection'}
              {view === 'sap_atc' && 'SAP ATC Results Hub'}
              {view === 'sap_packages' && 'SAP Package Explorer'}
              {view === 'upload' && 'Upload & Analyze'}
              {view === 'fixes' && 'Fix Approval Queue'}
              {view === 'audit' && 'Audit Trail'}
              {view === 'analysis' && 'Analysis Pipeline'}
            </span>
          </div>
          <div className="client-logo-container">
            <img src="/motiveminds-logo.png" alt="MotiveMinds" className="client-logo" />
          </div>
        </header>

        {error && (
          <div className="card fade-in" style={{ marginBottom: 'var(--space-md)', borderColor: 'var(--error)', background: 'var(--error-bg)' }}>
            <span style={{ color: 'var(--error)' }}>⚠ {error}</span>
            <button className="btn btn-icon btn-sm btn-secondary" style={{ marginLeft: 'auto', float: 'right' }} onClick={() => setError('')} aria-label="Dismiss error">
              <X size={15} aria-hidden="true" />
            </button>
          </div>
        )}

        {/* ─── HOME VIEW ──────────────────────────────────── */}
        {view === 'home' && (
          <div className="fade-in">
            <div className="hero">
              <h2>SAP ECC → S/4HANA Code Remediation</h2>
              <p>AI-powered analysis, auto-fix, and validation of custom ABAP code for S/4HANA Clean Core compliance. SUM-inspired workflow with developer approval gates.</p>
              <div className="hero-actions">
                <button className="btn btn-primary btn-lg" onClick={() => setView('upload')}>
                  <Upload size={18} aria-hidden="true" />
                  Upload ABAP File
                </button>
                <button className="btn btn-secondary btn-lg" onClick={() => setView('connection')}>
                  <Link2 size={18} aria-hidden="true" />
                  Connect to SAP
                </button>
              </div>
            </div>
            <PhaseStepper activePhase={session ? getActivePhase(session.status) : 0} />
            {session && (
              <div className="stats-grid">
                <div className="stat-card"><div className="stat-value">{session.total_findings}</div><div className="stat-label">Total Findings</div></div>
                <div className="stat-card"><div className="stat-value">{session.fixes_generated}</div><div className="stat-label">Fixes Generated</div></div>
                <div className="stat-card"><div className="stat-value">{session.fixes_approved}</div><div className="stat-label">Approved</div></div>
                <div className="stat-card"><div className="stat-value">{session.human_review_count}</div><div className="stat-label">Human Review</div></div>
                <div className="stat-card"><div className="stat-value">{session.tokens_used}</div><div className="stat-label">LLM Tokens Used</div></div>
                <div className="stat-card"><div className="stat-value">{session.fixes.filter(f => f.tier === 'tier1_rule').length}</div><div className="stat-label">Rule-Based (Free)</div></div>
              </div>
            )}
          </div>
        )}

        {/* ─── SAP CONNECTION VIEW ────────────────────────── */}
        {view === 'connection' && (
          <div className="fade-in">
            <h2 className="section-title" style={{ marginBottom: 'var(--sapContent_Space_Large)' }}>
              <Cable size={24} aria-hidden="true" />
              SAP System Connection
            </h2>

            <div className="card" style={{ maxWidth: 620 }}>
              {/* ── ADT PRIMARY SECTION ── */}
              <div className="card-title" style={{ marginBottom: 4 }}>ADT REST API — Primary Connection</div>
              <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 'var(--sapContent_Space_Medium)' }}>
                Connects to SAP S/4HANA via HTTPS using the ABAP Development Tools (ADT) REST API.
                Works through Cloud Connector, SAProuter, and corporate firewalls — no NW RFC SDK required.
              </p>

              <div className="form-group">
                <label className="form-label">ADT BASE URL <span style={{color:'var(--error)'}}>*</span></label>
                <input
                  id="adt-url-input"
                  className="form-input"
                  value={sapForm.adt_url}
                  onChange={e => setSapForm({ ...sapForm, adt_url: e.target.value })}
                  placeholder="https://my-s4hana.example.com:44300"
                />
                <div style={{ fontSize: '0.73rem', color: 'var(--text-muted)', marginTop: 4 }}>
                  Typically port <strong>44300</strong> (HTTPS) or <strong>8443</strong> for Cloud Connector.
                  Do not add a trailing slash.
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 80px', gap: 'var(--sapContent_Gap)', marginBottom: 'var(--sapContent_Space_Medium)' }}>
                <div className="form-group" style={{marginBottom:0}}>
                  <label className="form-label">SAP CLIENT</label>
                  <input id="sap-client-input" className="form-input" value={sapForm.client} onChange={e => setSapForm({ ...sapForm, client: e.target.value })} placeholder="100" />
                </div>
                <div className="form-group" style={{marginBottom:0}}>
                  <label className="form-label">USER <span style={{color:'var(--error)'}}>*</span></label>
                  <input id="sap-user-input" className="form-input" value={sapForm.user} onChange={e => setSapForm({ ...sapForm, user: e.target.value })} autoComplete="username" />
                </div>
                <div className="form-group" style={{marginBottom:0}}>
                  <label className="form-label">LANG</label>
                  <input id="sap-lang-input" className="form-input" value={sapForm.lang} onChange={e => setSapForm({ ...sapForm, lang: e.target.value })} placeholder="EN" maxLength={2} />
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">PASSWORD <span style={{color:'var(--error)'}}>*</span></label>
                <input id="sap-password-input" className="form-input" type="password" value={sapForm.passwd} onChange={e => setSapForm({ ...sapForm, passwd: e.target.value })} autoComplete="current-password" />
              </div>

              <div style={{ marginBottom: 'var(--sapContent_Space_Medium)' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem' }}>
                  <input type="checkbox" id="adt-verify-ssl" checked={sapForm.adt_verify_ssl} onChange={e => setSapForm({ ...sapForm, adt_verify_ssl: e.target.checked })} />
                  Verify SSL Certificate
                </label>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4, paddingLeft: 22 }}>
                  Leave unchecked for self-signed certificates (common in dev/test landscapes).
                </div>
              </div>

              {/* ── RFC FALLBACK (OPTIONAL) ── */}
              <div style={{ padding: 'var(--sapContent_Space_Small)', background: 'var(--sapNeutralBackground)', borderRadius: 'var(--sapElement_BorderCornerRadius)', marginBottom: 'var(--sapContent_Space_Medium)', border: '1px solid var(--border)' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem' }}>
                  <input type="checkbox" id="rfc-fallback-toggle" checked={sapForm.use_adt_fallback} onChange={e => setSapForm({ ...sapForm, use_adt_fallback: e.target.checked })} />
                  Enable PyRFC Fallback (Optional — requires SAP NW RFC SDK installed locally)
                </label>
                {sapForm.use_adt_fallback && (
                  <div style={{ marginTop: 'var(--sapContent_Space_Small)', display: 'grid', gridTemplateColumns: '1fr 80px', gap: 'var(--sapContent_Gap)' }}>
                    <div className="form-group" style={{marginBottom:0}}>
                      <label className="form-label">APP SERVER HOST</label>
                      <input id="ashost-input" className="form-input" value={sapForm.ashost} onChange={e => setSapForm({ ...sapForm, ashost: e.target.value })} placeholder="e.g. 192.168.1.100 or my-sap-server.corp" />
                    </div>
                    <div className="form-group" style={{marginBottom:0}}>
                      <label className="form-label">SYS NO</label>
                      <input id="sysnr-input" className="form-input" value={sapForm.sysnr} onChange={e => setSapForm({ ...sapForm, sysnr: e.target.value })} placeholder="00" />
                    </div>
                  </div>
                )}
              </div>

              <button
                id="sap-connect-btn"
                className="btn btn-emphasized"
                onClick={handleSAPConnect}
                disabled={loading || !sapForm.user.trim() || (!sapForm.adt_url.trim() && !sapForm.ashost.trim())}
              >
                {loading ? <><span className="spinner" /> Connecting...</> : <><Link2 size={17} aria-hidden="true" /> Connect to SAP</>}
              </button>

              {!sapForm.adt_url.trim() && !sapForm.ashost.trim() && (
                <div style={{ marginTop: 8, fontSize: '0.78rem', color: 'var(--error)', paddingLeft: 2 }}>
                  ⚠ Enter an ADT Base URL above to connect via REST API.
                </div>
              )}

              {sapStatus && (
                <div className="card" style={{ marginTop: 'var(--space-md)', borderColor: sapStatus.connected ? 'var(--success)' : 'var(--error)', background: sapStatus.connected ? 'rgba(38,160,83,0.07)' : 'rgba(187,16,16,0.06)' }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                    <span className={`badge ${sapStatus.connected ? 'badge-approved' : 'badge-rejected'}`}>
                      {sapStatus.connected ? '✓ Connected' : '✕ Failed'}
                    </span>
                    <div style={{ flex: 1 }}>
                      {sapStatus.connected ? (
                        <div style={{ fontSize: '0.85rem' }}>
                          <div><strong>{sapStatus.system_id || 'S/4HANA'}</strong>{sapStatus.release ? ` · Release ${sapStatus.release}` : ''}</div>
                          <div style={{ color: 'var(--text-muted)', marginTop: 4 }}>{sapStatus.host}</div>
                          <div style={{ color: 'var(--success)', marginTop: 4, fontSize: '0.78rem' }}>{sapStatus.message}</div>
                        </div>
                      ) : (
                        <div style={{ fontSize: '0.82rem', color: 'var(--error)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                          {sapStatus.message}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ─── UPLOAD & ANALYZE VIEW ──────────────────────── */}
        {view === 'upload' && (
          <div className="fade-in">
            <h2 className="section-title" style={{ marginBottom: 'var(--space-lg)' }}>
              <FileCode2 size={24} aria-hidden="true" />
              Upload & Analyze ABAP Code
            </h2>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-lg)' }}>
              {/* Upload */}
              <div>
                <div className="upload-zone" onDragOver={e => e.preventDefault()} onDrop={handleDragDrop} onClick={() => fileRef.current?.click()}>
                  <div className="upload-icon"><FolderOpen size={48} aria-hidden="true" /></div>
                  <div className="upload-text"><strong>Click or drag & drop</strong> an ABAP file (.txt / .abap)</div>
                  <input ref={fileRef} type="file" accept=".txt,.abap,.ABAP" style={{ display: 'none' }} onChange={handleFileUpload} />
                </div>
                <div className="form-group" style={{ marginTop: 'var(--space-md)' }}>
                  <label className="form-label">Object Name</label>
                  <input className="form-input" value={objectName} onChange={e => setObjectName(e.target.value)} placeholder="e.g. ZMM_REPORT_01" />
                </div>
              </div>
              {/* Code Editor */}
              <div>
                <label className="form-label">ABAP Source Code (paste directly)</label>
                <textarea className="form-textarea" style={{ minHeight: 300 }} value={sourceCode} onChange={e => setSourceCode(e.target.value)}
                  placeholder={`REPORT ztest_migration.\n\nDATA: lv_matnr TYPE C LENGTH 18.\n\nSELECT * FROM vbuk INTO TABLE @DATA(lt_vbuk).\n\nMOVE lv_matnr TO lv_output.\n\nCALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'\n  EXPORTING it_fieldcat = lt_fcat\n  TABLES t_outtab = lt_vbuk.`} />
              </div>
            </div>
            <div style={{ marginTop: 'var(--space-lg)', display: 'flex', gap: 'var(--space-md)', alignItems: 'center' }}>
              <button className="btn btn-primary btn-lg" onClick={handleAnalyze} disabled={loading || !sourceCode.trim()}>
                {loading ? <><span className="spinner" /> Analyzing...</> : <><Rocket size={18} aria-hidden="true" /> Run Analysis Pipeline</>}
              </button>
              {sourceCode && <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>{sourceCode.split('\n').length} lines loaded</span>}
            </div>
          </div>
        )}

        {/* ─── ANALYSIS VIEW ──────────────────────────────── */}
        {view === 'analysis' && (
          <div className="fade-in">
            <h2 className="section-title" style={{ marginBottom: 'var(--space-lg)' }}>
              <Search size={24} aria-hidden="true" />
              Analysis Pipeline
            </h2>
            {session && <PhaseStepper activePhase={getActivePhase(session.status)} />}
            {loading && (
              <div className="card" style={{ textAlign: 'center', padding: 'var(--space-2xl)' }}>
                <div className="spinner" style={{ width: 40, height: 40, margin: '0 auto var(--space-md)' }} />
                <h3 className="pulse">{session?.current_step || 'Processing...'}</h3>
                {session && (
                  <div className="progress-container" style={{ maxWidth: 400, margin: '16px auto' }}>
                    <div className="progress-bar-track"><div className="progress-bar-fill" style={{ width: `${session.progress}%` }} /></div>
                    <div className="progress-text"><span>{session.status}</span><span>{session.progress.toFixed(0)}%</span></div>
                  </div>
                )}
              </div>
            )}
            {session && session.status === 'complete' && (
              <div>
                <div className="stats-grid">
                  <div className="stat-card"><div className="stat-value">{session.total_findings}</div><div className="stat-label">Findings</div></div>
                  <div className="stat-card"><div className="stat-value">{session.fixes_generated}</div><div className="stat-label">Fixes</div></div>
                  <div className="stat-card"><div className="stat-value">{session.human_review_count}</div><div className="stat-label">Need Review</div></div>
                  <div className="stat-card"><div className="stat-value">{session.tokens_used}</div><div className="stat-label">Tokens</div></div>
                </div>
                <button className="btn btn-primary" onClick={() => setView('fixes')}>
                  <Wrench size={17} aria-hidden="true" />
                  Review Fixes ({session.fixes.length})
                </button>
              </div>
            )}
          </div>
        )}

        {/* ─── FIXES / APPROVAL QUEUE VIEW ────────────────── */}
        {view === 'fixes' && session && (
          <div className="fade-in">
            <div className="card-header" style={{ marginBottom: 'var(--space-lg)' }}>
              <h2 className="section-title">
                <Wrench size={24} aria-hidden="true" />
                Fix Approval Queue — {session.object_name}
              </h2>
              <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
                <button className="btn btn-success btn-sm" onClick={handleBulkApprove}>
                  <Check size={15} aria-hidden="true" />
                  Bulk Approve (≥90%)
                </button>
                <span className="badge badge-pending">{session.fixes.filter(f => f.status === 'pending_review').length} Pending</span>
                <span className="badge badge-approved">{session.fixes_approved} Approved</span>
                <span className="badge badge-rejected">{session.fixes_rejected} Rejected</span>
              </div>
            </div>

            {session.fixes.map((fix, idx) => (
              <div key={fix.id} className="fix-card fade-in" style={{ animationDelay: `${idx * 0.05}s` }}>
                <div className="fix-card-header">
                  <div className="fix-card-meta">
                    <span className={`badge badge-${fix.priority.toLowerCase()}`}>{fix.priority}</span>
                    <span className={`badge badge-${fix.tier.replace('tier', 'tier')}`}>
                      {fix.tier === 'tier1_rule' ? 'Rule' : fix.tier === 'tier2_template' ? 'Template' : 'LLM'}
                    </span>
                    <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>{fix.category.replace(/_/g, ' ').toUpperCase()}</span>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>via {fix.worker_type}</span>
                  </div>
                  <div className="fix-card-actions">
                    <div className="confidence-meter" style={{ minWidth: 150 }}>
                      <div className="confidence-bar">
                        <div className={`confidence-fill ${fix.confidence >= 0.85 ? 'high' : fix.confidence >= 0.6 ? 'medium' : 'low'}`}
                             style={{ width: `${fix.confidence * 100}%` }} />
                      </div>
                      <span className="confidence-value">{(fix.confidence * 100).toFixed(0)}%</span>
                    </div>
                    {fix.requires_human_review && <span className="badge badge-review"><Eye size={12} aria-hidden="true" /> Human Review</span>}
                    <span className={`badge badge-${fix.status === 'approved' ? 'approved' : fix.status === 'rejected' ? 'rejected' : 'pending'}`}>
                      {fix.status.replace('_', ' ')}
                    </span>
                  </div>
                </div>
                <div className="fix-card-body">
                  <div className="fix-rationale">
                    <strong>Rationale:</strong> {fix.rationale}
                    {fix.sap_note_refs.length > 0 && (
                      <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        {fix.sap_note_refs.map(note => <span key={note} className="sap-note-ref">SAP Note {note}</span>)}
                      </div>
                    )}
                  </div>
                  <DiffViewer original={fix.original_code} fixed={fix.fixed_code} />
                  {fix.status === 'pending_review' && (
                    <div style={{ marginTop: 'var(--space-md)', display: 'flex', gap: 'var(--space-sm)' }}>
                      <button className="btn btn-success" onClick={() => handleFixAction(fix.id, 'approve')}><Check size={16} aria-hidden="true" /> Approve</button>
                      <button className="btn btn-danger" onClick={() => handleFixAction(fix.id, 'reject')}><X size={16} aria-hidden="true" /> Reject</button>
                    </div>
                  )}
                  {fix.tokens_used > 0 && (
                    <div style={{ marginTop: 8, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      Tokens used: {fix.tokens_used}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {session.fixes.length === 0 && (
              <div className="empty-state">
                <div className="empty-state-icon"><Check size={56} aria-hidden="true" /></div>
                <h3>No fixes needed!</h3>
                <p>Your code appears to be S/4HANA compliant.</p>
              </div>
            )}
          </div>
        )}

        {/* ─── AUDIT TRAIL VIEW ───────────────────────────── */}
        {view === 'audit' && session && (
          <div className="fade-in">
            <h2 className="section-title" style={{ marginBottom: 'var(--space-lg)' }}>
              <ClipboardList size={24} aria-hidden="true" />
              Audit Trail — {session.object_name}
            </h2>
            <div className="card">
              <table className="audit-table">
                <thead>
                  <tr><th>Timestamp</th><th>Action</th><th>Detail</th></tr>
                </thead>
                <tbody>
                  {session.audit_log.map((entry, i) => (
                    <tr key={i}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', whiteSpace: 'nowrap' }}>{entry.timestamp.replace('T', ' ').slice(0, 19)}</td>
                      <td><span className="badge" style={{ background: 'var(--accent-bg)', color: 'var(--accent)' }}>{entry.action}</span></td>
                      <td>{entry.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {session.audit_log.length === 0 && (
                <div className="empty-state"><p>No audit entries yet. Run an analysis to start.</p></div>
              )}
            </div>
          </div>
        )}

        {view === 'audit' && !session && (
          <div className="empty-state fade-in">
            <div className="empty-state-icon"><ClipboardList size={56} aria-hidden="true" /></div>
            <h3>No Active Session</h3>
            <p>Upload and analyze an ABAP file to generate audit entries.</p>
          </div>
        )}

        {view === 'fixes' && !session && (
          <div className="empty-state fade-in">
            <div className="empty-state-icon"><Wrench size={56} aria-hidden="true" /></div>
            <h3>No Fixes to Review</h3>
            <p>Upload and analyze an ABAP file first.</p>
            <button className="btn btn-primary" style={{ marginTop: 'var(--space-md)' }} onClick={() => setView('upload')}>
              <Upload size={17} aria-hidden="true" />
              Upload File
            </button>
          </div>
        )}

        {/* ─── SAP ATC HUB VIEW ────────────────────────── */}
        {view === 'sap_atc' && (
          <div className="fade-in">
            <h2 className="section-title" style={{ marginBottom: 'var(--space-lg)' }}>
              <Search size={24} aria-hidden="true" />
              SAP ATC Results Hub
            </h2>

            {!sapStatus?.connected ? (
              <div className="card" style={{ padding: 'var(--sapContent_Space_Large)', textAlign: 'center' }}>
                <div style={{ fontSize: '3rem', marginBottom: 16 }}>🔌</div>
                <h3 style={{ marginBottom: 8 }}>SAP Connection Required</h3>
                <p style={{ color: 'var(--text-muted)', marginBottom: 20, maxWidth: 420, margin: '0 auto 20px' }}>
                  Connect to an SAP system to retrieve central ATC check runs and findings.
                </p>
                <button className="btn btn-emphasized" onClick={() => setView('connection')}>
                  <Cable size={16} aria-hidden="true" />
                  Go to SAP Connection
                </button>
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr', gap: 'var(--sapContent_Gap)' }}>
                {/* Left Panel: Run list */}
                <div>
                  <div className="card" style={{ marginBottom: 12, padding: '16px 20px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                      <h3 style={{ fontSize: '0.95rem', fontWeight: 700 }}>ATC Check Runs</h3>
                      <button className="btn btn-secondary btn-sm" onClick={fetchATCResults} disabled={loading}>
                        <RefreshCw size={14} aria-hidden="true" />
                        Refresh
                      </button>
                    </div>
                    {/* Run ATC on Package */}
                    <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                      <input
                        className="form-input"
                        value={atcRunPackage}
                        onChange={e => setAtcRunPackage(e.target.value.toUpperCase())}
                        placeholder="Package name..."
                        style={{ flex: 1, fontSize: '0.8rem' }}
                      />
                      <button
                        className="btn btn-emphasized btn-sm"
                        onClick={handleRunATCOnPackage}
                        disabled={loading || !atcRunPackage.trim()}
                        title="Run ATC check on this package"
                      >
                        <Play size={14} aria-hidden="true" />
                        Run
                      </button>
                    </div>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: '55vh', overflowY: 'auto' }}>
                    {loading && atcResults.length === 0 && (
                      <div style={{ textAlign: 'center', padding: 32 }}>
                        <div className="spinner" style={{ width: 28, height: 28, margin: '0 auto 12px' }} />
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>Loading ATC runs...</div>
                      </div>
                    )}
                    {atcResults.map((run) => (
                      <div
                        key={run.id}
                        onClick={() => selectATCResult(run)}
                        className={`card fade-in`}
                        style={{
                          cursor: 'pointer',
                          borderLeft: selectedAtcResult?.id === run.id ? '4px solid var(--sapBrandColor)' : '4px solid transparent',
                          background: selectedAtcResult?.id === run.id ? '#f0f7ff' : 'var(--sapBaseColor)',
                          padding: '12px 16px',
                          margin: 0,
                          transition: 'all 0.15s ease',
                        }}
                      >
                        <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>{run.title}</div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4 }}>
                          ID: {run.id.length > 18 ? `${run.id.slice(0, 18)}…` : run.id
                        }</div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 }}>
                          <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                            {new Date(run.timestamp).toLocaleString()}
                          </span>
                          {run.findings_count > 0 && (
                            <span className="badge badge-pending" style={{ fontSize: '0.68rem' }}>
                              {run.findings_count}
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                    {!loading && atcResults.length === 0 && (
                      <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-muted)' }}>
                        <Info size={32} style={{ marginBottom: 8, opacity: 0.4 }} />
                        <div style={{ fontSize: '0.85rem' }}>No ATC check runs found.</div>
                        <div style={{ fontSize: '0.75rem', marginTop: 6 }}>
                          Enter a package name above and click <strong>Run</strong> to start a new ATC check.
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Right Panel: Findings */}
                <div className="card" style={{ margin: 0, display: 'flex', flexDirection: 'column', padding: 0 }}>
                  {selectedAtcResult ? (
                    <>
                      {/* Header */}
                      <div style={{ borderBottom: '1px solid #e5e5e5', padding: '16px 24px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                          <div>
                            <h3 style={{ fontSize: '1.05rem', fontWeight: 700, marginBottom: 4 }}>
                              {selectedAtcResult.title}
                            </h3>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                              Run ID: <code style={{ background: '#f0f1f2', padding: '2px 6px', borderRadius: 4, fontSize: '0.72rem' }}>{selectedAtcResult.id}</code>
                            </div>
                          </div>
                          <div style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-muted)' }}>
                            {atcFindings.length} finding{atcFindings.length !== 1 ? 's' : ''}
                          </div>
                        </div>
                      </div>

                      {/* Stats bar */}
                      {atcFindings.length > 0 && (
                        <div className="atc-stats-bar">
                          <div className="atc-stat-item atc-stat-p1">
                            <ShieldAlert size={15} />
                            <span className="atc-stat-count">{atcPriorityCounts.P1}</span>
                            <span className="atc-stat-label">P1 Critical</span>
                          </div>
                          <div className="atc-stat-item atc-stat-p2">
                            <AlertTriangle size={15} />
                            <span className="atc-stat-count">{atcPriorityCounts.P2}</span>
                            <span className="atc-stat-label">P2 Warning</span>
                          </div>
                          <div className="atc-stat-item atc-stat-p3">
                            <Info size={15} />
                            <span className="atc-stat-count">{atcPriorityCounts.P3}</span>
                            <span className="atc-stat-label">P3 Info</span>
                          </div>
                        </div>
                      )}

                      {/* Filter toolbar */}
                      <div className="atc-toolbar">
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                          <Filter size={14} style={{ color: 'var(--text-muted)' }} />
                          <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', fontWeight: 600 }}>Filter:</span>
                          {(['P1', 'P2', 'P3'] as const).map(p => (
                            <button
                              key={p}
                              className={`atc-filter-btn atc-filter-${p.toLowerCase()} ${atcPriorityFilter.includes(p) ? 'active' : ''}`}
                              onClick={() => toggleAtcPriorityFilter(p)}
                            >
                              {p} ({atcPriorityCounts[p]})
                            </button>
                          ))}
                        </div>
                        <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                          Showing {filteredAtcFindings.length} of {atcFindings.length}
                        </div>
                      </div>

                      {/* Findings table */}
                      <div style={{ overflowY: 'auto', flex: 1 }}>
                        <table className="audit-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                          <thead>
                            <tr>
                              <th className="sort-header" onClick={() => handleAtcSort('priority')} style={{ width: 80, padding: '10px 12px' }}>
                                Priority {atcSortField === 'priority' && (atcSortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />)}
                              </th>
                              <th className="sort-header" onClick={() => handleAtcSort('object_name')} style={{ padding: '10px 12px' }}>
                                Object {atcSortField === 'object_name' && (atcSortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />)}
                              </th>
                              <th className="sort-header" onClick={() => handleAtcSort('check_title')} style={{ padding: '10px 12px' }}>
                                Check Title {atcSortField === 'check_title' && (atcSortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />)}
                              </th>
                              <th className="sort-header" onClick={() => handleAtcSort('message')} style={{ padding: '10px 12px' }}>
                                Message {atcSortField === 'message' && (atcSortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />)}
                              </th>
                              <th style={{ padding: '10px 12px', textAlign: 'right' }}>Actions</th>
                            </tr>
                          </thead>
                          <tbody>
                            {filteredAtcFindings.map((finding, idx) => (
                              <tr
                                key={finding.id || idx}
                                className={`atc-priority-row atc-priority-${finding.priority.toLowerCase()}`}
                              >
                                <td style={{ padding: '10px 12px' }}>
                                  <span className={`badge badge-${finding.priority.toLowerCase()}`}>
                                    {finding.priority}
                                  </span>
                                </td>
                                <td style={{ padding: '10px 12px' }}>
                                  <div style={{ fontWeight: 600, fontSize: '0.84rem' }}>{finding.object_name}</div>
                                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                                    Line {finding.line} · {(finding.category || 'generic').replace(/_/g, ' ')}
                                  </div>
                                </td>
                                <td style={{ padding: '10px 12px', fontSize: '0.82rem' }}>{finding.check_title}</td>
                                <td style={{ padding: '10px 12px', fontSize: '0.82rem', color: '#475569' }}>{finding.message}</td>
                                <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                                  <button
                                    className="btn btn-emphasized btn-sm"
                                    onClick={() => handleAnalyzeATCFinding(finding)}
                                    disabled={loading}
                                  >
                                    <Wrench size={13} aria-hidden="true" />
                                    Fix
                                  </button>
                                </td>
                              </tr>
                            ))}
                            {filteredAtcFindings.length === 0 && atcFindings.length > 0 && (
                              <tr>
                                <td colSpan={5} style={{ textAlign: 'center', padding: 32, color: 'var(--text-muted)' }}>
                                  No findings match the current filter. Try adjusting the priority filter.
                                </td>
                              </tr>
                            )}
                            {atcFindings.length === 0 && (
                              <tr>
                                <td colSpan={5} style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>
                                  {loading ? (
                                    <><div className="spinner" style={{ width: 24, height: 24, margin: '0 auto 8px' }} /> Loading findings...</>
                                  ) : (
                                    'No findings in this check run.'
                                  )}
                                </td>
                              </tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                    </>
                  ) : (
                    <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--text-muted)' }}>
                      <BarChart3 size={48} style={{ marginBottom: 12, opacity: 0.3 }} />
                      <div style={{ fontSize: '0.95rem', fontWeight: 600 }}>Select an ATC Check Run</div>
                      <div style={{ fontSize: '0.82rem', marginTop: 6 }}>
                        Choose a run from the left panel to explore its findings.
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ─── SAP PACKAGE EXPLORER VIEW ────────────────── */}
        {view === 'sap_packages' && (
          <div className="fade-in">
            <h2 className="section-title" style={{ marginBottom: 'var(--space-lg)' }}>
              <FolderOpen size={24} aria-hidden="true" />
              SAP Package Explorer
            </h2>

            {!sapStatus?.connected ? (
              <div className="card" style={{ padding: 'var(--sapContent_Space_Medium)', textAlign: 'center' }}>
                <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>🔌</div>
                <h3>SAP Connection Required</h3>
                <p style={{ color: 'var(--text-muted)', marginBottom: 16 }}>
                  You must be connected to an SAP system to search and retrieve repository objects.
                </p>
                <button className="btn btn-primary" onClick={() => setView('connection')}>
                  Go to SAP Connection
                </button>
              </div>
            ) : (
              <div>
                {/* Search Bar */}
                <div className="card" style={{ marginBottom: 'var(--sapContent_Space_Small)' }}>
                  <div style={{ display: 'flex', gap: 'var(--sapContent_Gap)', alignItems: 'flex-end' }}>
                    <div className="form-group" style={{ flex: 1, marginBottom: 0 }}>
                      <label className="form-label">SAP PACKAGE NAME</label>
                      <input
                        className="form-input"
                        value={packageName}
                        onChange={e => setPackageName(e.target.value.toUpperCase())}
                        placeholder="e.g. ZCUSTOM"
                      />
                    </div>
                    <button className="btn btn-primary btn-emphasized" onClick={handleFetchPackageObjects} disabled={loading || !packageName.trim()}>
                      {loading ? 'Pulling...' : 'Pull Package Objects'}
                    </button>
                  </div>
                </div>

                {/* Objects Table */}
                {packageObjects.length > 0 && (
                  <div className="card" style={{ padding: '16px 24px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                      <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                        Found <strong>{packageObjects.length}</strong> objects bearing ABAP code.
                      </div>
                      <div style={{ display: 'flex', gap: 12 }}>
                        <button className="btn btn-secondary btn-sm" onClick={handleToggleAllObjects}>
                          {packageObjects.every(o => selectedObjects[o.name]) ? 'Deselect All' : 'Select All'}
                        </button>
                        <button
                          className="btn btn-primary btn-sm btn-emphasized"
                          disabled={Object.values(selectedObjects).filter(Boolean).length === 0 || loading}
                          onClick={handleAnalyzeSelectedObjects}
                        >
                          Analyze Selected ({Object.values(selectedObjects).filter(Boolean).length})
                        </button>
                      </div>
                    </div>

                    <div style={{ maxHeight: '50vh', overflowY: 'auto' }}>
                      <table className="audit-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                          <tr style={{ textAlign: 'left', borderBottom: '2px solid var(--border)' }}>
                            <th style={{ width: 40, padding: '8px 12px' }}>
                              <input
                                type="checkbox"
                                checked={packageObjects.length > 0 && packageObjects.every(o => selectedObjects[o.name])}
                                onChange={handleToggleAllObjects}
                              />
                            </th>
                            <th style={{ padding: '8px 12px' }}>Object Type</th>
                            <th style={{ padding: '8px 12px' }}>Object Name</th>
                            <th style={{ padding: '8px 12px' }}>Package</th>
                          </tr>
                        </thead>
                        <tbody>
                          {packageObjects.map((obj) => (
                            <tr
                              key={obj.name}
                              style={{
                                borderBottom: '1px solid var(--border)',
                                background: selectedObjects[obj.name] ? 'rgba(0,112,242,0.03)' : 'transparent'
                              }}
                            >
                              <td style={{ padding: '10px 12px' }}>
                                <input
                                  type="checkbox"
                                  checked={!!selectedObjects[obj.name]}
                                  onChange={() => handleToggleObjectSelection(obj.name)}
                                />
                              </td>
                              <td style={{ padding: '10px 12px' }}>
                                <span className={`badge`} style={{ background: '#e1e3e6', color: '#131e29' }}>
                                  {obj.type}
                                </span>
                              </td>
                              <td style={{ padding: '10px 12px', fontWeight: 600 }}>{obj.name}</td>
                              <td style={{ padding: '10px 12px', color: 'var(--text-muted)' }}>{obj.package}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
