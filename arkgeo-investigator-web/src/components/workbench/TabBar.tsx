/**
 * TabBar — dynamic workspace tab strip (VS Code-style).
 *
 * Supports opening, closing, switching between active tool tabs. Each tab
 * represents a *view* over the same evidence, not an independent copy.
 * The [ + ] button exposes a dropdown of available forensic tools.
 *
 * The dropdown separates core investigation views (already part of the
 * primary workflow) from specialized analysis tools that can be opened
 * on demand. Core tools open instantly; the launcher exists to reopen
 * closed tabs or surface secondary capabilities.
 */
import React, { useState, useRef, useEffect } from 'react';
import { Plus } from 'lucide-react';
import { TOOL_ICONS, type LucideIcon } from './icons';

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
  icon: LucideIcon;
  dirty?: boolean;
}

interface ToolDefinition {
  toolId: ToolTabId;
  title: string;
  icon: LucideIcon;
  description: string;
}

/** Core investigation views — part of the primary case workflow. */
const CORE_TOOLS: ToolDefinition[] = [
  { toolId: 'spatial', title: 'Spatial Canvas', icon: TOOL_ICONS.spatial, description: 'GIS, satellite, location hypotheses' },
  { toolId: 'fileforensics', title: 'File Forensics', icon: TOOL_ICONS.fileforensics, description: 'ExifTool tree, Hex, ELA, JPEG structure' },
  { toolId: 'vision', title: 'OCR & Vision', icon: TOOL_ICONS.vision, description: 'Text extraction, object/landmark detection' },
];

/** Specialized analysis tools — opened on demand for deeper inquiry. */
const SPECIALIZED_TOOLS: ToolDefinition[] = [
  { toolId: 'discovery', title: 'Source Discovery', icon: TOOL_ICONS.discovery, description: 'Reverse visual search, web timeline' },
  { toolId: 'provenance', title: 'Provenance & C2PA', icon: TOOL_ICONS.provenance, description: 'Cryptographic signatures, edit manifests' },
  { toolId: 'report', title: 'Case Report', icon: TOOL_ICONS.report, description: 'Chain-of-custody, analyst overrides, PDF' },
];

/** Full registry (kept for backwards-compatible imports). */
const TOOL_REGISTRY: ToolDefinition[] = [...CORE_TOOLS, ...SPECIALIZED_TOOLS];

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

  const openToolIds = new Set(tabs.map(t => t.toolId));

  return (
    <div className="tabbar">
      <div className="tabbar-tabs">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <div
              key={tab.id}
              className={`tabbar-tab ${activeTabId === tab.id ? 'tabbar-tab-active' : ''}`}
              onClick={() => onSelectTab(tab.id)}
              title={tab.title}
            >
              <span className="tabbar-tab-icon"><Icon className="w-4 h-4" /></span>
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
          );
        })}
      </div>
      <div className="tabbar-actions" ref={menuRef}>
        <button
          className="tabbar-add-btn"
          onClick={() => setShowMenu(!showMenu)}
          title="Open investigation tool"
          disabled={!tabs.length}
        >
          <Plus className="w-4 h-4" />
        </button>
        {showMenu && (
          <div className="tabbar-dropdown">
            <div className="tabbar-dropdown-header">Open Investigation Tool</div>
            <div className="tabbar-dropdown-group-label">CORE INVESTIGATION</div>
            {CORE_TOOLS.map((tool) => {
              const Icon = tool.icon;
              const isOpen = openToolIds.has(tool.toolId);
              return (
                <button
                  key={tool.toolId}
                  className={`tabbar-dropdown-item ${isOpen ? 'tabbar-dropdown-item-active' : ''}`}
                  onClick={() => { onOpenTool(tool.toolId); setShowMenu(false); }}
                >
                  <span className="tabbar-dropdown-icon"><Icon className="w-4 h-4" /></span>
                  <div className="tabbar-dropdown-text">
                    <div className="tabbar-dropdown-title">{tool.title}</div>
                    <div className="tabbar-dropdown-desc">{tool.description}</div>
                  </div>
                  {isOpen && <span className="tabbar-dropdown-open-tag">OPEN</span>}
                </button>
              );
            })}
            <div className="tabbar-dropdown-divider" />
            <div className="tabbar-dropdown-group-label">SPECIALIZED ANALYSIS</div>
            {SPECIALIZED_TOOLS.map((tool) => {
              const Icon = tool.icon;
              const isOpen = openToolIds.has(tool.toolId);
              return (
                <button
                  key={tool.toolId}
                  className={`tabbar-dropdown-item ${isOpen ? 'tabbar-dropdown-item-active' : ''}`}
                  onClick={() => { onOpenTool(tool.toolId); setShowMenu(false); }}
                >
                  <span className="tabbar-dropdown-icon"><Icon className="w-4 h-4" /></span>
                  <div className="tabbar-dropdown-text">
                    <div className="tabbar-dropdown-title">{tool.title}</div>
                    <div className="tabbar-dropdown-desc">{tool.description}</div>
                  </div>
                  {isOpen && <span className="tabbar-dropdown-open-tag">OPEN</span>}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export { TOOL_REGISTRY, CORE_TOOLS, SPECIALIZED_TOOLS };
