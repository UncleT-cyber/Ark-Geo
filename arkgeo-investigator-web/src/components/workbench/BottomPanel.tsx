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
 *   PLAN — AI Investigation: objective, proposed/amended plan + budget
 *          estimate, Approve / Resume (pause_to_ask) actions, open gaps
 *   AGENT — AI Investigation: tool activity log + live budget consumption
 *   EVIDENCE — immutable SHA-256 / SHA-1 / MD5 + file byte metrics (classic),
 *          OR the investigation evidence graph (nodes/edges/findings)
 *   AUDIT — timestamped chain-of-custody audit events
 *   TERMINAL — global interactive system terminal, connected across ALL domains
 */
import React, { useState, useRef, useEffect } from 'react';
import { ChevronUp, ChevronDown, RefreshCw, Play, PauseCircle } from 'lucide-react';
import { useInvestigation } from './useInvestigation';
import { CONSOLE_ICONS } from './icons';
import { api } from '../../api';
import { openAgentTaskEvents } from '../../api';
import { useArkBus } from './ArkBusContext';
import type {
  InvestigationSession,
  GraphGap,
  EvidenceEdge,
  EvidenceNode,
  InvestigationFinding,
  Observation,
  AgentTaskResponse,
  ReactMitigation,
} from '../../types';

type BottomTab = 'problems' | 'log' | 'plan' | 'agent' | 'evidence' | 'audit' | 'terminal';

interface BottomPanelProps {
  collapsed: boolean;
  onToggle: () => void;
  /** Optional legacy result for tools that still feed hashes/log directly. */
  result?: import('../../types').AnalyzeResponse | null;
}

interface TerminalLine {
  text: string;
  type: 'in' | 'out' | 'sys' | 'err' | 'tool' | 'hitl';
  tool?: { name: string; args: string; elapsed: string; status: 'completed' | 'running' | 'denied' | 'error'; executionId?: string };
  hitl?: { tool: string; args: Record<string, unknown>; prompt?: string; executionId?: string };
}

// ---- Dynamic tool-call parsing (zero hardcoding) ----
// Inspect the SSE payload structurally and extract whatever tool name /
// argument keys are present. No static IP/target regex or string matching.
function parseToolCall(ev: any): { name: string; args: Record<string, unknown>; executionId?: string } {
  const fn = ev?.function;
  const name: string =
    (fn && (fn.name ?? fn.tool_name)) ||
    ev?.tool ||
    ev?.tool_name ||
    (typeof ev?.tool === 'object' ? ev.tool?.name : undefined) ||
    'tool';
  const rawArgs =
    ((fn && (fn.arguments ?? fn.args)) ||
     ev?.args ||
     ev?.arguments) ??
    {};
  let args: Record<string, unknown> = {};
  if (typeof rawArgs === 'string') {
    try { args = JSON.parse(rawArgs || '{}'); } catch { args = { value: rawArgs }; }
  } else if (rawArgs && typeof rawArgs === 'object') {
    args = rawArgs as Record<string, unknown>;
  }
  return { name: String(name), args, executionId: ev?.execution_id ?? ev?.session_id };
}

// Render whatever key/value pairs exist inside the args object — generic.
function formatArgs(args: Record<string, unknown>): string {
  if (!args || typeof args !== 'object') return String(args ?? '');
  const keys = Object.keys(args);
  if (keys.length === 0) return '';
  return keys
    .map((k) => {
      const v = args[k];
      const s = typeof v === 'object' ? JSON.stringify(v) : String(v);
      return `${k}=${s}`;
    })
    .join(', ');
}

// Defense-in-depth: detect raw tool-call / tool-schema JSON that may have
// leaked through as a streamed text line so we never print it verbatim.
// CAI renders these as a structured call panel instead of raw JSON.
function looksLikeToolCallJson(text: string): boolean {
  const t = text.trim();
  if (!t.startsWith('{') || t.length < 12) return false;
  try {
    const o = JSON.parse(t);
    const fn = o && (o.function ?? o);
    const hasName = !!(fn && fn.name);
    const looksToolish =
      'function' in o || 'name' in o || 'parameters' in o ||
      (typeof o === 'object' && o.type === 'function');
    return !!(hasName || looksToolish);
  } catch {
    return false;
  }
}

const HELP_TEXT = [
  'ARK Terminal — commands:',
  '  help                 show this help',
  '  status               show active case / evidence / run summary',
  '  case                 list active case ID',
  '  evidence             show active evidence SHA-256',
  '  findings             list findings for the active run',
  '  audit                show audit trail for the active case',
  '  ark metadata extract extract IMINT 4-pillar metadata (WHAT/WHEN/WHERE/HOW)',
  '  ark ocr run          report OCR state for the active evidence',
  '  ark evidence info    show structured observations for the active case',
  '  ark evidence list    list OBS-* observation IDs attached to the case',
  '  ark jpeg inspect     inspect JPEG structure (format, dimensions, stego, class)',
  '  ark ladder           show the fallback investigation ladder state',
  '  ark inspect <path>   sandboxed local directory inspector (agent tool-calling)',
  '  ark capabilities     list the full ARK capability catalog (tools + platform)',
  '  perform a penetration test on <ip|cidr|url>  RE-ACT engagement: plans first,',
  '                       asks permission [always / now / deny], then runs plan→',
  '                       scan→exploit→escalate→mitigate on the authorized scope',
  '  <anything else>      ARK agent: directives with a target run tools; vague/',
  '                       conversational input is answered without running tools',
  '  clear                clear the terminal',
];

const GAP_TYPE_LABEL: Record<string, string> = {
  unverified_claim: 'UNVERIFIED CLAIM',
  open_contradiction: 'OPEN CONTRADICTION',
  low_corroboration: 'LOW CORROBORATION',
  missing_layer: 'MISSING LAYER',
};

const PROVENANCE_LABEL: Record<string, string> = {
  cryptographic: 'CRYPTOGRAPHIC',
  tool_inference: 'TOOL INFERENCE',
  ai_hypothesis: 'AI HYPOTHESIS',
  analyst: 'ANALYST',
};

// Styled CAI banner + status box shown at the top of the terminal session.
function CaiBanner() {
  const [activeModel, setActiveModel] = useState<string>('resolving…');
  const bus = useArkBus();
  // Bind to the central AI config (single source of truth) — never hardcode.
  useEffect(() => {
    let alive = true;
    const refresh = () =>
      api.configActiveModel()
        .then((m) => { if (alive) setActiveModel(`${m.provider}/${m.model_name}`); })
        .catch(() => { if (alive) setActiveModel('central-config'); });
    refresh();
    // Live rebind when an admin changes the active model in the Admin Console.
    const unsub = bus.subscribe((ev: any) => {
      if (ev && ev.category === 'model.changed') {
        const m = ev.model as string;
        if (m) setActiveModel(m);
      }
    });
    return () => { alive = false; unsub(); };
  }, [bus]);
  return (
    <div className="cai-banner mono">
      <pre className="cai-banner-art">{` █████╗ ██████╗ ██╗  ██╗
 ██╔══██╗██╔══██╗██║ ██╔╝    ARK • CAI UNIFIED ENGINE
 ███████║██████╔╝█████═╝     Cybersecurity AI — ReAct Orchestrator
 ██╔══██║██╔══██╗██╔═██╗     bound to ARK central AI config
 ██║  ██║██║  ██║██║  ██╗
 ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝`}</pre>
      <div className="cai-banner-box">
        <span><b>Model</b>    {activeModel}</span>
        <span><b>Agent</b>    operator</span>
        <span><b>Commands</b> /help · /agent · /case · /tools</span>
      </div>
    </div>
  );
}

export function BottomPanel({ collapsed, onToggle, result }: BottomPanelProps) {
  const inv = useInvestigation();
  // The active bottom-console tab is shared via the investigation context so
  // the Investigation workspace can focus the console (e.g. PLAN after
  // "Investigate Next") without duplicating state.
  const tab = inv.bottomTab as BottomTab;
  const setTab = (t: BottomTab) => inv.setBottomTab(t);

  // ---- Terminal height — drag-to-resize, persisted across sessions.
  const [panelHeight, setPanelHeight] = useState(() => {
    const saved = Number(localStorage.getItem('ark.bottomPanelH') ?? 0);
    return saved >= 120 && saved <= window.innerHeight * 0.8 ? saved : 200;
  });
  const dragState = useRef<{ startY: number; startH: number; current: number } | null>(null);

  const startResize = (e: React.MouseEvent) => {
    e.preventDefault();
    dragState.current = { startY: e.clientY, startH: panelHeight, current: panelHeight };
    const onMove = (ev: MouseEvent) => {
      const s = dragState.current;
      if (!s) return;
      const maxH = window.innerHeight * 0.8;
      const next = Math.min(maxH, Math.max(120, s.startH + (s.startY - ev.clientY)));
      s.current = next;
      setPanelHeight(next);
    };
    const onUp = () => {
      const final = dragState.current?.current ?? panelHeight;
      dragState.current = null;
      try { localStorage.setItem('ark.bottomPanelH', String(final)); } catch { /* non-blocking */ }
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      document.body.style.cursor = '';
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    document.body.style.cursor = 'row-resize';
  };

  // Shared ARK AI investigation session (context-managed, console-agnostic).
  const session = inv.session;
  const invBusy = inv.invBusy;
  const invError = inv.invError;
  const [resumeSteps, setResumeSteps] = useState(100);
  const invFileRef = useRef<HTMLInputElement>(null);

  // Canonical structured observations from the backend analysis (OBS-*).
  const observations: Observation[] = result?.observations
    || result?.evidence_summary?.observations
    || [];

  // Terminal state — persists across domain switches (module-level buffer).
  const [termLines, setTermLines] = useState<TerminalLine[]>([
    { text: 'ARK Terminal connected. Type "help" for commands.', type: 'sys' },
  ]);
  // In-progress streamed-answer buffer (single line until a paragraph break).
  const [streamLine, setStreamLine] = useState<string | null>(null);
  // Shows the CAI banner once a CAI task has been initialized this session.
  const [caiInitialized, setCaiInitialized] = useState(false);
  const [termInput, setTermInput] = useState('');
  const termEndRef = useRef<HTMLDivElement>(null);
  const termInputRef = useRef<HTMLInputElement>(null);
  const streamRef = useRef<string>('');
  const streamedRef = useRef<boolean>(false);

  // Pending RE-ACT engagement awaiting the permission prompt (CAI-parity):
  // while set, the next terminal input is treated as [always / now / deny].
  const [pendingApproval, setPendingApproval] = useState<{
    sessionId: string;
    tools: string[];
    target: string;
  } | null>(null);

  // ---- ARK-CAI unified engine (embedded CAI as THE ARK's AI core) ----
  // Session id shared with the backend so slash commands, role/model selection
  // and case attachment persist across turns in this terminal.
  const [caiSessionId, setCaiSessionId] = useState<string>(() => `cai-${Math.random().toString(36).slice(2, 10)}`);
  const [caiWorkspace, setCaiWorkspace] = useState<string | undefined>(undefined);
  const [caiRole, setCaiRole] = useState<string | undefined>(undefined);
  // Unified slash-command autocomplete menu (CAI engine + ARK workspace commands).
  const [slashMenu, setSlashMenu] = useState<{ name: string; group: string; description: string; usage: string }[]>([]);
  const [slashIndex, setSlashIndex] = useState(0);
  // HITL approval surfaced by the CAI engine as a single-key [Y/n/A] prompt.
  const [pendingCaiApproval, setPendingCaiApproval] = useState<string | null>(null);
  const [pendingExecutionId, setPendingExecutionId] = useState<string | null>(null);

  // Resolve a HITL gate with one of three operator actions:
  //   approve       → allow the single pending tool call
  //   allow_always  → enable session auto-approval (continuous execution)
  //   deny          → reject and force the model to re-plan
  const caiApprove = (mode: 'approve' | 'allow_always' | 'deny') => {
    const sid = pendingCaiApproval;
    const eid = pendingExecutionId ?? undefined;
    if (!sid) return;
    setPendingCaiApproval(null);
    setPendingExecutionId(null);
    const label = mode === 'approve' ? 'Y' : mode === 'allow_always' ? 'A' : 'N';
    setTermLines(prev => [...prev, { text: `$ ${label}`, type: 'in' }]);
    if (mode === 'allow_always') {
      setTermLines(prev => [...prev, { text: 'ARK-CAI: Auto-approval session grant enabled by operator.', type: 'sys' }]);
      api.caiTerminalApprove(sid, true, true, eid).catch(() => {});
    } else if (mode === 'approve') {
      setTermLines(prev => [...prev, { text: 'ARK: approval accepted — continuing.', type: 'sys' }]);
      api.caiTerminalApprove(sid, true, false, eid).catch(() => {});
    } else {
      setTermLines(prev => [...prev, { text: 'ARK: approval declined.', type: 'sys' }]);
      api.caiTerminalApprove(sid, false, false, eid).catch(() => {});
    }
  };

  // Live "preparing context and calling the model" spinner while a task runs.
  const [termBusy, setTermBusy] = useState(false);
  const [busyGlyph, setBusyGlyph] = useState('⠹');
  useEffect(() => {
    if (!termBusy) return;
    const glyphs = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
    let i = 0;
    const id = setInterval(() => {
      i = (i + 1) % glyphs.length;
      setBusyGlyph(glyphs[i]);
    }, 90);
    return () => clearInterval(id);
  }, [termBusy]);

  // The shared streaming feed (Telecom console, network diagnostics, vuln runs)
  // and the interactive command buffer are rendered together in one standard
  // terminal view so tool output and analyst commands share a single scroll.
  useEffect(() => {
    termEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [termLines, inv.terminal, termBusy]);

  // Live autocomplete for the unified slash-command surface: every keystroke
  // after a leading "/" queries THE ARK's CAI command registry (engine control
  // + ARK workspace commands rendered in a single menu).
  useEffect(() => {
    if (termInput.startsWith('/')) {
      api.caiCommands(termInput)
        .then(setSlashMenu)
        .catch(() => setSlashMenu([]));
    } else {
      setSlashMenu([]);
    }
  }, [termInput]);

  // Standard-terminal behaviour: focus the input whenever the terminal tab is
  // visible so the analyst can type immediately without hunting for the field.
  useEffect(() => {
    if (tab === 'terminal' && !collapsed) {
      termInputRef.current?.focus();
    }
  }, [tab, collapsed]);

  const runCommand = (raw: string) => {
    const cmd = raw.trim();
    const out: TerminalLine[] = [{ text: `$ ${cmd}`, type: 'in' }];
    const [name, ...args] = cmd.split(/\s+/);

    // Unified slash commands route to THE ARK's embedded CAI engine (engine
    // control + ARK workspace). The legacy non-slash commands below stay intact.
    if (cmd.startsWith('/')) {
      // /ws <workspace> <prompt> → invoke the workspace's CAI sub-agent role
      // (IMINTAgent, ReconAgent, BlueTeamAgent, ...) directly via the backend.
      if (cmd.startsWith('/ws ')) {
        const body = cmd.slice(4).trim();
        const sp = body.indexOf(' ');
        const ws = sp === -1 ? body : body.slice(0, sp);
        const prompt = sp === -1 ? '' : body.slice(sp + 1).trim();
        if (!prompt) {
          setTermLines(prev => [...prev, { text: `$ ${cmd}`, type: 'in' }, { text: 'Usage: /ws <imint|recon|network|siem|blueteam|case> <prompt>', type: 'err' }]);
          return;
        }
        setCaiWorkspace(ws);
        runCaiTask(prompt, ws);
        return;
      }
      // /agent <role> → select a CAI sub-agent role for this terminal session.
      if (cmd.startsWith('/agent ')) {
        const role = cmd.slice(7).trim();
        setCaiRole(role);
        setTermLines(prev => [...prev, { text: `$ ${cmd}`, type: 'in' }, { text: `● ARK: agent role set: ${role}`, type: 'sys' }]);
        return;
      }
      runCaiCommand(cmd);
      return;
    }
    const lname = name.toLowerCase();
    switch (lname) {
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
        if (session) out.push({ text: `AI Inv: ${session.investigation_id} [${session.status}] iter=${session.iterations}`, type: 'out' });
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
      case 'ark': {
        const sub = (args[0] || '').toLowerCase();
        const arg = (args[1] || '').toLowerCase();
        if (sub === 'metadata' && arg === 'extract') {
          const imint = result?.image_intelligence;
          if (!imint) { out.push({ text: 'No IMINT payload for the active evidence.', type: 'out' }); break; }
          const p = imint.analysis?.pillars_present || {};
          out.push({ text: 'IMINT 4-PILLAR EXTRACTION', type: 'sys' });
          out.push({ text: `  WHERE  geospatial: ${imint.geospatial?.has_coordinates ? `${imint.geospatial.latitude_decimal}, ${imint.geospatial.longitude_decimal}` : 'no GPS'}`, type: 'out' });
          out.push({ text: `  WHEN   temporal: ${imint.temporal?.has_timestamps ? imint.temporal.datetime_original : 'no timestamps'}`, type: 'out' });
          out.push({ text: `  WHAT   device: ${imint.device?.has_provenance ? `${imint.device.make} ${imint.device.model}`.trim() : 'no camera provenance'}`, type: 'out' });
          out.push({ text: `  HOW    capture: ${imint.capture?.has_capture ? `ISO ${imint.capture.iso} f/${imint.capture.f_number}` : 'no capture diagnostics'}`, type: 'out' });
          out.push({ text: `  Pillars present: ${Object.entries(p).filter(([, v]) => v).length}/${Object.keys(p).length}`, type: 'out' });
        } else if (sub === 'ocr' && arg === 'run') {
          const obs = observations.find(o => o.type === 'OCR');
          const tags = result?.consensus?.visual_evidence_tags || [];
          const ocrCount = tags.filter(t => t.category === 'ocr').length;
          if (obs && obs.status === 'UNAVAILABLE') {
            out.push({ text: 'OCR UNAVAILABLE — provider not configured (Admin required).', type: 'err' });
          } else {
            out.push({ text: `OCR completed — Text regions detected: ${ocrCount}`, type: 'out' });
            tags.filter(t => t.category === 'ocr').forEach(t => out.push({ text: `  "${t.label}" · ${Math.round(t.confidence * 100)}%`, type: 'out' }));
            if (ocrCount === 0) out.push({ text: 'No text regions detected in this image.', type: 'out' });
          }
        } else if (sub === 'evidence' && arg === 'info') {
          if (observations.length === 0) { out.push({ text: 'No observations recorded for the active case.', type: 'out' }); break; }
          out.push({ text: `STRUCTURED EVIDENCE — ${observations.length} observations across ${new Set(observations.map(o => o.layer)).size} layers`, type: 'sys' });
          observations.forEach(o => out.push({
            text: `${o.id} [${o.status}] ${o.type} — ${o.label}${o.detail ? ` (${o.detail})` : ''}`,
            type: o.status === 'ANOMALY' ? 'err' : 'out',
          }));
        } else if (sub === 'evidence' && arg === 'list') {
          if (observations.length === 0) { out.push({ text: 'No observations.', type: 'out' }); break; }
          out.push({ text: observations.map(o => o.id).join(' '), type: 'out' });
        } else if (sub === 'jpeg' && arg === 'inspect') {
          const deep = result?.deep_metadata?.file_info || {};
          out.push({ text: 'JPEG / STRUCTURE INSPECTION', type: 'sys' });
          out.push({ text: `  Format:    ${result?.file_format || deep.FileType || 'N/A'}`, type: 'out' });
          out.push({ text: `  Dimensions: ${deep.ImageWidth || deep.ExifImageWidth || '?'} × ${deep.ImageHeight || deep.ExifImageHeight || '?'}`, type: 'out' });
          out.push({ text: `  Steganography: ${result?.steganography_detected ? `DETECTED (${result.trailing_bytes_count} trailing bytes)` : 'CLEAN'}`, type: result?.steganography_detected ? 'err' : 'out' });
          out.push({ text: `  Classification: ${result?.image_classification || 'Unknown'}`, type: 'out' });
        } else if (sub === 'ladder') {
          const ladder = result?.evidence_summary?.ladder;
          if (!ladder) { out.push({ text: 'No ladder state — re-ingest the image.', type: 'out' }); break; }
          out.push({ text: `FALLBACK LADDER — ran ${ladder.ran}/${ladder.total} · blocked ${ladder.blocked} · complete ${ladder.complete ? 'yes' : 'no'}`, type: 'sys' });
          ladder.steps.forEach(s => out.push({
            text: `${s.status === 'ran' ? '✓' : s.status === 'blocked' ? '✕' : '→'} [${s.status.toUpperCase().padEnd(9)}] ${s.label}${s.fallback ? ` → fallback: ${s.fallback}` : ''}`,
            type: s.status === 'blocked' ? 'err' : 'out',
          }));
        } else if (sub === 'capabilities') {
          return runCapabilitiesCommand(out);
        } else if (sub === 'inspect') {
          const p = (args[1] || '').trim();
          if (!p) {
            out.push({ text: 'Usage: ark inspect <path> — e.g. ark inspect case-001 (auto-created under the sandbox root)', type: 'err' });
            break;
          }
          return runAgentTask(`ark inspect ${p}`, p);
        } else {
          out.push({ text: 'Usage: ark <metadata extract|ocr run|evidence info|evidence list|jpeg inspect|ladder|inspect <path>>', type: 'err' });
        }
        break;
      }
      case 'clear':
        setTermLines([]);
        return;
      case '':
        break;
      default:
        // Anything that is not a rigid legacy command is a natural-language
        // prompt routed to THE ARK's embedded CAI engine (advisory or
        // autonomous), which also handles RE-ACT-style tasks.
        if (name) return runCaiTask(cmd);
        out.push({ text: '', type: 'out' });
    }
    setTermLines(prev => [...prev, ...out]);
  };

  // ---- ARK-CAI unified engine: stream a task through the embedded CAI core ----
  // Routes through THE ARK's hybrid intent router (advisory vs autonomous) and
  // renders the live SSE event contract: streamed answer buffering, CAI-style
  // tool COMPLETED badges, and clean HITL [Y/n] approval prompts.
  const runCaiTask = (raw: string, workspace?: string) => {
    setTermBusy(true);
    setCaiInitialized(true);
    streamedRef.current = false;
    // Flush any leftover answer buffer from a previous task.
    if (streamRef.current.trim()) {
      const v = streamRef.current.trim();
      setTermLines(prev => [...prev, { text: v, type: 'out' }]);
      streamRef.current = '';
      setStreamLine(null);
    }
    setTermLines(prev => [
      ...prev,
      { text: `$ ${raw}`, type: 'in' },
    ]);

    const append = (text: string, type: TerminalLine['type']) =>
      setTermLines(prev => [...prev, { text, type }]);
    const flushStream = () => {
      const v = streamRef.current.trim();
      // Never print raw tool-call / tool-schema JSON — it is rendered as a
      // structured call badge via the `tool_call` event instead.
      if (v && !looksLikeToolCallJson(v)) setTermLines(prev => [...prev, { text: v, type: 'out' }]);
      streamRef.current = '';
      setStreamLine(null);
    };
    const argsStr = (a?: Record<string, unknown>) =>
      a ? Object.entries(a)
        .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
        .join(', ') : '';
    const elapsedStr = (ms?: number) => (ms != null ? `${(ms / 1000).toFixed(1)}s` : '0.0s');

    api.caiTerminalStream(
      raw,
      {
        sessionId: caiSessionId,
        model: undefined,
        caseId: inv.activeCase?.id,
        workspace: workspace ?? caiWorkspace,
        caseContext: result ? {
          image_sha256: result.image_sha256,
          source: result.source,
          filename: inv.activeEvidence?.filename,
          coordinates: result.coordinates,
          address: result.address,
          altitude: result.altitude,
          datetime_original: result.datetime_original,
          camera: result.camera,
          consensus: result.consensus,
          consistency_findings: result.consistency_findings,
          contradictions: result.contradictions,
          gps_spoofing_detected: result.gps_spoofing_detected,
          steganography_detected: result.steganography_detected,
          source_discovery: result.source_discovery,
          evidence_summary: result.evidence_summary,
          telemetry_resolve: result.telemetry_resolve,
          exif_raw: result.exif_raw,
          deep_metadata: result.deep_metadata,
        } : null,
      },
      (ev) => {
        if (ev.event === 'status') {
          if (ev.stage === 'planning') {
            flushStream();
            append(`● ARK — mode: ${ev.path ?? 'unknown'}${ev.reason ? ` — ${ev.reason}` : ''}`, 'sys');
          } else if (ev.stage === 'tool_running') {
            // The RUNNING badge is rendered from the dynamic `tool_call`
            // event below; this legacy status is intentionally not re-rendered
            // to avoid a duplicate badge.
            flushStream();
          } else if (ev.stage === 'tool_denied') {
            flushStream();
            setTermLines(prev => [...prev, {
              text: '', type: 'tool',
              tool: { name: ev.tool, args: '', elapsed: '0.0s', status: 'denied' },
            }]);
          }
          // 'thinking' / 'calling_model' are surfaced via the busy spinner.
        } else if ((ev.event === 'tool_call' || (ev.function && typeof ev.function === 'object')) && ev.event !== 'hitl') {
          // Dynamic tool-call parser — renders a RUNNING badge from whatever
          // tool name + argument keys the payload carries. No hardcoded regex.
          flushStream();
          const { name, args, executionId } = parseToolCall(ev);
          setTermLines(prev => [...prev, {
            text: '',
            type: 'tool',
            tool: {
              name,
              args: formatArgs(args),
              elapsed: '0.0s',
              status: 'running',
              executionId,
            },
          }]);
        } else if (ev.event === 'tool') {
          flushStream();
          const { name, args, executionId } = parseToolCall(ev);
          const res = (ev.result || {}) as { status?: string; error?: string };
          const failed = res.status === 'error';
          if (failed) {
            append(`ARK tool error (${name}): ${res.error || 'unknown error'}`, 'err');
          }
          setTermLines(prev => [...prev, {
            text: '',
            type: 'tool',
            tool: {
              name,
              args: formatArgs(args),
              elapsed: elapsedStr(ev.elapsed_ms),
              status: failed ? 'error' : 'completed',
              executionId,
            },
          }]);
        } else if (ev.event === 'token') {
          // Buffer into a single line; break only on an explicit paragraph (\n\n).
          const next = streamRef.current + ev.text;
          const parts = next.split('\n\n');
          if (parts.length > 1) {
            parts.slice(0, -1).map(p => p.trim()).filter(Boolean)
              .forEach(c => setTermLines(prev => [...prev, { text: c, type: 'out' }]));
            streamRef.current = parts[parts.length - 1];
          } else {
            streamRef.current = next;
          }
          setStreamLine(streamRef.current);
          streamedRef.current = true;
        } else if (ev.event === 'hitl') {
          flushStream();
          const { name, args, executionId } = parseToolCall(ev);
          setTermLines(prev => [...prev, {
            text: '',
            type: 'hitl',
            hitl: { tool: name, args, prompt: ev.continue ? ev.prompt : undefined, executionId },
          }]);
          setPendingCaiApproval(ev.session_id ?? caiSessionId);
          setPendingExecutionId(executionId ?? null);
        } else if (ev.event === 'final') {
          flushStream();
          // Advisory answers are already streamed token-by-token; only render
          // the final summary when it was NOT already streamed (autonomous).
          if (!streamedRef.current) append(`ARK: ${ev.text}`, 'out');
        } else if (ev.event === 'error') {
          flushStream();
          append(`ARK error: ${ev.message}`, 'err');
        }
      },
      () => setTermBusy(false),
    ).catch((err) => {
      flushStream();
      append(`ARK error: ${err instanceof Error ? err.message : String(err)}`, 'err');
      setTermBusy(false);
    });
  };

  // ---- ARK-CAI unified slash command dispatch ----
  const runCaiCommand = (raw: string) => {
    setTermLines(prev => [...prev, { text: `$ ${raw}`, type: 'in' }]);
    api.caiCommand(raw, caiSessionId)
      .then((res) => {
        if (!res.ok) {
          setTermLines(prev => [...prev, { text: `ARK: ${res.error ?? 'command failed'}`, type: 'err' }]);
          return;
        }
        const lines: TerminalLine[] = [];
        if (res.action === 'tools' && res.tools) {
          lines.push({ text: `ARK tools (${res.tools.length})`, type: 'sys' });
          res.tools.forEach((t: any) => lines.push({ text: `  [${t.domain}] ${t.id} — ${t.description}${t.simulated ? ' (simulated)' : ''}`, type: 'out' }));
        } else if (res.action === 'sessions') {
          lines.push({ text: `Session: ${res.session?.role ?? 'generalist'} · turns=${res.session?.turns ?? 0} · case=${res.session?.case_id ?? '—'}`, type: 'out' });
        } else if (res.action === 'help') {
          lines.push({ text: 'ARK unified commands:', type: 'sys' });
          (res.commands ?? []).forEach((c: any) => lines.push({ text: `  /${c.name} — ${c.description}`, type: 'out' }));
        } else if (res.action === 'evidence' && res.result) {
          lines.push({ text: `Evidence: ${JSON.stringify(res.result).slice(0, 200)}`, type: 'out' });
        } else if (res.action === 'clear') {
          setTermLines([]);
          return;
        } else {
          lines.push({ text: `ARK: ${res.action} ok${res.role ? ` · role=${res.role}` : ''}${res.model ? ` · model=${res.model}` : ''}${res.case_id ? ` · case=${res.case_id}` : ''}`, type: 'out' });
        }
        setTermLines(prev => [...prev, ...lines]);
      })
      .catch((err) => setTermLines(prev => [...prev, { text: `ARK command error: ${err instanceof Error ? err.message : String(err)}`, type: 'err' }]));
  };

  // ---- Agent tool-calling (local directory inspector / natural language) ----
  // Resolves a prompt on the backend: the prompt is intent-classified (vague /
  // conversational input never runs tools), model-proposed tool calls are
  // Policy Guarded, evidence graph + audit record what ran, and the tool's
  // structured output is synthesized into a natural-language "ARK AGENT:" reply
  // printed directly below the system trace in this drawer.
  const runCapabilitiesCommand = async (out: TerminalLine[]) => {
    setTermLines(prev => [...prev, ...out]);
    try {
      const cap = await api.agentCapabilities();
      const lines: TerminalLine[] = [];
      const domains = cap.domains.map(d => d.label).join(' · ');
      lines.push({ text: `ARK AGENT — registered tool surface (${cap.tools.length} domains · ${cap.tools.reduce((n, g) => n + g.tools.length, 0)} tools)`, type: 'sys' });
      lines.push({ text: `  DOMAINS: ${domains}`, type: 'out' });
      lines.push({ text: '  ——— TOOLS ———', type: 'sys' });
      cap.tools.forEach(g => {
        lines.push({ text: `  ${g.label}`, type: 'sys' });
        g.tools.forEach(t => lines.push({
          text: `    ${t.deterministic ? '•' : '◇'} ${t.tool_id} — ${t.description}`,
          type: 'out',
        }));
      });
      lines.push({ text: '  ——— PLATFORM ———', type: 'sys' });
      cap.platform.forEach(p => lines.push({
        text: `  • ${p.label} — ${p.detail}`,
        type: 'out',
      }));
      setTermLines(prev => [...prev, ...lines]);
    } catch (err) {
      setTermLines(prev => [...prev, {
        text: `ARK capabilities error: ${err instanceof Error ? err.message : String(err)}`,
        type: 'err',
      }]);
    }
  };

  // ---- RE-ACT pentest renderer — task-pane style like a live agent feed:
  // per-tool status lines, the synthesized ARK AGENT answer, findings, and the
  // mitigation posture.
  const renderPentestTask = (res: AgentTaskResponse): TerminalLine[] => {
    const lines: TerminalLine[] = [];
    if (res.kind === 'pentest') {
      lines.push({
        text: `RE-ACT ENGAGEMENT — ${res.target ?? 'authorized scope'} [${res.status.toUpperCase()}]`,
        type: 'sys',
      });
    }
    const calls = res.tool_calls ?? [];
    calls.forEach(c => {
      const done = c.status === 'ran';
      lines.push({
        text: `● ${c.tool_id || '(tool)'} ─ ${c.message || c.status}${done ? ' ✓ COMPLETED' : ` ${c.status.toUpperCase()}`}`,
        type: done ? 'out' : c.status === 'failed' ? 'err' : 'out',
      });
    });
    if (calls.length > 0) {
      lines.push({ text: `  … ${calls.length} task(s) in this engagement`, type: 'sys' });
    }
    if (res.answer) {
      res.answer
        .split('\n')
        .filter(Boolean)
        .forEach((l, i) => {
          lines.push({
            text: `${i === 0 ? 'ARK AGENT: ' : '           '}${l}`,
            type: 'out',
          });
        });
    }
    const findings = res.pentestFindings ?? [];
    if (findings.length > 0) {
      lines.push({ text: `FINDINGS — ${findings.length}`, type: 'sys' });
      findings.forEach(f => lines.push({
        text: `  [${f.severity.toUpperCase()}] ${f.title}: ${f.detail}`,
        type: f.severity === 'critical' || f.severity === 'high' ? 'err' : 'out',
      }));
    }
    const mitigation = res.mitigation ?? [];
    if (mitigation.length > 0) {
      lines.push({ text: `MITIGATION — ${mitigation.length}`, type: 'sys' });
      mitigation.forEach((m: ReactMitigation) => lines.push({
        text: `  → ${m.remediation}`,
        type: 'out',
      }));
    }
    return lines;
  };

  // ---- Permission prompt answer: executes or refuses the pending engagement.
  const confirmPendingApproval = async (input: string) => {
    const decision = input.trim().toLowerCase();
    const pending = pendingApproval;
    setPendingApproval(null);
    if (!pending) return;
    setTermBusy(true);
    setTermLines(prev => [
      ...prev,
      { text: `$ ${decision}`, type: 'in' },
      { text: `ARK AGENT — executing ${pending.target} engagement…`, type: 'sys' },
    ]);
    try {
      const res = await api.confirmAgentTask(pending.sessionId, decision);
      const lines = renderPentestTask(res);
      if (res.status === 'rejected') {
        lines.push({ text: `  (nothing executed — engagement closed)`, type: 'sys' });
      }
      setTermLines(prev => [...prev, ...lines]);
    } catch (err) {
      setTermLines(prev => [...prev, {
        text: `ARK AGENT error: ${err instanceof Error ? err.message : String(err)}`,
        type: 'err',
      }]);
    } finally {
      setTermBusy(false);
    }
  };

  const renderAgentResult = (res: AgentTaskResponse) => {
    const lines: TerminalLine[] = [];
    if (res.status === 'needs_approval' && res.kind === 'pentest' && res.session_id) {
      lines.push({
        text: `ARK AGENT: ${res.ask ?? `Use the planned tools on ${res.target ?? 'the authorized scope'}? [always / now / deny]`}`,
        type: 'out',
      });
      setTermLines(prev => [...prev, ...lines]);
      setPendingApproval({
        sessionId: res.session_id,
        tools: res.tools ?? [],
        target: res.target ?? '',
      });
      return;
    }
    if (res.kind === 'pentest') {
      lines.push(...renderPentestTask(res));
    } else {
      if (res.tool_calls && res.tool_calls.length > 0) {
        res.tool_calls.forEach(c => {
          const state = c.status === 'ran' ? 'ran' : c.status;
          lines.push({
            text: `  [${c.step_id}] ${c.tool_id} — ${state}: ${c.message}`,
            type: c.status === 'ran' ? 'out' : c.status === 'failed' ? 'err' : 'out',
          });
        });
      }
      if (res.answer) {
        res.answer
          .split('\n')
          .filter(Boolean)
          .forEach((l, i) => {
            lines.push({
              text: `${i === 0 ? 'ARK AGENT: ' : '           '}${l}`,
              type: 'out',
            });
          });
      }
    }
    setTermLines(prev => [...prev, ...lines]);

    if (res.observations && res.observations.length > 0) {
      const obs = res.observations.map(o => ({
        type: o.type,
        status: o.status,
        layer: o.layer,
        label: o.label,
        detail: o.detail,
        source: 'tool_inference' as const,
        confidence: o.confidence ?? null,
      }));
      inv.appendCaseObservations(obs, {
        domain: 'cases',
        title: `Agent ${res.task_id}${res.target_path ? ` — ${res.target_path}` : ''}`,
      });
      inv.pushTerminal('ok', `${obs.length} observation(s) folded into case ${inv.activeCase?.id ?? '(new case)'} — audit logged.`);
    } else if (res.tool_calls && res.tool_calls.length > 0 && res.kind !== 'pentest') {
      inv.pushTerminal('warn', 'Agent produced no foldable observations.');
    }
  };

  /** Non-streaming fallback (backend without SSE support or EventSource error). */
  const runAgentTaskDirect = async (raw: string, targetPath?: string) => {
    const res = await api.runAgentTask(
      targetPath
        ? `Inspect the local directory '${targetPath}' under the sandbox root and report what is there.`
        : raw,
      targetPath,
    );
    renderAgentResult(res);
  };

  const runAgentTask = (raw: string, targetPath?: string) => {
    setTermBusy(true);
    setTermLines(prev => [
      ...prev,
      { text: `$ ${raw}`, type: 'in' },
      { text: 'ARK AGENT — streaming ReAct loop…', type: 'sys' },
    ]);

    const prompt = targetPath
      ? `Inspect the local directory '${targetPath}' under the sandbox root and report what is there.`
      : raw;

    const fallback = (err?: unknown) => {
      runAgentTaskDirect(raw, targetPath).catch(fallbackErr => {
        const msg = fallbackErr instanceof Error ? fallbackErr.message : String(fallbackErr);
        setTermLines(prev => [...prev, { text: `ARK AGENT error: ${msg}`, type: 'err' }]);
      }).finally(() => setTermBusy(false));
    };

    api.runAgentTaskStream(prompt, targetPath)
      .then(stream => {
        let done = false;
        const es = openAgentTaskEvents(
          stream.task_id,
          (ev) => {
            if (ev.event === 'tool_started') {
              const stepId = String(ev.step_id ?? '');
              const toolId = String(ev.tool_id ?? '');
              const args = ev.arguments as Record<string, unknown> | undefined;
              const argsStr = args ? ` ${JSON.stringify(args)}` : '';
              setTermLines(prev => [...prev, { text: `  [${stepId}] AGENT → ${toolId}${argsStr}`, type: 'sys' }]);
            } else if (ev.event === 'tool_done') {
              const elapsed = Number(ev.elapsed_ms) || 0;
              const status = String(ev.status ?? '');
              const message = String(ev.message ?? '');
              setTermLines(prev => [...prev, { text: `  [${ev.step_id}] AGENT ← ${status} (${elapsed}ms) ${message}`, type: status === 'ran' ? 'out' : 'err' }]);
            } else if (ev.event === 'result') {
              done = true;
              es.close();
              const res = ev.result as AgentTaskResponse;
              renderAgentResult(res);
              setTermBusy(false);
            }
          },
          () => {
            if (!done) { done = true; fallback(); }
          },
        );
      })
      .catch(() => fallback())
      .catch(() => setTermBusy(false));
  };

  // ---- AI Investigation handlers (Phase C/D/E) — delegated to the shared
  // investigation context so the workspace can launch investigations too.
  const startInvestigation = (file: File) => inv.startInvestigation(file, {
    goal: 'verify_location_credibility',
    subject: file.name,
    domain: 'image',
    claims_to_verify: [{ field: 'gps.latitude' }],
  });

  const handleInvFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (f) startInvestigation(f);
  };

  const handleApprove = () => inv.approveInvestigation();

  const handleResume = () => inv.resumeInvestigation(resumeSteps);

  const handleRefresh = () => inv.refreshInvestigation();

  // Derive problems from the shared findings + legacy result anomalies.
  const problems = React.useMemo(() => {
    const list: { type: string; msg: string; severity: string }[] = [];
    inv.findings.forEach(f => {
      if (f.status !== 'OK') list.push({ type: f.type, msg: f.message, severity: f.status === 'ERROR' ? 'error' : 'warning' });
    });
    if (session) {
      session.gaps
        .filter(g => !g.resolved && g.gap_type === 'open_contradiction')
        .forEach(g => list.push({ type: 'CONTRADICTION', msg: g.rationale, severity: 'error' }));
    }
    if (result?.exif_missing && list.length === 0) list.push({ type: 'Metadata', msg: 'EXIF metadata stripped/missing', severity: 'warning' });
    if (result?.steganography_detected) list.push({ type: 'Structure', msg: `Trailing bytes after EOF (${result.trailing_bytes_count})`, severity: 'error' });
    if (result?.gps_spoofing_detected) list.push({ type: 'GPS', msg: `Spoofing suspected (anomaly ${Math.round((result.anomaly_score || 0) * 100)}%)`, severity: 'error' });
    return list;
  }, [inv.findings, result, session]);

  const analysisLog = inv.activeRun?.analysisLog || result?.analysis_log || [];
  const cert = result?.custody_certificate;

  // Live backend Event Bus feed -> ANALYSIS LOG tab (cross-tab reactivity).
  const bus = useArkBus();
  const [busLog, setBusLog] = useState<string[]>([]);
  useEffect(() => {
    return bus.subscribe((ev) => {
      const t = ev.type || ev.event || 'event';
      if (t === 'tool.start' || t === 'tool.output' || t === 'agent.status' || t === 'session' || t === 'done' || t === 'error') {
        let msg = '';
        if (t === 'tool.start') msg = `▶ ${ev.tool} ${ev.workspace ? `[${ev.workspace}]` : ''}`;
        else if (t === 'tool.output') msg = `  ✓ ${ev.tool} → ${ev.output?.substring?.(0, 80) ?? ''}`;
        else if (t === 'agent.status') msg = `◈ agent: ${ev.status}`;
        else if (t === 'session') msg = `» session ${ev.session_id}${ev.workspace ? ` [${ev.workspace}]` : ''}`;
        else if (t === 'error') msg = `✗ ${ev.message}`;
        else msg = t;
        if (msg) setBusLog((p) => p.concat(msg).slice(-120));
      }
    });
  }, [bus]);

  const tabs: { id: BottomTab; label: string }[] = [
    { id: 'problems', label: 'PROBLEMS' },
    { id: 'log', label: 'ANALYSIS LOG' },
    { id: 'plan', label: 'PLAN' },
    { id: 'agent', label: 'AGENT' },
    { id: 'evidence', label: 'EVIDENCE' },
    { id: 'audit', label: 'AUDIT' },
    { id: 'terminal', label: 'TERMINAL' },
  ];

  const Icon = (id: BottomTab) => {
    const C = CONSOLE_ICONS[id];
    return <C className="w-3 h-3" />;
  };

  const statusClass = (s: string) => (s === 'done' ? 'inv-status-ok' : s === 'paused' ? 'inv-status-pause' : s === 'running' ? 'inv-status-run' : 'inv-status-idle');

  const renderPlan = () => {
    if (!session) {
      return (
        <div className="inv-empty">
          <div className="inv-empty-title">AI INVESTIGATION</div>
          <div className="inv-empty-hint">Start an adaptive investigation: pick an evidence image, approve the model's plan, and the agent re-plans on every detected gap or contradiction.</div>
          {invError && <div className="inv-error">{invError}</div>}
          <button className="inv-btn inv-btn-primary" disabled={invBusy} onClick={() => invFileRef.current?.click()}>
            {invBusy ? 'Starting…' : 'Start AI Investigation'}
          </button>
          <input ref={invFileRef} type="file" accept="image/jpeg,image/png" onChange={handleInvFile} style={{ display: 'none' }} />
        </div>
      );
    }
    const s = session;
    const est = s.plan.budget_estimate;
    return (
      <div className="bottom-list">
        {invError && <div className="inv-error">{invError}</div>}
        <div className="inv-header">
          <span className={`inv-status ${statusClass(s.status)}`}>{s.status.toUpperCase()}</span>
          {s.pause_reason && <span className="inv-pause-reason">{s.pause_reason}</span>}
          <span className="inv-mono">iterations={s.iterations} · planner={s.planner_source}</span>
        </div>

        <div className="inv-section-title">OBJECTIVE</div>
        <div className="inv-row"><span className="bottom-row-type mono">GOAL</span><span className="bottom-row-msg">{s.objective.goal}</span></div>
        <div className="inv-row"><span className="bottom-row-type mono">SUBJECT</span><span className="bottom-row-msg">{s.objective.subject}</span></div>
        <div className="inv-row"><span className="bottom-row-type mono">DOMAIN</span><span className="bottom-row-msg">{s.objective.domain}</span></div>
        {s.objective.claims_to_verify.map(c => (
          <div className="inv-row" key={c.field}><span className="bottom-row-type mono">CLAIM</span><span className="bottom-row-msg">{c.field}{c.value ? ` = ${c.value}` : ''}</span></div>
        ))}
        {s.objective.natural_language && (
          <div className="inv-row"><span className="bottom-row-type mono">GOAL</span><span className="bottom-row-msg">{s.objective.natural_language}</span></div>
        )}

        <div className="inv-section-title">PLAN — {s.plan.revision_id}</div>
        <div className="inv-row"><span className="bottom-row-type mono">HASH</span><span className="bottom-row-msg mono">{s.plan.hash.slice(0, 24)}…</span></div>
        {s.plan.parent_revision_id && <div className="inv-row"><span className="bottom-row-type mono">PARENT</span><span className="bottom-row-msg mono">{s.plan.parent_revision_id}</span></div>}
        {s.plan.delta_reason && <div className="inv-row"><span className="bottom-row-type mono">DELTA</span><span className="bottom-row-msg">{s.plan.delta_reason}</span></div>}
        {est && (
          <div className="inv-row"><span className="bottom-row-type mono">BUDGET</span>
            <span className="bottom-row-msg">{est.estimated_steps} steps · {est.estimated_api_calls} api · {Math.round(est.estimated_ms / 1000)}s est{est.budget ? ` · cap ${est.budget.max_steps} steps` : ''}</span>
          </div>
        )}
        {s.plan.steps.map((st, i) => (
          <div className="inv-row" key={st.step_id}>
            <span className={`bottom-row-type mono inv-step-status inv-step-${st.status}`}>{st.status}</span>
            <span className="bottom-row-msg"><strong className="mono">{st.tool_id}</strong>{st.rationale ? ` — ${st.rationale}` : ''}</span>
            <span className="inv-mono">{st.step_id}</span>
          </div>
        ))}
        {s.revisions.length > 1 && (
          <>
            <div className="inv-section-title">MERGED PLAN ({s.merged_plan.count} steps across {s.revisions.length} revisions)</div>
            {s.merged_plan.steps.map((m, i) => (
              <div className="inv-row" key={`${m.tool_id}-${i}`}>
                <span className={`bottom-row-type mono inv-step-status inv-step-${m.status}`}>{m.status}</span>
                <span className="bottom-row-msg"><strong className="mono">{m.tool_id}</strong>{m.rationale ? ` — ${m.rationale}` : ''}</span>
                <span className="inv-mono" title={m.delta_reason || ''}>{m.revision_id.slice(0, 10)}</span>
              </div>
            ))}
          </>
        )}

        {s.status === 'proposed' && (
          <button className="inv-btn inv-btn-primary" disabled={invBusy} onClick={handleApprove}>
            {invBusy ? 'Running…' : <><Play className="w-3 h-3 inline" /> Approve Plan</>}
          </button>
        )}
        {s.status === 'paused' && (
          <div className="inv-resume">
            <label className="inv-mono" htmlFor="inv-resume-steps">max_steps:</label>
            <input id="inv-resume-steps" className="inv-input mono" type="number" min={1} value={resumeSteps} onChange={e => setResumeSteps(Number(e.target.value) || 1)} />
            <button className="inv-btn inv-btn-primary" disabled={invBusy} onClick={handleResume}>
              {invBusy ? 'Continuing…' : <><PauseCircle className="w-3 h-3 inline" /> Resume</>}
            </button>
          </div>
        )}
        {(s.status === 'running' || s.status === 'done') && (
          <button className="inv-btn" disabled={invBusy} onClick={handleRefresh}>
            <RefreshCw className="w-3 h-3 inline" /> Refresh
          </button>
        )}

        {s.gaps.length > 0 && (
          <>
            <div className="inv-section-title">OPEN GAPS ({s.gaps.filter(g => !g.resolved).length}) · acted={s.acted_gap_ids.length}</div>
            {s.gaps.map((g: GraphGap) => (
              <div className={`inv-row inv-gap ${g.resolved ? 'inv-gap-resolved' : ''}`} key={g.gap_id}>
                <span className={`bottom-row-sev ${g.severity}`}>{g.resolved ? '✓' : g.severity === 'high' ? '✕' : '▲'}</span>
                <span className="bottom-row-type mono">{GAP_TYPE_LABEL[g.gap_type] || g.gap_type}</span>
                <span className="bottom-row-msg">{g.rationale}<span className="inv-mono"> · {g.addressable_by.join(', ')}</span></span>
              </div>
            ))}
          </>
        )}
      </div>
    );
  };

  const renderAgent = () => {
    if (!session) {
      return <div className="inv-empty"><div className="inv-empty-hint">No agent activity yet — start an AI investigation from the PLAN tab.</div></div>;
    }
    const s = session;
    const u = s.budget_usage;
    return (
      <div className="bottom-list">
        <div className="inv-header">
          <span className={`inv-status ${statusClass(s.status)}`}>{s.status.toUpperCase()}</span>
          <span className="inv-mono">iter={s.iterations} · {s.activity_log.length} tool calls{s.model_id ? ` · ${s.model_id}` : ''}</span>
        </div>

        <div className="inv-section-title">BUDGET CONSUMPTION</div>
        <div className="inv-row"><span className="bottom-row-type mono">STEPS</span><span className="bottom-row-msg">{u.steps} / {u.budget.max_steps}</span></div>
        <div className="inv-row"><span className="bottom-row-type mono">TOKENS</span><span className="bottom-row-msg">{u.tokens} / {u.budget.max_tokens}</span></div>
        <div className="inv-row"><span className="bottom-row-type mono">TIME</span><span className="bottom-row-msg">{Math.round(u.ms / 1000)}s / {Math.round(u.budget.max_ms / 1000)}s</span></div>
        <div className="inv-row"><span className="bottom-row-type mono">API</span><span className="bottom-row-msg">{u.api_calls} / {u.budget.max_api_calls}</span></div>

        <div className="inv-section-title">TOOL ACTIVITY</div>
        {s.activity_log.length === 0 ? (
          <div className="bottom-empty">No tools executed yet — approve the plan.</div>
        ) : s.activity_log.map((e, i) => (
          <div className="inv-row" key={i}>
            <span className={`bottom-row-type mono inv-step-${e.status}`}>{e.status.toUpperCase()}</span>
            <span className="bottom-row-msg"><strong className="mono">{e.tool_id}</strong> — {e.message}</span>
            <span className="inv-mono">{e.elapsed_ms}ms</span>
          </div>
        ))}
      </div>
    );
  };

  const renderEvidence = () => {
    if (!session) {
      // Legacy evidence hash view (no active investigation) + canonical
      // observations so the console reflects the complete live case state.
      return (
        <div className="bottom-list">
          {!inv.activeEvidence && !result ? <div className="bottom-empty">No evidence loaded for the active case</div> : (
            <>
              <div className="bottom-row"><span className="bottom-row-type mono">SHA-256</span><span className="bottom-row-msg mono">{inv.activeEvidence?.sha256 || result?.image_sha256}</span></div>
              {cert && <div className="bottom-row"><span className="bottom-row-type mono">SHA-1</span><span className="bottom-row-msg mono">{cert.sha1}</span></div>}
              {cert && <div className="bottom-row"><span className="bottom-row-type mono">MD5</span><span className="bottom-row-msg mono">{cert.md5}</span></div>}
              <div className="bottom-row"><span className="bottom-row-type mono">MIME</span><span className="bottom-row-msg mono">{inv.activeEvidence?.mimeType || result?.file_format || 'N/A'}</span></div>
              {inv.activeEvidence?.byteSize && <div className="bottom-row"><span className="bottom-row-type mono">BYTES</span><span className="bottom-row-msg mono">{inv.activeEvidence.byteSize}</span></div>}
              {result?.custody_hash && <div className="bottom-row"><span className="bottom-row-type mono">CUSTODY</span><span className="bottom-row-msg mono">{result.custody_hash}</span></div>}
              {result?.image_classification && (
                <div className="bottom-row"><span className="bottom-row-type mono">ASSET</span><span className="bottom-row-msg">{result.image_classification}</span></div>
              )}
              {observations.length > 0 && (
                <div className="inv-section-title">OBSERVATIONS ({observations.length})</div>
              )}
              {observations.length === 0 ? (
                <div className="bottom-empty">No structured observations recorded.</div>
              ) : observations.map(o => (
                <div className={`inv-row ${o.status === 'ANOMALY' ? 'inv-row-contra' : ''}`} key={o.id}>
                  <span className={`bottom-row-sev ${o.status === 'ANOMALY' ? 'high' : o.status === 'UNAVAILABLE' ? 'medium' : 'ok'}`}>
                    {o.status === 'ANOMALY' ? '✕' : o.status === 'UNAVAILABLE' ? '▲' : '•'}
                  </span>
                  <span className="bottom-row-type mono">{o.type}</span>
                  <span className="bottom-row-msg">{o.label}<span className="inv-mono"> · {o.layer}</span>{o.detail ? ` — ${o.detail}` : ''}</span>
                  <span className="inv-mono">{o.id}</span>
                </div>
              ))}
            </>
          )}
        </div>
      );
    }
    const s = session;
    const nodes = Object.values(s.graph.nodes);
    const evidenceNodes = nodes.filter((n: EvidenceNode) => n.tool_id !== 'audit');
    const auditNodes = nodes.filter((n: EvidenceNode) => n.tool_id === 'audit');
    const contradicts = s.graph.edges.filter((e: EvidenceEdge) => e.relation === 'contradicts');
    const corroborates = s.graph.edges.filter((e: EvidenceEdge) => e.relation === 'corroborates');
    const nodeLabel = (id: string) => s.graph.nodes[id]?.claim_type || id.slice(0, 10);

    return (
      <div className="bottom-list">
        <div className="inv-header">
          <span className={`inv-status ${statusClass(s.status)}`}>{s.status.toUpperCase()}</span>
          <span className="inv-mono">case={s.case_id} · {nodes.length} nodes · {s.graph.edges.length} edges</span>
        </div>

        <div className="inv-section-title">FINDINGS ({s.findings.length})</div>
        {s.findings.length === 0 ? (
          <div className="bottom-empty">No promoted findings yet.</div>
        ) : s.findings.map((f: InvestigationFinding) => (
          <div className="inv-row" key={f.finding_id}>
            <span className={`bottom-row-sev ${f.severity}`}>{f.severity === 'high' || f.severity === 'critical' ? '✕' : '▲'}</span>
            <span className="bottom-row-type mono">{f.claim_type.toUpperCase()}</span>
            <span className="bottom-row-msg">{f.claim} <span className="inv-mono">· {Math.round(f.confidence * 100)}% · {f.finding_type}</span></span>
          </div>
        ))}

        <div className="inv-section-title">CONTRADICTIONS ({contradicts.length})</div>
        {contradicts.length === 0 ? (
          <div className="bottom-empty">No contradictory evidence edges.</div>
        ) : contradicts.map((e: EvidenceEdge) => (
          <div className="inv-row inv-row-contra" key={e.edge_id}>
            <span className="bottom-row-type mono">CONTRADICTS</span>
            <span className="bottom-row-msg">{nodeLabel(e.src)} ⟂ {nodeLabel(e.dst)}</span>
            <span className="inv-mono">{e.weight}</span>
          </div>
        ))}

        <div className="inv-section-title">CORROBORATIONS ({corroborates.length})</div>
        {corroborates.map((e: EvidenceEdge) => (
          <div className="inv-row inv-row-corro" key={e.edge_id}>
            <span className="bottom-row-type mono">CORROBORATES</span>
            <span className="bottom-row-msg">{nodeLabel(e.src)} + {nodeLabel(e.dst)}</span>
          </div>
        ))}

        <div className="inv-section-title">EVIDENCE NODES ({evidenceNodes.length})</div>
        {evidenceNodes.map((n: EvidenceNode) => (
          <div className="inv-row" key={n.node_id}>
            <span className="bottom-row-type mono">{PROVENANCE_LABEL[n.provenance_type] || n.provenance_type.toUpperCase()}</span>
            <span className="bottom-row-msg"><strong className="mono">{n.tool_id}</strong> <span className="mono">[{n.claim_type}]</span> {n.claim}</span>
            <span className="inv-mono">{Math.round(n.confidence * 100)}%</span>
          </div>
        ))}
        <div className="inv-row"><span className="bottom-row-type mono">AUDIT</span><span className="bottom-row-msg">+ {auditNodes.length} tamper-evident tool-invocation records</span></div>

        {s.hypotheses.length > 0 && (
          <>
            <div className="inv-section-title">HYPOTHESES (unit 05)</div>
            {s.hypotheses.map(h => (
              <div className="inv-row" key={h.hypothesis_id}>
                <span className="bottom-row-type mono">HYPOTHESIS</span>
                <span className="bottom-row-msg">{h.claim}</span>
                <span className="inv-mono">{Math.round(h.confidence * 100)}%</span>
              </div>
            ))}
          </>
        )}

        {s.critiques.length > 0 && (
          <>
            <div className="inv-section-title">CRITIQUES (unit 06)</div>
            {s.critiques.map(c => (
              <div className="inv-row inv-row-contra" key={c.critique_id}>
                <span className="bottom-row-type mono">CHALLENGE</span>
                <span className="bottom-row-msg">target <span className="mono">{c.target_id.slice(0, 12)}</span> — {c.risks.join(' · ')}</span>
              </div>
            ))}
          </>
        )}
      </div>
    );
  };

  return (
    <div
      className={`bottom-panel ${collapsed ? 'bottom-panel-collapsed' : ''} ${dragState.current ? 'bottom-panel-dragging' : ''}`}
      style={collapsed ? undefined : { height: panelHeight }}
    >
      {!collapsed && <div className="bottom-resize-handle" onMouseDown={startResize} title="Drag to resize terminal height" />}
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
              {t.id === 'plan' && session && session.status !== 'done' && session.status !== 'paused' && <span className="bottom-tab-badge">{session.gaps.filter(g => !g.resolved).length}</span>}
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
              {analysisLog.length === 0 && busLog.length === 0 ? (
                <div className="bottom-empty">No analysis events yet for the active run</div>
              ) : (
                <>
                  {analysisLog.map((line, i) => (
                    <div key={`a-${i}`} className="bottom-log-line mono">{line}</div>
                  ))}
                  {busLog.map((line, i) => (
                    <div key={`b-${i}`} className="bottom-log-line mono bottom-log-live">{line}</div>
                  ))}
                </>
              )}
            </div>
          )}
          {tab === 'plan' && renderPlan()}
          {tab === 'agent' && renderAgent()}
          {tab === 'evidence' && renderEvidence()}
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
            <div className="bottom-terminal" onClick={() => termInputRef.current?.focus()}>
              <div className="bottom-terminal-header">
                <span className="bottom-terminal-title mono">ARK TERMINAL — SIGNALING / TOOL FEED</span>
                <button className="bottom-terminal-clear mono" onClick={() => { inv.clearTerminal(); setTermLines([]); }}>clear</button>
              </div>
              <div className="bottom-terminal-body">
                {caiInitialized && <CaiBanner />}
                {termLines.length === 0 && inv.terminal.length === 0 && !caiInitialized ? (
                  <div className="bottom-terminal-line bottom-terminal-sys mono">Terminal idle — type "help" for commands, or run a Telecom / Network / Vulnerability workflow to stream into this terminal.</div>
                ) : (
                  <>
                    {termLines.map((l, i) => {
                      if (l.type === 'tool' && l.tool) {
                        const t = l.tool;
                        const badge = t.status === 'completed' ? '✔ COMPLETED' : t.status === 'running' ? '⏳ RUNNING' : t.status === 'error' ? '✕ ERROR' : '✕ DENIED';
                        return (
                          <div key={`c-${i}`} className="bottom-terminal-line bottom-terminal-tool mono">
                            <span className="cai-dot">●</span>
                            <span className="cai-agent">[ARK]</span>
                            <span className="cai-sep"> — </span>
                            <span className="cai-tool">{t.name}</span>
                            <span className="cai-args">({t.args})</span>
                            {t.status !== 'running' && <span className="cai-time"> ⏱ {t.elapsed}</span>}
                            <span className={`cai-badge cai-badge-${t.status}`}> [ {badge} ]</span>
                          </div>
                        );
                      }
                      if (l.type === 'hitl' && l.hitl) {
                        // Dynamic HITL overlay — reads the parsed tool name and
                        // argument object from the stream (no hardcoded target).
                        const hl = l.hitl;
                        const argStr = formatArgs(hl.args || {});
                        return (
                          <div key={`c-${i}`} className="bottom-terminal-line bottom-terminal-hitl mono">
                            {hl.prompt ? (
                              <span className="cai-hitl-q">{hl.prompt}</span>
                            ) : (
                              <>
                                <span className="cai-hitl-q">? ARK: requests approval to run:</span>
                                <span className="cai-hitl-tool"> {hl.tool}</span>
                                {argStr && <span className="cai-hitl-target"> ({argStr})</span>}
                              </>
                            )}
                          </div>
                        );
                      }
                      return (
                        <div key={`c-${i}`} className={`bottom-terminal-line bottom-terminal-${l.type} mono`}>{l.text}</div>
                      );
                    })}
                    {inv.terminal.map(l => (
                      <div key={l.id} className={`bottom-terminal-line bottom-terminal-${l.level === 'err' ? 'err' : l.level === 'ok' || l.level === 'warn' ? 'out' : 'sys'} mono`}>
                        <span className="bottom-terminal-ts">{l.ts}</span> {l.text}
                      </div>
                    ))}
                    {streamLine != null && (
                      <div className="bottom-terminal-line bottom-terminal-out mono">
                        {streamLine}<span className="cai-cursor">▋</span>
                      </div>
                    )}
                    {termBusy && streamLine == null && (
                      <div className="bottom-terminal-line bottom-terminal-sys mono">
                        {busyGlyph} ARK — preparing context and calling the model…
                      </div>
                    )}
                  </>
                )}
                <div ref={termEndRef} />
              </div>
              <div className="bottom-terminal-input-row">
                {pendingCaiApproval && (
                  <div className="bottom-hitl-row">
                    <span className="bottom-hitl-label mono">ARK HITL — authorize tool execution?</span>
                    <button
                      className="bottom-hitl-btn bottom-hitl-yes"
                      onClick={() => caiApprove('approve')}
                    >Y — Approve</button>
                    <button
                      className="bottom-hitl-btn bottom-hitl-always"
                      onClick={() => caiApprove('allow_always')}
                    >A — Allow Always</button>
                    <button
                      className="bottom-hitl-btn bottom-hitl-no"
                      onClick={() => caiApprove('deny')}
                    >N — Deny</button>
                  </div>
                )}
                {slashMenu.length > 0 && (
                  <div className="bottom-slash-menu">
                    <div className="bottom-slash-head mono">ARK UNIFIED COMMANDS</div>
                    {slashMenu.map((c, i) => (
                      <div
                        key={c.name}
                        className={`bottom-slash-item ${i === slashIndex ? 'bottom-slash-active' : ''}`}
                        onMouseDown={(e) => { e.preventDefault(); setTermInput(`/${c.name} `); setSlashMenu([]); }}
                      >
                        <span className="bottom-slash-name mono">/{c.name}</span>
                        <span className="bottom-slash-group mono">{c.group}</span>
                        <span className="bottom-slash-desc">{c.description}</span>
                      </div>
                    ))}
                  </div>
                )}
                <span className="bottom-terminal-prompt mono">$</span>
                <input
                  id="ark-term-input"
                  ref={termInputRef}
                  className="bottom-terminal-input mono"
                  value={termInput}
                  onChange={e => setTermInput(e.target.value)}
                  onKeyDown={e => {
                    // HITL single-key approval surfaced by the CAI engine.
                    if (pendingCaiApproval) {
                      if (e.key === 'Enter' || e.key === 'y' || e.key === 'Y') {
                        e.preventDefault();
                        caiApprove('approve');
                      } else if (e.key === 'a' || e.key === 'A') {
                        e.preventDefault();
                        caiApprove('allow_always');
                      } else if (e.key === 'n' || e.key === 'N') {
                        e.preventDefault();
                        caiApprove('deny');
                      }
                      return;
                    }
                    // Slash-command autocomplete navigation (arrow keys / Tab).
                    if (slashMenu.length > 0) {
                      if (e.key === 'ArrowDown') {
                        e.preventDefault();
                        setSlashIndex(i => (i + 1) % slashMenu.length);
                        return;
                      }
                      if (e.key === 'ArrowUp') {
                        e.preventDefault();
                        setSlashIndex(i => (i - 1 + slashMenu.length) % slashMenu.length);
                        return;
                      }
                      if (e.key === 'Tab' || (e.key === 'Enter' && termInput.endsWith('/') === false && termInput.startsWith('/'))) {
                        e.preventDefault();
                        const sel = slashMenu[slashIndex] ?? slashMenu[0];
                        setTermInput(`/${sel.name} `);
                        setSlashMenu([]);
                        return;
                      }
                    }
                    if (e.key === 'Enter') {
                      const input = termInput;
                      setTermInput('');
                      setSlashMenu([]);
                      if (pendingApproval) {
                        confirmPendingApproval(input);
                      } else {
                        runCommand(input);
                      }
                      requestAnimationFrame(() => termInputRef.current?.focus());
                    }
                  }}
                  placeholder={pendingApproval ? 'type: always / now / deny' : pendingCaiApproval ? '[Y/n/A]' : 'type a command or / for ARK commands (help)'}
                  autoComplete="off"
                  autoCapitalize="off"
                  spellCheck={false}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
