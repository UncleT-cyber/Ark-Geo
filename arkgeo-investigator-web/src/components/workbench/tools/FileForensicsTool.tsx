/**
 * FileForensicsTool — ExifTool tree, Hex view, ELA, JPEG structure,
 * metadata consistency findings.
 *
 * Displays the deep metadata from ExifTool as a collapsible grouped tree,
 * shows ELA heatmap, hex viewer, and structured consistency findings.
 */
import React, { useState } from 'react';
import type { AnalyzeResponse, ConsistencyFinding } from '../../../types';

interface FileForensicsToolProps {
  result: AnalyzeResponse;
  thumbnailUrl?: string;
}

function severityColor(severity: string): string {
  if (severity === 'HIGH' || severity === 'high' || severity === 'error') return '#EF4444';
  if (severity === 'MEDIUM' || severity === 'medium' || severity === 'warning') return '#F59E0B';
  return '#22C55E';
}

function ConsistencyFindingRow({ finding }: { finding: ConsistencyFinding }) {
  const [expanded, setExpanded] = useState(false);
  const color = severityColor(finding.severity);
  return (
    <div className="finding-row" style={{ borderLeftColor: color }}>
      <div className="finding-header" onClick={() => setExpanded(!expanded)}>
        <span className="finding-badge" style={{ color, borderColor: color }}>{finding.status}</span>
        <span className="finding-type mono">{finding.type}</span>
        <span className="finding-msg">{finding.message}</span>
        <span className="finding-chevron">{expanded ? '▾' : '▸'}</span>
      </div>
      {expanded && finding.evidence.length > 0 && (
        <div className="finding-evidence">
          {finding.evidence.map((e, i) => <div key={i} className="finding-evidence-item mono">{e}</div>)}
        </div>
      )}
    </div>
  );
}

function MetadataGroup({ name, entries }: { name: string; entries: { tag: string; value: string }[] }) {
  const [expanded, setExpanded] = useState(name === 'EXIF' || name === 'File');
  return (
    <div className="meta-group">
      <div className="meta-group-header" onClick={() => setExpanded(!expanded)}>
        <span className="meta-chevron">{expanded ? '▾' : '▸'}</span>
        <span className="meta-group-name">{name}</span>
        <span className="meta-group-count">{entries.length}</span>
      </div>
      {expanded && (
        <div className="meta-group-body">
          {entries.map((e, i) => (
            <div key={i} className="meta-row">
              <span className="meta-tag mono">{e.tag}</span>
              <span className="meta-value mono">{e.value}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function FileForensicsTool({ result, thumbnailUrl }: FileForensicsToolProps) {
  const [showHex, setShowHex] = useState(false);
  const [tab, setTab] = useState<'metadata' | 'ela' | 'consistency' | 'structure'>('metadata');

  const deep = result.deep_metadata;
  const groups = deep?.groups || {};
  const findings = result.consistency_findings || [];
  const hasFindings = findings.length > 0;
  const hexBytes = result.image_sha256.slice(0, 64).match(/.{1,2}/g) || [];

  return (
    <div className="tool-view tool-fileforensics">
      <div className="tool-subtabs">
        <button className={`tool-subtab ${tab === 'metadata' ? 'tool-subtab-active' : ''}`} onClick={() => setTab('metadata')}>ExifTool Tree</button>
        <button className={`tool-subtab ${tab === 'ela' ? 'tool-subtab-active' : ''}`} onClick={() => setTab('ela')}>ELA</button>
        <button className={`tool-subtab ${tab === 'consistency' ? 'tool-subtab-active' : ''}`} onClick={() => setTab('consistency')}>Consistency ({findings.length})</button>
        <button className={`tool-subtab ${tab === 'structure' ? 'tool-subtab-active' : ''}`} onClick={() => setTab('structure')}>Structure / Hex</button>
      </div>

      <div className="tool-content">
        {tab === 'metadata' && (
          <div className="tool-metadata">
            {!deep?.available ? (
              <div className="tool-empty">
                <div className="tool-empty-icon">📦</div>
                <div className="tool-empty-title">ExifTool Unavailable</div>
                <div className="tool-empty-text">{deep?.error || 'ExifTool is not installed on the server.'}</div>
              </div>
            ) : Object.keys(groups).length === 0 ? (
              <div className="tool-empty"><div className="tool-empty-text">No metadata fields discovered.</div></div>
            ) : (
              Object.entries(groups).map(([name, entries]) => (
                <MetadataGroup key={name} name={name} entries={entries as any} />
              ))
            )}
          </div>
        )}

        {tab === 'ela' && (
          <div className="tool-ela">
            {result.ela_heatmap ? (
              <>
                <div className="ela-image-wrap">
                  <img src={`data:image/png;base64,${result.ela_heatmap}`} alt="ELA Heatmap" className="ela-heatmap" />
                  {thumbnailUrl && <img src={thumbnailUrl} alt="Original" className="ela-original" />}
                </div>
                <div className="ela-interpretation">
                  <div className="ela-note">
                    Error Level Analysis re-compresses the image and highlights regions with different
                    compression characteristics. Brighter areas may indicate localized recompression
                    (potential editing). ELA alone is <strong>not</strong> proof of manipulation.
                  </div>
                </div>
              </>
            ) : (
              <div className="tool-empty">
                <div className="tool-empty-icon">📊</div>
                <div className="tool-empty-title">ELA Not Available</div>
                <div className="tool-empty-text">ELA heatmap could not be generated for this image.</div>
              </div>
            )}
          </div>
        )}

        {tab === 'consistency' && (
          <div className="tool-consistency">
            {!hasFindings ? (
              <div className="tool-empty">
                <div className="tool-empty-icon">✓</div>
                <div className="tool-empty-title">No Inconsistencies Found</div>
                <div className="tool-empty-text">Metadata consistency checks passed — no timeline anomalies, software edits, or device mismatches detected.</div>
              </div>
            ) : (
              <>
                <div className="consistency-intro">
                  {findings.length} structured finding(s). These describe observable inconsistencies, not proof of manipulation.
                </div>
                {findings.map((f, i) => <ConsistencyFindingRow key={i} finding={f} />)}
              </>
            )}
          </div>
        )}

        {tab === 'structure' && (
          <div className="tool-structure">
            <div className="structure-info">
              <div className="structure-row"><span className="structure-label">File Format:</span> <span className="mono">{result.file_format || 'N/A'}</span></div>
              <div className="structure-row"><span className="structure-label">MIME Type:</span> <span className="mono">{deep?.file_info?.mime_type as string || 'N/A'}</span></div>
              <div className="structure-row"><span className="structure-label">File Size:</span> <span className="mono">{deep?.file_info?.file_size as string || 'N/A'}</span></div>
              <div className="structure-row"><span className="structure-label">Dimensions:</span> <span className="mono">{deep?.file_info ? `${deep.file_info.image_width}×${deep.file_info.image_height}` : 'N/A'}</span></div>
              <div className="structure-row"><span className="structure-label">Steganography:</span> <span className="mono" style={{ color: result.steganography_detected ? '#EF4444' : '#22C55E' }}>{result.steganography_detected ? `DETECTED (${result.trailing_bytes_count} trailing bytes)` : 'CLEAN'}</span></div>
            </div>
            <button className="tool-btn" onClick={() => setShowHex(!showHex)}>{showHex ? 'Hide' : 'Show'} Hex Viewer</button>
            {showHex && (
              <div className="hex-view mono">
                {hexBytes.map((byte, i) => (
                  <span key={i} className="hex-byte">{byte}</span>
                ))}
                <div className="hex-note">SHA-256 digest (first 64 hex chars of {result.image_sha256.length})</div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
