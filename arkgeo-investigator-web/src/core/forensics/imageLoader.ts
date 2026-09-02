/**
 * Shared client-side image decoding.
 *
 * Every pipeline step decodes the asset once through loadImageForAnalysis
 * and reuses the small working canvas + full dimensions, avoiding repeated
 * decode work across the cascade.
 */

export interface AnalysisImage {
  width: number;
  height: number;
  /** Full-resolution ImageBitmap (used for thumbnail / original dims). */
  bitmap: ImageBitmap | null;
  /** Working canvas, max ~256px on the longest side, for pixel analysis. */
  smallCanvas: HTMLCanvasElement;
}

/** Load a file, get true dimensions, and build a small working canvas. */
export async function loadImageForAnalysis(file: File): Promise<AnalysisImage> {
  const source = await decodeImageSource(file);
  const width = source.width;
  const height = source.height;
  const maxSide = Math.max(width, height);
  const scale = Math.min(1, 256 / (maxSide || 1));
  const sw = Math.max(1, Math.round(width * scale));
  const sh = Math.max(1, Math.round(height * scale));

  const smallCanvas = document.createElement('canvas');
  smallCanvas.width = sw;
  smallCanvas.height = sh;
  const ctx = smallCanvas.getContext('2d', { willReadFrequently: true });
  if (ctx) ctx.drawImage(source.drawable, 0, 0, sw, sh);

  return { width, height, bitmap: source.bitmap, smallCanvas };
}

interface DecodedSource {
  width: number;
  height: number;
  drawable: CanvasImageSource;
  bitmap: ImageBitmap | null;
}

async function decodeImageSource(file: File): Promise<DecodedSource> {
  if (typeof createImageBitmap === 'function') {
    try {
      const bitmap = await createImageBitmap(file);
      return { width: bitmap.width, height: bitmap.height, drawable: bitmap, bitmap };
    } catch {
      /* fall through to <img> decode */
    }
  }
  return decodeViaImage(file);
}

function decodeViaImage(file: File): Promise<DecodedSource> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve({ width: img.naturalWidth, height: img.naturalHeight, drawable: img, bitmap: null });
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('Image decode failed'));
    };
    img.src = url;
  });
}

/** Read 32-bit RGBA pixel data from a canvas at the given size. */
export function readPixels(canvas: HTMLCanvasElement): ImageData | null {
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) return null;
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

/**
 * Inspect the raw file header to determine format, EXIF presence, embedded
 * JPEG dimensions, and quantization-table compression hint. Fast — operates
 * on the first KBs without a full decode.
 */
export interface BinaryHeaderInspect {
  format: string;
  hasExif: boolean;
  jpegWidth: number | null;
  jpegHeight: number | null;
  quantizationHint: number | null;
}

export function inspectBinaryHeader(file: File): Promise<BinaryHeaderInspect> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => {
      const buf = reader.result as ArrayBuffer;
      const bytes = new Uint8Array(buf);
      const out: BinaryHeaderInspect = {
        format: 'unknown',
        hasExif: false,
        jpegWidth: null,
        jpegHeight: null,
        quantizationHint: null,
      };

      if (bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xd8) {
        out.format = 'jpeg';
        const j = parseJpeg(bytes);
        out.hasExif = j.hasExif;
        out.jpegWidth = j.width;
        out.jpegHeight = j.height;
        out.quantizationHint = j.quantizationHint;
      } else if (
        bytes.length >= 8 &&
        bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47 &&
        bytes[4] === 0x0d && bytes[5] === 0x0a && bytes[6] === 0x1a && bytes[7] === 0x0a
      ) {
        out.format = 'png';
        out.hasExif = pngHasExif(bytes);
      } else if (bytes.length >= 12 && bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 &&
                 bytes[3] === 0x46 && bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 &&
                 bytes[11] === 0x50) {
        out.format = 'webp';
      } else if (bytes.length >= 4 && bytes[0] === 0x49 && bytes[1] === 0x49 && bytes[2] === 0x2a &&
                 bytes[3] === 0x00) {
        out.format = 'tiff';
      } else if (bytes.length >= 4 && bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46) {
        out.format = 'gif';
      }
      resolve(out);
    };
    reader.onerror = () => resolve({ format: 'unknown', hasExif: false, jpegWidth: null, jpegHeight: null, quantizationHint: null });
    reader.readAsArrayBuffer(file.slice(0, 65536));
  });
}

/** Legacy alias — format + EXIF presence only. */
export async function analyzeBinaryHeader(file: File): Promise<{ format: string; hasExif: boolean }> {
  const insp = await inspectBinaryHeader(file);
  return { format: insp.format, hasExif: insp.hasExif };
}

/** Scan JPEG segments for an APP1 "Exif" segment and read DQT tables. */
export function parseJpeg(bytes: Uint8Array): {
  hasExif: boolean;
  width: number | null;
  height: number | null;
  quantizationHint: number | null;
} {
  const out = { hasExif: false, width: null as number | null, height: null as number | null, quantizationHint: null as number | null };
  if (bytes.length < 2 || bytes[0] !== 0xff || bytes[1] !== 0xd8) return out;

  let i = 2;
  while (i + 3 < bytes.length) {
    if (bytes[i] !== 0xff) { i += 1; continue; }
    const marker = bytes[i + 1];
    if (marker === 0xff || marker === 0x00) { i += 1; continue; }
    // Standalone markers (no length).
    if (marker === 0xd8 || marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) { i += 2; continue; }
    const len = (bytes[i + 2] << 8) | bytes[i + 3];
    if (len < 2) break;

    if (marker === 0xe1 && len >= 8 && String.fromCharCode(bytes[i + 4], bytes[i + 5], bytes[i + 6], bytes[i + 7], bytes[i + 8]) === 'Exif\0') {
      out.hasExif = true;
    }
    if ((marker === 0xc0 || marker === 0xc1 || marker === 0xc2 || marker === 0xc3) && len >= 7) {
      out.height = (bytes[i + 5] << 8) | bytes[i + 6];
      out.width = (bytes[i + 7] << 8) | bytes[i + 8];
    }
    if (marker === 0xdb && len >= 3 && out.quantizationHint === null) {
      const pq = bytes[i + 4] >> 4;
      const size = 1 + (pq === 0 ? 64 : 128);
      if (len >= 2 + size) {
        const start = i + 5;
        let sum = 0;
        let count = 0;
        for (let k = 0; k < size; k++) {
          const v = bytes[start + k];
          sum += v;
          count += 1;
        }
        out.quantizationHint = count ? Math.round(sum / count) : null;
      }
    }
    if (out.hasExif && out.width !== null && out.height !== null && out.quantizationHint !== null) break;
    i += 2 + len;
  }
  return out;
}

function pngHasExif(bytes: Uint8Array): boolean {
  // PNG signature (8 bytes) then IHDR (25 bytes), then chunks.
  let i = 8;
  while (i + 8 <= bytes.length) {
    const len = ((bytes[i] << 24) | (bytes[i + 1] << 16) | (bytes[i + 2] << 8) | bytes[i + 3]) >>> 0;
    const type = String.fromCharCode(bytes[i + 4], bytes[i + 5], bytes[i + 6], bytes[i + 7]);
    if (type === 'eXIf' || type === 'iTXt' || type === 'tEXt') return true;
    if (len < 0 || i + 12 + len > bytes.length) break;
    i += 12 + len;
  }
  return false;
}
