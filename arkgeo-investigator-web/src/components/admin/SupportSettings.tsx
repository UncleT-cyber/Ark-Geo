/**
 * SupportSettings — the "heart" of ARK: Buy-Me-a-Coffee banner, open
 * source links and the deployed build version surfaced for the Super-Admin.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Heart } from 'lucide-react';
import { api } from '../../api';
import type { AdminSupportSettings } from '../../types';

export function SupportSettings() {
  const [support, setSupport] = useState<AdminSupportSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<Pick<AdminSupportSettings, 'bmc_url' | 'github_url' | 'discord_url'> | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const s = await api.getSupportSettings();
      setSupport(s);
      setDraft({ bmc_url: s.bmc_url, github_url: s.github_url, discord_url: s.discord_url });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load support settings');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggleBanner = async () => {
    if (!support) return;
    setSaving(true);
    try {
      await api.updateSupportSettings({ show_banner: !support.show_banner });
      await load();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to toggle banner');
    } finally {
      setSaving(false);
    }
  };

  const saveLinks = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      await api.updateSupportSettings(draft);
      await load();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save links');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="ark-section-head">
        <h2 className="ark-section-title">SUPPORT CORE</h2>
        <button className="ark-btn ark-btn-sm" onClick={load}><RefreshCw className="w-3 h-3" /> Refresh</button>
      </div>

      {error && <div className="ark-card ark-mt" style={{ color: '#FCA5A5' }}>{error}</div>}
      {loading ? (
        <div className="ark-admin-loading" style={{ minHeight: 220 }}><div className="ark-spinner" /><div>Loading support…</div></div>
      ) : support && draft && (
        <>
          <div className="ark-grid">
            <div className="ark-card">
              <div className="ark-cs-card-title"><Heart className="w-3.5 h-3.5" /> BUY ME A COFFEE BANNER</div>
              <div className="ark-inline ark-mt" style={{ justifyContent: 'flex-start' }}>
                <span>
                  {support.show_banner
                    ? <span className="ark-badge ark-badge-green"><span className="ark-badge-dot" /> LIVE</span>
                    : <span className="ark-badge ark-badge-gray">OFF</span>}
                </span>
                <button className="ark-btn ark-btn-sm" onClick={toggleBanner} disabled={saving}>
                  {support.show_banner ? 'Hide Banner' : 'Show Banner'}
                </button>
              </div>
              <p style={{ fontSize: 12, color: '#9CA3AF', lineHeight: 1.6, margin: '14px 0 0' }}>
                The banner is surfaced to clients in their Settings → Support tab with the configured
                donation link below.
              </p>
            </div>

            <div className="ark-card">
              <div className="ark-cs-card-title"><Heart className="w-3.5 h-3.5" /> DEPLOYED BUILD</div>
              <div className="ark-telemetry-grid ark-mt">
                <div className="ark-telemetry-item"><div className="ark-telemetry-k">Version</div>
                  <div className="ark-telemetry-v ark-mono">{support.build_version}</div></div>
              </div>
            </div>
          </div>

          <div className="ark-card ark-mt">
            <div className="ark-cs-card-title">COMMUNITY LINKS</div>
            <div className="ark-cs-grid-2">
              <div className="ark-cs-field">
                <span className="ark-cs-field-label">Buy Me a Coffee URL</span>
                <input className="ark-cs-input" value={draft.bmc_url}
                  onChange={e => setDraft({ ...draft, bmc_url: e.target.value })} placeholder="https://buymeacoffee.com/…" />
              </div>
              <div className="ark-cs-field">
                <span className="ark-cs-field-label">GitHub URL</span>
                <input className="ark-cs-input" value={draft.github_url}
                  onChange={e => setDraft({ ...draft, github_url: e.target.value })} placeholder="https://github.com/…" />
              </div>
              <div className="ark-cs-field">
                <span className="ark-cs-field-label">Discord URL</span>
                <input className="ark-cs-input" value={draft.discord_url}
                  onChange={e => setDraft({ ...draft, discord_url: e.target.value })} placeholder="https://discord.gg/…" />
              </div>
            </div>
            <button className="ark-btn ark-btn-primary ark-btn-sm ark-mt" onClick={saveLinks} disabled={saving}>
              {saving ? 'Saving…' : 'Save Community Links'}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
