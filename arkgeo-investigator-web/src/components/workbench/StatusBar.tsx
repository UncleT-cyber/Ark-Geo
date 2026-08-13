/**
 * StatusBar — persistent bottom status bar (VS Code-style).
 *
 * Shows real-time file hashes (SHA-256), active server connection,
 * analysis state, and coordinates.  Only shows useful, non-cluttered info.
 */
import React from 'react';
import type { AnalyzeResponse } from '../../types';

interface StatusBarProps {
  result: AnalyzeResponse | null;
  connected: boolean;
  analyzing: boolean;
}

export function StatusBar({ result, connected, analyzing }: StatusBarProps) {
  const shaShort = result?.image_sha256 ? result.image_sha256.slice(0, 12) + '...' : 'no evidence';
  const coords = result?.coordinates
    ? `${result.coordinates.lat.toFixed(4)}, ${result.coordinates.lon.toFixed(4)}`
    : '—';
  const caseId = result ? `ARK-${result.request_id.slice(0, 8).toUpperCase()}` : 'no case';

  return (
    <div className="statusbar">
      <div className="statusbar-left">
        <span className={`statusbar-item statusbar-conn ${connected ? 'statusbar-conn-ok' : 'statusbar-conn-err'}`}>
          <span className="statusbar-dot" /> {connected ? 'Backend Connected' : 'Backend Offline'}
        </span>
        <span className="statusbar-sep">|</span>
        <span className="statusbar-item" title="Image SHA-256">
          <span className="statusbar-label">SHA-256:</span>
          <span className="mono">{shaShort}</span>
        </span>
        <span className="statusbar-sep">|</span>
        <span className="statusbar-item">
          <span className="statusbar-label">Case:</span> {caseId}
        </span>
      </div>
      <div className="statusbar-right">
        <span className="statusbar-item">
          <span className="statusbar-label">Analysis:</span>
          {analyzing ? <span className="statusbar-analyzing">RUNNING</span> : (result ? 'Complete' : 'Idle')}
        </span>
        {result && (
          <>
            <span className="statusbar-sep">|</span>
            <span className="statusbar-item">
              <span className="statusbar-label">Confidence:</span> {Math.round(result.consensus.confidence_score * 100)}%
            </span>
          </>
        )}
        <span className="statusbar-sep">|</span>
        <span className="statusbar-item">
          <span className="statusbar-label">GPS:</span> <span className="mono">{coords}</span>
        </span>
      </div>
    </div>
  );
}
