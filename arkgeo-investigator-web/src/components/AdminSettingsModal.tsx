/**
 * AdminSettingsModal — system settings panel for API key management
 * and engine threshold configuration.
 *
 * API keys are password-masked and stored encrypted on the backend.
 * GET responses never return key values — only a boolean "configured" flag.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import type { SettingsResponse } from '../types';

interface Props {
  open: boolean;
  onClose: () => void;
  onToast?: (msg: string, type: 'success' | 'warning' | 'error') => void;
}

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

export function AdminSettingsModal({ open, onClose, onToast }: Props) {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [keyValues, setKeyValues] = useState<Record<string, string>>({});
  const [thresholds, setThresholds] = useState({
    min_confidence_threshold: 0.5,
    default_uncertainty_radius: 500,
  });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);

  const loadSettings = useCallback(async () => {
    try {
      const data = await api.getSettings();
      setSettings(data);
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
    } catch (err) {
      onToast?.('Failed to load settings', 'error');
    }
  }, [onToast]);

  useEffect(() => {
    if (open) loadSettings();
  }, [open, loadSettings]);

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
      await api.updateSettings(payload);
      setKeyValues({});
      await loadSettings();
      onToast?.('Settings saved — server updated without restart', 'success');
    } catch (err) {
      onToast?.('Failed to save settings', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleTestConnection = async (keyName: string) => {
    setTesting(keyName);
    try {
      const result = await api.testConnection(keyName);
      onToast?.(
        result.configured
          ? `${keyName} is configured ✓`
          : `${keyName} is NOT configured`,
        result.configured ? 'success' : 'warning',
      );
    } catch {
      onToast?.('Connection test failed', 'error');
    } finally {
      setTesting(null);
    }
  };

  if (!open) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-title">⚙ System Settings</span>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        <div className="modal-body">
          {/* API Keys Section */}
          <div className="settings-section">
            <div className="settings-section-title">API KEYS</div>
            {KEY_FIELDS.map((field) => {
              const configured = settings?.api_keys?.[field.name] ?? false;
              return (
                <div key={field.name} className="settings-key-row">
                  <label className="settings-key-label">{field.label}</label>
                  <div className="settings-key-input-row">
                    <input
                      type="password"
                      className="settings-key-input"
                      placeholder={configured ? '•••••••• (configured)' : field.placeholder}
                      value={keyValues[field.name] ?? ''}
                      onChange={(e) =>
                        setKeyValues((prev) => ({ ...prev, [field.name]: e.target.value }))
                      }
                    />
                    <button
                      className="settings-test-btn"
                      onClick={() => handleTestConnection(field.name)}
                      disabled={testing === field.name}
                    >
                      {testing === field.name ? '...' : 'Test'}
                    </button>
                  </div>
                  <div className={`settings-key-status ${configured ? 'status-on' : 'status-off'}`}>
                    {configured ? '● CONFIGURED' : '○ NOT SET'}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Engine Thresholds Section */}
          <div className="settings-section">
            <div className="settings-section-title">ENGINE THRESHOLDS</div>
            <div className="settings-threshold-row">
              <label className="settings-threshold-label">
                Minimum AI Confidence Threshold
                <span className="settings-threshold-value">
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
                className="settings-slider"
              />
            </div>
            <div className="settings-threshold-row">
              <label className="settings-threshold-label">
                Default Uncertainty Radius
                <span className="settings-threshold-value">
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
                className="settings-slider"
              />
            </div>
          </div>
        </div>

        <div className="modal-footer">
          <button className="modal-btn modal-btn-cancel" onClick={onClose}>Cancel</button>
          <button
            className="modal-btn modal-btn-save"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
}
