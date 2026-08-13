/**
 * TabBar — dynamic workspace tab strip (VS Code-style).
 *
 * Supports opening, closing, switching between active tool tabs. Each tab
 * represents a *view* over the same evidence, not an independent copy.
 * The [ + ] button exposes a dropdown of available forensic tools.
 */
import React, { useState, useRef, useEffect } from 'react';

export type ToolTabId =
  | 'overview'
  | 'spatial'
  | 'fileforensics'
  | 'discovery'
  | 'provenance'
  | 'vision'
  | 'report';

export interface TabInstance {
  id: string;
  toolId: ToolTabId;
  title: string;
  icon: string;
  dirty?: boolean;
}

interface ToolDefinition {
  toolId: ToolTabId;
  title: string;
  icon: string;
  description: string;
}

const TOOL_REGISTRY: ToolDefinition[] = [
  { toolId: 'spatial', title: 'Map & Spatial Canvas', icon: '🗺', description: 'GIS, satellite, location hypotheses' },
  { toolId: 'fileforensics', title: 'File Forensics & Metadata', icon: '📦', description: 'ExifTool tree, Hex, ELA, JPEG structure' },
  { toolId: 'discovery', title: 'Source Discovery & Footprint', icon: '🔍', description: 'Reverse visual search, web timeline' },
  { toolId: 'provenance', title: 'Provenance & C2PA', icon: '🔐', description: 'Cryptographic signatures, edit manifests' },
  { toolId: 'vision', title: 'OCR & Visual Intelligence', icon: '👁', description: 'Text extraction, object/landmark detection' },
  { toolId: 'report', title: 'Case Report & Evidence Log', icon: '📋', description: 'Chain-of-custody, analyst overrides, PDF' },
];

interface TabBarProps {
  tabs: TabInstance[];
  activeTabId: string | null;
  onSelectTab: (id: string) => void;
  onCloseTab: (id: string) => void;
  onOpenTool: (toolId: ToolTabId) => void;
}

export function TabBar({ tabs, activeTabId, onSelectTab, onCloseTab, onOpenTool }: TabBarProps) {
  const [showMenu, setShowMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showMenu) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowMenu(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showMenu]);

  return (
    <div className="tabbar">
      <div className="tabbar-tabs">
        {tabs.map((tab) => (
          <div
            key={tab.id}
            className={`tabbar-tab ${activeTabId === tab.id ? 'tabbar-tab-active' : ''}`}
            onClick={() => onSelectTab(tab.id)}
            title={tab.title}
          >
            <span className="tabbar-tab-icon">{tab.icon}</span>
            <span className="tabbar-tab-title">{tab.title}</span>
            {tab.dirty && <span className="tabbar-tab-dirty" title="Unsaved changes">●</span>}
            <button
              className="tabbar-tab-close"
              onClick={(e) => { e.stopPropagation(); onCloseTab(tab.id); }}
              title="Close tab"
            >
              ×
            </button>
          </div>
        ))}
      </div>
      <div className="tabbar-actions" ref={menuRef}>
        <button
          className="tabbar-add-btn"
          onClick={() => setShowMenu(!showMenu)}
          title="New Tool Tab"
          disabled={!tabs.length}
        >
          +
        </button>
        {showMenu && (
          <div className="tabbar-dropdown">
            <div className="tabbar-dropdown-header">Forensic Tools</div>
            {TOOL_REGISTRY.map((tool) => (
              <button
                key={tool.toolId}
                className="tabbar-dropdown-item"
                onClick={() => { onOpenTool(tool.toolId); setShowMenu(false); }}
              >
                <span className="tabbar-dropdown-icon">{tool.icon}</span>
                <div className="tabbar-dropdown-text">
                  <div className="tabbar-dropdown-title">{tool.title}</div>
                  <div className="tabbar-dropdown-desc">{tool.description}</div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export { TOOL_REGISTRY };
