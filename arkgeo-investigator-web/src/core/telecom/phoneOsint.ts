/**
 * phoneOsint — public-footprint aggregator for a phone number.
 *
 * Returns messenger / search links ONLY (WhatsApp, Telegram, social
 * search, OSINT search engines). No private-resolver or surveillance
 * capabilities: number-to-identity attribution beyond public search is
 * out of scope and requires lawful authorization.
 */
import { normalizeE164, countryCodeFromE164 } from './phoneParser';

export interface PhoneFootprintLink {
  name: string;
  url: string;
  note: string;
  kind: 'messenger' | 'social' | 'osint';
}

export interface PhoneOsintFootprint {
  phone: string;
  e164: string | null;
  countryCode: string | null;
  links: PhoneFootprintLink[];
  detail: string;
}

const digitsOnly = (e164: string) => e164.replace(/[^\d]/g, '');

/** Build the public footprint for a raw phone string. */
export function buildPhoneOsintFootprint(rawPhone: string): PhoneOsintFootprint {
  const e164 = normalizeE164(rawPhone);
  if (!e164) {
    return {
      phone: rawPhone.trim(),
      e164: null,
      countryCode: null,
      links: [],
      detail: 'Invalid phone number - no footprint generated',
    };
  }
  const d = digitsOnly(e164);
  const country = countryCodeFromE164(e164);

  const links: PhoneFootprintLink[] = [
    { name: 'WhatsApp', url: `https://wa.me/${d}`, note: 'Messaging reachability via wa.me deep link.', kind: 'messenger' },
    { name: 'Telegram', url: `https://t.me/+${d}`, note: 'Telegram resolves the number when a linked account exists.', kind: 'messenger' },
    { name: 'Signal', url: `https://signal.me/#p/${d}`, note: 'Signal contact deep link (only if the user opted into the URL format).', kind: 'messenger' },
    { name: 'Google Search', url: `https://www.google.com/search?q=${encodeURIComponent('"' + e164 + '"')}`, note: 'Web search for the quoted E.164 number.', kind: 'osint' },
    { name: 'DuckDuckGo', url: `https://duckduckgo.com/?q=${encodeURIComponent(e164)}`, note: 'Privacy-first web search.', kind: 'osint' },
    { name: 'Truecaller', url: `https://www.truecaller.com/search/${d}`, note: 'Community caller-ID directory (result varies by region / coverage).', kind: 'osint' },
    { name: 'Facebook', url: `https://www.facebook.com/search/top/?q=${encodeURIComponent(e164)}`, note: 'Facebook search for the number string.', kind: 'social' },
    { name: 'Instagram', url: `https://www.instagram.com/explore/search/keyword/?q=${encodeURIComponent(e164)}`, note: 'Instagram keyword search.', kind: 'social' },
    { name: 'TikTok', url: `https://www.tiktok.com/search/user?q=${encodeURIComponent(e164)}`, note: 'TikTok user search.', kind: 'social' },
  ];

  return {
    phone: rawPhone.trim(),
    e164,
    countryCode: country,
    links,
    detail: `${links.length} public footprint vectors (messenger + search only)`,
  };
}
