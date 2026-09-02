/**
 * ClientModelConfig — which provider runs the vision / reasoning loop:
 * cloud (OpenAI / Gemini / OpenRouter) or fully local Ollama (Zero-Cloud
 * Privacy Mode). Privacy mode keeps everything on the local node.
 */
import React from 'react';
import { Cpu, ShieldCheck, Server } from 'lucide-react';
import { useByok } from './ByokContext';
import type { ClientModelConfig as ModelCfg } from '../../types';

const PROVIDERS: { id: ModelCfg['provider']; label: string; desc: string }[] = [
  { id: 'openai', label: 'OpenAI (GPT-4o Vision)', desc: 'Default ensemble — best multi-factor reasoning quality.' },
  { id: 'gemini', label: 'Google Gemini', desc: 'Alternative cloud vision provider.' },
  { id: 'openrouter', label: 'OpenRouter', desc: 'Route to custom / community models.' },
  { id: 'ollama', label: 'Ollama (Local Node)', desc: 'Zero-Cloud Privacy Mode — runs entirely on your machine.' },
];

export function ClientModelConfigPanel() {
  const { model, setModel } = useByok();

  const set = (patch: Partial<ModelCfg>) => setModel({ ...model, ...patch });

  return (
    <div>
      <div className="ark-cs-card">
        <div className="ark-cs-card-title"><Cpu className="w-3.5 h-3.5" /> REASONING PROVIDER</div>
        <div className="ark-radio-group">
          {PROVIDERS.map(p => (
            <label key={p.id} className={`ark-radio ${model.provider === p.id ? 'ark-radio-active' : ''}`}>
              <input type="radio" checked={model.provider === p.id} onChange={() => set({ provider: p.id })} />
              <div>
                <div className="ark-radio-label">{p.label}</div>
                <div className="ark-radio-desc">{p.desc}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

      <div className="ark-cs-card">
        <div className="ark-cs-card-title"><Server className="w-3.5 h-3.5" /> LOCAL NODE CONFIG</div>
        <div className="ark-cs-grid-2">
          <div className="ark-cs-field">
            <span className="ark-cs-field-label">Ollama Base URL</span>
            <input className="ark-cs-input" value={model.ollamaUrl}
              onChange={e => set({ ollamaUrl: e.target.value })} placeholder="http://localhost:11434" />
          </div>
          <div className="ark-cs-field">
            <span className="ark-cs-field-label">Vision Model</span>
            <input className="ark-cs-input" value={model.ollamaModel}
              onChange={e => set({ ollamaModel: e.target.value })} placeholder="llama3.2-vision:latest" />
          </div>
        </div>
        {model.provider === 'openrouter' && (
          <div className="ark-cs-field" style={{ marginTop: 12 }}>
            <span className="ark-cs-field-label">OpenRouter Model Slug</span>
            <input className="ark-cs-input" value={model.openRouterModel ?? ''}
              onChange={e => set({ openRouterModel: e.target.value })} placeholder="openai/gpt-4o" />
          </div>
        )}
      </div>

      <div className="ark-cs-card" style={{ borderColor: model.privacyMode ? 'rgba(6,182,212,0.35)' : undefined }}>
        <div className="ark-cs-card-title"><ShieldCheck className="w-3.5 h-3.5" /> PRIVACY MODE</div>
        <div className="ark-inline">
          <label className="ark-byok-override">
            <input type="checkbox" className="ark-check-cs" checked={model.privacyMode}
              onChange={e => set({ privacyMode: e.target.checked })} />
            Zero-Cloud — never send pixels to cloud providers
          </label>
          <span style={{ marginLeft: 'auto' }}>
            {model.privacyMode
              ? <span className="ark-key-badge ark-key-valid"><span className="ark-badge-dot" /> PRIVATE</span>
              : <span className="ark-key-badge ark-key-invalid"><span className="ark-badge-dot" /> CLOUD ENABLED</span>}
          </span>
        </div>
        <p style={{ fontSize: 11.5, color: '#9CA3AF', lineHeight: 1.6, margin: '10px 0 0' }}>
          With privacy mode ON the cascade routes exclusively through your local Ollama node; uploads and
          intermediate results stay on this machine. Model quality depends on the local vision model.
        </p>
      </div>
    </div>
  );
}
