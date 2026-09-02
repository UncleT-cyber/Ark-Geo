/**
 * LayerControl — multi-provider basemap switcher for the Leaflet spatial canvas.
 *
 * Providers (honest degradation when a required key is absent):
 *   Esri World Imagery        — always available
 *   Mapbox Satellite / Hybrid — requires VITE_MAPBOX_TOKEN (client env token)
 *   Google Satellite / Hybrid — requires Google Maps API key (streetview config)
 *   OpenStreetMap Vector      — always available (standard raster tiles via Leaflet)
 *
 * Every layer runs at maxNativeZoom:18 / maxZoom:22. When a tile request 404s,
 * installTileFallback replaces the broken tile with an upscaled parent tile from
 * the next lower zoom level (progressively descending) so the map never shows
 * grey "map data not available" placeholders.
 */
import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import { Layers, Lock } from 'lucide-react';
import { api } from '../../api';

export type MapTileProviderId =
  | 'esri'
  | 'mapbox-satellite'
  | 'mapbox-hybrid'
  | 'google-satellite'
  | 'google-hybrid'
  | 'osm';

export interface TileProviderDef {
  id: MapTileProviderId;
  name: string;
  group: 'satellite' | 'hybrid' | 'streets';
  requires?: 'mapbox' | 'google';
  hint: string;
  template: string;
  labelsTemplate?: string;
  attribution: string;
  maxZoom: number;
  maxNativeZoom: number;
}

export const TILE_PROVIDERS: TileProviderDef[] = [
  {
    id: 'esri',
    name: 'Esri World Imagery',
    group: 'satellite',
    hint: 'Global satellite imagery, no key required.',
    template: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    labelsTemplate: 'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles © Esri',
    maxZoom: 22,
    maxNativeZoom: 18,
  },
  {
    id: 'mapbox-satellite',
    name: 'Mapbox High-Res Satellite',
    group: 'satellite',
    requires: 'mapbox',
    hint: 'Mapbox satellite-v9 high-resolution imagery.',
    template: 'https://api.mapbox.com/v4/mapbox.satellite-v9/{z}/{x}/{y}.jpg90?access_token={token}',
    attribution: '© Mapbox © OpenStreetMap',
    maxZoom: 22,
    maxNativeZoom: 18,
  },
  {
    id: 'mapbox-hybrid',
    name: 'Mapbox Streets Hybrid',
    group: 'hybrid',
    requires: 'mapbox',
    hint: 'Mapbox satellite imagery with road + place-name overlay.',
    template: 'https://api.mapbox.com/v4/mapbox.streets-satellite-v9/{z}/{x}/{y}.jpg90?access_token={token}',
    attribution: '© Mapbox © OpenStreetMap',
    maxZoom: 22,
    maxNativeZoom: 18,
  },
  {
    id: 'google-satellite',
    name: 'Google Satellite',
    group: 'satellite',
    requires: 'google',
    hint: 'Google satellite imagery (Map Tiles API).',
    template: '/api/v1/maps/tile/{z}/{x}/{y}?map_type=satellite',
    attribution: '© Google',
    maxZoom: 22,
    maxNativeZoom: 18,
  },
  {
    id: 'google-hybrid',
    name: 'Google Hybrid',
    group: 'hybrid',
    requires: 'google',
    hint: 'Google satellite imagery with labels + roads.',
    template: '/api/v1/maps/tile/{z}/{x}/{y}?map_type=hybrid',
    attribution: '© Google',
    maxZoom: 22,
    maxNativeZoom: 18,
  },
  {
    id: 'osm',
    name: 'OpenStreetMap Vector',
    group: 'streets',
    hint: 'Standard OpenStreetMap street map (vector-styled, raster tiles via Leaflet).',
    template: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '© OpenStreetMap contributors',
    maxZoom: 22,
    maxNativeZoom: 18,
  },
];

export interface LayerControlOpts {
  mapboxToken?: string;
  googleConfigured?: boolean;
}

export function isProviderAvailable(def: TileProviderDef, opts: LayerControlOpts): boolean {
  if (def.requires === 'mapbox') return Boolean(opts.mapboxToken);
  if (def.requires === 'google') return Boolean(opts.googleConfigured);
  return true;
}

/** Concrete URL template for a provider with any token inlined. */
function urlTemplate(def: TileProviderDef, opts: LayerControlOpts): string {
  return def.template.replace('{token}', opts.mapboxToken ?? '');
}

/**
 * Replace a failed tile with an upscaled copy of its parent tile from the next
 * lower zoom (progressively descending) instead of leaving a grey placeholder.
 */
function installTileFallback(layer: L.TileLayer, template: string): L.TileLayer {
  layer.on('tileerror', (ev) => {
    const e = ev as L.LeafletEvent & {
      tile: HTMLImageElement;
      coords: { z: number; x: number; y: number };
    };
    const tile = e.tile;
    const coords = e.coords;
    if (!tile || !coords) return;

    tryLoad(coords.z, coords.x, coords.y, 0);

    function tryLoad(z: number, x: number, y: number, depth: number) {
      if (depth >= 4 || z <= 2) return;
      const nz = z - 1;
      const nx = Math.floor(x / 2);
      const ny = Math.floor(y / 2);
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => {
        const size = typeof layer.options.tileSize === 'number' ? layer.options.tileSize : 256;
        const canvas = document.createElement('canvas');
        canvas.width = size;
        canvas.height = size;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;
        ctx.imageSmoothingEnabled = true;
        ctx.drawImage(img, 0, 0, size, size);
        tile.src = canvas.toDataURL('image/png');
      };
      img.onerror = () => tryLoad(nz, nx, ny, depth + 1);
      img.src = L.Util.template(template, { z: nz, x: nx, y: ny, s: '1' });
    }
  });
  return layer;
}

function buildLayer(def: TileProviderDef, opts: LayerControlOpts): L.TileLayer | null {
  if (!isProviderAvailable(def, opts)) return null;
  const template = urlTemplate(def, opts);
  const options: L.TileLayerOptions = {
    attribution: def.attribution,
    maxZoom: def.maxZoom,
    maxNativeZoom: def.maxNativeZoom,
  };
  // Only set subdomains when the template actually uses {s}. Passing `undefined`
  // shadows Leaflet's default 'abc' and makes _getSubdomain throw on every tile.
  if (def.template.includes('{s}')) {
    options.subdomains = '0123';
  }
  const layer = L.tileLayer(template, options);
  return installTileFallback(layer, template);
}

function buildLabelsLayer(def: TileProviderDef, opts: LayerControlOpts): L.TileLayer | null {
  if (!def.labelsTemplate) return null;
  const template = def.labelsTemplate.replace('{token}', opts.mapboxToken ?? '');
  return L.tileLayer(template, {
    attribution: def.attribution,
    maxZoom: def.maxZoom,
    maxNativeZoom: def.maxNativeZoom,
    opacity: 0.6,
  });
}

interface LayerControlProps {
  map: L.Map | null;
  initial?: MapTileProviderId;
}

const GROUPS: { id: string; label: string; members: MapTileProviderId[] }[] = [
  { id: 'satellite', label: 'SATELLITE', members: ['esri', 'mapbox-satellite', 'google-satellite'] },
  { id: 'hybrid', label: 'HYBRID', members: ['mapbox-hybrid', 'google-hybrid'] },
  { id: 'streets', label: 'STREETS', members: ['osm'] },
];

export function LayerControl({ map, initial = 'esri' }: LayerControlProps) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<MapTileProviderId>(initial);
  const [googleConfigured, setGoogleConfigured] = useState(false);
  const [labelsOn, setLabelsOn] = useState(true);
  const baseRef = useRef<L.TileLayer | null>(null);
  const labelsRef = useRef<L.TileLayer | null>(null);

  const mapboxToken = (import.meta as any).env?.VITE_MAPBOX_TOKEN as string | undefined;

  useEffect(() => {
    let active = true;
    api
      .health()
      .then((h) => {
        if (active) setGoogleConfigured(h.services?.streetview === 'configured');
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  const opts: LayerControlOpts = { mapboxToken, googleConfigured };

  const selectedDef = TILE_PROVIDERS.find((p) => p.id === selected);

  // Apply the current selection to the live map whenever it changes.
  useEffect(() => {
    if (!map) return;
    const def = selectedDef;
    if (!def) return;
    if (!isProviderAvailable(def, opts)) {
      setSelected('esri');
      return;
    }

    if (baseRef.current) map.removeLayer(baseRef.current);
    baseRef.current = null;

    // A provider switch also clears any labels overlay from the previous layer
    // (labels only apply to satellite providers that ship them separately).
    if (labelsRef.current) {
      map.removeLayer(labelsRef.current);
      labelsRef.current = null;
    }

    const base = buildLayer(def, opts);
    if (!base) {
      setSelected('esri');
      return;
    }
    // Auto-fallback: if a keyed layer (Google) fails repeatedly — e.g. the GCP
    // project has billing disabled and every tile 502s — drop to OpenStreetMap
    // so the map never stays grey.
    if (def.requires === 'google') {
      let fails = 0;
      const onErr = () => {
        fails += 1;
        if (fails >= 4) {
          base.off('tileerror', onErr);
          setSelected('osm');
        }
      };
      base.on('tileerror', onErr);
    }
    base.addTo(map);
    baseRef.current = base;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, selected, mapboxToken, googleConfigured]);

  // Manage the optional place-name labels overlay (base layer untouched).
  useEffect(() => {
    if (!map) return;
    const def = selectedDef;
    if (!def || !def.labelsTemplate) return;

    if (!labelsRef.current) {
      const labels = buildLabelsLayer(def, opts);
      if (!labels) return;
      labelsRef.current = labels;
    }
    if (labelsOn) {
      if (!map.hasLayer(labelsRef.current)) labelsRef.current.addTo(map);
    } else if (map.hasLayer(labelsRef.current)) {
      map.removeLayer(labelsRef.current);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, selected, labelsOn, mapboxToken, googleConfigured]);

  return (
    <div className="arkgeo-layer-control">
      <button
        type="button"
        className="arkgeo-layer-control-toggle"
        onClick={() => setOpen(!open)}
        title="Basemap layers"
      >
        <Layers size={13} />
        <span>MAP LAYERS</span>
      </button>

      {open && (
        <div className="arkgeo-layer-control-panel">
          {GROUPS.map((g) => (
            <div key={g.id} className="arkgeo-layer-group">
              <div className="arkgeo-layer-group-label">{g.label}</div>
              {g.members.map((id) => {
                const def = TILE_PROVIDERS.find((p) => p.id === id);
                if (!def) return null;
                const available = isProviderAvailable(def, opts);
                const active = selected === id;
                return (
                  <button
                    key={id}
                    type="button"
                    disabled={!available}
                    className={active ? 'arkgeo-layer-item arkgeo-layer-item-active' : 'arkgeo-layer-item'}
                    title={available ? def.hint : `${def.hint} — key not configured`}
                    onClick={() => setSelected(id)}
                  >
                    <span>{def.name}</span>
                    {!available && (
                      <span className="arkgeo-layer-lock">
                        <Lock size={9} /> KEY
                      </span>
                    )}
                    {active && <span className="arkgeo-layer-dot" />}
                  </button>
                );
              })}
            </div>
          ))}

          {selectedDef?.labelsTemplate && (
            <label className="arkgeo-layer-labels">
              <input
                type="checkbox"
                checked={labelsOn}
                onChange={(e) => setLabelsOn(e.target.checked)}
              />
              Place-name labels
            </label>
          )}
        </div>
      )}
    </div>
  );
}
