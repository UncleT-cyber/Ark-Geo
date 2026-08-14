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
