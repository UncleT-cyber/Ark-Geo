/**
 * NeutralWorkspace — the default central surface for a new investigation.
 *
 * It is deliberately minimal: an investigation identity line, a clear empty
 * state, and direct access to the available workspaces and investigation tools.
 * It is NOT the Image Intelligence System Overview (that belongs to Image
 * Intelligence, and only appears once the operator selects that workspace) and
 * it is NOT a second analytics dashboard.
 */
import React from 'react';
import { Compass, Image as ImageIcon, Globe, ShieldCheck, FolderSearch, type LucideIcon } from 'lucide-react';

export type NeutralWorkspaceId = 'image' | 'network' | 'secops' | 'browser' | 'cases';

interface NeutralWorkspaceProps {
  /** Investigation title (its identity line). */
  title: string;
  /** Investigation / case identifiers, for the identity line. */
  investigationId: string;
  caseId: string | null;
  /** Open a workspace for this investigation. */
  onSelectWorkspace: (id: NeutralWorkspaceId) => void;
  /** Workspaces the current build can actually open. */
  browserAvailable: boolean;
}

const WORKSPACES: {
  id: NeutralWorkspaceId; label: string; hint: string; icon: LucideIcon;
}[] = [
  { id: 'image', label: 'Image Intelligence', hint: 'EXIF, vision, geolocation and forensic metadata', icon: ImageIcon },
  { id: 'network', label: 'Network Intelligence', hint: 'Discovery, traffic, HTTP and security testing', icon: Globe },
  { id: 'secops', label: 'Threat & SecOps', hint: 'Detection, triage and incident response', icon: ShieldCheck },
  { id: 'browser', label: 'Browser', hint: 'Managed, screenshot-first browsing workspace', icon: Compass },
  { id: 'cases', label: 'Case Explorer', hint: 'Saved investigations and the audit vault', icon: FolderSearch },
];

export function NeutralWorkspace({
  title, investigationId, caseId, onSelectWorkspace, browserAvailable,
}: NeutralWorkspaceProps) {
  return (
    <div className="neutral-workspace">
      <header className="neutral-workspace-head">
        <div className="neutral-workspace-identity">
          <span className="neutral-workspace-kicker">Investigation</span>
          <h1 className="neutral-workspace-title">{title}</h1>
          <div className="neutral-workspace-ids mono">
            <span>INV {investigationId.slice(0, 8)}</span>
            {caseId && <span>· CASE {caseId}</span>}
            {!caseId && <span className="neutral-workspace-nocase">· no case yet</span>}
          </div>
        </div>
      </header>

      <div className="neutral-workspace-body">
        <div className="neutral-workspace-empty">
          <Compass size={26} aria-hidden="true" />
          <strong>New investigation</strong>
          <p>Select a workspace to begin. ARK is ready in the panel beside you — ask a question or run a command to start.</p>
        </div>

        <div className="neutral-workspace-grid" role="list">
          {WORKSPACES.map(({ id, label, hint, icon: Icon }) => {
            const disabled = id === 'browser' && !browserAvailable;
            return (
              <button
                key={id}
                type="button"
                role="listitem"
                className="neutral-workspace-card"
                disabled={disabled}
                title={disabled ? 'Managed browser runtime unavailable' : hint}
                onClick={() => !disabled && onSelectWorkspace(id)}
              >
                <Icon size={18} />
                <span className="neutral-workspace-card-label">{label}</span>
                <span className="neutral-workspace-card-hint">{disabled ? 'Unavailable' : hint}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
