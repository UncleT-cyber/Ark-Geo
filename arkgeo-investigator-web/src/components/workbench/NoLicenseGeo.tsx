/**
 * NoLicenseGeo — keyless phone / cell geolocation (no provider licence).
 *
 * Three licence-free paths, all backed by app/services/cell_geolocator.py:
 *   1. PHONE → REGION  : E.164 prefix mapped to MCC → mean of that operator's
 *      known towers (coarse, region/city level — never a live device fix).
 *   2. CGI → OPEN DB    : MCC/MNC/LAC/CellID resolved against the local open
 *      cell DB (provider=local) or the keyless community BeaconDB (beacondb-open).
 *   3. CAPTURE → FIX    : a set of captured neighbour cells (from your own SDR /
 *      IMSI-catcher sweep, which needs no operator licence) multilaterated into
 *      a fine position.
 *
 * The backend still keeps the licensed OpenCelliD/IPQS path intact — this is
 * the parallel, licence-free capability.
 */
import React, { useState } from 'react';
import { MapWorkspace, type MapPoint } from '../MapWorkspace/MapWorkspace';
import { api } from '../../api';
import { Loader2, Radio, Satellite, Smartphone, MapPin } from 'lucide-react';
import type {
  PhoneLocateResponse, CellLookupResponse, CaptureGeolocateResponse, CaptureObservation,
} from '../../types';

function ToolBtn({ onClick, busy, children, disabled }: { onClick: () => void; busy?: boolean; children: React.ReactNode; disabled?: boolean }) {
  return (
    <button className="tool-btn" onClick={onClick} disabled={disabled || busy}>
      {busy ? <Loader2 className="w-3 h-3 net-spin" /> : null}{children}
    </button>
  );
}

function KV({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="net-kv-row"><span>{k}</span><b className="mono">{v}</b></div>;
}

export function NoLicenseGeo() {
  const [points, setPoints] = useState<MapPoint[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // 1. phone -> region
  const [phone, setPhone] = useState('');
  const [phoneBusy, setPhoneBusy] = useState(false);
  const [phoneRes, setPhoneRes] = useState<PhoneLocateResponse | null>(null);

  // 2. cgi -> open db
  const [mcc, setMcc] = useState('');
  const [mnc, setMnc] = useState('');
  const [lac, setLac] = useState('');
  const [cid, setCid] = useState('');
  const [provider, setProvider] = useState<'local' | 'beacondb-open'>('local');
  const [cgiBusy, setCgiBusy] = useState(false);
  const [cgiRes, setCgiRes] = useState<CellLookupResponse | null>(null);

  // 3. capture -> fix
  const [obsText, setObsText] = useState(
    '621,30,1001,12345,-60\n621,30,1002,12346,-72\n621,20,2001,22345,-84',
  );
  const [captureBusy, setCaptureBusy] = useState(false);
  const [captureRes, setCaptureRes] = useState<CaptureGeolocateResponse | null>(null);

  const fly = (lat: number, lon: number, radius: number, label: string, source: string) => {
    setPoints([{ lat, lon, radius, confidence: 0.6, source, label, pulse: true, sector: true }]);
  };

  const runPhone = async () => {
    if (!phone.trim()) return;
    setPhoneBusy(true); setErr(null); setPhoneRes(null);
    try {
      const r = await api.phoneLocate(phone.trim());
      setPhoneRes(r);
      if (r.lat != null && r.lon != null) {
        fly(r.lat, r.lon, r.radius_m ?? 30000, `PHONE REGION ${r.phone_e164}`, 'PHONE_REGION');
        setNote(r.detail);
      } else {
        setNote(r.detail);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'phone-locate failed');
    } finally {
      setPhoneBusy(false);
    }
  };

  const runCgi = async () => {
    const m = parseInt(mcc, 10), n = parseInt(mnc, 10), c = parseInt(cid, 10);
    if (!m || !n || !c) { setErr('MCC / MNC / Cell ID are required'); return; }
    setCgiBusy(true); setErr(null); setCgiRes(null);
    try {
      const r = await api.cellLookup({
        mcc: m, mnc: n, lac: lac ? parseInt(lac, 10) : undefined,
        cell_id: c, provider,
      });
      setCgiRes(r);
      if (r.looked_up && r.lat != null && r.lon != null) {
        fly(r.lat, r.lon, r.range_meters ?? 2000, `CGI ${m}/${n}/${lac || '?'}/${c} (${provider})`, 'CGI_OPEN_DB');
        setNote(r.detail);
      } else {
        setNote(r.detail);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'cell-lookup failed');
    } finally {
      setCgiBusy(false);
    }
  };

  const runCapture = async () => {
    const obs: CaptureObservation[] = [];
    for (const line of obsText.split('\n')) {
      const t = line.trim();
      if (!t) continue;
      const [m, n, l, c, r] = t.split(',').map(s => s.trim());
      const mccN = parseInt(m, 10), mncN = parseInt(n, 10), cidN = parseInt(c, 10);
      if (!mccN || !mncN || !cidN) continue;
      obs.push({
        mcc: mccN, mnc: mncN,
        lac: l ? parseInt(l, 10) : null,
        cell_id: cidN,
        rssi: r ? parseFloat(r) : null,
      });
    }
    if (!obs.length) { setErr('No valid observation rows (mcc,mnc,lac,cell_id[,rssi])'); return; }
    setCaptureBusy(true); setErr(null); setCaptureRes(null);
    try {
      const r = await api.captureGeolocate(obs);
      setCaptureRes(r);
      if (r.looked_up && r.lat != null && r.lon != null) {
        fly(r.lat, r.lon, r.radius_m ?? 2000, `CAPTURE FIX (${r.towers_used} cells)`, 'CAPTURE_MULTILATERATE');
        setNote(r.detail);
      } else {
        setNote(r.detail);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'capture-geolocate failed');
    } finally {
      setCaptureBusy(false);
    }
  };

  return (
    <section className="net-card tw-panel tw-panel-fill">
      <div className="net-card-title">
        <span className="tel-proc-n tel-proc-n-panel">07</span> NO-LICENSE GEOLOCATE
        <span className="net-chip tel-sim-chip"><span>LICENCE</span><b>NONE REQUIRED</b></span>
      </div>
      <div className="net-card-hint">
        Licence-free phone/cell geolocation via the local open cell DB and the keyless
        community BeaconDB. The licensed OpenCelliD / IPQS path stays intact — this is the
        parallel, no-key capability. Fine location needs a CGI (your own SDR capture or a
        captured cell set); a phone number alone yields only a coarse operator region.
      </div>

      <div className="tw-nolic-grid">
        {/* 1. phone -> region */}
        <div className="tw-nolic-card">
          <div className="net-card-title-sm"><Smartphone className="w-3 h-3" /> PHONE → REGION</div>
          <div className="net-card-row net-card-row-wrap">
            <input className="net-input net-input-sm" value={phone}
              placeholder="+2348030000000"
              onChange={e => setPhone(e.target.value.replace(/[^\d+]/g, ''))}
              onKeyDown={e => { if (e.key === 'Enter') runPhone(); }} />
            <ToolBtn onClick={runPhone} busy={phoneBusy}>RESOLVE REGION</ToolBtn>
          </div>
          {phoneRes && (
            <div className="net-kv">
              <KV k="E.164" v={phoneRes.phone_e164} />
              {phoneRes.iso2 && <KV k="ISO" v={phoneRes.iso2} />}
              {phoneRes.mcc && <KV k="MCC" v={phoneRes.mcc} />}
              {phoneRes.operator && <KV k="Operator" v={phoneRes.operator} />}
              {phoneRes.lat != null && <KV k="Latitude" v={phoneRes.lat.toFixed(5)} />}
              {phoneRes.lon != null && <KV k="Longitude" v={phoneRes.lon.toFixed(5)} />}
              {phoneRes.lat != null && <KV k="Radius" v={`≈ ${Math.round(phoneRes.radius_m ?? 0)} m`} />}
              <KV k="Confidence" v={phoneRes.confidence.toFixed(2)} />
              <KV k="Method" v={phoneRes.method} />
            </div>
          )}
        </div>

        {/* 2. cgi -> open db */}
        <div className="tw-nolic-card">
          <div className="net-card-title-sm"><MapPin className="w-3 h-3" /> CGI → OPEN DB</div>
          <div className="net-card-row net-card-row-wrap">
            <input className="net-input net-input-sm" style={{ width: 64 }} value={mcc} placeholder="MCC" onChange={e => setMcc(e.target.value.replace(/\D/g, ''))} />
            <input className="net-input net-input-sm" style={{ width: 64 }} value={mnc} placeholder="MNC" onChange={e => setMnc(e.target.value.replace(/\D/g, ''))} />
            <input className="net-input net-input-sm" style={{ width: 64 }} value={lac} placeholder="LAC" onChange={e => setLac(e.target.value.replace(/\D/g, ''))} />
            <input className="net-input net-input-sm" style={{ width: 72 }} value={cid} placeholder="CellID" onChange={e => setCid(e.target.value.replace(/\D/g, ''))} />
            <select className="net-input net-input-sm" value={provider} onChange={e => setProvider(e.target.value as 'local' | 'beacondb-open')}>
              <option value="local">local open DB</option>
              <option value="beacondb-open">beacondb-open (keyless)</option>
            </select>
            <ToolBtn onClick={runCgi} busy={cgiBusy}>RESOLVE</ToolBtn>
          </div>
          {cgiRes && (
            <div className="net-kv">
              <KV k="Provider" v={cgiRes.provider} />
              {cgiRes.method && <KV k="Method" v={cgiRes.method} />}
              {cgiRes.lat != null && <KV k="Latitude" v={cgiRes.lat.toFixed(5)} />}
              {cgiRes.lon != null && <KV k="Longitude" v={cgiRes.lon.toFixed(5)} />}
              {cgiRes.range_meters != null && <KV k="Radius" v={`≈ ${Math.round(cgiRes.range_meters)} m`} />}
              {cgiRes.confidence != null && <KV k="Confidence" v={cgiRes.confidence.toFixed(2)} />}
            </div>
          )}
        </div>

        {/* 3. capture -> fix */}
        <div className="tw-nolic-card tw-nolic-card-wide">
          <div className="net-card-title-sm"><Radio className="w-3 h-3" /> CAPTURE → MULTILATERATE</div>
          <div className="net-card-row net-card-row-wrap">
            <span className="net-card-hint" style={{ margin: 0 }}>
              One row per captured cell: <span className="mono">mcc,mnc,lac,cell_id[,rssi]</span> (from your own SDR / IMSI-catcher sweep — no licence needed).
            </span>
          </div>
          <textarea className="net-input tw-nolic-ta" value={obsText}
            onChange={e => setObsText(e.target.value)} rows={4} />
          <div className="net-card-row net-card-row-wrap">
            <ToolBtn onClick={runCapture} busy={captureBusy}><Satellite className="w-3 h-3" /> MULTILATERATE</ToolBtn>
          </div>
          {captureRes && (
            <div className="net-kv">
              <KV k="Method" v={captureRes.method} />
              {captureRes.lat != null && <KV k="Latitude" v={captureRes.lat.toFixed(5)} />}
              {captureRes.lon != null && <KV k="Longitude" v={captureRes.lon.toFixed(5)} />}
              {captureRes.radius_m != null && <KV k="Radius" v={`≈ ${Math.round(captureRes.radius_m)} m`} />}
              <KV k="Cells used" v={captureRes.towers_used} />
              <KV k="Confidence" v={captureRes.confidence.toFixed(2)} />
            </div>
          )}
        </div>
      </div>

      <div className="tw-nolic-map">
        <MapWorkspace points={points} history={[]} />
      </div>

      {err && <div className="net-status net-status-error">{err}</div>}
      {note && <div className="osint-hint mono">{note}</div>}
    </section>
  );
}
