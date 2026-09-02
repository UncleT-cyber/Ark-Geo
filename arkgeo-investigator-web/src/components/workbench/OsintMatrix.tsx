/**
 * OsintMatrix — Tier-1 Multi-Source OSINT Enrichment Matrix.
 *
 * 3-tab breakdown (Network Telemetry / Digital Footprint / Fraud Risk &
 * Reputation). All data is REAL:
 *   - reference facts come keylessly from Google libphonenumber metadata +
 *     public numbering plans (`/telecom/hlr-lookup` free tier);
 *   - provider tiers (HLR live state, CNAM, risk, social probes, SIM-swap)
 *     come from `/signaling/osint` and only appear when their key / flag is
 *     configured. Missing tiers show an honest "requires key" state.
 *
 * Nothing is fabricated. The historical-records & billing block renders a
 * derived ledger reconstructed from public numbering plans, libphonenumber
 * metadata and availability probes — never a fabricated carrier statement.
 */
import { useState } from 'react';
import { Activity, Radar, ShieldAlert, Globe2, Hash, Clock3, Landmark } from 'lucide-react';
import type { PhoneOsintResponse, HlrLookupResponse, PhoneFootprint, PhoneReputation } from '../../types';

type TabId = 'telemetry' | 'footprint' | 'reputation';

interface Props {
  phone: string;
  osint?: PhoneOsintResponse | null;
  reference?: HlrLookupResponse | null;
  footprint?: PhoneFootprint | null;
  presenceLinks?: { platform: string; kind: string; url: string }[];
}

const PLATFORMS: { key: string; label: string }[] = [
  { key: 'whatsapp', label: 'WhatsApp' },
  { key: 'telegram', label: 'Telegram' },
  { key: 'signal', label: 'Signal' },
  { key: 'viber', label: 'Viber' },
];

function scoreColor(score: number): string {
  if (score < 40) return '#22C55E';
  if (score < 70) return '#F59E0B';
  return '#EF4444';
}

function RiskGauge({ score }: { score: number }) {
  const clamped = Math.max(0, Math.min(100, score));
  const angle = (clamped / 100) * 180;
  const color = scoreColor(clamped);
  return (
    <div className="osint-gauge">
      <svg viewBox="0 0 120 66" width={150} height={82}>
        <path d="M10 60 A 50 50 0 0 1 110 60" fill="none" stroke="#1E293B" strokeWidth={12} strokeLinecap="round" />
        <path
          d="M10 60 A 50 50 0 0 1 110 60"
          fill="none"
          stroke={color}
          strokeWidth={12}
          strokeLinecap="round"
          strokeDasharray={`${(angle / 180) * 157} 157`}
        />
      </svg>
      <div className="osint-gauge-readout" style={{ color }}>
        {clamped}<span>/100</span>
      </div>
    </div>
  );
}

function PresenceCheck({ label, present }: { label: string; present: boolean }) {
  return (
    <div className={`osint-check ${present ? 'osint-check-on' : ''}`}>
      <span className="osint-checkbox">{present ? '☑' : '☐'}</span>
      <span>{label}</span>
      <b className="mono">{present ? 'FOUND' : '—'}</b>
    </div>
  );
}

function RequiresKey({ what }: { what: string }) {
  return (
    <div className="osint-key-state">
      <Landmark className="w-4 h-4" />
      <div>
        <div className="osint-state-label">REQUIRES KEY</div>
        <div className="osint-hint mono">{what}</div>
      </div>
    </div>
  );
}

export function OsintMatrix({ phone, osint, reference, footprint: footprintProp, presenceLinks: presenceLinksProp }: Props) {
  const [tab, setTab] = useState<TabId>('telemetry');

  const requiresKey = osint?.requires_key ?? (reference && reference.looked_up
    ? ['line-state', 'simswap', 'footprint', 'ipqs', 'opencnam']
    : []);
  const lineState = osint?.line_state ?? null;
  const simChanged = osint?.sim_last_changed ?? null;
  const simRisk = osint?.sim_swap_risk ?? null;
  const sameDevice = osint?.same_device_score ?? null;

  const d = {
    valid: osint?.valid ?? reference?.valid ?? false,
    possible: osint?.possible ?? reference?.possible ?? false,
    number_type: osint?.number_type ?? reference?.number_type ?? null,
    carrier: osint?.carrier ?? reference?.carrier ?? null,
    mcc: osint?.mcc ?? reference?.mcc ?? null,
    mnc: osint?.mnc ?? reference?.mnc ?? null,
    line_type: osint?.line_type ?? reference?.line_type ?? null,
    geo_zone: osint?.geo_zone ?? null,
    geo_city: osint?.geo_city ?? reference?.geo_city ?? null,
    timezone: (osint?.timezone && osint.timezone.length ? osint.timezone : reference?.timezone) ?? [],
    national_format: osint?.national_format ?? reference?.national_format ?? '',
    international_format: osint?.international_format ?? reference?.international_format ?? '',
    national_number: osint?.national_number ?? reference?.national_number ?? null,
    ndc: osint?.ndc ?? reference?.ndc ?? null,
    subscriber_number: osint?.subscriber_number ?? reference?.subscriber_number ?? null,
    phone_e164: osint?.phone_e164 ?? reference?.phone_e164 ?? phone,
    active: osint?.active ?? null,
    ported: osint?.ported ?? null,
    roaming: osint?.roaming_country ?? null,
    live_state: osint?.live_state ?? null,
  };

  const footprint: PhoneFootprint = footprintProp ?? osint?.footprint ?? { presence: {}, probed: false, simulated: false, note: '' };
  const reputation: PhoneReputation = osint?.reputation ?? { threat_intel_flags: [], simulated: false, note: '' };
  const risk = osint?.risk ?? {};
  const callerName = osint?.caller_name ?? null;

  const footprintReal = footprint.probed && Object.keys(footprint.presence ?? {}).length > 0;
  const fraudScore = typeof risk.fraud_score === 'number' ? risk.fraud_score : null;
  const repReal = fraudScore != null || callerName != null || reputation.threat_intel_flags?.length > 0;

  const socialData = (osint?.workers?.social?.data ?? {}) as { presence_links?: { platform: string; kind: string; url: string }[] };
  const presenceLinks = presenceLinksProp ?? socialData.presence_links ?? [];

  const presence = footprint.presence ?? {};

  return (
    <div className="osint-matrix">
      <div className="osint-tabs" role="tablist">
        {([
          ['telemetry', 'NETWORK TELEMETRY', Activity],
          ['footprint', 'DIGITAL FOOTPRINT', Radar],
          ['reputation', 'FRAUD RISK & REPUTATION', ShieldAlert],
        ] as [TabId, string, typeof Activity][]).map(([id, label, Icon]) => (
          <button key={id} role="tab" aria-selected={tab === id}
            className={`osint-tab ${tab === id ? 'osint-tab-active' : ''}`} onClick={() => setTab(id)}>
            <Icon className="w-3 h-3" /> {label}
          </button>
        ))}
      </div>

      {tab === 'telemetry' && (
        <div className="osint-tab-body">
          <div className="osint-state-block">
            {lineState ? (
              <>
                <div className="osint-pulse" style={{ background: lineState === 'DISCONNECTED' ? '#64748B' : '#22C55E', boxShadow: `0 0 0 4px ${lineState === 'DISCONNECTED' ? '#64748B' : '#22C55E'}22, 0 0 14px ${lineState === 'DISCONNECTED' ? '#64748B' : '#22C55E'}66` }} />
                <div>
                  <div className="osint-state-label">LINE STATE</div>
                  <div className="osint-state-value" style={{ color: lineState === 'DISCONNECTED' ? '#64748B' : '#22C55E' }}>{lineState}</div>
                </div>
              </>
            ) : (
              <>
                <div className="osint-pulse osint-pulse-key" />
                <div>
                  <div className="osint-state-label">LINE STATE</div>
                  <div className="osint-state-value" style={{ color: '#F59E0B' }}>REQUIRES KEY</div>
                </div>
                <span className="net-chip tel-sim-chip"><span>REQUIRES</span><b>HLR PROVIDER</b></span>
              </>
            )}
          </div>
          <div className="net-kv" style={{ marginTop: 12 }}>
            <div className="net-kv-row"><Globe2 className="w-3 h-3" /> <span>E.164</span><b className="mono">{d.phone_e164 || '—'}</b></div>
            <div className="net-kv-row"><span>Reference validity</span><b className="mono">{d.valid ? 'VALID' : 'INVALID'}{d.possible ? ' · possible' : ' · not possible'}</b></div>
            <div className="net-kv-row"><span>Number type</span><b className="mono">{d.number_type ?? '—'}</b></div>
            <div className="net-kv-row"><span>Line type</span><b className="mono">{d.line_type ?? '—'}</b></div>
            {d.carrier && <div className="net-kv-row"><span>Carrier</span><b>{d.carrier} {d.mcc ? `· MCC ${d.mcc} MNC ${d.mnc ?? '?'}` : ''}</b></div>}
            {d.geo_zone && <div className="net-kv-row"><span>Geo zone</span><b>{d.geo_zone}</b></div>}
            {d.geo_city && <div className="net-kv-row"><span>Geo city</span><b>{d.geo_city}</b></div>}
            {d.timezone.length > 0 && <div className="net-kv-row"><Clock3 className="w-3 h-3" /> <span>Timezone</span><b className="mono">{d.timezone.join(', ')}</b></div>}
            {d.national_format && <div className="net-kv-row"><Hash className="w-3 h-3" /> <span>National format</span><b className="mono">{d.national_format}</b></div>}
            {d.international_format && <div className="net-kv-row"><span>International</span><b className="mono">{d.international_format}</b></div>}
            {d.subscriber_number && <div className="net-kv-row"><span>Subscriber</span><b className="mono">NDC {d.ndc ?? '?'} · {d.subscriber_number}</b></div>}
            {d.live_state && <div className="net-kv-row"><span>Live state</span><b className="mono">{d.live_state}</b></div>}
            {d.active != null && <div className="net-kv-row"><span>HLR attached</span><b className="mono">{d.active ? 'ON' : 'OFF'}</b></div>}
            {d.ported != null && <div className="net-kv-row"><span>Ported</span><b className="mono">{String(d.ported)}</b></div>}
            {d.roaming && <div className="net-kv-row"><span>Roaming</span><b>{d.roaming}</b></div>}
            {simChanged && <div className="net-kv-row"><span>SIM last changed</span><b className="mono">{simChanged}</b></div>}
            {simRisk != null && <div className="net-kv-row"><span>SIM-swap risk</span><b className="mono">{(simRisk * 100).toFixed(0)}% {simRisk > 0.7 ? '· SUSPECTED' : '· LOW'}</b></div>}
            {sameDevice != null && <div className="net-kv-row"><span>Same-device score</span><b className="mono">{(sameDevice * 100).toFixed(0)}%</b></div>}
          </div>
          {requiresKey.length > 0 && (
            <div className="osint-key-row">
              <span className="osint-key-label mono">REQUIRES KEY</span>
              {requiresKey.map(k => <span key={k} className="net-chip tel-sim-chip mono">{k}</span>)}
            </div>
          )}
          <div className="osint-hint mono">
            Reference facts: Google libphonenumber metadata · public numbering plans · national dialling registries.
            {requiresKey.includes('line-state') && ' Line state (ON/OFF) is a live HLR signal — there is no lawful keyless source; wire a working IPQS / Twilio / Infobip phone-lookup key to capture it.'}
          </div>
        </div>
      )}

      {tab === 'footprint' && (
        <div className="osint-tab-body">
          {footprintReal ? (
            <>
              <div className="osint-state-label">PLATFORM PRESENCE (PROBED)</div>
              <div className="osint-check-grid">
                {PLATFORMS.map(p => <PresenceCheck key={p.key} label={p.label} present={Boolean(presence[p.key])} />)}
              </div>
              <div className="osint-hint mono">{footprint.note}</div>
              {(footprint.probes ?? []).length > 0 && (
                <div className="osint-hint mono" style={{ marginTop: 6 }}>
                  {(footprint.probes as { platform: string; status_code: number }[]).map(p =>
                    `${p.platform} HTTP ${p.status_code}`
                  ).join(' · ')}
                </div>
              )}
            </>
          ) : (
            <RequiresKey what="No availability signal returned from the platform resolvers (wa.me / t.me / chats.viber.com / signal.me). Digital-footprint probes are an availability signal only — no account enumeration." />
          )}
          {presenceLinks.length > 0 && (
            <>
              <div className="net-card-sep" />
              <div className="osint-state-label">OPERATOR PRESENCE LINKS</div>
              <div className="osint-link-grid">
                {presenceLinks.map(l => (
                  <a key={l.platform} className="osint-link mono" href={l.url} target="_blank" rel="noreferrer">
                    <span>{l.platform}</span><b>↗</b>
                  </a>
                ))}
              </div>
              <div className="osint-hint mono">Link builders only — live profile / avatar / last-seen enumeration requires approved platform integration.</div>
            </>
          )}
        </div>
      )}

      {tab === 'reputation' && (
        <div className="osint-tab-body">
          {repReal ? (
            <div className="osint-rep-row">
              <div>
                <div className="osint-state-label">SPAM SCORE</div>
                {fraudScore != null ? <RiskGauge score={fraudScore} /> : <div className="osint-hint mono">No provider risk feed.</div>}
              </div>
              <div className="osint-flags">
                <div className="osint-state-label">REGISTRIES / FLAGS</div>
                {callerName && <div className="osint-check osint-check-on"><span className="osint-checkbox">☑</span><span>Caller ID</span><b className="mono">{callerName}</b></div>}
                {(risk.spam != null) && <div className="osint-check osint-check-on"><span className="osint-checkbox">⚠</span><span>Spam databases</span><b className="mono">{risk.spam ? 'HIT' : '—'}</b></div>}
                {(risk.risky != null) && <div className="osint-check osint-check-on"><span className="osint-checkbox">⚠</span><span>Risk behaviour</span><b className="mono">{risk.risky ? 'FLAGGED' : '—'}</b></div>}
                {(risk.leaktory != null) && <div className="osint-check osint-check-on"><span className="osint-checkbox">⚠</span><span>Leak compilation</span><b className="mono">{risk.leaktory ? 'HIT' : '—'}</b></div>}
                {reputation.threat_intel_flags?.map(f => (
                  <div key={f} className="osint-check osint-check-on"><span className="osint-checkbox">⚠</span><span className="mono">{f}</span></div>
                ))}
                {reputation.note && <div className="osint-hint mono">{reputation.note}</div>}
              </div>
            </div>
          ) : (
            <RequiresKey what="Spam score & threat-intel flags need a licensed provider feed (IPQS key). Caller-ID name needs OpenCNAM credentials." />
          )}
        </div>
      )}

      <div className="net-card-sep" />
      <div className="osint-billing-head">
        <div className="net-card-title-sm"><Landmark className="w-3 h-3" /> HISTORICAL RECORDS &amp; BILLING</div>
        <span className="net-chip tel-thread-chip"><span>DERIVED LEDGER</span><b>KEYLESS</b></span>
      </div>
      <div className="net-kv" style={{ marginTop: 8 }}>
        <div className="net-kv-row"><span>Number</span><b className="mono">{d.phone_e164 || '—'}</b></div>
        <div className="net-kv-row"><span>Carrier</span><b>{d.carrier || '—'}{d.mcc ? ` · MCC ${d.mcc} MNC ${d.mnc ?? '?'}` : ''}</b></div>
        <div className="net-kv-row"><span>Line type</span><b className="mono">{d.line_type ?? '—'}</b></div>
        <div className="net-kv-row"><span>Registration zone</span><b>{d.geo_zone || d.geo_city || '—'}</b></div>
        <div className="net-kv-row"><span>Timezone</span><b className="mono">{d.timezone.length ? d.timezone.join(', ') : '—'}</b></div>
        <div className="net-kv-row"><span>Ported</span><b className="mono">{d.ported == null ? '—' : String(d.ported)}</b></div>
        <div className="net-kv-row"><span>Line attached</span><b className="mono">{d.active == null ? '—' : d.active ? 'ON' : 'OFF'}</b></div>
        {callerName && <div className="net-kv-row"><span>Caller-ID name</span><b>{callerName}</b></div>}
      </div>
      <div className="osint-hint mono">
        Derived ledger reconstructed from public numbering plans, libphonenumber metadata and availability probes — it is not a carrier billing statement. A licensed billing integration (e.g. IPQS / Infobip / Twilio Lookup) can layer real call and message history behind a provider tier.
      </div>
    </div>
  );
}
