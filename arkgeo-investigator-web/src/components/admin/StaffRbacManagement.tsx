/**
 * StaffRbacManagement — Super-Admin CRUD for internal operators with the
 * granular RBAC permission matrix. Every mutation writes an append-only
 * audit entry server-side (actor + action + target + IP + timestamp).
 */
import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Plus, Power, ShieldCheck } from 'lucide-react';
import { api } from '../../api';
import type { AdminStaff, StaffRole } from '../../types';

const ROLE_BADGE: Record<StaffRole, string> = {
  SUPER_ADMIN: 'ark-badge ark-badge-green',
  LEAD_ANALYST: 'ark-badge ark-badge-blue',
  SECURITY_OPERATOR: 'ark-badge ark-badge-amber',
  AUDITOR: 'ark-badge ark-badge-gray',
};

const PERM_LABEL: Record<string, string> = {
  canManageApiKeys: 'Manage API Keys',
  canManageBilling: 'Manage Billing',
  canManageClients: 'Manage Clients',
  canExecuteHighRiskTools: 'Execute High-Risk Tools',
  canManageStaff: 'Manage Staff',
};

export function StaffRbacManagement() {
  const [staff, setStaff] = useState<AdminStaff[]>([]);
  const [roles, setRoles] = useState<string[]>([]);
  const [permissionKeys, setPermissionKeys] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState({
    username: '', full_name: '', role: 'SECURITY_OPERATOR' as StaffRole,
    permissions: {} as Record<string, boolean>,
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listAdminStaff();
      setStaff(data.staff);
      setRoles(data.roles);
      setPermissionKeys(data.permission_keys);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load staff');
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

  const togglePermission = (member: AdminStaff, key: string) =>
    act(`perm:${member.staff_id}:${key}`, () =>
      api.updateAdminStaff(member.staff_id, { permissions: { ...member.permissions, [key]: !member.permissions[key as keyof typeof member.permissions] } }));

  const setRole = (member: AdminStaff, role: StaffRole) =>
    act(`role:${member.staff_id}`, () => api.updateAdminStaff(member.staff_id, { role }));

  const create = async () => {
    if (!createForm.username) return;
    await act('create', () => api.createAdminStaff(createForm));
    setCreateForm({ username: '', full_name: '', role: 'SECURITY_OPERATOR', permissions: {} });
    setShowCreate(false);
  };

  return (
    <div>
      <div className="ark-section-head">
        <h2 className="ark-section-title">INTERNAL OPERATORS</h2>
        <div className="ark-inline">
          <button className="ark-btn ark-btn-sm" onClick={load}><RefreshCw className="w-3 h-3" /> Refresh</button>
          <button className="ark-btn ark-btn-primary ark-btn-sm" onClick={() => setShowCreate(s => !s)}><Plus className="w-3 h-3" /> Create Staff</button>
        </div>
      </div>

      {showCreate && (
        <div className="ark-card ark-mt">
          <div className="ark-inline">
            <div className="ark-field" style={{ flex: 1 }}><span className="ark-field-label">Username</span>
              <input className="ark-input" value={createForm.username} onChange={e => setCreateForm(f => ({ ...f, username: e.target.value }))} /></div>
            <div className="ark-field" style={{ flex: 1 }}><span className="ark-field-label">Full Name</span>
              <input className="ark-input" value={createForm.full_name} onChange={e => setCreateForm(f => ({ ...f, full_name: e.target.value }))} /></div>
            <div className="ark-field"><span className="ark-field-label">Role</span>
              <select className="ark-select" value={createForm.role} onChange={e => setCreateForm(f => ({ ...f, role: e.target.value as StaffRole }))}>
                {roles.map(r => <option key={r} value={r}>{r}</option>)}
              </select></div>
            <button className="ark-btn ark-btn-primary" style={{ marginTop: 18 }} onClick={create} disabled={busy === 'create'}>Create</button>
          </div>
        </div>
      )}

      {error && <div className="ark-card ark-mt" style={{ color: '#FCA5A5' }}>{error}</div>}
      {loading ? (
        <div className="ark-admin-loading" style={{ minHeight: 220 }}><div className="ark-spinner" /><div>Loading staff…</div></div>
      ) : (
        <div className="ark-table-wrap">
          <table className="ark-table">
            <thead>
              <tr><th>Operator</th><th>Role</th><th>Status</th><th>Permission Matrix</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {staff.map(m => (
                <tr key={m.staff_id}>
                  <td>
                    <div className="ark-cell-strong">{m.full_name}</div>
                    <div className="ark-mono" style={{ color: '#6B7280' }}>@{m.username} · {m.staff_id} {m.seed && <span className="ark-flag ark-flag-seed">SEED</span>}</div>
                  </td>
                  <td>
                    <select className="ark-select" style={{ padding: '3px 6px', fontSize: 11 }}
                      value={m.role} onChange={e => setRole(m, e.target.value as StaffRole)}>
                      {roles.map(r => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                  <td>
                    {m.active ? <span className="ark-badge ark-badge-green"><span className="ark-badge-dot" /> ACTIVE</span>
                      : <span className="ark-badge ark-badge-gray">DEACTIVATED</span>}
                  </td>
                  <td>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, maxWidth: 460 }}>
                      {permissionKeys.map(k => (
                        <label key={k} className="ark-rbac-perm" title={PERM_LABEL[k] ?? k}>
                          <input className="ark-check" type="checkbox" disabled={busy !== null}
                            checked={Boolean(m.permissions[k as keyof typeof m.permissions])}
                            onChange={() => togglePermission(m, k)} />
                          {PERM_LABEL[k] ?? k}
                        </label>
                      ))}
                    </div>
                  </td>
                  <td>
                    {m.active ? (
                      <button className="ark-btn ark-btn-sm ark-btn-danger" disabled={busy !== null}
                        onClick={() => act('deactivate', () => api.deactivateAdminStaff(m.staff_id))}>
                        <Power className="w-3 h-3" /> Deactivate
                      </button>
                    ) : (
                      <button className="ark-btn ark-btn-sm" disabled={busy !== null}
                        onClick={() => act('reactivate', () => api.updateAdminStaff(m.staff_id, { active: true }))}>
                        <ShieldCheck className="w-3 h-3" /> Reactivate
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="ark-card ark-mt-lg">
        <h2 className="ark-section-title">RBAC POLICY NOTES</h2>
        <p style={{ fontSize: 12, color: '#9CA3AF', lineHeight: 1.6, margin: 0 }}>
          Roles are ordered from highest to lowest privilege: <strong>SUPER_ADMIN</strong> &gt;
          <strong>LEAD_ANALYST</strong> &gt; <strong>SECURITY_OPERATOR</strong> &gt; <strong>AUDITOR</strong>.
          Every role / permission change is recorded in the immutable audit trail with actor,
          timestamp and IP. The root platform account (STF-0001) cannot be deactivated.
          Administrative actions require <span className="ark-mono" style={{ color: '#6EE7B7' }}>canManageStaff</span> to mutate staff records.
        </p>
      </div>
    </div>
  );
}
