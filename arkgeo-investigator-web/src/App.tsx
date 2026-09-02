import React, { useEffect } from 'react';
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Workbench } from './components/workbench/Workbench';
import { AdminLoginForm } from './components/AdminLoginForm';
import { AdminConsole } from './components/AdminConsole';
import { NotFoundPage } from './components/NotFoundPage';
import { adminAuth } from './api';
import './dashboard.css';
import './admin-console.css';
import './client-settings.css';

/**
 * Admin route slug — configurable via VITE_ADMIN_ROUTE_SLUG env var.
 * Defaults to 'console-auth'.  This obfuscates the admin login path so
 * it is not discoverable by casual navigation or directory brute-forcing.
 */
const ADMIN_ROUTE_SLUG =
  (import.meta as any).env?.VITE_ADMIN_ROUTE_SLUG || 'console-auth';
const ADMIN_LOGIN_PATH = `/${ADMIN_ROUTE_SLUG}`;
const ADMIN_CONSOLE_PATH = `/${ADMIN_ROUTE_SLUG}/console`;

/**
 * Route guard — redirects to 404 if not authenticated.
 * Shows the login form at the base admin slug; shows the console at /console.
 */
function AdminRoute({ mode }: { mode: 'login' | 'console' }) {
  const authenticated = adminAuth.isAuthenticated();

  if (mode === 'login') {
    // If already authenticated, go straight to console
    if (authenticated) {
      return <Navigate to={ADMIN_CONSOLE_PATH} replace />;
    }
    return <AdminLoginForm />;
  }

  // mode === 'console' — require auth, otherwise 404 (not login)
  if (!authenticated) {
    return <NotFoundPage />;
  }
  return <AdminConsole />;
}

export default function App() {
  const ADMIN_ROUTE_SLUG =
    (import.meta as any).env?.VITE_ADMIN_ROUTE_SLUG || 'console-auth';
  const ADMIN_LOGIN_PATH = `/${ADMIN_ROUTE_SLUG}`;

  // Global stealth hotkey: Cmd+Shift+P (Mac) / Ctrl+Shift+P (others) → admin
  // login. This is the ONLY way to reach Admin from the workbench — the profile
  // icon and activity bar never link to it. Fires on ALL routes. Uses both
  // e.key (letter) and e.code (physical key) so non-QWERTY layouts still work.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const modKey = e.metaKey || e.ctrlKey;
      const isP = e.key === 'P' || e.key === 'p' || e.code === 'KeyP';
      if (modKey && e.shiftKey && isP) {
        e.preventDefault();
        window.location.hash = ADMIN_LOGIN_PATH;
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [ADMIN_LOGIN_PATH]);

  return (
    <HashRouter>
      <Routes>
        {/* Public surface — THE ARK ISE (Integrated Security Environment) */}
        <Route path="/" element={<Workbench />} />

        {/* Obfuscated admin route — login gate */}
        <Route path={ADMIN_LOGIN_PATH} element={<AdminRoute mode="login" />} />

        {/* Obfuscated admin route — authenticated console */}
        <Route path={ADMIN_CONSOLE_PATH} element={<AdminRoute mode="console" />} />

        {/* All other paths → 404 (hides admin routes) */}
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </HashRouter>
  );
}
