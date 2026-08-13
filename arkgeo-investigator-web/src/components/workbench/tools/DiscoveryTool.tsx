/**
 * DiscoveryTool — Source Discovery & Digital Footprint.
 *
 * Provider-agnostic reverse image search.  Shows perceptual hash, embedded
 * URLs, and gracefully reports UNAVAILABLE when no provider is configured.
 * Never fabricates search results.
 */
import React from 'react';
import type { AnalyzeResponse } from '../../../types';

interface DiscoveryToolProps {
  result: AnalyzeResponse;
}

export function DiscoveryTool({ result }: DiscoveryToolProps) {
  const disc = result.source_discovery;
  if (!disc) {
    return <div className="tool-empty"><div className="tool-empty-text">Source discovery data not available.</div></div>;
  }

  const unavailable = disc.state === 'UNAVAILABLE';

  return (
    <div className="tool-view tool-discovery">
      <div className="tool-content">
        <div className="discovery-status-banner">
          <div className={`discovery-state ${unavailable ? 'discovery-state-unavail' : 'discovery-state-avail'}`}>
            {unavailable ? 'UNAVAILABLE' : 'AVAILABLE'}
          </div>
          <div className="discovery-detail">{disc.detail}</div>
        </div>

        <div className="discovery-section">
          <div className="discovery-section-title">LOCAL FINGERPRINT</div>
          <div className="discovery-phash">
            <span className="discovery-phash-label">Perceptual Hash (pHash):</span>
            <span className="discovery-phash-value mono">{disc.phash || 'N/A'}</span>
          </div>
        </div>

        <div className="discovery-section">
          <div className="discovery-section-title">EMBEDDED URLs ({disc.embedded_urls.length})</div>
          {disc.embedded_urls.length === 0 ? (
            <div className="discovery-empty">No URLs found in metadata</div>
          ) : (
            <div className="discovery-url-list">
              {disc.embedded_urls.map((url, i) => (
                <div key={i} className="discovery-url-item mono">{url}</div>
              ))}
            </div>
          )}
        </div>

        <div className="discovery-section">
          <div className="discovery-section-title">EXACT MATCHES ({disc.exact_matches.length})</div>
          {disc.exact_matches.length === 0 ? (
            <div className="discovery-empty">
              {unavailable ? 'Provider not configured — no search performed.' : 'No exact matches found.'}
            </div>
          ) : (
            <div className="discovery-match-list">
              {disc.exact_matches.map((m, i) => <div key={i} className="discovery-match-item">{JSON.stringify(m)}</div>)}
            </div>
          )}
        </div>

        <div className="discovery-section">
          <div className="discovery-section-title">SIMILAR MATCHES ({disc.similar_matches.length})</div>
          {disc.similar_matches.length === 0 ? (
            <div className="discovery-empty">
              {unavailable ? 'Provider not configured — no search performed.' : 'No similar matches found.'}
            </div>
          ) : (
            <div className="discovery-match-list">
              {disc.similar_matches.map((m, i) => <div key={i} className="discovery-match-item">{JSON.stringify(m)}</div>)}
            </div>
          )}
        </div>

        <div className="discovery-section">
          <div className="discovery-section-title">SOURCE TIMELINE ({disc.timeline.length})</div>
          {disc.timeline.length === 0 ? (
            <div className="discovery-empty">No timeline events available.</div>
          ) : (
            <div className="discovery-timeline">
              {disc.timeline.map((t, i) => <div key={i} className="discovery-timeline-item">{JSON.stringify(t)}</div>)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
