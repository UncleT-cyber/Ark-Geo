/**
 * BottomPanel — universal contextual console (domain-agnostic).
 *
 * Binds to the shared investigation context (active case/evidence/run/findings/
 * audit trail), NOT to any one domain. It displays data for the currently
 * active case, evidence asset, analysis run, and investigation domain — so it
 * works for IMAGE now and NETWORK later without being rewritten.
 *
 * Tabs:
 *   PROBLEMS — detected anomalies / errors for the active case
 *   ANALYSIS LOG — real-time backend stdout / execution log for the active run
 *   EVIDENCE — immutable SHA-256 / SHA-1 / MD5 + file byte metrics
 *   AUDIT — timestamped chain-of-custody audit events
 *   TERMINAL — global interactive system terminal, connected across ALL domains
 */
import React, { useState, useRef, useEffect } from 'react';
import { ChevronUp, ChevronDown } from 'lucide-react';
import { useInvestigation } from './useInvestigation';
import { CONSOLE_ICONS } from './icons';

type BottomTab = 'problems' | 'log' | 'evidence' | 'audit' | 'terminal';

interface BottomPanelProps {
  collapsed: boolean;
  onToggle: () => void;
  /** Optional legacy result for tools that still feed hashes/log directly. */
  result?: import('../../types').AnalyzeResponse | null;
}

interface TerminalLine { text: string; type: 'in' | 'out' | 'sys' | 'err'; }

const HELP_TEXT = [
  'ARK Terminal — commands:',
  '  help            show this help',
  '  status          show active case / evidence / run summary',
  '  case            list active case ID',
  '  evidence        show active evidence SHA-256',
  '  findings        list findings for the active run',
  '  audit           show audit trail for the active case',
  '  clear           clear the terminal',
];

export function BottomPanel({ collapsed, onToggle, result }: BottomPanelProps) {
  const inv = useInvestigation();
  const [tab, setTab] = useState<BottomTab>('problems');

  // Terminal state — persists across domain switches (module-level buffer).
  const [termLines, setTermLines] = useState<TerminalLine[]>([
    { text: 'ARK Terminal connected. Type "help" for commands.', type: 'sys' },
  ]);
  const [termInput, setTermInput] = useState('');
  const termEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    termEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [termLines]);

  const runCommand = (raw: string) => {
    const cmd = raw.trim();
    const out: TerminalLine[] = [{ text: `$ ${cmd}`, type: 'in' }];
    const [name, ...args] = cmd.split(/\s+/);
    switch (name.toLowerCase()) {
      case 'help':
        out.push(...HELP_TEXT.map(t => ({ text: t, type: 'out' as const })));
        break;
      case 'status': {
        if (!inv.activeCase) { out.push({ text: 'No active case.', type: 'out' }); break; }
        out.push({ text: `Domain: ${inv.domain.toUpperCase()}`, type: 'out' });
        out.push({ text: `Case:   ${inv.activeCase.id}`, type: 'out' });
        out.push({ text: `Title:  ${inv.activeCase.title}`, type: 'out' });
        if (inv.activeEvidence) out.push({ text: `Evidence: ${inv.activeEvidence.id} (${inv.activeEvidence.sha256.slice(0, 16)}...)`, type: 'out' });
        if (inv.activeRun) out.push({ text: `Run:    ${inv.activeRun.source} (${inv.activeRun.tier}) · ${Math.round(inv.activeRun.confidence * 100)}%`, type: 'out' });
        out.push({ text: `Findings: ${inv.findings.length} · Audit: ${inv.auditTrail.length}`, type: 'out' });
        break;
      }
      case 'case':
        out.push({ text: inv.activeCase ? inv.activeCase.id : 'No active case.', type: 'out' });
        break;
      case 'evidence':
        out.push({ text: inv.activeEvidence ? `SHA-256: ${inv.activeEvidence.sha256}` : 'No active evidence.', type: 'out' });
        break;
      case 'findings':
        if (inv.findings.length === 0) { out.push({ text: 'No findings.', type: 'out' }); break; }
        inv.findings.forEach(f => out.push({ text: `[${f.severity}] ${f.type}: ${f.message}`, type: f.status === 'ERROR' ? 'err' : 'out' }));
        break;
      case 'audit':
        if (inv.auditTrail.length === 0) { out.push({ text: 'No audit events.', type: 'out' }); break; }
        inv.auditTrail.forEach(a => out.push({ text: `${new Date(a.timestamp).toLocaleTimeString()} ${a.action} — ${a.detail}`, type: 'out' }));
        break;
      case 'clear':
        setTermLines([]);
        return;
      case '':
        break;
      default:
        out.push({ text: `Unknown command: ${name}. Type "help".`, type: 'err' });
    }
    setTermLines(prev => [...prev, ...out]);
  };

  // Derive problems from the shared findings + legacy result anomalies.
  const problems = React.useMemo(() => {
    const list: { type: string; msg: string; severity: string }[] = [];
    inv.findings.forEach(f => {
      if (f.status !== 'OK') list.push({ type: f.type, msg: f.message, severity: f.status === 'ERROR' ? 'error' : 'warning' });
    });
    if (result?.exif_missing && list.length === 0) list.push({ type: 'Metadata', msg: 'EXIF metadata stripped/missing', severity: 'warning' });
    if (result?.steganography_detected) list.push({ type: 'Structure', msg: `Trailing bytes after EOF (${result.trailing_bytes_count})`, severity: 'error' });
    if (result?.gps_spoofing_detected) list.push({ type: 'GPS', msg: `Spoofing suspected (anomaly ${Math.round((result.anomaly_score || 0) * 100)}%)`, severity: 'error' });
    return list;
  }, [inv.findings, result]);

  const analysisLog = inv.activeRun?.analysisLog || result?.analysis_log || [];
  const cert = result?.custody_certificate;
  const tabs: { id: BottomTab; label: string }[] = [
    { id: 'problems', label: 'PROBLEMS' },
    { id: 'log', label: 'ANALYSIS LOG' },
    { id: 'evidence', label: 'EVIDENCE' },
    { id: 'audit', label: 'AUDIT' },
    { id: 'terminal', label: 'TERMINAL' },
  ];

  const Icon = (id: BottomTab) => {
    const C = CONSOLE_ICONS[id];
    return <C className="w-3 h-3" />;
  };

  return (
    <div className={`bottom-panel ${collapsed ? 'bottom-panel-collapsed' : ''}`}>
      <div className="bottom-panel-header">
        <div className="bottom-panel-tabs">
          {tabs.map(t => (
            <button
              key={t.id}
              className={`bottom-tab ${tab === t.id ? 'bottom-tab-active' : ''}`}
              onClick={() => { setTab(t.id); if (collapsed) onToggle(); }}
            >
              <span className="bottom-tab-icon">{Icon(t.id)}</span>
              {t.id === 'problems' && problems.length > 0 && <span className="bottom-tab-badge">{problems.length}</span>}
              {t.label}
            </button>
          ))}
        </div>
        <button className="bottom-panel-toggle" onClick={onToggle} title={collapsed ? 'Expand panel' : 'Collapse panel'}>
          {collapsed ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
      </div>
      {!collapsed && (
        <div className="bottom-panel-content">
          {tab === 'problems' && (
            <div className="bottom-list">
              {problems.length === 0 ? (
                <div className="bottom-empty">No problems detected for the active case</div>
              ) : problems.map((p, i) => (
                <div key={i} className={`bottom-row bottom-row-${p.severity}`}>
                  <span className="bottom-row-sev">{p.severity === 'error' ? '✕' : '▲'}</span>
                  <span className="bottom-row-type mono">{p.type}</span>
                  <span className="bottom-row-msg">{p.msg}</span>
                </div>
              ))}
            </div>
          )}
          {tab === 'log' && (
            <div className="bottom-list bottom-log">
              {analysisLog.length === 0 ? (
                <div className="bottom-empty">No analysis events yet for the active run</div>
              ) : analysisLog.map((line, i) => (
                <div key={i} className="bottom-log-line mono">{line}</div>
              ))}
            </div>
          )}
          {tab === 'evidence' && (
            <div className="bottom-list">
              {!inv.activeEvidence && !result ? <div className="bottom-empty">No evidence loaded for the active case</div> : (
                <>
                  <div className="bottom-row"><span className="bottom-row-type mono">SHA-256</span><span className="bottom-row-msg mono">{inv.activeEvidence?.sha256 || result?.image_sha256}</span></div>
                  {cert && <div className="bottom-row"><span className="bottom-row-type mono">SHA-1</span><span className="bottom-row-msg mono">{cert.sha1}</span></div>}
                  {cert && <div className="bottom-row"><span className="bottom-row-type mono">MD5</span><span className="bottom-row-msg mono">{cert.md5}</span></div>}
                  <div className="bottom-row"><span className="bottom-row-type mono">MIME</span><span className="bottom-row-msg mono">{inv.activeEvidence?.mimeType || result?.file_format || 'N/A'}</span></div>
                  {inv.activeEvidence?.byteSize && <div className="bottom-row"><span className="bottom-row-type mono">BYTES</span><span className="bottom-row-msg mono">{inv.activeEvidence.byteSize}</span></div>}
                  {result?.custody_hash && <div className="bottom-row"><span className="bottom-row-type mono">CUSTODY</span><span className="bottom-row-msg mono">{result.custody_hash}</span></div>}
                </>
              )}
            </div>
          )}
          {tab === 'audit' && (
            <div className="bottom-list">
              {inv.auditTrail.length === 0 ? <div className="bottom-empty">No audit entries for the active case</div> : inv.auditTrail.map(e => (
                <div key={e.id} className="bottom-row">
                  <span className="bottom-row-type mono">{new Date(e.timestamp).toLocaleTimeString()}</span>
                  <span className="bottom-row-msg"><strong>{e.action}</strong> — {e.detail}</span>
                </div>
              ))}
            </div>
          )}
          {tab === 'terminal' && (
            <div className="bottom-terminal" onClick={() => (document.getElementById('ark-term-input') as HTMLInputElement)?.focus()}>
              <div className="bottom-terminal-body">
                {termLines.map((l, i) => (
                  <div key={i} className={`bottom-terminal-line bottom-terminal-${l.type} mono`}>{l.text}</div>
                ))}
                <div ref={termEndRef} />
              </div>
              <div className="bottom-terminal-input-row">
                <span className="bottom-terminal-prompt mono">$</span>
                <input
                  id="ark-term-input"
                  className="bottom-terminal-input mono"
                  value={termInput}
                  onChange={e => setTermInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { runCommand(termInput); setTermInput(''); } }}
                  placeholder="type a command (help)"
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
