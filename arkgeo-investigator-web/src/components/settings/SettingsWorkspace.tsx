/**
 * SettingsWorkspace — the full-page Settings surface.
 *
 * Replaces the deprecated floating modal. It renders inside the normal
 * application window, beneath the investigation tab strip, occupying the full
 * content area. When active, the investigation workspace hides its sidebar,
 * central viewport and ARK dock (see Workbench) and this component takes over.
 *
 * Layout is two-column: a fixed-width settings rail on the left and a
 * comfortable, independently-scrolling content column on the right. Styling is
 * the OLED-black THE ARK theme (see settings-workspace.css).
 *
 * This is a LAYOUT refactor only — every settings panel below is the same
 * component the modal used. No BYOK, model-routing or vault behaviour changes.
 */
import React, { useEffect, useState } from 'react';
import {
  KeyRound, Plug, Activity, Cpu, Folder, Bell, Heart, Shield, CheckCircle2, Lock,
} from 'lucide-react';
import { api } from '../../api';
import { ByokPanel } from './ByokPanel';
import { ClientModelConfigPanel } from './ClientModelConfig';
import { ClientVaultManager } from './ClientVaultManager';
import { NotificationsPanel } from './NotificationsPanel';
import { SupportPanel } from './SupportPanel';
import { ProvidersPanel, SystemHealthPanel } from './ProvidersPanel';
import type { SavedCase } from '../workbench/useInvestigation';
import type { ApiKeyStatus } from '../workbench/TopBar';
import './settings-workspace.css';

export type SettingsSectionId =
  | 'keys' | 'providers' | 'health' | 'model' | 'vault' | 'notifications' | 'support';

interface SectionMeta {
  id: SettingsSectionId;
  label: string;
  title: string;
  desc: string;
  icon: React.ComponentType<{ className?: string; size?: number | string }>;
}

export const SETTINGS_SECTIONS: SectionMeta[] = [
  { id: 'keys', label: 'API Keys (BYOK)', title: 'API Keys (BYOK)', icon: KeyRound,
    desc: 'Bring your own provider keys. Leave a field empty to fall back to the platform key or environment.' },
  { id: 'providers', label: 'Providers & Connections', title: 'Providers & Connections', icon: Plug,
    desc: 'Runtime connection state of every external provider the ARK can drive. Secrets are never shown here.' },
  { id: 'health', label: 'System Health', title: 'System Health', icon: Activity,
    desc: 'Backend connectivity and local toolchain availability.' },
  { id: 'model', label: 'Model & Privacy', title: 'Model & Privacy', icon: Cpu,
    desc: 'Choose the reasoning provider and whether pixels ever leave this machine.' },
  { id: 'vault', label: 'Saved Case Vault', title: 'Saved Case Vault', icon: Folder,
    desc: 'Local archive of completed evidence investigations.' },
  { id: 'notifications', label: 'Notifications', title: 'Notifications', icon: Bell,
    desc: 'Report branding and how you want to be alerted.' },
  { id: 'support', label: 'Support & Open Source', title: 'Support & Open Source', icon: Heart,
    desc: 'Community, funding and connection status.' },
];

interface SettingsWorkspaceProps {
  section: SettingsSectionId;
  onSection: (id: SettingsSectionId) => void;
  onRestoreCase: (saved: SavedCase) => void;
  apiStatuses: ApiKeyStatus[];
  connected: boolean;
}

export function SettingsWorkspace({
  section, onSection, onRestoreCase, apiStatuses, connected,
}: SettingsWorkspaceProps) {
  const [exifToolPath, setExifToolPath] = useState<string>('');
  const [exifToolOk, setExifToolOk] = useState<boolean | null>(null);
  const [checking, setChecking] = useState(false);

  // Provider/toolchain probe — carried over from the modal.
  useEffect(() => {
    let active = true;
    setChecking(true);
    api.health()
      .then((h: any) => {
        if (!active) return;
        setExifToolPath(h?.exiftool_path || h?.services?.exiftool_path || '(detected on PATH)');
        setExifToolOk(Boolean(h?.services?.exiftool ?? h?.exiftool_available ?? true));
      })
      .catch(() => { if (active) { setExifToolPath('—'); setExifToolOk(false); } })
      .finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, []);

  const meta = SETTINGS_SECTIONS.find(s => s.id === section) ?? SETTINGS_SECTIONS[0];

  const renderSection = () => {
    switch (section) {
      case 'keys':
        return <ByokPanel />;
      case 'providers':
        return <ProvidersPanel apiStatuses={apiStatuses} exifToolPath={exifToolPath} exifToolOk={exifToolOk} checking={checking} />;
      case 'health':
        return <SystemHealthPanel connected={connected} exifToolOk={exifToolOk} checking={checking} />;
      case 'model':
        return <ClientModelConfigPanel />;
      case 'vault':
        return <ClientVaultManager onRestoreCase={onRestoreCase} />;
      case 'notifications':
        return <NotificationsPanel />;
      case 'support':
        return <SupportPanel />;
      default:
        return null;
    }
  };

  return (
    <section className="settings-workspace" aria-label="Settings">
      <nav className="settings-workspace-nav" aria-label="Settings sections">
        <div className="settings-workspace-nav-head">Settings</div>
        <div className="settings-workspace-nav-list">
          {SETTINGS_SECTIONS.map(s => {
            const Icon = s.icon;
            return (
              <button
                key={s.id}
                type="button"
                className={`settings-workspace-nav-item ${section === s.id ? 'is-active' : ''}`}
                aria-current={section === s.id ? 'page' : undefined}
                onClick={() => onSection(s.id)}
              >
                <Icon size={15} />
                <span>{s.label}</span>
              </button>
            );
          })}
        </div>
        <div className="settings-workspace-nav-foot">
          <span className={`settings-workspace-conn ${connected ? 'is-on' : 'is-off'}`}>
            {connected ? <CheckCircle2 size={12} /> : <Activity size={12} />}
            {connected ? 'ARK Core connected' : 'ARK Core offline'}
          </span>
          <span className="settings-workspace-foot-note">
            <Shield size={12} /> Admin is a protected control plane — not accessible from here.
          </span>
        </div>
      </nav>

      <div className="settings-workspace-content">
        <div className="settings-workspace-scroll">
          <header className="settings-workspace-head">
            <h1>{meta.title}</h1>
            <p>{meta.desc}</p>
          </header>
          <div className="settings-workspace-body">{renderSection()}</div>
          <footer className="settings-workspace-footer">
            <span className="settings-workspace-foot-item">
              <Lock size={12} /> Keys are stored obfuscated on this device — see the security note under API Keys. They never reach our servers except during a connection test.
            </span>
          </footer>
        </div>
      </div>
    </section>
  );
}
