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
 */
import React, { useState, useRef, useEffect } from 'react';
import { ChevronUp, ChevronDown, RefreshCw, Play, PauseCircle } from 'lucide-react';
import { useInvestigation } from './useInvestigation';
import { CONSOLE_ICONS } from './icons';
import { useArkBus } from './ArkBusContext';
import type {
  InvestigationSession,
  GraphGap,
  EvidenceEdge,
  EvidenceNode,
  InvestigationFinding,
  Observation,
} from '../../types';

type BottomTab = 'problems' | 'log' | 'plan' | 'agent' | 'evidence' | 'audit';

interface BottomPanelProps {
  collapsed: boolean;
  onToggle: () => void;
  /** Optional legacy result for tools that still feed hashes/log directly. */
  result?: import('../../types').AnalyzeResponse | null;
  /** Single-tool inspector rendering (the `+` menu surface) — no internal tab bar. */
  inspector?: boolean;
  /** Kept for API symmetry; the ARK shell owns the inspector close control. */
  onClose?: () => void;
}

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

export function BottomPanel({ collapsed, onToggle, result, docked = false, inspector = false, onClose }: BottomPanelProps & { docked?: boolean; inspector?: boolean; onClose?: () => void }) {
  const inv = useInvestigation();
  // The active bottom-console tab is shared via the investigation context so
  // the Investigation workspace can focus the console (e.g. PLAN after
  // "Investigate Next") without duplicating state.
  const tab = inv.bottomTab as BottomTab;
  const setTab = (t: BottomTab) => inv.setBottomTab(t);

  // ---- Console height — drag-to-resize, persisted across sessions.
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

        {s.model_decision?.spec && (
          <div className="inv-row" title={s.model_decision.reason}>
            <span className="bottom-row-type mono">MODEL</span>
            <span className="bottom-row-msg mono">
              {s.model_decision.spec.model_id}
              {s.model_decision.spec.local ? ' · local' : ' · cloud'}
              {s.model_decision.forced_local ? ' · forced-local' : ''}
              {s.model_decision.fallback_used ? ' · fallback' : ''}
            </span>
          </div>
        )}

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

  const renderProblems = () => (
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
  );

  const renderLog = () => (
    <div className="bottom-list bottom-log">
      {analysisLog.length === 0 && busLog.length === 0 && inv.terminal.length === 0 ? (
        <div className="bottom-empty">No analysis events yet for the active run</div>
      ) : (
        <>
          {analysisLog.map((line, i) => (
            <div key={`a-${i}`} className="bottom-log-line mono">{line}</div>
          ))}
          {busLog.map((line, i) => (
            <div key={`b-${i}`} className="bottom-log-line mono bottom-log-live">{line}</div>
          ))}
          {inv.terminal.map(l => (
            <div key={l.id} className={`bottom-log-line mono bottom-log-live bottom-log-${l.level}`}>
              <span className="bottom-log-ts">{l.ts}</span> {l.text}
            </div>
          ))}
        </>
      )}
    </div>
  );

  const renderAudit = () => (
    <div className="bottom-list">
      {inv.auditTrail.length === 0 ? <div className="bottom-empty">No audit entries for the active case</div> : inv.auditTrail.map(e => (
        <div key={e.id} className="bottom-row">
          <span className="bottom-row-type mono">{new Date(e.timestamp).toLocaleTimeString()}</span>
          <span className="bottom-row-msg"><strong>{e.action}</strong> — {e.detail}</span>
        </div>
      ))}
    </div>
  );

  // ---- Inspector mode: render exactly one tool's content. The surrounding
  // ARK inspector shell (in ArkControl) owns the header/close chrome, and the
  // content comes from the same render functions as the docked console, so no
  // functionality is duplicated.
  if (inspector) {
    return (
      <div className="bottom-panel bottom-panel-inspector">
        <div className="bottom-panel-content bottom-inspector-content">
          {tab === 'problems' && renderProblems()}
          {tab === 'log' && renderLog()}
          {tab === 'plan' && renderPlan()}
          {tab === 'agent' && renderAgent()}
          {tab === 'evidence' && renderEvidence()}
          {tab === 'audit' && renderAudit()}
        </div>
      </div>
    );
  }

  return (
    <div
      className={`bottom-panel ${docked ? 'bottom-panel-docked' : ''} ${collapsed ? 'bottom-panel-collapsed' : ''} ${dragState.current ? 'bottom-panel-dragging' : ''}`}
      style={collapsed || docked ? undefined : { height: panelHeight }}
    >
      {!collapsed && !docked && <div className="bottom-resize-handle" onMouseDown={startResize} title="Drag to resize console height" />}
      <div className="bottom-panel-header">
        <div className="bottom-panel-tabs">
          {tabs.map(t => (
            <button
              key={t.id}
              aria-pressed={tab === t.id}
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
        {!docked && <button className="bottom-panel-toggle" onClick={onToggle} title={collapsed ? 'Expand panel' : 'Collapse panel'}>
          {collapsed ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>}
      </div>
      {!collapsed && (
        <div className="bottom-panel-content">
          {tab === 'problems' && renderProblems()}
          {tab === 'log' && renderLog()}
          {tab === 'plan' && renderPlan()}
          {tab === 'agent' && renderAgent()}
          {tab === 'evidence' && renderEvidence()}
          {tab === 'audit' && renderAudit()}
        </div>
      )}
    </div>
  );
}
