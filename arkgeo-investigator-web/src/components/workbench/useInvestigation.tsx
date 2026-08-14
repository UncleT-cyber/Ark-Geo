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
import React, { createContext, useContext, useState, useCallback, useMemo } from 'react';
import type { AnalyzeResponse } from '../../types';
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
}

const HISTORY_KEY = 'ark.caseHistory';

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

export interface InvestigationContextValue extends InvestigationContext {
  /** The active domain (IMAGE / NETWORK / CASES). */
  domain: DomainId;
  setDomain: (d: DomainId) => void;
  /** Hydrate the context from a backend analysis result (IMAGE upload). */
  loadFromAnalysis: (resp: AnalyzeResponse, filename: string) => void;
  /** Restore a previously saved case from history (CASES explorer). */
  restoreCase: (saved: SavedCase) => void;
  /** Reset to empty (new investigation). */
  clear: () => void;
  /** Saved investigation history (cross-domain case layer). */
  history: SavedCase[];
  /** Last backend result loaded (for tool views that still consume it directly). */
  result: AnalyzeResponse | null;
}

const Ctx = createContext<InvestigationContextValue | null>(null);

export function InvestigationProvider({ children }: { children: React.ReactNode }) {
  const [base, setBase] = useState<InvestigationContext>(emptyContext);
  const [domain, setDomain] = useState<DomainId>('image');
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [history, setHistory] = useState<SavedCase[]>(() => loadHistory());

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

    const auditTrail: AuditEvent[] = [
      { id: deriveShortId('AUD', 'INGEST' + caseId), caseId, evidenceId, runId, timestamp: now, action: 'Evidence acquired', detail: `SHA-256: ${resp.image_sha256.slice(0, 24)}...`, actor: 'system' },
      { id: deriveShortId('AUD', 'HASH' + caseId), caseId, evidenceId, runId, timestamp: now, action: 'Hashes computed', detail: `SHA-256 / SHA-1 / MD5 custody certificate`, actor: 'system' },
      { id: deriveShortId('AUD', 'RUN' + caseId), caseId, evidenceId, runId, timestamp: now, action: 'Analysis run completed', detail: `Source: ${resp.source} (${resp.consensus.tier_used}) · Confidence: ${Math.round(resp.consensus.confidence_score * 100)}%`, actor: 'system' },
    ];

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
  }, []);

  const restoreCase = useCallback((saved: SavedCase) => {
    const activeCase: Case = {
      id: saved.caseId, workspaceId: DEFAULT_WORKSPACE.id, title: saved.filename,
      domain: 'image', createdAt: saved.timestamp, updatedAt: saved.timestamp, status: 'open',
    };
    const activeEvidence: Evidence = {
      id: saved.evidenceId, caseId: saved.caseId, sha256: saved.sha256, filename: saved.filename,
      mimeType: 'image/jpeg', domain: 'image', ingestedAt: saved.timestamp,
    };
    const activeRun: AnalysisRun = {
      id: saved.runId, evidenceId: saved.evidenceId, caseId: saved.caseId, source: saved.source,
      tier: saved.tier, confidence: saved.confidence, startedAt: saved.timestamp,
      completedAt: saved.timestamp, analysisLog: [],
    };
    setBase(b => ({
      ...b, activeCase, activeEvidence, activeRun, findings: [], auditTrail: [], reports: [],
    }));
    setResult(null); // restored cases show entity metadata; tool views needing
                    // the full AnalyzeResponse will prompt to re-ingest.
    setDomain('image');
  }, []);

  const clear = useCallback(() => {
    setBase(emptyContext());
    setResult(null);
  }, []);

  const value = useMemo<InvestigationContextValue>(() => ({
    ...base, domain, result,
    setDomain, loadFromAnalysis, restoreCase, clear, history,
  }), [base, domain, result, loadFromAnalysis, restoreCase, clear, history]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useInvestigation(): InvestigationContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useInvestigation must be used within InvestigationProvider');
  return v;
}

export type { SavedCase };
