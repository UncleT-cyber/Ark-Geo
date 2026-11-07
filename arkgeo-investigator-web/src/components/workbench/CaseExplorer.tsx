/**
 * CaseExplorer — the cross-domain CASES layer.
 *
 * THE ARK's third top-level domain. A Case is the unit an analyst opens and
 * closes; it may hold image evidence, network evidence, or both. This view
 * is the saved-sessions and audit vault: it lists past investigations (from
 * the cross-domain case history), shows their entity relationships and audit
 * trails, and lets an analyst restore a past case to continue work.
 *
 * It binds to the shared investigation context, not the IMAGE domain
 * specifically — it works for any domain that has saved cases.
 */
import React from 'react';
import { FolderKanban, Clock, Shield, ArrowRight, Search, Network, AlertTriangle } from 'lucide-react';
import { useInvestigation, type SavedCase, type SavedCaseDomain } from './useInvestigation';
import { api } from '../../api';
import type { CaseSummary, CaseView } from '../../types';
import {
  domainsLabel,
  caseRisk,
  describeContradiction,
  statusLabel,
} from './casePresentation';

const RISK_COLOR: Record<SavedCase['risk'], string> = {
  critical: '#EF4444',
  medium: '#F59E0B',
  low: '#22C55E',
};

const DOMAIN_LABEL: Record<SavedCaseDomain, string> = {
  image: 'IMAGE',
  network: 'NETWORK',
  secops: 'SECOPS',
  telecom: 'TELECOM',
};

type DomainFilter = 'all' | SavedCaseDomain;

const FILTERS: { id: DomainFilter; label: string }[] = [
  { id: 'all', label: 'ALL' },
  { id: 'image', label: 'IMAGE' },
  { id: 'network', label: 'NETWORK' },
  { id: 'secops', label: 'SECOPS' },
  { id: 'telecom', label: 'TELECOM' },
];

interface CaseExplorerProps {
  onRestoreCase: (saved: SavedCase) => void;
}

export function CaseExplorer({ onRestoreCase }: CaseExplorerProps) {
  const inv = useInvestigation();
  const [query, setQuery] = React.useState('');
  const [domainFilter, setDomainFilter] = React.useState<DomainFilter>('all');
  const [backendCases, setBackendCases] = React.useState<CaseSummary[]>([]);
  const [openCase, setOpenCase] = React.useState<CaseView | null>(null);

  // Backend case engine (Phase G) — the authoritative cross-domain view.
  React.useEffect(() => {
    let cancelled = false;
    api.listCases()
      .then(r => { if (!cancelled) setBackendCases(r.cases ?? []); })
      .catch(() => { if (!cancelled) setBackendCases([]); });
    return () => { cancelled = true; };
  }, []);

  const openBackendCase = React.useCallback((caseId: string) => {
    api.getCase(caseId)
      .then(setOpenCase)
      .catch(() => setOpenCase(null));
  }, []);

  const counts = React.useMemo(() => {
    const c: Record<DomainFilter, number> = { all: inv.history.length, image: 0, network: 0, secops: 0, telecom: 0 };
    for (const h of inv.history) c[h.domain ?? 'image'] = (c[h.domain ?? 'image'] ?? 0) + 1;
    return c;
  }, [inv.history]);

  const filtered = inv.history.filter(h =>
    (domainFilter === 'all' || (h.domain ?? 'image') === domainFilter) &&
    (h.caseId.toLowerCase().includes(query.toLowerCase()) ||
     h.filename.toLowerCase().includes(query.toLowerCase()) ||
     h.source.toLowerCase().includes(query.toLowerCase()) ||
     (h.caseName ?? '').toLowerCase().includes(query.toLowerCase()) ||
     (h.tags ?? []).some(t => t.toLowerCase().includes(query.toLowerCase()))),
  );

  return (
    <div className="case-explorer">
      <div className="case-explorer-header">
        <div className="case-explorer-title-row">
          <FolderKanban className="w-5 h-5 case-explorer-title-icon" />
          <div className="case-explorer-title">Saved cases</div>
          <span className="case-explorer-count">{inv.history.length} saved</span>
        </div>
        <div className="case-explorer-search">
          <Search className="w-4 h-4 case-explorer-search-icon" />
          <input
            className="case-explorer-search-input"
            placeholder="Search by case ID, name, filename, source, or tag..."
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
        </div>
      </div>

      <div className="case-explorer-filters">
        {FILTERS.map(f => (
          <button
            key={f.id}
            className={`case-explorer-filter ${domainFilter === f.id ? 'case-explorer-filter-active' : ''}`}
            onClick={() => setDomainFilter(f.id)}
          >
            {f.label}
            <span className="case-explorer-filter-count">{counts[f.id] ?? 0}</span>
          </button>
        ))}
      </div>

      {inv.activeCase && (
        <div className="case-explorer-active">
          <div className="case-explorer-active-label">ACTIVE CASE</div>
          <div className="case-explorer-active-id mono">{inv.activeCase.id}</div>
          <div className="case-explorer-active-meta">
            <span>{inv.activeCase.title}</span>
            <span className="case-explorer-active-dot" />
            <span>{inv.activeCase.domain.toUpperCase()} domain</span>
            {inv.activeRun && <span className="case-explorer-active-conf">{Math.round(inv.activeRun.confidence * 100)}% confidence</span>}
          </div>
          {inv.auditTrail.length > 0 && (
            <div className="case-explorer-audit">
              <div className="case-explorer-audit-title"><Shield className="w-3 h-3" /> AUDIT TRAIL ({inv.auditTrail.length})</div>
              {inv.auditTrail.map(a => (
                <div key={a.id} className="case-explorer-audit-row">
                  <span className="case-explorer-audit-ts mono">{new Date(a.timestamp).toLocaleTimeString()}</span>
                  <span className="case-explorer-audit-action">{a.action}</span>
                  <span className="case-explorer-audit-detail">{a.detail}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {backendCases.length > 0 && (
        <div className="case-explorer-backend">
          <div className="case-explorer-section-label">
            <Network className="w-3 h-3" /> BACKEND CASES ({backendCases.length})
          </div>
          <div className="case-explorer-list">
            {backendCases.map(c => {
              const risk = caseRisk(c);
              return (
                <button
                  key={c.case_id}
                  className={`case-explorer-card ${openCase?.case_id === c.case_id ? 'case-explorer-card-open' : ''}`}
                  onClick={() => openBackendCase(c.case_id)}
                >
                  <div className="case-explorer-card-main">
                    <span className="case-explorer-card-id mono">{c.case_id}</span>
                    <span className="case-explorer-card-filename">{domainsLabel(c.domains)}</span>
                    <div className="case-explorer-card-tags">
                      <span className="case-explorer-tag case-explorer-tag-domain">{c.domain.toUpperCase()}</span>
                      <span className="case-explorer-tag">{c.investigation_count} inv</span>
                      <span className="case-explorer-tag">{c.evidence_count} evd</span>
                      <span className="case-explorer-tag">{c.finding_count} find</span>
                      {c.cross_domain_contradictions > 0 && (
                        <span className="case-explorer-tag" style={{ color: RISK_COLOR.critical, borderColor: RISK_COLOR.critical + '55' }}>
                          <AlertTriangle className="w-3 h-3" /> {c.cross_domain_contradictions} conflict
                        </span>
                      )}
                      <span className="case-explorer-tag" style={{ color: RISK_COLOR[risk], borderColor: RISK_COLOR[risk] + '55' }}>
                        {statusLabel(c.status)}
                      </span>
                    </div>
                  </div>
                  <div className="case-explorer-card-side">
                    <div className="case-explorer-card-ts">
                      <Clock className="w-3 h-3" /> {new Date(c.updated_at_ms).toLocaleDateString()}
                    </div>
                    <ArrowRight className="w-4 h-4 case-explorer-card-arrow" />
                  </div>
                </button>
              );
            })}
          </div>

          {openCase && (
            <div className="case-explorer-unified">
              <div className="case-explorer-unified-title">
                <Shield className="w-3 h-3" /> UNIFIED CASE · {domainsLabel(openCase.domains)}
              </div>
              <div className="case-explorer-unified-meta">
                {openCase.evidence_count} evidence · {openCase.finding_count} findings ·{' '}
                {openCase.investigation_ids.length} investigation(s)
              </div>
              {openCase.cross_domain_contradictions.length > 0 && (
                <div className="case-explorer-contradictions">
                  <div className="case-explorer-contradictions-title">
                    <AlertTriangle className="w-3 h-3" /> CROSS-DOMAIN CONTRADICTIONS ({openCase.cross_domain_contradictions.length})
                  </div>
                  {openCase.cross_domain_contradictions.map(c => (
                    <div key={c.edge_id} className="case-explorer-contradiction-row">
                      <span className="case-explorer-contradiction-desc">{describeContradiction(c)}</span>
                      {c.note && <span className="case-explorer-contradiction-note">{c.note}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="case-explorer-section-label">SAVED INVESTIGATIONS</div>
      {filtered.length === 0 ? (
        <div className="case-explorer-empty">
          <FolderKanban className="w-10 h-10 case-explorer-empty-icon" />
          <div className="case-explorer-empty-title">No saved cases</div>
          <div className="case-explorer-empty-text">
            Open the IMAGE domain and ingest an image to begin your first
            investigation. Saved cases appear here across all domains.
          </div>
        </div>
      ) : (
        <div className="case-explorer-list">
          {filtered.map(h => (
            <button key={h.caseId} className="case-explorer-card" onClick={() => onRestoreCase(h)}>
              <div className="case-explorer-card-main">
                <span className="case-explorer-card-id mono">{h.caseId}</span>
                <span className="case-explorer-card-filename">
                  {h.caseName || h.filename}
                  {h.caseName && <em className="case-explorer-card-file">{h.filename}</em>}
                </span>
                <div className="case-explorer-card-tags">
                  <span className="case-explorer-tag case-explorer-tag-domain">{DOMAIN_LABEL[h.domain ?? 'image']}</span>
                  <span className="case-explorer-tag">{h.source}</span>
                  <span className="case-explorer-tag">{h.tier}</span>
                  <span className="case-explorer-tag" style={{ color: RISK_COLOR[h.risk], borderColor: RISK_COLOR[h.risk] + '55' }}>
                    {h.risk}
                  </span>
                  {(h.tags ?? []).map(t => (
                    <span key={t} className="case-explorer-tag case-explorer-tag-custom">#{t}</span>
                  ))}
                </div>
              </div>
              <div className="case-explorer-card-side">
                <div className="case-explorer-card-conf">{Math.round(h.confidence * 100)}%</div>
                <div className="case-explorer-card-ts">
                  <Clock className="w-3 h-3" /> {new Date(h.timestamp).toLocaleDateString()}
                </div>
                <ArrowRight className="w-4 h-4 case-explorer-card-arrow" />
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
