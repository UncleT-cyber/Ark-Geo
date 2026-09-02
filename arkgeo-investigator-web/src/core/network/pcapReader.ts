/**
 * pcapReader — minimal classic .pcap (pcap-ng NOT yet supported) parser.
 *
 * Phase-1 scope: Ethernet (linktype 1) / NULL (0) / RAW (101) frames with
 * IPv4/IPv6 headers. Produces packet summaries + aggregated connection
 * candidates (src:port -> dst:port over TCP/UDP). pcapng and tshark
 * enrichment are a later phase; this reader stays dependency-free so the
 * Traffic Analysis tab can ingest a capture without external binaries.
 */
export interface PcapPacketSummary {
  ts: number;
  src: string;
  dst: string;
  sport: number | null;
  dport: number | null;
  proto: 'TCP' | 'UDP' | 'ICMP' | 'OTHER';
  len: number;
  flags: number | null;
}

export interface PcapConnection {
  src: string;
  sport: number | null;
  dst: string;
  dport: number | null;
  proto: 'TCP' | 'UDP' | 'ICMP' | 'OTHER';
  packets: number;
  bytes: number;
  firstTs: number;
  lastTs: number;
}

export interface PcapResult {
  ok: boolean;
  detail: string;
  packets: PcapPacketSummary[];
  connections: PcapConnection[];
  protoCounts: Record<string, number>;
  uniqueIps: string[];
  captureTimeMs: number;
}

const TCP = 6;
const UDP = 17;
const ICMP = 1;

function fmtIp4(b: DataView, off: number): string {
  return `${b.getUint8(off)}.${b.getUint8(off + 1)}.${b.getUint8(off + 2)}.${b.getUint8(off + 3)}`;
}

function fmtIp6(b: DataView, off: number): string {
  const parts: string[] = [];
  for (let i = 0; i < 8; i++) parts.push(b.getUint16(off + i * 2).toString(16));
  return parts.join(':');
}

/** Parse a classic .pcap byte array. Returns ok=false (never throws) on bad data. */
export function parsePcap(buf: ArrayBuffer): PcapResult {
  const view = new DataView(buf);
  const result: PcapResult = {
    ok: true,
    detail: '',
    packets: [],
    connections: [],
    protoCounts: {},
    uniqueIps: [],
    captureTimeMs: 0,
  };

  try {
    if (view.byteLength < 24) throw new Error('Not a pcap file (missing 24-byte global header)');
    const magic = view.getUint32(0, false);
    let little = false;
    if (magic === 0xd4c3b2a1) little = true;
    else if (magic === 0xa1b2c3d4) little = false;
    else throw new Error('Not a classic pcap (magic mismatch)');

    const g = (off: number) => view.getUint32(off, little);
    const linktype = g(20);
    if (![0, 1, 101].includes(linktype)) {
      throw new Error(`Unsupported linktype ${linktype} (Ethernet/NULL/RAW only in this phase)`);
    }

    const capStart = Date.now();
    let off = 24;
    while (off + 16 <= view.byteLength) {
      const tsSec = g(off);
      const tsUsec = g(off + 4);
      const inclLen = g(off + 8);
      const origLen = g(off + 12);
      off += 16;
      if (off + inclLen > view.byteLength) break;
      const ts = tsSec + tsUsec / 1e6;

      // Link layer -> network layer offset.
      let netOff = off;
      let etherType = 0;
      if (linktype === 1) {
        if (inclLen < 14) { off += inclLen; continue; }
        etherType = view.getUint16(off + 12, false);
        netOff = off + 14;
      } else if (linktype === 101) {
        etherType = view.getUint16(off, false);
        netOff = off;
      } else if (linktype === 0) {
        const family = view.getUint32(off, little);
        etherType = family === 2 ? 0x0800 : family === 24 ? 0x86dd : 0;
        netOff = off + 4;
      }

      let src = '?';
      let dst = '?';
      let proto: PcapPacketSummary['proto'] = 'OTHER';
      let sport: number | null = null;
      let dport: number | null = null;
      let flags: number | null = null;
      const pktLen = inclLen;

      if (etherType === 0x0800 && netOff + 20 <= off + inclLen) {
        const vihl = view.getUint8(netOff);
        const ihl = (vihl & 0x0f) * 4;
        if (netOff + ihl + 4 <= off + inclLen) {
          src = fmtIp4(view, netOff + 12);
          dst = fmtIp4(view, netOff + 16);
          const p = view.getUint8(netOff + 9);
          if (p === TCP) {
            proto = 'TCP';
            if (netOff + ihl + 4 <= off + inclLen) {
              sport = view.getUint16(netOff + ihl, false);
              dport = view.getUint16(netOff + ihl + 2, false);
              flags = view.getUint8(netOff + ihl + 13);
            }
          } else if (p === UDP) {
            proto = 'UDP';
            if (netOff + ihl + 4 <= off + inclLen) {
              sport = view.getUint16(netOff + ihl, false);
              dport = view.getUint16(netOff + ihl + 2, false);
            }
          } else if (p === ICMP) {
            proto = 'ICMP';
          }
        }
      } else if (etherType === 0x86dd && netOff + 40 <= off + inclLen) {
        src = fmtIp6(view, netOff + 8);
        dst = fmtIp6(view, netOff + 24);
        const p = view.getUint8(netOff + 6);
        if (p === TCP) proto = 'TCP';
        else if (p === UDP) proto = 'UDP';
        else if (p === ICMP) proto = 'ICMP';
        if ((p === TCP || p === UDP) && netOff + 48 <= off + inclLen) {
          sport = view.getUint16(netOff + 40, false);
          dport = view.getUint16(netOff + 42, false);
        }
      }

      result.packets.push({ ts, src, dst, sport, dport, proto, len: origLen, flags });
      result.protoCounts[proto] = (result.protoCounts[proto] || 0) + 1;
      for (const ip of [src, dst]) {
        if (ip !== '?' && !result.uniqueIps.includes(ip)) result.uniqueIps.push(ip);
      }
      off += inclLen;
    }

    result.captureTimeMs = Date.now() - capStart;
    result.detail = `Parsed ${result.packets.length} packets (linktype ${linktype}, ${result.uniqueIps.length} unique IPs)`;
  } catch (e) {
    result.ok = false;
    result.detail = e instanceof Error ? e.message : 'pcap parse failed';
  }

  // Aggregate connection candidates.
  const map = new Map<string, PcapConnection>();
  for (const p of result.packets) {
    const key = [p.proto, p.src, p.sport, p.dst, p.dport].join('|');
    const existing = map.get(key);
    if (existing) {
      existing.packets += 1;
      existing.bytes += p.len;
      existing.lastTs = Math.max(existing.lastTs, p.ts);
    } else {
      map.set(key, {
        src: p.src, sport: p.sport, dst: p.dst, dport: p.dport, proto: p.proto,
        packets: 1, bytes: p.len, firstTs: p.ts, lastTs: p.ts,
      });
    }
  }
  result.connections = Array.from(map.values()).sort((a, b) => b.bytes - a.bytes);
  return result;
}
