/**
 * ProvenanceTool — C2PA / Content Credentials provenance analysis.
 *
 * Shows manifest existence, signature status, issuer, claims, actions,
 * and modification history.  Clearly distinguishes verified / unavailable /
 * invalid / incomplete provenance.  Never claims absence = fake.
 *
 * Also displays contradictions detected across evidence layers.
 */
import React from 'react';
import { AlertTriangle } from 'lucide-react';
import type { AnalyzeResponse } from '../../../types';

interface ProvenanceToolProps {
  result: AnalyzeResponse;
}

function stateColor(state: string): string {
  switch (state) {
    case 'VERIFIED': return '#22C55E';
    case 'UNAVAILABLE': return '#64748B';
    case 'INVALID': return '#EF4444';
    case 'INCOMPLETE': return '#F59E0B';
    default: return '#94A3B8';
  }
}

export function ProvenanceTool({ result }: ProvenanceToolProps) {
  const prov = result.provenance;
  const contradictions = result.contradictions || [];

  return (
    <div className="tool-view tool-provenance">
      <div className="tool-content">
        {prov && (
          <div className="provenance-section">
            <div className="provenance-state-banner" style={{ borderColor: stateColor(prov.state) }}>
              <div className="provenance-state" style={{ color: stateColor(prov.state) }}>
                C2PA: {prov.state}
              </div>
              <div className="provenance-detail">{prov.detail}</div>
            </div>

            <div className="provenance-grid">
              <div className="provenance-field">
                <span className="provenance-label">Manifest Found:</span>
                <span className="provenance-value">{prov.manifest_found ? 'YES' : 'NO'}</span>
              </div>
              <div className="provenance-field">
                <span className="provenance-label">Issuer:</span>
                <span className="provenance-value">{prov.issuer || 'N/A'}</span>
              </div>
              <div className="provenance-field">
                <span className="provenance-label">Signature Valid:</span>
                <span className="provenance-value">
                  {prov.signature_valid === null ? 'N/A' : prov.signature_valid ? 'YES' : 'NO'}
                </span>
              </div>
              <div className="provenance-field">
                <span className="provenance-label">Claims:</span>
                <span className="provenance-value">{prov.claims.length}</span>
              </div>
              <div className="provenance-field">
                <span className="provenance-label">Actions:</span>
                <span className="provenance-value">{prov.actions.length ? prov.actions.join(', ') : 'None detected'}</span>
              </div>
              <div className="provenance-field">
                <span className="provenance-label">Modifications:</span>
                <span className="provenance-value">{prov.modifications.length ? prov.modifications.join(', ') : 'None detected'}</span>
              </div>
            </div>

            {prov.warnings.length > 0 && (
              <div className="provenance-warnings">
                <div className="provenance-warnings-title">WARNINGS</div>
                {prov.warnings.map((w, i) => <div key={i} className="provenance-warning"><AlertTriangle className="w-3.5 h-3.5" /> {w}</div>)}
              </div>
            )}
          </div>
        )}

        <div className="contradictions-section">
          <div className="contradictions-title">
            <AlertTriangle className="w-4 h-4" /> CONTRADICTIONS DETECTED ({contradictions.length})
          </div>
          {contradictions.length === 0 ? (
            <div className="contradictions-empty">
              No contradictions detected across evidence layers. This does not prove authenticity —
              it means no conflicts were found between the available signals.
            </div>
          ) : (
            <div className="contradictions-list">
              {contradictions.map((c, i) => (
                <div key={i} className={`contradiction-card contradiction-${c.severity.toLowerCase()}`}>
                  <div className="contradiction-type mono">{c.type}</div>
                  <div className="contradiction-what">{c.what_conflicts}</div>
                  <div className="contradiction-meta">
                    <span className="contradiction-meta-item">Severity: <strong style={{ color: c.severity === 'HIGH' ? '#EF4444' : '#F59E0B' }}>{c.severity}</strong></span>
                    <span className="contradiction-meta-item">Reliability: {c.reliability}</span>
                    <span className="contradiction-meta-item">Affects assessment: {c.affects_assessment ? 'YES' : 'NO'}</span>
                  </div>
                  {c.evidence_sources.length > 0 && (
                    <div className="contradiction-sources">
                      <span className="contradiction-sources-label">Sources:</span>
                      {c.evidence_sources.map((s, j) => <span key={j} className="contradiction-source mono">{s}</span>)}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
