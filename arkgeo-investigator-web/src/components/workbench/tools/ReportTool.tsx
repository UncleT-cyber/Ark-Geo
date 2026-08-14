/**
 * ReportTool — Case Report & Evidence Log.
 *
 * Evidence inventory, chain of custody, analyst overrides (confirm/reject/
 * needs_review), findings, contradictions, audit history, and PDF report.
 *
 * Reuses the existing ChainOfCustody component and pdfExport function.
 * Adds the analyst override interface for human assessment of machine findings.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Check, X, HelpCircle, FileText } from 'lucide-react';
import type { AnalyzeResponse, AnalystOverride } from '../../../types';
import { ChainOfCustody } from '../../ChainOfCustody/ChainOfCustody';
import { api } from '../../../api';

interface ReportToolProps {
  result: AnalyzeResponse;
  onExportPdf: () => void;
}

export function ReportTool({ result, onExportPdf }: ReportToolProps) {
  const [overrides, setOverrides] = useState<AnalystOverride[]>([]);
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const loadOverrides = useCallback(async () => {
    try {
      const list = await api.listAnalystOverrides(result.image_sha256);
      setOverrides(list);
    } catch {
      // Non-blocking
    }
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
    } catch {
      // Non-blocking
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="tool-view tool-report">
      <div className="tool-content">
        <div className="report-section">
          <div className="report-section-title">ANALYST OVERRIDE</div>
          <div className="report-override-intro">
            Machine assessment: <strong>{result.consensus.primary_country || result.address?.display_name || 'Unknown'}</strong> ({Math.round(result.consensus.confidence_score * 100)}%)
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
        </div>

        <div className="report-section">
          <div className="report-section-title">FINDINGS SUMMARY</div>
          <div className="report-findings">
            <div className="report-finding-row"><span className="report-finding-label">Location:</span> {result.geolocation_fusion?.primary_location || 'N/A'}</div>
            <div className="report-finding-row"><span className="report-finding-label">Confidence:</span> {Math.round((result.geolocation_fusion?.confidence || result.consensus.confidence_score) * 100)}%</div>
            <div className="report-finding-row"><span className="report-finding-label">Integrity:</span> {result.evidence_summary?.integrity || 'N/A'}</div>
            <div className="report-finding-row"><span className="report-finding-label">Provenance:</span> {result.provenance?.state || 'N/A'}</div>
            <div className="report-finding-row"><span className="report-finding-label">Contradictions:</span> {result.contradictions?.length || 0}</div>
            <div className="report-finding-row"><span className="report-finding-label">Evidence observations:</span> {result.consensus.visual_evidence_tags.length}</div>
          </div>
        </div>

        <div className="report-section">
          <div className="report-section-title">CHAIN OF CUSTODY</div>
          <ChainOfCustody
            response={result}
            exifMissing={result.exif_missing}
            steganographyDetected={result.steganography_detected}
          />
        </div>

        <div className="report-section">
          <button className="report-export-btn" onClick={onExportPdf}><FileText className="w-4 h-4" /> Generate PDF Report</button>
        </div>
      </div>
    </div>
  );
}
