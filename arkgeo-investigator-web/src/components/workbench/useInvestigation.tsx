/**
 * useInvestigationContext — shared cross-domain investigation state.
 *
 * Single React context provider that holds the active case/evidence/run/findings/
 * audit trail. Every domain (IMAGE, NETWORK, CASES) and the contextual bottom
 * console read from this. IMAGE populates it on upload; CASES restores it from
 * saved history.
 *
 * This is the client-side binding layer — the backend remains the forensic
 * source of truth, but the entity relationships (Case → Evidence → Run →
 * Finding → AuditEvent) live here so the whole UI is coherent.
 */
import React, { createContext, useContext, useState, useCallback, useMemo, useRef } from 'react';
import type { AnalyzeResponse, InvestigationSession, Observation } from '../../types';
import { api } from '../../api';
import { runImagePipeline } from '../../core/pipeline/ImagePipeline';
import type { ImagePipelineResult, PipelineProgress } from '../../core/types';
import {
  type InvestigationContext,
  type Case,
  type Evidence,
  type AnalysisRun,
  type Finding,
  type AuditEvent,
  type DomainId,
  emptyContext,
  caseIdFromRequest,
  evidenceIdFromSha,
  runIdFromRequest,
  deriveShortId,
  DEFAULT_TENANT,
  DEFAULT_WORKSPACE,
} from './entities';

/** Workspace a saved case belongs to (drives the Case Explorer filters). */
export type SavedCaseDomain = 'image' | 'network' | 'secops' | 'telecom';

interface SavedCase {
  caseId: string;
  evidenceId: string;
  runId: string;
  sha256: string;
  filename: string;
  source: string;
  confidence: number;
  tier: string;
  timestamp: number;
  anomalyCount: number;
  risk: 'critical' | 'medium' | 'low';
  /** Workspace origin — legacy records (no field) are treated as 'image'. */
  domain?: SavedCaseDomain;
  /** Optional analyst-supplied case name / label (Save Investigation prompt). */
  caseName?: string;
  /** Optional analyst-supplied tags. */
  tags?: string[];
}

const HISTORY_KEY = 'ark.caseHistory';
const SNAPSHOT_KEY = 'ark.caseSnapshots';
const SNAPSHOT_CAP = 12;

function loadHistory(): SavedCase[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.sort((a, b) => b.timestamp - a.timestamp) : [];
  } catch { return []; }
}

function saveHistory(list: SavedCase[]) {
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, 100))); } catch { /* non-blocking */ }
}

function pushHistory(rec: SavedCase) {
  const existing = loadHistory().filter(h => h.caseId !== rec.caseId);
  saveHistory([rec, ...existing].slice(0, 100));
}

/** A persisted snapshot that lets Restore fully re-hydrate a workspace. */
interface CaseSnapshot {
  result: AnalyzeResponse;
  findings: Finding[];
  auditTrail: AuditEvent[];
}

function loadSnapshots(): Record<string, CaseSnapshot> {
  try {
    const raw = localStorage.getItem(SNAPSHOT_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch { return {}; }
}

/** Trim an AnalyzeResponse before persisting to guard localStorage quota. */
function pruneResult(r: AnalyzeResponse): AnalyzeResponse {
  const copy: any = { ...r };
  if (Array.isArray(copy.analysis_log) && copy.analysis_log.length > 120) {
    copy.analysis_log = copy.analysis_log.slice(-120);
  }
  return copy;
}

function storeSnapshot(caseId: string, snap: CaseSnapshot) {
  try {
    const all = loadSnapshots();
    delete all[caseId];
    all[caseId] = snap;
    const keys = Object.keys(all);
    while (keys.length > SNAPSHOT_CAP) {
      const oldest = keys.shift();
      if (oldest) delete all[oldest];
    }
    localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(all));
  } catch {
    /* quota exceeded — drop the snapshot cache rather than corrupt the vault */
    try { localStorage.removeItem(SNAPSHOT_KEY); } catch { /* non-blocking */ }
  }
}

function dropSnapshot(caseId: string) {
  try {
    const all = loadSnapshots();
    delete all[caseId];
    localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(all));
  } catch { /* non-blocking */ }
}

/** Objective shape accepted by the ARK AI investigation API. */
export interface InvestigateObjective {
  goal?: string;
  subject?: string;
  domain?: string;
  claims_to_verify?: { field: string; value?: string | null }[];
  natural_language?: string;
}

export interface InvestigationContextValue extends InvestigationContext {
  /** The active domain (IMAGE / NETWORK / CASES). */
  domain: DomainId;
  setDomain: (d: DomainId) => void;
  /** Hydrate the context from a backend analysis result (IMAGE upload). */
  loadFromAnalysis: (resp: AnalyzeResponse, filename: string) => void;
  /** Restore a previously saved case from history (CASES explorer). */
  restoreCase: (saved: SavedCase) => void;
  /** Remove a single saved case from the client vault (local-only). */
  removeCase: (saved: SavedCase) => void;
  /** Purge the entire saved-case vault (local-only). */
  clearHistory: () => void;
  /** Compile the current workspace observations into a vault entry and make it
   *  appear immediately in the Case Explorer. Returns the saved record. */
  saveCase: (opts: {
    domain: SavedCaseDomain;
    caseName?: string;
    tags?: string[];
    filename?: string;
  }) => SavedCase;
  /** Reset to empty (new investigation). */
  clear: () => void;
  /** Saved investigation history (cross-domain case layer). */
  history: SavedCase[];
  /** Last backend result loaded (for tool views that still consume it directly). */
  result: AnalyzeResponse | null;
  /** Shared ARK AI investigation session (Plan / Agent / Evidence console). */
  session: InvestigationSession | null;
  invBusy: boolean;
  invError: string | null;
  /** Shared bottom-console active tab. */
  bottomTab: string;
  setBottomTab: (t: string) => void;
  /** Launch an AI investigation from the current evidence (context-aware). */
  startInvestigation: (file: File, objective: InvestigateObjective) => Promise<void>;
  /** Approve the proposed plan and run the adaptive loop. */
  approveInvestigation: () => Promise<void>;
  /** Resume a paused investigation. */
  resumeInvestigation: (steps: number) => Promise<void>;
  /** Poll the current session state. */
  refreshInvestigation: () => Promise<void>;
  /** Run the continuous image-intelligence cascade over an ingested asset and
   *  fold its observations, verdicts, timeline and location into the case. */
  runPipeline: (file: File, resp: AnalyzeResponse) => Promise<ImagePipelineResult>;
  /** The latest cascade result (classification, fusion verdicts, etc.). */
  pipeline: ImagePipelineResult | null;
  /** Progress of the in-flight cascade (null when idle). */
  pipelineProgress: PipelineProgress | null;
  /** Fold cross-domain observations (Network Workspace etc.) into the active
   *  case as findings + a single audit event. When no case is active yet, one
   *  is created on the fly (opts may set its domain + title). */
  appendCaseObservations: (obs: CaseObservation[], opts?: { domain?: DomainId; title?: string }) => void;
  /** Shared streaming terminal feed (Telecom console, network diagnostics).
   *  Bottom panel TERMINAL tab mirrors the latest entries live. */
  terminal: TerminalEntry[];
  pushTerminal: (level: 'info' | 'ok' | 'warn' | 'err', text: string) => void;
  clearTerminal: () => void;
}

/** One streaming line in the shared terminal feed. */
export interface TerminalEntry {
  id: string;
  ts: string;
  level: 'info' | 'ok' | 'warn' | 'err';
  text: string;
}

/** Simplified observation input accepted by appendCaseObservations. */
export interface CaseObservation {
  id?: string;
  type: string;
  status: Observation['status'];
  layer: string;
  label: string;
  detail: string;
  source?: Observation['source'];
  confidence?: number | null;
}

const Ctx = createContext<InvestigationContextValue | null>(null);

export function InvestigationProvider({ children }: { children: React.ReactNode }) {
  const [base, setBase] = useState<InvestigationContext>(emptyContext);
  const [domain, setDomain] = useState<DomainId>('image');
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [history, setHistory] = useState<SavedCase[]>(() => loadHistory());

  // Shared ARK AI investigation session + bottom-console tab.
  const [session, setSession] = useState<InvestigationSession | null>(null);
  const [invBusy, setInvBusy] = useState(false);
  const [invError, setInvError] = useState<string | null>(null);
  const [bottomTab, setBottomTab] = useState('problems');
  const [pipeline, setPipeline] = useState<ImagePipelineResult | null>(null);
  const [pipelineProgress, setPipelineProgress] = useState<PipelineProgress | null>(null);
  const [terminal, setTerminal] = useState<TerminalEntry[]>([]);
  const sessionRef = useRef<InvestigationSession | null>(null);
  sessionRef.current = session;
  const baseRef = useRef<InvestigationContext>(base);
  baseRef.current = base;
  const resultRef = useRef<AnalyzeResponse | null>(result);
  resultRef.current = result;

  const pushTerminal = useCallback((level: 'info' | 'ok' | 'warn' | 'err', text: string) => {
    const now = new Date();
    const entry: TerminalEntry = {
      id: `T${now.getTime()}-${Math.random().toString(36).slice(2, 7)}`,
      ts: now.toLocaleTimeString('en-GB', { hour12: false }),
      level,
      text,
    };
    setTerminal(t => [...t.slice(-499), entry]);
    setBottomTab('terminal');
  }, []);

  const clearTerminal = useCallback(() => setTerminal([]), []);

  /** Fold investigation outputs (findings + agent audit trail) into the case. */
  const mergeInvestigation = useCallback((s: InvestigationSession) => {
    setBase(b => {
      if (!b.activeCase) return b;
      const caseId = b.activeCase.id;
      const extraFindings: Finding[] = [];
      (s.findings || []).forEach(f => {
        if (b.findings.some(ex => ex.message === f.claim)) return;
        extraFindings.push({
          id: deriveShortId('FND', f.finding_id),
          runId: b.activeRun?.id || s.case_id,
          caseId,
          type: (f.claim_type || 'FINDING').toUpperCase(),
          severity: f.severity === 'high' || f.severity === 'critical' ? 'HIGH' as const
            : f.severity === 'medium' ? 'MEDIUM' as const : 'LOW' as const,
          status: f.severity === 'high' || f.severity === 'critical' ? 'WARNING' as const
            : 'INFO' as const,
          message: f.claim,
        });
      });
      const extraAudit: AuditEvent[] = (s.activity_log || []).map((e, i) => ({
        id: deriveShortId('AUD', 'AGENT' + s.investigation_id + i),
        caseId,
        evidenceId: b.activeEvidence?.id,
        runId: b.activeRun?.id,
        timestamp: Date.now(),
        action: `ARK AI agent: ${e.tool_id} ${e.status}`,
        detail: e.message,
        actor: 'ark-ai',
      }));
      const nb = {
        ...b,
        findings: [...b.findings, ...extraFindings],
        auditTrail: [...b.auditTrail, ...extraAudit],
        updatedAt: Date.now(),
      };
      const res = resultRef.current;
      if (res) {
        storeSnapshot(caseId, { result: pruneResult(res), findings: nb.findings, auditTrail: nb.auditTrail });
      }
      return nb;
    });
  }, []);

  const startInvestigation = useCallback(async (file: File, objective: InvestigateObjective) => {
    setInvBusy(true);
    setInvError(null);
    try {
      const s = await api.createInvestigation(file, objective);
      setSession(s);
      setBottomTab('plan');
    } catch (err) {
      setInvError(err instanceof Error ? err.message : 'Failed to start investigation');
    } finally {
      setInvBusy(false);
    }
  }, []);

  const approveInvestigation = useCallback(async () => {
    const current = sessionRef.current;
    if (!current) return;
    setInvBusy(true);
    setInvError(null);
    try {
      const s = await api.approveInvestigation(current.investigation_id);
      setSession(s);
      mergeInvestigation(s);
    } catch (err) {
      setInvError(err instanceof Error ? err.message : 'Approval failed');
    } finally {
      setInvBusy(false);
    }
  }, [mergeInvestigation]);

  const resumeInvestigation = useCallback(async (steps: number) => {
    const current = sessionRef.current;
    if (!current) return;
    setInvBusy(true);
    setInvError(null);
    try {
      const s = await api.resumeInvestigation(current.investigation_id, { max_steps: steps });
      setSession(s);
      mergeInvestigation(s);
    } catch (err) {
      setInvError(err instanceof Error ? err.message : 'Resume failed');
    } finally {
      setInvBusy(false);
    }
  }, [mergeInvestigation]);

  const refreshInvestigation = useCallback(async () => {
    const current = sessionRef.current;
    if (!current) return;
    try {
      const s = await api.getInvestigation(current.investigation_id);
      setSession(s);
      mergeInvestigation(s);
    } catch (err) {
      setInvError(err instanceof Error ? err.message : 'Refresh failed');
    }
  }, [mergeInvestigation]);

  const loadFromAnalysis = useCallback((resp: AnalyzeResponse, filename: string) => {
    const caseId = caseIdFromRequest(resp.request_id);
    const evidenceId = evidenceIdFromSha(resp.image_sha256);
    const runId = runIdFromRequest(resp.request_id);
    const now = resp.created_at ? new Date(resp.created_at).getTime() : Date.now();

    const activeCase: Case = {
      id: caseId,
      workspaceId: DEFAULT_WORKSPACE.id,
      title: filename,
      domain: 'image',
      createdAt: now,
      updatedAt: now,
      status: 'open',
    };

    const activeEvidence: Evidence = {
      id: evidenceId,
      caseId,
      sha256: resp.image_sha256,
      filename,
      mimeType: resp.file_format || 'image/jpeg',
      byteSize: (resp.deep_metadata?.file_info?.file_size as number) || undefined,
      domain: 'image',
      ingestedAt: now,
    };

    const activeRun: AnalysisRun = {
      id: runId,
      evidenceId,
      caseId,
      source: resp.source,
      tier: resp.consensus.tier_used,
      confidence: resp.consensus.confidence_score,
      startedAt: now,
      completedAt: now,
      analysisLog: resp.analysis_log || [],
    };

    const findings: Finding[] = [];
    (resp.consistency_findings || []).forEach((f) => {
      findings.push({
        id: deriveShortId('FND', f.type + f.message),
        runId, caseId,
        type: f.type,
        severity: f.severity,
        status: f.status,
        message: f.message,
      });
    });
    (resp.contradictions || []).forEach((c, i) => {
      findings.push({
        id: deriveShortId('FND', 'CONTRADICTION' + i + c.what_conflicts),
        runId, caseId,
        type: c.type || 'CONTRADICTION',
        severity: c.severity,
        status: c.severity === 'HIGH' ? 'ERROR' : 'WARNING',
        message: c.what_conflicts,
      });
    });
    if (resp.exif_missing) findings.push({ id: deriveShortId('FND', 'EXIF_MISSING'), runId, caseId, type: 'METADATA', severity: 'MEDIUM', status: 'WARNING', message: 'EXIF metadata stripped or missing' });
    if (resp.steganography_detected) findings.push({ id: deriveShortId('FND', 'STEGO'), runId, caseId, type: 'INTEGRITY', severity: 'HIGH', status: 'ERROR', message: `Steganographic trailing bytes after EOF (${resp.trailing_bytes_count})` });
    if (resp.gps_spoofing_detected) findings.push({ id: deriveShortId('FND', 'GPS_SPOOF'), runId, caseId, type: 'GEOLOCATION', severity: 'HIGH', status: 'ERROR', message: 'GPS spoofing suspected' });

    // Canonical observations → findings, so File Forensics evidence flows into
    // the case Investigation workspace (never a silent "Evidence: 0").
    const observations = resp.observations || resp.evidence_summary?.observations || [];
    observations.forEach((obs) => {
      const severity: Finding['severity'] = obs.status === 'ANOMALY' ? 'HIGH' : obs.status === 'UNAVAILABLE' ? 'LOW' : 'LOW';
      const status: Finding['status'] = obs.status === 'ANOMALY' ? 'WARNING' : obs.status === 'OBSERVED' ? 'OK' : 'INFO';
      findings.push({
        id: deriveShortId('FND', 'OBS' + obs.id),
        runId, caseId,
        type: obs.type,
        severity,
        status,
        message: `${obs.label} — ${obs.detail}`,
      });
    });

    const auditTrail: AuditEvent[] = [
      { id: deriveShortId('AUD', 'INGEST' + caseId), caseId, evidenceId, runId, timestamp: now, action: 'Evidence acquired', detail: `SHA-256: ${resp.image_sha256.slice(0, 24)}...`, actor: 'system' },
      { id: deriveShortId('AUD', 'HASH' + caseId), caseId, evidenceId, runId, timestamp: now, action: 'Hashes computed', detail: `SHA-256 / SHA-1 / MD5 custody certificate`, actor: 'system' },
      { id: deriveShortId('AUD', 'RUN' + caseId), caseId, evidenceId, runId, timestamp: now, action: 'Analysis run completed', detail: `Source: ${resp.source} (${resp.consensus.tier_used}) · Confidence: ${Math.round(resp.consensus.confidence_score * 100)}%`, actor: 'system' },
    ];
    if (observations.length) {
      auditTrail.push({
        id: deriveShortId('AUD', 'OBS' + caseId),
        caseId, evidenceId, runId, timestamp: now,
        action: `${observations.length} observations recorded`,
        detail: `Structured evidence across ${new Set(observations.map(o => o.layer)).size} forensic layers`,
        actor: 'system',
      });
    }
    if (resp.image_classification) {
      auditTrail.push({
        id: deriveShortId('AUD', 'CLASS' + caseId),
        caseId, evidenceId, runId, timestamp: now,
        action: `Asset classified: ${resp.image_classification}`,
        detail: 'Image type selected for downstream investigation strategy',
        actor: 'system',
      });
    }

    setBase({
      tenant: DEFAULT_TENANT,
      workspace: DEFAULT_WORKSPACE,
      activeCase,
      activeEvidence,
      activeRun,
      findings,
      auditTrail,
      reports: [],
    });
    setResult(resp);
    setDomain('image');

    // Persist to cross-domain case history
    const anomalyCount =
      (resp.steganography_detected ? 1 : 0) +
      (resp.gps_spoofing_detected ? 1 : 0) +
      (resp.exif_missing ? 1 : 0) +
      (resp.consistency_findings?.filter(f => f.status !== 'OK').length || 0) +
      (resp.contradictions?.length || 0);
    const risk: SavedCase['risk'] = anomalyCount >= 3 ? 'critical' : anomalyCount >= 1 ? 'medium' : 'low';
    const rec: SavedCase = {
      caseId, evidenceId, runId,
      sha256: resp.image_sha256,
      filename,
      source: resp.source,
      confidence: resp.consensus.confidence_score,
      tier: resp.consensus.tier_used,
      timestamp: now,
      anomalyCount,
      risk,
    };
    pushHistory(rec);
    setHistory(loadHistory());

    // Persist a full state snapshot so "Restore Session" can re-hydrate the
    // entire workspace (metadata, GPS, analysis logs, OSINT findings) instead
    // of only showing a toast.
    storeSnapshot(caseId, { result: pruneResult(resp), findings, auditTrail });
  }, []);

  /** Fold the continuous image-intelligence cascade into the active case:
   *  every pipeline observation becomes a finding (same FND-OBS pattern used
   *  for backend observations), and each step + the fusion summary are written
   *  to the audit trail. */
  const mergePipeline = useCallback((p: ImagePipelineResult) => {
    setPipeline(p);
    setPipelineProgress(null);
    // Fold frontend OCR→geocoding pins into the active result when the backend
    // response didn't already carry them (Feature 2).
    if (p.geo_candidates && p.geo_candidates.length > 0) {
      setResult(prev => {
        if (!prev || (prev.geo_candidates && prev.geo_candidates.length > 0)) return prev;
        return { ...prev, geo_candidates: p.geo_candidates };
      });
    }
    setBase(b => {
      if (!b.activeCase) return b;
      const caseId = b.activeCase.id;
      const runId = b.activeRun?.id ?? caseId;
      const evidenceId = b.activeEvidence?.id ?? caseId;
      const now = Date.now();

      const extraFindings: Finding[] = [];
      p.observations.forEach((obs) => {
        const msg = `${obs.label} — ${obs.detail}`;
        if (b.findings.some(ex => ex.message === msg)) return;
        extraFindings.push({
          id: deriveShortId('FND', 'OBS' + obs.id),
          runId,
          caseId,
          type: obs.type,
          severity: obs.status === 'ANOMALY' ? 'HIGH' as const : obs.status === 'UNAVAILABLE' ? 'LOW' as const : 'LOW' as const,
          status: obs.status === 'ANOMALY' ? 'WARNING' as const : obs.status === 'OBSERVED' ? 'OK' as const : 'INFO' as const,
          message: msg,
        });
      });

      const extraAudit: AuditEvent[] = [];
      p.steps.forEach((s) => {
        extraAudit.push({
          id: deriveShortId('AUD', 'PIPE' + s.step + s.name + s.elapsedMs),
          caseId,
          evidenceId,
          runId,
          timestamp: now,
          action: `Cascade step ${s.step}/${p.steps.length}: ${s.name}`,
          detail: s.ok
            ? `Completed in ${s.elapsedMs}ms — ${s.observations.length} observation(s)`
            : 'Step errored — see findings for details',
          actor: 'system',
        });
      });
      const verdicts = p.fusion?.verdicts || [];
      if (verdicts.length) {
        extraAudit.push({
          id: deriveShortId('AUD', 'FUSION' + caseId + verdicts.length),
          caseId,
          evidenceId,
          runId,
          timestamp: now,
          action: `Evidence fusion — ${verdicts.length} verdicts`,
          detail: verdicts.map(v => `${v.dimension}: ${v.status} — ${v.conclusion}`).join(' · '),
          actor: 'system',
        });
      }
      if (p.fusion?.location) {
        extraAudit.push({
          id: deriveShortId('AUD', 'LOC' + caseId + p.fusion.location.status),
          caseId,
          evidenceId,
          runId,
          timestamp: now,
          action: `Location assessment: ${p.fusion.location.status}`,
          detail: p.fusion.location.candidate || p.fusion.location.note,
          actor: 'system',
        });
      }

      const nb = {
        ...b,
        findings: [...b.findings, ...extraFindings],
        auditTrail: [...b.auditTrail, ...extraAudit],
        updatedAt: now,
      };
      const res = resultRef.current;
      if (res) {
        storeSnapshot(caseId, { result: pruneResult(res), findings: nb.findings, auditTrail: nb.auditTrail });
      }
      return nb;
    });
  }, []);

  /** Run the 5-step cascade over an ingested asset and fold it into the case. */
  const runPipeline = useCallback(async (file: File, resp: AnalyzeResponse) => {
    setPipelineProgress({ currentStep: 0, totalSteps: 5, name: 'Preparing cascade' });
    const p = await runImagePipeline(file, resp, {
      onProgress: (prog) => setPipelineProgress(prog),
    });
    mergePipeline(p);
    return p;
  }, [mergePipeline]);

  const restoreCase = useCallback((saved: SavedCase) => {
    const activeCase: Case = {
      id: saved.caseId, workspaceId: DEFAULT_WORKSPACE.id, title: saved.filename,
      domain: (saved.domain === 'secops' || saved.domain === 'network' || saved.domain === 'telecom') ? (saved.domain === 'telecom' ? 'network' : saved.domain) : 'image',
      createdAt: saved.timestamp, updatedAt: saved.timestamp, status: 'open',
    };
    const activeEvidence: Evidence = {
      id: saved.evidenceId, caseId: saved.caseId, sha256: saved.sha256, filename: saved.filename,
      mimeType: 'image/jpeg', domain: activeCase.domain, ingestedAt: saved.timestamp,
    };
    const activeRun: AnalysisRun = {
      id: saved.runId, evidenceId: saved.evidenceId, caseId: saved.caseId, source: saved.source,
      tier: saved.tier, confidence: saved.confidence, startedAt: saved.timestamp,
      completedAt: saved.timestamp, analysisLog: [],
    };
    // Full state re-hydration: a persisted snapshot restores the complete
    // analysis result (metadata, EXIF/GPS, analysis logs, OSINT findings) plus
    // the folded findings/audit trail, so the workspace is fully restored —
    // not merely a toast.
    const snap = loadSnapshots()[saved.caseId] || null;
    const findings = snap ? snap.findings : [];
    const auditTrail = snap ? snap.auditTrail : [];
    setBase(b => ({
      ...b, activeCase, activeEvidence, activeRun, findings, auditTrail, reports: [],
    }));
    if (snap) setResult(snap.result);
    else setResult(null);
    setDomain(activeCase.domain);
  }, []);

  const removeCase = useCallback((saved: SavedCase) => {
    dropSnapshot(saved.caseId);
    setHistory(prev => {
      const next = prev.filter(h => h.caseId !== saved.caseId);
      saveHistory(next);
      return next;
    });
  }, []);

  /** Purge the entire saved-case vault (Settings + Recent Sessions + Explorer). */
  const clearHistory = useCallback(() => {
    try { localStorage.removeItem(SNAPSHOT_KEY); } catch { /* non-blocking */ }
    setHistory(prev => { saveHistory([]); return []; });
  }, []);

  /** Compile the current workspace into a vault entry and surface it in the
   *  Case Explorer immediately. Persists a snapshot so Restore fully
   *  re-hydrates, and reuses the active case id when one exists. */
  const saveCase = useCallback((opts: {
    domain: SavedCaseDomain;
    caseName?: string;
    tags?: string[];
    filename?: string;
  }) => {
    const b = baseRef.current;
    const res = resultRef.current;
    const now = Date.now();
    const filename = opts.filename
      || b.activeEvidence?.filename
      || b.activeCase?.title
      || `${opts.domain.toUpperCase()} INVESTIGATION`;
    const caseId = b.activeCase?.id
      || deriveShortId('CASE', 'SAVE' + now.toString(16) + Math.floor(Math.random() * 1e6).toString(16));
    const risk: SavedCase['risk'] =
      b.findings.some(f => f.severity === 'HIGH') ? 'critical'
      : b.findings.length > 0 ? 'medium' : 'low';
    const rec: SavedCase = {
      caseId,
      evidenceId: b.activeEvidence?.id || deriveShortId('EVD', 'SAVE' + now.toString(16)),
      runId: b.activeRun?.id || deriveShortId('RUN', 'SAVE' + now.toString(16)),
      sha256: b.activeEvidence?.sha256 || 'MANUAL-SAVE',
      filename,
      source: b.activeRun?.source || 'MANUAL',
      confidence: b.activeRun?.confidence ?? 0.5,
      tier: b.activeRun?.tier || 'MANUAL',
      timestamp: now,
      anomalyCount: b.findings.length,
      risk,
      domain: opts.domain,
      caseName: opts.caseName?.trim() || undefined,
      tags: opts.tags?.length ? opts.tags : undefined,
    };
    pushHistory(rec);
    setHistory(loadHistory());
    if (res) {
      storeSnapshot(caseId, { result: pruneResult(res), findings: b.findings, auditTrail: b.auditTrail });
    }
    return rec;
  }, []);

  const clear = useCallback(() => {
    setBase(emptyContext());
    setResult(null);
    setSession(null);
    setInvError(null);
    setPipeline(null);
    setPipelineProgress(null);
  }, []);

  /** Fold cross-domain observations into the active case (Network Workspace,
   *  Vulnerability Matrix, future domains). Findings reuse the FND-OBS pattern
   *  so the Evidence / Problems consoles render them identically to pipeline
   *  observations. When no case is active yet, one is created on the fly so a
   *  standalone workspace (e.g. VULN run with no prior upload) still folds its
   *  findings into an open investigation. */
  const appendCaseObservations = useCallback((obs: CaseObservation[], opts?: { domain?: DomainId; title?: string }) => {
    if (!obs.length) return;
    setBase(b => {
      const now = Date.now();
      const hasCase = !!b.activeCase;
      const domain: DomainId = opts?.domain ?? (b.activeCase?.domain ?? 'network');
      const caseId: string = b.activeCase?.id ?? deriveShortId('CASE', 'OBS' + now.toString(16));
      const evidenceId: string = b.activeEvidence?.id ?? (hasCase ? caseId : deriveShortId('EVD', 'OBS' + now.toString(16)));
      const runId: string = b.activeRun?.id ?? (hasCase ? caseId : deriveShortId('RUN', 'OBS' + now.toString(16)));
      let base = b;
      if (!b.activeCase) {
        const title = opts?.title ?? 'Investigation Session';
        base = {
          ...b,
          activeCase: {
            id: caseId, workspaceId: DEFAULT_WORKSPACE.id, title,
            domain, createdAt: now, updatedAt: now, status: 'open',
          },
          activeEvidence: {
            id: evidenceId, caseId, sha256: 'MANUAL-OBS', filename: title,
            mimeType: 'application/json', domain, ingestedAt: now,
          },
          activeRun: {
            id: runId, evidenceId, caseId, source: 'TOOL_OBSERVATIONS',
            tier: 'MANUAL', confidence: 0.6, startedAt: now, completedAt: now, analysisLog: [],
          },
        };
      }
      const extraFindings: Finding[] = [];
      obs.forEach((o) => {
        const msg = `${o.label} — ${o.detail}`;
        if (base.findings.some(ex => ex.message === msg)) return;
        extraFindings.push({
          id: deriveShortId('FND', 'OBS' + (o.id || o.label + o.layer + msg)),
          runId, caseId,
          type: o.type,
          severity: o.status === 'ANOMALY' ? 'HIGH' as const : o.status === 'UNAVAILABLE' ? 'LOW' as const : 'LOW' as const,
          status: o.status === 'ANOMALY' ? 'WARNING' as const : o.status === 'OBSERVED' ? 'OK' as const : 'INFO' as const,
          message: msg,
        });
      });

      const extraAudit: AuditEvent[] = [];
      if (extraFindings.length) {
        extraAudit.push({
          id: deriveShortId('AUD', 'NW' + caseId + now),
          caseId, evidenceId, runId,
          timestamp: now,
          action: `${extraFindings.length} network observation(s) folded into case`,
          detail: `Layers: ${Array.from(new Set(obs.map(o => o.layer))).join(', ')}`,
          actor: 'system',
        });
      }

      const nb = {
        ...base,
        findings: [...base.findings, ...extraFindings],
        auditTrail: [...base.auditTrail, ...extraAudit],
        updatedAt: now,
      };
      const res = resultRef.current;
      if (res) {
        storeSnapshot(caseId, { result: pruneResult(res), findings: nb.findings, auditTrail: nb.auditTrail });
      }
      return nb;
    });
  }, []);

  const value = useMemo<InvestigationContextValue>(() => ({
    ...base, domain, result,
    setDomain, loadFromAnalysis, restoreCase, removeCase, clearHistory, saveCase, clear, history,
    session, invBusy, invError, bottomTab, setBottomTab,
    startInvestigation, approveInvestigation, resumeInvestigation, refreshInvestigation,
    runPipeline, pipeline, pipelineProgress, appendCaseObservations,
    terminal, pushTerminal, clearTerminal,
  }), [base, domain, result, loadFromAnalysis, restoreCase, removeCase, clearHistory, saveCase, clear, history,
      session, invBusy, invError, bottomTab,
      startInvestigation, approveInvestigation, resumeInvestigation, refreshInvestigation,
      runPipeline, pipeline, pipelineProgress, appendCaseObservations,
      terminal, pushTerminal, clearTerminal]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useInvestigation(): InvestigationContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useInvestigation must be used within InvestigationProvider');
  return v;
}

export type { SavedCase };
