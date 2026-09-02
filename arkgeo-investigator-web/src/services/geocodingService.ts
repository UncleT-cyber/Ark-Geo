/**
 * geocodingService — active OCR → geocoding (Feature 2).
 *
 * Takes location-relevant text extracted from an image (street names, place
 * names, landmark tokens) and resolves each string to candidate coordinates
 * via the backend `/maps/geocode/batch` proxy (Google → keyless Nominatim
 * fallback, cached server-side).  Candidate pins are then plotted on the
 * spatial canvas by SpatialTool.
 *
 * The pipeline geocodes automatically on every upload; unmatched queries are
 * dropped — candidate coordinates are never fabricated.
 */
import { api } from '../api';
import type { GeoCandidate } from '../types';
import type { OcrTelemetry } from '../core/types';

const MAX_QUERIES = 8;

/**
 * Search a single text string for candidate coordinates.
 * Returns null when the backend cannot geocode it.
 */
export async function search(text: string): Promise<GeoCandidate | null> {
  const candidates = await searchMany([text]);
  return candidates[0] ?? null;
}

/**
 * Search many text strings; returns only matched candidates.
 */
export async function searchMany(texts: string[]): Promise<GeoCandidate[]> {
  const queries = Array.from(
    new Set(
      (texts || [])
        .map((t) => (t || '').trim())
        .filter((t) => t.length >= 3),
    ),
  ).slice(0, MAX_QUERIES);

  if (queries.length === 0) return [];

  const res = await api.geocodeBatch(queries);
  if (!res.ok) return [];
  return (res.candidates || []).filter((c) => c && c.matched);
}

/** Build geocode queries from the location-relevant OCR output. */
export function queriesFromOcr(ocr: OcrTelemetry): string[] {
  const queries: string[] = [];
  const push = (q: string) => {
    const v = (q || '').trim();
    if (v && !queries.some((x) => x.toLowerCase() === v.toLowerCase())) {
      queries.push(v);
    }
  };
  (ocr.matches || []).forEach((m) => {
    if (m.kind === 'street' || m.kind === 'carrier') push(m.value);
  });
  // Proper-case multi-word fragments in the raw text are plausible place names.
  (ocr.text || '')
    .split(/\n|\./g)
    .map((line) => line.trim())
    .forEach((line) => {
      if (!line || line.length > 60) return;
      const words = line.split(/\s+/);
      if (
        words.length >= 1 &&
        words.length <= 4 &&
        words.every((w) => /^[A-Z][A-Za-z]+$/.test(w))
      ) {
        push(line);
      }
    });
  return queries;
}

/**
 * Geocode the location-relevant OCR text for an uploaded image.
 */
export async function geocodeFromOcr(ocr: OcrTelemetry): Promise<GeoCandidate[]> {
  if (!ocr || !ocr.text) return [];
  return searchMany(queriesFromOcr(ocr));
}
