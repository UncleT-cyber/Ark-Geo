/**
 * SupportPanel — the "Buy Me a Coffee" / community face of the client
 * settings dashboard. Keeps support contact and open-source links one
 * click away, with a live backend connection check.
 */
import React, { useEffect, useState } from 'react';
import { Heart, Coffee, Link2, Mail, RefreshCw } from 'lucide-react';
import { api } from '../../api';

export function SupportPanel() {
  const [backend, setBackend] = useState<boolean | null>(null);
  const [version, setVersion] = useState('');
  const [checking, setChecking] = useState(false);

  const check = async () => {
    setChecking(true);
    try {
      const h = await api.health();
      setBackend(true);
      setVersion(String((h as any)?.version || (h as any)?.app_version || ''));
    } catch {
      setBackend(false);
    } finally {
      setChecking(false);
    }
  };

  useEffect(() => { check(); }, []);

  return (
    <div>
      <div className="ark-cs-card" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <span className="ark-support-heart"><Heart className="w-5 h-5" /></span>
        <div style={{ flex: 1 }}>
          <h3 style={{ margin: 0, fontSize: 14, color: '#F9FAFB', fontWeight: 700 }}>Support the Project</h3>
          <p style={{ margin: '4px 0 0', fontSize: 12, color: '#9CA3AF', lineHeight: 1.5 }}>
            The Ark is open source. If the platform has helped your investigations, consider
            buying the maintainers a coffee — every contribution keeps the lights on.
          </p>
        </div>
        <a className="ark-link-btn" href="https://buymeacoffee.com/ark" target="_blank" rel="noreferrer">
          <Coffee className="w-3.5 h-3.5" /> Buy Me a Coffee
        </a>
      </div>

      <div className="ark-cs-card">
        <div className="ark-cs-card-title"><Link2 className="w-3.5 h-3.5" /> OPEN SOURCE</div>
        <div className="ark-inline">
          <a className="ark-link-btn" href="https://github.com/Ark-Geo" target="_blank" rel="noreferrer">
            <Link2 className="w-3.5 h-3.5" /> View on GitHub
          </a>
          <a className="ark-link-btn" href="mailto:support@ark.example">
            <Mail className="w-3.5 h-3.5" /> support@ark.example
          </a>
        </div>
        <p style={{ fontSize: 11.5, color: '#6B7280', margin: '12px 0 0', lineHeight: 1.6 }}>
          Docs, issue tracking and the core engine are MIT-licensed. Security disclosures should be
          sent to the maintainers directly rather than the public tracker.
        </p>
      </div>

      <div className="ark-cs-card">
        <div className="ark-cs-card-title"><RefreshCw className="w-3.5 h-3.5" /> CONNECTION</div>
        <div className="ark-inline">
          <button className="ark-byok-test" onClick={check} disabled={checking}>
            <RefreshCw className="w-3 h-3" /> {checking ? 'Checking…' : 'Re-check Backend'}
          </button>
          <span style={{ marginLeft: 8 }}>
            {backend === null
              ? <span className="ark-key-badge ark-key-testing"><span className="ark-badge-dot" /> CHECKING</span>
              : backend
                ? <span className="ark-key-badge ark-key-valid"><span className="ark-badge-dot" /> ARK CORE ONLINE</span>
                : <span className="ark-key-badge ark-key-invalid"><span className="ark-badge-dot" /> OFFLINE</span>}
          </span>
          {version && <span className="ark-key-detail">v{version}</span>}
        </div>
      </div>
    </div>
  );
}
