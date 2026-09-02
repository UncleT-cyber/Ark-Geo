/**
 * cellTowerMapper — turn a /telecom/cell-lookup response into a spatial
 * map point + operator label. The Telecom tab renders these on the shared
 * MapWorkspace and folds the location into the case as an observation.
 */
import type { CellLookupResponse } from '../../types';

export interface TowerPoint {
  lat: number;
  lon: number;
  radius: number;
  confidence: number;
  source: string;
  label: string;
  isHighRisk?: boolean;
}

/** Client-side MCC/MNC -> operator registry (best-effort label only). */
const OPERATOR_BY_MCC_MNC: Record<string, string> = {
  '621-30': 'MTN Nigeria',
  '621-20': 'Airtel Nigeria',
  '621-50': 'Glo Nigeria',
  '621-60': '9mobile Nigeria',
  '621-25': 'MTN Nigeria',
  '621-40': 'Airtel Nigeria',
  '310-410': 'AT&T (US)',
  '310-004': 'Verizon (US)',
  '310-260': 'T-Mobile (US)',
  '234-15': 'Vodafone UK',
  '234-10': 'O2 UK',
  '234-20': 'Three UK',
  '234-30': 'EE UK',
  '262-01': 'Telekom DE',
  '262-02': 'Vodafone DE',
  '262-03': 'O2 DE',
};

/** Human-readable operator label for an MCC/MNC pair. */
export function operatorLabel(mcc: number | null | undefined, mnc: number | null | undefined): string | null {
  if (mcc == null || mnc == null) return null;
  return OPERATOR_BY_MCC_MNC[`${mcc}-${mnc}`] ?? null;
}

/** Build a MapWorkspace-compatible point from a cell lookup. */
export function towerToMapPoint(resp: CellLookupResponse): TowerPoint | null {
  if (!resp.looked_up || resp.lat == null || resp.lon == null) return null;
  const op = operatorLabel(resp.mcc, resp.mnc);
  return {
    lat: resp.lat,
    lon: resp.lon,
    radius: resp.range_meters ?? 2000,
    confidence: 0.5,
    source: `${resp.provider} cell tower`,
    label: [
      op ? `Serving cell ${op}` : 'Serving cell',
      resp.mcc != null && resp.mnc != null ? `MCC ${resp.mcc} MNC ${resp.mnc}` : null,
      resp.lac != null ? `LAC ${resp.lac}` : null,
      resp.cell_id != null ? `CI ${resp.cell_id}` : null,
    ].filter(Boolean).join(' - '),
  };
}

/** Compact tower fingerprint used in case observation labels. */
export function towerObservationDetail(resp: CellLookupResponse): string {
  const parts: string[] = [];
  const op = operatorLabel(resp.mcc, resp.mnc);
  if (op) parts.push(op);
  if (resp.mcc != null && resp.mnc != null) parts.push(`MCC ${resp.mcc} / MNC ${resp.mnc}`);
  if (resp.lac != null) parts.push(`LAC ${resp.lac}`);
  if (resp.cell_id != null) parts.push(`cell ${resp.cell_id}`);
  if (resp.range_meters != null) parts.push(`~${resp.range_meters}m radius`);
  if (resp.radio) parts.push(`radio ${resp.radio}`);
  return parts.join('; ') || resp.detail;
}
