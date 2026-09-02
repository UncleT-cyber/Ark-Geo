/**
 * TopBar — 40px top application bar.
 *
 * Single subtle ARK identity on the left (one wordmark — no duplicate logos
 * elsewhere). Center: global command palette (Cmd/Ctrl+K). Right: status
 * badges, API provider indicators, connection state, and the logged-in
 * investigator's profile/session icon.
 *
 * The profile icon opens the Investigator Profile Modal — it NEVER links to
 * Admin. Admin is reachable only via the stealth hotkey Cmd/Ctrl+Shift+P
 * (handled globally in App.tsx) plus server-side authorization at /console-auth.
 */
import React from 'react';
import { Save } from 'lucide-react';
import { UI_ICONS } from './icons';

export interface ApiKeyStatus {
  configured: boolean;
  label: string;
  title: string;
}

interface TopBarProps {
  activeCaseId: string | null;
  apiStatuses: ApiKeyStatus[];
  connected: boolean;
  onOpenPalette: () => void;
  onOpenProfile: () => void;
  /** Save the current workspace observations into the Case Vault (all domains). */
  onSaveInvestigation: () => void;
}

export function TopBar({
  activeCaseId,
  apiStatuses,
  connected,
  onOpenPalette,
  onOpenProfile,
  onSaveInvestigation,
}: TopBarProps) {
  const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
  const paletteHint = isMac ? '⌘K' : 'Ctrl+K';
  const SearchIcon = UI_ICONS.search;
  const UserIcon = UI_ICONS.user;

  return (
    <div className="topbar">
      {/* Left: single subtle ARK identity + active case.
          macOS/Electron safe zone: padding-left keeps ARK clear of native
          traffic-light (Close/Minimize/Expand) window controls in desktop mode. */}
      <div className="topbar-left">
        <span className="topbar-ark">ARK</span>
        {activeCaseId && (
          <>
            <span className="topbar-sep" />
            <span className="topbar-case mono" title="Active case">{activeCaseId}</span>
          </>
        )}
      </div>

      {/* Center: command palette search */}
      <div className="topbar-center">
        <button className="topbar-search" onClick={onOpenPalette} title="Open command palette">
          <span className="topbar-search-icon"><SearchIcon className="w-4 h-4" /></span>
          <span className="topbar-search-text">Search or run a command…</span>
          <span className="topbar-search-kbd">{paletteHint}</span>
        </button>
      </div>

      {/* Right: status badges + API indicators + profile (NOT admin) */}
      <div className="topbar-right">
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
        <button
          className="topbar-icon-btn topbar-save-btn"
          onClick={onSaveInvestigation}
          title="Save Investigation to Case Vault"
        >
          <Save className="w-4 h-4" />
        </button>
        <button className="topbar-icon-btn" onClick={onOpenProfile} title="Investigator Profile & Session">
          <UserIcon className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
