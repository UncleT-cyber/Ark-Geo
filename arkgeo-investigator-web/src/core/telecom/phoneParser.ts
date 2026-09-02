/**
 * phoneParser — E.164 parsing, ITU country-code resolution and line-type
 * classification for the Telecom & Phone Intelligence module.
 *
 * Pure, side-effect-free helpers used by hlrTelemetry / phoneOsint and by
 * the Network Workspace Telecom tab. Operates ONLY on user-supplied phone
 * numbers for legitimate carrier / footprint OSINT.
 */
export const E164_MAX_DIGITS = 15;
export const E164_MIN_DIGITS = 7;

/** Strip dialing decoration and normalize to `+` + digits (empty if invalid). */
export function normalizeE164(input: string): string | null {
  let s = (input || '').trim();
  if (!s) return null;
  s = s.replace(/[\s\-().]/g, '');
  if (s.startsWith('00')) s = '+' + s.slice(2);
  if (!s.startsWith('+')) s = '+' + s;
  const digits = s.slice(1);
  if (!/^\d+$/.test(digits)) return null;
  if (digits.length < E164_MIN_DIGITS || digits.length > E164_MAX_DIGITS) return null;
  return s;
}

/** Longest-match ITU-T E.164 country code (e.g. '+234803...' -> '234'). */
export function itucodeFromE164(e164: string): string | null {
  const digits = (e164 || '').replace(/[^\d]/g, '');
  if (!digits) return null;
  let match: string | null = null;
  for (const [itu] of ITU_COUNTRY_CODES) {
    if (digits.startsWith(itu) && (!match || itu.length > match.length)) match = itu;
  }
  return match;
}

export interface LineTypeClass {
  line_type: 'mobile' | 'landline' | 'voip' | 'unknown';
  detail: string;
}

/**
 * Classify line type from provider signals, preferring hard signals
 * (voip flags, explicit line types) over carrier-name heuristics.
 */
export function classifyLineType(
  rawLineType: string | null | undefined,
  isVoip: boolean | null | undefined,
  carrier: string | null | undefined,
): LineTypeClass {
  const t = (rawLineType || '').toLowerCase();
  if (t.includes('mobile') || t.includes('cell')) return { line_type: 'mobile', detail: 'Mobile - cellular subscriber line' };
  if (t.includes('landline') || t.includes('fixed') || t.includes('toll')) return { line_type: 'landline', detail: 'Fixed / landline subscriber line' };
  if (t.includes('voip') || isVoip) return { line_type: 'voip', detail: 'Voice-over-IP virtual number' };
  if (t) return { line_type: 'unknown', detail: `Provider reported "${rawLineType}"` };
  const c = (carrier || '').toLowerCase();
  if (/(mobile|cell|cellular|wireless)/.test(c)) return { line_type: 'mobile', detail: `Carrier "${carrier}" implies mobile` };
  if (/(landline|fixed|voip)/.test(c)) return { line_type: c.includes('voip') ? 'voip' : 'landline', detail: `Carrier "${carrier}" implies non-mobile` };
  return { line_type: 'unknown', detail: 'No line-type signal available' };
}

/** Resolve the ISO country code from an E.164 string (longest-match ITU). */
export function countryCodeFromE164(e164: string): string | null {
  const itu = itucodeFromE164(e164);
  if (!itu) return null;
  return ITU_BY_CODE[itu] ?? null;
}

/** ITU region grouping used by the Telecom tab UI. */
export type ItuRegion = 'North America' | 'Latin America' | 'EMEA' | 'Asia Pacific';

/** ITU region label for a resolved country code. */
export function regionFromCountryCode(country: string): ItuRegion | null {
  return REGION_BY_COUNTRY[country] ?? null;
}

/** Common ITU-T E.164 country codes (callable subset) -> ISO 3166-1 alpha-2. */
const ITU_BY_CODE: Record<string, string> = {
  '1': 'US', '7': 'RU', '20': 'EG', '27': 'ZA', '30': 'GR',
  '31': 'NL', '32': 'BE', '33': 'FR', '34': 'ES', '36': 'HU',
  '39': 'IT', '40': 'RO', '41': 'CH', '43': 'AT', '44': 'GB',
  '45': 'DK', '46': 'SE', '47': 'NO', '48': 'PL', '49': 'DE',
  '51': 'PE', '52': 'MX', '53': 'CU', '54': 'AR', '55': 'BR',
  '56': 'CL', '57': 'CO', '58': 'VE', '60': 'MY', '61': 'AU',
  '62': 'ID', '63': 'PH', '64': 'NZ', '65': 'SG', '66': 'TH',
  '81': 'JP', '82': 'KR', '84': 'VN', '86': 'CN', '90': 'TR',
  '91': 'IN', '92': 'PK', '93': 'AF', '94': 'LK', '95': 'MM',
  '98': 'IR', '212': 'MA', '213': 'DZ', '216': 'TN', '218': 'LY',
  '220': 'GM', '221': 'SN', '225': 'CI', '226': 'BF', '227': 'NE',
  '228': 'TG', '229': 'BJ', '230': 'MU', '231': 'LR', '233': 'GH',
  '234': 'NG', '235': 'TD', '237': 'CM', '238': 'CV', '240': 'GQ',
  '242': 'CG', '243': 'CD', '244': 'AO', '245': 'GW', '249': 'SD',
  '250': 'RW', '251': 'ET', '252': 'SO', '253': 'DJ', '254': 'KE',
  '255': 'TZ', '256': 'UG', '257': 'BI', '258': 'MZ', '260': 'ZM',
  '263': 'ZW', '264': 'NA', '265': 'MW', '266': 'LS', '268': 'SZ',
  '353': 'IE', '354': 'IS', '355': 'AL', '356': 'MT', '357': 'CY',
  '358': 'FI', '359': 'BG', '370': 'LT', '371': 'LV', '372': 'EE',
  '373': 'MD', '374': 'AM', '375': 'BY', '376': 'AD', '380': 'UA',
  '381': 'RS', '382': 'ME', '385': 'HR', '386': 'SI', '387': 'BA',
  '389': 'MK', '420': 'CZ', '421': 'SK', '423': 'LI', '880': 'BD',
  '886': 'TW', '960': 'MV', '961': 'LB', '962': 'JO', '963': 'SY',
  '964': 'IQ', '965': 'KW', '966': 'SA', '967': 'YE', '968': 'OM',
  '971': 'AE', '972': 'IL', '973': 'BH', '974': 'QA', '975': 'BT',
  '976': 'MN', '977': 'NP', '992': 'TJ', '993': 'TM', '994': 'AZ',
  '995': 'GE', '996': 'KG', '998': 'UZ',
};

const ITU_COUNTRY_CODES: [string, string][] = Object.entries(ITU_BY_CODE);

const REGION_BY_COUNTRY: Record<string, ItuRegion> = {
  US: 'North America', CA: 'North America',
  MX: 'Latin America', PE: 'Latin America', AR: 'Latin America', BR: 'Latin America',
  CL: 'Latin America', CO: 'Latin America', CU: 'Latin America', VE: 'Latin America',
  GB: 'EMEA', DE: 'EMEA', FR: 'EMEA', IT: 'EMEA', ES: 'EMEA', NL: 'EMEA', BE: 'EMEA',
  CH: 'EMEA', AT: 'EMEA', SE: 'EMEA', NO: 'EMEA', DK: 'EMEA', FI: 'EMEA', IE: 'EMEA',
  PT: 'EMEA', PL: 'EMEA', RU: 'EMEA', UA: 'EMEA', NG: 'EMEA', ZA: 'EMEA', GH: 'EMEA',
  KE: 'EMEA', ET: 'EMEA', MA: 'EMEA', EG: 'EMEA', SA: 'EMEA', AE: 'EMEA', TR: 'EMEA',
  IL: 'EMEA', IN: 'Asia Pacific', PK: 'Asia Pacific', BD: 'Asia Pacific', CN: 'Asia Pacific',
  JP: 'Asia Pacific', KR: 'Asia Pacific', SG: 'Asia Pacific', MY: 'Asia Pacific',
  ID: 'Asia Pacific', PH: 'Asia Pacific', TH: 'Asia Pacific', VN: 'Asia Pacific',
  AU: 'Asia Pacific', NZ: 'Asia Pacific', TW: 'Asia Pacific', LK: 'Asia Pacific',
  MM: 'Asia Pacific', NP: 'Asia Pacific', AF: 'Asia Pacific', IR: 'Asia Pacific',
};
