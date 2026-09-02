/**
 * SpatialTool — Map & Spatial Canvas view.
 *
 * The map is the spatial workspace and NEVER disappears. If coordinates
 * were found, the marker + confidence radius + fusion panel are shown.
 * If no location was established, the map stays visible with a clear
 * "Location Not Established" overlay — it is not hidden simply because
 * GPS or AI geolocation is unavailable.
 *
 * Reuses the existing MapWorkspace component (Leaflet multi-provider
 * satellite map, confidence radius circles, geofence support) and the
 * geolocation fusion explainability panel (WHY? reasoning). When
 * coordinates exist, a ground-truth Street View side-panel cross-examines
 * the established location against real world imagery from the backend
 * `fetch_streetview_panorama` payload.
 */
import React, { useState } from 'react';
import { MapPin } from 'lucide-react';
import { MapWorkspace } from '../../MapWorkspace/MapWorkspace';
import type { AnalyzeResponse } from '../../../types';

interface SpatialToolProps {
  result: AnalyzeResponse;
  thumbnailUrl?: string;
  onCopyCoords: () => void;
  onGeofenceViolation: (point: { lat: number; lon: number }) => void;
}

interface StreetViewPayload {
  state?: string;
  status?: string;
  pano_id?: string | null;
  date?: string | null;
  image_url?: string | null;
  heading?: number | null;
  detail?: string;
}

function StreetViewPanel({ result }: { result: AnalyzeResponse }) {
  const sv = result.streetview as StreetViewPayload | null | undefined;
  const [imgFailed, setImgFailed] = useState(false);

  if (!sv || sv.state !== 'AVAILABLE' || !sv.image_url) {
    const reason =
      sv?.state === 'NO_PANORAMA'
        ? sv.detail || 'No Street View panorama exists for these coordinates.'
        : sv?.detail || 'Street View ground-truth is unavailable for these coordinates.';
    return (
      <div className="tool-side-panel sv-panel">
        <div className="tool-panel-title">GROUND-TRUTH — STREET VIEW</div>
        <div className="sv-unavailable">
          <div className="sv-unavailable-icon"><MapPin className="w-4 h-4" /></div>
          <div className="sv-unavailable-title">
            {sv?.state === 'NO_PANORAMA' ? 'No Panorama at Location' : 'Street View Unavailable'}
          </div>
          <div className="sv-unavailable-text">{reason}</div>
          {(!sv || sv.state === 'UNAVAILABLE') && (
            <div className="sv-unavailable-hint">
              Configure a Google Maps API key (Admin Console) to enable ground-truth
              panorama imagery for established coordinates.
            </div>
          )}
        </div>
      </div>
    );
  }

  const panoUrl = sv.pano_id
    ? `https://www.google.com/maps/@?api=1&map_action=pano&pano=${encodeURIComponent(sv.pano_id)}`
    : null;

  return (
    <div className="tool-side-panel sv-panel">
      <div className="tool-panel-title">GROUND-TRUTH — STREET VIEW</div>
      <div className="sv-image-wrap">
        {imgFailed ? (
          <div className="sv-image-fallback">
            <div className="sv-unavailable-title">Panorama image failed to load</div>
            <div className="sv-unavailable-text">
              The Street View static image could not be rendered. Verify the Google Maps key has
              Street View Static enabled.
            </div>
          </div>
        ) : (
          <img
            src={sv.image_url}
            alt="Google Street View panorama"
            className="sv-image"
            onError={() => setImgFailed(true)}
          />
        )}
      </div>
      <div className="sv-meta">
        {sv.pano_id && (
          <div className="sv-meta-row">
            <span className="sv-meta-label">PANO ID</span>
            <span className="sv-meta-value mono">{sv.pano_id}</span>
          </div>
        )}
        {sv.date && (
          <div className="sv-meta-row">
            <span className="sv-meta-label">CAPTURE DATE</span>
            <span className="sv-meta-value mono">{sv.date}</span>
          </div>
        )}
        {typeof sv.heading === 'number' && (
          <div className="sv-meta-row">
            <span className="sv-meta-label">HEADING</span>
            <span className="sv-meta-value mono">{sv.heading}°</span>
          </div>
        )}
      </div>
      {panoUrl && (
        <a
          className="sv-open-link"
          href={panoUrl}
          target="_blank"
          rel="noopener noreferrer"
        >
          OPEN IN STREET VIEW →
        </a>
      )}
    </div>
  );
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

  const candidatePoints = (result.geo_candidates || [])
    .filter((c) => c && c.matched)
    .map((c) => ({
      lat: c.lat,
      lon: c.lon,
      radius: 500,
      confidence: 0.35,
      source: c.source || 'OCR_GEOCODE',
      label: c.query,
    }));

  return (
    <div className="tool-view tool-spatial">
      <div className="tool-split">
        <div className="tool-map-area">
          {/* The map is always rendered — it is the spatial workspace. */}
          <MapWorkspace
            points={mapPoints}
            history={[]}
            candidatePoints={candidatePoints}
            onCopyCoords={onCopyCoords}
            onGeofenceViolation={onGeofenceViolation}
          />
          {!coords && result.geo_candidates && result.geo_candidates.length > 0 && (
            <div className="map-location-banner map-location-banner-candidate">
              <span className="map-location-banner-dot" />
              <span className="map-location-banner-text">
                {result.geo_candidates.length} OCR candidate pin(s) — text-matched locations (not confirmed)
              </span>
            </div>
          )}
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

        {coords && (
          <div className="tool-side-col">
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
            {!fusion && (
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

            <StreetViewPanel result={result} />
          </div>
        )}
      </div>
    </div>
  );
}
