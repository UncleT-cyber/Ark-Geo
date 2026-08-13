/**
 * MapWorkspace — Leaflet vector map with satellite overlay, reactive
 * flyTo animation, custom ARKGEO tactical markers, cyan uncertainty
 * circles, and historical trajectory lines.
 *
 * When new coordinates arrive the map performs an animated camera transition
 * (flyTo) with a zoom level chosen by the source tier:
 *   NATIVE_EXIF_HARDWARE → zoom 16
 *   AI_VISION            → zoom 12
 *   TELEMETRY            → zoom 8
 */
import React, { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

interface MapPoint {
  lat: number;
  lon: number;
  radius: number;
  confidence: number;
  source?: string;
  label?: string;
  thumbnailUrl?: string;
}

interface Props {
  points: MapPoint[];
  history?: MapPoint[];
  onCopyCoords?: () => void;
}

function zoomForSource(source?: string): number {
  switch (source) {
    case 'NATIVE_EXIF_HARDWARE':
      return 16;
    case 'AI_VISION':
      return 12;
    case 'TELEMETRY':
      return 8;
    default:
      return 14;
  }
}

function confidenceColor(conf: number): string {
  if (conf >= 0.7) return '#22C55E';
  if (conf >= 0.4) return '#F59E0B';
  return '#EF4444';
}

// Custom ARKGEO tactical marker — cyan diamond with dark border
function createTacticalMarker(
  lat: number,
  lon: number,
  color: string,
  thumbnailUrl?: string,
  onCopyCoords?: () => void,
): L.Marker {
  const thumbHtml = thumbnailUrl
    ? `<img src="${thumbnailUrl}" style="width:60px;height:60px;object-fit:cover;border-radius:4px;border:1px solid #38BDF8;" />`
    : `<div style="width:60px;height:60px;background:#0D1421;border-radius:4px;border:1px solid #334155;display:flex;align-items:center;justify-content:center;color:#64748B;font-size:24px;">📷</div>`;

  const popupHtml = `
    <div class="arkgeo-blueprint-popup" style="
      font-family: 'JetBrains Mono', monospace;
      min-width: 200px; padding: 0; overflow: hidden;
      background: #0B0F17; border: 1px solid #38BDF8; border-radius: 6px;
    ">
      <div style="
        background: #0D1421; padding: 6px 10px; border-bottom: 1px solid #1E293B;
        display: flex; align-items: center; gap: 8px;
      ">
        <div style="width:8px;height:8px;background:#38BDF8;border-radius:50%;box-shadow:0 0 6px #38BDF8;"></div>
        <span style="color:#38BDF8;font-size:11px;font-weight:700;letter-spacing:1px;">ARKGEO TARGET</span>
      </div>
      <div style="padding:10px;display:flex;gap:10px;align-items:flex-start;">
        ${thumbHtml}
        <div style="display:flex;flex-direction:column;gap:4px;">
          <div style="font-size:10px;color:#64748B;letter-spacing:1px;">COORDINATES</div>
          <div style="font-size:12px;color:#7DD3FC;font-weight:600;">
            ${lat.toFixed(5)}°, ${lon.toFixed(5)}°
          </div>
        </div>
      </div>
      <div style="padding:0 10px 10px;display:flex;flex-direction:column;gap:6px;">
        <button id="arkgeo-copy-coords" style="
          background:#0D1421;color:#38BDF8;border:1px solid #38BDF8;border-radius:4px;
          padding:6px 10px;font-size:11px;font-family:'JetBrains Mono',monospace;
          cursor:pointer;font-weight:600;transition:background 0.2s;
        ">⎘ COPY TARGET LAT/LONG</button>
        <a href="https://www.google.com/maps?q=${lat},${lon}" target="_blank" rel="noopener noreferrer" style="
          display:block;text-align:center;background:#0D1421;color:#F59E0B;
          border:1px solid #F59E0B;border-radius:4px;padding:6px 10px;font-size:11px;
          font-family:'JetBrains Mono',monospace;text-decoration:none;font-weight:600;
        ">🛰 OPEN IN SATELLITE →</a>
      </div>
    </div>`;

  const icon = L.divIcon({
    className: 'arkgeo-tactical-marker',
    html: `<div style="
      position: relative;
      width: 28px; height: 28px;
    ">
      <div style="
        position: absolute; top: 0; left: 0;
        width: 28px; height: 28px;
        background: ${color};
        border: 2px solid #0B0F17;
        border-radius: 50% 50% 50% 0;
        transform: rotate(-45deg);
        box-shadow: 0 0 12px ${color}99, 0 2px 6px rgba(0,0,0,0.6);
      "></div>
      <div style="
        position: absolute; top: 11px; left: 11px;
        width: 6px; height: 6px;
        background: #0B0F17;
        border-radius: 50%;
      "></div>
    </div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 28],
    popupAnchor: [0, -28],
  });
  const marker = L.marker([lat, lon], { icon });
  marker.bindPopup(popupHtml, { className: 'arkgeo-popup-wrapper', maxWidth: 300 });

  // Wire up the copy button after popup opens
  if (onCopyCoords) {
    marker.on('popupopen', () => {
      const btn = document.getElementById('arkgeo-copy-coords');
      if (btn) {
        btn.addEventListener('click', (e) => {
          e.preventDefault();
          onCopyCoords();
        });
      }
    });
  }

  return marker;
}

export function MapWorkspace({ points, history, onCopyCoords }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);
  const currentPointRef = useRef<MapPoint | null>(null);

  // Initialize map once
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, {
      center: [20, 0],
      zoom: 2,
      worldCopyJump: true,
      zoomControl: true,
      attributionControl: true,
    });

    // Satellite base layer
    L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      { attribution: 'Esri', maxZoom: 19 },
    ).addTo(map);

    // Labels overlay
    L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
      { maxZoom: 19, opacity: 0.6 },
    ).addTo(map);

    mapRef.current = map;
    layerRef.current = L.layerGroup().addTo(map);

    return () => {
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
    };
  }, []);

  // Reactive update — redraw layers + flyTo on new coordinates
  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!map || !layer) return;

    layer.clearLayers();
    if (points.length === 0) return;

    const activePoint = points[points.length - 1];
    currentPointRef.current = activePoint;

    // Draw uncertainty circle (cyan, semi-transparent)
    L.circle([activePoint.lat, activePoint.lon], {
      radius: activePoint.radius,
      color: '#38BDF8',
      fillColor: '#38BDF8',
      fillOpacity: 0.12,
      weight: 2,
      opacity: 0.7,
    }).addTo(layer);

    // Drop custom tactical marker
    const markerColor = confidenceColor(activePoint.confidence);
    const marker = createTacticalMarker(
      activePoint.lat,
      activePoint.lon,
      markerColor,
      activePoint.thumbnailUrl,
      onCopyCoords,
    );
    marker.addTo(layer);

    // Draw historical trajectory (dashed cyan)
    if (history && history.length > 1) {
      const latlngs = history.map((p) => [p.lat, p.lon]) as [number, number][];
      L.polyline(latlngs, {
        color: '#38BDF8',
        weight: 2,
        opacity: 0.5,
        dashArray: '6, 6',
      }).addTo(layer);

      // Small markers for historical points
      history.slice(0, -1).forEach((pt) => {
        L.circleMarker([pt.lat, pt.lon], {
          radius: 4,
          color: '#38BDF8',
          fillColor: '#0B0F17',
          fillOpacity: 1,
          weight: 2,
        }).addTo(layer);
      });
    }

    // Animated camera transition
    const targetZoom = zoomForSource(activePoint.source);
    map.flyTo([activePoint.lat, activePoint.lon], targetZoom, {
      animate: true,
      duration: 2.5,
      easeLinearity: 0.25,
    });
  }, [points, history, onCopyCoords]);

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: '100%', background: 'var(--bg-darkest)' }}
    />
  );
}
