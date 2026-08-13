/**
 * AdminLoginForm — secure login gate for the Admin Console.
 *
 * Submits credentials to POST /api/v1/admin/login.  On success, the JWT
 * is stored in-memory (adminAuth) and the user is redirected to the
 * console.  On failure, a 401 message is shown.
 *
 * The login route is served at an obfuscated path (VITE_ADMIN_ROUTE_SLUG)
 * so it is not discoverable by casual navigation.
 */
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, adminAuth } from '../api';

interface Props {
  onSuccess?: () => void;
}

export function AdminLoginForm({ onSuccess }: Props) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const resp = await api.adminLogin(username, password);
      adminAuth.setToken(resp.access_token);
      // Navigate to the console sub-route (no reload — preserves in-memory token)
      const slug = (import.meta as any).env?.VITE_ADMIN_ROUTE_SLUG || 'console-auth';
      navigate(`/${slug}/console`, { replace: true });
    } catch (err: any) {
      if (err?.response?.status === 401) {
        setError('Invalid credentials — access denied');
      } else {
        setError('Authentication service unavailable');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="admin-login-container">
      <div className="admin-login-card">
        <div className="admin-login-header">
          <div className="admin-login-icon">🔐</div>
          <h1 className="admin-login-title">ADMIN CONSOLE</h1>
          <p className="admin-login-subtitle">Authorized personnel only</p>
        </div>

        <form onSubmit={handleSubmit} className="admin-login-form">
          <div className="admin-login-field">
            <label className="admin-login-label">Username</label>
            <input
              type="text"
              className="admin-login-input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              required
            />
          </div>

          <div className="admin-login-field">
            <label className="admin-login-label">Password</label>
            <input
              type="password"
              className="admin-login-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>

          {error && (
            <div className="admin-login-error">
              <span className="admin-login-error-icon">⚠</span>
              {error}
            </div>
          )}

          <button
            type="submit"
            className="admin-login-btn"
            disabled={loading || !username || !password}
          >
            {loading ? 'Authenticating...' : 'Authenticate'}
          </button>
        </form>

        <div className="admin-login-footer">
          All access is logged. Unauthorized access is prohibited.
        </div>
      </div>
    </div>
  );
}
