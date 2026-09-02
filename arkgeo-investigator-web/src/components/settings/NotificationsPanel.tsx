/**
 * NotificationsPanel — report branding (report logo / watermark) and
 * alert preferences for the client's generated case reports.
 */
import React from 'react';
import { Bell, FileText, Droplets } from 'lucide-react';
import { useByok } from './ByokContext';

export function NotificationsPanel() {
  const { notifications, setNotifications } = useByok();
  const set = (patch: Partial<typeof notifications>) =>
    setNotifications({ ...notifications, ...patch });

  return (
    <div>
      <div className="ark-cs-card">
        <div className="ark-cs-card-title"><FileText className="w-3.5 h-3.5" /> REPORT BRANDING</div>
        <div className="ark-cs-grid-2">
          <div className="ark-cs-field">
            <span className="ark-cs-field-label">Report Logo Text</span>
            <input className="ark-cs-input" value={notifications.reportLogo}
              onChange={e => set({ reportLogo: e.target.value })} placeholder="THE ARK" />
          </div>
          <div className="ark-cs-field">
            <span className="ark-cs-field-label">Watermark</span>
            <input className="ark-cs-input" value={notifications.watermark}
              onChange={e => set({ watermark: e.target.value })} placeholder="ARK — CONFIDENTIAL" />
          </div>
        </div>
        <p style={{ fontSize: 11, color: '#6B7280', margin: '8px 0 0' }}>
          Applied to generated case report headers and page watermarks.
        </p>
      </div>

      <div className="ark-cs-card">
        <div className="ark-cs-card-title"><Bell className="w-3.5 h-3.5" /> ALERT PREFERENCES</div>
        <label className="ark-byok-override" style={{ marginBottom: 12 }}>
          <input type="checkbox" className="ark-check-cs" checked={notifications.emailAlerts}
            onChange={e => set({ emailAlerts: e.target.checked })} />
          Email alerts on case updates
        </label>
        <label className="ark-byok-override" style={{ marginBottom: 12 }}>
          <input type="checkbox" className="ark-check-cs" checked={notifications.pushAlerts}
            onChange={e => set({ pushAlerts: e.target.checked })} />
          In-app push alerts
        </label>
        <div className="ark-cs-field">
          <span className="ark-cs-field-label">Digest Frequency</span>
          <select className="ark-cs-select" value={notifications.digestFrequency}
            onChange={e => set({ digestFrequency: e.target.value as typeof notifications.digestFrequency })}>
            <option value="off">Off — no digest</option>
            <option value="daily">Daily summary</option>
            <option value="weekly">Weekly summary</option>
          </select>
        </div>
      </div>

      <div className="ark-cs-card">
        <div className="ark-cs-card-title" style={{ color: '#38BDF8' }}><Droplets className="w-3.5 h-3.5" /> PRIVACY</div>
        <p style={{ fontSize: 12, color: '#9CA3AF', lineHeight: 1.6, margin: 0 }}>
          Alerts reference case IDs and filenames only — never raw pixel data, coordinates or key material.
          Report watermarks are stamped client-side at export time.
        </p>
      </div>
    </div>
  );
}
