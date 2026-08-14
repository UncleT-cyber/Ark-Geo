/**
 * DashboardView — System Overview & Analytics default canvas (SURGE-style).
 *
 * Rendered in the main viewport when no target image is loaded.
 *   Card 1: Investigation Volume / Activity Trend (bar chart)
 *   Card 2: Risk & Metadata Breakdown (Critical / Medium / Low anomaly counts)
 *   Card 3: Recent Target Session History
 *
 * Session history is persisted in localStorage so analysts see their own
 * cumulative activity across reloads.
 */
import React, { useMemo, useState } from 'react';
import { Trash2, History } from 'lucide-react';

/** A single recorded analysis session (persisted to localStorage). */
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
  /** Reload a past target session into the active image workspace. */
  onSelectSession?: (s: SessionRecord) => void;
  /** External mutators can bump this to force a re-read of localStorage. */
  refreshKey?: number;
}

export function DashboardView({ onUpload, onSelectSession, refreshKey }: DashboardViewProps) {
  const [, force] = useState(0);
  const sessions = useMemo(() => loadSessions(), [refreshKey]);
  const [confirmClear, setConfirmClear] = useState(false);
  const [confirmDel, setConfirmDel] = useState<string | null>(null);

  // Activity trend: count sessions per day for the last 14 days
  const trend = useMemo(() => {
    const days: { label: string; count: number }[] = [];
    const now = new Date();
    for (let i = 13; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(now.getDate() - i);
      d.setHours(0, 0, 0, 0);
      const next = d.getTime() + 86400000;
      const count = sessions.filter(s => s.timestamp >= d.getTime() && s.timestamp < next).length;
      const label = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
      days.push({ label, count });
    }
    return days;
  }, [sessions]);

  const maxCount = Math.max(1, ...trend.map(d => d.count));

  // Risk breakdown
  const riskBreakdown = useMemo(() => {
    const critical = sessions.filter(s => s.risk === 'critical').length;
    const medium = sessions.filter(s => s.risk === 'medium').length;
    const low = sessions.filter(s => s.risk === 'low').length;
    return { critical, medium, low, total: sessions.length };
  }, [sessions]);

  const recent = sessions.slice(0, 8);

  const reload = () => force(n => n + 1);

  const handleDelete = (rid: string) => {
    deleteSession(rid);
    setConfirmDel(null);
    reload();
  };

  const handleClear = () => {
    clearSessions();
    setConfirmClear(false);
    reload();
  };

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <div>
          <div className="dashboard-title">System Overview</div>
          <div className="dashboard-subtitle">
            Forensic intelligence dashboard · {sessions.length} session{sessions.length === 1 ? '' : 's'} recorded
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
          {sessions.length === 0 && (
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

        {/* Card 3: Recent Sessions — fully selectable + per-row delete + clear */}
        <div className="dash-card dash-card-wide">
          <div className="dash-card-header">
            <span className="dash-card-title"><History className="w-3.5 h-3.5" style={{ display: 'inline', verticalAlign: '-2px', marginRight: '6px' }} />Recent Target Sessions</span>
            <div className="dash-card-header-actions">
              <span className="dash-card-sub">History</span>
              {sessions.length > 0 && (
                <button
                  className="dash-clear-btn"
                  onClick={() => setConfirmClear(true)}
                  title="Purge all saved sessions"
                >
                  <Trash2 className="w-3.5 h-3.5" /> Clear History
                </button>
              )}
            </div>
          </div>
          <div className="dash-sessions">
            {recent.length === 0 ? (
              <div className="dash-empty">No recent sessions.</div>
            ) : recent.map(s => (
              <div
                key={s.request_id}
                className={`dash-session-row ${onSelectSession ? 'dash-session-selectable' : ''}`}
                onClick={() => onSelectSession?.(s)}
                role={onSelectSession ? 'button' : undefined}
                title={onSelectSession ? `Reload ${s.filename}` : undefined}
              >
                <span className={`dash-session-risk dash-session-${s.risk}`} />
                <span className="dash-session-name" title={s.filename}>{s.filename}</span>
                <span className="dash-session-src">{s.source}</span>
                <span className="dash-session-conf">{Math.round(s.confidence * 100)}%</span>
                <span className="dash-session-time mono">{new Date(s.timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>
                <button
                  className="dash-session-del"
                  title="Delete session"
                  onClick={(e) => { e.stopPropagation(); setConfirmDel(s.request_id); }}
                >
                  <Trash2 className="w-4 h-4 text-red-400" />
                </button>
              </div>
            ))}
          </div>
          {confirmClear && (
            <div className="dash-confirm-inline">
              <span>Purge all {sessions.length} saved sessions? This cannot be undone.</span>
              <button className="dash-confirm-yes" onClick={handleClear}>Purge</button>
              <button className="dash-confirm-no" onClick={() => setConfirmClear(false)}>Cancel</button>
            </div>
          )}
          {confirmDel && (
            <div className="dash-confirm-inline">
              <span>Delete this session?</span>
              <button className="dash-confirm-yes" onClick={() => handleDelete(confirmDel)}>Delete</button>
              <button className="dash-confirm-no" onClick={() => setConfirmDel(null)}>Cancel</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
