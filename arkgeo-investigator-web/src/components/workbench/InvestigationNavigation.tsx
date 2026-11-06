import { useState } from 'react';
import {
  BookOpen, Bot, ChevronRight, Crosshair, FolderKanban, Globe, Image, MailSearch, MessageCircle, Network, PanelLeftClose, PanelLeftOpen, Plus,
  Search, Settings, ShieldCheck, Workflow, Wrench,
} from 'lucide-react';
import { DOMAIN_ICONS } from './icons';
import type { DomainId } from './entities';
import type { SavedCase } from './useInvestigation';

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
  activeCaseId: string | null;
  analyzing: boolean;
  history: SavedCase[];
  onToggle: () => void;
  onNew: () => void;
  onNavigate: (domain: DomainId) => void;
  onRestore: (saved: SavedCase) => void;
  onUseCase: (id: UseCaseId) => void;
  onTools: () => void;
  onSettings: () => void;
  onAdmin?: () => void;
}

export function InvestigationNavigation(props: Props) {
  const [showSearch, setShowSearch] = useState(false);
  const [query, setQuery] = useState('');
  const [showCatalog, setShowCatalog] = useState(false);
  const [useCaseQuery, setUseCaseQuery] = useState('');
  const [confirmNew, setConfirmNew] = useState(false);
  const useCaseIcons = [ShieldCheck, Network, Image, Globe, MailSearch, Crosshair, Workflow];
  const CollapseIcon = props.collapsed ? PanelLeftOpen : PanelLeftClose;
  const recent = props.history.filter(item =>
    [item.caseName, item.filename, item.caseId].some(value =>
      value?.toLowerCase().includes(query.trim().toLowerCase()),
    ),
  );
  const useCases = USE_CASES.filter(item => (showCatalog || ['discovery', 'forensics', 'web'].includes(item.id)) &&
    `${item.name} ${item.note}`.toLowerCase().includes(useCaseQuery.trim().toLowerCase()),
  );
  const startNew = () => {
    if (props.activeCaseId) {
      if (props.collapsed) props.onToggle();
      setConfirmNew(true);
    } else props.onNew();
  };

  return (
    <aside className={`workbench-sidebar investigation-navigation ${props.collapsed ? 'workbench-sidebar-collapsed' : ''}`} aria-label="Investigation navigation">
      <div className="investigation-brand-rail"><span>ARK</span></div>
      <div className="investigation-nav-heading">
        <button type="button" className="investigation-nav-item investigation-nav-new" onClick={startNew}
          disabled={props.analyzing} aria-label="New Investigation" title="New Investigation">
          <Plus size={17} /><span>New Investigation</span>
        </button>
        <button type="button" className="investigation-nav-item investigation-nav-collapse" onClick={props.onToggle}
          aria-label={props.collapsed ? 'Expand navigation' : 'Collapse navigation'}
          aria-expanded={!props.collapsed}
          title={props.collapsed ? 'Expand navigation' : 'Collapse navigation'}>
          <CollapseIcon size={17} />
        </button>
      </div>
      <div className="investigation-nav-scroll">
        {!props.collapsed && confirmNew && (
          <div className="investigation-nav-confirm">
            <p>Start fresh and clear the active workspace? Saved cases can still be reopened.</p>
            <button type="button" onClick={() => { setConfirmNew(false); props.onNew(); }} disabled={props.analyzing}>Start fresh</button>
            <button type="button" onClick={() => setConfirmNew(false)}>Cancel</button>
          </div>
        )}

        <details className="investigation-nav-group" open hidden={props.collapsed}>
          <summary>Recent Investigations<ChevronRight size={13} /></summary>
          {!!props.history.length && <button className="investigation-search-toggle" type="button" aria-label="Search recent investigations" aria-expanded={showSearch} onClick={() => { setShowSearch(!showSearch); setQuery(''); }}><Search size={13} /></button>}
          {showSearch && <label className="investigation-nav-search">
            <Search size={14} /><input aria-label="Search recent investigations" placeholder="Search saved investigations" value={query} onChange={event => setQuery(event.target.value)} />
          </label>}
          {recent.slice(0, query.trim() ? 10 : 3).map(item => (
            <button key={item.caseId} className="investigation-nav-item" type="button"
              disabled={props.analyzing}
              aria-current={item.caseId === props.activeCaseId ? 'true' : undefined}
              onClick={() => props.onRestore(item)} title={item.caseName || item.filename}>
              <MessageCircle size={14} /><span>{item.caseName || item.filename}</span>
            </button>
          ))}
          {!recent.length && <p className="investigation-nav-note">{query ? 'No matching saved investigations.' : 'Saved investigations appear here.'}</p>}
          <button className="investigation-nav-item" type="button" onClick={() => props.onNavigate('cases')}><BookOpen size={14} /><span>View All</span></button>
        </details>

        <details className="investigation-nav-group" open hidden={props.collapsed}>
          <summary>Use Cases<ChevronRight size={13} /></summary>
          {useCases.map(item => {
            const Icon = useCaseIcons[USE_CASES.indexOf(item)];
            return <button key={item.id} className="investigation-nav-item investigation-use-case" type="button"
              title={item.note} disabled={item.id === 'phishing' || item.id === 'custom'} onClick={() => props.onUseCase(item.id)}>
              <Icon size={15} /><span>{item.name}</span>{item.note === 'Planned' && <small>Planned</small>}{item.id === 'assessment' && <small>Passive</small>}
            </button>;
          })}
          {useCaseQuery && !useCases.length && <p className="investigation-nav-note">No matching use cases.</p>}
          {showCatalog && <label className="investigation-nav-search investigation-use-case-search">
            <Search size={13} /><input aria-label="Search use cases" placeholder="Filter use cases" value={useCaseQuery} onChange={event => setUseCaseQuery(event.target.value)} />
          </label>}
          <button type="button" className="investigation-nav-item" aria-expanded={showCatalog} onClick={() => { setShowCatalog(!showCatalog); setUseCaseQuery(''); }}><BookOpen size={14} /><span>{showCatalog ? 'Show fewer use cases' : 'View All Use Cases'}</span></button>
        </details>

        <details key={String(props.collapsed)} className="investigation-nav-group investigation-workspaces" open>
          <summary hidden={props.collapsed}>Workspaces<ChevronRight size={13} /></summary>
          {workspaces.map(([id, label]) => {
            const Icon = DOMAIN_ICONS[id];
            return <button className="investigation-nav-item" type="button" key={id} aria-label={label}
              aria-current={props.domain === id ? 'page' : undefined} title={label} onClick={() => props.onNavigate(id)}>
              <Icon size={16} /><span>{label}</span>
            </button>;
          })}
        </details>

        <div className="investigation-nav-group investigation-nav-library">
          <button type="button" className="investigation-nav-item" aria-label="Case Explorer" title="Case Explorer" aria-current={props.domain === 'cases' ? 'page' : undefined} onClick={() => props.onNavigate('cases')}><FolderKanban size={15} /><span>Case Explorer</span></button>
          <button type="button" className="investigation-nav-item" aria-label="Command Palette" title="Command Palette" onClick={props.onTools}><Wrench size={15} /><span>Command Palette</span></button>
          <button type="button" className="investigation-nav-item" hidden={props.collapsed} disabled><Bot size={15} /><span>Agents &amp; Workflows</span><small>Planned</small></button>
        </div>
      </div>
      <div className="investigation-nav-system">
        {props.onAdmin && <button type="button" className="investigation-nav-item" aria-label="Admin" title="Admin" onClick={props.onAdmin}><ShieldCheck size={16} /><span>Admin</span></button>}
        <button type="button" className="investigation-nav-item" aria-label="Settings" title="Settings" onClick={props.onSettings}><Settings size={16} /><span>Settings</span></button>
      </div>
    </aside>
  );
}
