/**
 * NetworkPlaceholder — the NETWORK investigation domain placeholder.
 *
 * THE ARK is organized by investigation domains. NETWORK is reserved for
 * future network-security tools (network discovery, traffic analysis, HTTP/Web
 * application analysis, endpoint discovery, network mapping, authorized
 * security-testing tools).
 *
 * The navigation architecture supports this domain cleanly; the tools
 * themselves are not implemented yet.
 */
import React from 'react';
import { Network, Radar, Globe, Activity, Waypoints, ShieldCheck } from 'lucide-react';

const FUTURE_TOOLS = [
  { icon: Radar, label: 'Network Discovery' },
  { icon: Activity, label: 'Traffic Analysis' },
  { icon: Globe, label: 'HTTP / Web Application Analysis' },
  { icon: Waypoints, label: 'Endpoint Discovery & Mapping' },
  { icon: ShieldCheck, label: 'Authorized Security Testing' },
];

export function NetworkPlaceholder() {
  return (
    <div className="domain-placeholder domain-placeholder-network">
      <div className="domain-placeholder-icon"><Network className="w-16 h-16" /></div>
      <div className="domain-placeholder-title">NETWORK INVESTIGATION</div>
      <div className="domain-placeholder-subtitle">
        The network-security investigation domain is reserved for future tooling.
      </div>
      <div className="domain-placeholder-body">
        THE ARK organizes capabilities by investigation domain. Just as image
        tools belong inside IMAGE, network tools will belong inside NETWORK —
        one continuous network investigation workflow.
      </div>
      <div className="domain-placeholder-section-label">PLANNED CAPABILITIES</div>
      <div className="domain-placeholder-list">
        {FUTURE_TOOLS.map((t) => {
          const Icon = t.icon;
          return (
            <div key={t.label} className="domain-placeholder-item">
              <span className="domain-placeholder-item-icon"><Icon className="w-4 h-4" /></span>
              <span className="domain-placeholder-item-label">{t.label}</span>
              <span className="domain-placeholder-item-tag">PLANNED</span>
            </div>
          );
        })}
      </div>
      <div className="domain-placeholder-note">
        These tools are not yet implemented. The navigation and workbench
        architecture is ready to host them when they arrive.
      </div>
    </div>
  );
}
