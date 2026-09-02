/**
 * ImagePipeline — the continuous image intelligence cascade.
 *
 * Every uploaded asset runs through a 5-step analysis regardless of metadata
 * presence. The pipeline is intentionally honest: when a provider or capability
 * is unavailable the affected step emits an explicit UNAVAILABLE / NOT_OBSERVED
 * observation instead of failing silently or fabricating evidence.
 *
 *   Step 1  Automated asset classification & screenshot attribution
 *   Step 2  Perceptual hashing & reverse source discovery
 *   Step 3  OCR & text telemetry extraction
 *   Step 4  Multi-modal visual geolocation & landmark analysis
 *   Step 5  Evidence fusion & defensible assessment
 *
 * The result is folded into the shared investigation case store by the caller
 * (useInvestigation.mergePipeline) so the whole workspace reflects the cascade.
 */
import { api } from '../../api';
import type { AnalyzeResponse, GeoCandidate } from '../../types';
import type {
  ImagePipelineResult,
  OcrTelemetry,
  PipelineObservation,
  PipelineProgress,
  PipelineStepResult,
} from '../types';
import { loadImageForAnalysis } from '../forensics/imageLoader';
import { classifyAsset } from '../forensics/screenshotAttribution';
import { runSourceDiscovery } from '../forensics/sourceDiscovery';
import { runOcrPipeline } from '../forensics/ocrPipeline';
import { geocodeFromOcr } from '../../services/geocodingService';
import { runVisualGeo } from '../forensics/visualGeoAI';
import { fuseEvidence } from '../fusion/evidenceFusion';

export interface ImagePipelineOptions {
  onProgress?: (p: PipelineProgress) => void;
}

let obsCounter = 0;

/** Build a structured observation with a stable, case-relative id. */
export function pipelineObservation(
  step: number,
  layer: string,
  type: string,
  status: PipelineObservation['status'],
  label: string,
  detail: string,
  source: PipelineObservation['source'],
  confidence?: number | null,
): PipelineObservation {
  obsCounter += 1;
  return {
    id: `OBS-C${step}-${String(obsCounter).padStart(2, '0')}`,
    step,
    type,
    status,
    layer,
    label,
    detail,
    source,
    confidence: confidence ?? null,
  };
}

/** Build observations for Step 1 (asset classification & screenshot attribution). */
function step1Observations(classification: Awaited<ReturnType<typeof classifyAsset>>): PipelineObservation[] {
  const out: PipelineObservation[] = [];

  out.push(
    pipelineObservation(
      1,
      'asset_classification',
      'ASSET_CLASSIFICATION',
      'OBSERVED',
      `Asset classified: ${classification.classification}`,
      `${classification.platformProfile} · confidence ${Math.round(classification.confidence * 100)}% · ${classification.reasons.slice(0, 4).join(' · ')}`,
      'tool_inference',
      classification.confidence,
    ),
  );

  out.push(
    pipelineObservation(
      1,
      'metadata',
      'EXIF',
      classification.hasExif ? 'OBSERVED' : 'NOT_OBSERVED',
      classification.hasExif ? 'EXIF metadata present' : 'EXIF metadata stripped or missing',
      classification.hasExif
        ? 'EXIF APP1 segment found in file header'
        : `Direct metadata unavailable for ${classification.format} (${classification.dimensions.width}×${classification.dimensions.height}) — proceeding with secondary analysis`,
      'cryptographic',
      classification.hasExif ? 0.95 : 0.8,
    ),
  );

  if (classification.classification === 'Likely Screenshot') {
    out.push(
      pipelineObservation(
        1,
        'screenshot_attribution',
        'SCREENSHOT',
        'OBSERVED',
        `Likely screenshot — ${classification.platformProfile}`,
        'Screen-resolution match and/or system overlay margins detected',
        'tool_inference',
        classification.confidence,
      ),
    );
  } else if (classification.classification === 'Likely Exported/Messenger Asset') {
    out.push(
      pipelineObservation(
        1,
        'messenger_profile',
        'MESSENGER',
        'OBSERVED',
        `Messenger-exported asset — ${classification.platformProfile}`,
        'Re-encode signature (no EXIF, compressed dimensions, JPEG quantization)',
        'tool_inference',
        classification.confidence,
      ),
    );
  }

  return out;
}

/** Build observations for Step 2 (perceptual hashing + source discovery). */
function step2Observations(sd: Awaited<ReturnType<typeof runSourceDiscovery>>): PipelineObservation[] {
  const out: PipelineObservation[] = [];

  out.push(
    pipelineObservation(
      2,
      'perceptual_hash',
      'HASHING',
      'OBSERVED',
      'Local perceptual hashes computed',
      `pHash ${sd.hashes.phash} · dHash ${sd.hashes.dhash} · aHash ${sd.hashes.ahash}`,
      'cryptographic',
      0.95,
    ),
  );

  if (!sd.providersConfigured) {
    out.push(
      pipelineObservation(
        2,
        'source_discovery',
        'SOURCE_DISCOVERY',
        'UNAVAILABLE',
        'Source Discovery Provider: Unconfigured',
        `Local pHash computed: ${sd.hashes.phash}. Configure a reverse-source provider (TinEye/Serper) via Admin to search online copies.`,
        'tool_inference',
        null,
      ),
    );
  } else if (sd.matches.length === 0) {
    out.push(
      pipelineObservation(
        2,
        'source_discovery',
        'SOURCE_DISCOVERY',
        'NOT_OBSERVED',
        'Source search completed — 0 sources discovered',
        `${sd.provider} · ${sd.detail}`,
        'tool_inference',
        null,
      ),
    );
  } else {
    const kinds = Array.from(new Set(sd.matches.map((m) => m.kind)));
    const firstSeen = sd.matches.filter((m) => m.firstSeen).map((m) => m.firstSeen as string).sort();
    out.push(
      pipelineObservation(
        2,
        'source_discovery',
        'SOURCE_DISCOVERY',
        'OBSERVED',
        `${sd.matches.length} source match(es) — ${kinds.join(', ')}`,
        firstSeen.length
          ? `Earliest copy: ${firstSeen[0]} · provider ${sd.provider}`
          : `provider ${sd.provider} · ${sd.detail}`,
        'tool_inference',
        0.7,
      ),
    );
    if (sd.timeline.length) {
      out.push(
        pipelineObservation(
          2,
        'source_timeline',
          'TIMELINE',
          'OBSERVED',
          `Source timeline reconstructed (${sd.timeline.length} point(s))`,
          sd.timeline.map((t) => `${t.date || 'unknown'} — ${t.note}`).join(' · '),
          'tool_inference',
          0.6,
        ),
      );
    }
  }

  return out;
}

/** Build observations for Step 3 (OCR & text telemetry). */
function step3Observations(ocr: Awaited<ReturnType<typeof runOcrPipeline>>): PipelineObservation[] {
  const out: PipelineObservation[] = [];

  if (ocr.regions > 0 && ocr.text) {
    out.push(
      pipelineObservation(
        3,
        'ocr',
        'OCR',
        'OBSERVED',
        `OCR text regions detected: ${ocr.regions}`,
        `${ocr.engine === 'server_ai' ? 'Server AI OCR' : 'Tesseract.js client OCR'} · ${ocr.language} · confidence ${Math.round(ocr.confidence * 100)}%`,
        'tool_inference',
        ocr.confidence,
      ),
    );
    const kinds = Array.from(new Set(ocr.matches.map((m) => m.kind)));
    if (ocr.matches.length) {
      out.push(
        pipelineObservation(
          3,
          'text_telemetry',
          'TEXT_TELEMETRY',
          'OBSERVED',
          `Text telemetry extracted: ${kinds.join(', ')}`,
          ocr.matches.map((m) => `${m.kind}: ${m.value}`).join(' · '),
          'tool_inference',
          0.6,
        ),
      );
    }

    const candidates = ocr.geo_candidates || [];
    if (candidates.length > 0) {
      out.push(
        pipelineObservation(
          3,
          'geocoding',
          'GEOCODING',
          'OBSERVED',
          `OCR text geocoded: ${candidates.length} candidate pin(s)`,
          candidates.map((c) => `${c.query} → ${c.lat.toFixed(4)}, ${c.lon.toFixed(4)}`).join(' · '),
          'tool_inference',
          0.5,
        ),
      );
    }
  } else {
    out.push(
      pipelineObservation(
        3,
        'ocr',
        'OCR',
        'NOT_OBSERVED',
        'OCR Completed. Text Regions Detected: 0',
        ocr.engine === 'none'
          ? 'No OCR provider available — configure a vision provider or allow client-side Tesseract.js to enable text extraction.'
          : 'Text extraction ran but found no text regions.',
        'tool_inference',
        null,
      ),
    );
  }

  return out;
}

/** Build observations for Step 4 (visual geolocation & landmark analysis). */
function step4Observations(vg: Awaited<ReturnType<typeof runVisualGeo>>): PipelineObservation[] {
  const out: PipelineObservation[] = [];

  if (vg.coordinates) {
    out.push(
      pipelineObservation(
        4,
        'visual_geolocation',
        'GEOLOCATION',
        'OBSERVED',
        'Visual geolocation returned',
        `${vg.coordinates.lat.toFixed(5)}, ${vg.coordinates.lon.toFixed(5)} · confidence ${Math.round(vg.coordinates.confidence * 100)}%`,
        'ai_hypothesis',
        vg.coordinates.confidence,
      ),
    );
  } else if (!vg.providersConfigured) {
    out.push(
      pipelineObservation(
        4,
        'visual_geolocation',
        'GEOLOCATION',
        'UNAVAILABLE',
        'Visual AI providers unconfigured',
        'No GeoSpy / multimodal vision key — using local heuristic feature analysis only.',
        'tool_inference',
        null,
      ),
    );
  } else {
    out.push(
      pipelineObservation(
        4,
        'visual_geolocation',
        'GEOLOCATION',
        'NOT_OBSERVED',
        'Visual geolocation did not produce coordinates',
        vg.note,
        'ai_hypothesis',
        null,
      ),
    );
  }

  vg.features.forEach((f) => {
    out.push(
      pipelineObservation(
        4,
        'visual_feature',
        'VISUAL_FEATURE',
        'HYPOTHESIS',
        `${f.label}: ${f.value}`,
        f.confidence >= 0.5 ? 'Heuristic visual signature' : 'Low-confidence heuristic — not deterministic evidence',
        'ai_hypothesis',
        f.confidence,
      ),
    );
  });

  return out;
}

/** Build observations for Step 5 (evidence fusion). */
function step5Observations(fused: Awaited<ReturnType<typeof fuseEvidence>>): PipelineObservation[] {
  const out: PipelineObservation[] = [];

  fused.contradictions.forEach((c) => {
    out.push(
      pipelineObservation(
        5,
        'contradiction',
        'CONTRADICTION',
        'ANOMALY',
        `Contradiction: ${c.label}`,
        `${c.detail} · ${c.layer}`,
        'ai_hypothesis',
        c.confidence,
      ),
    );
  });

  const locStatusObs =
    fused.location.status === 'CORROBORATED'
      ? 'OBSERVED'
      : fused.location.status === 'REQUIRES_REVIEW'
        ? 'ANOMALY'
        : 'NOT_OBSERVED';
  out.push(
    pipelineObservation(
      5,
      'location_assessment',
      'LOCATION_ASSESSMENT',
      locStatusObs,
      `Location assessment: ${fused.location.status}`,
      fused.location.candidate
        ? `Candidate: ${fused.location.candidate} · ${fused.location.supporting.length} supporting · ${fused.location.contradicting.length} contradicting`
        : fused.location.note,
      'ai_hypothesis',
      fused.location.confidence,
    ),
  );

  fused.verdicts.forEach((v) => {
    const status =
      v.status === 'ESTABLISHED'
        ? 'OBSERVED'
        : v.status === 'CONTRADICTED'
          ? 'ANOMALY'
          : v.status === 'PARTIAL'
            ? 'HYPOTHESIS'
            : 'NOT_OBSERVED';
    out.push(
      pipelineObservation(
        5,
        'verdict',
        `VERDICT_${v.dimension.toUpperCase()}`,
        status,
        `${v.dimension}: ${v.conclusion}`,
        `confidence ${Math.round(v.confidence * 100)}%`,
        'ai_hypothesis',
        v.confidence,
      ),
    );
  });

  return out;
}

/** Run the full 5-step cascade over an ingested asset. */
export async function runImagePipeline(
  file: File,
  backend: AnalyzeResponse,
  options?: ImagePipelineOptions,
): Promise<ImagePipelineResult> {
  const startedAt = Date.now();
  const totalSteps = 5;
  const report = (currentStep: number, name: string) => {
    options?.onProgress?.({ currentStep, totalSteps, name });
  };

  let health;
  try {
    health = await api.health();
  } catch {
    health = null;
  }
  const services = health?.services || {};

  const reverseConfigured =
    services.tineye === 'configured' || services.serper === 'configured';
  const visionConfigured =
    services.vision_geospy === 'configured' ||
    services.vision_geoinfer === 'configured' ||
    services.llm === 'configured' ||
    services.gemini === 'configured' ||
    services.anthropic === 'configured';
  const serverOcrAvailable = visionConfigured;

  const steps: PipelineStepResult[] = [];

  const makeStep = async (
    step: number,
    name: string,
    run: () => Promise<{ data: unknown; observations: PipelineObservation[] }>,
  ): Promise<PipelineStepResult> => {
    report(step, name);
    const t0 = Date.now();
    try {
      const { data, observations } = await run();
      return { step, name, ok: true, elapsedMs: Date.now() - t0, data, observations };
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Step failed';
      return {
        step,
        name,
        ok: false,
        elapsedMs: Date.now() - t0,
        data: null,
        observations: [
          pipelineObservation(
            step,
            'pipeline',
            'STEP_ERROR',
            'UNAVAILABLE',
            `${name} failed`,
            msg,
            'tool_inference',
            null,
          ),
        ],
      };
    }
  };

  const [classification, sourceDiscovery, ocr, visualGeo] = await Promise.all([
    (async () => {
      const analysis = await loadImageForAnalysis(file);
      const c = await classifyAsset({ file, analysis });
      return makeStep(1, 'Asset classification & screenshot attribution', async () => ({
        data: c,
        observations: step1Observations(c),
      }));
    })(),
    (async () => {
      const analysis = await loadImageForAnalysis(file);
      const sd = await runSourceDiscovery({
        analysisCanvas: analysis.smallCanvas,
        backendResult: backend,
        providersConfigured: reverseConfigured,
        providerLabel: 'configured reverse source provider',
      });
      return makeStep(2, 'Perceptual hashing & source discovery', async () => ({
        data: sd,
        observations: step2Observations(sd),
      }));
    })(),
    (async () => {
      const analysis = await loadImageForAnalysis(file);
      const o = await runOcrPipeline({
        file,
        analysisCanvas: analysis.smallCanvas,
        backendResult: backend,
        serverOcrAvailable,
      });
      // Active OCR → geocoding (Feature 2): resolve location-relevant OCR
      // text into candidate pins plotted on the spatial canvas.
      const geo_candidates: GeoCandidate[] = await geocodeFromOcr(o);
      o.geo_candidates = geo_candidates;
      return makeStep(3, 'OCR & text telemetry', async () => ({
        data: o,
        observations: step3Observations(o),
      }));
    })(),
    (async () => {
      const analysis = await loadImageForAnalysis(file);
      const v = await runVisualGeo({
        analysisCanvas: analysis.smallCanvas,
        backendResult: backend,
        providersConfigured: visionConfigured,
      });
      return makeStep(4, 'Visual geolocation & landmark analysis', async () => ({
        data: v,
        observations: step4Observations(v),
      }));
    })(),
  ]);

  steps.push(classification, sourceDiscovery, ocr, visualGeo);

  report(5, 'Evidence fusion');
  const t5 = Date.now();
  let fusionStep: PipelineStepResult;
  try {
    const fused = fuseEvidence({
      backend,
      classification: classification.data as Awaited<ReturnType<typeof classifyAsset>>,
      sourceDiscovery: sourceDiscovery.data as Awaited<ReturnType<typeof runSourceDiscovery>>,
      ocr: ocr.data as Awaited<ReturnType<typeof runOcrPipeline>>,
      visualGeo: visualGeo.data as Awaited<ReturnType<typeof runVisualGeo>>,
    });
    fusionStep = {
      step: 5,
      name: 'Evidence fusion',
      ok: true,
      elapsedMs: Date.now() - t5,
      data: fused,
      observations: step5Observations(fused),
    };
  } catch (err) {
    fusionStep = {
      step: 5,
      name: 'Evidence fusion',
      ok: false,
      elapsedMs: Date.now() - t5,
      data: null,
      observations: [
        pipelineObservation(5, 'pipeline', 'STEP_ERROR', 'UNAVAILABLE', 'Evidence fusion failed', err instanceof Error ? err.message : 'unknown', 'tool_inference', null),
      ],
    };
  }
  steps.push(fusionStep);

  const observations = steps.flatMap((s) => s.observations);

  const geo_candidates = ocr.data ? ((ocr.data as OcrTelemetry).geo_candidates || []) : [];

  return {
    file: { name: file.name, size: file.size, type: file.type },
    sha256: backend.image_sha256 || null,
    startedAt,
    completedAt: Date.now(),
    classification: classification.data as Awaited<ReturnType<typeof classifyAsset>>,
    sourceDiscovery: sourceDiscovery.data as Awaited<ReturnType<typeof runSourceDiscovery>>,
    ocr: ocr.data as Awaited<ReturnType<typeof runOcrPipeline>>,
    visualGeo: visualGeo.data as Awaited<ReturnType<typeof runVisualGeo>>,
    fusion: fusionStep.data as Awaited<ReturnType<typeof fuseEvidence>>,
    steps,
    observations,
    geo_candidates,
  };
}
