/**
 * STEP 3 — OCR & text telemetry extraction.
 *
 * Text is gathered from the strongest available engine:
 *   1. Server-side AI OCR — when a vision provider is configured, the backend
 *      already ran OCR (consensus.visual_evidence_tags / ai_evidence.scene).
 *   2. Client-side Tesseract.js — dynamic import; used when no server OCR
 *      text was produced. Fails gracefully (worker/language CDN unavailable).
 *   3. none — explicit NOT_OBSERVED output ("Text Regions Detected: 0").
 *
 * Extracted text is parsed for telemetry: URLs, phone numbers, social
 * handles, currencies, street names, license plates, and carrier keywords —
 * then passed to the evidence fusion step as geographic/text evidence.
 */
import type { AnalyzeResponse } from '../../types';
import type { OcrTelemetry, OcrTelemetryMatch } from '../types';

export interface OcrPipelineInput {
  file: File;
  analysisCanvas: HTMLCanvasElement;
  backendResult: AnalyzeResponse;
  serverOcrAvailable: boolean;
}

const OCR_TIMEOUT_MS = 45000;

/** Collect server-side OCR text from the backend analysis if any exists. */
export function collectServerOcr(backend: AnalyzeResponse): { text: string; confidence: number; regions: number } | null {
  const texts: string[] = [];

  (backend.consensus?.visual_evidence_tags || []).forEach((t) => {
    if (t.category === 'ocr' && t.label) texts.push(t.label);
  });

  const scene = (backend.ai_evidence as Record<string, unknown> | null)?.scene as
    | Record<string, unknown>
    | null
    | undefined;
  const ocrTexts = Array.isArray(scene?.ocr_texts) ? (scene.ocr_texts as string[]) : [];
  ocrTexts.forEach((t) => {
    if (typeof t === 'string' && t.trim()) texts.push(t);
  });

  if (texts.length === 0) return null;
  const joined = Array.from(new Set(texts.map((t) => t.trim()).filter(Boolean))).join('\n');
  return { text: joined, confidence: 0.8, regions: texts.length };
}

/** Run client-side OCR via Tesseract.js (dynamic import, graceful failure). */
async function runTesseractOcr(dataUrl: string): Promise<{ text: string; confidence: number; regions: number } | null> {
  try {
    const Tesseract = await import('tesseract.js');
    const result = await Promise.race([
      (async () => {
        const worker = await Tesseract.createWorker('eng', 1, { logger: () => {} });
        const { data } = await worker.recognize(dataUrl);
        await worker.terminate();
        const blocks = ((data.blocks as unknown) || []) as { text?: string }[];
        const regions = blocks.filter((b) => b && typeof b.text === 'string' && b.text.trim().length > 0).length;
        return {
          text: (data.text || '').trim(),
          confidence: typeof data.confidence === 'number' ? data.confidence / 100 : 0.5,
          regions,
        };
      })(),
      new Promise<never>((_, reject) => setTimeout(() => reject(new Error('OCR timeout')), OCR_TIMEOUT_MS)),
    ]);
    if (!result.text) return null;
    return result;
  } catch {
    return null;
  }
}

/** Extract telemetry patterns from OCR text. */
export function extractTextTelemetry(text: string): OcrTelemetryMatch[] {
  const matches: OcrTelemetryMatch[] = [];
  const add = (kind: OcrTelemetryMatch['kind'], value: string) => {
    const v = value.trim();
    if (v && !matches.some((m) => m.kind === kind && m.value.toLowerCase() === v.toLowerCase())) {
      matches.push({ kind, value: v });
    }
  };

  const urlRe = /\b(?:https?:\/\/|www\.)[^\s<>"']+[^\s<>"',.;:]/gi;
  (text.match(urlRe) || []).forEach((u) => add('url', u));
  // Bare domains that look like links.
  (text.match(/\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|co|ng|tv|me|xyz|info|blog|shop)\b/gi) || [])
    .forEach((d) => add('url', d));

  // Phone numbers: country-code aware (e.g., +234...), then local formats with 10+ digits.
  (text.match(/(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?){2,}\d{2,4}\b/g) || [])
    .filter((p) => p.replace(/\D/g, '').length >= 10 && p.replace(/\D/g, '').length <= 15)
    .forEach((p) => add('phone', p));

  // Social handles (@user), excluding emails.
  (text.match(/(?:^|[^\w@])(@[A-Za-z0-9_]{2,30})(?!@)/g) || [])
    .map((h) => h.trim().replace(/^[^\w@]+/, ''))
    .filter((h) => h.startsWith('@') && !/^@[\d.]+$/.test(h))
    .forEach((h) => add('social_handle', h));

  // Currencies with amounts.
  (text.match(/[$€£¥₦₿]\s?\d{1,3}(?:[.,]\d{1,3})*/g) || [])
    .forEach((c) => add('currency', c));

  // Street names: proper-case words + road suffix.
  (text.match(/\b[A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+){0,3}\s(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Boulevard|Blvd|Highway|Hwy|Way|Court|Ct|Crescent|Cres)\b/gi) || [])
    .forEach((s) => add('street', s));

  // License plates: conservative 6-8 alphanumeric plate-ish tokens.
  (text.match(/\b(?:[A-Z]{1,3}[\s-]?\d{1,4}|[A-Z]{2}\d[A-Z]{2,4})\b/g) || [])
    .filter((p) => !/(MTN|GLO|AIR|AIRTEL)/i.test(p))
    .forEach((p) => add('license_plate', p));

  // Mobile network / carrier keywords (strong geographic signal in West Africa).
  (text.match(/\b(?:MTN|Airtel|Glo|9mobile|Vodafone|Verizon|T-Mobile|AT&T|Orange|Safaricom|Telkom|Mtn)\b/gi) || [])
    .forEach((c) => add('carrier', c));

  return matches;
}

/** Run Step 3 — OCR + text telemetry. */
export async function runOcrPipeline(input: OcrPipelineInput): Promise<OcrTelemetry> {
  const server = collectServerOcr(input.backendResult);

  if (server) {
    return {
      text: server.text,
      confidence: server.confidence,
      regions: server.regions,
      engine: 'server_ai',
      language: 'unknown',
      matches: extractTextTelemetry(server.text),
    };
  }

  // Server OCR unavailable (no vision provider / no text) → try Tesseract.
  const dataUrl = input.analysisCanvas.toDataURL('image/png');
  const local = await runTesseractOcr(dataUrl);

  if (local) {
    return {
      text: local.text,
      confidence: local.confidence,
      regions: local.regions,
      engine: 'tesseract',
      language: 'eng',
      matches: extractTextTelemetry(local.text),
    };
  }

  return {
    text: '',
    confidence: 0,
    regions: 0,
    engine: 'none',
    language: 'unknown',
    matches: [],
  };
}
