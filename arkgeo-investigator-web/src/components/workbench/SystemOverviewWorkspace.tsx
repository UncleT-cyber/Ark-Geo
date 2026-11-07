/**
 * SystemOverviewWorkspace — THE ARK's standalone System Overview.
 *
 * A system-level destination (not an investigation). It renders the
 * principal-scoped operational aggregate from `GET /api/v1/overview`:
 * KPIs, operational activity, live agents, inference-engine health, security &
 * evidence posture and recent execution traces.
 *
 * Truthfulness contract: every value is real backend data. A metric that is
 * not measured renders as `—` (never a fabricated 0); a measured zero renders
 * as `0`. When the aggregate cannot be reached the surface says so rather than
 * showing stale or invented numbers.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, Bot, CheckCircle2, ChevronDown, ChevronRight, Cpu, Database,
  Gauge, RefreshCw, ShieldCheck, TriangleAlert, Workflow, XCircle,
} from 'lucide-react';
import { api } from '../../api';

type Period = '24h' | '7d' | '30d';

type Overview = Awaited<ReturnType<typeof api.systemOverview>>;

const PERIODS: { id: Period; label: string }[] = [
  { id: '24h', label: '24 hours' },
  { id: '7d', label: '7 days' },
  { id: '30d', label: '30 days' },
];

/** Render a measured value; `null`/`undefined` means "not measured" → em dash. */
function metric(value: number | null | undefined, format?: (n: number) => string): string {
  if (value === null || value === undefined) return '—';
  return format ? format(value) : String(value);
}

function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return `${Math.round(value * 100)}%`;
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const delta = Date.now() - then;
  const sec = Math.round(delta / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.round(hr / 24)}d ago`;
}

function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—';
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  return `${Math.round(s / 60)} min`;
}

function humanize(value: string | null | undefined): string {
  if (!value) return '—';
  return value
    .replace(/^SpecialistRole\./, '')
    .replace(/[._]/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
}

const STATUS_CLASS: Record<string, string> = {
  completed: 'so-status-ok',
  running: 'so-status-live',
  stopping: 'so-status-warn',
  failed: 'so-status-bad',
  interrupted: 'so-status-bad',
  cancelled: 'so-status-muted',
};

export function SystemOverviewWorkspace() {
  const [period, setPeriod] = useState<Period>('24h');
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedTrace, setExpandedTrace] = useState<string | null>(null);
  const [refreshedAt, setRefreshedAt] = useState<number>(Date.now());

  const load = useCallback(async (p: Period) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.systemOverview(p, 25);
      setData(result);
      setRefreshedAt(Date.now());
    } catch (err: any) {
      // A bare "Not Found" means the backend did not serve this route — almost
      // always an unreachable/mismatched backend, not a missing dashboard.
      // Say so plainly instead of echoing the raw FastAPI detail.
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail;
      const message = status === 404
        ? 'the overview endpoint was not found (is the backend running and reachable?)'
        : typeof detail === 'string' && detail ? detail
        : err?.message || 'System overview unavailable';
      setError(message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(period); }, [load, period]);

  const kpis = data?.kpis;
  const series = data?.activity.series ?? [];
  const maxSeries = useMemo(
    () => Math.max(1, ...series.map(b => b.count)),
    [series],
  );

  const modelRoute = data?.model;
  const usage = data?.usage;
  const security = data?.security;
  const evidence = data?.evidence;

  return (
    <div className="sys-overview">
      {/* A. Header ------------------------------------------------------- */}
      <header className="so-header">
        <div className="so-header-copy">
          <div className="so-header-eyebrow mono">Integrated Security Environment</div>
          <h1>System Overview</h1>
          <p>Operational posture across investigations, agents, inference and evidence custody.</p>
        </div>
        <div className="so-header-actions">
          <div className="so-period" role="group" aria-label="Reporting period">
            {PERIODS.map(p => (
              <button
                key={p.id}
                type="button"
                className={`so-period-btn ${period === p.id ? 'so-period-active' : ''}`}
                aria-pressed={period === p.id}
                onClick={() => setPeriod(p.id)}
              >
                {p.label}
              </button>
            ))}
          </div>
          <button type="button" className="so-refresh" onClick={() => void load(period)} disabled={loading} title="Refresh">
            <RefreshCw size={14} className={loading ? 'so-spin' : undefined} />
            <span>Refresh</span>
          </button>
        </div>
      </header>

      {error && (
        <div className="so-banner so-banner-error" role="alert">
          <TriangleAlert size={15} />
          <span>System overview unavailable — {error}</span>
          <button type="button" onClick={() => void load(period)}>Retry</button>
        </div>
      )}

      {loading && !data && (
        <div className="so-loading">
          <RefreshCw size={16} className="so-spin" />
          <span>Loading operational data…</span>
        </div>
      )}

      {/* B. KPI row ------------------------------------------------------ */}
      <section className="so-kpi-row" aria-label="Key metrics">
        <article className="so-kpi">
          <span className="so-kpi-icon"><Workflow size={15} /></span>
          <span className="so-kpi-label">Investigations</span>
          <span className="so-kpi-value">{metric(kpis?.investigations.total)}</span>
          <span className="so-kpi-sub">
            {kpis ? `${kpis.investigations.active} active` : '—'}
          </span>
        </article>

        <article className="so-kpi">
          <span className="so-kpi-icon"><Bot size={15} /></span>
          <span className="so-kpi-label">Active Agents</span>
          <span className="so-kpi-value">{metric(kpis?.active_agents.running)}</span>
          <span className="so-kpi-sub">
            {kpis ? `${kpis.active_agents.idle} idle sessions` : '—'}
          </span>
        </article>

        <article className="so-kpi">
          <span className="so-kpi-icon"><Activity size={15} /></span>
          <span className="so-kpi-label">Tool Executions</span>
          <span className="so-kpi-value">{metric(kpis?.tool_executions.total)}</span>
          <span className="so-kpi-sub">
            {kpis ? `${percent(kpis.tool_executions.success_rate)} success · ${kpis.tool_executions.failed} failed` : '—'}
          </span>
        </article>

        <article className="so-kpi">
          <span className="so-kpi-icon"><ShieldCheck size={15} /></span>
          <span className="so-kpi-label">Approvals Requested</span>
          <span className="so-kpi-value">{metric(kpis?.pending_approvals.count)}</span>
          <span className="so-kpi-sub">in period</span>
        </article>
      </section>

      {/* C. Operational activity + agent activity ------------------------ */}
      <section className="so-grid so-grid-2">
        <article className="so-card">
          <header className="so-card-header">
            <span className="so-card-title"><Activity size={14} /> Operational Activity</span>
            <span className="so-card-sub">{PERIODS.find(p => p.id === period)?.label} · {series.reduce((t, b) => t + b.count, 0)} runs</span>
          </header>
          {series.length === 0 ? (
            <div className="so-empty">No activity recorded in this period.</div>
          ) : (
            <div className="so-chart" role="img" aria-label="Run activity by interval">
              {series.map((b, i) => {
                const label = new Date(b.start).toLocaleString(undefined,
                  period === '24h' ? { hour: '2-digit' } : { month: 'short', day: 'numeric' });
                return (
                  <div key={i} className="so-chart-col" title={`${label}: ${b.count} runs${b.failed ? ` · ${b.failed} failed` : ''}`}>
                    <div className="so-chart-bar-wrap">
                      <div className={`so-chart-bar ${b.failed ? 'so-chart-bar-has-fail' : ''}`}
                        style={{ height: `${(b.count / maxSeries) * 100}%`, opacity: b.count ? 1 : 0.12 }} />
                    </div>
                    {(i % (period === '24h' ? 3 : 2) === 0) && <div className="so-chart-label mono">{label}</div>}
                  </div>
                );
              })}
            </div>
          )}
        </article>

        <article className="so-card">
          <header className="so-card-header">
            <span className="so-card-title"><Bot size={14} /> Agent Activity</span>
            <span className="so-card-sub">{data?.agents.length ?? 0} live</span>
          </header>
          {!data || data.agents.length === 0 ? (
            <div className="so-empty">No agents are running right now.</div>
          ) : (
            <ul className="so-agent-list">
              {data.agents.map(a => (
                <li key={a.run_id} className="so-agent-row">
                  <span className={`so-agent-dot ${STATUS_CLASS[a.status] ?? 'so-status-muted'}`} />
                  <span className="so-agent-role">{humanize(a.agent)}</span>
                  <span className="so-agent-mode mono">{a.mode ?? 'auto'}</span>
                  <span className="so-agent-state">{a.stop_requested ? 'stopping' : a.status}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="so-agent-foot">
            <span>Execution modes</span>
            <span className="mono">{security?.execution_modes.length ? security.execution_modes.join(', ') : '—'}</span>
          </div>
        </article>
      </section>

      {/* D. Inference engine --------------------------------------------- */}
      <section className="so-grid so-grid-2">
        <article className="so-card">
          <header className="so-card-header">
            <span className="so-card-title"><Cpu size={14} /> Inference Engine</span>
            <span className={`so-pill ${modelRoute?.available ? 'so-pill-ok' : 'so-pill-bad'}`}>
              {modelRoute?.available ? 'ready' : 'unavailable'}
            </span>
          </header>
          <dl className="so-kv">
            <div><dt>Active model</dt><dd className="mono">{modelRoute?.model ?? '—'}</dd></div>
            <div><dt>Provider</dt><dd>{modelRoute?.provider ?? '—'}</dd></div>
            <div><dt>Credential</dt><dd>{modelRoute?.credential_source ?? '—'}</dd></div>
            <div><dt>Route</dt><dd>{modelRoute?.route_status ?? '—'}</dd></div>
          </dl>
          {modelRoute?.routing_reason && <p className="so-note">{modelRoute.routing_reason}</p>}
          {modelRoute?.error && <p className="so-note so-note-error">{modelRoute.error}</p>}
          {data && data.providers.length > 0 && (
            <ul className="so-provider-list">
              {data.providers.map(p => (
                <li key={p.provider} className="so-provider-row">
                  {p.probed
                    ? <CheckCircle2 size={13} className="so-provider-ok" />
                    : p.configured
                      ? <Gauge size={13} className="so-provider-warn" />
                      : <XCircle size={13} className="so-provider-off" />}
                  <span className="so-provider-name">{p.provider}</span>
                  <span className="so-provider-detail mono">{p.latency_ms != null ? `${p.latency_ms} ms` : (p.detail ?? '—')}</span>
                </li>
              ))}
            </ul>
          )}
        </article>

        <article className="so-card">
          <header className="so-card-header">
            <span className="so-card-title"><Database size={14} /> Compute & Usage</span>
            <span className="so-card-sub">{usage ? `${usage.requests} requests` : '—'}</span>
          </header>
          <dl className="so-kv">
            <div><dt>Local inference</dt><dd>{metric(usage?.local_inference_runs)}</dd></div>
            <div><dt>Cloud inference</dt><dd>{metric(usage?.cloud_inference_runs)}</dd></div>
            <div><dt>Input tokens</dt><dd>{metric(usage?.input_tokens)}</dd></div>
            <div><dt>Output tokens</dt><dd>{metric(usage?.output_tokens)}</dd></div>
            <div><dt>Estimated cost</dt><dd>{usage?.cost_usd != null ? `$${usage.cost_usd}` : '—'}</dd></div>
          </dl>
          {usage?.note && <p className="so-note so-note-muted">{usage.note}</p>}
        </article>
      </section>

      {/* E. Security & evidence ------------------------------------------ */}
      <section className="so-grid so-grid-2">
        <article className="so-card">
          <header className="so-card-header">
            <span className="so-card-title"><ShieldCheck size={14} /> Security & Custody</span>
            <span className={`so-pill ${security?.scope_active ? 'so-pill-ok' : 'so-pill-muted'}`}>
              {security?.scope_active ? 'scope active' : 'no scope'}
            </span>
          </header>
          <dl className="so-kv">
            <div><dt>Approvals requested</dt><dd>{metric(security?.pending_approvals)}</dd></div>
            <div><dt>Scope denials</dt><dd>{metric(security?.scope_denials)}</dd></div>
            <div><dt>Blocked operations</dt><dd>{metric(security?.blocked_operations)}</dd></div>
          </dl>
          {security?.scope_lines.length ? (
            <pre className="so-scope mono">{security.scope_lines.join('\n')}</pre>
          ) : (
            <p className="so-note so-note-muted">No engagement scope is declared. Declare one in Admin → Engagement &amp; Scope to authorize targets.</p>
          )}
        </article>

        <article className="so-card">
          <header className="so-card-header">
            <span className="so-card-title"><Database size={14} /> Evidence & Audit</span>
          </header>
          <dl className="so-kv">
            <div><dt>Runs recorded</dt><dd>{metric(evidence?.runs_recorded)}</dd></div>
            <div><dt>Completed investigations</dt><dd>{metric(evidence?.completed_investigations)}</dd></div>
            <div><dt>Audit events</dt><dd>{metric(evidence?.audit_events)}</dd></div>
            <div><dt>Latest verified run</dt><dd className="mono">{evidence?.latest_verified ? evidence.latest_verified.slice(0, 12) : '—'}</dd></div>
          </dl>
        </article>
      </section>

      {/* F. Recent execution traces -------------------------------------- */}
      <section className="so-card so-card-wide">
        <header className="so-card-header">
          <span className="so-card-title"><Workflow size={14} /> Recent Execution Traces</span>
          <span className="so-card-sub">
            {data ? `${data.traces.length} shown` : '—'} · updated {relativeTime(new Date(refreshedAt).toISOString())}
          </span>
        </header>
        {!data || data.traces.length === 0 ? (
          <div className="so-empty">No executions recorded in this period.</div>
        ) : (
          <table className="so-traces">
            <thead>
              <tr>
                <th scope="col">Run</th>
                <th scope="col">Specialist</th>
                <th scope="col">Operation</th>
                <th scope="col">Status</th>
                <th scope="col">Verified</th>
                <th scope="col">Duration</th>
                <th scope="col">Started</th>
                <th scope="col" aria-label="Details" />
              </tr>
            </thead>
            <tbody>
              {data.traces.map(t => {
                const id = t.run_id ?? '';
                const open = expandedTrace === id;
                return (
                  <React.Fragment key={id}>
                    <tr className="so-trace-row" onClick={() => setExpandedTrace(open ? null : id)}>
                      <td className="mono">{id.slice(0, 10) || '—'}</td>
                      <td>{humanize(t.agent)}</td>
                      <td className="mono">{t.operation ?? '—'}</td>
                      <td><span className={`so-status ${STATUS_CLASS[t.status ?? ''] ?? 'so-status-muted'}`}>{t.status ?? '—'}</span></td>
                      <td>{t.verified === null ? '—' : t.verified ? 'yes' : 'no'}</td>
                      <td className="mono">{formatDuration(t.duration_ms)}</td>
                      <td className="mono">{relativeTime(t.started_at)}</td>
                      <td className="so-trace-toggle">
                        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                      </td>
                    </tr>
                    {open && (
                      <tr className="so-trace-detail">
                        <td colSpan={8}>
                          <dl className="so-kv so-kv-inline">
                            <div><dt>Session</dt><dd className="mono">{t.session_id ?? '—'}</dd></div>
                            <div><dt>Model</dt><dd className="mono">{t.model ?? '—'}</dd></div>
                            <div><dt>Events</dt><dd>{metric(t.event_count)}</dd></div>
                            <div><dt>Last event</dt><dd className="mono">{t.last_event ?? '—'}</dd></div>
                            <div><dt>Approval</dt><dd>{t.approval ?? '—'}</dd></div>
                            <div><dt>Evidence</dt><dd className="mono">{t.evidence_ref ?? '—'}</dd></div>
                          </dl>
                          {t.error && <p className="so-note so-note-error">{t.error}</p>}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
