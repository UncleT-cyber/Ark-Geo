import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Dashboard } from './views/Dashboard';
import { AdminLoginForm } from './components/AdminLoginForm';
import { AdminConsole } from './components/AdminConsole';
import { NotFoundPage } from './components/NotFoundPage';
import { adminAuth } from './api';
import './dashboard.css';

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
  return (
    <BrowserRouter>
      <Routes>
        {/* Public investigator portal */}
        <Route path="/" element={<Dashboard />} />

        {/* Obfuscated admin route — login gate */}
        <Route path={ADMIN_LOGIN_PATH} element={<AdminRoute mode="login" />} />

        {/* Obfuscated admin route — authenticated console */}
        <Route path={ADMIN_CONSOLE_PATH} element={<AdminRoute mode="console" />} />

        {/* All other paths → 404 (hides admin routes) */}
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  );
}
