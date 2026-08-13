/**
 * InvestigationOverview — displayed when an asset is opened.
 *
 * Answers:
 *   WHAT DO WE KNOW?
 *   WHAT DON'T WE KNOW?
 *   WHAT LOOKS SUSPICIOUS?
 *   WHAT SHOULD THE ANALYST INVESTIGATE NEXT?
 *
 * Every major finding is clickable and opens the relevant forensic view.
 */
import React from 'react';
import type { AnalyzeResponse } from '../../../types';
import type { ToolTabId } from '../TabBar';

interface InvestigationOverviewProps {
  result: AnalyzeResponse;
  onOpenTool: (toolId: ToolTabId) => void;
  thumbnailUrl?: string;
}

function confidenceColor(conf: number): string {
  if (conf >= 0.75) return '#22C55E';
  if (conf >= 0.4) return '#F59E0B';
  return '#EF4444';
}

function stateColor(state: string): string {
  switch (state) {
    case 'VERIFIED': return '#22C55E';
    case 'UNAVAILABLE': return '#64748B';
    case 'INVALID': return '#EF4444';
    case 'INCOMPLETE': return '#F59E0B';
    case 'REVIEW REQUIRED': return '#F59E0B';
    default: return '#94A3B8';
  }
}

export function InvestigationOverview({ result, onOpenTool, thumbnailUrl }: InvestigationOverviewProps) {
  const summary = result.evidence_summary;
  if (!summary) return null;
  const confColor = confidenceColor(summary.confidence);
  const provColor = stateColor(result.provenance?.state || 'UNAVAILABLE');
  const integColor = stateColor(summary.integrity);

  return (
    <div className="investigation-overview">
      <div className="overview-header">
        <div className="overview-title">ARKGEO ASSESSMENT</div>
        <div className="overview-case-id mono">Case {result.request_id.slice(0, 8).toUpperCase()}</div>
      </div>

      <div className="overview-tiles">
        <button className="overview-tile" onClick={() => onOpenTool('spatial')}>
          <div className="overview-tile-label">LOCATION</div>
          <div className="overview-tile-value">{summary.location}</div>
          <div className="overview-tile-sub" style={{ color: confColor }}>
            {Math.round(summary.confidence * 100)}% confidence
          </div>
        </button>

        <button className="overview-tile" onClick={() => onOpenTool('fileforensics')}>
          <div className="overview-tile-label">INTEGRITY</div>
          <div className="overview-tile-value" style={{ color: integColor }}>{summary.integrity}</div>
          <div className="overview-tile-sub">{result.exif_missing ? 'EXIF stripped' : 'EXIF present'}</div>
        </button>

        <button className="overview-tile" onClick={() => onOpenTool('provenance')}>
          <div className="overview-tile-label">PROVENANCE</div>
          <div className="overview-tile-value" style={{ color: provColor }}>{summary.provenance}</div>
          <div className="overview-tile-sub">C2PA status</div>
        </button>

        <button className="overview-tile" onClick={() => onOpenTool('provenance')}>
          <div className="overview-tile-label">CONTRADICTIONS</div>
          <div className="overview-tile-value" style={{ color: summary.contradictions > 0 ? '#F59E0B' : '#22C55E' }}>
            {summary.contradictions} detected
          </div>
          <div className="overview-tile-sub">cross-layer findings</div>
        </button>

        <button className="overview-tile" onClick={() => onOpenTool('vision')}>
          <div className="overview-tile-label">EVIDENCE</div>
          <div className="overview-tile-value">{summary.evidence_count} observations</div>
          <div className="overview-tile-sub">visual + OCR</div>
        </button>

        <button className="overview-tile" onClick={() => onOpenTool('discovery')}>
          <div className="overview-tile-label">SOURCES</div>
          <div className="overview-tile-value">{summary.sources_discovered} discovered</div>
          <div className="overview-tile-sub">{result.source_discovery?.state === 'UNAVAILABLE' ? 'not configured' : 'web matches'}</div>
        </button>
      </div>

      <div className="overview-sections">
        <div className="overview-section overview-known">
          <div className="overview-section-title">WHAT WE KNOW</div>
          {summary.known.length ? summary.known.map((k, i) => (
            <div key={i} className="overview-item overview-item-known">✓ {k}</div>
          )) : <div className="overview-item-muted">No confirmed facts yet</div>}
        </div>

        <div className="overview-section overview-unknown">
          <div className="overview-section-title">WHAT WE DON'T KNOW</div>
          {summary.unknown.length ? summary.unknown.map((k, i) => (
            <div key={i} className="overview-item overview-item-unknown">? {k}</div>
          )) : <div className="overview-item-muted">No gaps identified</div>}
        </div>

        <div className="overview-section overview-suspicious">
          <div className="overview-section-title">WHAT LOOKS SUSPICIOUS</div>
          {summary.suspicious.length ? summary.suspicious.map((k, i) => (
            <div key={i} className="overview-item overview-item-suspicious">⚠ {k}</div>
          )) : <div className="overview-item-muted">No anomalies detected</div>}
        </div>

        <div className="overview-section overview-next">
          <div className="overview-section-title">INVESTIGATE NEXT</div>
          {summary.next_steps.map((k, i) => (
            <div key={i} className="overview-item overview-item-next">→ {k}</div>
          ))}
        </div>
      </div>
    </div>
  );
}
