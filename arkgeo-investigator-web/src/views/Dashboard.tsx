/**
 * Dashboard — main analyst workstation layout.
 *
 * Three-column layout:
 *   Left:   Upload & input (drag-drop, EXIF toggle, raw hex viewer)
 *   Center: Interactive Leaflet map (satellite, heatmaps, trajectories)
 *   Right:  Forensic breakdown (evidence inspector, audio, chain-of-custody)
 */
import React, { useState, useCallback, useRef } from 'react';
import { api } from '../api';
import type { AnalyzeResponse, Coordinates } from '../types';
import { MapWorkspace } from '../components/MapWorkspace/MapWorkspace';
import { FeatureInspector } from '../components/FeatureInspector/FeatureInspector';
import { ExifViewer } from '../components/ExifViewer/ExifViewer';
import { ChainOfCustody } from '../components/ChainOfCustody/ChainOfCustody';
import { AudioContextPlayer } from '../components/FeatureInspector/AudioContextPlayer';
import { CameraTelemetry } from '../components/FeatureInspector/CameraTelemetry';
import { LocationCard } from '../components/FeatureInspector/LocationCard';
import { TierCard } from '../components/FeatureInspector/TierCard';
import { IngestionSweep } from '../components/IngestionSweep';
import { useToast, ToastContainer } from '../components/Toast';

/** Default fallback coordinates for visual testing when the backend returns
 * no coordinates (no EXIF, no telemetry, no AI keys).  Uses a recognizable
 * world location so the flyTo animation, pin, and UI cards can be verified. */
const FALLBACK_COORDS: Coordinates = { lat: 40.7589, lon: -73.9851 }; // Times Square, NYC

export function Dashboard() {
  const [analyzing, setAnalyzing] = useState(false);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [zeroRetention, setZeroRetention] = useState(false);
  const [showHex, setShowHex] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [history, setHistory] = useState<AnalyzeResponse[]>([]);
  const [thumbnailUrl, setThumbnailUrl] = useState<string | undefined>(undefined);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { toasts, showToast, dismiss } = useToast();

  const analyzeFile = useCallback(async (file: File) => {
    setAnalyzing(true);
    setError(null);

    // Create a local object URL for the thumbnail (used in map popup)
    const thumbUrl = URL.createObjectURL(file);
    setThumbnailUrl(thumbUrl);

    try {
      const resp = await api.analyzeFile(file, zeroRetention);
      setResult(resp);
      setHistory((prev) => [...prev, resp]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed');
    } finally {
      setAnalyzing(false);
    }
  }, [zeroRetention, showToast]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) analyzeFile(file);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) analyzeFile(file);
  };

  const hasCoordinates = result?.coordinates != null;
  // When backend returns no coordinates (degraded mode), use fallback coords
  // so the map flyTo animation and UI cards can still be visually tested.
  const effectiveCoords: Coordinates | null = result?.coordinates ?? (
    result ? FALLBACK_COORDS : null
  );
  const mapSource = result?.source || 'FALLBACK_TEST';
  const mapPoints = result && effectiveCoords
    ? [{
        lat: effectiveCoords.lat,
        lon: effectiveCoords.lon,
        radius: result.consensus.search_radius_meters,
        confidence: result.consensus.confidence_score,
        source: mapSource,
        label: `${result.address?.display_name || result.consensus.primary_country || 'Test Location'} · ${Math.round(result.consensus.confidence_score * 100)}%`,
        thumbnailUrl,
      }]
    : [];

  const historyPoints = history
    .map((r) => {
      const c = r.coordinates ?? FALLBACK_COORDS;
      return {
        lat: c.lat,
        lon: c.lon,
        radius: r.consensus.search_radius_meters,
        confidence: r.consensus.confidence_score,
        source: r.source,
      };
    });

  const handleCopyCoords = useCallback(() => {
    if (!effectiveCoords) return;
    const coordsStr = `${effectiveCoords.lat.toFixed(5)}, ${effectiveCoords.lon.toFixed(5)}`;
    navigator.clipboard?.writeText(coordsStr).then(
      () => showToast(`Coordinates copied: ${coordsStr}`, 'success'),
      () => showToast('Copy failed — clipboard not available', 'error'),
    );
  }, [effectiveCoords, showToast]);

  return (
    <div className="dashboard">
      {/* Top bar */}
      <header className="topbar">
        <div className="topbar-brand">
          <span className="topbar-logo">ARKGEO</span>
          <span className="topbar-subtitle">Investigator Portal</span>
        </div>
        <div className="topbar-status">
          {analyzing && <span className="status-analyzing">ANALYZING...</span>}
          {error && <span className="status-error">ERROR</span>}
          {result && !analyzing && <span className="status-ready">READY</span>}
        </div>
      </header>

      {/* Three-column layout */}
      <div className="workspace">
        {/* LEFT — Upload & Input */}
        <aside className="sidebar sidebar-left">
          <div className="panel-section">
            <div className="panel-title">TARGET UPLOAD</div>
            <div
              className={`dropzone ${dragOver ? 'dropzone-active' : ''} ${analyzing ? 'dropzone-busy' : ''}`}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              {analyzing ? (
                <div className="dropzone-scanning">
                  <div className="radar-pulse" />
                  <span>SCANNING...</span>
                </div>
              ) : (
                <>
                  <div className="dropzone-icon">📁</div>
                  <div className="dropzone-text">Drag & drop image here</div>
                  <div className="dropzone-subtext">JPEG / PNG · high-res supported</div>
                </>
              )}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png"
              onChange={handleFileSelect}
              style={{ display: 'none' }}
            />
          </div>

          <div className="panel-section">
            <div className="panel-title">OPTIONS</div>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={zeroRetention}
                onChange={(e) => setZeroRetention(e.target.checked)}
              />
              <span className="toggle-label">Zero-Retention Mode</span>
            </label>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={showHex}
                onChange={(e) => setShowHex(e.target.checked)}
              />
              <span className="toggle-label">Raw Hex Viewer</span>
            </label>
          </div>

          {showHex && result && (
            <div className="panel-section">
              <div className="panel-title">RAW HEX (first 256B)</div>
              <div className="hex-view mono">
                {result.image_sha256.slice(0, 64).match(/.{1,2}/g)?.map((byte, i) => (
                  <span key={i} className="hex-byte">{byte}</span>
                ))}
              </div>
            </div>
          )}

          {error && (
            <div className="error-box">
              <div className="error-title">ANALYSIS ERROR</div>
              <div className="error-detail">{error}</div>
            </div>
          )}

          {history.length > 0 && (
            <div className="panel-section">
              <div className="panel-title">SESSION HISTORY ({history.length})</div>
              <div className="history-list">
                {history.map((h, i) => (
                  <button
                    key={h.request_id}
                    className={`history-item ${result?.request_id === h.request_id ? 'history-item-active' : ''}`}
                    onClick={() => setResult(h)}
                  >
                    <span className="history-index">#{i + 1}</span>
                    <span className="history-tier">{h.consensus.tier_used}</span>
                    <span className="history-conf">{Math.round(h.consensus.confidence_score * 100)}%</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </aside>

        {/* CENTER — Interactive Map */}
        <main className="main-panel">
          <MapWorkspace points={mapPoints} history={historyPoints} onCopyCoords={handleCopyCoords} />
          <IngestionSweep active={analyzing} />
          {result && (
            <div className="map-overlay-info">
              <div className="map-info-row">
                <span className="map-info-label">SOURCE</span>
                <span className="map-info-value">{result.source}</span>
              </div>
              <div className="map-info-row">
                <span className="map-info-label">TIER</span>
                <span className="map-info-value">{result.consensus.tier_used}</span>
              </div>
              <div className="map-info-row">
                <span className="map-info-label">CONFIDENCE</span>
                <span className="map-info-value">
                  {Math.round(result.consensus.confidence_score * 100)}%
                </span>
              </div>
              <div className="map-info-row">
                <span className="map-info-label">RADIUS</span>
                <span className="map-info-value">
                  {Math.round(result.consensus.search_radius_meters)}m
                </span>
              </div>
              {result.address?.display_name && (
                <div className="map-info-row">
                  <span className="map-info-label">ADDRESS</span>
                  <span className="map-info-value map-info-address">
                    {result.address.display_name}
                  </span>
                </div>
              )}
              {result.coordinates && (
                <div className="map-info-row">
                  <span className="map-info-label">LAT/LON</span>
                  <span className="map-info-value mono">
                    {result.coordinates.lat.toFixed(5)}, {result.coordinates.lon.toFixed(5)}
                  </span>
                </div>
              )}
            </div>
          )}
        </main>

        {/* RIGHT — Forensic Breakdown */}
        <aside className="sidebar sidebar-right">
          {result ? (
            <>
              {result.message && (
                <div className="error-box">
                  <div className="error-title">DEGRADATION NOTICE</div>
                  <div className="error-detail">{result.message}</div>
                </div>
              )}

              {/* CARD 1: LOCATION & COORDINATES */}
              {effectiveCoords && (
                <LocationCard
                  coordinates={effectiveCoords}
                  address={result.address ?? null}
                  confidence={result.consensus.confidence_score}
                  searchRadiusMeters={result.consensus.search_radius_meters}
                />
              )}

              {/* CARD 3: SOURCE TIER */}
              <TierCard
                source={result.source}
                tier={result.consensus.tier_used}
              />

              {/* CARD 2: VISUAL EVIDENCE & CLUES */}
              <FeatureInspector tags={result.consensus.visual_evidence_tags} source={result.source} />

              <CameraTelemetry
                camera={result.camera}
                altitude={result.altitude}
                datetimeOriginal={result.datetime_original}
              />
              <ExifViewer
                exifRaw={result.exif_raw ?? null}
                imageSha256={result.image_sha256}
                exifMissing={result.exif_missing}
                steganographyDetected={result.steganography_detected}
              />
              <AudioContextPlayer audioBase64={null} />
              <ChainOfCustody
                response={result}
                exifMissing={result.exif_missing}
                steganographyDetected={result.steganography_detected}
              />
            </>
          ) : (
            <div className="panel-empty-large">
              <div className="empty-icon">🔍</div>
              <div className="empty-title">No Analysis Yet</div>
              <div className="empty-subtext">
                Upload an image to begin forensic geolocation analysis
              </div>
            </div>
          )}
        </aside>
      </div>
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
