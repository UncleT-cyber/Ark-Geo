/**
 * InvestigationOverview — the command center for the current image.
 *
 * Map-first: the spatial workspace is shown immediately at the top and NEVER
 * disappears. If a location was found the marker + geographic evidence are
 * displayed; if not, a clear "Location Not Established" state is shown over
 * the map. Below the map sits the ARK assessment (what we know / don't know /
 * what looks suspicious / investigate next) and the assessment tiles.
 *
 * Every major finding is clickable and opens the relevant forensic sub-view.
 */
import React from 'react';
import { Check, HelpCircle, AlertTriangle, ArrowRight, MapPin, PlayCircle } from 'lucide-react';
import { MapWorkspace } from '../../MapWorkspace/MapWorkspace';
import type { AnalyzeResponse, NextStep } from '../../../types';
import type { ToolTabId } from '../TabBar';

interface InvestigationOverviewProps {
  result: AnalyzeResponse;
  onOpenTool: (toolId: ToolTabId) => void;
  thumbnailUrl?: string;
  onCopyCoords?: () => void;
  onGeofenceViolation?: (point: { lat: number; lon: number }) => void;
  /** Launch a real ARK AI investigation for a recommended next step. */
  onInvestigateNext?: (step: NextStep) => void;
}

function confidenceColor(conf: number): string {
  if (conf >= 0.75) return '#22C55E';
  if (conf >= 0.4) return '#F59E0B';
  return '#EF4444';
}

function stateColor(state: string): string {
  switch (state) {
    case 'VERIFIED': return '#22C55E';
    case 'UNAVAILABLE': return '#64748B';
    case 'INVALID': return '#EF4444';
    case 'INCOMPLETE': return '#F59E0B';
    case 'REVIEW REQUIRED': return '#F59E0B';
    default: return '#94A3B8';
  }
}

export function InvestigationOverview({ result, onOpenTool, thumbnailUrl, onCopyCoords, onGeofenceViolation, onInvestigateNext }: InvestigationOverviewProps) {
  const summary = result.evidence_summary;
  if (!summary) return null;
  const confColor = confidenceColor(summary.confidence);
  const provColor = stateColor(result.provenance?.state || 'UNAVAILABLE');
  const integColor = stateColor(summary.integrity);
  const coords = result.coordinates;

  const imint = result.image_intelligence;
  const screenshotLikely = imint?.analysis?.is_screenshot_likely;
  const visionUnconfigured = result.source === 'EXIF_MISSING_NO_AI_KEY';
  const tags = result.consensus?.visual_evidence_tags || [];
  const ocrClues = tags.filter((t) => t.category === 'ocr').length;
  const objectClues = tags.filter((t) => t.category === 'infrastructure').length;
  const pillars = imint?.analysis?.pillars_present;
  const pillarCount = pillars
    ? Object.values(pillars).filter(Boolean).length
    : 0;

  const mapPoints = coords
    ? [{
        lat: coords.lat,
        lon: coords.lon,
        radius: result.consensus.search_radius_meters,
        confidence: result.consensus.confidence_score,
        source: result.source,
        label: `${result.address?.display_name || result.consensus.primary_country || 'Location'} · ${Math.round(result.consensus.confidence_score * 100)}%`,
        thumbnailUrl,
      }]
    : [];

  return (
    <div className="investigation-overview investigation-overview-map-first">
      <div className="overview-header">
        <div className="overview-title">THE ARK ASSESSMENT</div>
        <div className="overview-case-id mono">Case {result.request_id.slice(0, 8).toUpperCase()}</div>
      </div>

      {summary.image_classification && (
        <div className="overview-class-badge">
          <span className="overview-class-label">ASSET TYPE</span>
          <span className="overview-class-value">{summary.image_classification}</span>
        </div>
      )}

      {/* MAP-FIRST: the spatial workspace is always visible at the top. */}
      <div className="overview-map-container">
        <MapWorkspace
          points={mapPoints}
          history={[]}
          onCopyCoords={onCopyCoords}
          onGeofenceViolation={onGeofenceViolation}
        />
        {!coords && (
          <div className="location-not-established">
            <div className="location-not-established-card">
              <div className="location-not-established-icon"><MapPin className="w-8 h-8" /></div>
              <div className="location-not-established-title">Location Not Established</div>
              {screenshotLikely && (
                <div className="location-recovery-badges">
                  <span className="location-recovery-badge">SCREENSHOT LIKELY</span>
                  <span className="location-recovery-badge">METADATA STRIPPED</span>
                </div>
              )}
              <div className="location-not-established-text">
                {result.message || 'No GPS coordinates or AI-derived location for this image.'}
              </div>

              <div className="location-recovery-signals">
                <div className="location-recovery-signal-title">RECOVERY SIGNALS</div>
                <div className="location-recovery-signal-row">
                  <span className="location-recovery-signal-key">EXIF Pillars</span>
                  <span className="location-recovery-signal-val">{pillarCount}/4 present</span>
                </div>
                <div className="location-recovery-signal-row">
                  <span className="location-recovery-signal-key">OCR Text Clues</span>
                  <span className="location-recovery-signal-val">{ocrClues + objectClues}</span>
                </div>
                {visionUnconfigured && (
                  <div className="location-recovery-signal-row">
                    <span className="location-recovery-signal-key">Vision Geolocation</span>
                    <span className="location-recovery-signal-val location-recovery-signal-warn">NO AI KEYS CONFIGURED</span>
                  </div>
                )}
                {!visionUnconfigured && (
                  <div className="location-recovery-signal-row">
                    <span className="location-recovery-signal-key">Vision Geolocation</span>
                    <span className="location-recovery-signal-val">RUN — no candidate found</span>
                  </div>
                )}
              </div>

              <button className="location-not-established-action" onClick={() => onOpenTool('spatial')}>
                Open Spatial Workspace →
              </button>
            </div>
          </div>
        )}
        {coords && (
          <div className="map-location-banner">
            <span className="map-location-banner-dot" />
            <span className="map-location-banner-text">
              {result.address?.display_name || result.consensus.primary_country || 'Location established'}
            </span>
            <span className="map-location-banner-conf">
              {Math.round(result.consensus.confidence_score * 100)}% · {result.source}
            </span>
          </div>
        )}
      </div>

      {summary.location_hypothesis && (
        <div className="overview-location-hypothesis">
          <div className="overview-section-title">LOCATION HYPOTHESIS (GPS-OFF)</div>
          <div className="location-hyp-note">{summary.location_hypothesis.note}</div>
          {summary.location_hypothesis.hypothesis && (
            <div className="location-hyp-coords mono">
              {summary.location_hypothesis.hypothesis.lat.toFixed(5)}, {summary.location_hypothesis.hypothesis.lon.toFixed(5)}
              <span className="location-hyp-conf">{Math.round(summary.location_hypothesis.confidence * 100)}% hypothesis</span>
            </div>
          )}
          {summary.location_hypothesis.clues.length > 0 && (
            <div className="location-hyp-clues">
              <span className="location-hyp-subtitle">GEOGRAPHIC CLUES</span>
              {summary.location_hypothesis.clues.slice(0, 5).map((c, i) => (
                <div key={i} className="location-hyp-clue"><MapPin className="w-3 h-3" /> {c}</div>
              ))}
            </div>
          )}
          {summary.location_hypothesis.supporting.length > 0 && (
            <div className="location-hyp-sup">
              <span className="location-hyp-subtitle">SUPPORTING</span>
              {summary.location_hypothesis.supporting.map((s, i) => (
                <span key={i} className="location-hyp-badge location-hyp-sup-badge">{s.label}</span>
              ))}
            </div>
          )}
          {summary.location_hypothesis.contradicting.length > 0 && (
            <div className="location-hyp-sup">
              <span className="location-hyp-subtitle">CONTRADICTING</span>
              {summary.location_hypothesis.contradicting.map((s, i) => (
                <span key={i} className="location-hyp-badge location-hyp-con-badge">{s.label}</span>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="overview-tiles">
        <button className="overview-tile" onClick={() => onOpenTool('spatial')}>
          <div className="overview-tile-label">LOCATION</div>
          <div className="overview-tile-value">{summary.location}</div>
          <div className="overview-tile-sub" style={{ color: confColor }}>
            {Math.round(summary.confidence * 100)}% confidence
          </div>
        </button>

        <button className="overview-tile" onClick={() => onOpenTool('fileforensics')}>
          <div className="overview-tile-label">INTEGRITY</div>
          <div className="overview-tile-value" style={{ color: integColor }}>{summary.integrity}</div>
          <div className="overview-tile-sub">{result.exif_missing ? 'EXIF stripped' : 'EXIF present'}{screenshotLikely ? ' · screenshot' : ''}</div>
        </button>

        <button className="overview-tile" onClick={() => onOpenTool('provenance')}>
          <div className="overview-tile-label">PROVENANCE</div>
          <div className="overview-tile-value" style={{ color: provColor }}>{summary.provenance}</div>
          <div className="overview-tile-sub">C2PA status</div>
        </button>

        <button className="overview-tile" onClick={() => onOpenTool('provenance')}>
          <div className="overview-tile-label">CONTRADICTIONS</div>
          <div className="overview-tile-value" style={{ color: summary.contradictions > 0 ? '#F59E0B' : '#22C55E' }}>
            {summary.contradictions} detected
          </div>
          <div className="overview-tile-sub">cross-layer findings</div>
        </button>

        <button className="overview-tile" onClick={() => onOpenTool('vision')}>
          <div className="overview-tile-label">EVIDENCE</div>
          <div className="overview-tile-value">{summary.evidence_count} observations</div>
          <div className="overview-tile-sub">visual + OCR</div>
        </button>

        <button className="overview-tile" onClick={() => onOpenTool('discovery')}>
          <div className="overview-tile-label">SOURCES</div>
          <div className="overview-tile-value">{summary.sources_discovered} discovered</div>
          <div className="overview-tile-sub">{result.source_discovery?.state === 'UNAVAILABLE' ? 'not configured' : 'web matches'}</div>
        </button>
      </div>

      <div className="overview-sections">
        <div className="overview-section overview-known">
          <div className="overview-section-title">WHAT WE KNOW</div>
          {summary.known.length ? summary.known.map((k, i) => (
            <div key={i} className="overview-item overview-item-known"><Check className="w-3.5 h-3.5" /> {k}</div>
          )) : <div className="overview-item-muted">No confirmed facts yet</div>}
        </div>

        <div className="overview-section overview-unknown">
          <div className="overview-section-title">WHAT WE DON'T KNOW</div>
          {summary.unknown.length ? summary.unknown.map((k, i) => (
            <div key={i} className="overview-item overview-item-unknown"><HelpCircle className="w-3.5 h-3.5" /> {k}</div>
          )) : <div className="overview-item-muted">No gaps identified</div>}
        </div>

        <div className="overview-section overview-suspicious">
          <div className="overview-section-title">WHAT LOOKS SUSPICIOUS</div>
          {summary.suspicious.length ? summary.suspicious.map((k, i) => (
            <div key={i} className="overview-item overview-item-suspicious"><AlertTriangle className="w-3.5 h-3.5" /> {k}</div>
          )) : <div className="overview-item-muted">No anomalies detected</div>}
        </div>

        <div className="overview-section overview-next">
          <div className="overview-section-title">INVESTIGATE NEXT</div>
          {summary.next_steps.length === 0 && <div className="overview-item-muted">No further steps recommended</div>}
          {summary.next_steps.map((k, i) => (
            <div key={i} className="overview-next-row">
              <span className="overview-item overview-item-next"><ArrowRight className="w-3.5 h-3.5" /> {k.action}</span>
              <button
                className="investigate-next-btn"
                onClick={() => onInvestigateNext?.(k)}
                title={k.reason}
              >
                <PlayCircle className="w-3.5 h-3.5" /> Investigate
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
