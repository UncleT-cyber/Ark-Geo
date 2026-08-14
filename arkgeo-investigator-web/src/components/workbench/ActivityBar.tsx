/**
 * ActivityBar — narrow far-left DOMAIN navigation bar.
 *
 * THE ARK is organized by investigation domains, not individual tools.
 * Each domain contains all tools required to complete that investigation:
 *   - IMAGE   — full image intelligence & forensic investigation domain (primary)
 *   - NETWORK — reserved for future network-security tools (placeholder)
 *   - ADMIN   — admin control plane (bottom)
 *
 * Remains visually quiet and professional — Lucide SVG icons with tooltips.
 */
import React from 'react';
import { UI_ICONS, DOMAIN_ICONS } from './icons';
import type { LucideIcon } from './icons';

export type ActivityView = 'image' | 'network' | 'admin' | 'settings';

interface ActivityItem {
  id: ActivityView;
  icon: LucideIcon;
  label: string;
  badge?: number;
}

interface ActivityBarProps {
  active: ActivityView;
  onNavigate: (view: ActivityView) => void;
  evidenceCount?: number;
}

const PRIMARY_DOMAINS: ActivityItem[] = [
  { id: 'image', icon: DOMAIN_ICONS.image, label: 'Image Investigation' },
  { id: 'network', icon: DOMAIN_ICONS.network, label: 'Network Investigation' },
];

const FOOTER_ITEMS: ActivityItem[] = [
  { id: 'admin', icon: DOMAIN_ICONS.admin, label: 'Admin Console' },
  { id: 'settings', icon: UI_ICONS.settings, label: 'Settings' },
];

export function ActivityBar({ active, onNavigate, evidenceCount }: ActivityBarProps) {
  const Brand = UI_ICONS.brand;
  return (
    <div className="activity-bar">
      <div className="activity-brand"><Brand className="w-5 h-5" /></div>
      <div className="activity-items">
        {PRIMARY_DOMAINS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              className={`activity-item ${active === item.id ? 'activity-item-active' : ''}`}
              onClick={() => onNavigate(item.id)}
              title={item.label}
            >
              <span className="activity-icon"><Icon className="w-5 h-5" /></span>
              {item.id === 'image' && evidenceCount ? (
                <span className="activity-badge">{evidenceCount}</span>
              ) : null}
            </button>
          );
        })}
      </div>
      <div className="activity-footer">
        {FOOTER_ITEMS.map((item) => {
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
    </div>
  );
}
