/**
 * TopBar — 40px top application bar (VS Code / GXP Fusion style).
 *
 * Left:   Application icon + THE ARK title + workspace selector
 * Center: Global quick search / command palette bar (Cmd+K / Ctrl+Shift+P)
 * Right:  System status badges (malicious / review counts),
 *         API key status indicators, settings icon, user avatar
 */
import React from 'react';
import { UI_ICONS } from './icons';

/** API service status as returned by the backend /health endpoint. */
export interface ApiKeyStatus {
  configured: boolean;
  label: string;
  title: string;
}

interface TopBarProps {
  maliciousCount: number;
  reviewCount: number;
  apiStatuses: ApiKeyStatus[];
  connected: boolean;
  onOpenPalette: () => void;
  onOpenSettings: () => void;
  onOpenAdmin: () => void;
}

export function TopBar({
  maliciousCount,
  reviewCount,
  apiStatuses,
  connected,
  onOpenPalette,
  onOpenSettings,
  onOpenAdmin,
}: TopBarProps) {
  const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
  const paletteHint = isMac ? '⌘K' : 'Ctrl+K';
  const Brand = UI_ICONS.brand;
  const SearchIcon = UI_ICONS.search;
  const Chevron = UI_ICONS.chevronDown;
  const SettingsIcon = UI_ICONS.settings;
  const UserIcon = UI_ICONS.user;

  return (
    <div className="topbar">
      {/* Left: brand + workspace selector */}
      <div className="topbar-left">
        <span className="topbar-brand-icon" title="THE ARK"><Brand className="w-5 h-5" /></span>
        <span className="topbar-brand-title">THE ARK</span>
        <span className="topbar-sep" />
        <button className="topbar-workspace" title="Active workspace">
          <span className="topbar-workspace-label">Forensic Workbench</span>
          <span className="topbar-chevron"><Chevron className="w-3 h-3" /></span>
        </button>
      </div>

      {/* Center: command palette search */}
      <div className="topbar-center">
        <button className="topbar-search" onClick={onOpenPalette} title="Open command palette">
          <span className="topbar-search-icon"><SearchIcon className="w-4 h-4" /></span>
          <span className="topbar-search-text">Search or run a command…</span>
          <span className="topbar-search-kbd">{paletteHint}</span>
        </button>
      </div>

      {/* Right: status badges + API indicators + actions */}
      <div className="topbar-right">
        <div className="topbar-badges">
          <span className="topbar-badge topbar-badge-red" title="High-risk / malicious sessions">
            <span className="topbar-badge-dot" /> {maliciousCount} Malicious
          </span>
          <span className="topbar-badge topbar-badge-amber" title="Sessions flagged for review">
            <span className="topbar-badge-dot topbar-badge-dot-amber" /> {reviewCount} Review
          </span>
        </div>

        <span className="topbar-sep" />

        {/* API key status indicators */}
        <div className="topbar-api-status" title="Configured API providers">
          {apiStatuses.map((s) => (
            <span
              key={s.label}
              className={`topbar-api-dot ${s.configured ? 'topbar-api-on' : 'topbar-api-off'}`}
              title={s.title}
            >
              {s.label}
            </span>
          ))}
        </div>

        <span className="topbar-sep" />

        <button
          className={`topbar-conn ${connected ? 'topbar-conn-ok' : 'topbar-conn-err'}`}
          title={connected ? 'Backend connected' : 'Backend offline'}
        >
          <span className="topbar-conn-dot" />
        </button>
        <button className="topbar-icon-btn" onClick={onOpenSettings} title="Settings"><SettingsIcon className="w-4 h-4" /></button>
        <button className="topbar-icon-btn" onClick={onOpenAdmin} title="Admin Console"><UserIcon className="w-4 h-4" /></button>
      </div>
    </div>
  );
}
