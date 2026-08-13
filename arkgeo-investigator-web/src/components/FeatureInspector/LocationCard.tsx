/**
 * LocationCard — [CARD 1: LOCATION & COORDINATES]
 *
 * Prominent lat/lon display with N/S/E/W suffix, reverse-geocoded address
 * string, and a color-coded confidence progress bar.
 */
import React from 'react';
import type { AddressInfo, Coordinates } from '../../types';

interface Props {
  coordinates: Coordinates;
  address: AddressInfo | null;
  confidence: number;
  searchRadiusMeters: number;
}

function formatCoord(value: number, pos: string, neg: string): string {
  const suffix = value >= 0 ? pos : neg;
  return `${Math.abs(value).toFixed(4)}° ${suffix}`;
}

function confidenceColor(conf: number): string {
  if (conf >= 0.8) return '#22C55E';
  if (conf >= 0.5) return '#F59E0B';
  return '#EF4444';
}

export function LocationCard({ coordinates, address, confidence, searchRadiusMeters }: Props) {
  const pct = Math.round(confidence * 100);
  const color = confidenceColor(confidence);

  return (
    <div className="panel-section location-card">
      <div className="panel-title">LOCATION &amp; COORDINATES</div>

      {/* Coordinates */}
      <div className="coord-display">
        <span className="coord-value mono" style={{ color }}>
          {formatCoord(coordinates.lat, 'N', 'S')}
        </span>
        <span className="coord-sep">·</span>
        <span className="coord-value mono" style={{ color }}>
          {formatCoord(coordinates.lon, 'E', 'W')}
        </span>
      </div>

      {/* Reverse geocode address */}
      {address?.display_name ? (
        <div className="location-address">{address.display_name}</div>
      ) : (
        <div className="location-address location-address-muted">
          No reverse geocode available
        </div>
      )}

      {/* Confidence bar */}
      <div className="confidence-bar-container">
        <div className="confidence-bar-header">
          <span className="confidence-bar-label">CONFIDENCE</span>
          <span className="confidence-bar-pct mono" style={{ color }}>
            {pct}%
          </span>
        </div>
        <div className="confidence-bar-track">
          <div
            className="confidence-bar-fill"
            style={{ width: `${pct}%`, backgroundColor: color, boxShadow: `0 0 8px ${color}66` }}
          />
        </div>
        <div className="confidence-bar-detail mono">
          Search radius: {searchRadiusMeters >= 1000
            ? `${(searchRadiusMeters / 1000).toFixed(1)} km`
            : `${Math.round(searchRadiusMeters)} m`}
        </div>
      </div>
    </div>
  );
}
