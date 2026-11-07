import {
  BookOpen, Bot, FolderKanban, PanelLeftClose, PanelLeftOpen, Settings, ShieldCheck,
} from 'lucide-react';
import { DOMAIN_ICONS } from './icons';
import type { DomainId } from './entities';

const workspaces = [
  ['image', 'Image Intelligence'],
  ['network', 'Network Intelligence'],
  ['secops', 'Threat & SecOps'],
] as const;

export const USE_CASES = [
  { id: 'assessment', name: 'Security Assessment', note: 'Starts with passive Network Discovery' },
  { id: 'discovery', name: 'Network Discovery', note: 'Passive DNS and registry lookups' },
  { id: 'forensics', name: 'Image Forensics', note: 'Image intake and evidence analysis' },
  { id: 'web', name: 'Web & API Security', note: 'HTTP / Web Analysis' },
  { id: 'phishing', name: 'Phishing Investigation', note: 'Planned' },
  { id: 'hunting', name: 'Threat Hunting', note: 'Planned' },
  { id: 'custom', name: 'Custom Workflow', note: 'Planned' },
] as const;

type UseCaseId = typeof USE_CASES[number]['id'];

interface Props {
  collapsed: boolean;
  domain: DomainId;
  onToggle: () => void;
  onNavigate: (domain: DomainId) => void;
  /** Opens the Use Cases surface (quick-start catalog). */
  onUseCases: () => void;
  onSettings: () => void;
  onAdmin?: () => void;
}

/**
 * Investigation navigation — the sidebar information architecture.
 *
 * Scrollable body flows top to bottom: WORKSPACES, INVESTIGATIONS (with extra
 * breathing room), AUTOMATION. SYSTEM (Admin, Settings) is pinned to the
 * sidebar footer, below the scroll area, so account/system controls stay put
 * regardless of how many groups the body holds.
 *
 * Open investigation sessions live in the titlebar tabs, so this sidebar holds
 * no per-session list and no Command Palette entry (that is Cmd/Ctrl+K).
 */
export function InvestigationNavigation(props: Props) {
  const CollapseIcon = props.collapsed ? PanelLeftOpen : PanelLeftClose;

  return (
    <aside className={`workbench-sidebar investigation-navigation ${props.collapsed ? 'workbench-sidebar-collapsed' : ''}`} aria-label="Investigation navigation">
      <div className="investigation-brand-rail"><span>ARK</span></div>
      <div className="investigation-nav-heading">
        <button type="button" className="investigation-nav-item investigation-nav-collapse" onClick={props.onToggle}
          aria-label={props.collapsed ? 'Expand navigation' : 'Collapse navigation'}
          aria-expanded={!props.collapsed}
          title={props.collapsed ? 'Expand navigation' : 'Collapse navigation'}>
          <CollapseIcon size={17} />
        </button>
      </div>
      <div className="investigation-nav-scroll">
        <nav className="investigation-nav-group" aria-label="Workspaces">
          {!props.collapsed && <div className="investigation-nav-label">Workspaces</div>}
          {workspaces.map(([id, label]) => {
            const Icon = DOMAIN_ICONS[id];
            return <button className="investigation-nav-item" type="button" key={id} aria-label={label}
              aria-current={props.domain === id ? 'page' : undefined} title={label} onClick={() => props.onNavigate(id)}>
              <Icon size={16} /><span>{label}</span>
            </button>;
          })}
        </nav>

        <nav className="investigation-nav-group investigation-nav-group-gap" aria-label="Investigations">
          {!props.collapsed && <div className="investigation-nav-label">Investigations</div>}
          <button type="button" className="investigation-nav-item" aria-label="Case Explorer" title="Case Explorer"
            aria-current={props.domain === 'cases' ? 'page' : undefined} onClick={() => props.onNavigate('cases')}>
            <FolderKanban size={16} /><span>Case Explorer</span>
          </button>
          <button type="button" className="investigation-nav-item" aria-label="Use Cases" title="Use Cases" onClick={props.onUseCases}>
            <BookOpen size={16} /><span>Use Cases</span>
          </button>
        </nav>

        <nav className="investigation-nav-group" aria-label="Automation">
          {!props.collapsed && <div className="investigation-nav-label">Automation</div>}
          <button type="button" className="investigation-nav-item" aria-label="Agents & Workflows" title="Agents & Workflows" disabled>
            <Bot size={16} /><span>Agents &amp; Workflows</span><small>Planned</small>
          </button>
        </nav>
      </div>

      <nav className="investigation-nav-group investigation-nav-system" aria-label="System">
        {!props.collapsed && <div className="investigation-nav-label">System</div>}
        {props.onAdmin && <button type="button" className="investigation-nav-item" aria-label="Admin" title="Admin" onClick={props.onAdmin}><ShieldCheck size={16} /><span>Admin</span></button>}
        <button type="button" className="investigation-nav-item" aria-label="Settings" title="Settings" onClick={props.onSettings}><Settings size={16} /><span>Settings</span></button>
      </nav>
    </aside>
  );
}
