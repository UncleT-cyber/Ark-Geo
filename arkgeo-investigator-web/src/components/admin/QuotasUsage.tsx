/**
 * QuotasUsage — token budgets, rate limits and API spend per plan tier.
 * Editable per-plan limits are persisted via the admin store.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Gauge } from 'lucide-react';
import { api } from '../../api';
import type { AdminQuotas, PlanTier } from '../../types';

const TIER_ORDER: PlanTier[] = ['free', 'pro', 'enterprise'];
const TIER_LABEL: Record<PlanTier, string> = { free: 'Free', pro: 'Pro', enterprise: 'Enterprise' };

export function QuotasUsage() {
  const [quotas, setQuotas] = useState<AdminQuotas | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<PlanTier | null>(null);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState<Record<PlanTier, { monthly_token_budget: string; rate_limit_rpm: string; api_spend_cap_usd: string; storage_bytes: string; max_active_cases: string }> | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = await api.getQuotas();
      setQuotas(q);
      setDraft({
        free: fmt(q.free), pro: fmt(q.pro), enterprise: fmt(q.enterprise),
      });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load quotas');
    } finally {
      setLoading(false);
    }
  }, []);

  function fmt(p: AdminQuotas[PlanTier]) {
    return {
      monthly_token_budget: String(p.monthly_token_budget),
      rate_limit_rpm: String(p.rate_limit_rpm),
      api_spend_cap_usd: String(p.api_spend_cap_usd),
      storage_bytes: String(p.storage_bytes),
      max_active_cases: String(p.max_active_cases),
    };
  }

  useEffect(() => { load(); }, [load]);

  const saveTier = async (tier: PlanTier) => {
    if (!draft) return;
    setBusy(tier);
    try {
      const d = draft[tier];
      await api.updateQuotaPlan(tier, {
        monthly_token_budget: parseInt(d.monthly_token_budget) || 0,
        rate_limit_rpm: parseInt(d.rate_limit_rpm) || 0,
        api_spend_cap_usd: parseFloat(d.api_spend_cap_usd) || 0,
        storage_bytes: parseInt(d.storage_bytes) || 0,
        max_active_cases: parseInt(d.max_active_cases) || 0,
      });
      await load();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save quota');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <div className="ark-section-head">
        <h2 className="ark-section-title">PLAN QUOTAS</h2>
        <button className="ark-btn ark-btn-sm" onClick={load}><RefreshCw className="w-3 h-3" /> Refresh</button>
      </div>

      {error && <div className="ark-card ark-mt" style={{ color: '#FCA5A5' }}>{error}</div>}
      {loading ? (
        <div className="ark-admin-loading" style={{ minHeight: 220 }}><div className="ark-spinner" /><div>Loading quotas…</div></div>
      ) : quotas && draft && (
        <div className="ark-grid ark-grid-3">
          {TIER_ORDER.map(tier => (
            <div className="ark-card" key={tier}>
              <div className="ark-inline">
                <Gauge className="w-4 h-4" style={{ color: '#10B981' }} />
                <h3 className="ark-cc-card-title">{TIER_LABEL[tier]} Plan</h3>
              </div>
              <div className="ark-row-gap ark-mt">
                <div className="ark-cs-field">
                  <span className="ark-cs-field-label">Monthly Token Budget</span>
                  <input className="ark-cs-input" value={draft[tier].monthly_token_budget}
                    onChange={e => setDraft(d => d && ({ ...d, [tier]: { ...d[tier], monthly_token_budget: e.target.value } }))} />
                </div>
                <div className="ark-cs-field">
                  <span className="ark-cs-field-label">Rate Limit (RPM)</span>
                  <input className="ark-cs-input" value={draft[tier].rate_limit_rpm}
                    onChange={e => setDraft(d => d && ({ ...d, [tier]: { ...d[tier], rate_limit_rpm: e.target.value } }))} />
                </div>
                <div className="ark-cs-field">
                  <span className="ark-cs-field-label">API Spend Cap (USD)</span>
                  <input className="ark-cs-input" value={draft[tier].api_spend_cap_usd}
                    onChange={e => setDraft(d => d && ({ ...d, [tier]: { ...d[tier], api_spend_cap_usd: e.target.value } }))} />
                </div>
                <div className="ark-cs-field">
                  <span className="ark-cs-field-label">Storage (bytes)</span>
                  <input className="ark-cs-input" value={draft[tier].storage_bytes}
                    onChange={e => setDraft(d => d && ({ ...d, [tier]: { ...d[tier], storage_bytes: e.target.value } }))} />
                </div>
                <div className="ark-cs-field">
                  <span className="ark-cs-field-label">Max Active Cases</span>
                  <input className="ark-cs-input" value={draft[tier].max_active_cases}
                    onChange={e => setDraft(d => d && ({ ...d, [tier]: { ...d[tier], max_active_cases: e.target.value } }))} />
                </div>
                <button className="ark-btn ark-btn-primary ark-btn-sm" disabled={busy === tier}
                  onClick={() => saveTier(tier)}>{busy === tier ? 'Saving…' : 'Apply Override'}</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
