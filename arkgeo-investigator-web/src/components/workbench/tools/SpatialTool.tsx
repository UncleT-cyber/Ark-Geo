/**
 * SpatialTool — Map & Spatial Canvas view.
 *
 * Reuses the existing MapWorkspace component with the Leaflet satellite map,
 * confidence radius circles, and geofence support.  Also shows the
 * geolocation fusion explainability panel (WHY? reasoning).
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
          {coords ? (
            <MapWorkspace
              points={mapPoints}
              history={[]}
              onCopyCoords={onCopyCoords}
              onGeofenceViolation={onGeofenceViolation}
            />
          ) : (
            <div className="tool-empty">
              <div className="tool-empty-icon"><MapPin className="w-8 h-8" /></div>
              <div className="tool-empty-title">No Coordinates</div>
              <div className="tool-empty-text">
                {result.message || 'This image has no GPS coordinates. EXIF metadata is missing and no AI vision keys are configured.'}
              </div>
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
      </div>
    </div>
  );
}
