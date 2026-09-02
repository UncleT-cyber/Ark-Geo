/** Admin console navigation registry — single source of truth. */
import {
  LayoutGrid, Users, ShieldCheck, KeyRound, Settings2, Gauge,
  Wrench, ScrollText, Heart, Cpu, type LucideIcon,
} from 'lucide-react';

export type AdminSectionId =
  | 'overview'
  | 'clients'
  | 'staff'
  | 'gateway'
  | 'ai'
  | 'policy'
  | 'quotas'
  | 'tooling'
  | 'audit'
  | 'support';

export interface AdminNavItem {
  id: AdminSectionId;
  label: string;
  icon: LucideIcon;
}

export const ADMIN_NAV: AdminNavItem[] = [
  { id: 'overview', label: 'Command Center', icon: LayoutGrid },
  { id: 'clients', label: 'Client Directory & Telemetry', icon: Users },
  { id: 'staff', label: 'Internal Staff & RBAC', icon: ShieldCheck },
  { id: 'gateway', label: 'Model Gateway & API Keys', icon: KeyRound },
  { id: 'ai', label: 'AI & OSINT Gateway', icon: Cpu },
  { id: 'policy', label: 'Tool Policy & Governors', icon: Settings2 },
  { id: 'quotas', label: 'Quotas & Usage Tracking', icon: Gauge },
  { id: 'tooling', label: 'Local Tooling Binaries', icon: Wrench },
  { id: 'audit', label: 'Audit Logs & Chain-of-Custody', icon: ScrollText },
  { id: 'support', label: 'Open Source & Support', icon: Heart },
];

export const ADMIN_SECTION_TITLES: Record<AdminSectionId, { title: string; subtitle: string }> = {
  overview: {
    title: 'Command Center',
    subtitle: 'Centralized control plane for The Ark Intelligence Platform.',
  },
  clients: {
    title: 'Client Directory & Telemetry',
    subtitle: 'External subscribers, plans, forensic session handshake logs.',
  },
  staff: {
    title: 'Internal Staff & RBAC',
    subtitle: 'Operators, admin roles and the granular permission matrix.',
  },
  gateway: {
    title: 'Model Gateway & API Keys',
    subtitle: 'Global cloud LLMs, OpenRouter, local Ollama and OSINT providers.',
  },
  ai: {
    title: 'AI & OSINT Gateway',
    subtitle: 'Gateway health, cloud/OSINT search probes and the local vision model rotator.',
  },
  policy: {
    title: 'Tool Policy & Governors',
    subtitle: 'Risk rules, passive vs active OSINT tool execution controls.',
  },
  quotas: {
    title: 'Quotas & Usage Tracking',
    subtitle: 'Token budgets, rate limits and API spend per plan tier.',
  },
  tooling: {
    title: 'Local Tooling Binaries',
    subtitle: 'ExifTool, Tesseract and local inference node health.',
  },
  audit: {
    title: 'Audit Logs & Chain-of-Custody',
    subtitle: 'Non-repudiation action history, IP logs and session updates.',
  },
  support: {
    title: 'Open Source & Support Settings',
    subtitle: 'Public "Buy Me a Coffee" banner and community links.',
  },
};
