/**
 * AdminConsole — ARK Systems Console (Super-Admin control plane).
 *
 * Tabbed shell mounting the ten management sections:
 *   Overview / Clients / Staff / Gateway / AI & OSINT / Policy / Quotas /
 *   Tooling / Audit / Support.
 *
 * Auth is JWT-guarded: if the session token is invalid/expired the user
 * is redirected back to the login screen.
 */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, adminAuth } from '../api';
import { AdminLayout } from './admin/AdminLayout';
import { Overview } from './admin/Overview';
import { ClientManagement } from './admin/ClientManagement';
import { StaffRbacManagement } from './admin/StaffRbacManagement';
import { ApiGateway } from './admin/ApiGateway';
import { AIGatewayPanel } from './admin/AIGatewayPanel';
import { ToolPolicy } from './admin/ToolPolicy';
import { QuotasUsage } from './admin/QuotasUsage';
import { LocalTooling } from './admin/LocalTooling';
import { AuditLogs } from './admin/AuditLogs';
import { SupportSettings } from './admin/SupportSettings';
import type { AdminSectionId } from './admin/adminNav';

export function AdminConsole() {
  const [active, setActive] = useState<AdminSectionId>('overview');
  const [authError, setAuthError] = useState(false);
  const [booted, setBooted] = useState(false);
  const navigate = useNavigate();

  // On mount, ping the overview endpoint to validate the session token.
  useEffect(() => {
    if (!adminAuth.isAuthenticated()) {
      setAuthError(true);
      return;
    }
    let cancelled = false;
    // If the backend hangs, never trap the operator on "Booting control
    // plane…" — boot the shell anyway after a hard deadline. A later
    // section request surfaces its own error banner.
    const BOOT_TIMEOUT_MS = 8000;
    const deadline = new Promise<null>(resolve =>
      setTimeout(() => resolve(null), BOOT_TIMEOUT_MS));
    Promise.race([api.adminOverview(), deadline])
      .catch((err: unknown) => {
        const status = (err as { response?: { status?: number } })?.response?.status;
        if (status === 401) setAuthError(true);
      })
      .finally(() => { if (!cancelled) setBooted(true); });
    return () => { cancelled = true; };
  }, []);

  // Redirect to login if auth fails.
  useEffect(() => {
    if (authError) {
      adminAuth.logout();
      const slug = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_ADMIN_ROUTE_SLUG || 'console-auth';
      navigate(`/${slug}`, { replace: true });
    }
  }, [authError, navigate]);

  const handleLogout = () => {
    adminAuth.logout();
    const slug = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_ADMIN_ROUTE_SLUG || 'console-auth';
    navigate(`/${slug}`, { replace: true });
  };

  if (authError) {
    return (
      <div className="ark-admin">
        <div className="ark-admin-loading" style={{ minHeight: '100vh' }}>
          <div className="ark-spinner" />
          <div>Session expired — redirecting to login…</div>
        </div>
      </div>
    );
  }

  if (!booted) {
    return (
      <div className="ark-admin">
        <div className="ark-admin-loading" style={{ minHeight: '100vh' }}>
          <div className="ark-spinner" />
          <div>Booting control plane…</div>
        </div>
      </div>
    );
  }

  return (
    <AdminLayout active={active} onNavigate={setActive} onLogout={handleLogout}>
      {active === 'overview' && <Overview onNavigate={setActive} />}
      {active === 'clients' && <ClientManagement />}
      {active === 'staff' && <StaffRbacManagement />}
      {active === 'gateway' && <ApiGateway />}
      {active === 'ai' && <AIGatewayPanel />}
      {active === 'policy' && <ToolPolicy />}
      {active === 'quotas' && <QuotasUsage />}
      {active === 'tooling' && <LocalTooling />}
      {active === 'audit' && <AuditLogs />}
      {active === 'support' && <SupportSettings />}
    </AdminLayout>
  );
}
