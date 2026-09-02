/**
 * DashboardView — System Overview & Analytics default canvas (SURGE-style).
 *
 * Rendered in the main viewport when no target image is loaded.
 *   Card 1: Investigation Volume / Activity Trend (bar chart)
 *   Card 2: Risk & Metadata Breakdown (Critical / Medium / Low anomaly counts)
 *   Card 3: Recent Target Session History
 *
 * Session history is the UNIFIED case vault (`ark.caseHistory` via the shared
 * investigation context) — the exact same store surfaced by User Settings →
 * Saved Case Vault and by the CASES domain Case Explorer. Deleting, clearing
 * or restoring here reflects everywhere immediately. The legacy `arkgeo.sessions`
 * log is kept purely for backward-compat recordSession() callers and is purged
 * together with the vault on "Clear All Sessions".
 */
import React, { useMemo, useState } from 'react';
import { Trash2, History, FolderOpen } from 'lucide-react';
import { useInvestigation, type SavedCase } from './useInvestigation';

/** A single recorded analysis session (legacy log shape, kept for callers). */
export interface SessionRecord {
  request_id: string;
  filename: string;
  sha256_short: string;
  source: string;
  confidence: number;
  timestamp: number;
  anomaly_count: number;
  risk: 'critical' | 'medium' | 'low';
}

const STORAGE_KEY = 'arkgeo.sessions';

/** Read all recorded sessions from localStorage (newest first). */
export function loadSessions(): SessionRecord[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw) as SessionRecord[];
    return Array.isArray(arr) ? arr.sort((a, b) => b.timestamp - a.timestamp) : [];
  } catch {
    return [];
  }
}

/** Append a new session record (keeps the most recent 100). */
export function recordSession(rec: SessionRecord): void {
  try {
    const existing = loadSessions();
    const next = [rec, ...existing].slice(0, 100);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable — non-blocking */
  }
}

/** Classify anomaly count into a risk bucket. */
export function classifyRisk(anomalyCount: number): SessionRecord['risk'] {
  if (anomalyCount >= 3) return 'critical';
  if (anomalyCount >= 1) return 'medium';
  return 'low';
}

/** Remove a single session by request_id. */
export function deleteSession(request_id: string): void {
  try {
    const next = loadSessions().filter(s => s.request_id !== request_id);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch { /* storage unavailable — non-blocking */ }
}

/** Purge all saved target sessions. */
export function clearSessions(): void {
  try { localStorage.removeItem(STORAGE_KEY); } catch { /* non-blocking */ }
}

interface DashboardViewProps {
  onUpload: () => void;
  /** Fully restore a past target session into the active workspace. */
  onRestoreCase?: (saved: SavedCase) => void;
  /** External mutators can bump this to force a re-read (kept for compat). */
  refreshKey?: number;
}

export function DashboardView({ onUpload, onRestoreCase }: DashboardViewProps) {
  const inv = useInvestigation();
  const history = inv.history;
  const [confirmClear, setConfirmClear] = useState(false);
  const [confirmDel, setConfirmDel] = useState<string | null>(null);

  // Activity trend: count cases per day for the last 14 days (from the vault).
  const trend = useMemo(() => {
    const days: { label: string; count: number }[] = [];
    const now = new Date();
    for (let i = 13; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(now.getDate() - i);
      d.setHours(0, 0, 0, 0);
      const next = d.getTime() + 86400000;
      const count = history.filter(h => h.timestamp >= d.getTime() && h.timestamp < next).length;
      const label = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
      days.push({ label, count });
    }
    return days;
  }, [history]);

  const maxCount = Math.max(1, ...trend.map(d => d.count));

  // Risk breakdown (from the vault — same count as Settings & Case Explorer).
  const riskBreakdown = useMemo(() => {
    const critical = history.filter(h => h.risk === 'critical').length;
    const medium = history.filter(h => h.risk === 'medium').length;
    const low = history.filter(h => h.risk === 'low').length;
    return { critical, medium, low, total: history.length };
  }, [history]);

  const recent = history.slice(0, 8);

  const handleDelete = (caseId: string) => {
    const match = history.find(h => h.caseId === caseId);
    if (match) inv.removeCase(match);
    setConfirmDel(null);
  };

  const handleClear = () => {
    inv.clearHistory();
    clearSessions(); // purge the legacy log too so counts stay aligned
    setConfirmClear(false);
  };

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <div>
          <div className="dashboard-title">System Overview</div>
          <div className="dashboard-subtitle">
            Forensic intelligence dashboard · {history.length} session{history.length === 1 ? '' : 's'} recorded
          </div>
        </div>
      </div>

      <div className="dashboard-grid">
        {/* Card 1: Activity Trend */}
        <div className="dash-card dash-card-wide">
          <div className="dash-card-header">
            <span className="dash-card-title">Investigation Volume</span>
            <span className="dash-card-sub">14-day activity trend</span>
          </div>
          <div className="dash-chart">
            {trend.map((d, i) => (
              <div key={i} className="dash-chart-col" title={`${d.label}: ${d.count}`}>
                <div className="dash-chart-bar-wrap">
                  <div
                    className="dash-chart-bar"
                    style={{ height: `${(d.count / maxCount) * 100}%`, opacity: d.count ? 1 : 0.15 }}
                  />
                </div>
                <div className="dash-chart-label">{d.label}</div>
              </div>
            ))}
          </div>
          {history.length === 0 && (
            <div className="dash-empty">No investigations yet — upload an image to begin.</div>
          )}
        </div>

        {/* Card 2: Risk Breakdown */}
        <div className="dash-card">
          <div className="dash-card-header">
            <span className="dash-card-title">Risk & Metadata</span>
            <span className="dash-card-sub">Anomaly distribution</span>
          </div>
          <div className="dash-risk">
            <div className="dash-risk-row">
              <span className="dash-risk-dot dash-risk-critical" />
              <span className="dash-risk-label">Critical</span>
              <span className="dash-risk-count">{riskBreakdown.critical}</span>
            </div>
            <div className="dash-risk-row">
              <span className="dash-risk-dot dash-risk-medium" />
              <span className="dash-risk-label">Medium</span>
              <span className="dash-risk-count">{riskBreakdown.medium}</span>
            </div>
            <div className="dash-risk-row">
              <span className="dash-risk-dot dash-risk-low" />
              <span className="dash-risk-label">Low / Clean</span>
              <span className="dash-risk-count">{riskBreakdown.low}</span>
            </div>
          </div>
          <div className="dash-risk-bar">
            <div className="dash-risk-seg dash-risk-critical-bg" style={{ width: `${riskBreakdown.total ? (riskBreakdown.critical / riskBreakdown.total) * 100 : 0}%` }} />
            <div className="dash-risk-seg dash-risk-medium-bg" style={{ width: `${riskBreakdown.total ? (riskBreakdown.medium / riskBreakdown.total) * 100 : 0}%` }} />
            <div className="dash-risk-seg dash-risk-low-bg" style={{ width: `${riskBreakdown.total ? (riskBreakdown.low / riskBreakdown.total) * 100 : 0}%` }} />
          </div>
        </div>

        {/* Card 3: Recent Target Sessions — restore / per-row delete / clear all.
            Reads the SAME vault store as Settings → Saved Case Vault, so the
            counts always match (no more 1-case-vault vs 8-sessions mismatch). */}
        <div className="dash-card dash-card-wide">
          <div className="dash-card-header">
            <span className="dash-card-title"><History className="w-3.5 h-3.5" style={{ display: 'inline', verticalAlign: '-2px', marginRight: '6px' }} />Recent Target Sessions</span>
            <div className="dash-card-header-actions">
              <span className="dash-card-sub">{history.length} in vault</span>
              {history.length > 0 && (
                <button
                  className="dash-clear-btn"
                  onClick={() => setConfirmClear(true)}
                  title="Purge all saved sessions from the vault"
                >
                  <Trash2 className="w-3.5 h-3.5" /> Clear All Sessions
                </button>
              )}
            </div>
          </div>
          <div className="dash-sessions">
            {recent.length === 0 ? (
              <div className="dash-empty">No recent sessions.</div>
            ) : recent.map(s => (
              <div key={s.caseId} className="dash-session-row">
                <span className={`dash-session-risk dash-session-${s.risk}`} />
                <span className="dash-session-name" title={s.filename}>
                  {s.caseName ? `${s.caseName} — ` : ''}{s.filename}
                </span>
                <span className={`dash-session-domain mono`}>{(s.domain ?? 'image').toUpperCase()}</span>
                <span className="dash-session-src">{s.source}</span>
                <span className="dash-session-conf">{Math.round(s.confidence * 100)}%</span>
                <span className="dash-session-time mono">{new Date(s.timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>
                <span className="dash-session-actions">
                  {onRestoreCase && (
                    <button
                      className="dash-session-restore"
                      title="Restore full session state into the active workspace"
                      onClick={() => onRestoreCase(s)}
                    >
                      <FolderOpen className="w-3.5 h-3.5" /> Restore Session
                    </button>
                  )}
                  <button
                    className="dash-session-del"
                    title="Delete this session from the vault"
                    onClick={() => setConfirmDel(s.caseId)}
                  >
                    <Trash2 className="w-3.5 h-3.5" /> Delete
                  </button>
                </span>
              </div>
            ))}
          </div>
          {confirmClear && (
            <div className="dash-confirm-inline">
              <span>Purge all {history.length} saved sessions? This cannot be undone.</span>
              <button className="dash-confirm-yes" onClick={handleClear}>Purge All</button>
              <button className="dash-confirm-no" onClick={() => setConfirmClear(false)}>Cancel</button>
            </div>
          )}
          {confirmDel && (
            <div className="dash-confirm-inline">
              <span>Delete this session from the vault?</span>
              <button className="dash-confirm-yes" onClick={() => handleDelete(confirmDel)}>Delete</button>
              <button className="dash-confirm-no" onClick={() => setConfirmDel(null)}>Cancel</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
