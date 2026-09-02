/**
 * NetworkWorkbench — active Network Intelligence Workspace.
 *
 * Six tabs (route-style, matching the blueprint):
 *   /network/discovery  passive RDAP / BGP / DNS / CT enumeration
 *   /network/traffic    minimal .pcap ingest + connection candidates
 *   /network/webapp     single-request HTTP security-header audit
 *   /network/endpoints  certificate-transparency endpoint discovery
 *   /network/testing    authorized security-testing surface (Phase 3 gate)
 *   /network/telecom    phone + cell intelligence (E.164 / HLR / footprint)
 *
 * Every tab folds structured observations into the active case via
 * useInvestigation.appendCaseObservations and, for telecom, pushes cell
 * tower coordinates onto the shared Leaflet MapWorkspace.
 */
import React, { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { useInvestigation, type CaseObservation } from './useInvestigation';
import { parsePcap, type PcapResult } from '../../core/network/pcapReader';
import type {
  NetworkRdapResponse, NetworkBgpResponse,
  NetworkDnsResponse, NetworkCrtResponse, WebProbeResponse,
} from '../../types';
import {
  Radar, Activity, Globe, Waypoints, ShieldCheck, Smartphone,
  Upload, Search, Loader2,
  type LucideIcon,
} from 'lucide-react';
import { TelecomWorkspace } from './TelecomWorkspace';
import { SecurityTestingTab } from '../network/tabs/SecurityTestingTab';

export type NetworkTabId = 'discovery' | 'traffic' | 'webapp' | 'endpoints' | 'testing' | 'telecom';

export const NETWORK_TABS: { id: NetworkTabId; label: string; icon: LucideIcon; hint: string }[] = [
  { id: 'discovery', label: 'Network Discovery', icon: Radar, hint: 'RDAP / BGP / DNS / certificate transparency (passive)' },
  { id: 'traffic', label: 'Traffic Analysis', icon: Activity, hint: 'Ingest a .pcap capture and summarize connections' },
  { id: 'webapp', label: 'HTTP / Web Analysis', icon: Globe, hint: 'Passive security-header audit of a single URL' },
  { id: 'endpoints', label: 'Endpoint Mapping', icon: Waypoints, hint: 'Subdomain & endpoint discovery from CT logs' },
  { id: 'testing', label: 'Authorized Security Testing', icon: ShieldCheck, hint: 'Risk-gated scanning engines (Phase 3)' },
  { id: 'telecom', label: 'Telecom & Phone', icon: Smartphone, hint: 'HLR lookup, cell tower spatial, phone footprint' },
];

interface StatusBox {
  busy: boolean;
  error: string | null;
}

function Status({ busy, error }: StatusBox) {
  if (busy) {
    return (
      <div className="net-status net-status-busy">
        <Loader2 className="w-3 h-3 net-spin" /> Running passive query...
      </div>
    );
  }
  if (error) {
    return (
      <div className="net-status net-status-error">
        <div className="error-box" style={{ margin: 0 }}>
          <div className="error-title">NETWORK ERROR</div>
          <div className="error-detail">{error}</div>
        </div>
      </div>
    );
  }
  return null;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="net-field">
      <span className="net-field-label">{label}</span>
      {children}
    </label>
  );
}

// --------------------------------------------------------------------------- //
// /network/discovery
// --------------------------------------------------------------------------- //
function DiscoveryTab() {
  const inv = useInvestigation();
  const [target, setTarget] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rdap, setRdap] = useState<NetworkRdapResponse | null>(null);
  const [bgp, setBgp] = useState<NetworkBgpResponse | null>(null);
  const [dns, setDns] = useState<NetworkDnsResponse | null>(null);
  const [crt, setCrt] = useState<NetworkCrtResponse | null>(null);
  const [folded, setFolded] = useState(false);

  const run = async () => {
    const t = target.trim();
    if (!t) return;
    setBusy(true); setError(null); setRdap(null); setBgp(null); setDns(null); setCrt(null); setFolded(false);
    try {
      const rd = await api.rdap(t);
      setRdap(rd);
      const isIp = /^\d{1,3}(\.\d{1,3}){3}$/.test(t);
      if (isIp) {
        const bg = await api.bgpLookup(t);
        setBgp(bg);
      }
      const dn = await api.dnsLookup(t, isIp ? 'A' : 'A');
      setDns(dn);
      if (!isIp) {
        const cr = await api.crtSearch(t);
        setCrt(cr);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Discovery failed');
    } finally {
      setBusy(false);
    }
  };

  const fold = () => {
    const obs: CaseObservation[] = [];
    if (rdap) {
      obs.push({
        type: 'RDAP', status: 'OBSERVED', layer: 'passive_registry', label: 'RDAP registration',
        detail: `${rdap.kind} ${rdap.target} - ${rdap.registered_org || rdap.name || 'no registrant'}${rdap.handle ? ` (handle ${rdap.handle})` : ''}`,
        source: 'tool_inference',
      });
    }
    if (bgp && bgp.asn) {
      obs.push({
        type: 'BGP', status: 'OBSERVED', layer: 'passive_routing', label: `BGP AS${bgp.asn} ${bgp.asn_name || ''}`,
        detail: `ptr ${bgp.ptr_record || 'none'} - ${bgp.prefixes.length} prefix(es)`,
        source: 'tool_inference',
      });
    }
    if (dns && dns.answers.length) {
      obs.push({
        type: 'DNS', status: 'OBSERVED', layer: 'passive_dns', label: `DNS ${dns.type} ${dns.qname}`,
        detail: dns.answers.slice(0, 5).map(a => a.data).join(', '),
        source: 'tool_inference',
      });
    }
    if (crt && crt.certificates.length) {
      obs.push({
        type: 'CERT_TRANSPARENCY', status: 'OBSERVED', layer: 'passive_ct', label: `${crt.certificates.length} certificates issued`,
        detail: `CT logs for ${crt.domain} - ${crt.certificates.length} distinct cert(s)`,
        source: 'tool_inference',
      });
    }
    if (obs.length) { inv.appendCaseObservations(obs); setFolded(true); }
  };

  return (
    <div className="tool-view">
      <div className="net-card">
        <div className="net-card-title">PASSIVE NETWORK DISCOVERY</div>
        <div className="net-card-row">
          <Field label="TARGET (IP OR DOMAIN)">
            <input
              className="net-input"
              value={target}
              placeholder="example.com or 1.2.3.4"
              onChange={e => setTarget(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') run(); }}
            />
          </Field>
          <button className="tool-btn" onClick={run} disabled={busy || !target.trim()}>
            {busy ? <Loader2 className="w-3 h-3 net-spin" /> : <Search className="w-3 h-3" />} ENUMERATE
          </button>
        </div>
        <div className="net-card-hint">
          rdap.org (registration) · bgpview.io (ASN) · Cloudflare DoH (A) · crt.sh (CT). Passive only - no packets are sent to the target.
        </div>
      </div>

      <Status busy={busy} error={error} />

      {(rdap || bgp || dns || crt) && (
        <div className="net-results">
          {rdap && (
            <div className="net-card">
              <div className="net-card-title">RDAP - {rdap.kind.toUpperCase()}</div>
              <div className="net-kv">
                <div className="net-kv-row"><span>Registrant</span><b>{rdap.registered_org || rdap.name || '-'}</b></div>
                {rdap.handle && <div className="net-kv-row"><span>Handle</span><b className="mono">{rdap.handle}</b></div>}
                {rdap.cidr && <div className="net-kv-row"><span>CIDR</span><b className="mono">{rdap.cidr}</b></div>}
                {rdap.start_address && <div className="net-kv-row"><span>Range</span><b className="mono">{rdap.start_address} - {rdap.end_address}</b></div>}
                {rdap.events?.length ? <div className="net-kv-row"><span>Registered</span><b className="mono">{rdap.events.find(e => e.eventAction === 'registration')?.eventDate || '-'}</b></div> : null}
                <div className="net-kv-row"><span>Status</span><b>{rdap.status?.join(', ') || '-'}</b></div>
              </div>
            </div>
          )}
          {bgp && (
            <div className="net-card">
              <div className="net-card-title">BGP / ASN - {bgp.ip}</div>
              <div className="net-kv">
                <div className="net-kv-row"><span>PTR</span><b className="mono">{bgp.ptr_record || '-'}</b></div>
                {bgp.asn && <div className="net-kv-row"><span>ASN</span><b className="mono">AS{bgp.asn} {bgp.asn_name || ''} ({bgp.asn_country || '?'})</b></div>}
                {bgp.asn && <div className="net-kv-row"><span>Owner</span><b>{bgp.asn_description || '-'}</b></div>}
                <div className="net-kv-row"><span>Prefixes</span><b className="mono">{bgp.prefixes.slice(0, 6).map(p => p.prefix).join(', ') || '-'}</b></div>
              </div>
            </div>
          )}
          {dns && (
            <div className="net-card">
              <div className="net-card-title">DNS {dns.type} - {dns.qname}</div>
              <div className="net-kv">
                {dns.answers.slice(0, 12).map((a, i) => (
                  <div className="net-kv-row" key={i}><span>TTL {a.ttl}</span><b className="mono">{a.data}</b></div>
                ))}
                {!dns.answers.length && <div className="net-kv-row"><span>No answers</span><b>NXDOMAIN / empty set</b></div>}
              </div>
            </div>
          )}
          {crt && (
            <div className="net-card">
              <div className="net-card-title">CERTIFICATE TRANSPARENCY - {crt.certificates.length} Certs</div>
              <div className="net-kv">
                <div className="net-kv-row"><span>Issuer</span><b>{crt.certificates[0]?.issuer_name || '-'}</b></div>
                <div className="net-kv-row"><span>Not after</span><b className="mono">{crt.certificates[0]?.not_after || '-'}</b></div>
                <div className="net-kv-row"><span>Alt names</span><b>{crt.certificates.slice(0, 3).map(c => c.name_value).filter(Boolean).join(' | ') || '-'}</b></div>
              </div>
            </div>
          )}
          <button className="tool-btn" onClick={fold} disabled={folded}>
            {folded ? 'FOLDED INTO CASE' : 'FOLD OBSERVATIONS INTO CASE'}
          </button>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// /network/traffic
// --------------------------------------------------------------------------- //
function TrafficTab() {
  const inv = useInvestigation();
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PcapResult | null>(null);
  const [folded, setFolded] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);

  const onFile = async (f: File | null) => {
    if (!f) return;
    setBusy(true); setError(null); setResult(null); setFolded(false); setFileName(f.name);
    try {
      const buf = await f.arrayBuffer();
      const parsed = parsePcap(buf);
      setResult(parsed);
      if (!parsed.ok) setError(parsed.detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'pcap parse failed');
    } finally {
      setBusy(false);
    }
  };

  const fold = () => {
    if (!result || !result.ok) return;
    const obs: CaseObservation[] = [];
    obs.push({
      type: 'PCAP_INGEST', status: 'OBSERVED', layer: 'traffic_capture', label: `Capture ${fileName || ''} parsed`,
      detail: `${result.packets.length} packets, ${result.uniqueIps.length} unique IPs`,
      source: 'tool_inference',
    });
    const top = result.connections[0];
    if (top) {
      obs.push({
        type: 'TRAFFIC', status: top.proto === 'OTHER' ? 'OBSERVED' : 'OBSERVED', layer: 'traffic_flows',
        label: `Top flow: ${top.src}:${top.sport || '?'} -> ${top.dst}:${top.dport || '?'} (${top.proto})`,
        detail: `${top.packets} packets, ${top.bytes} bytes`,
        source: 'tool_inference',
      });
    }
    const anyRawIp = result.uniqueIps.some(ip => ip !== '?');
    if (anyRawIp) {
      obs.push({
        type: 'TRAFFIC', status: 'OBSERVED', layer: 'traffic_flows',
        label: `${result.uniqueIps.length} endpoint IPs`,
        detail: result.uniqueIps.filter(ip => ip !== '?').slice(0, 8).join(', '),
        source: 'tool_inference',
      });
    }
    if (obs.length) { inv.appendCaseObservations(obs); setFolded(true); }
  };

  return (
    <div className="tool-view">
      <div className="net-card">
        <div className="net-card-title">TRAFFIC ANALYSIS - .PCAP INGEST</div>
        <div className="net-card-row">
          <button className="tool-btn" onClick={() => fileRef.current?.click()} disabled={busy}>
            <Upload className="w-3 h-3" /> {fileName || 'SELECT .PCAP'}
          </button>
          <input ref={fileRef} type="file" accept=".pcap,application/vnd.tcpdump.pcap" style={{ display: 'none' }} onChange={e => onFile(e.target.files?.[0] ?? null)} />
          {busy && <span className="net-card-hint"><Loader2 className="w-3 h-3 net-spin" /> Parsing...</span>}
        </div>
        <div className="net-card-hint">
          Phase 1: classic .pcap (Ethernet/NULL/RAW), IPv4/IPv6, TCP/UDP/ICMP. pcapng + tshark enrichment land in a later phase.
        </div>
      </div>

      <Status busy={busy} error={error} />

      {result && result.ok && (
        <div className="net-results">
          <div className="net-chips">
            <div className="net-chip"><span>Packets</span><b>{result.packets.length}</b></div>
            <div className="net-chip"><span>Unique IPs</span><b>{result.uniqueIps.length}</b></div>
            <div className="net-chip"><span>TCP</span><b>{result.protoCounts.TCP || 0}</b></div>
            <div className="net-chip"><span>UDP</span><b>{result.protoCounts.UDP || 0}</b></div>
            <div className="net-chip"><span>ICMP</span><b>{result.protoCounts.ICMP || 0}</b></div>
            <div className="net-chip"><span>Connections</span><b>{result.connections.length}</b></div>
          </div>
          <div className="net-card">
            <div className="net-card-title">CONNECTION CANDIDATES (BY BYTES)</div>
            {result.connections.length === 0 ? (
              <div className="net-empty">No TCP/UDP flows parsed from this capture.</div>
            ) : (
              <table className="net-table">
                <thead>
                  <tr><th>PROTO</th><th>SRC</th><th>PORT</th><th>DST</th><th>PORT</th><th>PKTS</th><th>BYTES</th></tr>
                </thead>
                <tbody>
                  {result.connections.slice(0, 50).map((c, i) => (
                    <tr key={i}>
                      <td>{c.proto}</td>
                      <td className="mono">{c.src}</td>
                      <td className="mono">{c.sport ?? '-'}</td>
                      <td className="mono">{c.dst}</td>
                      <td className="mono">{c.dport ?? '-'}</td>
                      <td>{c.packets}</td>
                      <td>{c.bytes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <button className="tool-btn" onClick={fold} disabled={folded}>
            {folded ? 'FOLDED INTO CASE' : 'FOLD OBSERVATIONS INTO CASE'}
          </button>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// /network/webapp
// --------------------------------------------------------------------------- //
function WebappTab() {
  const inv = useInvestigation();
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [probe, setProbe] = useState<WebProbeResponse | null>(null);
  const [folded, setFolded] = useState(false);

  const run = async () => {
    const u = url.trim();
    if (!u) return;
    setBusy(true); setError(null); setProbe(null); setFolded(false);
    try {
      setProbe(await api.webProbe(u));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Web probe failed');
    } finally {
      setBusy(false);
    }
  };

  const gradeColor = (g: string) => {
    if (g === 'A') return '#22C55E';
    if (g === 'B') return '#84CC16';
    if (g === 'C') return '#F59E0B';
    return '#EF4444';
  };

  const fold = () => {
    if (!probe) return;
    const missing = Object.entries(probe.security_headers).filter(([, h]) => !h.present);
    const weak = Object.entries(probe.security_headers).filter(([, h]) => h.present && h.ok === false);
    const obs: CaseObservation[] = [];
    obs.push({
      type: 'WEB_PROBE', status: probe.status_code && probe.status_code >= 400 ? 'ANOMALY' : 'OBSERVED',
      layer: 'http_headers', label: `HTTP ${probe.status_code || '?'} security grade ${probe.grade || '-'}`,
      detail: `${probe.url} final ${probe.final_url}`,
      source: 'tool_inference',
    });
    missing.slice(0, 8).forEach(([name]) => {
      obs.push({
        type: 'WEB_HEADER', status: 'NOT_OBSERVED', layer: 'http_headers',
        label: `Missing security header: ${name}`, detail: probe.security_headers[name].detail,
        source: 'tool_inference',
      });
    });
    weak.slice(0, 8).forEach(([name]) => {
      obs.push({
        type: 'WEB_HEADER', status: 'ANOMALY', layer: 'http_headers',
        label: `Weak security header: ${name}`, detail: probe.security_headers[name].detail,
        source: 'tool_inference',
      });
    });
    if (obs.length) { inv.appendCaseObservations(obs); setFolded(true); }
  };

  return (
    <div className="tool-view">
      <div className="net-card">
        <div className="net-card-title">HTTP / WEB APPLICATION ANALYSIS</div>
        <div className="net-card-row">
          <Field label="URL">
            <input
              className="net-input"
              value={url}
              placeholder="https://example.com/"
              onChange={e => setUrl(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') run(); }}
            />
          </Field>
          <button className="tool-btn" onClick={run} disabled={busy || !url.trim()}>
            {busy ? <Loader2 className="w-3 h-3 net-spin" /> : <Search className="w-3 h-3" />} PROBE
          </button>
        </div>
        <div className="net-card-hint">
          One passive GET (headers only) to audit 7 security headers + a letter grade. No payloads, no crawling.
        </div>
      </div>

      <Status busy={busy} error={error} />

      {probe && (
        <div className="net-results">
          <div className="net-card">
            <div className="net-card-title">
              {probe.url} <span style={{ color: gradeColor(probe.grade || '') }}>GRADE {probe.grade || '-'}</span>
            </div>
            <div className="net-kv">
              <div className="net-kv-row"><span>Status</span><b>{probe.status_code ?? '-'}</b></div>
              <div className="net-kv-row"><span>Final URL</span><b className="mono">{probe.final_url}</b></div>
            </div>
            <div className="net-kv">
              {Object.entries(probe.security_headers).map(([name, h]) => (
                <div className="net-kv-row" key={name}>
                  <span>{name.toUpperCase()}</span>
                  <b className={h.ok ? 'net-ok' : h.ok === false ? 'net-bad' : ''}>
                    {h.ok === false ? 'MISCONFIGURED' : h.present ? 'PRESENT' : 'MISSING'}
                  </b>
                </div>
              ))}
            </div>
            {Object.keys(probe.tech_hints).length > 0 && (
              <div className="net-kv">
                {Object.entries(probe.tech_hints).map(([k, v]) => (
                  <div className="net-kv-row" key={k}><span>{k.toUpperCase()}</span><b className="mono">{v}</b></div>
                ))}
              </div>
            )}
          </div>
          <button className="tool-btn" onClick={fold} disabled={folded}>
            {folded ? 'FOLDED INTO CASE' : 'FOLD OBSERVATIONS INTO CASE'}
          </button>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// /network/endpoints
// --------------------------------------------------------------------------- //
function EndpointsTab() {
  const inv = useInvestigation();
  const [domain, setDomain] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [crt, setCrt] = useState<NetworkCrtResponse | null>(null);
  const [folded, setFolded] = useState(false);

  const run = async () => {
    const d = domain.trim();
    if (!d) return;
    setBusy(true); setError(null); setCrt(null); setFolded(false);
    try {
      setCrt(await api.crtSearch(d));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'CT search failed');
    } finally {
      setBusy(false);
    }
  };

  const names = crt
    ? Array.from(new Set((crt.certificates || []).flatMap(c => (c.name_value || '').split('\n').map(s => s.trim()).filter(Boolean))))
    : [];

  const fold = () => {
    if (!crt) return;
    const obs: CaseObservation[] = [];
    obs.push({
      type: 'ENDPOINT', status: 'OBSERVED', layer: 'endpoint_mapping',
      label: `${names.length} endpoints discovered for ${crt.domain}`,
      detail: names.slice(0, 10).join(', '),
      source: 'tool_inference',
    });
    inv.appendCaseObservations(obs);
    setFolded(true);
  };

  return (
    <div className="tool-view">
      <div className="net-card">
        <div className="net-card-title">ENDPOINT DISCOVERY - CERTIFICATE TRANSPARENCY</div>
        <div className="net-card-row">
          <Field label="DOMAIN">
            <input
              className="net-input"
              value={domain}
              placeholder="example.com"
              onChange={e => setDomain(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') run(); }}
            />
          </Field>
          <button className="tool-btn" onClick={run} disabled={busy || !domain.trim()}>
            {busy ? <Loader2 className="w-3 h-3 net-spin" /> : <Search className="w-3 h-3" />} DISCOVER
          </button>
        </div>
        <div className="net-card-hint">
          Queries crt.sh for every certificate ever issued to the domain - subdomains and alternate names become the endpoint map.
        </div>
      </div>

      <Status busy={busy} error={error} />

      {crt && (
        <div className="net-results">
          <div className="net-chips">
            <div className="net-chip"><span>Certificates</span><b>{crt.certificates.length}</b></div>
            <div className="net-chip"><span>Distinct names</span><b>{names.length}</b></div>
          </div>
          <div className="net-card">
            <div className="net-card-title">ENDPOINT NAMES</div>
            {names.length === 0 ? (
              <div className="net-empty">No names extracted.</div>
            ) : (
              <div className="net-taglist">
                {names.slice(0, 120).map((n, i) => <span key={i} className="net-tag mono">{n}</span>)}
              </div>
            )}
          </div>
          <button className="tool-btn" onClick={fold} disabled={folded}>
            {folded ? 'FOLDED INTO CASE' : 'FOLD OBSERVATIONS INTO CASE'}
          </button>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// /network/testing — see src/components/network/tabs/SecurityTestingTab.tsx
// (attestation-gated workspace with 5 assessment modules).
// --------------------------------------------------------------------------- //
interface NetworkWorkbenchProps {
  activeTab: NetworkTabId;
  onTabChange: (t: NetworkTabId) => void;
}

export function NetworkWorkbench({ activeTab, onTabChange }: NetworkWorkbenchProps) {
  return (
    <div className="network-workbench">
      <div className="tool-subtabs net-subtabs">
        {NETWORK_TABS.map(t => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              className={`tool-subtab ${activeTab === t.id ? 'tool-subtab-active' : ''}`}
              onClick={() => onTabChange(t.id)}
              title={t.hint}
            >
              <Icon className="w-3 h-3" /> {t.label}
            </button>
          );
        })}
      </div>
      {activeTab === 'discovery' && <DiscoveryTab />}
      {activeTab === 'traffic' && <TrafficTab />}
      {activeTab === 'webapp' && <WebappTab />}
      {activeTab === 'endpoints' && <EndpointsTab />}
      {activeTab === 'testing' && <SecurityTestingTab />}
      {activeTab === 'telecom' && <TelecomWorkspace />}
    </div>
  );
}
