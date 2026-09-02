/**
 * ClientSettingsModal — the client-side Settings & BYOK dashboard.
 *
 * Tabbed overlay (Keys / Model / Vault / Notifications / Support) reached
 * from the ActivityBar gear. Replaces the old read-only provider status
 * panel with an actionable dashboard: BYOK key vault, model + privacy
 * config, saved-case vault, notification prefs and support links.
 *
 * Contrast with the Admin console: this panel never writes server secrets
 * and never links to Admin. Admin remains reachable only via the stealth
 * hotkey Cmd/Ctrl+Shift+P plus authorization at /console-auth.
 */
import React, { useState } from 'react';
import {
  X, Settings, KeyRound, Cpu, Folder, Bell, Heart, Shield, CheckCircle2,
} from 'lucide-react';
import { ByokPanel } from './ByokPanel';
import { ClientModelConfigPanel } from './ClientModelConfig';
import { ClientVaultManager } from './ClientVaultManager';
import { NotificationsPanel } from './NotificationsPanel';
import { SupportPanel } from './SupportPanel';
import type { ApiKeyStatus } from '../workbench/TopBar';

type TabId = 'keys' | 'model' | 'vault' | 'notifications' | 'support';

const TABS: { id: TabId; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'keys', label: 'API Keys (BYOK)', icon: KeyRound },
  { id: 'model', label: 'Model & Privacy', icon: Cpu },
  { id: 'vault', label: 'Saved Case Vault', icon: Folder },
  { id: 'notifications', label: 'Notifications', icon: Bell },
  { id: 'support', label: 'Support & Open Source', icon: Heart },
];

interface ClientSettingsModalProps {
  open: boolean;
  onClose: () => void;
  apiStatuses: ApiKeyStatus[];
  connected: boolean;
}

export function ClientSettingsModal({ open, onClose, apiStatuses, connected }: ClientSettingsModalProps) {
  const [tab, setTab] = useState<TabId>('keys');

  if (!open) return null;

  return (
    <div className="ark-settings-overlay" onClick={onClose}>
      <div className="ark-settings ark-settings-modal" onClick={e => e.stopPropagation()}>
        <header className="ark-settings-header">
          <span className="ark-settings-title-row-icon" style={{ display: 'inline-flex' }}>
            <Settings className="w-4 h-4" style={{ color: '#06B6D4' }} />
          </span>
          <div className="ark-settings-header-title">
            <span className="ark-settings-title">CLIENT SETTINGS</span>
            <span className="ark-settings-subtitle">BYOK VAULT · MODEL · VAULT · NOTIFICATIONS</span>
          </div>
          <span className="ark-settings-plan-badge">PRO PLAN</span>
          <span className="ark-settings-header-spacer" />
          <button className="ark-settings-close" onClick={onClose} title="Close">
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="ark-settings-body">
          <nav className="ark-settings-tabs">
            {TABS.map(t => {
              const Icon = t.icon;
              return (
                <button
                  key={t.id}
                  className={`ark-settings-tab ${tab === t.id ? 'ark-settings-tab-active' : ''}`}
                  onClick={() => setTab(t.id)}
                >
                  <Icon className="w-4 h-4" />
                  {t.label}
                </button>
              );
            })}
          </nav>

          <div className="ark-settings-panel">
            {tab === 'keys' && (
              <>
                <h2 className="ark-settings-panel-title">Bring Your Own Keys</h2>
                <p className="ark-settings-panel-desc">
                  Personal provider keys stored locally. Leave empty to fall back to the Admin system key or .env.
                </p>
                <ByokPanel />
              </>
            )}
            {tab === 'model' && (
              <>
                <h2 className="ark-settings-panel-title">Model &amp; Privacy</h2>
                <p className="ark-settings-panel-desc">
                  Choose the reasoning provider and whether pixels ever leave this machine.
                </p>
                <ClientModelConfigPanel />
              </>
            )}
            {tab === 'vault' && (
              <>
                <h2 className="ark-settings-panel-title">Saved Case Vault</h2>
                <p className="ark-settings-panel-desc">
                  Local archive of completed evidence investigations.
                </p>
                <ClientVaultManager />
              </>
            )}
            {tab === 'notifications' && (
              <>
                <h2 className="ark-settings-panel-title">Notifications &amp; Branding</h2>
                <p className="ark-settings-panel-desc">
                  Report watermarks and how you want to be alerted.
                </p>
                <NotificationsPanel />
              </>
            )}
            {tab === 'support' && (
              <>
                <h2 className="ark-settings-panel-title">Support &amp; Open Source</h2>
                <p className="ark-settings-panel-desc">
                  Community, funding and connection status.
                </p>
                <SupportPanel />
              </>
            )}
          </div>
        </div>

        <footer className="ark-settings-footer">
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <Shield className="w-3 h-3" style={{ color: '#06B6D4' }} />
            Keys never leave this device unless tested — server-side system keys are never exposed here.
          </span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <CheckCircle2 className="w-3 h-3" style={{ color: connected ? '#10B981' : '#6B7280' }} />
            {connected ? 'ARK Core Connected' : 'ARK Core Offline'}
          </span>
        </footer>
      </div>
    </div>
  );
}
