/**
 * ExifViewer — raw metadata breakdown tree + IMINT 4-pillar image
 * intelligence folders.
 *
 * When exifMissing or steganographyDetected is true, the panel border and
 * text shift to pulsing Tactical Amber or Neon-Red. IMINT analysis flags
 * (clock drift, sub-second timestamp anomaly, geospatial conflicts) also
 * degrade the panel to amber.
 */
import React, { useState } from 'react';
import type { CandidateRegion, ImintPayload, ReverseSearchResult } from '../../types';

interface Props {
  exifRaw: Record<string, unknown> | null;
  imageSha256: string;
  exifMissing?: boolean;
  steganographyDetected?: boolean;
  imageIntelligence?: ImintPayload | null;
  /** Feature 1 — EXIF_PRESENT | STRIPPED_BY_INTERMEDIARY (full or partial strip). */
  metadataStatus?: string | null;
  /** Feature 4 — ranked Terrain IMINT candidate regions. */
  candidateRegions?: CandidateRegion[] | null;
  /** Feature 3 — on-demand reverse source search (Visual Identifiers). */
  reverseSearch?: ReverseSearchResult | null;
  reverseSearchLoading?: boolean;
  reverseSearchDisabled?: boolean;
  onReverseSearch?: () => void;
  onReverseSearchClear?: () => void;
}

const STRIPPED = 'STRIPPED_BY_INTERMEDIARY';

const PILLAR_ORDER = ['geospatial', 'temporal', 'device', 'capture'] as const;
const PILLAR_LABELS: Record<string, string> = {
  geospatial: 'PILLAR 1 · GEOSPATIAL (WHERE)',
  temporal: 'PILLAR 2 · TEMPORAL (WHEN)',
  device: 'PILLAR 3 · HARDWARE PROVENANCE (WHAT)',
  capture: 'PILLAR 4 · CAPTURE DIAGNOSTICS (HOW)',
};

function prettifyKey(key: string): string {
  return key.replace(/_/g, ' ').toUpperCase();
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'boolean') return v ? 'YES' : 'NO';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

function initialOpen(payload: ImintPayload | null): Record<string, boolean> {
  const open: Record<string, boolean> = { analysis: true };
  if (!payload) return open;
  for (const p of PILLAR_ORDER) {
    open[p] = payload.analysis?.pillars_present?.[p] === true;
  }
  return open;
}

export function ExifViewer({
  exifRaw,
  imageSha256,
  exifMissing,
  steganographyDetected,
  imageIntelligence,
  metadataStatus,
  candidateRegions,
  reverseSearch,
  reverseSearchLoading,
  reverseSearchDisabled,
  onReverseSearch,
  onReverseSearchClear,
}: Props) {
  const [showRaw, setShowRaw] = useState(false);
  const [openPillars, setOpenPillars] = useState<Record<string, boolean>>(() =>
    initialOpen(imageIntelligence ?? null),
  );

  const imintAlert =
    imageIntelligence?.analysis?.clock_drift_detected ||
    imageIntelligence?.analysis?.subsec_anomaly_detected ||
    (imageIntelligence?.analysis?.geospatial_conflicts?.length ?? 0) > 0;

  const degradationClass = steganographyDetected
    ? 'panel-degraded-red'
    : exifMissing || metadataStatus === STRIPPED || imintAlert
      ? 'panel-degraded-amber'
      : '';

  const entries = exifRaw ? Object.entries(exifRaw) : [];
  const togglePillar = (key: string) =>
    setOpenPillars((prev) => ({ ...prev, [key]: !prev[key] }));

  const renderRows = (data: Record<string, unknown>) => (
    <div className="exif-tree">
      {Object.entries(data).map(([key, value]) => (
        <div key={key} className="exif-row">
          <span className="exif-key mono">{prettifyKey(key)}</span>
          <span className="exif-value mono">{fmt(value)}</span>
        </div>
      ))}
    </div>
  );

  return (
    <div className={`panel-section ${degradationClass}`}>
      <div className="panel-title">EXIF / METADATA BREAKDOWN</div>

      {exifMissing && (
        <div className="alert-box alert-amber">
          <div className="alert-title">ASSET METADATA STRIPPED</div>
          <div className="alert-detail">
            No EXIF metadata present — image has been stripped of all embedded
            camera and GPS data.
          </div>
        </div>
      )}
      {metadataStatus === STRIPPED && !exifMissing && (
        <div className="alert-box alert-amber">
          <div className="alert-title">⚠️ EXIF STRIPPED / METADATA ABSENT</div>
          <div className="alert-detail">
            Metadata stripped by an intermediary — embedded GPS or EXIF was
            removed while some fields survived re-encode (partial strip). Treat
            surviving fields as untrusted provenance.
          </div>
        </div>
      )}
      {steganographyDetected && (
        <div className="alert-box alert-red">
          <div className="alert-title">STRUCTURAL ANOMALIES DETECTED</div>
          <div className="alert-detail">
            Trailing bytes found after EOF marker — possible steganographic payload.
          </div>
        </div>
      )}
      {imintAlert && !exifMissing && (
        <div className="alert-box alert-amber">
          <div className="alert-title">IMAGE INTELLIGENCE FLAGS</div>
          <div className="alert-detail">
            {imageIntelligence?.analysis?.clock_drift_detected
              ? 'Device and satellite clocks diverge beyond tolerance. '
              : ''}
            {imageIntelligence?.analysis?.subsec_anomaly_detected
              ? `Sub-second timestamp anomaly (${(imageIntelligence.analysis.subsec_anomaly_reasons ?? []).join(', ')}). `
              : ''}
            {(imageIntelligence?.analysis?.geospatial_conflicts ?? []).length > 0
              ? 'Geospatial conflicts detected across embedded coordinates.'
              : ''}
          </div>
        </div>
      )}

      <div className="exif-sha">
        <span className="exif-sha-label">SHA-256</span>
        <span className="exif-sha-value mono">{imageSha256}</span>
      </div>

      {imageIntelligence && (
        <div className="exif-imint">
          <div className="exif-imint-title">IMAGE INTELLIGENCE · 4-PILLAR ANALYSIS</div>
          {PILLAR_ORDER.map((pillar) => (
            <div key={pillar} className="exif-folder">
              <button
                className="exif-folder-head"
                onClick={() => togglePillar(pillar)}
              >
                <span className="exif-chevron">{openPillars[pillar] ? '▾' : '▸'}</span>
                <span className="exif-folder-label">{PILLAR_LABELS[pillar]}</span>
                <span
                  className={
                    imageIntelligence.analysis?.pillars_present?.[pillar]
                      ? 'exif-folder-badge present'
                      : 'exif-folder-badge'
                  }
                >
                  {imageIntelligence.analysis?.pillars_present?.[pillar]
                    ? 'PRESENT'
                    : 'ABSENT'}
                </span>
              </button>
              {openPillars[pillar] && (
                <div className="exif-folder-body">
                  {renderRows(imageIntelligence[pillar] as unknown as Record<string, unknown>)}
                </div>
              )}
            </div>
          ))}
          <div className="exif-folder">
            <button
              className="exif-folder-head"
              onClick={() => togglePillar('analysis')}
            >
              <span className="exif-chevron">{openPillars.analysis ? '▾' : '▸'}</span>
              <span className="exif-folder-label">DERIVED ANALYSIS · FINGERPRINT</span>
              <span className="exif-folder-badge present">ACTIVE</span>
            </button>
            {openPillars.analysis && (
              <div className="exif-folder-body">
                {renderRows({
                  pillars_present: imageIntelligence.analysis?.pillars_present,
                  clock_drift_detected: imageIntelligence.analysis?.clock_drift_detected,
                  dop_quality: imageIntelligence.analysis?.dop_quality,
                  subsec_anomaly_detected: imageIntelligence.analysis?.subsec_anomaly_detected,
                  subsec_anomaly_reasons: imageIntelligence.analysis?.subsec_anomaly_reasons,
                  geospatial_conflicts: imageIntelligence.analysis?.geospatial_conflicts,
                  unique_fingerprint: imageIntelligence.analysis?.unique_fingerprint,
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {candidateRegions && candidateRegions.length > 0 && (
        <div className="exif-imint">
          <div className="exif-imint-title">TERRAIN IMINT · RANKED CANDIDATE REGIONS</div>
          {candidateRegions.map((cr, i) => (
            <div key={i} className="exif-folder">
              <button
                className="exif-folder-head"
                onClick={() => togglePillar(`region-${i}`)}
              >
                <span className="exif-chevron">{openPillars[`region-${i}`] ? '▾' : '▸'}</span>
                <span className="exif-folder-label">#{i + 1} · {cr.region}</span>
                <span
                  className="exif-folder-badge"
                  style={{ color: cr.confidence >= 0.7 ? '#22C55E' : '#F59E0B', borderColor: cr.confidence >= 0.7 ? '#22C55E' : '#F59E0B' }}
                >
                  {Math.round(cr.confidence * 100)}%
                </span>
              </button>
              {openPillars[`region-${i}`] && cr.rationale && (
                <div className="exif-folder-body">
                  <div className="exif-tree">
                    <div className="exif-row">
                      <span className="exif-key mono">RATIONALE</span>
                      <span className="exif-value">{cr.rationale}</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="exif-imint">
        <div className="exif-imint-title">VISUAL IDENTIFIERS · REVERSE SOURCE SEARCH</div>
        <div className="exif-sha">
          <span className="exif-sha-label">PERCEPTUAL HASH (pHash)</span>
          <span className="exif-sha-value mono">{reverseSearch?.phash || '—'}</span>
        </div>
        <button
          className="tool-btn"
          disabled={reverseSearchLoading || reverseSearchDisabled}
          onClick={onReverseSearch}
          style={{ marginTop: 8, opacity: reverseSearchDisabled ? 0.4 : 1 }}
        >
          {reverseSearchLoading ? 'SEARCHING …' : '🌐 SEARCH VISUAL IDENTIFIERS'}
        </button>
        {reverseSearchDisabled && !reverseSearchLoading && (
          <div className="alert-detail" style={{ marginTop: 6, opacity: 0.8 }}>
            The original file is no longer available in this session — re-ingest the image to enable reverse search.
          </div>
        )}
        {reverseSearch && reverseSearch.state !== 'UNAVAILABLE' && reverseSearch.state !== 'ERROR' && (
          <div className="exif-folder-body" style={{ marginTop: 10 }}>
            <div className="exif-tree">
              <div className="exif-row">
                <span className="exif-key mono">EXACT MATCHES</span>
                <span className="exif-value">{reverseSearch.exact_matches?.length ?? 0}</span>
              </div>
              <div className="exif-row">
                <span className="exif-key mono">SIMILAR MATCHES</span>
                <span className="exif-value">{reverseSearch.similar_matches?.length ?? 0}</span>
              </div>
              {[...(reverseSearch.exact_matches || []), ...(reverseSearch.similar_matches || [])]
                .slice(0, 6)
                .map((m, i) => {
                  const src = m.source_url || m.image_url || m.url;
                  return (
                    <div key={i} className="exif-row">
                      <span className="exif-key mono">{m.title || 'MATCH'}</span>
                      {src ? (
                        <a className="exif-value" href={src} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--cyan-bright)' }}>
                          {src.length > 48 ? src.slice(0, 48) + '…' : src} ↗
                        </a>
                      ) : (
                        <span className="exif-value">{m.filepath || (m.score ?? 'source')}</span>
                      )}
                    </div>
                  );
                })}
            </div>
          </div>
        )}
        {reverseSearch && reverseSearch.state === 'UNAVAILABLE' && (
          <div className="alert-box alert-amber" style={{ marginTop: 10 }}>
            <div className="alert-title">REVERSE SEARCH UNAVAILABLE</div>
            <div className="alert-detail">
              No reverse-source provider configured (TinEye / Serper). Configure a key in the Admin
              Console to query for known copies of this image.
            </div>
          </div>
        )}
        {reverseSearch && reverseSearch.state === 'ERROR' && (
          <div className="alert-box alert-red" style={{ marginTop: 10 }}>
            <div className="alert-title">REVERSE SEARCH FAILED</div>
            <div className="alert-detail">{reverseSearch.detail}</div>
          </div>
        )}
        {reverseSearch && (
          <button
            className="exif-toggle"
            onClick={onReverseSearchClear}
            style={{ marginTop: 8 }}
          >
            CLEAR
          </button>
        )}
      </div>

      {entries.length === 0 ? (
        <div className="panel-empty">
          {exifMissing
            ? 'EXIF metadata stripped — no fields to display.'
            : 'No EXIF metadata found — image may be stripped or zero-retention.'}
        </div>
      ) : (
        <>
          <div className="exif-entry-count">
            {entries.length} field{entries.length !== 1 ? 's' : ''} extracted
          </div>
          <div className="exif-tree">
            {entries.slice(0, showRaw ? undefined : 15).map(([key, value]) => (
              <div key={key} className="exif-row">
                <span className="exif-key mono">{key}</span>
                <span className="exif-value mono">
                  {typeof value === 'object'
                    ? JSON.stringify(value)
                    : String(value)}
                </span>
              </div>
            ))}
          </div>
          {entries.length > 15 && (
            <button className="exif-toggle" onClick={() => setShowRaw(!showRaw)}>
              {showRaw ? 'SHOW LESS' : `SHOW ALL ${entries.length}`}
            </button>
          )}
        </>
      )}
    </div>
  );
}
