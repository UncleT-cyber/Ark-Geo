/**
 * AdminLayout — fixed-left-sidebar console shell with top header bar.
 * Header: "ARK SYSTEMS CONSOLE", Super-Admin badge, active user pill,
 * "Back to Workspace" link and logout.
 */
import React from 'react';
import { Shield, ArrowLeft, LogOut, Cpu } from 'lucide-react';
import { adminAuth } from '../../api';
import { AdminSidebar } from './AdminSidebar';
import { ADMIN_SECTION_TITLES, type AdminSectionId } from './adminNav';

interface AdminLayoutProps {
  active: AdminSectionId;
  onNavigate: (id: AdminSectionId) => void;
  onLogout: () => void;
  children: React.ReactNode;
}

export function AdminLayout({ active, onNavigate, onLogout, children }: AdminLayoutProps) {
  const meta = ADMIN_SECTION_TITLES[active];
  const user = adminAuth.getToken() ? 'super-admin' : '—';

  return (
    <div className="ark-admin">
      <header className="ark-admin-header">
        <div className="ark-admin-brand">
          <span className="ark-admin-logo"><Cpu className="w-4 h-4" /></span>
          <span className="ark-admin-brand-title">ARK SYSTEMS CONSOLE</span>
        </div>
        <span className="ark-admin-super-badge"><Shield className="w-3 h-3" /> SUPER-ADMIN</span>
        <div className="ark-admin-header-spacer" />
        <span className="ark-admin-user-pill">
          <span className="ark-admin-user-dot" />
          {user}
        </span>
        <a href="/" className="ark-admin-link">← Back to Workspace</a>
        <button className="ark-admin-logout" onClick={onLogout}>
          <LogOut className="w-3 h-3" /> Logout
        </button>
      </header>

      <div className="ark-admin-shell">
        <AdminSidebar active={active} onNavigate={onNavigate} />
        <main className="ark-admin-content">
          <h1 className="ark-admin-page-title">{meta.title}</h1>
          <p className="ark-admin-page-subtitle">{meta.subtitle}</p>
          {children}
        </main>
      </div>
    </div>
  );
}

export { ArrowLeft };
