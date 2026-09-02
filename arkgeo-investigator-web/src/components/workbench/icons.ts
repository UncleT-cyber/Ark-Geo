/**
 * Central icon registry — maps THE ARK concepts to Lucide SVG icons.
 *
 * Single source of truth so TabBar, ActivityBar, TopBar, Dropdowns, and
 * tool views all render the same icon family.  No consumer emojis.
 */
import {
  Globe,
  FileSearch,
  ScanText,
  Compass,
  ShieldCheck,
  FileText,
  Settings,
  Upload,
  FolderTree,
  Microscope,
  ClipboardList,
  Hexagon,
  User,
  Search,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  Check,
  X,
  HelpCircle,
  ArrowRight,
  Image as ImageIcon,
  BarChart3,
  FileWarning,
  Network,
  ShieldHalf,
  ChevronLeft,
  MapPin,
  FolderKanban,
  Terminal,
  Activity,
  Gauge,
  Siren,
  Crosshair,
  Radar,
  FolderSearch,
  Cpu,
  Bug,
  ShieldAlert,
  Wifi,
  PackageSearch,
  Frown,
  GitBranch,
  Zap,
  type LucideIcon,
} from 'lucide-react';

/** Tool-id → primary Lucide icon (used by tabs, dropdowns, launcher). */
export const TOOL_ICONS = {
  overview: Microscope,
  spatial: Globe,
  fileforensics: FileSearch,
  discovery: Compass,
  provenance: ShieldCheck,
  vision: ScanText,
  report: FileText,
} as const;

/** Activity-bar DOMAIN icons — investigation domains, not individual tools. */
export const DOMAIN_ICONS = {
  image: ImageIcon,
  network: Network,
  cases: FolderKanban,
  secops: ShieldHalf,
} as const;

/** Threat & SecOps domain sub-view icons (sidebar navigation within SECOPS domain). */
export const SECOPS_ICONS = {
  siem: Gauge,
  ids_ips: Siren,
  threat_hunting: Crosshair,
  detection: Radar,
  incident_mgmt: FolderSearch,
  secops_dashboard: Activity,
} as const;

/** Footer settings icon (system & API provider configuration — NEVER admin). */
export const FOOTER_ICONS = {
  settings: Settings,
  profile: User,
} as const;

/** Vulnerability Assessment 7-track module icons (VULN domain rail). */
export const VULN_ICONS = {
  nuclei: Zap,
  openvas: ShieldAlert,
  nmap: Network,
  owasp: PackageSearch,
  proton: Bug,
  shadow: GitBranch,
  aegis: Cpu,
} as const;

/** Image investigation sub-view icons (sidebar navigation within IMAGE domain). */
export const SUBVIEW_ICONS = {
  overview: Microscope,
  spatial: MapPin,
  fileforensics: FileSearch,
  vision: ScanText,
  discovery: Compass,
  provenance: ShieldCheck,
  report: FileText,
} as const;

/** Sidebar collapse toggle icons — arrow direction reflects the collapse action.
 *  Expanded → ChevronLeft (collapse toward the left); Collapsed → ChevronRight. */
export const SIDEBAR_ICONS = {
  collapse: ChevronLeft,
  expand: ChevronRight,
} as const;

/** Bottom console tab icons. */
export const CONSOLE_ICONS = {
  problems: AlertTriangle,
  log: Activity,
  plan: ClipboardList,
  agent: Cpu,
  evidence: FileSearch,
  audit: ShieldCheck,
  terminal: Terminal,
} as const;

/** Activity-bar area → Lucide icon. */
export const ACTIVITY_ICONS = {
  upload: Upload,
  explorer: FolderTree,
  analysis: Microscope,
  settings: Settings,
} as const;

/** Generic UI icons (re-exported for convenience). */
export const UI_ICONS = {
  brand: Hexagon,
  search: Search,
  settings: Settings,
  user: User,
  upload: Upload,
  chevronDown: ChevronDown,
  chevronRight: ChevronRight,
  alert: AlertTriangle,
  check: Check,
  close: X,
  help: HelpCircle,
  arrowRight: ArrowRight,
  image: ImageIcon,
  chart: BarChart3,
  fileWarning: FileWarning,
} as const;

export type { LucideIcon };
