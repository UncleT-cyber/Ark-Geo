/**
 * ApiGateway — dual-layer key settings (Admin Global System Keys vs the
 * user's BYOK fallback in Client Settings). The CONFIGURED badge reflects
 * whether a key is stored; the Live Test button runs a REAL provider probe
 * and reports CONNECTED / UNREACHABLE. Keys are encrypted server-side and
 * only masked previews are shown.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, KeyRound, Server, Globe, Eye, EyeOff, TestTube } from 'lucide-react';
import { api } from '../../api';
import type { AdminGateway, AdminGatewayProvider, GatewayModelCatalog } from '../../types';

/** Gateway provider → SettingsStore key field. */
const FIELD_BY_PROVIDER: Record<string, string> = {
  openai: 'llm_api_key',
  gemini: 'gemini_api_key',
  anthropic: 'anthropic_api_key',
  openrouter: 'openrouter_api_key',
  huggingface: 'huggingface_api_key',
  geospy: 'geospy_api_key',
  geoinfer: 'geoinfer_api_key',
  serper: 'serper_api_key',
  tineye: 'tineye_api_key',
  hlr: 'hlr_api_key',
  opencellid: 'opencellid_api_key',
  mapbox: 'mapbox_token',
  google_maps: 'google_maps_api_key',
  infobip: 'infobip_api_key',
  twilio: 'twilio_account_sid',
  opencnam: 'opencnam_account_sid',
  telesign: 'telesign_customer_id',
  truid: 'truid_client_id',
};

/** Paired-credential providers: extra store fields to save alongside the primary. */
const PAIRED_FIELDS: Record<string, { field: string; label: string; placeholder: string }[]> = {
  twilio: [
    { field: 'twilio_account_sid', label: 'Account SID', placeholder: 'ACxxxxxxxx…' },
    { field: 'twilio_auth_token', label: 'Auth Token', placeholder: 'Enter token to replace…' },
  ],
  opencnam: [
    { field: 'opencnam_account_sid', label: 'Account SID', placeholder: 'ACxxxxxxxx…' },
    { field: 'opencnam_auth_token', label: 'Auth Token', placeholder: 'Enter token to replace…' },
  ],
  telesign: [
    { field: 'telesign_customer_id', label: 'Customer ID', placeholder: 'xxxx-xxxx…' },
    { field: 'telesign_rest_key', label: 'REST API Key', placeholder: 'Enter key to replace…' },
  ],
  truid: [
    { field: 'truid_client_id', label: 'Client ID', placeholder: 'xxxx-xxxx…' },
    { field: 'truid_client_secret', label: 'Client Secret', placeholder: 'Enter secret to replace…' },
  ],
};

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI (GPT-4o)',
  gemini: 'Google Gemini',
  anthropic: 'Anthropic Claude',
  openrouter: 'OpenRouter',
  huggingface: 'HuggingFace Inference Providers',
  geospy: 'GeoSpy Vision',
  geoinfer: 'Geoinfer',
  serper: 'Serper / Google Lens',
  tineye: 'TinEye',
  hlr: 'HLR Telecom Lookup (IPQS)',
  opencellid: 'OpenCelliD',
  mapbox: 'Mapbox',
  google_maps: 'Google Maps (Geocoding + Street View)',
  infobip: 'Infobip Number Query',
  twilio: 'Twilio',
  opencnam: 'OpenCNAM Caller ID',
  telesign: 'Telesign Phone ID',
  truid: 'Tru.ID Phone Check',
};

const LLM_PROVIDERS = ['openai', 'gemini', 'anthropic', 'openrouter'];
const OSINT_PROVIDERS = ['geospy', 'geoinfer', 'serper', 'tineye', 'mapbox', 'google_maps'];
const TELECOM_PROVIDERS = ['hlr', 'opencellid', 'infobip', 'twilio', 'opencnam', 'telesign', 'truid'];
const HUGGINGFACE = 'huggingface';

/** Providers that expose a model list for the unified Active Provider & Model selector. */
const MODEL_PROVIDERS = ['ollama', 'openai', 'gemini', 'anthropic', 'openrouter', 'huggingface'];

/** Model selector → gateway store field (per provider). */
const MODEL_FIELD: Record<string, string> = {
  ollama: 'ollama_model',
  openai: 'openai_model',
  gemini: 'gemini_model',
  anthropic: 'anthropic_model',
  openrouter: 'openrouter_model',
  huggingface: 'huggingface_model',
};

/**
 * Recommended HuggingFace whitelist (Organization/Model-Name). Curated for
 * tool/function calling, throughput, and vision — the ARK ISE model tiers.
 */
const HF_RECOMMENDED_MODELS: { group: string; desc: string; models: string[] }[] = [
  {
    group: 'TECHNICAL & CYBER ORCHESTRATION',
    desc: 'Tool calling, complex logic trees, code & raw SIEM analysis',
    models: [
      'Qwen/Qwen2.5-Coder-7B-Instruct',
      'Qwen/Qwen2.5-Coder-32B-Instruct',
      'meta-llama/Llama-3.3-70B-Instruct',
    ],
  },
  {
    group: 'SPEED & HIGH THROUGHPUT',
    desc: 'Lightweight repetitive tasks — alert streams, raw firewall inputs',
    models: [
      'meta-llama/Llama-3.2-3B-Instruct',
      'meta-llama/Meta-Llama-3.1-8B-Instruct',
    ],
  },
  {
    group: 'IMAGE INTELLIGENCE & OSINT',
    desc: 'Multi-modal vision — blurry screenshot OCR, landmark & threat profiling',
    models: [
      'Qwen/Qwen2-VL-7B-Instruct',
      'meta-llama/Llama-3.2-11B-Vision-Instruct',
    ],
  },
];

/**
 * HuggingFace router routing-policy suffixes. Appended to the model id inside
 * the payload string: `org/Model:fastest` → HF auto-routes to the fastest
 * live provider; `:groq` / `:sambanova` / … pin a specific hardware pipeline.
 */
const HF_ROUTING_POLICIES: { value: string; label: string }[] = [
  { value: '', label: 'No suffix — provider auto-selected' },
  { value: 'fastest', label: ':fastest — route to fastest live provider' },
  { value: 'groq', label: ':groq — pin to Groq (fast inference)' },
  { value: 'sambanova', label: ':sambanova — pin to SambaNova' },
  { value: 'together', label: ':together — pin to Together AI' },
  { value: 'baseten', label: ':baseten — pin to Baseten' },
  { value: 'fireworks', label: ':fireworks — pin to Fireworks AI' },
  { value: 'cerebras', label: ':cerebras — pin to Cerebras' },
  { value: 'novita', label: ':novita — pin to Novita' },
  { value: 'fal', label: ':fal — pin to Fal.ai' },
  { value: 'hyperbolic', label: ':hyperbolic — pin to Hyperbolic' },
  { value: 'openai', label: ':openai — pin to OpenAI' },
  { value: 'openrouter', label: ':openrouter — pin to OpenRouter' },
];

const HF_ROUTING_SUFFIXES = new Set(HF_ROUTING_POLICIES.map(p => p.value).filter(Boolean));

/** Split `org/Model:provider` into { base, suffix } when the suffix is a
 *  recognized routing tag (model ids never contain a colon). */
function splitHfModel(model: string): { base: string; suffix: string } {
  const idx = model.lastIndexOf(':');
  if (idx > 0 && HF_ROUTING_SUFFIXES.has(model.slice(idx + 1))) {
    return { base: model.slice(0, idx), suffix: model.slice(idx + 1) };
  }
  return { base: model, suffix: '' };
}

interface TestState { testing: boolean; valid: boolean | null; detail: string; }

export function ApiGateway() {
  const [gateway, setGateway] = useState<AdminGateway | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [testStates, setTestStates] = useState<Record<string, TestState>>({});
  const [inputValues, setInputValues] = useState<Record<string, string>>({});
  const [showValues, setShowValues] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [catalog, setCatalog] = useState<Record<string, GatewayModelCatalog>>({});
  const [catalogLoading, setCatalogLoading] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setGateway(await api.getGateway());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load gateway');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  /** Fetch the live (or curated) model catalog for one provider. */
  const fetchCatalog = useCallback(async (provider: string) => {
    setCatalogLoading(s => ({ ...s, [provider]: true }));
    try {
      const c = await api.getGatewayModels(provider);
      setCatalog(s => ({ ...s, [provider]: c }));
    } catch (err) {
      setCatalog(s => ({
        ...s,
        [provider]: {
          provider, models: [], source: 'error',
          detail: err instanceof Error ? err.message : 'Failed to fetch models',
          latency_ms: 0,
        },
      }));
    } finally {
      setCatalogLoading(s => ({ ...s, [provider]: false }));
    }
  }, []);

  // Auto-fetch the catalog for whichever provider is currently active.
  useEffect(() => {
    const active = gateway?.active_llm_provider;
    if (active) fetchCatalog(active);
  }, [gateway?.active_llm_provider, fetchCatalog]);

  const activeModel = (gw: AdminGateway, provider: string): string => {
    if (provider === 'huggingface') return splitHfModel(gw.huggingface_model).base;
    return (gw[MODEL_FIELD[provider] as keyof AdminGateway] as string) ?? '';
  };

  const setActiveProvider = (provider: string) => {
    if (!gateway || provider === gateway.active_llm_provider) return;
    updateGateway({ active_llm_provider: provider });
  };

  const setActiveModel = (provider: string, model: string) => {
    if (!gateway) return;
    if (provider === 'huggingface') {
      const { suffix } = splitHfModel(gateway.huggingface_model);
      updateGateway({ huggingface_model: suffix ? `${model}:${suffix}` : model });
    } else if (provider === 'ollama') {
      updateGateway({ ollama_model: model, ollama_url: gateway.ollama_url });
    } else {
      updateGateway({ [MODEL_FIELD[provider]]: model } as Partial<AdminGateway>);
    }
  };

  const statusBadge = (p: AdminGatewayProvider) =>
    p.configured
      ? <span className="ark-badge ark-badge-blue"><span className="ark-badge-dot" /> CONFIGURED</span>
      : <span className="ark-badge ark-badge-red"><span className="ark-badge-dot" /> NOT CONFIGURED</span>;

  const testProvider = async (provider: string) => {
    setTestStates(s => ({ ...s, [provider]: { testing: true, valid: null, detail: 'Testing…' } }));
    try {
      const r = await api.adminTestKey(provider);
      setTestStates(s => ({ ...s, [provider]: { testing: false, valid: r.valid, detail: r.detail } }));
    } catch {
      setTestStates(s => ({ ...s, [provider]: { testing: false, valid: false, detail: 'Test failed' } }));
    }
  };

  const saveGlobalKey = async (provider: string) => {
    const paired = PAIRED_FIELDS[provider];
    if (paired) {
      const patch: Record<string, string> = {};
      for (const f of paired) {
        if (inputValues[`${provider}:${f.field}`]) patch[f.field] = inputValues[`${provider}:${f.field}`];
      }
      if (!Object.keys(patch).length) return;
      setSaving(true);
      try {
        await api.updateAdminConfig({ api_keys: patch });
        setInputValues(v => {
          const next = { ...v };
          for (const f of paired) delete next[`${provider}:${f.field}`];
          return next;
        });
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to save key');
      } finally {
        setSaving(false);
      }
      return;
    }
    const value = inputValues[provider];
    if (!value) return;
    setSaving(true);
    try {
      await api.updateAdminConfig({ api_keys: { [FIELD_BY_PROVIDER[provider]]: value } });
      setInputValues(v => ({ ...v, [provider]: '' }));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save key');
    } finally {
      setSaving(false);
    }
  };

  const updateGateway = async (patch: Partial<AdminGateway>) => {
    setSaving(true);
    try {
      setGateway(await api.updateGateway(patch));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update gateway');
    } finally {
      setSaving(false);
    }
  };

  const hasInput = (provider: string): boolean => {
    if (PAIRED_FIELDS[provider]) {
      return PAIRED_FIELDS[provider].some(f => Boolean(inputValues[`${provider}:${f.field}`]));
    }
    return Boolean(inputValues[provider]);
  };

  /** Change the routing suffix, keeping the model base. */
  const setHfRouting = (gw: AdminGateway, suffix: string) => {
    const { base } = splitHfModel(gw.huggingface_model);
    setGateway({ ...gw, huggingface_model: suffix ? `${base}:${suffix}` : base });
  };

  /** Provision a whitelist preset, keeping the current routing suffix. */
  const setHfModel = (gw: AdminGateway, model: string) => {
    const { suffix } = splitHfModel(gw.huggingface_model);
    setGateway({ ...gw, huggingface_model: suffix ? `${model}:${suffix}` : model });
  };

  const renderProviderRow = (provider: string) => {
    if (!gateway) return null;
    const p = gateway.providers[provider];
    const t = testStates[provider] ?? { testing: false, valid: null, detail: '' };
    return (
      <div className="ark-byok-row" key={provider}>
        <div className="ark-byok-head">
          <KeyRound className="w-3.5 h-3.5" style={{ color: '#6B7280' }} />
          <span className="ark-byok-label">{PROVIDER_LABELS[provider]}</span>
          {statusBadge(p)}
          {p.configured && p.preview && <span className="ark-mono" style={{ color: '#6B7280', fontSize: 10 }}>{p.preview}</span>}
          <span style={{ marginLeft: 'auto' }}>
            <button className="ark-byok-test" disabled={t.testing || !p.configured}
              onClick={() => testProvider(provider)}>
              <TestTube className="w-3 h-3" /> {t.testing ? 'Testing…' : 'Live Test'}
            </button>
          </span>
        </div>
        {t.valid !== null && (
          <div className="ark-inline">
            <span className={`ark-key-badge ${t.valid ? 'ark-key-valid' : 'ark-key-invalid'}`}>
              <span className="ark-badge-dot" />{t.valid ? 'CONNECTED' : 'UNREACHABLE'}
            </span>
            <span className="ark-key-detail">{t.detail}</span>
          </div>
        )}
        <div className="ark-byok-input-row">
          <div className="ark-byok-input-wrap">
            {PAIRED_FIELDS[provider] ? (
              PAIRED_FIELDS[provider].map(f => (
                <input
                  key={f.field}
                  className="ark-byok-input"
                  type="password"
                  placeholder={p.configured ? `Replace ${f.label}…` : `Set ${f.label}…`}
                  value={inputValues[`${provider}:${f.field}`] ?? ''}
                  onChange={e => setInputValues(v => ({ ...v, [`${provider}:${f.field}`]: e.target.value }))}
                  autoComplete="off"
                />
              ))
            ) : (
              <input
                className="ark-byok-input"
                type={showValues[provider] ? 'text' : 'password'}
                placeholder={p.configured ? 'Enter new value to replace admin key…' : 'Set admin global key…'}
                value={inputValues[provider] ?? ''}
                onChange={e => setInputValues(v => ({ ...v, [provider]: e.target.value }))}
                autoComplete="off"
              />
            )}
            {!PAIRED_FIELDS[provider] && (
              <button className="ark-byok-eye" onClick={() => setShowValues(s => ({ ...s, [provider]: !s[provider] }))}>
                {showValues[provider] ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
              </button>
            )}
          </div>
          <button className="ark-byok-test" disabled={saving || !hasInput(provider)}
            onClick={() => saveGlobalKey(provider)}>Encrypt & Save</button>
        </div>
      </div>
    );
  };

  return (
    <div>
      {error && <div className="ark-card ark-mt" style={{ color: '#FCA5A5' }}>{error}</div>}
      {loading ? (
        <div className="ark-admin-loading" style={{ minHeight: 220 }}><div className="ark-spinner" /><div>Loading gateway…</div></div>
      ) : gateway && (
        <>
          <div className="ark-card">
            <div className="ark-cs-card-title"><Globe className="w-3.5 h-3.5" /> ACTIVE PROVIDER &amp; MODEL</div>
            <div className="ark-inline">
              {MODEL_PROVIDERS.map(p => (
                <label key={p} className={`ark-radio ${gateway.active_llm_provider === p ? 'ark-radio-active' : ''}`}>
                  <input type="radio" name="active-provider" checked={gateway.active_llm_provider === p}
                    onChange={() => setActiveProvider(p)} />
                  <div>
                    <div className="ark-radio-label">{PROVIDER_LABELS[p]}</div>
                    <div className="ark-radio-desc">
                      {p === 'ollama' ? 'Local runtime' : gateway.providers[p]?.configured ? 'Configured' : 'Not configured'}
                    </div>
                  </div>
                </label>
              ))}
            </div>

            {(() => {
              const active = gateway.active_llm_provider;
              const currentModel = activeModel(gateway, active);
              const cat = catalog[active];
              const catalogModels = cat?.models ?? [];
              const options = currentModel && !catalogModels.includes(currentModel)
                ? [currentModel, ...catalogModels]
                : catalogModels;
              return (
                <div className="ark-mt" style={{ marginTop: 14 }}>
                  {active === 'ollama' && (
                    <div className="ark-cs-field" style={{ marginBottom: 10 }}>
                      <span className="ark-cs-field-label">Ollama Base URL</span>
                      <input className="ark-cs-input" value={gateway.ollama_url}
                        onChange={e => setGateway({ ...gateway, ollama_url: e.target.value })} />
                    </div>
                  )}
                  <div className="ark-inline">
                    <div className="ark-cs-field" style={{ flex: 1, minWidth: 0 }}>
                      <span className="ark-cs-field-label">Active model — {PROVIDER_LABELS[active]}</span>
                      <select className="ark-cs-select" value={currentModel}
                        onChange={e => setActiveModel(active, e.target.value)}>
                        {!options.length && <option value="">No models available — click Refresh</option>}
                        {options.map(m => <option key={m} value={m}>{m}</option>)}
                      </select>
                    </div>
                    <div className="ark-inline" style={{ alignItems: 'flex-end' }}>
                      <button className="ark-btn ark-btn-sm" disabled={catalogLoading[active]}
                        onClick={() => fetchCatalog(active)}>
                        <RefreshCw className="w-3 h-3" />
                        {catalogLoading[active] ? 'Fetching…' : 'Refresh'}
                      </button>
                      {active === 'ollama' && (
                        <button className="ark-btn ark-btn-sm" disabled={saving}
                          onClick={() => updateGateway({ ollama_url: gateway.ollama_url })}>
                          Save URL
                        </button>
                      )}
                    </div>
                  </div>
                  {cat && (
                    <div className="ark-inline ark-mt" style={{ marginTop: 8 }}>
                      <span className={`ark-key-badge ${cat.source === 'error' ? 'ark-key-invalid' : 'ark-key-valid'}`}>
                        <span className="ark-badge-dot" />
                        {cat.source === 'live'
                          ? `LIVE · ${cat.models.length} models`
                          : cat.source === 'curated' ? 'CURATED WHITELIST' : 'UNAVAILABLE'}
                      </span>
                      <span className="ark-key-detail">{cat.detail}</span>
                    </div>
                  )}
                </div>
              );
            })()}

            <div className="ark-flag ark-mt" style={{ marginTop: 12, color: '#6B7280' }}>
              Pick the active provider, then its active model. Model lists are fetched live from Ollama, OpenAI, Gemini, Anthropic
              and OpenRouter; HuggingFace uses the curated on-file whitelist. The chosen pair is what the agent consumes for LLM
              routing.
            </div>
          </div>

          <div className="ark-card">
            <div className="ark-cs-card-title"><Server className="w-3.5 h-3.5" /> HUGGINGFACE INFERENCE PROVIDERS</div>
            <div className="ark-cs-grid-2">
              <div className="ark-cs-field">
                <span className="ark-cs-field-label">Base URL</span>
                <input className="ark-cs-input" value={gateway.huggingface_url}
                  onChange={e => setGateway({ ...gateway, huggingface_url: e.target.value })} />
              </div>
              <div className="ark-cs-field">
                <span className="ark-cs-field-label">Routing policy</span>
                <select className="ark-cs-select"
                  value={splitHfModel(gateway.huggingface_model).suffix}
                  onChange={e => setHfRouting(gateway, e.target.value)}>
                  {HF_ROUTING_POLICIES.map(p => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="ark-cs-field ark-mt" style={{ marginTop: 12 }}>
              <span className="ark-cs-field-label">Model name — Organization/Model-Name[:provider]</span>
              <input className="ark-cs-input" placeholder="e.g. Qwen/Qwen2.5-Coder-7B-Instruct:fastest"
                value={gateway.huggingface_model}
                onChange={e => setGateway({ ...gateway, huggingface_model: e.target.value })} />
            </div>
            <div style={{ marginTop: 14 }}>
              <div className="ark-cs-field-label">Recommended whitelist — click to provision</div>
              {HF_RECOMMENDED_MODELS.map(g => (
                <div key={g.group} style={{ marginTop: 10 }}>
                  <div className="ark-cs-field-label" style={{ fontSize: 9, color: '#6B7280' }}>{g.group}</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
                    {g.models.map(m => {
                      const active = splitHfModel(gateway.huggingface_model).base === m;
                      return (
                        <button key={m} type="button"
                          className="ark-btn ark-btn-sm"
                          onClick={() => setHfModel(gateway, m)}
                          style={active
                            ? { borderColor: '#22d3ee', color: '#22d3ee', boxShadow: '0 0 0 1px rgba(34,211,238,0.4)' }
                            : undefined}>
                          {m}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
            <div className="ark-inline ark-mt">
              <button className="ark-btn ark-btn-sm" disabled={saving}
                onClick={() => updateGateway({ huggingface_url: gateway.huggingface_url, huggingface_model: gateway.huggingface_model })}>
                Save HuggingFace Config
              </button>
            </div>
            <div className="ark-mt" style={{ marginTop: 14 }}>
              {renderProviderRow(HUGGINGFACE)}
            </div>
            <div className="ark-flag ark-mt" style={{ color: '#6B7280' }}>
              Routing suffixes are evaluated by the HuggingFace router at request time: <span className="ark-mono">:fastest</span> auto-routes to
              the fastest live provider, while <span className="ark-mono">:groq</span>, <span className="ark-mono">:sambanova</span>, … pin a
              specific hardware pipeline. Personal access token (hf_…) with the "Inference Providers" permission. Live Test lists the models
              your token can reach; the provisioned model + token is the gateway configuration the agent consumes for HuggingFace routing.
            </div>
          </div>

          <div className="ark-card">
            <div className="ark-cs-card-title"><KeyRound className="w-3.5 h-3.5" /> GLOBAL CLOUD LLMs</div>
            {LLM_PROVIDERS.map(renderProviderRow)}
            <div className="ark-flag ark-mt" style={{ color: '#6B7280' }}>
              Dual-layer resolution: User BYOK override → Admin System Key (here) → .env. Keys are AES-256-GCM encrypted server-side and never returned in full.
            </div>
          </div>

          <div className="ark-card">
            <div className="ark-cs-card-title"><Globe className="w-3.5 h-3.5" /> OSINT &amp; IMAGE INTELLIGENCE APIs</div>
            {OSINT_PROVIDERS.map(renderProviderRow)}
          </div>

          <div className="ark-card">
            <div className="ark-cs-card-title"><Server className="w-3.5 h-3.5" /> TELECOM &amp; NUMBER INTELLIGENCE APIs</div>
            {TELECOM_PROVIDERS.map(renderProviderRow)}
            <div className="ark-flag ark-mt" style={{ color: '#6B7280' }}>
              Twilio, OpenCNAM, Telesign and Tru.ID require two credentials (account + token) — both are saved when you press Encrypt &amp; Save.
            </div>
          </div>

          <div className="ark-inline ark-mt">
            <button className="ark-btn ark-btn-sm" onClick={load}><RefreshCw className="w-3 h-3" /> Refresh Status</button>
          </div>
        </>
      )}
    </div>
  );
}
