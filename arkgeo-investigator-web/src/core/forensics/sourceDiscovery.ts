/**
 * STEP 2 — Perceptual hashing & reverse source discovery.
 *
 * Local perceptual hashes (pHash / dHash / aHash) are ALWAYS computed on
 * ingestion — they cost nothing and anchor every later comparison.
 *
 * Provider state is read from the health endpoint. When a reverse-search
 * provider is configured the step correlates the backend's provider results
 * (TinEye / Serper) into structured matches + timeline. When NO provider is
 * configured the step emits an explicit observation — never a silent blank:
 *   "Source Discovery Provider: Unconfigured. Local pHash computed: <hash>"
 */
import type { AnalyzeResponse } from '../../types';
import type { PerceptualHashes, SourceDiscoveryResult, SourceMatch } from '../types';

export interface SourceDiscoveryInput {
  analysisCanvas: HTMLCanvasElement;
  backendResult: AnalyzeResponse;
  providersConfigured: boolean;
  providerLabel: string;
}

/** Compute pHash / dHash / aHash from the working canvas (64-bit hex each). */
export function computePerceptualHashes(canvas: HTMLCanvasElement): PerceptualHashes {
  const gray32 = grayFromCanvas(canvas, 32, 32);
  const gray8 = grayFromCanvas(canvas, 8, 8);
  const gray9x8 = grayFromCanvas(canvas, 9, 8);

  return {
    phash: computePHash(gray32),
    dhash: computeDHash(gray9x8, 9, 8),
    ahash: computeAHash(gray8),
  };
}

/** Draw a canvas to w×h and return grayscale luminance (0-255). */
function grayFromCanvas(canvas: HTMLCanvasElement, w: number, h: number): Float32Array {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  if (!ctx) return new Float32Array(w * h);
  ctx.drawImage(canvas, 0, 0, w, h);
  const data = ctx.getImageData(0, 0, w, h);
  const out = new Float32Array(w * h);
  for (let i = 0; i < w * h; i++) {
    const p = i * 4;
    out[i] = 0.299 * data.data[p] + 0.587 * data.data[p + 1] + 0.114 * data.data[p + 2];
  }
  return out;
}

/** 1-D DCT-II (orthonormal). */
function dct1D(a: number[]): number[] {
  const n = a.length;
  const out = new Array<number>(n);
  for (let k = 0; k < n; k++) {
    let sum = 0;
    for (let i = 0; i < n; i++) {
      sum += a[i] * Math.cos((Math.PI / n) * (i + 0.5) * k);
    }
    out[k] = sum * (k === 0 ? Math.sqrt(1 / n) : Math.sqrt(2 / n));
  }
  return out;
}

/** Classic pHash: 32×32 → DCT → top-left 8×8 → bits vs median. */
function computePHash(gray: Float32Array): string {
  const n = 32;
  const rows = new Array<number[]>(n);
  for (let y = 0; y < n; y++) {
    const row: number[] = [];
    for (let x = 0; x < n; x++) row.push(gray[y * n + x]);
    rows[y] = dct1D(row);
  }
  const cols = new Array<number[]>(n);
  for (let x = 0; x < n; x++) {
    const col: number[] = [];
    for (let y = 0; y < n; y++) col.push(rows[y][x]);
    cols[x] = dct1D(col);
  }
  const coeffs: number[] = [];
  for (let y = 0; y < 8; y++) {
    for (let x = 0; x < 8; x++) {
      if (x === 0 && y === 0) continue;
      coeffs.push(cols[x][y]);
    }
  }
  const sorted = [...coeffs].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  return bitsToHex(coeffs.map((v) => (v > median ? 1 : 0)));
}

/** dHash: 9×8 grid, bit = neighbor comparison right. */
function computeDHash(gray: Float32Array, w: number, h: number): string {
  const bits: number[] = [];
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w - 1; x++) {
      bits.push(gray[y * w + x] > gray[y * w + x + 1] ? 1 : 0);
    }
  }
  return bitsToHex(bits);
}

/** aHash: 8×8 grid, bit = value > mean. */
function computeAHash(gray: Float32Array): string {
  let sum = 0;
  for (let i = 0; i < gray.length; i++) sum += gray[i];
  const mean = sum / (gray.length || 1);
  return bitsToHex(Array.from(gray, (v) => (v > mean ? 1 : 0)));
}

function bitsToHex(bits: number[]): string {
  let hex = '';
  for (let i = 0; i < bits.length; i += 4) {
    const nibble =
      (bits[i] << 3) | (bits[i + 1] << 2) | (bits[i + 2] << 1) | bits[i + 3];
    hex += nibble.toString(16);
  }
  return hex;
}

/** Normalize a backend source_discovery dict into our structured matches. */
export function parseBackendMatches(backend: unknown): {
  matches: SourceMatch[];
  timeline: SourceDiscoveryResult['timeline'];
  provider: string;
  state: string;
  detail: string;
} {
  const raw = (backend || {}) as Record<string, unknown>;
  const matches: SourceMatch[] = [];
  const exact = Array.isArray(raw.exact_matches) ? raw.exact_matches : [];
  const similar = Array.isArray(raw.similar_matches) ? raw.similar_matches : [];

  exact.forEach((m) => matches.push(normalizeMatch(m, 'exact')));
  similar.forEach((m) => {
    const kind = inferMatchKind(m);
    matches.push(normalizeMatch(m, kind));
  });

  const timeline = Array.isArray(raw.timeline)
    ? (raw.timeline as { date?: string | null; note?: string; source_url?: string | null }[])
        .filter((t) => t && typeof t === 'object')
        .map((t) => ({
          date: t.date ?? null,
          note: t.note ?? 'Source copy',
          sourceUrl: t.source_url ?? null,
        }))
    : [];

  return {
    matches,
    timeline,
    provider: typeof raw.provider === 'string' ? raw.provider : 'none',
    state: typeof raw.state === 'string' ? raw.state : 'UNAVAILABLE',
    detail: typeof raw.detail === 'string' ? raw.detail : '',
  };
}

function inferMatchKind(m: unknown): SourceMatch['kind'] {
  const o = (m || {}) as Record<string, unknown>;
  const s = `${o.type || ''} ${o.kind || ''} ${o.label || ''}`.toLowerCase();
  if (s.includes('crop')) return 'crop';
  if (s.includes('resiz')) return 'resized';
  if (s.includes('exact')) return 'exact';
  return 'similar';
}

function normalizeMatch(m: unknown, kind: SourceMatch['kind']): SourceMatch {
  const o = (m || {}) as Record<string, unknown>;
  const url = String(o.url || o.page_url || o.image_url || o.source_url || o.thumbnail || '');
  const similarity = typeof o.similarity === 'number' ? o.similarity : null;
  return {
    kind,
    url,
    similarity,
    firstSeen: (o.first_seen as string) || (o.published as string) || null,
    source: (o.source as string) || (o.provider as string) || null,
  };
}

/** Run Step 2 — hashes always computed; provider results correlated when configured. */
export async function runSourceDiscovery(input: SourceDiscoveryInput): Promise<SourceDiscoveryResult> {
  const hashes = computePerceptualHashes(input.analysisCanvas);

  const backend = parseBackendMatches(input.backendResult.source_discovery);

  if (!input.providersConfigured) {
    return {
      hashes,
      providersConfigured: false,
      provider: 'none',
      matches: [],
      timeline: [],
      detail: `Source Discovery Provider: Unconfigured. Local pHash computed: ${hashes.phash}`,
    };
  }

  return {
    hashes,
    providersConfigured: true,
    provider: backend.provider || input.providerLabel,
    matches: backend.matches,
    timeline: backend.timeline,
    detail: backend.detail || 'Reverse source search completed.',
  };
}
