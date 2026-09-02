/**
 * AdminSidebar — fixed left navigation for the ARK Systems Console.
 * Left-bordered active tabs with pill highlight overlays (emerald).
 */
import React from 'react';
import { ADMIN_NAV, type AdminSectionId } from './adminNav';

interface AdminSidebarProps {
  active: AdminSectionId;
  onNavigate: (id: AdminSectionId) => void;
}

export function AdminSidebar({ active, onNavigate }: AdminSidebarProps) {
  return (
    <nav className="ark-admin-sidebar">
      <div className="ark-admin-sidebar-label">Control Plane</div>
      {ADMIN_NAV.map(item => {
        const Icon = item.icon;
        return (
          <button
            key={item.id}
            className={`ark-admin-nav-item ${active === item.id ? 'ark-admin-nav-item-active' : ''}`}
            onClick={() => onNavigate(item.id)}
          >
            <Icon className="w-4 h-4" />
            <span>{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
