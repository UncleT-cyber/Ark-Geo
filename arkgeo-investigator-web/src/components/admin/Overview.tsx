/**
 * Overview — Command Center grid. Interactive cards navigate to the
 * matching console section; footer shows the keyboard shortcut hint.
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  Users, ShieldCheck, KeyRound, Settings2, Wrench, ScrollText,
  ChevronRight, Command,
} from 'lucide-react';
import { api } from '../../api';
import type { AdminOverview as AdminOverviewData } from '../../types';
import type { AdminSectionId } from './adminNav';

interface OverviewProps {
  onNavigate: (id: AdminSectionId) => void;
}

const CARDS: { id: AdminSectionId; title: string; desc: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'clients', title: 'Client Directory & Telemetry', desc: 'Monitor subscribers, active cases, suspension controls.', icon: Users },
  { id: 'staff', title: 'Staff & RBAC Management', desc: 'Manage internal operators, roles and administrative access.', icon: ShieldCheck },
  { id: 'gateway', title: 'Model & API Gateway', desc: 'Cloud AI, OpenRouter, Gemini, Ollama, OSINT APIs.', icon: KeyRound },
  { id: 'policy', title: 'Tool Policy Governor', desc: 'Toggle passive vs active OSINT tools & execution rules.', icon: Settings2 },
  { id: 'tooling', title: 'System Health & Local Binaries', desc: 'ExifTool status, Tesseract, Ollama node health.', icon: Wrench },
  { id: 'audit', title: 'Audit & Security Logs', desc: 'Non-repudiation log search by user, IP and timestamp.', icon: ScrollText },
];

function fmtBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${(bytes / 1024 ** 2).toFixed(0)} MB`;
}

export function Overview({ onNavigate }: OverviewProps) {
  const [data, setData] = useState<AdminOverviewData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.adminOverview());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load overview');
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <div className="ark-grid ark-grid-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
        {CARDS.map(card => {
          const Icon = card.icon;
          return (
            <button key={card.id} className="ark-card ark-cc-card" onClick={() => onNavigate(card.id)}>
              <span className="ark-cc-card-icon"><Icon className="w-5 h-5" /></span>
              <h3 className="ark-cc-card-title">{card.title}</h3>
              <p className="ark-cc-card-desc">{card.desc}</p>
              <span className="ark-cc-card-link">Open Section <ChevronRight className="w-3 h-3" /></span>
            </button>
          );
        })}
      </div>

      <div className="ark-mt-lg">
        <h2 className="ark-section-title">SYSTEM SNAPSHOT</h2>
      </div>

      {error ? (
        <div className="ark-card ark-mt" style={{ color: '#FCA5A5' }}>{error}</div>
      ) : !data ? (
        <div className="ark-admin-loading" style={{ minHeight: 220 }}>
          <div className="ark-spinner" />
          <div>Loading control plane telemetry…</div>
        </div>
      ) : (
        <div className="ark-grid ark-mt">
          <div className="ark-card">
            <h4 className="ark-card-title">Active Clients</h4>
            <div className="ark-card-value">{data.clients.active}</div>
            <div className="ark-card-sub">
              {data.clients.suspended} suspended · {data.clients.banned} banned · {data.clients.total} total
            </div>
          </div>
          <div className="ark-card">
            <h4 className="ark-card-title">Internal Staff</h4>
            <div className="ark-card-value">{data.staff.active}</div>
            <div className="ark-card-sub">{data.staff.total} operators total</div>
          </div>
          <div className="ark-card">
            <h4 className="ark-card-title">Active Cases</h4>
            <div className="ark-card-value">{data.cases.total}</div>
            <div className="ark-card-sub">across all tenants</div>
          </div>
          <div className="ark-card">
            <h4 className="ark-card-title">Token Usage</h4>
            <div className="ark-card-value">{data.usage.tokens_consumed.toLocaleString()}</div>
            <div className="ark-card-sub">${data.usage.api_spend_usd.toFixed(2)} total spend</div>
          </div>
          <div className="ark-card">
            <h4 className="ark-card-title">Storage Consumed</h4>
            <div className="ark-card-value">{fmtBytes(data.usage.storage_bytes)}</div>
            <div className="ark-card-sub">across client vaults</div>
          </div>
          <div className="ark-card">
            <h4 className="ark-card-title">Tool Policy</h4>
            <div className="ark-card-value">{data.tools.enabled}<span style={{ fontSize: 14, color: '#6B7280' }}>/{data.tools.total}</span></div>
            <div className="ark-card-sub">
              {data.tools.enabled_high_risk.length > 0
                ? `${data.tools.enabled_high_risk.length} HIGH-RISK enabled`
                : 'no high-risk tools enabled'}
            </div>
          </div>
          <div className="ark-card">
            <h4 className="ark-card-title">Audit Trail</h4>
            <div className="ark-card-value">{data.audit_count}</div>
            <div className="ark-card-sub">append-only chain-of-custody entries</div>
          </div>
          <div className="ark-card">
            <h4 className="ark-card-title">Support Banner</h4>
            <div className="ark-card-value" style={{ fontSize: 18 }}>
              {data.support.show_banner ? (
                <span className="ark-badge ark-badge-green"><span className="ark-badge-dot" /> LIVE</span>
              ) : (
                <span className="ark-badge ark-badge-gray">OFF</span>
              )}
            </div>
            <div className="ark-card-sub">Buy Me a Coffee widget state</div>
          </div>
        </div>
      )}

      <div className="ark-shortcut-bar">
        <Command className="w-4 h-4" />
        <span>Keyboard shortcut to toggle the Admin Console from anywhere:</span>
        <span className="ark-kbd">Ctrl</span>
        <span>+</span>
        <span className="ark-kbd">Shift</span>
        <span>+</span>
        <span className="ark-kbd">A</span>
        <span style={{ marginLeft: 'auto', opacity: 0.7 }}>stealth route: /console-auth</span>
      </div>
    </div>
  );
}
