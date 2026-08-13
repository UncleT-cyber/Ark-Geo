/**
 * EvidenceExplorer — Explorer-like evidence tree (VS Code-style).
 *
 * Renders a collapsible tree of the case's evidence, metadata, forensics,
 * intelligence, provenance, and sources.  Each leaf is clickable and can
 * open the relevant forensic tool tab.
 */
import React, { useState } from 'react';
import type { AnalyzeResponse } from '../../../types';
import type { ToolTabId } from '../TabBar';

interface EvidenceExplorerProps {
  result: AnalyzeResponse | null;
  onOpenTool: (toolId: ToolTabId) => void;
  thumbnailUrl?: string;
}

interface TreeNode {
  label: string;
  value?: string;
  toolId?: ToolTabId;
  children?: TreeNode[];
}

export function EvidenceExplorer({ result, onOpenTool, thumbnailUrl }: EvidenceExplorerProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set(['case', 'evidence', 'metadata', 'forensics']));

  const toggle = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  if (!result) {
    return (
      <div className="explorer-empty">
        <div className="explorer-empty-icon">🗂</div>
        <div className="explorer-empty-title">No Case Open</div>
        <div className="explorer-empty-text">
          Upload an image to begin an investigation. Evidence will appear here.
        </div>
      </div>
    );
  }

  const caseId = `ARK-${result.request_id.slice(0, 8).toUpperCase()}`;
  const fileName = thumbnailUrl ? 'target.jpg' : 'target.bin';
  const cert = result.custody_certificate;
  const deepGroups = result.deep_metadata?.groups || {};
  const fieldCount = Object.values(deepGroups).reduce((s, g: any) => s + g.length, 0);

  const tree: { section: string; key: string; nodes: TreeNode[] }[] = [
    {
      section: caseId, key: 'case', nodes: [
        { label: fileName, toolId: 'fileforensics' },
      ],
    },
    {
      section: 'Evidence', key: 'evidence', nodes: [
        { label: 'SHA-256', value: result.image_sha256?.slice(0, 16) + '...' },
        { label: 'SHA-1', value: cert?.sha1?.slice(0, 16) + '...' },
        { label: 'MD5', value: cert?.md5?.slice(0, 16) + '...' },
        { label: 'MIME', value: result.file_format || 'N/A' },
        { label: 'Size', value: result.deep_metadata?.file_info?.file_size as string || 'N/A' },
        { label: 'Dimensions', value: result.deep_metadata?.file_info ? `${result.deep_metadata.file_info.image_width}×${result.deep_metadata.file_info.image_height}` : 'N/A' },
      ],
    },
    {
      section: 'Metadata', key: 'metadata', nodes: [
        { label: 'EXIF', value: result.exif_missing ? 'STRIPPED' : `${Object.keys(result.exif_raw || {}).length} fields`, toolId: 'fileforensics' },
        { label: 'ExifTool', value: result.deep_metadata?.available ? `${fieldCount} fields` : 'N/A', toolId: 'fileforensics' },
        { label: 'XMP', value: deepGroups['XMP'] ? `${deepGroups['XMP'].length} fields` : 'none', toolId: 'fileforensics' },
        { label: 'IPTC', value: deepGroups['IPTC'] ? `${deepGroups['IPTC'].length} fields` : 'none', toolId: 'fileforensics' },
        { label: 'ICC', value: deepGroups['ICC_Profile'] ? `${deepGroups['ICC_Profile'].length} fields` : 'none', toolId: 'fileforensics' },
        { label: 'MakerNotes', value: deepGroups['MakerNotes'] ? `${deepGroups['MakerNotes'].length} fields` : 'none', toolId: 'fileforensics' },
      ],
    },
    {
      section: 'Forensics', key: 'forensics', nodes: [
        { label: 'ELA', value: result.ela_heatmap ? 'Available' : 'N/A', toolId: 'fileforensics' },
        { label: 'JPEG Structure', value: result.file_format || 'N/A', toolId: 'fileforensics' },
        { label: 'Steganography', value: result.steganography_detected ? 'DETECTED' : 'clean', toolId: 'fileforensics' },
        { label: 'GPS Spoofing', value: result.gps_spoofing_detected ? 'SUSPECTED' : 'clean', toolId: 'spatial' },
        { label: 'Consistency', value: `${result.consistency_findings?.length || 0} findings`, toolId: 'fileforensics' },
      ],
    },
    {
      section: 'Intelligence', key: 'intelligence', nodes: [
        { label: 'OCR', value: result.consensus?.visual_evidence_tags?.filter(t => t.category === 'ocr').length + ' texts' || 'N/A', toolId: 'vision' },
        { label: 'Objects', value: result.consensus?.visual_evidence_tags?.filter(t => t.category === 'infrastructure').length + ' detected' || 'N/A', toolId: 'vision' },
        { label: 'Landmarks', value: '0 confirmed', toolId: 'vision' },
        { label: 'Geolocation', value: result.coordinates ? `${result.coordinates.lat.toFixed(3)}, ${result.coordinates.lon.toFixed(3)}` : 'N/A', toolId: 'spatial' },
      ],
    },
    {
      section: 'Provenance', key: 'provenance', nodes: [
        { label: 'C2PA', value: result.provenance?.state || 'N/A', toolId: 'provenance' },
      ],
    },
    {
      section: 'Sources', key: 'sources', nodes: [
        { label: 'Exact Matches', value: `${result.source_discovery?.exact_matches?.length || 0}`, toolId: 'discovery' },
        { label: 'Similar Matches', value: `${result.source_discovery?.similar_matches?.length || 0}`, toolId: 'discovery' },
        { label: 'Timeline', value: `${result.source_discovery?.timeline?.length || 0}`, toolId: 'discovery' },
        { label: 'Embedded URLs', value: `${result.source_discovery?.embedded_urls?.length || 0}`, toolId: 'discovery' },
      ],
    },
  ];

  return (
    <div className="explorer">
      <div className="explorer-header">EVIDENCE EXPLORER</div>
      <div className="explorer-tree">
        {tree.map((group) => (
          <div key={group.key} className="explorer-group">
            <div className="explorer-section" onClick={() => toggle(group.key)}>
              <span className="explorer-chevron">{expanded.has(group.key) ? '▾' : '▸'}</span>
              <span className="explorer-section-label">{group.section}</span>
            </div>
            {expanded.has(group.key) && (
              <div className="explorer-children">
                {group.nodes.map((node, i) => (
                  <div
                    key={i}
                    className={`explorer-node ${node.toolId ? 'explorer-node-clickable' : ''}`}
                    onClick={() => node.toolId && onOpenTool(node.toolId)}
                  >
                    <span className="explorer-node-label">{node.label}</span>
                    {node.value && <span className="explorer-node-value mono">{node.value}</span>}
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
