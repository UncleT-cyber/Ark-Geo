/**
 * IngestionSweep — full-screen visual overlay shown while the backend
 * pipeline processes an uploaded image.
 *
 * Features:
 *   - Moving horizontal neon laser scanning line
 *   - Scrolling monospaced terminal text feed with pipeline state updates
 *   - Progress bar synced to the feed lines
 */
import React, { useEffect, useState, useRef } from 'react';

interface Props {
  active: boolean;
  /** Optional live cascade step label (continuous image-intelligence pipeline). */
  phase?: string | null;
}

interface FeedLine {
  text: string;
  tag: 'SYS' | 'INTEGRITY' | 'PARSING' | 'GEOCODE' | 'DONE';
}

const FEED_SEQUENCE: FeedLine[] = [
  { text: '[SYS_INIT] Ingesting asset bytes...', tag: 'SYS' },
  { text: '[INTEGRITY] Compiling cryptographic hash maps...', tag: 'INTEGRITY' },
  { text: '[INTEGRITY] SHA-256 digest computed', tag: 'INTEGRITY' },
  { text: '[INTEGRITY] SHA-1 digest computed', tag: 'INTEGRITY' },
  { text: '[INTEGRITY] MD5 digest computed', tag: 'INTEGRITY' },
  { text: '[PARSING] Inspecting magic bytes and binary structural integrity...', tag: 'PARSING' },
  { text: '[PARSING] Scanning for EOF steganographic anomalies...', tag: 'PARSING' },
  { text: '[PARSING] Extracting EXIF GPS coordinates...', tag: 'PARSING' },
  { text: '[GEOCODE] Reverse geocoding via OpenStreetMap Nominatim...', tag: 'GEOCODE' },
  { text: '[GEOCODE] Address resolved — plotting tactical marker...', tag: 'GEOCODE' },
  { text: '[DONE] Analysis complete — rendering forensic ledger...', tag: 'DONE' },
];

const TAG_COLORS: Record<FeedLine['tag'], string> = {
  SYS: '#38BDF8',
  INTEGRITY: '#7DD3FC',
  PARSING: '#F59E0B',
  GEOCODE: '#22C55E',
  DONE: '#38BDF8',
};

export function IngestionSweep({ active, phase }: Props) {
  const [visibleLines, setVisibleLines] = useState<FeedLine[]>([]);
  const [progress, setProgress] = useState(0);
  const feedEndRef = useRef<HTMLDivElement>(null);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    if (!active) {
      setVisibleLines([]);
      setProgress(0);
      timersRef.current.forEach(clearTimeout);
      timersRef.current = [];
      return;
    }

    // Reset and play the feed sequence
    setVisibleLines([]);
    setProgress(0);
    timersRef.current = [];

    FEED_SEQUENCE.forEach((line, i) => {
      const t = setTimeout(() => {
        setVisibleLines((prev) => [...prev, line]);
        setProgress(((i + 1) / FEED_SEQUENCE.length) * 100);
      }, i * 280);
      timersRef.current.push(t);
    });

    return () => {
      timersRef.current.forEach(clearTimeout);
      timersRef.current = [];
    };
  }, [active]);

  // Auto-scroll feed to bottom
  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [visibleLines]);

  if (!active) return null;

  return (
    <div className="ingestion-sweep-overlay">
      <div className="sweep-laser-line" />
      <div className="sweep-content">
        <div className="sweep-header">
          <div className="sweep-radar">
            <div className="sweep-radar-ring" />
            <div className="sweep-radar-ring sweep-radar-ring-2" />
            <div className="sweep-radar-dot" />
          </div>
          <div className="sweep-title">THE ARK FORENSIC INGESTION</div>
          <div className="sweep-subtitle">Processing target asset through cascade pipeline</div>
          {phase && <div className="sweep-phase mono">{phase}</div>}
        </div>

        <div className="sweep-progress-container">
          <div className="sweep-progress-track">
            <div
              className="sweep-progress-fill"
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="sweep-progress-pct mono">{Math.round(progress)}%</span>
        </div>

        <div className="sweep-terminal">
          <div className="sweep-terminal-header">
            <span className="sweep-terminal-dot sweep-terminal-dot-red" />
            <span className="sweep-terminal-dot sweep-terminal-dot-yellow" />
            <span className="sweep-terminal-dot sweep-terminal-dot-green" />
            <span className="sweep-terminal-title mono">arkgeo-pipeline — bash</span>
          </div>
          <div className="sweep-terminal-body">
            {visibleLines.map((line, i) => (
              <div key={i} className="sweep-terminal-line">
                <span className="sweep-terminal-prompt mono">$</span>
                <span
                  className="sweep-terminal-text mono"
                  style={{ color: TAG_COLORS[line.tag] }}
                >
                  {line.text}
                </span>
              </div>
            ))}
            <div ref={feedEndRef} />
          </div>
        </div>
      </div>
    </div>
  );
}
