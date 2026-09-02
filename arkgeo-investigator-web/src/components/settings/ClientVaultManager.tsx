/**
 * ClientVaultManager — saved-case archive. Reads the shared investigation
 * history (localStorage ark.caseHistory, capped at 100), lets the analyst
 * restore a case into the workspace, delete it, or export the whole vault
 * as a JSON backup. Shows a storage gauge against the plan cap.
 */
import React, { useMemo, useState } from 'react';
import { FolderOpen, Download, Trash2, Database, Folder } from 'lucide-react';
import { useInvestigation } from '../workbench/useInvestigation';
import type { SavedCase } from '../workbench/useInvestigation';

const RISK_COLOR: Record<SavedCase['risk'], string> = {
  critical: '#FCA5A5',
  medium: '#FCD34D',
  low: '#6EE7B7',
};

function fmtBytes(bytes: number): string {
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

export function ClientVaultManager() {
  const { history, restoreCase, removeCase, clearHistory } = useInvestigation();
  const [confirmClear, setConfirmClear] = useState(false);

  const { bytes, pct } = useMemo(() => {
    const b = history.reduce((acc, h) => acc + JSON.stringify(h).length, 0);
    const cap = 5 * 1024 * 1024; // 5 MB client vault cap
    return { bytes: b, pct: Math.min(100, (b / cap) * 100) };
  }, [history]);

  const exportVault = () => {
    const blob = new Blob([JSON.stringify(history, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ark-vault-backup-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const fmtTime = (ts: number) => new Date(ts).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });

  return (
    <div>
      <div className="ark-cs-card">
        <div className="ark-cs-card-title"><Database className="w-3.5 h-3.5" /> VAULT STORAGE</div>
        <div className="ark-cs-gauge-row">
          <span>{fmtBytes(bytes)} used</span>
          <span className="ark-cs-gauge-cap">{history.length}/100 cases</span>
        </div>
        <div className="ark-cs-gauge">
          <div className="ark-cs-gauge-fill" style={{ width: `${Math.max(pct, history.length > 0 ? 2 : 0)}%` }} />
        </div>
      </div>

      <div className="ark-cs-card">
        <div className="ark-inline">
          <div>
            <div className="ark-cs-card-title" style={{ margin: 0 }}><Folder className="w-3.5 h-3.5" /> SAVED CASES</div>
            <p style={{ fontSize: 11, color: '#6B7280', margin: '4px 0 0' }}>
              Evidence investigations persist locally on this device. Restore one to continue work.
            </p>
          </div>
          <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 8 }}>
            <button className="ark-cs-btn ark-cs-btn-sm" onClick={exportVault} disabled={history.length === 0}>
              <Download className="w-3 h-3" /> Export Backup
            </button>
            <button
              className="ark-cs-btn ark-cs-btn-sm ark-cs-btn-danger"
              onClick={() => setConfirmClear(true)}
              disabled={history.length === 0}
            >
              <Trash2 className="w-3 h-3" /> Clear Case Vault
            </button>
          </span>
        </div>

        {confirmClear && (
          <div className="ark-vault-clear-confirm">
            <span>Delete all {history.length} saved case{history.length === 1 ? '' : 's'} from this device? This cannot be undone.</span>
            <button className="ark-cs-btn ark-cs-btn-sm ark-cs-btn-danger" onClick={() => { clearHistory(); setConfirmClear(false); }}>
              Delete All
            </button>
            <button className="ark-cs-btn ark-cs-btn-sm" onClick={() => setConfirmClear(false)}>Cancel</button>
          </div>
        )}

        <div className="ark-mt">
          {history.length === 0 ? (
            <p style={{ fontSize: 12.5, color: '#6B7280', margin: 0 }}>
              No saved cases yet — ingest an image and run the intelligence cascade to populate this vault.
            </p>
          ) : (
            history.map(h => (
              <div className="ark-vault-row" key={h.caseId}>
                <span style={{ width: 8, height: 8, borderRadius: 99, background: RISK_COLOR[h.risk], flexShrink: 0 }} />
                <div className="ark-vault-main">
                  <div className="ark-vault-id">{h.caseId}</div>
                  <div className="ark-vault-file">{h.filename}</div>
                  <div className="ark-vault-meta">
                    {fmtTime(h.timestamp)} · {h.tier} · {Math.round(h.confidence * 100)}% · sha256 {h.sha256.slice(0, 10)}…
                  </div>
                </div>
                <div className="ark-vault-actions">
                  <button className="ark-cs-btn ark-cs-btn-sm" onClick={() => restoreCase(h)}>
                    <FolderOpen className="w-3 h-3" /> Restore
                  </button>
                  <button className="ark-cs-btn ark-cs-btn-sm ark-cs-btn-danger" onClick={() => removeCase(h)}>
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
