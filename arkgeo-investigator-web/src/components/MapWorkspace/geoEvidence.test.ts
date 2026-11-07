import { test } from 'node:test';
import assert from 'node:assert/strict';
import { classifyGeoEvidence, classifyCandidateEvidence, geoEvidenceLegend } from './geoEvidence.ts';

test('device EXIF GPS is verified', () => {
  const c = classifyGeoEvidence('NATIVE_EXIF_HARDWARE', 'metadata');
  assert.equal(c.kind, 'verified');
  assert.match(c.label, /GPS/);
});

test('carrier telemetry is verified', () => {
  assert.equal(classifyGeoEvidence('TELEMETRY', 'telemetry').kind, 'verified');
});

test('vision model output is inferred', () => {
  const c = classifyGeoEvidence('AI_VISION', 'consensus');
  assert.equal(c.kind, 'inferred');
  assert.match(c.label, /INFERRED/);
});

test('an unknown or missing source is never promoted to verified', () => {
  assert.equal(classifyGeoEvidence(undefined).kind, 'inferred');
  assert.equal(classifyGeoEvidence('').kind, 'inferred');
  assert.equal(classifyGeoEvidence('SOMETHING_NEW', 'consensus').kind, 'inferred');
});

test('metadata tier without a known source is still verified (deterministic tier)', () => {
  assert.equal(classifyGeoEvidence(null, 'metadata').kind, 'verified');
});

test('OCR / IMINT candidates are always hypotheses', () => {
  assert.equal(classifyCandidateEvidence().kind, 'inferred');
});

test('the legend names both kinds', () => {
  const legend = geoEvidenceLegend();
  assert.deepEqual(legend.map(l => l.kind).sort(), ['inferred', 'verified']);
});
