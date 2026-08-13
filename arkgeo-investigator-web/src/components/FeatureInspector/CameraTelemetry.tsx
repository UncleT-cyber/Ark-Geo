/**
 * CameraTelemetry — displays extracted camera parameters (Make, Model, Lens,
 * aperture, exposure, ISO, focal length) alongside GPS altitude and timestamp.
 *
 * Only renders when the backend returned real camera metadata from EXIF.
 */
import React from 'react';

interface Props {
  camera?: Record<string, unknown> | null;
  altitude?: number | null;
  datetimeOriginal?: string | null;
  gpsTimestamp?: string | null;
}

const FIELD_LABELS: Record<string, string> = {
  make: 'Make',
  model: 'Model',
  lens_model: 'Lens',
  software: 'Software',
  f_number: 'Aperture',
  exposure_time: 'Exposure',
  iso: 'ISO',
  focal_length: 'Focal Length',
};

function formatValue(key: string, value: unknown): string {
  if (value === null || value === undefined) return '';
  if (key === 'f_number') return `f/${value}`;
  if (key === 'exposure_time') {
    const n = Number(value);
    if (n > 0 && n < 1) return `1/${Math.round(1 / n)}s`;
    return `${value}s`;
  }
  if (key === 'focal_length') return `${value}mm`;
  if (key === 'iso') return `ISO ${value}`;
  return String(value);
}

export function CameraTelemetry({ camera, altitude, datetimeOriginal, gpsTimestamp }: Props) {
  const entries = camera
    ? Object.entries(camera).filter(([, v]) => v !== null && v !== undefined && v !== '')
    : [];

  const hasData = entries.length > 0 || altitude != null || datetimeOriginal || gpsTimestamp;

  if (!hasData) {
    return (
      <div className="panel-section">
        <div className="panel-title">CAMERA TELEMETRY</div>
        <div className="panel-empty">No camera EXIF data extracted</div>
      </div>
    );
  }

  return (
    <div className="panel-section">
      <div className="panel-title">CAMERA TELEMETRY</div>
      <div className="exif-tree">
        {entries.map(([key, value]) => (
          <div key={key} className="exif-row">
            <span className="exif-key mono">{FIELD_LABELS[key] || key}</span>
            <span className="exif-value mono">{formatValue(key, value)}</span>
          </div>
        ))}
        {altitude != null && (
          <div className="exif-row">
            <span className="exif-key mono">Altitude</span>
            <span className="exif-value mono">{altitude.toFixed(1)}m</span>
          </div>
        )}
        {datetimeOriginal && (
          <div className="exif-row">
            <span className="exif-key mono">DateTime</span>
            <span className="exif-value mono">{datetimeOriginal}</span>
          </div>
        )}
        {gpsTimestamp && (
          <div className="exif-row">
            <span className="exif-key mono">GPS Time</span>
            <span className="exif-value mono">{gpsTimestamp}</span>
          </div>
        )}
      </div>
    </div>
  );
}
