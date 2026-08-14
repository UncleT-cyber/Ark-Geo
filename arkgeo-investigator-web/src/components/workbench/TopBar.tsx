/**
 * TopBar — 40px top application bar (VS Code / GXP Fusion style).
 *
 * Left:   Application icon + ARKGEO title + workspace selector
 * Center: Global quick search / command palette bar (Cmd+K / Ctrl+Shift+P)
 * Right:  System status badges (malicious / review counts),
 *         API key status indicators, settings icon, user avatar
 */
import React from 'react';

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

  return (
    <div className="topbar">
      {/* Left: brand + workspace selector */}
      <div className="topbar-left">
        <span className="topbar-brand-icon" title="ArkGeo">⬢</span>
        <span className="topbar-brand-title">ARKGEO</span>
        <span className="topbar-sep" />
        <button className="topbar-workspace" title="Active workspace">
          <span className="topbar-workspace-label">Forensic Workbench</span>
          <span className="topbar-chevron">▾</span>
        </button>
      </div>

      {/* Center: command palette search */}
      <div className="topbar-center">
        <button className="topbar-search" onClick={onOpenPalette} title="Open command palette">
          <span className="topbar-search-icon">🔍</span>
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
        <button className="topbar-icon-btn" onClick={onOpenSettings} title="Settings">⚙</button>
        <button className="topbar-icon-btn" onClick={onOpenAdmin} title="Admin Console">👤</button>
      </div>
    </div>
  );
}
