/**
 * CaseReportView — court-ready forensic Investigation Report.
 *
 * Replaces the old ReportTool as the IMAGE domain's "Case / Report" sub-view.
 * Renders a comprehensive, multi-section document:
 *   A. Executive Summary & Case Metadata (Case ID, Date, SHA-256/1/MD5, file type, dims)
 *   B. Spatial & Geolocation Analysis (location, confidence, EXIF vs AI consensus)
 *   C. Deep Metadata & Structural Anomalies (ExifTool breakdown, ELA, inconsistencies)
 *   D. Provenance & C2PA Credentials (verification state, manifest checks)
 *   E. Chain of Custody & Audit Log (timestamped system action sequence)
 *
 * Also retains the analyst override interface (confirm/reject/needs_review)
 * for human assessment of machine findings, and a prominent Print / Export PDF
 * button that invokes a print-optimized layout (@media print in workbench.css).
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Check, X, HelpCircle, FileText, Printer, Fingerprint, MapPin, Layers, ShieldCheck, History, ListChecks } from 'lucide-react';
import type { AnalyzeResponse, AnalystOverride, ConsistencyFinding } from '../../../types';
import { ChainOfCustody } from '../../ChainOfCustody/ChainOfCustody';
import { api } from '../../../api';
import { useInvestigation } from '../useInvestigation';

interface CaseReportViewProps {
  result: AnalyzeResponse;
  thumbnailUrl?: string;
  onExportPdf: () => void;
}

function sevColor(severity: string): string {
  if (severity === 'HIGH' || severity === 'high' || severity === 'ERROR') return '#EF4444';
  if (severity === 'MEDIUM' || severity === 'medium' || severity === 'WARNING') return '#F59E0B';
  return '#22C55E';
}

function MetaField({ label, value, mono }: { label: string; value?: React.ReactNode; mono?: boolean }) {
  return (
    <div className="rpt-meta-field">
      <span className="rpt-meta-label">{label}</span>
      <span className={`rpt-meta-value ${mono ? 'mono' : ''}`}>{value || '—'}</span>
    </div>
  );
}

export function CaseReportView({ result, thumbnailUrl, onExportPdf }: CaseReportViewProps) {
  const [overrides, setOverrides] = useState<AnalystOverride[]>([]);
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const { pipeline } = useInvestigation();

  const loadOverrides = useCallback(async () => {
    try {
      const list = await api.listAnalystOverrides(result.image_sha256);
      setOverrides(list);
    } catch { /* non-blocking */ }
  }, [result.image_sha256]);

  useEffect(() => { loadOverrides(); }, [loadOverrides]);

  const submitOverride = async (decision: 'confirm' | 'reject' | 'needs_review') => {
    setSubmitting(true);
    try {
      await api.recordAnalystOverride({
        image_sha256: result.image_sha256,
        finding_key: 'location',
        decision,
        note,
      });
      setNote('');
      await loadOverrides();
    } catch { /* non-blocking */ }
    finally { setSubmitting(false); }
  };

  const handlePrint = () => { window.print(); };

  const cert = result.custody_certificate;
  const consensus = result.consensus;
  const fusion = result.geolocation_fusion;
  const summary = result.evidence_summary;
  const prov = result.provenance;
  const deep = result.deep_metadata;
  const fileInfo = deep?.file_info || {};
  const findings = (result.consistency_findings || []) as ConsistencyFinding[];
  const contradictions = result.contradictions || [];
  const audit = result.analysis_log || [];

  const coords = result.coordinates
    ? `${result.coordinates.lat.toFixed(5)}, ${result.coordinates.lon.toFixed(5)}`
    : (fusion?.hypothesis ? `${fusion.hypothesis.lat.toFixed(5)}, ${fusion.hypothesis.lon.toFixed(5)}` : null);

  const confidence = (fusion?.confidence ?? consensus.confidence_score) * 100;
  const integrity = summary?.integrity || (result.exif_missing || result.steganography_detected || result.gps_spoofing_detected ? 'Compromised' : 'Verified');
  const dims = (fileInfo as any).ImageWidth && (fileInfo as any).ImageHeight
    ? `${(fileInfo as any).ImageWidth} × ${(fileInfo as any).ImageHeight}`
    : (fileInfo as any).ExifImageWidth && (fileInfo as any).ExifImageHeight
      ? `${(fileInfo as any).ExifImageWidth} × ${(fileInfo as any).ExifImageHeight}`
      : '—';
  const fileSize = (fileInfo as any).FileSize || (result as any).byte_size;

  const groups = deep?.groups ? Object.entries(deep.groups) : [];

  return (
    <div className="tool-view tool-report case-report-view">
      {/* Print / Export toolbar — hidden in print */}
      <div className="case-report-toolbar no-print">
        <div className="case-report-toolbar-title">
          <FileText className="w-4 h-4" /> Investigation Report
        </div>
        <div className="case-report-toolbar-actions">
          <button className="case-report-print-btn" onClick={handlePrint} title="Print or save as PDF">
            <Printer className="w-4 h-4" /> Print / Export PDF
          </button>
          <button className="case-report-pdf-btn" onClick={onExportPdf} title="Generate formatted case evidence PDF">
            <FileText className="w-4 h-4" /> Generate PDF Report
          </button>
        </div>
      </div>

      <div className="case-report-document">
        {/* Document header */}
        <div className="case-report-doc-header">
          <div className="case-report-doc-brand">THE ARK</div>
          <div className="case-report-doc-type">FORENSIC INVESTIGATION REPORT</div>
          <div className="case-report-doc-id mono">Case {inv(result)}</div>
        </div>

        {/* Section A: Executive Summary & Case Metadata */}
        <section className="case-report-section">
          <div className="case-report-section-title"><Fingerprint className="w-4 h-4" /> A · Executive Summary &amp; Case Metadata</div>
          <div className="case-report-summary">
            <div className="case-report-thumb">
              {thumbnailUrl
                ? <img src={thumbnailUrl} alt="target evidence" />
                : <span className="case-report-thumb-ph"><FileText className="w-6 h-6" /></span>}
            </div>
            <div className="case-report-meta-grid">
              <MetaField label="Case ID" value={inv(result)} mono />
              <MetaField label="Evidence SHA-256" value={shortHash(result.image_sha256)} mono />
              <MetaField label="SHA-1" value={cert?.sha1 ? shortHash(cert.sha1) : '—'} mono />
              <MetaField label="MD5" value={cert?.md5 ? shortHash(cert.md5) : '—'} mono />
              <MetaField label="File Type" value={result.file_format || (fileInfo as any).FileType || '—'} />
              <MetaField label="Dimensions" value={dims} />
              <MetaField label="File Size" value={fileSize ? `${fileSize} bytes` : '—'} mono />
              <MetaField label="Ingested" value={result.created_at ? new Date(result.created_at).toLocaleString() : '—'} />
              <MetaField label="Source" value={result.source} />
              <MetaField label="Asset Classification" value={
                pipeline?.classification
                  ? `${pipeline.classification.classification} (${pipeline.classification.platformProfile}, ${Math.round(pipeline.classification.confidence * 100)}%)`
                  : result.image_classification || '—'
              } />
              <MetaField label="Integrity" value={integrity} />
            </div>
          </div>
          <div className="case-report-summary-text">
            <span className="rpt-meta-label">Assessment</span>
            <p className="case-report-narrative">
              This image was ingested into THE ARK forensic pipeline and processed through the
              4-tier Brain architecture (deterministic EXIF → vision ensemble → clue extractors →
              consensus). Determined location:{' '}
              <strong>{summary?.location || consensus.primary_country || result.address?.display_name || 'Not established'}</strong>
              {' '}with <strong>{Math.round(confidence)}%</strong> confidence. Integrity status: <strong>{integrity}</strong>.
              {pipeline?.classification && ` Asset classified as ${pipeline.classification.classification} (${pipeline.classification.platformProfile}).`}
              {pipeline?.fusion?.location.candidate && ` Fused location candidate: ${pipeline.fusion.location.candidate}.`}
              {result.exif_missing && ' EXIF metadata was stripped or missing, forcing fallback to visual analysis.'}
              {result.steganography_detected && ' Structural anomaly detected (trailing bytes after EOF).'}
              {result.gps_spoofing_detected && ' GPS spoofing suspected via sanity/climate cross-checks.'}
            </p>
          </div>
        </section>

        {/* Section B: Spatial & Geolocation Analysis */}
        <section className="case-report-section">
          <div className="case-report-section-title"><MapPin className="w-4 h-4" /> B · Spatial &amp; Geolocation Analysis</div>
          <div className="case-report-meta-grid">
            <MetaField label="Coordinates" value={coords} mono />
            <MetaField label="Search Radius" value={consensus.search_radius_meters ? `${consensus.search_radius_meters} m` : '—'} />
            <MetaField label="Confidence" value={`${Math.round(confidence)}%`} />
            <MetaField label="Primary Country" value={consensus.primary_country} />
            <MetaField label="Region" value={consensus.region} />
            <MetaField label="Tier Used" value={consensus.tier_used} />
            <MetaField label="Altitude" value={result.altitude != null ? `${result.altitude} m` : '—'} mono />
            <MetaField label="Low-Context Indoor" value={consensus.flag_low_context_indoor ? 'Yes' : 'No'} />
          </div>

          {fusion && (
            <div className="case-report-sub-block">
              <div className="case-report-sub-title">EXIF vs AI Consensus</div>
              <div className="case-report-fusion">
                <div className="case-report-fusion-row">
                  <span className="rpt-meta-label">Primary location</span>
                  <span className="rpt-meta-value">{fusion.primary_location}</span>
                </div>
                <div className="case-report-fusion-row">
                  <span className="rpt-meta-label">Independent evidence classes</span>
                  <span className="rpt-meta-value mono">{fusion.independent_evidence_classes}</span>
                </div>
                <div className="case-report-fusion-note">{fusion.detail?.note}</div>
                {fusion.supporting.length > 0 && (
                  <div className="case-report-fusion-list">
                    <span className="rpt-meta-label">Supporting evidence</span>
                    {fusion.supporting.map((e, i) => (
                      <div key={i} className="case-report-fusion-item"><span className="fusion-badge fusion-sup">SUPPORT</span>{e.layer}: {e.label}</div>
                    ))}
                  </div>
                )}
                {fusion.contradicting.length > 0 && (
                  <div className="case-report-fusion-list">
                    <span className="rpt-meta-label">Contradicting evidence</span>
                    {fusion.contradicting.map((e, i) => (
                      <div key={i} className="case-report-fusion-item"><span className="fusion-badge fusion-con">CONFLICT</span>{e.layer}: {e.label}</div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {consensus.visual_evidence_tags.length > 0 && (
            <div className="case-report-sub-block">
              <div className="case-report-sub-title">Visual Evidence Tags</div>
              <div className="case-report-tags">
                {consensus.visual_evidence_tags.map((t, i) => (
                  <span key={i} className="case-report-tag">{t.category}: {t.label} · {Math.round(t.confidence * 100)}%</span>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* Section C: Deep Metadata & Structural Anomalies */}
        <section className="case-report-section">
          <div className="case-report-section-title"><Layers className="w-4 h-4" /> C · Deep Metadata &amp; Structural Anomalies</div>

          {result.ela_heatmap && (
            <div className="case-report-sub-block">
              <div className="case-report-sub-title">Error-Level Analysis (ELA)</div>
              <div className="case-report-ela">
                <img src={result.ela_heatmap} alt="ELA heatmap" className="case-report-ela-img" />
                <span className="case-report-ela-note">Error-level analysis highlights regions of differing compression — bright areas indicate potential local edits.</span>
              </div>
            </div>
          )}

          <div className="case-report-sub-block">
            <div className="case-report-sub-title">ExifTool Metadata Breakdown {deep?.available ? '' : '(unavailable)'}</div>
            {deep?.available && groups.length > 0 ? (
              <div className="case-report-meta-tree">
                {groups.map(([gname, entries]) => (
                  <div key={gname} className="case-report-meta-group">
                    <div className="case-report-meta-group-name mono">{gname}</div>
                    <div className="case-report-meta-group-body">
                      {(entries as { tag: string; value: string }[]).map((e, i) => (
                        <div key={i} className="case-report-meta-row">
                          <span className="case-report-meta-tag mono">{e.tag}</span>
                          <span className="case-report-meta-value mono">{e.value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="case-report-empty">ExifTool metadata not available for this asset.</div>
            )}
          </div>

          <div className="case-report-sub-block">
            <div className="case-report-sub-title">Inconsistencies Detected ({findings.length})</div>
            {findings.length === 0 ? (
              <div className="case-report-empty">No structured consistency findings.</div>
            ) : (
              <div className="case-report-findings">
                {findings.map((f, i) => {
                  const c = sevColor(f.severity);
                  return (
                    <div key={i} className="case-report-finding" style={{ borderLeftColor: c }}>
                      <span className="finding-badge" style={{ color: c, borderColor: c }}>{f.status}</span>
                      <span className="finding-type mono">{f.type}</span>
                      <span className="finding-sev" style={{ color: c }}>{f.severity}</span>
                      <span className="finding-msg">{f.message}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {(result.steganography_detected || result.gps_spoofing_detected || (contradictions.length > 0)) && (
            <div className="case-report-sub-block">
              <div className="case-report-sub-title">Structural Anomalies</div>
              {result.steganography_detected && (
                <div className="case-report-anomaly"><span className="anomaly-tag anomaly-stego">STEGO</span>Trailing bytes after EOF ({result.trailing_bytes_count})</div>
              )}
              {result.gps_spoofing_detected && (
                <div className="case-report-anomaly"><span className="anomaly-tag anomaly-spoof">GPS SPOOF</span>GPS metadata fails sanity/climate cross-checks</div>
              )}
              {contradictions.map((c, i) => (
                <div key={i} className="case-report-anomaly"><span className="anomaly-tag anomaly-conflict" style={{ color: sevColor(c.severity) }}>CONFLICT</span>{c.what_conflicts}</div>
              ))}
            </div>
          )}
        </section>

        {/* Section D: Provenance & C2PA Credentials */}
        <section className="case-report-section">
          <div className="case-report-section-title"><ShieldCheck className="w-4 h-4" /> D · Provenance &amp; C2PA Credentials</div>
          {prov ? (
            <div className="case-report-provenance">
              <div className="case-report-meta-grid">
                <MetaField label="Verification State" value={prov.state} />
                <MetaField label="Manifest Found" value={prov.manifest_found ? 'Yes' : 'No'} />
                <MetaField label="Issuer" value={prov.issuer} />
                <MetaField label="Signature Valid" value={prov.signature_valid == null ? '—' : (prov.signature_valid ? 'Yes' : 'No')} />
              </div>
              <div className="case-report-prov-detail">{prov.detail}</div>
              {prov.actions.length > 0 && (
                <div className="case-report-prov-list">
                  <span className="rpt-meta-label">Actions</span>
                  {prov.actions.map((a, i) => <div key={i} className="case-report-prov-item">{String(a)}</div>)}
                </div>
              )}
              {prov.modifications.length > 0 && (
                <div className="case-report-prov-list">
                  <span className="rpt-meta-label">Modifications</span>
                  {prov.modifications.map((m, i) => <div key={i} className="case-report-prov-item">{String(m)}</div>)}
                </div>
              )}
              {prov.warnings.length > 0 && (
                <div className="case-report-prov-list">
                  <span className="rpt-meta-label">Warnings</span>
                  {prov.warnings.map((w, i) => <div key={i} className="case-report-prov-item case-report-warn">{String(w)}</div>)}
                </div>
              )}
            </div>
          ) : (
            <div className="case-report-empty">No provenance / C2PA manifest data available.</div>
          )}
        </section>

        {/* Section E: Chain of Custody & Audit Log */}
        <section className="case-report-section">
          <div className="case-report-section-title"><History className="w-4 h-4" /> E · Chain of Custody &amp; Audit Log</div>
          <ChainOfCustody
            response={result}
            exifMissing={result.exif_missing}
            steganographyDetected={result.steganography_detected}
          />
          {audit.length > 0 && (
            <div className="case-report-sub-block">
              <div className="case-report-sub-title">Analysis Run Log ({audit.length})</div>
              <div className="case-report-audit">
                {audit.map((line, i) => (
                  <div key={i} className="case-report-audit-row mono">{line}</div>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* Section F: Continuous Image Intelligence Cascade */}
        {pipeline && (
          <section className="case-report-section">
            <div className="case-report-section-title"><ListChecks className="w-4 h-4" /> F · Continuous Image Intelligence Cascade</div>

            <div className="case-report-sub-block">
              <div className="case-report-sub-title">Pipeline Steps</div>
              <div className="case-report-verdicts">
                {pipeline.steps.map((s) => (
                  <div key={s.step} className="case-report-verdict">
                    <span className={`case-report-verdict-status ${s.ok ? 'verdict-ok' : 'verdict-fail'}`}>{s.ok ? 'OK' : 'FAIL'}</span>
                    <span className="case-report-verdict-dim mono">STEP {s.step}</span>
                    <span className="case-report-verdict-concl">{s.name}</span>
                    <span className="case-report-verdict-conf mono">{s.elapsedMs}ms · {s.observations.length} obs</span>
                  </div>
                ))}
              </div>
            </div>

            {pipeline.fusion?.verdicts.length > 0 && (
              <div className="case-report-sub-block">
                <div className="case-report-sub-title">Fusion Verdicts</div>
                <div className="case-report-verdicts">
                  {pipeline.fusion.verdicts.map((v) => (
                    <div key={v.dimension} className="case-report-verdict">
                      <span className={`case-report-verdict-status verdict-${v.status.toLowerCase()}`}>{v.status}</span>
                      <span className="case-report-verdict-dim mono">{v.dimension.toUpperCase()}</span>
                      <span className="case-report-verdict-concl">{v.conclusion}</span>
                      <span className="case-report-verdict-conf mono">{Math.round(v.confidence * 100)}%</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="case-report-sub-block">
              <div className="case-report-sub-title">Location Assessment</div>
              <div className="case-report-meta-grid">
                <MetaField label="Status" value={pipeline.fusion?.location.status} />
                <MetaField label="Candidate" value={pipeline.fusion?.location.candidate} />
                <MetaField label="Confidence" value={pipeline.fusion?.location ? `${Math.round(pipeline.fusion.location.confidence * 100)}%` : '—'} />
                <MetaField label="Supporting" value={pipeline.fusion?.location ? String(pipeline.fusion.location.supporting.length) : '0'} />
                <MetaField label="Contradicting" value={pipeline.fusion?.location ? String(pipeline.fusion.location.contradicting.length) : '0'} />
              </div>
              {pipeline.fusion?.location.note && <div className="case-report-prov-detail">{pipeline.fusion.location.note}</div>}
            </div>

            {pipeline.fusion?.timeline.length > 0 && (
              <div className="case-report-sub-block">
                <div className="case-report-sub-title">Reconstructed Timeline ({pipeline.fusion.timeline.length})</div>
                <div className="case-report-audit">
                  {pipeline.fusion.timeline.map((t, i) => (
                    <div key={i} className="case-report-audit-row mono">{t.date || 'unknown date'} — {t.note}</div>
                  ))}
                </div>
              </div>
            )}

            {pipeline.observations.length > 0 && (
              <div className="case-report-sub-block">
                <div className="case-report-sub-title">Structured Observations ({pipeline.observations.length})</div>
                <div className="case-report-findings">
                  {pipeline.observations.map((o) => (
                    <div key={o.id} className="case-report-finding" style={{ borderLeftColor: sevColor(o.status === 'ANOMALY' ? 'HIGH' : o.status === 'UNAVAILABLE' ? 'LOW' : 'OK') }}>
                      <span className="finding-badge">{o.status}</span>
                      <span className="finding-type mono">{o.type}</span>
                      <span className="finding-sev mono">S{o.step}</span>
                      <span className="finding-msg">{o.label} — {o.detail}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        )}

        {/* Section G: AI Intelligence Analysis */}
        <section className="case-report-section">
          <div className="case-report-section-title"><Layers className="w-4 h-4" /> G · AI Intelligence Analysis</div>

          {/* Discrete AI provider results */}
          {result.ai_evidence && (
            <div className="case-report-sub-block">
              <div className="case-report-sub-title">Discrete AI Providers</div>
              <div className="case-report-meta-grid">
                {(() => {
                  const geospy = result.ai_evidence?.geospy as any;
                  const scene = result.ai_evidence?.scene as any;
                  return (
                    <>
                      <MetaField
                        label="GeoSpy Prediction"
                        value={geospy?.estimated_latitude != null
                          ? `${Number(geospy.estimated_latitude).toFixed(4)}, ${Number(geospy.estimated_longitude).toFixed(4)} (${Math.round((geospy.confidence_score || 0) * 100)}%)`
                          : '—'}
                      />
                      <MetaField
                        label="Vision Scene Country"
                        value={scene?.primary_country || scene?.region || '—'}
                      />
                      <MetaField
                        label="Vision Scene Confidence"
                        value={scene?.confidence_score != null ? `${Math.round(scene.confidence_score * 100)}%` : '—'}
                      />
                      <MetaField
                        label="Credible Interval (95%)"
                        value={result.credible_interval_radius != null ? `${Math.round(result.credible_interval_radius)} m` : '—'}
                      />
                    </>
                  );
                })()}
              </div>

              {(() => {
                const scene = result.ai_evidence?.scene as any;
                const ocr = (scene?.ocr_texts as string[] | undefined) || [];
                const regions = (scene?.candidate_regions as { region: string; confidence?: number; rationale?: string }[] | undefined) || [];
                return (
                  <>
                    {ocr.length > 0 && (
                      <div className="case-report-sub-block">
                        <div className="case-report-sub-title">OCR Text (scene)</div>
                        <div className="case-report-tags">
                          {ocr.map((t, i) => <span key={i} className="case-report-tag">{t}</span>)}
                        </div>
                      </div>
                    )}
                    {regions.length > 0 && (
                      <div className="case-report-sub-block">
                        <div className="case-report-sub-title">Terrain IMINT Candidate Regions</div>
                        <div className="case-report-findings">
                          {regions.map((r, i) => (
                            <div key={i} className="case-report-finding">
                              <span className="finding-badge">{Math.round((r.confidence || 0) * 100)}%</span>
                              <span className="finding-type">{r.region}</span>
                              <span className="finding-msg">{r.rationale || ''}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                );
              })()}
            </div>
          )}

          {/* Reverse source / source discovery */}
          {result.source_discovery && (
            <div className="case-report-sub-block">
              <div className="case-report-sub-title">Reverse Source Discovery</div>
              <div className="case-report-meta-grid">
                <MetaField label="State" value={result.source_discovery.state} />
                <MetaField label="Provider" value={result.source_discovery.provider} />
                <MetaField
                  label="Perceptual Hash"
                  value={result.source_discovery.phash ? String(result.source_discovery.phash).slice(0, 16) + '…' : '—'}
                  mono
                />
                <MetaField
                  label="Exact / Similar Matches"
                  value={`${(result.source_discovery.exact_matches || []).length} / ${(result.source_discovery.similar_matches || []).length}`}
                />
              </div>
              <div className="case-report-prov-detail">{result.source_discovery.detail}</div>

              {/* Original rehydration success */}
              {result.recovered_original?.recovered_gps && (
                <div className="case-report-recovered">
                  <span className="anomaly-tag anomaly-stego" style={{ color: '#22C55E', borderColor: '#22C55E' }}>REHYDRATED</span>
                  Recovered original GPS{' '}
                  <strong className="mono">
                    {Number(result.recovered_original.recovered_gps.lat).toFixed(4)}, {Number(result.recovered_original.recovered_gps.lon).toFixed(4)}
                  </strong>
                  {result.recovered_original.recovered_source_url && (
                    <> from <a className="case-report-link" href={result.recovered_original.recovered_source_url} target="_blank" rel="noreferrer">{result.recovered_original.recovered_source_url}</a></>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Satellite / aerial cross-reference */}
          {result.satellite_crossref?.state === 'AVAILABLE' && (
            <div className="case-report-sub-block">
              <div className="case-report-sub-title">Satellite / Aerial Cross-Reference ({result.satellite_crossref.provider})</div>
              {result.satellite_crossref.tile_url && (
                <img className="case-report-sat-tile" src={result.satellite_crossref.tile_url} alt="satellite reference" />
              )}
              <div className="case-report-prov-detail">{result.satellite_crossref.detail}</div>
            </div>
          )}

          {/* Probability surface */}
          {result.probability_surface && (
            <div className="case-report-sub-block">
              <div className="case-report-sub-title">Monte-Carlo Probability Surface</div>
              <div className="case-report-prov-detail">
                {`A ${result.probability_surface?.grid_span_m ? Math.round(Number(result.probability_surface.grid_span_m)) : '—'} m span centred on the resolved pin, derived from ${result.consensus?.monte_carlo_samples || '—'} Monte-Carlo samples. 95% credible interval: ${result.credible_interval_radius != null ? Math.round(result.credible_interval_radius) + ' m' : '—'}.`}
              </div>
            </div>
          )}
        </section>

        {/* Analyst override — evidentiary human assessment */}
        <section className="case-report-section no-print">
          <div className="case-report-section-title">Analyst Override</div>
          <div className="report-override-intro">
            Machine assessment: <strong>{consensus.primary_country || result.address?.display_name || 'Unknown'}</strong> ({Math.round(consensus.confidence_score * 100)}%)
          </div>
          <div className="report-override-buttons">
            <button className="override-btn override-confirm" disabled={submitting} onClick={() => submitOverride('confirm')}><Check className="w-4 h-4" /> Confirm</button>
            <button className="override-btn override-reject" disabled={submitting} onClick={() => submitOverride('reject')}><X className="w-4 h-4" /> Reject</button>
            <button className="override-btn override-review" disabled={submitting} onClick={() => submitOverride('needs_review')}><HelpCircle className="w-4 h-4" /> Needs Review</button>
          </div>
          <textarea
            className="override-note"
            placeholder="Analyst note (optional)..."
            value={note}
            onChange={e => setNote(e.target.value)}
            rows={3}
          />
          {overrides.length > 0 && (
            <div className="override-history">
              <div className="override-history-title">RECORDED OVERRIDES</div>
              {overrides.map((o, i) => (
                <div key={i} className={`override-history-item override-history-${o.decision}`}>
                  <span className="override-history-decision">{o.decision}</span>
                  <span className="override-history-note">{o.note || '(no note)'}</span>
                  <span className="override-history-time mono">{new Date(o.created_at_ms).toLocaleString()}</span>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Footer */}
        <div className="case-report-doc-footer">
          <span>Generated by THE ARK · {new Date().toLocaleString()}</span>
          <span className="mono">Custody seal: {shortHash(result.custody_hash)}</span>
        </div>
      </div>
    </div>
  );
}

/** Derive a case-style ID mirroring the shared entity model. */
function inv(result: AnalyzeResponse): string {
  const hex = (result.request_id || '').replace(/[^a-f0-9]/gi, '').slice(0, 8).toUpperCase();
  return `ARK-CASE-${hex || '00000000'}`;
}

function shortHash(h?: string): string {
  if (!h) return '—';
  return h.length > 24 ? `${h.slice(0, 16)}…${h.slice(-8)}` : h;
}
