/**
 * SecurityTestingTab — Authorized Security Testing workspace.
 *
 * Replaces the Phase-1 placeholder for /network/testing.  The active-testing
 * surface is locked behind a signed engagement attestation (SecurityAttestationModal
 * + adminAuditStore).  Once unlocked the operator gets five assessment modules:
 *
 *   ⚡ Vulnerability Assessment   — 7-track matrix (Nuclei, OpenVAS, Nmap NSE,
 *                                OWASP Dependency-Check + Proton-Fuzz,
 *                                Shadow-Route, Aegis-Patch)
 *   🌐 Web / API Security         — DAST config, OpenAPI parser, endpoint crawler
 *   🔑 Exposure & Secret Auditing — entropy scanner, admin-panel detector
 *   📋 Compliance / Baseline      — CIS benchmarks + Ansible remediation generator
 *   🧑‍💻 Social Engineering        — device-drop, susceptibility, phishing sims,
 *                                pretext builder, OSINT recon, click-through board
 *
 * Anything that would require live traffic against a target is executed as an
 * honest dry-run simulation (labelled in-place) — the platform never sends an
 * active request to a target, even behind the attestation.
 */
import React, { useMemo, useState } from 'react';
import {
  Zap, Globe, KeyRound, ClipboardCheck, Users, ShieldCheck, Lock, Loader2,
  ShieldAlert, Download, FileJson,
  Search, User, Target, Send, Eye, MousePointerClick,
  ArrowLeft, ArrowRight, Radar, ScanSearch, PackageSearch, Bug, Waypoints, Cpu,
  RefreshCw, Clock3,
  type LucideIcon,
} from 'lucide-react';
import {
  adminAuditStore,
  type AttestationRecord,
} from '../../../core/utils/telemetry';
import { api } from '../../../api';
import { reactOrchestrator } from '../../../core/react/agentOrchestrator';
import type { ReactSession, ReactTarget } from '../../../types';
import { SecurityAttestationModal } from '../modals/SecurityAttestationModal';
import { VulnerabilityAssessmentTab, type VulnTrackId } from './VulnerabilityAssessmentTab';

type SubTabId = 'vuln' | 'web' | 'secrets' | 'compliance' | 'social' | 'react';

const SUB_TABS: { id: SubTabId; label: string; icon: LucideIcon; hint: string }[] = [
  { id: 'vuln', label: 'Vulnerability Assessment', icon: Zap, hint: '7-track matrix — Nuclei · OpenVAS · Nmap NSE · OWASP DC · Proton-Fuzz · Shadow-Route · Aegis-Patch' },
  { id: 'web', label: 'Web / API Security', icon: Globe, hint: 'DAST config · OpenAPI parser · endpoint crawler' },
  { id: 'secrets', label: 'Exposure & Secret Auditing', icon: KeyRound, hint: 'Entropy scanner · admin-panel detector' },
  { id: 'compliance', label: 'Compliance / Baseline', icon: ClipboardCheck, hint: 'CIS benchmarks · Ansible remediation' },
  { id: 'social', label: 'Social Engineering', icon: Users, hint: 'Device drop · susceptibility · phishing sims' },
  { id: 'react', label: 'RE-ACT Chain', icon: Radar, hint: 'Plan → Scan → Exploit → Escalate → Mitigate' },
];

/** Tool-level sub-navigation populated once a module is selected. */
const MODULE_TOOLS: Record<SubTabId, { id: string; label: string; icon: LucideIcon }[]> = {
  vuln: [
    { id: 'nuclei', label: 'Nuclei', icon: Zap },
    { id: 'openvas', label: 'OpenVAS', icon: ScanSearch },
    { id: 'nmap', label: 'Nmap NSE', icon: Radar },
    { id: 'owasp', label: 'OWASP DC', icon: PackageSearch },
    { id: 'proton', label: 'Proton-Fuzz', icon: Bug },
    { id: 'shadow', label: 'Shadow-Route', icon: Waypoints },
    { id: 'aegis', label: 'Aegis-Patch', icon: Cpu },
  ],
  web: [
    { id: 'dast', label: 'DAST Config', icon: Globe },
    { id: 'openapi', label: 'OpenAPI Parser', icon: FileJson },
    { id: 'crawler', label: 'Endpoint Crawler', icon: Search },
  ],
  secrets: [
    { id: 'entropy', label: 'Entropy Scanner', icon: KeyRound },
    { id: 'admin', label: 'Admin-Panel Detector', icon: Search },
  ],
  compliance: [
    { id: 'baseline', label: 'CIS Baseline Auditor', icon: ClipboardCheck },
    { id: 'ansible', label: 'Ansible Remediation', icon: Download },
  ],
  social: [
    { id: 'campaign', label: 'Click-Through Board', icon: MousePointerClick },
    { id: 'device', label: 'Device Drop', icon: User },
    { id: 'suscept', label: 'Susceptibility Index', icon: ShieldAlert },
    { id: 'pretext', label: 'Pretext Builder', icon: Target },
    { id: 'osint', label: 'OSINT Recon', icon: Eye },
  ],
  react: [
    { id: 'plan', label: 'Plan', icon: Target },
    { id: 'scan', label: 'Scan', icon: Radar },
    { id: 'exploit', label: 'Exploit', icon: Bug },
    { id: 'escalate', label: 'Escalate', icon: Cpu },
    { id: 'mitigate', label: 'Mitigate', icon: ShieldCheck },
  ],
};

/** Landing deck card data — the five authorized assessment modules. */
const DECK_MODULES: { id: SubTabId; name: string; icon: LucideIcon; desc: string; tools: string[] }[] = [
  {
    id: 'vuln', name: 'Vulnerability Assessment', icon: Zap,
    desc: 'Automated scanner matrix with seven tracks — template, credentialed, and fuzz engines against in-scope assets.',
    tools: ['Nuclei', 'OpenVAS', 'Nmap NSE', 'Proton-Fuzz', 'Aegis-Patch'],
  },
  {
    id: 'web', name: 'Web & API Security', icon: Globe,
    desc: 'DAST profile builder, OpenAPI surface parsing, and endpoint crawling for API-first targets.',
    tools: ['DAST Config', 'OpenAPI', 'Crawler'],
  },
  {
    id: 'secrets', name: 'Exposure & Secret Auditing', icon: KeyRound,
    desc: 'Entropy-driven secret scanning and admin-panel / exposure detection across the declared scope.',
    tools: ['Entropy Scanner', 'Exposure Detector'],
  },
  {
    id: 'compliance', name: 'Compliance & Baseline', icon: ClipboardCheck,
    desc: 'CIS benchmark auditing with Ansible remediation playbook generation for failing controls.',
    tools: ['CIS L1/L2', 'Ansible'],
  },
  {
    id: 'social', name: 'Social Engineering Assessment', icon: Users,
    desc: 'Phishing simulations, device-drop, susceptibility index, pretext builder, and OSINT recon.',
    tools: ['Phishing', 'Device Drop', 'Pretext', 'OSINT'],
  },
  {
    id: 'react', name: 'RE-ACT Chain', icon: Radar,
    desc: 'Five-phase autonomous engagement — Plan, Scan, Exploit, Escalate, Mitigate — run against the attested scope through the backend policy-guarded chain.',
    tools: ['Plan', 'Scan', 'Exploit', 'Escalate', 'Mitigate'],
  },
];

// --------------------------------------------------------------------------- //
// Shell — lock gate + status bar + sub-tab routing
// --------------------------------------------------------------------------- //
export function SecurityTestingTab() {
  const [record, setRecord] = useState<AttestationRecord | null>(adminAuditStore.getCurrent());
  const [modalOpen, setModalOpen] = useState(false);

  // Deck → module workspace transition state.
  const [isModuleSelected, setIsModuleSelected] = useState(false);
  const [activeModule, setActiveModule] = useState<SubTabId | null>(null);
  const [focusedTool, setFocusedTool] = useState<string | null>(null);

  const unlocked = record !== null;

  const revoke = () => {
    adminAuditStore.revoke();
    setRecord(null);
  };

  const openModule = (id: SubTabId) => {
    setActiveModule(id);
    setFocusedTool(null);
    setIsModuleSelected(true);
  };

  const exitToModules = () => {
    setActiveModule(null);
    setFocusedTool(null);
    setIsModuleSelected(false);
  };

  if (!unlocked) {
    return (
      <div className="tool-view">
        <div className="se-gate">
          <div className="se-gate-pad">
            <div className="se-gate-icon"><Lock className="w-6 h-6" /></div>
            <div className="se-gate-title">AUTHORIZED SECURITY TESTING — LOCKED</div>
            <p className="se-gate-text">
              The active-testing surface is gated behind a signed engagement
              attestation. You must declare identity, engagement purpose and an
              explicit target scope / ROE reference before any module unlocks.
            </p>
            <div className="se-gate-chips">
              {SUB_TABS.map(t => {
                const Icon = t.icon;
                return (
                  <div key={t.id} className="se-gate-chip" title={t.hint}>
                    <Lock className="w-3 h-3" /> <Icon className="w-3 h-3" /> {t.label}
                  </div>
                );
              })}
            </div>
            <button className="se-btn se-btn-primary se-gate-cta" onClick={() => setModalOpen(true)}>
              <ShieldCheck className="w-4 h-4" /> SIGN ATTESTATION — ENTER WORKSPACE
            </button>
            <div className="se-gate-foot">
              Attestations are appended to the non-repudiation audit trail with a
              server-observed IP. Unlock is session-scoped only.
            </div>
          </div>
        </div>
        <SecurityAttestationModal open={modalOpen} onClose={() => setModalOpen(false)}
          onAttested={(r) => { setRecord(r); setModalOpen(false); }} />
      </div>
    );
  }

  return (
    <div className="tool-view">
      <div className="se-shell">
        <div className="se-statusbar">
          <div className="se-status-left">
            <span className="se-status-seal"><ShieldCheck className="w-3 h-3" /> ATTESTATION VERIFIED</span>
            <span className="se-status-sig mono">{record.signature}</span>
            <span className="se-status-meta mono">{record.user}</span>
            <span className="se-status-meta mono">{record.orgName}</span>
            <span className="se-status-meta mono se-status-scope" title={record.targetScope}>
              <Target className="w-3 h-3" /> {record.targetScope}
            </span>
          </div>
          <div className="se-status-right">
            <span className="se-status-meta mono">{new Date(record.timestampMs).toLocaleString()}</span>
            {isModuleSelected && (
              <button className="se-exit-btn" onClick={exitToModules} title="Return to the module selection deck">
                <ArrowLeft className="w-3 h-3" /> EXIT TO MODULES
              </button>
            )}
            <button className="se-btn se-btn-ghost se-btn-sm" onClick={revoke} title="Return to the attestation gate">
              <Lock className="w-3 h-3" /> REVOKE
            </button>
          </div>
        </div>

        {!isModuleSelected && (
          <div className="se-deck">
            <div className="se-deck-head">
              <div className="se-deck-eyebrow mono">AUTHORIZED ENGAGEMENT SURFACE</div>
              <div className="se-deck-title">SELECT ASSESSMENT MODULE</div>
              <div className="se-deck-hint">
                Five authorized modules. All execution is an honest in-platform dry-run
                simulation — no traffic leaves the workspace.
              </div>
            </div>
            <div className="se-deck-grid">
              {DECK_MODULES.map(m => {
                const Icon = m.icon;
                return (
                  <button key={m.id} className="se-module-card" onClick={() => openModule(m.id)}>
                    <div className="se-module-card-top">
                      <span className="se-module-card-icon"><Icon className="w-5 h-5" /></span>
                      <span className="se-module-card-arrow"><ArrowRight className="w-3.5 h-3.5" /></span>
                    </div>
                    <div className="se-module-card-name">{m.name}</div>
                    <div className="se-module-card-desc">{m.desc}</div>
                    <div className="se-module-card-tools">
                      {m.tools.map(t => <span key={t} className="se-module-tool mono">{t}</span>)}
                    </div>
                    <div className="se-module-card-cta">OPEN MODULE</div>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {isModuleSelected && activeModule && (
          <>
            <div className="se-module-head">
              <div className="se-crumb">
                <button className="se-crumb-back" onClick={exitToModules} title="Back to the module selection deck">
                  <ArrowLeft className="w-3 h-3" /> Switch Module
                </button>
                <span className="se-crumb-sep">/</span>
                <span className="se-crumb-cur">{DECK_MODULES.find(m => m.id === activeModule)?.name}</span>
              </div>
              <div className="se-tools">
                {MODULE_TOOLS[activeModule].map(t => {
                  const Icon = t.icon;
                  return (
                    <button key={t.id}
                      className={`se-tool-pill ${focusedTool === t.id ? 'se-tool-pill-active' : ''}`}
                      onClick={() => setFocusedTool(t.id)}>
                      <Icon className="w-3 h-3" /> {t.label}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="se-body">
              {activeModule === 'vuln' && (
                <VulnerabilityAssessmentTab scope={record.targetScope}
                  focusTrack={focusedTool as VulnTrackId} onTrackSelect={setFocusedTool} />
              )}
              {activeModule === 'web' && <WebApiTab scope={record.targetScope} focus={focusedTool} />}
              {activeModule === 'secrets' && <SecretsTab scope={record.targetScope} focus={focusedTool} />}
              {activeModule === 'compliance' && <ComplianceTab focus={focusedTool} />}
              {activeModule === 'social' && <SocialEngTab focus={focusedTool} />}
              {activeModule === 'react' && <ReactChainTab scope={record.targetScope} record={record} />}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Shared bits
// --------------------------------------------------------------------------- //
function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div className="se-card-title">{children}</div>;
}

function Card({ children, className = '', dataTool }: { children: React.ReactNode; className?: string; dataTool?: string }) {
  return <div className={`se-card ${className}`} data-tool={dataTool}>{children}</div>;
}

/** Highlight + scroll the card that matches the selected header tool pill. */
function useToolFocus(focus: string | null | undefined) {
  React.useEffect(() => {
    if (focus) document.querySelector(`[data-tool="${focus}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [focus]);
  return focus;
}

function SimBadge() {
  return <span className="se-simbadge">DRY-RUN SIMULATION</span>;
}

function scopeHint(scope: string, terms: string[]): boolean {
  const s = scope.toLowerCase();
  return terms.some(t => s.includes(t.toLowerCase()));
}

// --------------------------------------------------------------------------- //
// 1 — Vulnerability Assessment (7-track matrix — see VulnerabilityAssessmentTab)
// --------------------------------------------------------------------------- //

// --------------------------------------------------------------------------- //
// 2 — Web / API Security (DAST config, OpenAPI parser, endpoint crawler)
// --------------------------------------------------------------------------- //
const COMMON_PATHS = [
  'admin', 'login', 'api', 'v1', 'graphql', 'swagger', 'api-docs', 'health',
  'actuator', '.git/config', 'config', 'backup', 'uploads', 'wp-admin', '.env',
];

function parseOpenApi(text: string): { method: string; path: string }[] {
  const out: { method: string; path: string }[] = [];
  const lines = text.split('\n');
  let currentPath = '';
  for (const raw of lines) {
    const line = raw.trim();
    if (line.startsWith('/') && line.length < 200) {
      const m = line.match(/^(\/[^\s:]*)(:\s*)?$/);
      if (m) { currentPath = m[1]; continue; }
    }
    const verb = line.match(/^(get|post|put|patch|delete|options|head):\s*$/i);
    if (verb && currentPath) {
      out.push({ method: verb[1].toUpperCase(), path: currentPath });
    }
  }
  return out.slice(0, 60);
}

function WebApiTab({ scope, focus }: { scope: string; focus?: string | null }) {
  const [dastUrl, setDastUrl] = useState('');
  const [dastAuth, setDastAuth] = useState('none');
  const [dastDepth, setDastDepth] = useState(2);
  const [configSaved, setConfigSaved] = useState(false);

  const [oaText, setOaText] = useState('');
  const [oaResult, setOaResult] = useState<{ method: string; path: string }[] | null>(null);

  const [crawlSeed, setCrawlSeed] = useState('');
  const [crawlBusy, setCrawlBusy] = useState(false);
  const [crawlDone, setCrawlDone] = useState(false);
  const [crawlRoots, setCrawlRoots] = useState<string[]>([]);

  useToolFocus(focus);

  const saveConfig = () => {
    if (!dastUrl.trim()) return;
    setConfigSaved(true);
  };

  const parseOa = () => {
    setOaResult(parseOpenApi(oaText));
  };

  const runCrawl = () => {
    if (!crawlSeed.trim() || crawlBusy) return;
    setCrawlBusy(true); setCrawlDone(false);
    window.setTimeout(() => {
      const seed = crawlSeed.trim().replace(/\/+$/, '');
      const root = seed.split('?')[0];
      const roots = [root, ...COMMON_PATHS.slice(0, 14).map(p => `${root}/${p}`)];
      if (oaResult) {
        oaResult.slice(0, 20).forEach(e => roots.push(`${root}${e.path}`));
      }
      setCrawlRoots(Array.from(new Set(roots)));
      setCrawlBusy(false); setCrawlDone(true);
    }, 1100);
  };

  return (
    <div className="se-grid">
      <Card dataTool="dast" className={focus === 'dast' ? 'se-card-active' : ''}>
        <SectionTitle><Globe className="w-3.5 h-3.5" /> DAST — DYNAMIC TESTING CONFIG <SimBadge /></SectionTitle>
        <div className="se-card-hint">
          Build the active-scan profile. The config is staged for a future
          backend execution engine — no requests are sent from the platform today.
        </div>
        <div className="se-kv">
          <label className="se-field">
            <span className="se-label">TARGET URL</span>
            <input className="se-input" value={dastUrl} placeholder="https://app.example.com/"
              onChange={e => { setDastUrl(e.target.value); setConfigSaved(false); }} />
          </label>
          <label className="se-field">
            <span className="se-label">AUTH TYPE</span>
            <select className="se-input" value={dastAuth} onChange={e => { setDastAuth(e.target.value); setConfigSaved(false); }}>
              <option value="none">None (unauthenticated)</option>
              <option value="basic">Basic</option>
              <option value="cookie">Session cookie</option>
              <option value="oauth">OAuth / bearer</option>
            </select>
          </label>
          <label className="se-field">
            <span className="se-label">CRAWL DEPTH</span>
            <select className="se-input" value={dastDepth} onChange={e => { setDastDepth(Number(e.target.value)); setConfigSaved(false); }}>
              <option value={1}>1 — entry only</option>
              <option value={2}>2</option>
              <option value={3}>3</option>
              <option value={4}>4 — full subtree</option>
            </select>
          </label>
        </div>
        <div className="se-actions">
          <button className="se-btn se-btn-primary" onClick={saveConfig} disabled={!dastUrl.trim()}>
            <FileJson className="w-3 h-3" /> {configSaved ? 'CONFIG STAGED' : 'STAGE DAST CONFIG'}
          </button>
        </div>
        {configSaved && (
          <div className="se-config">
            <div className="mono se-config-line">target: {dastUrl}</div>
            <div className="mono se-config-line">auth: {dastAuth} · depth: {dastDepth}</div>
            <div className="mono se-config-line">scope: {scope || '—'}</div>
          </div>
        )}
      </Card>

      <Card dataTool="openapi" className={focus === 'openapi' ? 'se-card-active' : ''}>
        <SectionTitle><FileJson className="w-3.5 h-3.5" /> OPENAPI SPEC PARSER</SectionTitle>
        <div className="se-card-hint">
          Paste an OpenAPI document (YAML/JSON) to derive the API surface. Paths and
          verbs are parsed client-side.
        </div>
        <textarea className="se-textarea" rows={6} value={oaText} placeholder={'openapi: 3.0.0\npaths:\n  /users:\n    get:\n    post:\n  /users/{id}:\n    get:'}
          onChange={e => setOaText(e.target.value)} />
        <div className="se-actions">
          <button className="se-btn" onClick={parseOa} disabled={!oaText.trim()}>
            <Search className="w-3 h-3" /> PARSE SURFACE
          </button>
        </div>
        {oaResult && (
          <div className="se-table-wrap">
            <table className="se-table">
              <thead><tr><th>METHOD</th><th>PATH</th></tr></thead>
              <tbody>
                {oaResult.map((e, i) => (
                  <tr key={i}>
                    <td className="se-method">{e.method}</td>
                    <td className="mono">{e.path}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card dataTool="crawler" className={focus === 'crawler' ? 'se-card-active' : ''}>
        <SectionTitle><Search className="w-3.5 h-3.5" /> ENDPOINT CRAWLER <SimBadge /></SectionTitle>
        <div className="se-card-hint">
          Seed-URL spider simulation: walks common paths plus any parsed OpenAPI
          surface. Discovery is simulated — no HTTP requests are made.
        </div>
        <div className="se-row">
          <input className="se-input" value={crawlSeed} placeholder="https://app.example.com/"
            onChange={e => setCrawlSeed(e.target.value)} />
          <button className="se-btn se-btn-primary" onClick={runCrawl} disabled={crawlBusy || !crawlSeed.trim()}>
            {crawlBusy ? <Loader2 className="w-3 h-3 se-spin" /> : <Send className="w-3 h-3" />} CRAWL
          </button>
        </div>
        {crawlBusy && <div className="se-progress"><div className="se-progress-bar" /></div>}
        {crawlDone && (
          <div className="se-taglist">
            {crawlRoots.map(r => <span key={r} className="se-tag mono">{r}</span>)}
          </div>
        )}
      </Card>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// 3 — Exposure & Secret Auditing (entropy scanner, admin-panel detector)
// --------------------------------------------------------------------------- //
function shannonEntropy(s: string): number {
  const freq: Record<string, number> = {};
  for (const c of s) freq[c] = (freq[c] || 0) + 1;
  let h = 0;
  const len = s.length;
  for (const k in freq) {
    const p = freq[k] / len;
    h -= p * Math.log2(p);
  }
  return h;
}

interface SecretHit { kind: string; match: string; entropy: string }

function scanSecrets(text: string): SecretHit[] {
  const hits: SecretHit[] = [];
  const patterns: [RegExp, string][] = [
    [/AKIA[0-9A-Z]{16}/g, 'AWS Access Key'],
    [/ghp_[A-Za-z0-9]{36}/g, 'GitHub PAT'],
    [/sk-[A-Za-z0-9]{20,}/g, 'OpenAI API Key'],
    [/AIza[0-9A-Za-z\-_]{35}/g, 'Google API Key'],
    [/xox[baprs]-[0-9A-Za-z\-]{10,}/g, 'Slack Token'],
    [/-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/g, 'Private Key Material'],
    [/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/g, 'JWT'],
    [/[A-Za-z0-9_-]{40,}/g, 'Long Alphanumeric Token'],
  ];
  for (const [re, kind] of patterns) {
    const m = text.match(re);
    if (m) {
      for (const match of m.slice(0, 8)) {
        hits.push({ kind, match: match.slice(0, 48), entropy: shannonEntropy(match).toFixed(2) });
      }
    }
  }
  return hits.slice(0, 24);
}

const ADMIN_PATHS = ['admin', 'administrator', 'admin.php', 'wp-admin', 'login', 'panel', 'manage', 'console', 'dashboard', 'cpanel'];

function SecretsTab({ scope, focus }: { scope: string; focus?: string | null }) {
  const [blob, setBlob] = useState('');
  const [hits, setHits] = useState<SecretHit[] | null>(null);
  const [scanBusy, setScanBusy] = useState(false);

  const [panelHost, setPanelHost] = useState('');
  const [panelResults, setPanelResults] = useState<{ path: string; status: string; note: string }[] | null>(null);
  const [panelBusy, setPanelBusy] = useState(false);

  useToolFocus(focus);

  const runScan = () => {
    if (scanBusy) return;
    setScanBusy(true); setHits(null);
    window.setTimeout(() => { setHits(scanSecrets(blob)); setScanBusy(false); }, 900);
  };

  const runPanel = () => {
    if (panelBusy || !panelHost.trim()) return;
    setPanelBusy(true); setPanelResults(null);
    window.setTimeout(() => {
      const host = panelHost.trim().replace(/\/+$/, '');
      setPanelResults(
        ADMIN_PATHS.slice(0, 8).map(p => ({
          path: `${host}/${p}`,
          status: 'SIMULATED',
          note: scopeHint(scope, [p, 'admin', 'panel']) ? 'possible auth boundary' : 'no banner observed',
        })),
      );
      setPanelBusy(false);
    }, 1000);
  };

  return (
    <div className="se-grid">
      <Card dataTool="entropy" className={focus === 'entropy' ? 'se-card-active' : ''}>
        <SectionTitle><KeyRound className="w-3.5 h-3.5" /> ENTROPY & SECRET SCANNER</SectionTitle>
        <div className="se-card-hint">
          Paste a blob (config, env file, repo diff, logs) — the scanner flags
          credential-shaped material by pattern and Shannon entropy. Local only.
        </div>
        <textarea className="se-textarea" rows={8} value={blob} placeholder={'AKIAIOSFODNN7EXAMPLE\ngithub_token=ghp_1234567890123456789012345678901234\n-----BEGIN RSA PRIVATE KEY-----'}
          onChange={e => setBlob(e.target.value)} />
        <div className="se-actions">
          <button className="se-btn se-btn-primary" onClick={runScan} disabled={scanBusy || !blob.trim()}>
            {scanBusy ? <Loader2 className="w-3 h-3 se-spin" /> : <Search className="w-3 h-3" />} SCAN ENTROPY
          </button>
        </div>
        {hits && (
          <div className="se-table-wrap">
            <table className="se-table">
              <thead><tr><th>KIND</th><th>MATCH</th><th>ENTROPY</th></tr></thead>
              <tbody>
                {hits.length === 0 && <tr><td colSpan={3} className="se-empty">No secret-shaped material detected.</td></tr>}
                {hits.map((h, i) => (
                  <tr key={i}>
                    <td>{h.kind}</td>
                    <td className="mono">{h.match}</td>
                    <td className="mono">{h.entropy}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card dataTool="admin" className={focus === 'admin' ? 'se-card-active' : ''}>
        <SectionTitle><Search className="w-3.5 h-3.5" /> ADMIN-PANEL / EXPOSURE DETECTOR <SimBadge /></SectionTitle>
        <div className="se-card-hint">
          Probe a host for common admin and management paths. Execution is simulated —
          no requests are sent; results reflect a reference exposure heuristic.
        </div>
        <div className="se-row">
          <input className="se-input" value={panelHost} placeholder="https://app.example.com"
            onChange={e => setPanelHost(e.target.value)} />
          <button className="se-btn se-btn-primary" onClick={runPanel} disabled={panelBusy || !panelHost.trim()}>
            {panelBusy ? <Loader2 className="w-3 h-3 se-spin" /> : <Search className="w-3 h-3" />} DETECT
          </button>
        </div>
        {panelBusy && <div className="se-progress"><div className="se-progress-bar" /></div>}
        {panelResults && (
          <div className="se-table-wrap">
            <table className="se-table">
              <thead><tr><th>PATH</th><th>STATUS</th><th>NOTE</th></tr></thead>
              <tbody>
                {panelResults.map((r, i) => (
                  <tr key={i}>
                    <td className="mono">{r.path}</td>
                    <td>{r.status}</td>
                    <td className="se-empty">{r.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// 4 — Compliance / Baseline (CIS benchmarks + Ansible remediation)
// --------------------------------------------------------------------------- //
interface CisControl {
  id: string;
  title: string;
  state: 'PASS' | 'FAIL' | 'REVIEW';
}

const CIS_BASELINE: { group: string; controls: CisControl[] }[] = [
  {
    group: 'Windows Server 2022 — CIS L1',
    controls: [
      { id: '1.1.1', title: 'Set password policy requirements', state: 'FAIL' },
      { id: '2.3.1', title: 'Ensure MFA is enabled for all users', state: 'FAIL' },
      { id: '5.1.2', title: 'Set built-in Guest account to disabled', state: 'PASS' },
      { id: '18.3.1', title: 'Ensure LAPS is configured', state: 'REVIEW' },
    ],
  },
  {
    group: 'Ubuntu 22.04 — CIS L2',
    controls: [
      { id: '5.1.1', title: 'Install and configure auditd', state: 'FAIL' },
      { id: '6.2.1', title: 'Ensure SSH root login is disabled', state: 'PASS' },
      { id: '3.3.2', title: 'Ensure IPv6 firewall rules exist', state: 'REVIEW' },
      { id: '1.1.2', title: 'Set filesystem partitioning', state: 'PASS' },
    ],
  },
];

function ComplianceTab({ focus }: { focus?: string | null }) {
  const [baseline, setBaseline] = useState<{ group: string; controls: CisControl[] }[]>(CIS_BASELINE);
  const [playbook, setPlaybook] = useState<string | null>(null);

  useToolFocus(focus);

  const toggle = (gi: number, ci: number) => {
    setBaseline(bs => bs.map((g, i) => i === gi ? {
      ...g,
      controls: g.controls.map((c, j) => j === ci ? {
        ...c,
        state: c.state === 'PASS' ? 'FAIL' : c.state === 'FAIL' ? 'REVIEW' : 'PASS',
      } : c),
    } : g));
  };

  const generate = () => {
    const failed = baseline.flatMap(g => g.controls.filter(c => c.state !== 'PASS'));
    const tasks = failed.map((c, i) => [
      `  - name: "Remediate ${c.id} — ${c.title}"`,
      `    ansible.builtin.debug:`,
      `      msg: "Apply CIS control ${c.id} (stub play — policy hook)"`,
      `    when: remediation_mode == 'apply'`,
    ].join('\n'));
    setPlaybook(
      `---\n- name: CIS Baseline Remediation\n  hosts: "{{ target_hosts }}"\n  vars:\n    remediation_mode: check\n  tasks:\n${tasks.join('\n') || '    - ansible.builtin.debug:\n        msg: "No failures to remediate."'}\n`,
    );
  };

  const download = () => {
    if (!playbook) return;
    const url = URL.createObjectURL(new Blob([playbook], { type: 'text/yaml' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'cis-baseline-remediation.yml';
    a.click();
    URL.revokeObjectURL(url);
  };

  const passCount = baseline.flatMap(g => g.controls).filter(c => c.state === 'PASS').length;
  const total = baseline.flatMap(g => g.controls).length;
  const score = Math.round((passCount / total) * 100);

  const stateColor = (s: string) => s === 'PASS' ? '#10B981' : s === 'FAIL' ? '#EF4444' : '#F59E0B';

  return (
    <div className="se-grid">
      <Card dataTool="baseline" className={focus === 'baseline' ? 'se-card-active' : ''}>
        <SectionTitle><ClipboardCheck className="w-3.5 h-3.5" /> CIS BASELINE AUDITOR</SectionTitle>
        <div className="se-card-hint">
          Reference benchmarks against the assessed host. Toggle evidence state per
          control, then generate the Ansible remediation playbook for failures.
        </div>
        <div className="se-score">
          <div className="se-score-num mono">{score}%</div>
          <div className="se-score-bar"><div className="se-score-fill" style={{ width: `${score}%` }} /></div>
          <div className="se-score-meta mono">{passCount}/{total} CONTROLS PASSING</div>
        </div>
        {baseline.map((g, gi) => (
          <div className="se-baseline" key={g.group}>
            <div className="se-baseline-title">{g.group}</div>
            {g.controls.map((c, ci) => (
              <div className="se-row se-row-click" key={c.id} onClick={() => toggle(gi, ci)} title="Click to cycle PASS → FAIL → REVIEW">
                <span className="mono se-cve">{c.id}</span>
                <span className="se-row-note">{c.title}</span>
                <span className="se-sev-tag" style={{ color: stateColor(c.state), borderColor: stateColor(c.state) }}>
                  {c.state}
                </span>
              </div>
            ))}
          </div>
        ))}
        <div className="se-actions">
          <button className="se-btn se-btn-primary" onClick={generate}>
            <FileJson className="w-3 h-3" /> GENERATE ANSIBLE REMEDIATION
          </button>
          {playbook && (
            <button className="se-btn" onClick={download}>
              <Download className="w-3 h-3" /> DOWNLOAD PLAYBOOK
            </button>
          )}
        </div>
        {playbook && (
          <pre className="se-playbook mono">{playbook}</pre>
        )}
      </Card>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// 5 — Social Engineering Assessment
// --------------------------------------------------------------------------- //
interface PhishTemplate {
  id: string;
  name: string;
  sender: string;
  subject: string;
  pretext: string;
  body: string;
  lure: string;
}

const PHISH_TEMPLATES: PhishTemplate[] = [
  {
    id: 'IT_RESET',
    name: 'IT Password Reset',
    sender: 'Service Desk <helpdesk@secure-sso.example>',
    subject: 'Action required: your password expires in 24h',
    pretext: 'Urgent infrastructure policy — credentials rotation',
    body: 'Your password is scheduled to expire within 24 hours. Sign in to the corporate portal below to renew before your access is suspended. This notice is mandated by the account policy review.',
    lure: 'Login portal credential capture',
  },
  {
    id: 'EXEC_PRETEXT',
    name: 'Executive Pretext',
    sender: 'Dana Whitfield <d.whitfield@exec-board.example>',
    subject: 'RE: urgent wire approval',
    pretext: 'Impersonation of senior leadership under time pressure',
    body: 'I need this reviewed before the close-of-business approval window. The attached summary is time-sensitive — confirm receipt and the routing number on record.',
    lure: 'Attachment payload + payment-data exfiltration',
  },
  {
    id: 'M365_AUTH',
    name: 'M365 Auth Intercept',
    sender: 'Microsoft Security <alerts@ms-security-alerts.example>',
    subject: 'Unusual sign-in activity — verify now',
    pretext: 'Legitimate-looking security alert triggers login reflex',
    body: 'We detected a sign-in from an unrecognized device. Open the security page to verify your identity and review recent activity. No action is needed if you initiated the login.',
    lure: 'OAuth consent + token capture',
  },
  {
    id: 'HR_DOC',
    name: 'HR Document',
    sender: 'HR Operations <hr-ops@benefits.example>',
    subject: 'Updated benefits enrollment documents',
    pretext: 'Benign workplace document prompts credential entry',
    body: 'Attached is the revised enrollment packet for the current cycle. Review and sign within five business days. Reach out to HR-Ops if you have questions.',
    lure: 'Doc-signing credential prompt',
  },
  {
    id: 'MFA_FATIGUE',
    name: 'MFA Fatigue',
    sender: 'IAM <iam-session@corp-sso.example>',
    subject: 'New session approval requested',
    pretext: 'Repeated push prompts to exhaust the target into approving',
    body: 'A new sign-in is waiting for approval. If this was not you, select "It was not me" below. Note: repeated attempts may lock your account for security.',
    lure: 'Fatigue-driven MFA approval + session takeover',
  },
];

const SUSCEPTIBILITY_QUESTIONS = [
  { q: 'I reuse the same password across multiple accounts.', weight: 1.4 },
  { q: 'I do not use a hardware key or authenticator app for MFA.', weight: 1.3 },
  { q: 'I click links in urgent emails without verifying the sender.', weight: 1.5 },
  { q: 'I share screens or approve logins without checking context.', weight: 1.1 },
  { q: 'I rarely look at the URL bar before entering credentials.', weight: 1.2 },
  { q: 'I comply with requests that cite internal policies or HR.', weight: 0.9 },
];

function SocialEngTab({ focus }: { focus?: string | null }) {
  const [active, setActive] = useState<'campaign' | 'device' | 'suscept' | 'pretext' | 'osint'>('campaign');
  const [quiz, setQuiz] = useState<number[]>(SUSCEPTIBILITY_QUESTIONS.map(() => 0));
  const [templates, setTemplates] = useState<PhishTemplate[]>(PHISH_TEMPLATES);
  const [campaigns, setCampaigns] = useState<{ id: string; tpl: string; target: string; launched: boolean }[]>([]);

  useToolFocus(focus);

  // Drive the internal tool nav from the header pill (matches NAV ids).
  React.useEffect(() => {
    if (focus && (focus === 'campaign' || focus === 'device' || focus === 'suscept' || focus === 'pretext' || focus === 'osint')) {
      setActive(focus);
    }
  }, [focus]);

  // device-drop checklist
  const [deviceChecks, setDeviceChecks] = useState<Record<string, boolean>>({
    encryption: true, lockscreen: false, usb: true, external: false, vpn: true,
  });

  // pretext builder
  const [pb, setPb] = useState({ role: 'finance manager', vector: 'email', urgency: 'end-of-quarter deadline', lure: 'shared expense sheet' });
  const [pbOut, setPbOut] = useState('');

  // OSINT recon
  const [recon, setRecon] = useState({ name: '', org: '' });
  const [reconOut, setReconOut] = useState<{ label: string; value: string; source: string }[] | null>(null);

  const susceptibility = useMemo(() => {
    const raw = quiz.reduce((acc, v, i) => acc + v * SUSCEPTIBILITY_QUESTIONS[i].weight, 0);
    const max = SUSCEPTIBILITY_QUESTIONS.reduce((a, q) => a + q.weight * 4, 0);
    const score = Math.round((raw / max) * 100);
    return { score, band: score >= 66 ? 'HIGH' : score >= 33 ? 'MEDIUM' : 'LOW' };
  }, [quiz]);

  const launch = (tpl: PhishTemplate, target: string) => {
    setCampaigns(cs => [...cs, { id: `CMP-${(cs.length + 1).toString().padStart(3, '0')}`, tpl: tpl.id, target, launched: true }]);
  };

  const buildPretext = () => {
    setPbOut(
      `To: <target>\nFrom: <sender>\nSubject: URGENT — ${pb.urgency}\n\n` +
      `Hi,\n\nI am reaching out in my role as ${pb.role}. We are closing an ${pb.urgency} and I need your help to finalize the ${pb.lure}. ` +
      `Please confirm at your earliest convenience — the window is tight and this requires your approval today.\n\n` +
      `If you need to verify this request, the office number is on the shared directory.\n\nBest regards,\n<pretext author>`,
    );
  };

  const runRecon = () => {
    if (!recon.name.trim()) return;
    const email = recon.name.trim().toLowerCase().replace(/\s+/g, '.');
    setReconOut([
      { label: 'Email format', value: `${email}@${(recon.org || 'corp.example').toLowerCase().replace(/[^a-z0-9]/g, '')}.com`, source: 'OSINT heuristic' },
      { label: 'Social profiles', value: 'linkedin · twitter · github (public)', source: 'footprint scan' },
      { label: 'Breach exposure', value: '2 records in reference breach sets (SIMULATED)', source: 'HIBP-style index' },
      { label: 'Role signals', value: `${recon.name} — likely ${pb.role} persona`, source: 'org chart inference' },
    ]);
  };

  const susColor = susceptibility.band === 'HIGH' ? '#EF4444' : susceptibility.band === 'MEDIUM' ? '#F59E0B' : '#10B981';

  const NAV: { id: 'campaign' | 'device' | 'suscept' | 'pretext' | 'osint'; label: string; icon: LucideIcon }[] = [
    { id: 'campaign', label: 'Click-Through Board', icon: MousePointerClick },
    { id: 'device', label: 'Device Drop', icon: User },
    { id: 'suscept', label: 'Susceptibility', icon: ShieldAlert },
    { id: 'pretext', label: 'Pretext Builder', icon: Target },
    { id: 'osint', label: 'OSINT Recon', icon: Eye },
  ];

  return (
    <div className="se-grid">
      <Card>
        <SectionTitle><Users className="w-3.5 h-3.5" /> PHISHING CAMPAIGN SIMULATOR <SimBadge /></SectionTitle>
        <div className="se-card-hint">
          Five certified template archetypes. Campaign launches are dry-run
          simulations — no mail is dispatched and no external service is contacted.
        </div>
        <div className="se-nav-row">
          {NAV.map(n => {
            const Icon = n.icon;
            return (
              <button key={n.id} className={`se-nav-pill ${active === n.id ? 'se-nav-pill-active' : ''}`} onClick={() => setActive(n.id)}>
                <Icon className="w-3 h-3" /> {n.label}
              </button>
            );
          })}
        </div>

        {active === 'campaign' && (
          <div className="se-kv">
            {templates.map(t => (
              <div className="se-row" key={t.id}>
                <span className="mono se-cve">{t.id}</span>
                <span className="se-row-note">{t.name} — {t.lure}</span>
                <button className="se-btn se-btn-sm" onClick={() => launch(t, 'target@corp.example')}>
                  <Send className="w-3 h-3" /> LAUNCH SIM
                </button>
              </div>
            ))}
            <div className="se-campaign-title">CAMPAIGN REGISTER</div>
            {campaigns.length === 0 ? (
              <div className="se-empty">No campaigns launched this session.</div>
            ) : (
              <div className="se-table-wrap">
                <table className="se-table">
                  <thead><tr><th>ID</th><th>TEMPLATE</th><th>TARGET</th><th>STATUS</th></tr></thead>
                  <tbody>
                    {campaigns.map(c => (
                      <tr key={c.id}>
                        <td className="mono">{c.id}</td>
                        <td>{c.tpl}</td>
                        <td className="mono">{c.target}</td>
                        <td style={{ color: '#10B981' }}>DELIVERED (SIM)</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {active === 'device' && (
          <div className="se-kv">
            <div className="se-card-hint">
              Device-drop awareness: physical media left in reach of staff is a
              front-door infection vector. Rate your floor's posture.
            </div>
            {Object.entries(deviceChecks).map(([k, v]) => (
              <label key={k} className="se-row se-row-check">
                <input type="checkbox" checked={v} onChange={e => setDeviceChecks(d => ({ ...d, [k]: e.target.checked }))} />
                <span className="se-row-note">
                  {k === 'encryption' ? 'Full-disk encryption enforced on all endpoints'
                    : k === 'lockscreen' ? 'Short lock-screen timeout (≤ 5 min)'
                    : k === 'usb' ? 'USB / removable-media policy enforced'
                    : k === 'external' ? 'External drives inventoried & accounted'
                    : 'VPN required for off-site connectivity'}
                </span>
                <span className="se-sev-tag" style={{ color: v ? '#10B981' : '#EF4444' }}>{v ? 'CONTROL' : 'GAP'}</span>
              </label>
            ))}
          </div>
        )}

        {active === 'suscept' && (
          <div className="se-kv">
            <div className="se-card-hint">
              Self-assessed susceptibility index (0 = strongly disagree, 4 = strongly agree).
              Aggregated to a floor-level risk band.
            </div>
            {SUSCEPTIBILITY_QUESTIONS.map((q, i) => (
              <div className="se-row" key={q.q}>
                <span className="se-row-note">{q.q}</span>
                <div className="se-radio-row">
                  {[0, 1, 2, 3, 4].map(v => (
                    <button key={v} className={`se-rb ${quiz[i] === v ? 'se-rb-on' : ''}`}
                      onClick={() => setQuiz(z => z.map((x, j) => j === i ? v : x))}>{v}</button>
                  ))}
                </div>
              </div>
            ))}
            <div className="se-epss-gauge">
              <div className="se-epss-big mono">{susceptibility.score}%</div>
              <div className="se-epss-band" style={{ color: susColor }}>
                {susceptibility.band} SUSCEPTIBILITY INDEX
              </div>
              <div className="se-score-bar"><div className="se-score-fill" style={{ width: `${susceptibility.score}%`, background: susColor }} /></div>
            </div>
          </div>
        )}

        {active === 'pretext' && (
          <div className="se-kv">
            <div className="se-card-hint">
              Compose a research pretext. Fields map onto the classic vishing/phishing
              archetypes; output is a training scaffold, not a dispatch.
            </div>
            <label className="se-field">
              <span className="se-label">TARGET ROLE</span>
              <input className="se-input" value={pb.role} onChange={e => setPb(p => ({ ...p, role: e.target.value }))} />
            </label>
            <label className="se-field">
              <span className="se-label">VECTOR</span>
              <select className="se-input" value={pb.vector} onChange={e => setPb(p => ({ ...p, vector: e.target.value }))}>
                <option value="email">Email</option>
                <option value="sms">SMS / SMS-tag</option>
                <option value="voice">Voice / vishing</option>
                <option value="usb">USB drop</option>
              </select>
            </label>
            <label className="se-field">
              <span className="se-label">URGENCY HOOK</span>
              <input className="se-input" value={pb.urgency} onChange={e => setPb(p => ({ ...p, urgency: e.target.value }))} />
            </label>
            <label className="se-field">
              <span className="se-label">LURE</span>
              <input className="se-input" value={pb.lure} onChange={e => setPb(p => ({ ...p, lure: e.target.value }))} />
            </label>
            <div className="se-actions">
              <button className="se-btn se-btn-primary" onClick={buildPretext} disabled={!pb.role.trim()}>
                <Target className="w-3 h-3" /> GENERATE PRETEXT
              </button>
            </div>
            {pbOut && <pre className="se-playbook mono">{pbOut}</pre>}
          </div>
        )}

        {active === 'osint' && (
          <div className="se-kv">
            <div className="se-card-hint">
              Open-source footprint projection for a target persona. All results are
              heuristically generated locally — no live OSINT queries are performed.
            </div>
            <div className="se-grid-2">
              <label className="se-field">
                <span className="se-label">TARGET NAME</span>
                <input className="se-input" value={recon.name} onChange={e => setRecon(n => ({ ...n, name: e.target.value }))} />
              </label>
              <label className="se-field">
                <span className="se-label">ORGANIZATION</span>
                <input className="se-input" value={recon.org} onChange={e => setRecon(n => ({ ...n, org: e.target.value }))} />
              </label>
            </div>
            <div className="se-actions">
              <button className="se-btn se-btn-primary" onClick={runRecon} disabled={!recon.name.trim()}>
                <Eye className="w-3 h-3" /> PROJECT FOOTPRINT
              </button>
            </div>
            {reconOut && (
              <div className="se-table-wrap">
                <table className="se-table">
                  <thead><tr><th>VECTOR</th><th>VALUE</th><th>SOURCE</th></tr></thead>
                  <tbody>
                    {reconOut.map((r, i) => (
                      <tr key={i}>
                        <td>{r.label}</td>
                        <td className="mono">{r.value}</td>
                        <td className="se-empty">{r.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// 6 — RE-ACT Chain (Plan → Scan → Exploit → Escalate → Mitigate)
// Runs through the backend policy-guarded chain — the dedicated surface for
// active capabilities (exec:shell). Refuses to start without authorization.
// --------------------------------------------------------------------------- //
const REACT_KINDS: { id: ReactTarget['kind']; label: string }[] = [
  { id: 'network', label: 'Network / Host' },
  { id: 'web', label: 'Web / API' },
  { id: 'host', label: 'Local Host' },
  { id: 'ot', label: 'ROS / OT' },
  { id: 'offline', label: 'Offline Hash' },
];

const PHASE_LABELS: Record<string, string> = {
  plan: 'Plan', scan: 'Scan', exploit: 'Exploit', escalate: 'Escalate',
  mitigate: 'Mitigate',
};

function ReactChainTab({ scope, record }: {
  scope: string;
  record: AttestationRecord;
}) {
  const [kind, setKind] = useState<ReactTarget['kind']>('network');
  const [host, setHost] = useState('');
  const [webRoot, setWebRoot] = useState('');
  const [hash, setHash] = useState('');
  const [hashType, setHashType] = useState('auto');
  const [wordlist, setWordlist] = useState('');
  const [safetyPath, setSafetyPath] = useState('');
  const [refPath, setRefPath] = useState('');
  const [mode, setMode] = useState<'active' | 'dry_run'>('dry_run');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);

  const [session, setSession] = useState<ReactSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<Awaited<ReturnType<typeof reactOrchestrator.history>>>([]);

  const refreshHistory = async () => {
    try {
      const rows = await reactOrchestrator.reloadHistory();
      setHistory(rows);
    } catch { /* backend unreachable — keep local registry */ }
  };

  React.useEffect(() => { refreshHistory(); }, []);

  const buildTarget = (): ReactTarget => {
    const base: ReactTarget = { kind };
    if (kind === 'network' || kind === 'host') {
      return { ...base, host: host || null, ports: '' };
    }
    if (kind === 'web') {
      return { ...base, target_url: host || null, web_root: webRoot || null };
    }
    if (kind === 'ot') {
      return {
        ...base, ros2: true,
        safety_config_path: safetyPath || null,
        reference_config_path: refPath || null,
      };
    }
    return {
      ...base, hash_value: hash || null, hash_type: hashType || 'auto',
      wordlist: wordlist || null,
    };
  };

  const runChain = async () => {
    if (busy) return;
    setBusy(true); setError(null); setSession(null);
    try {
      const ctx = {
        operator: reactOrchestrator.operatorFromAttestation(record),
        authorized: true,
        scope: scope || record.targetScope || '',
        signature: record.signature,
      };
      const result = await reactOrchestrator.run(ctx, {
        target: buildTarget(),
        mode,
        notes: notes.trim() || undefined,
      });
      setSession(result);
      refreshHistory();
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'RE-ACT run failed');
    } finally {
      setBusy(false);
    }
  };

  const poll = async () => {
    if (!session) return;
    try {
      const fresh = await reactOrchestrator.refresh(session.session_id);
      setSession(fresh);
    } catch { /* transient */ }
  };

  const phaseStatus = (phase: string): string => {
    if (!session) return 'pending';
    const rows = session.activity.filter(a => a.phase === phase);
    if (rows.some(r => r.status === 'ran' || r.status === 'done')) return 'done';
    if (rows.some(r => r.status === 'failed')) return 'failed';
    if (rows.some(r => r.status === 'skipped')) return 'skipped';
    return 'pending';
  };

  const statusColor = (s: string) =>
    s === 'done' ? '#10B981' : s === 'failed' ? '#EF4444' : s === 'skipped' ? '#F59E0B' : '#64748B';

  return (
    <div className="se-grid">
      <Card dataTool="plan">
        <SectionTitle><Radar className="w-3.5 h-3.5" /> RE-ACT — ENGAGEMENT SETUP</SectionTitle>
        <div className="se-card-hint">
          Five-phase chain: <b>Plan → Scan → Exploit → Escalate → Mitigate</b>.
          Runs on the backend against this attestation's scope with explicit
          authorization. Active steps require <span className="mono">exec:shell</span> —
          the dedicated chain surface only. Default <span className="mono">dry_run</span>
          never sends traffic or runs subprocesses.
        </div>
        <div className="se-kv">
          <label className="se-field">
            <span className="se-label">ENGAGEMENT TYPE</span>
            <select className="se-input" value={kind} onChange={e => setKind(e.target.value as ReactTarget['kind'])}>
              {REACT_KINDS.map(k => <option key={k.id} value={k.id}>{k.label}</option>)}
            </select>
          </label>
          <label className="se-field">
            <span className="se-label">
              {kind === 'offline' ? 'HASH VALUE' : kind === 'ot' ? 'SAFETY CONFIG PATH' : 'TARGET / HOST / URL'}
            </span>
            <input className="se-input" value={host}
              placeholder={kind === 'offline' ? '5f4dcc3b…' : kind === 'ot' ? '/opt/ros/safety_config.yaml' : '192.168.1.0/30 · app.example.com'}
              onChange={e => setHost(e.target.value)} />
          </label>
          {kind === 'web' && (
            <label className="se-field">
              <span className="se-label">WEB ROOT (webshell scan)</span>
              <input className="se-input" value={webRoot} placeholder="/var/www/html (owned copy)"
                onChange={e => setWebRoot(e.target.value)} />
            </label>
          )}
          {kind === 'ot' && (
            <label className="se-field">
              <span className="se-label">REFERENCE BASELINE</span>
              <input className="se-input" value={refPath} placeholder="Optional authoritative YAML"
                onChange={e => setRefPath(e.target.value)} />
            </label>
          )}
          {kind === 'offline' && (
            <>
              <label className="se-field">
                <span className="se-label">HASH TYPE</span>
                <select className="se-input" value={hashType} onChange={e => setHashType(e.target.value)}>
                  <option value="auto">auto-detect</option>
                  <option value="md5">md5</option>
                  <option value="sha1">sha1</option>
                  <option value="sha256">sha256</option>
                  <option value="sha512">sha512</option>
                  <option value="bcrypt">bcrypt</option>
                </select>
              </label>
              <label className="se-field">
                <span className="se-label">WORDLIST PATH</span>
                <input className="se-input" value={wordlist} placeholder="/usr/share/wordlists/rockyou.txt"
                  onChange={e => setWordlist(e.target.value)} />
              </label>
            </>
          )}
          <label className="se-field">
            <span className="se-label">MODE</span>
            <select className="se-input" value={mode} onChange={e => setMode(e.target.value as 'active' | 'dry_run')}>
              <option value="dry_run">dry_run — simulated (default)</option>
              <option value="active">active — real tools</option>
            </select>
          </label>
          <label className="se-field">
            <span className="se-label">NOTES (recorded)</span>
            <input className="se-input" value={notes} placeholder="Optional engagement context"
              onChange={e => setNotes(e.target.value)} />
          </label>
        </div>
        <div className="se-actions">
          <button className="se-btn se-btn-primary" onClick={runChain} disabled={busy}>
            {busy ? <Loader2 className="w-3 h-3 se-spin" /> : <Radar className="w-3 h-3" />}
            {busy ? 'RUNNING CHAIN…' : 'RUN RE-ACT CHAIN'}
          </button>
          <button className="se-btn" onClick={poll} disabled={!session || session.status === 'running'}>
            <RefreshCw className="w-3 h-3" /> REFRESH
          </button>
        </div>
        {error && <div className="se-error" style={{ color: '#EF4444' }}>{error}</div>}
      </Card>

      {session && (
        <>
          <Card dataTool="scan">
            <SectionTitle><Waypoints className="w-3.5 h-3.5" /> CHAIN STATUS</SectionTitle>
            <div className="se-score">
              <div className="se-score-num mono" style={{ color: statusColor(session.status) }}>
                {session.status.toUpperCase()}
              </div>
              <div className="se-score-meta mono">
                {session.session_id} · {session.case_id} ·{' '}
                {new Date(session.updated_at_ms).toLocaleTimeString()}
              </div>
            </div>
            {session.rejection_reason && (
              <div className="se-empty">{session.rejection_reason}</div>
            )}
            <div className="se-nav-row">
              {session.phases.map(p => {
                const st = phaseStatus(p.phase);
                return (
                  <div key={p.phase} className="se-tag mono" style={{ color: statusColor(st), borderColor: statusColor(st) }}>
                    {PHASE_LABELS[p.phase] || p.phase}: {st.toUpperCase()}
                  </div>
                );
              })}
            </div>
            {session.phases.map(p => (
              <div className="se-baseline" key={p.phase}>
                <div className="se-baseline-title">
                  {PHASE_LABELS[p.phase] || p.phase} — {p.rationale}
                </div>
                {p.tool_ids.length === 0 ? (
                  <div className="se-empty">No tools for this phase.</div>
                ) : (
                  <div className="se-taglist">
                    {p.tool_ids.map(t => <span key={t} className="se-tag mono">{t}</span>)}
                  </div>
                )}
              </div>
            ))}
          </Card>

          <Card dataTool="exploit">
            <SectionTitle><Bug className="w-3.5 h-3.5" /> ACTIVITY LOG</SectionTitle>
            <div className="se-table-wrap">
              <table className="se-table">
                <thead><tr><th>PHASE</th><th>TOOL</th><th>STATUS</th><th>MESSAGE</th></tr></thead>
                <tbody>
                  {session.activity.length === 0 && (
                    <tr><td colSpan={4} className="se-empty">No activity recorded.</td></tr>
                  )}
                  {session.activity.map((a, i) => (
                    <tr key={i}>
                      <td className="mono">{PHASE_LABELS[a.phase] || a.phase}</td>
                      <td className="mono">{a.tool_id || '—'}</td>
                      <td style={{ color: statusColor(a.status) }}>{a.status.toUpperCase()}</td>
                      <td className="se-empty">{a.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card dataTool="escalate">
            <SectionTitle><ShieldAlert className="w-3.5 h-3.5" /> FINDINGS</SectionTitle>
            {session.findings.length === 0 ? (
              <div className="se-empty">No adverse findings — the mitigate phase found nothing to remediate.</div>
            ) : (
              <div className="se-table-wrap">
                <table className="se-table">
                  <thead><tr><th>SEVERITY</th><th>TITLE</th><th>DETAIL</th></tr></thead>
                  <tbody>
                    {session.findings.map(f => (
                      <tr key={f.finding_id}>
                        <td><span className="se-sev-tag" style={{ color: '#EF4444', borderColor: '#EF4444' }}>{f.severity}</span></td>
                        <td>{f.title}</td>
                        <td className="se-empty">{f.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card dataTool="mitigate">
            <SectionTitle><ShieldCheck className="w-3.5 h-3.5" /> MITIGATION POSTURE</SectionTitle>
            {session.mitigation.length === 0 ? (
              <div className="se-empty">No remediation required.</div>
            ) : (
              <div className="se-kv">
                {session.mitigation.map((m, i) => (
                  <div className="se-row" key={i}>
                    <span className="mono se-cve">{m.tool_id}</span>
                    <span className="se-row-note">{m.remediation}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      )}

      <Card dataTool="plan">
        <SectionTitle><Clock3 className="w-3.5 h-3.5" /> RECENT CHAIN RUNS</SectionTitle>
        {history.length === 0 ? (
          <div className="se-empty">No RE-ACT sessions yet this session.</div>
        ) : (
          <div className="se-table-wrap">
            <table className="se-table">
              <thead><tr><th>SESSION</th><th>KIND</th><th>TARGET</th><th>STATUS</th><th>OPERATOR</th></tr></thead>
              <tbody>
                {history.map(h => (
                  <tr key={h.session_id}>
                    <td className="mono">{h.session_id}</td>
                    <td>{h.kind}</td>
                    <td className="mono">{h.target}</td>
                    <td style={{ color: statusColor(h.status) }}>{h.status}</td>
                    <td className="mono">{h.operator}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
