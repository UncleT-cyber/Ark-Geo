/**
 * ActivityBar — narrow far-left navigation bar (VS Code-style).
 *
 * Provides access to major investigator areas:
 *   - Upload (Target)
 *   - Explorer (Evidence tree)
 *   - Analysis (Tool tabs)
 *   - Settings
 *
 * Remains visually quiet and professional — icons with tooltips only.
 */
import React from 'react';

export type ActivityView = 'upload' | 'explorer' | 'analysis' | 'settings';

interface ActivityItem {
  id: ActivityView;
  icon: string;
  label: string;
  badge?: number;
}

interface ActivityBarProps {
  active: ActivityView;
  onNavigate: (view: ActivityView) => void;
  evidenceCount?: number;
}

const ITEMS: ActivityItem[] = [
  { id: 'upload', icon: '⬆', label: 'Target Upload' },
  { id: 'explorer', icon: '🗀', label: 'Evidence Explorer' },
  { id: 'analysis', icon: '🔬', label: 'Analysis & Tools' },
  { id: 'settings', icon: '⚙', label: 'Settings' },
];

export function ActivityBar({ active, onNavigate, evidenceCount }: ActivityBarProps) {
  return (
    <div className="activity-bar">
      <div className="activity-brand">⬢</div>
      <div className="activity-items">
        {ITEMS.map((item) => (
          <button
            key={item.id}
            className={`activity-item ${active === item.id ? 'activity-item-active' : ''}`}
            onClick={() => onNavigate(item.id)}
            title={item.label}
          >
            <span className="activity-icon">{item.icon}</span>
            {item.id === 'explorer' && evidenceCount ? (
              <span className="activity-badge">{evidenceCount}</span>
            ) : null}
          </button>
        ))}
      </div>
      <div className="activity-footer">
        <span className="activity-icon activity-icon-dim" title="ARKGEO Forensic Workbench">ⓘ</span>
      </div>
    </div>
  );
}
