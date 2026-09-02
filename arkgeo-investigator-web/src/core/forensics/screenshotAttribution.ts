/**
 * STEP 1 — Automated asset classification & screenshot attribution.
 *
 * On ingestion the received file is treated as evidence, and we establish
 * exactly what survived in it BEFORE any analysis: binary header, JPEG
 * quantization tables, dimensions vs. known device screen resolutions, and
 * margin scan for system overlay bars (status / home indicator / navigation).
 *
 * The output is an honest classification + platform profile. When signals are
 * weak we say "Unknown" rather than pretending certainty.
 */
import type { AssetClassification } from '../types';
import { type AnalysisImage, inspectBinaryHeader, readPixels } from './imageLoader';

/** Known mobile/desktop screen resolutions (portrait orientation, w×h). */
const SCREEN_RESOLUTIONS: { width: number; height: number; platform: 'iOS' | 'Android'; device: string }[] = [
  { width: 1170, height: 2532, platform: 'iOS', device: 'iPhone 13 / 14' },
  { width: 1179, height: 2556, platform: 'iOS', device: 'iPhone 14 Pro' },
  { width: 1080, height: 2340, platform: 'iOS', device: 'iPhone 13 mini / 12 mini' },
  { width: 1284, height: 2778, platform: 'iOS', device: 'iPhone 13 Pro Max / 14 Pro Max' },
  { width: 1242, height: 2688, platform: 'iOS', device: 'iPhone 11 Pro Max / XS Max' },
  { width: 1125, height: 2436, platform: 'iOS', device: 'iPhone X / XS / 11 Pro' },
  { width: 828, height: 1792, platform: 'iOS', device: 'iPhone 11 / XR' },
  { width: 750, height: 1334, platform: 'iOS', device: 'iPhone SE (2nd/3rd gen) / 8' },
  { width: 1080, height: 2400, platform: 'Android', device: 'Samsung S21/S22/S23 · Pixel 6/7 · generic 1080p' },
  { width: 1440, height: 3200, platform: 'Android', device: 'Samsung S21 Ultra' },
  { width: 1440, height: 3120, platform: 'Android', device: 'Pixel 7 Pro' },
  { width: 1344, height: 2992, platform: 'Android', device: 'Pixel 8 Pro' },
  { width: 1440, height: 3216, platform: 'Android', device: 'OnePlus 9/10/11' },
  { width: 1080, height: 2160, platform: 'Android', device: 'Android 1080p (18:9)' },
];

const WHATSAPP_FILENAME = /^IMG-\d{8}-WA\d+/i;
const TELEGRAM_FILENAME = /telegram/i;

interface BandStats {
  mean: [number, number, number];
  variance: number;
  uniform: boolean;
}

function bandStats(data: ImageData, y0: number, y1: number): BandStats {
  const { width, height, data: px } = data;
  const y0c = Math.max(0, Math.floor(y0 * height));
  const y1c = Math.min(height, Math.max(y0c + 1, Math.floor(y1 * height)));
  let rSum = 0, gSum = 0, bSum = 0, n = 0;
  const sample = px;
  for (let y = y0c; y < y1c; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      rSum += sample[i];
      gSum += sample[i + 1];
      bSum += sample[i + 2];
      n += 1;
    }
  }
  if (n === 0) return { mean: [0, 0, 0], variance: Infinity, uniform: false };
  const mean: [number, number, number] = [rSum / n, gSum / n, bSum / n];
  let vr = 0, vg = 0, vb = 0;
  for (let y = y0c; y < y1c; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      const dr = sample[i] - mean[0];
      const dg = sample[i + 1] - mean[1];
      const db = sample[i + 2] - mean[2];
      vr += dr * dr;
      vg += dg * dg;
      vb += db * db;
    }
  }
  const variance = (vr + vg + vb) / (n * 3);
  return { mean, variance, uniform: variance < 40 };
}

function detectSystemOverlays(canvas: HTMLCanvasElement): {
  topBar: boolean;
  bottomBar: boolean;
  navBar: boolean;
} {
  const data = readPixels(canvas);
  if (!data || canvas.height < 24) return { topBar: false, bottomBar: false, navBar: false };

  const top = bandStats(data, 0, 0.04);
  const bottom = bandStats(data, 0.96, 1);
  const middle = bandStats(data, 0.45, 0.55);

  const topBar = top.uniform && top.variance < middle.variance * 0.3;
  const bottomBar = bottom.uniform && bottom.variance < middle.variance * 0.3;

  // Home-indicator / nav-bar: a thin darker strip at the very bottom edge that
  // is uniform but differs from the rest of the bottom band.
  const homeStrip = bandStats(data, 0.985, 1);
  const navBar = homeStrip.uniform && Math.abs(homeStrip.mean[0] - bottom.mean[0]) > 12;

  return { topBar, bottomBar, navBar };
}

export interface ScreenshotAttributionInput {
  file: File;
  analysis: AnalysisImage;
}

/**
 * Classify the received asset. Pure client-side heuristics — never fabricates
 * EXIF. Screenshot detection is based on screen-resolution matches and system
 * overlay margin scans; messenger re-encode detection on JPEG structure.
 */
export async function classifyAsset(input: ScreenshotAttributionInput): Promise<AssetClassification> {
  const { file, analysis } = input;
  const header = await inspectBinaryHeader(file);

  const width = analysis.width;
  const height = analysis.height;
  const maxSide = Math.max(width, height);
  const aspect = width / height;
  const reasons: string[] = [];

  const overlays = detectSystemOverlays(analysis.smallCanvas);
  if (overlays.topBar) reasons.push('Uniform top band — status bar margin');
  if (overlays.bottomBar) reasons.push('Uniform bottom band — system margin');
  if (overlays.navBar) reasons.push('Home-indicator strip at bottom edge');

  // Normalize orientation so portrait dims match the table.
  const [w, h] = height > width ? [width, height] : [height, width];
  const screenMatch = SCREEN_RESOLUTIONS.find((r) => r.width === w && r.height === h);

  let platformProfile: AssetClassification['platformProfile'] = 'Unknown';
  let classification: AssetClassification['classification'] = 'Unknown';
  let confidence = 0.4;
  let quantizationHint: number | null = header.quantizationHint;

  if (screenMatch) {
    reasons.push(`Dimensions match ${screenMatch.device} screen resolution (${w}×${h})`);
  }
  if (header.hasExif) reasons.push('EXIF metadata present');
  if (quantizationHint !== null) reasons.push(`JPEG quantization avg ≈ ${quantizationHint} (heavier = messenger re-encode)`);
  reasons.push(`Format: ${header.format} · ${width}×${height} · aspect ${aspect.toFixed(3)}`);

  const screenOverlay = overlays.topBar || overlays.bottomBar || overlays.navBar;

  if (screenMatch && (screenOverlay || (h / w) > 1.9)) {
    classification = 'Likely Screenshot';
    platformProfile = screenMatch.platform === 'iOS' ? 'iOS Native' : 'Android Native';
    confidence = screenOverlay ? 0.88 : 0.72;
  } else if (screenOverlay && h / w >= 1.6) {
    classification = 'Likely Screenshot';
    platformProfile = h / w >= 2 ? 'Android Native' : 'iOS Native';
    confidence = 0.65;
  } else if (WHATSAPP_FILENAME.test(file.name)) {
    classification = 'Likely Exported/Messenger Asset';
    platformProfile = 'WhatsApp Compression';
    confidence = 0.85;
    reasons.push(`Filename pattern ${file.name.match(WHATSAPP_FILENAME)?.[0]} — WhatsApp export`);
  } else if (TELEGRAM_FILENAME.test(file.name)) {
    classification = 'Likely Exported/Messenger Asset';
    platformProfile = 'Telegram Re-encode';
    confidence = 0.8;
    reasons.push('Filename references Telegram');
  } else if (
    header.format === 'jpeg' &&
    !header.hasExif &&
    maxSide <= 1600 &&
    maxSide >= 720 &&
    (quantizationHint === null || quantizationHint >= 8)
  ) {
    classification = 'Likely Exported/Messenger Asset';
    // 2560px is the Telegram auto-compress ceiling; 1280/1600 is WhatsApp's.
    platformProfile = maxSide >= 2560 ? 'Telegram Re-encode' : 'WhatsApp Compression';
    confidence = 0.6;
    reasons.push(`No EXIF · longest side ${maxSide}px · re-encode profile`);
  } else if (header.hasExif && (aspect === 4 / 3 || aspect === 3 / 2 || Math.abs(aspect - 16 / 9) < 0.05)) {
    classification = 'Likely Camera Photograph';
    platformProfile = 'Unknown';
    confidence = 0.75;
    reasons.push('EXIF present with camera-native aspect ratio');
  } else if (header.hasExif && maxSide >= 2000) {
    classification = 'Likely Camera Photograph';
    platformProfile = 'Unknown';
    confidence = 0.65;
  } else {
    classification = 'Unknown';
    platformProfile = 'Unknown';
    confidence = 0.3;
    reasons.push('Insufficient distinguishing signals — treating as unknown');
  }

  return {
    classification,
    platformProfile,
    confidence,
    reasons,
    dimensions: { width, height },
    format: header.format,
    hasExif: header.hasExif,
    maxSide,
    aspect: Math.round(aspect * 1000) / 1000,
    quantizationHint,
  };
}
