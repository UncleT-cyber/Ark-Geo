/**
 * ChainOfCustody — cryptographic audit log viewer.
 *
 * Displays SHA-256 + SHA-1 + MD5 hashes, millisecond timestamps, and API
 * response logs to maintain evidentiary standards.
 *
 * When exif_missing or steganography_detected is true, the panel border and
 * text shift to pulsing Tactical Amber or Neon-Red.
 */
import React from 'react';
import type { AnalyzeResponse } from '../../types';

interface CustodyEntry {
  timestamp: string;
  action: string;
  hash: string;
  hashLabel?: string;
  detail?: string;
}

interface Props {
  response: AnalyzeResponse | null;
  exifMissing?: boolean;
  steganographyDetected?: boolean;
}

export function ChainOfCustody({ response, exifMissing, steganographyDetected }: Props) {
  const degraded = exifMissing || steganographyDetected;
  const degradationClass = steganographyDetected
    ? 'panel-degraded-red'
    : exifMissing
      ? 'panel-degraded-amber'
      : '';

  const entries: CustodyEntry[] = response
    ? [
        {
          timestamp: response.created_at,
          action: 'IMAGE INGESTED',
          hash: response.custody_certificate?.sha256 || response.image_sha256,
          hashLabel: 'SHA-256',
          detail: 'Raw image bytes received and cryptographically hashed',
        },
        ...(response.custody_certificate?.sha1
          ? [{
              timestamp: response.created_at,
              action: 'SHA-1 FINGERPRINT',
              hash: response.custody_certificate.sha1,
              hashLabel: 'SHA-1',
              detail: 'Secondary cryptographic digest for cross-validation',
            }]
          : []),
        ...(response.custody_certificate?.md5
          ? [{
              timestamp: response.created_at,
              action: 'MD5 FINGERPRINT',
              hash: response.custody_certificate.md5,
              hashLabel: 'MD5',
              detail: 'Tertiary hash for legacy compatibility',
            }]
          : []),
        {
          timestamp: response.created_at,
          action: 'CUSTODY SEAL',
          hash: response.custody_hash,
          hashLabel: 'SHA-256',
          detail: `Chain-of-custody digest · Request ${response.request_id}`,
        },
        ...(response.custody_certificate?.ingested_at_ms
          ? [{
              timestamp: response.created_at,
              action: 'INGEST TIMESTAMP',
              hash: '',
              detail: `UTC: ${new Date(response.custody_certificate.ingested_at_ms).toISOString()} (${response.custody_certificate.ingested_at_ms} ms)`,
            }]
          : []),
        ...(response.steganography_detected
          ? [{
              timestamp: response.created_at,
              action: '⚠ STRUCTURAL ANOMALY',
              hash: '',
              detail: `Steganography detected — ${response.trailing_bytes_count} trailing bytes after EOF marker`,
            }]
          : []),
        ...(response.exif_missing
          ? [{
              timestamp: response.created_at,
              action: '⚠ METADATA STRIPPED',
              hash: '',
              detail: 'EXIF metadata missing or stripped from image',
            }]
          : []),
        {
          timestamp: response.created_at,
          action: 'CASCADE COMPLETE',
          hash: '',
          detail: `Source: ${response.source} · Tier: ${response.consensus.tier_used} · Confidence: ${Math.round(response.consensus.confidence_score * 100)}%`,
        },
      ]
    : [];

  return (
    <div className={`panel-section ${degradationClass}`}>
      <div className="panel-title">CHAIN OF CUSTODY</div>
      {steganographyDetected && (
        <div className="alert-box alert-red">
          <div className="alert-title">STRUCTURAL ANOMALIES DETECTED</div>
          <div className="alert-detail">
            Steganographic payload found: {response?.trailing_bytes_count} bytes
            appended after EOF marker.
          </div>
        </div>
      )}
      {exifMissing && !steganographyDetected && (
        <div className="alert-box alert-amber">
          <div className="alert-title">ASSET METADATA STRIPPED</div>
          <div className="alert-detail">
            EXIF metadata is missing or has been stripped from this image.
            Forensic integrity cannot be fully verified.
          </div>
        </div>
      )}
      {entries.length === 0 ? (
        <div className="panel-empty">No audit entries yet</div>
      ) : (
        <div className="custody-log">
          {entries.map((entry, i) => (
            <div key={i} className="custody-entry">
              <div className="custody-timeline">
                <div className="custody-dot" />
                {i < entries.length - 1 && <div className="custody-line" />}
              </div>
              <div className="custody-content">
                <div className="custody-action">{entry.action}</div>
                <div className="custody-time mono">
                  {new Date(entry.timestamp).toLocaleString()}
                </div>
                {entry.hash && (
                  <div className="custody-hash mono">
                    <span className="custody-hash-label">{entry.hashLabel || 'SHA-256'}:</span>
                    <span className="custody-hash-value">{entry.hash}</span>
                  </div>
                )}
                {entry.detail && (
                  <div className="custody-detail">{entry.detail}</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
