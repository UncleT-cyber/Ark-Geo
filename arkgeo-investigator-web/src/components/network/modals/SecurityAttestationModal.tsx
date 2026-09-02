/**
 * SecurityAttestationModal — authorized-engagement gatekeeper.
 *
 * The security-testing workspace is locked until an analyst records a signed
 * attestation: identity, position, engagement purpose and the target scope /
 * ROE reference.  On submit the modal reconciles the server-observed IP against
 * the WebRTC STUN/ICE-derived IP, persists the record through adminAuditStore
 * (local chain-of-custody + backend audit store when reachable) and unlocks the
 * session.  The unlock lives in sessionStorage only — it never survives a tab.
 */
import React, { useEffect, useState } from 'react';
import { ShieldCheck, X, Loader2, Fingerprint, Globe, AlertTriangle, Lock } from 'lucide-react';
import {
  adminAuditStore,
  resolveIpTelemetry,
  type AttestationRecord,
  type IpTelemetry,
} from '../../../core/utils/telemetry';

interface SecurityAttestationModalProps {
  open: boolean;
  onClose: () => void;
  onAttested: (record: AttestationRecord) => void;
}

interface FormState {
  fullName: string;
  email: string;
  position: string;
  orgName: string;
  purpose: string;
  targetScope: string;
  agreed: boolean;
}

const EMPTY: FormState = { fullName: '', email: '', position: '', orgName: '', purpose: '', targetScope: '', agreed: false };

export function SecurityAttestationModal({ open, onClose, onAttested }: SecurityAttestationModalProps) {
  const [form, setForm] = useState<FormState>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ip, setIp] = useState<IpTelemetry | null>(null);

  useEffect(() => {
    if (open) {
      const last = adminAuditStore.getLastIdentity();
      setForm(last ? {
        fullName: last.user,
        email: last.email,
        position: last.position,
        orgName: last.orgName,
        purpose: '',
        targetScope: '',
        agreed: false,
      } : EMPTY);
      setError(null);
      setBusy(false);
      setIp(null);
      resolveIpTelemetry().then(setIp).catch(() => setIp(null));
    }
  }, [open]);

  if (!open) return null;

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setForm(f => ({ ...f, [k]: v }));

  const submit = async () => {
    setError(null);
    if (!form.fullName.trim()) return setError('Full Name is required.');
    if (!form.position.trim()) return setError('Position / Role is required.');
    if (!form.orgName.trim()) return setError('Organization Name is required.');
    if (!form.purpose.trim()) return setError('Engagement purpose is required.');
    if (!form.targetScope.trim()) return setError('Target scope / ROE reference is required.');
    if (!form.agreed) return setError('You must certify written authorization for the declared scope.');

    setBusy(true);
    try {
      const resolved = ip ?? await resolveIpTelemetry();
      const record = await adminAuditStore.logAttestation({
        user: form.fullName.trim(),
        email: form.email.trim(),
        position: form.position.trim(),
        orgName: form.orgName.trim(),
        purpose: form.purpose.trim(),
        targetScope: form.targetScope.trim(),
        clientIP: resolved.clientIp,
        realIP: resolved.realIp ?? '',
        timestamp: new Date().toISOString(),
        userAgent: navigator.userAgent,
      });
      onAttested(record);
      setForm(EMPTY);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Attestation could not be recorded.');
    } finally {
      setBusy(false);
    }
  };

  const ipLine = ip?.clientIp ? (
    <div className="sectest-iprow">
      <Globe className="w-3 h-3" />
      <span>SERVER-OBSERVED <b className="mono">{ip.clientIp}</b></span>
      <span className="sectest-ipsep">|</span>
      <Fingerprint className="w-3 h-3" />
      <span>WEBRTC STUN/ICE <b className="mono">{ip.realIp || 'unavailable'}</b></span>
      {ip.drift && <span className="sectest-drift">VPN/PROXY DRIFT DETECTED</span>}
    </div>
  ) : null;

  return (
    <div className="sectest-overlay" onClick={() => !busy && onClose()}>
      <div className="sectest-modal" onClick={e => e.stopPropagation()}>
        <div className="sectest-modal-head">
          <div className="sectest-head-title">
            <ShieldCheck className="w-4 h-4" />
            AUTHORIZED SECURITY TESTING — ENGAGEMENT ATTESTATION
          </div>
          <button className="sectest-close" onClick={onClose} disabled={busy}>
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="sectest-modal-body">
          <p className="sectest-intro">
            Active security-testing engines are unlocked only after a signed declaration.
            This attestation is appended to the non-repudiation audit trail with a
            server-observed IP and cannot be silently edited.
          </p>

          <div className="sectest-grid">
            <label className="sectest-field">
              <span className="sectest-label">FULL NAME</span>
              <input className="sectest-input" value={form.fullName}
                placeholder="Analyst legal name" autoComplete="off"
                onChange={e => set('fullName', e.target.value)} />
            </label>
            <label className="sectest-field">
              <span className="sectest-label">EMAIL</span>
              <input className="sectest-input" value={form.email} autoComplete="off"
                placeholder="analyst@org.example"
                onChange={e => set('email', e.target.value)} />
            </label>
            <label className="sectest-field">
              <span className="sectest-label">POSITION / ROLE</span>
              <input className="sectest-input" value={form.position} autoComplete="off"
                placeholder="e.g. Offensive Security Lead"
                onChange={e => set('position', e.target.value)} />
            </label>
            <label className="sectest-field">
              <span className="sectest-label">ORGANIZATION NAME</span>
              <input className="sectest-input" value={form.orgName} autoComplete="off"
                placeholder="e.g. ARK Red Team"
                onChange={e => set('orgName', e.target.value)} />
            </label>
          </div>

          <label className="sectest-field">
            <span className="sectest-label">ENGAGEMENT PURPOSE</span>
            <textarea className="sectest-textarea" value={form.purpose} rows={3}
              placeholder="Describe the authorized objective — e.g. annual web-application assessment, phishing resilience drill, infrastructure posture review."
              onChange={e => set('purpose', e.target.value)} />
          </label>

          <label className="sectest-field">
            <span className="sectest-label">TARGET SCOPE / ROE REFERENCE</span>
            <textarea className="sectest-textarea" value={form.targetScope} rows={2}
              placeholder="Exact scope boundary + ROE doc reference — e.g. 10.0.0.0/24, app.example.com, ROE-2026-014."
              onChange={e => set('targetScope', e.target.value)} />
          </label>

          {ipLine}

          <label className="sectest-check">
            <input type="checkbox" checked={form.agreed}
              onChange={e => set('agreed', e.target.checked)} />
            <span>
              I certify I hold written authorization / signed Rules of Engagement for the
              declared target scope, and that any active testing is conducted solely within
              that boundary.
            </span>
          </label>

          {error && (
            <div className="sectest-error">
              <AlertTriangle className="w-3 h-3" /> {error}
            </div>
          )}
        </div>

        <div className="sectest-modal-foot">
          <span className="sectest-foot-note"><Lock className="w-3 h-3" /> Unlock lives in this session only</span>
          <div className="sectest-foot-btns">
            <button className="sectest-btn sectest-btn-ghost" onClick={onClose} disabled={busy}>CANCEL</button>
            <button className="sectest-btn sectest-btn-primary" onClick={submit} disabled={busy}>
              {busy ? <Loader2 className="w-4 h-4 sectest-spin" /> : <ShieldCheck className="w-4 h-4" />}
              ENTER WORKSPACE
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
