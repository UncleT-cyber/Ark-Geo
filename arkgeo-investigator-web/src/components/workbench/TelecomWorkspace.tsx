/**
 * TelecomWorkspace — non-scrolling six-step Telecom & Phone workspace.
 *
 * Layout: ONE parent workspace that never scrolls the page. A status rail on
 * the left lists the six procedures (01 IDENTIFY … 06 ASSESS); the centre
 * stage shows the sub-tools for the step the operator clicked. RUN
 * IDENTIFICATION fires a silent sequential background cascade 01→06 and each
 * rail step reflects grey (idle) → spinner (running) → green check (done) →
 * red cross (error). Clicking any rail step only switches the centre view —
 * it never hijacks the running cascade.
 *
 * Steps:
 *  01 IDENTIFY — E.164 intake + cleaned reference metadata (city===country
 *     falls back to the Core Routing Gateway Location from the backend).
 *  02 ENRICH   — Tier-1 OSINT enrichment matrix (real keyless facts).
 *  03 AUDIT    — credentials gate in the centre; DRY-RUN simulates the gate
 *     (green light + simulated IMSI/LAC from the public numbering plan),
 *     LIVE authenticates against the certified /signaling surface.
 *  04 GEO      — split layout; the map camera flies to the tower-sector
 *     coordinates (or the country bounding footprint at Tier-1).
 *  05 LIVE OPS — Pretext Template Selector + Canary Link Generator with an
 *     in-panel copy button (no scrolling), plus the certified ops row.
 *  06 ASSESS   — Run AI Analysis (Ollama/Qwen local or cloud) rendering the
 *     three forensic sections: RISK PROFILE / GEOSPATIAL ANALYSIS /
 *     AUDIT NEXT-STEPS.
 */
import React, { useEffect, useRef, useState } from 'react';
import { MapWorkspace, type MapPoint } from '../MapWorkspace/MapWorkspace';
import { OsintMatrix } from './OsintMatrix';
import { api } from '../../api';
import { useInvestigation, type CaseObservation } from './useInvestigation';
import { useByok } from '../settings/ByokContext';
import { buildHlrTelemetry, hlrObservationDetail } from '../../core/telecom/hlrTelemetry';
import { countryFootprint } from '../../core/telecom/osintSimulation';
import { NoLicenseGeo } from './NoLicenseGeo';
import type {
  SignalingAuditResponse, SignalingStatus, PersonnelIdentity, SignalingResult,
  SignalingAuditEntry, PhoneOsintResponse, HlrLookupResponse, PhoneAnalysisResponse,
  PhoneFootprint, PhonePresenceProbe,
} from '../../types';
import {
  Search, Radar, Activity, Satellite, ShieldCheck, Sparkles,
  Loader2, Play, KeyRound, LogIn, LogOut, Radio, ScrollText, MessageSquareText,
  BrainCircuit, Copy, Check, Circle, XCircle, CheckCircle2, Link2,
  RefreshCw, Lock, PhoneCall, type LucideIcon,
} from 'lucide-react';

type StepId = 'identify' | 'enrich' | 'audit' | 'geo' | 'ops' | 'assess' | 'nolic';
type StepStatus = 'idle' | 'running' | 'done' | 'error';
type GateMode = 'dry' | 'live';

const STEPS: { id: StepId; n: string; label: string; sub: string; icon: LucideIcon }[] = [
  { id: 'identify', n: '01', label: 'IDENTIFY', sub: 'E.164 intake', icon: Search },
  { id: 'enrich', n: '02', label: 'ENRICH', sub: 'OSINT matrix', icon: Radar },
  { id: 'audit', n: '03', label: 'AUDIT', sub: 'Signaling gate', icon: Activity },
  { id: 'geo', n: '04', label: 'GEO', sub: 'Map footprint', icon: Satellite },
  { id: 'ops', n: '05', label: 'LIVE OPS', sub: 'Pretext & canary', icon: ShieldCheck },
  { id: 'assess', n: '06', label: 'ASSESS', sub: 'AI analyst', icon: Sparkles },
  { id: 'nolic', n: '07', label: 'NO-LICENSE', sub: 'Open cell DB', icon: Radio },
];

const IDLE_STEPS: Record<StepId, StepStatus> = {
  identify: 'idle', enrich: 'idle', audit: 'idle', geo: 'idle', ops: 'idle',   assess: 'idle', nolic: 'idle',
};

const PRETEXT_TEMPLATES = [
  { id: 'canary-webhook', label: 'Method 3 — Canary Webhook', detail: 'Out-of-band callback to isolate the local gateway routing IP' },
  { id: 'verification-callback', label: 'Number Verification Callback', detail: 'M2M / OTP verification callback capture' },
  { id: 'account-recovery', label: 'Account Recovery SMS', detail: 'SIM-owner recovery flow' },
  { id: 'dispatch', label: 'Order Dispatch Confirmation', detail: 'Delivery update with a tracking link' },
  { id: 'it-incident', label: 'IT Incident Triage', detail: 'Business-hours network incident notice' },
];

const SEV_CLASS: Record<string, string> = {
  critical: 'ai-sev-critical', risk: 'ai-sev-risk',
  observation: 'ai-sev-obs', info: 'ai-sev-info',
};

/** Dry-run simulated IMSI/LAC derived ONLY from the public numbering plan —
 *  never real subscriber data. */
function simulateImsiLac(e164: string, ref?: HlrLookupResponse | null): { imsi: string; lac: string } {
  const digits = e164.replace(/\D/g, '');
  const mcc = ref?.mcc || digits.slice(3, 6) || '000';
  const mnc = ref?.mnc || digits.slice(6, 9) || '00';
  const subscriber = digits.slice(9).padEnd(9, '0').slice(0, 9);
  const imsi = `${mcc}${mnc}09${subscriber}`.slice(0, 15);
  const seed = parseInt(digits.slice(3, 9) || '0', 10) || 0;
  const lac = seed % 0xffff;
  return { imsi, lac: lac.toString(16).toUpperCase().padStart(4, '0') };
}

function buildCanaryUrl(phone: string, pretextId: string): string {
  const digits = phone.replace(/\D/g, '');
  const token = `${digits.slice(-8)}${Math.random().toString(36).slice(2, 10)}`.slice(0, 16);
  return `https://canary.arkgate.local/c/${token}?m=${pretextId}&p=${digits}`;
}

function StepStatusIcon({ status }: { status: StepStatus }) {
  if (status === 'running') return <Loader2 className="w-3 h-3 tw-step-spin" />;
  if (status === 'done') return <CheckCircle2 className="w-3 h-3 tw-step-done" />;
  if (status === 'error') return <XCircle className="w-3 h-3 tw-step-error" />;
  return <Circle className="w-3 h-3 tw-step-idle" />;
}

/** Cleaned lookup metadata — geo_city===country falls back to the Core
 *  Routing Gateway Location. */
function ReferenceFacts({ reference }: { reference: HlrLookupResponse | null }) {
  if (!reference) return null;
  const ref = reference;
  const loc = typeof ref.location === 'object' && ref.location ? ref.location as Record<string, unknown> : null;
  const rawCity = ref.geo_city ?? null;
  const city = rawCity && rawCity.toUpperCase() !== (ref.iso2 ?? '').toUpperCase() ? rawCity : null;
  const routing = ref.routing_location ?? null;
  return (
    <div className="tel-ref-facts">
      <div className="osint-state-label">REFERENCE IDENTIFICATION</div>
      <div className="net-kv">
        <div className="net-kv-row"><span>E.164</span><b className="mono">{ref.phone_e164}</b></div>
        {ref.caller_name && <div className="net-kv-row"><span>Name on account</span><b>{ref.caller_name}</b></div>}
        <div className="net-kv-row"><span>Validity</span><b className="mono">{ref.valid ? 'VALID' : 'INVALID'}{ref.possible ? ' · possible' : ''}</b></div>
        <div className="net-kv-row"><span>Number type</span><b className="mono">{ref.number_type ?? '—'}</b></div>
        <div className="net-kv-row"><span>Line type</span><b className="mono">{ref.line_type ?? '—'}</b></div>
        {ref.carrier && <div className="net-kv-row"><span>Carrier</span><b>{ref.carrier}{ref.mcc ? ` · MCC ${ref.mcc} / MNC ${ref.mnc ?? '?'}` : ''}</b></div>}
        <div className="net-kv-row"><span>Country</span><b className="mono">{ref.iso2 ?? '—'}</b></div>
        {city && <div className="net-kv-row"><span>City</span><b className="mono">{city}</b></div>}
        {!city && routing && (
          <div className="net-kv-row"><span>Core Routing Gateway Location</span><b className="mono">{routing}</b></div>
        )}
        {(!!loc?.city || !!loc?.region || !!loc?.zip_code) && (
          <div className="net-kv-row"><span>Provider region / ZIP</span><b className="mono">{[loc.city, loc.region, loc.zip_code].filter(Boolean).map(String).join(' · ')}</b></div>
        )}
        {ref.active != null && <div className="net-kv-row"><span>Line state</span><b className="mono">{ref.active ? 'ACTIVE' : 'INACTIVE'}</b></div>}
        {(ref.is_voip != null || ref.is_prepaid != null) && (
          <div className="net-kv-row"><span>Line flags</span><b className="mono">{[ref.is_voip ? 'VOIP' : null, ref.is_prepaid ? 'PREPAID' : null].filter(Boolean).join(' · ') || '—'}</b></div>
        )}
        {ref.timezone && ref.timezone.length > 0 && <div className="net-kv-row"><span>Timezone</span><b className="mono">{ref.timezone.join(', ')}</b></div>}
        {ref.national_format && <div className="net-kv-row"><span>National</span><b className="mono">{ref.national_format}</b></div>}
        {ref.international_format && <div className="net-kv-row"><span>International</span><b className="mono">{ref.international_format}</b></div>}
        {ref.subscriber_number && <div className="net-kv-row"><span>Subscriber</span><b className="mono">NDC {ref.ndc ?? '?'} · {ref.subscriber_number}</b></div>}
      </div>
      <div className="osint-hint mono">
        {ref.detail} Live ON/OFF, porting, roaming telemetry, caller name and risk scores unlock with an HLR provider key (BYOK or admin system key).
      </div>
    </div>
  );
}

/** AI assess — three forensic sections (Risk / Geospatial / Next-steps). */
function ForensicBrief({ a }: { a: PhoneAnalysisResponse }) {
  const sections: { id: string; label: string; body: string; cls: string }[] = [
    { id: 'risk', label: 'RISK PROFILE', body: a.risk_profile, cls: 'tw-fs-risk' },
    { id: 'geo', label: 'GEOSPATIAL ANALYSIS', body: a.geospatial_analysis, cls: 'tw-fs-geo' },
    { id: 'next', label: 'AUDIT NEXT-STEPS', body: a.audit_next_steps, cls: 'tw-fs-next' },
  ];
  return (
    <div className="ai-brief">
      <div className="ai-brief-head">
        <BrainCircuit className="w-4 h-4" />
        <div>
          <div className="ai-brief-title">{a.title}</div>
          <div className="ai-brief-meta mono">
            {a.ai_used ? `MODEL ${a.engine.toUpperCase()} · ${a.model}` : 'DETERMINISTIC FALLBACK · no model reachable'}
            {' · '}CONFIDENCE {a.confidence.toUpperCase()}
          </div>
        </div>
      </div>
      <div className="ai-brief-summary">{a.summary}</div>
      {sections.filter(s => s.body).map(s => (
        <div key={s.id} className={`tw-fs-section ${s.cls}`}>
          <div className="tw-fs-label">{s.label}</div>
          <div className="tw-fs-body">{s.body}</div>
        </div>
      ))}
      {a.findings.length > 0 && (
        <div className="ai-findings">
          {a.findings.map((f, i) => (
            <div key={i} className={`ai-finding ${SEV_CLASS[f.severity] ?? 'ai-sev-info'}`}>
              <span className="ai-finding-tag mono">{f.severity.toUpperCase()}</span>
              <div>
                <div className="ai-finding-title">{f.title}</div>
                {f.detail && <div className="ai-finding-detail">{f.detail}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
      {a.next_actions.length > 0 && (
        <div className="ai-block">
          <div className="ai-block-label">NEXT ACTIONS</div>
          <ul className="ai-list">{a.next_actions.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </div>
      )}
      <div className="ai-block">
        <div className="ai-block-label">CAVEATS</div>
        <ul className="ai-list">{(a.caveats.length ? a.caveats : ['Machine-generated assessment — verify against licensed provider feeds before acting.']).map((r, i) => <li key={i}>{r}</li>)}</ul>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="net-field">
      <span className="net-field-label">{label}</span>
      {children}
    </label>
  );
}

export function TelecomWorkspace() {
  const inv = useInvestigation();
  const byok = useByok();

  const [phone, setPhone] = useState('');
  const [mode, setMode] = useState<GateMode>('dry');
  const [activeStep, setActiveStep] = useState<StepId>('identify');
  const [steps, setSteps] = useState<Record<StepId, StepStatus>>(IDLE_STEPS);
  const [cascade, setCascade] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 01 / 02 — reference + OSINT facts
  const [tier1Ref, setTier1Ref] = useState<HlrLookupResponse | null>(null);
  const [osint, setOsint] = useState<PhoneOsintResponse | null>(null);
  const [osintBusy, setOsintBusy] = useState(false);
  const [footprint, setFootprint] = useState<PhoneFootprint | null>(null);
  const [presenceLinks, setPresenceLinks] = useState<{ platform: string; kind: string; url: string }[]>([]);

  // 03 — audit gate + extracted reveal
  const [gateOpen, setGateOpen] = useState(false);
  const [gateError, setGateError] = useState<string | null>(null);
  const [sigUser, setSigUser] = useState('');
  const [sigPass, setSigPass] = useState('');
  const [sigStatus, setSigStatus] = useState<SignalingStatus | null>(null);
  const [sigIdentity, setSigIdentity] = useState<PersonnelIdentity | null>(null);
  const [sigToken, setSigToken] = useState<string | null>(null);
  const [audit, setAudit] = useState<SignalingAuditResponse | null>(null);
  const [simImsi, setSimImsi] = useState<string | null>(null);
  const [simLac, setSimLac] = useState<string | null>(null);

  // 04 — geo footprint
  const [mapPoints, setMapPoints] = useState<MapPoint[]>([]);

  // 05 — pretext / canary / certified ops
  const [pretextId, setPretextId] = useState('canary-webhook');
  const [canaryUrl, setCanaryUrl] = useState<string | null>(null);
  const [canaryToken, setCanaryToken] = useState<string | null>(null);
  const [canaryHits, setCanaryHits] = useState<{ ts: string; ip: string; ua: string }[]>([]);
  const [copied, setCopied] = useState(false);
  const [opToken, setOpToken] = useState('');
  const [opOp, setOpOp] = useState('MTN NG');
  const [opMcc, setOpMcc] = useState('621');
  const [liveResult, setLiveResult] = useState<SignalingResult | null>(null);
  const [sigBusy, setSigBusy] = useState(false);
  const [auditDock, setAuditDock] = useState(false);
  const [auditEntries, setAuditEntries] = useState<SignalingAuditEntry[]>([]);
  const [smsText, setSmsText] = useState('');
  const [catcherBand, setCatcherBand] = useState('GSM-1800');

  // 06 — AI assess
  const [analysis, setAnalysis] = useState<PhoneAnalysisResponse | null>(null);
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);

  const phoneRef = useRef(phone);
  phoneRef.current = phone;
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const sigUserRef = useRef(sigUser);
  sigUserRef.current = sigUser;
  const sigPassRef = useRef(sigPass);
  sigPassRef.current = sigPass;
  const sigTokenRef = useRef(sigToken);
  sigTokenRef.current = sigToken;
  const pretextIdRef = useRef(pretextId);
  pretextIdRef.current = pretextId;
  const footprintRef = useRef(footprint);
  footprintRef.current = footprint;

  useEffect(() => {
    api.signalingStatus().then(setSigStatus).catch(() => {});
  }, []);

  // ------------------------------------------------------------------ //
  // Individual step runners (used both by the cascade and the panels)
  // ------------------------------------------------------------------ //
  const runIdentify = async (p: string) => {
    setError(null);
    const resolved = byok.resolveKey('hlr');
    const resp = await api.hlrLookup(p, resolved.source === 'byok' ? resolved.key || undefined : undefined);
    setTier1Ref(resp);
    setOsint(null);
    const obs: CaseObservation[] = [];
    const t = buildHlrTelemetry(p, resp);
    obs.push({
      type: 'HLR', status: resp.looked_up ? 'OBSERVED' : 'UNAVAILABLE', layer: 'telecom_hlr',
      label: `HLR lookup ${resp.looked_up ? 'resolved' : 'requires key'}`,
      detail: resp.looked_up ? hlrObservationDetail(t) : resp.detail,
      source: 'tool_inference',
    });
    inv.appendCaseObservations(obs);
    inv.pushTerminal(resp.looked_up ? 'ok' : 'warn',
      `HLR ${resp.looked_up ? `resolved ${resp.carrier || ''} (${resp.mcc}-${resp.mnc})` : resp.detail}`);
    return resp;
  };

  const runEnrich = async (p: string) => {
    setOsintBusy(true);
    try {
      const token = sigTokenRef.current;
      if (token) {
        const resolved = byok.resolveKey('hlr');
        const keys = resolved.source === 'byok' && resolved.key ? { hlr_api_key: resolved.key } : undefined;
        const resp = await api.signalingOsint(token, p, keys);
        setOsint(resp);
        setTier1Ref(null);
        setFootprint(resp.footprint ?? null);
        setPresenceLinks(((resp.workers?.social?.data as { presence_links?: { platform: string; kind: string; url: string }[] } | undefined)?.presence_links) ?? []);
        inv.pushTerminal('ok',
          `OSINT ENRICHMENT → ${resp.phone_e164} · ${resp.carrier || resp.geo_city || 'carrier?'} (${resp.mcc ?? '?'}-${resp.mnc ?? '?'}) · line ${resp.line_state ?? 'requires key'} · trace ${resp.trace_id}`);
        const obs: CaseObservation[] = [{
          type: 'SIGNALING_AUDIT', status: 'OBSERVED', layer: 'telecom_osint',
          label: `OSINT ${resp.phone_e164} (${resp.iso2})`,
          detail: [resp.carrier ? `carrier ${resp.carrier}` : null, resp.line_type ? `line ${resp.line_type}` : null,
            resp.geo_zone ? `zone ${resp.geo_zone}` : null, resp.routing_location ? `routing ${resp.routing_location}` : null].filter(Boolean).join(' · ') || resp.detail,
          source: 'tool_inference',
        }];
        inv.appendCaseObservations(obs);
        return;
      }
      const resolved = byok.resolveKey('hlr');
      const free = await api.hlrLookup(p, resolved.source === 'byok' ? resolved.key || undefined : undefined);
      setTier1Ref(free);
      setOsint(null);
      setFootprint(null);
      setPresenceLinks([]);
      let probe: PhonePresenceProbe | null = null;
      try {
        probe = await api.presenceProbe(p);
        if (probe?.ok && probe.presence && Object.keys(probe.presence).length > 0) {
          setFootprint({
            presence: probe.presence,
            probes: probe.probes,
            probed: true,
            simulated: false,
            note: probe.note,
          });
          setPresenceLinks(probe.presence_links ?? []);
        }
      } catch { /* presence probe is best-effort */ }
      inv.pushTerminal('info',
        free && free.looked_up
          ? `Tier-1 enrichment — libphonenumber metadata + public numbering plan for ${free.phone_e164} (${free.iso2 ?? '?'}).${free.live_state_available ? ` Live ON/OFF + risk active via HLR key · carrier ${free.carrier ?? '?'}.` : ' Live ON/OFF, SIM-swap and risk tiers need a certified login + provider keys.'}${probe?.probed ? ` Digital footprint probed (${Object.keys(probe.presence).filter(k => probe.presence[k]).join(', ') || 'none present'}).` : ''}`
          : 'Tier-1 enrichment — no reference data returned for this number.');
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'OSINT aggregation failed';
      inv.pushTerminal('err', `OSINT ERROR — ${msg}`);
      throw e;
    } finally {
      setOsintBusy(false);
    }
  };

  /** Credentials gate — dry-run simulates the airlock; live hits /signaling. */
  const runGate = async (p: string, m: GateMode): Promise<boolean> => {
    setGateError(null);
    if (m === 'dry' || !sigUserRef.current.trim()) {
      const sim = simulateImsiLac(p, tier1Ref);
      setSimImsi(sim.imsi);
      setSimLac(sim.lac);
      setGateOpen(true);
      setSigToken(null);
      setSigIdentity(null);
      inv.pushTerminal('ok', `AUDIT GATE (dry-run) — mock credentials accepted · simulated IMSI ${sim.imsi} · LAC ${sim.lac}`);
      return true;
    }
    setSigBusy(true);
    try {
      const auth = await api.signalingLogin(sigUserRef.current.trim(), sigPassRef.current);
      setSigToken(auth.access_token);
      setSigIdentity({
        username: sigUserRef.current.trim(),
        full_name: auth.full_name,
        role: auth.role,
        operator_scopes: auth.operator_scopes,
      });
      setGateOpen(true);
      setSigPass('');
      inv.pushTerminal('ok', `CERTIFIED ${auth.role} authenticated — ${auth.full_name}`);
      inv.pushTerminal('ok', 'AIRLOCK UNLOCKED — tier 2 reveal engaged');
      return true;
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Certified login failed';
      setGateError(msg);
      setGateOpen(false);
      inv.pushTerminal('err', `CERTIFIED LOGIN ERROR — ${msg}`);
      throw e;
    } finally {
      setSigBusy(false);
    }
  };

  const resolveGeo = async (p: string, unlocked: boolean, a: SignalingAuditResponse | null) => {
    const ex = a?.extracted;
    if (unlocked && ex && ex.mcc && ex.mnc) {
      const mccN = parseInt(ex.mcc, 10);
      const mncN = parseInt(ex.mnc, 10);
      const lacN = ex.lac ? parseInt(ex.lac, 16) : NaN;
      const ciN = ex.cell_id ? parseInt(ex.cell_id, 16) : NaN;
      const buildPoint = (lat: number, lon: number, radius: number, provider: string) => ({
        lat, lon, radius, confidence: 0.65, source: 'CELL_TELEMETRY' as const,
        pulse: true, sector: true,
        label: `${ex.operator ?? 'Cell'} — MCC ${ex.mcc} MNC ${ex.mnc} LAC ${ex.lac} CI ${ex.cell_id} (${provider})`,
      });
      try {
        const resolved = byok.resolveKey('opencellid');
        const res = await api.cellLookup(
          { mcc: mccN, mnc: mncN, lac: Number.isFinite(lacN) ? lacN : undefined, cell_id: Number.isFinite(ciN) ? ciN : undefined, provider: 'opencellid' },
          resolved.source === 'byok' ? resolved.key || undefined : undefined,
        );
        if (res.looked_up && res.lat != null && res.lon != null) {
          setMapPoints([buildPoint(res.lat, res.lon, res.range_meters ?? 2000, 'opencellid')]);
          inv.pushTerminal('ok', `spatial.resolved ${res.lat.toFixed(5)}, ${res.lon.toFixed(5)} (r≈${Math.round(res.range_meters ?? 0)}m) — sector radar engaged`);
          return;
        }
      } catch { /* fall through to local */ }
      const local = await api.cellLocal({
        mcc: mccN, mnc: mncN, lac: Number.isFinite(lacN) ? lacN : undefined,
        cell_id: Number.isFinite(ciN) ? ciN : undefined, operator: ex.operator ?? undefined,
      }).catch(() => null);
      if (local && local.looked_up && local.lat != null && local.lon != null) {
        setMapPoints([buildPoint(local.lat, local.lon, local.range_meters ?? 2000, 'custom_local_db')]);
        inv.pushTerminal('ok', `spatial.resolved ${local.lat.toFixed(5)}, ${local.lon.toFixed(5)} (local db) — sector radar engaged`);
        return;
      }
      inv.pushTerminal('warn', 'spatial resolution skipped — incomplete MCC/MNC/LAC/CI, trying city geocode');
    }
    // No live cell telemetry: at least fly to the city when the keyless
    // tier resolved one (libphonenumber geocoder) — better than a country
    // bounding circle. Falls back to the country centroid.
    const cityName = osint?.geo_city ?? tier1Ref?.geo_city ?? null;
    if (cityName) {
      const geo = await api.geocodeCity(cityName).catch(() => ({ ok: false as const, detail: 'geocode failed' }));
      if (geo?.ok && geo.lat != null && geo.lon != null) {
        setMapPoints([{
          lat: geo.lat, lon: geo.lon, radius: 2000,
          confidence: 0.5, source: 'CITY_GEOCODE', bounding: false,
          label: `${cityName} — city-level registration zone`,
        }]);
        inv.pushTerminal('ok', `footprint.city ${cityName} → ${geo.lat.toFixed(4)}, ${geo.lon.toFixed(4)} — fly-to city (no live cell telemetry)`);
        return;
      }
      inv.pushTerminal('warn', `city geocode failed (${geo?.detail ?? 'unknown'}) — country footprint`);
    }
    const iso2 = tier1Ref?.iso2 ?? a?.extracted.country ?? null;
    // No CGI available: try the keyless operator-region estimate (no licence).
    const reg = await api.phoneLocate(p).catch(() => null);
    if (reg?.lat != null && reg?.lon != null) {
      setMapPoints([{
        lat: reg.lat, lon: reg.lon, radius: reg.radius_m ?? 30000,
        confidence: reg.confidence, source: 'PHONE_REGION',
        label: `OPERATOR REGION ${reg.iso2 ?? ''} (no-licence estimate)`,
      }]);
      inv.pushTerminal('info', `region.estimate ${reg.lat.toFixed(4)}, ${reg.lon.toFixed(4)} — operator-region centroid (no licence)`);
      return;
    }
    const fp = countryFootprint(iso2);
    setMapPoints([{
      lat: fp.lat, lon: fp.lon, radius: fp.radius_km * 1000,
      confidence: 0.3, source: 'COUNTRY_TIER1', bounding: true,
      label: `${fp.label} — area-code territory`,
    }]);
    inv.pushTerminal('info', `footprint.country ${fp.label} — bounding circle r≈${fp.radius_km}km${unlocked ? ' · tier 2 radar requires a fresh authorized audit' : ''}`);
  };

  const runAudit = async (p: string, unlocked: boolean) => {
    const resp = await api.signalingAudit(p, unlocked ? 2 : 1);
    setAudit(resp);
    inv.pushTerminal('info', `workflow.audit complete — thread ${resp.thread} (tier ${resp.tier})`);
    await resolveGeo(p, unlocked, resp);
    const obs: CaseObservation[] = [{
      type: 'SIGNALING_AUDIT', status: 'OBSERVED', layer: 'telecom_ss7',
      label: `Simulated ${resp.thread} audit (tier ${resp.tier})`,
      detail: `${resp.steps.length} steps · ${resp.detail}`,
      source: 'tool_inference',
    }];
    const ex = resp.extracted;
    if (unlocked && ex.mcc && ex.mnc) {
      obs.push({
        type: 'CELL_PARAMETERS', status: 'OBSERVED', layer: 'telecom_ss7',
        label: `Extracted params MCC ${ex.mcc} / MNC ${ex.mnc} / LAC ${ex.lac ?? '-'} / CI ${ex.cell_id ?? '-'}`,
        detail: [ex.operator, ex.country ? `ISO ${ex.country}` : null, ex.cgi ? `CGI ${ex.cgi}` : null].filter(Boolean).join(' · ') || 'simulated workflow output',
        source: 'tool_inference',
      });
    }
    inv.appendCaseObservations(obs);
    inv.pushTerminal('ok', 'observations folded into case');
  };

  const generateCanary = async (p: string, pretext: string) => {
    if (sigToken) {
      const made = await api.canaryCreate(sigToken, p, pretext).catch(() => null);
      if (made?.url) {
        setCanaryUrl(made.url);
        setCanaryToken(made.token ?? '');
        setCanaryHits([]);
        setCopied(false);
        return made.url;
      }
    }
    const url = buildCanaryUrl(p, pretext);
    setCanaryUrl(url);
    setCanaryToken(url.split('/').pop()?.split('?')[0] ?? '');
    setCanaryHits([]);
    setCopied(false);
    return url;
  };

  const refreshCanaryHits = async () => {
    if (!sigToken || !canaryToken) return;
    const st = await api.canaryStatus(sigToken, canaryToken).catch(() => null);
    if (st?.ok) setCanaryHits(st.hits ?? []);
  };

  const runOps = async (p: string) => {
    const st = await api.signalingStatus().catch(() => null);
    if (st) {
      setSigStatus(st);
      inv.pushTerminal('info', `signaling backend ${st.backend} · live=${String(st.live)}`);
    }
    const url = await generateCanary(p, pretextIdRef.current);
    inv.pushTerminal('ok', `canary link generated — ${url.split('?')[0]}`);
  };

  const runAssess = async (p: string) => {
    setAnalysisBusy(true);
    setAnalysisError(null);
    try {
      const ref = tier1Ref;
      const os = osint;
      const ex = audit?.extracted;
      const unlocked = gateOpen && mode === 'live' && sigToken != null;
      const context: Record<string, unknown> = {
        phone_e164: p,
        iso2: ref?.iso2 ?? os?.iso2,
        valid: os?.valid ?? ref?.valid,
        possible: os?.possible ?? ref?.possible,
        number_type: os?.number_type ?? ref?.number_type,
        line_type: os?.line_type ?? ref?.line_type,
        carrier: os?.carrier ?? ref?.carrier,
        mcc: os?.mcc ?? ref?.mcc,
        mnc: os?.mnc ?? ref?.mnc,
        national_format: os?.national_format ?? ref?.national_format,
        international_format: os?.international_format ?? ref?.international_format,
        ndc: os?.ndc ?? ref?.ndc,
        subscriber_number: os?.subscriber_number ?? ref?.subscriber_number,
        geo_city: os?.geo_city ?? ref?.geo_city,
        routing_location: os?.routing_location ?? ref?.routing_location,
        timezone: (os?.timezone && os.timezone.length ? os.timezone : ref?.timezone) ?? [],
        active: os?.active ?? null,
        ported: os?.ported ?? null,
        roaming_country: os?.roaming_country ?? null,
        live_state: os?.live_state ?? null,
        caller_name: os?.caller_name ?? null,
        sim_swap_risk: os?.sim_swap_risk ?? null,
        requires_key: os?.requires_key ?? [],
        presence: footprintRef.current?.presence ?? {},
        footprint_probed: Boolean(footprintRef.current?.probed),
        tier: unlocked ? 2 : 1,
        thread: audit?.thread ?? null,
        imsi_revealed: unlocked ? ex?.imsi ?? simImsi : null,
        cgi_revealed: unlocked ? ex?.cgi : null,
        mode,
      };
      const resp = await api.telecomAnalyze(p, context);
      setAnalysis(resp);
      inv.pushTerminal(resp.ai_used ? 'ok' : 'info',
        `AI ASSESSMENT → engine ${resp.engine}${resp.model ? ` · ${resp.model}` : ''} · confidence ${resp.confidence}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Analysis failed';
      setAnalysisError(msg);
      inv.pushTerminal('err', `ANALYSIS ERROR — ${msg}`);
    } finally {
      setAnalysisBusy(false);
    }
  };

  // ------------------------------------------------------------------ //
  // Cascade — RUN IDENTIFICATION fires 01→06 silently in the background
  // ------------------------------------------------------------------ //
  const runCascade = async () => {
    const p = phoneRef.current.trim();
    if (!p) return;
    setCascade(true);
    setSteps(IDLE_STEPS);
    inv.clearTerminal();
    inv.pushTerminal('info', `telecom cascade --phone ${p} --mode ${modeRef.current}`);
    for (const s of STEPS) {
      setSteps(prev => ({ ...prev, [s.id]: 'running' }));
      try {
        if (s.id === 'identify') await runIdentify(p);
        else if (s.id === 'enrich') await runEnrich(p);
        else if (s.id === 'audit') {
          const unlocked = await runGate(p, modeRef.current);
          await runAudit(p, unlocked);
        } else if (s.id === 'geo') {
          await resolveGeo(p, gateOpen && modeRef.current === 'live' && sigTokenRef.current != null, audit);
        } else if (s.id === 'ops') await runOps(p);
        else if (s.id === 'assess') await runAssess(p);
        setSteps(prev => ({ ...prev, [s.id]: 'done' }));
      } catch (e) {
        setSteps(prev => ({ ...prev, [s.id]: 'error' }));
        inv.pushTerminal('err', `${s.n} ${s.label} — ${e instanceof Error ? e.message : 'failed'}`);
      }
    }
    setCascade(false);
    inv.pushTerminal('ok', 'cascade complete — inspect each step for its sub-tools');
  };

  // ------------------------------------------------------------------ //
  // 05 certified ops handlers (live-mode only, gated by the audit gate)
  // ------------------------------------------------------------------ //
  const signOut = () => {
    setSigToken(null); setSigIdentity(null); setOpToken(''); setLiveResult(null);
    setAuditEntries([]); setGateOpen(false);
    inv.pushTerminal('info', 'certified session ended');
  };

  const issueOpToken = async () => {
    if (!sigToken) return;
    setSigBusy(true); setGateError(null);
    try {
      const t = await api.signalingOperatorToken(sigToken, { operator: opOp, mcc: opMcc, valid_hours: 24 });
      setOpToken(t.token);
      inv.pushTerminal('ok', `operator token issued — ${t.operator} (MCC ${t.mcc}) trace ${t.trace_id}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Operator token failed';
      setGateError(msg);
      inv.pushTerminal('err', `OPERATOR TOKEN ERROR — ${msg}`);
    } finally {
      setSigBusy(false);
    }
  };

  const opMnc = () => {
    const digits = phoneRef.current.replace(/\D/g, '');
    return digits.slice(6, 9) || '30';
  };

  const runLive = async (op: 'sri' | 'ulr' | 'ati' | 'plr' | 'imsi' | 'cgi') => {
    if (!sigToken || !opToken || !phoneRef.current.trim()) return;
    setSigBusy(true); setGateError(null);
    try {
      const payload: Record<string, unknown> =
        op === 'cgi'
          ? { mcc: opMcc, mnc: opMnc(), lac: null, cell_id: null }
          : { msisdn: phoneRef.current.trim() };
      const resp = await api.signalingOp(op, sigToken, opToken, payload);
      setLiveResult(resp);
      inv.pushTerminal(resp.live ? 'ok' : 'warn',
        `${op.toUpperCase()} → backend ${resp.backend} live=${String(resp.live)} trace ${resp.trace_id}`);
      for (const s of resp.steps) {
        inv.pushTerminal(s.warn ? 'warn' : 'info', `${s.ts}  ${s.event.padEnd(24)}${s.detail}${s.warn ? `  [${s.warn}]` : ''}`);
      }
      const cell = resp.cell;
      if (cell && cell.lat != null && cell.lon != null) {
        setMapPoints([{
          lat: cell.lat, lon: cell.lon, radius: cell.radius_meters ?? 2000,
          confidence: 0.65, source: 'CELL_TELEMETRY', pulse: true,
          label: `${cell.operator ?? 'Cell'} — ${cell.cgi ?? ''}`,
        }]);
        inv.pushTerminal('ok', `spatial.resolved ${cell.lat.toFixed(5)}, ${cell.lon.toFixed(5)} — fly-to`);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Live signaling op failed';
      setGateError(msg);
      inv.pushTerminal('err', `${op.toUpperCase()} ERROR — ${msg}`);
    } finally {
      setSigBusy(false);
    }
  };

  const runLiveSms = async () => {
    if (!sigToken || !opToken || !phoneRef.current.trim()) return;
    setSigBusy(true); setGateError(null);
    try {
      const resp = await api.signalingSilentSms(sigToken, opToken, phoneRef.current.trim(), smsText);
      inv.pushTerminal(resp.sent ? 'ok' : 'warn', `SILENT-SMS ${resp.sent ? 'delivered' : 'suppressed'} — ${resp.detail} (${resp.message_id})`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Silent SMS failed';
      setGateError(msg);
      inv.pushTerminal('err', `SILENT-SMS ERROR — ${msg}`);
    } finally {
      setSigBusy(false);
    }
  };

  const runLiveCatcher = async () => {
    if (!sigToken || !opToken) return;
    setSigBusy(true); setGateError(null);
    try {
      const resp = await api.signalingImsiCatcher(sigToken, opToken, {
        band: catcherBand, radius_m: 500, capture_seconds: 15, mcc_filter: opMcc,
      });
      inv.pushTerminal('ok', `IMSI-CATCHER sweep ${catcherBand} — ${resp.count} captures (${resp.duration_ms}ms)`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'IMSI-catcher failed';
      setGateError(msg);
      inv.pushTerminal('err', `IMSI-CATCHER ERROR — ${msg}`);
    } finally {
      setSigBusy(false);
    }
  };

  const loadAudit = async () => {
    setAuditDock(v => !v);
    if (!sigToken) {
      inv.pushTerminal('info', 'audit trail locked — requires a certified login (AUDIT step, LIVE mode)');
      return;
    }
    setSigBusy(true); setGateError(null);
    try {
      const entries = await api.signalingAuditTrail(sigToken, 50);
      setAuditEntries(entries);
      inv.pushTerminal('info', `audit trail loaded — ${entries.length} entries`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Audit trail failed';
      setGateError(msg);
      inv.pushTerminal('err', `AUDIT ERROR — ${msg}`);
    } finally {
      setSigBusy(false);
    }
  };

  const copyCanary = async () => {
    if (!canaryUrl) return;
    try {
      await navigator.clipboard.writeText(canaryUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch { setCopied(false); }
  };

  const reFly = () => {
    if (mapPoints.length) setMapPoints([...mapPoints]);
  };

  const tier = (gateOpen && mode === 'live' && sigToken != null) ? 2 : 1;
  const cellPoint = mapPoints[mapPoints.length - 1] ?? null;
  const pretext = PRETEXT_TEMPLATES.find(t => t.id === pretextId) ?? PRETEXT_TEMPLATES[0];

  return (
    <div className="tw-root">
      {/* Header — target + RUN IDENTIFICATION + mode + status */}
      <div className="net-card tw-header">
        <div className="net-card-title">
          TELECOM & PHONE INTELLIGENCE
          <span className={`net-chip ${mode === 'live' && sigStatus?.live ? 'tel-live-chip' : 'tel-sim-chip'}`}>
            <span>{mode === 'live' ? (sigStatus?.live ? 'LIVE' : 'DRY-ENGINE') : 'DRY-RUN'}</span>
            <b>{sigStatus?.backend ?? '…'}</b>
          </span>
          <span className="net-chip tel-tier-chip"><span>ACCESS TIER</span><b>{tier === 2 ? '2 · UNLOCKED' : '1 · LOCKED'}</b></span>
          <span className="net-chip net-auth-chip"><Lock className="w-3 h-3" /> {sigIdentity ? sigIdentity.role : 'CERTIFIED PERSONNEL ONLY'}</span>
          {sigIdentity && (
            <button className="tw-header-logout" onClick={signOut} title="Sign out"><LogOut className="w-3 h-3" /></button>
          )}
        </div>
        <div className="net-card-row net-card-row-wrap">
          <Field label="PHONE (VALIDATED E.164)">
            <input
              className="net-input"
              value={phone}
              placeholder="+2348030000000"
              onChange={e => setPhone(e.target.value.replace(/[^\d+]/g, ''))}
              onKeyDown={e => { if (e.key === 'Enter') runCascade(); }}
            />
          </Field>
          <button className="tool-btn" onClick={runCascade} disabled={cascade || !phone.trim()} title="Fires the silent 01→06 background cascade">
            {cascade ? <Loader2 className="w-3 h-3 net-spin" /> : <Play className="w-3 h-3" />} RUN IDENTIFICATION
          </button>
          <div className="tw-cascade-note">
            {cascade
              ? <><Loader2 className="w-3 h-3 net-spin" /> Cascade 01→06 running in the background — you may click any step.</>
              : <>RUN IDENTIFICATION fires a silent sequential cascade 01 IDENTIFY → 06 ASSESS. Click any step to inspect its sub-tools.</>}
          </div>
        </div>
        {/* Credentials gate — always visible, never buried in a step */}
        <div className="tw-gate-strip">
          <div className="tw-gate-strip-left">
            <span className="tw-gate-strip-title mono">AUDIT · CREDENTIALS GATE</span>
            <div className="net-seg">
              <button className={`tool-btn ${mode === 'dry' ? 'tool-btn-active' : ''}`} onClick={() => setMode('dry')}>
                <Play className="w-3 h-3" /> DRY-RUN
              </button>
              <button className={`tool-btn ${mode === 'live' ? 'tool-btn-active' : ''}`} onClick={() => setMode('live')}>
                <Radio className="w-3 h-3" /> LIVE
              </button>
            </div>
          </div>
          <Field label="USERNAME">
            <input className="net-input net-input-sm" value={sigUser} autoComplete="off"
              placeholder={mode === 'dry' ? 'mock-sigops (dry-run)' : 'sigops / sigadmin / sigaudit'}
              onChange={e => setSigUser(e.target.value)} />
          </Field>
          <Field label="PASSWORD">
            <input className="net-input net-input-sm" type="password" value={sigPass} autoComplete="off"
              placeholder="••••••••" onChange={e => setSigPass(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') runGate(phone.trim(), mode); }} />
          </Field>
          <button className="tool-btn" onClick={() => runGate(phone.trim(), mode)} disabled={sigBusy}>
            {sigBusy ? <Loader2 className="w-3 h-3 net-spin" /> : mode === 'dry' ? <Play className="w-3 h-3" /> : <LogIn className="w-3 h-3" />}
            {mode === 'dry' ? 'RUN DRY-RUN GATE' : 'RUN LIVE GATE'}
          </button>
          <div className={`tw-gate-light ${gateOpen ? 'tw-gate-on' : ''}`}>
            <span className="tw-gate-bulb" />
            <div>
              <div className="osint-state-label">AUDIT GATE</div>
              <div className="tw-gate-value">{gateOpen ? 'OPEN — GREEN LIGHT' : 'CLOSED'}</div>
            </div>
          </div>
        </div>
        {gateError && <div className="net-status net-status-error">{gateError}</div>}
      </div>

      {/* Body — status rail + centre stage */}
      <div className="tw-body">
        <aside className="tw-rail">
          <div className="tel-procedure-title">PROCEDURE · STATUS</div>
          {STEPS.map(s => {
            const Icon = s.icon;
            const status = steps[s.id];
            return (
              <button
                key={s.id}
                className={`tw-step ${activeStep === s.id ? 'tw-step-active' : ''} ${status !== 'idle' ? 'tw-step-ran' : ''}`}
                onClick={() => setActiveStep(s.id)}
                title={s.sub}
              >
                <span className="tw-step-n">{s.n}</span>
                <StepStatusIcon status={status} />
                <Icon className="w-3 h-3 tw-step-ic" />
                <span className="tw-step-label">{s.label}</span>
              </button>
            );
          })}
        </aside>

        <div className="tw-stage">
          {activeStep === 'identify' && (
            <section className="net-card tw-panel">
              <div className="net-card-title">
                <span className="tel-proc-n tel-proc-n-panel">01</span> IDENTIFY
                <span className="net-chip tel-thread-chip"><span>E.164</span><b className="mono">{phone.trim() || '…'}</b></span>
              </div>
              <div className="net-card-row net-card-row-wrap">
                <button className="tool-btn" onClick={() => runIdentify(phone.trim())} disabled={osintBusy || !phone.trim()}>
                  {cascade ? <Loader2 className="w-3 h-3 net-spin" /> : <Search className="w-3 h-3" />} RUN IDENTIFICATION (STEP)
                </button>
              </div>
              <div className="net-card-hint">
                Keyless identification — Google libphonenumber metadata + public numbering plans. No key required. When the geocoder only resolves the country, the city field is cleaned and falls back to the Core Routing Gateway Location.
              </div>
              <ReferenceFacts reference={tier1Ref} />
              {error && <div className="net-status net-status-error">{error}</div>}
            </section>
          )}

          {activeStep === 'enrich' && (
            <section className="net-card tw-panel">
              <div className="net-card-title">
                <span className="tel-proc-n tel-proc-n-panel">02</span> ENRICH
                <span className="net-chip tel-sim-chip"><span>{sigToken ? 'CERTIFIED' : 'FREE TIER'}</span><b>{sigToken ? 'OSINT BACKEND' : 'NO LICENSE'}</b></span>
              </div>
              <div className="net-card-row net-card-row-wrap">
                <button className="tool-btn" onClick={() => runEnrich(phone.trim())} disabled={osintBusy || !phone.trim()}>
                  {osintBusy ? <Loader2 className="w-3 h-3 net-spin" /> : <BrainCircuit className="w-3 h-3" />} RUN OSINT ENRICHMENT
                </button>
              </div>
              <div className="net-card-hint">
                {sigToken
                  ? 'Aggregated via the certified OSINT backend — HLR live state, SIM-swap, footprint and risk tiers activate when provider keys are configured (BYOK or Admin system key).'
                  : 'Free tier extracts real keyless reference facts (validity / number type / carrier / MCC-MNC / formats / timezone from libphonenumber metadata + public numbering plans). Provider tiers need a certified login.'}
              </div>
              <OsintMatrix phone={phone} osint={osint} reference={tier1Ref} footprint={footprint} presenceLinks={presenceLinks} />
            </section>
          )}

          {activeStep === 'audit' && (
            <section className="net-card tw-panel">
              <div className="net-card-title">
                <span className="tel-proc-n tel-proc-n-panel">03</span> AUDIT — CREDENTIALS GATE
                <span className="net-chip tel-thread-chip"><span>THREAD</span><b className="mono">{audit?.thread ?? '…'}</b></span>
              </div>
              <div className="tw-gate-status">
                <div className={`tw-gate-light ${gateOpen ? 'tw-gate-on' : ''}`}>
                  <span className="tw-gate-bulb" />
                  <div>
                    <div className="osint-state-label">AUDIT GATE</div>
                    <div className="tw-gate-value">{gateOpen ? 'OPEN — GREEN LIGHT' : 'CLOSED'}</div>
                  </div>
                </div>
                <div className="net-chip tel-tier-chip"><span>MODE</span><b>{mode === 'dry' ? 'DRY-RUN SIMULATION' : 'LIVE /signaling'}</b></div>
                <span className="net-chip tel-sim-chip"><span>AIRLOCK</span><b>{gateOpen ? 'UNLOCKED' : 'LOCKED'}</b></span>
              </div>
              <div className="net-card-hint">
                The credentials gate lives at the top of this workspace — always visible, never buried in a step. Dry-run mode simulates the airlock: mock credentials flash the green light and IMSI/LAC values are derived from the public numbering plan only — never live subscriber data. Switch to LIVE and run the gate to authenticate against the certified /signaling surface (dev seeds: sigops/sigops-cert · sigadmin/sigadmin-cert · sigaudit/sigaudit-cert).
              </div>
              {simImsi && simLac && mode === 'dry' && (
                <div className="tw-sim-vars mono">
                  <div><span>SIMULATED IMSI</span><b>{simImsi}</b></div>
                  <div><span>SIMULATED LAC</span><b>{simLac}</b></div>
                  <div className="tw-sim-note">Dry-run values — NOT live subscriber data.</div>
                </div>
              )}
              {gateError && <div className="net-status net-status-error">{gateError}</div>}
              {audit && (
                <div className="tel-ref-facts">
                  <div className="osint-state-label">EXTRACTED FIELD REVEAL</div>
                  <div className="tw-reveal-grid mono">
                    <div><span>MCC</span><b>{audit.extracted.mcc ?? '—'}</b></div>
                    <div><span>MNC</span><b>{audit.extracted.mnc ?? '—'}</b></div>
                    <div><span>LAC</span><b>{tier === 2 ? (audit.extracted.lac ?? '—') : 'REDACTED'}</b></div>
                    <div><span>CELL ID</span><b>{tier === 2 ? (audit.extracted.cell_id ?? '—') : 'REDACTED'}</b></div>
                    <div><span>IMSI</span><b>{tier === 2 ? (audit.extracted.imsi ?? '—') : (simImsi ?? 'REDACTED')}</b></div>
                    <div><span>CGI</span><b>{tier === 2 ? (audit.extracted.cgi ?? '—') : 'REDACTED'}</b></div>
                  </div>
                  <div className="osint-hint mono">{audit.detail} · simulated={String(audit.simulated)}</div>
                </div>
              )}
            </section>
          )}

          {activeStep === 'geo' && (
            <section className="net-card tw-panel tw-panel-fill">
              <div className="net-card-title">
                <span className="tel-proc-n tel-proc-n-panel">04</span> GEO FOOTPRINT
                <span className={`net-chip ${tier === 2 ? 'tel-tier-chip' : 'tel-sim-chip'}`}>
                  <span>{tier === 2 ? 'T2' : 'T1'}</span><b>{tier === 2 ? 'SECTOR' : 'BOUNDING'}</b>
                </span>
                <button className="tool-btn" onClick={reFly} disabled={mapPoints.length === 0} title="Re-fly the camera to the current footprint">
                  <RefreshCw className="w-3 h-3" /> FLY TO SECTOR
                </button>
              </div>
              <div className="tw-geo-split">
                <div className="tw-geo-map">
                  <MapWorkspace points={mapPoints} history={[]} />
                </div>
                <div className="tw-geo-side">
                  <div className="osint-state-label">FOOTPRINT STATUS</div>
                  {cellPoint ? (
                    <div className="net-kv">
                      <div className="net-kv-row"><span>Source</span><b className="mono">{cellPoint.source}</b></div>
                      <div className="net-kv-row"><span>Latitude</span><b className="mono">{cellPoint.lat.toFixed(5)}</b></div>
                      <div className="net-kv-row"><span>Longitude</span><b className="mono">{cellPoint.lon.toFixed(5)}</b></div>
                      <div className="net-kv-row"><span>Radius</span><b className="mono">≈ {Math.round(cellPoint.radius)} m</b></div>
                      {cellPoint.label && <div className="net-kv-row"><span>Label</span><b>{cellPoint.label}</b></div>}
                    </div>
                  ) : (
                    <div className="net-card-hint">No footprint yet — run the cascade (RUN IDENTIFICATION) to fly the camera to the tower-sector or country bounding footprint.</div>
                  )}
                  <div className="net-card-hint">
                    {tier === 2
                      ? 'Tier-2 reveal auto-flies the radar sector to the resolved control-plane footprint (OpenCelliD key or local cell DB).'
                      : 'Tier-1 bounds the footprint to the country / area-code territory. Unlock Tier 2 (LIVE gate) to zoom into the neighborhood grid.'}
                  </div>
                </div>
              </div>
            </section>
          )}

          {activeStep === 'ops' && (
            <section className="net-card tw-panel">
              <div className="net-card-title">
                <span className="tel-proc-n tel-proc-n-panel">05</span> LIVE OPS
                <span className={`net-chip ${sigStatus?.live ? 'tel-live-chip' : 'tel-sim-chip'}`}>
                  <span>{sigStatus?.live ? 'LIVE' : 'SIMULATED'}</span><b>{sigStatus?.backend ?? '…'}</b>
                </span>
              </div>
              <div className="net-card-row net-card-row-wrap">
                <button className="tool-btn" onClick={() => runOps(phone.trim())} disabled={!phone.trim()}>
                  <Link2 className="w-3 h-3" /> GENERATE CANARY LINK
                </button>
              </div>
              <div className="net-card-title-sm"><PhoneCall className="w-3 h-3" /> PRETEXT TEMPLATE SELECTOR</div>
              <div className="tw-pretext-list">
                {PRETEXT_TEMPLATES.map(t => (
                  <button
                    key={t.id}
                    className={`tw-pretext ${pretextId === t.id ? 'tw-pretext-on' : ''}`}
                    onClick={() => { setPretextId(t.id); if (phone.trim()) generateCanary(phone.trim(), t.id); setCopied(false); }}
                  >
                    <span className="tw-pretext-radio">{pretextId === t.id ? <Check className="w-3 h-3" /> : null}</span>
                    <span className="tw-pretext-body">
                      <b>{t.label}</b>
                      <i>{t.detail}</i>
                    </span>
                  </button>
                ))}
              </div>
              <div className="net-card-title-sm"><Link2 className="w-3 h-3" /> CANARY LINK GENERATOR</div>
              <div className="tw-canary">
                <div className="tw-canary-url mono">{canaryUrl ?? '— generate a canary link above —'}</div>
                <button className="tool-btn" onClick={copyCanary} disabled={!canaryUrl}>
                  {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />} {copied ? 'COPIED' : 'COPY URL'}
                </button>
              </div>
              <div className="net-card-hint">
                {pretext.label} — the canary URL is a real callback URL hosted by the ARK backend. Opening it (or a simulated target visit) records the timestamp, IP and user-agent in the CALLBACK LEDGER below. For a real remote target, serve the backend behind a reachable public URL or the arkgate.local DNS entry — localhost links only reach the machine they are opened on.
              </div>
              {canaryUrl && (
                <div className="tel-ref-facts">
                  <div className="osint-state-label">CALLBACK LEDGER</div>
                  <div className="net-card-row net-card-row-wrap">
                    <button className="tool-btn" onClick={async () => { if (canaryToken) { await api.canaryHit(canaryToken); await refreshCanaryHits(); } }} disabled={!canaryToken}>
                      <Satellite className="w-3 h-3" /> SIMULATE TARGET VISIT
                    </button>
                    <button className="tool-btn" onClick={refreshCanaryHits} disabled={!canaryToken || !sigToken}>
                      <RefreshCw className="w-3 h-3" /> REFRESH
                    </button>
                  </div>
                  {canaryHits.length === 0 ? (
                    <div className="osint-hint mono">No callbacks yet — send the link or simulate a visit.</div>
                  ) : (
                    <div className="tw-canary-hits mono">
                      {canaryHits.map((h, i) => (
                        <div key={i} className="tw-canary-hit">
                          <span>#{i + 1}</span><b>{h.ip}</b><i>{h.ts}</i><u>{h.ua.slice(0, 60)}</u>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {sigIdentity && sigToken ? (
                <div className="tel-ref-facts">
                  <div className="osint-state-label">CERTIFIED SIGNALING OPS</div>
                  <div className="net-card-row net-card-row-wrap">
                    <Field label="OPERATOR">
                      <input className="net-input net-input-sm" value={opOp} onChange={e => setOpOp(e.target.value)} />
                    </Field>
                    <Field label="MCC">
                      <input className="net-input net-input-sm" value={opMcc} maxLength={3}
                        onChange={e => setOpMcc(e.target.value.replace(/\D/g, ''))} />
                    </Field>
                    <button className="tool-btn" onClick={issueOpToken} disabled={sigBusy || !opOp || opMcc.length !== 3}>
                      <KeyRound className="w-3 h-3" /> {opToken ? 'REISSUE' : 'ISSUE'} OP TOKEN
                    </button>
                  </div>
                  <div className="net-card-row net-card-row-wrap" style={{ marginTop: 10 }}>
                    {(['sri', 'ulr', 'ati', 'plr', 'imsi', 'cgi'] as const).map(op => (
                      <button key={op} className="tool-btn" onClick={() => runLive(op)}
                        disabled={sigBusy || !opToken || !phone.trim()}>
                        {op.toUpperCase()}
                      </button>
                    ))}
                    <button className="tool-btn" onClick={runLiveSms}
                      disabled={sigBusy || !opToken || !phone.trim()} title="Silent SMS (SMS-PP / SM-DELIVER)">
                      <MessageSquareText className="w-3 h-3" /> SILENT SMS
                    </button>
                    <button className="tool-btn" onClick={runLiveCatcher}
                      disabled={sigBusy || !opToken} title="IMSI-catcher sweep (SDR test band)">
                      <Radio className="w-3 h-3" /> IMSI-CATCHER
                    </button>
                  </div>
                  {liveResult && (
                    <div className="tel-live-result">
                      <div className="net-kv-row"><span>Op</span><b className="mono">{liveResult.op.toUpperCase()}</b></div>
                      <div className="net-kv-row"><span>Backend</span><b className="mono">{liveResult.backend} · live={String(liveResult.live)}</b></div>
                      <div className="net-kv-row"><span>Trace</span><b className="mono">{liveResult.trace_id}</b></div>
                      <div className="net-kv-row"><span>Detail</span><b>{liveResult.detail}</b></div>
                      {liveResult.subscriber?.imsi && <div className="net-kv-row"><span>IMSI</span><b className="mono">{liveResult.subscriber.imsi}</b></div>}
                      {liveResult.cell?.cgi && <div className="net-kv-row"><span>CGI</span><b className="mono">{liveResult.cell.cgi}</b></div>}
                    </div>
                  )}
                  {gateError && <div className="net-status net-status-error">{gateError}</div>}
                </div>
              ) : (
                <div className="net-auth-note">
                  <Lock className="w-3 h-3" /> Certified signaling ops are gated — authenticate via the AUDIT step (LIVE mode) to issue operator tokens and run SRI / ULR / ATI / PLR / IMSI / CGI.
                </div>
              )}
            </section>
          )}

          {activeStep === 'assess' && (
            <section className="net-card tw-panel">
              <div className="net-card-title">
                <span className="tel-proc-n tel-proc-n-panel">06</span> AI ASSESSMENT
                <span className="net-chip tel-thread-chip">
                  <span>ENGINE</span><b className="mono">{analysis ? (analysis.ai_used ? analysis.engine : 'heuristic') : '…'}</b>
                </span>
              </div>
              <div className="net-card-row net-card-row-wrap">
                <button className="tool-btn" onClick={() => runAssess(phone.trim())} disabled={analysisBusy || !phone.trim()}>
                  {analysisBusy ? <Loader2 className="w-3 h-3 net-spin" /> : <Sparkles className="w-3 h-3" />} RUN AI ANALYSIS
                </button>
                <div className="tw-engine-note">
                  <ShieldCheck className="w-3 h-3" /> Model: <b className="mono">{byok.model.provider.toUpperCase()}</b>
                  {' · '}
                  {byok.model.provider === 'ollama'
                    ? <span className="mono">{byok.model.ollamaUrl} / {byok.model.ollamaModel || 'qwen2.5'}</span>
                    : <span className="mono">{byok.model.openRouterModel || 'cloud model'}</span>}
                  {' · '}Ollama/Qwen local or OpenAI-compatible cloud via the backend gateway; deterministic fallback when unreachable.
                </div>
              </div>
              <div className="net-card-hint">
                The orchestrator consumes the collected reference + OSINT + audit facts and produces three forensic sections — RISK PROFILE · GEOSPATIAL ANALYSIS · AUDIT NEXT-STEPS — through the backend model gateway.
              </div>
              {analysis && <ForensicBrief a={analysis} />}
              {analysisError && <div className="net-status net-status-error">{analysisError}</div>}
            </section>
          )}

          {activeStep === 'nolic' && <NoLicenseGeo />}
        </div>
      </div>

      {/* Footer — audit trail dock */}
      <div className="net-card tw-footer">
        <div className="net-card-row net-card-row-wrap">
          <button className={`tool-btn ${auditDock ? 'tool-btn-active' : ''}`} onClick={loadAudit}>
            <ScrollText className="w-3 h-3" /> LOAD AUDIT TRAIL
          </button>
          {sigToken && <span className="net-chip tel-tier-chip"><span>SESSION</span><b>CERTIFIED</b></span>}
          <div className="net-card-hint" style={{ flex: '1 1 260px', margin: 0 }}>
            Every certified signaling action (allowed + denied) is audit-logged. Admins see all operators; other certified roles see their own actions.
          </div>
        </div>
        {auditDock && (
          <div className="tel-audit-body">
            {!sigToken ? (
              <div className="net-auth-note">
                <Lock className="w-3 h-3" /> AUDIT TRAIL LOCKED — authenticate via the AUDIT step (LIVE mode) to load the log.
              </div>
            ) : auditEntries.length === 0 ? (
              <div className="net-card-hint">No entries loaded yet.</div>
            ) : (
              <div className="tel-audit-table">
                {auditEntries.map((a, i) => (
                  <div key={i} className="tel-audit-row mono">
                    <span>{a.ts_iso.slice(11, 19)}</span>
                    <b className={a.outcome === 'ALLOWED' ? 'ai-sev-ok' : 'ai-sev-risk'}>{a.outcome}</b>
                    <span>{a.op}</span>
                    <span>{a.actor}</span>
                    <span className="net-kv-dim">{a.detail}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

