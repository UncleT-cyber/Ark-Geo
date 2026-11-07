/**
 * UseCasesView — the quick-start catalog.
 *
 * Reached from the sidebar (INVESTIGATIONS → Use Cases). Each card opens the
 * relevant workspace and tooling; planned workflows are shown but disabled so
 * the capability surface stays discoverable without dead navigation.
 */
import { ShieldCheck, Network, Image as ImageIcon, Globe, MailSearch, Crosshair, Workflow } from 'lucide-react';
import { USE_CASES } from './InvestigationNavigation';

type UseCaseId = typeof USE_CASES[number]['id'];

interface UseCasesViewProps {
  onUseCase: (id: UseCaseId) => void;
}

const USE_CASE_ICONS = [ShieldCheck, Network, ImageIcon, Globe, MailSearch, Crosshair, Workflow];

export function UseCasesView({ onUseCase }: UseCasesViewProps) {
  return (
    <div className="usecases-view">
      <div className="usecases-grid">
        {USE_CASES.map((item, index) => {
          const Icon = USE_CASE_ICONS[index];
          const planned = item.id === 'phishing' || item.id === 'custom';
          return (
            <button key={item.id} type="button" className="usecase-card" disabled={planned}
              title={item.note} onClick={() => onUseCase(item.id)}>
              <span className="usecase-card-icon"><Icon size={18} aria-hidden="true" /></span>
              <span className="usecase-card-body">
                <span className="usecase-card-name">
                  {item.name}
                  {planned && <small>Planned</small>}
                  {item.id === 'assessment' && <small>Passive</small>}
                </span>
                <span className="usecase-card-note">{item.note}</span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
