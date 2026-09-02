/**
 * ClientManagement — enterprise client control deck with forensic
 * telemetry (network identity, device fingerprint, usage metrics) and
 * administrative actions (suspend/ban/terminate/plan override).
 */
import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Ban, UserX, Power, Trash2, Plus, MonitorSmartphone } from 'lucide-react';
import { api } from '../../api';
import type { AdminClient, ClientStatus, PlanTier } from '../../types';

const PLAN_LABEL: Record<PlanTier, string> = { free: 'Free', pro: 'Pro', enterprise: 'Enterprise' };
const STATUS_BADGE: Record<ClientStatus, string> = {
  active: 'ark-badge ark-badge-green',
  suspended: 'ark-badge ark-badge-amber',
  banned: 'ark-badge ark-badge-red',
};

function fmtBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${(bytes / 1024 ** 2).toFixed(0)} MB`;
}

export function ClientManagement() {
  const [clients, setClients] = useState<AdminClient[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState({
    full_name: '', email: '', plan: 'free' as PlanTier, status: 'active' as ClientStatus,
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setClients(await api.listAdminClients());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load clients');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const act = useCallback(async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    try { await fn(); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : `Failed: ${label}`); }
    finally { setBusy(null); }
  }, [load]);

  const changeStatus = (client: AdminClient, status: ClientStatus) =>
    act(`status:${status}`, () => api.setClientStatus(client.client_id, status));

  const changePlan = (client: AdminClient, plan: PlanTier) =>
    act(`plan:${plan}`, () => api.updateAdminClient(client.client_id, { plan }));

  const create = async () => {
    if (!createForm.full_name || !createForm.email) return;
    await act('create', () => api.createAdminClient(createForm));
    setCreateForm({ full_name: '', email: '', plan: 'free', status: 'active' });
    setShowCreate(false);
  };

  return (
    <div>
      <div className="ark-section-head">
        <h2 className="ark-section-title">CLIENT DIRECTORY</h2>
        <div className="ark-inline">
          <button className="ark-btn ark-btn-sm" onClick={load}><RefreshCw className="w-3 h-3" /> Refresh</button>
          <button className="ark-btn ark-btn-primary ark-btn-sm" onClick={() => setShowCreate(s => !s)}>
            <Plus className="w-3 h-3" /> Add Client
          </button>
        </div>
      </div>

      {showCreate && (
        <div className="ark-card ark-mt">
          <div className="ark-row-gap">
            <div className="ark-inline">
              <div className="ark-field" style={{ flex: 2 }}><span className="ark-field-label">Full Name</span>
                <input className="ark-input" value={createForm.full_name} onChange={e => setCreateForm(f => ({ ...f, full_name: e.target.value }))} /></div>
              <div className="ark-field" style={{ flex: 2 }}><span className="ark-field-label">Email</span>
                <input className="ark-input" value={createForm.email} onChange={e => setCreateForm(f => ({ ...f, email: e.target.value }))} /></div>
              <div className="ark-field"><span className="ark-field-label">Plan</span>
                <select className="ark-select" value={createForm.plan} onChange={e => setCreateForm(f => ({ ...f, plan: e.target.value as PlanTier }))}>
                  <option value="free">Free</option><option value="pro">Pro</option><option value="enterprise">Enterprise</option>
                </select></div>
              <div className="ark-field"><span className="ark-field-label">Status</span>
                <select className="ark-select" value={createForm.status} onChange={e => setCreateForm(f => ({ ...f, status: e.target.value as ClientStatus }))}>
                  <option value="active">Active</option><option value="suspended">Suspended</option><option value="banned">Banned</option>
                </select></div>
              <button className="ark-btn ark-btn-primary" style={{ marginTop: 18 }} onClick={create} disabled={busy === 'create'}>Create</button>
            </div>
          </div>
        </div>
      )}

      {error && <div className="ark-card ark-mt" style={{ color: '#FCA5A5' }}>{error}</div>}
      {loading ? (
        <div className="ark-admin-loading" style={{ minHeight: 220 }}><div className="ark-spinner" /><div>Loading clients…</div></div>
      ) : clients.length === 0 ? (
        <div className="ark-card ark-empty">No clients registered yet.</div>
      ) : (
        <div className="ark-table-wrap">
          <table className="ark-table">
            <thead>
              <tr>
                <th>Client</th><th>Plan</th><th>Status</th><th>Created</th><th>Active Cases</th><th>Storage</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {clients.map(c => (
                <React.Fragment key={c.client_id}>
                  <tr onClick={() => setExpanded(expanded === c.client_id ? null : c.client_id)} style={{ cursor: 'pointer' }}>
                    <td>
                      <div className="ark-cell-strong">{c.full_name}</div>
                      <div className="ark-mono" style={{ color: '#6B7280' }}>{c.email}</div>
                      <div className="ark-mono" style={{ color: '#6B7280' }}>{c.client_id} {c.seed && <span className="ark-flag ark-flag-seed">SEED</span>}</div>
                    </td>
                    <td>
                      <select className="ark-select" style={{ padding: '3px 6px', fontSize: 11 }}
                        value={c.plan} onChange={e => changePlan(c, e.target.value as PlanTier)}>
                        <option value="free">Free</option><option value="pro">Pro</option><option value="enterprise">Enterprise</option>
                      </select>
                    </td>
                    <td><span className={STATUS_BADGE[c.status]}><span className="ark-badge-dot" />{c.status.toUpperCase()}</span></td>
                    <td className="ark-mono">{c.created_at.slice(0, 10)}</td>
                    <td>{c.usage.active_cases}</td>
                    <td className="ark-mono">{fmtBytes(c.usage.storage_bytes)}</td>
                    <td>
                      <div className="ark-inline">
                        {c.status !== 'active' ? (
                          <button className="ark-btn ark-btn-sm" disabled={busy !== null} onClick={e => { e.stopPropagation(); changeStatus(c, 'active'); }}><Power className="w-3 h-3" /> Activate</button>
                        ) : (
                          <button className="ark-btn ark-btn-sm" disabled={busy !== null} onClick={e => { e.stopPropagation(); changeStatus(c, 'suspended'); }}><UserX className="w-3 h-3" /> Suspend</button>
                        )}
                        {c.status !== 'banned' && (
                          <button className="ark-btn ark-btn-sm ark-btn-danger" disabled={busy !== null} onClick={e => { e.stopPropagation(); changeStatus(c, 'banned'); }}><Ban className="w-3 h-3" /> Ban</button>
                        )}
                      </div>
                    </td>
                  </tr>
                  {expanded === c.client_id && (
                    <tr>
                      <td colSpan={7} style={{ background: '#0d1217' }}>
                        <div className="ark-telemetry-grid">
                          <div className="ark-telemetry-item"><div className="ark-telemetry-k">Network Identity</div>
                            <div className="ark-telemetry-v">{c.telemetry.last_login_ip || '—'}</div>
                            <div className="ark-telemetry-v" style={{ fontSize: 10, color: '#6B7280' }}>
                              {c.telemetry.country || '—'}{c.telemetry.city ? `, ${c.telemetry.city}` : ''} · {c.telemetry.asn || 'ASN n/a'}
                            </div>
                            <div className="ark-inline ark-mt">
                              <span className="ark-badge ark-badge-gray">PROXY {c.telemetry.proxy ? 'YES' : 'NO'}</span>
                              <span className="ark-badge ark-badge-gray">VPN {c.telemetry.vpn ? 'YES' : 'NO'}</span>
                              <span className="ark-badge ark-badge-red">TOR {c.telemetry.tor_exit ? 'YES' : 'NO'}</span>
                            </div>
                          </div>
                          <div className="ark-telemetry-item"><div className="ark-telemetry-k">Device Fingerprint</div>
                            <div className="ark-telemetry-v" style={{ fontSize: 10 }}>{c.telemetry.user_agent || '—'}</div>
                            <div className="ark-telemetry-v" style={{ fontSize: 10, color: '#6B7280' }}>
                              {c.telemetry.os || 'OS —'} · {c.telemetry.browser || 'browser —'} · TLS {c.telemetry.tls_fingerprint || '—'}
                            </div>
                          </div>
                          <div className="ark-telemetry-item"><div className="ark-telemetry-k">Usage</div>
                            <div className="ark-telemetry-v">${c.usage.api_spend_usd.toFixed(2)} spend</div>
                            <div className="ark-telemetry-v" style={{ fontSize: 10, color: '#6B7280' }}>
                              {c.usage.tokens_consumed.toLocaleString()} tokens · {c.usage.active_cases} active cases
                            </div>
                          </div>
                          <div className="ark-telemetry-item"><div className="ark-telemetry-k">Admin Actions</div>
                            <div className="ark-inline ark-mt">
                              <button className="ark-btn ark-btn-sm" disabled={busy !== null}
                                onClick={() => act('terminate', () => api.terminateClientSessions(c.client_id))}>
                                <MonitorSmartphone className="w-3 h-3" /> Force Terminate Sessions
                              </button>
                              <button className="ark-btn ark-btn-sm ark-btn-danger" disabled={busy !== null}
                                onClick={() => act('delete', () => api.deleteAdminClient(c.client_id))}>
                                <Trash2 className="w-3 h-3" /> Delete
                              </button>
                            </div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
