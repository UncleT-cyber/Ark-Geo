/**
 * ProvidersPanel — Settings → Providers & Connections.
 *
 * Relocated from the old global header. Shows the read-only configuration
 * state of every external provider the ARK can use. Keys are never exposed —
 * only configured / not configured and the source of truth. Admin remains the
 * protected control plane for writing system keys.
 */
import React from 'react';
import { KeyRound, MapPin, Wrench, RefreshCw, Shield } from 'lucide-react';
import type { ApiKeyStatus } from '../workbench/TopBar';

interface ProviderRow {
  key: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  hint: string;
}

const PROVIDERS: ProviderRow[] = [
  { key: 'vision_geospy', label: 'GeoSpy Vision API', icon: KeyRound, hint: 'Street-level image geolocation (Tier 2 vision ensemble).' },
  { key: 'vision_geoinfer', label: 'GeoInfer Vision API', icon: KeyRound, hint: 'Dedicated geo-vision provider for location estimation.' },
  { key: 'llm', label: 'OpenAI Vision / LLM Ensemble', icon: KeyRound, hint: 'Multi-factor visual reasoning + clue extraction.' },
  { key: 'gemini', label: 'Gemini Vision API', icon: KeyRound, hint: 'Alternative vision provider for scene analysis.' },
  { key: 'anthropic', label: 'Anthropic Claude', icon: KeyRound, hint: 'Alternative vision provider for scene analysis.' },
  { key: 'reverse_search', label: 'Reverse Source Search', icon: KeyRound, hint: 'TinEye / Serper web reverse-source discovery (pHash + image matches).' },
  { key: 'streetview', label: 'Google Street View', icon: MapPin, hint: 'Panorama metadata + static imagery for established coordinates.' },
  { key: 'mapbox', label: 'Mapbox Token', icon: MapPin, hint: 'Vector / satellite map tiles in the spatial canvas.' },
  { key: 'exiftool', label: 'ExifTool Path', icon: Wrench, hint: 'Local binary for deep metadata extraction (Tier 1).' },
];

interface ProvidersPanelProps {
  apiStatuses: ApiKeyStatus[];
  exifToolPath: string;
  exifToolOk: boolean | null;
  checking: boolean;
}

export function ProvidersPanel({ apiStatuses, exifToolPath, exifToolOk, checking }: ProvidersPanelProps) {
  const lookup = (key: string): ApiKeyStatus | undefined => apiStatuses.find(s =>
    s.title.toLowerCase().includes(key.replace('vision_', '').replace('_', ' ')) ||
    (key === 'vision_geospy' && s.label === 'GS') ||
    (key === 'vision_geoinfer' && s.label === 'GI') ||
    (key === 'llm' && s.label === 'LLM') ||
    (key === 'gemini' && s.label === 'GM') ||
    (key === 'anthropic' && s.label === 'AN') ||
    (key === 'reverse_search' && s.label === 'RS') ||
    (key === 'streetview' && s.label === 'SV'),
  );

  return (
    <>
      <section className="settings-section">
        <div className="settings-section-title"><KeyRound className="w-3.5 h-3.5" /> VISION &amp; LLM PROVIDERS</div>
        <div className="settings-provider-list">
          {PROVIDERS.filter(p => ['vision_geospy', 'vision_geoinfer', 'llm', 'gemini', 'anthropic'].includes(p.key)).map(p => {
            const Icon = p.icon;
            const configured = !!lookup(p.key)?.configured;
            return (
              <div key={p.key} className={`settings-provider-row ${configured ? 'settings-provider-on' : 'settings-provider-off'}`}>
                <span className="settings-provider-icon"><Icon className="w-4 h-4" /></span>
                <div className="settings-provider-main">
                  <div className="settings-provider-label">{p.label}</div>
                  <div className="settings-provider-hint">{p.hint}</div>
                </div>
                <span className={`settings-provider-state ${configured ? 'state-on' : 'state-off'}`}>
                  {configured ? 'Configured' : 'Not Set'}
                </span>
              </div>
            );
          })}
        </div>
        <div className="settings-note">
          Keys are stored server-side and never exposed in the client. Configure them from the Admin control plane (Cmd/Ctrl+Shift+P), or supply a personal key in Settings → API Keys.
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-title"><KeyRound className="w-3.5 h-3.5" /> IMAGE INTELLIGENCE SUITE</div>
        <div className="settings-provider-list">
          {PROVIDERS.filter(p => ['reverse_search', 'streetview'].includes(p.key)).map(p => {
            const Icon = p.icon;
            const configured = !!lookup(p.key)?.configured;
            return (
              <div key={p.key} className={`settings-provider-row ${configured ? 'settings-provider-on' : 'settings-provider-off'}`}>
                <span className="settings-provider-icon"><Icon className="w-4 h-4" /></span>
                <div className="settings-provider-main">
                  <div className="settings-provider-label">{p.label}</div>
                  <div className="settings-provider-hint">{p.hint}</div>
                </div>
                <span className={`settings-provider-state ${configured ? 'state-on' : 'state-off'}`}>
                  {configured ? 'Configured' : 'Not Set'}
                </span>
              </div>
            );
          })}
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-title"><MapPin className="w-3.5 h-3.5" /> MAPBOX MAP TILES</div>
        <div className="settings-provider-row settings-provider-off">
          <span className="settings-provider-icon"><MapPin className="w-4 h-4" /></span>
          <div className="settings-provider-main">
            <div className="settings-provider-label">Mapbox Access Token</div>
            <div className="settings-provider-hint">Client map tiles (VITE_MAPBOX_TOKEN). A server-side token also powers Geocoding reverse lookups via Admin.</div>
          </div>
          <span className="settings-provider-state state-off">Client env (VITE_MAPBOX_TOKEN)</span>
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-title"><Wrench className="w-3.5 h-3.5" /> EXIFTOOL PATHING</div>
        <div className={`settings-provider-row ${exifToolOk ? 'settings-provider-on' : 'settings-provider-off'}`}>
          <span className="settings-provider-icon"><Wrench className="w-4 h-4" /></span>
          <div className="settings-provider-main">
            <div className="settings-provider-label">ExifTool Binary</div>
            <div className="settings-provider-hint">Local binary for deep EXIF/XMP/IPTC extraction (Tier 1 deterministic metadata).</div>
            <div className="settings-provider-path mono">{exifToolPath}</div>
          </div>
          <span className={`settings-provider-state ${exifToolOk ? 'state-on' : 'state-off'}`}>
            {checking ? 'Checking…' : exifToolOk ? 'Available' : 'Unavailable'}
          </span>
        </div>
      </section>

      <div className="settings-note settings-note-shield">
        <Shield className="w-3 h-3" /> Admin is a protected control plane — not accessible from here.
      </div>
    </>
  );
}

/** Backend/system health surface — relocated from the header connection dot. */
export function SystemHealthPanel({ connected, exifToolOk, checking }: { connected: boolean; exifToolOk: boolean | null; checking: boolean }) {
  return (
    <section className="settings-section">
      <div className="settings-section-title"><RefreshCw className="w-3.5 h-3.5" /> BACKEND CONNECTION</div>
      <div className={`settings-provider-row ${connected ? 'settings-provider-on' : 'settings-provider-off'}`}>
        <span className="settings-provider-icon"><RefreshCw className="w-4 h-4" /></span>
        <div className="settings-provider-main">
          <div className="settings-provider-label">ARK Core Engine</div>
          <div className="settings-provider-hint">FastAPI modular Brain pipeline (4-tier: metadata → vision → clue extractors → consensus).</div>
        </div>
        <span className={`settings-provider-state ${connected ? 'state-on' : 'state-off'}`}>
          {connected ? 'Connected' : 'Offline'}
        </span>
      </div>
      <div className={`settings-provider-row ${exifToolOk ? 'settings-provider-on' : 'settings-provider-off'}`}>
        <span className="settings-provider-icon"><Wrench className="w-4 h-4" /></span>
        <div className="settings-provider-main">
          <div className="settings-provider-label">ExifTool Toolchain</div>
          <div className="settings-provider-hint">Required for Tier 1 deterministic metadata extraction.</div>
        </div>
        <span className={`settings-provider-state ${exifToolOk ? 'state-on' : 'state-off'}`}>
          {checking ? 'Checking…' : exifToolOk ? 'Available' : 'Unavailable'}
        </span>
      </div>
    </section>
  );
}
