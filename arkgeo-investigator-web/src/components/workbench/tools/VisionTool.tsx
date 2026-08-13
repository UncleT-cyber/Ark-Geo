/**
 * VisionTool — OCR & Visual Intelligence.
 *
 * Displays OCR-extracted text, visual evidence tags (architecture, botanical,
 * infrastructure), and their geographic relevance.  Uses existing extraction
 * results from the consensus engine.  Shows graceful degradation when
 * OCR/AI providers are unavailable.
 */
import React from 'react';
import type { AnalyzeResponse, VisualEvidenceTag } from '../../../types';

interface VisionToolProps {
  result: AnalyzeResponse;
}

function categoryColor(cat: string): string {
  switch (cat) {
    case 'ocr': return '#38BDF8';
    case 'botanical': return '#22C55E';
    case 'architecture': return '#F59E0B';
    case 'infrastructure': return '#A78BFA';
    default: return '#94A3B8';
  }
}

function relevanceColor(conf: number): string {
  if (conf >= 0.7) return '#22C55E';
  if (conf >= 0.4) return '#F59E0B';
  return '#EF4444';
}

export function VisionTool({ result }: VisionToolProps) {
  const tags = result.consensus?.visual_evidence_tags || [];
  const ocrTags = tags.filter(t => t.category === 'ocr');
  const visualTags = tags.filter(t => t.category !== 'ocr');
  const aiKeysConfigured = result.source !== 'EXIF_MISSING_NO_AI_KEY' && result.source !== 'NATIVE_EXIF_HARDWARE';

  return (
    <div className="tool-view tool-vision">
      <div className="tool-content">
        {!aiKeysConfigured && result.source === 'EXIF_MISSING_NO_AI_KEY' && (
          <div className="vision-degraded">
            <div className="vision-degraded-title">VISUAL AI: UNAVAILABLE</div>
            <div className="vision-degraded-text">
              No AI vision API keys are configured on the server. OCR and visual object
              detection require an LLM provider. Configure one through Admin to enable this capability.
              Other analysis (EXIF, ELA, ExifTool) remains fully functional.
            </div>
          </div>
        )}

        <div className="vision-section">
          <div className="vision-section-title">OCR EXTRACTED TEXT ({ocrTags.length})</div>
          {ocrTags.length === 0 ? (
            <div className="vision-empty">
              {aiKeysConfigured ? 'No text regions detected in this image.' : 'OCR provider not configured.'}
            </div>
          ) : (
            <div className="vision-ocr-list">
              {ocrTags.map((tag, i) => (
                <div key={i} className="vision-ocr-item">
                  <div className="vision-ocr-text">"{tag.label}"</div>
                  <div className="vision-ocr-meta">
                    <span className="vision-ocr-conf" style={{ color: relevanceColor(tag.confidence) }}>
                      Confidence: {Math.round(tag.confidence * 100)}%
                    </span>
                    <span className="vision-ocr-rel">Geographic relevance: {tag.confidence >= 0.6 ? 'HIGH' : tag.confidence >= 0.3 ? 'MEDIUM' : 'LOW'}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="vision-section">
          <div className="vision-section-title">VISUAL OBJECTS & CLUES ({visualTags.length})</div>
          {visualTags.length === 0 ? (
            <div className="vision-empty">No visual objects detected.</div>
          ) : (
            <div className="vision-tag-grid">
              {visualTags.map((tag, i) => (
                <div key={i} className="vision-tag-card" style={{ borderLeftColor: categoryColor(tag.category) }}>
                  <div className="vision-tag-cat" style={{ color: categoryColor(tag.category) }}>{tag.category}</div>
                  <div className="vision-tag-label">{tag.label}</div>
                  <div className="vision-tag-conf">{Math.round(tag.confidence * 100)}%</div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="vision-section">
          <div className="vision-section-title">SCENE CLASSIFICATION</div>
          <div className="vision-scene">
            <div className="vision-scene-row">
              <span className="vision-scene-label">Climate Zone (GPS):</span>
              <span className="vision-scene-value mono">{result.gps_climate_zone || 'N/A'}</span>
            </div>
            <div className="vision-scene-row">
              <span className="vision-scene-label">Climate Zone (Visual):</span>
              <span className="vision-scene-value mono">{result.visual_climate_zone || 'N/A'}</span>
            </div>
            <div className="vision-scene-row">
              <span className="vision-scene-label">Anomaly Score:</span>
              <span className="vision-scene-value mono" style={{ color: (result.anomaly_score || 0) >= 0.5 ? '#EF4444' : '#22C55E' }}>
                {Math.round((result.anomaly_score || 0) * 100)}%
              </span>
            </div>
            {(result.sanity_mismatches || []).map((m, i) => (
              <div key={i} className="vision-mismatch">⚠ {m}</div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
