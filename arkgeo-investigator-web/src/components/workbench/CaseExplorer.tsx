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
import { FolderKanban, Clock, Shield, ArrowRight, Search } from 'lucide-react';
import { useInvestigation, type SavedCase, type SavedCaseDomain } from './useInvestigation';

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
          <div className="case-explorer-title">CASE EXPLORER</div>
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
