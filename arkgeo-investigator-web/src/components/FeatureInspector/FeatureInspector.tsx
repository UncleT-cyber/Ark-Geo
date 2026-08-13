/**
 * FeatureInspector — grouped expandable tags for detected architecture,
 * flora, signage, and OCR text.
 */
import React, { useState } from 'react';
import type { VisualEvidenceTag } from '../../types';

interface Props {
  tags: VisualEvidenceTag[];
}

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

export function FeatureInspector({ tags }: Props) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

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

  if (tags.length === 0) {
    return (
      <div className="panel-section">
        <div className="panel-title">VISUAL EVIDENCE</div>
        <div className="panel-empty">No evidence tags extracted</div>
      </div>
    );
  }

  return (
    <div className="panel-section">
      <div className="panel-title">VISUAL EVIDENCE INSPECTOR</div>
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
    </div>
  );
}
