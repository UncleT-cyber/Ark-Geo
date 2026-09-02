/**
 * LocalTooling — health of local binaries (ExifTool, Tesseract) and the
 * local inference node (Ollama / vLLM), with a live re-probe action.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Wrench, ScanText, Server } from 'lucide-react';
import { api } from '../../api';
import type { AdminTooling } from '../../types';

export function LocalTooling() {
  const [tooling, setTooling] = useState<AdminTooling | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [probing, setProbing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setTooling(await api.getTooling());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tooling');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const probe = async () => {
    setProbing(true);
    try {
      setTooling(await api.testTooling());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Probe failed');
    } finally {
      setProbing(false);
    }
  };

  const BinaryCard = ({ name, icon: Icon, data, pathLabel }: {
    name: string; icon: React.ComponentType<{ className?: string }>; data?: { available: boolean; path: string; version: string; detail: string }; pathLabel: string;
  }) => (
    <div className="ark-card">
      <div className="ark-inline">
        <span className="ark-cc-card-icon" style={{ marginBottom: 0 }}><Icon className="w-5 h-5" /></span>
        <div>
          <h3 className="ark-cc-card-title">{name}</h3>
          <div className="ark-mono" style={{ fontSize: 10, color: '#6B7280' }}>{pathLabel}</div>
        </div>
        <span style={{ marginLeft: 'auto' }}>
          {data?.available
            ? <span className="ark-badge ark-badge-green"><span className="ark-badge-dot" /> ONLINE</span>
            : <span className="ark-badge ark-badge-red"><span className="ark-badge-dot" /> OFFLINE</span>}
        </span>
      </div>
      {data && (
        <div className="ark-telemetry-grid ark-mt">
          <div className="ark-telemetry-item"><div className="ark-telemetry-k">Path</div>
            <div className="ark-telemetry-v" style={{ fontSize: 11 }}>{data.path || '—'}</div></div>
          <div className="ark-telemetry-item"><div className="ark-telemetry-k">Version</div>
            <div className="ark-telemetry-v">{data.version || '—'}</div></div>
          <div className="ark-telemetry-item" style={{ gridColumn: 'span 2' }}><div className="ark-telemetry-k">Status</div>
            <div className="ark-telemetry-v" style={{ fontSize: 11 }}>{data.detail}</div></div>
        </div>
      )}
    </div>
  );

  return (
    <div>
      <div className="ark-section-head">
        <h2 className="ark-section-title">SYSTEM HEALTH &amp; LOCAL BINARIES</h2>
        <button className="ark-btn ark-btn-sm" onClick={probe} disabled={probing}>
          <RefreshCw className="w-3 h-3" /> {probing ? 'Probing…' : 'Re-probe Health'}
        </button>
      </div>

      {error && <div className="ark-card ark-mt" style={{ color: '#FCA5A5' }}>{error}</div>}
      {loading ? (
        <div className="ark-admin-loading" style={{ minHeight: 220 }}><div className="ark-spinner" /><div>Loading tooling…</div></div>
      ) : tooling && (
        <>
          <div className="ark-grid">
            <BinaryCard name="ExifTool" icon={Wrench} data={tooling.exiftool} pathLabel="EXIF / XMP / IPTC extraction" />
            <BinaryCard name="Tesseract" icon={ScanText} data={tooling.tesseract} pathLabel="OCR text engine" />
          </div>

          <div className="ark-card ark-mt">
            <div className="ark-inline">
              <span className="ark-cc-card-icon" style={{ marginBottom: 0 }}><Server className="w-5 h-5" /></span>
              <div>
                <h3 className="ark-cc-card-title">Local Inference Node</h3>
                <div className="ark-mono" style={{ fontSize: 10, color: '#6B7280' }}>Ollama / vLLM (Zero-Cloud Mode)</div>
              </div>
              <span style={{ marginLeft: 'auto' }}>
                {tooling.ollama.available
                  ? <span className="ark-badge ark-badge-green"><span className="ark-badge-dot" /> ONLINE</span>
                  : <span className="ark-badge ark-badge-red"><span className="ark-badge-dot" /> OFFLINE</span>}
              </span>
            </div>
            <div className="ark-telemetry-grid ark-mt">
              <div className="ark-telemetry-item"><div className="ark-telemetry-k">Base URL</div>
                <div className="ark-telemetry-v" style={{ fontSize: 11 }}>{tooling.ollama.url}</div></div>
              <div className="ark-telemetry-item"><div className="ark-telemetry-k">Default Model</div>
                <div className="ark-telemetry-v">{tooling.ollama.model}</div></div>
              <div className="ark-telemetry-item" style={{ gridColumn: 'span 2' }}><div className="ark-telemetry-k">Probe Result</div>
                <div className="ark-telemetry-v" style={{ fontSize: 11 }}>{tooling.ollama.detail}</div></div>
            </div>
            {tooling.local_nodes.length > 0 && (
              <div className="ark-mt">
                <div className="ark-telemetry-k" style={{ marginBottom: 6 }}>Additional Local Nodes</div>
                {tooling.local_nodes.map(n => (
                  <div key={n.id} className="ark-telemetry-item" style={{ marginBottom: 6 }}>
                    <div className="ark-telemetry-v">{n.name} <span className="ark-mono" style={{ color: '#6B7280' }}>{n.url}</span>
                      <span style={{ marginLeft: 8 }}>{n.ok
                        ? <span className="ark-badge ark-badge-green"><span className="ark-badge-dot" /> ONLINE</span>
                        : <span className="ark-badge ark-badge-red"><span className="ark-badge-dot" /> OFFLINE</span>}</span></div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
