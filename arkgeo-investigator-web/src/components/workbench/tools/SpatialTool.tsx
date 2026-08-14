/**
 * SpatialTool — Map & Spatial Canvas view.
 *
 * The map is the spatial workspace and NEVER disappears. If coordinates
 * were found, the marker + confidence radius + fusion panel are shown.
 * If no location was established, the map stays visible with a clear
 * "Location Not Established" overlay — it is not hidden simply because
 * GPS or AI geolocation is unavailable.
 *
 * Reuses the existing MapWorkspace component (Leaflet satellite map,
 * confidence radius circles, geofence support) and the geolocation
 * fusion explainability panel (WHY? reasoning).
 */
import React from 'react';
import { MapPin } from 'lucide-react';
import { MapWorkspace } from '../../MapWorkspace/MapWorkspace';
import type { AnalyzeResponse } from '../../../types';

interface SpatialToolProps {
  result: AnalyzeResponse;
  thumbnailUrl?: string;
  onCopyCoords: () => void;
  onGeofenceViolation: (point: { lat: number; lon: number }) => void;
}

export function SpatialTool({ result, thumbnailUrl, onCopyCoords, onGeofenceViolation }: SpatialToolProps) {
  const coords = result.coordinates;
  const fusion = result.geolocation_fusion;

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
    <div className="tool-view tool-spatial">
      <div className="tool-split">
        <div className="tool-map-area">
          {/* The map is always rendered — it is the spatial workspace. */}
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
                <div className="location-not-established-text">
                  {result.message || 'This image has no GPS coordinates. EXIF metadata is missing and no AI vision keys are configured to infer a location.'}
                </div>
                <div className="location-not-established-hint">
                  The spatial workspace remains available. Configure a vision provider
                  (Admin Console) or ingest an image with intact EXIF to establish a location.
                </div>
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

        {fusion && (
          <div className="tool-side-panel">
            <div className="tool-panel-title">GEOLOCATION FUSION — WHY?</div>
            <div className="fusion-hypothesis">
              <div className="fusion-location">{fusion.primary_location || 'Unknown'}</div>
              <div className="fusion-confidence" style={{ color: fusion.confidence >= 0.6 ? '#22C55E' : '#F59E0B' }}>
                {Math.round(fusion.confidence * 100)}% confidence
              </div>
            </div>
            <div className="fusion-detail">
              <div className="fusion-question">{fusion.detail.question}</div>
              <div className="fusion-section">
                <div className="fusion-section-label">SUPPORTING ({fusion.supporting.length})</div>
                {fusion.supporting.length === 0 ? (
                  <div className="fusion-item-muted">No supporting evidence</div>
                ) : fusion.supporting.map((e, i) => (
                  <div key={i} className="fusion-item fusion-item-support">+ {e.layer} → {e.label}</div>
                ))}
              </div>
              <div className="fusion-section">
                <div className="fusion-section-label">AGAINST ({fusion.contradicting.length})</div>
                {fusion.contradicting.length === 0 ? (
                  <div className="fusion-item-muted">No contradicting evidence</div>
                ) : fusion.contradicting.map((e, i) => (
                  <div key={i} className="fusion-item fusion-item-against">- {e.label}</div>
                ))}
              </div>
              <div className="fusion-meta">
                <div>Independent evidence classes: <strong>{fusion.independent_evidence_classes}</strong></div>
                <div className="fusion-note">{fusion.detail.note}</div>
              </div>
            </div>
          </div>
        )}
        {!fusion && coords && (
          <div className="tool-side-panel">
            <div className="tool-panel-title">SPATIAL SUMMARY</div>
            <div className="fusion-hypothesis">
              <div className="fusion-location">{result.address?.display_name || result.consensus.primary_country || 'Location'}</div>
              <div className="fusion-confidence" style={{ color: result.consensus.confidence_score >= 0.6 ? '#22C55E' : '#F59E0B' }}>
                {Math.round(result.consensus.confidence_score * 100)}% confidence
              </div>
            </div>
            <div className="fusion-detail">
              <div className="fusion-section">
                <div className="fusion-section-label">SOURCE TIER</div>
                <div className="fusion-item">{result.source} ({result.consensus.tier_used})</div>
              </div>
              <div className="fusion-section">
                <div className="fusion-section-label">SEARCH RADIUS</div>
                <div className="fusion-item">{Math.round(result.consensus.search_radius_meters)} m</div>
              </div>
              <div className="fusion-section">
                <div className="fusion-section-label">COORDINATES</div>
                <div className="fusion-item mono">{coords.lat.toFixed(5)}°, {coords.lon.toFixed(5)}°</div>
              </div>
              {result.consensus.visual_evidence_tags && result.consensus.visual_evidence_tags.length > 0 && (
                <div className="fusion-section">
                  <div className="fusion-section-label">GEOGRAPHIC EVIDENCE</div>
                  {result.consensus.visual_evidence_tags.map((t, i) => (
                    <div key={i} className="fusion-item">{t.label}</div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
