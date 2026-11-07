/**
 * C.4 — Metadata absence classification.
 *
 * "No metadata" is not one state. An image whose EXIF was stripped by a
 * messaging app, an image that genuinely never carried EXIF, and a server
 * where ExifTool is not installed all render the same empty tree — but they
 * mean different things to an investigator.
 *
 * This module turns the backend's metadata signals into an explicit,
 * honest presentation state so absence is stated as a finding rather than
 * silently shown as an empty panel. Pure and dependency-free.
 */

export type MetadataAbsenceKind =
  | 'PRESENT'
  | 'STRIPPED'
  | 'NEVER_PRESENT'
  | 'TOOL_UNAVAILABLE';

export interface MetadataState {
  kind: MetadataAbsenceKind;
  /** Short headline for the panel. */
  label: string;
  tone: 'ok' | 'warn' | 'bad' | 'neutral';
  /** What this state means — and what it does NOT mean. */
  explanation: string;
  /** True when the absence is itself forensically significant. */
  significant: boolean;
}

export interface MetadataSignals {
  /** Backend `metadata_status` (EXIF_PRESENT | STRIPPED_BY_INTERMEDIARY). */
  metadataStatus?: string | null;
  /** Backend `exif_missing` flag. */
  exifMissing?: boolean | null;
  /** Whether ExifTool produced a metadata tree at all. */
  deepAvailable?: boolean | null;
  /** Whether the deep tree actually contained any fields. */
  fieldCount?: number;
}

/**
 * Classify the metadata state. Precedence: a missing analysis tool outranks
 * every data claim (we cannot assert anything about the file), then the
 * backend's explicit stripped/present signals, then a bare absence.
 */
export function classifyMetadataState(signals: MetadataSignals): MetadataState {
  const { metadataStatus, exifMissing, deepAvailable, fieldCount } = signals;

  if (deepAvailable === false) {
    return {
      kind: 'TOOL_UNAVAILABLE',
      label: 'Metadata tool unavailable',
      tone: 'neutral',
      explanation:
        'The metadata extraction tool did not run, so no conclusion about this file\'s metadata can be drawn. This is an analysis gap, not evidence of tampering.',
      significant: false,
    };
  }

  const status = (metadataStatus ?? '').toUpperCase();
  if (status === 'STRIPPED_BY_INTERMEDIARY' || exifMissing === true) {
    return {
      kind: 'STRIPPED',
      label: 'Metadata stripped',
      tone: 'warn',
      explanation:
        'EXIF metadata is absent or was removed — typical of images forwarded through messaging apps and social platforms. Absence is consistent with stripping but does not by itself prove manipulation.',
      significant: true,
    };
  }

  if (status === 'EXIF_PRESENT' || (typeof fieldCount === 'number' && fieldCount > 0)) {
    return {
      kind: 'PRESENT',
      label: 'Metadata present',
      tone: 'ok',
      explanation: 'Metadata fields were recovered and are shown below.',
      significant: false,
    };
  }

  return {
    kind: 'NEVER_PRESENT',
    label: 'No metadata fields',
    tone: 'neutral',
    explanation:
      'No metadata fields were found and no stripping signal was reported. The file may simply never have carried EXIF (e.g. a screenshot or exported render).',
    significant: false,
  };
}
