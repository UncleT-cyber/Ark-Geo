/**
 * InvestigatorProfileModal — the logged-in user's profile/session area.
 *
 * Opened from the TopBar profile icon and the ActivityBar footer profile icon.
 * Shows the investigator's identity, organization, role, clearance, the active
 * case + workspace status, saved investigation history (click to reload a past
 * case), and API key usage / permissions.
 *
 * This modal NEVER links to Admin. Admin is reachable only via the stealth
 * hotkey Cmd/Ctrl+Shift+P plus server-side authorization at /console-auth.
 */
import React from 'react';
import { X, Shield, Key, History, Building2, User, Activity, ChevronRight } from 'lucide-react';
import { useInvestigation, type SavedCase } from './useInvestigation';
import type { ApiKeyStatus } from './TopBar';

interface InvestigatorProfileModalProps {
  open: boolean;
  onClose: () => void;
  apiStatuses: ApiKeyStatus[];
  onRestoreCase: (saved: SavedCase) => void;
}

const RISK_COLOR: Record<SavedCase['risk'], string> = {
  critical: '#EF4444',
  medium: '#F59E0B',
  low: '#22C55E',
};

export function InvestigatorProfileModal({ open, onClose, apiStatuses, onRestoreCase }: InvestigatorProfileModalProps) {
  const inv = useInvestigation();
  if (!open) return null;

  const activeCase = inv.activeCase;
  const configuredCount = apiStatuses.filter(s => s.configured).length;

  return (
    <div className="profile-modal-overlay" onClick={onClose}>
      <div className="profile-modal" onClick={e => e.stopPropagation()}>
        <div className="profile-modal-header">
          <div className="profile-modal-title">INVESTIGATOR PROFILE</div>
          <button className="profile-modal-close" onClick={onClose}><X className="w-4 h-4" /></button>
        </div>

        <div className="profile-modal-body">
          {/* Identity */}
          <section className="profile-section">
            <div className="profile-section-title"><User className="w-3.5 h-3.5" /> IDENTITY</div>
            <div className="profile-grid">
              <div className="profile-field"><span className="profile-field-label">Name</span><span className="profile-field-value">Local Investigator</span></div>
              <div className="profile-field"><span className="profile-field-label">Role</span><span className="profile-field-value">Forensic Analyst</span></div>
              <div className="profile-field"><span className="profile-field-label">Organization</span><span className="profile-field-value">{inv.tenant.name}</span></div>
              <div className="profile-field"><span className="profile-field-label">Workspace</span><span className="profile-field-value">{inv.workspace.name}</span></div>
              <div className="profile-field"><span className="profile-field-label">Clearance</span><span className="profile-field-value profile-clearance">L3 — Analyst</span></div>
              <div className="profile-field"><span className="profile-field-label">Session</span><span className="profile-field-value mono">{new Date().toISOString().slice(0, 16)}Z</span></div>
            </div>
          </section>

          {/* Active case + workspace status */}
          <section className="profile-section">
            <div className="profile-section-title"><Activity className="w-3.5 h-3.5" /> ACTIVE SESSION</div>
            {activeCase ? (
              <div className="profile-active-case">
                <div className="profile-active-case-id mono">{activeCase.id}</div>
                <div className="profile-active-case-row">
                  <span className="profile-field-label">Title</span><span className="profile-field-value">{activeCase.title}</span>
                </div>
                <div className="profile-active-case-row">
                  <span className="profile-field-label">Domain</span><span className="profile-field-value">{activeCase.domain.toUpperCase()}</span>
                </div>
                {inv.activeEvidence && (
                  <div className="profile-active-case-row">
                    <span className="profile-field-label">Evidence</span><span className="profile-field-value mono">{inv.activeEvidence.id}</span>
                  </div>
                )}
                {inv.activeRun && (
                  <div className="profile-active-case-row">
                    <span className="profile-field-label">Run</span><span className="profile-field-value mono">{inv.activeRun.id}</span>
                  </div>
                )}
                <div className="profile-active-case-row">
                  <span className="profile-field-label">Status</span>
                  <span className="profile-field-value profile-status-open">Open</span>
                </div>
              </div>
            ) : (
              <div className="profile-empty-session">No active case. Open an investigation from the IMAGE domain.</div>
            )}
          </section>

          {/* Saved investigation history */}
          <section className="profile-section">
            <div className="profile-section-title"><History className="w-3.5 h-3.5" /> SAVED INVESTIGATIONS</div>
            {inv.history.length === 0 ? (
              <div className="profile-empty-session">No saved investigations yet.</div>
            ) : (
              <div className="profile-history-list">
                {inv.history.slice(0, 8).map(h => (
                  <button
                    key={h.caseId}
                    className="profile-history-item"
                    onClick={() => { onRestoreCase(h); onClose(); }}
                  >
                    <div className="profile-history-main">
                      <span className="profile-history-id mono">{h.caseId}</span>
                      <span className="profile-history-filename">{h.filename}</span>
                    </div>
                    <div className="profile-history-meta">
                      <span className="profile-history-source">{h.source}</span>
                      <span className="profile-history-conf">{Math.round(h.confidence * 100)}%</span>
                      <span className="profile-history-risk" style={{ color: RISK_COLOR[h.risk] }}>{h.risk}</span>
                      <ChevronRight className="w-3.5 h-3.5" />
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>

          {/* API key usage & permissions */}
          <section className="profile-section">
            <div className="profile-section-title"><Key className="w-3.5 h-3.5" /> API KEY USAGE & PERMISSIONS</div>
            <div className="profile-grid">
              <div className="profile-field"><span className="profile-field-label">Providers configured</span><span className="profile-field-value">{configuredCount}/{apiStatuses.length}</span></div>
              <div className="profile-field"><span className="profile-field-label">Permissions</span><span className="profile-field-value">Evidence ingest, analysis, report</span></div>
            </div>
            <div className="profile-api-list">
              {apiStatuses.map(s => (
                <div key={s.label} className="profile-api-row">
                  <span className="profile-api-label">{s.title}</span>
                  <span className={`profile-api-state ${s.configured ? 'profile-api-on' : 'profile-api-off'}`}>
                    {s.configured ? 'Configured' : 'Not Set'}
                  </span>
                </div>
              ))}
            </div>
          </section>
        </div>

        <div className="profile-modal-footer">
          <span className="profile-modal-hint">
            <Shield className="w-3 h-3" /> Admin is a protected control plane — not accessible from here.
          </span>
        </div>
      </div>
    </div>
  );
}
