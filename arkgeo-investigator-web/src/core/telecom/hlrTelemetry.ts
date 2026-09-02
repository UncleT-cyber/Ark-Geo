/**
 * hlrTelemetry — normalize raw HLR (IPQS) responses into structured
 * telemetry for the Telecom tab: active / original / ported carrier,
 * MCC/MNC, line type, and geographic hints.
 */
import type { HlrLookupResponse } from '../../types';
import { classifyLineType, countryCodeFromE164, normalizeE164 } from './phoneParser';

export interface HlrTelemetry {
  phone: string;
  e164: string | null;
  countryCode: string | null;
  lineType: 'mobile' | 'landline' | 'voip' | 'unknown';
  lineDetail: string;
  activeCarrier: string | null;
  originalCarrier: string | null;
  ported: boolean;
  mcc: string | null;
  mnc: string | null;
  location: string | null;
  isVoip: boolean | null;
  isPrepaid: boolean | null;
  liveStateAvailable: boolean;
  active: boolean | null;
  source: string;
}

/**
 * Build telemetry from a backend /telecom/hlr-lookup response.
 * `ported` is true when the provider reports a different original carrier
 * than the active one (carrier_ported carries the original network).
 * When `live_state_available` is false the row is FREE TIER — derived from
 * public numbering plans (no HLR API key); live ON/OFF is unknown.
 */
export function buildHlrTelemetry(rawPhone: string, resp: HlrLookupResponse): HlrTelemetry {
  const e164 = resp.phone_e164 || normalizeE164(rawPhone);
  const carrier = resp.carrier || null;
  const original = resp.carrier_ported || null;
  const cls = classifyLineType(resp.line_type, resp.is_voip, carrier);
  const live = resp.live_state_available ?? true;
  const loc = resp.location;
  let location: string | null = null;
  if (typeof loc === 'string') location = loc;
  else if (loc && typeof loc === 'object') {
    const z = (loc as Record<string, unknown>).zone;
    if (typeof z === 'string') location = z;
  }

  return {
    phone: rawPhone.trim(),
    e164,
    countryCode: resp.country_code || (e164 ? countryCodeFromE164(e164) : null),
    lineType: cls.line_type,
    lineDetail: cls.detail,
    activeCarrier: carrier,
    originalCarrier: original,
    ported: Boolean(original && original !== carrier),
    mcc: resp.mcc || null,
    mnc: resp.mnc || null,
    location,
    isVoip: resp.is_voip ?? null,
    isPrepaid: resp.is_prepaid ?? null,
    liveStateAvailable: live,
    active: resp.active ?? null,
    source: live ? 'IPQS HLR' : 'FREE NUMBERING PLAN',
  };
}

/** Short label used in case observations (never the raw number truncated). */
export function hlrObservationDetail(t: HlrTelemetry): string {
  const parts: string[] = [];
  if (t.lineType !== 'unknown') parts.push(`line ${t.lineType}`);
  if (t.activeCarrier) parts.push(`carrier ${t.activeCarrier}`);
  if (t.ported) parts.push('ported (original network reported)');
  if (t.mcc && t.mnc) parts.push(`MCC ${t.mcc} / MNC ${t.mnc}`);
  if (t.isPrepaid) parts.push('prepaid');
  if (t.location) parts.push(t.location);
  if (!t.liveStateAvailable) parts.push('live state: free-tier (no HLR key)');
  return parts.join('; ') || 'No carrier signal returned';
}
