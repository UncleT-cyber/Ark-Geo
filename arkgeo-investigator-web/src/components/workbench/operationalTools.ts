/**
 * Centralized operational tool registry.
 *
 * Single source of truth for the tools surfaced by the ARK header `+` menu and
 * rendered by the ARK Operational Inspector. Adding a tool is a one-line change
 * here — the menu, keyboard handling and inspector all read from this list, so
 * no rendering logic is hardcoded per tool in the header.
 */
import {
  AlertTriangle, Activity, ClipboardList, Cpu, FileSearch, ShieldCheck, Globe,
  type LucideIcon,
} from 'lucide-react';

export type OperationalToolId =
  | 'problems' | 'log' | 'plan' | 'agent' | 'evidence' | 'audit' | 'browser';

/**
 * Where a tool presents. `inspector` tools are dismissible overlays inside the
 * ARK conversation dock; `workspace` tools take over the central application
 * area (replacing System Overview / the active investigation view) — they are a
 * first-class application surface, not a panel squeezed into the dock.
 */
export type OperationalSurface = 'inspector' | 'workspace';

export interface OperationalTool {
  id: OperationalToolId;
  label: string;
  /** Short secondary line shown in the `+` menu. */
  description: string;
  icon: LucideIcon;
  /** Presentation surface (defaults to `inspector`). */
  surface: OperationalSurface;
  /** Browser requires the managed runtime; other tools are always available. */
  requiresBrowser?: boolean;
}

export const OPERATIONAL_TOOLS: readonly OperationalTool[] = [
  { id: 'problems', label: 'Problems', description: 'Errors, failures and warnings', icon: AlertTriangle, surface: 'inspector' },
  { id: 'log', label: 'Analysis Log', description: 'Execution events and tool output', icon: Activity, surface: 'inspector' },
  { id: 'plan', label: 'Plan', description: 'Objective, steps and progress', icon: ClipboardList, surface: 'inspector' },
  { id: 'agent', label: 'Agent', description: 'Specialists and execution detail', icon: Cpu, surface: 'inspector' },
  { id: 'evidence', label: 'Evidence', description: 'Artifacts, provenance and hashes', icon: FileSearch, surface: 'inspector' },
  { id: 'audit', label: 'Audit', description: 'Approvals and authorization history', icon: ShieldCheck, surface: 'inspector' },
  { id: 'browser', label: 'Browser', description: 'Managed browser sessions', icon: Globe, surface: 'workspace', requiresBrowser: true },
] as const;

/** Console-backed inspector tools map 1:1 onto the BottomPanel tabs. */
export type ConsoleToolId = Exclude<OperationalToolId, 'browser'>;

export function operationalTool(id: OperationalToolId): OperationalTool {
  return OPERATIONAL_TOOLS.find(t => t.id === id) ?? OPERATIONAL_TOOLS[0];
}

export function isConsoleTool(id: OperationalToolId): id is ConsoleToolId {
  return operationalTool(id).surface === 'inspector';
}

/** Whether a tool presents in the central workspace rather than the dock. */
export function isWorkspaceTool(id: OperationalToolId): boolean {
  return operationalTool(id).surface === 'workspace';
}
