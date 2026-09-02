/**
 * ToolPolicy — risk rules & tool governors. Toggle passive vs active
 * OSINT tools; HIGH/CRITICAL risk tools require explicit enablement and
 * are tracked in the audit trail.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, ShieldAlert } from 'lucide-react';
import { api } from '../../api';
import type { AdminToolPolicy } from '../../types';

const RISK_BADGE: Record<string, string> = {
  LOW: 'ark-badge ark-badge-green',
  MEDIUM: 'ark-badge ark-badge-blue',
  HIGH: 'ark-badge ark-badge-amber',
  CRITICAL: 'ark-badge ark-badge-red',
};

const TOOL_DESCRIPTIONS: Record<string, string> = {
  reverse_image_search: 'Reverse source discovery (TinEye / Serper) on candidate evidence.',
  exiftool_extraction: 'Deep EXIF / XMP / IPTC metadata extraction (Tier 1 deterministic).',
  ocr_text_telemetry: 'Optical character recognition + text telemetry extraction.',
  streetview_lookup: 'Google Street View panorama retrieval for established coordinates.',
  geocoding_reverse: 'Reverse geocoding to resolve lat/lon to a readable address.',
  phone_number_lookup: 'Public telephone number metadata lookups.',
  carrier_hlr_lookup: 'HLR telecom lookup (carrier, roaming, ported status).',
  cell_tower_scan: 'Active cell-tower probing for device localization.',
  passive_network_scan: 'Passive network telemetry capture during investigations.',
  active_sweep_execution: 'Automated active sweeps across OSINT providers (high volume).',
};

export function ToolPolicy() {
  const [policy, setPolicy] = useState<AdminToolPolicy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setPolicy(await api.getToolPolicy());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load policy');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggle = async (tool: string, enabled: boolean) => {
    setBusy(tool);
    try {
      setPolicy(await api.toggleTool(tool, enabled));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to toggle tool');
    } finally {
      setBusy(null);
    }
  };

  const enabledHighRisk = policy ? Object.entries(policy).filter(([, p]) => p.enabled && (p.risk_level === 'HIGH' || p.risk_level === 'CRITICAL')).length : 0;

  return (
    <div>
      <div className="ark-section-head">
        <h2 className="ark-section-title">TOOL GOVERNORS</h2>
        <button className="ark-btn ark-btn-sm" onClick={load}><RefreshCw className="w-3 h-3" /> Refresh</button>
      </div>

      {error && <div className="ark-card ark-mt" style={{ color: '#FCA5A5' }}>{error}</div>}
      {loading ? (
        <div className="ark-admin-loading" style={{ minHeight: 220 }}><div className="ark-spinner" /><div>Loading policy…</div></div>
      ) : policy && (
        <>
          <div className="ark-card">
            <div className="ark-cs-card-title"><ShieldAlert className="w-3.5 h-3.5" /> RISK RULES</div>
            <p style={{ fontSize: 12, color: '#9CA3AF', lineHeight: 1.6, margin: 0 }}>
              HIGH and CRITICAL risk tools are disabled by default and gated behind the
              <span className="ark-mono" style={{ color: '#6EE7B7' }}> canExecuteHighRiskTools</span>
              RBAC permission. <span style={{ color: enabledHighRisk > 0 ? '#FCD34D' : '#9CA3AF' }}>{enabledHighRisk} high-risk tool(s) currently enabled.</span>
            </p>
          </div>

          <div className="ark-table-wrap ark-mt">
            <table className="ark-table">
              <thead>
                <tr><th>Tool</th><th>Description</th><th>Risk</th><th>State</th><th>Governor</th></tr>
              </thead>
              <tbody>
                {Object.entries(policy).map(([tool, p]) => (
                  <tr key={tool}>
                    <td className="ark-cell-strong ark-mono">{tool}</td>
                    <td style={{ maxWidth: 380 }}>{TOOL_DESCRIPTIONS[tool] ?? '—'}</td>
                    <td><span className={RISK_BADGE[p.risk_level]}>{p.risk_level}</span></td>
                    <td>
                      {p.enabled
                        ? <span className="ark-badge ark-badge-green"><span className="ark-badge-dot" /> ACTIVE</span>
                        : <span className="ark-badge ark-badge-gray">DISABLED</span>}
                    </td>
                    <td>
                      <label className="ark-toggle">
                        <input type="checkbox" disabled={busy === tool}
                          checked={p.enabled} onChange={e => toggle(tool, e.target.checked)} />
                        <span className="ark-toggle-slider" />
                      </label>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
