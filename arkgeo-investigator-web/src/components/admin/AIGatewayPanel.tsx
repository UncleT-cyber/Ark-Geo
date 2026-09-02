/**
 * AIGatewayPanel — the "AI & OSINT Gateway" control surface.
 *
 * One-glance health for every AI + OSINT path the agent consumes:
 *   Cloud LLM providers  (probe status from /ai/status)
 *   OSINT search         (Tavily primary + DuckDuckGo keyless fallback)
 *   Local engine         (Ollama runtime, vision master switch, and the
 *                         per-task Vision Model Rotator persisted through
 *                         the admin gateway store).
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  RefreshCw, Cpu, Globe, Search, Server, Eye, TestTube, Bot, ShieldCheck,
  type LucideIcon,
} from 'lucide-react';
import { api, type AiStatusResponse } from '../../api';
import type { AdminGateway } from '../../types';

const CLOUD_CARDS: { id: string; label: string; icon: LucideIcon }[] = [
  { id: 'gemini', label: 'Google Gemini', icon: Bot },
  { id: 'huggingface', label: 'HuggingFace Inference', icon: Bot },
  { id: 'openai', label: 'OpenAI (GPT-4o)', icon: Bot },
  { id: 'anthropic', label: 'Anthropic Claude', icon: Bot },
  { id: 'openrouter', label: 'OpenRouter', icon: Bot },
];

const ROTOR_ROLES: { key: string; label: string; hint: string }[] = [
  {
    key: 'terminal',
    label: 'Code / Terminal Orchestration',
    hint: 'Text tool-calling, shell & SIEM analysis, complex logic trees',
  },
  {
    key: 'vision_imint',
    label: 'Vision IMINT',
    hint: 'Image payloads — scene analysis, blurry screenshot OCR, threat profiling',
  },
];

interface TestState { testing: boolean; valid: boolean | null; detail: string; }

export function AIGatewayPanel() {
  const [ai, setAi] = useState<AiStatusResponse | null>(null);
  const [gateway, setGateway] = useState<AdminGateway | null>(null);
  const [tavilyHealth, setTavilyHealth] = useState<string>('unknown');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [tavilyTest, setTavilyTest] = useState<TestState>({ testing: false, valid: null, detail: '' });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [aiRes, gw, health] = await Promise.all([
        api.aiStatus(),
        api.getGateway(),
        api.health(),
      ]);
      setAi(aiRes);
      setGateway(gw);
      setTavilyHealth(health.services?.tavily ?? 'unknown');
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load AI & OSINT gateway status');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const patchGateway = async (patch: Partial<AdminGateway>) => {
    setSaving(true);
    try {
      setGateway(await api.updateGateway(patch));
      setError(null);
      // Refresh the public status surface so badges stay truthful.
      setAi(await api.aiStatus());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save gateway setting');
    } finally {
      setSaving(false);
    }
  };

  const setVisionEnabled = (enabled: boolean) => patchGateway({ vision_enabled: enabled });

  const setTaskModel = (role: string, model: string) => {
    if (!gateway) return;
    patchGateway({ task_models: { ...(gateway.task_models ?? {}), [role]: model } });
  };

  const testTavily = async () => {
    setTavilyTest({ testing: true, valid: null, detail: 'Probing api.tavily.com…' });
    try {
      const r = await api.adminTestKey('tavily');
      setTavilyTest({ testing: false, valid: r.valid, detail: r.detail });
    } catch {
      setTavilyTest({ testing: false, valid: false, detail: 'Probe failed' });
    }
  };

  const cloudBadge = (p: { configured: boolean; probed: boolean }) =>
    p.configured && p.probed
      ? <span className="ark-badge ark-badge-green"><span className="ark-badge-dot" /> CONNECTED</span>
      : p.configured
        ? <span className="ark-badge ark-badge-red"><span className="ark-badge-dot" /> UNREACHABLE</span>
        : <span className="ark-badge ark-badge-gray"><span className="ark-badge-dot" /> NOT CONFIGURED</span>;

  const routeBadge = (status: string) => {
    if (status === 'cloud') return <span className="ark-badge ark-badge-green"><span className="ark-badge-dot" /> CLOUD ROUTE</span>;
    if (status === 'local_ollama') return <span className="ark-badge ark-badge-blue"><span className="ark-badge-dot" /> LOCAL OLLAMA ROUTE</span>;
    return <span className="ark-badge ark-badge-red"><span className="ark-badge-dot" /> OFFLINE</span>;
  };

  const models = ai?.ollama.models ?? [];
  const roleValue = (role: string) => gateway?.task_models?.[role] ?? '';

  return (
    <div>
      {error && <div className="ark-card ark-mt" style={{ color: '#FCA5A5' }}>{error}</div>}
      {loading ? (
        <div className="ark-admin-loading" style={{ minHeight: 220 }}><div className="ark-spinner" /><div>Loading gateway status…</div></div>
      ) : ai && gateway && (
        <>
          <div className="ark-card">
            <div className="ark-cs-card-title"><Cpu className="w-3.5 h-3.5" /> CURRENT ROUTE</div>
            <div className="ark-inline" style={{ gap: 8, flexWrap: 'wrap' }}>
              {routeBadge(ai.status)}
              {ai.route.provider && (
                <span className="ark-key-badge ark-key-valid"><span className="ark-badge-dot" /> {ai.route.provider.toUpperCase()}</span>
              )}
              {ai.route.model && <span className="ark-mono" style={{ color: '#6B7280', fontSize: 11 }}>{ai.route.model}</span>}
              <span className="ark-key-badge ark-key-valid"><span className="ark-badge-dot" /> {ai.latency_ms} ms</span>
              {ai.vision
                ? <span className="ark-badge ark-badge-green"><span className="ark-badge-dot" /> VISION READY</span>
                : <span className="ark-badge ark-badge-gray"><span className="ark-badge-dot" /> NO VISION PATH</span>}
              {!ai.vision_enabled && <span className="ark-badge ark-badge-red"><span className="ark-badge-dot" /> VISION SWITCH OFF</span>}
              <span style={{ marginLeft: 'auto' }}>
                <button className="ark-btn ark-btn-sm" onClick={load}>
                  <RefreshCw className="w-3 h-3" /> Refresh
                </button>
              </span>
            </div>
            <div className="ark-flag ark-mt" style={{ marginTop: 10, color: '#6B7280' }}>
              {ai.route.detail} — cascade: cloud providers first, then local Ollama, then honest offline.
            </div>
          </div>

          <div className="ark-card">
            <div className="ark-cs-card-title"><Globe className="w-3.5 h-3.5" /> CLOUD LLM PROVIDERS</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 10 }}>
              {CLOUD_CARDS.map(card => {
                const p = ai.cloud[card.id] ?? { configured: false, probed: false, detail: 'no status', latency_ms: null };
                const Icon = card.icon;
                return (
                  <div key={card.id} className="ark-byok-row" style={{ margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <div className="ark-byok-head" style={{ width: '100%' }}>
                      <Icon className="w-3.5 h-3.5" style={{ color: '#6B7280' }} />
                      <span className="ark-byok-label">{card.label}</span>
                      {cloudBadge(p)}
                    </div>
                    <div style={{ fontSize: 10, color: '#9CA3AF', fontFamily: 'JetBrains Mono, monospace' }}>
                      {p.detail}
                      {p.latency_ms != null && ` · ${p.latency_ms} ms`}
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="ark-flag ark-mt" style={{ marginTop: 10, color: '#6B7280' }}>
              Live probe status is served by <span className="ark-mono">/api/v1/ai/status</span>. Keys and active models are managed on the
              "Model Gateway &amp; API Keys" tab.
            </div>
          </div>

          <div className="ark-card">
            <div className="ark-cs-card-title"><Search className="w-3.5 h-3.5" /> OSINT SEARCH PROVIDERS</div>
            <div className="ark-byok-row">
              <div className="ark-byok-head">
                <Search className="w-3.5 h-3.5" style={{ color: '#6B7280' }} />
                <span className="ark-byok-label">Tavily (Primary — web_search)</span>
                {gateway.providers?.tavily?.configured || tavilyHealth === 'configured'
                  ? <span className="ark-badge ark-badge-blue"><span className="ark-badge-dot" /> CONFIGURED</span>
                  : <span className="ark-badge ark-badge-red"><span className="ark-badge-dot" /> NOT CONFIGURED</span>}
                <span style={{ marginLeft: 'auto' }}>
                  <button className="ark-byok-test" disabled={tavilyTest.testing}
                    onClick={testTavily}>
                    <TestTube className="w-3 h-3" /> {tavilyTest.testing ? 'Testing…' : 'Live Test'}
                  </button>
                </span>
              </div>
              {tavilyTest.valid !== null && (
                <div className="ark-inline">
                  <span className={`ark-key-badge ${tavilyTest.valid ? 'ark-key-valid' : 'ark-key-invalid'}`}>
                    <span className="ark-badge-dot" />{tavilyTest.valid ? 'CONNECTED' : 'UNREACHABLE'}
                  </span>
                  <span className="ark-key-detail">{tavilyTest.detail}</span>
                </div>
              )}
              <div style={{ fontSize: 10, color: '#9CA3AF' }}>
                api.tavily.com — powers the <span className="ark-mono">web_search</span> agent tool with answer synthesis.
              </div>
            </div>

            <div className="ark-byok-row">
              <div className="ark-byok-head">
                <Search className="w-3.5 h-3.5" style={{ color: '#6B7280' }} />
                <span className="ark-byok-label">DuckDuckGo (Fallback — keyless scraper)</span>
                <span className="ark-badge ark-badge-green"><span className="ark-badge-dot" /> ALWAYS AVAILABLE</span>
              </div>
              <div style={{ fontSize: 10, color: '#9CA3AF' }}>
                html.duckduckgo.com scraper — no key required. The <span className="ark-mono">web_search</span> tool degrades here when Tavily is unset.
              </div>
            </div>
          </div>

          <div className="ark-card">
            <div className="ark-cs-card-title"><Server className="w-3.5 h-3.5" /> LOCAL ENGINE — OLLAMA</div>
            <div className="ark-inline" style={{ gap: 8, flexWrap: 'wrap' }}>
              {ai.ollama.available
                ? <span className="ark-badge ark-badge-green"><span className="ark-badge-dot" /> ONLINE</span>
                : <span className="ark-badge ark-badge-red"><span className="ark-badge-dot" /> OFFLINE</span>}
              <span className="ark-mono" style={{ color: '#6B7280', fontSize: 11 }}>{gateway.ollama_url}</span>
              <span className="ark-key-badge ark-key-valid"><span className="ark-badge-dot" /> {models.length} MODELS</span>
            </div>
            {!ai.ollama.available && (
              <div className="ark-flag ark-mt" style={{ marginTop: 8, color: '#FCA5A5' }}>
                Ollama is not reachable at the configured base URL — start the runtime or fix the URL on the Model Gateway tab.
              </div>
            )}
            <div className="ark-inline ark-mt" style={{ marginTop: 12, gap: 10, alignItems: 'center' }}>
              <Eye className="w-3.5 h-3.5" style={{ color: '#6B7280' }} />
              <div style={{ flex: 1 }}>
                <div className="ark-cs-field-label">Vision master switch</div>
                <div style={{ fontSize: 10, color: '#9CA3AF' }}>
                  Off = Ollama never receives image payloads; vision requests resolve through cloud providers only.
                </div>
              </div>
              <label className="ark-toggle">
                <input type="checkbox" disabled={saving} checked={ai.vision_enabled}
                  onChange={e => setVisionEnabled(e.target.checked)} />
                <span className="ark-toggle-slider" />
              </label>
            </div>

            <div className="ark-cs-card-title ark-mt" style={{ marginTop: 16 }}>
              <ShieldCheck className="w-3.5 h-3.5" /> VISION MODEL ROTATOR
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
              {ROTOR_ROLES.map(role => (
                <div className="ark-cs-field" key={role.key}>
                  <span className="ark-cs-field-label">{role.label}</span>
                  <select className="ark-cs-select" disabled={saving}
                    value={roleValue(role.key)}
                    onChange={e => setTaskModel(role.key, e.target.value)}>
                    <option value="">Auto — gateway resolves</option>
                    {models.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                  <div style={{ fontSize: 10, color: '#9CA3AF', marginTop: 4 }}>{role.hint}</div>
                </div>
              ))}
            </div>
            <div className="ark-flag ark-mt" style={{ marginTop: 12, color: '#6B7280' }}>
              Assign an installed Ollama model to each role. A pinned model is honored only while it stays installed — otherwise the
              gateway auto-resolves (vision-capable tag first, then the ARK qwen2.5-coder local tier).
            </div>
          </div>
        </>
      )}
    </div>
  );
}
