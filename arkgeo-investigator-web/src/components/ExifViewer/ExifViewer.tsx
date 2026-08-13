/**
 * ExifViewer — raw metadata breakdown tree.
 *
 * When exifMissing or steganographyDetected is true, the panel border and
 * text shift to pulsing Tactical Amber or Neon-Red.
 */
import React, { useState } from 'react';

interface Props {
  exifRaw: Record<string, unknown> | null;
  imageSha256: string;
  exifMissing?: boolean;
  steganographyDetected?: boolean;
}

export function ExifViewer({ exifRaw, imageSha256, exifMissing, steganographyDetected }: Props) {
  const [showRaw, setShowRaw] = useState(false);

  const degradationClass = steganographyDetected
    ? 'panel-degraded-red'
    : exifMissing
      ? 'panel-degraded-amber'
      : '';

  const entries = exifRaw ? Object.entries(exifRaw) : [];

  return (
    <div className={`panel-section ${degradationClass}`}>
      <div className="panel-title">EXIF / METADATA BREAKDOWN</div>

      {exifMissing && (
        <div className="alert-box alert-amber">
          <div className="alert-title">ASSET METADATA STRIPPED</div>
          <div className="alert-detail">
            No EXIF metadata present — image has been stripped of all embedded
            camera and GPS data.
          </div>
        </div>
      )}
      {steganographyDetected && (
        <div className="alert-box alert-red">
          <div className="alert-title">STRUCTURAL ANOMALIES DETECTED</div>
          <div className="alert-detail">
            Trailing bytes found after EOF marker — possible steganographic payload.
          </div>
        </div>
      )}

      <div className="exif-sha">
        <span className="exif-sha-label">SHA-256</span>
        <span className="exif-sha-value mono">{imageSha256}</span>
      </div>

      {entries.length === 0 ? (
        <div className="panel-empty">
          {exifMissing
            ? 'EXIF metadata stripped — no fields to display.'
            : 'No EXIF metadata found — image may be stripped or zero-retention.'}
        </div>
      ) : (
        <>
          <div className="exif-entry-count">
            {entries.length} field{entries.length !== 1 ? 's' : ''} extracted
          </div>
          <div className="exif-tree">
            {entries.slice(0, showRaw ? undefined : 15).map(([key, value]) => (
              <div key={key} className="exif-row">
                <span className="exif-key mono">{key}</span>
                <span className="exif-value mono">
                  {typeof value === 'object'
                    ? JSON.stringify(value)
                    : String(value)}
                </span>
              </div>
            ))}
          </div>
          {entries.length > 15 && (
            <button className="exif-toggle" onClick={() => setShowRaw(!showRaw)}>
              {showRaw ? 'SHOW LESS' : `SHOW ALL ${entries.length}`}
            </button>
          )}
        </>
      )}
    </div>
  );
}
