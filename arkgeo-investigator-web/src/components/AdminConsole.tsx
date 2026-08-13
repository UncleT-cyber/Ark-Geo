/**
 * AdminConsole — authenticated admin configuration panel.
 *
 * Displays masked API key status (truncated previews, never full values)
 * and allows updating keys + thresholds.  All requests carry the admin
 * JWT via the api._adminHeaders() interceptor.
 *
 * If the session token is invalid/expired, the user is redirected back
 * to the login screen.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, adminAuth } from '../api';
import type { AdminConfigResponse } from '../types';

interface KeyField {
  name: string;
  label: string;
  placeholder: string;
}

const KEY_FIELDS: KeyField[] = [
  { name: 'geospy_api_key', label: 'GeoSpy / GeoInfer API Key', placeholder: 'GeoSpy API key...' },
  { name: 'geoinfer_api_key', label: 'GeoInfer API Key', placeholder: 'GeoInfer API key...' },
  { name: 'llm_api_key', label: 'OpenAI / Vision LLM API Key', placeholder: 'sk-...' },
  { name: 'twilio_account_sid', label: 'Twilio Account SID', placeholder: 'ACxxxxxxxx...' },
  { name: 'twilio_auth_token', label: 'Twilio Auth Token', placeholder: 'Twilio auth token...' },
  { name: 'twilio_from_number', label: 'Twilio From Number', placeholder: '+15551234567' },
];

interface ToastFn {
  (msg: string, type: 'success' | 'warning' | 'error'): void;
}

export function AdminConsole({ onToast }: { onToast?: ToastFn }) {
  const [config, setConfig] = useState<AdminConfigResponse | null>(null);
  const [keyValues, setKeyValues] = useState<Record<string, string>>({});
  const [thresholds, setThresholds] = useState({
    min_confidence_threshold: 0.5,
    default_uncertainty_radius: 500,
  });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [authError, setAuthError] = useState(false);
  const navigate = useNavigate();

  const loadConfig = useCallback(async () => {
    try {
      const data = await api.getAdminConfig();
      setConfig(data);
      if (data.thresholds.min_confidence_threshold !== undefined) {
        setThresholds((prev) => ({
          ...prev,
          min_confidence_threshold: data.thresholds.min_confidence_threshold,
        }));
      }
      if (data.thresholds.default_uncertainty_radius !== undefined) {
        setThresholds((prev) => ({
          ...prev,
          default_uncertainty_radius: data.thresholds.default_uncertainty_radius,
        }));
      }
    } catch (err: any) {
      if (err?.response?.status === 401) {
        setAuthError(true);
      } else {
        onToast?.('Failed to load config', 'error');
      }
    }
  }, [onToast]);

  useEffect(() => {
    if (!adminAuth.isAuthenticated()) {
      setAuthError(true);
      return;
    }
    loadConfig();
  }, [loadConfig]);

  // Redirect to login if auth fails
  useEffect(() => {
    if (authError) {
      adminAuth.logout();
      const slug = (import.meta as any).env?.VITE_ADMIN_ROUTE_SLUG || 'console-auth';
      navigate(`/${slug}`, { replace: true });
    }
  }, [authError, navigate]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const apiKeys: Record<string, string | null> = {};
      for (const field of KEY_FIELDS) {
        const val = keyValues[field.name];
        if (val !== undefined && val !== '') {
          apiKeys[field.name] = val;
        }
      }
      const payload: Record<string, unknown> = {};
      if (Object.keys(apiKeys).length > 0) payload.api_keys = apiKeys;
      payload.thresholds = {
        min_confidence_threshold: thresholds.min_confidence_threshold,
        default_uncertainty_radius: thresholds.default_uncertainty_radius,
      };
      const data = await api.updateAdminConfig(payload);
      setConfig(data);
      setKeyValues({});
      onToast?.('Config saved — keys encrypted server-side', 'success');
    } catch (err: any) {
      if (err?.response?.status === 401) {
        setAuthError(true);
      } else {
        onToast?.('Failed to save config', 'error');
      }
    } finally {
      setSaving(false);
    }
  };

  const handleTestConnection = async (keyName: string) => {
    setTesting(keyName);
    try {
      const result = await api.adminTestConnection(keyName);
      onToast?.(
        result.configured
          ? `${keyName} is configured ✓`
          : `${keyName} is NOT configured`,
        result.configured ? 'success' : 'warning',
      );
    } catch (err: any) {
      if (err?.response?.status === 401) {
        setAuthError(true);
      } else {
        onToast?.('Connection test failed', 'error');
      }
    } finally {
      setTesting(null);
    }
  };

  const handleLogout = () => {
    adminAuth.logout();
    const slug = (import.meta as any).env?.VITE_ADMIN_ROUTE_SLUG || 'console-auth';
    navigate(`/${slug}`, { replace: true });
  };

  if (authError) {
    return (
      <div className="admin-console-loading">
        <div className="admin-loading-text">Session expired — redirecting to login...</div>
      </div>
    );
  }

  if (!config) {
    return (
      <div className="admin-console-loading">
        <div className="admin-loading-spinner" />
        <div className="admin-loading-text">Loading encrypted config...</div>
      </div>
    );
  }

  return (
    <div className="admin-console">
      <header className="admin-console-header">
        <div className="admin-console-brand">
          <span className="admin-console-icon">⚙</span>
          <div>
            <h1 className="admin-console-title">ADMIN CONSOLE</h1>
            <p className="admin-console-user">
              Authenticated as: <span className="mono">{adminAuth.getToken() ? 'admin' : '—'}</span>
            </p>
          </div>
        </div>
        <div className="admin-console-actions">
          <a href="/" className="admin-console-link">← Back to Portal</a>
          <button className="admin-console-logout" onClick={handleLogout}>
            Logout
          </button>
        </div>
      </header>

      <div className="admin-console-body">
        {/* API Keys Section */}
        <section className="admin-section">
          <h2 className="admin-section-title">API KEYS (ENCRYPTED)</h2>
          <p className="admin-section-desc">
            Keys are AES-256-GCM encrypted and stored server-side. They are
            never returned in plain text — only masked previews are shown below.
            The vision pipeline pulls keys directly from the encrypted store.
          </p>
          {KEY_FIELDS.map((field) => {
            const status = config.api_keys?.[field.name];
            const configured = status?.configured ?? false;
            const preview = status?.key_preview ?? null;
            return (
              <div key={field.name} className="admin-key-row">
                <div className="admin-key-info">
                  <label className="admin-key-label">{field.label}</label>
                  <div className={`admin-key-status ${configured ? 'status-on' : 'status-off'}`}>
                    {configured
                      ? <>● CONFIGURED <span className="admin-key-preview mono">{preview}</span></>
                      : '○ NOT SET'}
                  </div>
                </div>
                <div className="admin-key-input-row">
                  <input
                    type="password"
                    className="admin-key-input"
                    placeholder={configured ? 'Enter new value to replace...' : field.placeholder}
                    value={keyValues[field.name] ?? ''}
                    onChange={(e) =>
                      setKeyValues((prev) => ({ ...prev, [field.name]: e.target.value }))
                    }
                  />
                  <button
                    className="admin-test-btn"
                    onClick={() => handleTestConnection(field.name)}
                    disabled={testing === field.name}
                  >
                    {testing === field.name ? '...' : 'Test'}
                  </button>
                </div>
              </div>
            );
          })}
        </section>

        {/* Engine Thresholds Section */}
        <section className="admin-section">
          <h2 className="admin-section-title">ENGINE THRESHOLDS</h2>
          <div className="admin-threshold-row">
            <label className="admin-threshold-label">
              Minimum AI Confidence Threshold
              <span className="admin-threshold-value">
                {Math.round(thresholds.min_confidence_threshold * 100)}%
              </span>
            </label>
            <input
              type="range"
              min="0"
              max="100"
              value={Math.round(thresholds.min_confidence_threshold * 100)}
              onChange={(e) =>
                setThresholds((prev) => ({
                  ...prev,
                  min_confidence_threshold: parseInt(e.target.value) / 100,
                }))
              }
              className="admin-slider"
            />
          </div>
          <div className="admin-threshold-row">
            <label className="admin-threshold-label">
              Default Uncertainty Radius
              <span className="admin-threshold-value">
                {Math.round(thresholds.default_uncertainty_radius)}m
              </span>
            </label>
            <input
              type="range"
              min="100"
              max="10000"
              step="100"
              value={thresholds.default_uncertainty_radius}
              onChange={(e) =>
                setThresholds((prev) => ({
                  ...prev,
                  default_uncertainty_radius: parseInt(e.target.value),
                }))
              }
              className="admin-slider"
            />
          </div>
        </section>

        {/* Save */}
        <div className="admin-save-bar">
          <button
            className="admin-save-btn"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? 'Encrypting & Saving...' : 'Save Configuration'}
          </button>
        </div>
      </div>
    </div>
  );
}
