/**
 * PDF / Case Evidence Export — generates a formatted forensic report.
 *
 * Uses the browser's native print-to-PDF via a styled HTML report window.
 * This avoids heavy dependencies (jspdf) and produces a clean, formatted
 * document capturing map telemetry, SHA-256 integrity seals, and target
 * image metadata.
 */
import type { AnalyzeResponse } from './types';

export function exportCasePdf(result: AnalyzeResponse, thumbnailUrl?: string): void {
  const reportWindow = window.open('', '_blank', 'width=800,height=1000');
  if (!reportWindow) {
    throw new Error('Popup blocked — allow popups to export PDF');
  }

  const coords = result.coordinates
    ? `${result.coordinates.lat.toFixed(5)}°, ${result.coordinates.lon.toFixed(5)}°`
    : 'N/A (no coordinates — EXIF missing, no AI keys configured)';

  const cert = result.custody_certificate;
  const tags = result.consensus.visual_evidence_tags || [];
  const tagsHtml = tags.length > 0
    ? tags.map((t) => `
        <tr>
          <td>${t.category}</td>
          <td>${t.label}</td>
          <td>${Math.round(t.confidence * 100)}%</td>
        </tr>`).join('')
    : '<tr><td colspan="3" style="color:#666;">No visual evidence tags</td></tr>';

  const spoofingHtml = result.gps_spoofing_detected
    ? `<div class="alert-spoofing">
         <h3>⚠ GPS SPOOFING DETECTED</h3>
         <p>Anomaly Score: ${Math.round((result.anomaly_score ?? 0) * 100)}%</p>
         ${(result.sanity_mismatches || []).map((m) => `<p>• ${m}</p>`).join('')}
       </div>`
    : '';

  const html = `<!DOCTYPE html>
<html>
<head>
<title>ARKGEO Case Evidence Report — ${result.request_id}</title>
<style>
  @page { size: A4; margin: 20mm; }
  body { font-family: 'Courier New', monospace; color: #1a1a2e; margin: 0; padding: 20px; font-size: 12px; }
  .header { border-bottom: 3px solid #38BDF8; padding-bottom: 10px; margin-bottom: 20px; }
  .header h1 { font-size: 20px; color: #0B0F17; margin: 0; letter-spacing: 2px; }
  .header .subtitle { font-size: 11px; color: #64748B; margin-top: 4px; }
  .section { margin-bottom: 20px; }
  .section-title { font-size: 13px; font-weight: bold; color: #0EA5E9; border-left: 3px solid #38BDF8; padding-left: 8px; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px; }
  .kv-row { display: flex; margin-bottom: 4px; }
  .kv-key { width: 200px; color: #64748B; font-weight: bold; }
  .kv-val { flex: 1; color: #1a1a2e; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th { text-align: left; background: #F1F5F9; padding: 6px 8px; font-size: 11px; color: #334155; border-bottom: 1px solid #CBD5E1; }
  td { padding: 6px 8px; font-size: 11px; border-bottom: 1px solid #E2E8F0; }
  .hash-box { background: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 4px; padding: 10px; margin-top: 8px; word-break: break-all; font-size: 10px; }
  .hash-label { font-size: 10px; color: #64748B; font-weight: bold; margin-bottom: 2px; }
  .alert-spoofing { background: #FEF2F2; border: 2px solid #EF4444; border-radius: 6px; padding: 12px; margin: 10px 0; }
  .alert-spoofing h3 { color: #EF4444; margin: 0 0 6px; font-size: 14px; }
  .alert-spoofing p { margin: 4px 0; font-size: 11px; color: #991B1B; }
  .thumbnail { max-width: 200px; max-height: 200px; border: 1px solid #CBD5E1; border-radius: 4px; margin-top: 8px; }
  .footer { margin-top: 30px; padding-top: 10px; border-top: 1px solid #CBD5E1; font-size: 10px; color: #94A3B8; text-align: center; }
  @media print { body { padding: 0; } .no-print { display: none; } }
</style>
</head>
<body>
  <div class="header">
    <h1>ARKGEO — CASE EVIDENCE REPORT</h1>
    <div class="subtitle">Request ID: ${result.request_id} · Generated: ${new Date().toISOString()}</div>
  </div>

  ${spoofingHtml}

  <div class="section">
    <div class="section-title">Target Image</div>
    ${thumbnailUrl ? `<img src="${thumbnailUrl}" class="thumbnail" alt="Target" />` : '<p>No image available</p>'}
    <div class="kv-row"><span class="kv-key">File Format:</span><span class="kv-val">${result.file_format || 'N/A'}</span></div>
    <div class="kv-row"><span class="kv-key">Source Tier:</span><span class="kv-val">${result.source} (${result.consensus.tier_used})</span></div>
    <div class="kv-row"><span class="kv-key">Status:</span><span class="kv-val">${result.status}</span></div>
  </div>

  <div class="section">
    <div class="section-title">Map Telemetry</div>
    <div class="kv-row"><span class="kv-key">Coordinates:</span><span class="kv-val">${coords}</span></div>
    <div class="kv-row"><span class="kv-key">Confidence:</span><span class="kv-val">${Math.round(result.consensus.confidence_score * 100)}%</span></div>
    <div class="kv-row"><span class="kv-key">Search Radius:</span><span class="kv-val">${Math.round(result.consensus.search_radius_meters)}m</span></div>
    <div class="kv-row"><span class="kv-key">Primary Country:</span><span class="kv-val">${result.consensus.primary_country || 'N/A'}</span></div>
    <div class="kv-row"><span class="kv-key">Address:</span><span class="kv-val">${result.address?.display_name || 'N/A'}</span></div>
    <div class="kv-row"><span class="kv-key">Climate Zone (GPS):</span><span class="kv-val">${result.gps_climate_zone || 'N/A'}</span></div>
    <div class="kv-row"><span class="kv-key">Climate Zone (Visual):</span><span class="kv-val">${result.visual_climate_zone || 'N/A'}</span></div>
  </div>

  <div class="section">
    <div class="section-title">Camera Parameters</div>
    <div class="kv-row"><span class="kv-key">Make:</span><span class="kv-val">${(result.camera as any)?.make || 'N/A'}</span></div>
    <div class="kv-row"><span class="kv-key">Model:</span><span class="kv-val">${(result.camera as any)?.model || 'N/A'}</span></div>
    <div class="kv-row"><span class="kv-key">Altitude:</span><span class="kv-val">${result.altitude ?? 'N/A'} m</span></div>
    <div class="kv-row"><span class="kv-key">DateTime Original:</span><span class="kv-val">${result.datetime_original || 'N/A'}</span></div>
  </div>

  <div class="section">
    <div class="section-title">Integrity Seals (Chain of Custody)</div>
    <div class="hash-box">
      <div class="hash-label">SHA-256:</div>
      <div>${result.image_sha256}</div>
    </div>
    ${cert ? `
    <div class="hash-box">
      <div class="hash-label">SHA-1:</div>
      <div>${cert.sha1}</div>
    </div>
    <div class="hash-box">
      <div class="hash-label">MD5:</div>
      <div>${cert.md5}</div>
    </div>` : ''}
    <div class="kv-row" style="margin-top:8px;"><span class="kv-key">EXIF Present:</span><span class="kv-val">${result.exif_missing ? 'NO (stripped/missing)' : 'YES'}</span></div>
    <div class="kv-row"><span class="kv-key">Steganography:</span><span class="kv-val">${result.steganography_detected ? 'DETECTED (' + result.trailing_bytes_count + ' trailing bytes)' : 'CLEAN'}</span></div>
  </div>

  <div class="section">
    <div class="section-title">Visual Evidence Tags</div>
    <table>
      <thead><tr><th>Category</th><th>Label</th><th>Confidence</th></tr></thead>
      <tbody>${tagsHtml}</tbody>
    </table>
  </div>

  ${result.message ? `
  <div class="section">
    <div class="section-title">System Notes</div>
    <div class="kv-val" style="color:#92400E;">${result.message}</div>
  </div>` : ''}

  <div class="footer">
    ARKGEO Forensic Geolocation Engine · This report was generated programmatically.
    Cryptographic seals verify image integrity. Unauthorized distribution prohibited.
  </div>

  <script>
    // Auto-trigger print dialog after load
    window.onload = function() { setTimeout(function() { window.print(); }, 500); };
  </script>
</body>
</html>`;

  reportWindow.document.open();
  reportWindow.document.write(html);
  reportWindow.document.close();
}
