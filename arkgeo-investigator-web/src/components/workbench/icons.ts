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
  PanelLeftClose,
  PanelLeftOpen,
  MapPin,
  FolderKanban,
  Terminal,
  Activity,
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
} as const;

/** Footer profile icon (user session — NEVER admin). */
export const FOOTER_ICONS = {
  profile: User,
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

/** Sidebar collapse toggle icons. */
export const SIDEBAR_ICONS = {
  collapse: PanelLeftClose,
  expand: PanelLeftOpen,
} as const;

/** Bottom console tab icons. */
export const CONSOLE_ICONS = {
  problems: AlertTriangle,
  log: Activity,
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
