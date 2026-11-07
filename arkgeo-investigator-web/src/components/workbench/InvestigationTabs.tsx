/**
 * Investigation tab strip + notification bell — the whole top navigation
 * surface for both the desktop titlebar and the web topbar.
 *
 * Single row, horizontally scrollable, tabs truncate gracefully, an overflow
 * menu appears only when tabs exceed the available width, and `+` creates a
 * new investigation. No second navigation row is introduced.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Bell, ChevronDown, Plus, X } from 'lucide-react';
import type { InvestigationTab } from '../../core/tabs/tabRegistry';
import { NOTIFICATION_META, type AppNotification } from '../../core/notifications';

const STATUS_DOT: Record<string, string> = {
  idle: 'ark-tab-dot-idle',
  running: 'ark-tab-dot-running',
  completed: 'ark-tab-dot-done',
  failed: 'ark-tab-dot-failed',
  interrupted: 'ark-tab-dot-interrupted',
};

interface TabStripProps {
  tabs: InvestigationTab[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  onNew: () => void;
}

export function InvestigationTabStrip({ tabs, activeId, onSelect, onClose, onNew }: TabStripProps) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const [overflowing, setOverflowing] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const measure = () => setOverflowing(el.scrollWidth > el.clientWidth + 2);
    measure();
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
    ro?.observe(el);
    window.addEventListener('resize', measure);
    return () => { ro?.disconnect(); window.removeEventListener('resize', measure); };
  }, [tabs.length]);

  // Keep the active tab visible when it changes.
  useEffect(() => {
    const el = scrollerRef.current?.querySelector<HTMLElement>('[data-active="true"]');
    el?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [activeId]);

  useEffect(() => {
    if (!menuOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest('.ark-tab-overflow')) setMenuOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [menuOpen]);

  return (
    <div className="ark-tab-strip" role="tablist" aria-label="Investigation tabs">
      <div className="ark-tab-scroller" ref={scrollerRef}>
        {tabs.map(tab => (
          <div
            key={tab.id}
            role="tab"
            tabIndex={0}
            data-active={tab.id === activeId}
            aria-selected={tab.id === activeId}
            className={`ark-tab ${tab.id === activeId ? 'ark-tab-active' : ''}`}
            title={tab.title}
            onClick={() => onSelect(tab.id)}
            onKeyDown={e => {
              if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(tab.id); }
            }}
          >
            <span className={`ark-tab-dot ${STATUS_DOT[tab.runStatus] ?? STATUS_DOT.idle}`} aria-hidden="true" />
            <span className="ark-tab-title">{tab.title}</span>
            <button
              type="button"
              className="ark-tab-close"
              aria-label={`Close ${tab.title}`}
              onClick={e => { e.stopPropagation(); onClose(tab.id); }}
            >
              <X size={13} />
            </button>
          </div>
        ))}
      </div>

      {/* `+` sits immediately after the scroller's visible edge — i.e. right
          after the final visible tab — and stays there under overflow. */}
      <button type="button" className="ark-tab-new" onClick={onNew} title="New investigation" aria-label="New investigation">
        <Plus size={17} />
      </button>

      {overflowing && (
        <div className="ark-tab-overflow">
          <button type="button" className="ark-tab-overflow-btn" aria-label="All investigations"
            aria-expanded={menuOpen} onClick={() => setMenuOpen(v => !v)} title="All investigations">
            <ChevronDown size={15} />
          </button>
          {menuOpen && (
            <div className="ark-tab-overflow-menu" role="menu">
              {tabs.map(tab => (
                <div key={tab.id} role="menuitem" tabIndex={0}
                  className={`ark-tab-overflow-item ${tab.id === activeId ? 'ark-tab-overflow-item-active' : ''}`}
                  onClick={() => { onSelect(tab.id); setMenuOpen(false); }}
                  onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(tab.id); setMenuOpen(false); } }}>
                  <span className={`ark-tab-dot ${STATUS_DOT[tab.runStatus] ?? STATUS_DOT.idle}`} aria-hidden="true" />
                  <span className="ark-tab-overflow-title">{tab.title}</span>
                  <button
                    type="button"
                    className="ark-tab-overflow-close"
                    aria-label={`Close ${tab.title}`}
                    onClick={e => { e.stopPropagation(); onClose(tab.id); }}
                  >
                    <X size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface BellProps {
  notifications: AppNotification[];
  unread: number;
  onOpen: (n: AppNotification) => void;
  onMarkAllRead: () => void;
}

export function NotificationBell({ notifications, unread, onOpen, onMarkAllRead }: BellProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const items = useMemo(() => notifications.slice(0, 30), [notifications]);

  return (
    <div className="ark-bell" ref={ref}>
      <button type="button" className="ark-bell-btn" aria-label={`Notifications (${unread} unread)`}
        aria-expanded={open} title="Notifications" onClick={() => setOpen(v => !v)}>
        <Bell size={17} />
        {unread > 0 && <span className="ark-bell-count" aria-hidden="true">{unread > 99 ? '99+' : unread}</span>}
      </button>
      {open && (
        <div className="ark-bell-menu" role="menu" aria-label="Notifications">
          <div className="ark-bell-head">
            <span>Notifications</span>
            {unread > 0 && <button type="button" className="ark-bell-clear" onClick={onMarkAllRead}>Mark all read</button>}
          </div>
          {items.length === 0 ? (
            <div className="ark-bell-empty">No notifications yet.</div>
          ) : items.map(n => {
            const meta = NOTIFICATION_META[n.kind];
            return (
              <button key={n.id} type="button" role="menuitem"
                className={`ark-bell-item ${n.read ? '' : 'ark-bell-item-unread'}`}
                onClick={() => { onOpen(n); setOpen(false); }}>
                <span className={`ark-bell-tone ark-bell-tone-${meta.tone}`} aria-hidden="true" />
                <span className="ark-bell-body">
                  <span className="ark-bell-title">{n.title}</span>
                  <span className="ark-bell-detail">{n.detail}</span>
                </span>
                <span className="ark-bell-kind">{meta.label}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
