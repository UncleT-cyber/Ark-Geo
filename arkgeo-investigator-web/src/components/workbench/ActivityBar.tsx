/**
 * ActivityBar — narrow far-left WORKSPACE navigation bar.
 *
 * THE ARK ISE is organized by investigation workspaces, not tools. The
 * top-level navigation represents the workspaces themselves:
 *   - IMAGE   — Image Intelligence Workspace (primary)
 *   - NETWORK — Network Workspace (structural placeholder)
 *   - SECOPS  — Threat & SecOps Workspace (SIEM, IDS/IPS, threat hunting,
 *               detection & correlation, incident management, SecOps dashboard)
 *   - CASES   — Case Workspace (cross-domain saved sessions & audit vault)
 *
 * The footer holds a SETTINGS gear (System & API Provider Configuration:
 * GeoSpy, OpenAI Vision, Mapbox, ExifTool pathing). The investigator's
 * PROFILE/session lives in the TopBar avatar on the right. Neither footer
 * nor topbar EVER links to Admin — Admin is a protected control plane
 * accessible only via stealth hotkey (Cmd/Ctrl+Shift+P) and server-side
 * authorization.
 *
 * A single subtle "ARK" wordmark sits at the very bottom in muted slate. There
 * are no duplicate logos anywhere else in the interface.
 */
import React from 'react';
import { DOMAIN_ICONS, FOOTER_ICONS } from './icons';
import type { LucideIcon } from './icons';
import type { DomainId } from './entities';

interface ActivityItem {
  id: DomainId;
  icon: LucideIcon;
  label: string;
}

interface ActivityBarProps {
  active: DomainId;
  onNavigate: (view: DomainId) => void;
  onOpenSettings: () => void;
}

const DOMAINS: ActivityItem[] = [
  { id: 'image', icon: DOMAIN_ICONS.image, label: 'Image Intelligence Workspace' },
  { id: 'network', icon: DOMAIN_ICONS.network, label: 'Network Workspace' },
  { id: 'secops', icon: DOMAIN_ICONS.secops, label: 'Threat & SecOps Workspace' },
  { id: 'cases', icon: DOMAIN_ICONS.cases, label: 'Case Workspace' },
];

export function ActivityBar({ active, onNavigate, onOpenSettings }: ActivityBarProps) {
  const SettingsIcon = FOOTER_ICONS.settings;
  return (
    <div className="activity-bar">
      <div className="activity-items">
        {DOMAINS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              className={`activity-item ${active === item.id ? 'activity-item-active' : ''}`}
              onClick={() => onNavigate(item.id)}
              title={item.label}
            >
              <span className="activity-icon"><Icon className="w-5 h-5" /></span>
            </button>
          );
        })}
      </div>
      <div className="activity-footer">
        <button
          className="activity-item"
          onClick={onOpenSettings}
          title="System & API Provider Configuration"
        >
          <span className="activity-icon"><SettingsIcon className="w-5 h-5" /></span>
        </button>
        {/* Single subtle ARK wordmark — no duplicate logos elsewhere. */}
        <div className="activity-wordmark">ARK</div>
      </div>
    </div>
  );
}
