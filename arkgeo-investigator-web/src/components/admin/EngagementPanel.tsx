/**
 * EngagementPanel — operator-declared execution scope.
 *
 * The operator declares which targets ARK may execute against. That
 * declaration is the source of truth for the target-authorization layer:
 * inside it ARK runs without asking; outside it, target-bearing tool calls are
 * refused before dispatch. Declaring an engagement installs it as the active
 * scope immediately; revoking it clears the scope at once.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, ShieldCheck, ShieldOff, Target } from 'lucide-react';
import { api } from '../../api';
import type { EngagementState, EngagementView } from '../../types';

function splitList(value: string): string[] {
  return value.split(/[\s,]+/).map(s => s.trim()).filter(Boolean);
}

function parsePorts(value: string): number[] {
  return splitList(value).map(p => Number(p)).filter(p => Number.isInteger(p) && p >= 1 && p <= 65535);
}

export function EngagementPanel() {
  const [state, setState] = useState<EngagementState | null>(null);
  const [targets, setTargets] = useState('');
  const [ports, setPorts] = useState('');
  const [allPorts, setAllPorts] = useState(true);
  const [label, setLabel] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setState(await api.getEngagement());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load engagement');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const declare = async () => {
    const parsedTargets = splitList(targets);
    if (parsedTargets.length === 0) {
      setError('Declare at least one target.');
      return;
    }
    if (!allPorts && parsePorts(ports).length === 0) {
      setError('Declare at least one port, or authorize all ports.');
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const engagement = await api.declareEngagement({
        targets: parsedTargets,
        all_ports: allPorts,
        ports: allPorts ? undefined : parsePorts(ports),
        label,
      });
      setNotice(`Engagement active — ARK may execute against ${engagement.targets.join(', ')}.`);
      setTargets('');
      setPorts('');
      setLabel('');
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to declare engagement');
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (engagement: EngagementView) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.revokeEngagement(engagement.engagement_id);
      setNotice('Engagement revoked — its targets are no longer authorized.');
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to revoke engagement');
    } finally {
      setBusy(false);
    }
  };

  const standDown = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.clearEngagement();
      setNotice('Scope stood down — target-bearing calls fail closed until an engagement is declared.');
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to clear the active scope');
    } finally {
      setBusy(false);
    }
  };

  const active = state?.active ?? null;
  const effective = state?.effective ?? null;
  const source = state?.effective_source ?? 'none';
  // A scope in force that the operator did not declare — an env fixture — is the
  // usual reason ARK refuses (or allows) a target the operator surface does not
  // show. Surface it explicitly instead of reading "no engagement active".
  const fixtureInForce = source === 'fixture';

  return (
    <div>
      <div className="ark-section-head">
        <h2 className="ark-section-title">EXECUTION SCOPE</h2>
        <button className="ark-btn ark-btn-sm" onClick={load} disabled={loading}>
          <RefreshCw className="w-3 h-3" /> Refresh
        </button>
      </div>

      <p className="ark-muted" style={{ marginBottom: 16 }}>
        Declare the targets ARK may operate against. The declaration is the source of
        truth for execution: inside it ARK runs without asking, outside it target-bearing
        calls are refused before dispatch.
      </p>

      {error && <div className="ark-alert ark-alert-error" style={{ marginBottom: 12 }}>{error}</div>}
      {notice && <div className="ark-alert ark-alert-info" style={{ marginBottom: 12 }}>{notice}</div>}

      <div className="ark-card" style={{ padding: 16, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          {effective ? <ShieldCheck className="w-4 h-4" /> : <ShieldOff className="w-4 h-4" />}
          <strong>{effective ? 'Scope in force' : 'No engagement active'}</strong>
          {effective && (
            <span className="ark-mono" style={{ fontSize: 11, opacity: 0.8 }}>
              ({source === 'operator' ? 'operator-declared' : source === 'fixture' ? 'environment fixture' : source})
            </span>
          )}
        </div>

        {fixtureInForce && (
          <div className="ark-alert ark-alert-info" style={{ marginBottom: 12 }}>
            ARK is enforcing an <span className="ark-mono">ARKGEO_ENGAGEMENT_SCOPE</span> fixture, not an
            operator declaration. Targets it authorizes are the ones listed below. Stand it down to
            enforce only what you declare here.
          </div>
        )}

        {effective ? (
          <div className="ark-muted" style={{ lineHeight: 1.7 }}>
            <div><Target className="w-3 h-3" style={{ display: 'inline', marginRight: 6 }} />
              Targets: <span className="ark-mono">{effective.targets.join(', ')}</span></div>
            <div>Ports: <span className="ark-mono">{effective.all_ports ? 'all ports' : effective.ports.join(', ') || 'none'}</span></div>
            <div>Expires: <span className="ark-mono">{effective.expiry}</span></div>
            {effective.label && <div>Label: <span className="ark-mono">{effective.label}</span></div>}
            <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
              {active && (
                <button className="ark-btn ark-btn-sm ark-btn-danger"
                  onClick={() => revoke(active)} disabled={busy}>
                  <ShieldOff className="w-3 h-3" /> Revoke
                </button>
              )}
              <button className="ark-btn ark-btn-sm ark-btn-danger"
                onClick={standDown} disabled={busy}>
                <ShieldOff className="w-3 h-3" /> Stand down
              </button>
            </div>
          </div>
        ) : (
          <div className="ark-muted">
            Target-bearing tool calls are refused until an engagement is declared.
          </div>
        )}
      </div>

      <div className="ark-card" style={{ padding: 16 }}>
        <strong style={{ display: 'block', marginBottom: 12 }}>Declare an engagement</strong>
        <label className="ark-label">Targets (addresses or CIDRs)</label>
        <input className="ark-input ark-mono" placeholder="10.0.0.5, 192.168.1.0/24, example.org"
          value={targets} onChange={e => setTargets(e.target.value)} />

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '12px 0' }}>
          <input type="checkbox" checked={allPorts} onChange={e => setAllPorts(e.target.checked)} />
          <span>Authorize all ports on these targets</span>
        </label>

        {!allPorts && (
          <>
            <label className="ark-label">Ports</label>
            <input className="ark-input ark-mono" placeholder="443, 80, 8080"
              value={ports} onChange={e => setPorts(e.target.value)} />
          </>
        )}

        <label className="ark-label" style={{ marginTop: 12 }}>Label (optional)</label>
        <input className="ark-input" placeholder="Client X external assessment"
          value={label} onChange={e => setLabel(e.target.value)} />

        <button className="ark-btn ark-btn-primary" style={{ marginTop: 16 }}
          onClick={declare} disabled={busy}>
          <ShieldCheck className="w-3 h-3" /> {busy ? 'Working…' : 'Declare & activate'}
        </button>
      </div>
    </div>
  );
}
