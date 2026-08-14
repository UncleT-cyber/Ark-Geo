/**
 * ActivityBar — narrow far-left navigation bar (VS Code-style).
 *
 * Provides access to major investigator areas:
 *   - Upload (Target)
 *   - Explorer (Evidence tree)
 *   - Analysis (Tool tabs)
 *   - Settings
 *
 * Remains visually quiet and professional — Lucide SVG icons with tooltips.
 */
import React from 'react';
import { ACTIVITY_ICONS, UI_ICONS } from './icons';
import type { LucideIcon } from './icons';

export type ActivityView = 'upload' | 'explorer' | 'analysis' | 'settings';

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

const ITEMS: ActivityItem[] = [
  { id: 'upload', icon: ACTIVITY_ICONS.upload, label: 'Target Upload' },
  { id: 'explorer', icon: ACTIVITY_ICONS.explorer, label: 'Evidence Explorer' },
  { id: 'analysis', icon: ACTIVITY_ICONS.analysis, label: 'Analysis & Tools' },
  { id: 'settings', icon: ACTIVITY_ICONS.settings, label: 'Settings' },
];

export function ActivityBar({ active, onNavigate, evidenceCount }: ActivityBarProps) {
  const Brand = UI_ICONS.brand;
  return (
    <div className="activity-bar">
      <div className="activity-brand"><Brand className="w-5 h-5" /></div>
      <div className="activity-items">
        {ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              className={`activity-item ${active === item.id ? 'activity-item-active' : ''}`}
              onClick={() => onNavigate(item.id)}
              title={item.label}
            >
              <span className="activity-icon"><Icon className="w-5 h-5" /></span>
              {item.id === 'explorer' && evidenceCount ? (
                <span className="activity-badge">{evidenceCount}</span>
              ) : null}
            </button>
          );
        })}
      </div>
      <div className="activity-footer">
        <span className="activity-icon activity-icon-dim" title="THE ARK Forensic Workbench">
          <Brand className="w-4 h-4" />
        </span>
      </div>
    </div>
  );
}
