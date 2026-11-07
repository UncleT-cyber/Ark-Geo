/**
 * ARK Browser — the central browsing workspace.
 *
 * This is a first-class application surface: `+ → Browser` opens it in the
 * central work area, replacing the active investigation view, exactly like any
 * other workspace. It is deliberately **not** an inspector squeezed into the
 * narrow ARK conversation dock.
 *
 * CAI decides *when* to browse; this surface shows *what* it is browsing and
 * lets the operator drive. It is screenshot-first: frames arrive as PNG captures
 * from the backend transport and are never proxied into an arbitrary
 * cross-origin iframe, so the operator view stays outside the untrusted page's
 * origin. A screenshot is presented as a captured frame — never as a live
 * session — and the view states plainly whether ARK or the operator is driving.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import type { BrowserSessionInfo } from '../../types';
import { useCaiBrowser } from './caiBrowserBus';
import {
  Globe, RefreshCw, MousePointerClick, Hand, Play, X, AlertTriangle,
  Camera, ShieldOff, ArrowLeft, ArrowRight, RotateCw, CornerDownLeft, Plus,
} from 'lucide-react';

const POLL_MS = 3000;

function timeAgo(ms: number): string {
  if (!ms) return '—';
  const secs = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  return `${Math.round(secs / 3600)}h ago`;
}

export function BrowserWorkspace({ onClose, caseId = '' }: { onClose: () => void; caseId?: string }) {
  const bus = useCaiBrowser();
  const [sessions, setSessions] = useState<BrowserSessionInfo[]>([]);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(bus.activeSessionId);
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [frameStamp, setFrameStamp] = useState<number>(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [urlDraft, setUrlDraft] = useState('');
  const pollRef = useRef<number | null>(null);

  const selectedSession = sessions.find(s => s.session_id === selected) ?? null;

  const refresh = useCallback(async () => {
    try {
      const status = await api.browserStatus();
      setAvailable(status.available);
      setReason(status.reason);
      setSessions(status.sessions ?? []);
      setError(null);
      setSelected(prev => {
        if (prev && (status.sessions ?? []).some(s => s.session_id === prev)) return prev;
        return status.sessions?.[0]?.session_id ?? null;
      });
    } catch {
      setAvailable(false);
      setReason('Backend unreachable');
    }
  }, []);

  /** Load the latest captured frame (or capture a fresh one) for a session. */
  const loadFrame = useCallback(async (sessionId: string, fresh: boolean) => {
    try {
      const url = fresh
        ? await api.browserCaptureUrl(sessionId)
        : `${await api.browserFrameUrl(sessionId)}?t=${Date.now()}`;
      setFrameUrl(url);
      setFrameStamp(Date.now());
    } catch {
      if (fresh) throw new Error('Capture failed');
      setFrameUrl(null);
    }
  }, []);

  // Poll while mounted; also react to live CAI browser tool activity.
  useEffect(() => { void refresh(); }, [refresh, bus.revision]);
  useEffect(() => {
    pollRef.current = window.setInterval(() => { void refresh(); }, POLL_MS);
    return () => { if (pollRef.current) window.clearInterval(pollRef.current); };
  }, [refresh]);

  // Follow CAI's active session unless the operator pinned one.
  useEffect(() => {
    if (bus.activeSessionId) setSelected(bus.activeSessionId);
  }, [bus.activeSessionId]);

  // Follow the session's captured frames as ARK drives (no fresh capture —
  // those are expensive and would race the agent's own screenshots).
  useEffect(() => {
    if (!selected) { setFrameUrl(null); return; }
    void loadFrame(selected, false);
  }, [selected, bus.revision, loadFrame]);

  useEffect(() => {
    if (selectedSession) setUrlDraft(selectedSession.url ?? '');
  }, [selectedSession?.url, selected]);

  const navigate = useCallback(async (event: React.FormEvent) => {
    event.preventDefault();
    if (!urlDraft.trim()) return;
    setBusy(true); setError(null);
    try {
      // With no live session, a URL from the omnibox starts one there.
      if (!selected) {
        const session = await api.browserOpen(urlDraft.trim(), '', caseId);
        setSelected(session.session_id);
        await loadFrame(session.session_id, true);
      } else {
        await api.browserNavigate(selected, urlDraft.trim());
        await loadFrame(selected, true);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Navigation failed (blocked or unreachable)');
    } finally { setBusy(false); }
  }, [selected, urlDraft, loadFrame, refresh, caseId]);

  const openSession = useCallback(async (url = '') => {
    setBusy(true); setError(null);
    try {
      const session = await api.browserOpen(url, '', caseId);
      setSelected(session.session_id);
      await refresh();
      await loadFrame(session.session_id, true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not open a browser session');
    } finally { setBusy(false); }
  }, [refresh, loadFrame, caseId]);

  const history = useCallback(async (action: 'back' | 'forward' | 'reload') => {
    if (!selected) return;
    setBusy(true); setError(null);
    try {
      await api.browserHistory(selected, action);
      await loadFrame(selected, true);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'History action failed');
    } finally { setBusy(false); }
  }, [selected, loadFrame, refresh]);

  const capture = useCallback(async () => {
    if (!selected) return;
    setBusy(true); setError(null);
    try {
      await loadFrame(selected, true);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Capture failed');
    } finally { setBusy(false); }
  }, [selected, loadFrame, refresh]);

  const takeControl = useCallback(async () => {
    if (!selected) return;
    setBusy(true);
    try {
      await api.browserControl(selected, selectedSession?.control === 'operator' ? 'return' : 'take');
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Control request failed');
    } finally { setBusy(false); }
  }, [selected, selectedSession?.control, refresh]);

  if (available === false) {
    return (
      <div className="ark-browser-ws ark-browser-ws-unavailable">
        <AlertTriangle size={30} />
        <h2>Managed browser unavailable</h2>
        <p>{reason || 'Playwright / Chromium is not installed in this backend environment.'}</p>
        <p className="ark-browser-ws-hint">
          The browser runtime is optional. Static retrieval (web.fetch / web.extract /
          web.links) and search remain available.
        </p>
      </div>
    );
  }

  return (
    <div className="ark-browser-ws">
      <div className="ark-browser-ws-toolbar">
        <div className="ark-browser-ws-nav" role="group" aria-label="History">
          <button type="button" onClick={() => void history('back')} disabled={!selected || busy} title="Back" aria-label="Back">
            <ArrowLeft size={15} />
          </button>
          <button type="button" onClick={() => void history('forward')} disabled={!selected || busy} title="Forward" aria-label="Forward">
            <ArrowRight size={15} />
          </button>
          <button type="button" onClick={() => void history('reload')} disabled={!selected || busy} title="Reload" aria-label="Reload">
            <RotateCw size={15} />
          </button>
        </div>

        <form className="ark-browser-ws-omnibox" onSubmit={navigate}>
          <Globe size={13} className="ark-browser-ws-omnibox-icon" />
          <input value={urlDraft} onChange={e => setUrlDraft(e.target.value)}
            placeholder={selected
              ? 'Enter a URL — navigation is validated by the egress guard'
              : 'Enter a URL to start a managed session'}
            aria-label="Navigate URL" spellCheck={false} disabled={busy} />
          <button type="submit" disabled={busy} title={selected ? 'Navigate' : 'Start session'} aria-label="Navigate">
            <CornerDownLeft size={14} />
          </button>
        </form>

        <button type="button" className="ark-browser-ws-btn" onClick={capture} disabled={!selected || busy} title="Capture a fresh frame">
          <Camera size={14} /> Capture
        </button>

        <button type="button" className="ark-browser-ws-btn" onClick={() => void openSession()} disabled={busy} title="Open a new managed browser session">
          <Plus size={14} /> New session
        </button>

        <select className="ark-browser-ws-sessions" aria-label="Browser session"
          value={selected ?? ''} disabled={!sessions.length}
          onChange={e => { setSelected(e.target.value || null); bus.focusSession(e.target.value || null); }}>
          {!sessions.length && <option value="">No session</option>}
          {sessions.map(s => (
            <option key={s.session_id} value={s.session_id}>
              {(s.title || s.url || s.session_id).slice(0, 60)}
            </option>
          ))}
        </select>

        {selectedSession && (
          <button type="button" className="ark-browser-ws-btn" onClick={takeControl} disabled={busy}>
            {selectedSession.control === 'operator'
              ? <><MousePointerClick size={14} /> Return to ARK</>
              : <><Hand size={14} /> Take control</>}
          </button>
        )}

        <button type="button" className="ark-browser-ws-btn ark-browser-ws-close"
          onClick={onClose} title="Close browser workspace" aria-label="Close browser workspace">
          <X size={15} />
        </button>
      </div>

      <div className="ark-browser-ws-statusbar">
        {selectedSession ? (
          <>
            <span className={`ark-browser-ws-live ${selectedSession.control}`}>
              {selectedSession.control === 'operator'
                ? <><Hand size={12} /> Operator in control</>
                : <><Play size={12} /> ARK driving</>}
            </span>
            <span className="ark-browser-ws-url mono" title={selectedSession.url}>{selectedSession.url || 'about:blank'}</span>
            <span className="ark-browser-ws-meta">{selectedSession.tab_count} tab{selectedSession.tab_count === 1 ? '' : 's'}</span>
            {selectedSession.blocked_requests > 0 && (
              <span className="ark-browser-ws-blocked" title="Requests blocked by the egress guard">
                <ShieldOff size={11} /> {selectedSession.blocked_requests} blocked
              </span>
            )}
            <span className="ark-browser-ws-meta ark-browser-ws-refresh" title="Refresh session list"
              onClick={() => void refresh()} role="button" tabIndex={0}
              onKeyDown={e => { if (e.key === 'Enter') void refresh(); }}>
              <RefreshCw size={11} /> {timeAgo(frameStamp)}
            </span>
          </>
        ) : (
          <span className="ark-browser-ws-meta">No active session</span>
        )}
      </div>

      <div className="ark-browser-ws-stage">
        {!selectedSession ? (
          <div className="ark-browser-ws-placeholder">
            <Globe size={44} />
            <p>No managed browser session.</p>
            <p className="ark-browser-ws-hint">
              Open one to browse directly, or ask ARK to research a site — when a
              page needs rendering it opens a managed session and it appears here.
            </p>
            <button type="button" className="ark-browser-ws-btn" onClick={() => void openSession()} disabled={busy}>
              <Plus size={14} /> Open a session
            </button>
          </div>
        ) : frameUrl ? (
          <>
            <img src={frameUrl} alt={`Captured frame of ${selectedSession.url}`} />
            <span className="ark-browser-ws-frame-note">Captured frame · {timeAgo(frameStamp)}</span>
          </>
        ) : (
          <div className="ark-browser-ws-placeholder">
            <Camera size={30} />
            <p>No frame captured yet.</p>
            <button type="button" className="ark-browser-ws-btn" onClick={capture} disabled={busy}>
              <Camera size={14} /> Capture frame
            </button>
          </div>
        )}
        {error && <p className="ark-browser-ws-error" role="alert">{error}</p>}
      </div>

      {selectedSession && selectedSession.artifacts.length > 0 && (
        <div className="ark-browser-ws-artifacts">
          <span className="ark-browser-ws-artifacts-label">Evidence artifacts</span>
          {selectedSession.artifacts.slice(-8).map(a => (
            <span key={a.sha256} className="ark-browser-ws-artifact mono"
              title={`${a.path}\nsha256 ${a.sha256}`}>
              {a.kind} · {a.sha256.slice(0, 10)}… · {(a.bytes / 1024).toFixed(0)} KB
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
