/**
 * ByokPanel — Bring Your Own Key vault. Lists every provider the client
 * pipeline can drive, split into Multimodal AI Reasoning and Image
 * Intelligence & OSINT. Each row: masked input + eye toggle, live
 * connection test, override switch, clear, and the resolved source tag
 * (User BYOK / Admin System / .env).
 */
import React, { useState } from 'react';
import { Eye, EyeOff, TestTube, Trash2, KeyRound, ShieldAlert } from 'lucide-react';
import { useByok } from './ByokContext';
import { BYOK_SPECS } from '../../core/byok/byokStore';
import type { ByokProviderId, KeySource } from '../../types';

const SOURCE_TAG: Record<KeySource, string> = {
  byok: 'BYOK',
  system: 'ADMIN SYS KEY',
  env: 'ENV',
  none: 'NONE',
};

const SOURCE_CLASS: Record<KeySource, string> = {
  byok: 'ark-source-byok',
  system: 'ark-source-system',
  env: 'ark-source-env',
  none: '',
};

function KeyRow({ id }: { id: ByokProviderId }) {
  const { keys, setKey, clearKey, setOverride, testKey } = useByok();
  const state = keys[id];
  const [value, setValue] = useState('');
  const [show, setShow] = useState(false);
  const t = state.testing;
  const result = state.tested;

  const submit = () => {
    if (!value.trim()) return;
    setKey(id, value);
    setValue('');
  };

  return (
    <div className="ark-byok-row">
      <div className="ark-byok-head">
        <KeyRound className="w-3.5 h-3.5" style={{ color: '#6B7280' }} />
        <span className="ark-byok-label">{state.spec.label}</span>
        <span className="ark-byok-hint">{state.spec.hint}</span>
        <span style={{ marginLeft: 'auto' }}>
          <span className={`ark-source-tag ${SOURCE_CLASS[state.resolved]}`}>{SOURCE_TAG[state.resolved]}</span>
        </span>
      </div>

      {result && (
        <div className="ark-inline">
          <span className={`ark-key-badge ${t ? 'ark-key-testing' : result.valid ? 'ark-key-valid' : 'ark-key-invalid'}`}>
            <span className="ark-badge-dot" />
            {t ? 'TESTING…' : result.valid ? `CONNECTED${result.latency_ms ? ` · ${result.latency_ms}ms` : ''}` : 'UNREACHABLE'}
          </span>
          <span className="ark-key-detail">{result.detail}</span>
        </div>
      )}

      <div className="ark-byok-input-row">
        <div className="ark-byok-input-wrap">
          <input
            className="ark-byok-input"
            type={show ? 'text' : 'password'}
            placeholder={state.stored ? 'Enter new value to replace…' : state.spec.placeholder}
            value={value}
            onChange={e => setValue(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && submit()}
            autoComplete="off"
          />
          <button className="ark-byok-eye" onClick={() => setShow(s => !s)}>
            {show ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
          </button>
        </div>
        <button className="ark-byok-test" disabled={!value.trim()} onClick={submit}>Save to Vault</button>
        <button className="ark-byok-test" disabled={t || !state.stored} onClick={() => testKey(id)}>
          <TestTube className="w-3 h-3" /> {t ? 'Testing…' : 'Test'}
        </button>
        {state.stored && (
          <button className="ark-byok-test" title="Clear stored key" onClick={() => clearKey(id)}>
            <Trash2 className="w-3 h-3" />
          </button>
        )}
      </div>

      <label className="ark-byok-override" style={{ alignSelf: 'flex-start' }}>
        <input
          type="checkbox"
          className="ark-check-cs"
          checked={state.override}
          onChange={e => setOverride(id, e.target.checked)}
          disabled={!state.stored}
        />
        Prefer this key over the Admin system key
      </label>
    </div>
  );
}

export function ByokPanel() {
  const { overrideCount } = useByok();
  const categories: { label: string; desc: string; ids: ByokProviderId[] }[] = [
    { label: 'Multimodal AI Reasoning', desc: 'Vision / LLM ensemble providers used by the analysis cascade.', ids: BYOK_SPECS.filter(s => s.category === 'Multimodal AI Reasoning').map(s => s.id) },
    { label: 'Image Intelligence & OSINT', desc: 'Geolocation and reverse-source discovery.', ids: BYOK_SPECS.filter(s => s.category === 'Image Intelligence & OSINT').map(s => s.id) },
    { label: 'Telecom Intelligence', desc: 'Phone-number, carrier and number-query lookups.', ids: BYOK_SPECS.filter(s => s.category === 'Telecom Intelligence').map(s => s.id) },
    { label: 'Maps & Geocoding', desc: 'Map tiles, Street View and address resolution.', ids: BYOK_SPECS.filter(s => s.category === 'Maps & Geocoding').map(s => s.id) },
  ];

  return (
    <div>
      <div className="ark-cs-card">
        <div className="ark-cs-card-title"><KeyRound className="w-3.5 h-3.5" /> ACTIVE KEY RESOLUTION</div>
        <p style={{ fontSize: 12.5, color: '#9CA3AF', lineHeight: 1.6, margin: 0 }}>
          Each provider resolves through the chain <span className="ark-source-tag ark-source-byok">USER BYOK</span> →
          <span className="ark-source-tag ark-source-system">ADMIN SYS KEY</span> → <span className="ark-source-tag ark-source-env">ENV</span>.
          {overrideCount > 0 && (
            <> <span style={{ color: '#A5F3FC' }}>{overrideCount} active override(s).</span></>
          )}
        </p>
      </div>

      <div className="ark-cs-card" style={{ borderColor: 'rgba(245, 158, 11, 0.25)' }}>
        <div className="ark-cs-card-title" style={{ color: '#FCD34D' }}><ShieldAlert className="w-3.5 h-3.5" /> SECURITY NOTE</div>
        <p style={{ fontSize: 11.5, color: '#9CA3AF', lineHeight: 1.6, margin: 0 }}>
          Keys are obfuscated in your browser's local storage — usable against casual reading but NOT strong
          encryption. The backend never logs or echoes them. For production-grade protection store keys in a
          password manager / hardware vault and leave the Admin system key as the source of truth.
        </p>
      </div>

      {categories.map(cat => (
        <div className="ark-cs-card" key={cat.label}>
          <div className="ark-cs-card-title">{cat.label}</div>
          <p style={{ fontSize: 11, color: '#6B7280', margin: '0 0 10px' }}>{cat.desc}</p>
          {cat.ids.map(id => <KeyRow key={id} id={id} />)}
        </div>
      ))}
    </div>
  );
}
