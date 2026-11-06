/**
 * SecOpsPlaceholder — the THREAT & SECOPS investigation domain.
 *
 * THE ARK is organized by investigation domains, not tools. The SECOPS domain
 * hosts the security-operations workflow. The six sub-modules below define the
 * continuous SecOps investigation lifecycle. The navigation architecture is
 * ready; the individual modules are surfaced as planned capabilities.
 *
 * Sub-modules:
 *   - SIEM                  — Security Information & Event Management
 *   - IDS / IPS             — Intrusion Detection / Prevention
 *   - Threat Hunting        — proactive adversary pursuit
 *   - Detection & Correlation — rule logic + cross-signal correlation
 *   - Incident Management   — case-bound incident lifecycle
 *   - Security Operations   — SecOps command dashboard
 */
import React from 'react';
import { SECOPS_ICONS } from './icons';

/** Ordered SecOps sub-modules — the in-domain workflow. */
const SECOPS_MODULES = [
  { id: 'siem', label: 'SIEM', icon: SECOPS_ICONS.siem,
    desc: 'Security Information & Event Management — aggregate log sources, normalize events, and run query-driven investigations across the estate.' },
  { id: 'ids_ips', label: 'IDS / IPS', icon: SECOPS_ICONS.ids_ips,
    desc: 'Intrusion Detection & Prevention — surface, triage, and action on signature and anomaly-based alerts from network and host sensors.' },
  { id: 'threat_hunting', label: 'Threat Hunting', icon: SECOPS_ICONS.threat_hunting,
    desc: 'Proactive adversary pursuit — hypothesis-driven hunts across telemetry to find threats that evaded automated detection.' },
  { id: 'detection', label: 'Detection & Correlation', icon: SECOPS_ICONS.detection,
    desc: 'Rule logic and cross-signal correlation — author, tune, and test detections; chain weak signals into high-confidence findings.' },
  { id: 'incident_mgmt', label: 'Incident Management', icon: SECOPS_ICONS.incident_mgmt,
    desc: 'Case-bound incident lifecycle — declare, scope, assign, and track incidents through to closure with full audit.' },
  { id: 'secops_dashboard', label: 'Security Operations', icon: SECOPS_ICONS.secops_dashboard,
    desc: 'SecOps command dashboard — live posture, MTTR/MTTD, open incidents, and analyst workload at a glance.' },
] as const;

export function SecOpsPlaceholder() {
  return (
    <section className="secops-roadmap" aria-label="Planned security operations modules">
      <div className="secops-roadmap-intro">
        <h2>Capability roadmap</h2>
        <p>Six modules planned across the security operations lifecycle.</p>
      </div>
      <div className="secops-roadmap-grid">
        {SECOPS_MODULES.map((m) => {
          const Icon = m.icon;
          return (
            <article key={m.id} className="secops-roadmap-card">
              <div><Icon size={18} aria-hidden="true" /><span>Planned</span></div>
              <h3>{m.label}</h3>
              <p>{m.desc}</p>
            </article>
          );
        })}
      </div>
    </section>
  );
}
