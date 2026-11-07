/**
 * TopBar — investigation tabs, and nothing else.
 *
 * Desktop: this bar IS the Electron titlebar. macOS traffic lights sit in the
 * left safe zone; Windows/Linux native window controls sit in the right safe
 * zone (see workbench.css). The empty strip is a drag region; controls opt out.
 *
 * Web: the same compact strip lives inside the existing topbar — there is no
 * second navigation row.
 *
 * The header is dedicated to investigation tabs:
 *   1. investigation tabs   2. `+` new investigation
 *   3. tab overflow         4. notification bell (far right)
 *
 * Search/command lives on Cmd+K / Ctrl+K only. Provider connections live in
 * Settings → Providers & Connections. Backend health lives in Settings →
 * System Health. Save lives in the investigation actions menu. Account lives
 * in user Settings.
 */
import React from 'react';
import { InvestigationTabStrip, NotificationBell } from './InvestigationTabs';
import type { InvestigationTab } from '../../core/tabs/tabRegistry';
import type { AppNotification } from '../../core/notifications';

interface TopBarProps {
  tabs: InvestigationTab[];
  activeTabId: string | null;
  onSelectTab: (id: string) => void;
  onCloseTab: (id: string) => void;
  onNewTab: () => void;
  notifications: AppNotification[];
  unread: number;
  onOpenNotification: (n: AppNotification) => void;
  onMarkAllRead: () => void;
}

export function TopBar({
  tabs,
  activeTabId,
  onSelectTab,
  onCloseTab,
  onNewTab,
  notifications,
  unread,
  onOpenNotification,
  onMarkAllRead,
}: TopBarProps) {
  return (
    <div className="topbar">
      <InvestigationTabStrip
        tabs={tabs}
        activeId={activeTabId}
        onSelect={onSelectTab}
        onClose={onCloseTab}
        onNew={onNewTab}
      />
      <div className="topbar-right">
        <NotificationBell
          notifications={notifications}
          unread={unread}
          onOpen={onOpenNotification}
          onMarkAllRead={onMarkAllRead}
        />
      </div>
    </div>
  );
}

/** Provider status is derived in Workbench and surfaced in Settings, not the
 *  header; the type is kept for existing imports. */
export interface ApiKeyStatus {
  configured: boolean;
  label: string;
  title: string;
}
