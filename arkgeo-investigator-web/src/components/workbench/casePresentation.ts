/**
 * casePresentation — pure presentation helpers for the cross-domain CASES layer.
 *
 * The backend case engine (GET /cases, GET /cases/{id}) is the source of truth;
 * these functions turn its payloads into the labels the Case Explorer renders.
 * Kept pure so they are unit-testable without a DOM or a live backend.
 */
import type {
  CaseSummary,
  CaseView,
  CrossDomainContradiction,
} from '../../types';

/** Human label for a domain id; "cross" reads as CROSS-DOMAIN. */
export function domainLabel(domain: string): string {
  if (domain === 'cross') return 'CROSS-DOMAIN';
  return (domain || 'unknown').toUpperCase();
}

/** Short "IMAGE + OSINT" style label for a case's domain set. */
export function domainsLabel(domains: string[]): string {
  if (!domains || domains.length === 0) return 'NO EVIDENCE';
  if (domains.length >= 2) return domains.map(d => d.toUpperCase()).join(' + ');
  return domainLabel(domains[0]);
}

/** True when the case spans ≥2 domains (the Phase G exit-gate condition). */
export function isCrossDomain(view: Pick<CaseView, 'domains'>): boolean {
  return (view.domains?.length ?? 0) >= 2;
}

/** Severity band for a case summary — cross-domain conflicts rank highest. */
export function caseRisk(summary: CaseSummary): 'critical' | 'medium' | 'low' {
  if (summary.cross_domain_contradictions > 0) return 'critical';
  if ((summary.domains?.length ?? 0) >= 2) return 'medium';
  return 'low';
}

/** One-line description of a cross-domain contradiction for the audit view. */
export function describeContradiction(c: CrossDomainContradiction): string {
  return `${c.src_domain.toUpperCase()} (${c.src_tool}) contradicts ` +
    `${c.dst_domain.toUpperCase()} (${c.dst_tool})`;
}

/** Findings grouped by their originating domain, cross-domain first. */
export function groupFindingsByDomain(
  view: CaseView,
): { domain: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const f of view.findings) {
    const d = f.domain || 'unattributed';
    counts.set(d, (counts.get(d) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([domain, count]) => ({ domain, count }))
    .sort((a, b) => b.count - a.count);
}

/** Case status → a display label; the rollup is the least-advanced session. */
export function statusLabel(status: string): string {
  switch (status) {
    case 'done': return 'CLOSED';
    case 'paused': return 'PAUSED';
    case 'running': return 'RUNNING';
    case 'approved': return 'APPROVED';
    case 'proposed': return 'PROPOSED';
    case 'failed': return 'FAILED';
    case 'rejected': return 'REJECTED';
    default: return (status || 'unknown').toUpperCase();
  }
}
