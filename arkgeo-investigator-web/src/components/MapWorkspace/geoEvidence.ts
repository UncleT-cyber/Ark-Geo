/**
 * C.3 — Geolocation evidence classification (no fabrication on the map).
 *
 * A pin on the map must never imply more certainty than the backend actually
 * reported. This module classifies every plotted point as either VERIFIED
 * (deterministic: device GPS from EXIF, or corroborating carrier telemetry) or
 * INFERRED (a model estimate: vision ensemble, geocoded OCR/IMINT candidates).
 *
 * Pure and dependency-free so it is unit-testable and usable from both the
 * spatial tool and the map renderer. The classification drives marker styling,
 * the "verified vs hypothesis" legend and the popup copy.
 */

export type GeoEvidenceKind = 'verified' | 'inferred';

export interface GeoEvidenceClassification {
  kind: GeoEvidenceKind;
  /** Human label for the legend / popup header. */
  label: string;
  /** One-line explanation of where the point came from. */
  basis: string;
}

/** Backend `source` values that are deterministic observations, not guesses. */
const _VERIFIED_SOURCES: Record<string, GeoEvidenceClassification> = {
  NATIVE_EXIF_HARDWARE: {
    kind: 'verified',
    label: 'DEVICE GPS',
    basis: 'Read directly from image EXIF hardware tags — not an estimate.',
  },
  TELEMETRY: {
    kind: 'verified',
    label: 'NETWORK TELEMETRY',
    basis: 'Derived from carrier/network telemetry — an observed signal.',
  },
};

/**
 * Classify a primary map point from the backend `source` and `tier_used`.
 * Unknown sources are treated as INFERRED — never silently promoted to
 * verified, because an unrecognised provenance cannot be asserted as fact.
 */
export function classifyGeoEvidence(
  source: string | undefined | null,
  tierUsed?: string | null,
): GeoEvidenceClassification {
  const key = (source ?? '').toUpperCase();
  const known = _VERIFIED_SOURCES[key];
  if (known) return known;

  const tier = (tierUsed ?? '').toLowerCase();
  if (tier === 'metadata' || tier === 'telemetry') {
    return {
      kind: 'verified',
      label: tier === 'metadata' ? 'DEVICE GPS' : 'NETWORK TELEMETRY',
      basis: 'Deterministic pipeline tier (metadata/telemetry).',
    };
  }

  return {
    kind: 'inferred',
    label: 'INFERRED LOCATION',
    basis: 'Model / geocoder estimate — a hypothesis, not a confirmed fix.',
  };
}

/** A reverse-geocoded OCR / IMINT candidate is always a hypothesis. */
export function classifyCandidateEvidence(): GeoEvidenceClassification {
  return {
    kind: 'inferred',
    label: 'CANDIDATE',
    basis: 'Reverse-geocoded text or visual match — unconfirmed candidate.',
  };
}

/** Compact legend summary for the map HUD. */
export function geoEvidenceLegend(): { kind: GeoEvidenceKind; label: string; detail: string }[] {
  return [
    { kind: 'verified', label: 'Verified fix', detail: 'Device GPS / telemetry — observed, not inferred.' },
    { kind: 'inferred', label: 'Inferred location', detail: 'Model or geocoder estimate — treat as a hypothesis.' },
  ];
}
