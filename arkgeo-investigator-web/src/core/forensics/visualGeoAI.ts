/**
 * STEP 4 — Multi-modal visual geolocation & landmark analysis.
 *
 * When a GeoSpy / multimodal vision provider is configured, the backend has
 * already run it during analysis; this step correlates those results
 * (coordinates + physical-environment features) into observations.
 *
 * When NO provider is configured, it falls back to local visual feature
 * tagging computed in the browser: lighting, sky presence, horizon detection,
 * and dominant color palette. These are clearly labelled heuristic estimates
 * (ai_hypothesis / tool_inference, low confidence) — never fabricated coords.
 */
import type { AnalyzeResponse } from '../../types';
import type { VisualFeature, VisualGeoResult } from '../types';
import { readPixels } from './imageLoader';

export interface VisualGeoInput {
  analysisCanvas: HTMLCanvasElement;
  backendResult: AnalyzeResponse;
  providersConfigured: boolean;
}

/** Correlate server-side AI geolocation + scene evidence when configured. */
export function collectServerVisualGeo(backend: AnalyzeResponse): {
  coordinates: { lat: number; lon: number; confidence: number } | null;
  features: VisualFeature[];
  hypothesis: { lat: number; lon: number; confidence: number } | null;
  scene: string;
} | null {
  const ai = (backend.ai_evidence || {}) as Record<string, unknown>;
  const geospy = ai.geospy as Record<string, unknown> | null | undefined;
  const scene = ai.scene as Record<string, unknown> | null | undefined;
  if (!geospy && !scene && !backend.geolocation_fusion) return null;

  const features: VisualFeature[] = [];

  const coords =
    geospy && typeof geospy.estimated_latitude === 'number' && typeof geospy.estimated_longitude === 'number'
      ? {
          lat: geospy.estimated_latitude as number,
          lon: geospy.estimated_longitude as number,
          confidence: (geospy.confidence_score as number) ?? 0.5,
        }
      : null;

  const tags = Array.isArray(scene?.evidence_tags) ? (scene.evidence_tags as Record<string, unknown>[]) : [];
  tags.forEach((t) => {
    features.push({
      kind: 'scene',
      label: String(t.label || t.category || 'visual clue'),
      value: String(t.label || ''),
      confidence: typeof t.confidence === 'number' ? t.confidence : 0.5,
    });
  });

  const desc = scene?.scene_description as string | undefined;
  if (desc) {
    features.push({ kind: 'scene', label: 'Scene description', value: desc, confidence: 0.8 });
  }

  const fusion = backend.geolocation_fusion;
  const hypothesis =
    fusion?.hypothesis && typeof fusion.hypothesis.lat === 'number' && typeof fusion.hypothesis.lon === 'number'
      ? { lat: fusion.hypothesis.lat, lon: fusion.hypothesis.lon, confidence: fusion.confidence }
      : null;

  return {
    coordinates: coords,
    features,
    hypothesis,
    scene: desc || '',
  };
}

/** Local pixel-analysis fallback — brightness / sky / horizon / palette. */
export function analyzeLocalVisuals(canvas: HTMLCanvasElement): VisualFeature[] {
  const data = readPixels(canvas);
  const features: VisualFeature[] = [];
  if (!data || canvas.width === 0 || canvas.height === 0) {
    features.push({ kind: 'lighting', label: 'Lighting', value: 'undetermined', confidence: 0.1 });
    return features;
  }

  const { width, height, data: px } = data;
  const n = width * height;
  const upperThird = Math.floor(height / 3);

  let lumSum = 0;
  let skyCount = 0;
  let upperBlueDominant = 0;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      const r = px[i], g = px[i + 1], b = px[i + 2];
      lumSum += 0.299 * r + 0.587 * g + 0.114 * b;
      if (y < upperThird) {
        if (b > r + 10 && b > 110) {
          skyCount += 1;
          if (b > r) upperBlueDominant += 1;
        }
      }
    }
  }
  const meanLum = lumSum / n;
  const skyRatio = upperThird > 0 ? skyCount / (width * upperThird) : 0;

  // Lighting heuristic.
  const lighting =
    meanLum > 150 ? 'bright / daylight conditions' : meanLum > 90 ? 'medium ambient light' : 'low-light conditions';
  features.push({
    kind: 'lighting',
    label: 'Lighting',
    value: lighting,
    confidence: 0.5,
  });

  // Sky presence (blue-dominant upper region).
  const skyConfidence = Math.min(0.7, skyRatio * 1.6 + 0.15);
  if (skyRatio > 0.25) {
    features.push({
      kind: 'sky',
      label: 'Open sky (blue-dominant)',
      value: `Sky visible in ${Math.round(skyRatio * 100)}% of upper frame`,
      confidence: skyConfidence,
    });
  } else {
    features.push({
      kind: 'sky',
      label: 'No clear sky region',
      value: 'Upper frame lacks blue-dominant sky — consistent with indoor or overcast capture',
      confidence: 0.45,
    });
  }

  // Horizon detection: strongest horizontal luminance discontinuity in the
  // upper 15%..60% of the frame.
  const horizon = detectHorizon(data);
  if (horizon) {
    features.push({
      kind: 'horizon',
      label: 'Horizon detected',
      value: `Horizontal transition at ${Math.round(horizon.ratio * 100)}% frame height (${horizon.gap.toFixed(0)} lum gap)`,
      confidence: 0.55,
    });
  }

  // Dominant color palette.
  const palette = dominantPalette(data, 3);
  features.push({
    kind: 'palette',
    label: 'Dominant colors',
    value: palette.map((p) => `#${p.hex}`).join(', '),
    confidence: 0.6,
  });

  // Scene estimate combining the heuristics above.
  if (skyRatio > 0.25 && horizon) {
    features.push({
      kind: 'scene',
      label: 'Scene estimate',
      value: 'Open-air scene (sky + horizon) — outdoor landscape or urban setting',
      confidence: 0.5,
    });
  } else if (meanLum < 90 && skyRatio < 0.15) {
    features.push({
      kind: 'scene',
      label: 'Scene estimate',
      value: 'Low light without sky — possibly indoor',
      confidence: 0.4,
    });
  } else {
    features.push({
      kind: 'scene',
      label: 'Scene estimate',
      value: 'Ambiguous — no decisive sky/horizon or low-light signature',
      confidence: 0.3,
    });
  }

  return features;
}

function detectHorizon(data: ImageData): { ratio: number; gap: number } | null {
  const { width, height, data: px } = data;
  const yStart = Math.floor(height * 0.15);
  const yEnd = Math.floor(height * 0.6);
  if (yEnd - yStart < 3) return null;

  const rowLum: number[] = [];
  for (let y = 0; y < height; y++) {
    let s = 0;
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      s += 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2];
    }
    rowLum.push(s / width);
  }

  let best = 0;
  let bestGap = -1;
  for (let y = yStart; y < yEnd; y++) {
    const gap = Math.abs(rowLum[y] - rowLum[y + 1]);
    if (gap > bestGap) {
      bestGap = gap;
      best = y;
    }
  }
  if (bestGap < 40) return null;
  return { ratio: best / height, gap: bestGap };
}

function dominantPalette(data: ImageData, count: number): { hex: string; share: number }[] {
  const { width, height, data: px } = data;
  const buckets = new Map<number, number>();
  for (let i = 0; i < width * height; i++) {
    const p = i * 4;
    const r = px[p] >> 4;
    const g = px[p + 1] >> 4;
    const b = px[p + 2] >> 4;
    const key = (r << 8) | (g << 4) | b;
    buckets.set(key, (buckets.get(key) || 0) + 1);
  }
  const total = width * height;
  return Array.from(buckets.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, count)
    .map(([key, cnt]) => {
      const r = ((key >> 8) & 0xf) * 16 + 8;
      const g = ((key >> 4) & 0xf) * 16 + 8;
      const b = (key & 0xf) * 16 + 8;
      return { hex: ((r << 16) | (g << 8) | b).toString(16).padStart(6, '0'), share: cnt / total };
    });
}

/** Run Step 4 — visual geolocation (server AI or local fallback). */
export async function runVisualGeo(input: VisualGeoInput): Promise<VisualGeoResult> {
  if (input.providersConfigured) {
    const server = collectServerVisualGeo(input.backendResult);
    if (server) {
      return {
        providersConfigured: true,
        coordinates: server.coordinates,
        features: server.features,
        geohypothesis: server.hypothesis,
        note: 'Visual geolocation from configured AI providers.',
      };
    }
  }

  const features = analyzeLocalVisuals(input.analysisCanvas);
  return {
    providersConfigured: input.providersConfigured,
    coordinates: null,
    features,
    geohypothesis: null,
    note: input.providersConfigured
      ? 'AI providers configured but returned no geolocation — local feature analysis shown.'
      : 'No AI vision providers configured — local heuristic feature analysis shown (low confidence).',
  };
}
