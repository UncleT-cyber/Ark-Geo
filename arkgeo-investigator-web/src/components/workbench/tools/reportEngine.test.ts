import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildReportModel, deriveReportStatus, fromGraphFinding } from './reportEngine.ts';

const graph: any = {
  case_id: 'C1',
  nodes: {
    n_crypto: { node_id: 'n_crypto', tool_id: 'custody.hash', provenance_type: 'cryptographic' },
    n_tool: { node_id: 'n_tool', tool_id: 'exif.extract', provenance_type: 'tool_inference' },
    n_ai: { node_id: 'n_ai', tool_id: 'vision.ensemble', provenance_type: 'ai_hypothesis' },
    n_ai2: { node_id: 'n_ai2', tool_id: 'vision.ensemble', provenance_type: 'ai_hypothesis' },
  },
  edges: [],
  findings: [],
};

const finding = (over: any = {}) => ({
  finding_id: 'F1', case_id: 'C1', claim_type: 'location', claim: 'Target is in Paris',
  value: {}, confidence: 0.8, supporting_node_ids: [], contradicting_node_ids: [],
  finding_type: 'location_credibility', severity: 'high', status: 'validated', ...over,
});

test('a finding with a higher-tier contradiction is CONTESTED', () => {
  assert.equal(deriveReportStatus(finding({ contradicting_node_ids: ['n_crypto'] }), graph), 'contested');
});

test('a finding with no support is UNSUPPORTED', () => {
  assert.equal(deriveReportStatus(finding(), graph), 'unsupported');
});

test('AI-only support is a HYPOTHESIS, never a conclusion', () => {
  assert.equal(deriveReportStatus(finding({ supporting_node_ids: ['n_ai', 'n_ai2'] }), graph), 'hypothesis');
});

test('tool support is a CONCLUSION', () => {
  assert.equal(deriveReportStatus(finding({ supporting_node_ids: ['n_tool'] }), graph), 'conclusion');
});

test('cryptographic support is a CONCLUSION', () => {
  assert.equal(deriveReportStatus(finding({ supporting_node_ids: ['n_crypto'] }), graph), 'conclusion');
});

test('supporting node ids resolve to originating tools', () => {
  const r = fromGraphFinding(finding({ supporting_node_ids: ['n_tool', 'n_crypto'] }), graph);
  assert.deepEqual(r.supportingTools.sort(), ['custody.hash', 'exif.extract']);
  assert.equal(r.provenance, 'deterministic');
});

test('pipeline findings are deterministic conclusions', () => {
  const model = buildReportModel({
    pipelineFindings: [{ type: 'TIMELINE_ANOMALY', severity: 'HIGH', status: 'WARNING', message: 'clock skew' } as any],
  });
  assert.equal(model.sections[0].id, 'deterministic');
  assert.equal(model.sections[0].findings[0].provenance, 'deterministic');
  assert.equal(model.sections[0].findings[0].status, 'conclusion');
  assert.equal(model.totals.conclusions, 1);
});

test('a graph finding that restates a deterministic finding is not duplicated', () => {
  const model = buildReportModel({
    pipelineFindings: [{ type: 'X', severity: 'HIGH', status: 'WARNING', message: 'clock skew' } as any],
    graphFindings: [finding({ claim: 'clock skew', supporting_node_ids: ['n_tool'] })],
    graph,
  });
  assert.equal(model.totals.findings, 1);
  assert.equal(model.sections.length, 1);
});

test('totals count contested and hypotheses separately from conclusions', () => {
  const model = buildReportModel({
    graphFindings: [
      finding({ finding_id: 'A', supporting_node_ids: ['n_tool'] }),
      finding({ finding_id: 'B', supporting_node_ids: ['n_ai'] }),
      finding({ finding_id: 'C', supporting_node_ids: ['n_tool'], contradicting_node_ids: ['n_crypto'] }),
    ],
    graph,
  });
  assert.equal(model.totals.conclusions, 1);
  assert.equal(model.totals.hypotheses, 1);
  assert.equal(model.totals.contested, 1);
});

test('severity ordering puts the most severe first', () => {
  const model = buildReportModel({
    graphFindings: [
      finding({ finding_id: 'LOW', severity: 'low', supporting_node_ids: ['n_tool'] }),
      finding({ finding_id: 'CRIT', severity: 'critical', supporting_node_ids: ['n_tool'] }),
    ],
    graph,
  });
  assert.equal(model.sections[0].findings[0].severity, 'CRITICAL');
});

test('empty input yields an empty, valid report', () => {
  const model = buildReportModel({});
  assert.equal(model.totals.findings, 0);
  assert.deepEqual(model.sections, []);
  assert.equal(model.severityCounts.HIGH, 0);
});
