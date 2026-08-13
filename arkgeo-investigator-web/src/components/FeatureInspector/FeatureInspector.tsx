/**
 * FeatureInspector — grouped expandable tags for detected architecture,
 * flora, signage, and OCR text.  Also hosts the Forensic Overlay Manager
 * (ELA heatmap toggle) and the Sanity Validation Matrix UI.
 */
import React, { useState } from 'react';
import type { VisualEvidenceTag, AnalyzeResponse } from '../../types';

interface Props {
  tags: VisualEvidenceTag[];
  source?: string;
  /** Full analysis response for ELA + sanity matrix features. */
  response?: AnalyzeResponse | null;
  /** Original image data URL for the canvas overlay. */
  imageUrl?: string | null;
}

type ViewTab = 'evidence' | 'ela' | 'sanity';

const CATEGORY_LABELS: Record<string, string> = {
  architecture: 'Architectural',
  botanical: 'Botanical / Geological',
  ocr: 'OCR / Text',
  infrastructure: 'Infrastructure',
};

const CATEGORY_COLORS: Record<string, string> = {
  architecture: '#38BDF8',
  botanical: '#22C55E',
  ocr: '#F59E0B',
  infrastructure: '#0EA5E9',
};

export function FeatureInspector({ tags, source, response, imageUrl }: Props) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [activeTab, setActiveTab] = useState<ViewTab>('evidence');

  // Group tags by category
  const grouped: Record<string, VisualEvidenceTag[]> = {};
  tags.forEach((tag) => {
    const cat = tag.category || 'other';
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(tag);
  });

  const toggle = (cat: string) => {
    setExpanded((prev) => ({ ...prev, [cat]: !prev[cat] }));
  };

  const hasEla = !!response?.ela_heatmap;
  const hasSpoofing = !!response?.gps_spoofing_detected;
  const spoofingScore = response?.anomaly_score ?? 0;

  return (
    <div className={`panel-section ${activeTab === 'ela' && hasEla ? 'panel-ela-active' : ''}`}>
      <div className="panel-title">VISUAL EVIDENCE &amp; CLUES</div>

      {/* Forensic Overlay Manager — view tabs */}
      <div className="forensic-tabs">
        <button
          className={`forensic-tab ${activeTab === 'evidence' ? 'forensic-tab-active' : ''}`}
          onClick={() => setActiveTab('evidence')}
        >
          🏷 Evidence
        </button>
        <button
          className={`forensic-tab ${activeTab === 'ela' ? 'forensic-tab-active' : ''} ${!hasEla ? 'forensic-tab-disabled' : ''}`}
          onClick={() => hasEla && setActiveTab('ela')}
          disabled={!hasEla}
        >
          🔍 ELA Heatmap
        </button>
        <button
          className={`forensic-tab ${activeTab === 'sanity' ? 'forensic-tab-active' : ''}`}
          onClick={() => setActiveTab('sanity')}
        >
          ⚖ Sanity Matrix
        </button>
      </div>

      {/* GPS Spoofing Warning Banner */}
      {hasSpoofing && (
        <div className="spoofing-banner">
          <div className="spoofing-banner-icon">⚠</div>
          <div className="spoofing-banner-content">
            <div className="spoofing-banner-title">GPS SPOOFING DETECTED</div>
            <div className="spoofing-banner-score">
              Anomaly Score: {(spoofingScore * 100).toFixed(0)}%
            </div>
            {response?.sanity_mismatches?.map((m, i) => (
              <div key={i} className="spoofing-banner-detail">• {m}</div>
            ))}
          </div>
        </div>
      )}

      {/* Tab content */}
      {activeTab === 'evidence' && (
        tags.length === 0 ? (
          <div className="panel-empty">
            No visual evidence tags for this target.
            <div className="panel-empty-sub">
              {source?.includes('EXIF') || source?.includes('NO_AI')
                ? 'Hardware EXIF or telemetry sources do not generate visual clue tags — these are produced by AI vision analysis only.'
                : 'AI vision analysis did not produce visual evidence tags for this image.'}
            </div>
          </div>
        ) : (
          <div className="tag-groups">
            {Object.entries(grouped).map(([cat, catTags]) => (
              <div key={cat} className="tag-group">
                <button
                  className="tag-group-header"
                  onClick={() => toggle(cat)}
                  style={{ borderLeftColor: CATEGORY_COLORS[cat] || '#334155' }}
                >
                  <span className="tag-group-label">
                    {CATEGORY_LABELS[cat] || cat}
                  </span>
                  <span className="tag-group-count">{catTags.length}</span>
                  <span className="tag-group-chevron">
                    {expanded[cat] ? '▼' : '▶'}
                  </span>
                </button>
                {expanded[cat] && (
                  <div className="tag-list">
                    {catTags.map((tag, i) => (
                      <div key={i} className="tag-item">
                        <span className="tag-label">{tag.label}</span>
                        <div className="tag-confidence">
                          <div className="tag-confidence-bar">
                            <div
                              className="tag-confidence-fill"
                              style={{
                                width: `${Math.round(tag.confidence * 100)}%`,
                                backgroundColor:
                                  tag.confidence >= 0.7 ? '#22C55E'
                                  : tag.confidence >= 0.4 ? '#F59E0B'
                                  : '#EF4444',
                              }}
                            />
                          </div>
                          <span className="tag-confidence-text">
                            {Math.round(tag.confidence * 100)}%
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )
      )}

      {/* ELA Heatmap View */}
      {activeTab === 'ela' && hasEla && (
        <div className="ela-viewer">
          <div className="ela-comparison">
            {imageUrl && (
              <div className="ela-image-cell">
                <div className="ela-image-label">ORIGINAL</div>
                <img src={imageUrl} alt="Original" className="ela-image" />
              </div>
            )}
            <div className="ela-image-cell">
              <div className="ela-image-label">ELA HEATMAP</div>
              <img
                src={response!.ela_heatmap!}
                alt="ELA heatmap"
                className="ela-image ela-image-heatmap"
              />
            </div>
          </div>
          <div className="ela-info">
            Higher red intensity indicates regions with greater compression
            discrepancy — potential edited or spliced areas.
          </div>
        </div>
      )}

      {/* Sanity Validation Matrix */}
      {activeTab === 'sanity' && (
        <div className="sanity-matrix">
          <div className="sanity-comparison">
            <div className="sanity-card">
              <div className="sanity-card-title">EXIF TELEMETRY PROFILE</div>
              <div className="sanity-card-row">
                <span className="sanity-card-key">Coordinates:</span>
                <span className="sanity-card-val mono">
                  {response?.coordinates
                    ? `${response.coordinates.lat.toFixed(5)}, ${response.coordinates.lon.toFixed(5)}`
                    : 'N/A'}
                </span>
              </div>
              <div className="sanity-card-row">
                <span className="sanity-card-key">Climate Zone:</span>
                <span className="sanity-card-val">
                  {response?.gps_climate_zone || 'N/A'}
                </span>
              </div>
              <div className="sanity-card-row">
                <span className="sanity-card-key">Source:</span>
                <span className="sanity-card-val">{response?.source || 'N/A'}</span>
              </div>
              <div className="sanity-card-row">
                <span className="sanity-card-key">EXIF:</span>
                <span className={`sanity-card-val ${response?.exif_missing ? 'val-red' : 'val-green'}`}>
                  {response?.exif_missing ? 'MISSING' : 'PRESENT'}
                </span>
              </div>
            </div>

            <div className="sanity-card">
              <div className="sanity-card-title">AI VISION OBSERVATIONS</div>
              <div className="sanity-card-row">
                <span className="sanity-card-key">Visual Climate:</span>
                <span className="sanity-card-val">
                  {response?.visual_climate_zone || 'N/A'}
                </span>
              </div>
              <div className="sanity-card-row">
                <span className="sanity-card-key">Evidence Tags:</span>
                <span className="sanity-card-val">{tags.length} tags</span>
              </div>
              <div className="sanity-card-row">
                <span className="sanity-card-key">Confidence:</span>
                <span className="sanity-card-val">
                  {Math.round((response?.consensus?.confidence_score ?? 0) * 100)}%
                </span>
              </div>
              <div className="sanity-card-row">
                <span className="sanity-card-key">Steganography:</span>
                <span className={`sanity-card-val ${response?.steganography_detected ? 'val-red' : 'val-green'}`}>
                  {response?.steganography_detected ? 'DETECTED' : 'CLEAN'}
                </span>
              </div>
            </div>
          </div>

          {/* Verdict */}
          <div className={`sanity-verdict ${hasSpoofing ? 'verdict-spoofed' : 'verdict-clean'}`}>
            <span className="sanity-verdict-icon">
              {hasSpoofing ? '⚠' : '✓'}
            </span>
            <span className="sanity-verdict-text">
              {hasSpoofing
                ? `CONTEXT MISMATCH — Spoofing suspected (${(spoofingScore * 100).toFixed(0)}% anomaly)`
                : 'Context validated — no anomalies detected'}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
