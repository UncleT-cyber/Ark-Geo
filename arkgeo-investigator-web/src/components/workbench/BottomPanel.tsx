/**
 * BottomPanel — expandable bottom diagnostic/output panel (VS Code-style).
 *
 * Tabs:
 *   PROBLEMS    – warnings/errors requiring analyst attention
 *   ANALYSIS LOG – forensic processing events (live stream)
 *   EVIDENCE    – hashes and core file information
 *   AUDIT       – chain-of-custody events
 *   OUTPUT      – provider/model/tool output
 */
import React, { useState } from 'react';
import type { AnalyzeResponse } from '../../types';

interface BottomPanelProps {
  result: AnalyzeResponse | null;
  collapsed: boolean;
  onToggle: () => void;
}

type BottomTab = 'problems' | 'log' | 'evidence' | 'audit' | 'output';

export function BottomPanel({ result, collapsed, onToggle }: BottomPanelProps) {
  const [tab, setTab] = useState<BottomTab>('problems');

  const problems: { type: string; msg: string; severity: string }[] = [];
  if (result?.exif_missing) problems.push({ type: 'Metadata', msg: 'EXIF metadata stripped/missing', severity: 'warning' });
  if (result?.steganography_detected) problems.push({ type: 'Structure', msg: `Trailing bytes after EOF (${result.trailing_bytes_count})`, severity: 'error' });
  if (result?.gps_spoofing_detected) problems.push({ type: 'GPS', msg: `Spoofing suspected (anomaly ${Math.round((result.anomaly_score || 0) * 100)}%)`, severity: 'error' });
  (result?.consistency_findings || []).forEach(f => {
    if (f.status !== 'OK') problems.push({ type: f.type, msg: f.message, severity: f.severity.toLowerCase() });
  });
  (result?.contradictions || []).forEach(c => {
    problems.push({ type: c.type, msg: c.what_conflicts, severity: c.severity.toLowerCase() });
  });

  const cert = result?.custody_certificate;
  const auditEntries = result ? [
    { ts: result.created_at, action: 'Evidence acquired', detail: `SHA-256: ${result.image_sha256.slice(0, 24)}...` },
    { ts: result.created_at, action: 'SHA-256 calculated', detail: result.image_sha256 },
    ...(cert ? [{ ts: result.created_at, action: 'SHA-1 fingerprint', detail: cert.sha1 }] : []),
    ...(cert ? [{ ts: result.created_at, action: 'MD5 fingerprint', detail: cert.md5 }] : []),
    { ts: result.created_at, action: 'Cascade complete', detail: `Source: ${result.source} · Confidence: ${Math.round(result.consensus.confidence_score * 100)}%` },
  ] : [];

  return (
    <div className={`bottom-panel ${collapsed ? 'bottom-panel-collapsed' : ''}`}>
      <div className="bottom-panel-header">
        <div className="bottom-panel-tabs">
          {(['problems', 'log', 'evidence', 'audit', 'output'] as BottomTab[]).map(t => (
            <button
              key={t}
              className={`bottom-tab ${tab === t ? 'bottom-tab-active' : ''}`}
              onClick={() => { setTab(t); if (collapsed) onToggle(); }}
            >
              {t === 'problems' && problems.length > 0 && <span className="bottom-tab-badge">{problems.length}</span>}
              {t.toUpperCase().replace('LOG', 'ANALYSIS LOG')}
            </button>
          ))}
        </div>
        <button className="bottom-panel-toggle" onClick={onToggle} title={collapsed ? 'Expand panel' : 'Collapse panel'}>
          {collapsed ? '▲' : '▼'}
        </button>
      </div>
      {!collapsed && (
        <div className="bottom-panel-content">
          {tab === 'problems' && (
            <div className="bottom-list">
              {problems.length === 0 ? (
                <div className="bottom-empty">No problems detected</div>
              ) : problems.map((p, i) => (
                <div key={i} className={`bottom-row bottom-row-${p.severity}`}>
                  <span className="bottom-row-icon">{p.severity === 'error' ? '✕' : '⚠'}</span>
                  <span className="bottom-row-type mono">{p.type}</span>
                  <span className="bottom-row-msg">{p.msg}</span>
                </div>
              ))}
            </div>
          )}
          {tab === 'log' && (
            <div className="bottom-list bottom-log">
              {(result?.analysis_log || []).length === 0 ? (
                <div className="bottom-empty">No analysis events yet</div>
              ) : (result?.analysis_log || []).map((line, i) => (
                <div key={i} className="bottom-log-line mono">{line}</div>
              ))}
            </div>
          )}
          {tab === 'evidence' && (
            <div className="bottom-list">
              {!result ? <div className="bottom-empty">No evidence loaded</div> : (
                <>
                  <div className="bottom-row"><span className="bottom-row-type mono">SHA-256</span><span className="bottom-row-msg mono">{result.image_sha256}</span></div>
                  {cert && <div className="bottom-row"><span className="bottom-row-type mono">SHA-1</span><span className="bottom-row-msg mono">{cert.sha1}</span></div>}
                  {cert && <div className="bottom-row"><span className="bottom-row-type mono">MD5</span><span className="bottom-row-msg mono">{cert.md5}</span></div>}
                  <div className="bottom-row"><span className="bottom-row-type mono">MIME</span><span className="bottom-row-msg mono">{result.file_format || 'N/A'}</span></div>
                  <div className="bottom-row"><span className="bottom-row-type mono">Custody</span><span className="bottom-row-msg mono">{result.custody_hash}</span></div>
                </>
              )}
            </div>
          )}
          {tab === 'audit' && (
            <div className="bottom-list">
              {!result ? <div className="bottom-empty">No audit entries</div> : auditEntries.map((e, i) => (
                <div key={i} className="bottom-row">
                  <span className="bottom-row-type mono">{new Date(e.ts).toLocaleTimeString()}</span>
                  <span className="bottom-row-msg"><strong>{e.action}</strong> — {e.detail}</span>
                </div>
              ))}
            </div>
          )}
          {tab === 'output' && (
            <div className="bottom-list">
              <div className="bottom-empty">
                {result ? `Source tier: ${result.source} (${result.consensus.tier_used})` : 'No output'}
              </div>
              {result?.message && <div className="bottom-row"><span className="bottom-row-msg">{result.message}</span></div>}
              {result?.source_discovery && <div className="bottom-row"><span className="bottom-row-type mono">DISCOVERY</span><span className="bottom-row-msg">{result.source_discovery.detail}</span></div>}
              {result?.provenance && <div className="bottom-row"><span className="bottom-row-type mono">C2PA</span><span className="bottom-row-msg">{result.provenance.detail}</span></div>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
