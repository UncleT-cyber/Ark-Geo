/**
 * AuditLogs — non-repudiation chain-of-custody search by user, IP and
 * timestamp. Append-only; entries carry actor, action, target, IP and
 * timestamp.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Search } from 'lucide-react';
import { api } from '../../api';
import type { AdminAuditEntry } from '../../types';

export function AuditLogs() {
  const [logs, setLogs] = useState<AdminAuditEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [actor, setActor] = useState('');
  const [action, setAction] = useState('');

  const load = useCallback(async (params?: { query?: string; actor?: string; action?: string }) => {
    setLoading(true);
    try {
      setLogs(await api.listAuditLogs(params));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load audit logs');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const applySearch = () => {
    load({ query: query || undefined, actor: actor || undefined, action: action || undefined });
  };

  const fmtTime = (ts: string) => ts.replace('T', ' ').slice(0, 19) + 'Z';

  return (
    <div>
      <div className="ark-section-head">
        <h2 className="ark-section-title">NON-REPUDIATION TRAIL</h2>
        <button className="ark-btn ark-btn-sm" onClick={() => load()}><RefreshCw className="w-3 h-3" /> Refresh</button>
      </div>

      <div className="ark-card">
        <div className="ark-inline">
          <div className="ark-field" style={{ flex: 2 }}><span className="ark-field-label">Search (any field)</span>
            <input className="ark-input" placeholder="user, IP, target, detail…" value={query}
              onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && applySearch()} /></div>
          <div className="ark-field"><span className="ark-field-label">Actor</span>
            <input className="ark-input" placeholder="e.g. admin" value={actor} onChange={e => setActor(e.target.value)} /></div>
          <div className="ark-field"><span className="ark-field-label">Action</span>
            <input className="ark-input" placeholder="e.g. client.suspend" value={action} onChange={e => setAction(e.target.value)} /></div>
          <button className="ark-btn ark-btn-primary" style={{ marginTop: 18 }} onClick={applySearch}>
            <Search className="w-3 h-3" /> Search
          </button>
        </div>
      </div>

      {error && <div className="ark-card ark-mt" style={{ color: '#FCA5A5' }}>{error}</div>}
      {loading ? (
        <div className="ark-admin-loading" style={{ minHeight: 220 }}><div className="ark-spinner" /><div>Loading audit trail…</div></div>
      ) : logs.length === 0 ? (
        <div className="ark-card ark-empty">No audit entries match.</div>
      ) : (
        <div className="ark-table-wrap ark-mt">
          <table className="ark-table">
            <thead>
              <tr><th>Log ID</th><th>Timestamp</th><th>Actor</th><th>Action</th><th>Target</th><th>IP</th><th>Detail</th></tr>
            </thead>
            <tbody>
              {logs.slice(0, 120).map(l => (
                <tr key={l.log_id}>
                  <td className="ark-mono" style={{ color: '#6B7280' }}>{l.log_id}</td>
                  <td className="ark-mono">{fmtTime(l.timestamp)}</td>
                  <td className="ark-cell-strong ark-mono">{l.actor}</td>
                  <td><span className="ark-badge ark-badge-blue ark-mono">{l.action}</span></td>
                  <td className="ark-mono">{l.target || '—'}</td>
                  <td className="ark-mono">{l.ip}</td>
                  <td style={{ maxWidth: 320 }}>{l.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
