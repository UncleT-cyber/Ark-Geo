/**
 * CommandPalette — Cmd/Ctrl+Shift+P command execution (VS Code-style).
 *
 * Provides quick access to forensic commands.  Coexists with the admin
 * login hotkey — the palette takes precedence when a case is open.
 */
import React, { useState, useEffect, useRef } from 'react';
import type { ToolTabId } from './TabBar';

interface Command {
  id: string;
  label: string;
  shortcut?: string;
  action: () => void;
  disabled?: boolean;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  onOpenTool: (toolId: ToolTabId) => void;
  onExportPdf: () => void;
  onUpload: () => void;
  onOpenAdmin: () => void;
  hasResult: boolean;
}

export function CommandPalette({ open, onClose, onOpenTool, onExportPdf, onUpload, onOpenAdmin, hasResult }: CommandPaletteProps) {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const commands: Command[] = [
    { id: 'upload', label: 'Upload Target Image', action: onUpload },
    { id: 'overview', label: 'Open Investigation Overview', action: () => onOpenTool('overview' as ToolTabId), disabled: !hasResult },
    { id: 'spatial', label: 'Open Spatial Canvas', action: () => onOpenTool('spatial'), disabled: !hasResult },
    { id: 'forensics', label: 'Open File Forensics & Metadata', action: () => onOpenTool('fileforensics'), disabled: !hasResult },
    { id: 'discovery', label: 'Open Source Discovery', action: () => onOpenTool('discovery'), disabled: !hasResult },
    { id: 'provenance', label: 'Verify C2PA / Provenance', action: () => onOpenTool('provenance'), disabled: !hasResult },
    { id: 'vision', label: 'Open OCR & Visual Intelligence', action: () => onOpenTool('vision'), disabled: !hasResult },
    { id: 'report', label: 'Open Case Report & Evidence Log', action: () => onOpenTool('report'), disabled: !hasResult },
    { id: 'pdf', label: 'Generate PDF Report', action: onExportPdf, disabled: !hasResult },
    { id: 'admin', label: 'Open Admin Console', action: onOpenAdmin },
  ];

  const filtered = commands.filter(c => c.label.toLowerCase().includes(query.toLowerCase()));

  useEffect(() => {
    if (open) {
      setQuery('');
      setSelected(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  useEffect(() => { setSelected(0); }, [query]);

  if (!open) return null;

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { onClose(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setSelected(s => Math.min(s + 1, filtered.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSelected(s => Math.max(s - 1, 0)); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      const cmd = filtered[selected];
      if (cmd && !cmd.disabled) { cmd.action(); onClose(); }
    }
  };

  return (
    <div className="cmd-palette-overlay" onClick={onClose}>
      <div className="cmd-palette" onClick={e => e.stopPropagation()}>
        <input
          ref={inputRef}
          className="cmd-palette-input"
          placeholder="Type a command..."
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={handleKey}
        />
        <div className="cmd-palette-list">
          {filtered.length === 0 ? (
            <div className="cmd-palette-empty">No matching commands</div>
          ) : filtered.map((cmd, i) => (
            <button
              key={cmd.id}
              className={`cmd-palette-item ${i === selected ? 'cmd-palette-item-selected' : ''} ${cmd.disabled ? 'cmd-palette-item-disabled' : ''}`}
              onClick={() => { if (!cmd.disabled) { cmd.action(); onClose(); } }}
              onMouseEnter={() => setSelected(i)}
            >
              {cmd.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
