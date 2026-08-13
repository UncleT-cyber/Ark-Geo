/**
 * ExifViewer — raw metadata breakdown tree.
 */
import React, { useState } from 'react';

interface Props {
  exifRaw: Record<string, unknown> | null;
  imageSha256: string;
}

export function ExifViewer({ exifRaw, imageSha256 }: Props) {
  const [showRaw, setShowRaw] = useState(false);

  const entries = exifRaw ? Object.entries(exifRaw) : [];

  return (
    <div className="panel-section">
      <div className="panel-title">EXIF / METADATA BREAKDOWN</div>

      <div className="exif-sha">
        <span className="exif-sha-label">SHA-256</span>
        <span className="exif-sha-value mono">{imageSha256}</span>
      </div>

      {entries.length === 0 ? (
        <div className="panel-empty">
          No EXIF metadata found — image may be stripped or zero-retention.
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
