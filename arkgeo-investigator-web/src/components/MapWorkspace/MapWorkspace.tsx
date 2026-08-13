/**
 * MapWorkspace — Leaflet vector map with satellite overlay, uncertainty
 * heatmaps, and historical trajectory lines.
 */
import React, { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import type { ConsensusResult } from '../../types';

interface MapPoint {
  lat: number;
  lon: number;
  radius: number;
  confidence: number;
  label?: string;
}

interface Props {
  points: MapPoint[];
  history?: MapPoint[];
}

// Fix default icon paths for bundlers
delete (L.Icon.Default.prototype as unknown as { _getIconUrl?: unknown })._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

export function MapWorkspace({ points, history }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, {
      center: [20, 0],
      zoom: 2,
      worldCopyJump: true,
    });

    // Satellite layer
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      attribution: 'Esri',
      maxZoom: 19,
    }).addTo(map);

    // Labels overlay
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19,
      opacity: 0.6,
    }).addTo(map);

    mapRef.current = map;
    layerRef.current = L.layerGroup().addTo(map);

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!layerRef.current || !mapRef.current) return;
    layerRef.current.clearLayers();

    if (points.length === 0) return;

    // Draw uncertainty circles (heatmap-like)
    points.forEach((pt) => {
      const color = pt.confidence >= 0.7 ? '#22C55E' : pt.confidence >= 0.4 ? '#F59E0B' : '#EF4444';

      L.circle([pt.lat, pt.lon], {
        radius: pt.radius,
        color,
        fillColor: color,
        fillOpacity: 0.15,
        weight: 2,
      }).addTo(layerRef.current!);

      L.marker([pt.lat, pt.lon])
        .bindPopup(pt.label || `Confidence: ${Math.round(pt.confidence * 100)}%`)
        .addTo(layerRef.current!);
    });

    // Draw historical trajectory
    if (history && history.length > 1) {
      const latlngs = history.map((p) => [p.lat, p.lon]) as [number, number][];
      L.polyline(latlngs, {
        color: '#38BDF8',
        weight: 2,
        opacity: 0.6,
        dashArray: '5, 5',
      }).addTo(layerRef.current!);
    }

    // Fit bounds
    const bounds = L.latLngBounds(points.map((p) => [p.lat, p.lon] as [number, number]));
    mapRef.current.fitBounds(bounds, { padding: [50, 50] });
  }, [points, history]);

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: '100%', background: 'var(--bg-darkest)' }}
    />
  );
}
