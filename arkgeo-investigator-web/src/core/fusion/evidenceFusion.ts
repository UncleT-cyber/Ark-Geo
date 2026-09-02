/**
 * STEP 5 — Evidence Fusion engine.
 *
 * Aggregates every step output plus the backend forensic result into one
 * defensible assessment:
 *   - corroborations / contradictions (cross-evidence correlation)
 *   - provenance timeline
 *   - location assessment (candidate + supporting + contradicting + status)
 *   - per-dimension verdicts (origin / location / camera / source / timeline /
 *     screenshot / metadata)
 *
 * Nothing is asserted beyond what the evidence supports; the default status
 * is REQUIRES_REVIEW / UNRESOLVED rather than a fabricated conclusion.
 */
import type { AnalyzeResponse } from '../../types';
import type {
  AssetClassification,
  EvidenceFusionResult,
  EvidenceVerdict,
  FusionItem,
  LocationAssessment,
  OcrTelemetry,
  SourceDiscoveryResult,
  VisualGeoResult,
} from '../types';

export interface EvidenceFusionInput {
  backend: AnalyzeResponse;
  classification: AssetClassification;
  sourceDiscovery: SourceDiscoveryResult;
  ocr: OcrTelemetry;
  visualGeo: VisualGeoResult;
}

/** Small E.164 country-code → country map for OCR phone telemetry. */
const COUNTRY_CODES: Record<string, string> = {
  '234': 'Nigeria',
  '233': 'Ghana',
  '254': 'Kenya',
  '255': 'Tanzania',
  '27': 'South Africa',
  '256': 'Uganda',
  '260': 'Zambia',
  '20': 'Egypt',
  '212': 'Morocco',
  '44': 'United Kingdom',
  '1': 'United States/Canada',
  '91': 'India',
  '55': 'Brazil',
  '49': 'Germany',
  '33': 'France',
  '2340': 'Nigeria',
};

const CARRIER_COUNTRIES: Record<string, string> = {
  MTN: 'Nigeria / South Africa / Uganda',
  Airtel: 'Nigeria / Kenya / Ghana',
  Glo: 'Nigeria',
  '9mobile': 'Nigeria',
  Safaricom: 'Kenya',
  Vodafone: 'Ghana / South Africa',
};

function countryFromPhone(value: string): string | null {
  const digits = value.replace(/\D/g, '');
  if (!digits) return null;
  const m = digits.match(/^(\d{1,3})/);
  if (!m) return null;
  const code = m[1];
  return COUNTRY_CODES[code] ?? COUNTRY_CODES[`${code}`] ?? null;
}

function backendLocationLabel(backend: AnalyzeResponse): string | null {
  return (
    backend.address?.display_name ||
    backend.address?.city ||
    backend.address?.country ||
    backend.consensus?.primary_country ||
    null
  );
}

/** Run Step 5 — evidence fusion. */
export function fuseEvidence(input: EvidenceFusionInput): EvidenceFusionResult {
  const { backend, classification, sourceDiscovery, ocr, visualGeo } = input;

  const corroborations: FusionItem[] = [];
  const contradictions: FusionItem[] = [];

  // --- Reuse the backend fusion explainability (supporting / against) ---
  const fusion = backend.geolocation_fusion;
  (fusion?.supporting || []).forEach((e) => {
    corroborations.push({ layer: e.layer, label: e.label, detail: 'Backend geolocation fusion', confidence: null });
  });
  (fusion?.contradicting || []).forEach((e) => {
    contradictions.push({ layer: e.layer, label: e.label, detail: 'Backend geolocation fusion', confidence: null });
  });

  // --- Backend structured contradictions ---
  (backend.contradictions || []).forEach((c) => {
    contradictions.push({
      layer: c.type || 'CONTRADICTION',
      label: c.what_conflicts,
      detail: c.evidence_sources?.join('; ') || 'Backend contradiction engine',
      confidence: null,
    });
  });

  // --- Location hypothesis contradicting layer (GPS-off cases) ---
  const locationHyp = (backend as unknown as {
    location_hypothesis?: { contradicting?: { layer: string; label: string }[] } | null;
  }).location_hypothesis;
  (locationHyp?.contradicting || []).forEach((c) => {
    contradictions.push({ layer: c.layer, label: c.label, detail: 'Location hypothesis', confidence: null });
  });

  // --- Visual geolocation corroboration (EXIF GPS vs AI geospy) ---
  if (backend.coordinates && visualGeo.coordinates) {
    corroborations.push({
      layer: 'visual_geolocation',
      label: 'AI geolocation returned coordinates consistent with EXIF',
      detail: `GeoSpy confidence ${Math.round(visualGeo.coordinates.confidence * 100)}%`,
      confidence: visualGeo.coordinates.confidence,
    });
  }

  // --- OCR geographic telemetry ---
  const ocrGeo: string[] = [];
  ocr.matches.forEach((m) => {
    if (m.kind === 'phone') {
      const country = countryFromPhone(m.value);
      if (country) {
        corroborations.push({
          layer: 'ocr',
          label: `Phone number dialing code → ${country}`,
          detail: m.value,
          confidence: 0.6,
        });
        ocrGeo.push(country);
      }
    }
    if (m.kind === 'carrier') {
      const country = CARRIER_COUNTRIES[m.value.toUpperCase()];
      if (country) {
        corroborations.push({
          layer: 'ocr',
          label: `Carrier "${m.value}" → ${country}`,
          detail: 'Mobile network operator in OCR text',
          confidence: 0.5,
        });
        ocrGeo.push(m.value);
      }
    }
    if (m.kind === 'street') {
      corroborations.push({
        layer: 'ocr',
        label: `Street reference: ${m.value}`,
        detail: 'Geographic text telemetry',
        confidence: 0.5,
      });
    }
  });

  // --- OCR region vs backend location conflict ---
  const backendLoc = backendLocationLabel(backend);
  if (ocrGeo.length > 0 && backendLoc) {
    const backendLower = backendLoc.toLowerCase();
    const regionHit = ocrGeo.some((r) => backendLower.includes(r.toLowerCase()));
    if (!regionHit) {
      contradictions.push({
        layer: 'ocr',
        label: 'OCR geographic signal not reflected in established location',
        detail: `OCR: ${ocrGeo.join(', ')} · Location: ${backendLoc}`,
        confidence: 0.4,
      });
    }
  }

  // --- Screenshot classification corroboration ---
  if (classification.classification === 'Likely Screenshot') {
    corroborations.push({
      layer: 'asset_classification',
      label: `Likely screenshot (${classification.platformProfile})`,
      detail: classification.reasons.slice(0, 3).join(' · '),
      confidence: classification.confidence,
    });
    if (!backend.exif_missing && backend.camera) {
      contradictions.push({
        layer: 'asset_classification',
        label: 'Screenshot-classified asset but camera EXIF present',
        detail: 'Camera metadata would be unexpected in a native screenshot',
        confidence: 0.3,
      });
    }
  } else if (classification.classification === 'Likely Exported/Messenger Asset') {
    corroborations.push({
      layer: 'asset_classification',
      label: `Messenger-exported asset (${classification.platformProfile})`,
      detail: `Received copy — original camera file was re-encoded; EXIF may have been stripped`,
      confidence: classification.confidence,
    });
  } else if (classification.classification === 'Likely Camera Photograph') {
    corroborations.push({
      layer: 'asset_classification',
      label: 'Likely camera photograph',
      detail: 'EXIF and camera-native geometry present',
      confidence: classification.confidence,
    });
  }

  // --- Source discovery corroborations / timeline ---
  const timeline: { date: string | null; note: string; sourceUrl?: string | null }[] = [];

  sourceDiscovery.matches.forEach((m) => {
    if (m.firstSeen) {
      timeline.push({ date: m.firstSeen, note: `${m.kind} match`, sourceUrl: m.url });
    }
  });
  sourceDiscovery.timeline.forEach((t) => {
    timeline.push({ date: t.date, note: t.note, sourceUrl: t.sourceUrl });
  });
  if (backend.datetime_original) {
    timeline.push({ date: backend.datetime_original, note: 'EXIF DateTimeOriginal (as recorded in received copy)' });
  }

  const exact = sourceDiscovery.matches.filter((m) => m.kind === 'exact');
  const similar = sourceDiscovery.matches.filter((m) => m.kind === 'similar');
  const crop = sourceDiscovery.matches.filter((m) => m.kind === 'crop');
  if (exact.length) {
    corroborations.push({
      layer: 'source_discovery',
      label: `${exact.length} exact online match(es)`,
      detail: exact[0].url,
      confidence: 0.9,
    });
  }
  if (similar.length) {
    corroborations.push({
      layer: 'source_discovery',
      label: `${similar.length} similar online match(es)`,
      detail: `Perceptual similarity ${similar[0].similarity != null ? Math.round(similar[0].similarity * 100) + '%' : 'n/a'}`,
      confidence: 0.6,
    });
  }
  if (crop.length) {
    corroborations.push({
      layer: 'source_discovery',
      label: `${crop.length} cropped-variant match(es)`,
      detail: crop[0].url,
      confidence: 0.65,
    });
  }

  // --- Temporal contradiction: source copy predates the EXIF capture date ---
  if (backend.datetime_original) {
    const capDate = new Date(backend.datetime_original);
    if (!isNaN(capDate.getTime())) {
      const predating = timeline.filter((t) => {
        if (!t.date) return false;
        const d = new Date(t.date);
        return !isNaN(d.getTime()) && d.getTime() < capDate.getTime();
      });
      if (predating.length) {
        contradictions.push({
          layer: 'timeline',
          label: 'Discovered source copy predates the EXIF capture date',
          detail: `Source ${predating[0].date} < captured ${backend.datetime_original}`,
          confidence: 0.7,
        });
      }
    }
  }

  // --- Location assessment ---
  const candidate = backendLoc || null;
  const locationSupport = corroborations.filter((c) =>
    ['visual_geolocation', 'ocr', 'geolocation', 'address'].some((k) => c.layer.toLowerCase().includes(k)),
  );
  const locationAgainst = contradictions.filter((c) =>
    ['ocr', 'timeline', 'geolocation', 'source'].some((k) => c.layer.toLowerCase().includes(k)),
  );

  let locationStatus: LocationAssessment['status'];
  if (candidate && backend.coordinates) {
    locationStatus = locationAgainst.length ? 'REQUIRES_REVIEW' : 'CORROBORATED';
  } else if (candidate && !backend.coordinates) {
    locationStatus = 'REQUIRES_REVIEW';
  } else {
    locationStatus = 'NOT_ESTABLISHED';
  }

  const location: LocationAssessment = {
    candidate,
    confidence: backend.consensus?.confidence_score ?? visualGeo.coordinates?.confidence ?? 0,
    supporting: locationSupport,
    contradicting: locationAgainst,
    status: locationStatus,
    note:
      candidate
        ? `Candidate location ${candidate} — ${locationAgainst.length ? 'review required (contradicting evidence present).' : 'supported by available evidence.'}`
        : 'Location could not be established from the available evidence.',
  };

  // --- Verdicts ---
  const verdicts: EvidenceVerdict[] = [];

  verdicts.push({
    dimension: 'origin',
    conclusion: sourceDiscovery.matches.length
      ? `Online copies located (${sourceDiscovery.matches.length}) — origin traceable`
      : 'No online source copy located',
    confidence: sourceDiscovery.matches.length ? 0.6 : 0.2,
    status: sourceDiscovery.matches.length ? 'PARTIAL' : 'UNRESOLVED',
  });

  verdicts.push({
    dimension: 'location',
    conclusion: backend.coordinates
      ? `Location established (${Math.round((backend.consensus?.confidence_score ?? 0) * 100)}%)`
      : visualGeo.coordinates
        ? `AI geolocation hypothesis available`
        : 'Location could not be established',
    confidence: backend.coordinates ? backend.consensus?.confidence_score ?? 0.5 : visualGeo.coordinates?.confidence ?? 0,
    status: backend.coordinates
      ? location.contradicting.length ? 'PARTIAL' : 'ESTABLISHED'
      : visualGeo.coordinates ? 'PARTIAL' : 'UNRESOLVED',
  });

  verdicts.push({
    dimension: 'camera',
    conclusion: backend.camera ? `Camera identified: ${Object.keys(backend.camera).slice(0, 3).join(', ')}` : 'No camera metadata recovered',
    confidence: backend.camera ? 0.7 : 0.2,
    status: backend.camera ? 'ESTABLISHED' : 'UNRESOLVED',
  });

  verdicts.push({
    dimension: 'source',
    conclusion: sourceDiscovery.providersConfigured
      ? sourceDiscovery.matches.length
        ? `${sourceDiscovery.matches.length} source match(es)`
        : 'Source search ran — no matches'
      : 'Source discovery provider not configured',
    confidence: sourceDiscovery.matches.length ? 0.6 : 0.15,
    status: sourceDiscovery.matches.length ? 'PARTIAL' : sourceDiscovery.providersConfigured ? 'UNRESOLVED' : 'UNRESOLVED',
  });

  verdicts.push({
    dimension: 'timeline',
    conclusion: timeline.length ? `${timeline.length} timeline point(s)` : 'No timeline reconstructed',
    confidence: timeline.length ? 0.5 : 0.1,
    status: timeline.length ? 'PARTIAL' : 'UNRESOLVED',
  });

  verdicts.push({
    dimension: 'screenshot',
    conclusion: classification.classification,
    confidence: classification.confidence,
    status:
      classification.classification === 'Likely Camera Photograph'
        ? 'CONTRADICTED'
        : classification.classification === 'Unknown'
          ? 'UNRESOLVED'
          : 'ESTABLISHED',
  });

  verdicts.push({
    dimension: 'metadata',
    conclusion: backend.exif_missing
      ? 'Direct metadata unavailable — proceeding with secondary analysis'
      : `Direct metadata recovered (${backend.source})`,
    confidence: backend.exif_missing ? 0.4 : 0.8,
    status: backend.exif_missing ? 'PARTIAL' : 'ESTABLISHED',
  });

  return {
    corroborations,
    contradictions,
    timeline,
    location,
    verdicts,
    note: `Fused ${corroborations.length} corroborating and ${contradictions.length} contradicting evidence items across asset classification, OCR, visual geolocation, source discovery, and backend forensics.`,
  };
}
